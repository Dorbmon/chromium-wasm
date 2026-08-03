#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Server and result validation helpers for the M3 Content Shell gate."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
import json
import math
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import queue
import struct
import threading
from typing import Any
from urllib.parse import urlencode, urlsplit
import zlib

from m0_common import M0Error, REPO_ROOT


M3_CASE = "content_shell_m3"
M4_CASE = "ozone_pointer_m4"
M4_SELECTION_CASE = "ozone_selection_m4"
M4_WHEEL_CASE = "ozone_wheel_m4"
M4_KEYBOARD_CASE = "ozone_keyboard_m4"
M4_PRINTABLE_KEY_CASE = "ozone_printable_key_m4"
M4_BACKSPACE_CASE = "ozone_backspace_m4"
M4_FOCUS_CASE = "ozone_focus_m4"
M4_IME_BRIDGE_CASE = "ozone_ime_bridge_m4"
M3_PROTOCOL = 1
M3_WIDTH = 800
M3_HEIGHT = 600
M3_MINIMUM_RUNTIME_MS = 3000
M3_MINIMUM_TIMER_TICKS = 60
M3_MINIMUM_ANIMATION_FRAMES = 30
M3_MAXIMUM_TIMER_GAP_MS = 250
M3_MAX_RESULT_BYTES = 8 * 1024 * 1024
M3_HOST_DIR = Path(__file__).with_name("host")
M3_TESTDATA_DIR = Path(__file__).with_name("testdata")
M3_AHEM_FONT = (
    REPO_ROOT / "third_party" / "blink" / "web_tests" / "resources"
    / "Ahem.woff2"
)
M3_FONT_MARKER = "__M3_AHEM_WOFF2_BASE64__"
M3_SCREENSHOT_CONTRACT = (
    M3_TESTDATA_DIR / "m3_content_screenshot_contract.json"
)
M4_POINTER_FIXTURE = M3_TESTDATA_DIR / "m4_ozone_input_page.html"
M4_SELECTION_FIXTURE = M3_TESTDATA_DIR / "m4_ozone_selection_page.html"
M4_WHEEL_FIXTURE = M3_TESTDATA_DIR / "m4_ozone_wheel_page.html"
M4_KEYBOARD_FIXTURE = M3_TESTDATA_DIR / "m4_ozone_keyboard_page.html"
M4_PRINTABLE_KEY_FIXTURE = (
    M3_TESTDATA_DIR / "m4_ozone_printable_key_page.html"
)
M4_BACKSPACE_FIXTURE = M3_TESTDATA_DIR / "m4_ozone_backspace_page.html"
M4_FOCUS_FIXTURE = M3_TESTDATA_DIR / "m4_ozone_focus_page.html"
M4_IME_BRIDGE_FIXTURE = M3_TESTDATA_DIR / "m4_ozone_ime_bridge_page.html"

SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "X-Content-Type-Options": "nosniff",
}

CONTENT_TYPES = {
    ".data": "application/octet-stream",
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".map": "application/json",
    ".wasm": "application/wasm",
    ".woff2": "font/woff2",
}


def fixture_html() -> str:
    return (M3_TESTDATA_DIR / "m3_content_page.html").read_text(
        encoding="utf-8"
    )


def build_fixture_data_url(
    template: str | None = None,
    font_bytes: bytes | None = None,
) -> str:
    """Build the exact data: URL navigated by Content Shell in the M3 gate."""

    if template is None:
        template = fixture_html()
    if template.count(M3_FONT_MARKER) != 1:
        raise M0Error("M3 fixture must contain exactly one Ahem marker")
    if font_bytes is None:
        font_bytes = M3_AHEM_FONT.read_bytes()
    if not font_bytes:
        raise M0Error("M3 Ahem fixture font is empty")
    encoded_font = base64.b64encode(font_bytes).decode("ascii")
    expanded = template.replace(M3_FONT_MARKER, encoded_font)
    encoded_page = base64.b64encode(expanded.encode("utf-8")).decode("ascii")
    return f"data:text/html;charset=utf-8;base64,{encoded_page}"


@dataclass
class M3ServerState:
    token: str
    out_dir: Path
    module_name: str
    result_queue: queue.Queue[dict[str, Any]]
    verbose: bool = False
    result_received: bool = False
    result_lock: threading.Lock = field(default_factory=threading.Lock)


def accept_result(
    state: M3ServerState, result: dict[str, Any]
) -> bool:
    with state.result_lock:
        if state.result_received:
            return False
        state.result_received = True
        state.result_queue.put_nowait(result)
    return True


def _artifact_for_request(
    state: M3ServerState, request_path: str
) -> Path | None:
    prefix = "/__m3__/artifacts/"
    if not request_path.startswith(prefix):
        return None
    requested_name = request_path.removeprefix(prefix)
    if not requested_name or Path(requested_name).name != requested_name:
        return None
    if not (
        requested_name == f"{state.module_name}.js"
        or requested_name.startswith(f"{state.module_name}.")
    ):
        return None
    artifact = state.out_dir / requested_name
    if not artifact.is_file():
        return None
    resolved_artifact = artifact.resolve()
    if resolved_artifact.parent != state.out_dir:
        return None
    return resolved_artifact


class M3RequestHandler(BaseHTTPRequestHandler):
    server_version = "ChromiumWasmM3/1"

    @property
    def state(self) -> M3ServerState:
        return self.server.state  # type: ignore[attr-defined]

    def end_headers(self) -> None:
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        super().end_headers()

    def log_message(self, format_string: str, *args: object) -> None:
        if self.state.verbose:
            super().log_message(format_string, *args)

    def _send_bytes(
        self,
        body: bytes,
        content_type: str,
        *,
        status: int = 200,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        request_path = urlsplit(self.path).path
        static_paths = {
            "/": M3_HOST_DIR / "content_shell.html",
            "/__m3__/": M3_HOST_DIR / "content_shell.html",
            "/__m3__/content_shell_host.js": (
                M3_HOST_DIR / "content_shell_host.js"
            ),
            "/__m3__/fixture.html": (
                M3_TESTDATA_DIR / "m3_content_page.html"
            ),
            "/__m3__/m4-fixture.html": M4_POINTER_FIXTURE,
            "/__m3__/m4-selection-fixture.html": M4_SELECTION_FIXTURE,
            "/__m3__/m4-wheel-fixture.html": M4_WHEEL_FIXTURE,
            "/__m3__/m4-keyboard-fixture.html": M4_KEYBOARD_FIXTURE,
            "/__m3__/m4-printable-key-fixture.html": M4_PRINTABLE_KEY_FIXTURE,
            "/__m3__/m4-backspace-fixture.html": M4_BACKSPACE_FIXTURE,
            "/__m3__/m4-focus-fixture.html": M4_FOCUS_FIXTURE,
            "/__m3__/m4-ime-bridge-fixture.html": M4_IME_BRIDGE_FIXTURE,
            "/__m3__/Ahem.woff2": M3_AHEM_FONT,
            "/__m3__/screenshot-contract.json": M3_SCREENSHOT_CONTRACT,
        }
        static_path = static_paths.get(request_path)
        if static_path is not None:
            if not static_path.is_file():
                self.send_error(404)
                return
            self._send_bytes(
                static_path.read_bytes(),
                CONTENT_TYPES.get(
                    static_path.suffix, "application/octet-stream"
                ),
            )
            return

        artifact = _artifact_for_request(self.state, request_path)
        if artifact is None:
            self.send_error(404)
            return
        self._send_bytes(
            artifact.read_bytes(),
            CONTENT_TYPES.get(artifact.suffix, "application/octet-stream"),
        )

    def do_POST(self) -> None:
        request_path = urlsplit(self.path).path
        expected_path = f"/__m3__/result/{self.state.token}"
        if request_path != expected_path:
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400)
            return
        if length <= 0 or length > M3_MAX_RESULT_BYTES:
            self.send_error(413)
            return
        try:
            result = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_error(400)
            return
        if (
            not isinstance(result, dict)
            or result.get("protocol") != M3_PROTOCOL
            or result.get("case") not in (
                M3_CASE,
                M4_CASE,
                M4_SELECTION_CASE,
                M4_WHEEL_CASE,
                M4_KEYBOARD_CASE,
                M4_PRINTABLE_KEY_CASE,
                M4_BACKSPACE_CASE,
                M4_IME_BRIDGE_CASE,
                M4_FOCUS_CASE,
            )
        ):
            self.send_error(400)
            return
        if not accept_result(self.state, result):
            self.send_error(409)
            return
        self._send_bytes(b'{"accepted":true}\n', "application/json")


class M3HTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        state: M3ServerState,
    ) -> None:
        self.state = state
        super().__init__(address, M3RequestHandler)


def create_m3_server(
    bind: str,
    port: int,
    out_dir: Path,
    token: str,
    result_queue: queue.Queue[dict[str, Any]],
    *,
    module_name: str = "content_shell_wasm",
    verbose: bool = False,
) -> M3HTTPServer:
    resolved_out_dir = out_dir.resolve()
    for artifact_name in (f"{module_name}.js", f"{module_name}.wasm"):
        if not (resolved_out_dir / artifact_name).is_file():
            raise M0Error(
                f"{artifact_name} is missing from the output directory"
            )
    if not M3_AHEM_FONT.is_file():
        raise M0Error(f"M3 Ahem font is missing: {M3_AHEM_FONT}")
    state = M3ServerState(
        token=token,
        out_dir=resolved_out_dir,
        module_name=module_name,
        result_queue=result_queue,
        verbose=verbose,
    )
    return M3HTTPServer((bind, port), state)


def m3_smoke_url(
    server: M3HTTPServer,
    token: str,
    versions: dict[str, str],
    *,
    module_name: str = "content_shell_wasm",
    timeout_seconds: float = 90.0,
) -> str:
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "case": M3_CASE,
            "chromium": versions["chromium"],
            "emscripten": versions["emscripten"],
            "fixture": "/__m3__/fixture.html",
            "font": "/__m3__/Ahem.woff2",
            "module": f"/__m3__/artifacts/{module_name}.js",
            "port": versions["port"],
            "token": token,
            "timeout_ms": max(
                1000, min(180000, int(timeout_seconds * 1000))
            ),
            "v8": versions["v8"],
        }
    )
    return f"http://{host}:{port}/__m3__/?{query}"


def m4_smoke_url(
    server: M3HTTPServer,
    token: str,
    versions: dict[str, str],
    *,
    module_name: str = "content_shell_wasm",
    timeout_seconds: float = 90.0,
) -> str:
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "case": M4_CASE,
            "chromium": versions["chromium"],
            "emscripten": versions["emscripten"],
            "fixture": "/__m3__/m4-fixture.html",
            "font": "/__m3__/Ahem.woff2",
            "module": f"/__m3__/artifacts/{module_name}.js",
            "port": versions["port"],
            "token": token,
            "timeout_ms": max(
                1000, min(180000, int(timeout_seconds * 1000))
            ),
            "v8": versions["v8"],
        }
    )
    return f"http://{host}:{port}/__m3__/?{query}"


def m4_selection_smoke_url(
    server: M3HTTPServer,
    token: str,
    versions: dict[str, str],
    *,
    module_name: str = "content_shell_wasm",
    timeout_seconds: float = 90.0,
) -> str:
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "case": M4_SELECTION_CASE,
            "chromium": versions["chromium"],
            "emscripten": versions["emscripten"],
            "fixture": "/__m3__/m4-selection-fixture.html",
            "font": "/__m3__/Ahem.woff2",
            "module": f"/__m3__/artifacts/{module_name}.js",
            "port": versions["port"],
            "token": token,
            "timeout_ms": max(
                1000, min(180000, int(timeout_seconds * 1000))
            ),
            "v8": versions["v8"],
        }
    )
    return f"http://{host}:{port}/__m3__/?{query}"


def m4_wheel_smoke_url(
    server: M3HTTPServer,
    token: str,
    versions: dict[str, str],
    *,
    module_name: str = "content_shell_wasm",
    timeout_seconds: float = 90.0,
) -> str:
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "case": M4_WHEEL_CASE,
            "chromium": versions["chromium"],
            "emscripten": versions["emscripten"],
            "fixture": "/__m3__/m4-wheel-fixture.html",
            "font": "/__m3__/Ahem.woff2",
            "module": f"/__m3__/artifacts/{module_name}.js",
            "port": versions["port"],
            "token": token,
            "timeout_ms": max(
                1000, min(180000, int(timeout_seconds * 1000))
            ),
            "v8": versions["v8"],
        }
    )
    return f"http://{host}:{port}/__m3__/?{query}"


def m4_keyboard_smoke_url(
    server: M3HTTPServer,
    token: str,
    versions: dict[str, str],
    *,
    module_name: str = "content_shell_wasm",
    timeout_seconds: float = 90.0,
) -> str:
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "case": M4_KEYBOARD_CASE,
            "chromium": versions["chromium"],
            "emscripten": versions["emscripten"],
            "fixture": "/__m3__/m4-keyboard-fixture.html",
            "font": "/__m3__/Ahem.woff2",
            "module": f"/__m3__/artifacts/{module_name}.js",
            "port": versions["port"],
            "token": token,
            "timeout_ms": max(
                1000, min(180000, int(timeout_seconds * 1000))
            ),
            "v8": versions["v8"],
        }
    )
    return f"http://{host}:{port}/__m3__/?{query}"


def m4_printable_key_smoke_url(
    server: M3HTTPServer,
    token: str,
    versions: dict[str, str],
    *,
    module_name: str = "content_shell_wasm",
    timeout_seconds: float = 90.0,
) -> str:
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "case": M4_PRINTABLE_KEY_CASE,
            "chromium": versions["chromium"],
            "emscripten": versions["emscripten"],
            "fixture": "/__m3__/m4-printable-key-fixture.html",
            "font": "/__m3__/Ahem.woff2",
            "module": f"/__m3__/artifacts/{module_name}.js",
            "port": versions["port"],
            "token": token,
            "timeout_ms": max(
                1000, min(180000, int(timeout_seconds * 1000))
            ),
            "v8": versions["v8"],
        }
    )
    return f"http://{host}:{port}/__m3__/?{query}"


def m4_backspace_smoke_url(
    server: M3HTTPServer,
    token: str,
    versions: dict[str, str],
    *,
    module_name: str = "content_shell_wasm",
    timeout_seconds: float = 90.0,
) -> str:
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "case": M4_BACKSPACE_CASE,
            "chromium": versions["chromium"],
            "emscripten": versions["emscripten"],
            "fixture": "/__m3__/m4-backspace-fixture.html",
            "font": "/__m3__/Ahem.woff2",
            "module": f"/__m3__/artifacts/{module_name}.js",
            "port": versions["port"],
            "token": token,
            "timeout_ms": max(
                1000, min(180000, int(timeout_seconds * 1000))
            ),
            "v8": versions["v8"],
        }
    )
    return f"http://{host}:{port}/__m3__/?{query}"


def m4_ime_bridge_smoke_url(
    server: M3HTTPServer,
    token: str,
    versions: dict[str, str],
    *,
    module_name: str = "content_shell_wasm",
    timeout_seconds: float = 90.0,
    terminal_mode: str = "commit",
) -> str:
    if terminal_mode not in ("commit", "cancel"):
        raise M0Error(
            "M4 IME bridge terminal mode must be 'commit' or 'cancel', got "
            f"{terminal_mode!r}"
        )
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "case": M4_IME_BRIDGE_CASE,
            "chromium": versions["chromium"],
            "emscripten": versions["emscripten"],
            "fixture": "/__m3__/m4-ime-bridge-fixture.html",
            "font": "/__m3__/Ahem.woff2",
            "module": f"/__m3__/artifacts/{module_name}.js",
            "port": versions["port"],
            "ime_terminal": terminal_mode,
            "token": token,
            "timeout_ms": max(
                1000, min(180000, int(timeout_seconds * 1000))
            ),
            "v8": versions["v8"],
        }
    )
    return f"http://{host}:{port}/__m3__/?{query}"


def m4_focus_smoke_url(
    server: M3HTTPServer,
    token: str,
    versions: dict[str, str],
    *,
    module_name: str = "content_shell_wasm",
    timeout_seconds: float = 90.0,
) -> str:
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "case": M4_FOCUS_CASE,
            "chromium": versions["chromium"],
            "emscripten": versions["emscripten"],
            "fixture": "/__m3__/m4-focus-fixture.html",
            "font": "/__m3__/Ahem.woff2",
            "module": f"/__m3__/artifacts/{module_name}.js",
            "port": versions["port"],
            "token": token,
            "timeout_ms": max(
                1000, min(180000, int(timeout_seconds * 1000))
            ),
            "v8": versions["v8"],
        }
    )
    return f"http://{host}:{port}/__m3__/?{query}"



