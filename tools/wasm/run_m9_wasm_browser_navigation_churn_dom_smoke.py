#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run bounded same-instance native data: navigation churn for M9 preparation.

This runner serves immutable byte snapshots of one Chrome Wasm artifact and
the narrow host harness. The host never supplies a URL or invokes a navigation
command: C++ owns six fixed, script-free data: documents, their history/title/
RFH/FVP checks, and shutdown. The host reports a later Canvas2D backing-store
copy plus existing read-only native Wasm capacity/maximum/headroom and
PageAllocator logical-mapping counters for each verified native stage. These
counters are bounded observations only, not navigation-performance, network,
persistence, worker, RSS, committed-memory, allocation, residency, leak,
out-of-memory, drain, or M8 feature tests.
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
from m0_common import M0Error, REPO_ROOT, load_manifest, parse_timeout
from m9_browser_cleanup import (
    BrowserStderrReader,
    abort_browser_group,
    stop_browser_group,
)
from m9_server_cleanup import (
    M9TrackingThreadingHTTPServer,
    shutdown_server_bounded,
)
from m9_descriptor_snapshot import snapshot_regular_file, snapshot_regular_files
from run_browser_smoke import browser_command, find_browser
import run_wasm_browser_view_smoke as browser_view_smoke


SENTINEL = "CHROMIUM_WASM_M9_NAVIGATION_CHURN_DOM"
CASE = "browser_same_instance_navigation_churn_m9"
SCOPE = (
    "fixed-three-cycle-same-instance-local-data-navigation-churn-with-later-"
    "backing-store-copy-and-native-memory-observation-only"
)
SWITCH = "--wasm-browser-host-navigation-churn-smoke"
READY_MARKER = "CHROMIUM_WASM_M9_NAVIGATION_CHURN:READY"
NAVIGATED_MARKER = "CHROMIUM_WASM_M9_NAVIGATION_CHURN:NAVIGATED"
PRESENTED_MARKER = "CHROMIUM_WASM_M9_NAVIGATION_CHURN:PRESENTED"
PASS_MARKER = "CHROMIUM_WASM_M9_NAVIGATION_CHURN:PASS"
LIFECYCLE_PASS_MARKER = "CHROMIUM_WASM_M6_BROWSER_LIFECYCLE:PASS"
# A live self-owned receiver on the IO sequence is an explicit Chrome-side
# teardown leak, not an expected single-process/Wasm diagnostic. In
# particular, suppressing this warning by invalidating its weak pointers would
# skip the receiver destructor which releases the client's discardable-memory
# allocations. Keep the bounded churn witness fail-closed until the renderer
# lifecycle has a real close path.
DISCARDABLE_MEMORY_MANAGER_LEAK_MARKERS = (
    "MojoDiscardableSharedMemoryManagerImpls are still alive",
    "will be leaked",
)
DEFAULT_OUT_DIR = Path("out/wasm-chrome-m6")
PRODUCT_MODULE_NAME = "chrome_wasm"
DEFAULT_MODULE_NAME = PRODUCT_MODULE_NAME
HOST_ROOT = "/__m9_browser_navigation_churn__"
CYCLE_COUNT = 3
NAVIGATION_NAMES = ("first", "second")
NAVIGATIONS_PER_CYCLE = len(NAVIGATION_NAMES)
STAGE_COUNT = CYCLE_COUNT * NAVIGATIONS_PER_CYCLE
FRAME_TRANSITION_POLICY = (
    "previous-backing-store-copy-may-share-next-navigation-marker-frame"
)
WASM_PAGE_SIZE_BYTES = 64 * 1024
# This is a bounded wasm32 safety floor for every native checkpoint in this
# smoke. It does not characterize committed memory, allocations, residency,
# leaks, or out-of-memory behavior outside those observations.
MINIMUM_WASM_LINEAR_MEMORY_HEADROOM_BYTES = 1024 * 1024 * 1024
WASM_HEAP_BUFFER_CAPACITY_SAMPLE_COUNT = STAGE_COUNT + 2
WASM_HEAP_BUFFER_CAPACITY_DEFINITION = (
    "Module.HEAPU8.buffer.byteLength capacity observed at runtime initialization, "
    "each stage's later Canvas2D backing-store-copy observation, and runtime "
    "exit; not allocated or resident memory usage"
)
WASM_HEAP_BUFFER_CAPACITY_LIMITATION = (
    "Module.HEAPU8.buffer.byteLength capacity is not allocations, residency, "
    "address-space headroom, a leak, out-of-memory, or drain proof"
)
NATIVE_MEMORY_SAMPLE_COUNT = STAGE_COUNT + 1
NATIVE_MEMORY_SNAPSHOT_DEFINITION = (
    "read-only native Emscripten current linear-memory capacity, configured "
    "linear-memory maximum, and derived headroom plus PageAllocator total "
    "logical mappings across clients at runtime initialization and each "
    "stage's later Canvas2D backing-store-copy observation; mappings may be "
    "uncommitted; not RSS, committed memory, allocation, residency, leak, "
    "out-of-memory, or drain evidence"
)
NATIVE_MEMORY_SNAPSHOT_LIMITATION = (
    "native memory counters are point-in-time capacity/maximum/headroom and "
    "logical-mapping observations, not RSS, committed memory, allocations, "
    "residency, leaks, out-of-memory, or drain proof"
)
MAX_SAFE_INTEGER = (1 << 53) - 1
LIMITATIONS = (
    "does_not_exercise_omnibox_or_trusted_dom_navigation_input",
    "does_not_exercise_page_javascript",
    "does_not_exercise_page_webassembly",
    "does_not_exercise_wisp_or_network_reconnect",
    "does_not_prove_opfs_persistence_or_recovery",
    "does_not_claim_m7_profile_persistence",
    WASM_HEAP_BUFFER_CAPACITY_LIMITATION,
    NATIVE_MEMORY_SNAPSHOT_LIMITATION,
    "does_not_measure_or_exhaust_the_pthread_pool",
    "does_not_prove_raster_compositor_display_or_vsync_presentation",
    "does_not_claim_m8_feature_compatibility",
)
ARTIFACT_SOURCE_PROVENANCE = "unverified"
ARTIFACT_DELIVERY = "immutable-in-memory-server-snapshot"
SOURCE_SNAPSHOT_PROVENANCE = (
    "on-disk-byte-snapshots-at-server-startup-not-commit-provenance"
)
VERSION_PROVENANCE = (
    "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance"
)
MAX_RESULT_BYTES = 2 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024 * 1024
MAX_FRAME_DIMENSION = 16384
MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
GIT_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
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
_WASM_HEAP_BUFFER_CAPACITY_FIELDS = frozenset(
    (
        "definition",
        "grew",
        "highWaterBytes",
        "nondecreasing",
        "sampleCount",
        "samples",
    )
)
_WASM_HEAP_BUFFER_CAPACITY_SAMPLE_FIELDS = frozenset(
    (
        "bufferKind",
        "capacityBytes",
        "frameId",
        "heapU8Exported",
        "observation",
        "stage",
    )
)
_NATIVE_MEMORY_SNAPSHOT_FIELDS = frozenset(
    (
        "definition",
        "nondecreasingLinearCapacity",
        "sampleCount",
        "samples",
    )
)
_NATIVE_MEMORY_SAMPLE_FIELDS = frozenset(
    (
        "frameId",
        "observation",
        "pageAllocatorTotalMappedBytes",
        "stage",
        "wasmLinearMemoryCapacityBytes",
        "wasmLinearMemoryHeadroomBytes",
        "wasmLinearMemoryMaximumBytes",
    )
)


