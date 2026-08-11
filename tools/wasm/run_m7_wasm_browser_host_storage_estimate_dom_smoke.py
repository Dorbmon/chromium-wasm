#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the outer-origin storage-estimate Chrome Wasm smoke in a browser.

The host owns only the bounded navigator.storage.estimate() call and fixed
ordinal acknowledgements. The Wasm browser owns the Settings navigation,
native WebUI identity and immutable snapshot comparison.
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


SENTINEL = "CHROMIUM_WASM_M7_HOST_STORAGE_ESTIMATE_DOM"
CASE = "browser_host_storage_estimate_m7"
SCOPE = "outer-origin-estimate-native-settings-webui-later-frame"
SWITCH = "--wasm-browser-host-storage-estimate-smoke"
READY_MARKER = "CHROMIUM_WASM_M7_HOST_STORAGE_ESTIMATE:READY"
NAVIGATED_MARKER = "CHROMIUM_WASM_M7_HOST_STORAGE_ESTIMATE:SETTINGS_NAVIGATED"
PASS_MARKER = "CHROMIUM_WASM_M7_HOST_STORAGE_ESTIMATE:PASS"
MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
MAX_RESULT_BYTES = 1024 * 1024
HOST_ROOT = "/__m7_browser_host_storage_estimate__"


class HostStorageEstimateSmokeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    result_queue: queue.Queue[dict[str, Any]]
    result_token: str
    result_received: bool
    result_lock: threading.Lock


class HostStorageEstimateSmokeRequestHandler(BaseHTTPRequestHandler):
    server: HostStorageEstimateSmokeServer

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

    def _artifact_path(self, requested_name: str) -> Path | None:
        if requested_name not in {
            f"{self.server.module_name}.js",
            f"{self.server.module_name}.wasm",
        }:
            return None
        candidate = (self.server.out_dir / requested_name).resolve()
        try:
            candidate.relative_to(self.server.out_dir)
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path in (HOST_ROOT, f"{HOST_ROOT}/"):
            self._send_bytes(
                HTTPStatus.OK, "text/html; charset=utf-8", self.server.html_bytes
            )
            return
        if path == f"{HOST_ROOT}/chrome_wasm_browser_host_storage_estimate_smoke_host.js":
            self._send_bytes(
                HTTPStatus.OK,
                "text/javascript; charset=utf-8",
                self.server.host_js_bytes,
            )
            return
        if path == f"{HOST_ROOT}/chrome_wasm_storage_estimate.js":
            self._send_bytes(
                HTTPStatus.OK,
                "text/javascript; charset=utf-8",
                self.server.storage_estimate_js_bytes,
            )
            return
        prefix = f"{HOST_ROOT}/artifacts/"
        if path.startswith(prefix):
            artifact = self._artifact_path(path[len(prefix) :])
            if artifact is None:
                self._not_found()
                return
            self._send_bytes(
                HTTPStatus.OK,
                "application/wasm"
                if artifact.suffix == ".wasm"
                else "text/javascript; charset=utf-8",
                artifact.read_bytes(),
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
                b"invalid host-storage-estimate result\n",
            )
            return
        with self.server.result_lock:
            if self.server.result_received:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"host-storage-estimate result already received\n",
                )
                return
            try:
                self.server.result_queue.put_nowait(result)
            except queue.Full:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"host-storage-estimate result queue is full\n",
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


def create_server(
    host: str,
    port: int,
    out_dir: Path,
    result_token: str,
    result_queue: queue.Queue[dict[str, Any]],
    *,
    module_name: str,
) -> HostStorageEstimateSmokeServer:
    if not MODULE_NAME_RE.fullmatch(module_name):
        raise M0Error("module name must contain only ASCII letters, digits, or _")
    out_dir = out_dir.resolve()
    if not out_dir.is_dir():
        raise M0Error(f"host-storage-estimate output directory is missing: {out_dir}")
    host_dir = Path(__file__).with_name("host")
    server = HostStorageEstimateSmokeServer(
        (host, port), HostStorageEstimateSmokeRequestHandler
    )
    server.out_dir = out_dir
    server.module_name = module_name
    server.result_token = result_token
    server.result_queue = result_queue
    server.result_received = False
    server.result_lock = threading.Lock()
    server.html_bytes = (
        host_dir / "chrome_wasm_browser_host_storage_estimate_smoke.html"
    ).read_bytes()
    server.host_js_bytes = (
        host_dir / "chrome_wasm_browser_host_storage_estimate_smoke_host.js"
    ).read_bytes()
    server.storage_estimate_js_bytes = (
        host_dir / "chrome_wasm_storage_estimate.js"
    ).read_bytes()
    return server


def smoke_url(
    server: HostStorageEstimateSmokeServer,
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
            f"host-storage-estimate result {field} mismatch: expected {expected!r}, "
            f"got {result.get(field)!r}"
        )


def _validate_later_frame(result: dict[str, Any]) -> None:
    marker_frame = result.get("navigationMarkerFrameId")
    presented_frame = result.get("frameIdAfterNavigation")
    if (
        type(marker_frame) is not int
        or type(presented_frame) is not int
        or marker_frame < 0
        or presented_frame <= marker_frame
    ):
        raise M0Error("host-storage-estimate lacks strictly later frame evidence")


