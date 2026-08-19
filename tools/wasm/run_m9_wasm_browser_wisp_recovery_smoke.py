#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Prove one Chrome-in-Wasm WISP carrier-close recovery in one Browser.

This is intentionally a narrow follow-on to the M5 relay and M6 Chrome UI
smokes.  The outer host browser may observe its own console and deliver only
physical Ctrl+L, committed text, and Enter to the focusable Ozone canvas.  It
does not command the inner Chrome tab.  The inner document causes the relay to
close its WISP carrier, then renderer code makes its recovery request and
replacement navigation in the same Browser/WebContents.
"""

from __future__ import annotations

import argparse
import base64
import binascii
from collections import Counter, deque
import contextlib
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
import http.client
import ipaddress
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
from typing import Any, Callable, TextIO
from urllib.parse import urlencode, urlsplit

from m0_common import (
    M0Error,
    REPO_ROOT,
    checked_output,
    load_manifest,
    parse_timeout,
    print_context,
)
from m4_cdp import unused_loopback_port, wait_for_page_client
from m9_browser_cleanup import (
    BrowserStderrReader,
    RelayReadinessLatch,
    abort_browser_group,
    abort_process_group,
    stop_browser_group,
    stop_process_group,
)
from m9_descriptor_snapshot import snapshot_regular_files
from m9_server_cleanup import M9TrackingThreadingHTTPServer, shutdown_server_bounded
from run_browser_smoke import browser_command, find_browser
from run_content_shell_smoke import manifest_versions
from run_m5_wisp_smoke import (
    artifact_delivery_identity,
    byte_snapshot_identity,
    find_node,
    m5_host_origin,
    materialized_wisp_relay_closure_from_snapshot,
    relay_command,
    scan_wisp_snapshot_for_private_key,
    snapshot_wisp_artifacts,
    snapshot_wisp_relay_closure,
    validate_m5_https_url,
    validate_relay_transcript_url,
    validate_wisp_artifact_snapshots,
    validate_wisp_endpoint,
    verify_optional_wisp_data_private_key_pem_artifact,
    wisp_relay_closure_identity,
)


SENTINEL = "CHROMIUM_WASM_M9_BROWSER_WISP_RECOVERY"
CASE = "browser_m9_wisp_carrier_close_recovery"
SCOPE = "same-instance-chrome-ozone-wisp-carrier-close-recovery"
SMOKE_SWITCH = "--wasm-browser-m9-wisp-recovery-smoke"
URL_SWITCH = "--wasm-browser-m9-wisp-recovery-url"
READY_MARKER = "CHROMIUM_WASM_M9_WISP_RECOVERY:READY"
NAVIGATED_MARKER = "CHROMIUM_WASM_M9_WISP_RECOVERY:NAVIGATED"
NATIVE_DISCONNECT_MARKER = (
    "CHROMIUM_WASM_M9_WISP_RECOVERY:NATIVE_ERR_INTERNET_DISCONNECTED"
)
H2_RECOVERED_MARKER = "CHROMIUM_WASM_M9_WISP_RECOVERY:H2_RECOVERED"
SAME_INSTANCE_MARKER = "CHROMIUM_WASM_M9_WISP_RECOVERY:SAME_INSTANCE"
PASS_MARKER = "CHROMIUM_WASM_M9_WISP_RECOVERY:PASS"
CDP_SIGNAL_PREFIX = "CHROMIUM_WASM_M9_WISP_RECOVERY_HOST:"
CDP_CTRL_L_READY = CDP_SIGNAL_PREFIX + "CTRL_L_READY"
CDP_INSERT_TEXT_READY = CDP_SIGNAL_PREFIX + "INSERT_TEXT_READY"
CDP_ENTER_READY = CDP_SIGNAL_PREFIX + "ENTER_READY"
ADDRESS_TEXT = "https://a.test/m5/m9-wisp-recovery"
M9_WISP_RECOVERY_PATH = "/m5/m9-wisp-recovery"
M9_WISP_RECOVERY_COMPLETE_PATH = "/m5/m9-wisp-recovery-complete"
GATEWAY_LOGICAL_PORT = 443
RELAY_FIXTURE = "chromium-wasm-m5-network-v1"
DEFAULT_OUT_DIR = Path("out/wasm-chrome-m6")
DEFAULT_MODULE_NAME = "chrome_wasm_m6_https_test"
HOST_ROOT = "/__m9_browser_wisp_recovery__"
HOST_DIR = Path(__file__).with_name("host")
HOST_RESOURCE_NAMES = (
    "chrome_wasm_browser_m9_wisp_recovery_smoke.html",
    "chrome_wasm_browser_m9_wisp_recovery_smoke_host.js",
    "chrome_wasm_text_input.js",
)
MAX_RESULT_BYTES = 8 * 1024 * 1024
MAX_HOST_RESOURCE_BYTES = 4 * 1024 * 1024
MAX_RELAY_READY_LINE_BYTES = 16 * 1024
MAX_RELAY_STATUS_BYTES = 256 * 1024
MAX_RELAY_TRANSCRIPT_ENTRIES = 256
MAX_RELAY_COUNTER = 16
MAX_RELAY_FIELD_VALUE = 8 * MAX_RELAY_STATUS_BYTES
MAX_SCREENSHOT_PNG_BYTES = 4 * 1024 * 1024
MAX_SCREENSHOT_BASE64_LENGTH = ((MAX_SCREENSHOT_PNG_BYTES + 2) // 3) * 4
MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
RELAY_EVENT_RE = re.compile(r"^[a-z0-9:/._-]{1,96}$", re.IGNORECASE)
CLEANUP_TIMEOUT_SECONDS = 5.0
RELAY_QUIESCENCE_POLL_SECONDS = 0.05
LEADER_STOP_OBSERVATION_SECONDS = 1.0
LEADER_STOP_POLL_SECONDS = 0.01

# This runner consumes the M5 fixture's complete status record.  Keep the
# shape frozen: an added, omitted, or injected field must fail the M9 gate
# rather than silently weakening the post-browser cleanup evidence.
M9_RELAY_STATUS_FIELDS = frozenset(
    (
        "fixture",
        "protocol",
        "ready",
        "activeWispSessions",
        "activeWispTransports",
        "cacheConditionalRequests",
        "cacheNotModified304s",
        "cacheStore200s",
        "cacheUnexpectedRequests",
        "cancelStreamCancelResets",
        "cancelStreamFirstChunks",
        "cancelStreamPhase",
        "cancelStreamProofs",
        "cancelStreamProofSessionMismatches",
        "cancelStreamProofTimeouts",
        "cancelStreamRequests",
        "cancelStreamUnexpectedResets",
        "cspConnectSrcProofs",
        "cspConnectSrcTargetRequests",
        "cspConnectSrcTargetTcpConnections",
        "corsDeniedRequests",
        "corsRequests",
        "h2Requests",
        "largeDownloadBackpressureEvents",
        "largeDownloadBytes",
        "largeDownloadChunks",
        "largeDownloadCompletions",
        "largeDownloadPhase",
        "largeDownloadRequests",
        "largeDownloadUnexpectedCloses",
        "localGateway443Requests",
        "localGateway443StreamsOpened",
        "localGatewayBlockedPortAttempts",
        "m6UiRequests",
        "m9WispRecoveryCompleteRequests",
        "m9WispRecoveryRequests",
        "m9WispRecoveryScriptRequests",
        "multiplexBarrierReleases",
        "multiplexBarrierTimeouts",
        "multiplexBothStreamsOpen",
        "multiplexCorrelationFailures",
        "multiplexDistinctWispStreamCount",
        "multiplexH1Requests",
        "multiplexH2Requests",
        "multiplexPhase",
        "multiplexResponses",
        "multiplexSharedCarrier",
        "multiplexUnexpectedCloses",
        "mixedContentProofs",
        "mixedContentTargetPostControlRequests",
        "mixedContentTargetPostControlTcpConnections",
        "mixedContentTargetPostControlWispConnects",
        "plaintextHttpControlPhase",
        "plaintextHttpControlProofs",
        "plaintextHttpControlRequests",
        "plaintextHttpControlTcpConnections",
        "redirectCookieValidations",
        "redirectIntermediateCookieValidations",
        "redirectIntermediateRequests",
        "redirectRequests",
        "reconnectDisconnectRequests",
        "reconnectFirstChunkAcks",
        "reconnectFirstChunks",
        "reconnectPhase",
        "reconnectRecoveryRequests",
        "reconnectSessionMismatches",
        "reconnectStreamRequests",
        "reconnectUnexpectedCloses",
        "reconnectUnexpectedRetries",
        "rejectedDestinations",
        "relayErrors",
        "requestedDestinations",
        "slowStreamCompletedStreams",
        "slowStreamConsumerBurstBytes",
        "slowStreamConsumerBurstWrites",
        "slowStreamConsumerPauseReadyRequests",
        "slowStreamConsumerResumes",
        "slowStreamFirstStageAcks",
        "slowStreamFirstStages",
        "slowStreamPhase",
        "slowStreamSessionMismatches",
        "slowStreamStageAckTimeouts",
        "slowStreamProofs",
        "slowStreamRequests",
        "slowStreamSecondStageAcks",
        "slowStreamSecondStages",
        "slowStreamStageDelayMs",
        "slowStreamStageDelaySchedules",
        "slowStreamThirdStages",
        "slowStreamUnexpectedCloses",
        "tlsMismatchHttpStreams",
        "tlsMismatchTcpConnections",
        "udpPackets",
        "webSocketEchoes",
        "wispSessions",
        "wispTransportClosures",
        "wispTransportCloseTimeouts",
        "transcript",
    )
)
M9_RELAY_PHASE_FIELDS = frozenset(
    (
        "cancelStreamPhase",
        "largeDownloadPhase",
        "multiplexPhase",
        "plaintextHttpControlPhase",
        "reconnectPhase",
        "slowStreamPhase",
    )
)
M9_RELAY_BOOLEAN_FIELDS = frozenset(
    ("multiplexBothStreamsOpen", "multiplexSharedCarrier")
)
M9_RELAY_SPECIAL_STATUS_FIELDS = (
    frozenset(
        (
            "fixture",
            "protocol",
            "ready",
            "h2Requests",
            "requestedDestinations",
            "transcript",
        )
    )
    | M9_RELAY_PHASE_FIELDS
    | M9_RELAY_BOOLEAN_FIELDS
)
M9_RELAY_NONNEGATIVE_INT_FIELDS = (
    M9_RELAY_STATUS_FIELDS - M9_RELAY_SPECIAL_STATUS_FIELDS
)
M9_RELAY_PRE_CLEANUP_NUMERIC_EXPECTATIONS = {
    **{field: 0 for field in M9_RELAY_NONNEGATIVE_INT_FIELDS},
    "activeWispSessions": 1,
    "activeWispTransports": 1,
    "localGateway443StreamsOpened": 4,
    "m9WispRecoveryCompleteRequests": 1,
    "m9WispRecoveryRequests": 1,
    "m9WispRecoveryScriptRequests": 1,
    "reconnectDisconnectRequests": 1,
    "reconnectFirstChunkAcks": 1,
    "reconnectFirstChunks": 1,
    "reconnectRecoveryRequests": 1,
    "reconnectStreamRequests": 1,
    "slowStreamStageDelayMs": 150,
    "wispSessions": 2,
    "wispTransportClosures": 1,
}
M9_RELAY_PRE_CLEANUP_PHASE_EXPECTATIONS = {
    "cancelStreamPhase": "pre-cancel",
    "largeDownloadPhase": "pre-download",
    "multiplexPhase": "pre-multiplex",
    "plaintextHttpControlPhase": "pre-control",
    "reconnectPhase": "recovered",
    "slowStreamPhase": "pre-stream",
}
M9_RELAY_PRE_CLEANUP_BOOLEAN_EXPECTATIONS = {
    "multiplexBothStreamsOpen": False,
    "multiplexSharedCarrier": False,
}
M9_RELAY_EVENT_NAMES = frozenset(
    (
        "fixture-ready",
        "wisp-connected",
        "wisp-ready",
        "connect-requested",
        "connect-open",
        "h2-m9-wisp-recovery",
        "h2-m9-wisp-recovery-script",
        "h2-reconnect-stream-start",
        "h2-reconnect-stream-first-chunk",
        "h2-reconnect-first-chunk-ack",
        "h2-reconnect-disconnect-requested",
        "h2-reconnect-carrier-close",
        "wisp-disconnected",
        "h2-reconnect-wisp-disconnected",
        "h2-reconnect-stream-disconnected",
        "h2-reconnect-recovery",
        "h2-m9-wisp-recovery-complete",
        "stream-client-close",
        "wisp-transport-closed",
        "wisp-transport-close-timeout",
    )
)
M9_RELAY_EVENT_FIELD_NAMES = {
    "fixture-ready": frozenset(
        (
            "sequence",
            "event",
            "cspConnectSrcTargetPort",
            "h1Port",
            "h2Port",
            "plaintextHttpControlPort",
            "tlsFailurePort",
        )
    ),
    "connect-requested": frozenset(
        ("sequence", "event", "streamId", "destination")
    ),
    "connect-open": frozenset(("sequence", "event", "streamId", "destination")),
    "stream-client-close": frozenset(("sequence", "event", "streamId")),
}
M9_RELAY_PRE_CLEANUP_EVENT_COUNTS = {
    "fixture-ready": 1,
    "wisp-connected": 2,
    "wisp-ready": 2,
    "connect-requested": 4,
    "connect-open": 4,
    "h2-m9-wisp-recovery": 1,
    "h2-m9-wisp-recovery-script": 1,
    "h2-reconnect-stream-start": 1,
    "h2-reconnect-stream-first-chunk": 1,
    "h2-reconnect-first-chunk-ack": 1,
    "h2-reconnect-disconnect-requested": 1,
    "h2-reconnect-carrier-close": 1,
    "wisp-disconnected": 1,
    "h2-reconnect-wisp-disconnected": 1,
    "h2-reconnect-stream-disconnected": 1,
    "h2-reconnect-recovery": 1,
    "h2-m9-wisp-recovery-complete": 1,
    "stream-client-close": 2,
    "wisp-transport-closed": 1,
}
M9_RELAY_PRE_CLEANUP_PENDING_EVENT_COUNTS = {
    event: count
    for event, count in M9_RELAY_PRE_CLEANUP_EVENT_COUNTS.items()
    if event != "wisp-transport-closed"
}


@dataclass(frozen=True)
class RelayReady:
    """The private relay values that the browser host is allowed to consume."""

    wisp_endpoint: str
    transcript_url: str


def _json_object_without_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _require_nonempty_bytes(value: object, description: str) -> bytes:
    if type(value) is not bytes or not value:
        raise M0Error(f"{description} snapshot is invalid")
    return bytes(value)


def _decode_snapshot_text(value: bytes, description: str) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise M0Error(f"{description} is not UTF-8") from exc


def validate_m9_host_snapshots(value: object) -> dict[str, bytes]:
    """Accept only the three immutable resources executed by the M9 host."""

    if not isinstance(value, dict) or set(value) != set(HOST_RESOURCE_NAMES):
        raise M0Error("M9 host snapshots have an unexpected resource set")
    snapshots = {
        name: _require_nonempty_bytes(value[name], f"M9 host {name}")
        for name in HOST_RESOURCE_NAMES
    }
    for name, contents in snapshots.items():
        if len(contents) > MAX_HOST_RESOURCE_BYTES:
            raise M0Error(f"M9 host {name} exceeds its bounded size")
        scan_wisp_snapshot_for_private_key(contents, f"M9 host {name}")

    html = _decode_snapshot_text(
        snapshots["chrome_wasm_browser_m9_wisp_recovery_smoke.html"],
        "M9 host HTML",
    )
    host_js = _decode_snapshot_text(
        snapshots["chrome_wasm_browser_m9_wisp_recovery_smoke_host.js"],
        "M9 host JavaScript",
    )
    text_input_js = _decode_snapshot_text(
        snapshots["chrome_wasm_text_input.js"], "M9 trusted text adapter"
    )
    required_html = (
        "m9-wisp-recovery-root",
        "browser-canvas",
        "browser-text-proxy",
        "chrome_wasm_browser_m9_wisp_recovery_smoke_host.js",
    )
    if any(token not in html for token in required_html):
        raise M0Error("M9 host HTML does not bind the dedicated recovery host")
    required_host_js = (
        ADDRESS_TEXT,
        SMOKE_SWITCH,
        URL_SWITCH,
        NATIVE_DISCONNECT_MARKER,
        H2_RECOVERED_MARKER,
        SAME_INSTANCE_MARKER,
        CDP_SIGNAL_PREFIX.rstrip(":"),
        "CTRL_L_READY",
        "INSERT_TEXT_READY",
        "ENTER_READY",
    )
    if any(token not in host_js for token in required_host_js):
        raise M0Error("M9 host JavaScript lacks its fixed recovery contract")
    if "ChromiumWasmTrustedTextInput" not in text_input_js:
        raise M0Error("M9 host lacks the shared trusted text adapter")
    # Keep this source boundary auditable without teaching the runner any
    # inner-tab command primitive.  Construct the spellings so this runner
    # itself cannot accidentally grow one while checking the host.
    forbidden_protocol_methods = ("Page" + ".navigate", "Runtime" + ".evaluate")
    if any(method in host_js for method in forbidden_protocol_methods):
        raise M0Error("M9 host contains an inner-tab protocol command")
    return snapshots


def snapshot_m9_host_resources() -> dict[str, bytes]:
    return validate_m9_host_snapshots(
        snapshot_regular_files(
            HOST_DIR,
            HOST_RESOURCE_NAMES,
            maximum_bytes=MAX_HOST_RESOURCE_BYTES,
            description="M9 WISP recovery host resource",
        )
    )


def m9_host_delivery_identity(snapshots: object) -> dict[str, object]:
    captured = validate_m9_host_snapshots(snapshots)
    return {
        "host_html": byte_snapshot_identity(
            captured["chrome_wasm_browser_m9_wisp_recovery_smoke.html"],
            "M9 host HTML",
        ),
        "host_js": byte_snapshot_identity(
            captured["chrome_wasm_browser_m9_wisp_recovery_smoke_host.js"],
            "M9 host JavaScript",
        ),
        "trusted_text_input_js": byte_snapshot_identity(
            captured["chrome_wasm_text_input.js"], "M9 trusted text adapter"
        ),
    }


class M9WispRecoverySmokeServer(M9TrackingThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    result_queue: queue.Queue[dict[str, Any]]
    result_token: str
    result_received: bool
    result_lock: threading.Lock
    artifact_snapshots: dict[str, bytes]
    host_snapshots: dict[str, bytes]
    module_name: str


class M9WispRecoverySmokeRequestHandler(BaseHTTPRequestHandler):
    server: M9WispRecoverySmokeServer

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

    def _artifact_bytes(self, requested_name: str) -> bytes | None:
        expected_names = {
            f"{self.server.module_name}.js",
            f"{self.server.module_name}.wasm",
        }
        if requested_name not in expected_names:
            return None
        return self.server.artifact_snapshots.get(requested_name)

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path in (HOST_ROOT, f"{HOST_ROOT}/"):
            self._send_bytes(
                HTTPStatus.OK,
                "text/html; charset=utf-8",
                self.server.host_snapshots[
                    "chrome_wasm_browser_m9_wisp_recovery_smoke.html"
                ],
            )
            return
        if path == (
            f"{HOST_ROOT}/chrome_wasm_browser_m9_wisp_recovery_smoke_host.js"
        ):
            self._send_bytes(
                HTTPStatus.OK,
                "text/javascript; charset=utf-8",
                self.server.host_snapshots[
                    "chrome_wasm_browser_m9_wisp_recovery_smoke_host.js"
                ],
            )
            return
        if path == f"{HOST_ROOT}/chrome_wasm_text_input.js":
            self._send_bytes(
                HTTPStatus.OK,
                "text/javascript; charset=utf-8",
                self.server.host_snapshots["chrome_wasm_text_input.js"],
            )
            return
        prefix = f"{HOST_ROOT}/artifacts/"
        if path.startswith(prefix):
            requested_name = path[len(prefix) :]
            artifact = self._artifact_bytes(requested_name)
            if artifact is None:
                self._not_found()
                return
            self._send_bytes(
                HTTPStatus.OK,
                (
                    "application/wasm"
                    if requested_name.endswith(".wasm")
                    else "text/javascript; charset=utf-8"
                ),
                artifact,
            )
            return
        self._not_found()

    def do_POST(self) -> None:
        if urlsplit(self.path).path != f"{HOST_ROOT}/result/{self.server.result_token}":
            self._not_found()
            return
        try:
            content_length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            content_length = -1
        if content_length < 0 or content_length > MAX_RESULT_BYTES:
            self._send_bytes(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "text/plain; charset=utf-8",
                b"invalid result size\n",
            )
            return
        result = parse_result_payload(self.rfile.read(content_length))
        if result is None:
            self._send_bytes(
                HTTPStatus.BAD_REQUEST,
                "text/plain; charset=utf-8",
                b"invalid M9 recovery result\n",
            )
            return
        with self.server.result_lock:
            if self.server.result_received:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"M9 recovery result already received\n",
                )
                return
            try:
                self.server.result_queue.put_nowait(result)
            except queue.Full:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"M9 recovery result queue is full\n",
                )
                return
            self.server.result_received = True
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()


def parse_result_payload(payload: bytes) -> dict[str, Any] | None:
    try:
        result = json.loads(
            payload.decode("utf-8"), object_pairs_hook=_json_object_without_duplicate_keys
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
    artifact_snapshots: dict[str, bytes] | None = None,
    host_snapshots: dict[str, bytes] | None = None,
) -> M9WispRecoverySmokeServer:
    if not MODULE_NAME_RE.fullmatch(module_name):
        raise M0Error("M9 module name contains unsupported characters")
    artifacts = (
        snapshot_wisp_artifacts(out_dir, module_name)
        if artifact_snapshots is None
        else validate_wisp_artifact_snapshots(artifact_snapshots, module_name)
    )
    host_resources = (
        snapshot_m9_host_resources()
        if host_snapshots is None
        else validate_m9_host_snapshots(host_snapshots)
    )
    server = M9WispRecoverySmokeServer(
        (host, port), M9WispRecoverySmokeRequestHandler
    )
    server.module_name = module_name
    server.out_dir = out_dir
    server.result_token = result_token
    server.result_queue = result_queue
    server.result_received = False
    server.result_lock = threading.Lock()
    server.artifact_snapshots = artifacts
    server.host_snapshots = host_resources
    return server


def _fixture_port(value: str, description: str) -> int:
    try:
        port = urlsplit(value).port
    except ValueError as exc:
        raise M0Error(f"{description} has an invalid port") from exc
    if type(port) is not int or not 1 <= port <= 65535:
        raise M0Error(f"{description} must contain an explicit port")
    return port


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
    endpoint = validate_wisp_endpoint(value)
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme not in ("ws", "wss")
        or not _is_loopback_wisp_hostname(parsed.hostname)
        or parsed.path != "/wisp/"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise M0Error("M9 WISP endpoint must be a loopback /wisp/ URL")
    _fixture_port(endpoint, "M9 WISP endpoint")
    return endpoint


def parse_relay_ready_line(line: str) -> RelayReady:
    if not isinstance(line, str) or len(line.encode("utf-8")) > MAX_RELAY_READY_LINE_BYTES:
        raise M0Error("M9 relay readiness line is invalid")
    try:
        ready = json.loads(line, object_pairs_hook=_json_object_without_duplicate_keys)
    except (json.JSONDecodeError, ValueError) as exc:
        raise M0Error("M9 relay readiness line is not valid JSON") from exc
    schema_version = ready.get("schema_version") if isinstance(ready, dict) else None
    if (
        not isinstance(ready, dict)
        or schema_version is not None
        and (type(schema_version) is not int or schema_version != 1)
    ):
        raise M0Error("M9 relay readiness metadata is invalid")
    # Validate the private listener as relay infrastructure only.  The visible
    # Chrome address remains the fixed no-port gateway URL above.
    validate_m5_https_url(ready.get("httpsUrl"))
    return RelayReady(
        wisp_endpoint=validate_controlled_wisp_endpoint(ready.get("wispEndpoint")),
        transcript_url=validate_relay_transcript_url(ready.get("transcriptUrl")),
    )


def _queue_relay_ready_line(ready_lines: RelayReadinessLatch, text: str) -> None:
    ready_lines.put(text)


def _queue_relay_ready_eof(ready_lines: RelayReadinessLatch) -> None:
    ready_lines.put(None)


def wait_for_relay_ready(
    relay: subprocess.Popen[str],
    ready_lines: RelayReadinessLatch,
    relay_stderr: deque[str],
    deadline: float,
) -> RelayReady:
    while time.monotonic() < deadline:
        if relay.poll() is not None:
            raise M0Error(
                "M9 relay exited before readiness "
                f"(status {relay.returncode}): " + "\n".join(relay_stderr)
            )
        try:
            line = ready_lines.get(timeout=min(0.1, max(0.0, deadline - time.monotonic())))
        except queue.Empty:
            continue
        if line is None:
            raise M0Error("M9 relay closed stdout before readiness")
        return parse_relay_ready_line(line)
    raise M0Error("M9 relay readiness timed out: " + "\n".join(relay_stderr))


def smoke_url(
    server: M9WispRecoverySmokeServer,
    token: str,
    versions: dict[str, str],
    *,
    relay_ready: RelayReady,
    module_name: str,
    timeout_seconds: float,
) -> str:
    if not MODULE_NAME_RE.fullmatch(module_name):
        raise M0Error("M9 module name contains unsupported characters")
    wisp_endpoint = validate_controlled_wisp_endpoint(relay_ready.wisp_endpoint)
    validate_relay_transcript_url(relay_ready.transcript_url)
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "token": token,
            "module": module_name,
            "timeoutMs": str(max(1000, min(180000, int(timeout_seconds * 1000)))),
            "versions": json.dumps(versions, sort_keys=True, separators=(",", ":")),
            "wispEndpoint": wisp_endpoint,
            "fixtureUrl": ADDRESS_TEXT,
        }
    )
    return f"http://{host}:{port}{HOST_ROOT}/?{query}"


def _require_exact_int(
    values: dict[str, Any], field: str, expected: int, description: str
) -> None:
    if values.get(field) != expected or type(values.get(field)) is not int:
        raise M0Error(f"{description} {field} is not exactly {expected}")


def fetch_relay_status(url: str, *, timeout_seconds: float) -> dict[str, Any]:
    status_url = validate_relay_transcript_url(url)
    parsed = urlsplit(status_url)
    if parsed.hostname is None:
        raise M0Error("M9 relay transcript URL has no hostname")
    connection = http.client.HTTPConnection(
        parsed.hostname,
        _fixture_port(status_url, "M9 relay transcript URL"),
        timeout=max(0.1, timeout_seconds),
    )
    try:
        connection.request("GET", parsed.path, headers={"Cache-Control": "no-store"})
        response = connection.getresponse()
        if response.status != HTTPStatus.OK:
            raise M0Error(f"M9 relay status returned HTTP {response.status}")
        content_length = response.getheader("Content-Length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError as exc:
                raise M0Error("M9 relay status has invalid Content-Length") from exc
            if declared < 0 or declared > MAX_RELAY_STATUS_BYTES:
                raise M0Error("M9 relay status exceeds its bounded size")
        payload = response.read(MAX_RELAY_STATUS_BYTES + 1)
    finally:
        connection.close()
    if len(payload) > MAX_RELAY_STATUS_BYTES:
        raise M0Error("M9 relay status exceeds its bounded size")
    try:
        status = json.loads(
            payload.decode("utf-8"), object_pairs_hook=_json_object_without_duplicate_keys
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise M0Error("M9 relay status is not valid JSON") from exc
    if not isinstance(status, dict):
        raise M0Error("M9 relay status must be an object")
    return status


def _validate_m9_relay_status_shape(status: dict[str, Any]) -> None:
    if set(status) != M9_RELAY_STATUS_FIELDS:
        raise M0Error("M9 relay status has an unexpected field set")
    for field in M9_RELAY_NONNEGATIVE_INT_FIELDS:
        value = status.get(field)
        if type(value) is not int or not 0 <= value <= MAX_RELAY_FIELD_VALUE:
            raise M0Error(f"M9 relay status {field} has an invalid integer shape")
    for field in M9_RELAY_PHASE_FIELDS:
        value = status.get(field)
        if type(value) is not str or not value or len(value) > 96:
            raise M0Error(f"M9 relay status {field} has an invalid phase shape")
    for field in M9_RELAY_BOOLEAN_FIELDS:
        if type(status.get(field)) is not bool:
            raise M0Error(f"M9 relay status {field} has an invalid boolean shape")
    h2 = status.get("h2Requests")
    if (
        not isinstance(h2, dict)
        or set(h2) != {"count", "protocol"}
        or type(h2.get("count")) is not int
        or not 0 <= h2["count"] <= MAX_RELAY_FIELD_VALUE
        or type(h2.get("protocol")) is not str
    ):
        raise M0Error("M9 relay status h2Requests has an invalid shape")
    destinations = status.get("requestedDestinations")
    if not isinstance(destinations, list) or len(destinations) > MAX_RELAY_COUNTER:
        raise M0Error("M9 relay status requestedDestinations has an invalid shape")


def _validated_transcript(status: dict[str, Any]) -> list[dict[str, Any]]:
    transcript = status.get("transcript")
    if not isinstance(transcript, list) or not 1 <= len(transcript) <= MAX_RELAY_TRANSCRIPT_ENTRIES:
        raise M0Error("M9 relay transcript is outside its bounded range")
    previous_sequence = 0
    validated: list[dict[str, Any]] = []
    for entry in transcript:
        if not isinstance(entry, dict):
            raise M0Error("M9 relay transcript entry is not an object")
        sequence = entry.get("sequence")
        event = entry.get("event")
        if (
            type(sequence) is not int
            or sequence != previous_sequence + 1
            or not isinstance(event, str)
            or not RELAY_EVENT_RE.fullmatch(event)
        ):
            raise M0Error("M9 relay transcript sequence is invalid")
        if event not in M9_RELAY_EVENT_NAMES:
            raise M0Error("M9 relay transcript has an unexpected event")
        expected_fields = M9_RELAY_EVENT_FIELD_NAMES.get(
            event, frozenset(("sequence", "event"))
        )
        if set(entry) != expected_fields:
            raise M0Error("M9 relay transcript entry has an invalid field shape")
        if event == "fixture-ready":
            for field in (
                "cspConnectSrcTargetPort",
                "h1Port",
                "h2Port",
                "plaintextHttpControlPort",
                "tlsFailurePort",
            ):
                port = entry.get(field)
                if type(port) is not int or not 1 <= port <= 65535:
                    raise M0Error("M9 relay fixture-ready port is invalid")
        elif event in (
            "connect-requested",
            "connect-open",
            "stream-client-close",
        ):
            stream_id = entry.get("streamId")
            if type(stream_id) is not int or not 1 <= stream_id <= 0xFFFFFFFF:
                raise M0Error("M9 relay transcript stream ID is invalid")
            if event != "stream-client-close" and entry.get("destination") != (
                f"a.test:{GATEWAY_LOGICAL_PORT}"
            ):
                raise M0Error("M9 relay target stream is not a.test:443")
        previous_sequence = sequence
        validated.append(entry)
    return validated


def _exact_event_index(entries: list[dict[str, Any]], event: str) -> int:
    indices = [index for index, entry in enumerate(entries) if entry.get("event") == event]
    if len(indices) != 1:
        raise M0Error(f"M9 relay transcript lacks exactly one {event}")
    return indices[0]


def _event_indices(entries: list[dict[str, Any]], event: str) -> list[int]:
    return [index for index, entry in enumerate(entries) if entry.get("event") == event]


def validate_m9_relay_status(status: dict[str, Any]) -> None:
    """Require a causally ordered carrier close and fresh WISP/H2 recovery."""

    _validate_m9_relay_status_shape(status)
    if (
        status.get("fixture") != RELAY_FIXTURE
        or type(status.get("protocol")) is not int
        or status.get("protocol") != 1
        or status.get("ready") is not True
    ):
        raise M0Error("M9 relay status is not the expected ready fixture")
    for field, expected in M9_RELAY_PRE_CLEANUP_NUMERIC_EXPECTATIONS.items():
        _require_exact_int(status, field, expected, "M9 relay")
    for field, expected in M9_RELAY_PRE_CLEANUP_PHASE_EXPECTATIONS.items():
        if status.get(field) != expected or type(status.get(field)) is not str:
            raise M0Error(f"M9 relay {field} is not exactly {expected}")
    for field, expected in M9_RELAY_PRE_CLEANUP_BOOLEAN_EXPECTATIONS.items():
        if status.get(field) is not expected:
            raise M0Error(f"M9 relay {field} is not exactly {expected}")
    h2 = status.get("h2Requests")
    if (
        not isinstance(h2, dict)
        or h2.get("protocol") != "h2"
        or h2["count"] != 6
    ):
        raise M0Error("M9 relay lacks exactly six HTTP/2 requests")
    destinations = status.get("requestedDestinations")
    if (
        not isinstance(destinations, list)
        or len(destinations) != 4
        or any(
            destination != {"hostname": "a.test", "port": GATEWAY_LOGICAL_PORT}
            for destination in destinations
        )
    ):
        raise M0Error("M9 relay lacks exactly four a.test:443 WISP CONNECTs")

    entries = _validated_transcript(status)
    if Counter(entry["event"] for entry in entries) != M9_RELAY_PRE_CLEANUP_EVENT_COUNTS:
        raise M0Error("M9 relay transcript has unexpected or missing events")
    for event in (
        "h2-m9-wisp-recovery",
        "h2-m9-wisp-recovery-script",
        "h2-reconnect-stream-start",
        "h2-reconnect-stream-first-chunk",
        "h2-reconnect-first-chunk-ack",
        "h2-reconnect-disconnect-requested",
        "h2-reconnect-carrier-close",
        "h2-reconnect-stream-disconnected",
        "h2-reconnect-wisp-disconnected",
        "h2-reconnect-recovery",
        "h2-m9-wisp-recovery-complete",
    ):
        _exact_event_index(entries, event)
    connected = _event_indices(entries, "wisp-connected")
    ready = _event_indices(entries, "wisp-ready")
    disconnected = _event_indices(entries, "wisp-disconnected")
    if len(connected) != 2 or len(ready) != 2 or len(disconnected) != 1:
        raise M0Error("M9 relay does not prove 2 connects/readies and 1 disconnect")
    old_transport_closed = _exact_event_index(entries, "wisp-transport-closed")
    # The peer's close callback tears down the logical relay before the raw
    # WebSocket close callback records its physical transport closure.  The
    # latter can race freely with the fresh carrier/recovery, but it cannot
    # predate that old relay teardown.
    if disconnected[0] >= old_transport_closed:
        raise M0Error("M9 old WISP transport closed before relay disconnect")
    connect_requested = _event_indices(entries, "connect-requested")
    connect_open = _event_indices(entries, "connect-open")
    if len(connect_requested) != 4 or len(connect_open) != 4:
        raise M0Error("M9 relay lacks exactly four target stream records")
    for requested_index, open_index in zip(connect_requested, connect_open):
        if (
            requested_index >= open_index
            or entries[requested_index]["streamId"] != entries[open_index]["streamId"]
        ):
            raise M0Error("M9 relay target stream request/open pairing is invalid")
    post_recovery_stream_ids = [
        entries[index]["streamId"] for index in connect_requested[2:]
    ]
    client_close_stream_ids = [
        entries[index]["streamId"]
        for index in _event_indices(entries, "stream-client-close")
    ]
    if Counter(post_recovery_stream_ids) != Counter(client_close_stream_ids):
        raise M0Error("M9 relay client closes do not match post-recovery streams")

    ordered_events = (
        "h2-m9-wisp-recovery",
        "h2-m9-wisp-recovery-script",
        "h2-reconnect-stream-start",
        "h2-reconnect-stream-first-chunk",
        "h2-reconnect-first-chunk-ack",
        "h2-reconnect-disconnect-requested",
        "h2-reconnect-carrier-close",
        "h2-reconnect-stream-disconnected",
        "wisp-ready",
        "h2-reconnect-recovery",
        "h2-m9-wisp-recovery-complete",
    )
    indices = [_exact_event_index(entries, event) for event in ordered_events[:-4]]
    carrier_close = _exact_event_index(entries, "h2-reconnect-carrier-close")
    old_stream_disconnected = _exact_event_index(
        entries, "h2-reconnect-stream-disconnected"
    )
    reconnect_wisp_disconnected = _exact_event_index(
        entries, "h2-reconnect-wisp-disconnected"
    )
    reconnect_stream_started = _exact_event_index(
        entries, "h2-reconnect-stream-start"
    )
    recovery = _exact_event_index(entries, "h2-reconnect-recovery")
    complete = _exact_event_index(entries, "h2-m9-wisp-recovery-complete")
    if indices != sorted(indices):
        raise M0Error("M9 relay carrier-close setup ordering is invalid")
    # Closing the carrier tears down its target H2 stream asynchronously. A
    # browser can create the fresh carrier as that old stream's close callback
    # is still pending, so do not turn that permitted race into a false
    # recovery failure. Its event must still be downstream of the deliberate
    # carrier close; the WISP-carrier lifecycle itself establishes that the
    # new ready session precedes recovery.
    if carrier_close >= old_stream_disconnected:
        raise M0Error("M9 old reconnect stream did not follow carrier close")
    if not (
        carrier_close
        < reconnect_wisp_disconnected
        < connected[1]
        < ready[1]
        < connect_requested[2]
        < connect_open[2]
        < recovery
    ):
        raise M0Error("M9 relay reconnect WISP transition ordering is invalid")
    initial_document = _exact_event_index(entries, "h2-m9-wisp-recovery")
    recovery_script = _exact_event_index(entries, "h2-m9-wisp-recovery-script")
    if not (
        connected[0]
        < ready[0]
        < connect_requested[0]
        < connect_open[0]
        < initial_document
        < recovery_script
        < connect_requested[1]
        < connect_open[1]
        < reconnect_stream_started
        < carrier_close
        < disconnected[0]
        < connected[1]
        < ready[1]
        < connect_requested[2]
        < connect_open[2]
        < recovery
        < connect_requested[3]
        < connect_open[3]
        < complete
    ):
        raise M0Error("M9 relay carrier lifecycle is not fresh-session evidence")


def _validate_m9_relay_pre_cleanup_progress(status: dict[str, Any]) -> bool:
    """Accept only the old transport's one bounded asynchronous close gap."""

    try:
        validate_m9_relay_status(status)
        return True
    except M0Error:
        pass

    _validate_m9_relay_status_shape(status)
    for field, expected in {
        "activeWispSessions": 1,
        "activeWispTransports": 2,
        "wispTransportClosures": 0,
        "wispTransportCloseTimeouts": 0,
    }.items():
        _require_exact_int(status, field, expected, "M9 relay pre-cleanup")
    entries = _validated_transcript(status)
    if Counter(entry["event"] for entry in entries) != (
        M9_RELAY_PRE_CLEANUP_PENDING_EVENT_COUNTS
    ):
        raise M0Error("M9 relay pre-cleanup transcript is not the expected transport gap")

    # The old physical close can race the fresh carrier's later request/open
    # callbacks. Do not impose an artificial ordering on it; normalize only
    # the one missing terminal record to reuse the strict recovery validator.
    normalized = dict(status)
    normalized["activeWispTransports"] = 1
    normalized["wispTransportClosures"] = 1
    normalized["transcript"] = [
        *entries,
        {
            "sequence": len(entries) + 1,
            "event": "wisp-transport-closed",
        },
    ]
    validate_m9_relay_status(normalized)
    return False


