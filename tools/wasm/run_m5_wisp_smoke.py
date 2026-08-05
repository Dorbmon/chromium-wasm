#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the controlled M5 HTTPS fixture through WISP in a host browser.

The relay is a local, test-only process.  Its first stdout line is a JSON
readiness record with a loopback WISP endpoint and the fixed ``a.test`` HTTPS
fixture URL.  This runner passes those values only to the Wasm host's narrow
M5 test lane; it never loads the fixture with the outer browser or host
``fetch()``.
"""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
import http.client
import ipaddress
import json
from pathlib import Path
import queue
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, TextIO
from urllib.parse import urlencode, urlsplit

from m0_common import (
    M0Error,
    REPO_ROOT,
    checked_output,
    load_manifest,
    parse_timeout,
    print_context,
)
from m3_content_server import create_m3_server
from run_browser_smoke import (
    browser_command,
    drain_stream,
    find_browser,
    stop_browser,
)
from run_content_shell_smoke import manifest_versions


SENTINEL = "CHROMIUM_WASM_M5_WISP"
M5_CASE = "wisp_network_m5"
M5_FIXTURE = "chromium-wasm-m5-network-v1"
M5_TEST_HOSTNAME = "a.test"
M5_HTTPS_FIXTURE_PATH = "/m5/"
M5_REDIRECT_PATH = "/m5/redirect-cookie"
M5_HTTP1_CORS_PATH = "/m5/cors-resource"
M5_TLS_NAME_MISMATCH_PATH = "/m5/tls-name-mismatch"
M5_PLAINTEXT_HTTP_CONTROL_PATH = "/m5/plaintext-control"
M5_MIXED_CONTENT_TARGET_PATH = "/m5/mixed-content-target"
M5_DEVTOOLS_NETWORK_EVENT_ORDER = (
    "Network.requestWillBeSent:redirect",
    "Network.requestWillBeSent:final",
    "Network.responseReceived:final",
    "Network.loadingFinished:final",
    "Network.requestWillBeSent:reconnect",
    "Network.loadingFailed:reconnect",
)
# The relay holds each post-ack response stage for this bounded interval. The
# page must observe both elapsed time and its independent timer while Blink is
# reading the response, rather than treating a fully buffered body as a slow
# stream.
M5_SLOW_STREAM_MIN_ELAPSED_MS = 75
M5_SLOW_STREAM_MIN_TIMER_TICKS_WHILE_WAITING = 2
M5_SLOW_STREAM_MIN_STAGE_DELAY_MS = 75
M5_SLOW_STREAM_MIN_CONSUMER_PAUSE_MS = 75
M5_SLOW_STREAM_MIN_CONSUMER_PAUSE_TIMER_TICKS = 2
M5_SLOW_STREAM_MIN_HOST_TIMER_TICKS = 2
M5_SLOW_STREAM_MIN_HOST_ANIMATION_FRAMES = 2
M5_SLOW_STREAM_MAX_HOST_TIMER_GAP_MS = 250
M5_SLOW_STREAM_CONSUMER_BURST_BYTES = 64 * 1024
M5_LARGE_DOWNLOAD_BYTES = 512 * 1024
M5_LARGE_DOWNLOAD_CHUNK_BYTES = 16 * 1024
M5_LARGE_DOWNLOAD_CHUNKS = M5_LARGE_DOWNLOAD_BYTES // M5_LARGE_DOWNLOAD_CHUNK_BYTES
M5_BROWSER_WINDOW_SIZE = "1280,800"
MAXIMUM_RELAY_READY_LINE_BYTES = 16 * 1024
MAXIMUM_RELAY_STATUS_BYTES = 256 * 1024
PRIVATE_KEY_PEM_MARKERS = (
    b"-----BEGIN PRIVATE KEY-----",
    b"-----BEGIN ENCRYPTED PRIVATE KEY-----",
    b"-----BEGIN RSA PRIVATE KEY-----",
    b"-----BEGIN EC PRIVATE KEY-----",
)
ARTIFACT_SCAN_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class RelayReady:
    """The bounded, public readiness information from the local relay."""

    wisp_endpoint: str
    https_url: str
    redirect_url: str
    plaintext_http_control_url: str
    mixed_content_target_url: str
    http1_url: str
    tls_failure_url: str
    transcript_url: str


def _validated_port(parsed: Any, description: str) -> int:
    try:
        port = parsed.port
    except ValueError as exc:
        raise M0Error(f"{description} has an invalid port") from exc
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise M0Error(f"{description} must include a port")
    return port


def _is_loopback_hostname(hostname: str) -> bool:
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def validate_wisp_endpoint(value: object) -> str:
    """Accept only a local, credential-free WebSocket relay endpoint."""

    if not isinstance(value, str) or not value:
        raise M0Error("relay wispEndpoint must be a nonempty string")
    if len(value.encode("utf-8")) > 2048:
        raise M0Error("relay wispEndpoint is too long")
    parsed = urlsplit(value)
    if parsed.scheme not in ("ws", "wss"):
        raise M0Error("relay wispEndpoint must use ws or wss")
    if (
        not parsed.hostname
        or not _is_loopback_hostname(parsed.hostname)
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise M0Error("relay wispEndpoint is not a safe loopback URL")
    _validated_port(parsed, "relay wispEndpoint")
    if not parsed.path.startswith("/") or not parsed.path.endswith("/"):
        raise M0Error("relay wispEndpoint must have a slash-terminated path")
    return value


def validate_m5_https_url(
    value: object,
    *,
    description: str = "relay httpsUrl",
    expected_path: str = M5_HTTPS_FIXTURE_PATH,
) -> str:
    """Accept one exact HTTPS M5 fixture URL."""

    if not isinstance(value, str) or not value:
        raise M0Error(f"{description} must be a nonempty string")
    if len(value.encode("utf-8")) > 2048:
        raise M0Error(f"{description} is too long")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != M5_TEST_HOSTNAME
        or parsed.username is not None
        or parsed.password is not None
        or "@" in parsed.netloc
        or parsed.query
        or parsed.fragment
        or "?" in value
        or "#" in value
        or parsed.path != expected_path
    ):
        raise M0Error(f"{description} violates the M5 fixture policy")
    _validated_port(parsed, description)
    return value


def validate_m5_redirect_url(value: object, *, https_url: str) -> str:
    """Accept a distinct M5 redirect source on the H2 fixture listener."""

    redirect_url = validate_m5_https_url(
        value,
        description="relay redirectUrl",
        expected_path=M5_REDIRECT_PATH,
    )
    h2_port = _validated_port(urlsplit(https_url), "relay httpsUrl")
    redirect_port = _validated_port(
        urlsplit(redirect_url), "relay redirectUrl"
    )
    if redirect_port != h2_port:
        raise M0Error("relay redirectUrl must use the H2 fixture port")
    if redirect_url == https_url:
        raise M0Error("relay redirectUrl must differ from relay httpsUrl")
    return redirect_url


def _validate_m5_plaintext_http_url(
    value: object, *, description: str, expected_path: str
) -> str:
    """Accept one exact plaintext M5 fixture URL."""

    if not isinstance(value, str) or not value:
        raise M0Error(f"{description} must be a nonempty string")
    if len(value.encode("utf-8")) > 2048:
        raise M0Error(f"{description} is too long")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname != M5_TEST_HOSTNAME
        or parsed.username
        or parsed.password
        or "@" in parsed.netloc
        or parsed.query
        or parsed.fragment
        or "?" in value
        or "#" in value
        or parsed.path != expected_path
    ):
        raise M0Error(f"{description} violates the M5 plaintext fixture policy")
    _validated_port(parsed, description)
    return value


def validate_m5_plaintext_http_control_url(value: object) -> str:
    """Accept only the fixed M5 plaintext HTTP control navigation."""

    return _validate_m5_plaintext_http_url(
        value,
        description="relay plaintextHttpControlUrl",
        expected_path=M5_PLAINTEXT_HTTP_CONTROL_PATH,
    )


def validate_m5_mixed_content_target_url(
    value: object, *, plaintext_http_control_url: str
) -> str:
    """Accept the exact M5 active mixed-content target on the control port."""

    mixed_content_target_url = _validate_m5_plaintext_http_url(
        value,
        description="relay mixedContentTargetUrl",
        expected_path=M5_MIXED_CONTENT_TARGET_PATH,
    )
    control_port = _validated_port(
        urlsplit(plaintext_http_control_url), "relay plaintextHttpControlUrl"
    )
    target_port = _validated_port(
        urlsplit(mixed_content_target_url), "relay mixedContentTargetUrl"
    )
    if target_port != control_port:
        raise M0Error(
            "relay mixedContentTargetUrl must use the plaintext control port"
        )
    return mixed_content_target_url


def validate_relay_transcript_url(value: object) -> str:
    """Accept only the relay's local, fixed-path diagnostic endpoint."""

    if not isinstance(value, str) or not value:
        raise M0Error("relay transcriptUrl must be a nonempty string")
    if len(value.encode("utf-8")) > 2048:
        raise M0Error("relay transcriptUrl is too long")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or not parsed.hostname
        or not _is_loopback_hostname(parsed.hostname)
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path != "/status"
    ):
        raise M0Error("relay transcriptUrl is not a safe loopback status URL")
    _validated_port(parsed, "relay transcriptUrl")
    return value


