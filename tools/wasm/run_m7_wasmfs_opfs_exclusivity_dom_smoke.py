#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the isolated OPFS SyncAccessHandle writer-exclusivity smoke.

The first same-origin document starts two independent WasmFS Module factories.
The holder retains a writable OPFS descriptor while the contender requires an
EACCES result for its own writable open. Both runtimes intentionally stay live
until a whole-document navigation. A fresh same-origin document then creates a
third Module, proves that the outer teardown released the handle, and removes
the test file. This is not a Chrome profile, SQLite/LevelDB locking, crash
recovery, or graceful WasmFS shutdown test.
"""

from __future__ import annotations

import argparse
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
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


SENTINEL = "CHROMIUM_WASM_M7_OPFS_EXCLUSIVITY_DOM"
CASE = "m7_wasmfs_opfs_writer_exclusivity"
SCOPE = "isolated-wasmfs-opfs-two-live-modules-same-document"
EXCLUSIVITY_SCOPE = "opfs-sync-access-handle-writer-exclusivity-only"
CONTENTION_PHASE = "contention"
REOPEN_PHASE = "reopen"
DEFAULT_OUT_DIR = Path("out/wasm-chrome-m6")
MODULE_NAME = "m7_wasmfs_opfs_exclusivity_smoke"
HOST_ROOT = "/__m7_wasmfs_opfs_exclusivity_smoke__"
MAX_RESULT_BYTES = 256 * 1024
MAX_OUTPUT_LINES = 128
OPAQUE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
MODULE_ID_RE = re.compile(r"^[a-f0-9]{32}$")
HOLDER_ROLE = "holder"
CONTENDER_ROLE = "contender"
REOPEN_ROLE = "reopen"
HOLDER_READY_MARKER = (
    "CHROMIUM_WASM_M7_OPFS_EXCLUSIVITY:HOLDER_READY "
    "access_fd_held=1 fdatasync=ok"
)
CONTENDER_OPEN_BEGIN_MARKER = (
    "CHROMIUM_WASM_M7_OPFS_EXCLUSIVITY:CONTENDER_OPEN_BEGIN mode=O_RDWR"
)
CONTENDER_EACCES_MARKER = (
    "CHROMIUM_WASM_M7_OPFS_EXCLUSIVITY:CONTENDER_EACCES errno=eacces"
)
REOPEN_OK_MARKER = "CHROMIUM_WASM_M7_OPFS_EXCLUSIVITY:REOPEN_OK cleanup=ok"
FAIL_MARKER = "CHROMIUM_WASM_M7_OPFS_EXCLUSIVITY:FAIL"


class M7WasmfsOpfsExclusivityServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    out_dir: Path
    result_token: str
    run_namespace: str
    result_queue: queue.Queue[tuple[str, dict[str, Any]]]
    result_lock: threading.Lock
    received_phases: set[str]
    html_bytes: bytes
    host_js_bytes: bytes


class M7WasmfsOpfsExclusivityRequestHandler(BaseHTTPRequestHandler):
    server: M7WasmfsOpfsExclusivityServer

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
        self._send_bytes(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found\n")

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
        if path == f"{HOST_ROOT}/m7_wasmfs_opfs_exclusivity_smoke.js":
            self._send_bytes(
                HTTPStatus.OK,
                "text/javascript; charset=utf-8",
                self.server.host_js_bytes,
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
        prefix = f"{HOST_ROOT}/result/{self.server.result_token}/"
        if not path.startswith(prefix):
            self._not_found()
            return
        phase = path[len(prefix) :]
        if phase not in (CONTENTION_PHASE, REOPEN_PHASE) or "/" in phase:
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
                b"M7 OPFS exclusivity result must be JSON\n",
            )
            return
        result = parse_result_payload(
            self.rfile.read(content_length), phase, self.server.run_namespace
        )
        if result is None:
            self._send_bytes(
                HTTPStatus.BAD_REQUEST,
                "text/plain; charset=utf-8",
                b"invalid M7 OPFS exclusivity result\n",
            )
            return
        with self.server.result_lock:
            if phase in self.server.received_phases:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"duplicate M7 OPFS exclusivity phase\n",
                )
                return
            self.server.received_phases.add(phase)
            try:
                self.server.result_queue.put_nowait((phase, result))
            except queue.Full:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"M7 OPFS exclusivity result queue is full\n",
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
    """Remove per-run credentials from user-visible output and diagnostics."""

    redacted = str(value)
    for opaque_value in opaque_values:
        if opaque_value:
            redacted = redacted.replace(opaque_value, "<redacted>")
    return redacted


def redact_opaque_value(value: object, *opaque_values: str | None) -> object:
    """Return a diagnostic-safe copy without changing the trusted result."""

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
    payload: bytes, phase: str, expected_run_namespace: str
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
        or result.get("phase") != phase
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
    result_queue: queue.Queue[tuple[str, dict[str, Any]]],
) -> M7WasmfsOpfsExclusivityServer:
    if not OPAQUE_TOKEN_RE.fullmatch(token) or not OPAQUE_TOKEN_RE.fullmatch(
        run_namespace
    ):
        raise M0Error("M7 OPFS exclusivity token or run namespace is invalid")
    if not out_dir.is_dir():
        raise M0Error(f"M7 OPFS exclusivity output directory is missing: {out_dir}")
    host_dir = Path(__file__).with_name("host")
    server = M7WasmfsOpfsExclusivityServer(
        (host, port), M7WasmfsOpfsExclusivityRequestHandler
    )
    server.out_dir = out_dir.resolve()
    server.result_token = token
    server.run_namespace = run_namespace
    server.result_queue = result_queue
    server.result_lock = threading.Lock()
    server.received_phases = set()
    server.html_bytes = (
        host_dir / "m7_wasmfs_opfs_exclusivity_smoke.html"
    ).read_bytes()
    server.host_js_bytes = (
        host_dir / "m7_wasmfs_opfs_exclusivity_smoke.js"
    ).read_bytes()
    return server


def smoke_url(
    server: M7WasmfsOpfsExclusivityServer,
    token: str,
    run_namespace: str,
    *,
    timeout_seconds: float,
) -> str:
    if token != server.result_token or run_namespace != server.run_namespace:
        raise M0Error("M7 OPFS exclusivity URL does not match its server namespace")
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "token": token,
            "phase": CONTENTION_PHASE,
            "run": run_namespace,
            "timeoutMs": str(max(1000, min(180000, int(timeout_seconds * 1000)))),
        }
    )
    return f"http://{host}:{port}{HOST_ROOT}/?{query}"


def _require_equal(result: dict[str, Any], field: str, expected: object) -> None:
    actual = result.get(field)
    if type(actual) is not type(expected) or actual != expected:
        raise M0Error(
            "M7 OPFS exclusivity "
            f"{result.get('phase', '<unknown>')} result {field} mismatch: "
            f"expected {expected!r}, got {actual!r}"
        )


def _require_positive_number(result: dict[str, Any], field: str) -> float:
    value = result.get(field)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise M0Error(f"M7 OPFS exclusivity result {field} is invalid")
    return float(value)


def _require_module_identity(value: object, field: str) -> str:
    if not isinstance(value, str) or not MODULE_ID_RE.fullmatch(value):
        raise M0Error(f"M7 OPFS exclusivity result {field} is invalid")
    return value


def _output_lines(result: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for field in ("stdout", "stderr"):
        output = result.get(field)
        if not isinstance(output, list) or len(output) > MAX_OUTPUT_LINES:
            raise M0Error(f"M7 OPFS exclusivity result {field} is invalid")
        if any(not isinstance(value, str) for value in output):
            raise M0Error(
                f"M7 OPFS exclusivity result {field} contains a non-string line"
            )
        values.extend(output)
    return values


def _require_exact_output(result: dict[str, Any], marker: str) -> None:
    values = _output_lines(result)
    if marker not in values:
        raise M0Error(f"M7 OPFS exclusivity output is missing exact {marker}")
    if any(FAIL_MARKER in line for line in values):
        raise M0Error("M7 OPFS exclusivity native smoke emitted FAIL")


def _require_runtime_snapshot(
    result: dict[str, Any], field: str, role: str, marker: str
) -> dict[str, Any]:
    snapshot = result.get(field)
    if not isinstance(snapshot, dict):
        raise M0Error(f"M7 OPFS exclusivity result {field} is invalid")
    for snapshot_field, expected in {
        "role": role,
        "factorySettled": True,
        "runtimeInitialized": True,
        "runtimeExitCode": None,
        "abort": None,
        "completionObserved": True,
        "completionMarker": marker,
        "factoryError": None,
        "completionError": None,
        "nativeStartObserved": True,
        "contenderOpenBeginObserved": role == CONTENDER_ROLE,
        "runtimeLifecycle": "live-runtime",
    }.items():
        _require_equal(snapshot, snapshot_field, expected)
    _require_module_identity(snapshot.get("moduleIdentity"), f"{field}.moduleIdentity")
    _require_exact_output(snapshot, marker)
    return snapshot


def _validate_common_result(
    result: dict[str, Any], *, expected_phase: str, expected_run_namespace: str,
    expected_origin: str
) -> None:
    for field, expected in {
        "protocol": 1,
        "case": CASE,
        "scope": SCOPE,
        "phase": expected_phase,
        "runNamespace": expected_run_namespace,
        "status": "pass",
        "origin": expected_origin,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "opfsCapability": True,
        "opfsFallbackUsed": False,
        "exclusivityScope": EXCLUSIVITY_SCOPE,
        "sqliteLeveldbLockSemanticsProven": False,
        "atomicRecoveryProven": False,
        "gracefulRuntimeShutdownProven": False,
        "teardownMode": "outer-document",
        "failureDiagnostics": None,
        "error": None,
    }.items():
        _require_equal(result, field, expected)
    _require_positive_number(result, "timeOrigin")


def validate_contention_result(
    result: dict[str, Any], *, expected_run_namespace: str, expected_origin: str
) -> None:
    _validate_common_result(
        result,
        expected_phase=CONTENTION_PHASE,
        expected_run_namespace=expected_run_namespace,
        expected_origin=expected_origin,
    )
    for field, expected in {
        "syncAccessHandleWriterExclusivityProven": True,
        "independentModuleInstancesProven": True,
        "holderLiveAfterContender": True,
        "releaseAfterOuterDocumentTeardownProven": False,
        "outerReload": False,
        "priorTimeOrigin": None,
        "priorHolderModuleIdentity": None,
        "priorContenderModuleIdentity": None,
        "freshOuterDocument": False,
        "reopen": None,
    }.items():
        _require_equal(result, field, expected)
    holder = _require_runtime_snapshot(
        result, "holder", HOLDER_ROLE, HOLDER_READY_MARKER
    )
    contender = _require_runtime_snapshot(
        result, "contender", CONTENDER_ROLE, CONTENDER_EACCES_MARKER
    )
    if CONTENDER_OPEN_BEGIN_MARKER not in _output_lines(contender):
        raise M0Error("M7 OPFS contender did not reach its direct writable open")
    if holder["moduleIdentity"] == contender["moduleIdentity"]:
        raise M0Error("M7 OPFS holder and contender Module identities match")


def validate_reopen_result(
    result: dict[str, Any], *, expected_run_namespace: str, expected_origin: str
) -> None:
    _validate_common_result(
        result,
        expected_phase=REOPEN_PHASE,
        expected_run_namespace=expected_run_namespace,
        expected_origin=expected_origin,
    )
    for field, expected in {
        "syncAccessHandleWriterExclusivityProven": False,
        "independentModuleInstancesProven": False,
        "holderLiveAfterContender": False,
        "releaseAfterOuterDocumentTeardownProven": True,
        "outerReload": True,
        "holder": None,
        "contender": None,
        "freshOuterDocument": True,
    }.items():
        _require_equal(result, field, expected)
    _require_positive_number(result, "priorTimeOrigin")
    _require_module_identity(
        result.get("priorHolderModuleIdentity"), "priorHolderModuleIdentity"
    )
    _require_module_identity(
        result.get("priorContenderModuleIdentity"), "priorContenderModuleIdentity"
    )
    reopen = _require_runtime_snapshot(result, "reopen", REOPEN_ROLE, REOPEN_OK_MARKER)
    if reopen["moduleIdentity"] in {
        result["priorHolderModuleIdentity"],
        result["priorContenderModuleIdentity"],
    }:
        raise M0Error("M7 OPFS reopen Module identity reused a contention Module")


def validate_result_pair(
    contention_result: dict[str, Any],
    reopen_result: dict[str, Any],
    *,
    expected_run_namespace: str,
    expected_origin: str,
) -> None:
    validate_contention_result(
        contention_result,
        expected_run_namespace=expected_run_namespace,
        expected_origin=expected_origin,
    )
    validate_reopen_result(
        reopen_result,
        expected_run_namespace=expected_run_namespace,
        expected_origin=expected_origin,
    )
    contention_time_origin = _require_positive_number(contention_result, "timeOrigin")
    reopen_time_origin = _require_positive_number(reopen_result, "timeOrigin")
    if reopen_time_origin <= contention_time_origin:
        raise M0Error("M7 OPFS reopen did not receive a newer document time origin")
    if reopen_result.get("priorTimeOrigin") != contention_result.get("timeOrigin"):
        raise M0Error("M7 OPFS reopen did not preserve contention time origin")
    holder = contention_result["holder"]
    contender = contention_result["contender"]
    assert isinstance(holder, dict)
    assert isinstance(contender, dict)
    if reopen_result.get("priorHolderModuleIdentity") != holder.get("moduleIdentity"):
        raise M0Error("M7 OPFS reopen did not preserve holder Module identity")
    if reopen_result.get("priorContenderModuleIdentity") != contender.get(
        "moduleIdentity"
    ):
        raise M0Error("M7 OPFS reopen did not preserve contender Module identity")
    if reopen_result.get("origin") != contention_result.get("origin"):
        raise M0Error("M7 OPFS phases did not remain same-origin")


def _drain_results(
    result_queue: queue.Queue[tuple[str, dict[str, Any]]],
    results: dict[str, dict[str, Any]],
) -> None:
    while True:
        try:
            phase, result = result_queue.get_nowait()
        except queue.Empty:
            return
        if phase in results:
            raise M0Error(f"M7 OPFS exclusivity phase result was duplicated: {phase}")
        results[phase] = result


def _failure_progress_summary(result: dict[str, Any]) -> str:
    diagnostics = result.get("failureDiagnostics")
    if not isinstance(diagnostics, dict):
        return ""
    stage = diagnostics.get("stage")
    if not isinstance(stage, str) or not re.fullmatch(r"[a-z0-9-]{1,64}", stage):
        stage = "invalid"
    timed_out = diagnostics.get("timedOut") is True
    opfs_capability = result.get("opfsCapability") is True
    holder_registered = diagnostics.get("holderRegistered") is True
    contender_registered = diagnostics.get("contenderRegistered") is True
    reopen_registered = diagnostics.get("reopenRegistered") is True
    holder_native_start = diagnostics.get("holderNativeStartObserved") is True
    holder_ready = diagnostics.get("holderReadyObserved") is True
    contender_native_start = (
        diagnostics.get("contenderNativeStartObserved") is True
    )
    contender_open_begin = diagnostics.get("contenderOpenBeginObserved") is True
    contender_eacces = diagnostics.get("contenderEaccesObserved") is True
    reopen_native_start = diagnostics.get("reopenNativeStartObserved") is True
    reopen_ok = diagnostics.get("reopenOkObserved") is True
    return (
        " [stage="
        + stage
        + f" timed_out={timed_out} opfs_capability={opfs_capability}"
        + f" holder_registered={holder_registered}"
        + f" holder_native_start={holder_native_start} holder_ready={holder_ready}"
        + f" contender_registered={contender_registered}"
        + f" contender_native_start={contender_native_start}"
        + f" contender_open_begin={contender_open_begin}"
        + f" contender_eacces={contender_eacces}"
        + f" reopen_registered={reopen_registered}"
        + f" reopen_native_start={reopen_native_start} reopen_ok={reopen_ok}]"
    )


def wait_for_result_pair(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    result_queue: queue.Queue[tuple[str, dict[str, Any]]],
    deadline: float,
    results: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    while time.monotonic() < deadline:
        _drain_results(result_queue, results)
        for phase, result in results.items():
            if result.get("status") == "fail":
                raise M0Error(
                    "M7 OPFS exclusivity "
                    + phase
                    + " host reported failure: "
                    + str(result.get("error", "<unspecified>"))
                    + _failure_progress_summary(result)
                )
        if CONTENTION_PHASE in results and REOPEN_PHASE in results:
            return results
        if browser.poll() is not None:
            raise M0Error(
                "host browser exited before both M7 OPFS exclusivity results: "
                + "\n".join(browser_stderr)
            )
        time.sleep(0.05)
    raise M0Error("M7 OPFS exclusivity smoke did not post both phase results")


def write_failure_diagnostics(
    diagnostics_dir: Path,
    *,
    stage: str,
    error: Exception,
    browser_path: Path | None,
    browser_version: str | None,
    browser: subprocess.Popen[str] | None,
    browser_stderr: deque[str],
    results: dict[str, dict[str, Any]],
    result_token: str | None,
    run_namespace: str | None,
) -> Path:
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / "m7-wasmfs-opfs-exclusivity-dom-smoke-failure.json"
    payload = {
        "schema_version": 1,
        "runner": "run_m7_wasmfs_opfs_exclusivity_dom_smoke.py",
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
        "results": redact_opaque_value(results, result_token, run_namespace),
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the isolated OPFS writer-exclusivity WasmFS smoke."
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--diagnostics-dir", type=Path)
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--timeout", type=parse_timeout, default=90.0)
    args = parser.parse_args()
    if args.timeout < 5.0:
        parser.error("--timeout must be at least five seconds")
    out_dir = args.out_dir if args.out_dir.is_absolute() else REPO_ROOT / args.out_dir
    diagnostics_dir = args.diagnostics_dir or out_dir / "diagnostics"
    if not diagnostics_dir.is_absolute():
        diagnostics_dir = REPO_ROOT / diagnostics_dir
    server: M7WasmfsOpfsExclusivityServer | None = None
    server_thread: threading.Thread | None = None
    browser: subprocess.Popen[str] | None = None
    browser_path: Path | None = None
    browser_version: str | None = None
    browser_stderr: deque[str] = deque(maxlen=300)
    stderr_thread: threading.Thread | None = None
    outer_profile: tempfile.TemporaryDirectory[str] | None = None
    results: dict[str, dict[str, Any]] = {}
    result_token: str | None = None
    run_namespace: str | None = None
    stage = "check_artifacts"

    try:
        for suffix in (".js", ".wasm"):
            if not (out_dir / f"{MODULE_NAME}{suffix}").is_file():
                raise M0Error(
                    f"M7 OPFS exclusivity artifact is missing: {MODULE_NAME}{suffix}"
                )
        stage = "find_browser"
        browser_path, browser_version = find_browser(args.browser)
        result_token = secrets.token_urlsafe(24)
        run_namespace = secrets.token_urlsafe(24)
        if result_token == run_namespace:
            raise M0Error(
                "M7 OPFS exclusivity result token and run namespace unexpectedly match"
            )
        result_queue: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue(maxsize=2)
        stage = "create_server"
        server = create_server(
            "127.0.0.1",
            0,
            out_dir,
            result_token,
            run_namespace,
            result_queue,
        )
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m7-wasmfs-opfs-exclusivity-server",
            daemon=True,
        )
        server_thread.start()
        url = smoke_url(
            server,
            result_token,
            run_namespace,
            timeout_seconds=max(1.0, args.timeout - 5.0),
        )
        outer_profile = tempfile.TemporaryDirectory(
            prefix="chromium-wasm-m7-opfs-exclusivity-outer-"
        )
        stage = "launch_browser"
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
            name="chromium-wasm-m7-wasmfs-opfs-exclusivity-browser-stderr",
            daemon=True,
        )
        stderr_thread.start()
        deadline = time.monotonic() + args.timeout
        stage = "wait_for_contention_and_reopen_results"
        results = wait_for_result_pair(
            browser, browser_stderr, result_queue, deadline, results
        )
        expected_origin = f"http://{server.server_address[0]}:{server.server_address[1]}"
        stage = "validate_writer_exclusivity"
        validate_result_pair(
            results[CONTENTION_PHASE],
            results[REOPEN_PHASE],
            expected_run_namespace=run_namespace,
            expected_origin=expected_origin,
        )
        print(
            f"{SENTINEL}:RESULT "
            + json.dumps(
                redact_opaque_value(results, result_token, run_namespace),
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )
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
                results=results,
                result_token=result_token,
                run_namespace=run_namespace,
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