def _require_product_module_name(module_name: object, boundary: str) -> str:
    if not isinstance(module_name, str) or not MODULE_NAME_RE.fullmatch(module_name):
        raise M0Error(f"navigation-churn {boundary} module name is invalid")
    if module_name != PRODUCT_MODULE_NAME:
        raise M0Error(
            "navigation-churn "
            f"{boundary} only supports the {PRODUCT_MODULE_NAME} product module"
        )
    return module_name


class NavigationChurnSmokeServer(M9TrackingThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    module_name: str
    artifacts: dict[str, bytes]
    result_token: str
    result_queue: queue.Queue[dict[str, Any]]
    result_lock: threading.Lock
    result_received: bool
    host_html: bytes
    host_js: bytes
    runner_source: bytes


class NavigationChurnSmokeRequestHandler(BaseHTTPRequestHandler):
    server: NavigationChurnSmokeServer

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def end_headers(self) -> None:
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def _send_bytes(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self) -> None:
        self._send_bytes(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found\n")

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path in (HOST_ROOT, f"{HOST_ROOT}/"):
            self._send_bytes(
                HTTPStatus.OK, "text/html; charset=utf-8", self.server.host_html
            )
            return
        if path == f"{HOST_ROOT}/chrome_wasm_browser_navigation_churn_smoke_host.js":
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
            if artifact is not None:
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
        path = urlsplit(self.path).path
        if path != f"{HOST_ROOT}/result/{self.server.result_token}":
            self._not_found()
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_RESULT_BYTES:
            self._send_bytes(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "text/plain; charset=utf-8",
                b"invalid result size\n",
            )
            return
        result = parse_result_payload(self.rfile.read(length))
        if result is None:
            self._send_bytes(
                HTTPStatus.BAD_REQUEST,
                "text/plain; charset=utf-8",
                b"invalid navigation-churn result\n",
            )
            return
        with self.server.result_lock:
            if self.server.result_received:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"navigation-churn result already received\n",
                )
                return
            try:
                self.server.result_queue.put_nowait(result)
            except queue.Full:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"navigation-churn result queue is full\n",
                )
                return
            self.server.result_received = True
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()