def parse_relay_ready_line(line: str) -> RelayReady:
    """Parse and validate the relay's first JSON stdout line."""

    if not isinstance(line, str):
        raise M0Error("relay readiness line must be text")
    if len(line.encode("utf-8")) > MAXIMUM_RELAY_READY_LINE_BYTES:
        raise M0Error("relay readiness line is too long")
    try:
        ready = json.loads(line)
    except json.JSONDecodeError as exc:
        raise M0Error("relay readiness line is not valid JSON") from exc
    if not isinstance(ready, dict):
        raise M0Error("relay readiness line must be a JSON object")
    schema_version = ready.get("schema_version")
    if schema_version is not None and schema_version != 1:
        raise M0Error("relay readiness schema version is unsupported")
    https_url = validate_m5_https_url(ready.get("httpsUrl"))
    redirect_url = validate_m5_redirect_url(
        ready.get("redirectUrl"), https_url=https_url
    )
    plaintext_http_control_url = validate_m5_plaintext_http_control_url(
        ready.get("plaintextHttpControlUrl")
    )
    mixed_content_target_url = validate_m5_mixed_content_target_url(
        ready.get("mixedContentTargetUrl"),
        plaintext_http_control_url=plaintext_http_control_url,
    )
    http1_url = validate_m5_https_url(
        ready.get("http1Url"),
        description="relay http1Url",
        expected_path=M5_HTTP1_CORS_PATH,
    )
    tls_failure_url = validate_m5_https_url(
        ready.get("tlsFailureUrl"),
        description="relay tlsFailureUrl",
        expected_path=M5_TLS_NAME_MISMATCH_PATH,
    )
    h2_port = _validated_port(urlsplit(https_url), "relay httpsUrl")
    h1_port = _validated_port(urlsplit(http1_url), "relay http1Url")
    tls_failure_port = _validated_port(
        urlsplit(tls_failure_url), "relay tlsFailureUrl"
    )
    plaintext_http_control_port = _validated_port(
        urlsplit(plaintext_http_control_url), "relay plaintextHttpControlUrl"
    )
    if tls_failure_port in (h2_port, h1_port, plaintext_http_control_port):
        raise M0Error("relay tlsFailureUrl must use a distinct fixture port")
    if plaintext_http_control_port in (h2_port, h1_port):
        raise M0Error(
            "relay plaintextHttpControlUrl must use a distinct fixture port"
        )
    return RelayReady(
        wisp_endpoint=validate_wisp_endpoint(ready.get("wispEndpoint")),
        https_url=https_url,
        redirect_url=redirect_url,
        plaintext_http_control_url=plaintext_http_control_url,
        mixed_content_target_url=mixed_content_target_url,
        http1_url=http1_url,
        tls_failure_url=tls_failure_url,
        transcript_url=validate_relay_transcript_url(
            ready.get("transcriptUrl")
        ),
    )


def m5_host_origin(server: Any) -> str:
    """Return the exact local origin that serves the COOP/COEP host page."""

    host, port = server.server_address[:2]
    host = str(host)
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{int(port)}"


def m5_smoke_url(
    server: Any,
    token: str,
    versions: dict[str, str],
    *,
    relay_ready: RelayReady,
    module_name: str = "content_shell_wasm_m5_test",
    timeout_seconds: float = 120.0,
) -> str:
    """Build the tokenized host URL for the narrow M5 network case."""

    # Validate again at the call boundary so no caller can accidentally put a
    # nonlocal relay endpoint or arbitrary navigation URL into the host query.
    wisp_endpoint = validate_wisp_endpoint(relay_ready.wisp_endpoint)
    https_url = validate_m5_https_url(relay_ready.https_url)
    redirect_url = validate_m5_redirect_url(
        relay_ready.redirect_url, https_url=https_url
    )
    plaintext_http_control_url = validate_m5_plaintext_http_control_url(
        relay_ready.plaintext_http_control_url
    )
    validate_m5_mixed_content_target_url(
        relay_ready.mixed_content_target_url,
        plaintext_http_control_url=plaintext_http_control_url,
    )
    http1_url = validate_m5_https_url(
        relay_ready.http1_url,
        description="relay http1Url",
        expected_path=M5_HTTP1_CORS_PATH,
    )
    tls_failure_url = validate_m5_https_url(
        relay_ready.tls_failure_url,
        description="relay tlsFailureUrl",
        expected_path=M5_TLS_NAME_MISMATCH_PATH,
    )
    h2_port = _validated_port(urlsplit(https_url), "relay httpsUrl")
    h1_port = _validated_port(urlsplit(http1_url), "relay http1Url")
    plaintext_http_control_port = _validated_port(
        urlsplit(plaintext_http_control_url), "relay plaintextHttpControlUrl"
    )
    tls_failure_port = _validated_port(
        urlsplit(tls_failure_url), "relay tlsFailureUrl"
    )
    if plaintext_http_control_port in (h2_port, h1_port):
        raise M0Error(
            "relay plaintextHttpControlUrl must use a distinct fixture port"
        )
    if tls_failure_port in (h2_port, h1_port, plaintext_http_control_port):
        raise M0Error("relay tlsFailureUrl must use a distinct fixture port")
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "case": M5_CASE,
            "chromium": versions["chromium"],
            "emscripten": versions["emscripten"],
            "m5_url": redirect_url,
            "m5_plaintext_http_control_url": plaintext_http_control_url,
            "m5_tls_failure_url": tls_failure_url,
            "module": f"/__m3__/artifacts/{module_name}.js",
            "port": versions["port"],
            "token": token,
            "timeout_ms": max(1000, min(180000, int(timeout_seconds * 1000))),
            "v8": versions["v8"],
            "wisp_endpoint": wisp_endpoint,
        }
    )
    return f"http://{host}:{port}/__m3__/?{query}"


def m5_browser_command(
    browser: Path, profile: str, url: str, *, no_sandbox: bool
) -> list[str]:
    """Launch a viewport that contains the entire fixed host canvas."""

    command = browser_command(browser, profile, url, no_sandbox=no_sandbox)
    command[1:1] = [f"--window-size={M5_BROWSER_WINDOW_SIZE}"]
    return command


def verify_no_private_key_pem_artifacts(
    out_dir: Path, module_name: str
) -> None:
    """Reject test artifacts that embed a PEM private key.

    The controlled trust root is a generated DER include. Chromium carries
    generic certificate-parser strings, so search only complete PEM key
    headers rather than broad terms such as ``PRIVATE KEY``.
    """

    longest_marker = max(len(marker) for marker in PRIVATE_KEY_PEM_MARKERS)
    for suffix in (".js", ".wasm", ".data"):
        artifact = out_dir / f"{module_name}{suffix}"
        if not artifact.is_file():
            continue
        previous = b""
        with artifact.open("rb") as stream:
            while chunk := stream.read(ARTIFACT_SCAN_CHUNK_BYTES):
                payload = previous + chunk
                if any(marker in payload for marker in PRIVATE_KEY_PEM_MARKERS):
                    raise M0Error(
                        "M5 test artifact embeds a PEM private-key header: "
                        f"{artifact.name}"
                    )
                previous = payload[-(longest_marker - 1) :]


