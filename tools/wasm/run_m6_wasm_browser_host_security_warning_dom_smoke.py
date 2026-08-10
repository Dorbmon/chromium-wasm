#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run trusted DOM security-warning input through Chrome's Wasm host.

The runner sends exactly three physical DevTools pointer clicks to targets
derived by C++ after real Views layout: BrowserView Menu, its Security warning
item, and the child dialog's Dismiss button. The switch-gated C++ verifier
proves WCMDM block/unblock, child-widget visibility/bounds, and later host
canvas frames; this runner never invokes a Wasm command or navigation export.
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
from m4_cdp import unused_loopback_port, wait_for_page_client
from run_browser_smoke import browser_command, drain_stream, find_browser, stop_browser
from run_content_shell_smoke import manifest_versions
import run_wasm_browser_view_smoke as browser_view_smoke


SENTINEL = "CHROMIUM_WASM_M6_HOST_SECURITY_WARNING_DOM"
CASE = "browser_host_security_warning_m6"
SCOPE = "trusted-dom-pointer-ozone-aura-views-constrained-security-warning"
SWITCH = "--wasm-browser-host-security-warning-smoke"
READY_MARKER = "CHROMIUM_WASM_M6_HOST_SECURITY_WARNING:READY"
MENU_OPEN_MARKER = "CHROMIUM_WASM_M6_HOST_SECURITY_WARNING:MENU_OPEN"
MENU_PRESENTED_MARKER = "CHROMIUM_WASM_M6_HOST_SECURITY_WARNING:MENU_PRESENTED"
DIALOG_OPEN_MARKER = "CHROMIUM_WASM_M6_HOST_SECURITY_WARNING:DIALOG_OPEN"
DIALOG_INTERACTION_READY_MARKER = (
    "CHROMIUM_WASM_M6_HOST_SECURITY_WARNING:DIALOG_INTERACTION_READY"
)
DIALOG_DISMISSED_MARKER = "CHROMIUM_WASM_M6_HOST_SECURITY_WARNING:DIALOG_DISMISSED"
OBSERVATION_FAILED_MARKER = (
    "CHROMIUM_WASM_M6_HOST_SECURITY_WARNING:OBSERVATION_FAILED"
)
PASS_MARKER = "CHROMIUM_WASM_M6_HOST_SECURITY_WARNING:PASS"
MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
MAX_RESULT_BYTES = 1024 * 1024
MAX_FRAME_DIMENSION = 16384
HOST_ROOT = "/__m6_browser_host_security_warning__"


class HostSecurityWarningSmokeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    result_queue: queue.Queue[dict[str, Any]]
    result_token: str
    result_received: bool
    result_lock: threading.Lock


class HostSecurityWarningSmokeRequestHandler(BaseHTTPRequestHandler):
    server: HostSecurityWarningSmokeServer

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
        if path == f"{HOST_ROOT}/chrome_wasm_browser_host_security_warning_smoke_host.js":
            self._send_bytes(
                HTTPStatus.OK,
                "text/javascript; charset=utf-8",
                self.server.host_js_bytes,
            )
            return
        if path == f"{HOST_ROOT}/chrome_wasm_pointer_input.js":
            self._send_bytes(
                HTTPStatus.OK,
                "text/javascript; charset=utf-8",
                self.server.pointer_input_js_bytes,
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
                b"invalid security-warning result\n",
            )
            return
        with self.server.result_lock:
            if self.server.result_received:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"security-warning result already received\n",
                )
                return
            try:
                self.server.result_queue.put_nowait(result)
            except queue.Full:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"security-warning result queue is full\n",
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
) -> HostSecurityWarningSmokeServer:
    if not MODULE_NAME_RE.fullmatch(module_name):
        raise M0Error("module name must contain only ASCII letters, digits, or _")
    out_dir = out_dir.resolve()
    if not out_dir.is_dir():
        raise M0Error(f"security-warning output directory is missing: {out_dir}")
    host_dir = Path(__file__).with_name("host")
    server = HostSecurityWarningSmokeServer(
        (host, port), HostSecurityWarningSmokeRequestHandler
    )
    server.out_dir = out_dir
    server.module_name = module_name
    server.result_token = result_token
    server.result_queue = result_queue
    server.result_received = False
    server.result_lock = threading.Lock()
    server.html_bytes = (
        host_dir / "chrome_wasm_browser_host_security_warning_smoke.html"
    ).read_bytes()
    server.host_js_bytes = (
        host_dir / "chrome_wasm_browser_host_security_warning_smoke_host.js"
    ).read_bytes()
    server.pointer_input_js_bytes = (host_dir / "chrome_wasm_pointer_input.js").read_bytes()
    return server


