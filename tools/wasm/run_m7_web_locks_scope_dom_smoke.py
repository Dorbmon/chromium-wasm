#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the isolated same-top-level-document Web Locks probe.

This host-only probe verifies named Web Locks contention and lifetime in the
outer browser's current storage bucket. It intentionally does not infer
origin-wide/cross-document coordination, load Wasm, touch OPFS, or claim
SQLite, LevelDB, profile persistence, or recovery semantics.
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


SENTINEL = "CHROMIUM_WASM_M7_WEB_LOCKS_SCOPE_DOM"
CASE = "m7_web_locks_scope"
SCOPE = (
    "isolated-host-web-locks-same-top-level-document-sibling-dedicated-workers-only"
)
HOST_ROOT = "/__m7_web_locks_scope__"
MAX_RESULT_BYTES = 64 * 1024
MAX_TRACE_EVENTS = 32
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
ORDER_FIELDS = (
    "holderExplicitHeld",
    "contenderIfAvailable",
    "contenderExplicitQueued",
    "contenderExplicitBlocked",
    "explicitReleaseCommand",
    "holderExplicitReleased",
    "contenderExplicitGranted",
    "contenderExplicitReleased",
    "holderTerminationHeld",
    "contenderTerminationQueued",
    "contenderTerminationBlocked",
    "holderTerminationCommand",
    "contenderTerminationGranted",
    "contenderTerminationReleased",
)
ORDER_MARKERS = {
    "holderExplicitHeld": "holder:held:explicit",
    "contenderIfAvailable": "contender:if_available:explicit",
    "contenderExplicitQueued": "contender:wait_queued:explicit",
    "contenderExplicitBlocked": "contender:state:explicit",
    "explicitReleaseCommand": "parent:explicit-release-command",
    "holderExplicitReleased": "holder:released:explicit",
    "contenderExplicitGranted": "contender:held:explicit",
    "contenderExplicitReleased": "contender:released:explicit",
    "holderTerminationHeld": "holder:held:termination",
    "contenderTerminationQueued": "contender:wait_queued:termination",
    "contenderTerminationBlocked": "contender:state:termination",
    "holderTerminationCommand": "parent:holder-termination-command",
    "contenderTerminationGranted": "contender:held:termination",
    "contenderTerminationReleased": "contender:released:termination",
}
EXPECTED_TRACE_MARKERS = {
    "holder:ready",
    "contender:ready",
    *ORDER_MARKERS.values(),
}
TRACE_MARKER_RE = re.compile(
    r"^(?:(?:holder|contender):ready|"
    r"(?:holder|contender):(?:held|if_available|wait_queued|state|released):"
    r"(?:explicit|termination)|"
    r"parent:(?:explicit-release-command|holder-termination-command))$"
)
RESULT_FIELDS = frozenset(
    {
        "protocol",
        "case",
        "scope",
        "status",
        "runNamespace",
        "origin",
        "secureContext",
        "crossOriginIsolated",
        "sharedArrayBuffer",
        "sameTopLevelDocumentSiblingDedicatedWorkersProven",
        "holderWorkerWebLocksAvailable",
        "contenderWorkerWebLocksAvailable",
        "ifAvailableReturnedNull",
        "contenderPendingBeforeExplicitRelease",
        "explicitReleaseQueuedGrantProven",
        "contenderPendingBeforeHolderTermination",
        "holderTerminationQueuedGrantProven",
        "holderWorkerTerminated",
        "webLocksScopeLimitation",
        "terminationReacquisitionLimitation",
        "workerEventTrace",
        "eventOrder",
        "opfsTouched",
        "syncAccessHandleCoordinated",
        "syncAccessHandleWriterExclusivityProven",
        "posixFcntlLocksProven",
        "byteRangeLocksProven",
        "sqliteLeveldbLockSemanticsProven",
        "profilePersistenceProven",
        "atomicRecoveryProven",
        "crashRecoveryProven",
        "gracefulRuntimeShutdownProven",
        "gracefulProfileShutdownProven",
        "m7GateComplete",
        "failureDiagnostics",
        "error",
    }
)


class WebLocksScopeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    result_token: str
    run_namespace: str
    result_queue: queue.Queue[dict[str, Any]]
    result_lock: threading.Lock
    result_received: bool
    html_bytes: bytes
    host_js_bytes: bytes
    worker_js_bytes: bytes


class WebLocksScopeRequestHandler(BaseHTTPRequestHandler):
    server: WebLocksScopeServer

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def end_headers(self) -> None:
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def send_bytes(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def not_found(self) -> None:
        self.send_bytes(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found\n")

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path in (HOST_ROOT, f"{HOST_ROOT}/"):
            self.send_bytes(
                HTTPStatus.OK, "text/html; charset=utf-8", self.server.html_bytes
            )
            return
        assets = {
            f"{HOST_ROOT}/m7_web_locks_scope_smoke.js": self.server.host_js_bytes,
            f"{HOST_ROOT}/m7_web_locks_scope_smoke_worker.js": self.server.worker_js_bytes,
        }
        if path in assets:
            self.send_bytes(HTTPStatus.OK, "text/javascript; charset=utf-8", assets[path])
            return
        self.not_found()

    def do_POST(self) -> None:
        if urlsplit(self.path).path != f"{HOST_ROOT}/result/{self.server.result_token}":
            self.not_found()
            return
        try:
            content_length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            content_length = -1
        if content_length < 0 or content_length > MAX_RESULT_BYTES:
            self.send_bytes(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "text/plain; charset=utf-8",
                b"invalid Web Locks result size\n",
            )
            return
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0]
        if content_type.strip().lower() != "application/json":
            self.send_bytes(
                HTTPStatus.BAD_REQUEST,
                "text/plain; charset=utf-8",
                b"Web Locks result must be JSON\n",
            )
            return
        result = parse_result_payload(
            self.rfile.read(content_length), self.server.run_namespace
        )
        if result is None:
            self.send_bytes(
                HTTPStatus.BAD_REQUEST,
                "text/plain; charset=utf-8",
                b"invalid Web Locks result\n",
            )
            return
        expected_origin = f"http://{self.server.server_address[0]}:{self.server.server_address[1]}"
        try:
            validate_result(
                result,
                expected_origin=expected_origin,
                expected_run_namespace=self.server.run_namespace,
            )
        except M0Error:
            self.send_bytes(
                HTTPStatus.BAD_REQUEST,
                "text/plain; charset=utf-8",
                b"Web Locks result did not satisfy the scoped contract\n",
            )
            return
        with self.server.result_lock:
            if self.server.result_received:
                self.send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"duplicate Web Locks result\n",
                )
                return
            try:
                self.server.result_queue.put_nowait(result)
            except queue.Full:
                self.send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"Web Locks result queue is full\n",
                )
                return
            self.server.result_received = True
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def parse_result_payload(payload: bytes, expected_run_namespace: str) -> dict[str, Any] | None:
    try:
        result = json.loads(
            payload.decode("utf-8"), object_pairs_hook=reject_duplicate_keys
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    if (
        not isinstance(result, dict)
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
    result_token: str,
    run_namespace: str,
    result_queue: queue.Queue[dict[str, Any]],
) -> WebLocksScopeServer:
    if not TOKEN_RE.fullmatch(result_token) or not TOKEN_RE.fullmatch(run_namespace):
        raise M0Error("Web Locks result token or namespace is invalid")
    host_dir = Path(__file__).with_name("host")
    server = WebLocksScopeServer((host, port), WebLocksScopeRequestHandler)
    server.result_token = result_token
    server.run_namespace = run_namespace
    server.result_queue = result_queue
    server.result_lock = threading.Lock()
    server.result_received = False
    server.html_bytes = (host_dir / "m7_web_locks_scope_smoke.html").read_bytes()
    server.host_js_bytes = (host_dir / "m7_web_locks_scope_smoke.js").read_bytes()
    server.worker_js_bytes = (
        host_dir / "m7_web_locks_scope_smoke_worker.js"
    ).read_bytes()
    return server


def smoke_url(
    server: WebLocksScopeServer,
    result_token: str,
    run_namespace: str,
    timeout_seconds: float,
) -> str:
    if result_token != server.result_token or run_namespace != server.run_namespace:
        raise M0Error("Web Locks URL credentials do not match its server")
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "token": result_token,
            "run": run_namespace,
            "timeoutMs": str(max(1000, min(180000, int(timeout_seconds * 1000)))),
        }
    )
    return f"http://{host}:{port}{HOST_ROOT}/?{query}"


