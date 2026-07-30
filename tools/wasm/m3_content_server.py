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
            or result.get("case") != M3_CASE
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
