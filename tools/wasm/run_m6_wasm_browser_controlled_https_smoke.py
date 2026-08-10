#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run Chrome's controlled HTTPS UI smoke over the local M5 WISP relay.

This harness serves the dedicated test-only Chrome executable from a
cross-origin-isolated page.  The host configures the WISP bridge before the
Emscripten factory starts, while the C++ smoke performs the only controlled
HTTPS navigation through its real Views address field.
"""

from __future__ import annotations

import argparse
import base64
import binascii
from collections import deque
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import ipaddress
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
from typing import Any, TextIO
from urllib.parse import urlencode, urlsplit

import check_m6_chrome_boundary
from check_m6_chrome_boundary import check_boundary
from m0_common import (
    M0Error,
    REPO_ROOT,
    checked_output,
    load_manifest,
    parse_timeout,
    print_context,
)
from run_browser_smoke import (
    browser_command,
    drain_stream,
    find_browser,
    stop_browser,
)
from run_content_shell_smoke import manifest_versions
from m3_content_server import compare_screenshots, decode_png
from run_m5_wisp_smoke import (
    find_node,
    m5_host_origin,
    relay_command,
    validate_m5_https_url,
    validate_relay_transcript_url,
    validate_wisp_endpoint,
    verify_no_private_key_pem_artifacts,
)
import run_wasm_browser_view_smoke as browser_view_smoke


SENTINEL = "CHROMIUM_WASM_M6_CONTROLLED_HTTPS"
CASE = "browser_controlled_https_m6"
SCOPE = "chrome-views-wisp-controlled-https"
SMOKE_SWITCH = "--wasm-browser-controlled-https-smoke"
URL_SWITCH = "--wasm-browser-controlled-https-url"
READY_MARKER = "CHROMIUM_WASM_M6_CONTROLLED_HTTPS:READY"
NAVIGATED_MARKER = "CHROMIUM_WASM_M6_CONTROLLED_HTTPS:NAVIGATED"
PASS_MARKER = "CHROMIUM_WASM_M6_CONTROLLED_HTTPS:PASS"
M6_UI_PATH = "/m5/m6-ui"
GATEWAY_FIXTURE_URL = "https://a.test/m5/m6-ui"
GATEWAY_LOGICAL_PORT = 443
RELAY_FIXTURE = "chromium-wasm-m5-network-v1"
DEFAULT_OUT_DIR = Path("out/wasm-chrome-m6")
DEFAULT_MODULE_NAME = "chrome_wasm_m6_https_test"
CONTROLLED_HTTPS_GN_TARGET = "//chrome:chrome_wasm_m6_https_test"
HOST_ROOT = "/__m6_browser_controlled_https__"
MAX_RESULT_BYTES = 8 * 1024 * 1024
MAX_SCREENSHOT_PNG_BYTES = 4 * 1024 * 1024
MAX_SCREENSHOT_BASE64_LENGTH = ((MAX_SCREENSHOT_PNG_BYTES + 2) // 3) * 4
CONTROLLED_HTTPS_SCREENSHOT_CONTRACT = (
    Path(__file__).with_name("testdata")
    / "m6_controlled_https_screenshot_contract.json"
)
MAX_RELAY_READY_LINE_BYTES = 16 * 1024
MAX_RELAY_STATUS_BYTES = 256 * 1024
MAX_RELAY_TRANSCRIPT_ENTRIES = 256
MAX_RELAY_COUNTER = 16
MAX_RELAY_TRANSCRIPT_EVENT_LENGTH = 96
RELAY_TRANSCRIPT_EVENT_RE = re.compile(r"^[a-z0-9:/._-]{1,96}$", re.IGNORECASE)
MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


@dataclass(frozen=True)
class RelayReady:
    """The minimal, validated M5 fixture information this M6 lane needs."""

    wisp_endpoint: str
    m6_ui_url: str
    transcript_url: str


def _require_screenshot_contract_string(
    contract: dict[str, Any], field: str
) -> str:
    value = contract.get(field)
    if not isinstance(value, str) or not value:
        raise M0Error(f"controlled-HTTPS screenshot contract {field} is invalid")
    return value


def load_controlled_https_screenshot_contract(
    path: Path = CONTROLLED_HTTPS_SCREENSHOT_CONTRACT,
) -> dict[str, Any]:
    """Load the narrow, unmasked visual comparison policy for this lane."""

    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise M0Error(
            f"cannot read controlled-HTTPS screenshot contract: {exc}"
        ) from exc
    expected_fields = {
        "schema_version",
        "fixture",
        "gateway_url",
        "baseline",
        "baseline_policy",
        "visual_strategy",
        "width",
        "height",
        "channel_tolerance",
        "maximum_different_pixel_ratio",
        "comparison",
    }
    if not isinstance(contract, dict) or set(contract) != expected_fields:
        raise M0Error("controlled-HTTPS screenshot contract shape is unsupported")
    if contract.get("schema_version") != 1:
        raise M0Error("controlled-HTTPS screenshot contract schema is unsupported")
    if contract.get("fixture") != "chromium-wasm-m6-controlled-https-v1":
        raise M0Error("controlled-HTTPS screenshot fixture is unsupported")
    if contract.get("gateway_url") != GATEWAY_FIXTURE_URL:
        raise M0Error("controlled-HTTPS screenshot gateway URL is unsupported")
    baseline = _require_screenshot_contract_string(contract, "baseline")
    baseline_path = Path(baseline)
    if baseline_path.name != baseline or baseline_path.suffix != ".png":
        raise M0Error("controlled-HTTPS screenshot baseline name is invalid")
    for field in ("baseline_policy", "visual_strategy", "comparison"):
        _require_screenshot_contract_string(contract, field)
    if (
        type(contract.get("width")) is not int
        or contract["width"] != 640
        or type(contract.get("height")) is not int
        or contract["height"] != 480
    ):
        raise M0Error("controlled-HTTPS screenshot dimensions are unsupported")
    tolerance = contract.get("channel_tolerance")
    if type(tolerance) is not int or not 0 <= tolerance <= 255:
        raise M0Error("controlled-HTTPS screenshot channel tolerance is invalid")
    ratio = contract.get("maximum_different_pixel_ratio")
    if (
        type(ratio) not in (int, float)
        or isinstance(ratio, bool)
        or not 0 <= float(ratio) <= 1
    ):
        raise M0Error(
            "controlled-HTTPS maximum different-pixel ratio is invalid"
        )
    return contract


class ControlledHttpsSmokeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    result_queue: queue.Queue[dict[str, Any]]
    result_token: str
    result_received: bool
    result_lock: threading.Lock


class ControlledHttpsSmokeRequestHandler(BaseHTTPRequestHandler):
    server: ControlledHttpsSmokeServer

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
        expected_names = {
            f"{self.server.module_name}.js",
            f"{self.server.module_name}.wasm",
        }
        if requested_name not in expected_names:
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
        if path == (
            f"{HOST_ROOT}/chrome_wasm_browser_controlled_https_smoke_host.js"
        ):
            self._send_bytes(
                HTTPStatus.OK,
                "text/javascript; charset=utf-8",
                self.server.host_js_bytes,
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
                (
                    "application/wasm"
                    if artifact.suffix == ".wasm"
                    else "text/javascript; charset=utf-8"
                ),
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
                b"invalid controlled-HTTPS result\n",
            )
            return
        with self.server.result_lock:
            if self.server.result_received:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"controlled-HTTPS result already received\n",
                )
                return
            try:
                self.server.result_queue.put_nowait(result)
            except queue.Full:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"controlled-HTTPS result queue is full\n",
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


def _fixture_port(url: str, description: str) -> int:
    try:
        port = urlsplit(url).port
    except ValueError as exc:
        raise M0Error(f"{description} has an invalid port") from exc
    if type(port) is not int or not 1 <= port <= 65535:
        raise M0Error(f"{description} must contain an explicit port")
    return port


def validate_m6_ui_url(value: object) -> str:
    """Accept the relay's private-H2 M6 document as infrastructure evidence."""

    return validate_m5_https_url(
        value,
        description="relay m6UiUrl",
        expected_path=M6_UI_PATH,
    )


