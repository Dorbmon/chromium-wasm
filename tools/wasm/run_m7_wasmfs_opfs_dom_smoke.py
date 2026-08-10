#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the isolated two-document WasmFS/OPFS persistence feasibility smoke.

The host page never reads or writes OPFS. It starts a dedicated Wasm executable
with an opaque per-run namespace, waits for its exact native PASS marker while
the target retains a live runtime, and then performs a full same-origin
`location.replace()` into a new document. That outer document teardown is
intentional and is not an orderly WasmFS/backend/thread shutdown claim. The
new document creates a new Emscripten Module and verifies only primitive
durable filesystem behavior. This is deliberately not a Chrome profile mount,
database recovery, or file-locking claim.
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


SENTINEL = "CHROMIUM_WASM_M7_WASMFS_OPFS_DOM"
CASE = "m7_wasmfs_opfs_outer_reload"
SCOPE = "isolated-wasmfs-opfs-two-document-same-origin"
PERSISTENCE_SCOPE = "primitive-opfs-persistence-only"
WRITE_PHASE = "write"
VERIFY_PHASE = "verify"
DEFAULT_OUT_DIR = Path("out/wasm-chrome-m6")
MODULE_NAME = "m7_wasmfs_opfs_smoke"
HOST_ROOT = "/__m7_wasmfs_opfs_smoke__"
MAX_RESULT_BYTES = 256 * 1024
MAX_OUTPUT_LINES = 128
OPAQUE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
MODULE_ID_RE = re.compile(r"^[a-f0-9]{32}$")
WRITE_READY_MARKER = "CHROMIUM_WASM_M7_OPFS:WRITE_READY"
VERIFY_STARTED_MARKER = "CHROMIUM_WASM_M7_OPFS:VERIFY_STARTED"
PASS_MARKER = "CHROMIUM_WASM_M7_OPFS:PASS"
FAIL_MARKER = "CHROMIUM_WASM_M7_OPFS:FAIL"


class M7WasmfsOpfsSmokeServer(ThreadingHTTPServer):
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


class M7WasmfsOpfsSmokeRequestHandler(BaseHTTPRequestHandler):
    server: M7WasmfsOpfsSmokeServer

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
        if name not in {
            f"{MODULE_NAME}.js",
            f"{MODULE_NAME}.wasm",
        }:
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
        if path == f"{HOST_ROOT}/m7_wasmfs_opfs_smoke.js":
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
        if phase not in (WRITE_PHASE, VERIFY_PHASE) or "/" in phase:
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
                b"M7 OPFS result must be JSON\n",
            )
            return
        result = parse_result_payload(
            self.rfile.read(content_length), phase, self.server.run_namespace
        )
        if result is None:
            self._send_bytes(
                HTTPStatus.BAD_REQUEST,
                "text/plain; charset=utf-8",
                b"invalid M7 OPFS result\n",
            )
            return
        with self.server.result_lock:
            if phase in self.server.received_phases:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"duplicate M7 OPFS phase\n",
                )
                return
            self.server.received_phases.add(phase)
            try:
                self.server.result_queue.put_nowait((phase, result))
            except queue.Full:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"M7 OPFS result queue is full\n",
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


def redact_opaque_value(
    value: object, *opaque_values: str | None
) -> object:
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
) -> M7WasmfsOpfsSmokeServer:
    if not OPAQUE_TOKEN_RE.fullmatch(token) or not OPAQUE_TOKEN_RE.fullmatch(
        run_namespace
    ):
        raise M0Error("M7 OPFS token or run namespace is invalid")
    if not out_dir.is_dir():
        raise M0Error(f"M7 OPFS output directory is missing: {out_dir}")
    host_dir = Path(__file__).with_name("host")
    server = M7WasmfsOpfsSmokeServer((host, port), M7WasmfsOpfsSmokeRequestHandler)
    server.out_dir = out_dir.resolve()
    server.result_token = token
    server.run_namespace = run_namespace
    server.result_queue = result_queue
    server.result_lock = threading.Lock()
    server.received_phases = set()
    server.html_bytes = (host_dir / "m7_wasmfs_opfs_smoke.html").read_bytes()
    server.host_js_bytes = (host_dir / "m7_wasmfs_opfs_smoke.js").read_bytes()
    return server