def wait_for_m9_relay_pre_cleanup_status(
    url: str, *, timeout_seconds: float
) -> dict[str, Any]:
    """Wait for the first carrier's physical close before stopping Browser."""

    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise M0Error("M9 relay pre-cleanup timeout is invalid")
    deadline = time.monotonic() + timeout_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M0Error("M9 relay did not finish its old transport cleanup")
        status = fetch_relay_status(
            url, timeout_seconds=min(1.0, max(0.1, remaining))
        )
        if _validate_m9_relay_pre_cleanup_progress(status):
            return status
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M0Error("M9 relay did not finish its old transport cleanup")
        time.sleep(min(RELAY_QUIESCENCE_POLL_SECONDS, remaining))


def _require_equal(result: dict[str, Any], field: str, expected: object) -> None:
    if result.get(field) != expected or type(result.get(field)) is not type(expected):
        raise M0Error(f"M9 result {field} is invalid")


def _exact_json_equal(left: object, right: object) -> bool:
    return json.dumps(left, sort_keys=True, separators=(",", ":")) == json.dumps(
        right, sort_keys=True, separators=(",", ":")
    )


def _m9_relay_static_status(status: dict[str, Any]) -> dict[str, Any]:
    return {
        field: value
        for field, value in status.items()
        if field
        not in {
            "activeWispSessions",
            "activeWispTransports",
            "wispTransportClosures",
            "transcript",
        }
    }