def _require_number(
    value: object,
    description: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise M0Error(f"{description} must be a finite number")
    converted = float(value)
    if minimum is not None and converted < minimum:
        raise M0Error(f"{description} must be at least {minimum}")
    if maximum is not None and converted > maximum:
        raise M0Error(f"{description} must be at most {maximum}")
    return converted


def _require_dict(value: object, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise M0Error(f"{description} must be an object")
    return value


def _require_safe_integer(
    value: object,
    description: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < -(1 << 53) + 1
        or value > (1 << 53) - 1
    ):
        raise M0Error(f"{description} must be a safe integer")
    if minimum is not None and value < minimum:
        raise M0Error(f"{description} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise M0Error(f"{description} must be at most {maximum}")
    return value


def _exact_json_value_equal(actual: object, expected: object) -> bool:
    """Compare JSON-shaped values without Python's bool/int coercion."""

    if type(actual) is not type(expected):
        return False
    if type(actual) is dict:
        if set(actual) != set(expected):
            return False
        return all(
            _exact_json_value_equal(actual[key], expected[key])
            for key in actual
        )
    if type(actual) is list:
        return len(actual) == len(expected) and all(
            _exact_json_value_equal(actual_item, expected_item)
            for actual_item, expected_item in zip(actual, expected)
        )
    return actual == expected


def _require_linear_memory_bytes(value: object, description: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value <= 0
        or value > (1 << 53) - 1
    ):
        raise M0Error(f"{description} must be a positive safe integer")
    if value % (64 * 1024) != 0:
        raise M0Error(f"{description} must be aligned to a 64 KiB page")
    return value


def validate_m3_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
) -> bytes:
    expected = {
        "protocol": M3_PROTOCOL,
        "case": M3_CASE,
        "status": "pass",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "failedChecks": [],
        "error": None,
    }
    for field, expected_value in expected.items():
        actual_value = result.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M3 result {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )

    versions = _require_dict(result.get("versions"), "M3 versions")
    if versions != expected_versions:
        raise M0Error(
            f"M3 version display mismatch: expected {expected_versions!r}, "
            f"got {versions!r}"
        )

    readiness = _require_dict(result.get("readiness"), "M3 readiness")
    heartbeat = _require_dict(result.get("heartbeat"), "M3 heartbeat")
    readiness_heartbeat = _require_dict(
        readiness.get("heartbeat"), "M3 readiness heartbeat"
    )
    if heartbeat != readiness_heartbeat:
        raise M0Error("M3 readiness and result heartbeat evidence differ")
    if heartbeat.get("anchor") != "data-navigation-committed":
        raise M0Error(
            "M3 outer heartbeat was not anchored to the committed data: "
            "navigation"
        )
    _require_number(
        heartbeat.get("elapsedMs"),
        "M3 outer heartbeat elapsed time",
        minimum=M3_MINIMUM_RUNTIME_MS,
    )
    _require_number(
        heartbeat.get("timerDelta"),
        "M3 outer timer ticks",
        minimum=M3_MINIMUM_TIMER_TICKS,
    )
    _require_number(
        heartbeat.get("animationFrameDelta"),
        "M3 outer animation frames",
        minimum=M3_MINIMUM_ANIMATION_FRAMES,
    )
    maximum_gap = _require_number(
        heartbeat.get("maxTimerGapMs"), "M3 outer maximum timer gap"
    )
    if maximum_gap > M3_MAXIMUM_TIMER_GAP_MS:
        raise M0Error(
            "M3 outer timer gap exceeded "
            f"{M3_MAXIMUM_TIMER_GAP_MS} ms: {maximum_gap}"
        )

    required_ready_fields = (
        "ready",
        "baseReady",
        "interactionReady",
        "runtimeInitialized",
        "shellReady",
        "surfaceReady",
        "navigationCommitted",
        "firstVisuallyNonEmptyPaint",
        "pageReady",
    )
    for field in required_ready_fields:
        if readiness.get(field) is not True:
            raise M0Error(f"M3 readiness field {field} is not true")
    if readiness.get("fatalErrors") != []:
        raise M0Error("M3 readiness reported fatal errors")

    frame = _require_dict(readiness.get("frame"), "M3 readiness frame")
    frame_id = _require_safe_integer(
        frame.get("id"), "M3 frame ID", minimum=1
    )
    _require_number(frame.get("timestampMs"), "M3 frame timestamp", minimum=0)
    frame_width = _require_safe_integer(
        frame.get("width"), "M3 frame width", minimum=1
    )
    frame_height = _require_safe_integer(
        frame.get("height"), "M3 frame height", minimum=1
    )
    if frame_width != M3_WIDTH or frame_height != M3_HEIGHT:
        raise M0Error("M3 readiness frame dimensions do not match the canvas")
    input_frame_id = _require_safe_integer(
        readiness.get("inputPostedAtFrameId"),
        "M3 input-post frame ID",
        minimum=0,
    )
    interaction_frame_id = _require_safe_integer(
        readiness.get("interactionObservedAtFrameId"),
        "M3 interaction-observed frame ID",
        minimum=0,
    )
    if interaction_frame_id < input_frame_id:
        raise M0Error(
            "M3 trusted interaction was observed before input was posted"
        )
    if frame_id <= interaction_frame_id:
        raise M0Error(
            "M3 screenshot readiness is not backed by a "
            "post-interaction frame"
        )

    page_probe = _require_dict(
        readiness.get("pageProbe"), "M3 page probe"
    )
    expected_probe = {
        "fixture": "chromium-wasm-m3-static-v1",
        "ready": True,
        "fontReady": True,
        "imageReady": True,
        "canvasReady": True,
        "scrollTop": 48,
        "formValue": "M3 form",
        "inputClicks": 1,
        "inputTrusted": True,
        "buttonText": "CLICKED",
    }
    for field, expected_value in expected_probe.items():
        actual_value = page_probe.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M3 page probe {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )
    _require_safe_integer(
        page_probe.get("timerTicks"), "M3 inner page timer ticks", minimum=3
    )
    button_center_x = _require_safe_integer(
        page_probe.get("buttonCenterX"),
        "M3 input target x",
        minimum=0,
        maximum=M3_WIDTH - 1,
    )
    button_center_y = _require_safe_integer(
        page_probe.get("buttonCenterY"),
        "M3 input target y",
        minimum=0,
        maximum=M3_HEIGHT - 1,
    )

    input_result = _require_dict(
        result.get("inputResult"), "M3 input result"
    )
    expected_input = {
        "ok": True,
        "accepted": True,
        "code": "CLICK_POSTED",
        "eventType": "click",
    }
    for field, expected_value in expected_input.items():
        actual_value = input_result.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M3 input result {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )
    _require_safe_integer(
        input_result.get("button"),
        "M3 input button",
        minimum=0,
        maximum=0,
    )
    input_x = _require_safe_integer(
        input_result.get("x"),
        "M3 input result x",
        minimum=0,
        maximum=M3_WIDTH - 1,
    )
    input_y = _require_safe_integer(
        input_result.get("y"),
        "M3 input result y",
        minimum=0,
        maximum=M3_HEIGHT - 1,
    )
    if (
        input_x != button_center_x
        or input_y != button_center_y
    ):
        raise M0Error("M3 input result does not target the fixture button")

    shutdown = _require_dict(result.get("shutdown"), "M3 shutdown result")
    expected_shutdown = {
        "ok": True,
        "accepted": True,
        "complete": True,
    }
    for field, expected_value in expected_shutdown.items():
        actual_value = shutdown.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M3 shutdown {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )
    for field in ("exitCode", "runtimeExitCode"):
        exit_code = _require_safe_integer(
            shutdown.get(field), f"M3 shutdown {field}"
        )
        if exit_code != 0:
            raise M0Error(
                f"M3 shutdown {field} mismatch: expected 0, "
                f"got {exit_code!r}"
            )
    linear_memory = _require_dict(
        shutdown.get("linearMemory"), "M3 shutdown linear memory"
    )
    initial_memory_bytes = _require_linear_memory_bytes(
        linear_memory.get("initialBytes"),
        "M3 initial linear memory bytes",
    )
    peak_memory_bytes = _require_linear_memory_bytes(
        linear_memory.get("peakBytes"),
        "M3 peak linear memory bytes",
    )
    if peak_memory_bytes < initial_memory_bytes:
        raise M0Error(
            "M3 peak linear memory bytes must be at least the initial bytes"
        )

    logs = _require_dict(result.get("logs"), "M3 logs")
    for stream in ("host", "stdout", "stderr"):
        if not isinstance(logs.get(stream), list):
            raise M0Error(f"M3 {stream} log must be an array")
    combined_logs = "\n".join(
        str(line)
        for stream in ("host", "stdout", "stderr")
        for line in logs[stream]
    )
    if "abort:" in combined_logs.lower():
        raise M0Error("M3 logs contain a Wasm abort")
    required_log_markers = (
        "resize:640x480@1",
        "resize:800x600@1",
        "input:click:",
        "resize:799x600@1",
        "resize:800x600@1",
        "shutdown:accepted",
        "process:exit:0",
        "runtime:exit:0",
        "shutdown:complete",
    )
    host_logs = [str(line) for line in logs["host"]]
    marker_cursor = 0
    for marker in required_log_markers:
        matching_position = next(
            (
                index
                for index in range(marker_cursor, len(host_logs))
                if marker in host_logs[index]
            ),
            None,
        )
        if matching_position is None:
            if any(marker in line for line in host_logs):
                raise M0Error("M3 lifecycle markers are out of order")
            raise M0Error(f"M3 logs are missing lifecycle marker {marker!r}")
        marker_cursor = matching_position + 1

    screenshot = _require_dict(result.get("screenshot"), "M3 screenshot")
    if (
        screenshot.get("mimeType") != "image/png"
        or screenshot.get("width") != M3_WIDTH
        or screenshot.get("height") != M3_HEIGHT
    ):
        raise M0Error("M3 screenshot metadata does not match the contract")
    encoded = screenshot.get("dataBase64")
    if not isinstance(encoded, str) or not encoded:
        raise M0Error("M3 screenshot payload is missing")
    try:
        png_bytes = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise M0Error("M3 screenshot is not valid base64") from exc
    if not png_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise M0Error("M3 screenshot is not a PNG")
    return png_bytes


def validate_m4_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
) -> None:
    """Validate the M4 trusted-DOM-pointer to Ozone/Aura evidence."""

    expected = {
        "protocol": M3_PROTOCOL,
        "case": M4_CASE,
        "status": "pass",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "failedChecks": [],
        "error": None,
    }
    for field, expected_value in expected.items():
        actual_value = result.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 result {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )

    versions = _require_dict(result.get("versions"), "M4 versions")
    if versions != expected_versions:
        raise M0Error(
            f"M4 version display mismatch: expected {expected_versions!r}, "
            f"got {versions!r}"
        )

    readiness = _require_dict(result.get("readiness"), "M4 readiness")
    for field in (
        "baseReady",
        "runtimeInitialized",
        "shellReady",
        "surfaceReady",
        "navigationCommitted",
        "firstVisuallyNonEmptyPaint",
        "pageReady",
    ):
        if readiness.get(field) is not True:
            raise M0Error(f"M4 readiness field {field} is not true")
    if readiness.get("fatalErrors") != []:
        raise M0Error("M4 readiness reported fatal errors")
    heartbeat = _require_dict(readiness.get("heartbeat"), "M4 heartbeat")
    if heartbeat.get("anchor") != "data-navigation-committed":
        raise M0Error("M4 heartbeat was not anchored to data navigation")
    _require_number(
        heartbeat.get("elapsedMs"), "M4 heartbeat elapsed time", minimum=0
    )

    frame = _require_dict(readiness.get("frame"), "M4 readiness frame")
    frame_id = _require_safe_integer(
        frame.get("id"), "M4 frame ID", minimum=1
    )
    _require_number(frame.get("timestampMs"), "M4 frame timestamp", minimum=0)
    if frame.get("width") != M3_WIDTH or frame.get("height") != M3_HEIGHT:
        raise M0Error("M4 readiness frame dimensions do not match the canvas")

    page_probe = _require_dict(readiness.get("pageProbe"), "M4 page probe")
    expected_probe = {
        "fontReady": True,
        "protocol": M3_PROTOCOL,
        "fixture": "chromium-wasm-m4-ozone-pointer-v1",
        "ready": True,
        "activationCount": 1,
        "clickTrusted": True,
        "resultText": "ACTIVATED",
    }
    for field, expected_value in expected_probe.items():
        actual_value = page_probe.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 page probe {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )
    target_x = _require_safe_integer(
        page_probe.get("targetCenterX"),
        "M4 input target x",
        minimum=0,
        maximum=M3_WIDTH - 1,
    )
    target_y = _require_safe_integer(
        page_probe.get("targetCenterY"),
        "M4 input target y",
        minimum=0,
        maximum=M3_HEIGHT - 1,
    )
    _require_safe_integer(
        page_probe.get("timerTicks"), "M4 inner page timer ticks", minimum=3
    )
    pointer_events = _require_dict(
        page_probe.get("pointerEvents"), "M4 inner pointer events"
    )
    for event_name in (
        "mousemove",
        "mousedown",
        "mouseup",
        "pointermove",
        "pointerdown",
        "pointerup",
    ):
        _require_safe_integer(
            pointer_events.get(event_name),
            f"M4 inner {event_name} count",
            minimum=1,
        )

    pointer_input = _require_dict(
        result.get("pointerInput"), "M4 pointer input"
    )
    readiness_pointer = _require_dict(
        readiness.get("pointerInput"), "M4 readiness pointer input"
    )
    if pointer_input != readiness_pointer:
        raise M0Error("M4 pointer evidence differs from readiness evidence")
    if pointer_input.get("enabled") is not True:
        raise M0Error("M4 pointer listeners were not enabled")
    received_count = _require_safe_integer(
        pointer_input.get("receivedCount"),
        "M4 received pointer count",
        minimum=2,
    )
    trusted_count = _require_safe_integer(
        pointer_input.get("trustedCount"),
        "M4 trusted DOM pointer count",
        minimum=2,
    )
    queued_count = _require_safe_integer(
        pointer_input.get("queuedCount"),
        "M4 queued host pointer count",
        minimum=2,
    )
    if trusted_count > received_count or queued_count > received_count:
        raise M0Error("M4 pointer count exceeds received pointer records")
    last_queued = _require_dict(
        pointer_input.get("lastQueued"), "M4 last queued pointer"
    )
    if last_queued.get("type") != "up":
        raise M0Error("M4 final queued pointer is not a primary release")
    if last_queued.get("trusted") is not True:
        raise M0Error("M4 queued pointer was not a trusted DOM event")
    if last_queued.get("queued") is not True:
        raise M0Error("M4 final pointer was not queued on the UI runner")
    if last_queued.get("canvasFocused") is not True:
        raise M0Error("M4 canvas was not focused before pointer delivery")
    _require_safe_integer(
        last_queued.get("sequence"), "M4 pointer sequence", minimum=1
    )
    if _require_safe_integer(
        last_queued.get("x"),
        "M4 queued pointer x",
        minimum=0,
        maximum=M3_WIDTH - 1,
    ) != target_x:
        raise M0Error("M4 pointer x does not match the fixture target")
    if _require_safe_integer(
        last_queued.get("y"),
        "M4 queued pointer y",
        minimum=0,
        maximum=M3_HEIGHT - 1,
    ) != target_y:
        raise M0Error("M4 pointer y does not match the fixture target")
    input_frame_id = _require_safe_integer(
        last_queued.get("frameIdBefore"),
        "M4 input frame ID",
        minimum=1,
    )
    if frame_id <= input_frame_id:
        raise M0Error("M4 result has no compositor frame after input")

    shutdown = _require_dict(result.get("shutdown"), "M4 shutdown result")
    for field, expected_value in {
        "ok": True,
        "accepted": True,
        "complete": True,
    }.items():
        if shutdown.get(field) is not expected_value:
            raise M0Error(f"M4 shutdown field {field} is not true")
    for field in ("exitCode", "runtimeExitCode"):
        if (
            _require_safe_integer(shutdown.get(field), f"M4 shutdown {field}")
            != 0
        ):
            raise M0Error(f"M4 shutdown {field} is not zero")

    logs = _require_dict(result.get("logs"), "M4 logs")
    for stream in ("host", "stdout", "stderr"):
        if not isinstance(logs.get(stream), list):
            raise M0Error(f"M4 {stream} log must be an array")
    combined_logs = "\n".join(
        str(line)
        for stream in ("host", "stdout", "stderr")
        for line in logs[stream]
    )
    if "abort:" in combined_logs.lower():
        raise M0Error("M4 logs contain a Wasm abort")
    host_logs = [str(line) for line in logs["host"]]
    for marker in (
        "m4:pointer:listeners-attached",
        "m4:pointer:down:queued",
        "m4:pointer:up:queued",
        "shutdown:complete",
    ):
        if not any(marker in line for line in host_logs):
            raise M0Error(f"M4 logs are missing lifecycle marker {marker!r}")


def validate_m4_selection_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
) -> None:
    """Validate a bounded trusted pointer drag selects static Blink text.

    This deliberately validates a complete outer DOM/Ozone pointer trace, the
    corresponding inner Blink mouse and pointer traces, and the final native
    editor selection.  The fixture must not manufacture the selection through
    DOM mutation or a host text command.
    """

    expected = {
        "protocol": M3_PROTOCOL,
        "case": M4_SELECTION_CASE,
        "status": "pass",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "failedChecks": [],
        "error": None,
    }
    for field, expected_value in expected.items():
        actual_value = result.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 selection result {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )

    versions = _require_dict(
        result.get("versions"), "M4 selection versions"
    )
    if versions != expected_versions:
        raise M0Error(
            "M4 selection version display mismatch: expected "
            f"{expected_versions!r}, got {versions!r}"
        )

    activation_proof = _require_dict(
        result.get("activationProof"), "M4 selection activation proof"
    )
    for field in (
        "outerTraceExact",
        "activationEvidence",
        "selectionCollapsed",
        "selectionDirectionNone",
        "selectedTextEmpty",
        "frameAfterActivation",
    ):
        if activation_proof.get(field) is not True:
            raise M0Error(
                f"M4 selection activation proof {field} is not true"
            )
    activation_selection_start = _require_safe_integer(
        activation_proof.get("selectionStart"),
        "M4 selection activation selection start",
        minimum=0,
        maximum=4,
    )
    activation_selection_end = _require_safe_integer(
        activation_proof.get("selectionEnd"),
        "M4 selection activation selection end",
        minimum=0,
        maximum=4,
    )
    if activation_selection_start != activation_selection_end:
        raise M0Error(
            "M4 selection activation proof selection is not collapsed"
        )
    if activation_proof.get("selectionDirection") != "none":
        raise M0Error(
            "M4 selection activation proof selection direction is not 'none'"
        )
    if activation_proof.get("selectedText") != "":
        raise M0Error(
            "M4 selection activation proof selected text is not empty"
        )

    readiness = _require_dict(
        result.get("readiness"), "M4 selection readiness"
    )
    for field in (
        "baseReady",
        "runtimeInitialized",
        "shellReady",
        "surfaceReady",
        "navigationCommitted",
        "firstVisuallyNonEmptyPaint",
        "pageReady",
    ):
        if readiness.get(field) is not True:
            raise M0Error(
                f"M4 selection readiness field {field} is not true"
            )
    if readiness.get("fatalErrors") != []:
        raise M0Error("M4 selection readiness reported fatal errors")
    heartbeat = _require_dict(
        readiness.get("heartbeat"), "M4 selection heartbeat"
    )
    if heartbeat.get("anchor") != "data-navigation-committed":
        raise M0Error(
            "M4 selection heartbeat was not anchored to data navigation"
        )
    _require_number(
        heartbeat.get("elapsedMs"),
        "M4 selection heartbeat elapsed time",
        minimum=0,
    )

    frame = _require_dict(readiness.get("frame"), "M4 selection frame")
    frame_id = _require_safe_integer(
        frame.get("id"), "M4 selection frame ID", minimum=1
    )
    _require_number(
        frame.get("timestampMs"), "M4 selection frame timestamp", minimum=0
    )
    for field, expected_value in {
        "width": M3_WIDTH,
        "height": M3_HEIGHT,
    }.items():
        actual_value = frame.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                "M4 selection frame dimensions do not match the canvas"
            )

    page_probe = _require_dict(
        readiness.get("pageProbe"), "M4 selection page probe"
    )
    expected_probe = {
        "fontReady": True,
        "protocol": M3_PROTOCOL,
        "fixture": "chromium-wasm-m4-ozone-selection-v1",
        "ready": True,
        "activeElementId": "editable-target",
        "clickTrusted": True,
        "focusTrusted": True,
        "value": "WASM",
        "selectionStart": 0,
        "selectionEnd": 4,
        "selectedText": "WASM",
        "resultText": "TEXT SELECTED",
    }
    for field, expected_value in expected_probe.items():
        actual_value = page_probe.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 selection page probe {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )
    if page_probe.get("selectionDirection") not in (
        "none",
        "forward",
    ):
        raise M0Error("M4 selection page probe selection direction is invalid")
    _require_safe_integer(
        page_probe.get("activationCount"),
        "M4 selection activation count",
        minimum=1,
    )
    _require_safe_integer(
        page_probe.get("focusCount"),
        "M4 selection focus count",
        minimum=1,
    )
    _require_safe_integer(
        page_probe.get("timerTicks"),
        "M4 selection inner page timer ticks",
        minimum=3,
    )

    coordinates: dict[str, int] = {}
    for field in (
        "targetX",
        "targetY",
        "dragStartX",
        "dragStartY",
        "dragMiddleX",
        "dragMiddleY",
        "dragEndX",
        "dragEndY",
    ):
        maximum = M3_WIDTH - 1 if field.endswith("X") else M3_HEIGHT - 1
        coordinates[field] = _require_safe_integer(
            page_probe.get(field),
            f"M4 selection {field}",
            minimum=0,
            maximum=maximum,
        )

    selection_activity = _require_dict(
        page_probe.get("selectionActivity"),
        "M4 selection activity",
    )
    _require_safe_integer(
        selection_activity.get("count"),
        "M4 selection activity count",
        minimum=1,
    )
    _require_safe_integer(
        selection_activity.get("selectCount"),
        "M4 selection select count",
        minimum=1,
    )
    _require_safe_integer(
        selection_activity.get("selectionChangeCount"),
        "M4 selection selectionchange count",
        minimum=1,
    )
    for field in (
        "trusted",
        "nonCollapsed",
        "trustedNonCollapsed",
        "selectTrusted",
        "selectionChangeTrusted",
    ):
        if selection_activity.get(field) is not True:
            raise M0Error(f"M4 selection activity {field} is not true")

    text_input_events = _require_dict(
        page_probe.get("textInputEvents"),
        "M4 selection text input events",
    )
    for field in (
        "beforeinputCount",
        "inputCount",
        "compositionstartCount",
        "compositionupdateCount",
        "compositionendCount",
    ):
        if _require_safe_integer(
            text_input_events.get(field),
            f"M4 selection {field}",
            minimum=0,
        ) != 0:
            raise M0Error(
                "M4 selection unexpectedly received text or composition "
                f"input: {field}"
            )

    target_x = coordinates["targetX"]
    target_y = coordinates["targetY"]
    drag_start_x = coordinates["dragStartX"]
    drag_start_y = coordinates["dragStartY"]
    drag_middle_x = coordinates["dragMiddleX"]
    drag_middle_y = coordinates["dragMiddleY"]
    drag_end_x = coordinates["dragEndX"]
    drag_end_y = coordinates["dragEndY"]
    if not (
        drag_start_x < drag_middle_x < drag_end_x
        and drag_start_y == drag_middle_y == drag_end_y
    ):
        raise M0Error("M4 selection drag geometry is not strictly forward")
    expected_outer_trace = (
        ("move", target_x, target_y),
        ("down", target_x, target_y),
        ("up", target_x, target_y),
        ("move", drag_start_x, drag_start_y),
        ("down", drag_start_x, drag_start_y),
        ("move", drag_middle_x, drag_middle_y),
        ("move", drag_end_x, drag_end_y),
        ("up", drag_end_x, drag_end_y),
    )

    pointer_input = _require_dict(
        result.get("pointerInput"), "M4 selection pointer input"
    )
    readiness_pointer = _require_dict(
        readiness.get("pointerInput"),
        "M4 selection readiness pointer input",
    )
    if not _exact_json_value_equal(pointer_input, readiness_pointer):
        raise M0Error(
            "M4 selection pointer evidence differs from readiness evidence"
        )
    if pointer_input.get("enabled") is not True:
        raise M0Error("M4 selection pointer listeners were not enabled")
    for field in ("receivedCount", "trustedCount", "queuedCount"):
        if _require_safe_integer(
            pointer_input.get(field),
            f"M4 selection pointer {field}",
            minimum=0,
        ) != len(expected_outer_trace):
            raise M0Error(
                f"M4 selection pointer {field} is not exactly "
                f"{len(expected_outer_trace)}"
            )
    queued_records = pointer_input.get("queuedRecords")
    if not isinstance(queued_records, list) or len(queued_records) != len(
        expected_outer_trace
    ):
        raise M0Error(
            "M4 selection queued pointer trace is not exactly eight records"
        )
    previous_sequence = 0
    drag_up_frame_id = 0
    for index, (event_type, expected_x, expected_y) in enumerate(
        expected_outer_trace
    ):
        record = _require_dict(
            queued_records[index],
            f"M4 selection queued pointer trace {index}",
        )
        expected_record = {
            "type": event_type,
            "trusted": True,
            "queued": True,
            "canvasFocused": True,
        }
        for field, expected_value in expected_record.items():
            actual_value = record.get(field)
            if (
                type(actual_value) is not type(expected_value)
                or actual_value != expected_value
            ):
                raise M0Error(
                    f"M4 selection queued pointer trace {index} {field} "
                    f"mismatch: expected {expected_value!r}, got "
                    f"{actual_value!r}"
                )
        actual_x = _require_safe_integer(
            record.get("x"),
            f"M4 selection queued pointer trace {index} x",
            minimum=0,
            maximum=M3_WIDTH - 1,
        )
        actual_y = _require_safe_integer(
            record.get("y"),
            f"M4 selection queued pointer trace {index} y",
            minimum=0,
            maximum=M3_HEIGHT - 1,
        )
        if actual_x != expected_x or actual_y != expected_y:
            raise M0Error(
                f"M4 selection queued pointer trace {index} does not match "
                "the fixture coordinates"
            )
        sequence = _require_safe_integer(
            record.get("sequence"),
            f"M4 selection queued pointer trace {index} sequence",
            minimum=previous_sequence + 1,
        )
        if sequence != index + 1 or sequence <= previous_sequence:
            raise M0Error(
                "M4 selection queued pointer trace sequence is not exact"
            )
        previous_sequence = sequence
        record_frame_id = _require_safe_integer(
            record.get("frameIdBefore"),
            f"M4 selection queued pointer trace {index} frame ID",
            minimum=1,
        )
        if index == len(expected_outer_trace) - 1:
            drag_up_frame_id = record_frame_id
    last_queued = _require_dict(
        pointer_input.get("lastQueued"), "M4 selection last queued pointer"
    )
    if not _exact_json_value_equal(last_queued, queued_records[-1]):
        raise M0Error(
            "M4 selection last queued pointer does not match the drag release"
        )
    if frame_id <= drag_up_frame_id:
        raise M0Error("M4 selection result has no compositor frame after drag")

    expected_inner_trace = (
        ("move", target_x, target_y, -1, 0),
        ("move", target_x, target_y, -1, 0),
        ("down", target_x, target_y, 0, 1),
        ("move", target_x, target_y, -1, 1),
        ("up", target_x, target_y, 0, 0),
        ("move", drag_start_x, drag_start_y, -1, 0),
        ("down", drag_start_x, drag_start_y, 0, 1),
        ("move", drag_middle_x, drag_middle_y, -1, 1),
        ("move", drag_end_x, drag_end_y, -1, 1),
        ("up", drag_end_x, drag_end_y, 0, 0),
    )

    def require_inner_trace(
        field: str,
        prefix: str,
    ) -> None:
        trace = page_probe.get(field)
        if not isinstance(trace, list) or len(trace) != len(
            expected_inner_trace
        ):
            raise M0Error(
                f"M4 selection {prefix} trace is not exactly "
                f"{len(expected_inner_trace)} events"
            )
        for index, (kind, x, y, pointer_button, buttons) in enumerate(
            expected_inner_trace
        ):
            record = _require_dict(
                trace[index], f"M4 selection {prefix} trace {index}"
            )
            expected_record = {
                "type": prefix + kind,
                "trusted": True,
                # Blink's MouseEvent::button() reports the primary button for
                # mousemove, whereas PointerEvent::button is -1 for a move.
                "button": 0 if prefix == "mouse" and kind == "move"
                else pointer_button,
                "buttons": buttons,
                "clientX": x,
                "clientY": y,
                "targetId": "editable-target",
                "defaultPrevented": False,
            }
            for record_field, expected_value in expected_record.items():
                actual_value = record.get(record_field)
                if (
                    type(actual_value) is not type(expected_value)
                    or actual_value != expected_value
                ):
                    raise M0Error(
                        f"M4 selection {prefix} trace {index} "
                        f"{record_field} mismatch: expected "
                        f"{expected_value!r}, got {actual_value!r}"
                    )

    require_inner_trace("mouseEventTrace", "mouse")
    require_inner_trace("pointerEventTrace", "pointer")

    shutdown = _require_dict(result.get("shutdown"), "M4 selection shutdown")
    for field in ("ok", "accepted", "complete"):
        if shutdown.get(field) is not True:
            raise M0Error(f"M4 selection shutdown {field} is not true")
    for field in ("exitCode", "runtimeExitCode"):
        if _require_safe_integer(
            shutdown.get(field), f"M4 selection shutdown {field}"
        ) != 0:
            raise M0Error(f"M4 selection shutdown {field} is not zero")

    logs = _require_dict(result.get("logs"), "M4 selection logs")
    for stream in ("host", "stdout", "stderr"):
        entries = logs.get(stream)
        if type(entries) is not list:
            raise M0Error(f"M4 selection {stream} log must be an array")
        for index, entry in enumerate(entries):
            if type(entry) is not str:
                raise M0Error(
                    f"M4 selection {stream} log entry {index} must be a "
                    "string"
                )
    combined_logs = "\n".join(
        line
        for stream in ("host", "stdout", "stderr")
        for line in logs[stream]
    )
    if "abort:" in combined_logs.lower():
        raise M0Error("M4 selection logs contain a Wasm abort")
    host_logs = logs["host"]
    pointer_logs = [
        line for line in host_logs if line.startswith("m4:pointer:")
    ]
    expected_pointer_logs = [
        "m4:pointer:listeners-attached",
        "m4:pointer:move:queued",
        "m4:pointer:down:queued",
        "m4:pointer:up:queued",
        "m4:pointer:move:queued",
        "m4:pointer:down:queued",
        "m4:pointer:move:queued",
        "m4:pointer:move:queued",
        "m4:pointer:up:queued",
    ]
    if pointer_logs != expected_pointer_logs:
        raise M0Error("M4 selection pointer lifecycle logs are not exact")
    shutdown_index = next(
        (
            index
            for index, line in enumerate(host_logs)
            if line == "shutdown:complete"
        ),
        None,
    )
    if shutdown_index is None:
        raise M0Error("M4 selection logs are missing lifecycle marker "
                      "'shutdown:complete'")
    if any(
        line.startswith("m4:pointer:")
        for line in host_logs[shutdown_index + 1 :]
    ):
        raise M0Error("M4 selection pointer lifecycle continued after shutdown")


