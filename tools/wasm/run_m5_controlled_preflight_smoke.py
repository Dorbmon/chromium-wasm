#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the isolated local M5 gateway-denial preflight through WISP.

Unlike the broad controlled fixture, this runner sends no document URL to the
host page. The test-only native binary owns the one canonical ``a.test:443``
document and first proves that its same-host ``:444`` precursor is denied by
the loopback relay.
"""

from __future__ import annotations

import argparse
from collections import deque
import json
from pathlib import Path
import queue
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any
from urllib.parse import urlencode

from m0_common import (
    M0Error,
    REPO_ROOT,
    checked_output,
    load_manifest,
    parse_timeout,
    print_context,
)
from m3_content_server import M5_CONTROLLED_PREFLIGHT_CASE, create_m3_server
from run_browser_smoke import drain_stream, find_browser, stop_browser
from run_content_shell_smoke import manifest_versions
from run_m5_wisp_smoke import (
    M5_FIXTURE,
    M5_TEST_HOSTNAME,
    RelayReady,
    _drain_relay_stdout,
    fetch_relay_transcript,
    find_node,
    m5_browser_command,
    m5_host_origin,
    relay_command,
    verify_no_private_key_pem_artifacts,
    wait_for_relay_ready,
    wait_for_result,
)


SENTINEL = "CHROMIUM_WASM_M5_CONTROLLED_PREFLIGHT"
M5_CONTROLLED_PREFLIGHT_FIXTURE = "chromium-wasm-m5-controlled-preflight-v1"
M5_CONTROLLED_PREFLIGHT_MODULE = "content_shell_wasm_m5_controlled_preflight_test"
M5_CONTROLLED_PREFLIGHT_HEARTBEAT = (
    "m5-controlled-preflight-navigation-committed"
)
M5_CONTROLLED_PREFLIGHT_EVENTS = (
    "Network.requestWillBeSent:document",
    "Network.responseReceived:document",
    "Network.loadingFinished:document",
)
MAXIMUM_URL_FREE_RESULT_BYTES = 256 * 1024
URL_LIKE_VALUE_PATTERN = re.compile(r"\b(?:https?|wss?)://", re.IGNORECASE)


def controlled_preflight_smoke_url(
    server: Any,
    token: str,
    versions: dict[str, str],
    *,
    relay_ready: RelayReady,
    module_name: str = M5_CONTROLLED_PREFLIGHT_MODULE,
    timeout_seconds: float = 120.0,
) -> str:
    """Build a host URL with only loopback transport configuration.

    The fixed browser document is intentionally absent from this query. Its
    ownership is native, not a caller-controlled JavaScript input.
    """

    from run_m5_wisp_smoke import validate_wisp_endpoint

    wisp_endpoint = validate_wisp_endpoint(relay_ready.wisp_endpoint)
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "case": M5_CONTROLLED_PREFLIGHT_CASE,
            "chromium": versions["chromium"],
            "emscripten": versions["emscripten"],
            "module": f"/__m3__/artifacts/{module_name}.js",
            "port": versions["port"],
            "token": token,
            "timeout_ms": max(1000, min(180000, int(timeout_seconds * 1000))),
            "v8": versions["v8"],
            "wisp_endpoint": wisp_endpoint,
        }
    )
    return f"http://{host}:{port}/__m3__/?{query}"


def _require_dict(value: object, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise M0Error(f"{description} is not an object")
    return value


def _require_exact(value: object, expected: object, description: str) -> None:
    if value != expected or type(value) is not type(expected):
        raise M0Error(f"{description} mismatch")


def _require_positive_integer(value: object, description: str) -> int:
    if type(value) is not int or value < 1:
        raise M0Error(f"{description} is not a positive integer")
    return value


def _reject_url_like_values(value: object, description: str = "result") -> None:
    if isinstance(value, str):
        if URL_LIKE_VALUE_PATTERN.search(value):
            raise M0Error(f"{description} contains a URL-like string")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_url_like_values(item, f"{description}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_url_like_values(key, f"{description} key")
            _reject_url_like_values(item, f"{description}.{key}")


def _validate_frame(
    value: object, description: str, *, minimum_id: int = 1
) -> dict[str, Any]:
    frame = _require_dict(value, description)
    if (
        _require_positive_integer(frame.get("id"), f"{description} id")
        < minimum_id
        or frame.get("width") != 800
        or frame.get("height") != 600
    ):
        raise M0Error(f"{description} is not the fixed host canvas frame")
    return frame


def expected_controlled_preflight_devtools_network() -> dict[str, object]:
    return {
        "protocol": 1,
        "state": "complete",
        "networkEnabled": True,
        "documentRequest": True,
        "responseReceived": True,
        "loadingFinished": True,
        "requestIdCorrelated": True,
        "responseStatus": 200,
        "responseProtocol": "h2",
        "wispWebSocketOpened": True,
        "wispHandshakeReady": True,
        "wispConfirmedStream": True,
        "wispDestinationMatched": True,
        "wispDeniedRequest": True,
        "wispDeniedLoadingFailed": True,
        "wispDeniedRequestIdCorrelated": True,
        "wispDeniedByAdministrator": True,
        "events": list(M5_CONTROLLED_PREFLIGHT_EVENTS),
    }


def validate_controlled_preflight_result(
    result: dict[str, Any], *, expected_versions: dict[str, str]
) -> None:
    """Require URL-free native CDP, navigation, WISP, and lifecycle evidence."""

    serialized = json.dumps(result, sort_keys=True, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > MAXIMUM_URL_FREE_RESULT_BYTES:
        raise M0Error("controlled preflight result exceeds its bound")
    _reject_url_like_values(result)
    for field, expected in {
        "protocol": 1,
        "case": M5_CONTROLLED_PREFLIGHT_CASE,
        "status": "pass",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "versions": expected_versions,
        "failedChecks": [],
        "navigationResult": {"ok": True, "scheme": "https"},
    }.items():
        _require_exact(result.get(field), expected, f"controlled {field}")

    initial_frame = _validate_frame(result.get("initialFrame"), "initial frame")
    controlled_frame = _validate_frame(
        result.get("controlledPreflightFrame"),
        "controlled preflight frame",
        minimum_id=initial_frame["id"] + 1,
    )
    if controlled_frame["id"] <= initial_frame["id"]:
        raise M0Error("controlled preflight did not present a later frame")

    _require_exact(
        result.get("controlledPreflightDevtoolsNetworkEnabled"),
        {"protocol": 1, "state": "enabled", "networkEnabled": True, "events": []},
        "controlled DevTools Network.enable",
    )
    readiness = _require_dict(result.get("readiness"), "controlled readiness")
    for field in (
        "runtimeInitialized",
        "shellReady",
        "surfaceReady",
        "navigationCommitted",
        "firstVisuallyNonEmptyPaint",
    ):
        if readiness.get(field) is not True:
            raise M0Error(f"controlled readiness field {field} is not true")
    if readiness.get("fatalErrors") != []:
        raise M0Error("controlled readiness reported fatal errors")
    _require_exact(
        readiness.get("navigation"),
        {
            "committed": True,
            "scheme": "https",
            "responseCode": 200,
            "connectionProtocol": "h2",
        },
        "controlled navigation",
    )
    _require_exact(
        readiness.get("controlledPreflightDevtoolsNetwork"),
        expected_controlled_preflight_devtools_network(),
        "controlled DevTools Network trace",
    )
    heartbeat = _require_dict(readiness.get("heartbeat"), "controlled heartbeat")
    if heartbeat.get("anchor") != M5_CONTROLLED_PREFLIGHT_HEARTBEAT:
        raise M0Error("controlled heartbeat is not navigation-anchored")
    for field in ("timerDelta", "animationFrameDelta"):
        if type(heartbeat.get(field)) is not int or heartbeat[field] < 2:
            raise M0Error(f"controlled heartbeat {field} is too small")
    max_gap = heartbeat.get("maxTimerGapMs")
    if type(max_gap) not in (int, float) or not 0 <= max_gap <= 250:
        raise M0Error("controlled heartbeat maxTimerGapMs is out of range")

    logs = _require_dict(result.get("logs"), "controlled logs")
    host_logs = logs.get("host")
    if not isinstance(host_logs, list) or not all(
        isinstance(item, str) for item in host_logs
    ):
        raise M0Error("controlled host logs are invalid")
    required_logs = (
        "initialize:wisp-configured",
        "m5:controlled-preflight-devtools-network:enabled",
        "navigation:requested:m5-controlled-preflight",
        "navigation:committed:m5-controlled-preflight",
        "m5:controlled-preflight-devtools-network:complete",
        "shutdown:complete",
    )
    for marker in required_logs:
        if host_logs.count(marker) != 1:
            raise M0Error(f"controlled host logs must contain one {marker!r}")
    if [host_logs.index(marker) for marker in required_logs] != sorted(
        host_logs.index(marker) for marker in required_logs
    ):
        raise M0Error("controlled host logs do not preserve phase order")
    if host_logs[-1:] != ["shutdown:complete"]:
        raise M0Error("controlled host logs do not end with shutdown")

    shutdown = _require_dict(result.get("shutdown"), "controlled shutdown")
    for field in ("ok", "accepted", "complete"):
        if shutdown.get(field) is not True:
            raise M0Error(f"controlled shutdown {field} is not true")
    for field in ("exitCode", "runtimeExitCode"):
        if shutdown.get(field) != 0:
            raise M0Error(f"controlled shutdown {field} is not zero")


def validate_controlled_preflight_relay_transcript(
    status: dict[str, Any]
) -> None:
    """Require the native :444 denial before exactly one mapped :443 stream."""

    if status.get("fixture") != M5_FIXTURE or status.get("protocol") != 1:
        raise M0Error("controlled relay fixture or protocol mismatch")
    if status.get("ready") is not True:
        raise M0Error("controlled relay did not report readiness")
    for field, expected in {
        "wispSessions": 1,
        "rejectedDestinations": 1,
        "localGatewayBlockedPortAttempts": 1,
        "localGateway443StreamsOpened": 1,
        "localGateway443Requests": 1,
        "udpPackets": 0,
        "relayErrors": 0,
    }.items():
        if status.get(field) != expected:
            raise M0Error(
                f"controlled relay {field} mismatch: expected {expected!r}")
    _require_exact(
        status.get("h2Requests"), {"protocol": "h2", "count": 1},
        "controlled relay H2 requests",
    )
    _require_exact(
        status.get("requestedDestinations"),
        [{"hostname": M5_TEST_HOSTNAME, "port": 443}],
        "controlled relay requested destinations",
    )
    transcript = status.get("transcript")
    if not isinstance(transcript, list) or not all(
        isinstance(entry, dict) for entry in transcript
    ):
        raise M0Error("controlled relay transcript is invalid")
    events = [entry.get("event") for entry in transcript]
    required_events = (
        "wisp-connected",
        "wisp-ready",
        "local-gateway-444-blocked",
        "connect-requested",
        "connect-open",
        "local-gateway-443-request",
    )
    for event in required_events:
        if events.count(event) != 1:
            raise M0Error(f"controlled relay requires one {event!r} event")
    if any(event in events for event in (
        "connect-rejected", "local-gateway-443-route-rejected",
    )):
        raise M0Error("controlled relay recorded an unexpected target rejection")
    if [events.index(event) for event in required_events] != sorted(
        events.index(event) for event in required_events
    ):
        raise M0Error("controlled relay events are out of native preflight order")
    for event in ("local-gateway-444-blocked", "local-gateway-443-request"):
        entry = next(item for item in transcript if item.get("event") == event)
        if set(entry) != {"sequence", "event"}:
            raise M0Error(f"controlled relay {event!r} is not redacted")
    for event in ("connect-requested", "connect-open"):
        entry = next(item for item in transcript if item.get("event") == event)
        if entry.get("destination") != f"{M5_TEST_HOSTNAME}:443":
            raise M0Error(f"controlled relay {event!r} did not use a.test:443")


def write_failure_diagnostics(
    diagnostics_dir: Path,
    *,
    stage: str,
    error: Exception,
    result: dict[str, Any] | None,
    relay_status: dict[str, Any] | None,
    browser_stderr: deque[str],
    relay_stderr: deque[str],
) -> Path:
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    output = diagnostics_dir / "m5-controlled-preflight-failure.json"
    payload = {
        "schema_version": 1,
        "runner": "run_m5_controlled_preflight_smoke.py",
        "case": M5_CONTROLLED_PREFLIGHT_CASE,
        "status": "fail",
        "stage": stage,
        "failure": {"type": type(error).__name__, "message": str(error)},
        "browser_stderr_tail": list(browser_stderr),
        "relay_stderr_tail": list(relay_stderr),
        "runtime_result": result,
        "relay_status": relay_status,
    }
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the isolated local M5 WISP gateway-denial preflight."
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument(
        "--out-dir", type=Path, default=Path("out/wasm-content-m3")
    )
    parser.add_argument("--module-name", default=M5_CONTROLLED_PREFLIGHT_MODULE)
    parser.add_argument("--node", type=Path)
    parser.add_argument(
        "--relay-script",
        type=Path,
        default=REPO_ROOT / "tools/wasm/m5_wisp_test_server.js",
    )
    parser.add_argument("--diagnostics-dir", type=Path)
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--timeout", type=parse_timeout, default=120.0)
    parser.add_argument("--verbose-server", action="store_true")
    args = parser.parse_args()

    out_dir = args.out_dir if args.out_dir.is_absolute() else REPO_ROOT / args.out_dir
    diagnostics_dir = args.diagnostics_dir or (
        out_dir / "diagnostics-m5-controlled-preflight"
    )
    if not diagnostics_dir.is_absolute():
        diagnostics_dir = REPO_ROOT / diagnostics_dir
    relay_script = args.relay_script
    if not relay_script.is_absolute():
        relay_script = REPO_ROOT / relay_script
    relay_script = relay_script.resolve()

    server = None
    server_thread = None
    browser: subprocess.Popen[str] | None = None
    relay: subprocess.Popen[str] | None = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    browser_stderr: deque[str] = deque(maxlen=300)
    relay_stdout: deque[str] = deque(maxlen=300)
    relay_stderr: deque[str] = deque(maxlen=300)
    browser_stderr_thread = None
    relay_stdout_thread = None
    relay_stderr_thread = None
    result: dict[str, Any] | None = None
    relay_status: dict[str, Any] | None = None
    stage = "load_manifest"
    server_started = False

    try:
        manifest = load_manifest()
        versions = manifest_versions(manifest, checked_output(["git", "rev-parse", "HEAD"]))
        print_context(
            "run_m5_controlled_preflight_smoke.py",
            manifest,
            case=M5_CONTROLLED_PREFLIGHT_CASE,
            gn_args=manifest.get("m3_content_gn_args", manifest.get("gn_args")),
            module_name=args.module_name,
            host_browser_sandbox=not args.no_sandbox,
            transport="WISP v2.1 over a local test-only WebSocket relay",
        )
        stage = "find_browser"
        browser_path, browser_version = find_browser(args.browser)
        print(
            f"{SENTINEL}:HOST_BROWSER " + json.dumps(
                {"browser_version": browser_version},
                sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        stage = "find_node"
        node = find_node(args.node)
        if not relay_script.is_file():
            raise M0Error("controlled preflight relay script is missing")
        stage = "verify_test_artifacts"
        verify_no_private_key_pem_artifacts(out_dir, args.module_name)
        token = secrets.token_urlsafe(24)
        result_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        stage = "create_host_server"
        server = create_m3_server(
            "127.0.0.1", 0, out_dir, token, result_queue,
            module_name=args.module_name, verbose=args.verbose_server)
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m5-controlled-preflight-host-server",
            daemon=True,
        )
        server_thread.start()
        server_started = True

        stage = "launch_relay"
        relay = subprocess.Popen(
            relay_command(node, relay_script, m5_host_origin(server)),
            cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True)
        assert relay.stdout is not None
        assert relay.stderr is not None
        ready_lines: queue.Queue[str | None] = queue.Queue()
        relay_stdout_thread = threading.Thread(
            target=_drain_relay_stdout,
            args=(relay.stdout, relay_stdout, ready_lines), daemon=True)
        relay_stdout_thread.start()
        relay_stderr_thread = threading.Thread(
            target=drain_stream, args=(relay.stderr, relay_stderr), daemon=True)
        relay_stderr_thread.start()
        stage = "wait_for_relay_ready"
        relay_ready = wait_for_relay_ready(
            relay, ready_lines, relay_stderr,
            time.monotonic() + min(30.0, max(1.0, args.timeout - 1.0)))
        print(f"{SENTINEL}:RELAY_READY loopback=true", flush=True)

        url = controlled_preflight_smoke_url(
            server, token, versions, relay_ready=relay_ready,
            module_name=args.module_name,
            timeout_seconds=min(180.0, max(1.0, args.timeout - 1.0)))
        profile = tempfile.TemporaryDirectory(
            prefix="chromium-wasm-m5-controlled-preflight-")
        stage = "launch_browser"
        browser = subprocess.Popen(
            m5_browser_command(browser_path, profile.name, url, no_sandbox=args.no_sandbox),
            cwd=REPO_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, start_new_session=True)
        assert browser.stderr is not None
        browser_stderr_thread = threading.Thread(
            target=drain_stream, args=(browser.stderr, browser_stderr), daemon=True)
        browser_stderr_thread.start()
        deadline = time.monotonic() + args.timeout
        stage = "wait_for_result"
        result = wait_for_result(browser, browser_stderr, result_queue, deadline)
        stage = "validate_runtime_contract"
        validate_controlled_preflight_result(result, expected_versions=versions)
        stage = "fetch_relay_transcript"
        relay_status = fetch_relay_transcript(
            relay_ready.transcript_url,
            timeout_seconds=min(10.0, max(1.0, deadline - time.monotonic())))
        stage = "validate_relay_transcript"
        validate_controlled_preflight_relay_transcript(relay_status)
        print(
            f"{SENTINEL}:BROWSER_RESULT " + json.dumps(
                result, sort_keys=True, separators=(",", ":")), flush=True)
        print(
            f"{SENTINEL}:RELAY_TRANSCRIPT " + json.dumps(
                relay_status, sort_keys=True, separators=(",", ":")), flush=True)
        print(f"{SENTINEL}:PASS", flush=True)
        return 0
    except (M0Error, OSError, KeyError, TypeError, ValueError) as exc:
        if browser is not None:
            stop_browser(browser)
        if relay is not None:
            stop_browser(relay)
        try:
            diagnostic = write_failure_diagnostics(
                diagnostics_dir, stage=stage, error=exc, result=result,
                relay_status=relay_status, browser_stderr=browser_stderr,
                relay_stderr=relay_stderr)
            print(f"{SENTINEL}:DIAGNOSTICS {json.dumps({'path': str(diagnostic)})}",
                  file=sys.stderr, flush=True)
        except OSError as diagnostic_error:
            print(f"{SENTINEL}:DIAGNOSTICS_FAIL reason={diagnostic_error}",
                  file=sys.stderr, flush=True)
        print(f"{SENTINEL}:FAIL reason={exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        if browser is not None:
            stop_browser(browser)
        if relay is not None:
            stop_browser(relay)
        if profile is not None:
            profile.cleanup()
        if server is not None:
            if server_started:
                server.shutdown()
            server.server_close()
        if server_thread is not None:
            server_thread.join(timeout=3)
        for thread in (
            browser_stderr_thread, relay_stdout_thread, relay_stderr_thread,
        ):
            if thread is not None:
                thread.join(timeout=1)


if __name__ == "__main__":
    sys.exit(main())