def _validate_m9_relay_quiescence_progress(
    status: dict[str, Any], *, pre_cleanup_status: dict[str, Any]
) -> bool:
    """Accept only the one bounded terminal transition after browser stop.

    Return true once the upgraded peer's actual TCP transport has closed.  A
    relay removal alone is only an intermediate state: the old peer can still
    own a FIN_WAIT/CLOSE_WAIT transport until its close callback runs.
    """

    validate_m9_relay_status(pre_cleanup_status)
    _validate_m9_relay_status_shape(status)
    if not _exact_json_equal(
        _m9_relay_static_status(status), _m9_relay_static_status(pre_cleanup_status)
    ):
        raise M0Error("M9 relay status changed outside terminal transport cleanup")

    pre_entries = _validated_transcript(pre_cleanup_status)
    entries = _validated_transcript(status)
    terminal_disconnect = {
        "sequence": len(pre_entries) + 1,
        "event": "wisp-disconnected",
    }
    terminal_transport_close = {
        "sequence": len(pre_entries) + 2,
        "event": "wisp-transport-closed",
    }
    pending_entries = [*pre_entries, terminal_disconnect]
    final_entries = [*pending_entries, terminal_transport_close]
    if _exact_json_equal(entries, pending_entries):
        for field, expected in {
            "activeWispSessions": 0,
            "activeWispTransports": 1,
            "wispTransportClosures": 1,
        }.items():
            _require_exact_int(status, field, expected, "M9 relay terminal")
        return False
    if _exact_json_equal(entries, final_entries):
        for field, expected in {
            "activeWispSessions": 0,
            "activeWispTransports": 0,
            "wispTransportClosures": 2,
        }.items():
            _require_exact_int(status, field, expected, "M9 relay terminal")
        return True
    raise M0Error("M9 relay terminal transcript is not the expected quiescence delta")