def _is_loopback_wisp_hostname(hostname: str | None) -> bool:
    if hostname == "localhost":
        return True
    if hostname is None:
        return False
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def validate_controlled_wisp_endpoint(value: object) -> str:
    """Require the exact local WISP endpoint consumed by this fixture."""

    endpoint = validate_wisp_endpoint(value)
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme not in ("ws", "wss")
        or not _is_loopback_wisp_hostname(parsed.hostname)
        or parsed.path != "/wisp/"
    ):
        raise M0Error(
            "controlled-HTTPS WISP endpoint must be loopback with path /wisp/"
        )
    _fixture_port(endpoint, "controlled-HTTPS WISP endpoint")
    return endpoint


def parse_relay_ready_line(line: str) -> RelayReady:
    """Require the relay's WISP endpoint and dedicated M6 fixture URL."""

    if not isinstance(line, str):
        raise M0Error("relay readiness line must be text")
    if len(line.encode("utf-8")) > MAX_RELAY_READY_LINE_BYTES:
        raise M0Error("relay readiness line is too long")
    try:
        ready = json.loads(line, object_pairs_hook=_json_object_without_duplicate_keys)
    except (json.JSONDecodeError, ValueError) as exc:
        raise M0Error("relay readiness line is not valid JSON") from exc
    if not isinstance(ready, dict):
        raise M0Error("relay readiness line must be a JSON object")
    if ready.get("schema_version") not in (None, 1):
        raise M0Error("relay readiness schema version is unsupported")

    h2_url = validate_m5_https_url(ready.get("httpsUrl"))
    m6_ui_url = validate_m6_ui_url(ready.get("m6UiUrl"))
    if _fixture_port(h2_url, "relay httpsUrl") != _fixture_port(
        m6_ui_url, "relay m6UiUrl"
    ):
        raise M0Error("relay m6UiUrl must use the controlled H2 fixture port")
    return RelayReady(
        wisp_endpoint=validate_controlled_wisp_endpoint(
            ready.get("wispEndpoint")
        ),
        m6_ui_url=m6_ui_url,
        transcript_url=validate_relay_transcript_url(ready.get("transcriptUrl")),
    )