def validate_m4_wheel_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
) -> None:
    """Validate trusted DOM wheel input reaches Ozone, Aura, and Blink."""

    expected = {
        "protocol": M3_PROTOCOL,
        "case": M4_WHEEL_CASE,
        "status": "pass",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "failedChecks": [],
        "error": None,
    }
    for field, expected_value in expected.items():
        actual_value = result.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 wheel result {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )

    versions = _require_dict(result.get("versions"), "M4 wheel versions")
    if versions != expected_versions:
        raise M0Error(
            "M4 wheel version display mismatch: expected "
            f"{expected_versions!r}, got {versions!r}"
        )

    readiness = _require_dict(result.get("readiness"), "M4 wheel readiness")
    for field in (
        "baseReady",
        "runtimeInitialized",
        "shellReady",
        "surfaceReady",
        "navigationCommitted",
        "firstVisuallyNonEmptyPaint",
        "pageReady",
    ):
        if readiness.get(field) is not True:
            raise M0Error(f"M4 wheel readiness field {field} is not true")
    if readiness.get("fatalErrors") != []:
        raise M0Error("M4 wheel readiness reported fatal errors")
    heartbeat = _require_dict(
        readiness.get("heartbeat"), "M4 wheel heartbeat"
    )
    if heartbeat.get("anchor") != "data-navigation-committed":
        raise M0Error("M4 wheel heartbeat was not anchored to data navigation")
    _require_number(
        heartbeat.get("elapsedMs"),
        "M4 wheel heartbeat elapsed time",
        minimum=0,
    )

    frame = _require_dict(readiness.get("frame"), "M4 wheel frame")
    frame_id = _require_safe_integer(
        frame.get("id"), "M4 wheel frame ID", minimum=1
    )
    _require_number(
        frame.get("timestampMs"), "M4 wheel frame timestamp", minimum=0
    )
    if frame.get("width") != M3_WIDTH or frame.get("height") != M3_HEIGHT:
        raise M0Error("M4 wheel frame dimensions do not match the canvas")

    page_probe = _require_dict(
        readiness.get("pageProbe"), "M4 wheel page probe"
    )
    expected_probe = {
        "fontReady": True,
        "protocol": M3_PROTOCOL,
        "fixture": "chromium-wasm-m4-ozone-wheel-v1",
        "ready": True,
    }
    for field, expected_value in expected_probe.items():
        actual_value = page_probe.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 wheel page probe {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )
    target_x = _require_safe_integer(
        page_probe.get("targetCenterX"),
        "M4 wheel target x",
        minimum=0,
        maximum=M3_WIDTH - 1,
    )
    target_y = _require_safe_integer(
        page_probe.get("targetCenterY"),
        "M4 wheel target y",
        minimum=0,
        maximum=M3_HEIGHT - 1,
    )
    _require_safe_integer(
        page_probe.get("timerTicks"),
        "M4 wheel inner page timer ticks",
        minimum=3,
    )
    wheel_events = _require_dict(
        page_probe.get("wheelEvents"), "M4 inner wheel events"
    )
    _require_safe_integer(
        wheel_events.get("count"), "M4 inner wheel count", minimum=1
    )
    if wheel_events.get("trusted") is not True:
        raise M0Error("M4 inner wheel event was not trusted")
    if wheel_events.get("deltaMode") != 0:
        raise M0Error("M4 inner wheel did not use pixel delta mode")
    if _require_number(
        wheel_events.get("deltaX"), "M4 inner wheel deltaX"
    ) != 0:
        raise M0Error("M4 inner wheel deltaX is not zero")
    if _require_number(
        wheel_events.get("deltaY"), "M4 inner wheel deltaY"
    ) != 160:
        raise M0Error("M4 inner wheel deltaY is not the trusted DOM delta")
    _require_safe_integer(
        page_probe.get("innerScrollTop"),
        "M4 inner scroll top",
        minimum=1,
    )
    for field in (
        "innerScrollLeft",
        "outerScrollLeft",
        "outerScrollTop",
        "documentScrollTop",
    ):
        if _require_safe_integer(
            page_probe.get(field), f"M4 wheel {field}"
        ) != 0:
            raise M0Error(f"M4 wheel {field} changed unexpectedly")

    wheel_input = _require_dict(
        result.get("wheelInput"), "M4 wheel input"
    )
    readiness_wheel = _require_dict(
        readiness.get("wheelInput"), "M4 readiness wheel input"
    )
    if wheel_input != readiness_wheel:
        raise M0Error("M4 wheel evidence differs from readiness evidence")
    if wheel_input.get("enabled") is not True:
        raise M0Error("M4 wheel listeners were not enabled")
    received_count = _require_safe_integer(
        wheel_input.get("receivedCount"),
        "M4 received wheel count",
        minimum=1,
    )
    trusted_count = _require_safe_integer(
        wheel_input.get("trustedCount"),
        "M4 trusted DOM wheel count",
        minimum=1,
    )
    queued_count = _require_safe_integer(
        wheel_input.get("queuedCount"),
        "M4 queued host wheel count",
        minimum=1,
    )
    if trusted_count > received_count or queued_count > received_count:
        raise M0Error("M4 wheel count exceeds received wheel records")
    last_queued = _require_dict(
        wheel_input.get("lastQueued"), "M4 last queued wheel"
    )
    for field, expected_value in {
        "type": "wheel",
        "trusted": True,
        "queued": True,
        "canvasFocused": True,
        "defaultPrevented": True,
        "deltaMode": 0,
        "deltaX": 0,
        "deltaY": 160,
    }.items():
        if last_queued.get(field) != expected_value:
            raise M0Error(
                f"M4 queued wheel {field} mismatch: expected "
                f"{expected_value!r}, got {last_queued.get(field)!r}"
            )
    if _require_number(
        last_queued.get("domDeltaX"), "M4 queued DOM wheel deltaX"
    ) != 0:
        raise M0Error("M4 queued DOM wheel deltaX is not zero")
    if _require_number(
        last_queued.get("domDeltaY"), "M4 queued DOM wheel deltaY"
    ) != 160:
        raise M0Error("M4 queued DOM wheel deltaY is not positive down")
    _require_safe_integer(
        last_queued.get("sequence"), "M4 wheel sequence", minimum=1
    )
    if _require_safe_integer(
        last_queued.get("x"),
        "M4 queued wheel x",
        minimum=0,
        maximum=M3_WIDTH - 1,
    ) != target_x:
        raise M0Error("M4 wheel x does not match the fixture target")
    if _require_safe_integer(
        last_queued.get("y"),
        "M4 queued wheel y",
        minimum=0,
        maximum=M3_HEIGHT - 1,
    ) != target_y:
        raise M0Error("M4 wheel y does not match the fixture target")
    input_frame_id = _require_safe_integer(
        last_queued.get("frameIdBefore"),
        "M4 wheel input frame ID",
        minimum=1,
    )
    if frame_id <= input_frame_id:
        raise M0Error("M4 result has no compositor frame after wheel input")

    shutdown = _require_dict(result.get("shutdown"), "M4 wheel shutdown")
    for field in ("ok", "accepted", "complete"):
        if shutdown.get(field) is not True:
            raise M0Error(f"M4 wheel shutdown {field} is not true")
    for field in ("exitCode", "runtimeExitCode"):
        if _require_safe_integer(
            shutdown.get(field), f"M4 wheel shutdown {field}"
        ) != 0:
            raise M0Error(f"M4 wheel shutdown {field} is not zero")

    logs = _require_dict(result.get("logs"), "M4 wheel logs")
    for stream in ("host", "stdout", "stderr"):
        if not isinstance(logs.get(stream), list):
            raise M0Error(f"M4 wheel {stream} log must be an array")
    combined_logs = "\n".join(
        str(line)
        for stream in ("host", "stdout", "stderr")
        for line in logs[stream]
    )
    if "abort:" in combined_logs.lower():
        raise M0Error("M4 wheel logs contain a Wasm abort")
    host_logs = [str(line) for line in logs["host"]]
    for marker in (
        "m4:wheel:listeners-attached",
        "m4:wheel:queued",
        "shutdown:complete",
    ):
        if not any(marker in line for line in host_logs):
            raise M0Error(
                f"M4 wheel logs are missing lifecycle marker {marker!r}"
            )