def require_equal(result: dict[str, Any], field: str, expected: object) -> None:
    actual = result.get(field)
    if type(actual) is not type(expected) or actual != expected:
        raise M0Error(
            f"Web Locks result {field} mismatch: expected {expected!r}, got {actual!r}"
        )


def require_positive_integer(value: object, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise M0Error(f"Web Locks result {field} is invalid")
    return value


def validate_event_order(result: dict[str, Any]) -> None:
    order = result.get("eventOrder")
    if not isinstance(order, dict) or set(order) != set(ORDER_FIELDS):
        raise M0Error("Web Locks result eventOrder has an invalid shape")
    values = {
        field: require_positive_integer(order.get(field), field)
        for field in ORDER_FIELDS
    }
    if len(set(values.values())) != len(values):
        raise M0Error("Web Locks result eventOrder contains duplicate ordinals")
    trace = result["workerEventTrace"]
    by_ordinal = {entry["ordinal"]: entry["marker"] for entry in trace}
    for field, marker in ORDER_MARKERS.items():
        if by_ordinal.get(values[field]) != marker:
            raise M0Error("Web Locks result eventOrder does not match its trace")
    if not (
        values["holderExplicitHeld"] < values["contenderIfAvailable"]
        < values["contenderExplicitQueued"]
        < values["contenderExplicitBlocked"]
        < values["explicitReleaseCommand"]
        < values["contenderExplicitGranted"]
        and values["holderExplicitHeld"] < values["holderExplicitReleased"]
        and values["explicitReleaseCommand"] < values["holderExplicitReleased"]
        and values["contenderExplicitGranted"] < values["contenderExplicitReleased"]
        and values["contenderExplicitReleased"] < values["holderTerminationHeld"]
        and values["holderTerminationHeld"] < values["contenderTerminationQueued"]
        < values["contenderTerminationBlocked"]
        < values["holderTerminationCommand"]
        < values["contenderTerminationGranted"]
        and values["contenderTerminationGranted"]
        < values["contenderTerminationReleased"]
    ):
        raise M0Error("Web Locks result event ordering is invalid")


def validate_result(result: dict[str, Any], *, expected_origin: str, expected_run_namespace: str) -> None:
    if set(result) != RESULT_FIELDS:
        raise M0Error("Web Locks result has an invalid top-level field set")
    expected = {
        "protocol": 1,
        "case": CASE,
        "scope": SCOPE,
        "status": "pass",
        "runNamespace": expected_run_namespace,
        "origin": expected_origin,
        "secureContext": True,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "sameTopLevelDocumentSiblingDedicatedWorkersProven": True,
        "holderWorkerWebLocksAvailable": True,
        "contenderWorkerWebLocksAvailable": True,
        "ifAvailableReturnedNull": True,
        "contenderPendingBeforeExplicitRelease": True,
        "explicitReleaseQueuedGrantProven": True,
        "contenderPendingBeforeHolderTermination": True,
        "holderTerminationQueuedGrantProven": True,
        "holderWorkerTerminated": True,
        "webLocksScopeLimitation": (
            "per-storage-bucket-not-origin-wide-or-cross-document-proof"
        ),
        "terminationReacquisitionLimitation": (
            "observed-current-browser-behavior-not-profile-recovery"
        ),
        "opfsTouched": False,
        "syncAccessHandleCoordinated": False,
        "syncAccessHandleWriterExclusivityProven": False,
        "posixFcntlLocksProven": False,
        "byteRangeLocksProven": False,
        "sqliteLeveldbLockSemanticsProven": False,
        "profilePersistenceProven": False,
        "atomicRecoveryProven": False,
        "crashRecoveryProven": False,
        "gracefulRuntimeShutdownProven": False,
        "gracefulProfileShutdownProven": False,
        "m7GateComplete": False,
        "failureDiagnostics": None,
        "error": None,
    }
    for field, expected_value in expected.items():
        require_equal(result, field, expected_value)
    trace = result.get("workerEventTrace")
    if not isinstance(trace, list) or len(trace) != len(EXPECTED_TRACE_MARKERS):
        raise M0Error("Web Locks result workerEventTrace is invalid")
    if len(trace) > MAX_TRACE_EVENTS:
        raise M0Error("Web Locks result workerEventTrace exceeds its bound")
    if any(
        not isinstance(entry, dict)
        or set(entry) != {"marker", "ordinal"}
        or type(entry["ordinal"]) is not int
        or not isinstance(entry["marker"], str)
        or TRACE_MARKER_RE.fullmatch(entry["marker"]) is None
        for entry in trace
    ):
        raise M0Error("Web Locks result workerEventTrace has invalid entries")
    ordinals = [entry["ordinal"] for entry in trace]
    if sorted(ordinals) != list(range(1, len(trace) + 1)):
        raise M0Error("Web Locks result workerEventTrace ordinals are not dense")
    markers = [entry["marker"] for entry in trace]
    if len(set(markers)) != len(markers) or set(markers) != EXPECTED_TRACE_MARKERS:
        raise M0Error("Web Locks result workerEventTrace is incomplete")
    validate_event_order(result)


def redact_text(value: object, *opaque_values: str) -> str:
    redacted = str(value)
    for opaque_value in opaque_values:
        redacted = redacted.replace(opaque_value, "<redacted>")
    return redacted


def redact_value(value: object, *opaque_values: str) -> object:
    if isinstance(value, dict):
        return {
            key: "<redacted>"
            if key == "runNamespace"
            else redact_value(item, *opaque_values)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item, *opaque_values) for item in value]
    if isinstance(value, str):
        return redact_text(value, *opaque_values)
    return value