def _validate_storage_result(result: dict[str, Any]) -> None:
    storage_result = result.get("storageResult")
    if not isinstance(storage_result, dict) or set(storage_result) != {
        "generation",
        "status",
        "delivered",
    }:
        raise M0Error("host-storage-estimate has an invalid storage-result shape")
    if (
        type(storage_result["generation"]) is not int
        or storage_result["generation"] < 1
        or storage_result["status"] != "available"
        or storage_result["delivered"] is not True
    ):
        raise M0Error("host-storage-estimate did not accept an available estimate")


def validate_result(result: dict[str, Any], *, expected_versions: dict[str, str]) -> None:
    for field, expected in {
        "protocol": 1,
        "case": CASE,
        "scope": SCOPE,
        "status": "pass",
        "m7GateComplete": False,
        "runtimeExitCode": 0,
        "runtimeInitialized": True,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "readyObserved": True,
        "settingsNavigatedObserved": True,
        "passObserved": True,
        "storageCheckQueued": True,
        "storageCheckAccepted": True,
        "settingsPresentationQueued": True,
        "settingsPresentationAccepted": True,
        "fixedOrdinals": [1, 2],
        "abort": None,
        "failedChecks": [],
        "error": None,
    }.items():
        _require_equal(result, field, expected)
    process_exit_code = result.get("processExitCode")
    if process_exit_code is not None and process_exit_code != 0:
        raise M0Error("host-storage-estimate process exit disagrees with normal close")
    if result.get("versions") != expected_versions:
        raise M0Error("host-storage-estimate versions do not match the manifest")
    for field in ("fatalErrors", "windowErrors", "unhandledRejections"):
        if not isinstance(result.get(field), list) or result[field]:
            raise M0Error(f"host-storage-estimate {field} is not empty")
    for field in ("stdout", "stderr"):
        if not isinstance(result.get(field), list):
            raise M0Error(f"host-storage-estimate {field} is not a list")
    stderr = "\n".join(str(value) for value in result["stderr"])
    for marker in (READY_MARKER, NAVIGATED_MARKER, PASS_MARKER):
        if marker not in stderr:
            raise M0Error(f"host-storage-estimate stderr is missing {marker}")
    _validate_storage_result(result)
    _validate_later_frame(result)
    browser_view_smoke._validate_frame_reports(result.get("frameReports"))
    browser_view_smoke._validate_readiness(
        result.get("readiness"), result.get("readinessReports")
    )


def verify_explicit_smoke_exports(module_loader: Path) -> None:
    try:
        loader = module_loader.read_text(encoding="utf-8")
    except OSError as error:
        raise M0Error(
            f"cannot read host-storage-estimate module loader: {error}"
        ) from error
    for export in (
        'Module["_chromium_wasm_browser_host_storage_estimate_complete"]',
        'Module["_chromium_wasm_browser_host_storage_estimate_check"]',
        'Module["_chromium_wasm_browser_host_storage_estimate_presented"]',
    ):
        if export not in loader:
            raise M0Error(
                "host-storage-estimate module does not expose required ABI " + export
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
                "host browser exited before host-storage-estimate result: "
                + "\n".join(browser_stderr)
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M0Error(
                "host-storage-estimate smoke timeout: " + "\n".join(browser_stderr)
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
    context: dict[str, object] | None,
    browser_path: Path | None,
    browser_version: str | None,
    browser: subprocess.Popen[str] | None,
    browser_stderr: deque[str],
    runtime_result: dict[str, Any] | None,
) -> Path:
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / "chrome-browser-host-storage-estimate-m7-failure.json"
    payload = {
        "schema_version": 1,
        "runner": "run_m7_wasm_browser_host_storage_estimate_dom_smoke.py",
        "case": CASE,
        "scope": SCOPE,
        "stage": stage,
        "failure": {"type": type(error).__name__, "message": str(error)},
        "context": context,
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
        description="Run host-origin storage capacity through native Settings WebUI."
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
    server: HostStorageEstimateSmokeServer | None = None
    server_thread: threading.Thread | None = None
    browser: subprocess.Popen[str] | None = None
    browser_path: Path | None = None
    browser_version: str | None = None
    browser_stderr: deque[str] = deque(maxlen=300)
    stderr_thread: threading.Thread | None = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    result: dict[str, Any] | None = None
    context: dict[str, object] | None = None
    stage = "check_artifacts"

    try:
        stage = "check_boundary"
        check_boundary(out_dir)
        for suffix in (".js", ".wasm"):
            if not (out_dir / f"{args.module_name}{suffix}").is_file():
                raise M0Error(f"host-storage-estimate artifact is missing: {suffix}")
        verify_explicit_smoke_exports(out_dir / f"{args.module_name}.js")
        stage = "load_manifest"
        manifest = load_manifest()
        versions = manifest_versions(
            manifest, checked_output(["git", "rev-parse", "HEAD"])
        )
        context = print_context(
            "run_m7_wasm_browser_host_storage_estimate_dom_smoke.py",
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
        server = create_server(
            "127.0.0.1", 0, out_dir, token, result_queue, module_name=args.module_name
        )
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m7-host-storage-estimate-server",
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
            prefix="chromium-wasm-m7-host-storage-estimate-"
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
            name="chromium-wasm-m7-host-storage-estimate-browser-stderr",
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
                context=context,
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
