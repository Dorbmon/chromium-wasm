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
M5_TEST_PATH_PREFIX = "/m5/"
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
    value: object, *, description: str = "relay httpsUrl"
) -> str:
    """Accept only the fixed HTTPS fixture navigation URL."""

    if not isinstance(value, str) or not value:
        raise M0Error(f"{description} must be a nonempty string")
    if len(value.encode("utf-8")) > 2048:
        raise M0Error(f"{description} is too long")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != M5_TEST_HOSTNAME
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith(M5_TEST_PATH_PREFIX)
    ):
        raise M0Error(f"{description} violates the M5 fixture policy")
    _validated_port(parsed, description)
    return value


def validate_m5_redirect_url(value: object, *, https_url: str) -> str:
    """Accept a distinct M5 redirect source on the H2 fixture listener."""

    redirect_url = validate_m5_https_url(
        value, description="relay redirectUrl"
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
    http1_url = validate_m5_https_url(
        ready.get("http1Url"), description="relay http1Url"
    )
    tls_failure_url = validate_m5_https_url(
        ready.get("tlsFailureUrl"), description="relay tlsFailureUrl"
    )
    h2_port = _validated_port(urlsplit(https_url), "relay httpsUrl")
    h1_port = _validated_port(urlsplit(http1_url), "relay http1Url")
    tls_failure_port = _validated_port(
        urlsplit(tls_failure_url), "relay tlsFailureUrl"
    )
    if tls_failure_port in (h2_port, h1_port):
        raise M0Error("relay tlsFailureUrl must use a distinct fixture port")
    return RelayReady(
        wisp_endpoint=validate_wisp_endpoint(ready.get("wispEndpoint")),
        https_url=https_url,
        redirect_url=redirect_url,
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
    tls_failure_url = validate_m5_https_url(
        relay_ready.tls_failure_url, description="relay tlsFailureUrl"
    )
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "case": M5_CASE,
            "chromium": versions["chromium"],
            "emscripten": versions["emscripten"],
            "m5_url": redirect_url,
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
    result: dict[str, Any], *, expected_versions: dict[str, str]
) -> None:
    """Require evidence from Chromium's HTTPS page, not host success alone."""

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
    heartbeat = _require_dict(readiness.get("heartbeat"), "M5 heartbeat")
    if heartbeat.get("anchor") != "m5-https-navigation-committed":
        raise M0Error("M5 heartbeat was not anchored to HTTPS navigation")

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
    }
    for field, expected_value in expected_probe.items():
        actual = page_probe.get(field)
        if type(actual) is not type(expected_value) or actual != expected_value:
            raise M0Error(
                f"M5 page probe {field} mismatch: expected "
                f"{expected_value!r}, got {actual!r}"
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
    for marker in (
        "initialize:wisp-configured",
        "navigation:requested:m5-https",
        "navigation:requested:m5-https-tls-failure",
        "navigation:failed:m5-https:-200",
        "shutdown:complete",
    ):
        if marker not in host_logs:
            raise M0Error(f"M5 host logs are missing {marker!r}")
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
    for field in (
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
        "tlsMismatchTcpConnections",
        "tlsMismatchHttpStreams",
    ):
        value = status.get(field)
        if type(value) is not int or value < 0:
            raise M0Error(f"relay transcript {field} is not a nonnegative int")
    if status["wispSessions"] != 1:
        raise M0Error("relay did not observe exactly one WISP session")
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
    ):
        if status[field] != expected_value:
            raise M0Error(
                f"relay {field} mismatch: expected exactly "
                f"{expected_value}, got {status[field]}"
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
    tls_failure_port = _validated_port(
        urlsplit(relay_ready.tls_failure_url), "relay tlsFailureUrl"
    )
    if tls_failure_port in (h2_port, h1_port):
        raise M0Error("relay TLS-mismatch destination is not distinct")
    h2_count = 0
    h1_count = 0
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
        elif port == tls_failure_port:
            tls_failure_count += 1
        else:
            raise M0Error("relay observed a non-fixture WISP port")
    if h2_count < 1 or h1_count < 2 or tls_failure_count < 1:
        raise M0Error("relay did not observe all fixed M5 destination streams")

    transcript = status.get("transcript")
    if not isinstance(transcript, list) or not transcript:
        raise M0Error("relay transcript is missing")
    event_names = [
        entry.get("event") for entry in transcript if isinstance(entry, dict)
    ]
    events = set(event_names)
    for event in (
        "wisp-ready",
        "connect-open",
        "h2-page",
        "h2-redirect",
        "h2-redirect-cookie",
        "h2-page-cookie",
        "h2-resource",
        "h2-cache-store-200",
        "h2-cache-revalidate-304",
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
        validate_m5_result(result, expected_versions=versions)
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