def find_node(explicit: Path | None) -> Path:
    """Find the pinned Node runtime, allowing an explicit test override."""

    if explicit is not None:
        candidate = explicit.expanduser().resolve()
        if not candidate.is_file():
            raise M0Error("--node does not name an executable file")
        return candidate

    # Keep the M5 relay on Chromium's pinned Node before accepting a host
    # installation from PATH.  The latter remains a useful local fallback.
    candidates = [
        REPO_ROOT / "third_party/emsdk/node/22.16.0_64bit/bin/node"
    ]
    node_on_path = shutil.which("node")
    if node_on_path:
        candidates.append(Path(node_on_path))
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved.is_file():
            return resolved
    raise M0Error("no Node executable found; pass --node")


def relay_command(node: Path, relay_script: Path, host_origin: str) -> list[str]:
    return [str(node), str(relay_script), "--host-origin", host_origin]


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
    """Wait for exactly the first nonempty relay stdout line to be JSON."""

    while time.monotonic() < deadline:
        if relay.poll() is not None:
            raise M0Error(
                "M5 relay exited before readiness "
                f"(status {relay.returncode}): " + "\n".join(relay_stderr)
            )
        remaining = deadline - time.monotonic()
        try:
            line = ready_lines.get(timeout=min(0.1, max(0.0, remaining)))
        except queue.Empty:
            continue
        if line is None:
            raise M0Error("M5 relay closed stdout before readiness")
        return parse_relay_ready_line(line)
    raise M0Error("M5 relay readiness timeout: " + "\n".join(relay_stderr))


