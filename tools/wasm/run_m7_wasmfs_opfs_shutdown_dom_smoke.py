#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the isolated WasmFS/OPFS normal-shutdown smoke in a Worker.

The page starts one dedicated module Worker. That Worker instantiates the
target using the existing PROXY_TO_PTHREAD/EXIT_RUNTIME toolchain settings;
the C++ application returns normally after a bounded OPFS read/write cleanup.
The result is accepted only after the Worker reports native completion plus
onExit(0), a C++ atexit marker ordered after native cleanup, and a
Worker-owned bounded pre-terminal settlement plus a same-turn post-terminal
microtask and self-close protocol exposes errors runnable in that bounded
window. The page's timer/frame heartbeat must stay below a bounded gap through
terminal delivery before it disposes the outer Worker after a self-close
initiation record. A test-only noExitRuntime negative control proves that the
same native completion does not get mistaken for normal teardown: it observes
the still-live Worker for bounded turns, then terminates that Worker explicitly.
This is not a Chrome profile, locking, or recovery test.
"""

from __future__ import annotations

import argparse
from collections import deque
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

from m0_common import M0Error, REPO_ROOT, parse_timeout
from run_browser_smoke import browser_command, drain_stream, find_browser, stop_browser


SENTINEL = "CHROMIUM_WASM_M7_OPFS_SHUTDOWN_DOM"
CASE = "m7_wasmfs_opfs_normal_shutdown"
SCOPE = "isolated-wasmfs-opfs-dedicated-worker-normal-shutdown"
SHUTDOWN_SCOPE = "wasmfs-opfs-backend-cleanup-and-normal-runtime-exit-only"
DEFAULT_OUT_DIR = Path("out/wasm-chrome-m6")
MODULE_NAME = "m7_wasmfs_opfs_shutdown_smoke"
HOST_ROOT = "/__m7_wasmfs_opfs_shutdown_smoke__"
MAX_RESULT_BYTES = 256 * 1024
MAX_OUTPUT_LINES = 128
OPAQUE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
RUNTIME_START_MARKER = (
    "CHROMIUM_WASM_M7_OPFS_SHUTDOWN:RUNTIME_START run_id=redacted"
)
COMPLETION_MARKER = (
    "CHROMIUM_WASM_M7_OPFS_SHUTDOWN:NATIVE_COMPLETE "
    "rw=ok fdatasync=ok close=ok cleanup=ok"
)
ATEXIT_MARKER = "CHROMIUM_WASM_M7_OPFS_ATEXIT:after-native-complete"
FAIL_MARKER = "CHROMIUM_WASM_M7_OPFS_SHUTDOWN:FAIL"
PAGE_HEARTBEAT_ANCHOR = "before-worker-launch-through-terminal"
MAX_PAGE_HEARTBEAT_GAP_MS = 250
POST_EXIT_PAGE_BARRIER_TURNS = 1
PRE_TERMINAL_WORKER_SETTLEMENT_TURNS = 2
NO_EXIT_RUNTIME_WORKER_OBSERVATION_TURNS = 2
NO_EXIT_RUNTIME_PAGE_OBSERVATION_TURNS = 1
TEST_FAULT_DELAYED_POST_TERMINAL_ERROR = "delayed-post-terminal-error"
TEST_FAULT_NO_EXIT_RUNTIME = "no-exit-runtime"
NO_EXIT_RUNTIME_LIFECYCLE = "no-exit-runtime-negative-control"
ADVERSARIAL_DELAYED_POST_TERMINAL_ERROR = (
    "M7 OPFS shutdown adversarial delayed post-terminal error"
)


class M7WasmfsOpfsShutdownServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    out_dir: Path
    result_token: str
    run_namespace: str
    result_queue: queue.Queue[dict[str, Any]]
    result_lock: threading.Lock
    received_result: bool
    html_bytes: bytes
    host_js_bytes: bytes
    worker_js_bytes: bytes


class M7WasmfsOpfsShutdownRequestHandler(BaseHTTPRequestHandler):
    server: M7WasmfsOpfsShutdownServer

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def end_headers(self) -> None:
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def _send_bytes(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self) -> None:
        self._send_bytes(
            HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found\n"
        )

    def _artifact_path(self, name: str) -> Path | None:
        if name not in {f"{MODULE_NAME}.js", f"{MODULE_NAME}.wasm"}:
            return None
        artifact = (self.server.out_dir / name).resolve()
        try:
            artifact.relative_to(self.server.out_dir)
        except ValueError:
            return None
        return artifact if artifact.is_file() else None

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path in (HOST_ROOT, f"{HOST_ROOT}/"):
            self._send_bytes(
                HTTPStatus.OK, "text/html; charset=utf-8", self.server.html_bytes
            )
            return
        if path == f"{HOST_ROOT}/m7_wasmfs_opfs_shutdown_smoke.js":
            self._send_bytes(
                HTTPStatus.OK,
                "text/javascript; charset=utf-8",
                self.server.host_js_bytes,
            )
            return
        if path == f"{HOST_ROOT}/m7_wasmfs_opfs_shutdown_smoke_worker.js":
            self._send_bytes(
                HTTPStatus.OK,
                "text/javascript; charset=utf-8",
                self.server.worker_js_bytes,
            )
            return
        prefix = f"{HOST_ROOT}/artifacts/"
        if path.startswith(prefix):
            artifact = self._artifact_path(path[len(prefix) :])
            if artifact is not None:
                content_type = (
                    "application/wasm"
                    if artifact.suffix == ".wasm"
                    else "text/javascript; charset=utf-8"
                )
                self._send_bytes(HTTPStatus.OK, content_type, artifact.read_bytes())
                return
        self._not_found()

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path != f"{HOST_ROOT}/result/{self.server.result_token}":
            self._not_found()
            return
        try:
            content_length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            content_length = -1
        if content_length < 0 or content_length > MAX_RESULT_BYTES:
            self._send_bytes(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "text/plain; charset=utf-8",
                b"invalid result size\n",
            )
            return
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0]
        if content_type.strip().lower() != "application/json":
            self._send_bytes(
                HTTPStatus.BAD_REQUEST,
                "text/plain; charset=utf-8",
                b"M7 OPFS shutdown result must be JSON\n",
            )
            return
        result = parse_result_payload(
            self.rfile.read(content_length), self.server.run_namespace
        )
        if result is None:
            self._send_bytes(
                HTTPStatus.BAD_REQUEST,
                "text/plain; charset=utf-8",
                b"invalid M7 OPFS shutdown result\n",
            )
            return
        with self.server.result_lock:
            if self.server.received_result:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"duplicate M7 OPFS shutdown result\n",
                )
                return
            self.server.received_result = True
            try:
                self.server.result_queue.put_nowait(result)
            except queue.Full:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"M7 OPFS shutdown result queue is full\n",
                )
                return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()


def _json_object_without_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def redact_opaque_text(value: object, *opaque_values: str | None) -> str:
    redacted = str(value)
    for opaque_value in opaque_values:
        if opaque_value:
            redacted = redacted.replace(opaque_value, "<redacted>")
    return redacted


def redact_opaque_value(value: object, *opaque_values: str | None) -> object:
    if isinstance(value, dict):
        return {
            key: (
                "<redacted>"
                if key in {"runNamespace", "token", "resultToken"}
                else redact_opaque_value(item, *opaque_values)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_opaque_value(item, *opaque_values) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_opaque_value(item, *opaque_values) for item in value)
    if isinstance(value, str):
        return redact_opaque_text(value, *opaque_values)
    return value


def parse_result_payload(
    payload: bytes, expected_run_namespace: str
) -> dict[str, Any] | None:
    try:
        result = json.loads(
            payload.decode("utf-8"), object_pairs_hook=_json_object_without_duplicate_keys
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    if (
        not isinstance(result, dict)
        or type(result.get("protocol")) is not int
        or result.get("protocol") != 1
        or result.get("case") != CASE
        or result.get("scope") != SCOPE
        or result.get("runNamespace") != expected_run_namespace
    ):
        return None
    return result


def create_server(
    host: str,
    port: int,
    out_dir: Path,
    token: str,
    run_namespace: str,
    result_queue: queue.Queue[dict[str, Any]],
) -> M7WasmfsOpfsShutdownServer:
    if not OPAQUE_TOKEN_RE.fullmatch(token) or not OPAQUE_TOKEN_RE.fullmatch(
        run_namespace
    ):
        raise M0Error("M7 OPFS shutdown token or run namespace is invalid")
    if not out_dir.is_dir():
        raise M0Error(f"M7 OPFS shutdown output directory is missing: {out_dir}")
    host_dir = Path(__file__).with_name("host")
    server = M7WasmfsOpfsShutdownServer(
        (host, port), M7WasmfsOpfsShutdownRequestHandler
    )
    server.out_dir = out_dir.resolve()
    server.result_token = token
    server.run_namespace = run_namespace
    server.result_queue = result_queue
    server.result_lock = threading.Lock()
    server.received_result = False
    server.html_bytes = (host_dir / "m7_wasmfs_opfs_shutdown_smoke.html").read_bytes()
    server.host_js_bytes = (host_dir / "m7_wasmfs_opfs_shutdown_smoke.js").read_bytes()
    server.worker_js_bytes = (
        host_dir / "m7_wasmfs_opfs_shutdown_smoke_worker.js"
    ).read_bytes()
    return server


def smoke_url(
    server: M7WasmfsOpfsShutdownServer,
    token: str,
    run_namespace: str,
    *,
    timeout_seconds: float,
    test_fault: str | None = None,
) -> str:
    if token != server.result_token or run_namespace != server.run_namespace:
        raise M0Error("M7 OPFS shutdown URL does not match its server namespace")
    if test_fault not in (
        None,
        TEST_FAULT_DELAYED_POST_TERMINAL_ERROR,
        TEST_FAULT_NO_EXIT_RUNTIME,
    ):
        raise M0Error("M7 OPFS shutdown test fault is invalid")
    host, port = server.server_address[:2]
    query_values = {
        "token": token,
        "run": run_namespace,
        "timeoutMs": str(max(1000, min(180000, int(timeout_seconds * 1000)))),
    }
    if test_fault is not None:
        query_values["testFault"] = test_fault
    query = urlencode(query_values)
    return f"http://{host}:{port}{HOST_ROOT}/?{query}"


def _require_equal(result: dict[str, Any], field: str, expected: object) -> None:
    actual = result.get(field)
    if type(actual) is not type(expected) or actual != expected:
        raise M0Error(
            "M7 OPFS shutdown result "
            f"{field} mismatch: expected {expected!r}, got {actual!r}"
        )


def _require_positive_int(result: dict[str, Any], field: str) -> int:
    value = result.get(field)
    if type(value) is not int or value < 1:
        raise M0Error(f"M7 OPFS shutdown result {field} is invalid")
    return value


def _require_nonnegative_int(result: dict[str, Any], field: str) -> int:
    value = result.get(field)
    if type(value) is not int or value < 0:
        raise M0Error(f"M7 OPFS shutdown result {field} is invalid")
    return value


def _output_lines(snapshot: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for field in ("stdout", "stderr"):
        output = snapshot.get(field)
        if not isinstance(output, list) or len(output) > MAX_OUTPUT_LINES:
            raise M0Error(f"M7 OPFS shutdown runtime {field} is invalid")
        if any(not isinstance(value, str) for value in output):
            raise M0Error(
                f"M7 OPFS shutdown runtime {field} contains a non-string line"
            )
        values.extend(output)
    return values


def _validate_runtime(result: dict[str, Any]) -> None:
    runtime = result.get("runtime")
    if not isinstance(runtime, dict):
        raise M0Error("M7 OPFS shutdown result runtime is invalid")
    for field, expected in {
        "factorySettled": True,
        "runtimeInitialized": True,
        "runtimeExitCode": 0,
        "onExitObserved": True,
        "abort": None,
        "onAbortObserved": False,
        "factoryError": None,
        "workerError": None,
        "workerHosted": True,
        "opfsCapability": True,
        "nativeStartObserved": True,
        "completionObserved": True,
        "completionMarker": COMPLETION_MARKER,
        "completionError": None,
        "atexitObserved": True,
        "atexitMarker": ATEXIT_MARKER,
        "atexitError": None,
        "terminalReason": "on-exit",
        "postExitBarrierObserved": True,
        "postExitBarrierTurns": PRE_TERMINAL_WORKER_SETTLEMENT_TURNS,
        "postExitError": None,
        "noExitRuntimeRequested": False,
        "noExitRuntimeWorkerObservationObserved": False,
        "noExitRuntimeWorkerObservationTurns": 0,
        "runtimeLifecycle": "normal-exit",
    }.items():
        _require_equal(runtime, field, expected)
    output = _output_lines(runtime)
    if (
        RUNTIME_START_MARKER not in output
        or COMPLETION_MARKER not in output
        or ATEXIT_MARKER not in output
    ):
        raise M0Error("M7 OPFS shutdown runtime lacks exact native markers")
    stdout = runtime.get("stdout")
    if not isinstance(stdout, list):
        raise M0Error("M7 OPFS shutdown runtime stdout is invalid")
    if stdout.index(ATEXIT_MARKER) <= stdout.index(COMPLETION_MARKER):
        raise M0Error("M7 OPFS shutdown atexit marker is not after completion")
    if any(FAIL_MARKER in line for line in output):
        raise M0Error("M7 OPFS shutdown native smoke emitted FAIL")
    if type(runtime.get("expectedExitStatusObserved")) is not bool:
        raise M0Error(
            "M7 OPFS shutdown runtime expectedExitStatusObserved is invalid"
        )


def _validate_terminal_page_heartbeat(result: dict[str, Any]) -> None:
    _require_equal(result, "pageHeartbeatAnchor", PAGE_HEARTBEAT_ANCHOR)
    _require_equal(result, "pageHeartbeatGapLimitMs", MAX_PAGE_HEARTBEAT_GAP_MS)
    _require_equal(result, "pageHeartbeatTerminalObserved", True)
    timer_gap = _require_nonnegative_int(result, "pageTimerMaxGapMs")
    frame_gap = _require_nonnegative_int(result, "pageFrameMaxGapMs")
    maximum_gap = _require_nonnegative_int(result, "pageHeartbeatMaxGapMs")
    if maximum_gap != max(timer_gap, frame_gap):
        raise M0Error("M7 OPFS shutdown page heartbeat maximum gap is inconsistent")
    if maximum_gap > MAX_PAGE_HEARTBEAT_GAP_MS:
        raise M0Error("M7 OPFS shutdown page heartbeat exceeded the bounded gap")


def validate_result(
    result: dict[str, Any], *, expected_run_namespace: str, expected_origin: str
) -> None:
    for field, expected in {
        "protocol": 1,
        "case": CASE,
        "scope": SCOPE,
        "shutdownScope": SHUTDOWN_SCOPE,
        "runNamespace": expected_run_namespace,
        "status": "pass",
        "origin": expected_origin,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "opfsCapability": True,
        "opfsFallbackUsed": False,
        "normalRuntimeShutdownProven": True,
        "runtimeLifecycle": "normal-exit",
        "outerPageResponsive": True,
        "workerPreTerminalSettlementObserved": True,
        "workerPreTerminalSettlementTurns": PRE_TERMINAL_WORKER_SETTLEMENT_TURNS,
        "workerPostTerminalMicrotaskObserved": True,
        "workerSelfCloseInitiated": True,
        "workerSelfCloseInitiatedBeforeDisposal": True,
        "postExitPageBarrierObserved": True,
        "postExitPageBarrierTurns": POST_EXIT_PAGE_BARRIER_TURNS,
        "noExitRuntimeNegativeControlProven": False,
        "noExitRuntimeWorkerObservationObserved": False,
        "noExitRuntimeWorkerObservationTurns": 0,
        "noExitRuntimePageObservationObserved": False,
        "noExitRuntimePageObservationTurns": 0,
        "workerTerminationRequested": True,
        "workerTerminationRequestedAfterCleanResult": True,
        "workerTerminationRequestedForNoExitRuntimeControl": False,
        "profilePersistenceProven": False,
        "fileLockSemanticsProven": False,
        "atomicRecoveryProven": False,
        "databaseRecoveryProven": False,
        "failureDiagnostics": None,
        "error": None,
    }.items():
        _require_equal(result, field, expected)
    _require_positive_int(result, "pageTickDelta")
    _require_positive_int(result, "pageFrameDelta")
    _validate_terminal_page_heartbeat(result)
    _validate_runtime(result)


def _validate_no_exit_runtime_negative_control_runtime(
    result: dict[str, Any]
) -> None:
    runtime = result.get("runtime")
    if not isinstance(runtime, dict):
        raise M0Error("M7 OPFS noExitRuntime result runtime is invalid")
    for field, expected in {
        "factorySettled": True,
        "runtimeInitialized": True,
        "runtimeExitCode": None,
        "onExitObserved": False,
        "abort": None,
        "onAbortObserved": False,
        "factoryError": None,
        "workerError": None,
        "workerHosted": True,
        "opfsCapability": True,
        "nativeStartObserved": True,
        "completionObserved": True,
        "completionMarker": COMPLETION_MARKER,
        "completionError": None,
        "atexitObserved": False,
        "atexitMarker": None,
        "atexitError": None,
        "terminalReason": NO_EXIT_RUNTIME_LIFECYCLE,
        "postExitBarrierObserved": False,
        "postExitBarrierTurns": 0,
        "postExitError": None,
        "expectedExitStatusObserved": False,
        "noExitRuntimeRequested": True,
        "noExitRuntimeWorkerObservationObserved": True,
        "noExitRuntimeWorkerObservationTurns": (
            NO_EXIT_RUNTIME_WORKER_OBSERVATION_TURNS
        ),
        "runtimeLifecycle": NO_EXIT_RUNTIME_LIFECYCLE,
    }.items():
        _require_equal(runtime, field, expected)
    output = _output_lines(runtime)
    if RUNTIME_START_MARKER not in output or COMPLETION_MARKER not in output:
        raise M0Error("M7 OPFS noExitRuntime runtime lacks exact native markers")
    if ATEXIT_MARKER in output:
        raise M0Error("M7 OPFS noExitRuntime runtime unexpectedly ran atexit")
    if any(FAIL_MARKER in line for line in output):
        raise M0Error("M7 OPFS noExitRuntime native smoke emitted FAIL")
    stdout = runtime.get("stdout")
    if not isinstance(stdout, list) or COMPLETION_MARKER not in stdout:
        raise M0Error("M7 OPFS noExitRuntime completion marker is not stdout")


def validate_no_exit_runtime_negative_control_result(
    result: dict[str, Any], *, expected_run_namespace: str, expected_origin: str
) -> None:
    """Require the test-only absence of normal Emscripten teardown.

    The outer module factory alone receives noExitRuntime=True. C++ still
    emits its exact completion marker, but the test must observe neither
    onExit nor the native atexit marker before it explicitly terminates the
    retained outer Worker.
    """

    for field, expected in {
        "protocol": 1,
        "case": CASE,
        "scope": SCOPE,
        "shutdownScope": SHUTDOWN_SCOPE,
        "runNamespace": expected_run_namespace,
        "status": "pass",
        "origin": expected_origin,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "opfsCapability": True,
        "opfsFallbackUsed": False,
        "normalRuntimeShutdownProven": False,
        "noExitRuntimeNegativeControlProven": True,
        "runtimeLifecycle": NO_EXIT_RUNTIME_LIFECYCLE,
        "outerPageResponsive": True,
        "workerPreTerminalSettlementObserved": False,
        "workerPreTerminalSettlementTurns": 0,
        "workerPostTerminalMicrotaskObserved": False,
        "workerSelfCloseInitiated": False,
        "workerSelfCloseInitiatedBeforeDisposal": False,
        "postExitPageBarrierObserved": False,
        "postExitPageBarrierTurns": 0,
        "noExitRuntimeWorkerObservationObserved": True,
        "noExitRuntimeWorkerObservationTurns": (
            NO_EXIT_RUNTIME_WORKER_OBSERVATION_TURNS
        ),
        "noExitRuntimePageObservationObserved": True,
        "noExitRuntimePageObservationTurns": NO_EXIT_RUNTIME_PAGE_OBSERVATION_TURNS,
        "workerTerminationRequested": True,
        "workerTerminationRequestedAfterCleanResult": False,
        "workerTerminationRequestedForNoExitRuntimeControl": True,
        "profilePersistenceProven": False,
        "fileLockSemanticsProven": False,
        "atomicRecoveryProven": False,
        "databaseRecoveryProven": False,
        "failureDiagnostics": None,
        "error": None,
    }.items():
        _require_equal(result, field, expected)
    _require_positive_int(result, "pageTickDelta")
    _require_positive_int(result, "pageFrameDelta")
    _validate_terminal_page_heartbeat(result)
    _validate_no_exit_runtime_negative_control_runtime(result)


def _failure_progress_summary(result: dict[str, Any]) -> str:
    diagnostics = result.get("failureDiagnostics")
    if not isinstance(diagnostics, dict):
        return ""
    stage = diagnostics.get("stage")
    if not isinstance(stage, str) or not re.fullmatch(r"[a-z0-9-]{1,64}", stage):
        stage = "invalid"
    runtime = diagnostics.get("runtime")
    lifecycle = runtime.get("runtimeLifecycle") if isinstance(runtime, dict) else None
    return (
        f" [stage={stage} timed_out={diagnostics.get('timedOut') is True}"
        f" worker_created={diagnostics.get('workerCreated') is True}"
        f" terminal_received={diagnostics.get('terminalReceived') is True}"
        f" clean_result_received={diagnostics.get('cleanResultReceived') is True}"
        f" runtime_lifecycle={lifecycle!r}]"
    )


def validate_adversarial_delayed_post_terminal_error_result(
    result: dict[str, Any],
    *,
    expected_run_namespace: str,
    expected_origin: str,
) -> None:
    """Require the test-only delayed error to prevent successful disposal.

    The Worker injects this failure after its normal terminal snapshot and
    before its final self-close confirmation. A pass would prove that the
    bounded Worker-owned post-terminal microtask is not fail-closed.
    """

    for field, expected in {
        "protocol": 1,
        "case": CASE,
        "scope": SCOPE,
        "shutdownScope": SHUTDOWN_SCOPE,
        "runNamespace": expected_run_namespace,
        "status": "fail",
        "origin": expected_origin,
        "normalRuntimeShutdownProven": False,
        "workerPreTerminalSettlementObserved": True,
        "workerPreTerminalSettlementTurns": PRE_TERMINAL_WORKER_SETTLEMENT_TURNS,
        "workerPostTerminalMicrotaskObserved": False,
        "workerSelfCloseInitiated": False,
        "workerSelfCloseInitiatedBeforeDisposal": False,
        "workerTerminationRequested": True,
        "workerTerminationRequestedAfterCleanResult": False,
        "postExitPageBarrierObserved": False,
        "postExitPageBarrierTurns": 0,
    }.items():
        _require_equal(result, field, expected)
    error = result.get("error")
    if (
        not isinstance(error, str)
        or ADVERSARIAL_DELAYED_POST_TERMINAL_ERROR not in error
    ):
        raise M0Error("M7 OPFS shutdown delayed post-terminal error was not surfaced")
    diagnostics = result.get("failureDiagnostics")
    if not isinstance(diagnostics, dict):
        raise M0Error("M7 OPFS shutdown adversarial failure diagnostics are missing")
    for field, expected in {
        "terminalReceived": True,
        "workerPreTerminalSettlementObserved": True,
        "workerPostTerminalMicrotaskObserved": False,
        "workerSelfCloseInitiated": False,
        "workerSelfCloseInitiatedBeforeDisposal": False,
        "workerTerminationRequested": True,
        "workerTerminationRequestedAfterCleanResult": False,
    }.items():
        _require_equal(diagnostics, field, expected)
    worker_error = diagnostics.get("pageWorkerError")
    if (
        not isinstance(worker_error, str)
        or ADVERSARIAL_DELAYED_POST_TERMINAL_ERROR not in worker_error
    ):
        raise M0Error(
            "M7 OPFS shutdown delayed post-terminal Worker error was not retained"
        )


def wait_for_result(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    result_queue: queue.Queue[dict[str, Any]],
    deadline: float,
    *,
    expect_failure: bool = False,
) -> dict[str, Any]:
    while time.monotonic() < deadline:
        try:
            result = result_queue.get_nowait()
        except queue.Empty:
            result = None
        if result is not None:
            if result.get("status") == "fail":
                if expect_failure:
                    return result
                raise M0Error(
                    "M7 OPFS shutdown host reported failure: "
                    + str(result.get("error", "<unspecified>"))
                    + _failure_progress_summary(result)
                )
            if expect_failure:
                raise M0Error(
                    "M7 OPFS shutdown adversarial delayed post-terminal error "
                    "unexpectedly passed"
                )
            return result
        if browser.poll() is not None:
            raise M0Error(
                "host browser exited before M7 OPFS shutdown result: "
                + "\n".join(browser_stderr)
            )
        time.sleep(0.05)
    raise M0Error("M7 OPFS shutdown smoke did not post a result")


def write_failure_diagnostics(
    diagnostics_dir: Path,
    *,
    stage: str,
    error: Exception,
    browser_path: Path | None,
    browser_version: str | None,
    browser: subprocess.Popen[str] | None,
    browser_stderr: deque[str],
    result: dict[str, Any] | None,
    result_token: str | None,
    run_namespace: str | None,
) -> Path:
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / "m7-wasmfs-opfs-shutdown-dom-smoke-failure.json"
    payload = {
        "schema_version": 1,
        "runner": "run_m7_wasmfs_opfs_shutdown_dom_smoke.py",
        "case": CASE,
        "scope": SCOPE,
        "stage": stage,
        "failure": {
            "type": type(error).__name__,
            "message": redact_opaque_text(error, result_token, run_namespace),
        },
        "host_browser": {
            "path": str(browser_path) if browser_path else None,
            "version": browser_version,
            "return_code": browser.poll() if browser else None,
            "stderr_tail": [
                redact_opaque_text(line, result_token, run_namespace)
                for line in browser_stderr
            ],
        },
        "result": redact_opaque_value(result, result_token, run_namespace),
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the isolated WasmFS/OPFS normal-shutdown smoke."
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--diagnostics-dir", type=Path)
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--timeout", type=parse_timeout, default=90.0)
    parser.add_argument(
        "--test-delayed-post-terminal-error",
        action="store_true",
        help=(
            "inject one test-only Worker error after terminal settlement and "
            "require the smoke to reject it before disposal"
        ),
    )
    parser.add_argument(
        "--test-no-exit-runtime",
        action="store_true",
        help=(
            "set noExitRuntime only on the outer Worker factory and require "
            "the bounded, explicitly terminated negative-control result"
        ),
    )
    args = parser.parse_args()
    if args.timeout < 5.0:
        parser.error("--timeout must be at least five seconds")
    if args.test_delayed_post_terminal_error and args.test_no_exit_runtime:
        parser.error(
            "--test-delayed-post-terminal-error and --test-no-exit-runtime "
            "cannot be combined"
        )
    out_dir = args.out_dir if args.out_dir.is_absolute() else REPO_ROOT / args.out_dir
    diagnostics_dir = args.diagnostics_dir or out_dir / "diagnostics"
    if not diagnostics_dir.is_absolute():
        diagnostics_dir = REPO_ROOT / diagnostics_dir

    server: M7WasmfsOpfsShutdownServer | None = None
    server_thread: threading.Thread | None = None
    browser: subprocess.Popen[str] | None = None
    browser_path: Path | None = None
    browser_version: str | None = None
    browser_stderr: deque[str] = deque(maxlen=300)
    stderr_thread: threading.Thread | None = None
    outer_profile: tempfile.TemporaryDirectory[str] | None = None
    result: dict[str, Any] | None = None
    result_token: str | None = None
    run_namespace: str | None = None
    stage = "check-artifacts"

    try:
        for suffix in (".js", ".wasm"):
            if not (out_dir / f"{MODULE_NAME}{suffix}").is_file():
                raise M0Error(
                    f"M7 OPFS shutdown artifact is missing: {MODULE_NAME}{suffix}"
                )
        stage = "find-browser"
        browser_path, browser_version = find_browser(args.browser)
        result_token = secrets.token_urlsafe(24)
        run_namespace = secrets.token_urlsafe(24)
        if result_token == run_namespace:
            raise M0Error(
                "M7 OPFS shutdown result token and run namespace unexpectedly match"
            )
        result_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        stage = "create-server"
        server = create_server(
            "127.0.0.1", 0, out_dir, result_token, run_namespace, result_queue
        )
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m7-wasmfs-opfs-shutdown-server",
            daemon=True,
        )
        server_thread.start()
        url = smoke_url(
            server,
            result_token,
            run_namespace,
            timeout_seconds=max(1.0, args.timeout - 5.0),
            test_fault=(
                TEST_FAULT_DELAYED_POST_TERMINAL_ERROR
                if args.test_delayed_post_terminal_error
                else (
                    TEST_FAULT_NO_EXIT_RUNTIME
                    if args.test_no_exit_runtime
                    else None
                )
            ),
        )
        outer_profile = tempfile.TemporaryDirectory(
            prefix="chromium-wasm-m7-opfs-shutdown-outer-"
        )
        stage = "launch-browser"
        command = browser_command(
            browser_path, outer_profile.name, url, no_sandbox=args.no_sandbox
        )
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
            name="chromium-wasm-m7-wasmfs-opfs-shutdown-browser-stderr",
            daemon=True,
        )
        stderr_thread.start()
        stage = (
            "wait-for-adversarial-post-terminal-result"
            if args.test_delayed_post_terminal_error
            else (
                "wait-for-no-exit-runtime-negative-control-result"
                if args.test_no_exit_runtime
                else "wait-for-normal-shutdown-result"
            )
        )
        result = wait_for_result(
            browser,
            browser_stderr,
            result_queue,
            time.monotonic() + args.timeout,
            expect_failure=args.test_delayed_post_terminal_error,
        )
        expected_origin = f"http://{server.server_address[0]}:{server.server_address[1]}"
        if args.test_delayed_post_terminal_error:
            stage = "validate-adversarial-post-terminal-result"
            validate_adversarial_delayed_post_terminal_error_result(
                result,
                expected_run_namespace=run_namespace,
                expected_origin=expected_origin,
            )
        elif args.test_no_exit_runtime:
            stage = "validate-no-exit-runtime-negative-control-result"
            validate_no_exit_runtime_negative_control_result(
                result,
                expected_run_namespace=run_namespace,
                expected_origin=expected_origin,
            )
        else:
            stage = "validate-normal-shutdown"
            validate_result(
                result,
                expected_run_namespace=run_namespace,
                expected_origin=expected_origin,
            )
        print(
            f"{SENTINEL}:RESULT "
            + json.dumps(
                redact_opaque_value(result, result_token, run_namespace),
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )
        if args.test_delayed_post_terminal_error:
            print(f"{SENTINEL}:ADVERSARIAL_PASS", flush=True)
        elif args.test_no_exit_runtime:
            print(f"{SENTINEL}:NO_EXIT_RUNTIME_NEGATIVE_CONTROL_PASS", flush=True)
        else:
            print(f"{SENTINEL}:PASS", flush=True)
        return 0
    except (M0Error, OSError, TypeError, ValueError) as error:
        if browser is not None:
            stop_browser(browser)
        if stderr_thread is not None:
            stderr_thread.join(timeout=1)
        try:
            diagnostic = write_failure_diagnostics(
                diagnostics_dir,
                stage=stage,
                error=error,
                browser_path=browser_path,
                browser_version=browser_version,
                browser=browser,
                browser_stderr=browser_stderr,
                result=result,
                result_token=result_token,
                run_namespace=run_namespace,
            )
            print(
                f"{SENTINEL}:DIAGNOSTICS " + json.dumps({"path": str(diagnostic)}),
                file=sys.stderr,
            )
        except (OSError, TypeError, ValueError) as diagnostic_error:
            print(
                f"{SENTINEL}:DIAGNOSTICS_FAIL reason={diagnostic_error}",
                file=sys.stderr,
            )
        print(
            f"{SENTINEL}:FAIL reason="
            + redact_opaque_text(error, result_token, run_namespace),
            file=sys.stderr,
            flush=True,
        )
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
        if outer_profile is not None:
            outer_profile.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
