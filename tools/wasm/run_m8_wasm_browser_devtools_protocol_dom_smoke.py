#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the fixed in-process DevTools protocol smoke in a real browser host.

The real browser supplies the cross-origin-isolated worker environment needed
by the mandatory OPFS profile backend.  This runner serves immutable snapshots
of one built loader and Wasm module, then requires the native fixed
Network.enable, Runtime.enable, Runtime.evaluate, Console API event, detach,
and lifecycle-close markers.  It is neither a DevTools frontend nor a remote
debugging/protocol transport, and it does not claim M8 completion.
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
from m9_descriptor_snapshot import snapshot_regular_files
from run_browser_smoke import browser_command, drain_stream, find_browser, stop_browser
from run_content_shell_smoke import manifest_versions
import run_wasm_browser_view_smoke as browser_view_smoke


SENTINEL = "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL_DOM"
CASE = "browser_devtools_protocol_m8"
SCOPE = (
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-"
    "runtime-enable-runtime-evaluate-console-event-detach-close"
)
SWITCH = "--wasm-browser-devtools-protocol-smoke"
NETWORK_ENABLE_MARKER = "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:NETWORK_ENABLE_OK"
RUNTIME_ENABLE_MARKER = "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:RUNTIME_ENABLE_OK"
RUNTIME_EVALUATE_MARKER = (
    "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:RUNTIME_EVALUATE_OK"
)
RUNTIME_CONSOLE_API_CALLED_MARKER = (
    "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:RUNTIME_CONSOLE_API_CALLED_OK"
)
DETACHED_MARKER = "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:DETACHED"
FAILURE_MARKER = "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:FAIL"
LIFECYCLE_PASS_MARKER = "CHROMIUM_WASM_M6_BROWSER_LIFECYCLE:PASS"
HOST_ROOT = "/__m8_browser_devtools_protocol__"
MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
MAX_RESULT_BYTES = 1024 * 1024
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024 * 1024
ARTIFACT_DELIVERY = "immutable-in-memory-server-snapshot"
LIMITATIONS = (
    "does_not_enable_or_exercise_page_webassembly",
    "does_not_provide_a_devtools_frontend_or_generic_protocol_bridge",
    "does_not_claim_m8_compatibility_completion",
)


class DevToolsProtocolSmokeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    artifacts: dict[str, bytes]
    host_html: bytes
    host_js: bytes
    module_name: str
    result_token: str
    result_queue: queue.Queue[dict[str, Any]]
    result_lock: threading.Lock
    result_received: bool


class DevToolsProtocolSmokeRequestHandler(BaseHTTPRequestHandler):
    server: DevToolsProtocolSmokeServer

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
                HTTPStatus.OK, "text/html; charset=utf-8", self.server.host_html
            )
            return
        if path == (
            f"{HOST_ROOT}/chrome_wasm_browser_devtools_protocol_smoke_host.js"
        ):
            self._send_bytes(
                HTTPStatus.OK,
                "text/javascript; charset=utf-8",
                self.server.host_js,
            )
            return
        prefix = f"{HOST_ROOT}/artifacts/"
        if path.startswith(prefix):
            name = path[len(prefix) :]
            artifact = self.server.artifacts.get(name)
            if artifact is not None:
                self._send_bytes(
                    HTTPStatus.OK,
                    "application/wasm"
                    if name.endswith(".wasm")
                    else "text/javascript; charset=utf-8",
                    artifact,
                )
                return
        self._not_found()

    def do_POST(self) -> None:
        expected = f"{HOST_ROOT}/result/{self.server.result_token}"
        if urlsplit(self.path).path != expected:
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
                b"invalid DevTools protocol result\n",
            )
            return
        with self.server.result_lock:
            if self.server.result_received:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"DevTools protocol result already received\n",
                )
                return
            try:
                self.server.result_queue.put_nowait(result)
            except queue.Full:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"DevTools protocol result queue is full\n",
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
        or type(result.get("protocol")) is not int
        or result.get("protocol") != 1
        or result.get("case") != CASE
        or result.get("scope") != SCOPE
    ):
        return None
    return result


def create_server(
    host: str,
    port: int,
    out_dir: Path,
    result_token: str,
    result_queue: queue.Queue[dict[str, Any]],
    *,
    module_name: str,
) -> DevToolsProtocolSmokeServer:
    if not MODULE_NAME_RE.fullmatch(module_name):
        raise M0Error("module name must contain only ASCII letters, digits, or _")
    out_dir = out_dir.resolve()
    host_dir = Path(__file__).with_name("host")
    artifacts = snapshot_regular_files(
        out_dir,
        (f"{module_name}.js", f"{module_name}.wasm"),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="DevTools protocol artifacts",
    )
    host_resources = snapshot_regular_files(
        host_dir,
        (
            "chrome_wasm_browser_devtools_protocol_smoke.html",
            "chrome_wasm_browser_devtools_protocol_smoke_host.js",
        ),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="DevTools protocol host resources",
    )
    server = DevToolsProtocolSmokeServer(
        (host, port), DevToolsProtocolSmokeRequestHandler
    )
    server.artifacts = artifacts
    server.host_html = host_resources[
        "chrome_wasm_browser_devtools_protocol_smoke.html"
    ]
    server.host_js = host_resources[
        "chrome_wasm_browser_devtools_protocol_smoke_host.js"
    ]
    server.module_name = module_name
    server.result_token = result_token
    server.result_queue = result_queue
    server.result_lock = threading.Lock()
    server.result_received = False
    return server


def _byte_identity(contents: bytes) -> dict[str, object]:
    return {
        "bytes": len(contents),
        "sha256": hashlib.sha256(contents).hexdigest(),
    }


