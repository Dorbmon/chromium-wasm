#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run trusted DOM History and Downloads input through Chrome's Wasm host.

The browser receives both HTTPS visits only through physical Ctrl+L,
Input.insertText, and physical Enter. It reaches History and Downloads only
through physical pointer clicks at C++-reported BrowserView targets. The
runner reads one frozen host-state object between actions; it has no Wasm
command, host navigation, or page-script control channel.
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
from run_browser_smoke import (
    browser_command,
    drain_stream,
    find_browser,
    stop_browser,
)
from run_content_shell_smoke import manifest_versions
from run_m5_wisp_smoke import (
    find_node,
    m5_host_origin,
    relay_command,
    verify_no_private_key_pem_artifacts,
)
import run_m6_wasm_browser_controlled_https_smoke as controlled_https
import run_wasm_browser_view_smoke as browser_view_smoke


SENTINEL = "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS_DOM"
CASE = "browser_host_history_downloads_m6"
SCOPE = "trusted-dom-text-pointer-ozone-aura-views-history-downloads-volatile"
SMOKE_SWITCH = "--wasm-browser-host-history-downloads-smoke"
URL_SWITCH = "--wasm-browser-controlled-https-url"
FIRST_ADDRESS_TEXT = "https://a.test/m5/m6-ui#wasm_journal=1"
SECOND_ADDRESS_TEXT = "https://a.test/m5/m6-ui"
CONTROLLED_ROOT_URL = SECOND_ADDRESS_TEXT
READY_MARKER = "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:READY"
FIRST_NAVIGATED_MARKER = "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:FIRST_NAVIGATED"
SECOND_TAB_READY_MARKER = "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:SECOND_TAB_READY"
SECOND_NAVIGATED_MARKER = "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:SECOND_NAVIGATED"
MENU_OPEN_HISTORY_MARKER = "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:MENU_OPEN_HISTORY"
MENU_CLOSED_HISTORY_MARKER = "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:MENU_CLOSED_HISTORY"
HISTORY_NAVIGATED_MARKER = "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:HISTORY_NAVIGATED"
MENU_OPEN_DOWNLOADS_MARKER = "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:MENU_OPEN_DOWNLOADS"
MENU_CLOSED_DOWNLOADS_MARKER = "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:MENU_CLOSED_DOWNLOADS"
DOWNLOADS_NAVIGATED_MARKER = "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:DOWNLOADS_NAVIGATED"
PASS_MARKER = "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:PASS"

DEFAULT_OUT_DIR = Path("out/wasm-chrome-m6")
DEFAULT_MODULE_NAME = "chrome_wasm_m6_https_test"
CONTROLLED_HTTPS_GN_TARGET = "//chrome:chrome_wasm_m6_https_test"
HOST_ROOT = "/__m6_browser_history_downloads__"
MAX_RESULT_BYTES = 8 * 1024 * 1024
MAX_FRAME_DIMENSION = 16384
MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


class HostHistoryDownloadsSmokeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    result_queue: queue.Queue[dict[str, Any]]
    result_token: str
    result_received: bool
    result_lock: threading.Lock


class HostHistoryDownloadsSmokeRequestHandler(BaseHTTPRequestHandler):
    server: HostHistoryDownloadsSmokeServer

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
        expected = {
            f"{self.server.module_name}.js",
            f"{self.server.module_name}.wasm",
        }
        if requested_name not in expected:
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
        static_files = {
            f"{HOST_ROOT}/chrome_wasm_browser_host_history_downloads_smoke_host.js": (
                "text/javascript; charset=utf-8",
                self.server.host_js_bytes,
            ),
            f"{HOST_ROOT}/chrome_wasm_text_input.js": (
                "text/javascript; charset=utf-8",
                self.server.text_input_js_bytes,
            ),
            f"{HOST_ROOT}/chrome_wasm_pointer_input.js": (
                "text/javascript; charset=utf-8",
                self.server.pointer_input_js_bytes,
            ),
        }
        static = static_files.get(path)
        if static is not None:
            self._send_bytes(HTTPStatus.OK, static[0], static[1])
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
                b"invalid History/Downloads result\n",
            )
            return
        with self.server.result_lock:
            if self.server.result_received:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"History/Downloads result already received\n",
                )
                return
            try:
                self.server.result_queue.put_nowait(result)
            except queue.Full:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"History/Downloads result queue is full\n",
                )
                return
            self.server.result_received = True
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