def validate_m4_keyboard_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
) -> None:
    """Validate trusted raw ArrowDown delivery through Ozone, Aura, and
    Blink."""

    expected = {
        "protocol": M3_PROTOCOL,
        "case": M4_KEYBOARD_CASE,
        "status": "pass",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "failedChecks": [],
        "error": None,
    }
    for field, expected_value in expected.items():
        actual_value = result.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 keyboard result {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )

    versions = _require_dict(
        result.get("versions"), "M4 keyboard versions"
    )
    if versions != expected_versions:
        raise M0Error(
            "M4 keyboard version display mismatch: expected "
            f"{expected_versions!r}, got {versions!r}"
        )

    readiness = _require_dict(
        result.get("readiness"), "M4 keyboard readiness"
    )
    for field in (
        "baseReady",
        "runtimeInitialized",
        "shellReady",
        "surfaceReady",
        "navigationCommitted",
        "firstVisuallyNonEmptyPaint",
        "pageReady",
    ):
        if readiness.get(field) is not True:
            raise M0Error(
                f"M4 keyboard readiness field {field} is not true"
            )
    if readiness.get("fatalErrors") != []:
        raise M0Error("M4 keyboard readiness reported fatal errors")
    heartbeat = _require_dict(
        readiness.get("heartbeat"), "M4 keyboard heartbeat"
    )
    if heartbeat.get("anchor") != "data-navigation-committed":
        raise M0Error(
            "M4 keyboard heartbeat was not anchored to data navigation"
        )
    _require_number(
        heartbeat.get("elapsedMs"),
        "M4 keyboard heartbeat elapsed time",
        minimum=0,
    )

    frame = _require_dict(readiness.get("frame"), "M4 keyboard frame")
    frame_id = _require_safe_integer(
        frame.get("id"), "M4 keyboard frame ID", minimum=1
    )
    _require_number(
        frame.get("timestampMs"), "M4 keyboard frame timestamp", minimum=0
    )
    if frame.get("width") != M3_WIDTH or frame.get("height") != M3_HEIGHT:
        raise M0Error(
            "M4 keyboard frame dimensions do not match the canvas"
        )

    page_probe = _require_dict(
        readiness.get("pageProbe"), "M4 keyboard page probe"
    )
    expected_probe = {
        "fontReady": True,
        "protocol": M3_PROTOCOL,
        "fixture": "chromium-wasm-m4-ozone-keyboard-v1",
        "ready": True,
        "activeElementId": "keyboard-target",
        "activationCount": 1,
        "clickTrusted": True,
        "focusTrusted": True,
        "resultText": "ARROW DOWN RECEIVED",
    }
    for field, expected_value in expected_probe.items():
        actual_value = page_probe.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 keyboard page probe {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )
    _require_safe_integer(
        page_probe.get("focusCount"),
        "M4 keyboard focus count",
        minimum=1,
    )
    target_x = _require_safe_integer(
        page_probe.get("targetCenterX"),
        "M4 keyboard target x",
        minimum=0,
        maximum=M3_WIDTH - 1,
    )
    target_y = _require_safe_integer(
        page_probe.get("targetCenterY"),
        "M4 keyboard target y",
        minimum=0,
        maximum=M3_HEIGHT - 1,
    )
    _require_safe_integer(
        page_probe.get("timerTicks"),
        "M4 keyboard inner page timer ticks",
        minimum=3,
    )
    _require_number(
        page_probe.get("scrollTop"),
        "M4 keyboard document scroll top",
        minimum=1,
    )
    key_events = _require_dict(
        page_probe.get("keyEvents"), "M4 inner key events"
    )
    for field in ("keydownCount", "keyupCount"):
        if _require_safe_integer(
            key_events.get(field), f"M4 inner {field}", minimum=1
        ) != 1:
            raise M0Error(f"M4 inner {field} is not exactly one")
    for event_name in ("keydown", "keyup"):
        expected_event = {
            f"{event_name}Trusted": True,
            f"{event_name}Code": "ArrowDown",
            f"{event_name}Key": "ArrowDown",
            f"{event_name}Repeat": False,
            f"{event_name}Composing": False,
            f"{event_name}DefaultPrevented": False,
            f"{event_name}TargetId": "keyboard-target",
        }
        for field, expected_value in expected_event.items():
            actual_value = key_events.get(field)
            if (
                type(actual_value) is not type(expected_value)
                or actual_value != expected_value
            ):
                raise M0Error(
                    f"M4 inner {field} mismatch: expected "
                    f"{expected_value!r}, got {actual_value!r}"
                )
    text_input_events = _require_dict(
        page_probe.get("textInputEvents"),
        "M4 keyboard text input events",
    )
    for field in (
        "beforeinputCount",
        "inputCount",
        "compositionstartCount",
        "compositionupdateCount",
        "compositionendCount",
    ):
        if _require_safe_integer(
            text_input_events.get(field),
            f"M4 keyboard {field}",
            minimum=0,
        ) != 0:
            raise M0Error(
                f"M4 keyboard unexpected text or composition event {field}"
            )

    pointer_input = _require_dict(
        result.get("pointerInput"), "M4 keyboard pointer input"
    )
    readiness_pointer = _require_dict(
        readiness.get("pointerInput"), "M4 keyboard readiness pointer input"
    )
    if pointer_input != readiness_pointer:
        raise M0Error(
            "M4 keyboard pointer evidence differs from readiness evidence"
        )
    if pointer_input.get("enabled") is not True:
        raise M0Error("M4 keyboard pointer listeners were not enabled")
    pointer_received = _require_safe_integer(
        pointer_input.get("receivedCount"),
        "M4 keyboard received pointer count",
        minimum=2,
    )
    pointer_trusted = _require_safe_integer(
        pointer_input.get("trustedCount"),
        "M4 keyboard trusted pointer count",
        minimum=2,
    )
    pointer_queued = _require_safe_integer(
        pointer_input.get("queuedCount"),
        "M4 keyboard queued pointer count",
        minimum=2,
    )
    if pointer_trusted > pointer_received or pointer_queued > pointer_received:
        raise M0Error(
            "M4 keyboard pointer count exceeds received pointer records"
        )
    last_pointer = _require_dict(
        pointer_input.get("lastQueued"),
        "M4 keyboard last queued pointer",
    )
    for field, expected_value in {
        "type": "up",
        "trusted": True,
        "queued": True,
        "canvasFocused": True,
    }.items():
        if last_pointer.get(field) != expected_value:
            raise M0Error(
                f"M4 keyboard queued pointer {field} mismatch: expected "
                f"{expected_value!r}, got {last_pointer.get(field)!r}"
            )
    if _require_safe_integer(
        last_pointer.get("x"),
        "M4 keyboard queued pointer x",
        minimum=0,
        maximum=M3_WIDTH - 1,
    ) != target_x:
        raise M0Error(
            "M4 keyboard pointer x does not match the fixture target"
        )
    if _require_safe_integer(
        last_pointer.get("y"),
        "M4 keyboard queued pointer y",
        minimum=0,
        maximum=M3_HEIGHT - 1,
    ) != target_y:
        raise M0Error(
            "M4 keyboard pointer y does not match the fixture target"
        )
    _require_safe_integer(
        last_pointer.get("sequence"),
        "M4 keyboard pointer sequence",
        minimum=1,
    )
    _require_safe_integer(
        last_pointer.get("frameIdBefore"),
        "M4 keyboard pointer frame ID",
        minimum=1,
    )

    keyboard_input = _require_dict(
        result.get("keyboardInput"), "M4 keyboard input"
    )
    readiness_keyboard = _require_dict(
        readiness.get("keyboardInput"), "M4 readiness keyboard input"
    )
    if keyboard_input != readiness_keyboard:
        raise M0Error(
            "M4 keyboard evidence differs from readiness evidence"
        )
    if keyboard_input.get("enabled") is not True:
        raise M0Error("M4 keyboard listeners were not enabled")
    if keyboard_input.get("activated") is not True:
        raise M0Error("M4 keyboard input was not activated by pointer input")
    if keyboard_input.get("pressedCodes") != []:
        raise M0Error("M4 keyboard key state was not released")
    keyboard_received = _require_safe_integer(
        keyboard_input.get("receivedCount"),
        "M4 received keyboard count",
        minimum=2,
    )
    keyboard_trusted = _require_safe_integer(
        keyboard_input.get("trustedCount"),
        "M4 trusted DOM keyboard count",
        minimum=2,
    )
    keyboard_queued = _require_safe_integer(
        keyboard_input.get("queuedCount"),
        "M4 queued host keyboard count",
        minimum=2,
    )
    if (
        keyboard_trusted > keyboard_received
        or keyboard_queued > keyboard_received
    ):
        raise M0Error(
            "M4 keyboard count exceeds received keyboard records"
        )

    def require_key_record(
        value: object, description: str, expected_type: str
    ) -> int:
        record = _require_dict(value, description)
        expected_record = {
            "type": expected_type,
            "code": "ArrowDown",
            "key": "ArrowDown",
            "trusted": True,
            "queued": True,
            "repeat": False,
            "isComposing": False,
            "canvasFocused": True,
            "pointerActivated": True,
            "defaultPrevented": True,
        }
        for field, expected_value in expected_record.items():
            actual_value = record.get(field)
            if (
                type(actual_value) is not type(expected_value)
                or actual_value != expected_value
            ):
                raise M0Error(
                    f"{description} {field} mismatch: expected "
                    f"{expected_value!r}, got {actual_value!r}"
                )
        if record.get("modifiers") != {
            "alt": False,
            "control": False,
            "meta": False,
            "shift": False,
        }:
            raise M0Error(f"{description} modifiers are not all false")
        _require_safe_integer(
            record.get("sequence"), f"{description} sequence", minimum=1
        )
        return _require_safe_integer(
            record.get("frameIdBefore"),
            f"{description} frame ID",
            minimum=1,
        )

    key_down_frame_id = require_key_record(
        keyboard_input.get("lastQueuedDown"),
        "M4 last queued key down",
        "down",
    )
    require_key_record(
        keyboard_input.get("lastQueuedUp"),
        "M4 last queued key up",
        "up",
    )
    if frame_id <= key_down_frame_id:
        raise M0Error(
            "M4 keyboard result has no compositor frame after raw key input"
        )

    shutdown = _require_dict(
        result.get("shutdown"), "M4 keyboard shutdown"
    )
    for field in ("ok", "accepted", "complete"):
        if shutdown.get(field) is not True:
            raise M0Error(f"M4 keyboard shutdown {field} is not true")
    for field in ("exitCode", "runtimeExitCode"):
        if _require_safe_integer(
            shutdown.get(field), f"M4 keyboard shutdown {field}"
        ) != 0:
            raise M0Error(f"M4 keyboard shutdown {field} is not zero")

    logs = _require_dict(result.get("logs"), "M4 keyboard logs")
    for stream in ("host", "stdout", "stderr"):
        if not isinstance(logs.get(stream), list):
            raise M0Error(f"M4 keyboard {stream} log must be an array")
    combined_logs = "\n".join(
        str(line)
        for stream in ("host", "stdout", "stderr")
        for line in logs[stream]
    )
    if "abort:" in combined_logs.lower():
        raise M0Error("M4 keyboard logs contain a Wasm abort")
    host_logs = [str(line) for line in logs["host"]]
    for marker in (
        "m4:pointer:listeners-attached",
        "m4:keyboard:listeners-attached",
        "m4:pointer:down:queued",
        "m4:pointer:up:queued",
        "m4:keyboard:pointer-activation",
        "m4:keyboard:down:queued",
        "m4:keyboard:up:queued",
        "shutdown:complete",
    ):
        if not any(marker in line for line in host_logs):
            raise M0Error(
                "M4 keyboard logs are missing lifecycle marker "
                f"{marker!r}"
            )


