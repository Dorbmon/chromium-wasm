#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the formal Target-6 continuous flow through trusted DOM/Ozone input.

The first phase keeps one Chrome Browser lifetime through controlled HTTPS,
new-tab/version/tab-switch/menu/Settings/close-B/reload/screenshot. It issues
only trusted CDP keyboard, Input.insertText, and pointer records against the
frozen host witness. After normal lifecycle close, the host outer document
navigates to a fresh page that launches and normally closes a restart Browser.
No runner path calls a Wasm navigation, command, menu, or Browser ABI.
"""

from __future__ import annotations

import argparse
import base64
import binascii
from collections import deque
import contextlib
import copy
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
import json
import math
import os
from pathlib import Path
import queue
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Sequence
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
from m3_content_server import compare_screenshots, decode_png
from m4_cdp import unused_loopback_port, wait_for_page_client
from m9_browser_cleanup import (
    BrowserStderrReader,
    RelayReadinessLatch,
    abort_browser_group,
    stop_browser_group,
)
from m9_server_cleanup import M9TrackingThreadingHTTPServer, shutdown_server_bounded
from m9_descriptor_snapshot import snapshot_regular_file, snapshot_regular_files
from run_browser_smoke import browser_command, find_browser
from run_content_shell_smoke import manifest_versions
from run_m5_wisp_smoke import (
    PRIVATE_KEY_PEM_MARKERS,
    find_node,
    materialized_wisp_relay_closure,
    m5_host_origin,
    relay_command,
    verify_optional_wisp_data_private_key_pem_artifact,
)
import run_m6_wasm_browser_controlled_https_smoke as controlled_https
import run_wasm_browser_view_smoke as browser_view_smoke


SENTINEL = "CHROMIUM_WASM_M6_CONTINUOUS_FLOW_DOM"
CASE = "browser_continuous_flow_target6_m6"
SCOPE = "formal-target-6-trusted-dom-one-browser-lifetime"
FLOW_PHASE = "flow"
RESTART_PHASE = "restart"
FLOW_SWITCH = "--wasm-browser-host-continuous-flow-smoke"
RESTART_SWITCH = "--wasm-browser-host-continuous-flow-restart-smoke"
URL_SWITCH = "--wasm-browser-controlled-https-url"
HTTPS_TEXT = "https://a.test/m5/m6-ui"
VERSION_TEXT = "chrome://version/"
DEFAULT_OUT_DIR = Path("out/wasm-chrome-m6")
DEFAULT_MODULE_NAME = "chrome_wasm_m6_https_test"
CONTROLLED_HTTPS_GN_TARGET = "//chrome:chrome_wasm_m6_https_test"
HOST_ROOT = "/__m6_browser_continuous_flow__"
MAX_RESULT_BYTES = 8 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024 * 1024
MAX_HOST_RESOURCE_BYTES = 4 * 1024 * 1024
MAX_FRAME_DIMENSION = 16384
MAX_SCREENSHOT_BYTES = 4 * 1024 * 1024
MAX_SCREENSHOT_BASE64_LENGTH = ((MAX_SCREENSHOT_BYTES + 2) // 3) * 4
CLEANUP_TIMEOUT_SECONDS = 5.0
CLEANUP_POLL_SECONDS = 0.05
MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_BYTE_IDENTITY_FIELDS = frozenset(("bytes", "sha256"))
_ARTIFACT_IDENTITY_FIELDS = frozenset(
    (
        "artifact_delivery",
        "artifact_source_provenance",
        "loader",
        "module_name",
        "wasm",
    )
)
ARTIFACT_SOURCE_PROVENANCE = "unverified"
ARTIFACT_DELIVERY = "immutable-in-memory-server-snapshot"
HOST_RESOURCE_FILES = {
    "host_html": "chrome_wasm_browser_continuous_flow_smoke.html",
    "host_js": "chrome_wasm_browser_continuous_flow_smoke_host.js",
    "text_input_js": "chrome_wasm_text_input.js",
    "pointer_input_js": "chrome_wasm_pointer_input.js",
}
_HOST_RESOURCE_FIELDS = frozenset(HOST_RESOURCE_FILES)
CONTROLLED_HTTPS_SCREENSHOT_CONTRACT = (
    Path(__file__).with_name("testdata")
    / "m6_controlled_https_screenshot_contract.json"
)

MARKERS = (
    "CHROMIUM_WASM_M6_CONTINUOUS:READY",
    "CHROMIUM_WASM_M6_CONTINUOUS:HTTPS_NAVIGATED",
    "CHROMIUM_WASM_M6_CONTINUOUS:VERSION_READY",
    "CHROMIUM_WASM_M6_CONTINUOUS:VERSION_NAVIGATED",
    "CHROMIUM_WASM_M6_CONTINUOUS:FIRST_TAB_SELECTED",
    "CHROMIUM_WASM_M6_CONTINUOUS:MENU_READY",
    "CHROMIUM_WASM_M6_CONTINUOUS:MENU_OPENED",
    "CHROMIUM_WASM_M6_CONTINUOUS:SETTINGS_NAVIGATED",
    "CHROMIUM_WASM_M6_CONTINUOUS:FIRST_TAB_RETURNED",
    "CHROMIUM_WASM_M6_CONTINUOUS:SECOND_TAB_CLOSED",
    "CHROMIUM_WASM_M6_CONTINUOUS:RELOAD_READY",
    "CHROMIUM_WASM_M6_CONTINUOUS:RELOADED",
    "CHROMIUM_WASM_M6_CONTINUOUS:PASS",
)
RESTART_MARKERS = (
    "CHROMIUM_WASM_M6_CONTINUOUS:RESTART_READY",
    "CHROMIUM_WASM_M6_CONTINUOUS:RESTART_CLOSING",
)


class ContinuousFlowServer(M9TrackingThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    module_name: str
    artifacts: dict[str, bytes]
    result_token: str
    result_queue: queue.Queue[tuple[str, dict[str, Any]]]
    result_lock: threading.Lock
    received_phases: set[str]
    html_bytes: bytes
    host_js_bytes: bytes
    text_input_js_bytes: bytes
    pointer_input_js_bytes: bytes
    host_resource_identity: dict[str, object]


class ContinuousFlowRequestHandler(BaseHTTPRequestHandler):
    server: ContinuousFlowServer

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

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path in (HOST_ROOT, f"{HOST_ROOT}/"):
            self._send_bytes(HTTPStatus.OK, "text/html; charset=utf-8", self.server.html_bytes)
            return
        static = {
            f"{HOST_ROOT}/chrome_wasm_browser_continuous_flow_smoke_host.js": (
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
        }.get(path)
        if static is not None:
            self._send_bytes(HTTPStatus.OK, static[0], static[1])
            return
        prefix = f"{HOST_ROOT}/artifacts/"
        if path.startswith(prefix):
            artifact_name = path[len(prefix) :]
            artifact = self.server.artifacts.get(artifact_name)
            if artifact is not None:
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
        path = urlsplit(self.path).path
        prefix = f"{HOST_ROOT}/result/{self.server.result_token}/"
        if not path.startswith(prefix):
            self._not_found()
            return
        phase = path[len(prefix) :]
        if phase not in (FLOW_PHASE, RESTART_PHASE) or "/" in phase:
            self._not_found()
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_RESULT_BYTES:
            self._send_bytes(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "text/plain; charset=utf-8",
                b"invalid result size\n",
            )
            return
        result = parse_result_payload(self.rfile.read(length), phase)
        if result is None:
            self._send_bytes(
                HTTPStatus.BAD_REQUEST,
                "text/plain; charset=utf-8",
                b"invalid continuous-flow result\n",
            )
            return
        if "hostResources" in result:
            self._send_bytes(
                HTTPStatus.BAD_REQUEST,
                "text/plain; charset=utf-8",
                b"client-supplied host resource identity is forbidden\n",
            )
            return
        result["hostResources"] = copy.deepcopy(self.server.host_resource_identity)
        with self.server.result_lock:
            if phase in self.server.received_phases:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"duplicate continuous-flow phase\n",
                )
                return
            self.server.received_phases.add(phase)
            try:
                self.server.result_queue.put_nowait((phase, result))
            except queue.Full:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"continuous-flow result queue is full\n",
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


def parse_result_payload(payload: bytes, phase: str) -> dict[str, Any] | None:
    try:
        result = json.loads(
            payload.decode("utf-8"), object_pairs_hook=_json_object_without_duplicate_keys
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    if (
        not isinstance(result, dict)
        or result.get("protocol") != 1
        or result.get("case") != CASE
        or result.get("scope") != SCOPE
        or result.get("phase") != phase
    ):
        return None
    return result


def _require_module_name(value: object, description: str) -> str:
    if type(value) is not str or not MODULE_NAME_RE.fullmatch(value):
        raise M0Error(
            f"continuous-flow {description} module name must contain only ASCII "
            "letters, digits, or _"
        )
    return value


def _snapshot_regular_file(
    path: Path, *, maximum_bytes: int, description: str
) -> bytes:
    """Capture one file through the shared no-follow ancestor walk."""

    return snapshot_regular_file(
        path,
        maximum_bytes=maximum_bytes,
        description=f"continuous-flow {description}",
    )


def _snapshot_reviewed_screenshot_baseline(path: Path) -> bytes:
    """Capture the one reviewed PNG used by this child before it launches."""

    return _snapshot_regular_file(
        path,
        maximum_bytes=MAX_SCREENSHOT_BYTES,
        description="reviewed controlled-HTTPS screenshot baseline",
    )


def validate_host_resource_snapshots(host_snapshots: object) -> dict[str, bytes]:
    """Validate the exact four immutable resources served by this host."""

    if (
        not isinstance(host_snapshots, dict)
        or set(host_snapshots) != _HOST_RESOURCE_FIELDS
        or any(type(contents) is not bytes for contents in host_snapshots.values())
    ):
        raise M0Error("continuous-flow host resource snapshots are invalid")
    snapshots = {
        name: bytes(host_snapshots[name]) for name in _HOST_RESOURCE_FIELDS
    }
    if any(
        not contents or len(contents) > MAX_HOST_RESOURCE_BYTES
        for contents in snapshots.values()
    ):
        raise M0Error("continuous-flow host resource snapshot is invalid")
    return snapshots


def snapshot_host_resources(host_dir: Path | None = None) -> dict[str, bytes]:
    """Capture all host inputs before constructing one continuous-flow server."""

    selected_host_dir = host_dir or Path(__file__).with_name("host")
    captured = snapshot_regular_files(
        selected_host_dir,
        tuple(HOST_RESOURCE_FILES.values()),
        maximum_bytes=MAX_HOST_RESOURCE_BYTES,
        description="continuous-flow host resource",
    )
    snapshots = {
        name: captured[filename]
        for name, filename in HOST_RESOURCE_FILES.items()
    }
    return validate_host_resource_snapshots(snapshots)


def host_resource_snapshot_identity(host_snapshots: object) -> dict[str, object]:
    """Return path-free byte identities for the exact served host resources."""

    snapshots = validate_host_resource_snapshots(host_snapshots)
    identity = {
        name: _byte_identity(snapshots[name]) for name in sorted(_HOST_RESOURCE_FIELDS)
    }
    return validate_host_resource_snapshot_identity(identity)


def create_server(
    host: str,
    port: int,
    out_dir: Path,
    token: str,
    result_queue: queue.Queue[tuple[str, dict[str, Any]]],
    *,
    module_name: str,
    host_dir: Path | None = None,
) -> ContinuousFlowServer:
    module_name = _require_module_name(module_name, "server")
    artifact_names = (f"{module_name}.js", f"{module_name}.wasm")
    artifacts = snapshot_regular_files(
        out_dir,
        artifact_names,
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="continuous-flow executable artifact",
    )
    host_snapshots = snapshot_host_resources(host_dir)
    server = ContinuousFlowServer((host, port), ContinuousFlowRequestHandler)
    server.module_name = module_name
    server.artifacts = artifacts
    server.result_token = token
    server.result_queue = result_queue
    server.result_lock = threading.Lock()
    server.received_phases = set()
    server.html_bytes = host_snapshots["host_html"]
    server.host_js_bytes = host_snapshots["host_js"]
    server.text_input_js_bytes = host_snapshots["text_input_js"]
    server.pointer_input_js_bytes = host_snapshots["pointer_input_js"]
    server.host_resource_identity = host_resource_snapshot_identity(host_snapshots)
    return server


def _byte_identity(contents: bytes) -> dict[str, object]:
    return {"bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}


def artifact_identity(
    server: ContinuousFlowServer, *, module_name: str
) -> dict[str, object]:
    module_name = _require_module_name(module_name, "artifact")
    if server.module_name != module_name:
        raise M0Error("continuous-flow artifact module name disagrees with server")
    try:
        loader = server.artifacts[f"{module_name}.js"]
        wasm = server.artifacts[f"{module_name}.wasm"]
    except KeyError as error:
        raise M0Error("continuous-flow server artifact snapshot is incomplete") from error
    return {
        "artifact_delivery": ARTIFACT_DELIVERY,
        "artifact_source_provenance": ARTIFACT_SOURCE_PROVENANCE,
        "loader": _byte_identity(loader),
        "module_name": module_name,
        "wasm": _byte_identity(wasm),
    }


def verify_no_private_key_pem_snapshot_artifacts(
    server: ContinuousFlowServer, *, module_name: str
) -> None:
    """Reject PEM private-key markers from the immutable served snapshots."""
    module_name = _require_module_name(module_name, "snapshot")
    for suffix in (".js", ".wasm"):
        artifact_name = f"{module_name}{suffix}"
        try:
            contents = server.artifacts[artifact_name]
        except KeyError as error:
            raise M0Error(
                "continuous-flow server artifact snapshot is incomplete"
            ) from error
        if type(contents) is not bytes:
            raise M0Error("continuous-flow server artifact snapshot is invalid")
        if any(marker in contents for marker in PRIVATE_KEY_PEM_MARKERS):
            raise M0Error(
                "continuous-flow artifact snapshot embeds a PEM private-key "
                f"header: {artifact_name}"
            )


def smoke_url(
    server: ContinuousFlowServer,
    token: str,
    versions: dict[str, str],
    *,
    relay_ready: controlled_https.RelayReady,
    artifact: dict[str, object],
    module_name: str,
    timeout_seconds: float,
) -> str:
    module_name = _require_module_name(module_name, "URL")
    validate_artifact_identity(
        artifact,
        expected_artifact_identity=artifact_identity(server, module_name=module_name),
    )
    wisp_endpoint = controlled_https.validate_controlled_wisp_endpoint(
        relay_ready.wisp_endpoint
    )
    controlled_https.validate_m6_ui_url(relay_ready.m6_ui_url)
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "token": token,
            "module": module_name,
            "phase": FLOW_PHASE,
            "timeoutMs": str(max(1000, min(180000, int(timeout_seconds * 1000)))),
            "versions": json.dumps(versions, sort_keys=True, separators=(",", ":")),
            "artifact": json.dumps(artifact, sort_keys=True, separators=(",", ":")),
            "wispEndpoint": wisp_endpoint,
            "fixtureUrl": HTTPS_TEXT,
        }
    )
    return f"http://{host}:{port}{HOST_ROOT}/?{query}"


def verify_required_exports(module_loader: bytes) -> None:
    try:
        loader = module_loader.decode("utf-8")
    except UnicodeDecodeError as error:
        raise M0Error(f"cannot decode continuous-flow module loader: {error}") from error
    for export in (
        'Module["_chromium_wasm_browser_host_key"]',
        'Module["_chromium_wasm_browser_host_text"]',
        'Module["_chromium_wasm_browser_host_pointer"]',
        'Module["_chromium_wasm_browser_host_pointer_exit"]',
        'Module["_chromium_wasm_browser_host_continuous_flow_check"]',
        'Module["_chromium_wasm_browser_host_continuous_flow_presented"]',
        'Module["_malloc"]',
        'Module["_free"]',
        'Module["ccall"]',
        'Module["HEAPU8"]',
    ):
        if export not in loader:
            raise M0Error(f"continuous-flow module lacks required export {export}")


def _require_equal(value: object, expected: object, description: str) -> None:
    if not browser_view_smoke._exact_json_value_equal(value, expected):
        raise M0Error(f"{description}: expected {expected!r}, got {value!r}")


def _require_exact_fields(
    value: object, expected: frozenset[str], description: str
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        actual = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise M0Error(
            f"continuous-flow {description} schema is invalid: expected "
            f"{sorted(expected)!r}, got {actual!r}"
        )
    return value


def _validate_byte_identity(value: object, description: str) -> None:
    identity = _require_exact_fields(value, _BYTE_IDENTITY_FIELDS, description)
    if type(identity.get("bytes")) is not int or identity["bytes"] < 1:
        raise M0Error(f"continuous-flow {description} byte count is invalid")
    sha256 = identity.get("sha256")
    if type(sha256) is not str or not SHA256_RE.fullmatch(sha256):
        raise M0Error(f"continuous-flow {description} SHA-256 is invalid")


def validate_host_resource_snapshot_identity(
    value: object,
    *,
    expected_host_resource_identity: dict[str, object] | None = None,
) -> dict[str, object]:
    """Validate the raw four-file identity captured by one server instance."""

    identity = _require_exact_fields(
        value, _HOST_RESOURCE_FIELDS, "host resource identity"
    )
    normalized: dict[str, object] = {}
    for name in sorted(_HOST_RESOURCE_FIELDS):
        snapshot = identity.get(name)
        _validate_byte_identity(snapshot, f"host resource {name}")
        assert isinstance(snapshot, dict)
        normalized[name] = {
            "bytes": snapshot["bytes"],
            "sha256": snapshot["sha256"],
        }
    if expected_host_resource_identity is not None:
        expected = validate_host_resource_snapshot_identity(
            expected_host_resource_identity
        )
        if not browser_view_smoke._exact_json_value_equal(normalized, expected):
            raise M0Error(
                "continuous-flow host resource identity disagrees with served "
                "snapshot"
            )
    return normalized


def validate_artifact_identity(
    value: object, *, expected_artifact_identity: dict[str, object]
) -> None:
    artifact = _require_exact_fields(
        value, _ARTIFACT_IDENTITY_FIELDS, "artifact identity"
    )
    if artifact.get("artifact_delivery") != ARTIFACT_DELIVERY:
        raise M0Error("continuous-flow artifact delivery is invalid")
    if artifact.get("artifact_source_provenance") != ARTIFACT_SOURCE_PROVENANCE:
        raise M0Error("continuous-flow artifact source provenance is invalid")
    _require_module_name(artifact.get("module_name"), "artifact")
    for field in ("loader", "wasm"):
        _validate_byte_identity(artifact.get(field), f"artifact {field}")
    if not browser_view_smoke._exact_json_value_equal(
        artifact, expected_artifact_identity
    ):
        raise M0Error("continuous-flow artifact identity disagrees with served snapshot")


def _validate_target(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise M0Error(f"continuous-flow {name} target is missing")
    for field in ("x", "y"):
        coordinate = value.get(field)
        if type(coordinate) is not int or not 0 <= coordinate < MAX_FRAME_DIMENSION:
            raise M0Error(f"continuous-flow {name} target {field} is invalid")
    for field in ("clientX", "clientY"):
        coordinate = value.get(field)
        if not isinstance(coordinate, (int, float)) or not 0 <= coordinate < 10000:
            raise M0Error(f"continuous-flow {name} target {field} is invalid")
    return value


def _validate_frame_after(proof: dict[str, Any], before: str, after: str) -> None:
    start = proof.get(before)
    finish = proof.get(after)
    if type(start) is not int or type(finish) is not int or start < 0 or finish <= start:
        raise M0Error(f"continuous-flow lacks strict frame ordering {before}->{after}")


def _validate_pointer_action(
    record: object, target: dict[str, object], event_type: str, buttons: int, index: int
) -> None:
    if not isinstance(record, dict):
        raise M0Error(f"continuous-flow pointer action {index} is invalid")
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
                f"continuous-flow pointer action {index} {field} is invalid"
            )


def _validate_text_transaction(transaction: object, phase: str, sequence: int) -> None:
    if not isinstance(transaction, dict):
        raise M0Error(f"continuous-flow {phase} text transaction is invalid")
    for field, expected in {
        "phase": phase,
        "adapterId": 1,
        "expectedSequence": sequence,
        "ctrlLComplete": True,
        "proxyFocused": True,
        "admissionCount": 1,
        "deliveryCount": 1,
        "deliverySequences": [sequence],
        "deliveryAccepted": True,
        "enterComplete": True,
        "rejected": False,
    }.items():
        if transaction.get(field) != expected:
            raise M0Error(f"continuous-flow {phase} text {field} is invalid")
    adapter = transaction.get("adapter")
    if not isinstance(adapter, dict) or "textareaValue" in adapter:
        raise M0Error(f"continuous-flow {phase} text metadata is invalid")
    expected_text = HTTPS_TEXT if phase == "https" else VERSION_TEXT
    before_input = adapter.get("beforeInputRecords")
    if not isinstance(before_input, list) or len(before_input) != 1:
        raise M0Error(f"continuous-flow {phase} beforeinput evidence is invalid")
    record = before_input[0]
    expected_before_input = {
        "inputType": "insertText",
        "dataOmitted": True,
        "dataUtf16Units": len(expected_text),
        "dataUtf8Bytes": len(expected_text.encode("utf-8")),
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
        raise M0Error(f"continuous-flow {phase} retained raw text")
    for field, expected in expected_before_input.items():
        if record.get(field) != expected:
            raise M0Error(f"continuous-flow {phase} beforeinput {field} is invalid")
    if adapter.get("browserTextDeliveryReports") != [
        {"action": 4, "sessionId": 0, "sequence": sequence, "accepted": True}
    ]:
        raise M0Error(f"continuous-flow {phase} action-4 delivery is invalid")
    ctrl_l = adapter.get("ctrlLRecords")
    expected_ctrl_l = [
        ("keydown", "ControlLeft"),
        ("keydown", "KeyL"),
        ("keyup", "KeyL"),
        ("keyup", "ControlLeft"),
    ]
    if not isinstance(ctrl_l, list) or len(ctrl_l) != len(expected_ctrl_l):
        raise M0Error(f"continuous-flow {phase} Ctrl+L evidence is invalid")
    for index, (event_type, code) in enumerate(expected_ctrl_l):
        item = ctrl_l[index]
        if not isinstance(item, dict) or any(
            item.get(field) != expected
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
            raise M0Error(f"continuous-flow {phase} Ctrl+L record is invalid")
    enter = adapter.get("enterRecords")
    if not isinstance(enter, list) or len(enter) != 2:
        raise M0Error(f"continuous-flow {phase} Enter evidence is invalid")
    for index, event_type in enumerate(("keydown", "keyup")):
        item = enter[index]
        if not isinstance(item, dict) or any(
            item.get(field) != expected
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
            raise M0Error(f"continuous-flow {phase} Enter record is invalid")
    if adapter.get("rejectedRecords") != [] or adapter.get("cleanupRecords") != []:
        raise M0Error(f"continuous-flow {phase} has rejected or cleanup text input")


def _validate_screenshot(
    result: dict[str, Any], proof: dict[str, Any], frames: list[dict[str, Any]],
    screenshot_contract: dict[str, Any],
) -> bytes:
    screenshot = result.get("screenshot")
    required = {
        "mimeType", "dataBase64", "width", "height", "frameId", "timestampMs",
        "observationSequence",
    }
    if not isinstance(screenshot, dict) or set(screenshot) != required:
        raise M0Error("continuous-flow screenshot metadata is invalid")
    if screenshot.get("mimeType") != "image/png":
        raise M0Error("continuous-flow screenshot is not PNG")
    data = screenshot.get("dataBase64")
    if not isinstance(data, str) or not data or len(data) > MAX_SCREENSHOT_BASE64_LENGTH:
        raise M0Error("continuous-flow screenshot base64 is invalid")
    try:
        png = base64.b64decode(data.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError) as error:
        raise M0Error("continuous-flow screenshot base64 is invalid") from error
    if not png or len(png) > MAX_SCREENSHOT_BYTES:
        raise M0Error("continuous-flow screenshot PNG is out of bounds")
    for field in ("width", "height", "frameId", "observationSequence"):
        if type(screenshot.get(field)) is not int or screenshot[field] < 1:
            raise M0Error(f"continuous-flow screenshot {field} is invalid")
    if (
        screenshot["width"] != screenshot_contract["width"]
        or screenshot["height"] != screenshot_contract["height"]
        or screenshot["frameId"] != proof.get("frameAfterSecondFvp")
        or screenshot["frameId"] <= proof.get("frameAtReloaded", -1)
        or screenshot["frameId"] <= proof.get("frameAtSecondFvp", -1)
    ):
        raise M0Error("continuous-flow screenshot is not after reload and phase-2 FVP")
    matching = [frame for frame in frames if frame["id"] == screenshot["frameId"]]
    if len(matching) != 1 or any(
        screenshot[field] != matching[0][field] for field in ("width", "height", "timestampMs")
    ):
        raise M0Error("continuous-flow screenshot does not match its frame")
    image = decode_png(png)
    if image.width != screenshot["width"] or image.height != screenshot["height"]:
        raise M0Error("continuous-flow screenshot PNG dimensions disagree")
    return png


def validate_flow_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
    expected_artifact_identity: dict[str, object],
    expected_host_resource_identity: dict[str, object],
    screenshot_contract: dict[str, Any],
) -> bytes:
    for field, expected in {
        "protocol": 1,
        "case": CASE,
        "scope": SCOPE,
        "phase": FLOW_PHASE,
        "status": "pass",
        "formalTarget6AcceptanceFlow": True,
        "m6ProductBreadthComplete": False,
        "runtimeExitCode": 0,
        "runtimeInitialized": True,
        "factorySettled": True,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "abort": None,
        "error": None,
    }.items():
        _require_equal(result.get(field), expected, f"continuous-flow result {field}")
    if result.get("processExitCode") not in (None, 0):
        raise M0Error("continuous-flow process exit disagrees with runtime")
    _require_equal(result.get("versions"), expected_versions, "continuous-flow versions")
    validate_artifact_identity(
        result.get("artifact"),
        expected_artifact_identity=expected_artifact_identity,
    )
    validate_host_resource_snapshot_identity(
        result.get("hostResources"),
        expected_host_resource_identity=expected_host_resource_identity,
    )
    for field in ("fatalErrors", "windowErrors", "unhandledRejections"):
        if not isinstance(result.get(field), list) or result[field]:
            raise M0Error(f"continuous-flow {field} is not empty")
    output = "\n".join(
        str(line) for name in ("stdout", "stderr") for line in result.get(name, [])
    )
    for marker in MARKERS:
        if marker not in output:
            raise M0Error(f"continuous-flow output is missing {marker}")
    proof = result.get("continuousFlow")
    if not isinstance(proof, dict):
        raise M0Error("continuous-flow proof is missing")
    for field in (
        "wispConfigured", "runtimeArgumentsConfigured", "configurationPrecededFactory",
        "readyObserved", "httpsNavigatedObserved", "versionReadyObserved",
        "versionNavigatedObserved", "firstTabSelectedObserved", "menuReadyObserved",
        "menuOpenedObserved", "settingsNavigatedObserved", "firstTabReturnedObserved",
        "secondTabClosedObserved", "reloadReadyObserved", "reloadedObserved",
        "firstFvpObserved", "secondFvpObserved", "check1Queued", "check2Queued",
        "check3Queued", "check4Queued", "check5Queued", "check6Queued",
        "finalPresentationQueued", "passObserved",
    ):
        if proof.get(field) is not True:
            raise M0Error(f"continuous-flow proof {field} is not true")
    if proof.get("timeoutObserved") is not False:
        raise M0Error("continuous-flow native watchdog fired")
    for before, after in (
        ("frameAtHttpsNavigated", "frameAfterHttpsNavigated"),
        ("frameAtFirstFvp", "frameAfterFirstFvp"),
        ("frameAtVersionReady", "frameAfterVersionReady"),
        ("frameAtVersionNavigated", "frameAfterVersionNavigated"),
        ("frameAtFirstTabSelected", "frameAfterFirstTabSelected"),
        ("frameAtMenuReady", "frameAfterMenuReady"),
        ("frameAtMenuOpened", "frameAfterMenuOpened"),
        ("frameAtSettingsNavigated", "frameAfterSettingsNavigated"),
        ("frameAtFirstTabReturned", "frameAfterFirstTabReturned"),
        ("frameAtReloadReady", "frameAfterReloadReady"),
        ("frameAtReloaded", "frameAfterReloaded"),
        ("frameAtSecondFvp", "frameAfterSecondFvp"),
    ):
        _validate_frame_after(proof, before, after)
    if proof["frameAfterFirstFvp"] <= proof["frameAtHttpsNavigated"]:
        raise M0Error("first Target-FVP frame was not after HTTPS marker")
    if proof["frameAfterSecondFvp"] <= proof["frameAtReloaded"]:
        raise M0Error("second Target-FVP frame was not after RELOADED marker")
    frames = result.get("frameReports")
    browser_view_smoke._validate_frame_reports(frames)
    assert isinstance(frames, list)
    browser_view_smoke._validate_readiness(
        result.get("readiness"), result.get("readinessReports")
    )
    browser_view_smoke._validate_focus_reports(result.get("ozoneFocusReports"))
    host_input = result.get("hostInput")
    if not isinstance(host_input, dict):
        raise M0Error("continuous-flow host input is missing")
    for field, expected in {
        "singlePersistentAction4Adapter": True,
        "action4SessionId": 0,
        "textAdapterDetachedAfterSecondSequence": True,
        "proxyTextEmpty": True,
        "reloadRejectedRecords": [],
        "reloadCleanupRecords": [],
    }.items():
        if host_input.get(field) != expected:
            raise M0Error(f"continuous-flow host input {field} is invalid")
    transactions = host_input.get("textTransactions")
    if not isinstance(transactions, list) or len(transactions) != 2:
        raise M0Error("continuous-flow does not retain two text transactions")
    _validate_text_transaction(transactions[0], "https", 1)
    _validate_text_transaction(transactions[1], "version", 2)
    targets = [
        ("newTabTarget", "newTabActionOffset"),
        ("switchFirstTarget", "switchFirstActionOffset"),
        ("switchSecondTarget", "switchSecondActionOffset"),
        ("menuTarget", "menuActionOffset"),
        ("settingsTarget", "settingsActionOffset"),
        ("returnFirstTarget", "returnFirstActionOffset"),
        ("closeSecondTarget", "closeSecondActionOffset"),
    ]
    pointer_records = host_input.get("pointerRecords")
    if not isinstance(pointer_records, list):
        raise M0Error("continuous-flow pointer records are missing")
    actions = [
        record for record in pointer_records
        if isinstance(record, dict) and record.get("type") in ("down", "up")
    ]
    if len(actions) != 14:
        raise M0Error("continuous-flow lacks exactly seven trusted pointer clicks")
    for index, (target_field, offset_field) in enumerate(targets):
        target = _validate_target(proof.get(target_field), target_field)
        if proof.get(offset_field) != index * 2:
            raise M0Error(f"continuous-flow {offset_field} is not ordered")
        _validate_pointer_action(actions[index * 2], target, "down", 1, index * 2)
        _validate_pointer_action(actions[index * 2 + 1], target, "up", 0, index * 2 + 1)
    ctrl_r = host_input.get("ctrlRRecords")
    expected_ctrl_r = [
        ("keydown", "ControlLeft"),
        ("keydown", "KeyR"),
        ("keyup", "KeyR"),
        ("keyup", "ControlLeft"),
    ]
    if not isinstance(ctrl_r, list) or len(ctrl_r) != len(expected_ctrl_r):
        raise M0Error("continuous-flow Ctrl+R evidence is invalid")
    for record, (event_type, code) in zip(ctrl_r, expected_ctrl_r):
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
            raise M0Error("continuous-flow Ctrl+R record is invalid")
    return _validate_screenshot(result, proof, frames, screenshot_contract)


def validate_restart_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
    expected_artifact_identity: dict[str, object],
    expected_host_resource_identity: dict[str, object],
) -> None:
    for field, expected in {
        "protocol": 1,
        "case": CASE,
        "scope": SCOPE,
        "phase": RESTART_PHASE,
        "status": "pass",
        "formalTarget6AcceptanceFlow": False,
        "m6ProductBreadthComplete": False,
        "outerPageFreshRestart": True,
        "runtimeExitCode": 0,
        "runtimeInitialized": True,
        "factorySettled": True,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "abort": None,
        "error": None,
    }.items():
        _require_equal(result.get(field), expected, f"restart result {field}")
    _require_equal(result.get("versions"), expected_versions, "restart versions")
    validate_artifact_identity(
        result.get("artifact"),
        expected_artifact_identity=expected_artifact_identity,
    )
    validate_host_resource_snapshot_identity(
        result.get("hostResources"),
        expected_host_resource_identity=expected_host_resource_identity,
    )
    for field in ("fatalErrors", "windowErrors", "unhandledRejections"):
        if not isinstance(result.get(field), list) or result[field]:
            raise M0Error(f"restart {field} is not empty")
    proof = result.get("continuousFlow")
    if not isinstance(proof, dict):
        raise M0Error("restart proof is missing")
    for field in (
        "restartReadyObserved", "restartPresentationQueued", "restartClosingObserved",
    ):
        if proof.get(field) is not True:
            raise M0Error(f"restart proof {field} is not true")
    _validate_frame_after(proof, "frameAtRestartReady", "frameAfterRestartReady")
    output = "\n".join(
        str(line) for name in ("stdout", "stderr") for line in result.get(name, [])
    )
    for marker in RESTART_MARKERS:
        if marker not in output:
            raise M0Error(f"restart output is missing {marker}")


def wait_for_state(
    client: Any,
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    results: dict[str, dict[str, Any]],
    result_queue: queue.Queue[tuple[str, dict[str, Any]]],
    desired: str,
    deadline: float,
) -> dict[str, object]:
    """Poll only a frozen read-only host witness before a trusted CDP input."""

    expression = "globalThis.__chromiumWasmM6ContinuousFlowState || null"
    last_state: object = None
    while time.monotonic() < deadline:
        if browser.poll() is not None:
            raise M0Error(f"host browser exited before {desired}: " + "\n".join(browser_stderr))
        _drain_results(result_queue, results)
        if results:
            raise M0Error(
                f"continuous-flow finished before {desired}: "
                + json.dumps(results, sort_keys=True, separators=(",", ":"))
            )
        try:
            last_state = client.evaluate(expression)
        except Exception as error:
            last_state = {"evaluationError": str(error)}
        if isinstance(last_state, dict) and last_state.get("state") == desired:
            return last_state
        time.sleep(0.05)
    raise M0Error(
        f"continuous-flow did not reach {desired}: "
        + json.dumps(last_state, sort_keys=True, separators=(",", ":"))
    )


def click_target(client: Any, state: dict[str, object], field: str) -> None:
    target = state.get(field)
    if not isinstance(target, dict):
        raise M0Error(f"continuous-flow state lacks {field}")
    x = target.get("clientX")
    y = target.get("clientY")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        raise M0Error(f"continuous-flow {field} client target is invalid")
    client.dispatch_primary_click(float(x), float(y))


def dispatch_unmodified_enter(client: Any) -> None:
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
    results: dict[str, dict[str, Any]],
    result_queue: queue.Queue[tuple[str, dict[str, Any]]],
    deadline: float,
    *,
    phase: str,
    text: str,
) -> None:
    wait_for_state(
        client, browser, browser_stderr, results, result_queue,
        f"awaiting-trusted-dom-{phase}-ctrl-l", deadline,
    )
    client.dispatch_control_shortcut("KeyL", "l", 76)
    wait_for_state(
        client, browser, browser_stderr, results, result_queue,
        f"awaiting-trusted-dom-{phase}-insert-text", deadline,
    )
    # Input.insertText creates the sole trusted DOM beforeinput record. It is
    # the fixed input text only; no result/state evaluation carries it back.
    client.call("Input.insertText", {"text": text})
    wait_for_state(
        client, browser, browser_stderr, results, result_queue,
        f"awaiting-trusted-dom-{phase}-enter", deadline,
    )
    dispatch_unmodified_enter(client)


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
            raise M0Error(f"continuous-flow result phase was duplicated: {phase}")
        results[phase] = result


def wait_for_phase_result(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    results: dict[str, dict[str, Any]],
    result_queue: queue.Queue[tuple[str, dict[str, Any]]],
    phase: str,
    deadline: float,
) -> dict[str, Any]:
    while time.monotonic() < deadline:
        _drain_results(result_queue, results)
        if phase in results:
            return results[phase]
        if browser.poll() is not None:
            raise M0Error(
                f"host browser exited before {phase} result: " + "\n".join(browser_stderr)
            )
        time.sleep(0.05)
    raise M0Error(f"continuous-flow did not post its {phase} result")


def _redact(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return value.replace(HTTPS_TEXT, "<redacted-url>").replace(
            VERSION_TEXT, "<redacted-url>"
        )
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
    results: dict[str, dict[str, Any]],
) -> Path:
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / "chrome-browser-continuous-flow-target6-failure.json"
    payload = {
        "schema_version": 1,
        "runner": "run_m6_wasm_browser_continuous_flow_dom_smoke.py",
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
        "results": results,
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(_redact(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def _relay_group_exists(relay: subprocess.Popen[str]) -> bool:
    """Return whether the relay's dedicated session still contains a process."""

    try:
        os.killpg(relay.pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError as error:
        raise M0Error(
            "cannot verify continuous-flow relay process-group absence after "
            "leader exit"
        ) from error


def _signal_relay_group(
    relay: subprocess.Popen[str], signal_number: int
) -> None:
    """Signal the relay group even when its leader has already exited."""

    try:
        os.killpg(relay.pid, signal_number)
    except ProcessLookupError:
        return
    except OSError as error:
        raise M0Error(
            "cannot signal continuous-flow relay process group during cleanup"
        ) from error


def _relay_reader_failure(
    reader: BrowserStderrReader, stream_name: str
) -> M0Error | None:
    if reader.error is not None:
        return M0Error(
            f"continuous-flow relay {stream_name} reader failed: {reader.error}"
        )
    if not reader.is_alive() and not reader.reached_eof:
        return M0Error(
            f"continuous-flow relay {stream_name} reader stopped before EOF"
        )
    return None


def _relay_readers_failure(
    stdout_reader: BrowserStderrReader, stderr_reader: BrowserStderrReader
) -> M0Error | None:
    for reader, stream_name in (
        (stdout_reader, "stdout"),
        (stderr_reader, "stderr"),
    ):
        failure = _relay_reader_failure(reader, stream_name)
        if failure is not None:
            return failure
    return None


def _wait_for_relay_cleanup(
    relay: subprocess.Popen[str],
    readers: Sequence[BrowserStderrReader],
    timeout: float,
) -> tuple[bool, BaseException | None]:
    """Wait for leader, both output EOFs, and process-group absence together."""

    deadline = time.monotonic() + timeout
    while True:
        try:
            group_exists = _relay_group_exists(relay)
        except BaseException as error:
            # Still permit the caller's SIGKILL escalation after a failed
            # signal-zero probe; this is never treated as cleanup success.
            return False, error
        if (
            relay.poll() is not None
            and not any(reader.is_alive() for reader in readers)
            and not group_exists
        ):
            return True, None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False, None
        alive_readers = [reader for reader in readers if reader.is_alive()]
        if alive_readers:
            for reader in alive_readers:
                reader.join(timeout=min(CLEANUP_POLL_SECONDS, remaining))
        else:
            time.sleep(min(CLEANUP_POLL_SECONDS, remaining))


def _close_relay_reader_after_cleanup(
    reader: BrowserStderrReader,
) -> BaseException | None:
    """Close only a reader that can no longer be blocked in a pipe read."""

    if reader.is_alive():
        return None
    try:
        if reader.started:
            reader.close_after_reader_stops()
        else:
            reader.close_unstarted_pipe()
    except BaseException as error:
        return error
    return None


def _close_relay_readers_after_cleanup(
    readers: Sequence[BrowserStderrReader],
) -> BaseException | None:
    close_error: BaseException | None = None
    for reader in readers:
        error = _close_relay_reader_after_cleanup(reader)
        if close_error is None and error is not None:
            close_error = error
    return close_error


def stop_relay_group(
    relay: subprocess.Popen[str],
    stdout_reader: BrowserStderrReader,
    stderr_reader: BrowserStderrReader,
) -> None:
    """Stop the relay and prove both inherited output paths have completed.

    The controlled-flow relay owns a different session from its Python runner.
    A reaped leader is therefore insufficient: a descendant can retain either
    pipe or remain in that session. SIGKILL is failure-only because it cannot
    prove the relay's normal shutdown path ran.
    """

    readers = (stdout_reader, stderr_reader)
    if not all(reader.started for reader in readers):
        raise M0Error("continuous-flow relay output reader was never started")

    first_problem: BaseException | None = None
    try:
        _signal_relay_group(relay, signal.SIGTERM)
    except BaseException as error:
        first_problem = error
    cooperative_complete = False
    if first_problem is None:
        cooperative_complete, first_problem = _wait_for_relay_cleanup(
            relay, readers, CLEANUP_TIMEOUT_SECONDS
        )
    if cooperative_complete:
        close_problem = _close_relay_readers_after_cleanup(readers)
        reader_problem = _relay_readers_failure(stdout_reader, stderr_reader)
        if first_problem is not None:
            raise M0Error("cannot verify continuous-flow relay cleanup") from first_problem
        if close_problem is not None:
            raise M0Error("could not close stopped continuous-flow relay pipe") from close_problem
        if reader_problem is not None:
            raise reader_problem
        return

    # A failed first probe cannot suppress the emergency group kill. The
    # resulting forced path is always a failed observation, even if it does
    # remove every remaining process and closes both pipes.
    kill_problem: BaseException | None = None
    try:
        _signal_relay_group(relay, signal.SIGKILL)
    except BaseException as error:
        kill_problem = error
    forced_complete, forced_wait_problem = _wait_for_relay_cleanup(
        relay, readers, CLEANUP_TIMEOUT_SECONDS
    )
    close_problem = _close_relay_readers_after_cleanup(readers)
    reader_problem = _relay_readers_failure(stdout_reader, stderr_reader)
    root_problem = first_problem or kill_problem or forced_wait_problem or reader_problem
    if not forced_complete:
        raise M0Error(
            "continuous-flow relay process group or output readers did not stop "
            "after SIGTERM and SIGKILL"
        ) from root_problem
    if close_problem is not None:
        raise M0Error("could not close stopped continuous-flow relay pipe") from close_problem
    if root_problem is not None:
        raise M0Error("cannot verify continuous-flow relay cleanup") from root_problem
    raise M0Error(
        "continuous-flow relay cleanup required SIGKILL; normal relay shutdown "
        "cannot be proven"
    )


def abort_relay_group(
    relay: subprocess.Popen[str], readers: Sequence[BrowserStderrReader]
) -> None:
    """Best-effort failure cleanup for a relay without clean evidence."""

    started_readers = tuple(reader for reader in readers if reader.started)
    first_problem: BaseException | None = None
    try:
        _signal_relay_group(relay, signal.SIGTERM)
    except BaseException as error:
        first_problem = error
    cooperative_complete = False
    if first_problem is None:
        cooperative_complete, first_problem = _wait_for_relay_cleanup(
            relay, started_readers, CLEANUP_TIMEOUT_SECONDS
        )
    if cooperative_complete:
        kill_problem = None
        forced_complete = True
        forced_wait_problem = None
    else:
        try:
            _signal_relay_group(relay, signal.SIGKILL)
            kill_problem = None
        except BaseException as error:
            kill_problem = error
        forced_complete, forced_wait_problem = _wait_for_relay_cleanup(
            relay, started_readers, CLEANUP_TIMEOUT_SECONDS
        )

    close_problem = _close_relay_readers_after_cleanup(readers)
    reader_problem: BaseException | None = None
    for reader, stream_name in zip(readers, ("stdout", "stderr")):
        if reader.started:
            reader_problem = _relay_reader_failure(reader, stream_name)
            if reader_problem is not None:
                break
    root_problem = first_problem or kill_problem or forced_wait_problem or reader_problem
    if not forced_complete:
        raise M0Error(
            "continuous-flow relay abort cleanup could not stop the process group"
        ) from root_problem
    if close_problem is not None:
        raise M0Error("could not close continuous-flow relay pipe during abort") from close_problem
    if root_problem is not None:
        raise M0Error("cannot verify continuous-flow relay abort cleanup") from root_problem


def _run_cleanup_action(
    cleanup_error: BaseException | None, action: Callable[[], object]
) -> BaseException | None:
    """Run every teardown action while retaining the first failure."""

    try:
        action()
    except BaseException as error:
        if cleanup_error is None:
            return error
    return cleanup_error


def _join_continuous_flow_server(thread: threading.Thread) -> None:
    thread.join(timeout=CLEANUP_TIMEOUT_SECONDS)
    if thread.is_alive():
        raise M0Error("continuous-flow host server did not stop")


def _cleanup_continuous_flow_server(
    *,
    server: ContinuousFlowServer | None,
    server_thread: threading.Thread | None,
    server_thread_started: bool,
) -> BaseException | None:
    """Boundedly drain the server before a continuous-flow pass is visible."""

    cleanup_error: BaseException | None = None
    if server is not None:
        if server_thread_started:
            cleanup_error = _run_cleanup_action(
                cleanup_error,
                lambda: shutdown_server_bounded(
                    server,
                    timeout=CLEANUP_TIMEOUT_SECONDS,
                    description="continuous-flow host server",
                ),
            )
        cleanup_error = _run_cleanup_action(cleanup_error, server.server_close)
    if server_thread_started and server_thread is not None:
        cleanup_error = _run_cleanup_action(
            cleanup_error, lambda: _join_continuous_flow_server(server_thread)
        )
    if server is not None:
        cleanup_error = _run_cleanup_action(
            cleanup_error,
            lambda: server.join_request_handlers(
                timeout=CLEANUP_TIMEOUT_SECONDS,
                description="continuous-flow host server",
            ),
        )
    return cleanup_error


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the formal Target-6 trusted-DOM continuous Chrome flow."
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--module-name", default=DEFAULT_MODULE_NAME)
    parser.add_argument("--host-dir", type=Path)
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
    if args.timeout < 10.0:
        parser.error("--timeout must be at least ten seconds")
    if not MODULE_NAME_RE.fullmatch(args.module_name):
        parser.error("--module-name must contain only ASCII letters, digits, or _")

    out_dir = args.out_dir if args.out_dir.is_absolute() else REPO_ROOT / args.out_dir
    host_dir = args.host_dir
    if host_dir is not None and not host_dir.is_absolute():
        host_dir = REPO_ROOT / host_dir
    diagnostics_dir = args.diagnostics_dir or out_dir / "diagnostics"
    if not diagnostics_dir.is_absolute():
        diagnostics_dir = REPO_ROOT / diagnostics_dir
    relay_script = args.relay_script if args.relay_script.is_absolute() else REPO_ROOT / args.relay_script

    server: ContinuousFlowServer | None = None
    server_thread: threading.Thread | None = None
    server_thread_started = False
    browser: subprocess.Popen[str] | None = None
    client: Any = None
    browser_path: Path | None = None
    browser_version: str | None = None
    browser_stderr: deque[str] = deque(maxlen=300)
    browser_stderr_reader: BrowserStderrReader | None = None
    relay: subprocess.Popen[str] | None = None
    relay_stdout: deque[str] = deque(maxlen=300)
    relay_stderr: deque[str] = deque(maxlen=300)
    relay_stdout_reader: BrowserStderrReader | None = None
    relay_stderr_reader: BrowserStderrReader | None = None
    relay_fixture_stack: contextlib.ExitStack | None = None
    relay_ready: controlled_https.RelayReady | None = None
    relay_status: dict[str, Any] | None = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    results: dict[str, dict[str, Any]] = {}
    context: dict[str, object] | None = None
    artifact: dict[str, object] | None = None
    stage = "check_artifacts"
    primary_error: BaseException | None = None
    client_closed = False
    browser_cleanup_complete = False
    relay_cleanup_complete = False
    server_cleanup_complete = False
    profile_cleanup_complete = False

    try:
        stage = "check_boundary"
        check_boundary(out_dir)
        controlled_https.check_controlled_https_boundary(out_dir)
        token = secrets.token_urlsafe(24)
        result_queue: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue(maxsize=2)
        stage = "snapshot_server_inputs"
        server = create_server(
            "127.0.0.1",
            0,
            out_dir,
            token,
            result_queue,
            module_name=args.module_name,
            host_dir=host_dir,
        )
        artifact = artifact_identity(server, module_name=args.module_name)
        verify_required_exports(server.artifacts[f"{args.module_name}.js"])
        verify_no_private_key_pem_snapshot_artifacts(
            server, module_name=args.module_name
        )
        stage = "verify_optional_data_artifact"
        verify_optional_wisp_data_private_key_pem_artifact(
            out_dir, args.module_name
        )
        screenshot_contract = controlled_https.load_controlled_https_screenshot_contract()
        baseline_path = CONTROLLED_HTTPS_SCREENSHOT_CONTRACT.with_name(
            str(screenshot_contract["baseline"])
        )
        stage = "snapshot_reviewed_baseline"
        baseline_png = _snapshot_reviewed_screenshot_baseline(baseline_path)

        stage = "load_manifest"
        manifest = load_manifest()
        versions = manifest_versions(manifest, checked_output(["git", "rev-parse", "HEAD"]))
        context = print_context(
            "run_m6_wasm_browser_continuous_flow_dom_smoke.py",
            manifest,
            case=CASE,
            scope=SCOPE,
            gn_args=manifest.get("m6_chrome_gn_args", manifest.get("gn_args")),
            artifact=artifact,
            module_name=args.module_name,
            host_browser_sandbox=not args.no_sandbox,
            runtime_arguments=[FLOW_SWITCH, URL_SWITCH + "=" + HTTPS_TEXT],
            restart_runtime_arguments=[RESTART_SWITCH],
            transport="WISP v2.1 over local controlled relay",
            h2_fixture_requests=2,
            screenshot_baseline=str(baseline_path),
        )
        stage = "find_browser"
        browser_path, browser_version = find_browser(args.browser)
        stage = "find_node"
        node = find_node(args.node)

        assert artifact is not None
        stage = "serve_host_server"
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m6-continuous-flow-server",
            daemon=True,
        )
        server_thread.start()
        server_thread_started = True

        stage = "snapshot_relay_closure"
        relay_fixture_stack = contextlib.ExitStack()
        materialized_relay_script = relay_fixture_stack.enter_context(
            materialized_wisp_relay_closure(relay_script)
        )
        stage = "launch_relay"
        relay = subprocess.Popen(
            relay_command(node, materialized_relay_script, m5_host_origin(server)),
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        assert relay.stdout is not None and relay.stderr is not None
        ready_lines = RelayReadinessLatch()
        relay_stdout_reader = BrowserStderrReader(
            relay.stdout,
            relay_stdout,
            name="chromium-wasm-m6-continuous-flow-relay-stdout",
            on_line=ready_lines.put,
            on_eof=lambda: ready_lines.put(None),
        )
        relay_stderr_reader = BrowserStderrReader(
            relay.stderr,
            relay_stderr,
            name="chromium-wasm-m6-continuous-flow-relay-stderr",
        )
        # Construct both wrappers before either Thread.start() call. A
        # partially failed start can then close the unstarted pipe only after
        # the started reader has reached a terminal state.
        relay_stdout_reader.start()
        relay_stderr_reader.start()
        stage = "wait_for_relay"
        relay_ready = controlled_https.wait_for_relay_ready(
            relay,
            ready_lines,
            relay_stderr,
            time.monotonic() + min(30.0, max(1.0, args.timeout - 1.0)),
        )

        url = smoke_url(
            server,
            token,
            versions,
            relay_ready=relay_ready,
            artifact=artifact,
            module_name=args.module_name,
            timeout_seconds=max(1.0, args.timeout - 1.0),
        )
        profile = tempfile.TemporaryDirectory(prefix="chromium-wasm-m6-continuous-flow-")
        debug_port = unused_loopback_port()
        stage = "launch_browser"
        command = browser_command(browser_path, profile.name, url, no_sandbox=args.no_sandbox)
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
        browser_stderr_reader = BrowserStderrReader(
            browser.stderr,
            browser_stderr,
            name="chromium-wasm-m6-continuous-flow-browser-stderr",
        )
        browser_stderr_reader.start()
        deadline = time.monotonic() + args.timeout
        stage = "connect_devtools"
        client = wait_for_page_client(debug_port, url.split("?", 1)[0], deadline)

        stage = "trusted_https_transaction"
        dispatch_address_transaction(
            client, browser, browser_stderr, results, result_queue, deadline,
            phase="https", text=HTTPS_TEXT,
        )
        stage = "trusted_new_tab"
        state = wait_for_state(
            client, browser, browser_stderr, results, result_queue,
            "awaiting-trusted-dom-new-tab", deadline,
        )
        click_target(client, state, "newTabTarget")
        stage = "trusted_version_transaction"
        dispatch_address_transaction(
            client, browser, browser_stderr, results, result_queue, deadline,
            phase="version", text=VERSION_TEXT,
        )
        stage = "trusted_switch_a"
        state = wait_for_state(
            client, browser, browser_stderr, results, result_queue,
            "awaiting-trusted-dom-switch-a", deadline,
        )
        click_target(client, state, "switchFirstTarget")
        stage = "trusted_switch_b"
        state = wait_for_state(
            client, browser, browser_stderr, results, result_queue,
            "awaiting-trusted-dom-switch-b", deadline,
        )
        click_target(client, state, "switchSecondTarget")
        stage = "trusted_menu"
        state = wait_for_state(
            client, browser, browser_stderr, results, result_queue,
            "awaiting-trusted-dom-menu", deadline,
        )
        click_target(client, state, "menuTarget")
        stage = "trusted_settings"
        state = wait_for_state(
            client, browser, browser_stderr, results, result_queue,
            "awaiting-trusted-dom-settings", deadline,
        )
        click_target(client, state, "settingsTarget")
        stage = "trusted_return_a"
        state = wait_for_state(
            client, browser, browser_stderr, results, result_queue,
            "awaiting-trusted-dom-return-a", deadline,
        )
        click_target(client, state, "returnFirstTarget")
        stage = "trusted_close_b"
        state = wait_for_state(
            client, browser, browser_stderr, results, result_queue,
            "awaiting-trusted-dom-close-b", deadline,
        )
        click_target(client, state, "closeSecondTarget")
        stage = "trusted_reload"
        wait_for_state(
            client, browser, browser_stderr, results, result_queue,
            "awaiting-trusted-dom-ctrl-r", deadline,
        )
        client.dispatch_control_shortcut("KeyR", "r", 82)

        stage = "wait_for_flow_result"
        flow_result = wait_for_phase_result(
            browser, browser_stderr, results, result_queue, FLOW_PHASE, deadline
        )
        stage = "validate_flow_result"
        actual_png = validate_flow_result(
            flow_result,
            expected_versions=versions,
            expected_artifact_identity=artifact,
            expected_host_resource_identity=server.host_resource_identity,
            screenshot_contract=screenshot_contract,
        )
        stage = "compare_reviewed_baseline"
        comparison = compare_screenshots(
            actual_png,
            baseline_png,
            channel_tolerance=int(screenshot_contract["channel_tolerance"]),
            maximum_different_pixel_ratio=float(
                screenshot_contract["maximum_different_pixel_ratio"]
            ),
        )
        if not comparison.matches:
            raise M0Error(
                "final single-A reload screenshot differs from the reviewed baseline: "
                + json.dumps(comparison.as_dict(), sort_keys=True, separators=(",", ":"))
            )

        stage = "wait_for_outer_restart_result"
        restart_result = wait_for_phase_result(
            browser, browser_stderr, results, result_queue, RESTART_PHASE, deadline
        )
        stage = "validate_outer_restart_result"
        validate_restart_result(
            restart_result,
            expected_versions=versions,
            expected_artifact_identity=artifact,
            expected_host_resource_identity=server.host_resource_identity,
        )
        stage = "validate_relay"
        assert relay_ready is not None
        relay_status = controlled_https.fetch_relay_status(
            relay_ready.transcript_url,
            timeout_seconds=min(10.0, max(1.0, deadline - time.monotonic())),
        )
        controlled_https.validate_relay_status(relay_status)

        # Do not expose a passing continuous-flow record until every process
        # session, diagnostic pipe, and HTTP handler owned by this child has
        # reached a bounded terminal state. The M9 parent can prove only this
        # Python child exited, so the child itself owns this stronger evidence.
        stage = "cleanup_before_pass"
        if client is not None:
            client.close()
            client_closed = True
        if browser is not None:
            if browser_stderr_reader is None:
                raise M0Error("continuous-flow browser stderr reader is missing")
            stop_browser_group(browser, browser_stderr_reader)
            browser_cleanup_complete = True
        if relay is not None:
            if relay_stdout_reader is None or relay_stderr_reader is None:
                raise M0Error("continuous-flow relay output readers are missing")
            stop_relay_group(relay, relay_stdout_reader, relay_stderr_reader)
            relay_cleanup_complete = True
        server_cleanup_error = _cleanup_continuous_flow_server(
            server=server,
            server_thread=server_thread,
            server_thread_started=server_thread_started,
        )
        if server_cleanup_error is not None:
            raise server_cleanup_error
        server_cleanup_complete = True
        if profile is not None:
            profile.cleanup()
            profile_cleanup_complete = True
        print(
            f"{SENTINEL}:SCREENSHOT "
            + json.dumps(comparison.as_dict(), sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        print(
            f"{SENTINEL}:FLOW_RESULT "
            + json.dumps(_redact(flow_result), sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        print(
            f"{SENTINEL}:RESTART_RESULT "
            + json.dumps(_redact(restart_result), sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        print(f"{SENTINEL}:PASS", flush=True)
        return 0
    except (M0Error, OSError, KeyError, TypeError, ValueError) as error:
        primary_error = error
        try:
            diagnostic = write_failure_diagnostics(
                diagnostics_dir,
                stage=stage,
                error=error,
                context=context,
                browser_path=browser_path,
                browser_version=browser_version,
                browser=browser,
                browser_stderr=browser_stderr,
                relay=relay,
                relay_stderr=relay_stderr,
                relay_status=relay_status,
                results=results,
            )
            print(f"{SENTINEL}:DIAGNOSTICS " + json.dumps({"path": str(diagnostic)}), file=sys.stderr)
        except (OSError, TypeError, ValueError) as diagnostic_error:
            print(f"{SENTINEL}:DIAGNOSTICS_FAIL reason={diagnostic_error}", file=sys.stderr)
        print(f"{SENTINEL}:FAIL reason={error}", file=sys.stderr, flush=True)
        return 1
    except BaseException as error:
        primary_error = error
        raise
    finally:
        cleanup_error: BaseException | None = None
        if client is not None and not client_closed:
            cleanup_error = _run_cleanup_action(cleanup_error, client.close)
        if browser is not None and not browser_cleanup_complete:
            cleanup_error = _run_cleanup_action(
                cleanup_error,
                lambda: abort_browser_group(browser, browser_stderr_reader),
            )
        if relay is not None and not relay_cleanup_complete:
            relay_readers = tuple(
                reader
                for reader in (relay_stdout_reader, relay_stderr_reader)
                if reader is not None
            )
            cleanup_error = _run_cleanup_action(
                cleanup_error,
                lambda: abort_relay_group(relay, relay_readers),
            )
        if relay_fixture_stack is not None:
            cleanup_error = _run_cleanup_action(
                cleanup_error, relay_fixture_stack.close
            )
        if not server_cleanup_complete:
            server_error = _cleanup_continuous_flow_server(
                server=server,
                server_thread=server_thread,
                server_thread_started=server_thread_started,
            )
            if cleanup_error is None and server_error is not None:
                cleanup_error = server_error
        if profile is not None and not profile_cleanup_complete:
            cleanup_error = _run_cleanup_action(cleanup_error, profile.cleanup)
        if primary_error is None and cleanup_error is not None:
            raise cleanup_error


if __name__ == "__main__":
    sys.exit(main())