def parse_result_payload(payload: bytes) -> dict[str, Any] | None:
    try:
        result = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_json_object_without_duplicate_keys,
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
) -> HostHistoryDownloadsSmokeServer:
    if not MODULE_NAME_RE.fullmatch(module_name):
        raise M0Error("module name must contain only ASCII letters, digits, or _")
    resolved_out_dir = out_dir.resolve()
    if not resolved_out_dir.is_dir():
        raise M0Error(f"History/Downloads output directory is missing: {out_dir}")
    host_dir = Path(__file__).with_name("host")
    server = HostHistoryDownloadsSmokeServer(
        (host, port), HostHistoryDownloadsSmokeRequestHandler
    )
    server.out_dir = resolved_out_dir
    server.module_name = module_name
    server.result_token = result_token
    server.result_queue = result_queue
    server.result_received = False
    server.result_lock = threading.Lock()
    server.html_bytes = (
        host_dir / "chrome_wasm_browser_host_history_downloads_smoke.html"
    ).read_bytes()
    server.host_js_bytes = (
        host_dir / "chrome_wasm_browser_host_history_downloads_smoke_host.js"
    ).read_bytes()
    server.text_input_js_bytes = (host_dir / "chrome_wasm_text_input.js").read_bytes()
    server.pointer_input_js_bytes = (
        host_dir / "chrome_wasm_pointer_input.js"
    ).read_bytes()
    return server


def smoke_url(
    server: HostHistoryDownloadsSmokeServer,
    token: str,
    versions: dict[str, str],
    *,
    relay_ready: controlled_https.RelayReady,
    module_name: str,
    timeout_seconds: float,
) -> str:
    wisp_endpoint = controlled_https.validate_controlled_wisp_endpoint(
        relay_ready.wisp_endpoint
    )
    controlled_https.validate_m6_ui_url(relay_ready.m6_ui_url)
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "token": token,
            "module": module_name,
            "timeoutMs": str(max(1000, min(180000, int(timeout_seconds * 1000)))),
            "versions": json.dumps(versions, sort_keys=True, separators=(",", ":")),
            "wispEndpoint": wisp_endpoint,
            "fixtureUrl": CONTROLLED_ROOT_URL,
        }
    )
    return f"http://{host}:{port}{HOST_ROOT}/?{query}"


def verify_required_exports(module_loader: Path) -> None:
    try:
        loader = module_loader.read_text(encoding="utf-8")
    except OSError as error:
        raise M0Error(f"cannot read History/Downloads module loader: {error}") from error
    for export in (
        'Module["_chromium_wasm_browser_host_key"]',
        'Module["_chromium_wasm_browser_host_text"]',
        'Module["_chromium_wasm_browser_host_pointer"]',
        'Module["_chromium_wasm_browser_host_pointer_exit"]',
        'Module["_chromium_wasm_browser_host_history_downloads_check"]',
        'Module["_chromium_wasm_browser_host_history_downloads_presented"]',
        'Module["_malloc"]',
        'Module["_free"]',
        'Module["ccall"]',
        'Module["HEAPU8"]',
    ):
        if export not in loader:
            raise M0Error(
                "History/Downloads module lacks required trusted-input export "
                + export
            )


def _require_equal(result: dict[str, Any], field: str, expected: object) -> None:
    if not browser_view_smoke._exact_json_value_equal(result.get(field), expected):
        raise M0Error(
            f"History/Downloads result {field} mismatch: expected {expected!r}, "
            f"got {result.get(field)!r}"
        )


def _validate_target(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise M0Error(f"History/Downloads {name} target is missing")
    for field in ("x", "y"):
        coordinate = value.get(field)
        if type(coordinate) is not int or not 0 <= coordinate < MAX_FRAME_DIMENSION:
            raise M0Error(f"History/Downloads {name} target {field} is invalid")
    for field in ("clientX", "clientY"):
        coordinate = value.get(field)
        if not isinstance(coordinate, (int, float)) or not 0 <= coordinate < 10000:
            raise M0Error(f"History/Downloads {name} target {field} is invalid")
    return value


def _validate_frame_after(
    value: dict[str, object], before_field: str, after_field: str
) -> None:
    before = value.get(before_field)
    after = value.get(after_field)
    if type(before) is not int or type(after) is not int or before < 0 or after <= before:
        raise M0Error(
            "History/Downloads has no ordered presentation evidence for "
            f"{after_field}"
        )


def _validate_pointer_action(
    record: object,
    target: dict[str, object],
    event_type: str,
    buttons: int,
    index: int,
) -> None:
    if not isinstance(record, dict):
        raise M0Error(f"History/Downloads pointer action {index} is not an object")
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
                f"History/Downloads pointer action {index} {field} is invalid: "
                f"{record.get(field)!r}"
            )


