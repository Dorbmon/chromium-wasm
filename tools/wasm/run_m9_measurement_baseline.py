#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Capture one explicitly non-benchmark M9 host measurement baseline.

The runner serves immutable snapshots of the current ``chrome_wasm`` loader
and Wasm module, creates a fresh outer-browser profile, and observes one
normal browser lifetime through a dedicated diagnostics host.  The result is
machine-readable evidence for future optimization work, not an M9 acceptance
test: it does not compare samples, derive performance conclusions, claim Wasm
memory residency from a HEAP buffer capacity, or cover persistence, networking,
long-run reliability, worker utilization, or worker exhaustion.
"""

from __future__ import annotations

import argparse
from collections import deque
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable
from urllib.parse import urlencode, urlsplit

if __package__:
    # Several established Wasm harness helpers are executable scripts that
    # import their siblings by filename. Keep this tool usable both as a
    # package module in its focused tests and as the documented script.
    _TOOLS_DIRECTORY = str(Path(__file__).resolve().parent)
    if _TOOLS_DIRECTORY not in sys.path:
        sys.path.insert(0, _TOOLS_DIRECTORY)
    from .check_m6_chrome_boundary import check_boundary
    from .m0_common import (
        M0Error,
        REPO_ROOT,
        load_manifest,
        parse_timeout,
    )
    from .m4_cdp import unused_loopback_port, wait_for_page_client
    from .run_browser_smoke import (
        browser_command,
        find_browser,
    )
    from .m9_browser_cleanup import (
        BrowserStderrReader,
        abort_browser_group,
        stop_browser_group,
    )
    from .m9_server_cleanup import (
        M9TrackingThreadingHTTPServer,
        shutdown_server_bounded,
    )
else:
    from check_m6_chrome_boundary import check_boundary
    from m0_common import (
        M0Error,
        REPO_ROOT,
        load_manifest,
        parse_timeout,
    )
    from m4_cdp import unused_loopback_port, wait_for_page_client
    from run_browser_smoke import (
        browser_command,
        find_browser,
    )
    from m9_browser_cleanup import (
        BrowserStderrReader,
        abort_browser_group,
        stop_browser_group,
    )
    from m9_server_cleanup import (
        M9TrackingThreadingHTTPServer,
        shutdown_server_bounded,
    )


SENTINEL = "CHROMIUM_WASM_M9_BASELINE"
SCHEMA_VERSION = 1
CASE = "chrome_wasm_m9_measurement_baseline"
SCOPE = (
    "one-fresh-host-run-cold-loader-runtime-frame-wasm-buffer-capacity-"
    "worker-observation"
)
BASELINE_KIND = "pre-release-m9-measurement-baseline"
RELEASE_STATUS = "pre_m7_m8_not_releasable"
HOST_ROOT = "/__m9__"
DEFAULT_MODULE_NAME = "chrome_wasm"
MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
GIT_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_ARTIFACT_BYTES = 4 * 1024 * 1024 * 1024
MAX_FAILURE_CHARS = 1024
HOST_PROTOCOL = 1
ARTIFACT_SOURCE_PROVENANCE = "unverified"
ARTIFACT_DELIVERY = "immutable-in-memory-server-snapshot"
HARNESS_KIND = "dedicated-real-chrome-wasm-observation-host"
HARNESS_LOADER_ROUTE = "normal-blob-backed-pthread-loader"
SOURCE_SNAPSHOT_PROVENANCE = (
    "on-disk-byte-snapshots-at-capture-server-startup-not-commit-provenance"
)
VERSION_PROVENANCE = (
    "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance"
)
COLD_START_DEFINITION = (
    "one outer-page navigation in a fresh host-browser profile; "
    "no OS cache eviction or cross-run comparison"
)
WASM_HEAP_BUFFER_CAPACITY_DEFINITION = (
    "HEAPU8.buffer.byteLength capacity; not allocated or resident memory usage"
)
WORKER_OBSERVATION_DEFINITION = (
    "host Worker construction and loader loaded-control messages only; "
    "not worker utilization or saturation"
)
SAMPLE_MEASUREMENT_LIMITS = (
    "observational pre-release baseline only; not a performance gate",
    "one sample only; no cross-run performance inference or benchmark claim",
    (
        "frame timing is the host callback after synchronous Canvas2D "
        "ImageData copy; not raster, compositor, or vsync presentation timing"
    ),
    (
        "HEAPU8.buffer.byteLength is Wasm buffer capacity, not allocated or "
        "resident memory usage"
    ),
    (
        "terminal 25 ms grace observes queued host errors only; it does not "
        "prove worker drain, utilization, or saturation"
    ),
    (
        "worker evidence counts host Worker construction and loader "
        "loaded-control messages only; it does not measure utilization or saturation"
    ),
    (
        "does not measure V8, layout, raster, network, OPFS, persistence, "
        "or long-run reliability"
    ),
)
RESULT_MEASUREMENT_LIMITS = (
    "one fresh host run only; no cross-run performance inference",
    "pre-release observation only; not a performance or release gate",
    (
        "artifact source provenance is unverified; toolchain manifest versions "
        "and on-disk harness snapshots are not artifact source identities"
    ),
)
REQUIRED_HEADERS = {
    "Cache-Control": "no-store",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "X-Content-Type-Options": "nosniff",
}
_REQUIRED_TIMING_FIELDS = (
    "host_module_evaluated",
    "host_run_started",
    "loader_fetch_started",
    "loader_response_ready",
    "loader_blob_ready",
    "module_import_started",
    "module_factory_export_ready",
    "factory_call_started",
    "runtime_initialized",
    "first_frame_callback_after_canvas_copy",
    "surface_ready_callback",
    "ready",
    "shutdown_requested",
    "runtime_exit",
)
_REQUIRED_DURATION_FIELDS = (
    "factory_call_to_runtime_initialized",
    "first_frame_callback_after_canvas_copy_to_surface_ready_callback",
    "host_module_evaluated_to_loader_fetch_started",
    "loader_blob_to_module_import_started",
    "loader_fetch_to_loader_response",
    "loader_response_to_loader_blob",
    "module_import_to_factory_export",
    "navigation_to_first_frame_callback_after_canvas_copy",
    "ready_to_shutdown_request",
    "runtime_initialized_to_first_frame_callback_after_canvas_copy",
    "shutdown_request_to_runtime_exit",
)
_SNAPSHOT_FIELDS = frozenset(
    (
        "case",
        "cold_start_definition",
        "durations_ms",
        "failure",
        "first_frame",
        "host",
        "lifecycle",
        "m9_gate_complete",
        "measurement_limits",
        "performance_gate",
        "release_status",
        "schema_version",
        "scope",
        "status",
        "timing_ms",
        "wasm_heap_buffer_capacity",
        "worker_observation",
    )
)
_HOST_FIELDS = frozenset(
    ("canvas_focused", "cross_origin_isolated", "shared_array_buffer_available")
)
_LIFECYCLE_FIELDS = frozenset(
    (
        "active_ozone_focus_observed",
        "factory_rejected",
        "factory_settled",
        "fatal_error_count",
        "process_exit_code",
        "readiness",
        "runtime_exit_code",
        "runtime_initialized",
        "shutdown_results",
        "status_sequence",
        "unhandled_rejection_count",
        "window_error_count",
    )
)
_READINESS_FIELDS = frozenset(
    ("firstVisuallyNonEmptyPaint", "shellReady", "surfaceReady")
)
_WASM_HEAP_BUFFER_CAPACITY_FIELDS = frozenset(
    (
        "at_first_frame",
        "at_runtime_initialized",
        "at_runtime_exit",
        "definition",
        "grew_before_first_frame_callback",
        "grew_by_runtime_exit",
    )
)
_WASM_HEAP_BUFFER_CAPACITY_SNAPSHOT_FIELDS = frozenset(
    (
        "buffer_kind",
        "heap_u8_exported",
        "shared",
        "wasm_heap_buffer_capacity_bytes",
    )
)
_FRAME_FIELDS = frozenset(
    (
        "chromium_timestamp_ms",
        "height",
        "host_callback_after_canvas_copy_ms",
        "id",
        "width",
    )
)
_WORKER_OBSERVATION_FIELDS = frozenset(
    ("at_first_frame", "at_runtime_initialized", "at_runtime_exit", "definition")
)
_WORKER_SNAPSHOT_FIELDS = frozenset(
    (
        "construction_attempts",
        "error_events",
        "loaded_control_messages",
        "message_error_events",
        "workers_constructed",
    )
)
_ARTIFACT_FIELDS = frozenset(
    (
        "args_gn",
        "artifact_source_provenance",
        "loader",
        "module_name",
        "wasm",
    )
)
_ARTIFACT_BLOB_FIELDS = frozenset(("bytes", "sha256"))
_CAPTURE_HARNESS_FIELDS = frozenset(
    (
        "artifact_delivery",
        "host_protocol",
        "host_html",
        "host_js",
        "kind",
        "loader_route",
        "runner_source",
        "source_snapshot_provenance",
        "version_provenance",
    )
)
_HOST_BROWSER_FIELDS = frozenset(("version",))
_VERSIONS_FIELDS = frozenset(("chromium", "emscripten", "v8"))
_RESULT_FIELDS = frozenset(
    (
        "artifact",
        "capture_harness",
        "case",
        "host_browser",
        "kind",
        "m9_gate_complete",
        "measurement_limits",
        "performance_gate",
        "release_status",
        "sample",
        "schema_version",
        "scope",
        "versions",
    )
)
_DURATION_PAIRS = {
    "factory_call_to_runtime_initialized": (
        "factory_call_started",
        "runtime_initialized",
    ),
    "first_frame_callback_after_canvas_copy_to_surface_ready_callback": (
        "first_frame_callback_after_canvas_copy",
        "surface_ready_callback",
    ),
    "host_module_evaluated_to_loader_fetch_started": (
        "host_module_evaluated",
        "loader_fetch_started",
    ),
    "loader_blob_to_module_import_started": (
        "loader_blob_ready",
        "module_import_started",
    ),
    "loader_fetch_to_loader_response": (
        "loader_fetch_started",
        "loader_response_ready",
    ),
    "loader_response_to_loader_blob": (
        "loader_response_ready",
        "loader_blob_ready",
    ),
    "module_import_to_factory_export": (
        "module_import_started",
        "module_factory_export_ready",
    ),
    "navigation_to_first_frame_callback_after_canvas_copy": (
        "navigation_start",
        "first_frame_callback_after_canvas_copy",
    ),
    "ready_to_shutdown_request": ("ready", "shutdown_requested"),
    "runtime_initialized_to_first_frame_callback_after_canvas_copy": (
        "runtime_initialized",
        "first_frame_callback_after_canvas_copy",
    ),
    "shutdown_request_to_runtime_exit": ("shutdown_requested", "runtime_exit"),
}


def _require_exact_fields(
    value: object, expected: frozenset[str], description: str
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        actual = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise M0Error(
            f"M9 measurement {description} schema mismatch: "
            f"expected {sorted(expected)!r}, got {actual!r}"
        )
    return value


class M9MeasurementServer(M9TrackingThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        *,
        artifacts: dict[str, bytes],
        served_artifact_names: frozenset[str],
        host_html: bytes,
        host_js: bytes,
        module_name: str,
        runner_source: bytes,
    ) -> None:
        # These bytes are the only inputs served or identified for this run.
        # They are copied from disk once at server startup and are immutable.
        self.artifacts = dict(artifacts)
        self.served_artifact_names = frozenset(served_artifact_names)
        self.host_html = bytes(host_html)
        self.host_js = bytes(host_js)
        self.module_name = module_name
        self.runner_source = bytes(runner_source)
        super().__init__(address, M9MeasurementRequestHandler)


class M9MeasurementRequestHandler(BaseHTTPRequestHandler):
    server: M9MeasurementServer

    def log_message(self, _format: str, *_args: object) -> None:
        # Successful capture output must stay limited to the runner's one
        # machine-readable sentinel.
        return

    def end_headers(self) -> None:
        for name, value in REQUIRED_HEADERS.items():
            self.send_header(name, value)
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
        request_path = urlsplit(self.path).path
        if request_path in (HOST_ROOT, f"{HOST_ROOT}/"):
            self._send_bytes(
                HTTPStatus.OK, "text/html; charset=utf-8", self.server.host_html
            )
            return
        if request_path == f"{HOST_ROOT}/chrome_wasm_m9_measurement_host.js":
            self._send_bytes(
                HTTPStatus.OK,
                "text/javascript; charset=utf-8",
                self.server.host_js,
            )
            return
        prefix = f"{HOST_ROOT}/artifacts/"
        if request_path.startswith(prefix):
            artifact_name = request_path.removeprefix(prefix)
            contents = self.server.artifacts.get(artifact_name)
            if (artifact_name in self.server.served_artifact_names and
                    contents is not None):
                content_type = (
                    "application/wasm"
                    if artifact_name.endswith(".wasm")
                    else "text/javascript; charset=utf-8"
                )
                self._send_bytes(HTTPStatus.OK, content_type, contents)
                return
        self._not_found()


def _safe_artifact_path(out_dir: Path, artifact_name: str) -> Path:
    candidate = (out_dir / artifact_name).resolve()
    if candidate.parent != out_dir or not candidate.is_file():
        raise M0Error(f"M9 measurement artifact is missing or unsafe: {artifact_name}")
    size = candidate.stat().st_size
    if size <= 0 or size > MAX_ARTIFACT_BYTES:
        raise M0Error(f"M9 measurement artifact size is invalid: {artifact_name}")
    return candidate


def _read_source_snapshot(path: Path, description: str) -> bytes:
    """Reads one bounded on-disk source input before the capture server starts."""

    try:
        contents = path.read_bytes()
    except OSError as exc:
        raise M0Error(f"M9 measurement {description} cannot be snapshotted") from exc
    if not contents or len(contents) > MAX_ARTIFACT_BYTES:
        raise M0Error(f"M9 measurement {description} snapshot is invalid")
    return contents


def create_measurement_server(
    bind: str,
    port: int,
    out_dir: Path,
    *,
    module_name: str,
    host_dir: Path | None = None,
    runner_source_path: Path | None = None,
) -> M9MeasurementServer:
    """Snapshots artifact, host, and runner bytes before serving a measurement.

    ``host_dir`` and ``runner_source_path`` exist for focused snapshot tests;
    production capture uses this runner's own on-disk host and source files.
    """

    if not MODULE_NAME_RE.fullmatch(module_name):
        raise M0Error("M9 measurement module name is invalid")
    resolved_out_dir = out_dir.resolve()
    if not resolved_out_dir.is_dir():
        raise M0Error(f"M9 measurement output directory is missing: {resolved_out_dir}")
    loader_name = f"{module_name}.js"
    wasm_name = f"{module_name}.wasm"
    # args.gn is never served to the page. It is captured with the executable
    # bytes so the recorded identity cannot hash a file that changed after the
    # real host began receiving its immutable artifacts.
    artifact_names = (loader_name, wasm_name, "args.gn")
    artifacts = {
        name: _read_source_snapshot(
            _safe_artifact_path(resolved_out_dir, name), f"artifact {name}"
        )
        for name in artifact_names
    }
    selected_host_dir = host_dir or Path(__file__).with_name("host")
    selected_runner_source = runner_source_path or Path(__file__)
    host_html = _read_source_snapshot(
        selected_host_dir / "chrome_wasm_m9_measurement.html", "host HTML"
    )
    host_js = _read_source_snapshot(
        selected_host_dir / "chrome_wasm_m9_measurement_host.js", "host JavaScript"
    )
    runner_source = _read_source_snapshot(selected_runner_source, "runner source")
    return M9MeasurementServer(
        (bind, port),
        artifacts=artifacts,
        served_artifact_names=frozenset((loader_name, wasm_name)),
        host_html=host_html,
        host_js=host_js,
        module_name=module_name,
        runner_source=runner_source,
    )


def measurement_url(
    server: M9MeasurementServer, *, module_name: str, timeout_seconds: float
) -> str:
    if not MODULE_NAME_RE.fullmatch(module_name):
        raise M0Error("M9 measurement URL module name is invalid")
    timeout_ms = int(timeout_seconds * 1000)
    if timeout_ms < 10000 or timeout_ms > 120000:
        raise M0Error("M9 measurement URL timeout is out of range")
    host, port = server.server_address[:2]
    query = urlencode({"module": module_name, "timeout_ms": str(timeout_ms)})
    return f"http://{host}:{port}{HOST_ROOT}/?{query}"


def artifact_identity(
    server: M9MeasurementServer, *, module_name: str
) -> dict[str, object]:
    loader_name = f"{module_name}.js"
    wasm_name = f"{module_name}.wasm"
    loader = server.artifacts[loader_name]
    wasm = server.artifacts[wasm_name]
    args_gn = server.artifacts["args.gn"]
    return {
        "args_gn": _byte_identity(args_gn),
        "artifact_source_provenance": ARTIFACT_SOURCE_PROVENANCE,
        "loader": _byte_identity(loader),
        "module_name": module_name,
        "wasm": _byte_identity(wasm),
    }


def _byte_identity(contents: bytes) -> dict[str, object]:
    return {
        "bytes": len(contents),
        "sha256": hashlib.sha256(contents).hexdigest(),
    }


def capture_harness_identity(server: M9MeasurementServer) -> dict[str, object]:
    """Identifies only the in-memory harness source snapshots for this run.

    The hashes identify the actual runner and host bytes captured when the
    server was created. They intentionally make no claim that those files came
    from a particular Git checkout or built the Wasm artifact.
    """

    return {
        "artifact_delivery": ARTIFACT_DELIVERY,
        "host_html": _byte_identity(server.host_html),
        "host_js": _byte_identity(server.host_js),
        "host_protocol": HOST_PROTOCOL,
        "kind": HARNESS_KIND,
        "loader_route": HARNESS_LOADER_ROUTE,
        "runner_source": _byte_identity(server.runner_source),
        "source_snapshot_provenance": SOURCE_SNAPSHOT_PROVENANCE,
        "version_provenance": VERSION_PROVENANCE,
    }


def _require_boolean(value: object, description: str) -> bool:
    if type(value) is not bool:
        raise M0Error(f"M9 measurement {description} is not boolean")
    return value


def _require_integer(value: object, description: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise M0Error(f"M9 measurement {description} is invalid")
    return value


def _require_finite_number(value: object, description: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise M0Error(f"M9 measurement {description} is not numeric")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0:
        raise M0Error(f"M9 measurement {description} is invalid")
    return numeric


def _validate_wasm_heap_buffer_capacity_snapshot(
    value: object, description: str
) -> int:
    value = _require_exact_fields(
        value, _WASM_HEAP_BUFFER_CAPACITY_SNAPSHOT_FIELDS, description
    )
    if value.get("buffer_kind") != "SharedArrayBuffer":
        raise M0Error(
            f"M9 measurement {description} is not a shared Wasm heap buffer"
        )
    if value.get("heap_u8_exported") is not True or value.get("shared") is not True:
        raise M0Error(
            f"M9 measurement {description} lacks HEAPU8 shared-buffer evidence"
        )
    return _require_integer(
        value.get("wasm_heap_buffer_capacity_bytes"),
        f"{description} Wasm heap buffer capacity",
        minimum=1,
    )


def _validate_worker_snapshot(value: object, description: str) -> dict[str, int]:
    value = _require_exact_fields(value, _WORKER_SNAPSHOT_FIELDS, description)
    snapshot = {
        field: _require_integer(value.get(field), f"{description} {field}")
        for field in (
            "construction_attempts",
            "error_events",
            "loaded_control_messages",
            "message_error_events",
            "workers_constructed",
        )
    }
    if snapshot["workers_constructed"] > snapshot["construction_attempts"]:
        raise M0Error(
            f"M9 measurement {description} has more constructed workers than attempts"
        )
    if snapshot["loaded_control_messages"] > snapshot["workers_constructed"]:
        raise M0Error(
            f"M9 measurement {description} has more loaded messages than workers"
        )
    return snapshot


def _validate_nondecreasing_worker_snapshots(
    earlier: dict[str, int], later: dict[str, int], description: str
) -> None:
    for field in _WORKER_SNAPSHOT_FIELDS:
        if later[field] < earlier[field]:
            raise M0Error(
                f"M9 measurement worker {field} regressed {description}"
            )


def validate_measurement_snapshot(snapshot: dict[str, Any]) -> None:
    """Rejects a misleading or incomplete one-run M9 measurement observation."""

    snapshot = _require_exact_fields(snapshot, _SNAPSHOT_FIELDS, "sample")

    # Python and JavaScript both make booleans numeric-looking in some
    # comparisons. Keep release/gate fields and schema markers type-strict so
    # a malformed machine-readable result cannot become a false clean sample.
    _require_boolean(snapshot.get("m9_gate_complete"), "m9_gate_complete")
    _require_boolean(snapshot.get("performance_gate"), "performance_gate")
    if _require_integer(snapshot.get("schema_version"), "schema version") != SCHEMA_VERSION:
        raise M0Error("M9 measurement schema_version mismatch")

    expected = {
        "case": CASE,
        "m9_gate_complete": False,
        "performance_gate": False,
        "release_status": RELEASE_STATUS,
        "schema_version": SCHEMA_VERSION,
        "scope": SCOPE,
        "status": "complete",
        "failure": None,
    }
    for field, value in expected.items():
        if snapshot.get(field) != value:
            raise M0Error(
                f"M9 measurement {field} mismatch: expected {value!r}, "
                f"got {snapshot.get(field)!r}"
            )

    if snapshot.get("cold_start_definition") != COLD_START_DEFINITION:
        raise M0Error("M9 measurement cold-start definition is missing")
    if snapshot.get("measurement_limits") != list(SAMPLE_MEASUREMENT_LIMITS):
        raise M0Error("M9 measurement limits do not retain the bounded caveats")

    host = _require_exact_fields(snapshot["host"], _HOST_FIELDS, "host")
    for field in (
        "canvas_focused",
        "cross_origin_isolated",
        "shared_array_buffer_available",
    ):
        if host.get(field) is not True:
            raise M0Error(f"M9 measurement host {field} is not true")

    timing = _require_exact_fields(
        snapshot["timing_ms"], frozenset(_REQUIRED_TIMING_FIELDS), "timing map"
    )
    previous = -1.0
    for field in _REQUIRED_TIMING_FIELDS:
        value = _require_finite_number(timing.get(field), f"timing {field}")
        if value < previous:
            raise M0Error(f"M9 measurement timing {field} is out of order")
        previous = value
    durations = _require_exact_fields(
        snapshot["durations_ms"], frozenset(_REQUIRED_DURATION_FIELDS), "duration map"
    )
    for field, (start, end) in _DURATION_PAIRS.items():
        duration = _require_finite_number(durations[field], f"duration {field}")
        start_value = 0.0 if start == "navigation_start" else _require_finite_number(
            timing[start], f"timing {start}"
        )
        end_value = _require_finite_number(timing[end], f"timing {end}")
        expected_duration = round(end_value - start_value, 3)
        if not math.isclose(duration, expected_duration, abs_tol=0.0005):
            raise M0Error(
                f"M9 measurement duration {field} disagrees with its timestamps"
            )

    frame = _require_exact_fields(
        snapshot["first_frame"], _FRAME_FIELDS, "first host frame"
    )
    for field in ("id", "width", "height"):
        _require_integer(frame.get(field), f"first frame {field}", minimum=1)
    if frame["width"] > 16384 or frame["height"] > 16384:
        raise M0Error("M9 measurement first frame exceeds the host bound")
    _require_finite_number(
        frame.get("chromium_timestamp_ms"), "first frame Chromium timestamp"
    )
    _require_finite_number(
        frame.get("host_callback_after_canvas_copy_ms"),
        "first frame host callback timestamp",
    )
    if not math.isclose(
        float(frame["host_callback_after_canvas_copy_ms"]),
        _require_finite_number(
            timing["first_frame_callback_after_canvas_copy"],
            "timing first_frame_callback_after_canvas_copy",
        ),
        abs_tol=0.0005,
    ):
        raise M0Error(
            "M9 measurement first frame does not match its host-copy callback timing"
        )

    lifecycle = _require_exact_fields(
        snapshot["lifecycle"], _LIFECYCLE_FIELDS, "lifecycle"
    )
    for field in ("active_ozone_focus_observed", "runtime_initialized"):
        if lifecycle.get(field) is not True:
            raise M0Error(f"M9 measurement lifecycle {field} is not true")
    if lifecycle.get("factory_rejected") is not False:
        raise M0Error("M9 measurement module factory rejected")
    if lifecycle.get("factory_settled") is not True:
        raise M0Error("M9 measurement module factory did not settle by runtime exit")
    if _require_integer(
        lifecycle.get("runtime_exit_code"), "lifecycle runtime exit code"
    ) != 0:
        raise M0Error("M9 measurement runtime exit is nonzero")
    if _require_integer(
        lifecycle.get("process_exit_code"), "lifecycle bridge process exit code"
    ) != 0:
        raise M0Error("M9 measurement bridge process exit is nonzero")
    shutdown_results = lifecycle.get("shutdown_results")
    if (not isinstance(shutdown_results, list) or
            len(shutdown_results) != 2 or
            any(type(result) is not int for result in shutdown_results) or
            shutdown_results != [1, 0]):
        raise M0Error("M9 measurement host shutdown did not return exactly [1, 0]")
    if lifecycle.get("status_sequence") != [
        "starting",
        "loading",
        "ready",
        "shutting_down",
        "complete",
    ]:
        raise M0Error(
            "M9 measurement lifecycle status sequence is missing or reordered"
        )
    for field in (
        "fatal_error_count",
        "unhandled_rejection_count",
        "window_error_count",
    ):
        if _require_integer(lifecycle.get(field), f"lifecycle {field}") != 0:
            raise M0Error(f"M9 measurement lifecycle {field} is nonzero")
    readiness = _require_exact_fields(
        lifecycle["readiness"], _READINESS_FIELDS, "readiness"
    )
    if any(type(readiness[field]) is not bool for field in readiness):
        raise M0Error("M9 measurement readiness fields are not boolean")
    if readiness.get("surfaceReady") is not True:
        raise M0Error("M9 measurement host surface readiness is missing")

    capacity = _require_exact_fields(
        snapshot["wasm_heap_buffer_capacity"],
        _WASM_HEAP_BUFFER_CAPACITY_FIELDS,
        "Wasm heap buffer capacity",
    )
    if capacity.get("definition") != WASM_HEAP_BUFFER_CAPACITY_DEFINITION:
        raise M0Error("M9 measurement Wasm heap capacity definition is invalid")
    runtime_bytes = _validate_wasm_heap_buffer_capacity_snapshot(
        capacity.get("at_runtime_initialized"), "runtime Wasm heap buffer"
    )
    frame_bytes = _validate_wasm_heap_buffer_capacity_snapshot(
        capacity.get("at_first_frame"), "first-frame Wasm heap buffer"
    )
    exit_bytes = _validate_wasm_heap_buffer_capacity_snapshot(
        capacity.get("at_runtime_exit"), "runtime-exit Wasm heap buffer"
    )
    if frame_bytes < runtime_bytes:
        raise M0Error(
            "M9 measurement Wasm heap buffer capacity shrank before the first frame"
        )
    if exit_bytes < frame_bytes:
        raise M0Error(
            "M9 measurement Wasm heap buffer capacity shrank before runtime exit"
        )
    grew_before_frame = _require_boolean(
        capacity.get("grew_before_first_frame_callback"),
        "Wasm heap capacity first-frame growth flag",
    )
    if grew_before_frame != (frame_bytes > runtime_bytes):
        raise M0Error(
            "M9 measurement Wasm heap capacity first-frame growth flag disagrees "
            "with captured capacities"
        )
    grew_by_exit = _require_boolean(
        capacity.get("grew_by_runtime_exit"),
        "Wasm heap capacity runtime-exit growth flag",
    )
    if grew_by_exit != (exit_bytes > runtime_bytes):
        raise M0Error(
            "M9 measurement Wasm heap capacity runtime-exit growth flag disagrees "
            "with captured capacities"
        )

    workers = _require_exact_fields(
        snapshot["worker_observation"], _WORKER_OBSERVATION_FIELDS,
        "worker observation",
    )
    if workers.get("definition") != WORKER_OBSERVATION_DEFINITION:
        raise M0Error("M9 measurement worker-observation definition is missing")
    runtime_workers = _validate_worker_snapshot(
        workers.get("at_runtime_initialized"), "runtime workers"
    )
    frame_workers = _validate_worker_snapshot(
        workers.get("at_first_frame"), "first-frame workers"
    )
    exit_workers = _validate_worker_snapshot(
        workers.get("at_runtime_exit"), "runtime-exit workers"
    )
    _validate_nondecreasing_worker_snapshots(
        runtime_workers, frame_workers, "before first frame"
    )
    _validate_nondecreasing_worker_snapshots(
        frame_workers, exit_workers, "before runtime exit"
    )
    if frame_workers["workers_constructed"] < 1:
        raise M0Error("M9 measurement observed no host Worker construction")
    if frame_workers["loaded_control_messages"] < 1:
        raise M0Error("M9 measurement observed no worker loaded-control message")
    for field in ("error_events", "message_error_events"):
        if frame_workers[field] != 0 or exit_workers[field] != 0:
            raise M0Error(f"M9 measurement worker {field} is nonzero")


def _validate_artifact_blob(value: object, description: str) -> None:
    value = _require_exact_fields(value, _ARTIFACT_BLOB_FIELDS, description)
    _require_integer(value.get("bytes"), f"{description} bytes", minimum=1)
    sha256 = value.get("sha256")
    if not isinstance(sha256, str) or not SHA256_RE.fullmatch(sha256):
        raise M0Error(f"M9 measurement {description} SHA-256 is invalid")


def _validate_artifact_identity(value: object) -> None:
    artifact = _require_exact_fields(value, _ARTIFACT_FIELDS, "artifact identity")
    if artifact.get("artifact_source_provenance") != ARTIFACT_SOURCE_PROVENANCE:
        raise M0Error("M9 measurement artifact source provenance is invalid")
    module_name = artifact.get("module_name")
    if not isinstance(module_name, str) or not MODULE_NAME_RE.fullmatch(module_name):
        raise M0Error("M9 measurement artifact module name is invalid")
    for field in ("args_gn", "loader", "wasm"):
        _validate_artifact_blob(artifact.get(field), f"artifact {field}")


def _validate_capture_harness(value: object) -> None:
    harness = _require_exact_fields(value, _CAPTURE_HARNESS_FIELDS, "capture harness")
    expected = {
        "artifact_delivery": ARTIFACT_DELIVERY,
        "kind": HARNESS_KIND,
        "loader_route": HARNESS_LOADER_ROUTE,
        "source_snapshot_provenance": SOURCE_SNAPSHOT_PROVENANCE,
        "version_provenance": VERSION_PROVENANCE,
    }
    for field, expected_value in expected.items():
        if harness.get(field) != expected_value:
            raise M0Error(
                f"M9 measurement capture harness {field} is invalid"
            )
    if _require_integer(
        harness.get("host_protocol"), "capture harness host protocol", minimum=1
    ) != HOST_PROTOCOL:
        raise M0Error("M9 measurement capture harness host_protocol is invalid")
    for field in ("host_html", "host_js", "runner_source"):
        _validate_artifact_blob(harness.get(field), f"capture harness {field}")


def toolchain_manifest_versions(manifest: dict[str, Any]) -> dict[str, str]:
    """Returns manifest metadata, explicitly not executable artifact provenance."""

    try:
        versions = {
            "chromium": manifest["chromium"]["revision"],
            "emscripten": manifest["emscripten"]["source_revision"],
            "v8": manifest["git_dependencies"]["v8"]["revision"],
        }
    except (KeyError, TypeError) as exc:
        raise M0Error("M9 toolchain manifest lacks a version field") from exc
    if not all(
        isinstance(value, str) and GIT_REVISION_RE.fullmatch(value)
        for value in versions.values()
    ):
        raise M0Error("M9 toolchain manifest contains an invalid version field")
    return versions


def validate_baseline_result(result: dict[str, Any]) -> None:
    """Rejects result metadata that overstates artifact or release provenance."""

    result = _require_exact_fields(result, _RESULT_FIELDS, "result")
    _require_boolean(result.get("m9_gate_complete"), "result m9_gate_complete")
    _require_boolean(result.get("performance_gate"), "result performance_gate")
    if _require_integer(
        result.get("schema_version"), "result schema version"
    ) != SCHEMA_VERSION:
        raise M0Error("M9 measurement result schema_version is invalid")
    expected = {
        "case": CASE,
        "kind": BASELINE_KIND,
        "m9_gate_complete": False,
        "performance_gate": False,
        "release_status": RELEASE_STATUS,
        "schema_version": SCHEMA_VERSION,
        "scope": SCOPE,
    }
    for field, expected_value in expected.items():
        if result.get(field) != expected_value:
            raise M0Error(f"M9 measurement result {field} is invalid")
    if result.get("measurement_limits") != list(RESULT_MEASUREMENT_LIMITS):
        raise M0Error("M9 measurement result limits do not retain bounded caveats")
    _validate_artifact_identity(result.get("artifact"))
    _validate_capture_harness(result.get("capture_harness"))
    host_browser = _require_exact_fields(
        result.get("host_browser"), _HOST_BROWSER_FIELDS, "host browser"
    )
    browser_version = host_browser.get("version")
    if not isinstance(browser_version, str) or not browser_version or len(browser_version) > 512:
        raise M0Error("M9 measurement host browser version is invalid")
    versions = _require_exact_fields(result.get("versions"), _VERSIONS_FIELDS, "versions")
    for name in _VERSIONS_FIELDS:
        value = versions.get(name)
        if not isinstance(value, str) or not GIT_REVISION_RE.fullmatch(value):
            raise M0Error(f"M9 measurement version {name} is invalid")
    sample = result.get("sample")
    if not isinstance(sample, dict):
        raise M0Error("M9 measurement result sample is invalid")
    validate_measurement_snapshot(sample)


def make_baseline_result(
    *,
    snapshot: dict[str, Any],
    artifact: dict[str, object],
    capture_harness: dict[str, object],
    versions: dict[str, str],
    host_browser_version: str,
) -> dict[str, object]:
    result: dict[str, object] = {
        "artifact": artifact,
        "capture_harness": capture_harness,
        "case": CASE,
        "host_browser": {"version": host_browser_version},
        "kind": BASELINE_KIND,
        "m9_gate_complete": False,
        "measurement_limits": list(RESULT_MEASUREMENT_LIMITS),
        "performance_gate": False,
        "release_status": RELEASE_STATUS,
        "schema_version": SCHEMA_VERSION,
        "scope": SCOPE,
        "sample": snapshot,
        "versions": versions,
    }
    validate_baseline_result(result)
    return result


_STATUS_EXPRESSION = r"""
(() => {
  const measurement = globalThis.__chromiumWasmM9MeasurementV1;
  if (!measurement || typeof measurement.snapshot !== "function") {
    return {status: "pending"};
  }
  return measurement.snapshot();
})()
"""

_REQUEST_SHUTDOWN_EXPRESSION = r"""
(() => {
  const measurement = globalThis.__chromiumWasmM9MeasurementV1;
  return Boolean(measurement && typeof measurement.requestShutdown === "function" &&
      measurement.requestShutdown());
})()
"""


def _bounded_error_text(value: object) -> str:
    return str(value).replace("\n", " ")[:MAX_FAILURE_CHARS]


def _measurement_status(client: Any) -> dict[str, Any]:
    value = client.evaluate(_STATUS_EXPRESSION)
    if not isinstance(value, dict):
        raise M0Error("M9 measurement host status is not an object")
    return value


def _wait_for_status(
    *,
    client: Any,
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    deadline: float,
    expected_status: str,
) -> dict[str, Any]:
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        if browser.poll() is not None:
            tail = " ".join(browser_stderr)
            raise M0Error(
                "host browser exited while waiting for M9 measurement "
                f"{expected_status} (status {browser.returncode}): "
                + _bounded_error_text(tail)
            )
        status = _measurement_status(client)
        last = status
        state = status.get("status")
        if state == "failed":
            raise M0Error(
                "M9 measurement host failed: "
                + _bounded_error_text(status.get("failure", "unknown failure"))
            )
        if state == expected_status:
            return status
        time.sleep(0.05)
    raise M0Error(
        f"timed out waiting for M9 measurement {expected_status}: "
        + _bounded_error_text(json.dumps(last, sort_keys=True, default=str))
    )


def _run_cleanup_action(
    cleanup_error: BaseException | None, action: Callable[[], object]
) -> BaseException | None:
    """Runs one cleanup action without preventing the remaining cleanup."""

    try:
        action()
    except BaseException as exc:
        if cleanup_error is None:
            return exc
    return cleanup_error


def _cleanup_measurement_server(
    *,
    server: M9MeasurementServer | None,
    server_thread: threading.Thread | None,
    server_thread_started: bool,
) -> BaseException | None:
    """Stops a started server while always closing its socket and joining it."""

    cleanup_error: BaseException | None = None
    if server is not None:
        if server_thread_started:
            cleanup_error = _run_cleanup_action(
                cleanup_error,
                lambda: shutdown_server_bounded(
                    server, timeout=5, description="M9 measurement server"
                ),
            )
        cleanup_error = _run_cleanup_action(cleanup_error, server.server_close)
    if server_thread_started and server_thread is not None:
        cleanup_error = _run_cleanup_action(
            cleanup_error, lambda: _join_measurement_server(server_thread)
        )
    if server is not None:
        cleanup_error = _run_cleanup_action(
            cleanup_error,
            lambda: server.join_request_handlers(
                timeout=5, description="M9 measurement server"
            ),
        )
    return cleanup_error


def _join_measurement_server(thread: threading.Thread) -> None:
    """Joins a started server thread and rejects an incomplete teardown."""

    thread.join(timeout=5)
    if thread.is_alive():
        raise M0Error("M9 measurement server did not stop")


def run_measurement(
    *,
    server: M9MeasurementServer,
    url: str,
    browser_argument: Path | None,
    no_sandbox: bool,
    timeout: float,
) -> tuple[dict[str, Any], str]:
    browser: subprocess.Popen[str] | None = None
    stderr_reader: BrowserStderrReader | None = None
    client: Any = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    browser_stderr: deque[str] = deque(maxlen=80)
    primary_error: BaseException | None = None
    try:
        browser_path, browser_version = find_browser(browser_argument)
        profile = tempfile.TemporaryDirectory(prefix="chromium-wasm-m9-baseline-")
        debug_port = unused_loopback_port()
        command = browser_command(
            browser_path, profile.name, url, no_sandbox=no_sandbox
        )
        command[1:1] = [
            "--enable-logging=stderr",
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
        stderr_reader = BrowserStderrReader(
            browser.stderr,
            browser_stderr,
            name="chromium-wasm-m9-baseline-browser-stderr",
            thread_factory=threading.Thread,
        )
        stderr_reader.start()
        deadline = time.monotonic() + timeout
        client = wait_for_page_client(debug_port, url, deadline)
        _wait_for_status(
            client=client,
            browser=browser,
            browser_stderr=browser_stderr,
            deadline=deadline,
            expected_status="ready",
        )
        if client.evaluate(_REQUEST_SHUTDOWN_EXPRESSION) is not True:
            raise M0Error("M9 measurement host rejected the one-shot shutdown request")
        complete = _wait_for_status(
            client=client,
            browser=browser,
            browser_stderr=browser_stderr,
            deadline=deadline,
            expected_status="complete",
        )
        return complete, browser_version
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        cleanup_error: BaseException | None = None
        if client is not None:
            cleanup_error = _run_cleanup_action(cleanup_error, client.close)
        if browser is not None and stderr_reader is not None and stderr_reader.started:
            cleanup_error = _run_cleanup_action(
                cleanup_error, lambda: stop_browser_group(browser, stderr_reader)
            )
        elif browser is not None:
            # A failed reader start has no concurrent pipe read, but the
            # browser session can still contain Chrome descendants.  Abort
            # that retained process group rather than killing only its leader.
            cleanup_error = _run_cleanup_action(
                cleanup_error, lambda: abort_browser_group(browser, stderr_reader)
            )
        if profile is not None:
            cleanup_error = _run_cleanup_action(cleanup_error, profile.cleanup)
        if primary_error is None and cleanup_error is not None:
            raise cleanup_error


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture one pre-release Chromium Wasm M9 measurement baseline."
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument(
        "--out-dir", type=Path, default=Path("out/wasm-chrome-m6")
    )
    parser.add_argument("--module-name", default=DEFAULT_MODULE_NAME)
    parser.add_argument(
        "--no-sandbox",
        action="store_true",
        help="disable the host browser sandbox (isolated CI only)",
    )
    parser.add_argument("--timeout", type=parse_timeout, default=120.0)
    args = parser.parse_args()
    if args.timeout < 10.0:
        parser.error("--timeout must allow one cold Chrome Wasm host launch")
    if not MODULE_NAME_RE.fullmatch(args.module_name):
        parser.error("--module-name must contain only ASCII letters, digits, or _")

    out_dir = args.out_dir
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    server: M9MeasurementServer | None = None
    server_thread: threading.Thread | None = None
    server_thread_started = False
    primary_error: BaseException | None = None
    result: dict[str, object] | None = None
    try:
        check_boundary(out_dir)
        manifest = load_manifest()
        versions = toolchain_manifest_versions(manifest)
        server = create_measurement_server(
            "127.0.0.1", 0, out_dir, module_name=args.module_name
        )
        identity = artifact_identity(server, module_name=args.module_name)
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m9-measurement-server",
            daemon=True,
        )
        server_thread.start()
        server_thread_started = True
        url = measurement_url(
            server, module_name=args.module_name, timeout_seconds=args.timeout
        )
        snapshot, browser_version = run_measurement(
            server=server,
            url=url,
            browser_argument=args.browser,
            no_sandbox=args.no_sandbox,
            timeout=args.timeout,
        )
        result = make_baseline_result(
            artifact=identity,
            capture_harness=capture_harness_identity(server),
            host_browser_version=browser_version,
            snapshot=snapshot,
            versions=versions,
        )
    except (M0Error, OSError, TypeError, ValueError) as exc:
        primary_error = exc
        print(
            f"{SENTINEL}:CAPTURE_FAILED reason={_bounded_error_text(exc)}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        cleanup_error = _cleanup_measurement_server(
            server=server,
            server_thread=server_thread,
            server_thread_started=server_thread_started,
        )
        if primary_error is None and cleanup_error is not None:
            raise cleanup_error
    if result is None:
        raise RuntimeError("M9 measurement capture completed without a result")
    # Do not make a successful observation visible until its server teardown
    # has completed, because a teardown failure invalidates the capture.
    print(
        f"{SENTINEL}:CAPTURED "
        + json.dumps(result, sort_keys=True, separators=(",", ":")),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
