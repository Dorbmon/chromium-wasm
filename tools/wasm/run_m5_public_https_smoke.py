#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run one opt-in public HTTPS probe through Chromium and an external WISP.

This deliberately does not reuse the controlled M5 relay. An operator supplies
an uncredentialed WSS gateway and one project-controlled public HTTPS document
at invocation time. Neither value is a default, is committed, or is written to
the runner's result and diagnostics. The gateway must independently allow only
the exact public DNS hostname on TCP port 443.
"""

from __future__ import annotations

import argparse
from collections import deque
import ipaddress
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
from urllib.parse import quote, quote_plus, unquote, urlencode, urlsplit, urlunsplit

from m0_common import (
    M0Error,
    REPO_ROOT,
    checked_output,
    load_manifest,
    parse_timeout,
    print_context,
)
from m3_content_server import M5_PUBLIC_HTTPS_CASE, create_m3_server
from run_browser_smoke import (
    browser_command,
    drain_stream,
    find_browser,
    stop_browser,
)
from run_content_shell_smoke import manifest_versions
from run_m5_wisp_smoke import verify_no_private_key_pem_artifacts


SENTINEL = "CHROMIUM_WASM_M5_PUBLIC_HTTPS"
DEFAULT_MODULE_NAME = "content_shell_wasm_m5_public_test"
MAXIMUM_URL_BYTES = 2048
MAXIMUM_TIMER_GAP_MS = 250
MINIMUM_HEARTBEAT_TIMER_TICKS = 2
MINIMUM_HEARTBEAT_ANIMATION_FRAMES = 2
BROWSER_WINDOW_SIZE = "1280,800"
PUBLIC_SPECIAL_USE_HOSTNAME_SUFFIXES = (
    ".localhost",
    ".local",
    ".test",
    ".example",
    ".invalid",
    ".onion",
    ".home.arpa",
)
URL_LIKE_VALUE_PATTERN = re.compile(
    r"\b(?:https?|wss)(?:://|%3a%2f%2f)[^\s\"'<>]*",
    re.IGNORECASE,
)


def _validated_port(parsed: Any, description: str) -> int | None:
    try:
        port = parsed.port
    except ValueError as exc:
        raise M0Error(f"{description} has an invalid port") from exc
    if port is not None and not 1 <= port <= 65535:
        raise M0Error(f"{description} has an invalid port")
    return port


def _split_public_url(value: str, description: str) -> Any:
    try:
        return urlsplit(value)
    except ValueError as exc:
        raise M0Error(f"{description} is not a valid URL") from exc


def _is_public_dns_hostname(hostname: str) -> bool:
    """Reject literals and local-only DNS names before they reach a gateway."""

    normalized = hostname.lower()
    if (
        not normalized
        or not normalized.isascii()
        or normalized == "localhost"
        or normalized == "home.arpa"
        or normalized.endswith(".")
        or any(
            normalized.endswith(suffix)
            for suffix in PUBLIC_SPECIAL_USE_HOSTNAME_SUFFIXES
        )
        or "." not in normalized
    ):
        return False
    try:
        ipaddress.ip_address(normalized)
        return False
    except ValueError:
        pass
    labels = normalized.split(".")
    if not all(
        label
        and len(label) <= 63
        and label[0].isalnum()
        and label[-1].isalnum()
        and all(character.isalnum() or character == "-" for character in label)
        for label in labels
    ):
        return False
    # WHATWG URL parsing canonicalizes legacy IPv4 spellings such as 127.1,
    # 0177.0.0.1, and 0x7f.0x0.0x0.0x1 to 127.0.0.1. Reject every
    # all-numeric component form conservatively before the browser turns a
    # seemingly public WSS hostname into a loopback literal.
    def is_legacy_ipv4_component(label: str) -> bool:
        if label.startswith("0x"):
            return len(label) > 2 and all(
                character in "0123456789abcdef" for character in label[2:]
            )
        return label.isdecimal()

    return not (
        len(labels) <= 4
        and all(is_legacy_ipv4_component(label) for label in labels)
    )


def _has_noncanonical_path(path: str) -> bool:
    decoded_path = unquote(path)
    return (
        "\\" in decoded_path
        or any(
            component in (".", "..")
            for component in decoded_path.split("/")
        )
    )


def _canonical_public_url(
    parsed: Any, *, scheme: str, port: int | None, default_port: int
) -> str:
    assert parsed.hostname is not None
    netloc = parsed.hostname.lower()
    if port is not None and port != default_port:
        netloc = f"{netloc}:{port}"
    return urlunsplit((scheme, netloc, parsed.path, "", ""))


def validate_public_wisp_endpoint(value: object) -> str:
    """Accept one credential-free external WSS endpoint, never a local relay."""

    if not isinstance(value, str) or not value:
        raise M0Error("public WISP endpoint must be a nonempty string")
    if len(value.encode("utf-8")) > MAXIMUM_URL_BYTES:
        raise M0Error("public WISP endpoint is too long")
    parsed = _split_public_url(value, "public WISP endpoint")
    port = _validated_port(parsed, "public WISP endpoint")
    if (
        parsed.scheme != "wss"
        or not parsed.hostname
        or not _is_public_dns_hostname(parsed.hostname)
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/")
        or not parsed.path.endswith("/")
        or _has_noncanonical_path(parsed.path)
    ):
        raise M0Error("public WISP endpoint violates the external policy")
    return _canonical_public_url(
        parsed, scheme="wss", port=port, default_port=443
    )


def validate_public_probe_url(value: object) -> str:
    """Accept a canonical public HTTPS document on the default TLS port."""

    if not isinstance(value, str) or not value:
        raise M0Error("public HTTPS probe URL must be a nonempty string")
    if len(value.encode("utf-8")) > MAXIMUM_URL_BYTES:
        raise M0Error("public HTTPS probe URL is too long")
    parsed = _split_public_url(value, "public HTTPS probe URL")
    port = _validated_port(parsed, "public HTTPS probe URL")
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not _is_public_dns_hostname(parsed.hostname)
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or port not in (None, 443)
        or not parsed.path.startswith("/")
        or _has_noncanonical_path(parsed.path)
    ):
        raise M0Error("public HTTPS probe URL violates the public-probe policy")
    return _canonical_public_url(
        parsed, scheme="https", port=port, default_port=443
    )


def parse_expected_status(value: str) -> int:
    try:
        status = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "expected HTTP status must be an integer"
        ) from exc
    if not 100 <= status <= 599:
        raise argparse.ArgumentTypeError(
            "expected HTTP status must be in [100, 599]"
        )
    return status


def public_smoke_url(
    server: Any,
    token: str,
    versions: dict[str, str],
    *,
    public_wisp_endpoint: str,
    public_probe_url: str,
    expected_status: int,
    expected_protocol: str,
    module_name: str = DEFAULT_MODULE_NAME,
    timeout_seconds: float = 120.0,
) -> str:
    """Build the local host URL without logging the supplied public inputs."""

    endpoint = validate_public_wisp_endpoint(public_wisp_endpoint)
    probe_url = validate_public_probe_url(public_probe_url)
    if expected_protocol not in ("h2", "http/1.1"):
        raise M0Error("public HTTPS expected protocol is invalid")
    if not 100 <= expected_status <= 599:
        raise M0Error("public HTTPS expected status is invalid")
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "case": M5_PUBLIC_HTTPS_CASE,
            "chromium": versions["chromium"],
            "emscripten": versions["emscripten"],
            "m5_public_protocol": expected_protocol,
            "m5_public_status": expected_status,
            "m5_public_url": probe_url,
            "module": f"/__m3__/artifacts/{module_name}.js",
            "port": versions["port"],
            "token": token,
            "timeout_ms": max(1000, min(180000, int(timeout_seconds * 1000))),
            "v8": versions["v8"],
            "wisp_endpoint": endpoint,
        }
    )
    return f"http://{host}:{port}/__m3__/?{query}"


def public_browser_command(
    browser: Path, profile: str, url: str, *, no_sandbox: bool
) -> list[str]:
    command = browser_command(browser, profile, url, no_sandbox=no_sandbox)
    command[1:1] = [f"--window-size={BROWSER_WINDOW_SIZE}"]
    return command


def _require_dict(value: object, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise M0Error(f"{description} must be an object")
    return value


def _require_bool(value: object, description: str) -> bool:
    if type(value) is not bool:
        raise M0Error(f"{description} must be a bool")
    return value


def _require_int(value: object, description: str) -> int:
    if type(value) is not int:
        raise M0Error(f"{description} must be an int")
    return value


def _require_string(value: object, description: str) -> str:
    if not isinstance(value, str):
        raise M0Error(f"{description} must be a string")
    return value


def validate_public_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
    expected_status: int,
    expected_protocol: str,
    public_wisp_endpoint: str,
    public_probe_url: str,
) -> None:
    """Validate only redacted public-network evidence from the inner browser."""

    canonical_endpoint = validate_public_wisp_endpoint(public_wisp_endpoint)
    canonical_probe_url = validate_public_probe_url(public_probe_url)
    if result.get("protocol") != 1:
        raise M0Error("public HTTPS result protocol mismatch")
    if result.get("case") != M5_PUBLIC_HTTPS_CASE:
        raise M0Error("public HTTPS result case mismatch")
    if result.get("status") != "pass":
        raise M0Error("public HTTPS host reported failure")
    for field in ("crossOriginIsolated", "sharedArrayBuffer", "canvasFocused"):
        if _require_bool(result.get(field), f"public HTTPS {field}") is not True:
            raise M0Error(f"public HTTPS {field} is false")
    if result.get("versions") != expected_versions:
        raise M0Error("public HTTPS versions mismatch")
    initial_frame = _require_dict(
        result.get("initialFrame"), "public HTTPS initial frame"
    )
    initial_frame_id = _require_int(
        initial_frame.get("id"), "public HTTPS initial frame id"
    )
    if (
        initial_frame_id < 1
        or initial_frame.get("width") != 800
        or initial_frame.get("height") != 600
    ):
        raise M0Error("public HTTPS initial frame is invalid")
    public_frame = _require_dict(
        result.get("publicFrame"), "public HTTPS post-navigation frame"
    )
    public_frame_id = _require_int(
        public_frame.get("id"), "public HTTPS post-navigation frame id"
    )
    if (
        public_frame_id <= initial_frame_id
        or public_frame.get("width") != 800
        or public_frame.get("height") != 600
    ):
        raise M0Error("public HTTPS post-navigation frame is invalid")
    navigation_result = _require_dict(
        result.get("navigationResult"), "public HTTPS navigation result"
    )
    if navigation_result != {"ok": True, "scheme": "https"}:
        raise M0Error("public HTTPS navigation result is invalid")
    public_devtools_network_enabled = _require_dict(
        result.get("publicDevtoolsNetworkEnabled"),
        "public HTTPS DevTools Network enable",
    )
    if public_devtools_network_enabled != {
        "protocol": 1,
        "state": "enabled",
        "networkEnabled": True,
        "events": [],
    }:
        raise M0Error("public HTTPS DevTools Network.enable is invalid")
    readiness = _require_dict(result.get("readiness"), "public HTTPS readiness")
    navigation = _require_dict(
        readiness.get("navigation"), "public HTTPS navigation evidence"
    )
    if navigation != {
        "committed": True,
        "scheme": "https",
        "responseCode": expected_status,
        "connectionProtocol": expected_protocol,
    }:
        raise M0Error("public HTTPS navigation metadata is invalid")
    if readiness.get("firstVisuallyNonEmptyPaint") is not True:
        raise M0Error("public HTTPS page did not paint")
    if readiness.get("fatalErrors") != []:
        raise M0Error("public HTTPS readiness reported fatal errors")
    public_devtools_network = _require_dict(
        readiness.get("publicDevtoolsNetwork"),
        "public HTTPS DevTools Network log",
    )
    if public_devtools_network != {
        "protocol": 1,
        "state": "complete",
        "networkEnabled": True,
        "documentRequest": True,
        "responseReceived": True,
        "loadingFinished": True,
        "requestIdCorrelated": True,
        "responseStatus": expected_status,
        "responseProtocol": expected_protocol,
        "wispWebSocketOpened": True,
        "wispHandshakeReady": True,
        "wispConfirmedStream": True,
        "events": [
            "Network.requestWillBeSent:document",
            "Network.responseReceived:document",
            "Network.loadingFinished:document",
        ],
    }:
        raise M0Error(
            "public HTTPS DevTools Network log does not contain the bounded "
            "Chromium CDP and WISP completion trace"
        )
    heartbeat = _require_dict(
        readiness.get("heartbeat"), "public HTTPS host heartbeat"
    )
    if (
        heartbeat.get("anchor") != "m5-public-https-navigation-committed"
        or _require_int(
            heartbeat.get("timerDelta"), "public HTTPS heartbeat timer delta"
        )
        < MINIMUM_HEARTBEAT_TIMER_TICKS
        or _require_int(
            heartbeat.get(
                "animationFrameDelta"
            ),
            "public HTTPS heartbeat animation-frame delta",
        )
        < MINIMUM_HEARTBEAT_ANIMATION_FRAMES
        or _require_int(
            heartbeat.get("maxTimerGapMs"),
            "public HTTPS heartbeat maximum timer gap",
        )
        > MAXIMUM_TIMER_GAP_MS
    ):
        raise M0Error("public HTTPS host heartbeat is invalid")
    logs = _require_dict(result.get("logs"), "public HTTPS logs")
    host_logs = logs.get("host")
    if not isinstance(host_logs, list):
        raise M0Error("public HTTPS host logs must be an array")
    for marker in (
        "initialize:wisp-configured",
        "m5:public-devtools-network:enabled",
        "navigation:requested:m5-public-https",
        "navigation:committed:m5-public-https",
        "m5:public-devtools-network:complete",
        "shutdown:complete",
    ):
        if host_logs.count(marker) != 1:
            raise M0Error(f"public HTTPS host logs need one {marker!r}")
    if not (
        host_logs.index("initialize:wisp-configured")
        < host_logs.index("m5:public-devtools-network:enabled")
        < host_logs.index("navigation:requested:m5-public-https")
        < host_logs.index("navigation:committed:m5-public-https")
        < host_logs.index("m5:public-devtools-network:complete")
        < host_logs.index("shutdown:complete")
    ):
        raise M0Error("public HTTPS host log ordering is invalid")
    shutdown = _require_dict(result.get("shutdown"), "public HTTPS shutdown")
    if (
        shutdown.get("ok") is not True
        or shutdown.get("complete") is not True
        or shutdown.get("exitCode") != 0
        or shutdown.get("runtimeExitCode") != 0
    ):
        raise M0Error("public HTTPS shutdown is invalid")
    if result.get("failedChecks") != [] or result.get("error") is not None:
        raise M0Error("public HTTPS result contains a failed check")

    # The outer host receives the raw inputs only long enough to configure
    # Emscripten. Do not let them escape back into a result artifact.
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    for secret in (
        public_wisp_endpoint,
        public_probe_url,
        canonical_endpoint,
        canonical_probe_url,
    ):
        for rendered in (secret, quote(secret, safe=""), quote_plus(secret)):
            if rendered and rendered in serialized:
                raise M0Error("public HTTPS result leaked a configured URL")
    if URL_LIKE_VALUE_PATTERN.search(serialized):
        raise M0Error("public HTTPS result contains an unredacted URL")


def wait_for_result(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    result_queue: queue.Queue[dict[str, Any]],
    deadline: float,
) -> dict[str, Any]:
    while time.monotonic() < deadline:
        if browser.poll() is not None:
            raise M0Error(
                "host browser exited before the public HTTPS result "
                f"(status {browser.returncode})"
            )
        remaining = deadline - time.monotonic()
        try:
            return result_queue.get(timeout=min(0.1, max(0.0, remaining)))
        except queue.Empty:
            continue
    raise M0Error("public HTTPS browser timeout")


def _redact_text(value: str, *, endpoint: str, probe_url: str) -> str:
    result = value
    candidates = [endpoint, probe_url]
    try:
        candidates.append(validate_public_wisp_endpoint(endpoint))
    except M0Error:
        pass
    try:
        candidates.append(validate_public_probe_url(probe_url))
    except M0Error:
        pass
    for secret in candidates:
        for rendered in (secret, quote(secret, safe=""), quote_plus(secret)):
            if rendered:
                result = result.replace(rendered, "<redacted>")
    return URL_LIKE_VALUE_PATTERN.sub("<redacted-url>", result)


def _redact_value(value: Any, *, endpoint: str, probe_url: str) -> Any:
    if isinstance(value, str):
        return _redact_text(value, endpoint=endpoint, probe_url=probe_url)
    if isinstance(value, list):
        return [
            _redact_value(item, endpoint=endpoint, probe_url=probe_url)
            for item in value
        ]
    if isinstance(value, dict):
        return {
            str(key): _redact_value(
                item, endpoint=endpoint, probe_url=probe_url
            )
            for key, item in value.items()
        }
    return value


def write_failure_diagnostics(
    diagnostics_dir: Path,
    *,
    stage: str,
    error: Exception,
    context: dict[str, object] | None,
    browser_path: Path | None,
    browser_version: str | None,
    browser: subprocess.Popen[str] | None,
    browser_stderr: deque[str],
    result: dict[str, Any] | None,
    public_wisp_endpoint: str,
    public_probe_url: str,
) -> Path:
    """Persist redacted diagnostics without exposing runtime-only URLs."""

    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    diagnostic_path = diagnostics_dir / "m5-public-https-failure.json"
    diagnostic = {
        "schema_version": 1,
        "runner": "run_m5_public_https_smoke.py",
        "case": M5_PUBLIC_HTTPS_CASE,
        "status": "fail",
        "stage": stage,
        "failure": {
            "type": type(error).__name__,
            "message": _redact_text(
                str(error),
                endpoint=public_wisp_endpoint,
                probe_url=public_probe_url,
            ),
        },
        "context": _redact_value(
            context, endpoint=public_wisp_endpoint, probe_url=public_probe_url
        ),
        "configured_inputs": {
            "public_wisp_endpoint": "<redacted>",
            "public_probe_url": "<redacted>",
        },
        "host_browser": {
            "path": str(browser_path) if browser_path else None,
            "version": browser_version,
            "return_code": browser.poll() if browser else None,
            "stderr_tail": _redact_value(
                list(browser_stderr),
                endpoint=public_wisp_endpoint,
                probe_url=public_probe_url,
            ),
        },
        "runtime_result": _redact_value(
            result, endpoint=public_wisp_endpoint, probe_url=public_probe_url
        ),
    }
    temporary_path = diagnostic_path.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(diagnostic, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(diagnostic_path)
    return diagnostic_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run one operator-configured public HTTPS document through "
            "Chromium's WISP socket transport."
        )
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument(
        "--out-dir", type=Path, default=Path("out/wasm-content-m3")
    )
    parser.add_argument("--module-name", default=DEFAULT_MODULE_NAME)
    parser.add_argument(
        "--public-wisp-endpoint",
        required=True,
        help="credential-free external wss:// gateway; never persisted",
    )
    parser.add_argument(
        "--public-probe-url",
        required=True,
        help="one project-controlled https:// DNS-hostname:443 document",
    )
    parser.add_argument(
        "--expected-status",
        required=True,
        type=parse_expected_status,
        help="expected final HTTP response status for the exact probe",
    )
    parser.add_argument(
        "--expected-protocol",
        choices=("h2", "http/1.1"),
        required=True,
        help="expected Chromium HTTP protocol; HTTP/3 remains disabled",
    )
    parser.add_argument(
        "--diagnostics-dir",
        type=Path,
        help="failure directory (default: OUT_DIR/diagnostics-m5-public-https)",
    )
    parser.add_argument(
        "--no-sandbox",
        action="store_true",
        help="disable the host browser sandbox (isolated CI only)",
    )
    parser.add_argument("--timeout", type=parse_timeout, default=120.0)
    args = parser.parse_args()

    out_dir = args.out_dir
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    diagnostics_dir = args.diagnostics_dir
    if diagnostics_dir is None:
        diagnostics_dir = out_dir / "diagnostics-m5-public-https"
    elif not diagnostics_dir.is_absolute():
        diagnostics_dir = REPO_ROOT / diagnostics_dir

    public_wisp_endpoint = args.public_wisp_endpoint
    public_probe_url = args.public_probe_url
    server = None
    server_thread = None
    server_started = False
    browser: subprocess.Popen[str] | None = None
    browser_path: Path | None = None
    browser_version: str | None = None
    browser_stderr: deque[str] = deque(maxlen=300)
    browser_stderr_thread: threading.Thread | None = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    result: dict[str, Any] | None = None
    context: dict[str, object] | None = None
    stage = "validate_inputs"

    try:
        public_wisp_endpoint = validate_public_wisp_endpoint(
            public_wisp_endpoint
        )
        public_probe_url = validate_public_probe_url(public_probe_url)
        stage = "load_manifest"
        manifest = load_manifest()
        port_revision = checked_output(["git", "rev-parse", "HEAD"])
        versions = manifest_versions(manifest, port_revision)
        stage = "print_context"
        context = print_context(
            "run_m5_public_https_smoke.py",
            manifest,
            case=M5_PUBLIC_HTTPS_CASE,
            gn_args=manifest.get(
                "m3_content_gn_args", manifest.get("gn_args")
            ),
            module_name=args.module_name,
            host_browser_sandbox=not args.no_sandbox,
            transport="WISP v2.1 over an operator-provisioned external WSS gateway",
            configured_endpoint="<redacted>",
            configured_probe="<redacted>",
        )
        stage = "find_browser"
        browser_path, browser_version = find_browser(args.browser)
        print(
            f"{SENTINEL}:HOST_BROWSER "
            + json.dumps(
                {"browser_version": browser_version},
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )

        token = secrets.token_urlsafe(24)
        result_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        stage = "verify_test_artifacts"
        verify_no_private_key_pem_artifacts(out_dir, args.module_name)
        stage = "create_host_server"
        server = create_m3_server(
            "127.0.0.1",
            0,
            out_dir,
            token,
            result_queue,
            module_name=args.module_name,
        )
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m5-public-host-server",
            daemon=True,
        )
        server_thread.start()
        server_started = True
        host_url = public_smoke_url(
            server,
            token,
            versions,
            public_wisp_endpoint=public_wisp_endpoint,
            public_probe_url=public_probe_url,
            expected_status=args.expected_status,
            expected_protocol=args.expected_protocol,
            module_name=args.module_name,
            timeout_seconds=min(180.0, max(1.0, args.timeout - 1.0)),
        )

        profile = tempfile.TemporaryDirectory(
            prefix="chromium-wasm-m5-public-"
        )
        stage = "launch_browser"
        browser = subprocess.Popen(
            public_browser_command(
                browser_path, profile.name, host_url, no_sandbox=args.no_sandbox
            ),
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        assert browser.stderr is not None
        browser_stderr_thread = threading.Thread(
            target=drain_stream,
            args=(browser.stderr, browser_stderr),
            name="chromium-wasm-m5-public-browser-stderr",
            daemon=True,
        )
        browser_stderr_thread.start()
        deadline = time.monotonic() + args.timeout
        stage = "wait_for_result"
        result = wait_for_result(browser, browser_stderr, result_queue, deadline)
        stage = "validate_runtime_contract"
        validate_public_result(
            result,
            expected_versions=versions,
            expected_status=args.expected_status,
            expected_protocol=args.expected_protocol,
            public_wisp_endpoint=public_wisp_endpoint,
            public_probe_url=public_probe_url,
        )
        print(f"{SENTINEL}:PASS", flush=True)
        return 0
    except (M0Error, OSError, KeyError, TypeError, ValueError) as exc:
        if browser is not None:
            stop_browser(browser)
        if browser_stderr_thread is not None:
            browser_stderr_thread.join(timeout=1)
        try:
            diagnostic_path = write_failure_diagnostics(
                diagnostics_dir,
                stage=stage,
                error=exc,
                context=context,
                browser_path=browser_path,
                browser_version=browser_version,
                browser=browser,
                browser_stderr=browser_stderr,
                result=result,
                public_wisp_endpoint=public_wisp_endpoint,
                public_probe_url=public_probe_url,
            )
            print(
                f"{SENTINEL}:DIAGNOSTICS "
                + json.dumps(
                    {"path": str(diagnostic_path)},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                file=sys.stderr,
                flush=True,
            )
        except (OSError, TypeError, ValueError) as diagnostic_error:
            print(
                f"{SENTINEL}:DIAGNOSTICS_FAIL reason={diagnostic_error}",
                file=sys.stderr,
                flush=True,
            )
        print(
            f"{SENTINEL}:FAIL reason="
            + _redact_text(
                str(exc),
                endpoint=public_wisp_endpoint,
                probe_url=public_probe_url,
            ),
            file=sys.stderr,
            flush=True,
        )
        return 1
    finally:
        if browser is not None:
            stop_browser(browser)
        if profile is not None:
            profile.cleanup()
        if server is not None:
            if server_started:
                server.shutdown()
            server.server_close()
        if server_started and server_thread is not None:
            server_thread.join(timeout=3)
        if browser_stderr_thread is not None:
            browser_stderr_thread.join(timeout=1)


if __name__ == "__main__":
    raise SystemExit(main())