def _require_dict(value: object, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise M0Error(f"{description} is not an object")
    return value


def _require_positive_integer(value: object, description: str) -> int:
    if type(value) is not int or value < 1:
        raise M0Error(f"{description} is not a positive integer")
    return value


def validate_m5_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
    relay_ready: RelayReady,
) -> None:
    """Require Chromium evidence across plaintext, HTTPS, and TLS phases."""

    plaintext_http_control_url = validate_m5_plaintext_http_control_url(
        relay_ready.plaintext_http_control_url
    )
    mixed_content_target_url = validate_m5_mixed_content_target_url(
        relay_ready.mixed_content_target_url,
        plaintext_http_control_url=plaintext_http_control_url,
    )

    expected = {
        "protocol": 1,
        "case": M5_CASE,
        "status": "pass",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "versions": expected_versions,
        "failedChecks": [],
        "error": None,
    }
    for field, expected_value in expected.items():
        actual = result.get(field)
        if type(actual) is not type(expected_value) or actual != expected_value:
            raise M0Error(
                f"M5 result {field} mismatch: expected {expected_value!r}, "
                f"got {actual!r}"
            )

    initial_frame = _require_dict(result.get("initialFrame"), "M5 initial frame")
    _require_positive_integer(initial_frame.get("id"), "M5 initial frame ID")
    if initial_frame.get("width") != 800 or initial_frame.get("height") != 600:
        raise M0Error("M5 initial frame dimensions do not match the canvas")

    plaintext_http_control_navigation_result = _require_dict(
        result.get("plaintextHttpControlNavigationResult"),
        "M5 plaintext HTTP control navigation result",
    )
    if plaintext_http_control_navigation_result != {
        "ok": True,
        "scheme": "http",
        "hostname": M5_TEST_HOSTNAME,
    }:
        raise M0Error(
            "M5 plaintext HTTP control navigation result does not identify "
            "the fixture"
        )
    plaintext_http_control_readiness = _require_dict(
        result.get("plaintextHttpControlReadiness"),
        "M5 plaintext HTTP control readiness",
    )
    for field in (
        "runtimeInitialized",
        "shellReady",
        "surfaceReady",
        "navigationCommitted",
        "pageReady",
    ):
        if plaintext_http_control_readiness.get(field) is not True:
            raise M0Error(
                f"M5 plaintext HTTP control readiness field {field} is not true"
            )
    if plaintext_http_control_readiness.get("fatalErrors") != []:
        raise M0Error("M5 plaintext HTTP control readiness reported fatal errors")
    plaintext_http_control_navigation = _require_dict(
        plaintext_http_control_readiness.get("navigation"),
        "M5 plaintext HTTP control navigation",
    )
    if plaintext_http_control_navigation != {"committed": True, "scheme": "http"}:
        raise M0Error("M5 plaintext HTTP control did not commit the HTTP navigation")
    plaintext_http_control_heartbeat = _require_dict(
        plaintext_http_control_readiness.get("heartbeat"),
        "M5 plaintext HTTP control heartbeat",
    )
    if (
        plaintext_http_control_heartbeat.get("anchor")
        != "m5-plaintext-http-control-navigation-committed"
    ):
        raise M0Error(
            "M5 plaintext HTTP control heartbeat was not anchored to HTTP "
            "navigation"
        )
    plaintext_http_control_probe = _require_dict(
        plaintext_http_control_readiness.get("pageProbe"),
        "M5 plaintext HTTP control page probe",
    )
    for field, expected_value in {
        "protocol": 1,
        "fixture": M5_FIXTURE,
        "ready": True,
        "phase": "plaintext-http-control",
        "plaintextHttpControlDocument": True,
        "plaintextHttpControlProof": True,
    }.items():
        actual = plaintext_http_control_probe.get(field)
        if type(actual) is not type(expected_value) or actual != expected_value:
            raise M0Error(
                f"M5 plaintext HTTP control page probe {field} mismatch: "
                f"expected {expected_value!r}, got {actual!r}"
            )

    navigation_result = _require_dict(
        result.get("navigationResult"), "M5 navigation result"
    )
    if navigation_result != {
        "ok": True,
        "scheme": "https",
        "hostname": M5_TEST_HOSTNAME,
    }:
        raise M0Error("M5 navigation result does not identify the HTTPS fixture")

    readiness = _require_dict(result.get("readiness"), "M5 readiness")
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
            raise M0Error(f"M5 readiness field {field} is not true")
    if readiness.get("fatalErrors") != []:
        raise M0Error("M5 readiness reported fatal errors")
    navigation = _require_dict(readiness.get("navigation"), "M5 navigation")
    if navigation != {"committed": True, "scheme": "https"}:
        raise M0Error("M5 readiness did not commit the HTTPS navigation")
    devtools_network_enabled = _require_dict(
        result.get("devtoolsNetworkEnabled"), "M5 DevTools Network enable"
    )
    if devtools_network_enabled != {
        "protocol": 1,
        "state": "enabled",
        "networkEnabled": True,
        "events": [],
    }:
        raise M0Error("M5 DevTools Network.enable did not complete cleanly")
    devtools_network = _require_dict(
        readiness.get("devtoolsNetwork"), "M5 DevTools Network log"
    )
    expected_devtools_network = {
        "protocol": 1,
        "state": "complete",
        "networkEnabled": True,
        "redirectRequest": True,
        "finalRequest": True,
        "responseReceived": True,
        "loadingFinished": True,
        "requestIdCorrelated": True,
        "responseStatus": 200,
        "responseProtocol": "h2",
        "reconnectRequest": True,
        "reconnectLoadingFailed": True,
        "reconnectRequestIdCorrelated": True,
        "reconnectInternetDisconnected": True,
        "events": list(M5_DEVTOOLS_NETWORK_EVENT_ORDER),
    }
    if devtools_network != expected_devtools_network:
        raise M0Error(
            "M5 DevTools Network log does not contain the bounded Chromium "
            "CDP request/response/completion trace"
        )
    m5_download = _require_dict(
        readiness.get("m5Download"), "M5 DownloadManager log"
    )
    expected_m5_download = {
        "protocol": 1,
        "state": "complete",
        "singleDownload": True,
        "navigationSource": True,
        "responseStatusMatched": True,
        "contentDispositionMatched": True,
        "mimeTypeMatched": True,
        "allDataSaved": True,
        "targetPathDetermined": True,
        "targetDirectoryMatched": True,
        "interruptReasonNone": True,
        "totalBytes": M5_LARGE_DOWNLOAD_BYTES,
        "receivedBytes": M5_LARGE_DOWNLOAD_BYTES,
        "filePatternVerified": True,
    }
    if m5_download != expected_m5_download:
        raise M0Error(
            "M5 DownloadManager log does not contain the fixed native "
            "attachment completion evidence"
        )
    heartbeat = _require_dict(readiness.get("heartbeat"), "M5 heartbeat")
    if heartbeat.get("anchor") != "m5-https-navigation-committed":
        raise M0Error("M5 heartbeat was not anchored to HTTPS navigation")
    slow_stream_heartbeat = _require_dict(
        result.get("slowStreamHeartbeat"), "M5 slow-stream host heartbeat"
    )
    if slow_stream_heartbeat.get("anchor") != "m5-https-navigation-committed":
        raise M0Error(
            "M5 slow-stream host heartbeat was not anchored to HTTPS navigation"
        )
    for field, minimum in (
        ("elapsedMs", M5_SLOW_STREAM_MIN_ELAPSED_MS),
        ("timerDelta", M5_SLOW_STREAM_MIN_HOST_TIMER_TICKS),
        ("animationFrameDelta", M5_SLOW_STREAM_MIN_HOST_ANIMATION_FRAMES),
    ):
        actual = slow_stream_heartbeat.get(field)
        if type(actual) not in (int, float) or not (actual >= minimum):
            raise M0Error(
                f"M5 slow-stream host heartbeat {field} must be at least "
                f"{minimum}, got {actual!r}"
            )
    for field in ("timerDelta", "animationFrameDelta"):
        if type(slow_stream_heartbeat[field]) is not int:
            raise M0Error(
                f"M5 slow-stream host heartbeat {field} must be an integer"
            )
    max_timer_gap_ms = slow_stream_heartbeat.get("maxTimerGapMs")
    if type(max_timer_gap_ms) not in (int, float) or not (
        0 <= max_timer_gap_ms <= M5_SLOW_STREAM_MAX_HOST_TIMER_GAP_MS
    ):
        raise M0Error(
            "M5 slow-stream host heartbeat maxTimerGapMs is outside the "
            "bounded responsive range"
        )

    page_probe = _require_dict(readiness.get("pageProbe"), "M5 page probe")
    expected_probe = {
        "protocol": 1,
        "fixture": M5_FIXTURE,
        "ready": True,
        "h2Fetch": True,
        "h2Protocol": "h2",
        "corsFetch": True,
        "webSocketEcho": True,
        "altSvcH3Advertised": True,
        "redirected": True,
        "cacheStored": True,
        "cacheRevalidated": True,
        "cancelStreamStarted": True,
        "cancelStreamReceivedFirstChunk": True,
        "cancelStreamAborted": True,
        "cancelStreamErrorName": "AbortError",
        "cancelStreamProof": True,
        "slowStreamStarted": True,
        "slowStreamFirstStage": True,
        "slowStreamSecondStage": True,
        "slowStreamThirdStage": True,
        "slowStreamComplete": True,
        "slowStreamProof": True,
        "slowStreamConsumerPauseStarted": True,
        "slowStreamConsumerBurstRead": True,
        "slowStreamConsumerResume": True,
        "largeDownloadNavigationRequested": True,
        "largeDownloadNativeComplete": True,
        "reconnectStreamStarted": True,
        "reconnectFirstChunkReceived": True,
        "reconnectFirstChunkAck": True,
        "reconnectDisconnectRequested": True,
        "reconnectStreamFailed": True,
        "reconnectStreamErrorName": "TypeError",
        "reconnectRecovered": True,
        "reconnectRecoveryProtocol": "h2",
        "cspConnectSrcBlocked": True,
        "phase": "https-fixture",
        "activeMixedContentBlocked": True,
        "activeMixedContentErrorName": "TypeError",
        "activeMixedContentCspAllowed": True,
    }
    for field, expected_value in expected_probe.items():
        actual = page_probe.get(field)
        if type(actual) is not type(expected_value) or actual != expected_value:
            raise M0Error(
                f"M5 page probe {field} mismatch: expected "
                f"{expected_value!r}, got {actual!r}"
            )
    for field, minimum in (
        ("slowStreamElapsedMs", M5_SLOW_STREAM_MIN_ELAPSED_MS),
        (
            "slowStreamFirstToSecondStageDelayMs",
            M5_SLOW_STREAM_MIN_STAGE_DELAY_MS,
        ),
        (
            "slowStreamSecondToThirdStageDelayMs",
            M5_SLOW_STREAM_MIN_STAGE_DELAY_MS,
        ),
        (
            "slowStreamConsumerPauseElapsedMs",
            M5_SLOW_STREAM_MIN_CONSUMER_PAUSE_MS,
        ),
        (
            "slowStreamConsumerPauseTimerTicks",
            M5_SLOW_STREAM_MIN_CONSUMER_PAUSE_TIMER_TICKS,
        ),
        (
            "slowStreamTimerTicksWhileWaiting",
            M5_SLOW_STREAM_MIN_TIMER_TICKS_WHILE_WAITING,
        ),
    ):
        actual = page_probe.get(field)
        if type(actual) is not int or actual < minimum:
            raise M0Error(
                f"M5 page probe {field} must be an integer at least "
                f"{minimum}, got {actual!r}"
            )
    if page_probe.get("activeMixedContentTargetUrl") != mixed_content_target_url:
        raise M0Error(
            "M5 page probe activeMixedContentTargetUrl does not match the "
            "relay fixture target"
        )
    nonce = page_probe.get("nonce")
    if not isinstance(nonce, str) or not nonce:
        raise M0Error("M5 page probe has no fixture nonce")

    tls_failure_navigation_result = _require_dict(
        result.get("tlsFailureNavigationResult"),
        "M5 TLS-failure navigation result",
    )
    if tls_failure_navigation_result != {
        "ok": True,
        "scheme": "https",
        "hostname": M5_TEST_HOSTNAME,
    }:
        raise M0Error(
            "M5 TLS-failure navigation result does not identify the HTTPS "
            "fixture"
        )
    tls_failure_readiness = _require_dict(
        result.get("tlsFailureReadiness"), "M5 TLS-failure readiness"
    )
    tls_failure_navigation = _require_dict(
        tls_failure_readiness.get("navigation"), "M5 TLS-failure navigation"
    )
    expected_tls_failure_navigation = {
        "committed": False,
        "scheme": "https",
        "netError": -200,
    }
    for field, expected_value in expected_tls_failure_navigation.items():
        actual = tls_failure_navigation.get(field)
        if type(actual) is not type(expected_value) or actual != expected_value:
            raise M0Error(
                f"M5 TLS-failure navigation {field} mismatch: expected "
                f"{expected_value!r}, got {actual!r}"
            )
    if tls_failure_readiness.get("navigationCommitted") is not False:
        raise M0Error("M5 TLS-failure readiness unexpectedly committed")
    if tls_failure_readiness.get("fatalErrors") != []:
        raise M0Error("M5 TLS-failure readiness reported fatal errors")
    tls_failure_heartbeat = _require_dict(
        tls_failure_readiness.get("heartbeat"), "M5 TLS-failure heartbeat"
    )
    if tls_failure_heartbeat.get("anchor") != "m5-https-navigation-tls-rejected":
        raise M0Error("M5 TLS-failure heartbeat was not natively rejected")

    logs = _require_dict(result.get("logs"), "M5 logs")
    for stream in ("host", "stdout", "stderr"):
        if not isinstance(logs.get(stream), list):
            raise M0Error(f"M5 {stream} log is not an array")
    host_logs = logs["host"]
    required_host_markers = (
        "initialize:wisp-configured",
        "m5:devtools-network:enabled",
        "navigation:requested:m5-plaintext-http-control",
        "navigation:committed:m5-plaintext-http-control",
        "navigation:requested:m5-https",
        "m5:download-manager:complete",
        "m5:devtools-network:complete",
        "navigation:requested:m5-https-tls-failure",
        "navigation:failed:m5-https:-200",
        "shutdown:complete",
    )
    for marker in required_host_markers:
        if marker not in host_logs:
            raise M0Error(f"M5 host logs are missing {marker!r}")
    for marker in required_host_markers[1:]:
        if host_logs.count(marker) != 1:
            raise M0Error(f"M5 host logs must contain exactly one {marker!r}")
    if not (
        host_logs.index("m5:devtools-network:enabled")
        < host_logs.index("navigation:requested:m5-plaintext-http-control")
        < host_logs.index("navigation:committed:m5-plaintext-http-control")
        < host_logs.index("navigation:requested:m5-https")
        < host_logs.index("m5:download-manager:complete")
        < host_logs.index("m5:devtools-network:complete")
        < host_logs.index("navigation:requested:m5-https-tls-failure")
        < host_logs.index("navigation:failed:m5-https:-200")
        < host_logs.index("shutdown:complete")
    ):
        raise M0Error("M5 host logs do not preserve the M5 phase order")
    if host_logs[-1:] != ["shutdown:complete"]:
        raise M0Error("M5 host logs do not end with clean shutdown")

    shutdown = _require_dict(result.get("shutdown"), "M5 shutdown")
    for field in ("ok", "accepted", "complete"):
        if shutdown.get(field) is not True:
            raise M0Error(f"M5 shutdown {field} is not true")
    for field in ("exitCode", "runtimeExitCode"):
        if shutdown.get(field) != 0:
            raise M0Error(f"M5 shutdown {field} is not zero")