def _validate_text_record(transaction: object, phase: str) -> None:
    if not isinstance(transaction, dict) or transaction.get("phase") != phase:
        raise M0Error(f"History/Downloads {phase} text transaction is invalid")
    if transaction.get("adapterId") != 1:
        raise M0Error(
            f"History/Downloads {phase} text transaction lost its adapter identity"
        )
    for field in (
        "ctrlLComplete",
        "proxyFocusedAfterCtrlL",
        "textDeliveryAccepted",
        "enterComplete",
    ):
        if transaction.get(field) is not True:
            raise M0Error(f"History/Downloads {phase} text {field} is not true")
    sequence = 1 if phase == "first" else 2
    if (
        transaction.get("nativeTextAdmissionCount") != 1
        or transaction.get("nativeTextDeliveryCount") != 1
        or transaction.get("nativeTextDeliverySequences") != [sequence]
        or transaction.get("rejected") is not False
    ):
        raise M0Error(f"History/Downloads {phase} text counters are invalid")
    adapter = transaction.get("adapter")
    if not isinstance(adapter, dict) or "textareaValue" in adapter:
        raise M0Error(f"History/Downloads {phase} text metadata is invalid")
    for field in (
        "deliveryAccepted",
        "shortcutComplete",
        "proxySessionCleared",
    ):
        expected = field != "proxySessionCleared"
        if adapter.get(field) is not expected:
            raise M0Error(
                f"History/Downloads {phase} adapter {field} is invalid"
            )
    for field in (
        "deliveryRejected",
    ):
        if adapter.get(field) is not False:
            raise M0Error(
                f"History/Downloads {phase} adapter {field} is invalid"
            )
    for field in (
        "pendingDeliveryCount",
        "pendingTextUtf8Bytes",
        "tombstonedDeliveryCount",
    ):
        if adapter.get(field) != 0:
            raise M0Error(
                f"History/Downloads {phase} adapter {field} is nonzero"
            )
    expected_text = FIRST_ADDRESS_TEXT if phase == "first" else SECOND_ADDRESS_TEXT
    before_input = adapter.get("beforeInputRecords")
    if not isinstance(before_input, list) or len(before_input) != 1:
        raise M0Error(f"History/Downloads {phase} beforeinput evidence is invalid")
    record = before_input[0]
    expected_before_input = {
        "inputType": "insertText",
        "dataOmitted": True,
        "dataUtf16Units": len(expected_text),
        "dataUtf8Bytes": len(expected_text),
        "trusted": True,
        "cancelable": True,
        "isComposing": False,
        "proxyFocused": True,
        "queued": True,
        "defaultPrevented": True,
        "sequence": sequence,
        "nativeDispatched": True,
        "nativeAccepted": True,
    }
    if not isinstance(record, dict) or "data" in record:
        raise M0Error(f"History/Downloads {phase} beforeinput retained raw text")
    for field, expected in expected_before_input.items():
        if record.get(field) != expected:
            raise M0Error(
                f"History/Downloads {phase} beforeinput {field} is invalid"
            )
    delivery = adapter.get("browserTextDeliveryReports")
    if delivery != [
        {"action": 4, "sessionId": 0, "sequence": sequence, "accepted": True}
    ]:
        raise M0Error(f"History/Downloads {phase} text delivery is invalid")
    ctrl_l = adapter.get("ctrlLRecords")
    expected_ctrl_l = [
        ("keydown", "ControlLeft"),
        ("keydown", "KeyL"),
        ("keyup", "KeyL"),
        ("keyup", "ControlLeft"),
    ]
    if not isinstance(ctrl_l, list) or len(ctrl_l) != len(expected_ctrl_l):
        raise M0Error(f"History/Downloads {phase} Ctrl+L records are invalid")
    for index, (event_type, code) in enumerate(expected_ctrl_l):
        record = ctrl_l[index]
        if not isinstance(record, dict) or any(
            record.get(field) != expected
            for field, expected in {
                "type": event_type,
                "code": code,
                "trusted": True,
                "cancelable": True,
                "canvasFocused": True,
                "accepted": True,
                "defaultPrevented": True,
            }.items()
        ):
            raise M0Error(
                f"History/Downloads {phase} Ctrl+L record {index} is invalid"
            )
    enter = adapter.get("enterRecords")
    if not isinstance(enter, list) or len(enter) != 2:
        raise M0Error(f"History/Downloads {phase} Enter records are invalid")
    for index, event_type in enumerate(("keydown", "keyup")):
        record = enter[index]
        if not isinstance(record, dict) or any(
            record.get(field) != expected
            for field, expected in {
                "type": event_type,
                "code": "Enter",
                "key": "Enter",
                "trusted": True,
                "cancelable": True,
                "proxyFocused": True,
                "accepted": True,
                "defaultPrevented": True,
            }.items()
        ):
            raise M0Error(
                f"History/Downloads {phase} Enter record {index} is invalid"
            )
    for field in ("rejectedRecords", "cleanupRecords"):
        if adapter.get(field) != []:
            raise M0Error(f"History/Downloads {phase} has unexpected {field}")