def validate_m9_relay_quiescence(
    status: dict[str, Any], *, pre_cleanup_status: dict[str, Any]
) -> None:
    if not _validate_m9_relay_quiescence_progress(
        status, pre_cleanup_status=pre_cleanup_status
    ):
        raise M0Error("M9 relay transport cleanup is still in progress")


def wait_for_m9_relay_quiescence(
    url: str,
    *,
    pre_cleanup_status: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    """Poll the private status endpoint until its only allowed terminal delta."""

    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise M0Error("M9 relay quiescence timeout is invalid")
    validate_m9_relay_status(pre_cleanup_status)
    deadline = time.monotonic() + timeout_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M0Error("M9 relay did not reach terminal transport quiescence")
        status = fetch_relay_status(
            url, timeout_seconds=min(1.0, max(0.1, remaining))
        )
        if _exact_json_equal(status, pre_cleanup_status):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise M0Error("M9 relay did not reach terminal transport quiescence")
            time.sleep(min(RELAY_QUIESCENCE_POLL_SECONDS, remaining))
            continue
        if _validate_m9_relay_quiescence_progress(
            status, pre_cleanup_status=pre_cleanup_status
        ):
            return status
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M0Error("M9 relay did not reach terminal transport quiescence")
        time.sleep(min(RELAY_QUIESCENCE_POLL_SECONDS, remaining))


def _require_exact_records(
    records: object, expected: list[dict[str, object]], description: str
) -> None:
    if not _exact_json_equal(records, expected):
        raise M0Error(f"M9 {description} records are invalid")


def _decode_recovery_screenshot(value: object) -> tuple[dict[str, Any], int, int]:
    if not isinstance(value, dict):
        raise M0Error("M9 recovery screenshot is absent")
    encoded = value.get("dataBase64")
    if (
        not isinstance(encoded, str)
        or not encoded
        or len(encoded) > MAX_SCREENSHOT_BASE64_LENGTH
    ):
        raise M0Error("M9 recovery screenshot encoding is invalid")
    try:
        png = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise M0Error("M9 recovery screenshot is not base64") from exc
    if (
        not 8 <= len(png) <= MAX_SCREENSHOT_PNG_BYTES
        or png[:8] != b"\x89PNG\r\n\x1a\n"
        or value.get("mimeType") != "image/png"
    ):
        raise M0Error("M9 recovery screenshot is not a bounded PNG")
    if (
        len(png) < 33
        or png[8:12] != b"\x00\x00\x00\r"
        or png[12:16] != b"IHDR"
    ):
        raise M0Error("M9 recovery screenshot lacks a PNG IHDR")
    width = int.from_bytes(png[16:20], "big")
    height = int.from_bytes(png[20:24], "big")
    if width < 1 or height < 1:
        raise M0Error("M9 recovery screenshot PNG dimensions are invalid")
    return value, width, height


def _marker_lines(result: dict[str, Any]) -> tuple[list[str], list[str]]:
    streams: list[list[str]] = []
    for field in ("stdout", "stderr"):
        values = result.get(field)
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise M0Error(f"M9 result {field} is invalid")
        streams.append(values)
    return streams[0], streams[1]


def _validate_exact_native_markers(result: dict[str, Any]) -> None:
    stdout_lines, stderr_lines = _marker_lines(result)
    previous = -1
    for marker in (
        READY_MARKER,
        NAVIGATED_MARKER,
        NATIVE_DISCONNECT_MARKER,
        H2_RECOVERED_MARKER,
        SAME_INSTANCE_MARKER,
        PASS_MARKER,
    ):
        exact = [index for index, line in enumerate(stdout_lines) if line == marker]
        occurrences = sum(line.count(marker) for line in stdout_lines)
        stderr_occurrences = sum(line.count(marker) for line in stderr_lines)
        if (
            len(exact) != 1
            or occurrences != 1
            or stderr_occurrences != 0
            or exact[0] <= previous
        ):
            raise M0Error(f"M9 native marker transcript is invalid at {marker}")
        previous = exact[0]


def validate_result(result: dict[str, Any], *, expected_versions: dict[str, str]) -> None:
    """Bind input, native terminal records, and post-recovery canvas evidence."""

    for field, expected in {
        "protocol": 1,
        "case": CASE,
        "scope": SCOPE,
        "status": "pass",
        "m9GateComplete": False,
        "runtimeExitCode": 0,
        "runtimeInitialized": True,
        "factorySettled": True,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "abort": None,
        "failedChecks": [],
        "error": None,
    }.items():
        _require_equal(result, field, expected)
    process_exit = result.get("processExitCode")
    if process_exit is not None and (type(process_exit) is not int or process_exit != 0):
        raise M0Error("M9 bridge process exit disagrees with the runtime")
    if not _exact_json_equal(result.get("versions"), expected_versions):
        raise M0Error("M9 result versions do not match the manifest")
    for field in ("fatalErrors", "windowErrors", "unhandledRejections"):
        if not isinstance(result.get(field), list) or result[field]:
            raise M0Error(f"M9 result {field} is not empty")
    _validate_exact_native_markers(result)

    recovery = result.get("m9WispRecovery")
    if not isinstance(recovery, dict):
        raise M0Error("M9 recovery evidence is absent")
    for field in (
        "wispConfigured",
        "runtimeArgumentsConfigured",
        "configurationPrecededFactory",
        "readyMarkerObserved",
        "navigatedMarkerObserved",
        "nativeDisconnectMarkerObserved",
        "h2RecoveredMarkerObserved",
        "sameInstanceMarkerObserved",
        "passMarkerObserved",
        "recoveryFrameObserved",
    ):
        if recovery.get(field) is not True:
            raise M0Error(f"M9 recovery evidence {field} is absent")
    for field in (
        "frameIdAtH2Recovered",
        "h2RecoveredObservationSequence",
        "sameInstanceObservationSequence",
        "recoveryFrameId",
    ):
        if type(recovery.get(field)) is not int or recovery[field] < 1:
            raise M0Error(f"M9 recovery evidence {field} is invalid")
    if recovery["recoveryFrameId"] <= recovery["frameIdAtH2Recovered"]:
        raise M0Error("M9 recovery canvas frame does not follow H2")

    frames = result.get("frameReports")
    if not isinstance(frames, list) or not frames:
        raise M0Error("M9 has no frame report history")
    last_frame: dict[str, Any] | None = None
    previous_frame_id = 0
    for frame in frames:
        if (
            not isinstance(frame, dict)
            or type(frame.get("id")) is not int
            or frame["id"] <= previous_frame_id
            or type(frame.get("width")) is not int
            or frame["width"] < 1
            or type(frame.get("height")) is not int
            or frame["height"] < 1
        ):
            raise M0Error("M9 frame report is invalid")
        previous_frame_id = frame["id"]
        last_frame = frame
    if last_frame is None:
        raise M0Error("M9 has no final frame report")
    screenshot, png_width, png_height = _decode_recovery_screenshot(
        result.get("recoveryScreenshot")
    )
    for field in ("id", "width", "height", "observationSequence"):
        if type(screenshot.get(field)) is not int or screenshot[field] < 1:
            raise M0Error(f"M9 recovery screenshot {field} is invalid")
    first_post_h2 = next(
        (frame for frame in frames if frame["id"] > recovery["frameIdAtH2Recovered"]),
        None,
    )
    if (
        first_post_h2 is None
        or screenshot["id"] != recovery["recoveryFrameId"]
        or screenshot["id"] != first_post_h2["id"]
        or screenshot["width"] != first_post_h2["width"]
        or screenshot["height"] != first_post_h2["height"]
        or png_width != screenshot["width"]
        or png_height != screenshot["height"]
        or not (
            recovery["h2RecoveredObservationSequence"]
            < screenshot["observationSequence"]
            < recovery["sameInstanceObservationSequence"]
        )
    ):
        raise M0Error("M9 screenshot is not the first presentation between H2 and same instance")
    if not _exact_json_equal(
        result.get("canvasBackingStore"),
        {"width": last_frame["width"], "height": last_frame["height"]},
    ):
        raise M0Error("M9 canvas backing store disagrees with final frame")

    readiness = result.get("readiness")
    readiness_reports = result.get("readinessReports")
    if (
        not isinstance(readiness, dict)
        or readiness.get("firstVisuallyNonEmptyPaint") is not True
        or not isinstance(readiness_reports, list)
        or not any(
            isinstance(report, dict)
            and report.get("firstVisuallyNonEmptyPaint") is True
            for report in readiness_reports
        )
    ):
        raise M0Error("M9 first visually non-empty paint evidence is absent")
    focus_reports = result.get("ozoneFocusReports")
    if not isinstance(focus_reports, list) or not any(
        isinstance(report, dict)
        and report.get("keyboardTargetPresent") is True
        and report.get("active") is True
        for report in focus_reports
    ):
        raise M0Error("M9 active Ozone keyboard target evidence is absent")
    text_states = result.get("ozoneTextInputStates")
    if not isinstance(text_states, list) or not any(
        isinstance(state, dict)
        and state.get("focusedClientPresent") is True
        and state.get("editable") is True
        for state in text_states
    ):
        raise M0Error("M9 editable Ozone text state evidence is absent")

    input_evidence = result.get("hostInput")
    if not isinstance(input_evidence, dict):
        raise M0Error("M9 trusted host input evidence is absent")
    if "textareaValue" in input_evidence:
        raise M0Error("M9 trusted host input retained textarea text")
    for field, expected in {
        "readyObserved": True,
        "ctrlLComplete": True,
        "proxyFocusedAfterCtrlL": True,
        "nativeTextAdmissionCount": 1,
        "nativeTextDeliveryCount": 1,
        "nativeTextDeliverySequences": [1],
        "textDeliveryAccepted": True,
        "enterComplete": True,
        "attached": True,
        "deliveryAccepted": True,
        "deliveryRejected": False,
        "pendingDeliveryCount": 0,
        "pendingTextUtf8Bytes": 0,
        "tombstonedDeliveryCount": 0,
        "proxyTextEmpty": True,
        "rejectedRecords": [],
        "cleanupRecords": [],
    }.items():
        if not _exact_json_equal(input_evidence.get(field), expected):
            raise M0Error(f"M9 trusted host input {field} is invalid")
    _require_exact_records(
        input_evidence.get("ctrlLRecords"),
        [
            {
                "type": "keydown",
                "code": "ControlLeft",
                "trusted": True,
                "cancelable": True,
                "canvasFocused": True,
                "accepted": True,
                "defaultPrevented": True,
            },
            {
                "type": "keydown",
                "code": "KeyL",
                "trusted": True,
                "cancelable": True,
                "canvasFocused": True,
                "accepted": True,
                "defaultPrevented": True,
            },
            {
                "type": "keyup",
                "code": "KeyL",
                "trusted": True,
                "cancelable": True,
                "canvasFocused": True,
                "accepted": True,
                "defaultPrevented": True,
            },
            {
                "type": "keyup",
                "code": "ControlLeft",
                "trusted": True,
                "cancelable": True,
                "canvasFocused": True,
                "accepted": True,
                "defaultPrevented": True,
            },
        ],
        "Ctrl+L",
    )
    _require_exact_records(
        input_evidence.get("beforeInputRecords"),
        [
            {
                "inputType": "insertText",
                "dataOmitted": True,
                "dataUtf16Units": len(ADDRESS_TEXT),
                "trusted": True,
                "cancelable": True,
                "isComposing": False,
                "proxyFocused": True,
                "queued": True,
                "defaultPrevented": True,
                "dataUtf8Bytes": len(ADDRESS_TEXT.encode("utf-8")),
                "sequence": 1,
                "nativeDispatched": True,
                "nativeAccepted": True,
            }
        ],
        "beforeinput",
    )
    _require_exact_records(
        input_evidence.get("browserTextDeliveryReports"),
        [{"action": 4, "sessionId": 0, "sequence": 1, "accepted": True}],
        "browser action-4 delivery",
    )
    _require_exact_records(
        input_evidence.get("enterRecords"),
        [
            {
                "type": "keydown",
                "code": "Enter",
                "key": "Enter",
                "trusted": True,
                "cancelable": True,
                "proxyFocused": True,
                "accepted": True,
                "defaultPrevented": True,
            },
            {
                "type": "keyup",
                "code": "Enter",
                "key": "Enter",
                "trusted": True,
                "cancelable": True,
                "proxyFocused": True,
                "accepted": True,
                "defaultPrevented": True,
            },
        ],
        "Enter",
    )


def wait_for_console_marker(
    client: Any,
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    result_queue: queue.Queue[dict[str, Any]],
    deadline: float,
    marker: str,
) -> None:
    """Wait only for an outer-host console witness before trusted input."""

    while time.monotonic() < deadline:
        if browser.poll() is not None:
            raise M0Error(
                f"M9 host browser exited before {marker}: " + "\n".join(browser_stderr)
            )
        try:
            early_result = result_queue.get_nowait()
        except queue.Empty:
            early_result = None
        if early_result is not None:
            raise M0Error(
                f"M9 smoke finished before {marker}: "
                + json.dumps(early_result, sort_keys=True, separators=(",", ":"))
            )
        event = client.next_event(min(0.1, max(0.0, deadline - time.monotonic())))
        if event is None or event.get("method") != "Runtime.consoleAPICalled":
            continue
        params = event.get("params")
        if not isinstance(params, dict) or not isinstance(params.get("args"), list):
            continue
        for argument in params["args"]:
            if (
                isinstance(argument, dict)
                and argument.get("type") == "string"
                and argument.get("value") == marker
            ):
                return
    raise M0Error(f"M9 host did not emit {marker} before its deadline")


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


def wait_for_result(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    result_queue: queue.Queue[dict[str, Any]],
    deadline: float,
) -> dict[str, Any]:
    while time.monotonic() < deadline:
        if browser.poll() is not None:
            raise M0Error(
                "M9 host browser exited before result "
                f"(status {browser.returncode}): " + "\n".join(browser_stderr)
            )
        try:
            return result_queue.get(timeout=min(0.1, max(0.0, deadline - time.monotonic())))
        except queue.Empty:
            continue
    raise M0Error("M9 host browser timed out: " + "\n".join(browser_stderr))


def redact_screenshot_data(result: dict[str, Any]) -> dict[str, Any]:
    redacted = json.loads(json.dumps(result))
    screenshot = redacted.get("recoveryScreenshot")
    if isinstance(screenshot, dict) and isinstance(screenshot.get("dataBase64"), str):
        screenshot["dataBase64"] = "<omitted>"
    return redacted


def _run_cleanup_action(
    cleanup_error: BaseException | None, action: Callable[[], object]
) -> BaseException | None:
    try:
        action()
    except BaseException as exc:
        if cleanup_error is None:
            return exc
    return cleanup_error


def _require_live_leader_for_clean_stop(
    process: subprocess.Popen[str], *, description: str
) -> None:
    """Prove that this runner, rather than a prior exit, stopped a leader.

    ``stop_browser_group`` and ``stop_process_group`` intentionally establish
    group, pipe, and reader cleanup even when a child is already gone.  That
    is useful on failure paths, but it is insufficient evidence for this
    runner's terminal success: an outer browser or relay that died after the
    recovery observation must not be relabeled as a deliberate clean stop.

    A standalone ``poll()`` has a race with the later process-group signal,
    and ``kill()`` alone can report success for an unreaped zombie. Freeze the
    direct child with uncatchable ``SIGSTOP`` and observe its stopped state
    through ``waitid(WNOWAIT)`` before queuing ``SIGTERM`` and resuming it.
    The following group cleanup then handles every descendant and output pipe.
    """

    returncode = process.poll()
    if returncode is not None:
        raise M0Error(
            f"{description} exited before clean-stop (status {returncode})"
        )

    required_waitid_constants = (
        "waitid",
        "P_PID",
        "WEXITED",
        "WSTOPPED",
        "WNOHANG",
        "WNOWAIT",
        "CLD_STOPPED",
    )
    if any(not hasattr(os, constant) for constant in required_waitid_constants):
        raise M0Error(
            f"{description} clean-stop requires waitid stopped-state observation"
        )

    try:
        os.kill(process.pid, signal.SIGSTOP)
    except ProcessLookupError as exc:
        raise M0Error(f"{description} exited before clean-stop") from exc
    except OSError as exc:
        raise M0Error(f"cannot stop {description} leader for clean-stop") from exc

    waitid_options = os.WEXITED | os.WSTOPPED | os.WNOHANG | os.WNOWAIT
    deadline = time.monotonic() + LEADER_STOP_OBSERVATION_SECONDS
    try:
        while True:
            observation = os.waitid(os.P_PID, process.pid, waitid_options)
            if observation is not None:
                if (
                    observation.si_code == os.CLD_STOPPED
                    and observation.si_status == signal.SIGSTOP
                ):
                    break
                raise M0Error(f"{description} exited before clean-stop")
            if time.monotonic() >= deadline:
                raise M0Error(
                    f"{description} did not acknowledge clean-stop before its deadline"
                )
            time.sleep(LEADER_STOP_POLL_SECONDS)
    except (M0Error, OSError, ChildProcessError) as exc:
        try:
            os.kill(process.pid, signal.SIGCONT)
        except ProcessLookupError:
            pass
        except OSError as resume_error:
            raise M0Error(
                f"cannot resume {description} leader after clean-stop failure"
            ) from resume_error
        if isinstance(exc, M0Error):
            raise
        raise M0Error(
            f"cannot observe {description} leader during clean-stop"
        ) from exc

    try:
        # Terminate while the stopped-state witness still holds. SIGCONT below
        # lets a cooperative browser or relay run its normal shutdown handler.
        os.kill(process.pid, signal.SIGTERM)
        os.kill(process.pid, signal.SIGCONT)
    except ProcessLookupError as exc:
        raise M0Error(f"{description} exited during clean-stop") from exc
    except OSError as exc:
        raise M0Error(f"cannot signal {description} leader for clean-stop") from exc


def _join_server(thread: threading.Thread) -> None:
    thread.join(timeout=CLEANUP_TIMEOUT_SECONDS)
    if thread.is_alive():
        raise M0Error("M9 host server did not stop")


def cleanup_server(
    *,
    server: M9WispRecoverySmokeServer | None,
    server_thread: threading.Thread | None,
    server_thread_started: bool,
) -> BaseException | None:
    cleanup_error: BaseException | None = None
    if server is not None:
        if server_thread_started:
            cleanup_error = _run_cleanup_action(
                cleanup_error,
                lambda: shutdown_server_bounded(
                    server,
                    timeout=CLEANUP_TIMEOUT_SECONDS,
                    description="M9 WISP recovery host server",
                ),
            )
        cleanup_error = _run_cleanup_action(cleanup_error, server.server_close)
    if server_thread_started and server_thread is not None:
        cleanup_error = _run_cleanup_action(
            cleanup_error, lambda: _join_server(server_thread)
        )
    if server is not None:
        cleanup_error = _run_cleanup_action(
            cleanup_error,
            lambda: server.join_request_handlers(
                timeout=CLEANUP_TIMEOUT_SECONDS,
                description="M9 WISP recovery host server",
            ),
        )
    return cleanup_error


def _recheck_source_identities(
    *,
    out_dir: Path,
    module_name: str,
    relay_script: Path,
    expected: dict[str, object],
) -> None:
    current = {
        "artifacts": artifact_delivery_identity(
            snapshot_wisp_artifacts(out_dir, module_name), module_name
        ),
        "host": m9_host_delivery_identity(snapshot_m9_host_resources()),
        "relay": wisp_relay_closure_identity(snapshot_wisp_relay_closure(relay_script)),
    }
    if not _exact_json_equal(current, expected):
        raise M0Error("M9 executable, host, or relay input changed during the smoke")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the same-instance Chrome WISP carrier-close recovery smoke."
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
    relay_script = (
        args.relay_script
        if args.relay_script.is_absolute()
        else REPO_ROOT / args.relay_script
    )
    diagnostics_dir = args.diagnostics_dir or out_dir / "diagnostics"
    if not diagnostics_dir.is_absolute():
        diagnostics_dir = REPO_ROOT / diagnostics_dir

    server: M9WispRecoverySmokeServer | None = None
    server_thread: threading.Thread | None = None
    server_thread_started = False
    browser: subprocess.Popen[str] | None = None
    browser_path: Path | None = None
    browser_version: str | None = None
    browser_stderr: deque[str] = deque(maxlen=300)
    browser_stderr_reader: BrowserStderrReader | None = None
    browser_stderr_stream: TextIO | None = None
    client: Any | None = None
    client_closed = False
    relay: subprocess.Popen[str] | None = None
    relay_stdout: deque[str] = deque(maxlen=300)
    relay_stderr: deque[str] = deque(maxlen=300)
    relay_stdout_reader: BrowserStderrReader | None = None
    relay_stderr_reader: BrowserStderrReader | None = None
    relay_stdout_stream: TextIO | None = None
    relay_stderr_stream: TextIO | None = None
    relay_stack: contextlib.ExitStack | None = None
    relay_ready: RelayReady | None = None
    relay_status: dict[str, Any] | None = None
    relay_quiescent_status: dict[str, Any] | None = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    result: dict[str, Any] | None = None
    source_identity: dict[str, object] | None = None
    context: dict[str, object] | None = None
    stage = "initialize"
    primary_error: BaseException | None = None
    browser_cleanup_complete = False
    relay_cleanup_complete = False
    server_cleanup_complete = False
    profile_cleanup_complete = False

    try:
        stage = "snapshot_executable_artifacts"
        artifacts = snapshot_wisp_artifacts(out_dir, args.module_name)
        stage = "verify_optional_data_artifact"
        verify_optional_wisp_data_private_key_pem_artifact(out_dir, args.module_name)
        stage = "snapshot_host_resources"
        host_resources = snapshot_m9_host_resources()
        stage = "snapshot_relay_closure"
        relay_closure = snapshot_wisp_relay_closure(relay_script)
        source_identity = {
            "artifacts": artifact_delivery_identity(artifacts, args.module_name),
            "host": m9_host_delivery_identity(host_resources),
            "relay": wisp_relay_closure_identity(relay_closure),
        }

        stage = "load_manifest"
        manifest = load_manifest()
        versions = manifest_versions(manifest, checked_output(["git", "rev-parse", "HEAD"]))
        context = print_context(
            "run_m9_wasm_browser_wisp_recovery_smoke.py",
            manifest,
            case=CASE,
            scope=SCOPE,
            gn_args=manifest.get("m6_chrome_gn_args", manifest.get("gn_args")),
            module_name=args.module_name,
            host_browser_sandbox=not args.no_sandbox,
            runtime_arguments=[SMOKE_SWITCH, URL_SWITCH + "=" + ADDRESS_TEXT],
            transport="WISP v2.1 local carrier-close recovery",
            fixture_url=ADDRESS_TEXT,
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
            artifact_snapshots=artifacts,
            host_snapshots=host_resources,
        )
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m9-wisp-recovery-server",
            daemon=True,
        )
        server_thread.start()
        server_thread_started = True

        stage = "materialize_relay_snapshot"
        relay_stack = contextlib.ExitStack()
        materialized_relay = relay_stack.enter_context(
            materialized_wisp_relay_closure_from_snapshot(relay_closure)
        )
        relay_command_line = relay_command(node, materialized_relay, m5_host_origin(server))
        stage = "launch_relay"
        relay = subprocess.Popen(
            relay_command_line,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        relay_stdout_stream, relay_stderr_stream = relay.stdout, relay.stderr
        if relay_stdout_stream is None or relay_stderr_stream is None:
            raise M0Error("M9 relay did not provide both owned output pipes")
        ready_lines = RelayReadinessLatch()
        relay_stdout_reader = BrowserStderrReader(
            relay_stdout_stream,
            relay_stdout,
            name="chromium-wasm-m9-wisp-recovery-relay-stdout",
            on_line=lambda text: _queue_relay_ready_line(ready_lines, text),
            on_eof=lambda: _queue_relay_ready_eof(ready_lines),
        )
        relay_stdout_stream = None
        relay_stderr_reader = BrowserStderrReader(
            relay_stderr_stream,
            relay_stderr,
            name="chromium-wasm-m9-wisp-recovery-relay-stderr",
        )
        relay_stderr_stream = None
        relay_stdout_reader.start()
        relay_stderr_reader.start()
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
        profile = tempfile.TemporaryDirectory(prefix="chromium-wasm-m9-wisp-recovery-")
        debug_port = unused_loopback_port()
        stage = "launch_outer_browser"
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
        browser_stderr_stream = browser.stderr
        if browser_stderr_stream is None:
            raise M0Error("M9 host browser did not provide its stderr pipe")
        browser_stderr_reader = BrowserStderrReader(
            browser_stderr_stream,
            browser_stderr,
            name="chromium-wasm-m9-wisp-recovery-browser-stderr",
        )
        browser_stderr_stream = None
        browser_stderr_reader.start()

        deadline = time.monotonic() + args.timeout
        stage = "connect_outer_devtools"
        client = wait_for_page_client(debug_port, url.split("?", 1)[0], deadline)
        stage = "enable_outer_console_observation"
        client.call("Runtime.enable")
        stage = "wait_for_trusted_ctrl_l"
        wait_for_console_marker(
            client, browser, browser_stderr, result_queue, deadline, CDP_CTRL_L_READY
        )
        stage = "dispatch_trusted_ctrl_l"
        client.dispatch_control_shortcut("KeyL", "l", 76)
        stage = "wait_for_trusted_text"
        wait_for_console_marker(
            client,
            browser,
            browser_stderr,
            result_queue,
            deadline,
            CDP_INSERT_TEXT_READY,
        )
        stage = "dispatch_trusted_committed_text"
        client.call("Input.insertText", {"text": ADDRESS_TEXT})
        stage = "wait_for_trusted_enter"
        wait_for_console_marker(
            client, browser, browser_stderr, result_queue, deadline, CDP_ENTER_READY
        )
        stage = "dispatch_trusted_enter"
        dispatch_unmodified_enter(client)
        stage = "wait_for_result"
        result = wait_for_result(browser, browser_stderr, result_queue, deadline)
        stage = "validate_result"
        validate_result(result, expected_versions=versions)
        stage = "wait_for_pre_cleanup_transport"
        relay_status = wait_for_m9_relay_pre_cleanup_status(
            relay_ready.transcript_url,
            timeout_seconds=min(
                CLEANUP_TIMEOUT_SECONDS, max(0.1, deadline - time.monotonic())
            ),
        )
        stage = "validate_relay_status"
        validate_m9_relay_status(relay_status)

        # Do not emit terminal success until every owned process, pipe, server,
        # profile, and immutable-source postflight has completed normally.
        stage = "cleanup_before_pass"
        client.close()
        client_closed = True
        if browser_stderr_reader is None:
            raise M0Error("M9 browser cleanup evidence is missing")
        if browser is None:
            raise M0Error("M9 host browser cleanup evidence is missing")
        _require_live_leader_for_clean_stop(
            browser, description="M9 host browser"
        )
        stop_browser_group(browser, browser_stderr_reader)
        browser_cleanup_complete = True
        stage = "wait_for_relay_quiescence"
        if relay_ready is None or relay_status is None:
            raise M0Error("M9 relay quiescence evidence is missing")
        relay_quiescent_status = wait_for_m9_relay_quiescence(
            relay_ready.transcript_url,
            pre_cleanup_status=relay_status,
            timeout_seconds=CLEANUP_TIMEOUT_SECONDS,
        )
        stage = "stop_relay"
        if relay_stdout_reader is None or relay_stderr_reader is None:
            raise M0Error("M9 relay cleanup evidence is missing")
        if relay is None:
            raise M0Error("M9 relay cleanup evidence is missing")
        _require_live_leader_for_clean_stop(relay, description="M9 WISP relay")
        stop_process_group(
            relay,
            (relay_stdout_reader, relay_stderr_reader),
            description="M9 WISP relay",
        )
        relay_cleanup_complete = True
        relay_stack.close()
        relay_stack = None
        server_cleanup_error = cleanup_server(
            server=server,
            server_thread=server_thread,
            server_thread_started=server_thread_started,
        )
        if server_cleanup_error is not None:
            raise server_cleanup_error
        server_cleanup_complete = True
        profile.cleanup()
        profile_cleanup_complete = True
        stage = "recheck_source_identities"
        if source_identity is None:
            raise M0Error("M9 immutable source identity is missing")
        _recheck_source_identities(
            out_dir=out_dir,
            module_name=args.module_name,
            relay_script=relay_script,
            expected=source_identity,
        )
        print(
            f"{SENTINEL}:ARTIFACT_DELIVERY "
            + json.dumps(source_identity, sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        print(
            f"{SENTINEL}:BROWSER_RESULT "
            + json.dumps(
                redact_screenshot_data(result), sort_keys=True, separators=(",", ":")
            ),
            flush=True,
        )
        print(
            f"{SENTINEL}:RELAY_STATUS "
            + json.dumps(relay_status, sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        print(
            f"{SENTINEL}:RELAY_QUIESCENT_STATUS "
            + json.dumps(
                relay_quiescent_status, sort_keys=True, separators=(",", ":")
            ),
            flush=True,
        )
        print(f"{SENTINEL}:PASS", flush=True)
        return 0
    except (M0Error, OSError, KeyError, TypeError, ValueError, binascii.Error) as exc:
        primary_error = exc
        diagnostics_dir.mkdir(parents=True, exist_ok=True)
        diagnostic_path = diagnostics_dir / "chrome-browser-m9-wisp-recovery-failure.json"
        diagnostic = {
            "schema_version": 1,
            "runner": "run_m9_wasm_browser_wisp_recovery_smoke.py",
            "case": CASE,
            "scope": SCOPE,
            "stage": stage,
            "failure": {"type": type(exc).__name__, "message": str(exc)},
            "context": context,
            "host_browser": {
                "path": str(browser_path) if browser_path else None,
                "version": browser_version,
                "return_code": browser.poll() if browser else None,
                "stderr_tail": list(browser_stderr),
            },
            "relay": {
                "return_code": relay.poll() if relay else None,
                "ready": (
                    {
                        "transcriptUrl": relay_ready.transcript_url,
                        "wispEndpoint": relay_ready.wisp_endpoint,
                    }
                    if relay_ready
                    else None
                ),
                "stdout_tail": list(relay_stdout),
                "stderr_tail": list(relay_stderr),
                "status": relay_status,
                "quiescent_status": relay_quiescent_status,
            },
            "runtime_result": redact_screenshot_data(result) if result else None,
        }
        try:
            temporary = diagnostic_path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(diagnostic, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temporary.replace(diagnostic_path)
            print(
                f"{SENTINEL}:DIAGNOSTICS "
                + json.dumps({"path": str(diagnostic_path)}, sort_keys=True),
                file=sys.stderr,
                flush=True,
            )
        except OSError as diagnostic_error:
            print(
                f"{SENTINEL}:DIAGNOSTICS_FAIL reason={diagnostic_error}",
                file=sys.stderr,
                flush=True,
            )
        print(f"{SENTINEL}:FAIL reason={exc}", file=sys.stderr, flush=True)
        return 1
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        cleanup_error: BaseException | None = None
        if client is not None and not client_closed:
            cleanup_error = _run_cleanup_action(cleanup_error, client.close)
        if browser is not None and not browser_cleanup_complete:
            cleanup_error = _run_cleanup_action(
                cleanup_error,
                lambda: abort_browser_group(
                    browser,
                    browser_stderr_reader,
                    unowned_streams=(
                        (browser_stderr_stream,) if browser_stderr_stream is not None else ()
                    ),
                ),
            )
        if relay is not None and not relay_cleanup_complete:
            readers = tuple(
                reader
                for reader in (relay_stdout_reader, relay_stderr_reader)
                if reader is not None
            )
            cleanup_error = _run_cleanup_action(
                cleanup_error,
                lambda: abort_process_group(
                    relay,
                    readers,
                    description="M9 WISP relay",
                    unowned_streams=tuple(
                        stream
                        for stream in (relay_stdout_stream, relay_stderr_stream)
                        if stream is not None
                    ),
                ),
            )
        if relay_stack is not None:
            cleanup_error = _run_cleanup_action(cleanup_error, relay_stack.close)
        if not server_cleanup_complete:
            server_cleanup_error = cleanup_server(
                server=server,
                server_thread=server_thread,
                server_thread_started=server_thread_started,
            )
            if cleanup_error is None and server_cleanup_error is not None:
                cleanup_error = server_cleanup_error
        if profile is not None and not profile_cleanup_complete:
            cleanup_error = _run_cleanup_action(cleanup_error, profile.cleanup)
        if primary_error is None and cleanup_error is not None:
            raise cleanup_error


if __name__ == "__main__":
    sys.exit(main())