def fetch_relay_transcript(
    transcript_url: str, *, timeout_seconds: float
) -> dict[str, Any]:
    """Fetch bounded relay metadata without following redirects or proxies."""

    validated_url = validate_relay_transcript_url(transcript_url)
    parsed = urlsplit(validated_url)
    assert parsed.hostname is not None
    port = _validated_port(parsed, "relay transcriptUrl")
    connection = http.client.HTTPConnection(
        parsed.hostname, port, timeout=timeout_seconds
    )
    try:
        connection.request(
            "GET",
            parsed.path,
            headers={"Accept": "application/json", "Cache-Control": "no-store"},
        )
        response = connection.getresponse()
        body = response.read(MAXIMUM_RELAY_STATUS_BYTES + 1)
        content_type = response.getheader("Content-Type") or ""
        if response.status != 200:
            raise M0Error(
                f"relay transcript endpoint returned HTTP {response.status}"
            )
        if not content_type.lower().startswith("application/json"):
            raise M0Error("relay transcript endpoint did not return JSON")
    except (OSError, http.client.HTTPException) as exc:
        raise M0Error(f"cannot read relay transcript: {exc}") from exc
    finally:
        connection.close()
    if len(body) > MAXIMUM_RELAY_STATUS_BYTES:
        raise M0Error("relay transcript response is too large")
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise M0Error("relay transcript response is not valid JSON") from exc
    return _require_dict(value, "relay transcript")