def artifact_identity(server: DevToolsProtocolSmokeServer) -> dict[str, object]:
    return {
        "delivery": ARTIFACT_DELIVERY,
        "module": server.module_name,
        "loader": _byte_identity(server.artifacts[f"{server.module_name}.js"]),
        "wasm": _byte_identity(server.artifacts[f"{server.module_name}.wasm"]),
    }


def smoke_url(
    server: DevToolsProtocolSmokeServer,
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
            f"DevTools protocol result {field} mismatch: "
            f"expected {expected!r}, got {result.get(field)!r}"
        )


def _require_unique_ordered_markers(stderr: list[object]) -> None:
    output = "\n".join(str(value) for value in stderr)
    markers = (
        NETWORK_ENABLE_MARKER,
        RUNTIME_ENABLE_MARKER,
        RUNTIME_EVALUATE_MARKER,
        RUNTIME_CONSOLE_API_CALLED_MARKER,
        DETACHED_MARKER,
        LIFECYCLE_PASS_MARKER,
    )
    positions: dict[str, int] = {}
    for marker in markers:
        count = output.count(marker)
        if count != 1:
            raise M0Error(
                f"DevTools protocol native marker count is {count}: {marker}"
            )
        positions[marker] = output.index(marker)
    if FAILURE_MARKER in output:
        raise M0Error("DevTools protocol native smoke emitted a failure marker")
    if not (
        positions[NETWORK_ENABLE_MARKER] < positions[RUNTIME_ENABLE_MARKER]
        < positions[RUNTIME_EVALUATE_MARKER] < positions[DETACHED_MARKER]
        < positions[LIFECYCLE_PASS_MARKER]
        and positions[RUNTIME_ENABLE_MARKER]
        < positions[RUNTIME_CONSOLE_API_CALLED_MARKER]
        < positions[DETACHED_MARKER]
    ):
        raise M0Error("DevTools protocol native markers are not ordered")


def validate_result(result: dict[str, Any], *, expected_versions: dict[str, str]) -> None:
    for field, expected in {
        "protocol": 1,
        "case": CASE,
        "scope": SCOPE,
        "status": "pass",
        "m8GateComplete": False,
        "runtimeExitCode": 0,
        "runtimeInitialized": True,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocusAccepted": True,
        "networkEnableObserved": True,
        "runtimeEnableObserved": True,
        "runtimeEvaluateObserved": True,
        "runtimeConsoleApiCalledObserved": True,
        "detachedObserved": True,
        "lifecyclePassObserved": True,
        "abort": None,
        "failedChecks": [],
        "error": None,
    }.items():
        _require_equal(result, field, expected)
    process_exit_code = result.get("processExitCode")
    if process_exit_code is not None and (
        type(process_exit_code) is not int or process_exit_code != 0
    ):
        raise M0Error("DevTools protocol process exit disagrees with normal close")
    if result.get("versions") != expected_versions:
        raise M0Error("DevTools protocol versions do not match the manifest")
    for field in ("fatalErrors", "windowErrors", "unhandledRejections", "stdout"):
        if not isinstance(result.get(field), list) or result[field]:
            raise M0Error(f"DevTools protocol {field} is not empty")
    stderr = result.get("stderr")
    if not isinstance(stderr, list):
        raise M0Error("DevTools protocol stderr is not a list")
    _require_unique_ordered_markers(stderr)
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
                "host browser exited before DevTools protocol result: "
                + "\n".join(browser_stderr)
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M0Error(
                "DevTools protocol smoke timeout: " + "\n".join(browser_stderr)
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
) -> Path:
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / "chrome-browser-devtools-protocol-m8-failure.json"
    payload = {
        "schema_version": 1,
        "runner": "run_m8_wasm_browser_devtools_protocol_dom_smoke.py",
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
        description="Run the fixed in-process DevTools protocol smoke in a browser."
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--out-dir", type=Path, default=Path("out/wasm-chrome-m6"))
    parser.add_argument("--module-name", default="chrome_wasm")
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
    server: DevToolsProtocolSmokeServer | None = None
    server_thread: threading.Thread | None = None
    browser: subprocess.Popen[str] | None = None
    browser_path: Path | None = None
    browser_version: str | None = None
    browser_stderr: deque[str] = deque(maxlen=300)
    stderr_thread: threading.Thread | None = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    result: dict[str, Any] | None = None
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
            "run_m8_wasm_browser_devtools_protocol_dom_smoke.py",
            manifest,
            case=CASE,
            scope=SCOPE,
            gn_args=manifest.get("m6_chrome_gn_args", manifest.get("gn_args")),
            module_name=args.module_name,
            host_browser_sandbox=not args.no_sandbox,
            artifact_delivery=ARTIFACT_DELIVERY,
            runtime_arguments=[SWITCH],
            limitations=list(LIMITATIONS),
        )
        stage = "find_browser"
        browser_path, browser_version = find_browser(args.browser)
        token = secrets.token_urlsafe(24)
        result_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        stage = "snapshot_and_create_server"
        server = create_server(
            "127.0.0.1",
            0,
            out_dir,
            token,
            result_queue,
            module_name=args.module_name,
        )
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m8-devtools-protocol-server",
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
        profile = tempfile.TemporaryDirectory(
            prefix="chromium-wasm-m8-devtools-protocol-"
        )
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
            name="chromium-wasm-m8-devtools-protocol-browser-stderr",
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
            f"{SENTINEL}:ARTIFACT "
            + json.dumps(
                artifact_identity(server), sort_keys=True, separators=(",", ":")
            ),
            flush=True,
        )
        print(
            f"{SENTINEL}:BROWSER_RESULT "
            + json.dumps(result, sort_keys=True, separators=(",", ":")),
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