def validate_m4_printable_key_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
) -> None:
    """Validate one trusted US KeyA through Ozone, Aura, and direct text
    editing in Blink."""

    expected = {
        "protocol": M3_PROTOCOL,
        "case": M4_PRINTABLE_KEY_CASE,
        "status": "pass",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "failedChecks": [],
        "error": None,
    }
    for field, expected_value in expected.items():
        actual_value = result.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 printable-key result {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )

    versions = _require_dict(
        result.get("versions"), "M4 printable-key versions"
    )
    if versions != expected_versions:
        raise M0Error(
            "M4 printable-key version display mismatch: expected "
            f"{expected_versions!r}, got {versions!r}"
        )

    readiness = _require_dict(
        result.get("readiness"), "M4 printable-key readiness"
    )
    for field in (
        "baseReady",
        "runtimeInitialized",
        "shellReady",
        "surfaceReady",
        "navigationCommitted",
        "firstVisuallyNonEmptyPaint",
        "pageReady",
    ):
        if readiness.get(field) is not True:
            raise M0Error(
                f"M4 printable-key readiness field {field} is not true"
            )
    if readiness.get("fatalErrors") != []:
        raise M0Error("M4 printable-key readiness reported fatal errors")
    heartbeat = _require_dict(
        readiness.get("heartbeat"), "M4 printable-key heartbeat"
    )
    if heartbeat.get("anchor") != "data-navigation-committed":
        raise M0Error(
            "M4 printable-key heartbeat was not anchored to data navigation"
        )
    _require_number(
        heartbeat.get("elapsedMs"),
        "M4 printable-key heartbeat elapsed time",
        minimum=0,
    )

    frame = _require_dict(readiness.get("frame"), "M4 printable-key frame")
    frame_id = _require_safe_integer(
        frame.get("id"), "M4 printable-key frame ID", minimum=1
    )
    _require_number(
        frame.get("timestampMs"),
        "M4 printable-key frame timestamp",
        minimum=0,
    )
    if frame.get("width") != M3_WIDTH or frame.get("height") != M3_HEIGHT:
        raise M0Error(
            "M4 printable-key frame dimensions do not match the canvas"
        )

    page_probe = _require_dict(
        readiness.get("pageProbe"), "M4 printable-key page probe"
    )
    expected_probe = {
        "fontReady": True,
        "protocol": M3_PROTOCOL,
        "fixture": "chromium-wasm-m4-ozone-printable-key-v1",
        "ready": True,
        "activeElementId": "editable-target",
        "activationCount": 1,
        "clickTrusted": True,
        "focusTrusted": True,
        "value": "a",
        "selectionStart": 1,
        "selectionEnd": 1,
        "resultText": "TEXT INPUT RECEIVED",
    }
    for field, expected_value in expected_probe.items():
        actual_value = page_probe.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 printable-key page probe {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )
    _require_safe_integer(
        page_probe.get("focusCount"),
        "M4 printable-key focus count",
        minimum=1,
    )
    target_x = _require_safe_integer(
        page_probe.get("targetCenterX"),
        "M4 printable-key target x",
        minimum=0,
        maximum=M3_WIDTH - 1,
    )
    target_y = _require_safe_integer(
        page_probe.get("targetCenterY"),
        "M4 printable-key target y",
        minimum=0,
        maximum=M3_HEIGHT - 1,
    )
    _require_safe_integer(
        page_probe.get("timerTicks"),
        "M4 printable-key inner page timer ticks",
        minimum=3,
    )

    key_events = _require_dict(
        page_probe.get("keyEvents"), "M4 printable-key inner key events"
    )
    for field in ("keydownCount", "keyupCount"):
        if _require_safe_integer(
            key_events.get(field), f"M4 printable-key inner {field}", minimum=1
        ) != 1:
            raise M0Error(f"M4 printable-key inner {field} is not exactly one")
    for event_name in ("keydown", "keyup"):
        expected_event = {
            f"{event_name}Trusted": True,
            f"{event_name}Code": "KeyA",
            f"{event_name}Key": "a",
            f"{event_name}Repeat": False,
            f"{event_name}Composing": False,
            f"{event_name}DefaultPrevented": False,
            f"{event_name}TargetId": "editable-target",
        }
        for field, expected_value in expected_event.items():
            actual_value = key_events.get(field)
            if (
                type(actual_value) is not type(expected_value)
                or actual_value != expected_value
            ):
                raise M0Error(
                    f"M4 printable-key inner {field} mismatch: expected "
                    f"{expected_value!r}, got {actual_value!r}"
                )

    text_input_events = _require_dict(
        page_probe.get("textInputEvents"),
        "M4 printable-key text input events",
    )
    expected_text_events = {
        "beforeinputCount": 1,
        "inputCount": 1,
        "beforeinputTrusted": True,
        "inputTrusted": True,
        "beforeinputInputType": "insertText",
        "inputInputType": "insertText",
        "beforeinputData": "a",
        "inputData": "a",
        "beforeinputTargetId": "editable-target",
        "inputTargetId": "editable-target",
        "compositionstartCount": 0,
        "compositionupdateCount": 0,
        "compositionendCount": 0,
    }
    for field, expected_value in expected_text_events.items():
        actual_value = text_input_events.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 printable-key {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )

    pointer_input = _require_dict(
        result.get("pointerInput"), "M4 printable-key pointer input"
    )
    readiness_pointer = _require_dict(
        readiness.get("pointerInput"),
        "M4 printable-key readiness pointer input",
    )
    if pointer_input != readiness_pointer:
        raise M0Error(
            "M4 printable-key pointer evidence differs from readiness evidence"
        )
    if pointer_input.get("enabled") is not True:
        raise M0Error("M4 printable-key pointer listeners were not enabled")
    for field in ("receivedCount", "trustedCount", "queuedCount"):
        _require_safe_integer(
            pointer_input.get(field),
            f"M4 printable-key pointer {field}",
            minimum=2,
        )
    last_pointer = _require_dict(
        pointer_input.get("lastQueued"),
        "M4 printable-key last queued pointer",
    )
    for field, expected_value in {
        "type": "up",
        "trusted": True,
        "queued": True,
        "canvasFocused": True,
    }.items():
        if last_pointer.get(field) != expected_value:
            raise M0Error(
                f"M4 printable-key queued pointer {field} mismatch: expected "
                f"{expected_value!r}, got {last_pointer.get(field)!r}"
            )
    if _require_safe_integer(
        last_pointer.get("x"),
        "M4 printable-key queued pointer x",
        minimum=0,
        maximum=M3_WIDTH - 1,
    ) != target_x:
        raise M0Error(
            "M4 printable-key pointer x does not match the fixture target"
        )
    if _require_safe_integer(
        last_pointer.get("y"),
        "M4 printable-key queued pointer y",
        minimum=0,
        maximum=M3_HEIGHT - 1,
    ) != target_y:
        raise M0Error(
            "M4 printable-key pointer y does not match the fixture target"
        )
    _require_safe_integer(
        last_pointer.get("frameIdBefore"),
        "M4 printable-key pointer frame ID",
        minimum=1,
    )

    keyboard_input = _require_dict(
        result.get("keyboardInput"), "M4 printable-key keyboard input"
    )
    readiness_keyboard = _require_dict(
        readiness.get("keyboardInput"),
        "M4 printable-key readiness keyboard input",
    )
    if keyboard_input != readiness_keyboard:
        raise M0Error(
            "M4 printable-key keyboard evidence differs from readiness evidence"
        )
    if keyboard_input.get("enabled") is not True:
        raise M0Error("M4 printable-key listeners were not enabled")
    if keyboard_input.get("activated") is not True:
        raise M0Error(
            "M4 printable-key input was not activated by pointer input"
        )
    if keyboard_input.get("pressedCodes") != []:
        raise M0Error("M4 printable-key key state was not released")
    for field in ("receivedCount", "trustedCount", "queuedCount"):
        count = _require_safe_integer(
            keyboard_input.get(field),
            f"M4 printable-key keyboard {field}",
            minimum=2,
        )
        if count != 2:
            raise M0Error(
                f"M4 printable-key keyboard {field} is not exactly two"
            )

    def require_key_record(
        value: object, description: str, expected_type: str
    ) -> int:
        record = _require_dict(value, description)
        expected_record = {
            "type": expected_type,
            "code": "KeyA",
            "key": "a",
            "trusted": True,
            "queued": True,
            "repeat": False,
            "isComposing": False,
            "canvasFocused": True,
            "pointerActivated": True,
            "defaultPrevented": True,
        }
        for field, expected_value in expected_record.items():
            actual_value = record.get(field)
            if (
                type(actual_value) is not type(expected_value)
                or actual_value != expected_value
            ):
                raise M0Error(
                    f"{description} {field} mismatch: expected "
                    f"{expected_value!r}, got {actual_value!r}"
                )
        if record.get("modifiers") != {
            "alt": False,
            "control": False,
            "meta": False,
            "shift": False,
        }:
            raise M0Error(f"{description} modifiers are not all false")
        return _require_safe_integer(
            record.get("frameIdBefore"),
            f"{description} frame ID",
            minimum=1,
        )

    key_down_frame_id = require_key_record(
        keyboard_input.get("lastQueuedDown"),
        "M4 printable-key last queued key down",
        "down",
    )
    require_key_record(
        keyboard_input.get("lastQueuedUp"),
        "M4 printable-key last queued key up",
        "up",
    )
    if frame_id <= key_down_frame_id:
        raise M0Error(
            "M4 printable-key result has no compositor frame after text input"
        )

    shutdown = _require_dict(
        result.get("shutdown"), "M4 printable-key shutdown"
    )
    for field in ("ok", "accepted", "complete"):
        if shutdown.get(field) is not True:
            raise M0Error(f"M4 printable-key shutdown {field} is not true")
    for field in ("exitCode", "runtimeExitCode"):
        if _require_safe_integer(
            shutdown.get(field), f"M4 printable-key shutdown {field}"
        ) != 0:
            raise M0Error(f"M4 printable-key shutdown {field} is not zero")

    logs = _require_dict(result.get("logs"), "M4 printable-key logs")
    for stream in ("host", "stdout", "stderr"):
        if not isinstance(logs.get(stream), list):
            raise M0Error(
                f"M4 printable-key {stream} log must be an array"
            )
    combined_logs = "\n".join(
        str(line)
        for stream in ("host", "stdout", "stderr")
        for line in logs[stream]
    )
    if "abort:" in combined_logs.lower():
        raise M0Error("M4 printable-key logs contain a Wasm abort")
    host_logs = [str(line) for line in logs["host"]]
    for marker in (
        "m4:pointer:listeners-attached",
        "m4:keyboard:listeners-attached",
        "m4:pointer:down:queued",
        "m4:pointer:up:queued",
        "m4:keyboard:pointer-activation",
        "m4:keyboard:down:queued",
        "m4:keyboard:up:queued",
        "shutdown:complete",
    ):
        if not any(marker in line for line in host_logs):
            raise M0Error(
                "M4 printable-key logs are missing lifecycle marker "
                f"{marker!r}"
            )