def validate_relay_transcript(
    status: dict[str, Any], *, relay_ready: RelayReady
) -> None:
    """Require relay-side evidence for the inner Chromium traffic."""

    if status.get("fixture") != M5_FIXTURE or status.get("protocol") != 1:
        raise M0Error("relay transcript fixture or protocol mismatch")
    if status.get("ready") is not True:
        raise M0Error("relay transcript did not report readiness")
    if status.get("plaintextHttpControlPhase") != "post-control":
        raise M0Error("relay plaintext HTTP control phase did not reach post-control")
    if status.get("cancelStreamPhase") != "cancel-observed":
        raise M0Error("relay cancel stream phase did not observe an HTTP/2 CANCEL")
    if status.get("slowStreamPhase") != "complete":
        raise M0Error("relay slow stream phase did not complete")
    if status.get("largeDownloadPhase") != "complete":
        raise M0Error("relay large download phase did not complete")
    if status.get("reconnectPhase") != "recovered":
        raise M0Error("relay reconnect phase did not recover on a fresh session")
    for field in (
        "activeWispSessions",
        "wispSessions",
        "rejectedDestinations",
        "udpPackets",
        "relayErrors",
        "corsRequests",
        "webSocketEchoes",
        "redirectRequests",
        "redirectCookieValidations",
        "cacheStore200s",
        "cacheConditionalRequests",
        "cacheNotModified304s",
        "cacheUnexpectedRequests",
        "cancelStreamRequests",
        "cancelStreamFirstChunks",
        "cancelStreamCancelResets",
        "cancelStreamProofs",
        "cancelStreamProofSessionMismatches",
        "cancelStreamProofTimeouts",
        "cancelStreamUnexpectedResets",
        "largeDownloadBackpressureEvents",
        "largeDownloadBytes",
        "largeDownloadChunks",
        "largeDownloadCompletions",
        "largeDownloadRequests",
        "largeDownloadUnexpectedCloses",
        "reconnectDisconnectRequests",
        "reconnectFirstChunkAcks",
        "reconnectFirstChunks",
        "reconnectRecoveryRequests",
        "reconnectSessionMismatches",
        "reconnectStreamRequests",
        "reconnectUnexpectedCloses",
        "reconnectUnexpectedRetries",
        "slowStreamRequests",
        "slowStreamFirstStages",
        "slowStreamSecondStages",
        "slowStreamThirdStages",
        "slowStreamCompletedStreams",
        "slowStreamConsumerBurstBytes",
        "slowStreamConsumerBurstWrites",
        "slowStreamConsumerPauseReadyRequests",
        "slowStreamConsumerResumes",
        "slowStreamFirstStageAcks",
        "slowStreamSecondStageAcks",
        "slowStreamProofs",
        "slowStreamSessionMismatches",
        "slowStreamStageAckTimeouts",
        "slowStreamUnexpectedCloses",
        "slowStreamStageDelayMs",
        "slowStreamStageDelaySchedules",
        "cspConnectSrcProofs",
        "cspConnectSrcTargetTcpConnections",
        "cspConnectSrcTargetRequests",
        "plaintextHttpControlTcpConnections",
        "plaintextHttpControlRequests",
        "plaintextHttpControlProofs",
        "mixedContentTargetPostControlWispConnects",
        "mixedContentTargetPostControlTcpConnections",
        "mixedContentTargetPostControlRequests",
        "mixedContentProofs",
        "tlsMismatchTcpConnections",
        "tlsMismatchHttpStreams",
    ):
        value = status.get(field)
        if type(value) is not int or value < 0:
            raise M0Error(f"relay transcript {field} is not a nonnegative int")
    if status.get("activeWispSessions") != 1:
        raise M0Error("relay does not retain exactly one recovered WISP session")
    if status["wispSessions"] != 2:
        raise M0Error("relay did not observe one WISP disconnect and fresh reconnect")
    if status["rejectedDestinations"] != 0:
        raise M0Error("relay rejected a destination during the M5 fixture")
    if status["udpPackets"] != 0:
        raise M0Error("relay observed an unsupported UDP WISP request")
    if status["relayErrors"] != 0:
        raise M0Error("relay reported a WISP protocol or target error")
    if status["corsRequests"] < 1:
        raise M0Error("relay did not observe the inner CORS request")
    if status["webSocketEchoes"] < 1:
        raise M0Error("relay did not observe the inner WebSocket echo")
    if status["redirectRequests"] < 1:
        raise M0Error("relay did not observe the M5 redirect request")
    if status["redirectCookieValidations"] < 1:
        raise M0Error("relay did not validate the M5 redirect cookie")
    for field, expected_value in (
        ("cacheStore200s", 1),
        ("cacheConditionalRequests", 1),
        ("cacheNotModified304s", 1),
        ("cacheUnexpectedRequests", 0),
        ("cancelStreamRequests", 1),
        ("cancelStreamFirstChunks", 1),
        ("cancelStreamCancelResets", 1),
        ("cancelStreamProofs", 1),
        ("cancelStreamProofSessionMismatches", 0),
        ("cancelStreamProofTimeouts", 0),
        ("cancelStreamUnexpectedResets", 0),
        ("largeDownloadBytes", M5_LARGE_DOWNLOAD_BYTES),
        ("largeDownloadChunks", M5_LARGE_DOWNLOAD_CHUNKS),
        ("largeDownloadCompletions", 1),
        ("largeDownloadRequests", 1),
        ("largeDownloadUnexpectedCloses", 0),
        ("reconnectDisconnectRequests", 1),
        ("reconnectFirstChunkAcks", 1),
        ("reconnectFirstChunks", 1),
        ("reconnectRecoveryRequests", 1),
        ("reconnectSessionMismatches", 0),
        ("reconnectStreamRequests", 1),
        ("reconnectUnexpectedCloses", 0),
        ("reconnectUnexpectedRetries", 0),
        ("slowStreamRequests", 1),
        ("slowStreamFirstStages", 1),
        ("slowStreamSecondStages", 1),
        ("slowStreamThirdStages", 1),
        ("slowStreamCompletedStreams", 1),
        ("slowStreamConsumerBurstBytes", M5_SLOW_STREAM_CONSUMER_BURST_BYTES),
        ("slowStreamConsumerBurstWrites", 1),
        ("slowStreamConsumerPauseReadyRequests", 1),
        ("slowStreamConsumerResumes", 1),
        ("slowStreamFirstStageAcks", 1),
        ("slowStreamSecondStageAcks", 1),
        ("slowStreamProofs", 1),
        ("slowStreamSessionMismatches", 0),
        ("slowStreamStageAckTimeouts", 0),
        ("slowStreamUnexpectedCloses", 0),
        ("slowStreamStageDelaySchedules", 2),
        ("cspConnectSrcProofs", 1),
        ("cspConnectSrcTargetTcpConnections", 0),
        ("cspConnectSrcTargetRequests", 0),
        ("plaintextHttpControlRequests", 1),
        ("plaintextHttpControlProofs", 1),
        ("mixedContentTargetPostControlWispConnects", 0),
        ("mixedContentTargetPostControlTcpConnections", 0),
        ("mixedContentTargetPostControlRequests", 0),
        ("mixedContentProofs", 1),
    ):
        if status[field] != expected_value:
            raise M0Error(
                f"relay {field} mismatch: expected exactly "
                f"{expected_value}, got {status[field]}"
            )
    if status["slowStreamStageDelayMs"] < M5_SLOW_STREAM_MIN_ELAPSED_MS:
        raise M0Error(
            "relay slowStreamStageDelayMs is shorter than the controlled "
            "slow-stream interval"
        )
    if not (
        1 <= status["largeDownloadBackpressureEvents"]
        <= M5_LARGE_DOWNLOAD_CHUNKS
    ):
        raise M0Error(
            "relay largeDownloadBackpressureEvents is outside the bounded "
            "H2 write-backpressure range"
        )
    if status["plaintextHttpControlTcpConnections"] < 1:
        raise M0Error(
            "relay did not observe the plaintext HTTP control TCP connection"
        )
    if status["tlsMismatchTcpConnections"] < 1:
        raise M0Error("relay did not observe the TLS-mismatch TCP connection")
    if status["tlsMismatchHttpStreams"] != 0:
        raise M0Error("relay observed an HTTP stream after TLS mismatch")

    h2_requests = _require_dict(status.get("h2Requests"), "relay H2 requests")
    if h2_requests.get("protocol") != "h2":
        raise M0Error("relay H2 request protocol is not h2")
    if _require_positive_integer(h2_requests.get("count"), "relay H2 count") < 2:
        raise M0Error("relay did not observe the H2 page and subresource")

    destinations = status.get("requestedDestinations")
    if not isinstance(destinations, list) or not destinations:
        raise M0Error("relay has no observed WISP destinations")
    h2_port = _validated_port(urlsplit(relay_ready.https_url), "relay httpsUrl")
    h1_port = _validated_port(urlsplit(relay_ready.http1_url), "relay http1Url")
    plaintext_http_control_port = _validated_port(
        urlsplit(relay_ready.plaintext_http_control_url),
        "relay plaintextHttpControlUrl",
    )
    mixed_content_target_port = _validated_port(
        urlsplit(relay_ready.mixed_content_target_url),
        "relay mixedContentTargetUrl",
    )
    tls_failure_port = _validated_port(
        urlsplit(relay_ready.tls_failure_url), "relay tlsFailureUrl"
    )
    if mixed_content_target_port != plaintext_http_control_port:
        raise M0Error(
            "relay mixed-content target is not on the plaintext control port"
        )
    if tls_failure_port in (h2_port, h1_port, plaintext_http_control_port):
        raise M0Error("relay TLS-mismatch destination is not distinct")
    if plaintext_http_control_port in (h2_port, h1_port):
        raise M0Error("relay plaintext HTTP control destination is not distinct")
    h2_count = 0
    h1_count = 0
    plaintext_http_control_count = 0
    tls_failure_count = 0
    for destination in destinations:
        if not isinstance(destination, dict):
            raise M0Error("relay destination is not an object")
        if destination.get("hostname") != M5_TEST_HOSTNAME:
            raise M0Error("relay observed a non-fixture WISP hostname")
        port = destination.get("port")
        if type(port) is not int:
            raise M0Error("relay destination port is not an integer")
        if port == h2_port:
            h2_count += 1
        elif port == h1_port:
            h1_count += 1
        elif port == plaintext_http_control_port:
            plaintext_http_control_count += 1
        elif port == tls_failure_port:
            tls_failure_count += 1
        else:
            raise M0Error("relay observed a non-fixture WISP port")
    if (
        h2_count < 2
        or h1_count < 2
        or plaintext_http_control_count < 1
        or tls_failure_count < 1
    ):
        raise M0Error("relay did not observe all fixed M5 destination streams")

    transcript = status.get("transcript")
    if not isinstance(transcript, list) or not transcript:
        raise M0Error("relay transcript is missing")
    event_entries = [entry for entry in transcript if isinstance(entry, dict)]
    event_names = [entry.get("event") for entry in event_entries]
    events = set(event_names)
    for event in (
        "wisp-connected",
        "wisp-ready",
        "wisp-disconnected",
        "connect-open",
        "plaintext-http-control-tcp-connect",
        "h1-plaintext-http-control",
        "h1-plaintext-http-control-proof",
        "plaintext-http-control-phase-complete",
        "h2-page",
        "h2-redirect",
        "h2-redirect-cookie",
        "h2-page-cookie",
        "h2-resource",
        "h2-cache-store-200",
        "h2-cache-revalidate-304",
        "h2-csp-connect-src-proof",
        "h2-mixed-content-proof",
        "h2-cancel-stream-start",
        "h2-cancel-stream-cancel-reset",
        "h2-cancel-stream-proof",
        "h2-slow-stream-start",
        "h2-slow-stream-first-stage",
        "h2-slow-stream-first-stage-ack",
        "h2-slow-stream-second-stage",
        "h2-slow-stream-consumer-pause-ready",
        "h2-slow-stream-consumer-burst",
        "h2-slow-stream-consumer-resume",
        "h2-slow-stream-second-stage-ack",
        "h2-slow-stream-third-stage",
        "h2-slow-stream-complete",
        "h2-slow-stream-proof",
        "h2-large-download-start",
        "h2-large-download-complete",
        "h2-reconnect-stream-start",
        "h2-reconnect-stream-first-chunk",
        "h2-reconnect-first-chunk-ack",
        "h2-reconnect-disconnect-requested",
        "h2-reconnect-carrier-close",
        "h2-reconnect-stream-disconnected",
        "h2-reconnect-wisp-disconnected",
        "h2-reconnect-recovery",
        "h1-cors",
        "h1-wss-echo",
        "tls-failure-tcp-connect",
    ):
        if event not in events:
            raise M0Error(f"relay transcript is missing {event!r}")
    if event_names.index("h2-redirect-cookie") >= event_names.index(
        "h2-page-cookie"
    ):
        raise M0Error("relay accepted the final page before redirect cookie")
    if event_names.index("h2-cache-store-200") >= event_names.index(
        "h2-cache-revalidate-304"
    ):
        raise M0Error("relay revalidated the cache before storing the entry")
    csp_proof_event = "h2-csp-connect-src-proof"
    if event_names.count(csp_proof_event) != 1:
        raise M0Error(
            f"relay transcript must contain exactly one {csp_proof_event!r}"
        )
    if not (
        event_names.index("h2-cache-revalidate-304")
        < event_names.index(csp_proof_event)
        < event_names.index("h1-cors")
    ):
        raise M0Error(
            "relay CSP proof event is not between cache revalidation and CORS"
        )
    for event in (
        "h1-plaintext-http-control",
        "h1-plaintext-http-control-proof",
        "plaintext-http-control-phase-complete",
        "h2-mixed-content-proof",
        "h2-cancel-stream-start",
        "h2-cancel-stream-cancel-reset",
        "h2-cancel-stream-proof",
        "h2-slow-stream-start",
        "h2-slow-stream-first-stage",
        "h2-slow-stream-first-stage-ack",
        "h2-slow-stream-second-stage",
        "h2-slow-stream-consumer-pause-ready",
        "h2-slow-stream-consumer-burst",
        "h2-slow-stream-consumer-resume",
        "h2-slow-stream-second-stage-ack",
        "h2-slow-stream-third-stage",
        "h2-slow-stream-complete",
        "h2-slow-stream-proof",
        "h2-large-download-start",
        "h2-large-download-complete",
        "h2-reconnect-stream-start",
        "h2-reconnect-stream-first-chunk",
        "h2-reconnect-first-chunk-ack",
        "h2-reconnect-disconnect-requested",
        "h2-reconnect-carrier-close",
        "h2-reconnect-stream-disconnected",
        "h2-reconnect-wisp-disconnected",
        "h2-reconnect-recovery",
    ):
        if event_names.count(event) != 1:
            raise M0Error(f"relay transcript must contain exactly one {event!r}")
    for event, expected_count in (
        ("wisp-connected", 2),
        ("wisp-ready", 2),
        ("wisp-disconnected", 1),
    ):
        if event_names.count(event) != expected_count:
            raise M0Error(
                f"relay transcript must contain exactly {expected_count} "
                f"{event!r} events"
            )
    cancel_reset_entry = next(
        entry
        for entry in transcript
        if isinstance(entry, dict)
        and entry.get("event") == "h2-cancel-stream-cancel-reset"
    )
    if cancel_reset_entry.get("rstCode") != 8:
        raise M0Error(
            "relay cancel stream reset did not report NGHTTP2_CANCEL (8)"
        )
    slow_stream_consumer_burst_entry = next(
        entry
        for entry in transcript
        if isinstance(entry, dict)
        and entry.get("event") == "h2-slow-stream-consumer-burst"
    )
    if (
        slow_stream_consumer_burst_entry.get("bytes")
        != M5_SLOW_STREAM_CONSUMER_BURST_BYTES
    ):
        raise M0Error(
            "relay slow-stream consumer burst does not report the exact "
            "bounded payload size"
        )
    if slow_stream_consumer_burst_entry.get("backpressured") is not True:
        raise M0Error(
            "relay slow-stream consumer burst did not observe H2 write "
            "backpressure"
        )
    if not (
        event_names.index("plaintext-http-control-tcp-connect")
        < event_names.index("h1-plaintext-http-control")
        < event_names.index("h1-plaintext-http-control-proof")
        < event_names.index("plaintext-http-control-phase-complete")
        < event_names.index("h2-redirect")
    ):
        raise M0Error(
            "relay plaintext HTTP control did not complete before HTTPS "
            "navigation"
        )
    if not (
        event_names.index(csp_proof_event)
        < event_names.index("h2-mixed-content-proof")
        < event_names.index("h2-cancel-stream-start")
        < event_names.index("h2-cancel-stream-cancel-reset")
        < event_names.index("h2-cancel-stream-proof")
        < event_names.index("h1-cors")
    ):
        raise M0Error(
            "relay cancellation proof events are not between active mixed-content "
            "proof and CORS"
        )
    if not (
        event_names.index("h2-slow-stream-proof")
        < event_names.index("h2-large-download-start")
        < event_names.index("h2-large-download-complete")
        < event_names.index("h1-cors")
    ):
        raise M0Error(
            "relay large download events are not between slow-stream proof "
            "and CORS"
        )
    if not (
        event_names.index("h2-large-download-complete")
        < event_names.index("h2-reconnect-stream-start")
        < event_names.index("h2-reconnect-stream-first-chunk")
        < event_names.index("h2-reconnect-first-chunk-ack")
        < event_names.index("h2-reconnect-disconnect-requested")
        < event_names.index("h2-reconnect-carrier-close")
        < event_names.index("wisp-disconnected")
        < event_names.index("h2-reconnect-wisp-disconnected")
        < event_names.index("h2-reconnect-recovery")
        < event_names.index("h1-cors")
    ):
        raise M0Error(
            "relay reconnect events are not between the large download and CORS"
        )
    # Closing the RFC 6455 carrier removes the H2 socket asynchronously. The
    # old stream may therefore report its close before or after the explicit
    # relay teardown marker, but it must be caused by the carrier close and
    # finish before the page advances to its CORS check.
    if not (
        event_names.index("h2-reconnect-carrier-close")
        < event_names.index("h2-reconnect-stream-disconnected")
        < event_names.index("h1-cors")
    ):
        raise M0Error(
            "relay reconnect stream did not terminate after the carrier close "
            "and before CORS"
        )
    first_wisp_connected = event_names.index("wisp-connected")
    second_wisp_connected = event_names.index(
        "wisp-connected", first_wisp_connected + 1
    )
    first_wisp_ready = event_names.index("wisp-ready")
    second_wisp_ready = event_names.index("wisp-ready", first_wisp_ready + 1)
    if not (
        event_names.index("wisp-disconnected")
        < second_wisp_connected
        < second_wisp_ready
        < event_names.index("h2-reconnect-recovery")
    ):
        raise M0Error(
            "relay reconnect recovery did not use a fresh WISP handshake"
        )
    recovery_connect_open = next(
        (
            index
            for index, entry in enumerate(event_entries)
            if index > second_wisp_ready and entry.get("event") == "connect-open"
        ),
        None,
    )
    if recovery_connect_open is None or not (
        second_wisp_ready
        < recovery_connect_open
        < event_names.index("h2-reconnect-recovery")
    ):
        raise M0Error(
            "relay reconnect recovery did not open a fresh TCP stream"
        )
    expected_recovery_destination = f"{M5_TEST_HOSTNAME}:{h2_port}"
    if event_entries[recovery_connect_open].get("destination") != (
        expected_recovery_destination
    ):
        raise M0Error(
            "relay reconnect recovery did not open the original H2 destination"
        )
    if not (
        event_names.index("h2-cancel-stream-proof")
        < event_names.index("h2-slow-stream-start")
        < event_names.index("h2-slow-stream-first-stage")
        < event_names.index("h2-slow-stream-first-stage-ack")
        < event_names.index("h2-slow-stream-second-stage")
        < event_names.index("h2-slow-stream-consumer-pause-ready")
        < event_names.index("h2-slow-stream-consumer-burst")
        < event_names.index("h2-slow-stream-consumer-resume")
        < event_names.index("h2-slow-stream-second-stage-ack")
        < event_names.index("h2-slow-stream-third-stage")
        < event_names.index("h2-slow-stream-complete")
        < event_names.index("h2-slow-stream-proof")
        < event_names.index("h1-cors")
    ):
        raise M0Error(
            "relay slow stream stage events are not between cancellation "
            "proof and CORS"
        )
    for event in (
        "h2-cancel-stream-rejected",
        "h2-cancel-stream-unexpected-reset",
        "h2-cancel-stream-proof-rejected",
        "h2-cancel-stream-proof-session-mismatch",
        "h2-cancel-stream-proof-timeout",
    ):
        if event in events:
            raise M0Error(
                "relay transcript unexpectedly contains cancellation failure "
                f"event {event!r}"
            )
    for event in (
        "h2-slow-stream-rejected",
        "h2-slow-stream-unexpected-close",
        "h2-slow-stream-stage-ack-rejected",
        "h2-slow-stream-stage-ack-session-mismatch",
        "h2-slow-stream-stage-ack-timeout",
        "h2-slow-stream-consumer-pause-ready-rejected",
        "h2-slow-stream-consumer-pause-ready-session-mismatch",
        "h2-slow-stream-consumer-resume-rejected",
        "h2-slow-stream-consumer-resume-session-mismatch",
        "h2-slow-stream-proof-rejected",
        "h2-slow-stream-proof-session-mismatch",
        "h2-slow-stream-proof-timeout",
    ):
        if event in events:
            raise M0Error(
                "relay transcript unexpectedly contains slow-stream failure "
                f"event {event!r}"
            )
    for event in (
        "h2-large-download-rejected",
        "h2-large-download-unexpected-close",
    ):
        if event in events:
            raise M0Error(
                "relay transcript unexpectedly contains large-download failure "
                f"event {event!r}"
            )
    for event in (
        "h2-reconnect-stream-rejected",
        "h2-reconnect-stream-unexpected-close",
        "h2-reconnect-first-chunk-ack-rejected",
        "h2-reconnect-first-chunk-ack-session-mismatch",
        "h2-reconnect-relay-selection-failed",
        "h2-reconnect-recovery-rejected",
        "h2-reconnect-recovery-session-mismatch",
        "h2-reconnect-recovery-timeout",
        "h2-reconnect-recovery-unexpected-close",
    ):
        if event in events:
            raise M0Error(
                "relay transcript unexpectedly contains reconnect failure "
                f"event {event!r}"
            )
    if "h2-reconnect-global-close" in events:
        raise M0Error("relay reconnect unexpectedly emitted a WISP global close")
    for event in (
        "csp-connect-src-target-tcp-connect",
        "h1-csp-connect-src-target-request",
    ):
        if event in events:
            raise M0Error(
                f"relay transcript unexpectedly contains forbidden CSP target "
                f"event {event!r}"
            )
    for event in (
        "mixed-content-target-post-control-wisp-connect",
        "mixed-content-target-post-control-tcp-connect",
        "h1-mixed-content-target-post-control-request",
    ):
        if event in events:
            raise M0Error(
                "relay transcript unexpectedly contains post-control mixed "
                f"content target event {event!r}"
            )


