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
M4_SELECT_CASE = "ozone_select_m4"
M4_RESIZE_CASE = "ozone_resize_m4"
M4_DPR_CASE = "ozone_dpr_m4"
M4_CONTEXT_MENU_CASE = "ozone_context_menu_m4"
M4_TOOLTIP_CASE = "ozone_tooltip_m4"
M4_SELECTION_CASE = "ozone_selection_m4"
M4_PRIMARY_PASTE_CASE = "ozone_primary_paste_m4"
M4_COPY_PASTE_CASE = "ozone_copy_paste_m4"
M4_WHEEL_CASE = "ozone_wheel_m4"
M4_KEYBOARD_CASE = "ozone_keyboard_m4"
M4_PRINTABLE_KEY_CASE = "ozone_printable_key_m4"
M4_BACKSPACE_CASE = "ozone_backspace_m4"
M4_FOCUS_CASE = "ozone_focus_m4"
M4_FOCUS_RETENTION_CASE = "ozone_focus_retention_m4"
M4_IME_BRIDGE_CASE = "ozone_ime_bridge_m4"
M5_WISP_CASE = "wisp_network_m5"
M5_PUBLIC_HTTPS_CASE = "wisp_public_https_m5"
M3_PROTOCOL = 1
M3_RESULT_CASES = (
    M3_CASE,
    M4_CASE,
    M4_SELECT_CASE,
    M4_RESIZE_CASE,
    M4_DPR_CASE,
    M4_CONTEXT_MENU_CASE,
    M4_TOOLTIP_CASE,
    M4_SELECTION_CASE,
    M4_PRIMARY_PASTE_CASE,
    M4_COPY_PASTE_CASE,
    M4_WHEEL_CASE,
    M4_KEYBOARD_CASE,
    M4_PRINTABLE_KEY_CASE,
    M4_BACKSPACE_CASE,
    M4_IME_BRIDGE_CASE,
    M4_FOCUS_CASE,
    M4_FOCUS_RETENTION_CASE,
    M5_WISP_CASE,
    M5_PUBLIC_HTTPS_CASE,
)
M3_WIDTH = 800
M3_HEIGHT = 600
M4_RESIZE_NARROW_WIDTH = 640
M4_RESIZE_NARROW_HEIGHT = 480
M4_DPR_SCALE = 2
M4_TOOLTIP_CLEAR_QUIESCENCE_MS = 750
M4_TOOLTIP_RAPID_MOVE_MAX_GAP_MS = 250
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
M4_SELECT_FIXTURE = M3_TESTDATA_DIR / "m4_ozone_select_page.html"
M4_RESIZE_FIXTURE = M3_TESTDATA_DIR / "m4_ozone_resize_page.html"
M4_CONTEXT_MENU_FIXTURE = M3_TESTDATA_DIR / "m4_ozone_context_menu_page.html"
M4_TOOLTIP_FIXTURE = M3_TESTDATA_DIR / "m4_ozone_tooltip_page.html"
M4_SELECTION_FIXTURE = M3_TESTDATA_DIR / "m4_ozone_selection_page.html"
M4_PRIMARY_PASTE_FIXTURE = (
    M3_TESTDATA_DIR / "m4_ozone_primary_paste_page.html"
)
M4_COPY_PASTE_FIXTURE = M3_TESTDATA_DIR / "m4_ozone_copy_paste_page.html"
M4_WHEEL_FIXTURE = M3_TESTDATA_DIR / "m4_ozone_wheel_page.html"
M4_KEYBOARD_FIXTURE = M3_TESTDATA_DIR / "m4_ozone_keyboard_page.html"
M4_PRINTABLE_KEY_FIXTURE = (
    M3_TESTDATA_DIR / "m4_ozone_printable_key_page.html"
)
M4_BACKSPACE_FIXTURE = M3_TESTDATA_DIR / "m4_ozone_backspace_page.html"
M4_FOCUS_FIXTURE = M3_TESTDATA_DIR / "m4_ozone_focus_page.html"
M4_FOCUS_RETENTION_FIXTURE = (
    M3_TESTDATA_DIR / "m4_ozone_focus_retention_page.html"
)
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


def is_supported_result_case(value: object) -> bool:
    return isinstance(value, str) and value in M3_RESULT_CASES