def _validate_host_input(value: object) -> None:
    if not isinstance(value, dict):
        raise M0Error("History/Downloads result has no host-input evidence")
    if value.get("singleAdapterRetained") is not True:
        raise M0Error("History/Downloads did not retain one text adapter")
    for field in (
        "newTabCheckQueued",
        "historyMenuOpenCheckQueued",
        "historyMenuClosedCheckQueued",
        "downloadsMenuOpenCheckQueued",
        "downloadsMenuClosedCheckQueued",
        "finalPresentationQueued",
    ):
        if value.get(field) is not True:
            raise M0Error(f"History/Downloads host input {field} is not true")
    transactions = value.get("textTransactions")
    if not isinstance(transactions, list) or len(transactions) != 2:
        raise M0Error("History/Downloads does not have two text transactions")
    _validate_text_record(transactions[0], "first")
    _validate_text_record(transactions[1], "second")
    for field, expected in (
        ("newTabActionOffset", 0),
        ("firstMenuActionOffset", 2),
        ("historyActionOffset", 4),
        ("secondMenuActionOffset", 6),
        ("downloadsActionOffset", 8),
    ):
        if value.get(field) != expected:
            raise M0Error(
                f"History/Downloads host input {field} is not {expected}"
            )
    targets = [
        _validate_target(value.get("newTabTarget"), "New Tab"),
        _validate_target(value.get("firstMenuTarget"), "first Menu"),
        _validate_target(value.get("historyTarget"), "History"),
        _validate_target(value.get("secondMenuTarget"), "second Menu"),
        _validate_target(value.get("downloadsTarget"), "Downloads"),
    ]
    if len({(target["x"], target["y"]) for target in targets}) < 3:
        raise M0Error("History/Downloads pointer targets are implausibly collapsed")
    records = value.get("pointerRecords")
    if not isinstance(records, list):
        raise M0Error("History/Downloads pointer records are missing")
    if any(isinstance(record, dict) and record.get("accepted") is not True for record in records):
        raise M0Error("History/Downloads rejected a trusted pointer record")
    actions = [
        record
        for record in records
        if isinstance(record, dict) and record.get("type") in ("down", "up")
    ]
    if len(actions) != 10:
        raise M0Error("History/Downloads lacks exactly five pointer clicks")
    for click, target in enumerate(targets):
        _validate_pointer_action(actions[click * 2], target, "down", 1, click * 2)
        _validate_pointer_action(
            actions[click * 2 + 1], target, "up", 0, click * 2 + 1
        )


def _validate_history_downloads_proof(value: object) -> None:
    if not isinstance(value, dict):
        raise M0Error("History/Downloads proof is missing")
    for field in (
        "wispConfigured",
        "runtimeArgumentsConfigured",
        "configurationPrecededFactory",
        "readyObserved",
        "firstNavigatedObserved",
        "secondTabReadyObserved",
        "secondNavigatedObserved",
        "menuOpenHistoryObserved",
        "menuClosedHistoryObserved",
        "historyNavigatedObserved",
        "menuOpenDownloadsObserved",
        "menuClosedDownloadsObserved",
        "downloadsNavigatedObserved",
        "passObserved",
    ):
        if value.get(field) is not True:
            raise M0Error(f"History/Downloads proof {field} is not true")
    for before, after in (
        ("frameIdAtFirstNavigatedMarker", "frameIdAfterFirstNavigatedMarker"),
        ("frameIdAtSecondTabReadyMarker", "frameIdAfterSecondTabReadyMarker"),
        ("frameIdAtSecondNavigatedMarker", "frameIdAfterSecondNavigatedMarker"),
        (
            "frameIdAtMenuOpenHistoryMarker",
            "frameIdAfterMenuOpenHistoryMarker",
        ),
        (
            "frameIdAtMenuClosedHistoryMarker",
            "frameIdAfterMenuClosedHistoryMarker",
        ),
        ("frameIdAtHistoryNavigatedMarker", "frameIdAfterHistoryNavigatedMarker"),
        (
            "frameIdAtMenuOpenDownloadsMarker",
            "frameIdAfterMenuOpenDownloadsMarker",
        ),
        (
            "frameIdAtMenuClosedDownloadsMarker",
            "frameIdAfterMenuClosedDownloadsMarker",
        ),
        (
            "frameIdAtDownloadsNavigatedMarker",
            "frameIdAfterDownloadsNavigatedMarker",
        ),
    ):
        _validate_frame_after(value, before, after)