def validate_m4_backspace_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
) -> None:
    """Validate a fixed-US KeyA insert followed by physical Backspace.

    The outer driver may queue only raw physical-key records. The exact
    trusted Blink trace below proves that normal text editing, rather than a
    DevTools text command or the composition bridge, inserted and then
    deleted the character.
    """

    expected = {
        "protocol": M3_PROTOCOL,
        "case": M4_BACKSPACE_CASE,
        "status": "pass",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "failedChecks": [],
        "error": None,
    }
    for field, expected_value in expected.items():
        actual_value = result.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 backspace result {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )

    versions = _require_dict(result.get("versions"), "M4 backspace versions")
    if versions != expected_versions:
        raise M0Error(
            "M4 backspace version display mismatch: expected "
            f"{expected_versions!r}, got {versions!r}"
        )

    readiness = _require_dict(result.get("readiness"), "M4 backspace readiness")
    for field in (
        "baseReady",
        "runtimeInitialized",
        "shellReady",
        "surfaceReady",
        "navigationCommitted",
        "firstVisuallyNonEmptyPaint",
        "pageReady",
    ):
        if readiness.get(field) is not True:
            raise M0Error(f"M4 backspace readiness field {field} is not true")
    if readiness.get("fatalErrors") != []:
        raise M0Error("M4 backspace readiness reported fatal errors")
    heartbeat = _require_dict(readiness.get("heartbeat"), "M4 backspace heartbeat")
    if heartbeat.get("anchor") != "data-navigation-committed":
        raise M0Error(
            "M4 backspace heartbeat was not anchored to data navigation"
        )
    _require_number(
        heartbeat.get("elapsedMs"),
        "M4 backspace heartbeat elapsed time",
        minimum=0,
    )

    frame = _require_dict(readiness.get("frame"), "M4 backspace frame")
    frame_id = _require_safe_integer(
        frame.get("id"), "M4 backspace frame ID", minimum=1
    )
    _require_number(
        frame.get("timestampMs"), "M4 backspace frame timestamp", minimum=0
    )
    for field, expected_value in {
        "width": M3_WIDTH,
        "height": M3_HEIGHT,
    }.items():
        actual_value = frame.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                "M4 backspace frame dimensions do not match the canvas"
            )

    page_probe = _require_dict(
        readiness.get("pageProbe"), "M4 backspace page probe"
    )
    expected_probe = {
        "fontReady": True,
        "protocol": M3_PROTOCOL,
        "fixture": "chromium-wasm-m4-ozone-backspace-v1",
        "ready": True,
        "activeElementId": "editable-target",
        "activationCount": 1,
        "clickTrusted": True,
        "focusTrusted": True,
        "value": "",
        "selectionStart": 0,
        "selectionEnd": 0,
        "resultText": "TEXT INSERTED THEN DELETED",
    }
    for field, expected_value in expected_probe.items():
        actual_value = page_probe.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 backspace page probe {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )
    _require_safe_integer(
        page_probe.get("focusCount"), "M4 backspace focus count", minimum=1
    )
    target_x = _require_safe_integer(
        page_probe.get("targetCenterX"),
        "M4 backspace target x",
        minimum=0,
        maximum=M3_WIDTH - 1,
    )
    target_y = _require_safe_integer(
        page_probe.get("targetCenterY"),
        "M4 backspace target y",
        minimum=0,
        maximum=M3_HEIGHT - 1,
    )
    _require_safe_integer(
        page_probe.get("timerTicks"),
        "M4 backspace inner page timer ticks",
        minimum=3,
    )

    key_event_trace = page_probe.get("keyEventTrace")
    if not isinstance(key_event_trace, list) or len(key_event_trace) != 4:
        raise M0Error("M4 backspace inner key trace is not exactly four events")
    expected_key_trace = (
        ("keydown", "KeyA", "a"),
        ("keyup", "KeyA", "a"),
        ("keydown", "Backspace", "Backspace"),
        ("keyup", "Backspace", "Backspace"),
    )
    for index, (event_type, code, key) in enumerate(expected_key_trace):
        record = _require_dict(
            key_event_trace[index], f"M4 backspace inner key trace {index}"
        )
        expected_record = {
            "type": event_type,
            "trusted": True,
            "code": code,
            "key": key,
            "repeat": False,
            "isComposing": False,
            "defaultPrevented": False,
            "targetId": "editable-target",
        }
        for field, expected_value in expected_record.items():
            actual_value = record.get(field)
            if (
                type(actual_value) is not type(expected_value)
                or actual_value != expected_value
            ):
                raise M0Error(
                    f"M4 backspace inner key trace {index} {field} mismatch: "
                    f"expected {expected_value!r}, got {actual_value!r}"
                )

    text_input_trace = page_probe.get("textInputTrace")
    if not isinstance(text_input_trace, list) or len(text_input_trace) != 4:
        raise M0Error("M4 backspace text trace is not exactly four events")
    expected_text_trace = (
        ("beforeinput", "insertText", "a"),
        ("input", "insertText", "a"),
        ("beforeinput", "deleteContentBackward", None),
        ("input", "deleteContentBackward", None),
    )
    for index, (event_type, input_type, data) in enumerate(expected_text_trace):
        record = _require_dict(
            text_input_trace[index], f"M4 backspace text trace {index}"
        )
        expected_record = {
            "type": event_type,
            "trusted": True,
            "inputType": input_type,
            "data": data,
            "isComposing": False,
            "targetId": "editable-target",
        }
        for field, expected_value in expected_record.items():
            actual_value = record.get(field)
            if (
                type(actual_value) is not type(expected_value)
                or actual_value != expected_value
            ):
                raise M0Error(
                    f"M4 backspace text trace {index} {field} mismatch: "
                    f"expected {expected_value!r}, got {actual_value!r}"
                )

    composition_counts = _require_dict(
        page_probe.get("compositionEventCounts"),
        "M4 backspace composition event counts",
    )
    for event_type in (
        "compositionstart",
        "compositionupdate",
        "compositionend",
    ):
        if _require_safe_integer(
            composition_counts.get(event_type),
            f"M4 backspace {event_type} count",
            minimum=0,
        ) != 0:
            raise M0Error(f"M4 backspace {event_type} count is not zero")

    pointer_input = _require_dict(
        result.get("pointerInput"), "M4 backspace pointer input"
    )
    readiness_pointer = _require_dict(
        readiness.get("pointerInput"), "M4 backspace readiness pointer input"
    )
    if not _exact_json_value_equal(pointer_input, readiness_pointer):
        raise M0Error(
            "M4 backspace pointer evidence differs from readiness evidence"
        )
    if pointer_input.get("enabled") is not True:
        raise M0Error("M4 backspace pointer listeners were not enabled")
    pointer_received = _require_safe_integer(
        pointer_input.get("receivedCount"),
        "M4 backspace pointer receivedCount",
        minimum=2,
    )
    pointer_trusted = _require_safe_integer(
        pointer_input.get("trustedCount"),
        "M4 backspace pointer trustedCount",
        minimum=2,
    )
    pointer_queued = _require_safe_integer(
        pointer_input.get("queuedCount"),
        "M4 backspace pointer queuedCount",
        minimum=2,
    )
    if pointer_trusted > pointer_received:
        raise M0Error(
            "M4 backspace trusted pointer count exceeds received pointer "
            "records"
        )
    if pointer_queued > pointer_trusted:
        raise M0Error(
            "M4 backspace queued pointer count exceeds trusted pointer "
            "records"
        )
    last_pointer = _require_dict(
        pointer_input.get("lastQueued"), "M4 backspace last queued pointer"
    )
    for field, expected_value in {
        "type": "up",
        "trusted": True,
        "queued": True,
        "canvasFocused": True,
    }.items():
        actual_value = last_pointer.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 backspace queued pointer {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )
    _require_safe_integer(
        last_pointer.get("sequence"),
        "M4 backspace queued pointer sequence",
        minimum=1,
    )
    if _require_safe_integer(
        last_pointer.get("x"),
        "M4 backspace queued pointer x",
        minimum=0,
        maximum=M3_WIDTH - 1,
    ) != target_x:
        raise M0Error("M4 backspace pointer x does not match the fixture target")
    if _require_safe_integer(
        last_pointer.get("y"),
        "M4 backspace queued pointer y",
        minimum=0,
        maximum=M3_HEIGHT - 1,
    ) != target_y:
        raise M0Error("M4 backspace pointer y does not match the fixture target")
    _require_safe_integer(
        last_pointer.get("frameIdBefore"),
        "M4 backspace pointer frame ID",
        minimum=1,
    )

    keyboard_input = _require_dict(
        result.get("keyboardInput"), "M4 backspace keyboard input"
    )
    readiness_keyboard = _require_dict(
        readiness.get("keyboardInput"), "M4 backspace readiness keyboard input"
    )
    if not _exact_json_value_equal(keyboard_input, readiness_keyboard):
        raise M0Error(
            "M4 backspace keyboard evidence differs from readiness evidence"
        )
    if keyboard_input.get("enabled") is not True:
        raise M0Error("M4 backspace keyboard listeners were not enabled")
    if keyboard_input.get("activated") is not True:
        raise M0Error("M4 backspace input was not activated by pointer input")
    if keyboard_input.get("pressedCodes") != []:
        raise M0Error("M4 backspace key state was not released")
    for field in ("receivedCount", "trustedCount", "queuedCount"):
        count = _require_safe_integer(
            keyboard_input.get(field),
            f"M4 backspace keyboard {field}",
            minimum=4,
        )
        if count != 4:
            raise M0Error(
                f"M4 backspace keyboard {field} is not exactly four"
            )

    queued_records = keyboard_input.get("queuedRecords")
    if not isinstance(queued_records, list) or len(queued_records) != 4:
        raise M0Error("M4 backspace queued key trace is not exactly four records")
    expected_queue = (
        ("down", "KeyA", "a"),
        ("up", "KeyA", "a"),
        ("down", "Backspace", "Backspace"),
        ("up", "Backspace", "Backspace"),
    )
    previous_sequence = 0
    backspace_down_frame_id = 0
    for index, (event_type, code, key) in enumerate(expected_queue):
        record = _require_dict(
            queued_records[index], f"M4 backspace queued key trace {index}"
        )
        expected_record = {
            "type": event_type,
            "code": code,
            "key": key,
            "trusted": True,
            "queued": True,
            "repeat": False,
            "isComposing": False,
            "canvasFocused": True,
            "pointerActivated": True,
            "defaultPrevented": True,
        }
        for field, expected_value in expected_record.items():
            actual_value = record.get(field)
            if (
                type(actual_value) is not type(expected_value)
                or actual_value != expected_value
            ):
                raise M0Error(
                    f"M4 backspace queued key trace {index} {field} mismatch: "
                    f"expected {expected_value!r}, got {actual_value!r}"
                )
        expected_modifiers = {
            "alt": False,
            "control": False,
            "meta": False,
            "shift": False,
        }
        modifiers = record.get("modifiers")
        if type(modifiers) is not dict:
            raise M0Error(
                f"M4 backspace queued key trace {index} modifiers are not "
                "all false"
            )
        for field, expected_value in expected_modifiers.items():
            actual_value = modifiers.get(field)
            if (
                type(actual_value) is not type(expected_value)
                or actual_value != expected_value
            ):
                raise M0Error(
                    f"M4 backspace queued key trace {index} modifiers are not "
                    "all false"
                )
        if set(modifiers) != set(expected_modifiers):
            raise M0Error(
                f"M4 backspace queued key trace {index} modifiers are not "
                "all false"
            )
        sequence = _require_safe_integer(
            record.get("sequence"),
            f"M4 backspace queued key trace {index} sequence",
            minimum=previous_sequence + 1,
        )
        if sequence <= previous_sequence:
            raise M0Error(
                "M4 backspace queued key trace sequence is not strictly "
                "increasing"
            )
        previous_sequence = sequence
        record_frame_id = _require_safe_integer(
            record.get("frameIdBefore"),
            f"M4 backspace queued key trace {index} frame ID",
            minimum=1,
        )
        if index == 2:
            backspace_down_frame_id = record_frame_id

    if keyboard_input.get("lastQueuedDown") != queued_records[2]:
        raise M0Error("M4 backspace last queued key down is not Backspace")
    if keyboard_input.get("lastQueuedUp") != queued_records[3]:
        raise M0Error("M4 backspace last queued key up is not Backspace")
    if frame_id <= backspace_down_frame_id:
        raise M0Error(
            "M4 backspace result has no compositor frame after Backspace"
        )

    shutdown = _require_dict(result.get("shutdown"), "M4 backspace shutdown")
    for field in ("ok", "accepted", "complete"):
        if shutdown.get(field) is not True:
            raise M0Error(f"M4 backspace shutdown {field} is not true")
    for field in ("exitCode", "runtimeExitCode"):
        if _require_safe_integer(
            shutdown.get(field), f"M4 backspace shutdown {field}"
        ) != 0:
            raise M0Error(f"M4 backspace shutdown {field} is not zero")

    logs = _require_dict(result.get("logs"), "M4 backspace logs")
    for stream in ("host", "stdout", "stderr"):
        entries = logs.get(stream)
        if type(entries) is not list:
            raise M0Error(f"M4 backspace {stream} log must be an array")
        for index, entry in enumerate(entries):
            if type(entry) is not str:
                raise M0Error(
                    f"M4 backspace {stream} log entry {index} must be a "
                    "string"
                )
    combined_logs = "\n".join(
        line
        for stream in ("host", "stdout", "stderr")
        for line in logs[stream]
    )
    if "abort:" in combined_logs.lower():
        raise M0Error("M4 backspace logs contain a Wasm abort")
    host_logs = logs["host"]
    for marker in (
        "m4:pointer:listeners-attached",
        "m4:keyboard:listeners-attached",
        "m4:pointer:down:queued",
        "m4:pointer:up:queued",
        "m4:keyboard:pointer-activation",
        "m4:keyboard:down:queued",
        "m4:keyboard:up:queued",
        "shutdown:complete",
    ):
        if not any(marker in line for line in host_logs):
            raise M0Error(
                "M4 backspace logs are missing lifecycle marker "
                f"{marker!r}"
            )