def stage_info(stage: int) -> dict[str, object]:
    if type(stage) is not int or not 1 <= stage <= STAGE_COUNT:
        raise M0Error("navigation-churn stage is out of range")
    return {
        "cycle": ((stage - 1) // NAVIGATIONS_PER_CYCLE) + 1,
        "stage": stage,
        "navigation": NAVIGATION_NAMES[(stage - 1) % NAVIGATIONS_PER_CYCLE],
    }


def _reject_duplicate_object_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def parse_result_payload(payload: bytes) -> dict[str, Any] | None:
    try:
        result = json.loads(
            payload.decode("utf-8"), object_pairs_hook=_reject_duplicate_object_keys
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
    token: str,
    result_queue: queue.Queue[dict[str, Any]],
    *,
    module_name: str,
    host_dir: Path | None = None,
    runner_source_path: Path | None = None,
) -> NavigationChurnSmokeServer:
    module_name = _require_product_module_name(module_name, "server")
    artifacts = snapshot_regular_files(
        out_dir,
        (f"{module_name}.js", f"{module_name}.wasm"),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="navigation-churn artifacts",
    )
    selected_host_dir = host_dir or Path(__file__).with_name("host")
    selected_runner_source = runner_source_path or Path(__file__)
    host_snapshots = snapshot_regular_files(
        selected_host_dir,
        (
            "chrome_wasm_browser_navigation_churn_smoke.html",
            "chrome_wasm_browser_navigation_churn_smoke_host.js",
        ),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="navigation-churn host resources",
    )
    runner_source = snapshot_regular_file(
        selected_runner_source,
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="navigation-churn runner source",
    )
    server = NavigationChurnSmokeServer(
        (host, port), NavigationChurnSmokeRequestHandler
    )
    server.module_name = module_name
    server.artifacts = artifacts
    server.result_token = token
    server.result_queue = result_queue
    server.result_lock = threading.Lock()
    server.result_received = False
    server.host_html = host_snapshots[
        "chrome_wasm_browser_navigation_churn_smoke.html"
    ]
    server.host_js = host_snapshots[
        "chrome_wasm_browser_navigation_churn_smoke_host.js"
    ]
    server.runner_source = runner_source
    return server


def _byte_identity(contents: bytes) -> dict[str, object]:
    return {"bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}


def artifact_identity(
    server: NavigationChurnSmokeServer, *, module_name: str
) -> dict[str, object]:
    module_name = _require_product_module_name(module_name, "artifact")
    _require_product_module_name(server.module_name, "artifact server")
    return {
        "artifact_delivery": ARTIFACT_DELIVERY,
        "artifact_source_provenance": ARTIFACT_SOURCE_PROVENANCE,
        "loader": _byte_identity(server.artifacts[f"{module_name}.js"]),
        "module_name": module_name,
        "wasm": _byte_identity(server.artifacts[f"{module_name}.wasm"]),
    }


def capture_harness_identity(server: NavigationChurnSmokeServer) -> dict[str, object]:
    return {
        "host_html": _byte_identity(server.host_html),
        "host_js": _byte_identity(server.host_js),
        "runner_source": _byte_identity(server.runner_source),
        "source_snapshot_provenance": SOURCE_SNAPSHOT_PROVENANCE,
        "version_provenance": VERSION_PROVENANCE,
    }


def toolchain_manifest_versions(manifest: dict[str, Any]) -> dict[str, str]:
    try:
        versions = {
            "chromium": manifest["chromium"]["revision"],
            "v8": manifest["git_dependencies"]["v8"]["revision"],
            "emscripten": manifest["emscripten"]["source_revision"],
        }
    except (KeyError, TypeError) as error:
        raise M0Error("navigation-churn manifest lacks toolchain version metadata") from error
    if not all(
        isinstance(value, str) and GIT_REVISION_RE.fullmatch(value)
        for value in versions.values()
    ):
        raise M0Error("navigation-churn manifest toolchain version metadata is invalid")
    return versions


def smoke_url(
    server: NavigationChurnSmokeServer,
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


def verify_required_exports(module_loader: bytes) -> None:
    try:
        loader = module_loader.decode("utf-8")
    except UnicodeDecodeError as error:
        raise M0Error(f"cannot decode navigation-churn module loader: {error}") from error
    for export in (
        'Module["_chromium_wasm_browser_host_navigation_churn_presented"]',
        'Module["ccall"]',
        'Module["_chromium_wasm_browser_host_memory_linear_capacity_bytes"]',
        'Module["_chromium_wasm_browser_host_memory_linear_maximum_bytes"]',
        (
            'Module["_chromium_wasm_browser_host_memory_page_allocator_total_mapped_bytes"]'
        ),
    ):
        if export not in loader:
            raise M0Error(f"navigation-churn module lacks required export {export}")


def _require_equal(result: dict[str, Any], field: str, expected: object) -> None:
    if not browser_view_smoke._exact_json_value_equal(result.get(field), expected):
        raise M0Error(
            f"navigation-churn result {field} mismatch: expected {expected!r}, "
            f"got {result.get(field)!r}"
        )


def _require_exact_fields(
    value: object, expected: frozenset[str], description: str
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        actual = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise M0Error(
            f"navigation-churn {description} schema is invalid: "
            f"expected {sorted(expected)!r}, got {actual!r}"
        )
    return value


def _validate_byte_identity(value: object, description: str) -> None:
    identity = _require_exact_fields(value, _BYTE_IDENTITY_FIELDS, description)
    if type(identity.get("bytes")) is not int or identity["bytes"] < 1:
        raise M0Error(f"navigation-churn {description} byte count is invalid")
    sha256 = identity.get("sha256")
    if type(sha256) is not str or not SHA256_RE.fullmatch(sha256):
        raise M0Error(f"navigation-churn {description} SHA-256 is invalid")


def _validate_artifact_identity(
    value: object, expected_identity: dict[str, object]
) -> None:
    artifact = _require_exact_fields(
        value, _ARTIFACT_IDENTITY_FIELDS, "artifact identity"
    )
    if artifact.get("artifact_source_provenance") != ARTIFACT_SOURCE_PROVENANCE:
        raise M0Error("navigation-churn artifact source provenance is invalid")
    if artifact.get("artifact_delivery") != ARTIFACT_DELIVERY:
        raise M0Error("navigation-churn artifact delivery is invalid")
    _require_product_module_name(artifact.get("module_name"), "artifact")
    for field in ("loader", "wasm"):
        _validate_byte_identity(artifact.get(field), f"artifact {field}")
    if not browser_view_smoke._exact_json_value_equal(artifact, expected_identity):
        raise M0Error("navigation-churn artifact identity disagrees with served snapshot")


def _validate_capture_harness_identity(
    value: object, expected_identity: dict[str, object]
) -> None:
    harness = _require_exact_fields(
        value, _CAPTURE_HARNESS_FIELDS, "capture harness identity"
    )
    if harness.get("source_snapshot_provenance") != SOURCE_SNAPSHOT_PROVENANCE:
        raise M0Error("navigation-churn capture-harness source provenance is invalid")
    if harness.get("version_provenance") != VERSION_PROVENANCE:
        raise M0Error("navigation-churn capture-harness version provenance is invalid")
    for field in ("host_html", "host_js", "runner_source"):
        _validate_byte_identity(harness.get(field), f"capture harness {field}")
    if not browser_view_smoke._exact_json_value_equal(harness, expected_identity):
        raise M0Error("navigation-churn capture harness disagrees with served snapshot")


def _validate_stage(
    value: object,
    expected_stage: int,
    frame_ids: set[int],
    previous_stage: dict[str, object] | None,
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise M0Error(f"navigation-churn stage {expected_stage} is missing")
    expected = stage_info(expected_stage)
    expected_keys = {
        "cycle",
        "stage",
        "navigation",
        "historyEntries",
        "historyIndex",
        "historyBaselineEntries",
        "historyBaselineIndex",
        "historyAppendVerified",
        "forwardHistory",
        "backHistory",
        "historyExact",
        "titleExact",
        "rfhLive",
        "fvp",
        "navigationMarkerFrameId",
        "backingStoreCopyFrameId",
        "presentationQueued",
        "presentedObserved",
    }
    if set(value) != expected_keys:
        raise M0Error(f"navigation-churn stage {expected_stage} schema is invalid")
    for field in ("cycle", "stage"):
        if type(value.get(field)) is not int or value[field] != expected[field]:
            raise M0Error(f"navigation-churn stage {expected_stage} {field} is invalid")
    if value.get("navigation") != expected["navigation"]:
        raise M0Error(f"navigation-churn stage {expected_stage} navigation is invalid")
    for field in (
        "historyEntries",
        "historyIndex",
        "historyBaselineEntries",
        "historyBaselineIndex",
        "navigationMarkerFrameId",
        "backingStoreCopyFrameId",
    ):
        if type(value.get(field)) is not int:
            raise M0Error(f"navigation-churn stage {expected_stage} {field} is invalid")
    if (
        value["historyEntries"] < 1
        or value["historyIndex"] < 0
        or value["historyIndex"] >= value["historyEntries"]
        or value["historyBaselineEntries"] < 1
        or value["historyBaselineIndex"] < 0
        or value["historyBaselineIndex"] >= value["historyBaselineEntries"]
    ):
        raise M0Error(f"navigation-churn stage {expected_stage} history evidence is invalid")
    if type(value.get("backHistory")) is not bool:
        raise M0Error(f"navigation-churn stage {expected_stage} backHistory is invalid")
    if expected_stage == 1:
        if (
            value.get("historyAppendVerified") is not False
            or value["historyBaselineEntries"] != value["historyEntries"]
            or value["historyBaselineIndex"] != value["historyIndex"]
        ):
            raise M0Error(
                "navigation-churn stage one did not capture its post-navigation baseline"
            )
    elif (
        value.get("historyAppendVerified") is not True
        or value["historyEntries"] != value["historyBaselineEntries"] + 1
        or value["historyIndex"] != value["historyBaselineIndex"] + 1
        or previous_stage is None
        or value["historyBaselineEntries"] != previous_stage["historyEntries"]
        or value["historyBaselineIndex"] != previous_stage["historyIndex"]
    ):
        raise M0Error(
            f"navigation-churn stage {expected_stage} did not append from prior history"
        )
    if expected_stage > 1 and value["backHistory"] is not True:
        raise M0Error(
            f"navigation-churn stage {expected_stage} backHistory is not true"
        )
    for field in (
        "forwardHistory",
        "historyExact",
        "titleExact",
        "rfhLive",
        "fvp",
        "presentationQueued",
        "presentedObserved",
    ):
        expected_value = False if field == "forwardHistory" else True
        if value.get(field) is not expected_value:
            raise M0Error(
                f"navigation-churn stage {expected_stage} {field} is not "
                f"{str(expected_value).lower()}"
            )
    marker_frame = value["navigationMarkerFrameId"]
    copy_frame = value["backingStoreCopyFrameId"]
    if marker_frame < 0 or copy_frame < 1 or copy_frame not in frame_ids:
        raise M0Error(f"navigation-churn stage {expected_stage} frame evidence is invalid")
    if marker_frame > 0 and marker_frame not in frame_ids:
        raise M0Error(
            f"navigation-churn stage {expected_stage} marker frame is invalid"
        )
    if copy_frame <= marker_frame:
        raise M0Error(
            f"navigation-churn stage {expected_stage} lacks ordered Canvas2D copy evidence"
        )
    return value


def _validate_wasm_heap_buffer_capacity(
    value: object, stages: list[dict[str, object]]
) -> None:
    """Validates all fixed, re-acquired Wasm-capacity observations.

    The eight samples are intentionally only a linear-memory-capacity trace:
    runtime initialization, each already-established stage/frame copy witness,
    and runtime exit. A larger valid capacity is evidence to record, never a
    test failure by itself.
    """

    capacity = _require_exact_fields(
        value,
        _WASM_HEAP_BUFFER_CAPACITY_FIELDS,
        "Wasm heap buffer capacity",
    )
    if capacity.get("definition") != WASM_HEAP_BUFFER_CAPACITY_DEFINITION:
        raise M0Error("navigation-churn Wasm capacity definition is invalid")
    if (
        type(capacity.get("sampleCount")) is not int
        or capacity["sampleCount"] != WASM_HEAP_BUFFER_CAPACITY_SAMPLE_COUNT
    ):
        raise M0Error("navigation-churn Wasm capacity sample count is invalid")
    samples = capacity.get("samples")
    if (
        not isinstance(samples, list)
        or len(samples) != WASM_HEAP_BUFFER_CAPACITY_SAMPLE_COUNT
    ):
        raise M0Error("navigation-churn Wasm capacity does not have eight samples")

    capacities: list[int] = []
    for index, raw_sample in enumerate(samples):
        sample = _require_exact_fields(
            raw_sample,
            _WASM_HEAP_BUFFER_CAPACITY_SAMPLE_FIELDS,
            f"Wasm capacity sample {index}",
        )
        if sample.get("bufferKind") != "SharedArrayBuffer":
            raise M0Error(
                f"navigation-churn Wasm capacity sample {index} is not shared"
            )
        if sample.get("heapU8Exported") is not True:
            raise M0Error(
                f"navigation-churn Wasm capacity sample {index} lacks Uint8Array evidence"
            )
        capacity_bytes = sample.get("capacityBytes")
        if (
            type(capacity_bytes) is not int
            or capacity_bytes <= 0
            or capacity_bytes > MAX_SAFE_INTEGER
            or capacity_bytes % WASM_PAGE_SIZE_BYTES != 0
        ):
            raise M0Error(
                f"navigation-churn Wasm capacity sample {index} is not a positive "
                "safe Wasm-page multiple"
            )
        capacities.append(capacity_bytes)

        expected_observation = "stage_backing_store_copy"
        expected_stage: int | None = None
        expected_frame_id: int | None = None
        if index == 0:
            expected_observation = "runtime_initialized"
        elif index == WASM_HEAP_BUFFER_CAPACITY_SAMPLE_COUNT - 1:
            expected_observation = "runtime_exit"
        else:
            expected_stage = index
            expected_frame_id = stages[index - 1]["backingStoreCopyFrameId"]
        if sample.get("observation") != expected_observation:
            raise M0Error(
                f"navigation-churn Wasm capacity sample {index} observation is invalid"
            )
        if expected_stage is None:
            if sample.get("stage") is not None or sample.get("frameId") is not None:
                raise M0Error(
                    f"navigation-churn Wasm capacity sample {index} is not terminal"
                )
        elif (
            type(sample.get("stage")) is not int
            or sample["stage"] != expected_stage
            or type(sample.get("frameId")) is not int
            or sample["frameId"] != expected_frame_id
        ):
            raise M0Error(
                f"navigation-churn Wasm capacity sample {index} is not bound to "
                "its stage/frame copy observation"
            )

    if any(later < earlier for earlier, later in zip(capacities, capacities[1:])):
        raise M0Error("navigation-churn Wasm capacity samples are not nondecreasing")
    if capacity.get("nondecreasing") is not True:
        raise M0Error("navigation-churn Wasm capacity nondecreasing flag is invalid")
    high_water_bytes = max(capacities)
    if (
        type(capacity.get("highWaterBytes")) is not int
        or capacity["highWaterBytes"] != high_water_bytes
    ):
        raise M0Error("navigation-churn Wasm capacity high water is invalid")
    if type(capacity.get("grew")) is not bool or capacity["grew"] != (
        high_water_bytes > capacities[0]
    ):
        raise M0Error("navigation-churn Wasm capacity growth flag is invalid")


def _validate_native_memory_snapshot(
    value: object, stages: list[dict[str, object]]
) -> None:
    """Validates fixed native counter observations without leak inference.

    The seven samples are runtime initialization followed by each established
    stage/frame copy. There is deliberately no post-``onExit`` observation:
    native teardown can invalidate the application state. PageAllocator logical
    mappings may rise or fall between points, so only Wasm linear capacity is
    monotonic; mappings are neither compared nor treated as leak evidence.
    """

    snapshot = _require_exact_fields(
        value, _NATIVE_MEMORY_SNAPSHOT_FIELDS, "native memory snapshot"
    )
    if snapshot.get("definition") != NATIVE_MEMORY_SNAPSHOT_DEFINITION:
        raise M0Error("navigation-churn native memory definition is invalid")
    if (
        type(snapshot.get("sampleCount")) is not int
        or snapshot["sampleCount"] != NATIVE_MEMORY_SAMPLE_COUNT
    ):
        raise M0Error("navigation-churn native memory sample count is invalid")
    samples = snapshot.get("samples")
    if not isinstance(samples, list) or len(samples) != NATIVE_MEMORY_SAMPLE_COUNT:
        raise M0Error("navigation-churn native memory does not have seven samples")

    capacities: list[int] = []
    for index, raw_sample in enumerate(samples):
        sample = _require_exact_fields(
            raw_sample, _NATIVE_MEMORY_SAMPLE_FIELDS, f"native memory sample {index}"
        )
        expected_observation = "stage_backing_store_copy"
        expected_stage: int | None = None
        expected_frame_id: int | None = None
        if index == 0:
            expected_observation = "runtime_initialized"
        else:
            expected_stage = index
            expected_frame_id = stages[index - 1]["backingStoreCopyFrameId"]
        if sample.get("observation") != expected_observation:
            raise M0Error(
                f"navigation-churn native memory sample {index} observation is invalid"
            )
        if expected_stage is None:
            if sample.get("stage") is not None or sample.get("frameId") is not None:
                raise M0Error(
                    f"navigation-churn native memory sample {index} is not runtime initialization"
                )
        elif (
            type(sample.get("stage")) is not int
            or sample["stage"] != expected_stage
            or type(sample.get("frameId")) is not int
            or sample["frameId"] != expected_frame_id
        ):
            raise M0Error(
                f"navigation-churn native memory sample {index} is not bound to "
                "its stage/frame copy observation"
            )

        values: dict[str, int] = {}
        for field in (
            "pageAllocatorTotalMappedBytes",
            "wasmLinearMemoryCapacityBytes",
            "wasmLinearMemoryHeadroomBytes",
            "wasmLinearMemoryMaximumBytes",
        ):
            value_bytes = sample.get(field)
            if (
                type(value_bytes) is not int
                or value_bytes < 0
                or value_bytes > MAX_SAFE_INTEGER
                or value_bytes % WASM_PAGE_SIZE_BYTES != 0
            ):
                raise M0Error(
                    f"navigation-churn native memory sample {index} {field} is not "
                    "a safe nonnegative Wasm-page multiple"
                )
            values[field] = value_bytes
        if values["wasmLinearMemoryCapacityBytes"] < WASM_PAGE_SIZE_BYTES:
            raise M0Error(
                f"navigation-churn native memory sample {index} capacity is below one page"
            )
        if values["wasmLinearMemoryMaximumBytes"] < (
            values["wasmLinearMemoryCapacityBytes"]
        ):
            raise M0Error(
                f"navigation-churn native memory sample {index} maximum is below capacity"
            )
        if values["wasmLinearMemoryHeadroomBytes"] != (
            values["wasmLinearMemoryMaximumBytes"]
            - values["wasmLinearMemoryCapacityBytes"]
        ):
            raise M0Error(
                f"navigation-churn native memory sample {index} headroom is inconsistent"
            )
        if (
            values["wasmLinearMemoryHeadroomBytes"]
            < MINIMUM_WASM_LINEAR_MEMORY_HEADROOM_BYTES
        ):
            raise M0Error(
                f"navigation-churn native memory sample {index} headroom is below "
                "the required 1 GiB safety floor"
            )
        capacities.append(values["wasmLinearMemoryCapacityBytes"])

    nondecreasing = all(
        later >= earlier for earlier, later in zip(capacities, capacities[1:])
    )
    if snapshot.get("nondecreasingLinearCapacity") is not nondecreasing:
        raise M0Error(
            "navigation-churn native memory linear-capacity monotonic flag is invalid"
        )
    if not nondecreasing:
        raise M0Error("navigation-churn native memory linear capacity regressed")


def _navigated_marker(stage: dict[str, object]) -> str:
    return (
        f"{NAVIGATED_MARKER} cycle={stage['cycle']} stage={stage['stage']} "
        f"navigation={stage['navigation']} historyEntries={stage['historyEntries']} "
        f"historyIndex={stage['historyIndex']} "
        f"historyBaselineEntries={stage['historyBaselineEntries']} "
        f"historyBaselineIndex={stage['historyBaselineIndex']} "
        f"historyAppendVerified={int(stage['historyAppendVerified'])} "
        f"forwardHistory=0 backHistory={int(stage['backHistory'])} "
        "historyExact=1 titleExact=1 rfhLive=1 fvp=1"
    )


def _presented_marker(stage: dict[str, object]) -> str:
    return (
        f"{PRESENTED_MARKER} cycle={stage['cycle']} stage={stage['stage']} "
        f"navigation={stage['navigation']}"
    )


def _validate_markers(stderr: object, stages: list[dict[str, object]]) -> None:
    if not isinstance(stderr, list) or any(type(line) is not str for line in stderr):
        raise M0Error("navigation-churn stderr is invalid")
    ready = f"{READY_MARKER} cycles={CYCLE_COUNT} navigations={STAGE_COUNT}"
    passed = f"{PASS_MARKER} cycles={CYCLE_COUNT} navigations={STAGE_COUNT}"
    ordered = [ready]
    for stage in stages:
        ordered.extend((_navigated_marker(stage), _presented_marker(stage)))
    ordered.extend((passed, LIFECYCLE_PASS_MARKER))
    previous_index = -1
    for marker in ordered:
        if stderr.count(marker) != 1:
            raise M0Error(f"navigation-churn marker is missing or duplicated: {marker}")
        marker_index = stderr.index(marker)
        if marker_index <= previous_index:
            raise M0Error(f"navigation-churn markers have invalid order: {marker}")
        previous_index = marker_index
    stderr_text = "\n".join(stderr)
    if all(
        marker in stderr_text for marker in DISCARDABLE_MEMORY_MANAGER_LEAK_MARKERS
    ):
        raise M0Error(
            "navigation-churn observed a live discardable-memory Mojo receiver "
            "during shutdown"
        )


def validate_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
    expected_artifact_identity: dict[str, object],
    expected_capture_harness_identity: dict[str, object],
) -> None:
    for field, expected in {
        "protocol": 1,
        "case": CASE,
        "scope": SCOPE,
        "status": "pass",
        "m9GateComplete": False,
        "runtimeExitCode": 0,
        "processExitCode": 0,
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
    if result.get("limitations") != list(LIMITATIONS):
        raise M0Error("navigation-churn limitations are not exact")
    if not browser_view_smoke._exact_json_value_equal(
        result.get("versions"), expected_versions
    ):
        raise M0Error("navigation-churn versions do not match the manifest")
    _validate_artifact_identity(result.get("artifact"), expected_artifact_identity)
    _validate_capture_harness_identity(
        result.get("capture_harness"), expected_capture_harness_identity
    )
    for field in ("fatalErrors", "windowErrors", "unhandledRejections"):
        if not isinstance(result.get(field), list) or result[field]:
            raise M0Error(f"navigation-churn {field} is not empty")
    if not isinstance(result.get("stdout"), list):
        raise M0Error("navigation-churn stdout is not a list")
    frame_reports = result.get("frameReports")
    browser_view_smoke._validate_frame_reports(frame_reports)
    browser_view_smoke._validate_readiness(
        result.get("readiness"), result.get("readinessReports")
    )
    churn = result.get("navigationChurn")
    expected_churn_keys = {
        "cycleCount",
        "navigationsPerCycle",
        "stageCount",
        "frameTransitionPolicy",
        "readyObserved",
        "passObserved",
        "lifecyclePassObserved",
        "stages",
    }
    if not isinstance(churn, dict) or set(churn) != expected_churn_keys:
        raise M0Error("navigation-churn evidence schema is invalid")
    if (
        type(churn.get("cycleCount")) is not int
        or type(churn.get("navigationsPerCycle")) is not int
        or type(churn.get("stageCount")) is not int
        or churn["cycleCount"] != CYCLE_COUNT
        or churn["navigationsPerCycle"] != NAVIGATIONS_PER_CYCLE
        or churn["stageCount"] != STAGE_COUNT
        or churn.get("frameTransitionPolicy") != FRAME_TRANSITION_POLICY
        or churn.get("readyObserved") is not True
        or churn.get("passObserved") is not True
        or churn.get("lifecyclePassObserved") is not True
    ):
        raise M0Error("navigation-churn fixed evidence metadata is invalid")
    raw_stages = churn.get("stages")
    if not isinstance(raw_stages, list) or len(raw_stages) != STAGE_COUNT:
        raise M0Error("navigation-churn evidence does not include every fixed stage")
    assert isinstance(frame_reports, list)
    frame_ids = {frame["id"] for frame in frame_reports if isinstance(frame, dict)}
    stages: list[dict[str, object]] = []
    for index, raw_stage in enumerate(raw_stages):
        stage = _validate_stage(
            raw_stage, index + 1, frame_ids, stages[-1] if stages else None
        )
        if stages and stages[-1]["backingStoreCopyFrameId"] > stage["navigationMarkerFrameId"]:
            raise M0Error("navigation-churn stages have invalid copy chronology")
        stages.append(stage)
    _validate_markers(result.get("stderr"), stages)
    _validate_wasm_heap_buffer_capacity(result.get("wasmHeapBufferCapacity"), stages)
    _validate_native_memory_snapshot(result.get("nativeMemorySnapshot"), stages)


def wait_for_result(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    result_queue: queue.Queue[dict[str, Any]],
    deadline: float,
) -> dict[str, Any]:
    while True:
        if browser.poll() is not None:
            raise M0Error(
                "host browser exited before navigation-churn result: "
                + "\n".join(browser_stderr)
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M0Error(
                "navigation-churn smoke timeout: " + "\n".join(browser_stderr)
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
) -> Path:
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / "chrome-browser-navigation-churn-m9-failure.json"
    payload = {
        "schema_version": 1,
        "runner": "run_m9_wasm_browser_navigation_churn_dom_smoke.py",
        "case": CASE,
        "scope": SCOPE,
        "stage": stage,
        "limitations": list(LIMITATIONS),
        "failure": {"type": type(error).__name__, "message": str(error)},
        "host_browser": {
            "path": str(browser_path) if browser_path else None,
            "version": browser_version,
            "return_code": browser.poll() if browser else None,
            "stderr_tail": list(browser_stderr),
        },
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
    """Runs one cleanup action without preventing the remaining cleanup."""

    try:
        action()
    except BaseException as exc:
        if cleanup_error is None:
            return exc
    return cleanup_error


def _join_navigation_churn_server(thread: threading.Thread) -> None:
    """Joins a started navigation-churn server after shutdown."""

    thread.join(timeout=1)
    if thread.is_alive():
        raise M0Error("M9 navigation-churn server did not stop")


def _cleanup_navigation_churn_server(
    *,
    server: NavigationChurnSmokeServer | None,
    server_thread: threading.Thread | None,
    server_thread_started: bool,
) -> BaseException | None:
    """Stops the server while always closing its socket and joining it."""

    cleanup_error: BaseException | None = None
    if server is not None:
        if server_thread_started:
            cleanup_error = _run_cleanup_action(
                cleanup_error,
                lambda: shutdown_server_bounded(
                    server, timeout=1, description="M9 navigation-churn server"
                ),
            )
        cleanup_error = _run_cleanup_action(cleanup_error, server.server_close)
    if server_thread_started and server_thread is not None:
        cleanup_error = _run_cleanup_action(
            cleanup_error, lambda: _join_navigation_churn_server(server_thread)
        )
    if server is not None:
        cleanup_error = _run_cleanup_action(
            cleanup_error,
            lambda: server.join_request_handlers(
                timeout=1, description="M9 navigation-churn server"
            ),
        )
    return cleanup_error


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run bounded same-instance native data: navigation churn."
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--module-name", default=DEFAULT_MODULE_NAME)
    parser.add_argument("--diagnostics-dir", type=Path)
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--timeout", type=parse_timeout, default=90.0)
    args = parser.parse_args()
    if args.timeout < 15.0:
        parser.error("--timeout must be at least fifteen seconds")
    if not MODULE_NAME_RE.fullmatch(args.module_name):
        parser.error("--module-name must contain only ASCII letters, digits, or _")
    if args.module_name != PRODUCT_MODULE_NAME:
        parser.error(
            "--module-name must be chrome_wasm for this product navigation churn"
        )

    out_dir = args.out_dir if args.out_dir.is_absolute() else REPO_ROOT / args.out_dir
    diagnostics_dir = args.diagnostics_dir or out_dir / "diagnostics"
    if not diagnostics_dir.is_absolute():
        diagnostics_dir = REPO_ROOT / diagnostics_dir
    server: NavigationChurnSmokeServer | None = None
    server_thread: threading.Thread | None = None
    server_thread_started = False
    browser: subprocess.Popen[str] | None = None
    browser_path: Path | None = None
    browser_version: str | None = None
    browser_stderr: deque[str] = deque(maxlen=300)
    stderr_reader: BrowserStderrReader | None = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    result: dict[str, Any] | None = None
    stage = "check_artifacts"
    primary_error: BaseException | None = None
    reported_error: Exception | None = None

    try:
        stage = "check_boundary"
        check_boundary(out_dir)
        token = secrets.token_urlsafe(24)
        result_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        stage = "snapshot_server_inputs"
        server = create_server(
            "127.0.0.1", 0, out_dir, token, result_queue, module_name=args.module_name
        )
        artifact = artifact_identity(server, module_name=args.module_name)
        capture_harness = capture_harness_identity(server)
        verify_required_exports(server.artifacts[f"{args.module_name}.js"])
        stage = "load_manifest"
        manifest = load_manifest()
        versions = toolchain_manifest_versions(manifest)
        context = {
            "artifact": artifact,
            "capture_harness": capture_harness,
            "case": CASE,
            "cycles": CYCLE_COUNT,
            "host_browser_sandbox": not args.no_sandbox,
            "limitations": list(LIMITATIONS),
            "module_name": args.module_name,
            "runtime_arguments": [SWITCH],
            "scope": SCOPE,
            "script": "run_m9_wasm_browser_navigation_churn_dom_smoke.py",
            "toolchain_versions": versions,
            "version_provenance": VERSION_PROVENANCE,
        }
        print(
            "CHROMIUM_WASM_M0:CONFIG "
            + json.dumps(context, sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        stage = "find_browser"
        browser_path, browser_version = find_browser(args.browser)
        stage = "serve"
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m9-navigation-churn-server",
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
        profile = tempfile.TemporaryDirectory(
            prefix="chromium-wasm-m9-navigation-churn-"
        )
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
            name="chromium-wasm-m9-navigation-churn-browser-stderr",
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
            cleanup_error = _run_cleanup_action(
                cleanup_error, lambda: abort_browser_group(browser, stderr_reader)
            )
        server_cleanup_error = _cleanup_navigation_churn_server(
            server=server,
            server_thread=server_thread,
            server_thread_started=server_thread_started,
        )
        if cleanup_error is None:
            cleanup_error = server_cleanup_error
        if profile is not None:
            cleanup_error = _run_cleanup_action(cleanup_error, profile.cleanup)
        if primary_error is None and cleanup_error is not None:
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
    if result is None:
        raise RuntimeError("navigation-churn smoke completed without a result")
    # Do not report a passing churn result until server teardown succeeds.
    print(
        f"{SENTINEL}:BROWSER_RESULT "
        + json.dumps(result, sort_keys=True, separators=(",", ":")),
        flush=True,
    )
    print(f"{SENTINEL}:PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