def _drain_relay_stdout(
    stream: TextIO,
    destination: deque[str],
    ready_lines: queue.Queue[str | None],
) -> None:
    for line in stream:
        text = line.rstrip()
        destination.append(text)
        if text:
            ready_lines.put(text)
    ready_lines.put(None)


def wait_for_relay_ready(
    relay: subprocess.Popen[str],
    ready_lines: queue.Queue[str | None],
    relay_stderr: deque[str],
    deadline: float,
) -> RelayReady:
    while time.monotonic() < deadline:
        if relay.poll() is not None:
            raise M0Error(
                "controlled-HTTPS relay exited before readiness "
                f"(status {relay.returncode}): " + "\n".join(relay_stderr)
            )
        remaining = deadline - time.monotonic()
        try:
            line = ready_lines.get(timeout=min(0.1, max(0.0, remaining)))
        except queue.Empty:
            continue
        if line is None:
            raise M0Error("controlled-HTTPS relay closed stdout before readiness")
        return parse_relay_ready_line(line)
    raise M0Error(
        "controlled-HTTPS relay readiness timeout: " + "\n".join(relay_stderr)
    )


def create_server(
    host: str,
    port: int,
    out_dir: Path,
    result_token: str,
    result_queue: queue.Queue[dict[str, Any]],
    *,
    module_name: str,
) -> ControlledHttpsSmokeServer:
    if not MODULE_NAME_RE.fullmatch(module_name):
        raise M0Error("module name must contain only ASCII letters, digits, or _")
    resolved_out_dir = out_dir.resolve()
    if not resolved_out_dir.is_dir():
        raise M0Error(f"controlled-HTTPS output directory is missing: {out_dir}")
    host_dir = Path(__file__).with_name("host")
    server = ControlledHttpsSmokeServer(
        (host, port), ControlledHttpsSmokeRequestHandler
    )
    server.out_dir = resolved_out_dir
    server.module_name = module_name
    server.result_token = result_token
    server.result_queue = result_queue
    server.result_received = False
    server.result_lock = threading.Lock()
    server.html_bytes = (
        host_dir / "chrome_wasm_browser_controlled_https_smoke.html"
    ).read_bytes()
    server.host_js_bytes = (
        host_dir / "chrome_wasm_browser_controlled_https_smoke_host.js"
    ).read_bytes()
    return server


def smoke_url(
    server: ControlledHttpsSmokeServer,
    token: str,
    versions: dict[str, str],
    *,
    relay_ready: RelayReady,
    module_name: str,
    timeout_seconds: float,
) -> str:
    """Build the tokenized page URL after validating every relay value again."""

    wisp_endpoint = validate_controlled_wisp_endpoint(relay_ready.wisp_endpoint)
    # The relay's m6UiUrl is its private ephemeral H2 listener, which remains
    # useful infrastructure evidence but must never reach the visible browser
    # address. Chrome instead receives the fixed public-looking gateway URL;
    # WISP maps its logical a.test:443 connect to that private listener.
    validate_m6_ui_url(relay_ready.m6_ui_url)
    fixture_url = GATEWAY_FIXTURE_URL
    validate_relay_transcript_url(relay_ready.transcript_url)
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "token": token,
            "module": module_name,
            "timeoutMs": str(max(1000, min(180000, int(timeout_seconds * 1000)))),
            "versions": json.dumps(versions, sort_keys=True, separators=(",", ":")),
            "wispEndpoint": wisp_endpoint,
            "fixtureUrl": fixture_url,
        }
    )
    return f"http://{host}:{port}{HOST_ROOT}/?{query}"