def _require_redacted_serialization(result: dict[str, Any]) -> None:
    serialized = json.dumps(result, sort_keys=True, separators=(",", ":"))
    for raw in (FIRST_ADDRESS_TEXT, SECOND_ADDRESS_TEXT):
        if raw in serialized:
            raise M0Error("History/Downloads result retained a raw typed URL")


def validate_result(result: dict[str, Any], *, expected_versions: dict[str, str]) -> None:
    for field, expected in {
        "protocol": 1,
        "case": CASE,
        "scope": SCOPE,
        "status": "pass",
        "m6GateComplete": False,
        "runtimeExitCode": 0,
        "runtimeInitialized": True,
        "factorySettled": True,
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
        raise M0Error("History/Downloads bridge process exit disagrees with runtime")
    if result.get("versions") != expected_versions:
        raise M0Error("History/Downloads versions do not match manifest")
    for field in ("fatalErrors", "windowErrors", "unhandledRejections"):
        if not isinstance(result.get(field), list) or result[field]:
            raise M0Error(f"History/Downloads {field} is not empty")
    for field in ("stdout", "stderr"):
        if not isinstance(result.get(field), list):
            raise M0Error(f"History/Downloads {field} is not a list")
    output = "\n".join(
        str(line) for field in ("stdout", "stderr") for line in result[field]
    )
    for marker in (
        READY_MARKER,
        FIRST_NAVIGATED_MARKER,
        SECOND_TAB_READY_MARKER,
        SECOND_NAVIGATED_MARKER,
        MENU_OPEN_HISTORY_MARKER,
        MENU_CLOSED_HISTORY_MARKER,
        HISTORY_NAVIGATED_MARKER,
        MENU_OPEN_DOWNLOADS_MARKER,
        MENU_CLOSED_DOWNLOADS_MARKER,
        DOWNLOADS_NAVIGATED_MARKER,
        PASS_MARKER,
    ):
        if marker not in output:
            raise M0Error(f"History/Downloads output is missing {marker}")
    browser_view_smoke._validate_frame_reports(result.get("frameReports"))
    browser_view_smoke._validate_readiness(
        result.get("readiness"), result.get("readinessReports")
    )
    browser_view_smoke._validate_focus_reports(result.get("ozoneFocusReports"))
    text_states = result.get("ozoneTextInputStates")
    if not isinstance(text_states, list) or not any(
        isinstance(state, dict)
        and state.get("focusedClientPresent") is True
        and state.get("editable") is True
        for state in text_states
    ):
        raise M0Error("History/Downloads has no editable Ozone text state")
    _validate_history_downloads_proof(result.get("historyDownloads"))
    _validate_host_input(result.get("hostInput"))
    _require_redacted_serialization(result)
    backing_store = result.get("canvasBackingStore")
    frames = result.get("frameReports")
    if not isinstance(frames, list) or not frames:
        raise M0Error("History/Downloads frame reports are missing")
    last = frames[-1]
    if backing_store != {"width": last["width"], "height": last["height"]}:
        raise M0Error("History/Downloads backing store differs from final frame")


def _drain_relay_stdout(
    stream: Any,
    destination: deque[str],
    ready_lines: queue.Queue[str | None],
) -> None:
    for line in stream:
        text = line.rstrip()
        destination.append(text)
        if text:
            ready_lines.put(text)
    ready_lines.put(None)


def _take_early_result(
    result_queue: queue.Queue[dict[str, Any]], stage: str
) -> None:
    try:
        result = result_queue.get_nowait()
    except queue.Empty:
        return
    raise M0Error(
        f"History/Downloads smoke finished before {stage}: "
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
    """Poll only a frozen, read-only host witness between physical inputs."""

    last_state: object = None
    expression = "globalThis.__chromiumWasmM6HostHistoryDownloadsState || null"
    while time.monotonic() < deadline:
        if browser.poll() is not None:
            raise M0Error(
                f"host browser exited before {desired}: " + "\n".join(browser_stderr)
            )
        _take_early_result(result_queue, desired)
        # This fixed expression cannot focus, mutate a proxy, invoke an
        # export, or navigate Chromium. The only subsequent actions are CDP
        # trusted keyboard/pointer records.
        last_state = client.evaluate(expression)
        if isinstance(last_state, dict) and last_state.get("state") == desired:
            return last_state
        time.sleep(0.05)
    raise M0Error(
        f"History/Downloads smoke did not reach {desired}: "
        + json.dumps(last_state, sort_keys=True, separators=(",", ":"))
    )


def click_target(client: Any, state: dict[str, object], field: str) -> None:
    target = state.get(field)
    if not isinstance(target, dict):
        raise M0Error(f"History/Downloads state lacks {field}")
    x = target.get("clientX")
    y = target.get("clientY")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        raise M0Error(f"History/Downloads {field} client coordinates are invalid")
    # This is a physical Chrome DevTools mouse sequence. It cannot call a
    # Wasm export, browser command, or host navigation surface.
    client.dispatch_primary_click(float(x), float(y))


def dispatch_unmodified_enter(client: Any) -> None:
    """Dispatch a physical Enter pair, with no DOM navigation command."""

    for event_type in ("rawKeyDown", "keyUp"):
        params: dict[str, Any] = {
            "type": event_type,
            "key": "Enter",
            "code": "Enter",
            "windowsVirtualKeyCode": 13,
            "nativeVirtualKeyCode": 13,
            "modifiers": 0,
        }
        if event_type == "rawKeyDown":
            params["text"] = ""
            params["unmodifiedText"] = ""
        client.call("Input.dispatchKeyEvent", params)


def dispatch_address_transaction(
    client: Any,
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    result_queue: queue.Queue[dict[str, Any]],
    deadline: float,
    *,
    phase: str,
    text: str,
) -> None:
    wait_for_state(
        client,
        browser,
        browser_stderr,
        result_queue,
        f"awaiting-{phase}-https-ctrl-l",
        deadline,
    )
    client.dispatch_control_shortcut("KeyL", "l", 76)
    wait_for_state(
        client,
        browser,
        browser_stderr,
        result_queue,
        f"awaiting-{phase}-https-insert-text",
        deadline,
    )
    # Input.insertText supplies the one fixed, trusted DOM beforeinput record.
    # The value is never placed in host state/result JSON.
    client.call("Input.insertText", {"text": text})
    wait_for_state(
        client,
        browser,
        browser_stderr,
        result_queue,
        f"awaiting-{phase}-https-enter",
        deadline,
    )
    dispatch_unmodified_enter(client)


def wait_for_result(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    result_queue: queue.Queue[dict[str, Any]],
    deadline: float,
) -> dict[str, Any]:
    while True:
        if browser.poll() is not None:
            raise M0Error(
                "host browser exited before History/Downloads result: "
                + "\n".join(browser_stderr)
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M0Error(
                "History/Downloads browser timeout: " + "\n".join(browser_stderr)
            )
        try:
            return result_queue.get(timeout=min(0.1, remaining))
        except queue.Empty:
            continue


def _redact_for_diagnostics(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _redact_for_diagnostics(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_for_diagnostics(item) for item in value]
    if isinstance(value, str):
        result = value
        for raw in (FIRST_ADDRESS_TEXT, SECOND_ADDRESS_TEXT):
            result = result.replace(raw, "<redacted-url>")
        return result
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
    relay: subprocess.Popen[str] | None,
    relay_stderr: deque[str],
    relay_status: dict[str, Any] | None,
    runtime_result: dict[str, Any] | None,
) -> Path:
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / "chrome-browser-host-history-downloads-m6-failure.json"
    payload = {
        "schema_version": 1,
        "runner": "run_m6_wasm_browser_host_history_downloads_dom_smoke.py",
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
        "relay": {
            "return_code": relay.poll() if relay else None,
            "stderr_tail": list(relay_stderr),
            "status": relay_status,
        },
        "runtime_result": _redact_for_diagnostics(runtime_result),
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(_redact_for_diagnostics(payload), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run two trusted HTTPS visits plus BrowserView History/Downloads "
            "menu input through Chrome Wasm."
        )
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--module-name", default=DEFAULT_MODULE_NAME)
    parser.add_argument("--node", type=Path)
    parser.add_argument(
        "--relay-script",
        type=Path,
        default=REPO_ROOT / "tools/wasm/m5_wisp_test_server.js",
    )
    parser.add_argument("--diagnostics-dir", type=Path)
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--timeout", type=parse_timeout, default=120.0)
    args = parser.parse_args()
    if args.timeout < 5.0:
        parser.error("--timeout must be at least five seconds")
    if not MODULE_NAME_RE.fullmatch(args.module_name):
        parser.error("--module-name must contain only ASCII letters, digits, or _")

    out_dir = args.out_dir if args.out_dir.is_absolute() else REPO_ROOT / args.out_dir
    diagnostics_dir = args.diagnostics_dir or out_dir / "diagnostics"
    if not diagnostics_dir.is_absolute():
        diagnostics_dir = REPO_ROOT / diagnostics_dir
    relay_script = args.relay_script
    if not relay_script.is_absolute():
        relay_script = REPO_ROOT / relay_script
    relay_script = relay_script.resolve()

    server: HostHistoryDownloadsSmokeServer | None = None
    server_thread: threading.Thread | None = None
    browser: subprocess.Popen[str] | None = None
    client: Any = None
    browser_path: Path | None = None
    browser_version: str | None = None
    browser_stderr: deque[str] = deque(maxlen=300)
    browser_stderr_thread: threading.Thread | None = None
    relay: subprocess.Popen[str] | None = None
    relay_stdout: deque[str] = deque(maxlen=300)
    relay_stderr: deque[str] = deque(maxlen=300)
    relay_stdout_thread: threading.Thread | None = None
    relay_stderr_thread: threading.Thread | None = None
    relay_ready: controlled_https.RelayReady | None = None
    relay_status: dict[str, Any] | None = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    result: dict[str, Any] | None = None
    context: dict[str, object] | None = None
    stage = "check_artifacts"

    try:
        stage = "check_boundary"
        # The test executable carries the exact test-only root; retain the
        # regular M6 source-closure guard before loading host artifacts.
        check_boundary(out_dir)
        controlled_https.check_controlled_https_boundary(out_dir)
        for suffix in (".js", ".wasm"):
            artifact = out_dir / f"{args.module_name}{suffix}"
            if not artifact.is_file():
                raise M0Error(f"History/Downloads artifact is missing: {artifact}")
        verify_required_exports(out_dir / f"{args.module_name}.js")
        stage = "verify_test_artifacts"
        verify_no_private_key_pem_artifacts(out_dir, args.module_name)
        stage = "load_manifest"
        manifest = load_manifest()
        versions = manifest_versions(
            manifest, checked_output(["git", "rev-parse", "HEAD"])
        )
        context = print_context(
            "run_m6_wasm_browser_host_history_downloads_dom_smoke.py",
            manifest,
            case=CASE,
            scope=SCOPE,
            gn_args=manifest.get("m6_chrome_gn_args", manifest.get("gn_args")),
            module_name=args.module_name,
            host_browser_sandbox=not args.no_sandbox,
            runtime_arguments=[SMOKE_SWITCH, URL_SWITCH + "=" + CONTROLLED_ROOT_URL],
            transport="WISP v2.1 over the local controlled relay",
            h2_fixture_requests=2,
        )
        stage = "find_browser"
        browser_path, browser_version = find_browser(args.browser)
        print(
            f"{SENTINEL}:HOST_BROWSER "
            + json.dumps({"browser_version": browser_version}, sort_keys=True),
            flush=True,
        )
        stage = "find_node"
        node = find_node(args.node)
        if not relay_script.is_file():
            raise M0Error(f"History/Downloads relay script is missing: {relay_script}")

        token = secrets.token_urlsafe(24)
        result_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        stage = "create_host_server"
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
            name="chromium-wasm-m6-history-downloads-server",
            daemon=True,
        )
        server_thread.start()

        stage = "launch_relay"
        relay = subprocess.Popen(
            relay_command(node, relay_script, m5_host_origin(server)),
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        assert relay.stdout is not None
        assert relay.stderr is not None
        ready_lines: queue.Queue[str | None] = queue.Queue()
        relay_stdout_thread = threading.Thread(
            target=_drain_relay_stdout,
            args=(relay.stdout, relay_stdout, ready_lines),
            name="chromium-wasm-m6-history-downloads-relay-stdout",
            daemon=True,
        )
        relay_stdout_thread.start()
        relay_stderr_thread = threading.Thread(
            target=drain_stream,
            args=(relay.stderr, relay_stderr),
            name="chromium-wasm-m6-history-downloads-relay-stderr",
            daemon=True,
        )
        relay_stderr_thread.start()
        stage = "wait_for_relay_ready"
        relay_ready = controlled_https.wait_for_relay_ready(
            relay,
            ready_lines,
            relay_stderr,
            time.monotonic() + min(30.0, max(1.0, args.timeout - 1.0)),
        )
        print(f"{SENTINEL}:RELAY_READY", flush=True)

        url = smoke_url(
            server,
            token,
            versions,
            relay_ready=relay_ready,
            module_name=args.module_name,
            timeout_seconds=max(1.0, args.timeout - 1.0),
        )
        profile = tempfile.TemporaryDirectory(
            prefix="chromium-wasm-m6-host-history-downloads-"
        )
        debug_port = unused_loopback_port()
        stage = "launch_browser"
        command = browser_command(
            browser_path, profile.name, url, no_sandbox=args.no_sandbox
        )
        command[1:1] = [
            "--enable-logging=stderr",
            "--window-size=1280,800",
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
        browser_stderr_thread = threading.Thread(
            target=drain_stream,
            args=(browser.stderr, browser_stderr),
            name="chromium-wasm-m6-history-downloads-browser-stderr",
            daemon=True,
        )
        browser_stderr_thread.start()

        deadline = time.monotonic() + args.timeout
        stage = "connect_devtools"
        client = wait_for_page_client(debug_port, url.split("?", 1)[0], deadline)
        stage = "first_trusted_https"
        dispatch_address_transaction(
            client,
            browser,
            browser_stderr,
            result_queue,
            deadline,
            phase="first",
            text=FIRST_ADDRESS_TEXT,
        )
        stage = "wait_for_new_tab_target_after_first_fvp"
        state = wait_for_state(
            client,
            browser,
            browser_stderr,
            result_queue,
            "awaiting-trusted-dom-new-tab",
            deadline,
        )
        stage = "trusted_new_tab_pointer"
        click_target(client, state, "newTabTarget")

        stage = "second_trusted_https"
        dispatch_address_transaction(
            client,
            browser,
            browser_stderr,
            result_queue,
            deadline,
            phase="second",
            text=SECOND_ADDRESS_TEXT,
        )
        stage = "wait_for_first_menu_target_after_second_fvp"
        state = wait_for_state(
            client,
            browser,
            browser_stderr,
            result_queue,
            "awaiting-trusted-dom-menu-history",
            deadline,
        )
        stage = "trusted_first_menu_pointer"
        click_target(client, state, "firstMenuTarget")
        stage = "wait_for_history_target_after_menu_frame"
        state = wait_for_state(
            client,
            browser,
            browser_stderr,
            result_queue,
            "awaiting-trusted-dom-history",
            deadline,
        )
        stage = "trusted_history_pointer"
        click_target(client, state, "historyTarget")

        stage = "wait_for_second_menu_target_after_history_fvp"
        state = wait_for_state(
            client,
            browser,
            browser_stderr,
            result_queue,
            "awaiting-trusted-dom-menu-downloads",
            deadline,
        )
        stage = "trusted_second_menu_pointer"
        click_target(client, state, "secondMenuTarget")
        stage = "wait_for_downloads_target_after_menu_frame"
        state = wait_for_state(
            client,
            browser,
            browser_stderr,
            result_queue,
            "awaiting-trusted-dom-downloads",
            deadline,
        )
        stage = "trusted_downloads_pointer"
        click_target(client, state, "downloadsTarget")

        stage = "wait_for_result"
        result = wait_for_result(browser, browser_stderr, result_queue, deadline)
        stage = "validate_result"
        validate_result(result, expected_versions=versions)
        stage = "fetch_relay_status"
        assert relay_ready is not None
        relay_status = controlled_https.fetch_relay_status(
            relay_ready.transcript_url,
            timeout_seconds=min(10.0, max(1.0, deadline - time.monotonic())),
        )
        stage = "validate_relay_status"
        # This shared controlled-relay checker requires exactly two H2 M6 UI
        # fixture requests and exact a.test:443 WISP destinations.
        controlled_https.validate_relay_status(relay_status)
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
        if browser_stderr_thread is not None:
            browser_stderr_thread.join(timeout=1)
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
                relay=relay,
                relay_stderr=relay_stderr,
                relay_status=relay_status,
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
        if browser_stderr_thread is not None:
            browser_stderr_thread.join(timeout=1)
        if relay is not None:
            stop_browser(relay)
        if relay_stdout_thread is not None:
            relay_stdout_thread.join(timeout=1)
        if relay_stderr_thread is not None:
            relay_stderr_thread.join(timeout=1)
        if server is not None:
            server.shutdown()
            server.server_close()
        if server_thread is not None:
            server_thread.join(timeout=1)
        if profile is not None:
            profile.cleanup()


if __name__ == "__main__":
    sys.exit(main())