def wait_for_result(
    browser: subprocess.Popen[str],
    result_queue: queue.Queue[dict[str, Any]],
    deadline: float,
) -> dict[str, Any]:
    while True:
        if browser.poll() is not None:
            raise M0Error("host browser exited before Web Locks result")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M0Error("timed out waiting for Web Locks result")
        try:
            return result_queue.get(timeout=min(remaining, 0.25))
        except queue.Empty:
            continue


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the isolated same-top-level-document Web Locks DOM smoke."
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--timeout", type=parse_timeout, default=120.0)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    browser: subprocess.Popen[str] | None = None
    server: WebLocksScopeServer | None = None
    server_thread: threading.Thread | None = None
    stderr_thread: threading.Thread | None = None
    browser_stderr: deque[str] = deque(maxlen=128)
    try:
        browser_path, browser_version = find_browser(args.browser)
        result_token = secrets.token_urlsafe(24)
        run_namespace = secrets.token_urlsafe(24)
        result_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        server = create_server(
            "127.0.0.1", 0, result_token, run_namespace, result_queue
        )
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m7-web-locks-scope-server",
            daemon=True,
        )
        server_thread.start()
        url = smoke_url(server, result_token, run_namespace, args.timeout)
        with tempfile.TemporaryDirectory(prefix="chromium-wasm-m7-web-locks-") as profile:
            browser = subprocess.Popen(
                browser_command(
                    browser_path, profile, url, no_sandbox=args.no_sandbox
                ),
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
                name="chromium-wasm-m7-web-locks-scope-browser-stderr",
                daemon=True,
            )
            stderr_thread.start()
            result = wait_for_result(browser, result_queue, time.monotonic() + args.timeout)
            origin = f"http://{server.server_address[0]}:{server.server_address[1]}"
            validate_result(
                result,
                expected_origin=origin,
                expected_run_namespace=run_namespace,
            )
            print(
                f"{SENTINEL}:RESULT "
                + json.dumps(
                    redact_value(result, result_token, run_namespace),
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                flush=True,
            )
            print(f"{SENTINEL}:PASS browser={browser_version}", flush=True)
            return 0
    except (M0Error, OSError, TypeError, ValueError, queue.Full) as error:
        print(
            f"{SENTINEL}:FAIL reason={redact_text(error, result_token if 'result_token' in locals() else '', run_namespace if 'run_namespace' in locals() else '')}",
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


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
