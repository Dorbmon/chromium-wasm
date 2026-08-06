#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the isolated local M5 gateway-denial preflight through WISP.

Unlike the broad controlled fixture, this runner sends no document URL to the
host page. The test-only native binary owns the one canonical ``a.test:443``
document and first proves that its same-host ``:444`` precursor is denied by
the loopback relay.
"""

from __future__ import annotations

import argparse
from collections import deque
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
from urllib.parse import urlencode

from m0_common import (
    M0Error,
    REPO_ROOT,
    checked_output,
    load_manifest,
    parse_timeout,
    print_context,
)
from m3_content_server import M5_CONTROLLED_PREFLIGHT_CASE, create_m3_server
from m4_cdp import unused_loopback_port, wait_for_page_client
from run_browser_smoke import drain_stream, find_browser, stop_browser
from run_content_shell_smoke import manifest_versions
from run_m5_wisp_smoke import (
    M5_FIXTURE,
    M5_TEST_HOSTNAME,
    RelayReady,
    _drain_relay_stdout,
    fetch_relay_transcript,
    find_node,
    m5_browser_command,
    m5_host_origin,
    relay_command,
    verify_no_private_key_pem_artifacts,
    wait_for_relay_ready,
    wait_for_result,
)


SENTINEL = "CHROMIUM_WASM_M5_CONTROLLED_PREFLIGHT"
M5_CONTROLLED_PREFLIGHT_FIXTURE = "chromium-wasm-m5-controlled-preflight-v1"
M5_CONTROLLED_PREFLIGHT_MODULE = "content_shell_wasm_m5_controlled_preflight_test"
M5_CONTROLLED_PREFLIGHT_HEARTBEAT = (
    "m5-controlled-preflight-navigation-committed"
)
M5_CONTROLLED_PREFLIGHT_EVENTS = (
    "Network.requestWillBeSent:document",
    "Network.responseReceived:document",
    "Network.loadingFinished:document",
)
MAXIMUM_URL_FREE_RESULT_BYTES = 256 * 1024
URL_LIKE_VALUE_PATTERN = re.compile(r"\b(?:https?|wss?)://", re.IGNORECASE)
DEBUG_CDP_CONNECT_TIMEOUT_SECONDS = 12.0
DEBUG_CDP_MAXIMUM_COUNT = 512
DEBUG_CDP_LOG_MARKERS = (
    "loading_workers",
    "worker_error",
    "wasm",
    "abort",
    "error",
)
DEBUG_CDP_RESOURCE_KINDS = ("wasm", "javascript", "blob", "other")
DEBUG_CDP_PHASE_MARKERS = (
    "resize",
    "bootstrap_requested",
    "network_preparation_requested",
    "network_enabled",
    "preflight_requested",
    "preflight_committed",
    "shutdown_accepted",
    "shutdown_complete",
    "shutdown_failed",
    "process_exit",
    "runtime_exit",
)
DEBUG_CDP_FATAL_MARKERS = (
    "controlled_preflight",
    "devtools_network",
    "recorder_start_failed",
    "agent_host_closed",
    "gateway_denial",
    "primary_frame_not_live",
    "wisp_evidence_window_rejected",
    "wisp_initial_diagnostics_not_clean",
    "early_exit",
    "shutdown",
    "wisp",
    "socket",
    "uncaught",
    "invalid",
)
CONTROLLED_PREFLIGHT_RELAY_CAPTURE_STATES = (
    "captured",
    "not_ready",
    "relay_exited",
    "unavailable",
    "internal_error",
    "invalid",
)
CONTROLLED_PREFLIGHT_RELAY_COUNTERS = (
    ("wisp_sessions", "wispSessions"),
    ("rejected_destinations", "rejectedDestinations"),
    (
        "local_gateway_blocked_port_attempts",
        "localGatewayBlockedPortAttempts",
    ),
    (
        "local_gateway_443_streams_opened",
        "localGateway443StreamsOpened",
    ),
    ("local_gateway_443_requests", "localGateway443Requests"),
    ("udp_packets", "udpPackets"),
    ("relay_errors", "relayErrors"),
)
CONTROLLED_PREFLIGHT_RELAY_EVENTS = (
    ("wisp_connected", "wisp-connected"),
    ("wisp_ready", "wisp-ready"),
    ("local_gateway_444_blocked", "local-gateway-444-blocked"),
    ("connect_requested", "connect-requested"),
    ("connect_open", "connect-open"),
    ("local_gateway_443_request", "local-gateway-443-request"),
    ("connect_rejected", "connect-rejected"),
    (
        "local_gateway_443_route_rejected",
        "local-gateway-443-route-rejected",
    ),
)

# This expression intentionally produces only a fixed, URL-free diagnostic
# schema. It may inspect raw host logs and resource names in the page to count
# categories, but it never returns them over the DevTools connection.
DEBUG_CDP_SNAPSHOT_EXPRESSION = r"""
(async () => {
  const maximumCount = 512;
  const boundedCount = (value) => Number.isSafeInteger(value) && value >= 0
    ? Math.min(value, maximumCount) : 0;
  const lines = (value) => Array.isArray(value)
    ? value.filter((item) => typeof item === "string").slice(-maximumCount)
    : [];
  const markerCounts = (values) => {
    const result = {
      loading_workers: 0,
      worker_error: 0,
      wasm: 0,
      abort: 0,
      error: 0,
    };
    for (const value of values) {
      const lower = value.toLowerCase();
      if (lower.includes("loading-workers")) result.loading_workers += 1;
      if (lower.includes("worker") && lower.includes("error")) {
        result.worker_error += 1;
      }
      if (lower.includes("wasm")) result.wasm += 1;
      if (lower.includes("abort")) result.abort += 1;
      if (lower.includes("error")) result.error += 1;
    }
    for (const key of Object.keys(result)) {
      result[key] = boundedCount(result[key]);
    }
    return result;
  };
  const root = document.querySelector("#smoke-root");
  const canvas = document.querySelector("#browser-canvas");
  const rootValue = root?.dataset?.state;
  const rootState = rootValue === undefined ? "missing" :
    (["running", "pass", "fail"].includes(rootValue) ? rootValue : "other");
  const readyState = ["loading", "interactive", "complete"].includes(
      document.readyState) ? document.readyState : "other";
  const host = window.chromiumWasmHost;
  let logs = null;
  try {
    if (host && typeof host.logs === "function") {
      logs = await host.logs();
    }
  } catch (_) {}
  const hostLines = lines(logs?.host);
  const stdoutLines = lines(logs?.stdout);
  const stderrLines = lines(logs?.stderr);
  const fatalLines = stderrLines.filter((line) => line.startsWith("HOST_FATAL:"));
  const hasHostPrefix = (prefix) => hostLines.some(
      (line) => line.startsWith(prefix));
  const fatalMarkerCounts = () => {
    const result = {
      controlled_preflight: 0,
      devtools_network: 0,
      recorder_start_failed: 0,
      agent_host_closed: 0,
      gateway_denial: 0,
      primary_frame_not_live: 0,
      wisp_evidence_window_rejected: 0,
      wisp_initial_diagnostics_not_clean: 0,
      early_exit: 0,
      shutdown: 0,
      wisp: 0,
      socket: 0,
      uncaught: 0,
      invalid: 0,
    };
    for (const line of fatalLines) {
      const lower = line.toLowerCase();
      if (lower.includes("controlled preflight")) result.controlled_preflight += 1;
      if (lower.includes("devtools network")) result.devtools_network += 1;
      if (lower.includes(
          "could not start the m5 controlled preflight devtools network recorder")) {
        result.recorder_start_failed += 1;
      }
      if (lower.includes("closed before the public network trace completed")) {
        result.agent_host_closed += 1;
      }
      if (lower.includes("gateway-denial")) result.gateway_denial += 1;
      if (lower.includes("primary-frame-not-live")) {
        result.primary_frame_not_live += 1;
      }
      if (lower.includes("wisp-evidence-window-rejected")) {
        result.wisp_evidence_window_rejected += 1;
      }
      if (lower.includes("wisp-initial-diagnostics-not-clean")) {
        result.wisp_initial_diagnostics_not_clean += 1;
      }
      if (lower.includes("before shutdown was requested")) result.early_exit += 1;
      if (lower.includes("shutdown")) result.shutdown += 1;
      if (lower.includes("wisp")) result.wisp += 1;
      if (lower.includes("socket")) result.socket += 1;
      if (lower.includes("uncaught")) result.uncaught += 1;
      if (lower.includes("invalid")) result.invalid += 1;
    }
    for (const key of Object.keys(result)) {
      result[key] = boundedCount(result[key]);
    }
    return result;
  };
  let readiness = {
    available: false,
    runtime_initialized: false,
    shell_ready: false,
    surface_ready: false,
    navigation_committed: false,
    first_visually_non_empty_paint: false,
    fatal_error_count: 0,
    frame_present: false,
  };
  try {
    if (host && typeof host.readiness === "function") {
      const value = await host.readiness();
      readiness = {
        available: true,
        runtime_initialized: value?.runtimeInitialized === true,
        shell_ready: value?.shellReady === true,
        surface_ready: value?.surfaceReady === true,
        navigation_committed: value?.navigationCommitted === true,
        first_visually_non_empty_paint:
          value?.firstVisuallyNonEmptyPaint === true,
        fatal_error_count: boundedCount(Array.isArray(value?.fatalErrors)
          ? value.fatalErrors.length : 0),
        frame_present: value?.frame !== null && value?.frame !== undefined,
      };
    }
  } catch (_) {}
  const resources = {wasm: 0, javascript: 0, blob: 0, other: 0};
  for (const entry of performance.getEntriesByType("resource").slice(-maximumCount)) {
    const name = String(entry?.name || "");
    const kind = name.startsWith("blob:") ? "blob" :
      (name.endsWith(".wasm") ? "wasm" :
        (name.endsWith(".js") || entry?.initiatorType === "script"
          ? "javascript" : "other"));
    resources[kind] += 1;
  }
  for (const key of Object.keys(resources)) {
    resources[key] = boundedCount(resources[key]);
  }
  return {
    state: "captured",
    page: {
      ready_state: readyState,
      root_state: rootState,
      cross_origin_isolated: crossOriginIsolated === true,
      shared_array_buffer: typeof SharedArrayBuffer === "function",
      host_present: Boolean(host),
      canvas_present: canvas instanceof HTMLCanvasElement,
      canvas_focused: canvas !== null && document.activeElement === canvas,
    },
    host: {
      logs_available: logs !== null,
      host_log_count: boundedCount(hostLines.length),
      stdout_line_count: boundedCount(stdoutLines.length),
      stderr_line_count: boundedCount(stderrLines.length),
      fatal_log_count: boundedCount(fatalLines.length),
      markers: {
        initialize_start: hostLines.includes("initialize:start"),
        wisp_configured: hostLines.includes("initialize:wisp-configured"),
        runtime_initialized: hostLines.includes("runtime:initialized"),
        factory_resolved: hostLines.includes("initialize:factory-resolved"),
        initialize_complete: hostLines.includes("initialize:complete"),
      },
      stdout_markers: markerCounts(stdoutLines),
      stderr_markers: markerCounts(stderrLines),
      phases: {
        resize: hostLines.includes("resize:800x600@1"),
        bootstrap_requested: hostLines.includes("navigation:requested:data"),
        network_preparation_requested: hostLines.includes(
            "m5:controlled-preflight-devtools-network:start-requested"),
        network_enabled: hostLines.includes(
            "m5:controlled-preflight-devtools-network:enabled"),
        preflight_requested: hostLines.includes(
            "navigation:requested:m5-controlled-preflight"),
        preflight_committed: hostLines.includes(
            "navigation:committed:m5-controlled-preflight"),
        shutdown_accepted: hostLines.includes("shutdown:accepted"),
        shutdown_complete: hostLines.includes("shutdown:complete"),
        shutdown_failed: hasHostPrefix("shutdown:failed:"),
        process_exit: hasHostPrefix("process:exit:"),
        runtime_exit: hasHostPrefix("runtime:exit:"),
      },
      fatal_markers: fatalMarkerCounts(),
      readiness,
    },
    resources,
  };
})()
"""


def controlled_preflight_smoke_url(
    server: Any,
    token: str,
    versions: dict[str, str],
    *,
    relay_ready: RelayReady,
    module_name: str = M5_CONTROLLED_PREFLIGHT_MODULE,
    timeout_seconds: float = 120.0,
) -> str:
    """Build a host URL with only loopback transport configuration.

    The fixed browser document is intentionally absent from this query. Its
    ownership is native, not a caller-controlled JavaScript input.
    """

    from run_m5_wisp_smoke import validate_wisp_endpoint

    wisp_endpoint = validate_wisp_endpoint(relay_ready.wisp_endpoint)
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "case": M5_CONTROLLED_PREFLIGHT_CASE,
            "chromium": versions["chromium"],
            "emscripten": versions["emscripten"],
            "module": f"/__m3__/artifacts/{module_name}.js",
            "port": versions["port"],
            "token": token,
            "timeout_ms": max(1000, min(180000, int(timeout_seconds * 1000))),
            "v8": versions["v8"],
            "wisp_endpoint": wisp_endpoint,
        }
    )
    return f"http://{host}:{port}/__m3__/?{query}"


def _require_dict(value: object, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise M0Error(f"{description} is not an object")
    return value


def _require_exact(value: object, expected: object, description: str) -> None:
    if value != expected or type(value) is not type(expected):
        raise M0Error(f"{description} mismatch")


def _require_positive_integer(value: object, description: str) -> int:
    if type(value) is not int or value < 1:
        raise M0Error(f"{description} is not a positive integer")
    return value


def _reject_url_like_values(value: object, description: str = "result") -> None:
    if isinstance(value, str):
        if URL_LIKE_VALUE_PATTERN.search(value):
            raise M0Error(f"{description} contains a URL-like string")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_url_like_values(item, f"{description}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_url_like_values(key, f"{description} key")
            _reject_url_like_values(item, f"{description}.{key}")


def _validate_frame(
    value: object, description: str, *, minimum_id: int = 1
) -> dict[str, Any]:
    frame = _require_dict(value, description)
    if (
        _require_positive_integer(frame.get("id"), f"{description} id")
        < minimum_id
        or frame.get("width") != 800
        or frame.get("height") != 600
    ):
        raise M0Error(f"{description} is not the fixed host canvas frame")
    return frame


def expected_controlled_preflight_devtools_network() -> dict[str, object]:
    return {
        "protocol": 1,
        "state": "complete",
        "networkEnabled": True,
        "documentRequest": True,
        "responseReceived": True,
        "loadingFinished": True,
        "requestIdCorrelated": True,
        "responseStatus": 200,
        "responseProtocol": "h2",
        "wispWebSocketOpened": True,
        "wispHandshakeReady": True,
        "wispConfirmedStream": True,
        "wispDestinationMatched": True,
        "wispDeniedRequest": True,
        "wispDeniedLoadingFailed": True,
        "wispDeniedRequestIdCorrelated": True,
        "wispDeniedByAdministrator": True,
        "events": list(M5_CONTROLLED_PREFLIGHT_EVENTS),
    }


def validate_controlled_preflight_result(
    result: dict[str, Any], *, expected_versions: dict[str, str]
) -> None:
    """Require URL-free native CDP, navigation, WISP, and lifecycle evidence."""

    serialized = json.dumps(result, sort_keys=True, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > MAXIMUM_URL_FREE_RESULT_BYTES:
        raise M0Error("controlled preflight result exceeds its bound")
    _reject_url_like_values(result)
    for field, expected in {
        "protocol": 1,
        "case": M5_CONTROLLED_PREFLIGHT_CASE,
        "status": "pass",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "versions": expected_versions,
        "failedChecks": [],
        "navigationResult": {"ok": True, "scheme": "https"},
    }.items():
        _require_exact(result.get(field), expected, f"controlled {field}")

    initial_frame = _validate_frame(result.get("initialFrame"), "initial frame")
    controlled_frame = _validate_frame(
        result.get("controlledPreflightFrame"),
        "controlled preflight frame",
        minimum_id=initial_frame["id"] + 1,
    )
    if controlled_frame["id"] <= initial_frame["id"]:
        raise M0Error("controlled preflight did not present a later frame")

    _require_exact(
        result.get("controlledPreflightDevtoolsNetworkEnabled"),
        {"protocol": 1, "state": "enabled", "networkEnabled": True, "events": []},
        "controlled DevTools Network.enable",
    )
    readiness = _require_dict(result.get("readiness"), "controlled readiness")
    for field in (
        "runtimeInitialized",
        "shellReady",
        "surfaceReady",
        "navigationCommitted",
        "firstVisuallyNonEmptyPaint",
    ):
        if readiness.get(field) is not True:
            raise M0Error(f"controlled readiness field {field} is not true")
    if readiness.get("fatalErrors") != []:
        raise M0Error("controlled readiness reported fatal errors")
    _require_exact(
        readiness.get("navigation"),
        {
            "committed": True,
            "scheme": "https",
            "responseCode": 200,
            "connectionProtocol": "h2",
        },
        "controlled navigation",
    )
    _require_exact(
        readiness.get("controlledPreflightDevtoolsNetwork"),
        expected_controlled_preflight_devtools_network(),
        "controlled DevTools Network trace",
    )
    heartbeat = _require_dict(readiness.get("heartbeat"), "controlled heartbeat")
    if heartbeat.get("anchor") != M5_CONTROLLED_PREFLIGHT_HEARTBEAT:
        raise M0Error("controlled heartbeat is not navigation-anchored")
    for field in ("timerDelta", "animationFrameDelta"):
        if type(heartbeat.get(field)) is not int or heartbeat[field] < 2:
            raise M0Error(f"controlled heartbeat {field} is too small")
    max_gap = heartbeat.get("maxTimerGapMs")
    if type(max_gap) not in (int, float) or not 0 <= max_gap <= 250:
        raise M0Error("controlled heartbeat maxTimerGapMs is out of range")

    logs = _require_dict(result.get("logs"), "controlled logs")
    host_logs = logs.get("host")
    if not isinstance(host_logs, list) or not all(
        isinstance(item, str) for item in host_logs
    ):
        raise M0Error("controlled host logs are invalid")
    required_logs = (
        "initialize:wisp-configured",
        "navigation:requested:data",
        "m5:controlled-preflight-devtools-network:start-requested",
        "m5:controlled-preflight-devtools-network:enabled",
        "navigation:requested:m5-controlled-preflight",
        "navigation:committed:m5-controlled-preflight",
        "m5:controlled-preflight-devtools-network:complete",
        "shutdown:complete",
    )
    for marker in required_logs:
        if host_logs.count(marker) != 1:
            raise M0Error(f"controlled host logs must contain one {marker!r}")
    if [host_logs.index(marker) for marker in required_logs] != sorted(
        host_logs.index(marker) for marker in required_logs
    ):
        raise M0Error("controlled host logs do not preserve phase order")
    if host_logs[-1:] != ["shutdown:complete"]:
        raise M0Error("controlled host logs do not end with shutdown")

    shutdown = _require_dict(result.get("shutdown"), "controlled shutdown")
    for field in ("ok", "accepted", "complete"):
        if shutdown.get(field) is not True:
            raise M0Error(f"controlled shutdown {field} is not true")
    for field in ("exitCode", "runtimeExitCode"):
        if shutdown.get(field) != 0:
            raise M0Error(f"controlled shutdown {field} is not zero")


def validate_controlled_preflight_relay_transcript(
    status: dict[str, Any]
) -> None:
    """Require the native :444 denial before exactly one mapped :443 stream."""

    if status.get("fixture") != M5_FIXTURE or status.get("protocol") != 1:
        raise M0Error("controlled relay fixture or protocol mismatch")
    if status.get("ready") is not True:
        raise M0Error("controlled relay did not report readiness")
    for field, expected in {
        "wispSessions": 1,
        "rejectedDestinations": 1,
        "localGatewayBlockedPortAttempts": 1,
        "localGateway443StreamsOpened": 1,
        "localGateway443Requests": 1,
        "udpPackets": 0,
        "relayErrors": 0,
    }.items():
        if status.get(field) != expected:
            raise M0Error(
                f"controlled relay {field} mismatch: expected {expected!r}")
    _require_exact(
        status.get("h2Requests"), {"protocol": "h2", "count": 1},
        "controlled relay H2 requests",
    )
    _require_exact(
        status.get("requestedDestinations"),
        [{"hostname": M5_TEST_HOSTNAME, "port": 443}],
        "controlled relay requested destinations",
    )
    transcript = status.get("transcript")
    if not isinstance(transcript, list) or not all(
        isinstance(entry, dict) for entry in transcript
    ):
        raise M0Error("controlled relay transcript is invalid")
    events = [entry.get("event") for entry in transcript]
    required_events = (
        "wisp-connected",
        "wisp-ready",
        "local-gateway-444-blocked",
        "connect-requested",
        "connect-open",
        "local-gateway-443-request",
    )
    for event in required_events:
        if events.count(event) != 1:
            raise M0Error(f"controlled relay requires one {event!r} event")
    if any(event in events for event in (
        "connect-rejected", "local-gateway-443-route-rejected",
    )):
        raise M0Error("controlled relay recorded an unexpected target rejection")
    if [events.index(event) for event in required_events] != sorted(
        events.index(event) for event in required_events
    ):
        raise M0Error("controlled relay events are out of native preflight order")
    for event in ("local-gateway-444-blocked", "local-gateway-443-request"):
        entry = next(item for item in transcript if item.get("event") == event)
        if set(entry) != {"sequence", "event"}:
            raise M0Error(f"controlled relay {event!r} is not redacted")
    for event in ("connect-requested", "connect-open"):
        entry = next(item for item in transcript if item.get("event") == event)
        if entry.get("destination") != f"{M5_TEST_HOSTNAME}:443":
            raise M0Error(f"controlled relay {event!r} did not use a.test:443")


def controlled_preflight_debug_cdp_switches(port: int) -> list[str]:
    """Return the opt-in, loopback-only DevTools command-line switches."""

    if type(port) is not int or not 1 <= port <= 65535:
        raise M0Error("controlled preflight DevTools port is invalid")
    return [
        "--remote-allow-origins=http://localhost",
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={port}",
    ]


def _debug_cdp_count(value: object) -> int:
    if type(value) is not int or value < 0:
        return 0
    return min(value, DEBUG_CDP_MAXIMUM_COUNT)


def _debug_cdp_boolean(value: object) -> bool:
    return value is True


def _debug_cdp_enum(
    value: object, allowed: tuple[str, ...], fallback: str
) -> str:
    return value if isinstance(value, str) and value in allowed else fallback


def sanitize_controlled_preflight_debug_snapshot(value: object) -> dict[str, object]:
    """Whitelist one URL-free CDP snapshot schema before it reaches disk."""

    if not isinstance(value, dict):
        return {"state": "invalid"}

    page = value.get("page")
    host = value.get("host")
    resources = value.get("resources")
    page = page if isinstance(page, dict) else {}
    host = host if isinstance(host, dict) else {}
    resources = resources if isinstance(resources, dict) else {}
    markers = host.get("markers")
    markers = markers if isinstance(markers, dict) else {}
    readiness = host.get("readiness")
    readiness = readiness if isinstance(readiness, dict) else {}
    stdout_markers = host.get("stdout_markers")
    stdout_markers = (
        stdout_markers if isinstance(stdout_markers, dict) else {}
    )
    stderr_markers = host.get("stderr_markers")
    stderr_markers = (
        stderr_markers if isinstance(stderr_markers, dict) else {}
    )
    phases = host.get("phases")
    phases = phases if isinstance(phases, dict) else {}
    fatal_markers = host.get("fatal_markers")
    fatal_markers = fatal_markers if isinstance(fatal_markers, dict) else {}

    return {
        "state": "captured",
        "page": {
            "ready_state": _debug_cdp_enum(
                page.get("ready_state"),
                ("loading", "interactive", "complete", "other"),
                "other",
            ),
            "root_state": _debug_cdp_enum(
                page.get("root_state"),
                ("running", "pass", "fail", "missing", "other"),
                "other",
            ),
            "cross_origin_isolated": _debug_cdp_boolean(
                page.get("cross_origin_isolated")
            ),
            "shared_array_buffer": _debug_cdp_boolean(
                page.get("shared_array_buffer")
            ),
            "host_present": _debug_cdp_boolean(page.get("host_present")),
            "canvas_present": _debug_cdp_boolean(page.get("canvas_present")),
            "canvas_focused": _debug_cdp_boolean(page.get("canvas_focused")),
        },
        "host": {
            "logs_available": _debug_cdp_boolean(host.get("logs_available")),
            "host_log_count": _debug_cdp_count(host.get("host_log_count")),
            "stdout_line_count": _debug_cdp_count(
                host.get("stdout_line_count")
            ),
            "stderr_line_count": _debug_cdp_count(
                host.get("stderr_line_count")
            ),
            "fatal_log_count": _debug_cdp_count(host.get("fatal_log_count")),
            "markers": {
                "initialize_start": _debug_cdp_boolean(
                    markers.get("initialize_start")
                ),
                "wisp_configured": _debug_cdp_boolean(
                    markers.get("wisp_configured")
                ),
                "runtime_initialized": _debug_cdp_boolean(
                    markers.get("runtime_initialized")
                ),
                "factory_resolved": _debug_cdp_boolean(
                    markers.get("factory_resolved")
                ),
                "initialize_complete": _debug_cdp_boolean(
                    markers.get("initialize_complete")
                ),
            },
            "stdout_markers": {
                marker: _debug_cdp_count(stdout_markers.get(marker))
                for marker in DEBUG_CDP_LOG_MARKERS
            },
            "stderr_markers": {
                marker: _debug_cdp_count(stderr_markers.get(marker))
                for marker in DEBUG_CDP_LOG_MARKERS
            },
            "phases": {
                marker: _debug_cdp_boolean(phases.get(marker))
                for marker in DEBUG_CDP_PHASE_MARKERS
            },
            "fatal_markers": {
                marker: _debug_cdp_count(fatal_markers.get(marker))
                for marker in DEBUG_CDP_FATAL_MARKERS
            },
            "readiness": {
                "available": _debug_cdp_boolean(readiness.get("available")),
                "runtime_initialized": _debug_cdp_boolean(
                    readiness.get("runtime_initialized")
                ),
                "shell_ready": _debug_cdp_boolean(
                    readiness.get("shell_ready")
                ),
                "surface_ready": _debug_cdp_boolean(
                    readiness.get("surface_ready")
                ),
                "navigation_committed": _debug_cdp_boolean(
                    readiness.get("navigation_committed")
                ),
                "first_visually_non_empty_paint": _debug_cdp_boolean(
                    readiness.get("first_visually_non_empty_paint")
                ),
                "fatal_error_count": _debug_cdp_count(
                    readiness.get("fatal_error_count")
                ),
                "frame_present": _debug_cdp_boolean(
                    readiness.get("frame_present")
                ),
            },
        },
        "resources": {
            kind: _debug_cdp_count(resources.get(kind))
            for kind in DEBUG_CDP_RESOURCE_KINDS
        },
    }


def _controlled_preflight_relay_count(value: object) -> int:
    if type(value) is not int or value < 0:
        return 0
    return min(value, DEBUG_CDP_MAXIMUM_COUNT)


def sanitize_controlled_preflight_relay_status(
    value: object, *, capture_state: str
) -> dict[str, object]:
    """Whitelist bounded, URL-free relay evidence for a failure artifact."""

    if capture_state not in CONTROLLED_PREFLIGHT_RELAY_CAPTURE_STATES:
        return {"state": "invalid"}
    if capture_state != "captured":
        return {"state": capture_state}
    if not isinstance(value, dict):
        return {"state": "invalid"}

    h2_requests = value.get("h2Requests")
    h2_requests = h2_requests if isinstance(h2_requests, dict) else {}
    destinations = value.get("requestedDestinations")
    destinations = destinations if isinstance(destinations, list) else []
    transcript = value.get("transcript")
    transcript = transcript if isinstance(transcript, list) else []
    bounded_destinations = destinations[:DEBUG_CDP_MAXIMUM_COUNT]
    bounded_transcript = transcript[:DEBUG_CDP_MAXIMUM_COUNT]
    event_counts = {
        diagnostic_name: 0
        for diagnostic_name, _ in CONTROLLED_PREFLIGHT_RELAY_EVENTS
    }
    event_names = {
        event_name: diagnostic_name
        for diagnostic_name, event_name in CONTROLLED_PREFLIGHT_RELAY_EVENTS
    }
    for entry in bounded_transcript:
        if not isinstance(entry, dict):
            continue
        diagnostic_name = event_names.get(entry.get("event"))
        if diagnostic_name is not None:
            event_counts[diagnostic_name] += 1

    return {
        "state": "captured",
        "fixture_matches": value.get("fixture") == M5_FIXTURE,
        "protocol_matches": value.get("protocol") == 1,
        "ready": value.get("ready") is True,
        "counters": {
            diagnostic_name: _controlled_preflight_relay_count(
                value.get(status_name)
            )
            for diagnostic_name, status_name in CONTROLLED_PREFLIGHT_RELAY_COUNTERS
        },
        "h2": {
            "protocol": (
                "h2" if h2_requests.get("protocol") == "h2" else "other"
            ),
            "request_count": _controlled_preflight_relay_count(
                h2_requests.get("count")
            ),
        },
        "requested_destinations": {
            "count": _controlled_preflight_relay_count(len(destinations)),
            "a_test_443_count": sum(
                1
                for destination in bounded_destinations
                if isinstance(destination, dict)
                and destination.get("hostname") == M5_TEST_HOSTNAME
                and destination.get("port") == 443
            ),
        },
        "transcript_events": event_counts,
    }


def capture_controlled_preflight_relay_status(
    *,
    relay: subprocess.Popen[str] | None,
    relay_ready: RelayReady | None,
) -> tuple[dict[str, Any] | None, str]:
    """Read the local relay status before failure cleanup, if it is live.

    The raw status remains in memory only.  ``write_failure_diagnostics``
    applies the fixed redaction schema before writing any artifact.
    """

    if relay_ready is None:
        return None, "not_ready"
    if relay is None or relay.poll() is not None:
        return None, "relay_exited"
    try:
        return (
            fetch_relay_transcript(
                relay_ready.transcript_url, timeout_seconds=2.0
            ),
            "captured",
        )
    except (M0Error, OSError, KeyError, TypeError, ValueError):
        return None, "unavailable"
    except Exception:
        return None, "internal_error"


def capture_controlled_preflight_debug_snapshot(
    *,
    browser: subprocess.Popen[str],
    debug_port: int,
    host_url_prefix: str,
) -> dict[str, object]:
    """Best-effort, redacted CDP state capture for a no-result failure.

    This is intentionally a one-shot diagnostic. It does not drive the page,
    does not enable console logging, and never lets a DevTools failure replace
    the original controlled-preflight error.
    """

    if browser.poll() is not None:
        return {"state": "browser_exited"}

    client = None
    try:
        client = wait_for_page_client(
            debug_port,
            host_url_prefix,
            time.monotonic() + DEBUG_CDP_CONNECT_TIMEOUT_SECONDS,
        )
    except (M0Error, OSError, TypeError, ValueError):
        return {"state": "target_unavailable"}

    try:
        return sanitize_controlled_preflight_debug_snapshot(
            client.evaluate(DEBUG_CDP_SNAPSHOT_EXPRESSION)
        )
    except (M0Error, OSError, TypeError, ValueError):
        return {"state": "evaluate_unavailable"}
    except Exception:
        return {"state": "internal_error"}
    finally:
        if client is not None:
            client.close()


def write_failure_diagnostics(
    diagnostics_dir: Path,
    *,
    stage: str,
    error: Exception,
    result: dict[str, Any] | None,
    relay_status: dict[str, Any] | None,
    relay_capture_state: str,
    browser_stderr: deque[str],
    relay_stderr: deque[str],
    debug_cdp: dict[str, object] | None = None,
) -> Path:
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    output = diagnostics_dir / "m5-controlled-preflight-failure.json"
    payload = {
        "schema_version": 1,
        "runner": "run_m5_controlled_preflight_smoke.py",
        "case": M5_CONTROLLED_PREFLIGHT_CASE,
        "status": "fail",
        "stage": stage,
        "failure": {"type": type(error).__name__, "message": str(error)},
        "browser_stderr_tail": list(browser_stderr),
        "relay_stderr_tail": list(relay_stderr),
        "runtime_result": result,
        "relay_status": sanitize_controlled_preflight_relay_status(
            relay_status, capture_state=relay_capture_state
        ),
    }
    if debug_cdp is not None:
        payload["debug_cdp"] = debug_cdp
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the isolated local M5 WISP gateway-denial preflight."
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument(
        "--out-dir", type=Path, default=Path("out/wasm-content-m3")
    )
    parser.add_argument("--module-name", default=M5_CONTROLLED_PREFLIGHT_MODULE)
    parser.add_argument("--node", type=Path)
    parser.add_argument(
        "--relay-script",
        type=Path,
        default=REPO_ROOT / "tools/wasm/m5_wisp_test_server.js",
    )
    parser.add_argument("--diagnostics-dir", type=Path)
    parser.add_argument(
        "--debug-cdp",
        action="store_true",
        help="capture a redacted loopback DevTools snapshot after a no-result timeout",
    )
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--timeout", type=parse_timeout, default=120.0)
    parser.add_argument("--verbose-server", action="store_true")
    args = parser.parse_args()

    out_dir = args.out_dir if args.out_dir.is_absolute() else REPO_ROOT / args.out_dir
    diagnostics_dir = args.diagnostics_dir or (
        out_dir / "diagnostics-m5-controlled-preflight"
    )
    if not diagnostics_dir.is_absolute():
        diagnostics_dir = REPO_ROOT / diagnostics_dir
    relay_script = args.relay_script
    if not relay_script.is_absolute():
        relay_script = REPO_ROOT / relay_script
    relay_script = relay_script.resolve()

    server = None
    server_thread = None
    browser: subprocess.Popen[str] | None = None
    relay: subprocess.Popen[str] | None = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    browser_stderr: deque[str] = deque(maxlen=300)
    relay_stdout: deque[str] = deque(maxlen=300)
    relay_stderr: deque[str] = deque(maxlen=300)
    browser_stderr_thread = None
    relay_stdout_thread = None
    relay_stderr_thread = None
    result: dict[str, Any] | None = None
    relay_status: dict[str, Any] | None = None
    relay_capture_state = "not_ready"
    relay_ready: RelayReady | None = None
    debug_cdp: dict[str, object] | None = None
    debug_port: int | None = None
    host_url_prefix: str | None = None
    stage = "load_manifest"
    server_started = False

    try:
        manifest = load_manifest()
        versions = manifest_versions(manifest, checked_output(["git", "rev-parse", "HEAD"]))
        print_context(
            "run_m5_controlled_preflight_smoke.py",
            manifest,
            case=M5_CONTROLLED_PREFLIGHT_CASE,
            gn_args=manifest.get("m3_content_gn_args", manifest.get("gn_args")),
            module_name=args.module_name,
            host_browser_sandbox=not args.no_sandbox,
            transport="WISP v2.1 over a local test-only WebSocket relay",
        )
        stage = "find_browser"
        browser_path, browser_version = find_browser(args.browser)
        print(
            f"{SENTINEL}:HOST_BROWSER " + json.dumps(
                {"browser_version": browser_version},
                sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        stage = "find_node"
        node = find_node(args.node)
        if not relay_script.is_file():
            raise M0Error("controlled preflight relay script is missing")
        stage = "verify_test_artifacts"
        verify_no_private_key_pem_artifacts(out_dir, args.module_name)
        token = secrets.token_urlsafe(24)
        result_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        stage = "create_host_server"
        server = create_m3_server(
            "127.0.0.1", 0, out_dir, token, result_queue,
            module_name=args.module_name, verbose=args.verbose_server)
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m5-controlled-preflight-host-server",
            daemon=True,
        )
        server_thread.start()
        server_started = True

        stage = "launch_relay"
        relay = subprocess.Popen(
            relay_command(node, relay_script, m5_host_origin(server)),
            cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True)
        assert relay.stdout is not None
        assert relay.stderr is not None
        ready_lines: queue.Queue[str | None] = queue.Queue()
        relay_stdout_thread = threading.Thread(
            target=_drain_relay_stdout,
            args=(relay.stdout, relay_stdout, ready_lines), daemon=True)
        relay_stdout_thread.start()
        relay_stderr_thread = threading.Thread(
            target=drain_stream, args=(relay.stderr, relay_stderr), daemon=True)
        relay_stderr_thread.start()
        stage = "wait_for_relay_ready"
        relay_ready = wait_for_relay_ready(
            relay, ready_lines, relay_stderr,
            time.monotonic() + min(30.0, max(1.0, args.timeout - 1.0)))
        print(f"{SENTINEL}:RELAY_READY loopback=true", flush=True)

        url = controlled_preflight_smoke_url(
            server, token, versions, relay_ready=relay_ready,
            module_name=args.module_name,
            timeout_seconds=min(180.0, max(1.0, args.timeout - 1.0)))
        profile = tempfile.TemporaryDirectory(
            prefix="chromium-wasm-m5-controlled-preflight-")
        stage = "launch_browser"
        command = m5_browser_command(
            browser_path, profile.name, url, no_sandbox=args.no_sandbox
        )
        if args.debug_cdp:
            debug_port = unused_loopback_port()
            command[1:1] = controlled_preflight_debug_cdp_switches(debug_port)
            host_url_prefix = url.split("?", 1)[0]
        browser = subprocess.Popen(
            command,
            cwd=REPO_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, start_new_session=True)
        assert browser.stderr is not None
        browser_stderr_thread = threading.Thread(
            target=drain_stream, args=(browser.stderr, browser_stderr), daemon=True)
        browser_stderr_thread.start()
        deadline = time.monotonic() + args.timeout
        stage = "wait_for_result"
        result = wait_for_result(browser, browser_stderr, result_queue, deadline)
        stage = "validate_runtime_contract"
        validate_controlled_preflight_result(result, expected_versions=versions)
        stage = "fetch_relay_transcript"
        relay_status = fetch_relay_transcript(
            relay_ready.transcript_url,
            timeout_seconds=min(10.0, max(1.0, deadline - time.monotonic())))
        relay_capture_state = "captured"
        stage = "validate_relay_transcript"
        validate_controlled_preflight_relay_transcript(relay_status)
        print(
            f"{SENTINEL}:BROWSER_RESULT " + json.dumps(
                result, sort_keys=True, separators=(",", ":")), flush=True)
        print(
            f"{SENTINEL}:RELAY_TRANSCRIPT " + json.dumps(
                relay_status, sort_keys=True, separators=(",", ":")), flush=True)
        print(f"{SENTINEL}:PASS", flush=True)
        return 0
    except (M0Error, OSError, KeyError, TypeError, ValueError) as exc:
        if relay_status is None:
            relay_status, relay_capture_state = (
                capture_controlled_preflight_relay_status(
                    relay=relay, relay_ready=relay_ready
                )
            )
        if (
            args.debug_cdp
            and stage == "wait_for_result"
            and result is None
            and browser is not None
            and debug_port is not None
            and host_url_prefix is not None
        ):
            debug_cdp = capture_controlled_preflight_debug_snapshot(
                browser=browser,
                debug_port=debug_port,
                host_url_prefix=host_url_prefix,
            )
        if browser is not None:
            stop_browser(browser)
        if relay is not None:
            stop_browser(relay)
        try:
            diagnostic = write_failure_diagnostics(
                diagnostics_dir, stage=stage, error=exc, result=result,
                relay_status=relay_status,
                relay_capture_state=relay_capture_state,
                browser_stderr=browser_stderr,
                relay_stderr=relay_stderr, debug_cdp=debug_cdp)
            print(f"{SENTINEL}:DIAGNOSTICS {json.dumps({'path': str(diagnostic)})}",
                  file=sys.stderr, flush=True)
        except OSError as diagnostic_error:
            print(f"{SENTINEL}:DIAGNOSTICS_FAIL reason={diagnostic_error}",
                  file=sys.stderr, flush=True)
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
        if server_thread is not None:
            server_thread.join(timeout=3)
        for thread in (
            browser_stderr_thread, relay_stdout_thread, relay_stderr_thread,
        ):
            if thread is not None:
                thread.join(timeout=1)


if __name__ == "__main__":
    sys.exit(main())