def smoke_url(
    server: M7WasmfsOpfsSmokeServer,
    token: str,
    run_namespace: str,
    *,
    timeout_seconds: float,
) -> str:
    if token != server.result_token or run_namespace != server.run_namespace:
        raise M0Error("M7 OPFS URL does not match its server-bound namespace")
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "token": token,
            "phase": WRITE_PHASE,
            "run": run_namespace,
            "timeoutMs": str(max(1000, min(180000, int(timeout_seconds * 1000)))),
        }
    )
    return f"http://{host}:{port}{HOST_ROOT}/?{query}"


def _require_equal(result: dict[str, Any], field: str, expected: object) -> None:
    actual = result.get(field)
    if type(actual) is not type(expected) or actual != expected:
        raise M0Error(
            f"M7 OPFS {result.get('phase', '<unknown>')} result {field} mismatch: "
            f"expected {expected!r}, got {actual!r}"
        )


def _output_lines(result: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for field in ("stdout", "stderr"):
        output = result.get(field)
        if not isinstance(output, list) or len(output) > MAX_OUTPUT_LINES:
            raise M0Error(f"M7 OPFS result {field} is invalid")
        if any(not isinstance(value, str) for value in output):
            raise M0Error(f"M7 OPFS result {field} contains a non-string line")
        values.extend(output)
    return values


def _require_output(result: dict[str, Any], marker: str) -> None:
    values = _output_lines(result)
    if not any(marker in line for line in values):
        raise M0Error(f"M7 OPFS output is missing {marker}")
    if any(FAIL_MARKER in line for line in values):
        raise M0Error("M7 OPFS native smoke emitted FAIL")


def _require_exact_output(result: dict[str, Any], marker: str) -> None:
    values = _output_lines(result)
    if marker not in values:
        raise M0Error(f"M7 OPFS output is missing exact {marker}")
    if any(FAIL_MARKER in line for line in values):
        raise M0Error("M7 OPFS native smoke emitted FAIL")


def _require_positive_number(result: dict[str, Any], field: str) -> float:
    value = result.get(field)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise M0Error(f"M7 OPFS result {field} is invalid")
    return float(value)


def validate_phase_result(
    result: dict[str, Any],
    *,
    expected_phase: str,
    expected_run_namespace: str,
    expected_origin: str,
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
        "persistenceScope": PERSISTENCE_SCOPE,
        "fileLockSemanticsProven": False,
        "concurrentAccessHandleSemanticsProven": False,
        # The target intentionally uses emscripten_exit_with_live_runtime()
        # after PASS. A location.replace() of this isolated document is the
        # teardown boundary; normal exit/atexit/global destructor behavior is
        # deliberately not exercised or claimed here.
        "runtimeExitCode": None,
        "completionObserved": True,
        "completionMarker": f"{PASS_MARKER} phase={expected_phase}",
        "runtimeLifecycle": "live-runtime",
        "teardownMode": "outer-document",
        "runtimeInitialized": True,
        "factorySettled": True,
        "abort": None,
        "error": None,
    }.items():
        _require_equal(result, field, expected)
    _require_positive_number(result, "timeOrigin")
    module_identity = result.get("moduleIdentity")
    if not isinstance(module_identity, str) or not MODULE_ID_RE.fullmatch(module_identity):
        raise M0Error("M7 OPFS result Module identity is invalid")
    if expected_phase == WRITE_PHASE:
        _require_equal(result, "outerReload", False)
        _require_equal(result, "priorTimeOrigin", None)
        _require_equal(result, "priorModuleIdentity", None)
        _require_equal(result, "freshOuterDocument", False)
        _require_equal(result, "freshModuleIdentity", False)
        _require_output(result, WRITE_READY_MARKER)
    else:
        _require_equal(result, "outerReload", True)
        _require_equal(result, "freshOuterDocument", True)
        _require_equal(result, "freshModuleIdentity", True)
        _require_positive_number(result, "priorTimeOrigin")
        prior_module_identity = result.get("priorModuleIdentity")
        if not isinstance(prior_module_identity, str) or not MODULE_ID_RE.fullmatch(
            prior_module_identity
        ):
            raise M0Error("M7 OPFS verify result prior Module identity is invalid")
        _require_output(result, VERIFY_STARTED_MARKER)
    _require_exact_output(result, f"{PASS_MARKER} phase={expected_phase}")


def validate_result_pair(
    write_result: dict[str, Any],
    verify_result: dict[str, Any],
    *,
    expected_run_namespace: str,
    expected_origin: str,
) -> None:
    validate_phase_result(
        write_result,
        expected_phase=WRITE_PHASE,
        expected_run_namespace=expected_run_namespace,
        expected_origin=expected_origin,
    )
    validate_phase_result(
        verify_result,
        expected_phase=VERIFY_PHASE,
        expected_run_namespace=expected_run_namespace,
        expected_origin=expected_origin,
    )
    write_time_origin = _require_positive_number(write_result, "timeOrigin")
    verify_time_origin = _require_positive_number(verify_result, "timeOrigin")
    if verify_time_origin <= write_time_origin:
        raise M0Error("M7 OPFS verify did not receive a newer document time origin")
    if verify_result.get("priorTimeOrigin") != write_result.get("timeOrigin"):
        raise M0Error("M7 OPFS verify did not preserve the write document time origin")
    if verify_result.get("priorModuleIdentity") != write_result.get("moduleIdentity"):
        raise M0Error("M7 OPFS verify did not preserve the write Module identity")
    if verify_result.get("moduleIdentity") == write_result.get("moduleIdentity"):
        raise M0Error("M7 OPFS verify reused the write Module identity")
    if verify_result.get("origin") != write_result.get("origin"):
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
            raise M0Error(f"M7 OPFS phase result was duplicated: {phase}")
        results[phase] = result


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
                    "M7 OPFS "
                    + phase
                    + " host reported failure: "
                    + str(result.get("error", "<unspecified>"))
                )
        if WRITE_PHASE in results and VERIFY_PHASE in results:
            return results
        if browser.poll() is not None:
            raise M0Error(
                "host browser exited before both M7 OPFS results: "
                + "\n".join(browser_stderr)
            )
        time.sleep(0.05)
    raise M0Error("M7 OPFS smoke did not post both outer-document phase results")


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
    path = diagnostics_dir / "m7-wasmfs-opfs-dom-smoke-failure.json"
    payload = {
        "schema_version": 1,
        "runner": "run_m7_wasmfs_opfs_dom_smoke.py",
        "case": CASE,
        "scope": SCOPE,
        "stage": stage,
        "failure": {
            "type": type(error).__name__,
            "message": redact_opaque_text(
                error, result_token, run_namespace
            ),
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
        description="Run the isolated two-document WasmFS/OPFS persistence smoke."
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
    server: M7WasmfsOpfsSmokeServer | None = None
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
                raise M0Error(f"M7 OPFS artifact is missing: {MODULE_NAME}{suffix}")
        stage = "find_browser"
        browser_path, browser_version = find_browser(args.browser)
        result_token = secrets.token_urlsafe(24)
        run_namespace = secrets.token_urlsafe(24)
        if result_token == run_namespace:
            raise M0Error("M7 OPFS result token and run namespace unexpectedly match")
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
            name="chromium-wasm-m7-wasmfs-opfs-server",
            daemon=True,
        )
        server_thread.start()
        url = smoke_url(
            server,
            result_token,
            run_namespace,
            # Leave the runner enough time to receive and preserve a terminal
            # host result after the page-level runtime watchdog fires.
            timeout_seconds=max(1.0, args.timeout - 5.0),
        )
        outer_profile = tempfile.TemporaryDirectory(prefix="chromium-wasm-m7-opfs-outer-")
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
            name="chromium-wasm-m7-wasmfs-opfs-browser-stderr",
            daemon=True,
        )
        stderr_thread.start()
        deadline = time.monotonic() + args.timeout
        stage = "wait_for_outer_reload_results"
        results = wait_for_result_pair(
            browser, browser_stderr, result_queue, deadline, results
        )
        expected_origin = f"http://{server.server_address[0]}:{server.server_address[1]}"
        stage = "validate_two_document_persistence"
        validate_result_pair(
            results[WRITE_PHASE],
            results[VERIFY_PHASE],
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
    sys.exit(main())