def check_controlled_https_boundary(out_dir: Path) -> None:
    """Keep both production and test-only Chrome graphs off desktop targets."""

    check_boundary(out_dir)
    resolved_out_dir = out_dir.resolve()
    gn = REPO_ROOT / "buildtools/linux64/gn"
    if not gn.is_file():
        raise M0Error(f"GN executable is missing: {gn}")
    for forbidden in check_m6_chrome_boundary._FORBIDDEN_TARGETS:
        result = subprocess.run(
            [
                str(gn),
                "path",
                str(resolved_out_dir),
                CONTROLLED_HTTPS_GN_TARGET,
                forbidden,
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise M0Error(
                "gn path failed for controlled HTTPS target "
                f"({CONTROLLED_HTTPS_GN_TARGET} -> {forbidden}): "
                + result.stderr.strip()
            )
        if "No non-data paths found between these two targets." not in result.stdout:
            raise M0Error(
                "controlled HTTPS Chrome source closure reaches a forbidden "
                f"target ({CONTROLLED_HTTPS_GN_TARGET} -> {forbidden}):\n"
                + result.stdout.strip()
            )


def _require_equal(result: dict[str, Any], field: str, expected: object) -> None:
    if not browser_view_smoke._exact_json_value_equal(result.get(field), expected):
        raise M0Error(
            f"controlled-HTTPS result {field} mismatch: expected {expected!r}, "
            f"got {result.get(field)!r}"
        )


def _decode_screenshot_evidence(
    result: dict[str, Any],
    controlled: dict[str, Any],
    frame_reports: list[dict[str, Any]],
    screenshot_contract: dict[str, Any],
) -> bytes:
    """Decode one bounded PNG and bind it to the first eligible frame."""

    screenshot = result.get("screenshot")
    expected_fields = {
        "mimeType",
        "dataBase64",
        "width",
        "height",
        "frameId",
        "timestampMs",
        "observationSequence",
    }
    if not isinstance(screenshot, dict) or set(screenshot) != expected_fields:
        raise M0Error("controlled-HTTPS screenshot metadata is invalid")
    if screenshot.get("mimeType") != "image/png":
        raise M0Error("controlled-HTTPS screenshot is not a PNG")
    data_base64 = screenshot.get("dataBase64")
    if (
        not isinstance(data_base64, str)
        or not data_base64
        or len(data_base64) > MAX_SCREENSHOT_BASE64_LENGTH
    ):
        raise M0Error("controlled-HTTPS screenshot base64 is invalid")
    try:
        png = base64.b64decode(data_base64.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
        raise M0Error("controlled-HTTPS screenshot base64 is invalid") from exc
    if not png or len(png) > MAX_SCREENSHOT_PNG_BYTES:
        raise M0Error("controlled-HTTPS screenshot PNG exceeds its byte limit")
    for field in ("width", "height", "frameId", "observationSequence"):
        if type(screenshot.get(field)) is not int or screenshot[field] < 1:
            raise M0Error(f"controlled-HTTPS screenshot {field} is invalid")
    timestamp_ms = screenshot.get("timestampMs")
    if (
        type(timestamp_ms) not in (int, float)
        or isinstance(timestamp_ms, bool)
        or not math.isfinite(float(timestamp_ms))
        or timestamp_ms < 0
    ):
        raise M0Error("controlled-HTTPS screenshot timestamp is invalid")
    if (
        screenshot["width"] != screenshot_contract["width"]
        or screenshot["height"] != screenshot_contract["height"]
    ):
        raise M0Error("controlled-HTTPS screenshot dimensions violate the contract")
    image = decode_png(png)
    if (
        image.width != screenshot["width"]
        or image.height != screenshot["height"]
    ):
        raise M0Error(
            "controlled-HTTPS screenshot PNG dimensions do not match metadata"
        )
    if (
        screenshot["frameId"] != controlled["firstEligibleScreenshotFrameId"]
        or screenshot["frameId"] != controlled["screenshotFrameId"]
        or screenshot["observationSequence"]
        != controlled["screenshotObservationSequence"]
    ):
        raise M0Error(
            "controlled-HTTPS screenshot is not bound to its first eligible "
            "frame"
        )
    matching_frames = [
        frame for frame in frame_reports if frame["id"] == screenshot["frameId"]
    ]
    if len(matching_frames) != 1:
        raise M0Error("controlled-HTTPS screenshot frame was not reported")
    captured_frame = matching_frames[0]
    if (
        screenshot["width"] != captured_frame["width"]
        or screenshot["height"] != captured_frame["height"]
        or screenshot["timestampMs"] != captured_frame["timestampMs"]
    ):
        raise M0Error(
            "controlled-HTTPS screenshot does not match the captured frame"
        )
    return png


def validate_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
    screenshot_contract: dict[str, Any] | None = None,
) -> bytes:
    """Require real C++ terminal markers and presentation/focus evidence."""

    if screenshot_contract is None:
        screenshot_contract = load_controlled_https_screenshot_contract()

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
    if process_exit_code is not None and (
        type(process_exit_code) is not int or process_exit_code != 0
    ):
        raise M0Error("controlled-HTTPS bridge process exit disagrees with runtime")
    if not browser_view_smoke._exact_json_value_equal(
        result.get("versions"), expected_versions
    ):
        raise M0Error("controlled-HTTPS versions do not match the manifest")
    for field in ("fatalErrors", "windowErrors", "unhandledRejections"):
        if not isinstance(result.get(field), list) or result[field]:
            raise M0Error(f"controlled-HTTPS {field} is not empty")
    for field in ("stdout", "stderr"):
        if not isinstance(result.get(field), list):
            raise M0Error(f"controlled-HTTPS {field} is not a list")
    output = "\n".join(
        str(line) for field in ("stdout", "stderr") for line in result[field]
    )
    for marker in (READY_MARKER, NAVIGATED_MARKER, PASS_MARKER):
        if marker not in output:
            raise M0Error(f"controlled-HTTPS output is missing {marker}")

    controlled = result.get("controlledHttps")
    if not isinstance(controlled, dict):
        raise M0Error("controlled-HTTPS setup evidence is missing")
    for field in (
        "wispConfigured",
        "runtimeArgumentsConfigured",
        "configurationPrecededFactory",
        "readyMarkerObserved",
        "navigatedMarkerObserved",
        "postNavigatedFrameObserved",
        "firstVisuallyNonEmptyPaintReportObserved",
        "targetFirstVisuallyNonEmptyPaintSignalObserved",
        "postNavigatedFrameAfterFirstVisuallyNonEmptyPaintObserved",
        "screenshotCaptureAttempted",
        "passMarkerObserved",
    ):
        if controlled.get(field) is not True:
            raise M0Error(f"controlled-HTTPS setup {field} is not true")

    for field in (
        "navigatedMarkerObservationSequence",
        "firstVisuallyNonEmptyPaintObservationSequence",
        "targetFirstVisuallyNonEmptyPaintSignalObservationSequence",
        "firstEligibleScreenshotFrameId",
        "screenshotFrameId",
        "screenshotObservationSequence",
    ):
        if type(controlled.get(field)) is not int or controlled[field] < 1:
            raise M0Error(f"controlled-HTTPS setup {field} is invalid")
    navigated_frame_id = controlled.get("frameIdAtNavigatedMarker")
    if type(navigated_frame_id) is not int or navigated_frame_id < 0:
        raise M0Error("controlled-HTTPS NAVIGATED frame ID is invalid")
    if (
        controlled["firstEligibleScreenshotFrameId"]
        <= navigated_frame_id
        or controlled["screenshotFrameId"]
        != controlled["firstEligibleScreenshotFrameId"]
    ):
        raise M0Error(
            "controlled-HTTPS screenshot was not captured from the first "
            "post-NAVIGATED frame eligible after FVP"
        )
    if (
        controlled["targetFirstVisuallyNonEmptyPaintSignalObservationSequence"]
        <= controlled["navigatedMarkerObservationSequence"]
    ):
        raise M0Error(
            "controlled-HTTPS target first visually non-empty paint signal "
            "was not observed after NAVIGATED"
        )
    if (
        controlled["screenshotObservationSequence"]
        <= controlled["navigatedMarkerObservationSequence"]
        or controlled["screenshotObservationSequence"]
        <= controlled[
            "targetFirstVisuallyNonEmptyPaintSignalObservationSequence"
        ]
    ):
        raise M0Error(
            "controlled-HTTPS screenshot was not observed after NAVIGATED "
            "and target first visually non-empty paint signal"
        )

    last_frame = browser_view_smoke._validate_frame_reports(
        result.get("frameReports")
    )
    if not any(
        frame["id"] > navigated_frame_id for frame in result["frameReports"]
    ):
        raise M0Error(
            "controlled-HTTPS has no canvas frame after the NAVIGATED marker"
        )
    browser_view_smoke._validate_readiness(
        result.get("readiness"), result.get("readinessReports")
    )
    readiness = result["readiness"]
    readiness_reports = result["readinessReports"]
    if readiness.get("firstVisuallyNonEmptyPaint") is not True:
        raise M0Error("controlled-HTTPS first visually non-empty paint is absent")
    if not any(
        report.get("firstVisuallyNonEmptyPaint") is True
        for report in readiness_reports
    ):
        raise M0Error(
            "controlled-HTTPS first visually non-empty paint was never reported"
        )
    browser_view_smoke._validate_focus_reports(result.get("ozoneFocusReports"))
    backing_store = result.get("canvasBackingStore")
    if not browser_view_smoke._exact_json_value_equal(
        backing_store,
        {"width": last_frame["width"], "height": last_frame["height"]},
    ):
        raise M0Error(
            "controlled-HTTPS canvas backing store does not match the final frame"
        )
    frame_reports = result.get("frameReports")
    if not isinstance(frame_reports, list):
        raise M0Error("controlled-HTTPS frame reports are invalid")
    return _decode_screenshot_evidence(
        result,
        controlled,
        frame_reports,
        screenshot_contract,
    )


def fetch_relay_status(url: str, *, timeout_seconds: float) -> dict[str, Any]:
    """Fetch only the relay's fixed loopback status endpoint."""

    status_url = validate_relay_transcript_url(url)
    parsed = urlsplit(status_url)
    assert parsed.hostname is not None
    port = _fixture_port(status_url, "relay transcriptUrl")
    connection = http.client.HTTPConnection(
        parsed.hostname, port, timeout=max(0.1, timeout_seconds)
    )
    try:
        connection.request("GET", parsed.path, headers={"Cache-Control": "no-store"})
        response = connection.getresponse()
        if response.status != HTTPStatus.OK:
            raise M0Error(
                f"controlled-HTTPS relay status returned HTTP {response.status}"
            )
        content_length = response.getheader("Content-Length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError as exc:
                raise M0Error("relay status has an invalid Content-Length") from exc
            if declared_size < 0 or declared_size > MAX_RELAY_STATUS_BYTES:
                raise M0Error("relay status exceeds its bounded response size")
        payload = response.read(MAX_RELAY_STATUS_BYTES + 1)
    finally:
        connection.close()
    if len(payload) > MAX_RELAY_STATUS_BYTES:
        raise M0Error("relay status exceeds its bounded response size")
    try:
        status = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_json_object_without_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise M0Error("relay status is not valid JSON") from exc
    if not isinstance(status, dict):
        raise M0Error("relay status must be an object")
    return status


def validate_relay_status(status: dict[str, Any]) -> None:
    """Confirm bounded, fresh delivery of the controlled H2 fixture."""

    if (
        status.get("fixture") != RELAY_FIXTURE
        or status.get("protocol") != 1
        or status.get("ready") is not True
    ):
        raise M0Error("controlled-HTTPS relay status is not ready")
    m6_ui_requests = status.get("m6UiRequests")
    if (
        type(m6_ui_requests) is not int
        or not 0 <= m6_ui_requests <= MAX_RELAY_COUNTER
        or m6_ui_requests != 1
    ):
        raise M0Error(
            "controlled-HTTPS relay did not observe exactly one M6 UI request"
        )
    h2_requests = status.get("h2Requests")
    if (
        not isinstance(h2_requests, dict)
        or h2_requests.get("protocol") != "h2"
        or type(h2_requests.get("count")) is not int
        or not 0 <= h2_requests["count"] <= MAX_RELAY_COUNTER
        or h2_requests["count"] != 1
    ):
        raise M0Error("controlled-HTTPS relay lacks exactly one HTTP/2 request")
    if status.get("localGateway443StreamsOpened") != 1:
        raise M0Error(
            "controlled-HTTPS relay did not open exactly one mapped "
            "a.test:443 WISP stream"
        )
    if status.get("localGateway443Requests") != 0:
        raise M0Error(
            "controlled-HTTPS relay received an unexpected local-gateway probe"
        )
    requested_destinations = status.get("requestedDestinations")
    if requested_destinations != [
        {"hostname": "a.test", "port": GATEWAY_LOGICAL_PORT}
    ]:
        raise M0Error(
            "controlled-HTTPS relay lacks the exact WISP CONNECT for "
            "a.test:443"
        )
    transcript = status.get("transcript")
    if (
        not isinstance(transcript, list)
        or not 1 <= len(transcript) <= MAX_RELAY_TRANSCRIPT_ENTRIES
    ):
        raise M0Error("controlled-HTTPS relay transcript is outside its bounds")
    events: list[str] = []
    previous_sequence = 0
    for entry in transcript:
        if not isinstance(entry, dict):
            raise M0Error("controlled-HTTPS relay transcript is malformed")
        sequence = entry.get("sequence")
        event = entry.get("event")
        if (
            type(sequence) is not int
            or sequence < 1
            or sequence <= previous_sequence
            or not isinstance(event, str)
            or not RELAY_TRANSCRIPT_EVENT_RE.fullmatch(event)
            or len(event) > MAX_RELAY_TRANSCRIPT_EVENT_LENGTH
        ):
            raise M0Error("controlled-HTTPS relay transcript is malformed")
        previous_sequence = sequence
        events.append(event)
    fixture_events = events.count("h2-m6-ui")
    if fixture_events != 1:
        raise M0Error(
            "controlled-HTTPS relay transcript lacks exactly one M6 UI event"
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
                "host browser exited before controlled-HTTPS result "
                f"(status {browser.returncode}): " + "\n".join(browser_stderr)
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M0Error(
                "controlled-HTTPS browser timeout: " + "\n".join(browser_stderr)
            )
        try:
            return result_queue.get(timeout=min(0.1, remaining))
        except queue.Empty:
            continue


def redact_screenshot_data(result: dict[str, Any]) -> dict[str, Any]:
    """Keep PNG base64 out of terminal and JSON diagnostics output."""

    redacted = dict(result)
    screenshot = redacted.get("screenshot")
    if isinstance(screenshot, dict):
        redacted_screenshot = dict(screenshot)
        if isinstance(redacted_screenshot.get("dataBase64"), str):
            redacted_screenshot["dataBase64"] = "<omitted>"
        redacted["screenshot"] = redacted_screenshot
    return redacted


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
    relay_command_line: list[str] | None,
    relay_ready: RelayReady | None,
    relay_stdout: deque[str],
    relay_stderr: deque[str],
    relay_status: dict[str, Any] | None,
    runtime_result: dict[str, Any] | None,
    actual_png: bytes | None,
) -> Path:
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    if actual_png is not None:
        (diagnostics_dir / "chrome-browser-controlled-https-m6-actual.png").write_bytes(
            actual_png
        )
    path = diagnostics_dir / "chrome-browser-controlled-https-m6-failure.json"
    sanitized_result = (
        redact_screenshot_data(runtime_result) if runtime_result is not None else None
    )
    if isinstance(sanitized_result, dict) and actual_png is not None:
        screenshot = sanitized_result.get("screenshot")
        if isinstance(screenshot, dict):
            screenshot["dataBase64"] = (
                "<saved as chrome-browser-controlled-https-m6-actual.png>"
            )
    payload = {
        "schema_version": 1,
        "runner": "run_m6_wasm_browser_controlled_https_smoke.py",
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
            "command": relay_command_line,
            "return_code": relay.poll() if relay else None,
            "ready": (
                {
                    "m6UiUrl": relay_ready.m6_ui_url,
                    "transcriptUrl": relay_ready.transcript_url,
                    "wispEndpoint": relay_ready.wisp_endpoint,
                }
                if relay_ready
                else None
            ),
            "stdout_tail": list(relay_stdout),
            "stderr_tail": list(relay_stderr),
            "status": relay_status,
        },
        "runtime_result": sanitized_result,
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Chrome's controlled HTTPS smoke over the local WISP relay."
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
    parser.add_argument(
        "--baseline",
        type=Path,
        help=(
            "reviewed full-canvas PNG baseline (default is the named M6 "
            "contract baseline when present)"
        ),
    )
    parser.add_argument(
        "--capture-baseline",
        type=Path,
        help=(
            "write one unreviewed PNG candidate and exit 2; this never "
            "reports the controlled-HTTPS lane as passing"
        ),
    )
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--timeout", type=parse_timeout, default=120.0)
    args = parser.parse_args()
    if args.baseline is not None and args.capture_baseline is not None:
        parser.error("--baseline and --capture-baseline are mutually exclusive")
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

    screenshot_contract: dict[str, Any] | None = None
    baseline_path: Path | None = None
    capture_path: Path | None = None
    try:
        screenshot_contract = load_controlled_https_screenshot_contract()
        if args.baseline is not None:
            baseline_path = args.baseline
            if not baseline_path.is_absolute():
                baseline_path = REPO_ROOT / baseline_path
        else:
            baseline_path = (
                CONTROLLED_HTTPS_SCREENSHOT_CONTRACT.parent
                / str(screenshot_contract["baseline"])
            )
        if args.capture_baseline is not None:
            capture_path = args.capture_baseline
            if not capture_path.is_absolute():
                capture_path = REPO_ROOT / capture_path
            if capture_path.suffix != ".png":
                raise M0Error("controlled-HTTPS baseline path must end in .png")
            if capture_path.exists():
                raise M0Error(
                    f"refusing to overwrite existing baseline: {capture_path}"
                )
        if capture_path is None and not baseline_path.is_file():
            raise M0Error(
                "controlled-HTTPS screenshot baseline is missing; use "
                "--capture-baseline, review the image, then rerun with "
                "--baseline"
            )
    except (M0Error, OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))

    server: ControlledHttpsSmokeServer | None = None
    server_thread: threading.Thread | None = None
    browser: subprocess.Popen[str] | None = None
    browser_path: Path | None = None
    browser_version: str | None = None
    browser_stderr: deque[str] = deque(maxlen=300)
    browser_stderr_thread: threading.Thread | None = None
    relay: subprocess.Popen[str] | None = None
    relay_stdout: deque[str] = deque(maxlen=300)
    relay_stderr: deque[str] = deque(maxlen=300)
    relay_stdout_thread: threading.Thread | None = None
    relay_stderr_thread: threading.Thread | None = None
    relay_command_line: list[str] | None = None
    relay_ready: RelayReady | None = None
    relay_status: dict[str, Any] | None = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    result: dict[str, Any] | None = None
    actual_png: bytes | None = None
    context: dict[str, object] | None = None
    stage = "check_artifacts"

    try:
        stage = "check_boundary"
        check_controlled_https_boundary(out_dir)
        for suffix in (".js", ".wasm"):
            artifact = out_dir / f"{args.module_name}{suffix}"
            if not artifact.is_file():
                raise M0Error(f"controlled-HTTPS artifact is missing: {artifact}")
        stage = "verify_test_artifacts"
        verify_no_private_key_pem_artifacts(out_dir, args.module_name)
        stage = "load_manifest"
        manifest = load_manifest()
        versions = manifest_versions(manifest, checked_output(["git", "rev-parse", "HEAD"]))
        context = print_context(
            "run_m6_wasm_browser_controlled_https_smoke.py",
            manifest,
            case=CASE,
            scope=SCOPE,
            gn_args=manifest.get("m6_chrome_gn_args", manifest.get("gn_args")),
            module_name=args.module_name,
            host_browser_sandbox=not args.no_sandbox,
            runtime_arguments=[SMOKE_SWITCH, URL_SWITCH + "=" + GATEWAY_FIXTURE_URL],
            transport="WISP v2.1 over the local controlled relay",
            screenshot_gateway_url=GATEWAY_FIXTURE_URL,
            screenshot_channel_tolerance=screenshot_contract["channel_tolerance"],
            screenshot_maximum_different_pixel_ratio=(
                screenshot_contract["maximum_different_pixel_ratio"]
            ),
            screenshot_baseline=(str(baseline_path) if baseline_path else None),
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
            raise M0Error(f"controlled-HTTPS relay script is missing: {relay_script}")

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
            name="chromium-wasm-m6-controlled-https-server",
            daemon=True,
        )
        server_thread.start()

        stage = "launch_relay"
        relay_command_line = relay_command(node, relay_script, m5_host_origin(server))
        relay = subprocess.Popen(
            relay_command_line,
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
            name="chromium-wasm-m6-controlled-https-relay-stdout",
            daemon=True,
        )
        relay_stdout_thread.start()
        relay_stderr_thread = threading.Thread(
            target=drain_stream,
            args=(relay.stderr, relay_stderr),
            name="chromium-wasm-m6-controlled-https-relay-stderr",
            daemon=True,
        )
        relay_stderr_thread.start()
        stage = "wait_for_relay_ready"
        relay_ready = wait_for_relay_ready(
            relay,
            ready_lines,
            relay_stderr,
            time.monotonic() + min(30.0, max(1.0, args.timeout - 1.0)),
        )
        print(
            f"{SENTINEL}:RELAY_READY "
            + json.dumps(
                {
                    "m6UiUrl": relay_ready.m6_ui_url,
                    "transcriptUrl": relay_ready.transcript_url,
                    "wispEndpoint": relay_ready.wisp_endpoint,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )

        url = smoke_url(
            server,
            token,
            versions,
            relay_ready=relay_ready,
            module_name=args.module_name,
            timeout_seconds=max(1.0, args.timeout - 1.0),
        )
        profile = tempfile.TemporaryDirectory(
            prefix="chromium-wasm-m6-controlled-https-"
        )
        stage = "launch_browser"
        command = browser_command(
            browser_path, profile.name, url, no_sandbox=args.no_sandbox
        )
        command[1:1] = ["--enable-logging=stderr", "--window-size=1280,800"]
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
            name="chromium-wasm-m6-controlled-https-browser-stderr",
            daemon=True,
        )
        browser_stderr_thread.start()

        deadline = time.monotonic() + args.timeout
        stage = "wait_for_result"
        result = wait_for_result(browser, browser_stderr, result_queue, deadline)
        stage = "validate_result"
        actual_png = validate_result(
            result,
            expected_versions=versions,
            screenshot_contract=screenshot_contract,
        )
        stage = "fetch_relay_status"
        relay_status = fetch_relay_status(
            relay_ready.transcript_url,
            timeout_seconds=min(10.0, max(1.0, deadline - time.monotonic())),
        )
        stage = "validate_relay_status"
        validate_relay_status(relay_status)
        if capture_path is not None:
            stage = "capture_baseline"
            capture_path.parent.mkdir(parents=True, exist_ok=True)
            capture_path.write_bytes(actual_png)
            print(
                f"{SENTINEL}:BASELINE_CAPTURED_REVIEW_REQUIRED "
                + json.dumps(
                    {
                        "path": str(capture_path),
                        "gatewayUrl": GATEWAY_FIXTURE_URL,
                        "frameId": result["screenshot"]["frameId"],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                flush=True,
            )
            return 2
        assert baseline_path is not None
        stage = "compare_screenshot"
        comparison = compare_screenshots(
            actual_png,
            baseline_path.read_bytes(),
            channel_tolerance=int(screenshot_contract["channel_tolerance"]),
            maximum_different_pixel_ratio=float(
                screenshot_contract["maximum_different_pixel_ratio"]
            ),
        )
        if not comparison.matches:
            raise M0Error(
                "controlled-HTTPS screenshot exceeded tolerance: "
                + json.dumps(
                    comparison.as_dict(),
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        print(
            f"{SENTINEL}:SCREENSHOT "
            + json.dumps(
                comparison.as_dict(),
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )
        print(
            f"{SENTINEL}:BROWSER_RESULT "
            + json.dumps(
                redact_screenshot_data(result),
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )
        print(
            f"{SENTINEL}:RELAY_STATUS "
            + json.dumps(relay_status, sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        print(f"{SENTINEL}:PASS", flush=True)
        return 0
    except (M0Error, OSError, KeyError, TypeError, ValueError) as exc:
        if browser is not None:
            stop_browser(browser)
        if relay is not None:
            stop_browser(relay)
        if browser_stderr_thread is not None:
            browser_stderr_thread.join(timeout=1)
        if relay_stdout_thread is not None:
            relay_stdout_thread.join(timeout=1)
        if relay_stderr_thread is not None:
            relay_stderr_thread.join(timeout=1)
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
                relay_command_line=relay_command_line,
                relay_ready=relay_ready,
                relay_stdout=relay_stdout,
                relay_stderr=relay_stderr,
                relay_status=relay_status,
                runtime_result=result,
                actual_png=actual_png,
            )
            print(
                f"{SENTINEL}:DIAGNOSTICS "
                + json.dumps({"path": str(diagnostic)}, sort_keys=True),
                file=sys.stderr,
                flush=True,
            )
        except (OSError, TypeError, ValueError) as diagnostic_error:
            print(
                f"{SENTINEL}:DIAGNOSTICS_FAIL reason={diagnostic_error}",
                file=sys.stderr,
                flush=True,
            )
        print(f"{SENTINEL}:FAIL reason={exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        if browser is not None:
            stop_browser(browser)
        if relay is not None:
            stop_browser(relay)
        if profile is not None:
            profile.cleanup()
        if server is not None:
            server.shutdown()
            server.server_close()
        if server_thread is not None:
            server_thread.join(timeout=3)
        if browser_stderr_thread is not None:
            browser_stderr_thread.join(timeout=1)
        if relay_stdout_thread is not None:
            relay_stdout_thread.join(timeout=1)
        if relay_stderr_thread is not None:
            relay_stderr_thread.join(timeout=1)


if __name__ == "__main__":
    sys.exit(main())