def validate_m4_ime_bridge_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
    terminal_mode: str = "commit",
) -> None:
    """Validate one trusted proxy composition reaches the Blink editor.

    The outer textarea is solely the browser-owned IME capture surface. This
    gate requires its bounded, trusted records to be acknowledged by the
    Ozone-owned InputMethod and then observes the resulting native Blink
    composition and terminal action in the inner editor. ``terminal_mode`` is
    either ``commit`` or ``cancel``. It intentionally exposes only text
    summaries in the result; the candidate string itself stays private to the
    host bridge.
    """

    if terminal_mode not in ("commit", "cancel"):
        raise M0Error(
            "M4 IME bridge terminal mode must be 'commit' or 'cancel', got "
            f"{terminal_mode!r}"
        )
    is_cancellation = terminal_mode == "cancel"

    expected = {
        "protocol": M3_PROTOCOL,
        "case": M4_IME_BRIDGE_CASE,
        "status": "pass",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": False,
        "proxyFocused": True,
        "terminalMode": terminal_mode,
        "failedChecks": [],
        "error": None,
    }
    for field, expected_value in expected.items():
        actual_value = result.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 IME bridge result {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )

    versions = _require_dict(result.get("versions"), "M4 IME bridge versions")
    if versions != expected_versions:
        raise M0Error(
            "M4 IME bridge version display mismatch: expected "
            f"{expected_versions!r}, got {versions!r}"
        )

    readiness = _require_dict(result.get("readiness"), "M4 IME bridge readiness")
    for field in (
        "baseReady",
        "runtimeInitialized",
        "shellReady",
        "surfaceReady",
        "navigationCommitted",
        "firstVisuallyNonEmptyPaint",
        "pageReady",
    ):
        if readiness.get(field) is not True:
            raise M0Error(
                f"M4 IME bridge readiness field {field} is not true"
            )
    if readiness.get("fatalErrors") != []:
        raise M0Error("M4 IME bridge readiness reported fatal errors")
    heartbeat = _require_dict(
        readiness.get("heartbeat"), "M4 IME bridge heartbeat"
    )
    if heartbeat.get("anchor") != "data-navigation-committed":
        raise M0Error(
            "M4 IME bridge heartbeat was not anchored to data navigation"
        )
    _require_number(
        heartbeat.get("elapsedMs"),
        "M4 IME bridge heartbeat elapsed time",
        minimum=0,
    )
    frame = _require_dict(readiness.get("frame"), "M4 IME bridge frame")
    _require_safe_integer(frame.get("id"), "M4 IME bridge frame ID", minimum=1)
    if frame.get("width") != M3_WIDTH or frame.get("height") != M3_HEIGHT:
        raise M0Error("M4 IME bridge frame dimensions do not match the canvas")

    page_probe = _require_dict(
        readiness.get("pageProbe"), "M4 IME bridge page probe"
    )
    expected_text_summary = {
        "utf16Length": 2,
        "utf8Bytes": 4,
        "codePointCount": 1,
    }
    empty_text_summary = {
        "utf16Length": 0,
        "utf8Bytes": 0,
        "codePointCount": 0,
    }
    terminal_text_summary = (
        empty_text_summary if is_cancellation else expected_text_summary
    )
    terminal_value_matches_expected = not is_cancellation
    terminal_selection = 0 if is_cancellation else 2
    # Both terminal paths have the same inner lifecycle cardinality. An
    # empty ``Input.imeSetComposition`` produces a second trusted
    # update/beforeinput/input triplet before its observed compositionend.
    terminal_event_count = 2
    terminal_accepted_count = 7 if is_cancellation else 8
    terminal_derived_count = 0 if is_cancellation else 1
    terminal_observed_clear_count = 1 if is_cancellation else 0
    terminal_native_queued_count = 2 if is_cancellation else 3
    terminal_set_delivery_count = 1 if is_cancellation else 2
    terminal_confirm_delivery_count = 0 if is_cancellation else 1
    terminal_clear_delivery_count = 1 if is_cancellation else 0
    terminal_native_action = 3 if is_cancellation else 2
    terminal_native_action_name = (
        "clear-composition" if is_cancellation else "confirm-composition"
    )
    # The native terminal must be bound to the outer source record that
    # authorizes it: trusted empty input is record 7 for cancellation, while
    # the constrained compositionend acknowledgement is record 8 for commit.
    terminal_native_sequence = 7 if is_cancellation else 8
    terminal_result_text = (
        "INNER EDITOR COMPOSITION ENDED"
        if is_cancellation
        else "INNER EDITOR COMMITTED"
    )
    expected_probe = {
        "fontReady": True,
        "protocol": M3_PROTOCOL,
        "fixture": "chromium-wasm-m4-ozone-ime-bridge-v1",
        "ready": True,
        "activeElementId": "editable-target",
        "activationCount": 1,
        "clickTrusted": True,
        "focusTrusted": True,
        "valueMatchesExpected": terminal_value_matches_expected,
        "selectionStart": terminal_selection,
        "selectionEnd": terminal_selection,
        "resultText": terminal_result_text,
    }
    for field, expected_value in expected_probe.items():
        actual_value = page_probe.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 IME bridge page probe {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )

    if page_probe.get("value") != terminal_text_summary:
        raise M0Error("M4 IME bridge inner value summary is invalid")
    _require_safe_integer(
        page_probe.get("focusCount"),
        "M4 IME bridge inner focus count",
        minimum=1,
    )
    _require_safe_integer(
        page_probe.get("targetCenterX"),
        "M4 IME bridge target x",
        minimum=0,
        maximum=M3_WIDTH - 1,
    )
    _require_safe_integer(
        page_probe.get("targetCenterY"),
        "M4 IME bridge target y",
        minimum=0,
        maximum=M3_HEIGHT - 1,
    )
    text_events = _require_dict(
        page_probe.get("textInputEvents"), "M4 IME bridge inner text events"
    )
    exact_text_event_counts = {
        "compositionstartCount": 1,
        "compositionupdateCount": terminal_event_count,
        "beforeinputCount": terminal_event_count,
        "inputCount": terminal_event_count,
        "compositionendCount": 1,
    }
    for field, expected_count in exact_text_event_counts.items():
        actual_count = _require_safe_integer(
            text_events.get(field), f"M4 IME bridge inner {field}", minimum=0
        )
        if actual_count != expected_count:
            raise M0Error(
                f"M4 IME bridge inner {field} must be exactly "
                f"{expected_count}"
            )

    def trace_record(
        event_type: str,
        data: dict[str, int] | None,
        data_matches_expected: bool,
        value: dict[str, int],
        selection_start: int,
        selection_end: int,
        trusted: bool,
    ) -> dict[str, Any]:
        is_text_input = event_type in ("beforeinput", "input")
        return {
            "type": event_type,
            "data": data,
            "dataMatchesExpected": data_matches_expected,
            "trusted": trusted,
            "inputType": "insertCompositionText" if is_text_input else None,
            "isComposing": is_text_input,
            "value": value,
            "selectionStart": selection_start,
            "selectionEnd": selection_end,
        }

    # Chromium marks the source composition transaction trusted, but dispatches
    # its terminal compositionend through the scoped event queue as untrusted.
    # Bind both sides of that boundary in the inner Blink trace.
    candidate_trace = [
        trace_record(
            "compositionstart",
            empty_text_summary,
            False,
            empty_text_summary,
            0,
            0,
            True,
        ),
        trace_record(
            "compositionupdate",
            expected_text_summary,
            True,
            empty_text_summary,
            0,
            0,
            True,
        ),
        trace_record(
            "beforeinput",
            expected_text_summary,
            True,
            empty_text_summary,
            0,
            0,
            True,
        ),
        trace_record(
            "input",
            expected_text_summary,
            True,
            expected_text_summary,
            2,
            2,
            True,
        ),
    ]
    if is_cancellation:
        expected_text_trace = candidate_trace + [
            trace_record(
                "compositionupdate",
                empty_text_summary,
                False,
                expected_text_summary,
                0,
                2,
                True,
            ),
            trace_record(
                "beforeinput",
                empty_text_summary,
                False,
                expected_text_summary,
                0,
                2,
                True,
            ),
            trace_record(
                "input", None, False, empty_text_summary, 0, 0, True
            ),
            trace_record(
                "compositionend",
                empty_text_summary,
                False,
                empty_text_summary,
                0,
                0,
                False,
            ),
        ]
    else:
        expected_text_trace = candidate_trace + [
            trace_record(
                "compositionupdate",
                expected_text_summary,
                True,
                expected_text_summary,
                0,
                2,
                True,
            ),
            trace_record(
                "beforeinput",
                expected_text_summary,
                True,
                expected_text_summary,
                0,
                2,
                True,
            ),
            trace_record(
                "input",
                expected_text_summary,
                True,
                expected_text_summary,
                2,
                2,
                True,
            ),
            trace_record(
                "compositionend",
                expected_text_summary,
                True,
                expected_text_summary,
                2,
                2,
                False,
            ),
        ]

    text_trace = page_probe.get("textInputTrace")
    if not isinstance(text_trace, list):
        raise M0Error("M4 IME bridge inner text trace must be an array")
    if len(text_trace) != len(expected_text_trace):
        raise M0Error(
            "M4 IME bridge inner text trace does not match event counts"
        )
    for index, expected_entry in enumerate(expected_text_trace):
        entry = _require_dict(
            text_trace[index], f"M4 IME bridge inner text trace {index}"
        )
        if entry != expected_entry:
            raise M0Error(
                "M4 IME bridge inner text trace record "
                f"{index} does not match the {terminal_mode} lifecycle"
            )

    pointer_input = _require_dict(
        result.get("pointerInput"), "M4 IME bridge pointer input"
    )
    if pointer_input != readiness.get("pointerInput"):
        raise M0Error(
            "M4 IME bridge pointer evidence differs from readiness evidence"
        )
    if pointer_input.get("enabled") is not True:
        raise M0Error("M4 IME bridge pointer listeners were not enabled")
    for field in ("receivedCount", "trustedCount", "queuedCount"):
        _require_safe_integer(
            pointer_input.get(field),
            f"M4 IME bridge pointer {field}",
            minimum=2,
        )
    last_pointer = _require_dict(
        pointer_input.get("lastQueued"), "M4 IME bridge last queued pointer"
    )
    for field, expected_value in {
        "type": "up",
        "trusted": True,
        "queued": True,
    }.items():
        if last_pointer.get(field) != expected_value:
            raise M0Error(
                f"M4 IME bridge queued pointer {field} mismatch: expected "
                f"{expected_value!r}, got {last_pointer.get(field)!r}"
            )

    focus_input = _require_dict(
        result.get("focusInput"), "M4 IME bridge focus input"
    )
    if focus_input != readiness.get("focusInput"):
        raise M0Error(
            "M4 IME bridge focus evidence differs from readiness evidence"
        )
    if (
        focus_input.get("enabled") is not True
        or focus_input.get("hostWindowActive") is not True
    ):
        raise M0Error("M4 IME bridge proxy focus deactivated Aura/Ozone")

    ozone_focus = _require_dict(
        readiness.get("ozoneFocusState"), "M4 IME bridge Ozone focus state"
    )
    if (
        ozone_focus.get("keyboardTargetPresent") is not True
        or ozone_focus.get("active") is not True
    ):
        raise M0Error("M4 IME bridge proxy focus lost Ozone's keyboard target")
    _require_safe_integer(
        ozone_focus.get("sequence"), "M4 IME bridge Ozone focus sequence", minimum=1
    )

    ozone_text_input = _require_dict(
        readiness.get("ozoneTextInputState"),
        "M4 IME bridge Ozone text-input state",
    )
    for field in ("focusedClientPresent", "editable", "canComposeInline"):
        if ozone_text_input.get(field) is not True:
            raise M0Error(
                f"M4 IME bridge native text-input acknowledgement {field} "
                "is not true"
            )
    _require_safe_integer(
        ozone_text_input.get("sequence"),
        "M4 IME bridge Ozone text-input sequence",
        minimum=1,
    )

    ime_proxy = _require_dict(
        result.get("imeProxyInput"), "M4 IME bridge proxy input"
    )
    readiness_proxy = _require_dict(
        readiness.get("imeProxyInput"), "M4 IME bridge readiness proxy input"
    )
    if ime_proxy != readiness_proxy:
        raise M0Error(
            "M4 IME bridge proxy evidence differs from readiness evidence"
        )
    expected_proxy = {
        "enabled": True,
        "present": True,
        "focused": True,
        "hostWindowActive": True,
        "sessionId": 1,
        "receivedCount": 8,
        "trustedCount": 7,
        "acceptedCount": terminal_accepted_count,
        "derivedTerminalCount": terminal_derived_count,
        "observedClearTerminalCount": terminal_observed_clear_count,
        "compositionStartCount": 1,
        "compositionUpdateCount": 2,
        "compositionEndCount": 1,
        "beforeinputCount": 2,
        "inputCount": 2,
        "compositionActive": False,
        "terminalCancellationPending": False,
        "pendingTransaction": False,
        "activationPending": False,
        "nativeTextInputReady": True,
        "nativeQueuedCount": terminal_native_queued_count,
        "nativeSetDeliveryCount": terminal_set_delivery_count,
        "nativeConfirmDeliveryCount": terminal_confirm_delivery_count,
        "nativeClearDeliveryCount": terminal_clear_delivery_count,
        "nativePendingDelivery": False,
        "nativeCompositionActive": False,
        "nativeTerminalAction": None,
        "failure": None,
    }
    for field, expected_value in expected_proxy.items():
        actual_value = ime_proxy.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 IME bridge proxy {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )
    _require_safe_integer(
        ime_proxy.get("focusCount"), "M4 IME bridge proxy focus count", minimum=1
    )
    if _require_safe_integer(
        ime_proxy.get("blurCount"), "M4 IME bridge proxy blur count", minimum=0
    ) != 0:
        raise M0Error("M4 IME bridge proxy blurred during composition")
    transaction = _require_dict(
        ime_proxy.get("lastConfirmedTransaction"),
        "M4 IME bridge confirmed transaction",
    )
    expected_transaction = {
        "sessionId": 1,
        "opcode": "set-composition",
        "rangeStart": 0,
        "rangeEnd": 2,
        "selection": {"start": 2, "end": 2},
        "text": {"utf16Length": 2, "utf8Bytes": 4, "codePointCount": 1},
    }
    for field, expected_value in expected_transaction.items():
        if transaction.get(field) != expected_value:
            raise M0Error(
                f"M4 IME bridge transaction {field} mismatch: expected "
                f"{expected_value!r}, got {transaction.get(field)!r}"
            )
    _require_safe_integer(
        transaction.get("sequence"), "M4 IME bridge transaction sequence", minimum=1
    )
    last_native_delivery = _require_dict(
        ime_proxy.get("lastNativeDelivery"),
        "M4 IME bridge last native delivery",
    )
    expected_last_native_delivery = {
        "action": terminal_native_action,
        "actionName": terminal_native_action_name,
        "sessionId": 1,
        "sequence": terminal_native_sequence,
        "queued": True,
        "deliveryAccepted": True,
        "text": None,
        "selection": {"start": 0, "end": 0},
    }
    for field, expected_value in expected_last_native_delivery.items():
        actual_value = last_native_delivery.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 IME bridge last native delivery {field} mismatch: "
                f"expected {expected_value!r}, got {actual_value!r}"
            )
    proxy_text = _require_dict(
        ime_proxy.get("proxyText"), "M4 IME bridge proxy text summary"
    )
    if proxy_text != {
        **terminal_text_summary,
        "selection": {
            "start": terminal_selection,
            "end": terminal_selection,
        },
    }:
        raise M0Error("M4 IME bridge proxy range summary is invalid")

    shutdown = _require_dict(result.get("shutdown"), "M4 IME bridge shutdown")
    for field in ("ok", "accepted", "complete"):
        if shutdown.get(field) is not True:
            raise M0Error(f"M4 IME bridge shutdown {field} is not true")
    for field in ("exitCode", "runtimeExitCode"):
        if _require_safe_integer(
            shutdown.get(field), f"M4 IME bridge shutdown {field}"
        ) != 0:
            raise M0Error(f"M4 IME bridge shutdown {field} is not zero")

    logs = _require_dict(result.get("logs"), "M4 IME bridge logs")
    for stream in ("host", "stdout", "stderr"):
        if not isinstance(logs.get(stream), list):
            raise M0Error(f"M4 IME bridge {stream} log must be an array")
    combined_logs = "\n".join(
        str(line)
        for stream in ("host", "stdout", "stderr")
        for line in logs[stream]
    )
    if "abort:" in combined_logs.lower():
        raise M0Error("M4 IME bridge logs contain a Wasm abort")
    host_logs = [str(line) for line in logs["host"]]
    common_markers = (
        "m4:pointer:listeners-attached",
        "m4:focus:listeners-attached",
        "m4:ime-proxy:listeners-attached",
        "m4:ime-proxy:pointer-arm-awaiting-native-editable",
        "ozone:text-input:client-present:editable:inline",
        "m4:focus:canvas-blur:expected-proxy-transfer",
        "m4:ime-proxy:native-editable-focus",
        "m4:ime-proxy:compositionstart:accepted",
        "m4:ime-proxy:compositionupdate:accepted",
        "m4:ime-proxy:beforeinput:native-set-queued",
        "ozone:text-input-delivery:set-composition:accepted",
        "m4:ime-proxy:input:confirmed-native-set",
        "shutdown:complete",
    )
    terminal_markers = (
        (
            "m4:ime-proxy:compositionupdate:cancellation-pending",
            "m4:ime-proxy:beforeinput:cancellation-pending",
            "m4:ime-proxy:input:native-clear-queued",
            "ozone:text-input-delivery:clear-composition:accepted",
            "m4:ime-proxy:compositionend:clear-observed",
        )
        if is_cancellation
        else (
            "m4:ime-proxy:compositionend:native-confirm-queued",
            "ozone:text-input-delivery:confirm-composition:accepted",
        )
    )
    for marker in common_markers + terminal_markers:
        if not any(marker in line for line in host_logs):
            raise M0Error(
                "M4 IME bridge logs are missing lifecycle marker "
                f"{marker!r}"
            )