def smoke_url(
    server: HostSecurityWarningSmokeServer,
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
            f"security-warning result {field} mismatch: expected {expected!r}, "
            f"got {result.get(field)!r}"
        )


def _validate_target(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise M0Error(f"security-warning {name} target is missing")
    for field in ("x", "y"):
        coordinate = value.get(field)
        if type(coordinate) is not int or not 0 <= coordinate < MAX_FRAME_DIMENSION:
            raise M0Error(f"security-warning {name} target {field} is invalid")
    for field in ("clientX", "clientY"):
        coordinate = value.get(field)
        if not isinstance(coordinate, (int, float)) or not 0 <= coordinate < 10000:
            raise M0Error(f"security-warning {name} target {field} is invalid")
    return value


def _validate_frame_order(value: dict[str, Any], before_field: str, after_field: str) -> None:
    before = value.get(before_field)
    after = value.get(after_field)
    if type(before) is not int or type(after) is not int or before < 0 or after <= before:
        raise M0Error(
            "security-warning has no ordered presentation evidence for "
            f"{after_field}"
        )


def _validate_pointer_action(
    record: object, target: dict[str, object], event_type: str, buttons: int, index: int
) -> None:
    if not isinstance(record, dict):
        raise M0Error(f"security-warning action {index} is not an object")
    expected = {
        "type": event_type,
        "trusted": True,
        "cancelable": True,
        "pointerType": "mouse",
        "primary": True,
        "button": 0,
        "buttons": buttons,
        "accepted": True,
        "defaultPrevented": True,
        "x": target["x"],
        "y": target["y"],
        "reason": None,
    }
    for field, expected_value in expected.items():
        if record.get(field) != expected_value:
            raise M0Error(
                f"security-warning action {index} {field} is invalid: "
                f"{record.get(field)!r}"
            )


def _validate_host_input(value: object) -> None:
    if not isinstance(value, dict):
        raise M0Error("security-warning result has no host-input evidence")
    for field in (
        "attached",
        "readyObserved",
        "menuOpenedObserved",
        "menuPresentedObserved",
        "dialogOpenedObserved",
        "dialogInteractionReadyObserved",
        "dialogDismissedObserved",
        "passObserved",
        "menuCheckQueued",
        "menuPresentationQueued",
        "dialogCheckQueued",
        "dismissCheckQueued",
        "presentationQueued",
    ):
        if value.get(field) is not True:
            raise M0Error(f"security-warning input {field} is not true")
    menu_target = _validate_target(value.get("menuTarget"), "Menu")
    warning_target = _validate_target(value.get("warningTarget"), "Security warning")
    dismiss_target = _validate_target(value.get("dismissTarget"), "Dismiss")
    if (menu_target["x"], menu_target["y"]) == (
        warning_target["x"], warning_target["y"]
    ):
        raise M0Error("security-warning Menu and warning targets must differ")
    if (warning_target["x"], warning_target["y"]) == (
        dismiss_target["x"], dismiss_target["y"]
    ):
        raise M0Error("security-warning warning and Dismiss targets must differ")
    _validate_frame_order(
        value, "frameIdAtMenuOpenedMarker", "frameIdAfterMenuOpen"
    )
    _validate_frame_order(
        value, "frameIdAtWarningAction", "frameIdAfterWarningAction"
    )
    _validate_frame_order(
        value, "frameIdAtDialogOpenedMarker", "frameIdAfterDialogOpen"
    )
    _validate_frame_order(
        value,
        "frameIdAtDialogInteractionReadyMarker",
        "frameIdAfterDialogInteractionReady",
    )
    _validate_frame_order(
        value, "frameIdAtDismissAction", "frameIdAfterDismissAction"
    )
    _validate_frame_order(
        value, "frameIdAtDialogDismissedMarker", "frameIdAfterDialogDismiss"
    )
    # The host records the action after consuming the prior presented frame,
    # so its current frame ID may equal that frame. Each paired post-action
    # frame above remains strictly later.
    if value["frameIdAtWarningAction"] < value["frameIdAfterMenuOpen"]:
        raise M0Error("security-warning action did not wait for Menu presentation")
    if value["frameIdAtDialogOpenedMarker"] < value["frameIdAfterWarningAction"]:
        raise M0Error(
            "security-warning dialog check did not wait for action presentation"
        )
    if value["frameIdAtDismissAction"] < value["frameIdAfterDialogOpen"]:
        raise M0Error("security-warning Dismiss did not wait for dialog presentation")
    if (
        value["frameIdAtDismissAction"]
        < value["frameIdAfterDialogInteractionReady"]
    ):
        raise M0Error(
            "security-warning Dismiss did not wait for dialog interaction readiness"
        )
    if value["frameIdAtDialogDismissedMarker"] < value["frameIdAfterDismissAction"]:
        raise M0Error(
            "security-warning dismissal check did not wait for action presentation"
        )

    records = value.get("pointerRecords")
    if not isinstance(records, list):
        raise M0Error("security-warning pointer records are missing")
    rejected = [
        record
        for record in records
        if isinstance(record, dict) and record.get("accepted") is not True
    ]
    if rejected:
        raise M0Error("security-warning rejected an outer trusted pointer record")
    actions = [
        record
        for record in records
        if isinstance(record, dict) and record.get("type") in ("down", "up")
    ]
    if len(actions) != 6:
        raise M0Error("security-warning has not recorded exactly three pointer clicks")
    _validate_pointer_action(actions[0], menu_target, "down", 1, 0)
    _validate_pointer_action(actions[1], menu_target, "up", 0, 1)
    _validate_pointer_action(actions[2], warning_target, "down", 1, 2)
    _validate_pointer_action(actions[3], warning_target, "up", 0, 3)
    _validate_pointer_action(actions[4], dismiss_target, "down", 1, 4)
    _validate_pointer_action(actions[5], dismiss_target, "up", 0, 5)


def validate_result(result: dict[str, Any], *, expected_versions: dict[str, str]) -> None:
    for field, expected in {
        "protocol": 1,
        "case": CASE,
        "scope": SCOPE,
        "status": "pass",
        "m6GateComplete": False,
        "runtimeExitCode": 0,
        "runtimeInitialized": True,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "abort": None,
        "failedChecks": [],
        "error": None,
    }.items():
        _require_equal(result, field, expected)
    process_exit_code = result.get("processExitCode")
    if process_exit_code is not None and process_exit_code != 0:
        raise M0Error("security-warning process exit disagrees with runtime")
    if result.get("versions") != expected_versions:
        raise M0Error("security-warning versions do not match manifest")
    for field in ("fatalErrors", "windowErrors", "unhandledRejections"):
        if not isinstance(result.get(field), list) or result[field]:
            raise M0Error(f"security-warning {field} is not empty")
    for field in ("stdout", "stderr"):
        if not isinstance(result.get(field), list):
            raise M0Error(f"security-warning {field} is not a list")
    stderr = "\n".join(str(value) for value in result["stderr"])
    for marker in (
        READY_MARKER,
        MENU_OPEN_MARKER,
        MENU_PRESENTED_MARKER,
        DIALOG_OPEN_MARKER,
        DIALOG_INTERACTION_READY_MARKER,
        DIALOG_DISMISSED_MARKER,
        PASS_MARKER,
    ):
        if marker not in stderr:
            raise M0Error(f"security-warning stderr is missing {marker}")
    if OBSERVATION_FAILED_MARKER in stderr:
        raise M0Error("security-warning bounded post-input observation failed")
    browser_view_smoke._validate_frame_reports(result.get("frameReports"))
    # This validates reporting type/order and requires the actual Ozone
    # surface. It intentionally does not require generic Chrome FVP true:
    # target visibility is proved by the dedicated staged child-widget frames.
    browser_view_smoke._validate_readiness(
        result.get("readiness"), result.get("readinessReports")
    )
    browser_view_smoke._validate_focus_reports(result.get("ozoneFocusReports"))
    _validate_host_input(result.get("hostInput"))


def _take_early_result(
    result_queue: queue.Queue[dict[str, Any]], stage: str
) -> None:
    try:
        result = result_queue.get_nowait()
    except queue.Empty:
        return
    raise M0Error(
        f"security-warning smoke finished before {stage}: "
        + json.dumps(result, sort_keys=True, separators=(",", ":"))
    )


def wait_for_state(
    client: Any,
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    result_queue: queue.Queue[dict[str, Any]],
    desired: str,
    deadline: float,
) -> dict[str, object]:
    last_state: object = None
    # This is a fixed read-only page state expression. It cannot focus,
    # dispatch, mutate the proxy, invoke an export, or navigate Chromium.
    expression = "globalThis.__chromiumWasmM6HostSecurityWarningState || null"
    while time.monotonic() < deadline:
        if browser.poll() is not None:
            raise M0Error(
                f"host browser exited before {desired}: " + "\n".join(browser_stderr)
            )
        _take_early_result(result_queue, desired)
        last_state = client.evaluate(expression)
        if isinstance(last_state, dict) and last_state.get("state") == desired:
            return last_state
        time.sleep(0.05)
    raise M0Error(
        f"security-warning smoke did not reach {desired}: "
        + json.dumps(last_state, sort_keys=True, separators=(",", ":"))
    )


def click_target(client: Any, state: dict[str, object], field: str) -> None:
    target = state.get(field)
    if not isinstance(target, dict):
        raise M0Error(f"security-warning state lacks {field}")
    x = target.get("clientX")
    y = target.get("clientY")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        raise M0Error(f"security-warning {field} client coordinates are invalid")
    # The only mutation from this runner is Chrome DevTools physical mouse
    # input. It never calls an exported C++ test verifier or Browser action.
    client.dispatch_primary_click(float(x), float(y))


def wait_for_result(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    result_queue: queue.Queue[dict[str, Any]],
    deadline: float,
) -> dict[str, Any]:
    while True:
        if browser.poll() is not None:
            raise M0Error(
                "host browser exited before security-warning result: "
                + "\n".join(browser_stderr)
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M0Error(
                "security-warning smoke timeout: " + "\n".join(browser_stderr)
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
    path = diagnostics_dir / "chrome-browser-host-security-warning-m6-failure.json"
    payload = {
        "schema_version": 1,
        "runner": "run_m6_wasm_browser_host_security_warning_dom_smoke.py",
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
        description="Run trusted DOM security-warning pointer input through Chrome Wasm."
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
    server: HostSecurityWarningSmokeServer | None = None
    server_thread: threading.Thread | None = None
    browser: subprocess.Popen[str] | None = None
    browser_path: Path | None = None
    browser_version: str | None = None
    browser_stderr: deque[str] = deque(maxlen=300)
    stderr_thread: threading.Thread | None = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    result: dict[str, Any] | None = None
    context: dict[str, object] | None = None
    client: Any = None
    stage = "check_artifacts"

    try:
        stage = "check_boundary"
        check_boundary(out_dir)
        for suffix in (".js", ".wasm"):
            if not (out_dir / f"{args.module_name}{suffix}").is_file():
                raise M0Error(f"security-warning artifact is missing: {suffix}")
        stage = "load_manifest"
        manifest = load_manifest()
        versions = manifest_versions(manifest, checked_output(["git", "rev-parse", "HEAD"]))
        context = print_context(
            "run_m6_wasm_browser_host_security_warning_dom_smoke.py",
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
            name="chromium-wasm-m6-host-security-warning-server",
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
            prefix="chromium-wasm-m6-host-security-warning-"
        )
        debug_port = unused_loopback_port()
        stage = "launch_browser"
        command = browser_command(
            browser_path, profile.name, url, no_sandbox=args.no_sandbox
        )
        command[1:1] = [
            "--enable-logging=stderr",
            "--remote-allow-origins=http://localhost",
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={debug_port}",
        ]
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
            name="chromium-wasm-m6-host-security-warning-browser-stderr",
            daemon=True,
        )
        stderr_thread.start()
        deadline = time.monotonic() + args.timeout
        stage = "connect_devtools"
        client = wait_for_page_client(debug_port, url.split("?", 1)[0], deadline)
        stage = "wait_for_menu_target"
        state = wait_for_state(
            client,
            browser,
            browser_stderr,
            result_queue,
            "awaiting-trusted-dom-menu",
            deadline,
        )
        stage = "dispatch_trusted_dom_menu"
        click_target(client, state, "menuTarget")
        stage = "wait_for_dynamic_warning_target"
        state = wait_for_state(
            client,
            browser,
            browser_stderr,
            result_queue,
            "awaiting-trusted-dom-security-warning",
            deadline,
        )
        stage = "dispatch_trusted_dom_security_warning"
        click_target(client, state, "warningTarget")
        stage = "wait_for_dynamic_dismiss_target"
        state = wait_for_state(
            client,
            browser,
            browser_stderr,
            result_queue,
            "awaiting-trusted-dom-dismiss",
            deadline,
        )
        stage = "dispatch_trusted_dom_dismiss"
        click_target(client, state, "dismissTarget")
        stage = "wait_for_result"
        result = wait_for_result(browser, browser_stderr, result_queue, deadline)
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
        if client is not None:
            client.close()
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
    sys.exit(main())