def wait_for_result(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    result_queue: queue.Queue[dict[str, Any]],
    deadline: float,
) -> dict[str, Any]:
    while time.monotonic() < deadline:
        if browser.poll() is not None:
            raise M0Error(
                "host browser exited before the M5 result "
                f"(status {browser.returncode}): " + "\n".join(browser_stderr)
            )
        remaining = deadline - time.monotonic()
        try:
            return result_queue.get(timeout=min(0.1, max(0.0, remaining)))
        except queue.Empty:
            continue
    raise M0Error("M5 browser timeout: " + "\n".join(browser_stderr))


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
    result: dict[str, Any] | None,
) -> Path:
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    diagnostic_path = diagnostics_dir / "m5-wisp-failure.json"
    diagnostic = {
        "schema_version": 1,
        "runner": "run_m5_wisp_smoke.py",
        "case": M5_CASE,
        "status": "fail",
        "stage": stage,
        "failure": {
            "type": type(error).__name__,
            "message": str(error),
        },
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
                    "wispEndpoint": relay_ready.wisp_endpoint,
                    "httpsUrl": relay_ready.https_url,
                    "plaintextHttpControlUrl": (
                        relay_ready.plaintext_http_control_url
                    ),
                    "mixedContentTargetUrl": (
                        relay_ready.mixed_content_target_url
                    ),
                }
                if relay_ready
                else None
            ),
            "stdout_tail": list(relay_stdout),
            "stderr_tail": list(relay_stderr),
            "status": relay_status,
        },
        "runtime_result": result,
    }
    temporary_path = diagnostic_path.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(diagnostic, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(diagnostic_path)
    return diagnostic_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run controlled Chromium HTTPS traffic over the M5 WISP relay."
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument(
        "--out-dir", type=Path, default=Path("out/wasm-content-m3")
    )
    parser.add_argument("--module-name", default="content_shell_wasm_m5_test")
    parser.add_argument("--node", type=Path)
    parser.add_argument(
        "--relay-script",
        type=Path,
        default=REPO_ROOT / "tools/wasm/m5_wisp_test_server.js",
    )
    parser.add_argument(
        "--diagnostics-dir",
        type=Path,
        help="failure directory (default: OUT_DIR/diagnostics-m5-wisp)",
    )
    parser.add_argument(
        "--no-sandbox",
        action="store_true",
        help="disable the host browser sandbox (isolated CI only)",
    )
    parser.add_argument("--timeout", type=parse_timeout, default=150.0)
    parser.add_argument("--verbose-server", action="store_true")
    args = parser.parse_args()

    out_dir = args.out_dir
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    diagnostics_dir = args.diagnostics_dir
    if diagnostics_dir is None:
        diagnostics_dir = out_dir / "diagnostics-m5-wisp"
    elif not diagnostics_dir.is_absolute():
        diagnostics_dir = REPO_ROOT / diagnostics_dir
    relay_script = args.relay_script
    if not relay_script.is_absolute():
        relay_script = REPO_ROOT / relay_script
    relay_script = relay_script.resolve()

    server = None
    server_thread = None
    server_started = False
    relay: subprocess.Popen[str] | None = None
    relay_stdout: deque[str] = deque(maxlen=300)
    relay_stderr: deque[str] = deque(maxlen=300)
    relay_stdout_thread: threading.Thread | None = None
    relay_stderr_thread: threading.Thread | None = None
    relay_command_line: list[str] | None = None
    relay_ready: RelayReady | None = None
    relay_status: dict[str, Any] | None = None
    browser: subprocess.Popen[str] | None = None
    browser_path: Path | None = None
    browser_version: str | None = None
    browser_stderr: deque[str] = deque(maxlen=300)
    browser_stderr_thread: threading.Thread | None = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    result: dict[str, Any] | None = None
    context: dict[str, object] | None = None
    stage = "load_manifest"

    try:
        manifest = load_manifest()
        port_revision = checked_output(["git", "rev-parse", "HEAD"])
        versions = manifest_versions(manifest, port_revision)
        stage = "print_context"
        context = print_context(
            "run_m5_wisp_smoke.py",
            manifest,
            case=M5_CASE,
            gn_args=manifest.get("m3_content_gn_args", manifest.get("gn_args")),
            module_name=args.module_name,
            host_browser_sandbox=not args.no_sandbox,
            transport="WISP v2.1 over a local test-only WebSocket relay",
        )

        stage = "find_browser"
        browser_path, browser_version = find_browser(args.browser)
        print(
            f"{SENTINEL}:HOST_BROWSER "
            + json.dumps(
                {"browser_version": browser_version},
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )
        stage = "find_node"
        node = find_node(args.node)
        if not relay_script.is_file():
            raise M0Error(f"M5 relay script is missing: {relay_script}")

        token = secrets.token_urlsafe(24)
        result_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        stage = "verify_test_artifacts"
        verify_no_private_key_pem_artifacts(out_dir, args.module_name)
        stage = "create_host_server"
        server = create_m3_server(
            "127.0.0.1",
            0,
            out_dir,
            token,
            result_queue,
            module_name=args.module_name,
            verbose=args.verbose_server,
        )
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m5-host-server",
            daemon=True,
        )
        server_thread.start()
        server_started = True

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
            name="chromium-wasm-m5-relay-stdout",
            daemon=True,
        )
        relay_stdout_thread.start()
        relay_stderr_thread = threading.Thread(
            target=drain_stream,
            args=(relay.stderr, relay_stderr),
            name="chromium-wasm-m5-relay-stderr",
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
                    "http1Url": relay_ready.http1_url,
                    "httpsUrl": relay_ready.https_url,
                    "plaintextHttpControlUrl": (
                        relay_ready.plaintext_http_control_url
                    ),
                    "mixedContentTargetUrl": (
                        relay_ready.mixed_content_target_url
                    ),
                    "redirectUrl": relay_ready.redirect_url,
                    "tlsFailureUrl": relay_ready.tls_failure_url,
                    "transcriptUrl": relay_ready.transcript_url,
                    "wispEndpoint": relay_ready.wisp_endpoint,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )
        url = m5_smoke_url(
            server,
            token,
            versions,
            relay_ready=relay_ready,
            module_name=args.module_name,
            timeout_seconds=min(180.0, max(1.0, args.timeout - 1.0)),
        )

        profile = tempfile.TemporaryDirectory(prefix="chromium-wasm-m5-")
        stage = "launch_browser"
        browser = subprocess.Popen(
            m5_browser_command(
                browser_path,
                profile.name,
                url,
                no_sandbox=args.no_sandbox,
            ),
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
            name="chromium-wasm-m5-browser-stderr",
            daemon=True,
        )
        browser_stderr_thread.start()

        deadline = time.monotonic() + args.timeout
        stage = "wait_for_result"
        result = wait_for_result(browser, browser_stderr, result_queue, deadline)
        stage = "validate_runtime_contract"
        validate_m5_result(
            result, expected_versions=versions, relay_ready=relay_ready
        )
        stage = "fetch_relay_transcript"
        relay_status = fetch_relay_transcript(
            relay_ready.transcript_url,
            timeout_seconds=min(10.0, max(1.0, deadline - time.monotonic())),
        )
        stage = "validate_relay_transcript"
        validate_relay_transcript(relay_status, relay_ready=relay_ready)
        print(
            f"{SENTINEL}:BROWSER_RESULT "
            + json.dumps(result, sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        print(
            f"{SENTINEL}:RELAY_TRANSCRIPT "
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
            diagnostic_path = write_failure_diagnostics(
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
                result=result,
            )
            print(
                f"{SENTINEL}:DIAGNOSTICS "
                + json.dumps(
                    {"path": str(diagnostic_path)},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
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
            if server_started:
                server.shutdown()
            server.server_close()
        if server_started and server_thread is not None:
            server_thread.join(timeout=3)
        if browser_stderr_thread is not None:
            browser_stderr_thread.join(timeout=1)
        if relay_stdout_thread is not None:
            relay_stdout_thread.join(timeout=1)
        if relay_stderr_thread is not None:
            relay_stderr_thread.join(timeout=1)


if __name__ == "__main__":
    sys.exit(main())