def validate_m4_focus_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
) -> None:
    """Validate a trusted host focus loss clears Aura and Ozone state."""

    expected = {
        "protocol": M3_PROTOCOL,
        "case": M4_FOCUS_CASE,
        "status": "pass",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": False,
        "failedChecks": [],
        "error": None,
    }
    for field, expected_value in expected.items():
        actual_value = result.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 focus result {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )

    versions = _require_dict(result.get("versions"), "M4 focus versions")
    if versions != expected_versions:
        raise M0Error(
            "M4 focus version display mismatch: expected "
            f"{expected_versions!r}, got {versions!r}"
        )

    readiness = _require_dict(result.get("readiness"), "M4 focus readiness")
    for field in (
        "baseReady",
        "runtimeInitialized",
        "shellReady",
        "surfaceReady",
        "navigationCommitted",
        "firstVisuallyNonEmptyPaint",
        "pageReady",
    ):
        if readiness.get(field) is not True:
            raise M0Error(f"M4 focus readiness field {field} is not true")
    if readiness.get("fatalErrors") != []:
        raise M0Error("M4 focus readiness reported fatal errors")
    heartbeat = _require_dict(
        readiness.get("heartbeat"), "M4 focus heartbeat"
    )
    if heartbeat.get("anchor") != "data-navigation-committed":
        raise M0Error("M4 focus heartbeat was not anchored to data navigation")
    _require_number(
        heartbeat.get("elapsedMs"), "M4 focus heartbeat elapsed time", minimum=0
    )

    frame = _require_dict(readiness.get("frame"), "M4 focus frame")
    frame_id = _require_safe_integer(
        frame.get("id"), "M4 focus frame ID", minimum=1
    )
    _require_number(
        frame.get("timestampMs"), "M4 focus frame timestamp", minimum=0
    )
    if frame.get("width") != M3_WIDTH or frame.get("height") != M3_HEIGHT:
        raise M0Error("M4 focus frame dimensions do not match the canvas")

    page_probe = _require_dict(
        readiness.get("pageProbe"), "M4 focus page probe"
    )
    expected_probe = {
        "fontReady": True,
        "protocol": M3_PROTOCOL,
        "fixture": "chromium-wasm-m4-ozone-focus-v1",
        "ready": True,
        "activeElementId": "focus-target",
        "activationCount": 1,
        "clickTrusted": True,
        "focusTrusted": True,
        "windowBlurTrusted": True,
        "documentHasFocus": False,
        "resultText": "WINDOW BLURRED",
    }
    for field, expected_value in expected_probe.items():
        actual_value = page_probe.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 focus page probe {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )
    _require_safe_integer(
        page_probe.get("focusCount"), "M4 focus target focus count", minimum=1
    )
    _require_safe_integer(
        page_probe.get("windowBlurCount"), "M4 focus inner window blur count",
        minimum=1,
    )
    target_x = _require_safe_integer(
        page_probe.get("targetCenterX"),
        "M4 focus target x",
        minimum=0,
        maximum=M3_WIDTH - 1,
    )
    target_y = _require_safe_integer(
        page_probe.get("targetCenterY"),
        "M4 focus target y",
        minimum=0,
        maximum=M3_HEIGHT - 1,
    )
    _require_safe_integer(
        page_probe.get("timerTicks"), "M4 focus inner page timer ticks", minimum=3
    )
    _require_number(
        page_probe.get("scrollTop"), "M4 focus document scroll top", minimum=1
    )
    key_events = _require_dict(
        page_probe.get("keyEvents"), "M4 focus inner key events"
    )
    for field in ("keydownCount", "keyupCount"):
        if _require_safe_integer(
            key_events.get(field), f"M4 focus inner {field}", minimum=1
        ) != 1:
            raise M0Error(f"M4 focus inner {field} is not exactly one")
    for event_name in ("keydown", "keyup"):
        expected_event = {
            f"{event_name}Trusted": True,
            f"{event_name}Code": "ArrowDown",
            f"{event_name}Key": "ArrowDown",
            f"{event_name}Repeat": False,
            f"{event_name}Composing": False,
            f"{event_name}DefaultPrevented": False,
            f"{event_name}TargetId": "focus-target",
        }
        for field, expected_value in expected_event.items():
            actual_value = key_events.get(field)
            if (
                type(actual_value) is not type(expected_value)
                or actual_value != expected_value
            ):
                raise M0Error(
                    f"M4 focus inner {field} mismatch: expected "
                    f"{expected_value!r}, got {actual_value!r}"
                )

    pointer_input = _require_dict(
        result.get("pointerInput"), "M4 focus pointer input"
    )
    readiness_pointer = _require_dict(
        readiness.get("pointerInput"), "M4 focus readiness pointer input"
    )
    if pointer_input != readiness_pointer:
        raise M0Error("M4 focus pointer evidence differs from readiness evidence")
    if pointer_input.get("enabled") is not True:
        raise M0Error("M4 focus pointer listeners were not enabled")
    for count_name, minimum in (
        ("receivedCount", 2),
        ("trustedCount", 2),
        ("queuedCount", 2),
    ):
        _require_safe_integer(
            pointer_input.get(count_name),
            f"M4 focus pointer {count_name}",
            minimum=minimum,
        )
    last_pointer = _require_dict(
        pointer_input.get("lastQueued"), "M4 focus last queued pointer"
    )
    for field, expected_value in {
        "type": "up",
        "trusted": True,
        "queued": True,
        "canvasFocused": True,
    }.items():
        if last_pointer.get(field) != expected_value:
            raise M0Error(
                f"M4 focus queued pointer {field} mismatch: expected "
                f"{expected_value!r}, got {last_pointer.get(field)!r}"
            )
    if _require_safe_integer(
        last_pointer.get("x"),
        "M4 focus queued pointer x",
        minimum=0,
        maximum=M3_WIDTH - 1,
    ) != target_x:
        raise M0Error("M4 focus pointer x does not match the fixture target")
    if _require_safe_integer(
        last_pointer.get("y"),
        "M4 focus queued pointer y",
        minimum=0,
        maximum=M3_HEIGHT - 1,
    ) != target_y:
        raise M0Error("M4 focus pointer y does not match the fixture target")

    keyboard_input = _require_dict(
        result.get("keyboardInput"), "M4 focus keyboard input"
    )
    readiness_keyboard = _require_dict(
        readiness.get("keyboardInput"), "M4 focus readiness keyboard input"
    )
    if keyboard_input != readiness_keyboard:
        raise M0Error("M4 focus keyboard evidence differs from readiness evidence")
    if keyboard_input.get("enabled") is not True:
        raise M0Error("M4 focus keyboard listeners were not enabled")
    if keyboard_input.get("activated") is not False:
        raise M0Error("M4 focus keyboard activation survived host focus loss")
    if keyboard_input.get("pressedCodes") != []:
        raise M0Error("M4 focus key state was not released before deactivation")
    keyboard_received = _require_safe_integer(
        keyboard_input.get("receivedCount"),
        "M4 focus received keyboard count",
        minimum=2,
    )
    keyboard_trusted = _require_safe_integer(
        keyboard_input.get("trustedCount"),
        "M4 focus trusted DOM keyboard count",
        minimum=1,
    )
    keyboard_queued = _require_safe_integer(
        keyboard_input.get("queuedCount"),
        "M4 focus queued host keyboard count",
        minimum=2,
    )
    if keyboard_trusted > keyboard_received or keyboard_queued > keyboard_received:
        raise M0Error("M4 focus keyboard count exceeds received records")
    key_down = _require_dict(
        keyboard_input.get("lastQueuedDown"), "M4 focus last queued key down"
    )
    for field, expected_value in {
        "type": "down",
        "code": "ArrowDown",
        "key": "ArrowDown",
        "trusted": True,
        "queued": True,
        "repeat": False,
        "isComposing": False,
        "canvasFocused": True,
        "pointerActivated": True,
        "defaultPrevented": True,
    }.items():
        if key_down.get(field) != expected_value:
            raise M0Error(
                f"M4 focus key down {field} mismatch: expected "
                f"{expected_value!r}, got {key_down.get(field)!r}"
            )
    key_down_frame_id = _require_safe_integer(
        key_down.get("frameIdBefore"), "M4 focus key down frame ID", minimum=1
    )
    key_up = _require_dict(
        keyboard_input.get("lastQueuedUp"), "M4 focus generated key up"
    )
    for field, expected_value in {
        "type": "up",
        "code": "ArrowDown",
        "key": "ArrowDown",
        "trusted": False,
        "queued": True,
        "generated": True,
        "trigger": "canvas-blur",
        "triggerTrusted": True,
        "relatedTargetId": "m4-focus-sink",
        "repeat": False,
        "isComposing": False,
        "canvasFocused": False,
        "pointerActivated": False,
    }.items():
        if key_up.get(field) != expected_value:
            raise M0Error(
                f"M4 focus generated key up {field} mismatch: expected "
                f"{expected_value!r}, got {key_up.get(field)!r}"
            )
    key_up_frame_id = _require_safe_integer(
        key_up.get("frameIdBefore"), "M4 focus key up frame ID", minimum=1
    )
    if key_up_frame_id < key_down_frame_id:
        raise M0Error("M4 focus generated key up precedes the held key down")

    focus_input = _require_dict(result.get("focusInput"), "M4 focus input")
    readiness_focus = _require_dict(
        readiness.get("focusInput"), "M4 readiness focus input"
    )
    if focus_input != readiness_focus:
        raise M0Error("M4 focus evidence differs from readiness evidence")
    if focus_input.get("enabled") is not True:
        raise M0Error("M4 focus listeners were not enabled")
    if focus_input.get("hostWindowActive") is not False:
        raise M0Error("M4 Ozone window remained active after host focus loss")
    _require_safe_integer(
        focus_input.get("receivedCount"), "M4 focus received focus count", minimum=2
    )
    _require_safe_integer(
        focus_input.get("trustedCount"), "M4 trusted focus count", minimum=2
    )
    _require_safe_integer(
        focus_input.get("queuedCount"), "M4 queued focus count", minimum=2
    )
    focus_loss = _require_dict(
        focus_input.get("lastQueuedFocusLoss"), "M4 queued focus loss"
    )
    for field, expected_value in {
        "type": "canvas-blur",
        "trusted": True,
        "queued": True,
        "canvasFocused": False,
        "relatedTargetId": "m4-focus-sink",
    }.items():
        if focus_loss.get(field) != expected_value:
            raise M0Error(
                f"M4 queued focus loss {field} mismatch: expected "
                f"{expected_value!r}, got {focus_loss.get(field)!r}"
            )
    focus_loss_frame_id = _require_safe_integer(
        focus_loss.get("frameIdBefore"), "M4 focus loss frame ID", minimum=1
    )
    if frame_id <= focus_loss_frame_id:
        raise M0Error("M4 focus result has no compositor frame after focus loss")

    ozone_focus_state = _require_dict(
        result.get("ozoneFocusState"), "M4 focus Ozone focus state"
    )
    readiness_ozone_focus_state = _require_dict(
        readiness.get("ozoneFocusState"), "M4 readiness Ozone focus state"
    )
    if ozone_focus_state != readiness_ozone_focus_state:
        raise M0Error("M4 focus Ozone state differs from readiness evidence")
    if ozone_focus_state.get("keyboardTargetPresent") is not False:
        raise M0Error("M4 Ozone keyboard target remained after host focus loss")
    if ozone_focus_state.get("active") is not False:
        raise M0Error("M4 Ozone window remained active after host focus loss")
    ozone_focus_sequence = _require_safe_integer(
        ozone_focus_state.get("sequence"), "M4 Ozone focus report sequence", minimum=1
    )
    focus_report_sequence_before = _require_safe_integer(
        focus_loss.get("ozoneFocusReportSequenceBefore"),
        "M4 focus report sequence before deactivation",
        minimum=0,
    )
    if ozone_focus_sequence <= focus_report_sequence_before:
        raise M0Error("M4 Ozone focus state was not reported after deactivation")

    focus_sink_click = _require_dict(
        result.get("focusSinkClick"), "M4 focus sink click"
    )
    if focus_sink_click.get("trusted") is not True:
        raise M0Error("M4 host focus sink click was not trusted")
    if focus_sink_click.get("defaultPrevented") is not False:
        raise M0Error("M4 host focus sink click default was prevented")

    shutdown = _require_dict(result.get("shutdown"), "M4 focus shutdown")
    for field in ("ok", "accepted", "complete"):
        if shutdown.get(field) is not True:
            raise M0Error(f"M4 focus shutdown {field} is not true")
    for field in ("exitCode", "runtimeExitCode"):
        if _require_safe_integer(
            shutdown.get(field), f"M4 focus shutdown {field}"
        ) != 0:
            raise M0Error(f"M4 focus shutdown {field} is not zero")

    logs = _require_dict(result.get("logs"), "M4 focus logs")
    for stream in ("host", "stdout", "stderr"):
        if not isinstance(logs.get(stream), list):
            raise M0Error(f"M4 focus {stream} log must be an array")
    combined_logs = "\n".join(
        str(line)
        for stream in ("host", "stdout", "stderr")
        for line in logs[stream]
    )
    if "abort:" in combined_logs.lower():
        raise M0Error("M4 focus logs contain a Wasm abort")
    host_logs = [str(line) for line in logs["host"]]
    for marker in (
        "m4:pointer:listeners-attached",
        "m4:keyboard:listeners-attached",
        "m4:focus:listeners-attached",
        "m4:pointer:down:queued",
        "m4:pointer:up:queued",
        "m4:keyboard:pointer-activation",
        "m4:focus:pointer-activation",
        "m4:keyboard:down:queued",
        "m4:keyboard:canvas-blur:release-queued",
        "m4:focus:canvas-blur:deactivate-queued",
        "ozone:focus:keyboard-target-absent:inactive",
        "shutdown:complete",
    ):
        if not any(marker in line for line in host_logs):
            raise M0Error(
                "M4 focus logs are missing lifecycle marker " f"{marker!r}"
            )


@dataclass(frozen=True)
class PNGImage:
    width: int
    height: int
    rgba: bytes


def decode_png(png_bytes: bytes) -> PNGImage:
    """Decode the non-interlaced 8-bit RGB/RGBA PNGs emitted by canvas."""

    signature = b"\x89PNG\r\n\x1a\n"
    if not png_bytes.startswith(signature):
        raise M0Error("screenshot does not start with the PNG signature")
    offset = len(signature)
    width = height = color_type = bit_depth = interlace = None
    compressed = bytearray()
    saw_end = False
    while offset < len(png_bytes):
        if offset + 12 > len(png_bytes):
            raise M0Error("PNG chunk header is truncated")
        length = struct.unpack(">I", png_bytes[offset : offset + 4])[0]
        chunk_type = png_bytes[offset + 4 : offset + 8]
        chunk_start = offset + 8
        chunk_end = chunk_start + length
        crc_end = chunk_end + 4
        if crc_end > len(png_bytes):
            raise M0Error("PNG chunk payload is truncated")
        payload = png_bytes[chunk_start:chunk_end]
        expected_crc = struct.unpack(">I", png_bytes[chunk_end:crc_end])[0]
        actual_crc = zlib.crc32(chunk_type)
        actual_crc = zlib.crc32(payload, actual_crc) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise M0Error(f"PNG {chunk_type!r} chunk has a bad CRC")
        offset = crc_end
        if chunk_type == b"IHDR":
            if length != 13 or width is not None:
                raise M0Error("PNG has an invalid IHDR chunk")
            (
                width,
                height,
                bit_depth,
                color_type,
                compression_method,
                filter_method,
                interlace,
            ) = struct.unpack(">IIBBBBB", payload)
            if (
                width <= 0
                or height <= 0
                or width > 16384
                or height > 16384
                or width * height > 16 * 1024 * 1024
                or bit_depth != 8
                or color_type not in (2, 6)
                or compression_method != 0
                or filter_method != 0
                or interlace != 0
            ):
                raise M0Error(
                    "PNG must be non-interlaced 8-bit RGB or RGBA"
                )
        elif chunk_type == b"IDAT":
            if width is None:
                raise M0Error("PNG IDAT appeared before IHDR")
            compressed.extend(payload)
        elif chunk_type == b"IEND":
            if length != 0:
                raise M0Error("PNG IEND chunk is not empty")
            saw_end = True
            break
    if (
        width is None
        or height is None
        or color_type is None
        or bit_depth is None
        or interlace is None
        or not compressed
        or not saw_end
    ):
        raise M0Error("PNG is missing required chunks")
    try:
        filtered = zlib.decompress(bytes(compressed))
    except zlib.error as exc:
        raise M0Error("PNG IDAT stream cannot be decompressed") from exc
    channels = 4 if color_type == 6 else 3
    row_bytes = width * channels
    expected_bytes = height * (row_bytes + 1)
    if len(filtered) != expected_bytes:
        raise M0Error(
            f"PNG scanline size mismatch: expected {expected_bytes}, "
            f"got {len(filtered)}"
        )

    decoded = bytearray(height * row_bytes)
    source_offset = 0
    for row in range(height):
        filter_type = filtered[source_offset]
        source_offset += 1
        if filter_type > 4:
            raise M0Error(f"PNG uses unknown filter {filter_type}")
        row_start = row * row_bytes
        previous_start = row_start - row_bytes
        for column in range(row_bytes):
            raw = filtered[source_offset]
            source_offset += 1
            left = decoded[row_start + column - channels] if (
                column >= channels
            ) else 0
            above = decoded[previous_start + column] if row > 0 else 0
            upper_left = (
                decoded[previous_start + column - channels]
                if row > 0 and column >= channels
                else 0
            )
            if filter_type == 0:
                value = raw
            elif filter_type == 1:
                value = raw + left
            elif filter_type == 2:
                value = raw + above
            elif filter_type == 3:
                value = raw + ((left + above) // 2)
            else:
                estimate = left + above - upper_left
                left_distance = abs(estimate - left)
                above_distance = abs(estimate - above)
                upper_left_distance = abs(estimate - upper_left)
                predictor = (
                    left
                    if left_distance <= above_distance
                    and left_distance <= upper_left_distance
                    else above
                    if above_distance <= upper_left_distance
                    else upper_left
                )
                value = raw + predictor
            decoded[row_start + column] = value & 0xFF

    if channels == 4:
        rgba = bytes(decoded)
    else:
        expanded = bytearray(width * height * 4)
        for pixel in range(width * height):
            rgb_offset = pixel * 3
            rgba_offset = pixel * 4
            expanded[rgba_offset : rgba_offset + 3] = decoded[
                rgb_offset : rgb_offset + 3
            ]
            expanded[rgba_offset + 3] = 255
        rgba = bytes(expanded)
    return PNGImage(width=width, height=height, rgba=rgba)


@dataclass(frozen=True)
class ScreenshotComparison:
    width: int
    height: int
    different_pixels: int
    different_pixel_ratio: float
    maximum_channel_delta: int
    mean_channel_delta: float
    channel_tolerance: int
    maximum_different_pixel_ratio: float

    @property
    def matches(self) -> bool:
        return (
            self.different_pixel_ratio
            <= self.maximum_different_pixel_ratio
        )

    def as_dict(self) -> dict[str, int | float | bool]:
        return {
            "matches": self.matches,
            "width": self.width,
            "height": self.height,
            "differentPixels": self.different_pixels,
            "differentPixelRatio": self.different_pixel_ratio,
            "maximumChannelDelta": self.maximum_channel_delta,
            "meanChannelDelta": self.mean_channel_delta,
            "channelTolerance": self.channel_tolerance,
            "maximumDifferentPixelRatio": (
                self.maximum_different_pixel_ratio
            ),
        }


def compare_screenshots(
    actual_png: bytes,
    expected_png: bytes,
    *,
    channel_tolerance: int,
    maximum_different_pixel_ratio: float,
) -> ScreenshotComparison:
    if not 0 <= channel_tolerance <= 255:
        raise M0Error("screenshot channel tolerance is out of range")
    if not 0 <= maximum_different_pixel_ratio <= 1:
        raise M0Error("maximum different-pixel ratio is out of range")
    actual = decode_png(actual_png)
    expected = decode_png(expected_png)
    if (actual.width, actual.height) != (expected.width, expected.height):
        raise M0Error(
            "screenshot dimensions differ: actual "
            f"{actual.width}x{actual.height}, expected "
            f"{expected.width}x{expected.height}"
        )

    different_pixels = 0
    maximum_delta = 0
    total_delta = 0
    for pixel_offset in range(0, len(actual.rgba), 4):
        pixel_is_different = False
        for channel in range(4):
            delta = abs(
                actual.rgba[pixel_offset + channel]
                - expected.rgba[pixel_offset + channel]
            )
            maximum_delta = max(maximum_delta, delta)
            total_delta += delta
            if delta > channel_tolerance:
                pixel_is_different = True
        if pixel_is_different:
            different_pixels += 1
    pixel_count = actual.width * actual.height
    comparison = ScreenshotComparison(
        width=actual.width,
        height=actual.height,
        different_pixels=different_pixels,
        different_pixel_ratio=different_pixels / pixel_count,
        maximum_channel_delta=maximum_delta,
        mean_channel_delta=total_delta / (pixel_count * 4),
        channel_tolerance=channel_tolerance,
        maximum_different_pixel_ratio=maximum_different_pixel_ratio,
    )
    return comparison


def load_screenshot_contract(
    path: Path = M3_SCREENSHOT_CONTRACT,
) -> dict[str, Any]:
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise M0Error(f"cannot read M3 screenshot contract: {exc}") from exc
    if not isinstance(contract, dict) or contract.get("schema_version") != 1:
        raise M0Error("M3 screenshot contract schema is unsupported")
    if (
        contract.get("width") != M3_WIDTH
        or contract.get("height") != M3_HEIGHT
    ):
        raise M0Error("M3 screenshot contract dimensions changed")
    _require_number(
        contract.get("channel_tolerance"),
        "M3 screenshot channel tolerance",
        minimum=0,
    )
    ratio = _require_number(
        contract.get("maximum_different_pixel_ratio"),
        "M3 maximum different-pixel ratio",
        minimum=0,
    )
    if ratio > 1:
        raise M0Error("M3 maximum different-pixel ratio exceeds one")
    return contract