def _reject_duplicate_result_object_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    """Keep JSON result validation from silently collapsing duplicate fields."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON result object key")
        result[key] = value
    return result


def _parse_result_payload(payload: bytes) -> dict[str, Any] | None:
    """Decode one bounded host result before it enters the one-shot queue."""

    try:
        result = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_result_object_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    if (
        not isinstance(result, dict)
        or type(result.get("protocol")) is not int
        or result.get("protocol") != M3_PROTOCOL
    ):
        return None
    return result


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
            "/__m3__/m4-select-fixture.html": M4_SELECT_FIXTURE,
            "/__m3__/m4-resize-fixture.html": M4_RESIZE_FIXTURE,
            "/__m3__/m4-context-menu-fixture.html": M4_CONTEXT_MENU_FIXTURE,
            "/__m3__/m4-tooltip-fixture.html": M4_TOOLTIP_FIXTURE,
            "/__m3__/m4-selection-fixture.html": M4_SELECTION_FIXTURE,
            "/__m3__/m4-primary-paste-fixture.html": M4_PRIMARY_PASTE_FIXTURE,
            "/__m3__/m4-copy-paste-fixture.html": M4_COPY_PASTE_FIXTURE,
            "/__m3__/m4-wheel-fixture.html": M4_WHEEL_FIXTURE,
            "/__m3__/m4-keyboard-fixture.html": M4_KEYBOARD_FIXTURE,
            "/__m3__/m4-printable-key-fixture.html": M4_PRINTABLE_KEY_FIXTURE,
            "/__m3__/m4-backspace-fixture.html": M4_BACKSPACE_FIXTURE,
            "/__m3__/m4-focus-fixture.html": M4_FOCUS_FIXTURE,
            "/__m3__/m4-focus-retention-fixture.html": (
                M4_FOCUS_RETENTION_FIXTURE
            ),
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
        result = _parse_result_payload(self.rfile.read(length))
        if result is None or not is_supported_result_case(result.get("case")):
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


def m4_select_smoke_url(
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
            "case": M4_SELECT_CASE,
            "chromium": versions["chromium"],
            "emscripten": versions["emscripten"],
            "fixture": "/__m3__/m4-select-fixture.html",
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


def m4_resize_smoke_url(
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
            "case": M4_RESIZE_CASE,
            "chromium": versions["chromium"],
            "emscripten": versions["emscripten"],
            "fixture": "/__m3__/m4-resize-fixture.html",
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


def m4_dpr_smoke_url(
    server: M3HTTPServer,
    token: str,
    versions: dict[str, str],
    *,
    module_name: str = "content_shell_wasm",
    timeout_seconds: float = 90.0,
) -> str:
    """Build the bounded 1x-to-2x DPR smoke URL."""

    host, port = server.server_address[:2]
    query = urlencode(
        {
            "case": M4_DPR_CASE,
            "chromium": versions["chromium"],
            "emscripten": versions["emscripten"],
            # This probe already records the target's trusted CSS pointer
            # trace. Its additive display geometry proves the DPR transition.
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


def m4_primary_paste_smoke_url(
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
            "case": M4_PRIMARY_PASTE_CASE,
            "chromium": versions["chromium"],
            "emscripten": versions["emscripten"],
            "fixture": "/__m3__/m4-primary-paste-fixture.html",
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


def m4_context_menu_smoke_url(
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
            "case": M4_CONTEXT_MENU_CASE,
            "chromium": versions["chromium"],
            "emscripten": versions["emscripten"],
            "fixture": "/__m3__/m4-context-menu-fixture.html",
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


def m4_tooltip_smoke_url(
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
            "case": M4_TOOLTIP_CASE,
            "chromium": versions["chromium"],
            "emscripten": versions["emscripten"],
            "fixture": "/__m3__/m4-tooltip-fixture.html",
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


def m4_copy_paste_smoke_url(
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
            "case": M4_COPY_PASTE_CASE,
            "chromium": versions["chromium"],
            "emscripten": versions["emscripten"],
            "fixture": "/__m3__/m4-copy-paste-fixture.html",
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


def m4_focus_retention_smoke_url(
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
            "case": M4_FOCUS_RETENTION_CASE,
            "chromium": versions["chromium"],
            "emscripten": versions["emscripten"],
            "fixture": "/__m3__/m4-focus-retention-fixture.html",
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


def _require_m4_native_link_navigation(
    page_probe: dict[str, Any], description: str
) -> None:
    """Require one target-frame load caused by the uncancelled link click."""

    load_count_before = _require_safe_integer(
        page_probe.get("navigationFrameLoadCountBeforeActivation"),
        f"{description} navigation frame load count before activation",
        minimum=1,
    )
    load_count = _require_safe_integer(
        page_probe.get("navigationFrameLoadCount"),
        f"{description} navigation frame load count",
        minimum=2,
    )
    if load_count != load_count_before + 1:
        raise M0Error(
            f"{description} navigation target did not load exactly once "
            "after link activation"
        )
    if page_probe.get("navigationFrameLastLoadTrusted") is not True:
        raise M0Error(f"{description} navigation target load was not trusted")


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
        "fixture": "chromium-wasm-m4-ozone-pointer-v2",
        "ready": True,
        "activationCount": 1,
        "clickTrusted": True,
        "clickDefaultPrevented": False,
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
    _require_m4_native_link_navigation(page_probe, "M4 page probe")
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
    pointer_move_trace = page_probe.get("pointerMoveTrace")
    if not isinstance(pointer_move_trace, list) or not any(
        isinstance(record, dict)
        and record.get("type") == "pointermove"
        and record.get("trusted") is True
        and record.get("targetId") == "m4-link"
        and record.get("clientX") == target_x
        and record.get("clientY") == target_y
        for record in pointer_move_trace
    ):
        raise M0Error("M4 inner pointer hover did not reach the link")
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

    cursor = _require_dict(readiness.get("ozoneCursor"), "M4 Ozone cursor")
    result_cursor = _require_dict(result.get("cursor"), "M4 result cursor")
    if result_cursor != cursor:
        raise M0Error("M4 cursor evidence differs from readiness evidence")
    cursor_sequence = _require_safe_integer(
        cursor.get("sequence"), "M4 Ozone cursor sequence", minimum=1
    )
    cursor_sequence_before_input = _require_safe_integer(
        result.get("cursorReportSequenceBeforeInput"),
        "M4 Ozone cursor sequence before input",
        minimum=0,
    )
    if cursor_sequence <= cursor_sequence_before_input:
        raise M0Error("M4 Ozone cursor did not update after trusted hover")
    if cursor.get("cursorType") != 2:
        raise M0Error("M4 Ozone cursor type is not the Blink hand cursor")
    if cursor.get("cssCursor") != "pointer" or cursor.get("exact") is not True:
        raise M0Error("M4 host canvas cursor is not an exact pointer mapping")

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
        "ozone:cursor:2:pointer:exact",
        "shutdown:complete",
    ):
        if not any(marker in line for line in host_logs):
            raise M0Error(f"M4 logs are missing lifecycle marker {marker!r}")


def validate_m4_select_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
) -> None:
    """Validate native select popup rendering and pointer selection in M4."""

    expected = {
        "protocol": M3_PROTOCOL,
        "case": M4_SELECT_CASE,
        "status": "pass",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "popupClosed": True,
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
                f"M4 select result {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )

    versions = _require_dict(result.get("versions"), "M4 select versions")
    if versions != expected_versions:
        raise M0Error(
            "M4 select version display mismatch: expected "
            f"{expected_versions!r}, got {versions!r}"
        )

    readiness = _require_dict(result.get("readiness"), "M4 select readiness")
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
            raise M0Error(f"M4 select readiness field {field} is not true")
    if readiness.get("fatalErrors") != []:
        raise M0Error("M4 select readiness reported fatal errors")
    heartbeat = _require_dict(
        readiness.get("heartbeat"), "M4 select heartbeat"
    )
    if heartbeat.get("anchor") != "data-navigation-committed":
        raise M0Error("M4 select heartbeat was not anchored to data navigation")
    _require_number(
        heartbeat.get("elapsedMs"),
        "M4 select heartbeat elapsed time",
        minimum=0,
    )
    frame = _require_dict(readiness.get("frame"), "M4 select frame")
    frame_id = _require_safe_integer(
        frame.get("id"), "M4 select frame ID", minimum=1
    )
    _require_number(
        frame.get("timestampMs"), "M4 select frame timestamp", minimum=0
    )
    if frame.get("width") != M3_WIDTH or frame.get("height") != M3_HEIGHT:
        raise M0Error("M4 select frame dimensions do not match the canvas")

    page_probe = _require_dict(
        readiness.get("pageProbe"), "M4 select page probe"
    )
    expected_probe = {
        "fontReady": True,
        "protocol": M3_PROTOCOL,
        "fixture": "chromium-wasm-m4-ozone-select-v1",
        "ready": True,
        "selectValue": "two",
        "selectedIndex": 1,
        "resultText": "SELECTED:two",
    }
    for field, expected_value in expected_probe.items():
        actual_value = page_probe.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 select page probe {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )
    target_x = _require_safe_integer(
        page_probe.get("targetCenterX"),
        "M4 select target x",
        minimum=0,
        maximum=M3_WIDTH - 1,
    )
    target_y = _require_safe_integer(
        page_probe.get("targetCenterY"),
        "M4 select target y",
        minimum=0,
        maximum=M3_HEIGHT - 1,
    )
    _require_safe_integer(
        page_probe.get("timerTicks"),
        "M4 select inner page timer ticks",
        minimum=3,
    )
    target_bounds = _require_dict(
        page_probe.get("targetBounds"), "M4 select target bounds"
    )
    bounds: dict[str, int] = {}
    for field, maximum in (
        ("left", M3_WIDTH - 1),
        ("right", M3_WIDTH),
        ("top", M3_HEIGHT - 1),
        ("bottom", M3_HEIGHT),
    ):
        bounds[field] = _require_safe_integer(
            target_bounds.get(field),
            f"M4 select target {field}",
            minimum=0,
            maximum=maximum,
        )
    if bounds["right"] <= bounds["left"] or bounds["bottom"] <= bounds["top"]:
        raise M0Error("M4 select target bounds are empty")
    if target_x != (bounds["left"] + bounds["right"]) // 2 or target_y != (
        bounds["top"] + bounds["bottom"]
    ) // 2:
        raise M0Error("M4 select target center does not match its bounds")

    def require_trusted_select_event(
        trace: object,
        event_type: str,
        description: str,
    ) -> dict[str, Any]:
        if not isinstance(trace, list):
            raise M0Error(f"{description} must be an array")
        for record in trace:
            if (
                isinstance(record, dict)
                and record.get("type") == event_type
                and record.get("trusted") is True
                and record.get("targetId") == "select-target"
                and record.get("clientX") == target_x
                and record.get("clientY") == target_y
            ):
                return record
        raise M0Error(
            f"M4 select has no trusted {event_type} event at the opener"
        )

    opener_trace = page_probe.get("openerEventTrace")
    for event_type in ("pointerdown", "mousedown", "pointerup", "mouseup", "click"):
        require_trusted_select_event(
            opener_trace, event_type, "M4 select opener event trace"
        )

    def require_select_commit_event(
        trace_name: str,
        event_type: str,
    ) -> dict[str, Any]:
        trace = page_probe.get(trace_name)
        if not isinstance(trace, list) or len(trace) != 1:
            raise M0Error(f"M4 select {trace_name} is not exactly one event")
        event = _require_dict(trace[0], f"M4 select {trace_name} event")
        if (
            event.get("type") != event_type
            or event.get("trusted") is not True
            or event.get("targetId") != "select-target"
            or event.get("value") != "two"
            or event.get("selectedIndex") != 1
        ):
            raise M0Error(f"M4 select {trace_name} is not a trusted commit")
        _require_safe_integer(
            event.get("sequence"),
            f"M4 select {trace_name} sequence",
            minimum=1,
        )
        return event

    input_event = require_select_commit_event("inputEventTrace", "input")
    change_event = require_select_commit_event("changeEventTrace", "change")
    if input_event["sequence"] >= change_event["sequence"]:
        raise M0Error("M4 select change did not follow trusted input")

    popup_option_scan = _require_dict(
        result.get("popupOptionScan"), "M4 select popup option scan"
    )
    if popup_option_scan.get("rgba") != [250, 0, 250, 255]:
        raise M0Error("M4 select popup scan color is not exact opaque magenta")
    pixel_count = _require_safe_integer(
        popup_option_scan.get("pixelCount"),
        "M4 select popup scan pixel count",
        minimum=4096,
    )
    scan: dict[str, int] = {"pixelCount": pixel_count}
    for field, maximum in (
        ("minX", M3_WIDTH - 1),
        ("maxX", M3_WIDTH - 1),
        ("minY", M3_HEIGHT - 1),
        ("maxY", M3_HEIGHT - 1),
        ("targetX", M3_WIDTH - 1),
        ("targetY", M3_HEIGHT - 1),
    ):
        scan[field] = _require_safe_integer(
            popup_option_scan.get(field),
            f"M4 select popup scan {field}",
            minimum=0,
            maximum=maximum,
        )
    if (
        scan["maxX"] < scan["minX"]
        or scan["maxY"] < scan["minY"]
        or scan["minY"] <= bounds["bottom"]
        or scan["maxX"] - scan["minX"] + 1
        < bounds["right"] - bounds["left"] - 8
        or scan["maxY"] - scan["minY"] + 1 < 36
    ):
        raise M0Error("M4 select popup scan bounds are not a visible popup")
    if (
        scan["targetX"] != (scan["minX"] + scan["maxX"]) // 2
        or scan["targetY"] != (scan["minY"] + scan["maxY"]) // 2
    ):
        raise M0Error("M4 select popup click target was not scan-derived")

    pointer_input = _require_dict(
        result.get("pointerInput"), "M4 select pointer input"
    )
    readiness_pointer = _require_dict(
        readiness.get("pointerInput"), "M4 select readiness pointer input"
    )
    if not _exact_json_value_equal(pointer_input, readiness_pointer):
        raise M0Error("M4 select pointer evidence differs from readiness")
    if pointer_input.get("enabled") is not True:
        raise M0Error("M4 select pointer listeners were not enabled")
    received_count = _require_safe_integer(
        pointer_input.get("receivedCount"),
        "M4 select received pointer count",
        minimum=6,
    )
    trusted_count = _require_safe_integer(
        pointer_input.get("trustedCount"),
        "M4 select trusted pointer count",
        minimum=6,
    )
    if trusted_count > received_count:
        raise M0Error("M4 select trusted pointer count exceeds received count")
    if _require_safe_integer(
        pointer_input.get("queuedCount"),
        "M4 select queued pointer count",
        minimum=6,
    ) != 6:
        raise M0Error("M4 select pointer queue does not have two exact clicks")
    queued_records = pointer_input.get("queuedRecords")
    if not isinstance(queued_records, list) or len(queued_records) != 6:
        raise M0Error("M4 select queued pointer trace is not six records")
    expected_pointer_trace = (
        ("move", target_x, target_y, -1, 0),
        ("down", target_x, target_y, 0, 1),
        ("up", target_x, target_y, 0, 0),
        ("move", scan["targetX"], scan["targetY"], -1, 0),
        ("down", scan["targetX"], scan["targetY"], 0, 1),
        ("up", scan["targetX"], scan["targetY"], 0, 0),
    )
    for index, (event_type, x, y, button, buttons) in enumerate(
        expected_pointer_trace
    ):
        record = _require_dict(
            queued_records[index], f"M4 select pointer trace {index}"
        )
        for field, expected_value in {
            "type": event_type,
            "x": x,
            "y": y,
            "button": button,
            "buttons": buttons,
            "trusted": True,
            "queued": True,
            "canvasFocused": True,
            "sequence": index + 1,
        }.items():
            if record.get(field) != expected_value:
                raise M0Error(
                    f"M4 select pointer trace {index} {field} mismatch"
                )
        _require_safe_integer(
            record.get("frameIdBefore"),
            f"M4 select pointer trace {index} frame ID",
            minimum=1,
        )
    last_queued = _require_dict(
        pointer_input.get("lastQueued"), "M4 select last queued pointer"
    )
    if not _exact_json_value_equal(last_queued, queued_records[-1]):
        raise M0Error("M4 select last queued pointer differs from trace")
    popup_open_pointer = _require_dict(
        result.get("popupOpenPointer"), "M4 select popup-open pointer"
    )
    if not _exact_json_value_equal(popup_open_pointer, queued_records[2]):
        raise M0Error("M4 select popup-open pointer is not the opener release")
    option_pointer = _require_dict(
        result.get("optionPointer"), "M4 select option pointer"
    )
    if not _exact_json_value_equal(option_pointer, queued_records[-1]):
        raise M0Error("M4 select option pointer is not the option release")
    if frame_id <= _require_safe_integer(
        option_pointer.get("frameIdBefore"),
        "M4 select option pointer frame ID",
        minimum=1,
    ):
        raise M0Error("M4 select has no compositor frame after option input")

    shutdown = _require_dict(result.get("shutdown"), "M4 select shutdown")
    for field in ("ok", "accepted", "complete"):
        if shutdown.get(field) is not True:
            raise M0Error(f"M4 select shutdown field {field} is not true")
    for field in ("exitCode", "runtimeExitCode"):
        if _require_safe_integer(
            shutdown.get(field), f"M4 select shutdown {field}"
        ) != 0:
            raise M0Error(f"M4 select shutdown {field} is not zero")

    logs = _require_dict(result.get("logs"), "M4 select logs")
    for stream in ("host", "stdout", "stderr"):
        if not isinstance(logs.get(stream), list):
            raise M0Error(f"M4 select {stream} log must be an array")
    combined_logs = "\n".join(
        str(line)
        for stream in ("host", "stdout", "stderr")
        for line in logs[stream]
    )
    if "abort:" in combined_logs.lower():
        raise M0Error("M4 select logs contain a Wasm abort")
    host_logs = [str(line) for line in logs["host"]]
    pointer_logs = [
        line for line in host_logs if line.startswith("m4:pointer:")
    ]
    expected_pointer_logs = ["m4:pointer:listeners-attached"] + [
        f"m4:pointer:{event_type}:queued"
        for event_type in ("move", "down", "up", "move", "down", "up")
    ]
    if pointer_logs != expected_pointer_logs:
        raise M0Error("M4 select pointer lifecycle logs are not exact")
    if not any("shutdown:complete" in line for line in host_logs):
        raise M0Error("M4 select logs are missing clean shutdown")


def validate_m4_resize_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
) -> None:
    """Validate the native 1x display, viewport, and CSS resize sequence."""

    expected = {
        "protocol": M3_PROTOCOL,
        "case": M4_RESIZE_CASE,
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
                f"M4 resize result {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )

    versions = _require_dict(result.get("versions"), "M4 resize versions")
    if versions != expected_versions:
        raise M0Error(
            "M4 resize version display mismatch: expected "
            f"{expected_versions!r}, got {versions!r}"
        )

    def require_geometry(
        value: object,
        description: str,
        *,
        width: int,
        height: int,
        layout_mode: str,
    ) -> dict[str, Any]:
        geometry = _require_dict(value, description)
        expected_geometry = {
            "innerWidth": width,
            "innerHeight": height,
            "documentClientWidth": width,
            "documentClientHeight": height,
            "screenWidth": width,
            "screenHeight": height,
            "screenAvailWidth": width,
            "screenAvailHeight": height,
            "narrowMedia": layout_mode == "narrow",
            "layoutMode": layout_mode,
            "gridColumns": 1 if layout_mode == "narrow" else 2,
            "gridWidth": width - 64,
        }
        for field, expected_value in expected_geometry.items():
            actual_value = geometry.get(field)
            if (
                type(actual_value) is not type(expected_value)
                or actual_value != expected_value
            ):
                raise M0Error(
                    f"{description} {field} mismatch: expected "
                    f"{expected_value!r}, got {actual_value!r}"
                )
        if _require_number(
            geometry.get("devicePixelRatio"),
            f"{description} device pixel ratio",
        ) != 1:
            raise M0Error(f"{description} device pixel ratio is not 1")

        first = _require_dict(geometry.get("firstCard"), f"{description} first card")
        second = _require_dict(
            geometry.get("secondCard"), f"{description} second card"
        )

        def require_card(
            card: dict[str, Any], card_description: str
        ) -> dict[str, int]:
            parsed: dict[str, int] = {}
            for field, maximum in (
                ("left", width - 1),
                ("top", height - 1),
                ("width", width),
                ("height", height),
            ):
                parsed[field] = _require_safe_integer(
                    card.get(field), f"{card_description} {field}", minimum=0,
                    maximum=maximum,
                )
            if parsed["width"] <= 0 or parsed["height"] <= 0:
                raise M0Error(f"{card_description} has empty bounds")
            if (
                parsed["left"] + parsed["width"] > width
                or parsed["top"] + parsed["height"] > height
            ):
                raise M0Error(f"{card_description} exceeds the viewport")
            return parsed

        first_rect = require_card(first, f"{description} first card")
        second_rect = require_card(second, f"{description} second card")
        if (
            first_rect["left"] != 32
            or first_rect["height"] != 120
            or second_rect["height"] != 120
        ):
            raise M0Error(f"{description} card CSS geometry is invalid")
        if layout_mode == "wide":
            if (
                first_rect["top"] != second_rect["top"]
                or first_rect["width"] != second_rect["width"]
                or first_rect["width"] * 2 + 16 != width - 64
                or second_rect["left"]
                != first_rect["left"] + first_rect["width"] + 16
            ):
                raise M0Error(
                    f"{description} did not retain the two-column CSS layout"
                )
        elif layout_mode == "narrow":
            if (
                second_rect["left"] != first_rect["left"]
                or first_rect["width"] != width - 64
                or second_rect["width"] != width - 64
                or second_rect["top"]
                != first_rect["top"] + first_rect["height"] + 16
            ):
                raise M0Error(
                    f"{description} did not reflow to the one-column CSS layout"
                )
        else:
            raise M0Error(f"{description} has unknown layout mode")
        return geometry

    def require_frame(
        value: object,
        description: str,
        *,
        width: int,
        height: int,
    ) -> dict[str, Any]:
        frame = _require_dict(value, description)
        _require_safe_integer(frame.get("id"), f"{description} ID", minimum=1)
        _require_number(
            frame.get("timestampMs"), f"{description} timestamp", minimum=0
        )
        for field, expected_value in {"width": width, "height": height}.items():
            actual_value = frame.get(field)
            if (
                type(actual_value) is not type(expected_value)
                or actual_value != expected_value
            ):
                raise M0Error(
                    f"{description} {field} does not match the native surface"
                )
        return frame

    def require_resize_call(
        value: object, description: str, *, width: int, height: int
    ) -> dict[str, Any]:
        call = _require_dict(value, description)
        expected_call = {
            "ok": True,
            "width": width,
            "height": height,
            "devicePixelRatio": 1,
        }
        for field, expected_value in expected_call.items():
            actual_value = call.get(field)
            if (
                type(actual_value) is not type(expected_value)
                or actual_value != expected_value
            ):
                raise M0Error(
                    f"{description} {field} mismatch: expected "
                    f"{expected_value!r}, got {actual_value!r}"
                )
        return call

    def require_resize_event(
        value: object,
        description: str,
        *,
        sequence: int,
        width: int,
        height: int,
        layout_mode: str,
    ) -> dict[str, Any]:
        event = _require_dict(value, description)
        if (
            event.get("sequence") != sequence
            or event.get("type") != "resize"
            or event.get("trusted") is not True
        ):
            raise M0Error(f"{description} is not a trusted native resize")
        require_geometry(
            event.get("geometry"), f"{description} geometry", width=width,
            height=height, layout_mode=layout_mode,
        )
        return event

    readiness = _require_dict(result.get("readiness"), "M4 resize readiness")
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
            raise M0Error(f"M4 resize readiness field {field} is not true")
    if readiness.get("fatalErrors") != []:
        raise M0Error("M4 resize readiness reported fatal errors")
    heartbeat = _require_dict(
        readiness.get("heartbeat"), "M4 resize heartbeat"
    )
    if heartbeat.get("anchor") != "data-navigation-committed":
        raise M0Error("M4 resize heartbeat was not anchored to navigation")
    _require_number(
        heartbeat.get("elapsedMs"), "M4 resize heartbeat elapsed time", minimum=0
    )

    page_probe = _require_dict(
        readiness.get("pageProbe"), "M4 resize page probe"
    )
    for field, expected_value in {
        "protocol": M3_PROTOCOL,
        "fixture": "chromium-wasm-m4-ozone-resize-v1",
        "fontReady": True,
        "resizeCaptureArmed": True,
        "ready": True,
    }.items():
        actual_value = page_probe.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 resize page probe {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )
    _require_safe_integer(
        page_probe.get("timerTicks"), "M4 resize inner page timer ticks", minimum=3
    )
    final_geometry = require_geometry(
        page_probe.get("currentGeometry"), "M4 resize final page geometry",
        width=M3_WIDTH, height=M3_HEIGHT, layout_mode="wide",
    )
    final_frame = require_frame(
        readiness.get("frame"), "M4 resize final frame", width=M3_WIDTH,
        height=M3_HEIGHT,
    )

    resize_calls = result.get("resizeCalls")
    if not isinstance(resize_calls, list) or len(resize_calls) != 3:
        raise M0Error("M4 resize calls are not the exact three-call sequence")
    initial_call = require_resize_call(
        resize_calls[0], "M4 resize initial call", width=M3_WIDTH,
        height=M3_HEIGHT,
    )
    narrow_call = require_resize_call(
        resize_calls[1], "M4 resize narrow call",
        width=M4_RESIZE_NARROW_WIDTH, height=M4_RESIZE_NARROW_HEIGHT,
    )
    restored_call = require_resize_call(
        resize_calls[2], "M4 resize restored call", width=M3_WIDTH,
        height=M3_HEIGHT,
    )

    resize_events = result.get("resizeEvents")
    page_resize_events = page_probe.get("resizeEvents")
    if (
        not isinstance(resize_events, list)
        or len(resize_events) != 2
        or not _exact_json_value_equal(resize_events, page_resize_events)
    ):
        raise M0Error("M4 resize events differ from the native page trace")
    narrow_event = require_resize_event(
        resize_events[0], "M4 resize narrow event", sequence=1,
        width=M4_RESIZE_NARROW_WIDTH, height=M4_RESIZE_NARROW_HEIGHT,
        layout_mode="narrow",
    )
    restored_event = require_resize_event(
        resize_events[1], "M4 resize restored event", sequence=2,
        width=M3_WIDTH, height=M3_HEIGHT, layout_mode="wide",
    )

    resize_proof = _require_dict(
        result.get("resizeProof"), "M4 resize proof"
    )
    initial_proof = _require_dict(
        resize_proof.get("initial"), "M4 resize initial proof"
    )
    narrow_proof = _require_dict(
        resize_proof.get("narrow"), "M4 resize narrow proof"
    )
    restored_proof = _require_dict(
        resize_proof.get("restored"), "M4 resize restored proof"
    )
    if not _exact_json_value_equal(initial_proof.get("resize"), initial_call):
        raise M0Error("M4 resize initial proof does not retain its host call")
    if not _exact_json_value_equal(narrow_proof.get("resize"), narrow_call):
        raise M0Error("M4 resize narrow proof does not retain its host call")
    if not _exact_json_value_equal(restored_proof.get("resize"), restored_call):
        raise M0Error("M4 resize restored proof does not retain its host call")

    initial_frame = require_frame(
        initial_proof.get("frame"), "M4 resize initial proof frame",
        width=M3_WIDTH, height=M3_HEIGHT,
    )
    narrow_frame = require_frame(
        narrow_proof.get("frame"), "M4 resize narrow proof frame",
        width=M4_RESIZE_NARROW_WIDTH, height=M4_RESIZE_NARROW_HEIGHT,
    )
    restored_frame = require_frame(
        restored_proof.get("frame"), "M4 resize restored proof frame",
        width=M3_WIDTH, height=M3_HEIGHT,
    )
    if not (
        initial_frame["id"] < narrow_frame["id"] < restored_frame["id"]
    ):
        raise M0Error("M4 resize compositor frame IDs did not increase")
    if not _exact_json_value_equal(final_frame, restored_frame):
        raise M0Error("M4 resize final frame differs from the restored proof")

    initial_geometry = require_geometry(
        initial_proof.get("geometry"), "M4 resize initial proof geometry",
        width=M3_WIDTH, height=M3_HEIGHT, layout_mode="wide",
    )
    narrow_geometry = require_geometry(
        narrow_proof.get("geometry"), "M4 resize narrow proof geometry",
        width=M4_RESIZE_NARROW_WIDTH, height=M4_RESIZE_NARROW_HEIGHT,
        layout_mode="narrow",
    )
    restored_geometry = require_geometry(
        restored_proof.get("geometry"), "M4 resize restored proof geometry",
        width=M3_WIDTH, height=M3_HEIGHT, layout_mode="wide",
    )
    if not _exact_json_value_equal(final_geometry, restored_geometry):
        raise M0Error(
            "M4 resize final page geometry differs from the restored proof"
        )
    if not _exact_json_value_equal(narrow_proof.get("event"), narrow_event):
        raise M0Error("M4 resize narrow proof differs from its native event")
    if not _exact_json_value_equal(
        restored_proof.get("event"), restored_event
    ):
        raise M0Error("M4 resize restored proof differs from its native event")
    if not _exact_json_value_equal(
        narrow_event.get("geometry"), narrow_geometry
    ):
        raise M0Error("M4 resize narrow event geometry is not retained")
    if not _exact_json_value_equal(
        restored_event.get("geometry"), restored_geometry
    ):
        raise M0Error("M4 resize restored event geometry is not retained")
    if not _exact_json_value_equal(initial_geometry, initial_proof.get("geometry")):
        raise M0Error("M4 resize initial geometry proof is inconsistent")

    shutdown = _require_dict(result.get("shutdown"), "M4 resize shutdown")
    for field in ("ok", "accepted", "complete"):
        if shutdown.get(field) is not True:
            raise M0Error(f"M4 resize shutdown field {field} is not true")
    for field in ("exitCode", "runtimeExitCode"):
        if _require_safe_integer(
            shutdown.get(field), f"M4 resize shutdown {field}"
        ) != 0:
            raise M0Error(f"M4 resize shutdown {field} is not zero")

    logs = _require_dict(result.get("logs"), "M4 resize logs")
    for stream in ("host", "stdout", "stderr"):
        if not isinstance(logs.get(stream), list):
            raise M0Error(f"M4 resize {stream} log must be an array")
    combined_logs = "\n".join(
        str(line)
        for stream in ("host", "stdout", "stderr")
        for line in logs[stream]
    )
    if "abort:" in combined_logs.lower():
        raise M0Error("M4 resize logs contain a Wasm abort")
    host_logs = [str(line) for line in logs["host"]]
    resize_logs = [line for line in host_logs if line.startswith("resize:")]
    expected_resize_logs = [
        f"resize:{M3_WIDTH}x{M3_HEIGHT}@1",
        f"resize:{M4_RESIZE_NARROW_WIDTH}x{M4_RESIZE_NARROW_HEIGHT}@1",
        f"resize:{M3_WIDTH}x{M3_HEIGHT}@1",
    ]
    if resize_logs != expected_resize_logs:
        raise M0Error("M4 resize host resize lifecycle is not exact")
    if not any("shutdown:complete" in line for line in host_logs):
        raise M0Error("M4 resize logs are missing clean shutdown")


def validate_m4_dpr_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
) -> None:
    """Validate bounded 1x/2x display scale and CSS pointer agreement."""

    expected = {
        "protocol": M3_PROTOCOL,
        "case": M4_DPR_CASE,
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
                f"M4 DPR result {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )

    versions = _require_dict(result.get("versions"), "M4 DPR versions")
    if versions != expected_versions:
        raise M0Error(
            "M4 DPR version display mismatch: expected "
            f"{expected_versions!r}, got {versions!r}"
        )

    def require_resize_call(
        value: object, description: str, *, device_scale_factor: int
    ) -> dict[str, Any]:
        call = _require_dict(value, description)
        expected_call = {
            "ok": True,
            "width": M3_WIDTH,
            "height": M3_HEIGHT,
            "devicePixelRatio": device_scale_factor,
            "physicalWidth": M3_WIDTH * device_scale_factor,
            "physicalHeight": M3_HEIGHT * device_scale_factor,
        }
        for field, expected_value in expected_call.items():
            actual_value = call.get(field)
            if (
                type(actual_value) is not type(expected_value)
                or actual_value != expected_value
            ):
                raise M0Error(
                    f"{description} {field} mismatch: expected "
                    f"{expected_value!r}, got {actual_value!r}"
                )
        return call

    def require_frame(
        value: object, description: str, *, device_scale_factor: int
    ) -> dict[str, Any]:
        frame = _require_dict(value, description)
        _require_safe_integer(frame.get("id"), f"{description} ID", minimum=1)
        _require_number(
            frame.get("timestampMs"), f"{description} timestamp", minimum=0
        )
        expected_size = {
            "width": M3_WIDTH * device_scale_factor,
            "height": M3_HEIGHT * device_scale_factor,
        }
        for field, expected_value in expected_size.items():
            if frame.get(field) != expected_value:
                raise M0Error(
                    f"{description} {field} does not match the physical "
                    "backing surface"
                )
        return frame

    def require_geometry(
        value: object, description: str, *, device_scale_factor: int
    ) -> dict[str, Any]:
        geometry = _require_dict(value, description)
        expected_geometry = {
            "innerWidth": M3_WIDTH,
            "innerHeight": M3_HEIGHT,
            "documentClientWidth": M3_WIDTH,
            "documentClientHeight": M3_HEIGHT,
            "screenWidth": M3_WIDTH,
            "screenHeight": M3_HEIGHT,
            "screenAvailWidth": M3_WIDTH,
            "screenAvailHeight": M3_HEIGHT,
            "twoDppx": device_scale_factor == M4_DPR_SCALE,
        }
        for field, expected_value in expected_geometry.items():
            actual_value = geometry.get(field)
            if (
                type(actual_value) is not type(expected_value)
                or actual_value != expected_value
            ):
                raise M0Error(
                    f"{description} {field} mismatch: expected "
                    f"{expected_value!r}, got {actual_value!r}"
                )
        if _require_number(
            geometry.get("devicePixelRatio"),
            f"{description} device pixel ratio",
        ) != device_scale_factor:
            raise M0Error(
                f"{description} device pixel ratio does not match the "
                "bounded display scale"
            )
        return geometry

    def require_canvas(
        value: object, description: str, *, device_scale_factor: int
    ) -> dict[str, Any]:
        canvas = _require_dict(value, description)
        expected_canvas = {
            "clientWidth": M3_WIDTH,
            "clientHeight": M3_HEIGHT,
            "width": M3_WIDTH * device_scale_factor,
            "height": M3_HEIGHT * device_scale_factor,
            "styleWidth": f"{M3_WIDTH}px",
            "styleHeight": f"{M3_HEIGHT}px",
        }
        for field, expected_value in expected_canvas.items():
            actual_value = canvas.get(field)
            if (
                type(actual_value) is not type(expected_value)
                or actual_value != expected_value
            ):
                raise M0Error(
                    f"{description} {field} mismatch: expected "
                    f"{expected_value!r}, got {actual_value!r}"
                )
        return canvas

    readiness = _require_dict(result.get("readiness"), "M4 DPR readiness")
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
            raise M0Error(f"M4 DPR readiness field {field} is not true")
    if readiness.get("fatalErrors") != []:
        raise M0Error("M4 DPR readiness reported fatal errors")
    heartbeat = _require_dict(readiness.get("heartbeat"), "M4 DPR heartbeat")
    if heartbeat.get("anchor") != "data-navigation-committed":
        raise M0Error("M4 DPR heartbeat was not anchored to navigation")
    _require_number(
        heartbeat.get("elapsedMs"), "M4 DPR heartbeat elapsed time", minimum=0
    )

    final_page_probe = _require_dict(
        readiness.get("pageProbe"), "M4 DPR final page probe"
    )
    for field, expected_value in {
        "protocol": M3_PROTOCOL,
        "fixture": "chromium-wasm-m4-ozone-pointer-v2",
        "fontReady": True,
        "ready": True,
        "activationCount": 1,
        "clickTrusted": True,
        "clickDefaultPrevented": False,
        "resultText": "ACTIVATED",
    }.items():
        actual_value = final_page_probe.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 DPR final page probe {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )
    _require_m4_native_link_navigation(
        final_page_probe, "M4 DPR final page probe"
    )
    _require_safe_integer(
        final_page_probe.get("timerTicks"), "M4 DPR page timer ticks", minimum=3
    )
    final_geometry = require_geometry(
        final_page_probe.get("displayGeometry"), "M4 DPR final geometry",
        device_scale_factor=1,
    )
    final_frame = require_frame(
        readiness.get("frame"), "M4 DPR final frame", device_scale_factor=1
    )

    resize_calls = result.get("resizeCalls")
    if not isinstance(resize_calls, list) or len(resize_calls) != 3:
        raise M0Error("M4 DPR calls are not the exact three-call sequence")
    initial_call = require_resize_call(
        resize_calls[0], "M4 DPR initial call", device_scale_factor=1
    )
    scaled_call = require_resize_call(
        resize_calls[1], "M4 DPR scaled call",
        device_scale_factor=M4_DPR_SCALE,
    )
    restored_call = require_resize_call(
        resize_calls[2], "M4 DPR restored call", device_scale_factor=1
    )

    proof = _require_dict(result.get("dprProof"), "M4 DPR proof")
    initial_proof = _require_dict(proof.get("initial"), "M4 DPR initial proof")
    scaled_proof = _require_dict(proof.get("scaled"), "M4 DPR scaled proof")
    input_proof = _require_dict(proof.get("input"), "M4 DPR input proof")
    restored_proof = _require_dict(
        proof.get("restored"), "M4 DPR restored proof"
    )
    if not _exact_json_value_equal(initial_proof.get("resize"), initial_call):
        raise M0Error("M4 DPR initial proof does not retain its host call")
    if not _exact_json_value_equal(scaled_proof.get("resize"), scaled_call):
        raise M0Error("M4 DPR scaled proof does not retain its host call")
    if not _exact_json_value_equal(restored_proof.get("resize"), restored_call):
        raise M0Error("M4 DPR restored proof does not retain its host call")

    initial_frame = require_frame(
        initial_proof.get("frame"), "M4 DPR initial proof frame",
        device_scale_factor=1,
    )
    scaled_frame = require_frame(
        scaled_proof.get("frame"), "M4 DPR scaled proof frame",
        device_scale_factor=M4_DPR_SCALE,
    )
    input_frame = require_frame(
        input_proof.get("frame"), "M4 DPR input proof frame",
        device_scale_factor=M4_DPR_SCALE,
    )
    restored_frame = require_frame(
        restored_proof.get("frame"), "M4 DPR restored proof frame",
        device_scale_factor=1,
    )
    if not (
        initial_frame["id"] < scaled_frame["id"] < input_frame["id"]
        < restored_frame["id"]
    ):
        raise M0Error("M4 DPR compositor frame IDs did not increase")
    if not _exact_json_value_equal(final_frame, restored_frame):
        raise M0Error("M4 DPR final frame differs from the restored proof")

    initial_geometry = require_geometry(
        initial_proof.get("geometry"), "M4 DPR initial proof geometry",
        device_scale_factor=1,
    )
    scaled_geometry = require_geometry(
        scaled_proof.get("geometry"), "M4 DPR scaled proof geometry",
        device_scale_factor=M4_DPR_SCALE,
    )
    restored_geometry = require_geometry(
        restored_proof.get("geometry"), "M4 DPR restored proof geometry",
        device_scale_factor=1,
    )
    if not _exact_json_value_equal(final_geometry, restored_geometry):
        raise M0Error("M4 DPR final geometry differs from the restored proof")
    require_canvas(
        initial_proof.get("canvas"), "M4 DPR initial canvas",
        device_scale_factor=1,
    )
    require_canvas(
        scaled_proof.get("canvas"), "M4 DPR scaled canvas",
        device_scale_factor=M4_DPR_SCALE,
    )
    require_canvas(
        restored_proof.get("canvas"), "M4 DPR restored canvas",
        device_scale_factor=1,
    )

    target_css_x = _require_safe_integer(
        scaled_proof.get("targetCssX"), "M4 DPR target CSS x", minimum=0,
        maximum=M3_WIDTH - 1,
    )
    target_css_y = _require_safe_integer(
        scaled_proof.get("targetCssY"), "M4 DPR target CSS y", minimum=0,
        maximum=M3_HEIGHT - 1,
    )
    target_backing_x = _require_safe_integer(
        scaled_proof.get("targetBackingX"), "M4 DPR target backing x",
        minimum=0, maximum=M3_WIDTH * M4_DPR_SCALE - 1,
    )
    target_backing_y = _require_safe_integer(
        scaled_proof.get("targetBackingY"), "M4 DPR target backing y",
        minimum=0, maximum=M3_HEIGHT * M4_DPR_SCALE - 1,
    )
    if (
        target_backing_x != target_css_x * M4_DPR_SCALE
        or target_backing_y != target_css_y * M4_DPR_SCALE
    ):
        raise M0Error("M4 DPR target backing coordinates are not 2x CSS")
    for field, expected_value in {
        "targetCenterX": target_css_x,
        "targetCenterY": target_css_y,
    }.items():
        if final_page_probe.get(field) != expected_value:
            raise M0Error(
                f"M4 DPR final page probe {field} differs from the "
                "scaled CSS target"
            )

    input_page_probe = _require_dict(
        input_proof.get("pageProbe"), "M4 DPR input page probe"
    )
    for field, expected_value in {
        "activationCount": 1,
        "clickTrusted": True,
        "clickDefaultPrevented": False,
        "resultText": "ACTIVATED",
    }.items():
        actual_value = input_page_probe.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 DPR input page probe {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )
    _require_m4_native_link_navigation(
        input_page_probe, "M4 DPR input page probe"
    )
    require_geometry(
        input_page_probe.get("displayGeometry"), "M4 DPR input geometry",
        device_scale_factor=M4_DPR_SCALE,
    )
    trace = input_page_probe.get("pointerMoveTrace")
    if not isinstance(trace, list) or not any(
        record.get("type") == "pointermove"
        and record.get("trusted") is True
        and record.get("targetId") == "m4-link"
        and record.get("clientX") == target_css_x
        and record.get("clientY") == target_css_y
        for record in trace
        if isinstance(record, dict)
    ):
        raise M0Error("M4 DPR pointer did not arrive at the Blink CSS target")

    pointer = _require_dict(input_proof.get("pointer"), "M4 DPR pointer")
    if (
        pointer.get("enabled") is not True
        or _require_safe_integer(
            pointer.get("trustedCount"), "M4 DPR trusted pointer count", minimum=2
        ) < 2
        or _require_safe_integer(
            pointer.get("queuedCount"), "M4 DPR queued pointer count", minimum=2
        ) < 2
    ):
        raise M0Error("M4 DPR did not accept the trusted host pointer stream")
    last_queued = _require_dict(
        pointer.get("lastQueued"), "M4 DPR last queued pointer"
    )
    if (
        last_queued.get("type") != "up"
        or last_queued.get("trusted") is not True
        or last_queued.get("queued") is not True
        or last_queued.get("x") != target_backing_x
        or last_queued.get("y") != target_backing_y
    ):
        raise M0Error(
            "M4 DPR host pointer was not recorded in physical backing pixels"
        )
    posted_frame = _require_safe_integer(
        last_queued.get("frameIdBefore"), "M4 DPR pointer posted frame", minimum=1
    )
    if input_frame["id"] <= posted_frame:
        raise M0Error("M4 DPR trusted pointer produced no later compositor frame")
    if not _exact_json_value_equal(result.get("pointerInput"), pointer):
        raise M0Error("M4 DPR result pointer input differs from input proof")

    shutdown = _require_dict(result.get("shutdown"), "M4 DPR shutdown")
    for field in ("ok", "accepted", "complete"):
        if shutdown.get(field) is not True:
            raise M0Error(f"M4 DPR shutdown field {field} is not true")
    for field in ("exitCode", "runtimeExitCode"):
        if _require_safe_integer(
            shutdown.get(field), f"M4 DPR shutdown {field}"
        ) != 0:
            raise M0Error(f"M4 DPR shutdown {field} is not zero")

    logs = _require_dict(result.get("logs"), "M4 DPR logs")
    for stream in ("host", "stdout", "stderr"):
        if not isinstance(logs.get(stream), list):
            raise M0Error(f"M4 DPR {stream} log must be an array")
    combined_logs = "\n".join(
        str(line)
        for stream in ("host", "stdout", "stderr")
        for line in logs[stream]
    )
    if "abort:" in combined_logs.lower():
        raise M0Error("M4 DPR logs contain a Wasm abort")
    host_logs = [str(line) for line in logs["host"]]
    resize_logs = [line for line in host_logs if line.startswith("resize:")]
    expected_resize_logs = [
        f"resize:{M3_WIDTH}x{M3_HEIGHT}@1",
        f"resize:{M3_WIDTH}x{M3_HEIGHT}@{M4_DPR_SCALE}",
        f"resize:{M3_WIDTH}x{M3_HEIGHT}@1",
    ]
    if resize_logs != expected_resize_logs:
        raise M0Error("M4 DPR host resize lifecycle is not exact")
    if not any("m4:pointer:listeners-attached" == line for line in host_logs):
        raise M0Error("M4 DPR logs are missing pointer listener setup")
    if not any("shutdown:complete" in line for line in host_logs):
        raise M0Error("M4 DPR logs are missing clean shutdown")


def validate_m4_context_menu_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
) -> None:
    """Validate a real Aura context menu and its Copy command.

    The menu is not an outer-page DOM control: it is a rendered child of the
    existing Wasm Aura root.  This validates its opaque Copy row from the
    captured compositor output, a physical secondary click, normal Blink Copy,
    and the existing bounded physical Ctrl+V path.
    """

    expected = {
        "protocol": M3_PROTOCOL,
        "case": M4_CONTEXT_MENU_CASE,
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
                f"M4 context-menu result {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )

    versions = _require_dict(
        result.get("versions"), "M4 context-menu versions"
    )
    if versions != expected_versions:
        raise M0Error(
            "M4 context-menu version display mismatch: expected "
            f"{expected_versions!r}, got {versions!r}"
        )

    proof_fields = {
        "activationProof": (
            "outerTraceExact",
            "sourceFocused",
            "selectionCollapsed",
            "frameAfterActivation",
        ),
        "selectionProof": (
            "outerTraceExact",
            "nativeSelection",
            "frameAfterDrag",
        ),
        "menuOpenProof": (
            "outerTraceExact",
            "innerSecondary",
            "outerContextMenuSuppressed",
            "frameAfterSecondary",
        ),
        "menuCopyProof": (
            "outerTraceExact",
            "nativeCopy",
            "menuDismissed",
            "frameAfterCopy",
        ),
        "pasteActivationProof": (
            "outerTraceExact",
            "pasteFocused",
            "frameAfterActivation",
        ),
        "pasteProof": (
            "outerPointerTraceExact",
            "outerKeyTraceExact",
            "innerKeys",
            "nativePaste",
            "frameAfterPaste",
        ),
    }
    proofs: dict[str, dict[str, Any]] = {}
    for proof_name, fields in proof_fields.items():
        proof = _require_dict(
            result.get(proof_name), f"M4 context-menu {proof_name}"
        )
        proofs[proof_name] = proof
        for field in fields:
            if proof.get(field) is not True:
                raise M0Error(
                    f"M4 context-menu {proof_name} {field} is not true"
                )

    copy_row = _require_dict(
        proofs["menuOpenProof"].get("copyRow"),
        "M4 context-menu Copy-row scan",
    )
    if copy_row.get("rgba") != [0, 87, 184, 255]:
        raise M0Error("M4 context-menu Copy-row color is not opaque #0057b8")
    pixel_count = _require_safe_integer(
        copy_row.get("pixelCount"),
        "M4 context-menu Copy-row pixel count",
        minimum=5000,
    )
    copy_bounds: dict[str, int] = {}
    for field in ("minX", "minY", "maxX", "maxY", "targetX", "targetY"):
        maximum = M3_WIDTH - 1 if field.endswith("X") else M3_HEIGHT - 1
        copy_bounds[field] = _require_safe_integer(
            copy_row.get(field),
            f"M4 context-menu Copy-row {field}",
            minimum=0,
            maximum=maximum,
        )
    if (
        copy_bounds["maxX"] - copy_bounds["minX"] + 1 != 160
        or copy_bounds["maxY"] - copy_bounds["minY"] + 1 != 40
        or copy_bounds["targetX"]
        != (copy_bounds["minX"] + copy_bounds["maxX"]) // 2
        or copy_bounds["targetY"]
        != (copy_bounds["minY"] + copy_bounds["maxY"]) // 2
        or pixel_count > 160 * 40
    ):
        raise M0Error("M4 context-menu Copy-row scan geometry is invalid")

    readiness = _require_dict(
        result.get("readiness"), "M4 context-menu readiness"
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
                f"M4 context-menu readiness field {field} is not true"
            )
    if readiness.get("fatalErrors") != []:
        raise M0Error("M4 context-menu readiness reported fatal errors")
    heartbeat = _require_dict(
        readiness.get("heartbeat"), "M4 context-menu heartbeat"
    )
    if heartbeat.get("anchor") != "data-navigation-committed":
        raise M0Error(
            "M4 context-menu heartbeat was not anchored to navigation"
        )
    _require_number(
        heartbeat.get("elapsedMs"),
        "M4 context-menu heartbeat elapsed time",
        minimum=0,
    )

    frame = _require_dict(readiness.get("frame"), "M4 context-menu frame")
    frame_id = _require_safe_integer(
        frame.get("id"), "M4 context-menu frame ID", minimum=1
    )
    _require_number(
        frame.get("timestampMs"), "M4 context-menu frame timestamp", minimum=0
    )
    if frame.get("width") != M3_WIDTH or frame.get("height") != M3_HEIGHT:
        raise M0Error(
            "M4 context-menu frame dimensions do not match the canvas"
        )

    page_probe = _require_dict(
        readiness.get("pageProbe"), "M4 context-menu page probe"
    )
    expected_probe = {
        "protocol": M3_PROTOCOL,
        "fixture": "chromium-wasm-m4-ozone-context-menu-v1",
        "fontReady": True,
        "ready": True,
        "activeElementId": "context-paste",
        "sourceValue": "MENU",
        "pasteValue": "MENU",
        "pasteSelectionStart": 4,
        "pasteSelectionEnd": 4,
        "resultText": "NATIVE MENU COPY PASTED",
        "contextCopied": True,
    }
    for field, expected_value in expected_probe.items():
        actual_value = page_probe.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 context-menu page probe {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )
    for field in ("sourceFocusCount", "pasteFocusCount", "timerTicks"):
        _require_safe_integer(
            page_probe.get(field),
            f"M4 context-menu {field}",
            minimum=3 if field == "timerTicks" else 1,
        )

    coordinates: dict[str, int] = {}
    for field in (
        "sourceTargetX",
        "sourceTargetY",
        "dragStartX",
        "dragStartY",
        "dragMiddleX",
        "dragMiddleY",
        "dragEndX",
        "dragEndY",
        "pasteTargetX",
        "pasteTargetY",
    ):
        maximum = M3_WIDTH - 1 if field.endswith("X") else M3_HEIGHT - 1
        coordinates[field] = _require_safe_integer(
            page_probe.get(field),
            f"M4 context-menu {field}",
            minimum=0,
            maximum=maximum,
        )
    if not (
        coordinates["dragStartX"]
        < coordinates["dragMiddleX"]
        < coordinates["dragEndX"]
        and coordinates["dragStartY"]
        == coordinates["dragMiddleY"]
        == coordinates["dragEndY"]
    ):
        raise M0Error("M4 context-menu drag geometry is not strictly forward")

    selection = _require_dict(
        page_probe.get("sourceSelection"), "M4 context-menu source selection"
    )
    if (
        selection.get("start") != 0
        or selection.get("end") != 4
        or selection.get("text") != "MENU"
        or selection.get("direction") not in ("none", "forward")
    ):
        raise M0Error("M4 context-menu source selection is not MENU")
    selection_activity = _require_dict(
        page_probe.get("selectionActivity"),
        "M4 context-menu selection activity",
    )
    for field in ("trusted", "nonCollapsed", "trustedNonCollapsed"):
        if selection_activity.get(field) is not True:
            raise M0Error(
                f"M4 context-menu selection activity {field} is not true"
            )
    for field in ("count", "selectCount", "selectionChangeCount"):
        _require_safe_integer(
            selection_activity.get(field),
            f"M4 context-menu selection activity {field}",
            minimum=1,
        )

    def require_secondary_source_events(field: str, prefix: str) -> None:
        events = page_probe.get(field)
        if not isinstance(events, list):
            raise M0Error(f"M4 context-menu {field} is not an array")
        for event_type, buttons in (("down", 2), ("up", 0)):
            if not any(
                isinstance(event, dict)
                and event.get("type") == prefix + event_type
                and event.get("trusted") is True
                and event.get("button") == 2
                and event.get("buttons") == buttons
                and event.get("clientX") == coordinates["sourceTargetX"]
                and event.get("clientY") == coordinates["sourceTargetY"]
                and event.get("targetId") == "context-source"
                and event.get("defaultPrevented") is False
                for event in events
            ):
                raise M0Error(
                    f"M4 context-menu {field} has no trusted secondary "
                    f"{event_type} event"
                )

    require_secondary_source_events("sourcePointerTrace", "pointer")
    require_secondary_source_events("sourceMouseTrace", "mouse")
    context_events = page_probe.get("contextMenuTrace")
    if not isinstance(context_events, list) or len(context_events) != 1:
        raise M0Error("M4 context-menu inner trace is not exactly one event")
    context_event = _require_dict(
        context_events[0], "M4 context-menu inner contextmenu event"
    )
    for field, expected_value in {
        "type": "contextmenu",
        "trusted": True,
        "button": 2,
        "buttons": 2,
        "clientX": coordinates["sourceTargetX"],
        "clientY": coordinates["sourceTargetY"],
        "targetId": "context-source",
        "defaultPrevented": False,
    }.items():
        if context_event.get(field) != expected_value:
            raise M0Error(f"M4 context-menu inner event {field} mismatch")
    context_selection = _require_dict(
        context_event.get("selection"), "M4 context-menu inner selection"
    )
    if (
        context_selection.get("start") != 0
        or context_selection.get("end") != 4
        or context_selection.get("text") != "MENU"
    ):
        raise M0Error("M4 context-menu inner event lost MENU selection")

    copy_events = page_probe.get("copyEventTrace")
    if not isinstance(copy_events, list) or len(copy_events) != 1:
        raise M0Error("M4 context-menu copy trace is not exactly one event")
    copy_event = _require_dict(copy_events[0], "M4 context-menu copy event")
    for field, expected_value in {
        "type": "copy",
        "trusted": True,
        "targetId": "context-source",
        "defaultPrevented": False,
    }.items():
        if copy_event.get(field) != expected_value:
            raise M0Error(f"M4 context-menu copy event {field} mismatch")
    copy_selection = _require_dict(
        copy_event.get("selection"), "M4 context-menu Copy selection"
    )
    if (
        copy_selection.get("start") != 0
        or copy_selection.get("end") != 4
        or copy_selection.get("text") != "MENU"
    ):
        raise M0Error("M4 context-menu Copy did not target MENU")

    paste_events = page_probe.get("pasteEventTrace")
    if not isinstance(paste_events, list) or len(paste_events) != 1:
        raise M0Error("M4 context-menu paste trace is not exactly one event")
    paste_event = _require_dict(paste_events[0], "M4 context-menu paste event")
    for field, expected_value in {
        "type": "paste",
        "trusted": True,
        "targetId": "context-paste",
        "defaultPrevented": False,
        "text": "MENU",
    }.items():
        if paste_event.get(field) != expected_value:
            raise M0Error(f"M4 context-menu paste event {field} mismatch")
    paste_text = page_probe.get("pasteTextInputTrace")
    if not isinstance(paste_text, list) or len(paste_text) != 2:
        raise M0Error("M4 context-menu paste text trace has wrong length")
    for index, event_type in enumerate(("beforeinput", "input")):
        text_event = _require_dict(
            paste_text[index], f"M4 context-menu paste text event {index}"
        )
        for field, expected_value in {
            "type": event_type,
            "trusted": True,
            "inputType": "insertFromPaste",
            "data": "MENU",
            "isComposing": False,
            "targetId": "context-paste",
        }.items():
            if text_event.get(field) != expected_value:
                raise M0Error(
                    f"M4 context-menu paste text {index} {field} mismatch"
                )

    def click_trace(
        x: int, y: int
    ) -> tuple[tuple[str, int, int, int, int], ...]:
        return (
            ("move", x, y, -1, 0),
            ("down", x, y, 0, 1),
            ("up", x, y, 0, 0),
        )

    drag_trace = (
        ("move", coordinates["dragStartX"], coordinates["dragStartY"], -1, 0),
        ("down", coordinates["dragStartX"], coordinates["dragStartY"], 0, 1),
        ("move", coordinates["dragMiddleX"], coordinates["dragMiddleY"], -1, 1),
        ("move", coordinates["dragEndX"], coordinates["dragEndY"], -1, 1),
        ("up", coordinates["dragEndX"], coordinates["dragEndY"], 0, 0),
    )
    secondary_trace = (
        ("move", coordinates["sourceTargetX"], coordinates["sourceTargetY"], -1, 0),
        ("down", coordinates["sourceTargetX"], coordinates["sourceTargetY"], 2, 2),
        ("up", coordinates["sourceTargetX"], coordinates["sourceTargetY"], 2, 0),
    )
    expected_pointer_trace = (
        *click_trace(
            coordinates["sourceTargetX"], coordinates["sourceTargetY"]
        ),
        *drag_trace,
        *secondary_trace,
        *click_trace(copy_bounds["targetX"], copy_bounds["targetY"]),
        *click_trace(
            coordinates["pasteTargetX"], coordinates["pasteTargetY"]
        ),
    )
    pointer_input = _require_dict(
        result.get("pointerInput"), "M4 context-menu pointer input"
    )
    readiness_pointer = _require_dict(
        readiness.get("pointerInput"), "M4 context-menu readiness pointer"
    )
    if not _exact_json_value_equal(pointer_input, readiness_pointer):
        raise M0Error(
            "M4 context-menu pointer evidence differs from readiness evidence"
        )
    if pointer_input.get("enabled") is not True:
        raise M0Error("M4 context-menu pointer listeners were not enabled")
    queued_pointer = pointer_input.get("queuedRecords")
    if not isinstance(queued_pointer, list) or len(queued_pointer) != len(
        expected_pointer_trace
    ):
        raise M0Error("M4 context-menu pointer trace has wrong length")
    for field in ("receivedCount", "trustedCount", "queuedCount"):
        if pointer_input.get(field) != len(expected_pointer_trace):
            raise M0Error(f"M4 context-menu pointer {field} mismatch")
    final_pointer_frame = 0
    for index, (event_type, x, y, button, buttons) in enumerate(
        expected_pointer_trace
    ):
        record = _require_dict(
            queued_pointer[index], f"M4 context-menu pointer trace {index}"
        )
        for field, expected_value in {
            "type": event_type,
            "trusted": True,
            "queued": True,
            "button": button,
            "buttons": buttons,
            "sequence": index + 1,
            "x": x,
            "y": y,
            "canvasFocused": True,
        }.items():
            if record.get(field) != expected_value:
                raise M0Error(
                    f"M4 context-menu pointer {index} {field} mismatch"
                )
        record_frame = _require_safe_integer(
            record.get("frameIdBefore"),
            f"M4 context-menu pointer {index} frame",
            minimum=1,
        )
        if index == len(expected_pointer_trace) - 1:
            final_pointer_frame = record_frame
    last_queued = _require_dict(
        pointer_input.get("lastQueued"), "M4 context-menu last queued pointer"
    )
    if not _exact_json_value_equal(last_queued, queued_pointer[-1]):
        raise M0Error("M4 context-menu last pointer is not the paste release")
    if frame_id <= final_pointer_frame:
        raise M0Error("M4 context-menu has no compositor frame after paste")

    outer_context = pointer_input.get("contextMenuRecords")
    if not isinstance(outer_context, list) or len(outer_context) != 1:
        raise M0Error("M4 context-menu outer context trace has wrong length")
    outer_record = _require_dict(
        outer_context[0], "M4 context-menu outer context record"
    )
    for field, expected_value in {
        "sequence": 1,
        "trusted": True,
        "button": 2,
        "buttons": 2,
        "x": coordinates["sourceTargetX"],
        "y": coordinates["sourceTargetY"],
        "acceptedPointer": True,
        "defaultPrevented": True,
    }.items():
        if outer_record.get(field) != expected_value:
            raise M0Error(
                f"M4 context-menu outer context record {field} mismatch"
            )

    expected_key_trace = (
        ("down", "ControlLeft", "Control", True),
        ("down", "KeyV", "v", True),
        ("up", "KeyV", "v", True),
        ("up", "ControlLeft", "Control", False),
    )
    # Blink exposes platform-specific modifier timing on Control's own DOM
    # key events. The V down/up records remain the strict proof of the
    # Ctrl+V chord; Control events need only preserve their trusted sequence.
    expected_inner_key_trace = (
        ("down", "ControlLeft", "Control", None),
        ("down", "KeyV", "v", True),
        ("up", "KeyV", "v", True),
        ("up", "ControlLeft", "Control", None),
    )
    keyboard_input = _require_dict(
        result.get("keyboardInput"), "M4 context-menu keyboard input"
    )
    readiness_keyboard = _require_dict(
        readiness.get("keyboardInput"),
        "M4 context-menu readiness keyboard",
    )
    if not _exact_json_value_equal(keyboard_input, readiness_keyboard):
        raise M0Error(
            "M4 context-menu keyboard evidence differs from readiness evidence"
        )
    if (
        keyboard_input.get("enabled") is not True
        or keyboard_input.get("activated") is not True
        or keyboard_input.get("pressedCodes") != []
        or keyboard_input.get("receivedCount") != len(expected_key_trace)
        or keyboard_input.get("trustedCount") != len(expected_key_trace)
        or keyboard_input.get("queuedCount") != len(expected_key_trace)
    ):
        raise M0Error("M4 context-menu keyboard state is invalid")
    queued_keys = keyboard_input.get("queuedRecords")
    if not isinstance(queued_keys, list) or len(queued_keys) != len(
        expected_key_trace
    ):
        raise M0Error("M4 context-menu key trace has wrong length")
    paste_key_down_frame = 0
    for index, (event_type, code, key, control) in enumerate(expected_key_trace):
        record = _require_dict(
            queued_keys[index], f"M4 context-menu key trace {index}"
        )
        for field, expected_value in {
            "type": event_type,
            "code": code,
            "key": key,
            "trusted": True,
            "queued": True,
            "repeat": False,
            "isComposing": False,
            "sequence": index + 1,
            "canvasFocused": True,
            "pointerActivated": True,
            "defaultPrevented": True,
        }.items():
            if record.get(field) != expected_value:
                raise M0Error(
                    f"M4 context-menu key {index} {field} mismatch"
                )
        if record.get("modifiers") != {
            "alt": False,
            "control": control,
            "meta": False,
            "shift": False,
        }:
            raise M0Error(f"M4 context-menu key {index} modifiers mismatch")
        record_frame = _require_safe_integer(
            record.get("frameIdBefore"),
            f"M4 context-menu key {index} frame",
            minimum=1,
        )
        if index == 1:
            paste_key_down_frame = record_frame
    if frame_id <= paste_key_down_frame:
        raise M0Error("M4 context-menu has no frame after Ctrl+V")

    inner_keys = page_probe.get("pasteKeyEventTrace")
    if not isinstance(inner_keys, list) or len(inner_keys) != len(
        expected_key_trace
    ):
        raise M0Error("M4 context-menu inner key trace has wrong length")
    for index, (event_type, code, key, control) in enumerate(
        expected_inner_key_trace
    ):
        record = _require_dict(
            inner_keys[index], f"M4 context-menu inner key {index}"
        )
        for field, expected_value in {
            "type": "keydown" if event_type == "down" else "keyup",
            "code": code,
            "key": key,
            "trusted": True,
            "repeat": False,
            "isComposing": False,
            "targetId": "context-paste",
            "defaultPrevented": False,
        }.items():
            if record.get(field) != expected_value:
                raise M0Error(
                    f"M4 context-menu inner key {index} {field} mismatch"
                )
        if control is not None and record.get("ctrlKey") != control:
            raise M0Error(
                f"M4 context-menu inner key {index} ctrlKey mismatch"
            )

    shutdown = _require_dict(
        result.get("shutdown"), "M4 context-menu shutdown"
    )
    for field in ("ok", "accepted", "complete"):
        if shutdown.get(field) is not True:
            raise M0Error(f"M4 context-menu shutdown {field} is not true")
    for field in ("exitCode", "runtimeExitCode"):
        if shutdown.get(field) != 0:
            raise M0Error(f"M4 context-menu shutdown {field} is not zero")
    logs = _require_dict(result.get("logs"), "M4 context-menu logs")
    for stream in ("host", "stdout", "stderr"):
        if not isinstance(logs.get(stream), list):
            raise M0Error(f"M4 context-menu {stream} log is not an array")
    combined_logs = "\n".join(
        str(line)
        for stream in ("host", "stdout", "stderr")
        for line in logs[stream]
    )
    if "abort:" in combined_logs.lower():
        raise M0Error("M4 context-menu logs contain a Wasm abort")
    host_logs = [str(line) for line in logs["host"]]
    for marker in (
        "m4:pointer:listeners-attached",
        "m4:keyboard:listeners-attached",
        "m4:contextmenu:suppressed",
        "m4:keyboard:pointer-activation",
        "m4:keyboard:down:queued",
        "m4:keyboard:up:queued",
    ):
        if marker not in host_logs:
            raise M0Error(
                f"M4 context-menu logs are missing lifecycle marker {marker!r}"
            )
    if host_logs[-1:] != ["shutdown:complete"]:
        raise M0Error("M4 context-menu logs are missing clean shutdown")


def validate_m4_tooltip_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
) -> None:
    """Validate Blink's title through the native Aura tooltip path.

    Four physical mouse moves exercise a rapid title-to-title-less pair and a
    duplicate same-point title hover. A fifth trusted DOM move leaves the host
    canvas, which must become one native mouse-exit record rather than an
    out-of-viewport in-canvas move.
    """

    expected = {
        "protocol": M3_PROTOCOL,
        "case": M4_TOOLTIP_CASE,
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
                f"M4 tooltip result {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )

    versions = _require_dict(result.get("versions"), "M4 tooltip versions")
    if versions != expected_versions:
        raise M0Error(
            "M4 tooltip version display mismatch: expected "
            f"{expected_versions!r}, got {versions!r}"
        )

    readiness = _require_dict(result.get("readiness"), "M4 tooltip readiness")
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
            raise M0Error(f"M4 tooltip readiness field {field} is not true")
    if readiness.get("fatalErrors") != []:
        raise M0Error("M4 tooltip readiness reported fatal errors")
    heartbeat = _require_dict(
        readiness.get("heartbeat"), "M4 tooltip heartbeat"
    )
    if heartbeat.get("anchor") != "data-navigation-committed":
        raise M0Error("M4 tooltip heartbeat was not anchored to navigation")
    _require_number(
        heartbeat.get("elapsedMs"), "M4 tooltip heartbeat elapsed time", minimum=0
    )

    frame = _require_dict(readiness.get("frame"), "M4 tooltip frame")
    final_frame_id = _require_safe_integer(
        frame.get("id"), "M4 tooltip frame ID", minimum=1
    )
    _require_number(
        frame.get("timestampMs"), "M4 tooltip frame timestamp", minimum=0
    )
    if frame.get("width") != M3_WIDTH or frame.get("height") != M3_HEIGHT:
        raise M0Error("M4 tooltip frame dimensions do not match the canvas")

    page_probe = _require_dict(
        readiness.get("pageProbe"), "M4 tooltip page probe"
    )
    expected_probe = {
        "protocol": M3_PROTOCOL,
        "fixture": "chromium-wasm-m4-ozone-tooltip-v1",
        "fontReady": True,
        "ready": True,
        "tooltipTitle": "WASM TOOLTIP",
        "confirmTitle": "SWAM TOOLTIP",
        "clearTitle": None,
        "resultText": "TRUSTED MOVE 4",
    }
    for field, expected_value in expected_probe.items():
        actual_value = page_probe.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 tooltip page probe {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )
    _require_safe_integer(
        page_probe.get("timerTicks"), "M4 tooltip inner timer ticks", minimum=3
    )
    coordinates = {
        "hoverTargetX": 220,
        "hoverTargetY": 116,
        "confirmTargetX": 220,
        "confirmTargetY": 286,
        "clearTargetX": 580,
        "clearTargetY": 376,
    }
    for field, expected_value in coordinates.items():
        maximum = M3_WIDTH - 1 if field.endswith("X") else M3_HEIGHT - 1
        actual_value = _require_safe_integer(
            page_probe.get(field), f"M4 tooltip {field}", minimum=0,
            maximum=maximum,
        )
        if actual_value != expected_value:
            raise M0Error(
                f"M4 tooltip {field} mismatch: expected {expected_value}, "
                f"got {actual_value}"
            )
    hover_x = coordinates["hoverTargetX"]
    hover_y = coordinates["hoverTargetY"]
    confirm_x = coordinates["confirmTargetX"]
    confirm_y = coordinates["confirmTargetY"]
    clear_x = coordinates["clearTargetX"]
    clear_y = coordinates["clearTargetY"]
    if (
        hover_x + 12 + 110 > M3_WIDTH
        or hover_y + 18 + 24 > M3_HEIGHT
        or confirm_x + 12 + 110 > M3_WIDTH
        or confirm_y + 18 + 24 > M3_HEIGHT
    ):
        raise M0Error("M4 tooltip fixture can only show a clamped overlay")

    expected_moves = (
        ("tooltip-target", hover_x, hover_y),
        ("clear-target", clear_x, clear_y),
        ("confirm-target", confirm_x, confirm_y),
        ("confirm-target", confirm_x, confirm_y),
    )

    def require_inner_trace(prefix: str, button: int) -> None:
        trace = page_probe.get(f"{prefix}Trace")
        if not isinstance(trace, list) or len(trace) != len(expected_moves):
            raise M0Error(f"M4 tooltip {prefix} trace is not four moves")
        for index, (target_id, x, y) in enumerate(expected_moves):
            record = _require_dict(
                trace[index], f"M4 tooltip {prefix} trace {index}"
            )
            expected_record = {
                "type": f"{prefix}move",
                "trusted": True,
                "button": button,
                "buttons": 0,
                "clientX": x,
                "clientY": y,
                "targetId": target_id,
                "defaultPrevented": False,
            }
            for field, expected_value in expected_record.items():
                if record.get(field) != expected_value:
                    raise M0Error(
                        f"M4 tooltip {prefix} trace {index} {field} mismatch"
                    )

    require_inner_trace("mouse", 0)
    require_inner_trace("pointer", -1)
    mouse_leave_trace = page_probe.get("mouseLeaveTrace")
    if not isinstance(mouse_leave_trace, list) or len(mouse_leave_trace) != 1:
        raise M0Error("M4 tooltip inner mouseleave trace is not exact")
    mouse_leave = _require_dict(mouse_leave_trace[0], "M4 tooltip mouseleave")
    for field, expected_value in {
        "type": "mouseleave",
        "trusted": True,
        "button": 0,
        "buttons": 0,
        "clientX": confirm_x,
        "clientY": confirm_y,
        "targetId": "confirm-target",
        "defaultPrevented": False,
    }.items():
        if mouse_leave.get(field) != expected_value:
            raise M0Error(f"M4 tooltip mouseleave {field} mismatch")

    def require_move_gap(
        prefix: str, first_index: int, second_index: int, description: str
    ) -> int:
        trace = page_probe.get(f"{prefix}Trace")
        assert isinstance(trace, list)
        first_move = _require_dict(
            trace[first_index], f"M4 tooltip {prefix} {description} first move"
        )
        second_move = _require_dict(
            trace[second_index],
            f"M4 tooltip {prefix} {description} second move",
        )
        first_timestamp = _require_safe_integer(
            first_move.get("observedAtMs"),
            f"M4 tooltip {prefix} {description} first move timestamp",
            minimum=0,
        )
        second_timestamp = _require_safe_integer(
            second_move.get("observedAtMs"),
            f"M4 tooltip {prefix} {description} second move timestamp",
            minimum=0,
        )
        if second_timestamp < first_timestamp:
            raise M0Error(
                f"M4 tooltip {prefix} {description} timestamps are not ordered"
            )
        return second_timestamp - first_timestamp

    rapid_move_gap_ms = max(
        require_move_gap("mouse", 0, 1, "rapid move"),
        require_move_gap("pointer", 0, 1, "rapid move"),
    )
    if rapid_move_gap_ms > M4_TOOLTIP_RAPID_MOVE_MAX_GAP_MS:
        raise M0Error(
            "M4 tooltip rapid title clear was not delivered before hover"
        )
    duplicate_hover_gap_ms = max(
        require_move_gap("mouse", 2, 3, "duplicate hover"),
        require_move_gap("pointer", 2, 3, "duplicate hover"),
    )
    if duplicate_hover_gap_ms > M4_TOOLTIP_RAPID_MOVE_MAX_GAP_MS:
        raise M0Error("M4 tooltip duplicate title hover was not prompt")

    pointer_input = _require_dict(
        result.get("pointerInput"), "M4 tooltip pointer input"
    )
    readiness_pointer = _require_dict(
        readiness.get("pointerInput"), "M4 tooltip readiness pointer input"
    )
    if not _exact_json_value_equal(pointer_input, readiness_pointer):
        raise M0Error("M4 tooltip pointer evidence differs from readiness")
    exit_sequence = len(expected_moves) + 1
    if (
        pointer_input.get("enabled") is not True
        or pointer_input.get("receivedCount") != exit_sequence
        or pointer_input.get("trustedCount") != exit_sequence
        or pointer_input.get("queuedCount") != exit_sequence
    ):
        raise M0Error("M4 tooltip pointer input counts are not exact")
    queued_records = pointer_input.get("queuedRecords")
    if not isinstance(queued_records, list) or len(queued_records) != exit_sequence:
        raise M0Error("M4 tooltip pointer trace is not four moves and one exit")
    input_frames: list[int] = []
    for index, (_, x, y) in enumerate(expected_moves):
        record = _require_dict(
            queued_records[index], f"M4 tooltip pointer trace {index}"
        )
        expected_record = {
            "sequence": index + 1,
            "type": "move",
            "trusted": True,
            "queued": True,
            "button": -1,
            "buttons": 0,
            "x": x,
            "y": y,
            "canvasFocused": True,
        }
        for field, expected_value in expected_record.items():
            if record.get(field) != expected_value:
                raise M0Error(
                    f"M4 tooltip pointer trace {index} {field} mismatch"
                )
        input_frames.append(
            _require_safe_integer(
                record.get("frameIdBefore"),
                f"M4 tooltip pointer trace {index} frame ID",
                minimum=1,
            )
        )
    exit_record = _require_dict(
        queued_records[-1], "M4 tooltip pointer exit record"
    )
    for field, expected_value in {
        "sequence": exit_sequence,
        "type": "exit",
        "trusted": True,
        "queued": True,
        "button": -1,
        "buttons": 0,
        "canvasFocused": True,
    }.items():
        if exit_record.get(field) != expected_value:
            raise M0Error(
                f"M4 tooltip pointer exit {field} mismatch"
            )
    if "x" in exit_record or "y" in exit_record:
        raise M0Error("M4 tooltip pointer exit forwarded an outside coordinate")
    exit_frame_id = _require_safe_integer(
        exit_record.get("frameIdBefore"),
        "M4 tooltip pointer exit frame ID",
        minimum=1,
    )
    last_queued = _require_dict(
        pointer_input.get("lastQueued"), "M4 tooltip last queued pointer"
    )
    if not _exact_json_value_equal(last_queued, queued_records[-1]):
        raise M0Error("M4 tooltip last queued pointer differs from trace")

    rapid_clear_proof = _require_dict(
        result.get("tooltipRapidClearProof"), "M4 rapid tooltip clear proof"
    )
    rapid_clear_frame_id = _require_safe_integer(
        rapid_clear_proof.get("frameId"),
        "M4 rapid tooltip clear frame ID",
        minimum=1,
    )
    if rapid_clear_frame_id <= input_frames[1]:
        raise M0Error("M4 rapid tooltip clear has no newer compositor frame")
    if _require_safe_integer(
        rapid_clear_proof.get("backgroundPixels"),
        "M4 rapid tooltip clear background pixels",
        minimum=0,
    ) != 0:
        raise M0Error("M4 rapid tooltip clear proof leaves native background")
    rapid_quiet_for_ms = _require_safe_integer(
        rapid_clear_proof.get("quietForMs"),
        "M4 rapid tooltip clear quiet duration",
        minimum=0,
    )
    if rapid_quiet_for_ms < M4_TOOLTIP_CLEAR_QUIESCENCE_MS:
        raise M0Error("M4 rapid tooltip clear did not outlive the hover delay")
    if _require_safe_integer(
        rapid_clear_proof.get("moveGapMs"),
        "M4 rapid tooltip clear move gap",
        minimum=0,
    ) != rapid_move_gap_ms:
        raise M0Error("M4 rapid tooltip clear proof has the wrong input gap")

    show_proof = _require_dict(
        result.get("tooltipShowProof"), "M4 tooltip show proof"
    )
    show_frame_id = _require_safe_integer(
        show_proof.get("frameId"), "M4 tooltip show frame ID", minimum=1
    )
    if (
        show_frame_id <= rapid_clear_frame_id
        or show_frame_id <= input_frames[3]
    ):
        raise M0Error("M4 tooltip has no compositor frame after the hover")
    overlay = _require_dict(
        show_proof.get("overlay"), "M4 tooltip compositor overlay scan"
    )
    for field, expected_value in {
        "backgroundRgba": [32, 33, 36, 255],
        "borderRgba": [95, 99, 104, 255],
        "inkRgba": [255, 255, 255, 255],
        "backgroundPixels": 1952,
        "borderPixels": 264,
        "inkPixels": 424,
        "minX": confirm_x + 12,
        "minY": confirm_y + 18,
        "maxX": confirm_x + 12 + 110 - 1,
        "maxY": confirm_y + 18 + 24 - 1,
        "width": 110,
        "height": 24,
        "anchorX": confirm_x + 12,
        "anchorY": confirm_y + 18,
        "label": "SWAM TOOLTIP",
    }.items():
        actual_value = overlay.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 tooltip compositor overlay {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )
    if _require_safe_integer(
        show_proof.get("duplicateMoveGapMs"),
        "M4 tooltip duplicate hover move gap",
        minimum=0,
    ) != duplicate_hover_gap_ms:
        raise M0Error("M4 tooltip show proof has the wrong duplicate move gap")

    exit_proof = _require_dict(
        result.get("tooltipExitProof"), "M4 tooltip exit proof"
    )
    exit_proof_frame_id = _require_safe_integer(
        exit_proof.get("frameId"), "M4 tooltip exit frame ID", minimum=1
    )
    if exit_proof.get("overlayAbsent") is not True:
        raise M0Error("M4 tooltip exit proof does not remove the overlay")
    if _require_safe_integer(
        exit_proof.get("backgroundPixels"),
        "M4 tooltip exit background pixels",
        minimum=0,
    ) != 0:
        raise M0Error("M4 tooltip exit proof leaves native background pixels")
    quiet_for_ms = _require_safe_integer(
        exit_proof.get("quietForMs"),
        "M4 tooltip exit quiet duration",
        minimum=0,
    )
    if quiet_for_ms < M4_TOOLTIP_CLEAR_QUIESCENCE_MS:
        raise M0Error("M4 tooltip exit proof did not outlive the hover delay")
    if exit_proof_frame_id <= show_frame_id or exit_proof_frame_id <= exit_frame_id:
        raise M0Error("M4 tooltip has no newer compositor frame after exit")
    if final_frame_id != exit_proof_frame_id:
        raise M0Error("M4 tooltip final frame differs from the exit proof")

    shutdown = _require_dict(result.get("shutdown"), "M4 tooltip shutdown")
    for field in ("ok", "accepted", "complete"):
        if shutdown.get(field) is not True:
            raise M0Error(f"M4 tooltip shutdown {field} is not true")
    for field in ("exitCode", "runtimeExitCode"):
        if _require_safe_integer(
            shutdown.get(field), f"M4 tooltip shutdown {field}"
        ) != 0:
            raise M0Error(f"M4 tooltip shutdown {field} is not zero")

    logs = _require_dict(result.get("logs"), "M4 tooltip logs")
    for stream in ("host", "stdout", "stderr"):
        if not isinstance(logs.get(stream), list):
            raise M0Error(f"M4 tooltip {stream} log must be an array")
    combined_logs = "\n".join(
        str(line)
        for stream in ("host", "stdout", "stderr")
        for line in logs[stream]
    )
    if "abort:" in combined_logs.lower():
        raise M0Error("M4 tooltip logs contain a Wasm abort")
    host_logs = [str(line) for line in logs["host"]]
    pointer_logs = [
        line for line in host_logs if line.startswith("m4:pointer:")
    ]
    if pointer_logs != [
        "m4:pointer:listeners-attached",
        "m4:pointer:move:queued",
        "m4:pointer:move:queued",
        "m4:pointer:move:queued",
        "m4:pointer:move:queued",
        "m4:pointer:exit:queued",
    ]:
        raise M0Error("M4 tooltip pointer lifecycle logs are not exact")
    if host_logs[-1:] != ["shutdown:complete"]:
        raise M0Error("M4 tooltip logs are missing clean shutdown")


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
        "selectionDirectionNeutral",
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
    if activation_proof.get("selectionDirection") not in (
        "none",
        "forward",
    ):
        raise M0Error(
            "M4 selection activation proof selection direction is invalid"
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


def validate_m4_primary_paste_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
) -> None:
    """Validate native primary-selection paste through Ozone, Aura, and Blink.

    The source drag writes the Ozone-supported process-local primary-selection
    buffer. A later trusted middle mouse release must make Blink execute its
    normal PasteGlobalSelection command. No host Clipboard API or DOM editing
    command is involved.
    """

    expected = {
        "protocol": M3_PROTOCOL,
        "case": M4_PRIMARY_PASTE_CASE,
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
                f"M4 primary paste result {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )

    versions = _require_dict(
        result.get("versions"), "M4 primary paste versions"
    )
    if versions != expected_versions:
        raise M0Error(
            "M4 primary paste version display mismatch: expected "
            f"{expected_versions!r}, got {versions!r}"
        )

    for proof_name, required_fields in {
        "activationProof": (
            "outerTraceExact",
            "sourceActivated",
            "selectionCollapsed",
            "frameAfterActivation",
        ),
        "selectionProof": (
            "outerTraceExact",
            "nativeSelection",
            "innerSourceEvents",
            "frameAfterDrag",
        ),
        "primaryPasteProof": (
            "sourceSelection",
            "outerTraceExact",
            "nativePaste",
            "frameAfterPaste",
        ),
    }.items():
        proof = _require_dict(
            result.get(proof_name), f"M4 primary paste {proof_name}"
        )
        for field in required_fields:
            if proof.get(field) is not True:
                raise M0Error(
                    f"M4 primary paste {proof_name} {field} is not true"
                )

    readiness = _require_dict(
        result.get("readiness"), "M4 primary paste readiness"
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
                f"M4 primary paste readiness field {field} is not true"
            )
    if readiness.get("fatalErrors") != []:
        raise M0Error("M4 primary paste readiness reported fatal errors")
    heartbeat = _require_dict(
        readiness.get("heartbeat"), "M4 primary paste heartbeat"
    )
    if heartbeat.get("anchor") != "data-navigation-committed":
        raise M0Error(
            "M4 primary paste heartbeat was not anchored to data navigation"
        )
    _require_number(
        heartbeat.get("elapsedMs"),
        "M4 primary paste heartbeat elapsed time",
        minimum=0,
    )

    frame = _require_dict(readiness.get("frame"), "M4 primary paste frame")
    frame_id = _require_safe_integer(
        frame.get("id"), "M4 primary paste frame ID", minimum=1
    )
    _require_number(
        frame.get("timestampMs"),
        "M4 primary paste frame timestamp",
        minimum=0,
    )
    if frame.get("width") != M3_WIDTH or frame.get("height") != M3_HEIGHT:
        raise M0Error(
            "M4 primary paste frame dimensions do not match the canvas"
        )

    page_probe = _require_dict(
        readiness.get("pageProbe"), "M4 primary paste page probe"
    )
    expected_probe = {
        "fontReady": True,
        "protocol": M3_PROTOCOL,
        "fixture": "chromium-wasm-m4-ozone-primary-paste-v1",
        "ready": True,
        "activeElementId": "paste-target",
        "sourceValue": "WASM",
        "sourceSelectionStart": 0,
        "sourceSelectionEnd": 4,
        "sourceSelectedText": "WASM",
        "sourceActivationCount": 2,
        "sourceClickTrusted": True,
        "sourceFocusTrusted": True,
        "pasteActivationCount": 0,
        "pasteClickTrusted": False,
        "pasteAuxClickCount": 1,
        "pasteAuxClickTrusted": True,
        "pasteFocusTrusted": True,
        "pasteValue": "WASM",
        "pasteSelectionStart": 4,
        "pasteSelectionEnd": 4,
        "resultText": "PRIMARY SELECTION PASTED",
    }
    for field, expected_value in expected_probe.items():
        actual_value = page_probe.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 primary paste page probe {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )
    if page_probe.get("sourceSelectionDirection") not in (
        "none",
        "forward",
    ):
        raise M0Error(
            "M4 primary paste source selection direction is invalid"
        )
    for field in ("sourceFocusCount", "pasteFocusCount"):
        _require_safe_integer(
            page_probe.get(field),
            f"M4 primary paste {field}",
            minimum=1,
        )
    _require_safe_integer(
        page_probe.get("timerTicks"),
        "M4 primary paste inner page timer ticks",
        minimum=3,
    )

    coordinates: dict[str, int] = {}
    for field in (
        "sourceTargetX",
        "sourceTargetY",
        "dragStartX",
        "dragStartY",
        "dragMiddleX",
        "dragMiddleY",
        "dragEndX",
        "dragEndY",
        "pasteTargetX",
        "pasteTargetY",
    ):
        maximum = M3_WIDTH - 1 if field.endswith("X") else M3_HEIGHT - 1
        coordinates[field] = _require_safe_integer(
            page_probe.get(field),
            f"M4 primary paste {field}",
            minimum=0,
            maximum=maximum,
        )
    if not (
        coordinates["dragStartX"]
        < coordinates["dragMiddleX"]
        < coordinates["dragEndX"]
        and coordinates["dragStartY"]
        == coordinates["dragMiddleY"]
        == coordinates["dragEndY"]
    ):
        raise M0Error("M4 primary paste drag geometry is not strictly forward")

    source_activity = _require_dict(
        page_probe.get("sourceSelectionActivity"),
        "M4 primary paste source selection activity",
    )
    for field in (
        "trusted",
        "nonCollapsed",
        "trustedNonCollapsed",
        "selectTrusted",
        "selectionChangeTrusted",
    ):
        if source_activity.get(field) is not True:
            raise M0Error(
                f"M4 primary paste source selection {field} is not true"
            )
    for field in ("count", "selectCount", "selectionChangeCount"):
        _require_safe_integer(
            source_activity.get(field),
            f"M4 primary paste source selection {field}",
            minimum=1,
        )

    source_text = _require_dict(
        page_probe.get("sourceTextInputEvents"),
        "M4 primary paste source text input events",
    )
    for field in (
        "beforeinputCount",
        "inputCount",
        "compositionstartCount",
        "compositionupdateCount",
        "compositionendCount",
    ):
        if _require_safe_integer(
            source_text.get(field),
            f"M4 primary paste source {field}",
            minimum=0,
        ) != 0:
            raise M0Error(
                "M4 primary paste source unexpectedly received text or "
                f"composition input: {field}"
            )

    paste_events = page_probe.get("pasteEventTrace")
    if not isinstance(paste_events, list) or len(paste_events) != 1:
        raise M0Error("M4 primary paste event trace is not exactly one event")
    paste_event = _require_dict(paste_events[0], "M4 primary paste event")
    for field, expected_value in {
        "type": "paste",
        "trusted": True,
        "targetId": "paste-target",
        "defaultPrevented": False,
    }.items():
        if paste_event.get(field) != expected_value:
            raise M0Error(
                f"M4 primary paste event {field} mismatch: expected "
                f"{expected_value!r}, got {paste_event.get(field)!r}"
            )

    paste_text = page_probe.get("pasteTextInputTrace")
    if not isinstance(paste_text, list) or len(paste_text) != 2:
        raise M0Error(
            "M4 primary paste text trace is not exactly two events"
        )
    for index, event_type in enumerate(("beforeinput", "input")):
        text_event = _require_dict(
            paste_text[index], f"M4 primary paste text trace {index}"
        )
        for field, expected_value in {
            "type": event_type,
            "trusted": True,
            "inputType": "insertFromPaste",
            "data": "WASM",
            "isComposing": False,
            "targetId": "paste-target",
        }.items():
            if text_event.get(field) != expected_value:
                raise M0Error(
                    f"M4 primary paste text trace {index} {field} mismatch: "
                    f"expected {expected_value!r}, got "
                    f"{text_event.get(field)!r}"
                )

    expected_outer_trace = (
        ("move", coordinates["sourceTargetX"], coordinates["sourceTargetY"], -1, 0),
        ("down", coordinates["sourceTargetX"], coordinates["sourceTargetY"], 0, 1),
        ("up", coordinates["sourceTargetX"], coordinates["sourceTargetY"], 0, 0),
        ("move", coordinates["dragStartX"], coordinates["dragStartY"], -1, 0),
        ("down", coordinates["dragStartX"], coordinates["dragStartY"], 0, 1),
        ("move", coordinates["dragMiddleX"], coordinates["dragMiddleY"], -1, 1),
        ("move", coordinates["dragEndX"], coordinates["dragEndY"], -1, 1),
        ("up", coordinates["dragEndX"], coordinates["dragEndY"], 0, 0),
        ("move", coordinates["pasteTargetX"], coordinates["pasteTargetY"], -1, 0),
        ("down", coordinates["pasteTargetX"], coordinates["pasteTargetY"], 1, 4),
        ("up", coordinates["pasteTargetX"], coordinates["pasteTargetY"], 1, 0),
    )
    pointer_input = _require_dict(
        result.get("pointerInput"), "M4 primary paste pointer input"
    )
    readiness_pointer = _require_dict(
        readiness.get("pointerInput"), "M4 primary paste readiness pointer"
    )
    if not _exact_json_value_equal(pointer_input, readiness_pointer):
        raise M0Error(
            "M4 primary paste pointer evidence differs from readiness evidence"
        )
    if pointer_input.get("enabled") is not True:
        raise M0Error("M4 primary paste pointer listeners were not enabled")
    for field in ("receivedCount", "trustedCount", "queuedCount"):
        if _require_safe_integer(
            pointer_input.get(field),
            f"M4 primary paste pointer {field}",
            minimum=0,
        ) != len(expected_outer_trace):
            raise M0Error(
                f"M4 primary paste pointer {field} is not exactly "
                f"{len(expected_outer_trace)}"
            )
    queued_records = pointer_input.get("queuedRecords")
    if not isinstance(queued_records, list) or len(queued_records) != len(
        expected_outer_trace
    ):
        raise M0Error(
            "M4 primary paste queued pointer trace is not exactly eleven "
            "records"
        )
    paste_up_frame_id = 0
    for index, (event_type, x, y, button, buttons) in enumerate(
        expected_outer_trace
    ):
        record = _require_dict(
            queued_records[index],
            f"M4 primary paste queued pointer trace {index}",
        )
        for field, expected_value in {
            "type": event_type,
            "trusted": True,
            "queued": True,
            "button": button,
            "buttons": buttons,
            "sequence": index + 1,
            "x": x,
            "y": y,
        }.items():
            if record.get(field) != expected_value:
                raise M0Error(
                    f"M4 primary paste queued pointer trace {index} {field} "
                    f"mismatch: expected {expected_value!r}, got "
                    f"{record.get(field)!r}"
                )
        if record.get("canvasFocused") is not True:
            raise M0Error(
                f"M4 primary paste queued pointer trace {index} canvas focus "
                "mismatch"
            )
        if index >= len(expected_outer_trace) - 2:
            if record.get("defaultPrevented") is not True:
                raise M0Error(
                    "M4 primary paste middle-button pointer trace did not "
                    "prevent the outer page default"
                )
        record_frame_id = _require_safe_integer(
            record.get("frameIdBefore"),
            f"M4 primary paste queued pointer trace {index} frame ID",
            minimum=1,
        )
        if index == len(expected_outer_trace) - 1:
            paste_up_frame_id = record_frame_id
    last_queued = _require_dict(
        pointer_input.get("lastQueued"), "M4 primary paste last queued pointer"
    )
    if not _exact_json_value_equal(last_queued, queued_records[-1]):
        raise M0Error(
            "M4 primary paste last queued pointer does not match middle release"
        )
    if frame_id <= paste_up_frame_id:
        raise M0Error(
            "M4 primary paste result has no compositor frame after paste"
        )

    def require_inner_button(
        field: str,
        prefix: str,
        target_id: str,
        button: int,
        buttons: int,
    ) -> None:
        trace = page_probe.get(field)
        if not isinstance(trace, list):
            raise M0Error(f"M4 primary paste {field} is not an array")
        for event_type in ("down", "up"):
            expected_buttons = buttons if event_type == "down" else 0
            if not any(
                isinstance(record, dict)
                and record.get("type") == prefix + event_type
                and record.get("trusted") is True
                and record.get("button") == button
                and record.get("buttons") == expected_buttons
                and record.get("targetId") == target_id
                and record.get("defaultPrevented") is False
                for record in trace
            ):
                raise M0Error(
                    f"M4 primary paste {field} has no trusted {event_type} "
                    f"for {target_id} button {button}"
                )

    require_inner_button(
        "sourceMouseEventTrace", "mouse", "source-target", 0, 1
    )
    require_inner_button(
        "sourcePointerEventTrace", "pointer", "source-target", 0, 1
    )
    require_inner_button(
        "pasteMouseEventTrace", "mouse", "paste-target", 1, 4
    )
    require_inner_button(
        "pastePointerEventTrace", "pointer", "paste-target", 1, 4
    )

    shutdown = _require_dict(
        result.get("shutdown"), "M4 primary paste shutdown"
    )
    for field in ("ok", "accepted", "complete"):
        if shutdown.get(field) is not True:
            raise M0Error(f"M4 primary paste shutdown {field} is not true")
    for field in ("exitCode", "runtimeExitCode"):
        if _require_safe_integer(
            shutdown.get(field), f"M4 primary paste shutdown {field}"
        ) != 0:
            raise M0Error(
                f"M4 primary paste shutdown {field} is not zero"
            )

    logs = _require_dict(result.get("logs"), "M4 primary paste logs")
    for stream in ("host", "stdout", "stderr"):
        if not isinstance(logs.get(stream), list):
            raise M0Error(
                f"M4 primary paste {stream} log must be an array"
            )
    combined_logs = "\n".join(
        str(line)
        for stream in ("host", "stdout", "stderr")
        for line in logs[stream]
    )
    if "abort:" in combined_logs.lower():
        raise M0Error("M4 primary paste logs contain a Wasm abort")
    host_logs = [str(line) for line in logs["host"]]
    for marker in (
        "m4:pointer:listeners-attached",
        "m4:pointer:down:queued",
        "m4:pointer:up:queued",
        "shutdown:complete",
    ):
        if not any(marker in line for line in host_logs):
            raise M0Error(
                f"M4 primary paste logs are missing lifecycle marker {marker!r}"
            )


def validate_m4_copy_paste_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
) -> None:
    """Validate Ctrl+V after a decoy selection, then primary paste last."""

    expected = {
        "protocol": M3_PROTOCOL,
        "case": M4_COPY_PASTE_CASE,
        "status": "pass",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "failedChecks": [],
        "error": None,
    }
    for field, expected_value in expected.items():
        if result.get(field) != expected_value:
            raise M0Error(
                f"M4 copy/paste result {field} mismatch: expected "
                f"{expected_value!r}, got {result.get(field)!r}"
            )
    versions = _require_dict(
        result.get("versions"), "M4 copy/paste versions"
    )
    if versions != expected_versions:
        raise M0Error("M4 copy/paste version display mismatch")

    for proof_name, fields in {
        "activationProof": (
            "outerTraceExact",
            "sourceActivated",
            "frameAfterActivation",
        ),
        "bareShortcutProof": (
            "hostRejected",
            "noBlinkDelivery",
        ),
        "sourceSelectionProof": (
            "outerTraceExact",
            "nativeSelection",
            "frameAfterDrag",
        ),
        "copyProof": (
            "outerTraceExact",
            "nativeCopy",
            "bareShortcutRejected",
            "innerKeys",
            "shortcutReleased",
        ),
        "decoySelectionProof": (
            "outerTraceExact",
            "primarySelectionOverwritten",
            "releaseQueued",
        ),
        "primarySelectionPasteProof": (
            "outerTraceExact",
            "primaryBufferContainsDecoy",
            "frameAfterPrimaryPaste",
        ),
        "pasteProof": (
            "outerPointerTraceExact",
            "outerKeyTraceExact",
            "innerKeys",
            "nativePaste",
            "copyPasteBufferWins",
            "frameAfterPaste",
        ),
    }.items():
        proof = _require_dict(
            result.get(proof_name), f"M4 copy/paste {proof_name}"
        )
        for field in fields:
            if proof.get(field) is not True:
                raise M0Error(
                    f"M4 copy/paste {proof_name} {field} is not true"
                )

    readiness = _require_dict(
        result.get("readiness"), "M4 copy/paste readiness"
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
                f"M4 copy/paste readiness field {field} is not true"
            )
    if readiness.get("fatalErrors") != []:
        raise M0Error("M4 copy/paste readiness reported fatal errors")
    heartbeat = _require_dict(
        readiness.get("heartbeat"), "M4 copy/paste heartbeat"
    )
    if heartbeat.get("anchor") != "data-navigation-committed":
        raise M0Error(
            "M4 copy/paste heartbeat was not anchored to data navigation"
        )
    _require_number(
        heartbeat.get("elapsedMs"),
        "M4 copy/paste heartbeat elapsed time",
        minimum=0,
    )
    frame = _require_dict(readiness.get("frame"), "M4 copy/paste frame")
    frame_id = _require_safe_integer(
        frame.get("id"), "M4 copy/paste frame ID", minimum=1
    )
    if frame.get("width") != M3_WIDTH or frame.get("height") != M3_HEIGHT:
        raise M0Error(
            "M4 copy/paste frame dimensions do not match the canvas"
        )

    page_probe = _require_dict(
        readiness.get("pageProbe"), "M4 copy/paste page probe"
    )
    for field, expected_value in {
        "fontReady": True,
        "protocol": M3_PROTOCOL,
        "fixture": "chromium-wasm-m4-ozone-copy-paste-v1",
        "ready": True,
        "activeElementId": "primary-verify-target",
        "copySourceValue": "COPY",
        "decoyValue": "DECOY",
        "primaryVerifyValue": "DECOY",
        "primaryVerifySelectionStart": 5,
        "primaryVerifySelectionEnd": 5,
        "pasteValue": "COPY",
        "pasteSelectionStart": 4,
        "pasteSelectionEnd": 4,
        "pasteTargetActivationCount": 1,
        "resultText": "CTRL COPY/PASTE DELIVERED",
    }.items():
        if page_probe.get(field) != expected_value:
            raise M0Error(
                f"M4 copy/paste page probe {field} mismatch: expected "
                f"{expected_value!r}, got {page_probe.get(field)!r}"
            )
    _require_safe_integer(
        page_probe.get("timerTicks"),
        "M4 copy/paste page timer ticks",
        minimum=3,
    )
    for field in (
        "copySourceActivationCount",
        "copySourceFocusCount",
        "selectionDecoyActivationCount",
        "selectionDecoyFocusCount",
        "primaryVerifyFocusCount",
        "pasteTargetFocusCount",
    ):
        _require_safe_integer(
            page_probe.get(field),
            f"M4 copy/paste page probe {field}",
            minimum=1,
        )
    for field, expected_value in {
        "primaryVerifyAuxClickCount": 1,
        "primaryVerifyAuxClickTrusted": True,
        "primaryVerifyFocusTrusted": True,
    }.items():
        if page_probe.get(field) != expected_value:
            raise M0Error(
                f"M4 copy/paste page probe {field} mismatch: expected "
                f"{expected_value!r}, got {page_probe.get(field)!r}"
            )

    coordinates: dict[str, int] = {}
    for field in (
        "copySourceTargetX",
        "copySourceTargetY",
        "copyDragStartX",
        "copyDragStartY",
        "copyDragMiddleX",
        "copyDragMiddleY",
        "copyDragEndX",
        "copyDragEndY",
        "decoyTargetX",
        "decoyTargetY",
        "decoyDragStartX",
        "decoyDragStartY",
        "decoyDragMiddleX",
        "decoyDragMiddleY",
        "decoyDragEndX",
        "decoyDragEndY",
        "primaryVerifyTargetX",
        "primaryVerifyTargetY",
        "pasteTargetX",
        "pasteTargetY",
    ):
        maximum = M3_WIDTH - 1 if field.endswith("X") else M3_HEIGHT - 1
        coordinates[field] = _require_safe_integer(
            page_probe.get(field),
            f"M4 copy/paste {field}",
            minimum=0,
            maximum=maximum,
        )
    for prefix in ("copyDrag", "decoyDrag"):
        if not (
            coordinates[prefix + "StartX"]
            < coordinates[prefix + "MiddleX"]
            < coordinates[prefix + "EndX"]
            and coordinates[prefix + "StartY"]
            == coordinates[prefix + "MiddleY"]
            == coordinates[prefix + "EndY"]
        ):
            raise M0Error(
                f"M4 copy/paste {prefix} geometry is not strictly forward"
            )

    def require_selection(field: str, value: str) -> None:
        activity = _require_dict(
            page_probe.get(field), f"M4 copy/paste {field}"
        )
        for activity_field in (
            "trusted",
            "nonCollapsed",
            "trustedNonCollapsed",
            "selectTrusted",
            "selectionChangeTrusted",
        ):
            if activity.get(activity_field) is not True:
                raise M0Error(
                    f"M4 copy/paste {field} {activity_field} is not true"
                )
        selection = _require_dict(
            activity.get("lastNonCollapsed"),
            f"M4 copy/paste {field} last selection",
        )
        for selection_field, expected_value in {
            "trusted": True,
            "start": 0,
            "end": len(value),
            "text": value,
        }.items():
            if selection.get(selection_field) != expected_value:
                raise M0Error(
                    f"M4 copy/paste {field} {selection_field} mismatch"
                )
        if selection.get("direction") not in ("none", "forward"):
            raise M0Error(
                f"M4 copy/paste {field} selection direction is invalid"
            )

    require_selection("copySelectionActivity", "COPY")
    require_selection("decoySelectionActivity", "DECOY")
    for field in ("sourceTextInputEvents", "decoyTextInputEvents"):
        text_events = _require_dict(
            page_probe.get(field), f"M4 copy/paste {field}"
        )
        for event_field in (
            "beforeinputCount",
            "inputCount",
            "compositionstartCount",
            "compositionupdateCount",
            "compositionendCount",
        ):
            if _require_safe_integer(
                text_events.get(event_field),
                f"M4 copy/paste {field} {event_field}",
                minimum=0,
            ) != 0:
                raise M0Error(
                    f"M4 copy/paste {field} unexpectedly received "
                    f"text or composition input: {event_field}"
                )

    copy_events = page_probe.get("copyEventTrace")
    if not isinstance(copy_events, list) or len(copy_events) != 1:
        raise M0Error("M4 copy/paste copy trace is not exactly one event")
    copy_event = _require_dict(copy_events[0], "M4 copy/paste copy event")
    for field, expected_value in {
        "type": "copy",
        "trusted": True,
        "targetId": "copy-source",
        "defaultPrevented": False,
    }.items():
        if copy_event.get(field) != expected_value:
            raise M0Error(f"M4 copy/paste copy event {field} mismatch")
    copy_selection = _require_dict(
        copy_event.get("selection"), "M4 copy/paste copy selection"
    )
    if copy_selection.get("start") != 0 or copy_selection.get("end") != 4:
        raise M0Error("M4 copy/paste copy selection range mismatch")
    if copy_selection.get("text") != "COPY":
        raise M0Error("M4 copy/paste copy selection text mismatch")

    primary_paste_events = page_probe.get("primaryVerifyPasteEventTrace")
    if not isinstance(primary_paste_events, list) or len(
        primary_paste_events
    ) != 1:
        raise M0Error(
            "M4 copy/paste primary verification trace is not exactly one "
            "event"
        )
    primary_paste_event = _require_dict(
        primary_paste_events[0], "M4 copy/paste primary verification event"
    )
    for field, expected_value in {
        "type": "paste",
        "trusted": True,
        "targetId": "primary-verify-target",
        "defaultPrevented": False,
        "text": "DECOY",
    }.items():
        if primary_paste_event.get(field) != expected_value:
            raise M0Error(
                f"M4 copy/paste primary verification {field} mismatch"
            )
    primary_paste_text = page_probe.get("primaryVerifyPasteTextInputTrace")
    if not isinstance(primary_paste_text, list) or len(primary_paste_text) != 2:
        raise M0Error(
            "M4 copy/paste primary verification text trace has wrong length"
        )
    for index, event_type in enumerate(("beforeinput", "input")):
        text_event = _require_dict(
            primary_paste_text[index],
            f"M4 copy/paste primary verification text {index}",
        )
        for field, expected_value in {
            "type": event_type,
            "trusted": True,
            "inputType": "insertFromPaste",
            "data": "DECOY",
            "isComposing": False,
            "targetId": "primary-verify-target",
        }.items():
            if text_event.get(field) != expected_value:
                raise M0Error(
                    "M4 copy/paste primary verification text "
                    f"{index} {field} mismatch"
                )

    paste_events = page_probe.get("pasteEventTrace")
    if not isinstance(paste_events, list) or len(paste_events) != 1:
        raise M0Error("M4 copy/paste paste trace is not exactly one event")
    paste_event = _require_dict(paste_events[0], "M4 copy/paste paste event")
    for field, expected_value in {
        "type": "paste",
        "trusted": True,
        "targetId": "paste-target",
        "defaultPrevented": False,
        "text": "COPY",
    }.items():
        if paste_event.get(field) != expected_value:
            raise M0Error(f"M4 copy/paste paste event {field} mismatch")
    paste_text = page_probe.get("pasteTextInputTrace")
    if not isinstance(paste_text, list) or len(paste_text) != 2:
        raise M0Error("M4 copy/paste paste text trace has wrong length")
    for index, event_type in enumerate(("beforeinput", "input")):
        text_event = _require_dict(
            paste_text[index], f"M4 copy/paste paste text {index}"
        )
        for field, expected_value in {
            "type": event_type,
            "trusted": True,
            "inputType": "insertFromPaste",
            "data": "COPY",
            "isComposing": False,
            "targetId": "paste-target",
        }.items():
            if text_event.get(field) != expected_value:
                raise M0Error(
                    f"M4 copy/paste paste text {index} {field} mismatch"
                )

    def click_trace(x: int, y: int) -> tuple[tuple[str, int, int, int, int], ...]:
        return (
            ("move", x, y, -1, 0),
            ("down", x, y, 0, 1),
            ("up", x, y, 0, 0),
        )

    def middle_click_trace(
        x: int, y: int
    ) -> tuple[tuple[str, int, int, int, int], ...]:
        return (
            ("move", x, y, -1, 0),
            ("down", x, y, 1, 4),
            ("up", x, y, 1, 0),
        )

    def drag_trace(prefix: str) -> tuple[tuple[str, int, int, int, int], ...]:
        return (
            ("move", coordinates[prefix + "StartX"],
             coordinates[prefix + "StartY"], -1, 0),
            ("down", coordinates[prefix + "StartX"],
             coordinates[prefix + "StartY"], 0, 1),
            ("move", coordinates[prefix + "MiddleX"],
             coordinates[prefix + "MiddleY"], -1, 1),
            ("move", coordinates[prefix + "EndX"],
             coordinates[prefix + "EndY"], -1, 1),
            ("up", coordinates[prefix + "EndX"],
             coordinates[prefix + "EndY"], 0, 0),
        )

    expected_pointer_trace = (
        *click_trace(
            coordinates["copySourceTargetX"],
            coordinates["copySourceTargetY"],
        ),
        *drag_trace("copyDrag"),
        *click_trace(
            coordinates["decoyTargetX"], coordinates["decoyTargetY"]
        ),
        *drag_trace("decoyDrag"),
        *click_trace(
            coordinates["pasteTargetX"], coordinates["pasteTargetY"]
        ),
        *middle_click_trace(
            coordinates["primaryVerifyTargetX"],
            coordinates["primaryVerifyTargetY"],
        ),
    )
    pointer_input = _require_dict(
        result.get("pointerInput"), "M4 copy/paste pointer input"
    )
    readiness_pointer = _require_dict(
        readiness.get("pointerInput"), "M4 copy/paste readiness pointer"
    )
    if not _exact_json_value_equal(pointer_input, readiness_pointer):
        raise M0Error(
            "M4 copy/paste pointer evidence differs from readiness evidence"
        )
    if pointer_input.get("enabled") is not True:
        raise M0Error("M4 copy/paste pointer listeners were not enabled")
    queued_pointer = pointer_input.get("queuedRecords")
    if not isinstance(queued_pointer, list) or len(queued_pointer) != len(
        expected_pointer_trace
    ):
        raise M0Error("M4 copy/paste pointer trace has wrong length")
    for field in ("receivedCount", "trustedCount", "queuedCount"):
        if pointer_input.get(field) != len(expected_pointer_trace):
            raise M0Error(f"M4 copy/paste pointer {field} mismatch")
    for index, (event_type, x, y, button, buttons) in enumerate(
        expected_pointer_trace
    ):
        record = _require_dict(
            queued_pointer[index],
            f"M4 copy/paste pointer trace {index}",
        )
        for field, expected_value in {
            "type": event_type,
            "trusted": True,
            "queued": True,
            "button": button,
            "buttons": buttons,
            "sequence": index + 1,
            "x": x,
            "y": y,
            "canvasFocused": True,
        }.items():
            if record.get(field) != expected_value:
                raise M0Error(
                    f"M4 copy/paste pointer trace {index} {field} mismatch"
                )
        _require_safe_integer(
            record.get("frameIdBefore"),
            f"M4 copy/paste pointer trace {index} frame",
            minimum=1,
        )

    expected_key_trace = (
        ("down", "ControlLeft", "Control", True),
        ("down", "KeyC", "c", True),
        ("up", "KeyC", "c", True),
        ("up", "ControlLeft", "Control", False),
        ("down", "ControlLeft", "Control", True),
        ("down", "KeyV", "v", True),
        ("up", "KeyV", "v", True),
        ("up", "ControlLeft", "Control", False),
    )
    keyboard_input = _require_dict(
        result.get("keyboardInput"), "M4 copy/paste keyboard input"
    )
    readiness_keyboard = _require_dict(
        readiness.get("keyboardInput"), "M4 copy/paste readiness keyboard"
    )
    if not _exact_json_value_equal(keyboard_input, readiness_keyboard):
        raise M0Error(
            "M4 copy/paste keyboard evidence differs from readiness evidence"
        )
    if (
        keyboard_input.get("enabled") is not True
        or keyboard_input.get("activated") is not True
        or keyboard_input.get("pressedCodes") != []
    ):
        raise M0Error("M4 copy/paste keyboard state is invalid")
    queued_keys = keyboard_input.get("queuedRecords")
    if not isinstance(queued_keys, list) or len(queued_keys) != len(
        expected_key_trace
    ):
        raise M0Error("M4 copy/paste key trace has wrong length")
    if keyboard_input.get("receivedCount") != len(expected_key_trace) + 2:
        raise M0Error("M4 copy/paste keyboard receivedCount mismatch")
    if keyboard_input.get("trustedCount") != len(expected_key_trace) + 2:
        raise M0Error("M4 copy/paste keyboard trustedCount mismatch")
    if keyboard_input.get("queuedCount") != len(expected_key_trace):
        raise M0Error("M4 copy/paste keyboard queuedCount mismatch")
    rejected_keys = keyboard_input.get("rejectedRecords")
    if not isinstance(rejected_keys, list) or len(rejected_keys) != 2:
        raise M0Error("M4 copy/paste rejected shortcut trace has wrong length")
    for index, (event_type, reason) in enumerate(
        (("down", "UNSUPPORTED_SHORTCUT_STATE"), ("up", "UNMATCHED_UP"))
    ):
        record = _require_dict(
            rejected_keys[index], f"M4 copy/paste rejected shortcut {index}"
        )
        for field, expected_value in {
            "type": event_type,
            "code": "KeyC",
            "key": "c",
            "trusted": True,
            "queued": False,
            "reason": reason,
            "repeat": False,
            "isComposing": False,
            "sequence": index + 1,
            "canvasFocused": True,
            "pointerActivated": True,
        }.items():
            if record.get(field) != expected_value:
                raise M0Error(
                    f"M4 copy/paste rejected shortcut {index} {field} mismatch"
                )
        modifiers = _require_dict(
            record.get("modifiers"),
            f"M4 copy/paste rejected shortcut {index} modifiers",
        )
        if modifiers != {
            "alt": False,
            "control": False,
            "meta": False,
            "shift": False,
        }:
            raise M0Error(
                f"M4 copy/paste rejected shortcut {index} modifiers mismatch"
            )
    paste_key_down_frame_id = 0
    for index, (event_type, code, key, control) in enumerate(
        expected_key_trace
    ):
        record = _require_dict(
            queued_keys[index], f"M4 copy/paste key trace {index}"
        )
        for field, expected_value in {
            "type": event_type,
            "code": code,
            "key": key,
            "trusted": True,
            "queued": True,
            "repeat": False,
            "isComposing": False,
            "sequence": index + 3,
            "canvasFocused": True,
            "pointerActivated": True,
            "defaultPrevented": True,
        }.items():
            if record.get(field) != expected_value:
                raise M0Error(
                    f"M4 copy/paste key trace {index} {field} mismatch"
                )
        modifiers = _require_dict(
            record.get("modifiers"),
            f"M4 copy/paste key trace {index} modifiers",
        )
        if modifiers != {
            "alt": False,
            "control": control,
            "meta": False,
            "shift": False,
        }:
            raise M0Error(
                f"M4 copy/paste key trace {index} modifier mismatch"
            )
        record_frame_id = _require_safe_integer(
            record.get("frameIdBefore"),
            f"M4 copy/paste key trace {index} frame",
            minimum=1,
        )
        if index == 5:
            paste_key_down_frame_id = record_frame_id
    if frame_id <= paste_key_down_frame_id:
        raise M0Error("M4 copy/paste has no compositor frame after Ctrl+V")

    inner_keys = page_probe.get("keyEventTrace")
    if not isinstance(inner_keys, list) or len(inner_keys) != len(
        expected_key_trace
    ):
        raise M0Error("M4 copy/paste inner key trace has wrong length")
    expected_targets = (
        "copy-source",
        "copy-source",
        "copy-source",
        "copy-source",
        "paste-target",
        "paste-target",
        "paste-target",
        "paste-target",
    )
    for index, (event_type, code, key, _) in enumerate(expected_key_trace):
        record = _require_dict(
            inner_keys[index], f"M4 copy/paste inner key trace {index}"
        )
        for field, expected_value in {
            "type": "keydown" if event_type == "down" else "keyup",
            "code": code,
            "key": key,
            "trusted": True,
            "repeat": False,
            "isComposing": False,
            "targetId": expected_targets[index],
            "defaultPrevented": False,
        }.items():
            if record.get(field) != expected_value:
                raise M0Error(
                    f"M4 copy/paste inner key trace {index} {field} mismatch"
                )
        if code in ("KeyC", "KeyV") and record.get("ctrlKey") is not True:
            raise M0Error(
                f"M4 copy/paste inner key trace {index} lost Control"
            )

    shutdown = _require_dict(
        result.get("shutdown"), "M4 copy/paste shutdown"
    )
    for field in ("ok", "accepted", "complete"):
        if shutdown.get(field) is not True:
            raise M0Error(f"M4 copy/paste shutdown {field} is not true")
    for field in ("exitCode", "runtimeExitCode"):
        if shutdown.get(field) != 0:
            raise M0Error(f"M4 copy/paste shutdown {field} is not zero")
    logs = _require_dict(result.get("logs"), "M4 copy/paste logs")
    for stream in ("host", "stdout", "stderr"):
        if not isinstance(logs.get(stream), list):
            raise M0Error(f"M4 copy/paste {stream} log is not an array")
    host_logs = logs["host"]
    if (
        "m4:pointer:listeners-attached" not in host_logs
        or "m4:keyboard:listeners-attached" not in host_logs
        or "m4:keyboard:down:unsupported-shortcut-state" not in host_logs
        or "m4:keyboard:up:unmatched" not in host_logs
        or host_logs.count("m4:keyboard:down:queued") != 4
        or host_logs.count("m4:keyboard:up:queued") != 4
        or host_logs[-1:] != ["shutdown:complete"]
    ):
        raise M0Error("M4 copy/paste host lifecycle logs are invalid")


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
        "fixture": "chromium-wasm-m4-ozone-keyboard-v2",
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
    if _require_safe_integer(
        key_events.get("keydownCount"), "M4 inner keydownCount", minimum=1
    ) != 2:
        raise M0Error("M4 inner keydownCount is not exactly two")
    if _require_safe_integer(
        key_events.get("keyupCount"), "M4 inner keyupCount", minimum=1
    ) != 1:
        raise M0Error("M4 inner keyupCount is not exactly one")
    expected_summary = {
        "keydownTrusted": True,
        "keyupTrusted": True,
        "keydownCode": "ArrowDown",
        "keyupCode": "ArrowDown",
        "keydownKey": "ArrowDown",
        "keyupKey": "ArrowDown",
        "keydownRepeat": True,
        "keyupRepeat": False,
        "keydownComposing": False,
        "keyupComposing": False,
        "keydownDefaultPrevented": False,
        "keyupDefaultPrevented": False,
        "keydownTargetId": "keyboard-target",
        "keyupTargetId": "keyboard-target",
    }
    for field, expected_value in expected_summary.items():
        actual_value = key_events.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 inner {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )
    inner_trace = key_events.get("trace")
    expected_inner_trace = (
        ("keydown", False),
        ("keydown", True),
        ("keyup", False),
    )
    if not isinstance(inner_trace, list) or len(inner_trace) != len(
        expected_inner_trace
    ):
        raise M0Error("M4 inner key trace does not contain down/repeat/up")
    for index, (event_type, repeat) in enumerate(expected_inner_trace):
        record = _require_dict(
            inner_trace[index], f"M4 inner key trace {index}"
        )
        expected_record = {
            "type": event_type,
            "trusted": True,
            "code": "ArrowDown",
            "key": "ArrowDown",
            "repeat": repeat,
            "isComposing": False,
            "defaultPrevented": False,
            "targetId": "keyboard-target",
        }
        for field, expected_value in expected_record.items():
            if record.get(field) != expected_value:
                raise M0Error(
                    f"M4 inner key trace {index} {field} mismatch: expected "
                    f"{expected_value!r}, got {record.get(field)!r}"
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
        minimum=3,
    )
    keyboard_trusted = _require_safe_integer(
        keyboard_input.get("trustedCount"),
        "M4 trusted DOM keyboard count",
        minimum=3,
    )
    keyboard_queued = _require_safe_integer(
        keyboard_input.get("queuedCount"),
        "M4 queued host keyboard count",
        minimum=3,
    )
    if (
        keyboard_trusted > keyboard_received
        or keyboard_queued > keyboard_received
    ):
        raise M0Error(
            "M4 keyboard count exceeds received keyboard records"
        )

    def require_key_record(
        value: object,
        description: str,
        expected_type: str,
        expected_repeat: bool,
    ) -> int:
        record = _require_dict(value, description)
        expected_record = {
            "type": expected_type,
            "code": "ArrowDown",
            "key": "ArrowDown",
            "trusted": True,
            "queued": True,
            "repeat": expected_repeat,
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

    queued_records = keyboard_input.get("queuedRecords")
    expected_queued_trace = (
        ("down", False),
        ("down", True),
        ("up", False),
    )
    if not isinstance(queued_records, list) or len(queued_records) != len(
        expected_queued_trace
    ):
        raise M0Error("M4 keyboard trace does not contain down/repeat/up")
    queued_frame_ids = []
    for index, (event_type, repeat) in enumerate(expected_queued_trace):
        record = _require_dict(
            queued_records[index], f"M4 queued key trace {index}"
        )
        queued_frame_ids.append(
            require_key_record(
                record,
                f"M4 queued key trace {index}",
                event_type,
                repeat,
            )
        )
        if _require_safe_integer(
            record.get("sequence"),
            f"M4 queued key trace {index} sequence",
            minimum=1,
        ) != index + 1:
            raise M0Error("M4 keyboard trace sequence is not contiguous")
    key_down_frame_id = require_key_record(
        keyboard_input.get("lastQueuedDown"),
        "M4 last queued key down",
        "down",
        True,
    )
    require_key_record(
        keyboard_input.get("lastQueuedUp"),
        "M4 last queued key up",
        "up",
        False,
    )
    if key_down_frame_id != queued_frame_ids[1]:
        raise M0Error("M4 keyboard repeat frame does not match queued trace")
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
        "m4:keyboard:repeat:queued",
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
    """Validate trusted US KeyA then KeyB through Ozone, Aura, and Blink."""

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
        "fixture": "chromium-wasm-m4-ozone-printable-key-v2",
        "ready": True,
        "activeElementId": "editable-target",
        "activationCount": 1,
        "clickTrusted": True,
        "focusTrusted": True,
        "value": "ab",
        "selectionStart": 2,
        "selectionEnd": 2,
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
    key_a_proof = _require_dict(
        result.get("keyAProof"), "M4 printable-key KeyA-stage proof"
    )
    expected_key_a_proof = {
        "outerTraceExact": True,
        "innerTraceExact": True,
        "textTraceExact": True,
        "noComposition": True,
        "value": "a",
        "selectionStart": 1,
        "selectionEnd": 1,
        "frameAfterKeyADown": True,
    }
    for field, expected_value in expected_key_a_proof.items():
        actual_value = key_a_proof.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 printable-key KeyA-stage proof {field} mismatch: expected "
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
            key_events.get(field), f"M4 printable-key inner {field}", minimum=2
        ) != 2:
            raise M0Error(f"M4 printable-key inner {field} is not exactly two")

    expected_key_trace = [
        {
            "type": event_type,
            "trusted": True,
            "code": code,
            "key": key,
            "repeat": False,
            "isComposing": False,
            "defaultPrevented": False,
            "targetId": "editable-target",
        }
        for event_type, code, key in (
            ("keydown", "KeyA", "a"),
            ("keyup", "KeyA", "a"),
            ("keydown", "KeyB", "b"),
            ("keyup", "KeyB", "b"),
        )
    ]
    key_trace = page_probe.get("keyEventTrace")
    if key_trace != expected_key_trace:
        raise M0Error(
            "M4 printable-key inner keyEventTrace is not the exact "
            "trusted KeyA-down/up then KeyB-down/up sequence"
        )

    text_input_events = _require_dict(
        page_probe.get("textInputEvents"),
        "M4 printable-key text input events",
    )
    expected_text_counts = {
        "beforeinputCount": 2,
        "inputCount": 2,
        "compositionstartCount": 0,
        "compositionupdateCount": 0,
        "compositionendCount": 0,
    }
    for field, expected_value in expected_text_counts.items():
        actual_value = text_input_events.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 printable-key {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )
    expected_text_trace = [
        {
            "type": event_type,
            "trusted": True,
            "inputType": "insertText",
            "data": data,
            "isComposing": False,
            "targetId": "editable-target",
        }
        for event_type, data in (
            ("beforeinput", "a"),
            ("input", "a"),
            ("beforeinput", "b"),
            ("input", "b"),
        )
    ]
    text_trace = page_probe.get("textInputTrace")
    if text_trace != expected_text_trace:
        raise M0Error(
            "M4 printable-key inner textInputTrace is not the exact "
            "two trusted insertText pairs for a then b"
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
            minimum=4,
        )
        if count != 4:
            raise M0Error(
                f"M4 printable-key keyboard {field} is not exactly four"
            )

    def require_key_record(
        value: object,
        description: str,
        expected_type: str,
        expected_code: str,
        expected_key: str,
    ) -> int:
        record = _require_dict(value, description)
        expected_record = {
            "type": expected_type,
            "code": expected_code,
            "key": expected_key,
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

    queued_records = keyboard_input.get("queuedRecords")
    if not isinstance(queued_records, list) or len(queued_records) != 4:
        raise M0Error(
            "M4 printable-key queued records are not exactly the four "
            "trusted raw key transitions"
        )
    expected_outer_trace = (
        ("down", "KeyA", "a"),
        ("up", "KeyA", "a"),
        ("down", "KeyB", "b"),
        ("up", "KeyB", "b"),
    )
    queued_frame_ids = []
    for index, (event_type, code, key) in enumerate(expected_outer_trace):
        queued_frame_ids.append(
            require_key_record(
                queued_records[index],
                f"M4 printable-key queued record {index}",
                event_type,
                code,
                key,
            )
        )
    last_down = _require_dict(
        keyboard_input.get("lastQueuedDown"),
        "M4 printable-key last queued key down",
    )
    last_up = _require_dict(
        keyboard_input.get("lastQueuedUp"),
        "M4 printable-key last queued key up",
    )
    if last_down != queued_records[2] or last_up != queued_records[3]:
        raise M0Error(
            "M4 printable-key last queued records do not identify KeyB"
        )
    if frame_id <= queued_frame_ids[2]:
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
    for marker in ("m4:keyboard:down:queued", "m4:keyboard:up:queued"):
        if sum(marker in line for line in host_logs) != 2:
            raise M0Error(
                "M4 printable-key logs do not contain exactly two "
                f"{marker!r} records"
            )


def validate_m4_backspace_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
) -> None:
    """Validate KeyA/KeyB insertion then one physical Backspace repeat.

    The outer driver may queue only raw physical-key records. The exact
    trusted Blink trace below proves that normal text editing, rather than a
    DevTools text command or the composition bridge, inserted and then
    deleted both characters.
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
        "fixture": "chromium-wasm-m4-ozone-backspace-v2",
        "ready": True,
        "activeElementId": "editable-target",
        "activationCount": 1,
        "clickTrusted": True,
        "focusTrusted": True,
        "value": "",
        "selectionStart": 0,
        "selectionEnd": 0,
        "resultText": "TEXT INSERTED THEN REPEATEDLY DELETED",
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

    def require_stage_proof(
        field_name: str, expected_proof: dict[str, object]
    ) -> None:
        proof = _require_dict(
            result.get(field_name), f"M4 backspace {field_name}"
        )
        for proof_field, expected_value in expected_proof.items():
            actual_value = proof.get(proof_field)
            if (
                type(actual_value) is not type(expected_value)
                or actual_value != expected_value
            ):
                raise M0Error(
                    f"M4 backspace {field_name} {proof_field} mismatch: "
                    f"expected {expected_value!r}, got {actual_value!r}"
                )

    require_stage_proof(
        "keyAProof",
        {
            "outerTraceExact": True,
            "innerTraceExact": True,
            "textTraceExact": True,
            "noComposition": True,
            "value": "a",
            "selectionStart": 1,
            "selectionEnd": 1,
            "frameAfterKeyADown": True,
        },
    )
    require_stage_proof(
        "keyBProof",
        {
            "outerTraceExact": True,
            "innerTraceExact": True,
            "textTraceExact": True,
            "noComposition": True,
            "value": "ab",
            "selectionStart": 2,
            "selectionEnd": 2,
            "frameAfterKeyBDown": True,
        },
    )
    require_stage_proof(
        "backspaceRepeatProof",
        {
            "outerTraceExact": True,
            "innerTraceExact": True,
            "textTraceExact": True,
            "noComposition": True,
            "repeatExact": True,
            "initialDownRepeatFalse": True,
            "repeatedDownRepeatTrue": True,
            "releaseRepeatFalse": True,
            "backspaceHeld": True,
            "releaseExact": True,
            "value": "",
            "selectionStart": 0,
            "selectionEnd": 0,
            "frameAfterRepeatDown": True,
        },
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
    if not isinstance(key_event_trace, list) or len(key_event_trace) != 7:
        raise M0Error("M4 backspace inner key trace is not exactly seven events")
    expected_key_trace = (
        ("keydown", "KeyA", "a", False),
        ("keyup", "KeyA", "a", False),
        ("keydown", "KeyB", "b", False),
        ("keyup", "KeyB", "b", False),
        ("keydown", "Backspace", "Backspace", False),
        ("keydown", "Backspace", "Backspace", True),
        ("keyup", "Backspace", "Backspace", False),
    )
    for index, (event_type, code, key, repeat) in enumerate(expected_key_trace):
        record = _require_dict(
            key_event_trace[index], f"M4 backspace inner key trace {index}"
        )
        expected_record = {
            "type": event_type,
            "trusted": True,
            "code": code,
            "key": key,
            "repeat": repeat,
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
    if not isinstance(text_input_trace, list) or len(text_input_trace) != 8:
        raise M0Error("M4 backspace text trace is not exactly eight events")
    expected_text_trace = (
        ("beforeinput", "insertText", "a"),
        ("input", "insertText", "a"),
        ("beforeinput", "insertText", "b"),
        ("input", "insertText", "b"),
        ("beforeinput", "deleteContentBackward", None),
        ("input", "deleteContentBackward", None),
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
            minimum=7,
        )
        if count != 7:
            raise M0Error(
                f"M4 backspace keyboard {field} is not exactly seven"
            )

    queued_records = keyboard_input.get("queuedRecords")
    if not isinstance(queued_records, list) or len(queued_records) != 7:
        raise M0Error("M4 backspace queued key trace is not exactly seven records")
    expected_queue = (
        ("down", "KeyA", "a", False),
        ("up", "KeyA", "a", False),
        ("down", "KeyB", "b", False),
        ("up", "KeyB", "b", False),
        ("down", "Backspace", "Backspace", False),
        ("down", "Backspace", "Backspace", True),
        ("up", "Backspace", "Backspace", False),
    )
    previous_sequence = 0
    backspace_repeat_frame_id = 0
    for index, (event_type, code, key, repeat) in enumerate(expected_queue):
        record = _require_dict(
            queued_records[index], f"M4 backspace queued key trace {index}"
        )
        expected_record = {
            "type": event_type,
            "code": code,
            "key": key,
            "trusted": True,
            "queued": True,
            "repeat": repeat,
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
        if index == 5:
            backspace_repeat_frame_id = record_frame_id

    if keyboard_input.get("lastQueuedDown") != queued_records[5]:
        raise M0Error("M4 backspace last queued key down is not the repeat")
    if keyboard_input.get("lastQueuedUp") != queued_records[6]:
        raise M0Error("M4 backspace last queued key up is not Backspace")
    if frame_id <= backspace_repeat_frame_id:
        raise M0Error(
            "M4 backspace result has no compositor frame after Backspace repeat"
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
        "m4:keyboard:repeat:queued",
        "m4:keyboard:up:queued",
        "shutdown:complete",
    ):
        if not any(marker in line for line in host_logs):
            raise M0Error(
                "M4 backspace logs are missing lifecycle marker "
                f"{marker!r}"
            )
    for marker, expected_count in (
        ("m4:keyboard:down:queued", 3),
        ("m4:keyboard:repeat:queued", 1),
        ("m4:keyboard:up:queued", 3),
    ):
        if sum(marker in line for line in host_logs) != expected_count:
            raise M0Error(
                "M4 backspace logs do not contain exactly "
                f"{expected_count} {marker!r} records"
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


def validate_m4_focus_retention_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
) -> None:
    """Validate native Blink focus survives an unpressed canvas pointer move."""

    expected = {
        "protocol": M3_PROTOCOL,
        "case": M4_FOCUS_RETENTION_CASE,
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
                f"M4 focus-retention result {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )

    versions = _require_dict(
        result.get("versions"), "M4 focus-retention versions"
    )
    if versions != expected_versions:
        raise M0Error(
            "M4 focus-retention version display mismatch: expected "
            f"{expected_versions!r}, got {versions!r}"
        )

    readiness = _require_dict(
        result.get("readiness"), "M4 focus-retention readiness"
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
                f"M4 focus-retention readiness field {field} is not true"
            )
    if readiness.get("fatalErrors") != []:
        raise M0Error("M4 focus-retention readiness reported fatal errors")
    heartbeat = _require_dict(
        readiness.get("heartbeat"), "M4 focus-retention heartbeat"
    )
    if heartbeat.get("anchor") != "data-navigation-committed":
        raise M0Error(
            "M4 focus-retention heartbeat was not anchored to data navigation"
        )
    _require_number(
        heartbeat.get("elapsedMs"),
        "M4 focus-retention heartbeat elapsed time",
        minimum=0,
    )
    frame = _require_dict(
        readiness.get("frame"), "M4 focus-retention frame"
    )
    frame_id = _require_safe_integer(
        frame.get("id"), "M4 focus-retention frame ID", minimum=1
    )
    _require_number(
        frame.get("timestampMs"),
        "M4 focus-retention frame timestamp",
        minimum=0,
    )
    if frame.get("width") != M3_WIDTH or frame.get("height") != M3_HEIGHT:
        raise M0Error(
            "M4 focus-retention frame dimensions do not match the canvas"
        )

    page_probe = _require_dict(
        readiness.get("pageProbe"), "M4 focus-retention page probe"
    )
    expected_probe = {
        "fontReady": True,
        "protocol": M3_PROTOCOL,
        "fixture": "chromium-wasm-m4-ozone-focus-retention-v1",
        "ready": True,
        "activeElementId": "editable-target",
        "documentHasFocus": True,
    }
    for field, expected_value in expected_probe.items():
        actual_value = page_probe.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 focus-retention page probe {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )
    _require_safe_integer(
        page_probe.get("timerTicks"),
        "M4 focus-retention inner page timer ticks",
        minimum=3,
    )
    editable_x = _require_safe_integer(
        page_probe.get("editableTargetX"),
        "M4 focus-retention editable target x",
        minimum=0,
        maximum=M3_WIDTH - 1,
    )
    editable_y = _require_safe_integer(
        page_probe.get("editableTargetY"),
        "M4 focus-retention editable target y",
        minimum=0,
        maximum=M3_HEIGHT - 1,
    )
    retention_x = _require_safe_integer(
        page_probe.get("retentionTargetX"),
        "M4 focus-retention inert target x",
        minimum=0,
        maximum=M3_WIDTH - 1,
    )
    retention_y = _require_safe_integer(
        page_probe.get("retentionTargetY"),
        "M4 focus-retention inert target y",
        minimum=0,
        maximum=M3_HEIGHT - 1,
    )
    if (editable_x, editable_y) == (retention_x, retention_y):
        raise M0Error("M4 focus-retention targets overlap")
    for result_field, expected_value in (
        ("editableTargetX", editable_x),
        ("editableTargetY", editable_y),
        ("retentionTargetX", retention_x),
        ("retentionTargetY", retention_y),
    ):
        if result.get(result_field) != expected_value:
            raise M0Error(
                f"M4 focus-retention result {result_field} differs from "
                "the native fixture probe"
            )

    retention = _require_dict(
        page_probe.get("focusRetention"), "M4 focus-retention native trace"
    )
    expected_retention = {
        "editableActivationCount": 1,
        "editableClickTrusted": True,
        "editableFocusCount": 1,
        "editableFocusTrusted": True,
        "editableBlurCount": 0,
        "windowBlurCount": 0,
        "windowBlurTrusted": False,
        "retentionPointerMoveCount": 1,
        "retentionPointerMoveTrusted": True,
        "value": "a",
        "selectionStart": 1,
        "selectionEnd": 1,
        "resultText": "FOCUS RETAINED",
    }
    for field, expected_value in expected_retention.items():
        actual_value = retention.get(field)
        if (
            type(actual_value) is not type(expected_value)
            or actual_value != expected_value
        ):
            raise M0Error(
                f"M4 focus-retention native trace {field} mismatch: expected "
                f"{expected_value!r}, got {actual_value!r}"
            )
    expected_key_trace = [
        {
            "type": event_type,
            "trusted": True,
            "code": "KeyA",
            "key": "a",
            "repeat": False,
            "isComposing": False,
            "defaultPrevented": False,
            "targetId": "editable-target",
        }
        for event_type in ("keydown", "keyup")
    ]
    if retention.get("keyEventTrace") != expected_key_trace:
        raise M0Error(
            "M4 focus-retention native key trace is not the exact trusted "
            "KeyA down/up pair"
        )
    expected_text_trace = [
        {
            "type": event_type,
            "trusted": True,
            "inputType": "insertText",
            "data": "a",
            "isComposing": False,
            "targetId": "editable-target",
        }
        for event_type in ("beforeinput", "input")
    ]
    if retention.get("textInputTrace") != expected_text_trace:
        raise M0Error(
            "M4 focus-retention native text trace is not the exact trusted "
            "insertText a pair"
        )
    if retention.get("compositionEventCounts") != {
        "compositionstart": 0,
        "compositionupdate": 0,
        "compositionend": 0,
    }:
        raise M0Error("M4 focus-retention unexpectedly entered composition")

    pointer_input = _require_dict(
        result.get("pointerInput"), "M4 focus-retention pointer input"
    )
    readiness_pointer = _require_dict(
        readiness.get("pointerInput"),
        "M4 focus-retention readiness pointer input",
    )
    if pointer_input != readiness_pointer:
        raise M0Error(
            "M4 focus-retention pointer evidence differs from readiness evidence"
        )
    if pointer_input.get("enabled") is not True:
        raise M0Error("M4 focus-retention pointer listeners were not enabled")
    for field in ("receivedCount", "trustedCount", "queuedCount"):
        if _require_safe_integer(
            pointer_input.get(field),
            f"M4 focus-retention pointer {field}",
            minimum=4,
        ) != 4:
            raise M0Error(
                f"M4 focus-retention pointer {field} is not exactly four"
            )
    queued_pointer = pointer_input.get("queuedRecords")
    if not isinstance(queued_pointer, list) or len(queued_pointer) != 4:
        raise M0Error(
            "M4 focus-retention did not retain the four physical pointer records"
        )
    expected_pointer_trace = (
        ("move", editable_x, editable_y, -1, 0),
        ("down", editable_x, editable_y, 0, 1),
        ("up", editable_x, editable_y, 0, 0),
        ("move", retention_x, retention_y, -1, 0),
    )
    for index, (event_type, x, y, button, buttons) in enumerate(
        expected_pointer_trace
    ):
        record = _require_dict(
            queued_pointer[index],
            f"M4 focus-retention pointer record {index}",
        )
        for field, expected_value in {
            "sequence": index + 1,
            "type": event_type,
            "trusted": True,
            "queued": True,
            "canvasFocused": True,
            "x": x,
            "y": y,
            "button": button,
            "buttons": buttons,
        }.items():
            if record.get(field) != expected_value:
                raise M0Error(
                    f"M4 focus-retention pointer record {index} {field} "
                    f"mismatch: expected {expected_value!r}, got "
                    f"{record.get(field)!r}"
                )
        _require_safe_integer(
            record.get("frameIdBefore"),
            f"M4 focus-retention pointer record {index} frame ID",
            minimum=1,
        )
    if pointer_input.get("lastQueued") != queued_pointer[-1]:
        raise M0Error(
            "M4 focus-retention last queued pointer is not the inert move"
        )

    keyboard_input = _require_dict(
        result.get("keyboardInput"), "M4 focus-retention keyboard input"
    )
    readiness_keyboard = _require_dict(
        readiness.get("keyboardInput"),
        "M4 focus-retention readiness keyboard input",
    )
    if keyboard_input != readiness_keyboard:
        raise M0Error(
            "M4 focus-retention keyboard evidence differs from readiness evidence"
        )
    if keyboard_input.get("enabled") is not True:
        raise M0Error("M4 focus-retention keyboard listeners were not enabled")
    if keyboard_input.get("activated") is not True:
        raise M0Error("M4 focus-retention keyboard was not pointer activated")
    if keyboard_input.get("pressedCodes") != []:
        raise M0Error("M4 focus-retention KeyA was not released")
    for field in ("receivedCount", "trustedCount", "queuedCount"):
        if _require_safe_integer(
            keyboard_input.get(field),
            f"M4 focus-retention keyboard {field}",
            minimum=2,
        ) != 2:
            raise M0Error(
                f"M4 focus-retention keyboard {field} is not exactly two"
            )
    queued_keys = keyboard_input.get("queuedRecords")
    if not isinstance(queued_keys, list) or len(queued_keys) != 2:
        raise M0Error(
            "M4 focus-retention did not retain the two raw KeyA records"
        )
    key_frame_ids: list[int] = []
    for index, event_type in enumerate(("down", "up")):
        record = _require_dict(
            queued_keys[index],
            f"M4 focus-retention queued KeyA record {index}",
        )
        for field, expected_value in {
            "type": event_type,
            "code": "KeyA",
            "key": "a",
            "trusted": True,
            "queued": True,
            "repeat": False,
            "isComposing": False,
            "canvasFocused": True,
            "pointerActivated": True,
            "defaultPrevented": True,
        }.items():
            if record.get(field) != expected_value:
                raise M0Error(
                    f"M4 focus-retention KeyA record {index} {field} mismatch: "
                    f"expected {expected_value!r}, got {record.get(field)!r}"
                )
        if record.get("modifiers") != {
            "alt": False,
            "control": False,
            "meta": False,
            "shift": False,
        }:
            raise M0Error(
                f"M4 focus-retention KeyA record {index} has modifiers"
            )
        key_frame_ids.append(
            _require_safe_integer(
                record.get("frameIdBefore"),
                f"M4 focus-retention KeyA record {index} frame ID",
                minimum=1,
            )
        )
    if (
        keyboard_input.get("lastQueuedDown") != queued_keys[0]
        or keyboard_input.get("lastQueuedUp") != queued_keys[1]
    ):
        raise M0Error(
            "M4 focus-retention last queued keyboard records do not identify KeyA"
        )
    if frame_id <= key_frame_ids[0]:
        raise M0Error(
            "M4 focus-retention result has no compositor frame after KeyA"
        )

    focus_input = _require_dict(
        result.get("focusInput"), "M4 focus-retention focus input"
    )
    readiness_focus = _require_dict(
        readiness.get("focusInput"),
        "M4 focus-retention readiness focus input",
    )
    if focus_input != readiness_focus:
        raise M0Error(
            "M4 focus-retention focus evidence differs from readiness evidence"
        )
    expected_focus = {
        "enabled": True,
        "hostWindowActive": True,
        "receivedCount": 1,
        "trustedCount": 1,
        "queuedCount": 1,
        "lastQueuedFocusLoss": None,
    }
    for field, expected_value in expected_focus.items():
        if focus_input.get(field) != expected_value:
            raise M0Error(
                f"M4 focus-retention focus {field} mismatch: expected "
                f"{expected_value!r}, got {focus_input.get(field)!r}"
            )

    ozone_focus = _require_dict(
        result.get("ozoneFocusState"), "M4 focus-retention Ozone focus state"
    )
    readiness_ozone_focus = _require_dict(
        readiness.get("ozoneFocusState"),
        "M4 focus-retention readiness Ozone focus state",
    )
    if ozone_focus != readiness_ozone_focus:
        raise M0Error(
            "M4 focus-retention Ozone state differs from readiness evidence"
        )
    if (
        ozone_focus.get("keyboardTargetPresent") is not True
        or ozone_focus.get("active") is not True
    ):
        raise M0Error(
            "M4 focus-retention native interaction did not retain Ozone focus"
        )
    focus_sequence = _require_safe_integer(
        ozone_focus.get("sequence"),
        "M4 focus-retention Ozone focus sequence",
        minimum=1,
    )
    sequence_before = _require_safe_integer(
        result.get("retentionFocusSequenceBefore"),
        "M4 focus-retention Ozone sequence before inert pointer move",
        minimum=1,
    )
    sequence_after = _require_safe_integer(
        result.get("retentionFocusSequenceAfter"),
        "M4 focus-retention Ozone sequence after inert pointer move",
        minimum=1,
    )
    if sequence_after != sequence_before:
        raise M0Error(
            "M4 focus-retention pointer move unexpectedly changed the Ozone "
            "focus sequence"
        )
    if focus_sequence != sequence_before:
        raise M0Error(
            "M4 focus-retention final Ozone state does not match the "
            "pre-move sequence"
        )
    readiness_reports = readiness.get("ozoneFocusReports")
    if not isinstance(readiness_reports, list):
        raise M0Error("M4 focus-retention Ozone report history is not an array")
    if not readiness_reports or readiness_reports[-1] != ozone_focus:
        raise M0Error(
            "M4 focus-retention final Ozone state is not the final report"
        )
    reports_after = []
    previous_report_sequence = 0
    for index, report_value in enumerate(readiness_reports):
        report = _require_dict(
            report_value, f"M4 focus-retention Ozone report {index}"
        )
        sequence = _require_safe_integer(
            report.get("sequence"),
            f"M4 focus-retention Ozone report {index} sequence",
            minimum=1,
        )
        if sequence <= previous_report_sequence:
            raise M0Error(
                "M4 focus-retention Ozone report history is not strictly "
                "increasing"
            )
        previous_report_sequence = sequence
        if sequence > sequence_before:
            reports_after.append(report)
    if reports_after:
        raise M0Error(
            "M4 focus-retention pointer move unexpectedly reported a new "
            "Ozone focus state"
        )
    result_reports = result.get("retentionOzoneFocusReports")
    if result_reports != [] or result_reports != reports_after:
        raise M0Error(
            "M4 focus-retention result Ozone history differs from readiness "
            "evidence"
        )

    proof = _require_dict(
        result.get("focusRetentionProof"), "M4 focus-retention proof"
    )
    for field in (
        "pointerTraceExact",
        "nativeFocusStateStable",
        "blinkFocusRetained",
        "keyOuterTraceExact",
        "keyInnerTraceExact",
        "textTraceExact",
        "noComposition",
        "frameAfterKeyDown",
    ):
        if proof.get(field) is not True:
            raise M0Error(f"M4 focus-retention proof {field} is not true")

    shutdown = _require_dict(
        result.get("shutdown"), "M4 focus-retention shutdown"
    )
    for field in ("ok", "accepted", "complete"):
        if shutdown.get(field) is not True:
            raise M0Error(
                f"M4 focus-retention shutdown {field} is not true"
            )
    for field in ("exitCode", "runtimeExitCode"):
        if _require_safe_integer(
            shutdown.get(field), f"M4 focus-retention shutdown {field}"
        ) != 0:
            raise M0Error(
                f"M4 focus-retention shutdown {field} is not zero"
            )

    logs = _require_dict(result.get("logs"), "M4 focus-retention logs")
    for stream in ("host", "stdout", "stderr"):
        if not isinstance(logs.get(stream), list):
            raise M0Error(
                f"M4 focus-retention {stream} log must be an array"
            )
    combined_logs = "\n".join(
        str(line)
        for stream in ("host", "stdout", "stderr")
        for line in logs[stream]
    )
    if "abort:" in combined_logs.lower():
        raise M0Error("M4 focus-retention logs contain a Wasm abort")
    host_logs = [str(line) for line in logs["host"]]
    for marker in (
        "m4:pointer:listeners-attached",
        "m4:keyboard:listeners-attached",
        "m4:focus:listeners-attached",
        "m4:pointer:move:queued",
        "m4:pointer:down:queued",
        "m4:pointer:up:queued",
        "m4:keyboard:pointer-activation",
        "m4:focus:pointer-activation",
        "m4:keyboard:down:queued",
        "m4:keyboard:up:queued",
        "m4:focus:shutdown:deactivate-queued",
        "shutdown:complete",
    ):
        if not any(marker in line for line in host_logs):
            raise M0Error(
                "M4 focus-retention logs are missing lifecycle marker "
                f"{marker!r}"
            )
    if sum("m4:focus:pointer-activation" in line for line in host_logs) != 1:
        raise M0Error(
            "M4 focus-retention logs do not contain exactly one pointer "
            "activation"
        )
    for unexpected_reason in (
        "canvas-blur",
        "window-blur",
        "visibility-loss",
        "ime-proxy-blur",
    ):
        if any(
            f"m4:focus:{unexpected_reason}:deactivate-queued" in line
            for line in host_logs
        ):
            raise M0Error(
                "M4 focus-retention unexpectedly deactivated Ozone for "
                f"{unexpected_reason}"
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
