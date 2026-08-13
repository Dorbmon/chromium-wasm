#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Exercise three fixed tab-churn cycles in one real Chrome Wasm Browser.

The runner dispatches only trusted physical mouse input at native Views targets
published by the lifecycle-owned C++ coordinator. Each cycle opens a blank tab,
selects the initial tab, selects the new tab, and closes it. No host action
navigates, evaluates a page script, invokes a Wasm command export, or selects a
network/profile/worker operation.
"""

from __future__ import annotations

import argparse
from collections import deque
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
from urllib.parse import urlencode, urlsplit

from check_m6_chrome_boundary import check_boundary
from m0_common import (
    M0Error,
    REPO_ROOT,
    load_manifest,
    parse_timeout,
)
from m4_cdp import unused_loopback_port, wait_for_page_client
from run_browser_smoke import browser_command, drain_stream, find_browser, stop_browser
import run_wasm_browser_view_smoke as browser_view_smoke


SENTINEL = "CHROMIUM_WASM_M9_TAB_CHURN_DOM"
CASE = "browser_same_instance_tab_churn_m9"
SCOPE = (
    "fixed-three-cycle-same-instance-tab-churn-with-later-"
    "backing-store-copy-observation-only"
)
SWITCH = "--wasm-browser-host-tab-churn-smoke"
READY_MARKER = "CHROMIUM_WASM_M9_TAB_CHURN:READY"
VERIFIED_MARKER = "CHROMIUM_WASM_M9_TAB_CHURN:VERIFIED"
PASS_MARKER = "CHROMIUM_WASM_M9_TAB_CHURN:PASS"
LIFECYCLE_PASS_MARKER = "CHROMIUM_WASM_M6_BROWSER_LIFECYCLE:PASS"
DEFAULT_OUT_DIR = Path("out/wasm-chrome-m6")
DEFAULT_MODULE_NAME = "chrome_wasm"
HOST_ROOT = "/__m9_browser_tab_churn__"
CYCLE_COUNT = 3
ACTIONS = ("new-tab", "select-first", "select-second", "close-second")
STAGE_COUNT = CYCLE_COUNT * len(ACTIONS)
# A copy record may serve as both the previous stage's required later copy and
# the next stage's ready snapshot. The next READY marker is printed
# synchronously while the deferred copy verifier accepts that same report, so
# equal frame IDs are intentional; reverse frame order is never accepted.
FRAME_TRANSITION_POLICY = (
    "previous-backing-store-copy-may-share-next-ready-frame"
)
MAX_RESULT_BYTES = 2 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024 * 1024
MAX_FRAME_DIMENSION = 16384
MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
GIT_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
READY_RE = re.compile(
    r"^CHROMIUM_WASM_M9_TAB_CHURN:READY cycle=(\d+) stage=(\d+) "
    r"action=(new-tab|select-first|select-second|close-second) x=(\d+) y=(\d+)$"
)
VERIFIED_RE = re.compile(
    r"^CHROMIUM_WASM_M9_TAB_CHURN:VERIFIED cycle=(\d+) stage=(\d+) "
    r"action=(new-tab|select-first|select-second|close-second)$"
)
LIMITATIONS = (
    "does_not_exercise_navigation_or_page_javascript",
    "does_not_exercise_page_webassembly",
    "does_not_exercise_wisp_or_network_reconnect",
    "does_not_prove_opfs_persistence_or_recovery",
    "does_not_measure_memory_growth_or_address_space_pressure",
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
        "pointer_input_js",
        "runner_source",
        "source_snapshot_provenance",
        "version_provenance",
    )
)


class TabChurnSmokeServer(ThreadingHTTPServer):
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
    pointer_input_js: bytes
    runner_source: bytes


class TabChurnSmokeRequestHandler(BaseHTTPRequestHandler):
    server: TabChurnSmokeServer

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
        static = {
            f"{HOST_ROOT}/chrome_wasm_browser_tab_churn_smoke_host.js": (
                "text/javascript; charset=utf-8",
                self.server.host_js,
            ),
            f"{HOST_ROOT}/chrome_wasm_pointer_input.js": (
                "text/javascript; charset=utf-8",
                self.server.pointer_input_js,
            ),
        }.get(path)
        if static is not None:
            self._send_bytes(HTTPStatus.OK, static[0], static[1])
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
                b"invalid tab-churn result\n",
            )
            return
        with self.server.result_lock:
            if self.server.result_received:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"tab-churn result already received\n",
                )
                return
            try:
                self.server.result_queue.put_nowait(result)
            except queue.Full:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"tab-churn result queue is full\n",
                )
                return
            self.server.result_received = True
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()


def stage_info(stage: int) -> dict[str, object]:
    if type(stage) is not int or not 1 <= stage <= STAGE_COUNT:
        raise M0Error("tab-churn stage is out of range")
    return {
        "cycle": ((stage - 1) // len(ACTIONS)) + 1,
        "stage": stage,
        "action": ACTIONS[(stage - 1) % len(ACTIONS)],
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


def _read_snapshot(path: Path, description: str) -> bytes:
    try:
        contents = path.read_bytes()
    except OSError as error:
        raise M0Error(f"cannot snapshot tab-churn {description}: {error}") from error
    if not contents or len(contents) > MAX_SNAPSHOT_BYTES:
        raise M0Error(f"tab-churn {description} snapshot is invalid")
    return contents


def _artifact_snapshot_path(out_dir: Path, artifact_name: str) -> Path:
    candidate = (out_dir / artifact_name).resolve()
    if candidate.parent != out_dir or not candidate.is_file():
        raise M0Error(f"tab-churn artifact is missing or unsafe: {artifact_name}")
    return candidate


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
) -> TabChurnSmokeServer:
    if not MODULE_NAME_RE.fullmatch(module_name):
        raise M0Error("module name must contain only ASCII letters, digits, or _")
    out_dir = out_dir.resolve()
    if not out_dir.is_dir():
        raise M0Error(f"tab-churn output directory is missing: {out_dir}")
    loader_name = f"{module_name}.js"
    wasm_name = f"{module_name}.wasm"
    artifacts = {
        artifact_name: _read_snapshot(
            _artifact_snapshot_path(out_dir, artifact_name),
            f"artifact {artifact_name}",
        )
        for artifact_name in (loader_name, wasm_name)
    }
    selected_host_dir = host_dir or Path(__file__).with_name("host")
    selected_runner_source = runner_source_path or Path(__file__)
    server = TabChurnSmokeServer((host, port), TabChurnSmokeRequestHandler)
    server.artifacts = artifacts
    server.module_name = module_name
    server.result_token = token
    server.result_queue = result_queue
    server.result_lock = threading.Lock()
    server.result_received = False
    server.host_html = _read_snapshot(
        selected_host_dir / "chrome_wasm_browser_tab_churn_smoke.html", "host HTML"
    )
    server.host_js = _read_snapshot(
        selected_host_dir / "chrome_wasm_browser_tab_churn_smoke_host.js",
        "host JavaScript",
    )
    server.pointer_input_js = _read_snapshot(
        selected_host_dir / "chrome_wasm_pointer_input.js", "pointer-input JavaScript"
    )
    server.runner_source = _read_snapshot(selected_runner_source, "runner source")
    return server


def _byte_identity(contents: bytes) -> dict[str, object]:
    return {"bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}


def artifact_identity(
    server: TabChurnSmokeServer, *, module_name: str
) -> dict[str, object]:
    return {
        "artifact_delivery": ARTIFACT_DELIVERY,
        "artifact_source_provenance": ARTIFACT_SOURCE_PROVENANCE,
        "loader": _byte_identity(server.artifacts[f"{module_name}.js"]),
        "module_name": module_name,
        "wasm": _byte_identity(server.artifacts[f"{module_name}.wasm"]),
    }


def capture_harness_identity(server: TabChurnSmokeServer) -> dict[str, object]:
    return {
        "host_html": _byte_identity(server.host_html),
        "host_js": _byte_identity(server.host_js),
        "pointer_input_js": _byte_identity(server.pointer_input_js),
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
        raise M0Error("tab-churn manifest lacks toolchain version metadata") from error
    if not all(
        isinstance(value, str) and GIT_REVISION_RE.fullmatch(value)
        for value in versions.values()
    ):
        raise M0Error("tab-churn manifest toolchain version metadata is invalid")
    return versions


def smoke_url(
    server: TabChurnSmokeServer,
    token: str,
    versions: dict[str, str],
    *,
    artifact: dict[str, object],
    capture_harness: dict[str, object],
    module_name: str,
    timeout_seconds: float,
) -> str:
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
        raise M0Error(f"cannot decode tab-churn module loader: {error}") from error
    for export in (
        'Module["_chromium_wasm_browser_host_pointer"]',
        'Module["_chromium_wasm_browser_host_pointer_exit"]',
        'Module["_chromium_wasm_browser_host_tab_churn_check"]',
        'Module["_chromium_wasm_browser_host_tab_churn_presented"]',
        'Module["_malloc"]',
        'Module["_free"]',
        'Module["ccall"]',
        'Module["HEAPU8"]',
    ):
        if export not in loader:
            raise M0Error(f"tab-churn module lacks required export {export}")


def _require_equal(result: dict[str, Any], field: str, expected: object) -> None:
    if not browser_view_smoke._exact_json_value_equal(result.get(field), expected):
        raise M0Error(
            f"tab-churn result {field} mismatch: expected {expected!r}, "
            f"got {result.get(field)!r}"
        )


def _require_exact_fields(
    value: object, expected: frozenset[str], description: str
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        actual = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise M0Error(
            f"tab-churn {description} schema is invalid: "
            f"expected {sorted(expected)!r}, got {actual!r}"
        )
    return value


def _validate_byte_identity(value: object, description: str) -> None:
    identity = _require_exact_fields(value, _BYTE_IDENTITY_FIELDS, description)
    byte_count = identity.get("bytes")
    if type(byte_count) is not int or byte_count < 1:
        raise M0Error(f"tab-churn {description} byte count is invalid")
    sha256 = identity.get("sha256")
    if type(sha256) is not str or not SHA256_RE.fullmatch(sha256):
        raise M0Error(f"tab-churn {description} SHA-256 is invalid")


def _validate_artifact_identity(
    value: object, expected_identity: dict[str, object]
) -> None:
    artifact = _require_exact_fields(
        value, _ARTIFACT_IDENTITY_FIELDS, "artifact identity"
    )
    if artifact.get("artifact_source_provenance") != ARTIFACT_SOURCE_PROVENANCE:
        raise M0Error("tab-churn artifact source provenance is invalid")
    if artifact.get("artifact_delivery") != ARTIFACT_DELIVERY:
        raise M0Error("tab-churn artifact delivery is invalid")
    module_name = artifact.get("module_name")
    if type(module_name) is not str or not MODULE_NAME_RE.fullmatch(module_name):
        raise M0Error("tab-churn artifact module name is invalid")
    for field in ("loader", "wasm"):
        _validate_byte_identity(artifact.get(field), f"artifact {field}")
    if not browser_view_smoke._exact_json_value_equal(artifact, expected_identity):
        raise M0Error("tab-churn artifact identity disagrees with served snapshot")


def _validate_capture_harness_identity(
    value: object, expected_identity: dict[str, object]
) -> None:
    harness = _require_exact_fields(
        value, _CAPTURE_HARNESS_FIELDS, "capture harness identity"
    )
    if harness.get("source_snapshot_provenance") != SOURCE_SNAPSHOT_PROVENANCE:
        raise M0Error("tab-churn capture-harness source provenance is invalid")
    if harness.get("version_provenance") != VERSION_PROVENANCE:
        raise M0Error("tab-churn capture-harness version provenance is invalid")
    for field in ("host_html", "host_js", "pointer_input_js", "runner_source"):
        _validate_byte_identity(harness.get(field), f"capture harness {field}")
    if not browser_view_smoke._exact_json_value_equal(harness, expected_identity):
        raise M0Error("tab-churn capture harness disagrees with served snapshot")


def _validate_target(value: object, description: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {"x", "y", "clientX", "clientY"}:
        raise M0Error(f"tab-churn {description} target is invalid")
    for field in ("x", "y"):
        coordinate = value.get(field)
        if type(coordinate) is not int or not 0 <= coordinate < MAX_FRAME_DIMENSION:
            raise M0Error(f"tab-churn {description} target {field} is invalid")
    for field in ("clientX", "clientY"):
        coordinate = value.get(field)
        if type(coordinate) is bool or not isinstance(coordinate, (int, float)):
            raise M0Error(f"tab-churn {description} target {field} is invalid")
        if not 0 <= float(coordinate) < 10000:
            raise M0Error(f"tab-churn {description} target {field} is invalid")
    return value


def _validate_stage(
    value: object, expected_stage: int, frame_ids: set[int]
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise M0Error(f"tab-churn stage {expected_stage} is missing")
    expected = stage_info(expected_stage)
    expected_keys = {
        "cycle",
        "stage",
        "action",
        "target",
        "readyFrameId",
        "checkQueued",
        "verified",
        "verifiedFrameId",
        "backingStoreCopyFrameId",
        "backingStoreCopyQueued",
        "passObserved",
    }
    if set(value) != expected_keys:
        raise M0Error(f"tab-churn stage {expected_stage} schema is invalid")
    # Do not rely on Python's `True == 1` or `1.0 == 1` coercions for the
    # fixed ordinal evidence. These identity fields are part of the runner's
    # protocol, not merely values that happen to compare equal.
    for field in ("cycle", "stage"):
        if type(value.get(field)) is not int or value[field] != expected[field]:
            raise M0Error(f"tab-churn stage {expected_stage} {field} is invalid")
    if (
        type(value.get("action")) is not str
        or value["action"] != expected["action"]
    ):
        raise M0Error(f"tab-churn stage {expected_stage} action is invalid")
    _validate_target(value.get("target"), f"stage {expected_stage}")
    for field in (
        "readyFrameId",
        "verifiedFrameId",
        "backingStoreCopyFrameId",
    ):
        frame_id = value.get(field)
        if type(frame_id) is not int or frame_id < 1 or frame_id not in frame_ids:
            raise M0Error(f"tab-churn stage {expected_stage} {field} is invalid")
    if (
        value["readyFrameId"] > value["verifiedFrameId"]
        or value["backingStoreCopyFrameId"] <= value["verifiedFrameId"]
    ):
        raise M0Error(
            f"tab-churn stage {expected_stage} lacks ordered Canvas2D copy evidence"
        )
    for field in ("checkQueued", "verified", "backingStoreCopyQueued"):
        if value.get(field) is not True:
            raise M0Error(f"tab-churn stage {expected_stage} {field} is not true")
    if value.get("passObserved") is not (expected_stage == STAGE_COUNT):
        raise M0Error(f"tab-churn stage {expected_stage} pass observation is invalid")
    return value


def _validate_pointer_records(records: object, stages: list[dict[str, object]]) -> None:
    if not isinstance(records, list):
        raise M0Error("tab-churn pointer records are missing")
    for record in records:
        if isinstance(record, dict) and record.get("accepted") is not True:
            raise M0Error("tab-churn rejected a trusted outer pointer record")
    actions = [
        record
        for record in records
        if isinstance(record, dict) and record.get("type") in ("down", "up")
    ]
    if len(actions) != STAGE_COUNT * 2:
        raise M0Error("tab-churn must record exactly one click for each stage")
    for stage_index, stage in enumerate(stages):
        target = _validate_target(stage["target"], f"stage {stage_index + 1}")
        for record, event_type, buttons in (
            (actions[stage_index * 2], "down", 1),
            (actions[stage_index * 2 + 1], "up", 0),
        ):
            # `bool` is a subclass of `int`, so preserve exact JSON integer
            # semantics for the physical-button evidence before comparing it.
            if type(record.get("button")) is not int:
                raise M0Error(
                    f"tab-churn stage {stage_index + 1} pointer "
                    f"{event_type} button is invalid"
                )
            if type(record.get("buttons")) is not int:
                raise M0Error(
                    f"tab-churn stage {stage_index + 1} pointer "
                    f"{event_type} buttons is invalid"
                )
            for field, expected in {
                "type": event_type,
                "trusted": True,
                "cancelable": True,
                "pointerType": "mouse",
                "primary": True,
                "button": 0,
                "buttons": buttons,
                "accepted": True,
                "defaultPrevented": True,
                "x": target["x"],
                "y": target["y"],
                "reason": None,
            }.items():
                if not browser_view_smoke._exact_json_value_equal(
                    record.get(field), expected
                ):
                    raise M0Error(
                        "tab-churn stage "
                        f"{stage_index + 1} pointer {event_type} {field} is invalid"
                    )


def _validate_markers(stderr: object, stages: list[dict[str, object]]) -> None:
    if not isinstance(stderr, list):
        raise M0Error("tab-churn stderr is not a list")
    if any(type(value) is not str for value in stderr):
        raise M0Error("tab-churn stderr has a non-string record")
    lines = stderr
    ready: list[tuple[int, int, int, str, int, int]] = []
    verified: list[tuple[int, int, int, str]] = []
    for line_index, line in enumerate(lines):
        ready_match = READY_RE.fullmatch(line)
        if ready_match:
            ready.append(
                (
                    line_index,
                    int(ready_match.group(1)),
                    int(ready_match.group(2)),
                    ready_match.group(3),
                    int(ready_match.group(4)),
                    int(ready_match.group(5)),
                )
            )
        verified_match = VERIFIED_RE.fullmatch(line)
        if verified_match:
            verified.append(
                (
                    line_index,
                    int(verified_match.group(1)),
                    int(verified_match.group(2)),
                    verified_match.group(3),
                )
            )
    if len(ready) != STAGE_COUNT or len(verified) != STAGE_COUNT:
        raise M0Error("tab-churn does not have one READY/VERIFIED marker per stage")
    previous_verified_index = -1
    for stage in range(1, STAGE_COUNT + 1):
        expected = stage_info(stage)
        ready_index, ready_cycle, ready_stage, ready_action, x, y = ready[stage - 1]
        if (
            ready_cycle != expected["cycle"]
            or ready_stage != stage
            or ready_action != expected["action"]
            or not 0 <= x < MAX_FRAME_DIMENSION
            or not 0 <= y < MAX_FRAME_DIMENSION
        ):
            raise M0Error(f"tab-churn READY marker {stage} is invalid")
        target = _validate_target(stages[stage - 1]["target"], f"stage {stage}")
        if target["x"] != x or target["y"] != y:
            raise M0Error(f"tab-churn READY marker {stage} target is invalid")
        verified_index, verified_cycle, verified_stage, verified_action = verified[
            stage - 1
        ]
        if (
            verified_cycle != expected["cycle"]
            or verified_stage != stage
            or verified_action != expected["action"]
        ):
            raise M0Error(f"tab-churn VERIFIED marker {stage} is invalid")
        # Preserve the causal marker sequence, not just marker multiplicity:
        # the physical-action target for this stage must be published before
        # its native model verification, and the next target follows that
        # verification only after the accepted later copy callback.
        if ready_index <= previous_verified_index or verified_index <= ready_index:
            raise M0Error(f"tab-churn markers have invalid temporal order at stage {stage}")
        previous_verified_index = verified_index
    pass_marker = f"{PASS_MARKER} cycles={CYCLE_COUNT}"
    if lines.count(pass_marker) != 1:
        raise M0Error("tab-churn stderr has no unique final PASS marker")
    if lines.count(LIFECYCLE_PASS_MARKER) != 1:
        raise M0Error("tab-churn did not complete normal Browser lifecycle shutdown")
    pass_index = lines.index(pass_marker)
    lifecycle_pass_index = lines.index(LIFECYCLE_PASS_MARKER)
    if pass_index <= previous_verified_index or lifecycle_pass_index <= pass_index:
        raise M0Error("tab-churn final PASS/lifecycle marker order is invalid")


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
        raise M0Error("tab-churn limitations are not exact")
    process_exit_code = result.get("processExitCode")
    if process_exit_code is not None and (
        type(process_exit_code) is not int or process_exit_code != 0
    ):
        raise M0Error("tab-churn bridge process exit disagrees with runtime")
    if not browser_view_smoke._exact_json_value_equal(
        result.get("versions"), expected_versions
    ):
        raise M0Error("tab-churn versions do not match the manifest")
    _validate_artifact_identity(result.get("artifact"), expected_artifact_identity)
    _validate_capture_harness_identity(
        result.get("capture_harness"), expected_capture_harness_identity
    )
    for field in ("fatalErrors", "windowErrors", "unhandledRejections"):
        if not isinstance(result.get(field), list) or result[field]:
            raise M0Error(f"tab-churn {field} is not empty")
    if not isinstance(result.get("stdout"), list):
        raise M0Error("tab-churn stdout is not a list")
    frame_reports = result.get("frameReports")
    browser_view_smoke._validate_frame_reports(frame_reports)
    browser_view_smoke._validate_readiness(
        result.get("readiness"), result.get("readinessReports")
    )
    browser_view_smoke._validate_focus_reports(result.get("ozoneFocusReports"))

    churn = result.get("tabChurn")
    if not isinstance(churn, dict) or set(churn) != {
        "cycleCount",
        "frameTransitionPolicy",
        "stageCount",
        "stages",
        "pointerRecords",
    }:
        raise M0Error("tab-churn evidence schema is invalid")
    if (
        type(churn.get("cycleCount")) is not int
        or type(churn.get("stageCount")) is not int
        or churn.get("cycleCount") != CYCLE_COUNT
        or churn.get("stageCount") != STAGE_COUNT
    ):
        raise M0Error("tab-churn cycle or stage count is invalid")
    if churn.get("frameTransitionPolicy") != FRAME_TRANSITION_POLICY:
        raise M0Error("tab-churn frame transition policy is invalid")
    raw_stages = churn.get("stages")
    if not isinstance(raw_stages, list) or len(raw_stages) != STAGE_COUNT:
        raise M0Error("tab-churn evidence does not include every fixed stage")
    assert isinstance(frame_reports, list)
    frame_ids = {frame["id"] for frame in frame_reports if isinstance(frame, dict)}
    stages: list[dict[str, object]] = []
    for index, value in enumerate(raw_stages):
        stage = _validate_stage(value, index + 1, frame_ids)
        if stages:
            previous_copy = stages[-1]["backingStoreCopyFrameId"]
            next_ready = stage["readyFrameId"]
            # See FRAME_TRANSITION_POLICY: the same host copy may establish
            # the prior copy observation and expose the next native target.
            if previous_copy > next_ready:
                raise M0Error(
                    "tab-churn stages have invalid cross-stage copy chronology"
                )
        stages.append(stage)
    _validate_markers(result.get("stderr"), stages)
    _validate_pointer_records(churn.get("pointerRecords"), stages)


def _take_early_result(result_queue: queue.Queue[dict[str, Any]], stage: str) -> None:
    try:
        result = result_queue.get_nowait()
    except queue.Empty:
        return
    raise M0Error(
        f"tab-churn smoke finished before {stage}: "
        + json.dumps(result, sort_keys=True, separators=(",", ":"))
    )


def wait_for_stage(
    client: Any,
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    result_queue: queue.Queue[dict[str, Any]],
    expected: dict[str, object],
    deadline: float,
) -> dict[str, object]:
    last_state: object = None
    expression = "globalThis.__chromiumWasmM9TabChurnState || null"
    while time.monotonic() < deadline:
        if browser.poll() is not None:
            raise M0Error(
                "host browser exited before tab-churn stage "
                f"{expected['stage']}: " + "\n".join(browser_stderr)
            )
        _take_early_result(result_queue, f"tab-churn stage {expected['stage']}")
        last_state = client.evaluate(expression)
        if (
            isinstance(last_state, dict)
            and last_state.get("state") == "awaiting-trusted-dom-action"
            and last_state.get("stage") == expected["stage"]
            and last_state.get("cycle") == expected["cycle"]
            and last_state.get("action") == expected["action"]
        ):
            target = _validate_target(
                last_state.get("target"), f"state stage {expected['stage']}"
            )
            return {**last_state, "target": target}
        time.sleep(0.05)
    raise M0Error(
        "tab-churn smoke did not reach stage "
        f"{expected['stage']}: "
        + json.dumps(last_state, sort_keys=True, separators=(",", ":"))
    )


def click_target(client: Any, state: dict[str, object]) -> None:
    target = _validate_target(state.get("target"), "state")
    # This is a real host-browser DevTools physical mouse stream. The runner
    # never evaluates page JavaScript to manipulate Chrome or calls a Wasm
    # export, so C++ can only observe normal Ozone/Aura/Views input effects.
    client.dispatch_primary_click(float(target["clientX"]), float(target["clientY"]))


def wait_for_result(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    result_queue: queue.Queue[dict[str, Any]],
    deadline: float,
) -> dict[str, Any]:
    while time.monotonic() < deadline:
        if browser.poll() is not None:
            raise M0Error(
                "host browser exited before tab-churn result: "
                + "\n".join(browser_stderr)
            )
        try:
            return result_queue.get(timeout=0.1)
        except queue.Empty:
            continue
    raise M0Error("tab-churn smoke did not post its result")


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
    runtime_result: dict[str, Any] | None,
) -> Path:
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / "chrome-browser-tab-churn-m9-failure.json"
    payload = {
        "schema_version": 1,
        "runner": "run_m9_wasm_browser_tab_churn_dom_smoke.py",
        "case": CASE,
        "scope": SCOPE,
        "stage": stage,
        "limitations": list(LIMITATIONS),
        "failure": {"type": type(error).__name__, "message": str(error)},
        "context": context,
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run fixed same-instance Chrome Wasm tab churn through trusted DOM input."
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

    out_dir = args.out_dir if args.out_dir.is_absolute() else REPO_ROOT / args.out_dir
    diagnostics_dir = args.diagnostics_dir or out_dir / "diagnostics"
    if not diagnostics_dir.is_absolute():
        diagnostics_dir = REPO_ROOT / diagnostics_dir
    server: TabChurnSmokeServer | None = None
    server_thread: threading.Thread | None = None
    server_thread_started = False
    browser: subprocess.Popen[str] | None = None
    client: Any = None
    browser_path: Path | None = None
    browser_version: str | None = None
    browser_stderr: deque[str] = deque(maxlen=300)
    stderr_thread: threading.Thread | None = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    runtime_result: dict[str, Any] | None = None
    context: dict[str, object] | None = None
    artifact: dict[str, object] | None = None
    capture_harness: dict[str, object] | None = None
    stage = "check_artifacts"

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
        # The snapshots identify the exact bytes served to this run. They do
        # not establish which uncommitted/local source tree built them, so the
        # current Git HEAD is deliberately not reported as artifact provenance.
        context = {
            "actions_per_cycle": list(ACTIONS),
            "artifact": artifact,
            "capture_harness": capture_harness,
            "case": CASE,
            "cycles": CYCLE_COUNT,
            "host_browser_sandbox": not args.no_sandbox,
            "limitations": list(LIMITATIONS),
            "module_name": args.module_name,
            "runtime_arguments": [SWITCH],
            "scope": SCOPE,
            "script": "run_m9_wasm_browser_tab_churn_dom_smoke.py",
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
        stage = "create_server"
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m9-tab-churn-server",
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
        profile = tempfile.TemporaryDirectory(prefix="chromium-wasm-m9-tab-churn-")
        debug_port = unused_loopback_port()
        stage = "launch_browser"
        command = browser_command(browser_path, profile.name, url, no_sandbox=args.no_sandbox)
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
        stderr_thread = threading.Thread(
            target=drain_stream,
            args=(browser.stderr, browser_stderr),
            name="chromium-wasm-m9-tab-churn-browser-stderr",
            daemon=True,
        )
        stderr_thread.start()
        deadline = time.monotonic() + args.timeout
        stage = "connect_devtools"
        client = wait_for_page_client(debug_port, url.split("?", 1)[0], deadline)
        for tab_stage in range(1, STAGE_COUNT + 1):
            expected = stage_info(tab_stage)
            stage = f"wait_for_stage_{tab_stage}"
            state = wait_for_stage(
                client, browser, browser_stderr, result_queue, expected, deadline
            )
            stage = f"dispatch_stage_{tab_stage}"
            click_target(client, state)
        stage = "wait_for_result"
        runtime_result = wait_for_result(browser, browser_stderr, result_queue, deadline)
        stage = "validate_result"
        validate_result(
            runtime_result,
            expected_versions=versions,
            expected_artifact_identity=artifact,
            expected_capture_harness_identity=capture_harness,
        )
        print(
            f"{SENTINEL}:BROWSER_RESULT "
            + json.dumps(runtime_result, sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        print(f"{SENTINEL}:PASS", flush=True)
        return 0
    except (M0Error, OSError, KeyError, TypeError, ValueError) as error:
        if browser is not None:
            stop_browser(browser)
        if stderr_thread is not None:
            stderr_thread.join(timeout=1)
        try:
            diagnostic = write_failure_diagnostics(
                diagnostics_dir,
                stage=stage,
                error=error,
                context=context,
                browser_path=browser_path,
                browser_version=browser_version,
                browser=browser,
                browser_stderr=browser_stderr,
                runtime_result=runtime_result,
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
        print(f"{SENTINEL}:FAIL reason={error}", file=sys.stderr, flush=True)
        return 1
    finally:
        if client is not None:
            client.close()
        if browser is not None:
            stop_browser(browser)
        if stderr_thread is not None:
            stderr_thread.join(timeout=1)
        if server is not None:
            if server_thread_started:
                server.shutdown()
            server.server_close()
        if server_thread_started and server_thread is not None:
            server_thread.join(timeout=1)
        if profile is not None:
            profile.cleanup()


if __name__ == "__main__":
    sys.exit(main())
