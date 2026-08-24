#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the bounded native Chromium UI-sequence repeating-timer smoke.

This is M9 preparation evidence, not an M9 release gate. It proves only that
one visible single-process Browser executes three fixed ``base::RepeatingTimer``
callbacks while the outer host event loop remains responsive, then reaches the
ordinary Browser destruction barrier without later timer output. It does not
measure long-run timer reliability, worker drain, memory leaks, performance,
persistence, networking, a visually non-empty Chrome shell, or M8 feature
compatibility. The canvas must be surface-ready, but this smoke does not claim
the shell or first visually non-empty paint readiness reports.
"""

from __future__ import annotations

import argparse
from collections import deque
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
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
from typing import Any, Callable
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
from m9_browser_cleanup import (
    BrowserStderrReader,
    abort_browser_group,
    stop_browser_group,
)
from m9_descriptor_snapshot import snapshot_regular_file, snapshot_regular_files
from m9_server_cleanup import M9TrackingThreadingHTTPServer, shutdown_server_bounded
from run_browser_smoke import browser_command, find_browser
from run_content_shell_smoke import manifest_versions
import run_wasm_browser_view_smoke as browser_view_smoke


SENTINEL = "CHROMIUM_WASM_M9_REPEATING_TIMER_DOM"
CASE = "browser_repeating_timer_m9"
SCOPE = (
    "fixed-three-native-ui-repeating-timer-ticks-with-pre-shutdown-"
    "quiescence-and-post-shutdown-quiet-observation"
)
SWITCH = "--wasm-browser-m9-repeating-timer-smoke"
READY_MARKER = "CHROMIUM_WASM_M9_REPEATING_TIMER:READY ticks=3 interval_ms=50"
TICK_MARKER_PREFIX = "CHROMIUM_WASM_M9_REPEATING_TIMER:TICK ordinal="
QUIESCENCE_DURATION_MS = 200
QUIESCENT_MARKER = (
    "CHROMIUM_WASM_M9_REPEATING_TIMER:QUIESCENT ticks=3 duration_ms=200"
)
PASS_MARKER = "CHROMIUM_WASM_M9_REPEATING_TIMER:PASS ticks=3"
TIMEOUT_MARKER_PREFIX = "CHROMIUM_WASM_M9_REPEATING_TIMER:TIMEOUT"
TIMER_MARKER_PREFIX = "CHROMIUM_WASM_M9_REPEATING_TIMER:"
LIFECYCLE_PASS_MARKER = "CHROMIUM_WASM_M6_BROWSER_LIFECYCLE:PASS"
TICK_COUNT = 3
POST_EXIT_GRACE_MS = 100
HOST_ROOT = "/__m9_repeating_timer__"
PRODUCT_MODULE_NAME = "chrome_wasm"
MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
MAX_RESULT_BYTES = 1024 * 1024
MAX_ARTIFACT_BYTES = 4 * 1024 * 1024 * 1024
ARTIFACT_SOURCE_PROVENANCE = "unverified"
ARTIFACT_DELIVERY = "immutable-in-memory-server-snapshot"
SOURCE_SNAPSHOT_PROVENANCE = (
    "on-disk-byte-snapshots-at-server-startup-not-commit-provenance"
)
VERSION_PROVENANCE = (
    "toolchain-manifest-metadata-and-current-checkout-head-only-not-artifact-or-"
    "harness-source-provenance"
)
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
_CAPTURE_HARNESS_FIELDS = frozenset(
    (
        "host_html",
        "host_js",
        "runner_source",
        "source_snapshot_provenance",
        "version_provenance",
    )
)


class RepeatingTimerSmokeServer(M9TrackingThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    module_name: str
    result_queue: queue.Queue[dict[str, Any]]
    result_token: str
    result_received: bool
    result_lock: threading.Lock
    artifacts: dict[str, bytes]
    host_html: bytes
    host_js: bytes
    runner_source: bytes


class RepeatingTimerSmokeRequestHandler(BaseHTTPRequestHandler):
    server: RepeatingTimerSmokeServer

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

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path in (HOST_ROOT, f"{HOST_ROOT}/"):
            self._send_bytes(
                HTTPStatus.OK, "text/html; charset=utf-8", self.server.host_html
            )
            return
        if path == f"{HOST_ROOT}/chrome_wasm_browser_m9_repeating_timer_smoke.js":
            self._send_bytes(
                HTTPStatus.OK,
                "text/javascript; charset=utf-8",
                self.server.host_js,
            )
            return
        prefix = f"{HOST_ROOT}/artifacts/"
        if path.startswith(prefix):
            artifact_name = path[len(prefix) :]
            artifact = self.server.artifacts.get(artifact_name)
            if artifact is None:
                self._not_found()
                return
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
                b"invalid repeating-timer result\n",
            )
            return
        with self.server.result_lock:
            if self.server.result_received:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"repeating-timer result already received\n",
                )
                return
            try:
                self.server.result_queue.put_nowait(result)
            except queue.Full:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"repeating-timer result queue is full\n",
                )
                return
            self.server.result_received = True
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()


def parse_result_payload(payload: bytes) -> dict[str, Any] | None:
    try:
        result = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=browser_view_smoke._reject_duplicate_result_object_keys,
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


def _require_product_module_name(module_name: object, boundary: str) -> str:
    if not isinstance(module_name, str) or not MODULE_NAME_RE.fullmatch(module_name):
        raise M0Error(f"repeating-timer {boundary} module name is invalid")
    if module_name != PRODUCT_MODULE_NAME:
        raise M0Error(
            "repeating-timer "
            f"{boundary} only supports the {PRODUCT_MODULE_NAME} product module"
        )
    return module_name


def _snapshot_artifacts(
    out_dir: Path, module_name: str
) -> tuple[dict[str, bytes], dict[str, dict[str, object]]]:
    module_name = _require_product_module_name(module_name, "artifact")
    names = (f"{module_name}.js", f"{module_name}.wasm")
    artifacts = snapshot_regular_files(
        out_dir,
        names,
        maximum_bytes=MAX_ARTIFACT_BYTES,
        description="repeating-timer artifacts",
    )
    return artifacts, {name: _byte_identity(contents) for name, contents in artifacts.items()}


def create_server(
    host: str,
    port: int,
    out_dir: Path,
    result_token: str,
    result_queue: queue.Queue[dict[str, Any]],
    *,
    module_name: str,
) -> tuple[RepeatingTimerSmokeServer, dict[str, dict[str, object]]]:
    module_name = _require_product_module_name(module_name, "server")
    artifacts, artifact_identity = _snapshot_artifacts(out_dir, module_name)
    return (
        create_server_from_artifacts(
            host,
            port,
            artifacts,
            result_token,
            result_queue,
            module_name=module_name,
        ),
        artifact_identity,
    )


def create_server_from_artifacts(
    host: str,
    port: int,
    artifacts: dict[str, bytes],
    result_token: str,
    result_queue: queue.Queue[dict[str, Any]],
    *,
    module_name: str,
    host_dir: Path | None = None,
    runner_source_path: Path | None = None,
) -> RepeatingTimerSmokeServer:
    """Serve one already-captured private module without rereading it by path.

    The ordinary runner snapshots the raw build output before entering this
    helper. Package-bound runners use the same helper with aliases of verified
    public package bytes. In either case, the server owns only immutable bytes
    captured before its listening socket is created.
    """

    module_name = _require_product_module_name(module_name, "server")
    expected_artifact_names = {f"{module_name}.js", f"{module_name}.wasm"}
    if (
        type(artifacts) is not dict
        or set(artifacts) != expected_artifact_names
        or any(
            type(contents) is not bytes or not contents
            for contents in artifacts.values()
        )
    ):
        raise M0Error("repeating-timer server artifacts are invalid")
    if not isinstance(result_queue, queue.Queue) or not isinstance(result_token, str):
        raise M0Error("repeating-timer server result channel is invalid")

    host_dir = host_dir or Path(__file__).with_name("host")
    host_snapshots = snapshot_regular_files(
        host_dir,
        (
            "chrome_wasm_browser_m9_repeating_timer_smoke.html",
            "chrome_wasm_browser_m9_repeating_timer_smoke.js",
        ),
        maximum_bytes=MAX_ARTIFACT_BYTES,
        description="repeating-timer host resources",
    )
    runner_source = snapshot_regular_file(
        runner_source_path or Path(__file__),
        maximum_bytes=MAX_ARTIFACT_BYTES,
        description="repeating-timer runner source",
    )
    server = RepeatingTimerSmokeServer(
        (host, port), RepeatingTimerSmokeRequestHandler
    )
    server.result_token = result_token
    server.result_queue = result_queue
    server.result_received = False
    server.result_lock = threading.Lock()
    server.module_name = module_name
    server.artifacts = dict(artifacts)
    server.host_html = host_snapshots[
        "chrome_wasm_browser_m9_repeating_timer_smoke.html"
    ]
    server.host_js = host_snapshots[
        "chrome_wasm_browser_m9_repeating_timer_smoke.js"
    ]
    server.runner_source = runner_source
    return server


def _byte_identity(contents: bytes) -> dict[str, object]:
    return {"bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}


def artifact_identity(
    server: RepeatingTimerSmokeServer,
    *,
    module_name: str,
    artifact_delivery: str = ARTIFACT_DELIVERY,
    artifact_source_provenance: str = ARTIFACT_SOURCE_PROVENANCE,
) -> dict[str, object]:
    module_name = _require_product_module_name(module_name, "artifact")
    _require_product_module_name(server.module_name, "artifact server")
    if type(artifact_delivery) is not str or not artifact_delivery:
        raise M0Error("repeating-timer artifact delivery is invalid")
    if type(artifact_source_provenance) is not str or not artifact_source_provenance:
        raise M0Error("repeating-timer artifact source provenance is invalid")
    return {
        "artifact_delivery": artifact_delivery,
        "artifact_source_provenance": artifact_source_provenance,
        "loader": _byte_identity(server.artifacts[f"{module_name}.js"]),
        "module_name": module_name,
        "wasm": _byte_identity(server.artifacts[f"{module_name}.wasm"]),
    }


def capture_harness_identity(
    server: RepeatingTimerSmokeServer,
    *,
    version_provenance: str = VERSION_PROVENANCE,
) -> dict[str, object]:
    if type(version_provenance) is not str or not version_provenance:
        raise M0Error("repeating-timer capture-harness version provenance is invalid")
    return {
        "host_html": _byte_identity(server.host_html),
        "host_js": _byte_identity(server.host_js),
        "runner_source": _byte_identity(server.runner_source),
        "source_snapshot_provenance": SOURCE_SNAPSHOT_PROVENANCE,
        "version_provenance": version_provenance,
    }


def smoke_url(
    server: RepeatingTimerSmokeServer,
    token: str,
    versions: dict[str, str],
    *,
    artifact: dict[str, object],
    capture_harness: dict[str, object],
    module_name: str,
    timeout_seconds: float,
) -> str:
    module_name = _require_product_module_name(module_name, "URL")
    _require_product_module_name(server.module_name, "URL server")
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "token": token,
            "module": module_name,
            "timeoutMs": str(int(timeout_seconds * 1000)),
            "versions": json.dumps(versions, sort_keys=True, separators=(",", ":")),
            "artifact": json.dumps(artifact, sort_keys=True, separators=(",", ":")),
            "captureHarness": json.dumps(
                capture_harness, sort_keys=True, separators=(",", ":")
            ),
        }
    )
    return f"http://{host}:{port}{HOST_ROOT}/?{query}"


def _require_equal(result: dict[str, Any], field: str, expected: object) -> None:
    if not browser_view_smoke._exact_json_value_equal(result.get(field), expected):
        raise M0Error(
            f"repeating-timer result {field} mismatch: "
            f"expected {expected!r}, got {result.get(field)!r}"
        )


def _require_positive_int(value: object, description: str) -> int:
    if type(value) is not int or value < 0:
        raise M0Error(f"repeating-timer {description} is not a nonnegative integer")
    return value


def _validate_event_loop_snapshot(value: object, description: str) -> dict[str, int]:
    if not isinstance(value, dict) or set(value) != {
        "heartbeatCount",
        "animationFrameCount",
    }:
        raise M0Error(f"repeating-timer {description} shape is invalid")
    return {
        "heartbeatCount": _require_positive_int(
            value["heartbeatCount"], f"{description} heartbeat count"
        ),
        "animationFrameCount": _require_positive_int(
            value["animationFrameCount"], f"{description} frame count"
        ),
    }


def _validate_ticks(value: object) -> list[dict[str, int]]:
    if not isinstance(value, list) or len(value) != TICK_COUNT:
        raise M0Error("repeating-timer ticks do not have the fixed count")
    previous_heartbeat = -1
    previous_animation_frame = -1
    snapshots: list[dict[str, int]] = []
    for expected_ordinal, tick in enumerate(value, start=1):
        if not isinstance(tick, dict) or set(tick) != {
            "ordinal",
            "heartbeatCount",
            "animationFrameCount",
        }:
            raise M0Error("repeating-timer tick shape is invalid")
        if tick["ordinal"] != expected_ordinal:
            raise M0Error("repeating-timer tick ordinal is invalid")
        snapshot = _validate_event_loop_snapshot(
            {
                "heartbeatCount": tick["heartbeatCount"],
                "animationFrameCount": tick["animationFrameCount"],
            },
            "tick",
        )
        if (
            snapshot["heartbeatCount"] < previous_heartbeat
            or snapshot["animationFrameCount"] < previous_animation_frame
        ):
            raise M0Error("repeating-timer event-loop counters regressed")
        previous_heartbeat = snapshot["heartbeatCount"]
        previous_animation_frame = snapshot["animationFrameCount"]
        snapshots.append(snapshot)
    if (
        snapshots[-1]["heartbeatCount"] <= snapshots[0]["heartbeatCount"]
        and snapshots[-1]["animationFrameCount"]
        <= snapshots[0]["animationFrameCount"]
    ):
        raise M0Error(
            "repeating-timer host event-loop counters did not advance across native ticks"
        )
    return snapshots


def _validate_post_exit_observation(value: object) -> None:
    expected_fields = {
        "before",
        "after",
        "graceMs",
        "animationFrameAdvanced",
        "errorsQuiet",
        "framesQuiet",
        "heartbeatAdvanced",
        "timerMarkersQuiet",
    }
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise M0Error("repeating-timer post-exit observation shape is invalid")
    if value["graceMs"] != POST_EXIT_GRACE_MS:
        raise M0Error("repeating-timer post-exit grace is invalid")
    for field in (
        "animationFrameAdvanced",
        "errorsQuiet",
        "framesQuiet",
        "heartbeatAdvanced",
        "timerMarkersQuiet",
    ):
        if value[field] is not True:
            raise M0Error(f"repeating-timer post-exit check did not pass: {field}")
    expected_counts = {
        "animationFrameCount",
        "fatalErrors",
        "frameReports",
        "heartbeatCount",
        "timerMarkers",
        "unhandledRejections",
        "windowErrors",
    }
    for name in ("before", "after"):
        counts = value[name]
        if not isinstance(counts, dict) or set(counts) != expected_counts:
            raise M0Error(f"repeating-timer post-exit {name} count shape is invalid")
        for field, count in counts.items():
            _require_positive_int(count, f"post-exit {name} {field}")
    before = value["before"]
    after = value["after"]
    if (
        after["heartbeatCount"] <= before["heartbeatCount"]
        or after["animationFrameCount"] <= before["animationFrameCount"]
        or after["timerMarkers"] != before["timerMarkers"]
        or after["frameReports"] != before["frameReports"]
        or after["fatalErrors"] != before["fatalErrors"]
        or after["windowErrors"] != before["windowErrors"]
        or after["unhandledRejections"] != before["unhandledRejections"]
    ):
        raise M0Error("repeating-timer post-exit counters are inconsistent")


def _validate_native_markers(stderr: object) -> None:
    if not isinstance(stderr, list) or any(type(line) is not str for line in stderr):
        raise M0Error("repeating-timer stderr is invalid")
    timer_lines = [line for line in stderr if line.startswith(TIMER_MARKER_PREFIX)]
    expected_timer_lines = [
        READY_MARKER,
        *(f"{TICK_MARKER_PREFIX}{ordinal}" for ordinal in range(1, TICK_COUNT + 1)),
        QUIESCENT_MARKER,
        PASS_MARKER,
    ]
    if timer_lines != expected_timer_lines:
        raise M0Error("repeating-timer native markers are malformed or out of order")
    if any(line.startswith(TIMEOUT_MARKER_PREFIX) for line in stderr):
        raise M0Error("repeating-timer native watchdog timed out")
    if stderr.count(LIFECYCLE_PASS_MARKER) != 1:
        raise M0Error("repeating-timer lifecycle PASS marker is not unique")
    if stderr.index(LIFECYCLE_PASS_MARKER) <= stderr.index(PASS_MARKER):
        raise M0Error("repeating-timer lifecycle PASS did not follow native PASS")


def _require_exact_fields(
    value: object, expected: frozenset[str], description: str
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        actual = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise M0Error(
            f"repeating-timer {description} schema is invalid: "
            f"expected {sorted(expected)!r}, got {actual!r}"
        )
    return value


def _validate_byte_identity(value: object, description: str) -> None:
    identity = _require_exact_fields(value, _BYTE_IDENTITY_FIELDS, description)
    if type(identity.get("bytes")) is not int or identity["bytes"] < 1:
        raise M0Error(f"repeating-timer {description} byte count is invalid")
    digest = identity.get("sha256")
    if type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise M0Error(f"repeating-timer {description} SHA-256 is invalid")


def _validate_artifact_identity(
    value: object,
    expected_identity: dict[str, object],
    *,
    expected_artifact_delivery: str = ARTIFACT_DELIVERY,
    expected_artifact_source_provenance: str = ARTIFACT_SOURCE_PROVENANCE,
) -> None:
    artifact = _require_exact_fields(value, _ARTIFACT_IDENTITY_FIELDS, "artifact")
    if artifact.get("artifact_delivery") != expected_artifact_delivery:
        raise M0Error("repeating-timer artifact delivery is invalid")
    if (
        artifact.get("artifact_source_provenance")
        != expected_artifact_source_provenance
    ):
        raise M0Error("repeating-timer artifact source provenance is invalid")
    _require_product_module_name(artifact.get("module_name"), "artifact")
    for field in ("loader", "wasm"):
        _validate_byte_identity(artifact.get(field), f"artifact {field}")
    if not browser_view_smoke._exact_json_value_equal(artifact, expected_identity):
        raise M0Error("repeating-timer artifact identity disagrees with served snapshot")


def _validate_capture_harness_identity(
    value: object,
    expected_identity: dict[str, object],
    *,
    expected_version_provenance: str = VERSION_PROVENANCE,
) -> None:
    harness = _require_exact_fields(
        value, _CAPTURE_HARNESS_FIELDS, "capture harness"
    )
    if harness.get("source_snapshot_provenance") != SOURCE_SNAPSHOT_PROVENANCE:
        raise M0Error("repeating-timer capture-harness source provenance is invalid")
    if harness.get("version_provenance") != expected_version_provenance:
        raise M0Error("repeating-timer capture-harness version provenance is invalid")
    for field in ("host_html", "host_js", "runner_source"):
        _validate_byte_identity(harness.get(field), f"capture harness {field}")
    if not browser_view_smoke._exact_json_value_equal(harness, expected_identity):
        raise M0Error(
            "repeating-timer capture harness disagrees with served snapshot"
        )


def validate_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
    expected_artifact_identity: dict[str, object],
    expected_capture_harness_identity: dict[str, object],
    expected_artifact_delivery: str = ARTIFACT_DELIVERY,
    expected_artifact_source_provenance: str = ARTIFACT_SOURCE_PROVENANCE,
    expected_version_provenance: str = VERSION_PROVENANCE,
) -> None:
    for field, expected in {
        "protocol": 1,
        "case": CASE,
        "scope": SCOPE,
        "status": "pass",
        "m9GateComplete": False,
        "m9TimerSmokeOnly": True,
        "runtimeExitCode": 0,
        "processExitCode": 0,
        "runtimeInitialized": True,
        "factorySettled": True,
        "factoryRejected": False,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "readyObserved": True,
        "quiescentObserved": True,
        "passObserved": True,
        "lifecyclePassObserved": True,
        "ozoneFocusObserved": True,
        "abort": None,
        "failedChecks": [],
        "error": None,
    }.items():
        _require_equal(result, field, expected)
    if result.get("versions") != expected_versions:
        raise M0Error("repeating-timer versions do not match the manifest")
    _validate_artifact_identity(
        result.get("artifact"),
        expected_artifact_identity,
        expected_artifact_delivery=expected_artifact_delivery,
        expected_artifact_source_provenance=expected_artifact_source_provenance,
    )
    _validate_capture_harness_identity(
        result.get("captureHarness"),
        expected_capture_harness_identity,
        expected_version_provenance=expected_version_provenance,
    )
    for field in ("fatalErrors", "windowErrors", "unhandledRejections"):
        if not isinstance(result.get(field), list) or result[field]:
            raise M0Error(f"repeating-timer {field} is not empty")
    if not isinstance(result.get("stdout"), list):
        raise M0Error("repeating-timer stdout is not a list")
    _validate_native_markers(result.get("stderr"))
    ticks = _validate_ticks(result.get("ticks"))
    quiescence_responsiveness = _validate_event_loop_snapshot(
        result.get("responsivenessAtQuiescent"), "quiescence responsiveness"
    )
    if (
        quiescence_responsiveness["heartbeatCount"]
        <= ticks[-1]["heartbeatCount"]
        or quiescence_responsiveness["animationFrameCount"]
        <= ticks[-1]["animationFrameCount"]
    ):
        raise M0Error(
            "repeating-timer host event loop did not advance during native quiescence"
        )
    responsiveness = _validate_event_loop_snapshot(
        result.get("responsivenessAtPass"), "pass responsiveness"
    )
    if responsiveness["heartbeatCount"] < 2:
        raise M0Error("repeating-timer host interval did not advance before pass")
    if responsiveness["animationFrameCount"] < 1:
        raise M0Error("repeating-timer host animation frame did not advance before pass")
    _validate_post_exit_observation(result.get("postExitObservation"))
    browser_view_smoke._validate_frame_reports(result.get("frameReports"))
    browser_view_smoke._validate_readiness(
        result.get("readiness"), result.get("readinessReports")
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
                "host browser exited before repeating-timer result: "
                + "\n".join(browser_stderr)
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M0Error(
                "repeating-timer smoke timeout: " + "\n".join(browser_stderr)
            )
        try:
            return result_queue.get(timeout=min(0.1, remaining))
        except queue.Empty:
            continue


def write_failure_diagnostics(
    diagnostics_dir: Path,
    *,
    stage: str,
    error: Exception,
    browser_path: Path | None,
    browser_version: str | None,
    browser: subprocess.Popen[str] | None,
    browser_stderr: deque[str],
    runtime_result: dict[str, Any] | None,
    artifact_snapshot: dict[str, dict[str, object]] | None,
    artifact: dict[str, object] | None,
    capture_harness: dict[str, object] | None,
) -> Path:
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / "chrome-browser-m9-repeating-timer-failure.json"
    payload = {
        "schema_version": 1,
        "runner": "run_m9_wasm_browser_repeating_timer_dom_smoke.py",
        "case": CASE,
        "scope": SCOPE,
        "stage": stage,
        "failure": {"type": type(error).__name__, "message": str(error)},
        "host_browser": {
            "path": str(browser_path) if browser_path else None,
            "version": browser_version,
            "return_code": browser.poll() if browser else None,
            "stderr_tail": list(browser_stderr),
        },
        "artifact_snapshot": artifact_snapshot,
        "artifact": artifact,
        "capture_harness": capture_harness,
        "runtime_result": runtime_result,
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return path


def _run_cleanup_action(
    cleanup_error: BaseException | None, action: Callable[[], object]
) -> BaseException | None:
    """Runs one cleanup action without preventing later cleanup actions."""

    try:
        action()
    except BaseException as error:
        if cleanup_error is None:
            return error
    return cleanup_error


def _join_repeating_timer_server(thread: threading.Thread) -> None:
    """Joins a started repeating-timer server and rejects incomplete teardown."""

    thread.join(timeout=1)
    if thread.is_alive():
        raise M0Error("M9 repeating-timer server did not stop")


def _cleanup_repeating_timer_server(
    *,
    server: RepeatingTimerSmokeServer | None,
    server_thread: threading.Thread | None,
    server_thread_started: bool,
) -> BaseException | None:
    """Stops the server while always closing its socket and joining handlers."""

    cleanup_error: BaseException | None = None
    if server is not None:
        if server_thread_started:
            cleanup_error = _run_cleanup_action(
                cleanup_error,
                lambda: shutdown_server_bounded(
                    server, timeout=1, description="M9 repeating-timer server"
                ),
            )
        cleanup_error = _run_cleanup_action(cleanup_error, server.server_close)
    if server_thread_started and server_thread is not None:
        cleanup_error = _run_cleanup_action(
            cleanup_error, lambda: _join_repeating_timer_server(server_thread)
        )
    if server is not None:
        cleanup_error = _run_cleanup_action(
            cleanup_error,
            lambda: server.join_request_handlers(
                timeout=1, description="M9 repeating-timer server"
            ),
        )
    return cleanup_error


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the bounded Chromium UI-sequence repeating-timer smoke."
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--out-dir", type=Path, default=Path("out/wasm-chrome-m6"))
    parser.add_argument("--module-name", default=PRODUCT_MODULE_NAME)
    parser.add_argument("--diagnostics-dir", type=Path)
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--timeout", type=parse_timeout, default=60.0)
    args = parser.parse_args()
    if args.timeout < 2.0:
        parser.error("--timeout must be at least two seconds")
    if not MODULE_NAME_RE.fullmatch(args.module_name):
        parser.error("--module-name must contain only ASCII letters, digits, or _")
    if args.module_name != PRODUCT_MODULE_NAME:
        parser.error("--module-name must be chrome_wasm for this product timer smoke")

    out_dir = args.out_dir if args.out_dir.is_absolute() else REPO_ROOT / args.out_dir
    diagnostics_dir = args.diagnostics_dir or out_dir / "diagnostics"
    if not diagnostics_dir.is_absolute():
        diagnostics_dir = REPO_ROOT / diagnostics_dir
    server: RepeatingTimerSmokeServer | None = None
    server_thread: threading.Thread | None = None
    server_thread_started = False
    browser: subprocess.Popen[str] | None = None
    browser_path: Path | None = None
    browser_version: str | None = None
    browser_stderr: deque[str] = deque(maxlen=300)
    stderr_reader: BrowserStderrReader | None = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    result: dict[str, Any] | None = None
    artifact_snapshot: dict[str, dict[str, object]] | None = None
    artifact: dict[str, object] | None = None
    capture_harness: dict[str, object] | None = None
    stage = "check_artifacts"
    primary_error: BaseException | None = None
    reported_error: Exception | None = None

    try:
        stage = "check_boundary"
        check_boundary(out_dir)
        token = secrets.token_urlsafe(24)
        result_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        stage = "snapshot_server_inputs"
        server, artifact_snapshot = create_server(
            "127.0.0.1", 0, out_dir, token, result_queue, module_name=args.module_name
        )
        artifact = artifact_identity(server, module_name=args.module_name)
        capture_harness = capture_harness_identity(server)
        stage = "load_manifest"
        manifest = load_manifest()
        versions = manifest_versions(
            manifest, checked_output(["git", "rev-parse", "HEAD"])
        )
        print_context(
            "run_m9_wasm_browser_repeating_timer_dom_smoke.py",
            manifest,
            case=CASE,
            scope=SCOPE,
            gn_args=manifest.get("m6_chrome_gn_args", manifest.get("gn_args")),
            module_name=args.module_name,
            host_browser_sandbox=not args.no_sandbox,
            runtime_arguments=[SWITCH],
            artifact=artifact,
            capture_harness=capture_harness,
            version_provenance=VERSION_PROVENANCE,
        )
        stage = "find_browser"
        browser_path, browser_version = find_browser(args.browser)
        stage = "serve"
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m9-repeating-timer-server",
            daemon=True,
        )
        server_thread.start()
        server_thread_started = True
        url = smoke_url(
            server,
            token,
            versions,
            artifact=artifact,
            capture_harness=capture_harness,
            module_name=args.module_name,
            timeout_seconds=max(1.0, args.timeout - 1.0),
        )
        profile = tempfile.TemporaryDirectory(prefix="chromium-wasm-m9-repeating-timer-")
        stage = "launch_browser"
        command = browser_command(
            browser_path, profile.name, url, no_sandbox=args.no_sandbox
        )
        command[1:1] = ["--enable-logging=stderr"]
        browser = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        assert browser.stderr is not None
        stderr_reader = BrowserStderrReader(
            browser.stderr,
            browser_stderr,
            name="chromium-wasm-m9-repeating-timer-browser-stderr",
            thread_factory=threading.Thread,
        )
        stderr_reader.start()
        stage = "wait_for_normal_close_result"
        result = wait_for_result(
            browser, browser_stderr, result_queue, time.monotonic() + args.timeout
        )
        stage = "validate_result"
        validate_result(
            result,
            expected_versions=versions,
            expected_artifact_identity=artifact,
            expected_capture_harness_identity=capture_harness,
        )
    except (M0Error, OSError, KeyError, TypeError, ValueError) as error:
        primary_error = error
        reported_error = error
    except BaseException as error:
        primary_error = error
        raise
    finally:
        cleanup_error: BaseException | None = None
        if browser is not None and stderr_reader is not None and stderr_reader.started:
            cleanup_error = _run_cleanup_action(
                cleanup_error, lambda: stop_browser_group(browser, stderr_reader)
            )
        elif browser is not None:
            unowned_streams = ()
            if stderr_reader is None and browser.stderr is not None:
                unowned_streams = (browser.stderr,)
            cleanup_error = _run_cleanup_action(
                cleanup_error,
                lambda: abort_browser_group(
                    browser, stderr_reader, unowned_streams=unowned_streams
                ),
            )
        server_cleanup_error = _cleanup_repeating_timer_server(
            server=server,
            server_thread=server_thread,
            server_thread_started=server_thread_started,
        )
        if cleanup_error is None:
            cleanup_error = server_cleanup_error
        if profile is not None:
            cleanup_error = _run_cleanup_action(cleanup_error, profile.cleanup)
        if primary_error is None and cleanup_error is not None:
            if isinstance(cleanup_error, Exception):
                reported_error = cleanup_error
            else:
                raise cleanup_error

    if reported_error is not None:
        try:
            diagnostic = write_failure_diagnostics(
                diagnostics_dir,
                stage=stage,
                error=reported_error,
                browser_path=browser_path,
                browser_version=browser_version,
                browser=browser,
                browser_stderr=browser_stderr,
                runtime_result=result,
                artifact_snapshot=artifact_snapshot,
                artifact=artifact,
                capture_harness=capture_harness,
            )
            print(
                f"{SENTINEL}:DIAGNOSTICS "
                + json.dumps({"path": str(diagnostic)}, sort_keys=True),
                file=sys.stderr,
            )
        except (OSError, TypeError, ValueError) as diagnostic_error:
            print(
                f"{SENTINEL}:DIAGNOSTICS_FAIL reason={diagnostic_error}",
                file=sys.stderr,
            )
        print(f"{SENTINEL}:FAIL reason={reported_error}", file=sys.stderr, flush=True)
        return 1
    if result is None or artifact_snapshot is None:
        raise RuntimeError("repeating-timer smoke completed without a result")
    # Do not make a passing timer observation visible until the browser group,
    # stderr reader, server, request handlers, and temporary profile all drain.
    print(
        f"{SENTINEL}:BROWSER_RESULT "
        + json.dumps(
            {
                "artifact_snapshot": artifact_snapshot,
                "artifact": artifact,
                "capture_harness": capture_harness,
                "result": result,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        flush=True,
    )
    print(f"{SENTINEL}:PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
