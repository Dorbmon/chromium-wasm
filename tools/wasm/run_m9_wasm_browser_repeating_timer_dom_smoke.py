#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the bounded native Chromium UI-sequence repeating-timer smoke.

This is M9 preparation evidence, not an M9 release gate. It proves only that
one visible single-process Browser executes three fixed ``base::RepeatingTimer``
callbacks while the outer host event loop remains responsive, then reaches the
ordinary Browser destruction barrier without later timer output. It does not
measure long-run timer reliability, worker drain, memory leaks, performance,
persistence, networking, or M8 feature compatibility.
"""

from __future__ import annotations

import argparse
from collections import deque
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
from urllib.parse import urlencode, urlsplit

from check_m6_chrome_boundary import check_boundary
from m0_common import (
    M0Error,
    REPO_ROOT,
    checked_output,
    load_manifest,
    parse_timeout,
    print_context,
)
from run_browser_smoke import browser_command, drain_stream, find_browser, stop_browser
from run_content_shell_smoke import manifest_versions
import run_wasm_browser_view_smoke as browser_view_smoke


SENTINEL = "CHROMIUM_WASM_M9_REPEATING_TIMER_DOM"
CASE = "browser_repeating_timer_m9"
SCOPE = (
    "fixed-three-native-ui-repeating-timer-ticks-with-host-event-loop-and-"
    "post-shutdown-quiet-observation"
)
SWITCH = "--wasm-browser-m9-repeating-timer-smoke"
READY_MARKER = "CHROMIUM_WASM_M9_REPEATING_TIMER:READY ticks=3 interval_ms=50"
TICK_MARKER_PREFIX = "CHROMIUM_WASM_M9_REPEATING_TIMER:TICK ordinal="
PASS_MARKER = "CHROMIUM_WASM_M9_REPEATING_TIMER:PASS ticks=3"
TIMEOUT_MARKER_PREFIX = "CHROMIUM_WASM_M9_REPEATING_TIMER:TIMEOUT"
TIMER_MARKER_PREFIX = "CHROMIUM_WASM_M9_REPEATING_TIMER:"
LIFECYCLE_PASS_MARKER = "CHROMIUM_WASM_M6_BROWSER_LIFECYCLE:PASS"
TICK_COUNT = 3
POST_EXIT_GRACE_MS = 100
HOST_ROOT = "/__m9_repeating_timer__"
PRODUCT_MODULE_NAME = "chrome_wasm"
MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
MAX_RESULT_BYTES = 1024 * 1024
MAX_ARTIFACT_BYTES = 4 * 1024 * 1024 * 1024


class RepeatingTimerSmokeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    result_queue: queue.Queue[dict[str, Any]]
    result_token: str
    result_received: bool
    result_lock: threading.Lock


class RepeatingTimerSmokeRequestHandler(BaseHTTPRequestHandler):
    server: RepeatingTimerSmokeServer

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def end_headers(self) -> None:
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def _send_bytes(
        self, status: HTTPStatus, content_type: str, body: bytes
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self) -> None:
        self._send_bytes(
            HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found\n"
        )

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path in (HOST_ROOT, f"{HOST_ROOT}/"):
            self._send_bytes(
                HTTPStatus.OK, "text/html; charset=utf-8", self.server.html_bytes
            )
            return
        if path == f"{HOST_ROOT}/chrome_wasm_browser_m9_repeating_timer_smoke.js":
            self._send_bytes(
                HTTPStatus.OK,
                "text/javascript; charset=utf-8",
                self.server.host_js_bytes,
            )
            return
        prefix = f"{HOST_ROOT}/artifacts/"
        if path.startswith(prefix):
            artifact_name = path[len(prefix) :]
            artifact = self.server.artifacts.get(artifact_name)
            if artifact is None:
                self._not_found()
                return
            self._send_bytes(
                HTTPStatus.OK,
                "application/wasm"
                if artifact_name.endswith(".wasm")
                else "text/javascript; charset=utf-8",
                artifact,
            )
            return
        self._not_found()

    def do_POST(self) -> None:
        if urlsplit(self.path).path != f"{HOST_ROOT}/result/{self.server.result_token}":
            self._not_found()
            return
        content_length = self.headers.get("Content-Length")
        try:
            byte_count = int(content_length) if content_length is not None else -1
        except ValueError:
            byte_count = -1
        if byte_count < 0 or byte_count > MAX_RESULT_BYTES:
            self._send_bytes(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "text/plain; charset=utf-8",
                b"invalid result size\n",
            )
            return
        result = parse_result_payload(self.rfile.read(byte_count))
        if result is None:
            self._send_bytes(
                HTTPStatus.BAD_REQUEST,
                "text/plain; charset=utf-8",
                b"invalid repeating-timer result\n",
            )
            return
        with self.server.result_lock:
            if self.server.result_received:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"repeating-timer result already received\n",
                )
                return
            try:
                self.server.result_queue.put_nowait(result)
            except queue.Full:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"repeating-timer result queue is full\n",
                )
                return
            self.server.result_received = True
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()


def parse_result_payload(payload: bytes) -> dict[str, Any] | None:
    try:
        result = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=browser_view_smoke._reject_duplicate_result_object_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    if (
        not isinstance(result, dict)
        or result.get("protocol") != 1
        or result.get("case") != CASE
        or result.get("scope") != SCOPE
    ):
        return None
    return result


def _snapshot_artifacts(
    out_dir: Path, module_name: str
) -> tuple[dict[str, bytes], dict[str, dict[str, object]]]:
    artifacts: dict[str, bytes] = {}
    identity: dict[str, dict[str, object]] = {}
    for suffix in (".js", ".wasm"):
        name = f"{module_name}{suffix}"
        path = out_dir / name
        if not path.is_file():
            raise M0Error(f"repeating-timer artifact is missing: {path}")
        data = path.read_bytes()
        if not data or len(data) > MAX_ARTIFACT_BYTES:
            raise M0Error(f"repeating-timer artifact has invalid size: {path}")
        artifacts[name] = data
        identity[name] = {
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    return artifacts, identity


def create_server(
    host: str,
    port: int,
    out_dir: Path,
    result_token: str,
    result_queue: queue.Queue[dict[str, Any]],
    *,
    module_name: str,
) -> tuple[RepeatingTimerSmokeServer, dict[str, dict[str, object]]]:
    if not MODULE_NAME_RE.fullmatch(module_name):
        raise M0Error("module name must contain only ASCII letters, digits, or _")
    out_dir = out_dir.resolve()
    if not out_dir.is_dir():
        raise M0Error(f"repeating-timer output directory is missing: {out_dir}")
    artifacts, artifact_identity = _snapshot_artifacts(out_dir, module_name)
    host_dir = Path(__file__).with_name("host")
    server = RepeatingTimerSmokeServer(
        (host, port), RepeatingTimerSmokeRequestHandler
    )
    server.result_token = result_token
    server.result_queue = result_queue
    server.result_received = False
    server.result_lock = threading.Lock()
    server.artifacts = artifacts
    server.html_bytes = (
        host_dir / "chrome_wasm_browser_m9_repeating_timer_smoke.html"
    ).read_bytes()
    server.host_js_bytes = (
        host_dir / "chrome_wasm_browser_m9_repeating_timer_smoke.js"
    ).read_bytes()
    return server, artifact_identity


def smoke_url(
    server: RepeatingTimerSmokeServer,
    token: str,
    versions: dict[str, str],
    *,
    module_name: str,
    timeout_seconds: float,
) -> str:
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "token": token,
            "module": module_name,
            "timeoutMs": str(int(timeout_seconds * 1000)),
            "versions": json.dumps(versions, sort_keys=True, separators=(",", ":")),
        }
    )
    return f"http://{host}:{port}{HOST_ROOT}/?{query}"


def _require_equal(result: dict[str, Any], field: str, expected: object) -> None:
    if not browser_view_smoke._exact_json_value_equal(result.get(field), expected):
        raise M0Error(
            f"repeating-timer result {field} mismatch: "
            f"expected {expected!r}, got {result.get(field)!r}"
        )


def _require_positive_int(value: object, description: str) -> int:
    if type(value) is not int or value < 0:
        raise M0Error(f"repeating-timer {description} is not a nonnegative integer")
    return value


def _validate_event_loop_snapshot(value: object, description: str) -> dict[str, int]:
    if not isinstance(value, dict) or set(value) != {
        "heartbeatCount",
        "animationFrameCount",
    }:
        raise M0Error(f"repeating-timer {description} shape is invalid")
    return {
        "heartbeatCount": _require_positive_int(
            value["heartbeatCount"], f"{description} heartbeat count"
        ),
        "animationFrameCount": _require_positive_int(
            value["animationFrameCount"], f"{description} frame count"
        ),
    }


def _validate_ticks(value: object) -> None:
    if not isinstance(value, list) or len(value) != TICK_COUNT:
        raise M0Error("repeating-timer ticks do not have the fixed count")
    previous_heartbeat = -1
    previous_animation_frame = -1
    for expected_ordinal, tick in enumerate(value, start=1):
        if not isinstance(tick, dict) or set(tick) != {
            "ordinal",
            "heartbeatCount",
            "animationFrameCount",
        }:
            raise M0Error("repeating-timer tick shape is invalid")
        if tick["ordinal"] != expected_ordinal:
            raise M0Error("repeating-timer tick ordinal is invalid")
        snapshot = _validate_event_loop_snapshot(
            {
                "heartbeatCount": tick["heartbeatCount"],
                "animationFrameCount": tick["animationFrameCount"],
            },
            "tick",
        )
        if (
            snapshot["heartbeatCount"] < previous_heartbeat
            or snapshot["animationFrameCount"] < previous_animation_frame
        ):
            raise M0Error("repeating-timer event-loop counters regressed")
        previous_heartbeat = snapshot["heartbeatCount"]
        previous_animation_frame = snapshot["animationFrameCount"]


def _validate_post_exit_observation(value: object) -> None:
    expected_fields = {
        "before",
        "after",
        "graceMs",
        "animationFrameAdvanced",
        "errorsQuiet",
        "framesQuiet",
        "heartbeatAdvanced",
        "timerMarkersQuiet",
    }
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise M0Error("repeating-timer post-exit observation shape is invalid")
    if value["graceMs"] != POST_EXIT_GRACE_MS:
        raise M0Error("repeating-timer post-exit grace is invalid")
    for field in (
        "animationFrameAdvanced",
        "errorsQuiet",
        "framesQuiet",
        "heartbeatAdvanced",
        "timerMarkersQuiet",
    ):
        if value[field] is not True:
            raise M0Error(f"repeating-timer post-exit check did not pass: {field}")
    expected_counts = {
        "animationFrameCount",
        "fatalErrors",
        "frameReports",
        "heartbeatCount",
        "timerMarkers",
        "unhandledRejections",
        "windowErrors",
    }
    for name in ("before", "after"):
        counts = value[name]
        if not isinstance(counts, dict) or set(counts) != expected_counts:
            raise M0Error(f"repeating-timer post-exit {name} count shape is invalid")
        for field, count in counts.items():
            _require_positive_int(count, f"post-exit {name} {field}")
    before = value["before"]
    after = value["after"]
    if (
        after["heartbeatCount"] <= before["heartbeatCount"]
        or after["animationFrameCount"] <= before["animationFrameCount"]
        or after["timerMarkers"] != before["timerMarkers"]
        or after["frameReports"] != before["frameReports"]
        or after["fatalErrors"] != before["fatalErrors"]
        or after["windowErrors"] != before["windowErrors"]
        or after["unhandledRejections"] != before["unhandledRejections"]
    ):
        raise M0Error("repeating-timer post-exit counters are inconsistent")


def _validate_native_markers(stderr: object) -> None:
    if not isinstance(stderr, list) or any(type(line) is not str for line in stderr):
        raise M0Error("repeating-timer stderr is invalid")
    timer_lines = [line for line in stderr if line.startswith(TIMER_MARKER_PREFIX)]
    expected_timer_lines = [
        READY_MARKER,
        *(f"{TICK_MARKER_PREFIX}{ordinal}" for ordinal in range(1, TICK_COUNT + 1)),
        PASS_MARKER,
    ]
    if timer_lines != expected_timer_lines:
        raise M0Error("repeating-timer native markers are malformed or out of order")
    if any(line.startswith(TIMEOUT_MARKER_PREFIX) for line in stderr):
        raise M0Error("repeating-timer native watchdog timed out")
    if stderr.count(LIFECYCLE_PASS_MARKER) != 1:
        raise M0Error("repeating-timer lifecycle PASS marker is not unique")
    if stderr.index(LIFECYCLE_PASS_MARKER) <= stderr.index(PASS_MARKER):
        raise M0Error("repeating-timer lifecycle PASS did not follow native PASS")


def validate_result(result: dict[str, Any], *, expected_versions: dict[str, str]) -> None:
    for field, expected in {
        "protocol": 1,
        "case": CASE,
        "scope": SCOPE,
        "status": "pass",
        "m9GateComplete": False,
        "m9TimerSmokeOnly": True,
        "runtimeExitCode": 0,
        "processExitCode": 0,
        "runtimeInitialized": True,
        "factorySettled": True,
        "factoryRejected": False,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "readyObserved": True,
        "passObserved": True,
        "lifecyclePassObserved": True,
        "ozoneFocusObserved": True,
        "abort": None,
        "failedChecks": [],
        "error": None,
    }.items():
        _require_equal(result, field, expected)
    if result.get("versions") != expected_versions:
        raise M0Error("repeating-timer versions do not match the manifest")
    for field in ("fatalErrors", "windowErrors", "unhandledRejections"):
        if not isinstance(result.get(field), list) or result[field]:
            raise M0Error(f"repeating-timer {field} is not empty")
    if not isinstance(result.get("stdout"), list):
        raise M0Error("repeating-timer stdout is not a list")
    _validate_native_markers(result.get("stderr"))
    _validate_ticks(result.get("ticks"))
    responsiveness = _validate_event_loop_snapshot(
        result.get("responsivenessAtPass"), "pass responsiveness"
    )
    if responsiveness["heartbeatCount"] < 2:
        raise M0Error("repeating-timer host interval did not advance before pass")
    if responsiveness["animationFrameCount"] < 1:
        raise M0Error("repeating-timer host animation frame did not advance before pass")
    _validate_post_exit_observation(result.get("postExitObservation"))
    browser_view_smoke._validate_frame_reports(result.get("frameReports"))
    browser_view_smoke._validate_readiness(
        result.get("readiness"), result.get("readinessReports")
    )


def wait_for_result(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    result_queue: queue.Queue[dict[str, Any]],
    deadline: float,
) -> dict[str, Any]:
    while True:
        if browser.poll() is not None:
            raise M0Error(
                "host browser exited before repeating-timer result: "
                + "\n".join(browser_stderr)
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M0Error(
                "repeating-timer smoke timeout: " + "\n".join(browser_stderr)
            )
        try:
            return result_queue.get(timeout=min(0.1, remaining))
        except queue.Empty:
            continue


def write_failure_diagnostics(
    diagnostics_dir: Path,
    *,
    stage: str,
    error: Exception,
    browser_path: Path | None,
    browser_version: str | None,
    browser: subprocess.Popen[str] | None,
    browser_stderr: deque[str],
    runtime_result: dict[str, Any] | None,
    artifact_identity: dict[str, dict[str, object]] | None,
) -> Path:
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / "chrome-browser-m9-repeating-timer-failure.json"
    payload = {
        "schema_version": 1,
        "runner": "run_m9_wasm_browser_repeating_timer_dom_smoke.py",
        "case": CASE,
        "scope": SCOPE,
        "stage": stage,
        "failure": {"type": type(error).__name__, "message": str(error)},
        "host_browser": {
            "path": str(browser_path) if browser_path else None,
            "version": browser_version,
            "return_code": browser.poll() if browser else None,
            "stderr_tail": list(browser_stderr),
        },
        "artifact_snapshot": artifact_identity,
        "runtime_result": runtime_result,
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the bounded Chromium UI-sequence repeating-timer smoke."
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--out-dir", type=Path, default=Path("out/wasm-chrome-m6"))
    parser.add_argument("--module-name", default=PRODUCT_MODULE_NAME)
    parser.add_argument("--diagnostics-dir", type=Path)
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--timeout", type=parse_timeout, default=60.0)
    args = parser.parse_args()
    if args.timeout < 2.0:
        parser.error("--timeout must be at least two seconds")
    if not MODULE_NAME_RE.fullmatch(args.module_name):
        parser.error("--module-name must contain only ASCII letters, digits, or _")

    out_dir = args.out_dir if args.out_dir.is_absolute() else REPO_ROOT / args.out_dir
    diagnostics_dir = args.diagnostics_dir or out_dir / "diagnostics"
    if not diagnostics_dir.is_absolute():
        diagnostics_dir = REPO_ROOT / diagnostics_dir
    server: RepeatingTimerSmokeServer | None = None
    server_thread: threading.Thread | None = None
    browser: subprocess.Popen[str] | None = None
    browser_path: Path | None = None
    browser_version: str | None = None
    browser_stderr: deque[str] = deque(maxlen=300)
    stderr_thread: threading.Thread | None = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    result: dict[str, Any] | None = None
    artifact_identity: dict[str, dict[str, object]] | None = None
    stage = "check_artifacts"

    try:
        stage = "check_boundary"
        check_boundary(out_dir)
        stage = "load_manifest"
        manifest = load_manifest()
        versions = manifest_versions(
            manifest, checked_output(["git", "rev-parse", "HEAD"])
        )
        print_context(
            "run_m9_wasm_browser_repeating_timer_dom_smoke.py",
            manifest,
            case=CASE,
            scope=SCOPE,
            gn_args=manifest.get("m6_chrome_gn_args", manifest.get("gn_args")),
            module_name=args.module_name,
            host_browser_sandbox=not args.no_sandbox,
            runtime_arguments=[SWITCH],
        )
        stage = "find_browser"
        browser_path, browser_version = find_browser(args.browser)
        token = secrets.token_urlsafe(24)
        result_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        stage = "create_server"
        server, artifact_identity = create_server(
            "127.0.0.1", 0, out_dir, token, result_queue, module_name=args.module_name
        )
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m9-repeating-timer-server",
            daemon=True,
        )
        server_thread.start()
        url = smoke_url(
            server,
            token,
            versions,
            module_name=args.module_name,
            timeout_seconds=max(1.0, args.timeout - 1.0),
        )
        profile = tempfile.TemporaryDirectory(prefix="chromium-wasm-m9-repeating-timer-")
        stage = "launch_browser"
        command = browser_command(
            browser_path, profile.name, url, no_sandbox=args.no_sandbox
        )
        command[1:1] = ["--enable-logging=stderr"]
        browser = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        assert browser.stderr is not None
        stderr_thread = threading.Thread(
            target=drain_stream,
            args=(browser.stderr, browser_stderr),
            name="chromium-wasm-m9-repeating-timer-browser-stderr",
            daemon=True,
        )
        stderr_thread.start()
        stage = "wait_for_normal_close_result"
        result = wait_for_result(
            browser, browser_stderr, result_queue, time.monotonic() + args.timeout
        )
        stage = "validate_result"
        validate_result(result, expected_versions=versions)
        print(
            f"{SENTINEL}:BROWSER_RESULT "
            + json.dumps(
                {"artifact_snapshot": artifact_identity, "result": result},
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )
        print(f"{SENTINEL}:PASS", flush=True)
        return 0
    except (M0Error, OSError, KeyError, TypeError, ValueError) as exc:
        if browser is not None:
            stop_browser(browser)
        if stderr_thread is not None:
            stderr_thread.join(timeout=1)
        try:
            diagnostic = write_failure_diagnostics(
                diagnostics_dir,
                stage=stage,
                error=exc,
                browser_path=browser_path,
                browser_version=browser_version,
                browser=browser,
                browser_stderr=browser_stderr,
                runtime_result=result,
                artifact_identity=artifact_identity,
            )
            print(
                f"{SENTINEL}:DIAGNOSTICS "
                + json.dumps({"path": str(diagnostic)}),
                file=sys.stderr,
            )
        except (OSError, TypeError, ValueError) as diagnostic_error:
            print(
                f"{SENTINEL}:DIAGNOSTICS_FAIL reason={diagnostic_error}",
                file=sys.stderr,
            )
        print(f"{SENTINEL}:FAIL reason={exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        if browser is not None:
            stop_browser(browser)
        if stderr_thread is not None:
            stderr_thread.join(timeout=1)
        if server is not None:
            server.shutdown()
            server.server_close()
        if server_thread is not None:
            server_thread.join(timeout=1)
        if profile is not None:
            profile.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
