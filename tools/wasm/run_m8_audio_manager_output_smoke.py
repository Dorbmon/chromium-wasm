#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run one trusted-gesture AudioManager output stream through WebAudio.

Every served input is snapshotted before the server starts. The runner waits
for a fixed host-ready POST and sends one physical DevTools click; it never
evaluates page JavaScript or calls a Wasm export. Native output and browser
stderr are deliberately excluded from diagnostics because either can contain
untrusted strings.
"""

from __future__ import annotations

import argparse
from collections import deque
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
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

from m0_common import M0Error, REPO_ROOT, load_manifest, parse_timeout
from m4_cdp import unused_loopback_port, wait_for_page_client
from m9_descriptor_snapshot import snapshot_regular_file, snapshot_regular_files
from run_browser_smoke import browser_command, drain_stream, find_browser, stop_browser


SENTINEL = "CHROMIUM_WASM_M8_AUDIO_MANAGER_OUTPUT"
HOST_PROTOCOL = 1
DESCRIPTOR_PROTOCOL = 1
CASE = "m8_audio_manager_output"
SCOPE = (
    "one-default-low-latency-media-audiomanager-output-stream-to-trusted-webaudio-"
    "audioworklet"
)
DEFAULT_MODULE_NAME = "wasm_audio_manager_output_smoke"
DEFAULT_OUT_DIR = Path("out/wasm")
BRIDGE_LIBRARY_PATH = REPO_ROOT / "media" / "audio" / "wasm_audio_bridge.js"
HOST_ROOT = "/__m8_audio_manager_output__"
CAPACITY_FRAMES = 4096
CHANNELS = 2
SAMPLE_RATE = 48000
FRAMES_PER_BUFFER = 480
TOTAL_FRAMES = 12000
START_BUTTON_X = 120.0
START_BUTTON_Y = 48.0
MAX_RESULT_BYTES = 128 * 1024
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024 * 1024
MAX_BROWSER_STDERR_LINES = 300
MAX_COUNTER = 1 << 24
MAX_UNDERRUN_FRAMES = 1 << 22
MAX_UINT32 = (1 << 32) - 1
MODULE_RE = re.compile(r"^[A-Za-z0-9_]+$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_MARKERS = (
    "CHROMIUM_WASM_M8_AUDIO_MANAGER:READY",
    "CHROMIUM_WASM_M8_AUDIO_MANAGER:OPENED",
    "CHROMIUM_WASM_M8_AUDIO_MANAGER:STARTED",
    "CHROMIUM_WASM_M8_AUDIO_MANAGER:DRAINED",
    "CHROMIUM_WASM_M8_AUDIO_MANAGER:STOPPED",
    "CHROMIUM_WASM_M8_AUDIO_MANAGER:CLOSED",
)
FAILURE_STAGES = frozenset(
    {
        "pthread",
        "manager",
        "open",
        "start",
        "drain",
        "stop",
        "shutdown",
    }
)
FAILURE_CLASSES = frozenset(
    {
        "host-exception",
        "host-lifecycle",
        "host-timeout",
        "native-fixed-failure",
        "opaque-output-suppressed",
    }
)
FATAL_TAGS = frozenset(
    {
        "audio-context-close-failed",
        "audio-context-create-failed",
        "audio-context-not-running",
        "audio-context-sample-rate-invalid",
        "bridge-install-failed",
        "cleanup-invalid",
        "descriptor-duplicate",
        "descriptor-invalid",
        "descriptor-unregister-invalid",
        "document-prerequisite",
        "factory-failed",
        "host-exception",
        "marker-before-arm",
        "marker-inactive",
        "marker-native-failure",
        "marker-outside-stderr",
        "marker-unexpected",
        "memory-identity-invalid",
        "native-runtime-abort",
        "native-runtime-exit-invalid",
        "runtime-startup-timeout",
        "trusted-gesture-invalid",
        "worklet-drain-invalid",
        "worklet-protocol-invalid",
    }
)
LIMITATIONS = (
    "proves_only_one_default_low_latency_media_audiomanager_output_stream",
    "proves_only_fixed_0_5_per_stream_gain_for_this_smoke",
    "does_not_prove_audio_service_or_audio_input",
    "does_not_prove_device_change_mute_or_tab_switching_policy",
    "does_not_prove_dynamic_volume_changes_or_multi_stream_gain_mixing",
    "does_not_prove_browser_media_playback_or_global_scheduling",
    "does_not_prove_start_stop_start_or_stream_reuse",
    "does_not_serialize_raw_native_output_exceptions_or_sab_addresses",
    "does_not_claim_m8_2_audio_gate_or_m8_complete_or_normal_outer_browser_shutdown",
)
ARTIFACT_DELIVERY = "immutable-in-memory-server-snapshot"
ARTIFACT_SOURCE_PROVENANCE = "unverified"
BUILD_CONFIG_PROVENANCE = "selected-out-dir-args-gn-immutable-snapshot"
SOURCE_SNAPSHOT_PROVENANCE = (
    "on-disk-byte-snapshots-at-server-startup-not-commit-provenance"
)
VERSION_PROVENANCE = (
    "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance"
)

BYTE_IDENTITY_FIELDS = frozenset(("bytes", "sha256"))
ARTIFACT_FIELDS = frozenset(
    {
        "artifactDelivery",
        "artifactSourceProvenance",
        "buildConfig",
        "buildConfigProvenance",
        "loader",
        "moduleName",
        "wasm",
    }
)
CAPTURE_HARNESS_FIELDS = frozenset(
    {
        "bridgeLibrary",
        "hostHtml",
        "hostJs",
        "runnerSource",
        "sourceSnapshotProvenance",
        "versionProvenance",
        "workletJs",
    }
)
RESULT_FIELDS = frozenset(
    {
        "artifact",
        "audioContextClosed",
        "audioContextRunning",
        "audioManagerOutputPathProven",
        "audioServiceIntegrated",
        "browserMediaPlaybackProven",
        "capacityFrames",
        "case",
        "captureHarness",
        "channels",
        "cleanupComplete",
        "consumedFrames",
        "crossOriginIsolated",
        "descriptorGeneration",
        "descriptorProtocol",
        "descriptorRegistered",
        "descriptorRegistrationCount",
        "descriptorValidated",
        "deviceChangePolicyProven",
        "failureCode",
        "fixedGainPathProven",
        "framesPerBuffer",
        "hostState",
        "inputProven",
        "limitations",
        "m8GateComplete",
        "memoryIdentityChecks",
        "memoryIdentityStable",
        "mutePolicyProven",
        "nativeMarkerSequenceAccepted",
        "nativeMarkerSource",
        "nativeMarkers",
        "normalModuleExitObserved",
        "normalRuntimeShutdownProven",
        "onExitCount",
        "origin",
        "outputArmed",
        "producerError",
        "producedFrames",
        "protocol",
        "resumeRequestedInTrustedGesture",
        "runtimeAborted",
        "runtimeExitCode",
        "runtimeFactorySettled",
        "runtimeInitialized",
        "sampleRate",
        "sameOriginDocument",
        "scope",
        "secureContext",
        "sharedArrayBuffer",
        "startObserved",
        "status",
        "stopObserved",
        "tabSwitchingProven",
        "totalFrames",
        "trustedGesture",
        "underrunFrames",
        "unregisterObserved",
        "versions",
        "workletDisconnected",
        "workletDrained",
        "workletFramesRead",
        "workletNonSilentFrames",
        "workletProgressObserved",
        "workletReady",
        "workletStopRequested",
    }
)
FAILURE_FIELDS = frozenset(
    {
        "case",
        "failureClass",
        "firstFatalTag",
        "lifecycle",
        "nativeFailureStage",
        "protocol",
        "scope",
        "status",
    }
)
FAILURE_LIFECYCLE_FIELDS = frozenset(
    {
        "cleanupComplete",
        "descriptorRegistered",
        "factorySettled",
        "markerCount",
        "normalExitObserved",
        "outputArmed",
        "runtimeInitialized",
        "unregisterObserved",
        "workletDrained",
        "workletReady",
    }
)


class M8AudioManagerOutputServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    args_gn: bytes
    artifacts: dict[str, bytes]
    bridge_library: bytes
    host_html: bytes
    host_js: bytes
    module_name: str
    next_event_order: int
    ready_queue: queue.Queue[dict[str, Any]]
    ready_event_order: int | None
    ready_payload: dict[str, Any] | None
    ready_received: bool
    result_lock: threading.Lock
    result_queue: queue.Queue[dict[str, Any]]
    result_event_order: int | None
    result_payload: dict[str, Any] | None
    result_received: bool
    result_token: str
    runner_source: bytes
    worklet_js: bytes


class M8AudioManagerOutputRequestHandler(BaseHTTPRequestHandler):
    server: M8AudioManagerOutputServer

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
        static_paths = {
            f"{HOST_ROOT}/m8_audio_manager_output_smoke.js": (
                "text/javascript; charset=utf-8",
                self.server.host_js,
            ),
            f"{HOST_ROOT}/m8_audio_manager_output_worklet.js": (
                "text/javascript; charset=utf-8",
                self.server.worklet_js,
            ),
        }
        static = static_paths.get(path)
        if static is not None:
            self._send_bytes(HTTPStatus.OK, static[0], static[1])
            return
        prefix = f"{HOST_ROOT}/artifacts/"
        if path.startswith(prefix):
            artifact_name = path[len(prefix) :]
            artifact = self.server.artifacts.get(artifact_name)
            if artifact is not None:
                content_type = (
                    "application/wasm"
                    if artifact_name.endswith(".wasm")
                    else "text/javascript; charset=utf-8"
                )
                self._send_bytes(HTTPStatus.OK, content_type, artifact)
                return
        self._not_found()

    def _read_json_body(self) -> dict[str, Any] | None:
        try:
            content_length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            content_length = -1
        if content_length < 0 or content_length > MAX_RESULT_BYTES:
            return None
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0]
        if content_type.strip().lower() != "application/json":
            return None
        return parse_json_payload(self.rfile.read(content_length))

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path == f"{HOST_ROOT}/ready/{self.server.result_token}":
            value = self._read_json_body()
            if not is_ready_payload(value):
                self._send_bytes(
                    HTTPStatus.BAD_REQUEST,
                    "text/plain; charset=utf-8",
                    b"invalid ready result\n",
                )
                return
            with self.server.result_lock:
                if self.server.ready_received:
                    self._send_bytes(
                        HTTPStatus.CONFLICT,
                        "text/plain; charset=utf-8",
                        b"duplicate ready result\n",
                    )
                    return
                try:
                    self.server.ready_queue.put_nowait(value)
                except queue.Full:
                    self._send_bytes(
                        HTTPStatus.CONFLICT,
                        "text/plain; charset=utf-8",
                        b"ready queue full\n",
                    )
                    return
                self.server.ready_received = True
                self.server.next_event_order += 1
                self.server.ready_event_order = self.server.next_event_order
                self.server.ready_payload = value
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        if path == f"{HOST_ROOT}/result/{self.server.result_token}":
            value = self._read_json_body()
            if not is_result_payload(value):
                self._send_bytes(
                    HTTPStatus.BAD_REQUEST,
                    "text/plain; charset=utf-8",
                    b"invalid audio output result\n",
                )
                return
            with self.server.result_lock:
                if self.server.result_received:
                    self._send_bytes(
                        HTTPStatus.CONFLICT,
                        "text/plain; charset=utf-8",
                        b"duplicate audio output result\n",
                    )
                    return
                try:
                    self.server.result_queue.put_nowait(value)
                except queue.Full:
                    self._send_bytes(
                        HTTPStatus.CONFLICT,
                        "text/plain; charset=utf-8",
                        b"result queue full\n",
                    )
                    return
                self.server.result_received = True
                self.server.next_event_order += 1
                self.server.result_event_order = self.server.next_event_order
                self.server.result_payload = value
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        self._not_found()


def _reject_duplicate_object_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON object key")
        value[key] = item
    return value


def parse_json_payload(payload: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(
            payload.decode("utf-8"), object_pairs_hook=_reject_duplicate_object_keys
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def parse_result_payload(payload: bytes) -> dict[str, Any] | None:
    value = parse_json_payload(payload)
    return value if is_result_payload(value) else None


def is_result_payload(value: object) -> bool:
    if (
        not isinstance(value, dict)
        or type(value.get("protocol")) is not int
        or value.get("protocol") != HOST_PROTOCOL
        or value.get("case") != CASE
        or value.get("scope") != SCOPE
        or value.get("status") not in {"pass", "fail"}
    ):
        return False
    return True


def is_ready_payload(value: object) -> bool:
    return isinstance(value, dict) and value == {
        "protocol": HOST_PROTOCOL,
        "case": CASE,
        "scope": SCOPE,
        "ready": True,
    }


def _require_module_name(value: object, description: str) -> str:
    if not isinstance(value, str) or not MODULE_RE.fullmatch(value):
        raise M0Error(f"M8 audio output {description} module name is invalid")
    return value


def create_server(
    host: str,
    port: int,
    out_dir: Path,
    token: str,
    ready_queue: queue.Queue[dict[str, Any]],
    result_queue: queue.Queue[dict[str, Any]],
    *,
    module_name: str = DEFAULT_MODULE_NAME,
    host_dir: Path | None = None,
    bridge_library_path: Path | None = None,
    runner_source_path: Path | None = None,
) -> M8AudioManagerOutputServer:
    module_name = _require_module_name(module_name, "server")
    if not TOKEN_RE.fullmatch(token):
        raise M0Error("M8 audio output result token is invalid")
    artifacts = snapshot_regular_files(
        out_dir,
        (f"{module_name}.js", f"{module_name}.wasm"),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="M8 audio output artifacts",
    )
    args_gn = snapshot_regular_file(
        out_dir / "args.gn",
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="M8 audio output selected out-dir args.gn",
    )
    selected_host_dir = host_dir or Path(__file__).with_name("host")
    host_snapshots = snapshot_regular_files(
        selected_host_dir,
        (
            "m8_audio_manager_output_smoke.html",
            "m8_audio_manager_output_smoke.js",
            "m8_audio_manager_output_worklet.js",
        ),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="M8 audio output host resources",
    )
    bridge_library = snapshot_regular_file(
        bridge_library_path
        or BRIDGE_LIBRARY_PATH,
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="M8 audio output bridge library",
    )
    runner_source = snapshot_regular_file(
        runner_source_path or Path(__file__),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="M8 audio output runner source",
    )
    server = M8AudioManagerOutputServer(
        (host, port), M8AudioManagerOutputRequestHandler
    )
    server.args_gn = args_gn
    server.artifacts = artifacts
    server.bridge_library = bridge_library
    server.host_html = host_snapshots["m8_audio_manager_output_smoke.html"]
    server.host_js = host_snapshots["m8_audio_manager_output_smoke.js"]
    server.module_name = module_name
    server.next_event_order = 0
    server.ready_queue = ready_queue
    server.ready_event_order = None
    server.ready_payload = None
    server.ready_received = False
    server.result_lock = threading.Lock()
    server.result_queue = result_queue
    server.result_event_order = None
    server.result_payload = None
    server.result_received = False
    server.result_token = token
    server.runner_source = runner_source
    server.worklet_js = host_snapshots["m8_audio_manager_output_worklet.js"]
    return server


def _byte_identity(contents: bytes) -> dict[str, object]:
    return {"bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}


def artifact_identity(
    server: M8AudioManagerOutputServer, module_name: str
) -> dict[str, object]:
    module_name = _require_module_name(module_name, "artifact")
    if module_name != server.module_name:
        raise M0Error("M8 audio output artifact module does not match server")
    return {
        "artifactDelivery": ARTIFACT_DELIVERY,
        "artifactSourceProvenance": ARTIFACT_SOURCE_PROVENANCE,
        "buildConfig": _byte_identity(server.args_gn),
        "buildConfigProvenance": BUILD_CONFIG_PROVENANCE,
        "loader": _byte_identity(server.artifacts[f"{module_name}.js"]),
        "moduleName": module_name,
        "wasm": _byte_identity(server.artifacts[f"{module_name}.wasm"]),
    }


def capture_harness_identity(server: M8AudioManagerOutputServer) -> dict[str, object]:
    return {
        "bridgeLibrary": _byte_identity(server.bridge_library),
        "hostHtml": _byte_identity(server.host_html),
        "hostJs": _byte_identity(server.host_js),
        "runnerSource": _byte_identity(server.runner_source),
        "sourceSnapshotProvenance": SOURCE_SNAPSHOT_PROVENANCE,
        "versionProvenance": VERSION_PROVENANCE,
        "workletJs": _byte_identity(server.worklet_js),
    }


def toolchain_manifest_versions(manifest: dict[str, Any]) -> dict[str, str]:
    try:
        versions = {
            "chromium": manifest["chromium"]["revision"],
            "v8": manifest["git_dependencies"]["v8"]["revision"],
            "emscripten": manifest["emscripten"]["source_revision"],
        }
    except (KeyError, TypeError) as error:
        raise M0Error("M8 audio output manifest lacks version metadata") from error
    if not all(
        isinstance(value, str) and REVISION_RE.fullmatch(value)
        for value in versions.values()
    ):
        raise M0Error("M8 audio output manifest version metadata is invalid")
    return versions


def smoke_url(
    server: M8AudioManagerOutputServer,
    token: str,
    versions: dict[str, str],
    *,
    artifact: dict[str, object],
    capture_harness: dict[str, object],
    module_name: str,
    timeout_seconds: float,
) -> str:
    module_name = _require_module_name(module_name, "URL")
    if token != server.result_token or module_name != server.module_name:
        raise M0Error("M8 audio output URL does not match server")
    timeout_ms = int(timeout_seconds * 1000)
    if timeout_ms < 1000 or timeout_ms > 120000:
        raise M0Error("M8 audio output URL timeout is invalid")
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "token": token,
            "module": module_name,
            "timeoutMs": str(timeout_ms),
            "versions": json.dumps(versions, sort_keys=True, separators=(",", ":")),
            "artifact": json.dumps(artifact, sort_keys=True, separators=(",", ":")),
            "captureHarness": json.dumps(
                capture_harness, sort_keys=True, separators=(",", ":")
            ),
        }
    )
    return f"http://{host}:{port}{HOST_ROOT}/?{query}"


def _exact_json_equal(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return set(left) == set(right) and all(
            _exact_json_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _exact_json_equal(first, second)
            for first, second in zip(left, right)
        )
    return left == right


def _require_exact_fields(
    value: object, expected: frozenset[str], description: str
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise M0Error(f"M8 audio output {description} schema is invalid")
    return value


def _require_bool(result: dict[str, Any], field: str, expected: bool) -> None:
    if type(result.get(field)) is not bool or result[field] is not expected:
        raise M0Error(f"M8 audio output {field} is invalid")


def _require_integer(
    result: dict[str, Any], field: str, minimum: int, maximum: int
) -> int:
    value = result.get(field)
    if type(value) is not int or value < minimum or value > maximum:
        raise M0Error(f"M8 audio output {field} is invalid")
    return value


def _validate_byte_identity(value: object, expected: dict[str, object]) -> None:
    if not isinstance(value, dict) or set(value) != BYTE_IDENTITY_FIELDS:
        raise M0Error("M8 audio output byte identity is invalid")
    if not _exact_json_equal(value, expected):
        raise M0Error("M8 audio output byte identity differs from snapshot")


def _validate_artifact_identity(value: object, expected: dict[str, object]) -> None:
    result = _require_exact_fields(value, ARTIFACT_FIELDS, "artifact")
    for field in (
        "artifactDelivery",
        "artifactSourceProvenance",
        "buildConfigProvenance",
        "moduleName",
    ):
        if not _exact_json_equal(result.get(field), expected[field]):
            raise M0Error("M8 audio output artifact identity is invalid")
    for field in ("buildConfig", "loader", "wasm"):
        _validate_byte_identity(result.get(field), expected[field])


def _validate_capture_harness_identity(
    value: object, expected: dict[str, object]
) -> None:
    result = _require_exact_fields(value, CAPTURE_HARNESS_FIELDS, "capture harness")
    for field in ("sourceSnapshotProvenance", "versionProvenance"):
        if not _exact_json_equal(result.get(field), expected[field]):
            raise M0Error("M8 audio output capture harness is invalid")
    for field in ("bridgeLibrary", "hostHtml", "hostJs", "runnerSource", "workletJs"):
        _validate_byte_identity(result.get(field), expected[field])


def validate_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
    expected_artifact_identity: dict[str, object],
    expected_capture_harness_identity: dict[str, object],
    expected_origin: str,
) -> None:
    result = _require_exact_fields(result, RESULT_FIELDS, "result")
    for field, expected in {
        "protocol": HOST_PROTOCOL,
        "case": CASE,
        "scope": SCOPE,
        "status": "pass",
        "failureCode": None,
        "descriptorProtocol": DESCRIPTOR_PROTOCOL,
        "capacityFrames": CAPACITY_FRAMES,
        "channels": CHANNELS,
        "sampleRate": SAMPLE_RATE,
        "framesPerBuffer": FRAMES_PER_BUFFER,
        "totalFrames": TOTAL_FRAMES,
        "descriptorRegistrationCount": 1,
        "nativeMarkerSource": "stderr-only",
        "nativeMarkers": list(EXPECTED_MARKERS),
        "runtimeExitCode": 0,
        "onExitCount": 1,
        "producedFrames": TOTAL_FRAMES,
        "consumedFrames": TOTAL_FRAMES,
        "workletFramesRead": TOTAL_FRAMES,
        "workletNonSilentFrames": TOTAL_FRAMES,
        "producerError": 0,
        "hostState": 3,
        "origin": expected_origin,
        "limitations": list(LIMITATIONS),
    }.items():
        if not _exact_json_equal(result.get(field), expected):
            raise M0Error(f"M8 audio output {field} is invalid")
    for field in (
        "secureContext",
        "crossOriginIsolated",
        "sharedArrayBuffer",
        "sameOriginDocument",
        "descriptorRegistered",
        "descriptorValidated",
        "memoryIdentityStable",
        "nativeMarkerSequenceAccepted",
        "runtimeInitialized",
        "runtimeFactorySettled",
        "normalModuleExitObserved",
        "trustedGesture",
        "resumeRequestedInTrustedGesture",
        "audioContextRunning",
        "workletReady",
        "workletProgressObserved",
        "workletDrained",
        "outputArmed",
        "startObserved",
        "stopObserved",
        "unregisterObserved",
        "workletStopRequested",
        "workletDisconnected",
        "audioContextClosed",
        "cleanupComplete",
        "audioManagerOutputPathProven",
        "fixedGainPathProven",
    ):
        _require_bool(result, field, True)
    for field in (
        "runtimeAborted",
        "m8GateComplete",
        "audioServiceIntegrated",
        "inputProven",
        "deviceChangePolicyProven",
        "mutePolicyProven",
        "tabSwitchingProven",
        "browserMediaPlaybackProven",
        "normalRuntimeShutdownProven",
    ):
        _require_bool(result, field, False)
    _require_integer(result, "descriptorGeneration", 1, MAX_UINT32)
    _require_integer(result, "memoryIdentityChecks", 1, MAX_COUNTER)
    _require_integer(result, "underrunFrames", 0, MAX_UNDERRUN_FRAMES)
    versions = _require_exact_fields(result.get("versions"),
                                     frozenset({"chromium", "emscripten", "v8"}),
                                     "versions")
    if not _exact_json_equal(versions, expected_versions):
        raise M0Error("M8 audio output version metadata is invalid")
    _validate_artifact_identity(result.get("artifact"), expected_artifact_identity)
    _validate_capture_harness_identity(
        result.get("captureHarness"), expected_capture_harness_identity
    )


def validate_failed_host_result_summary(value: object) -> dict[str, Any]:
    result = _require_exact_fields(value, FAILURE_FIELDS, "failure result")
    if (
        result.get("protocol") != HOST_PROTOCOL
        or type(result.get("protocol")) is not int
        or result.get("case") != CASE
        or result.get("scope") != SCOPE
        or result.get("status") != "fail"
        or result.get("failureClass") not in FAILURE_CLASSES
        or not (
            result.get("firstFatalTag") is None
            or result.get("firstFatalTag") in FATAL_TAGS
        )
        or not (
            result.get("nativeFailureStage") is None
            or result.get("nativeFailureStage") in FAILURE_STAGES
        )
    ):
        raise M0Error("M8 audio output failure result is invalid")
    lifecycle = _require_exact_fields(
        result.get("lifecycle"), FAILURE_LIFECYCLE_FIELDS, "failure lifecycle"
    )
    for field in FAILURE_LIFECYCLE_FIELDS:
        value = lifecycle.get(field)
        if field == "markerCount":
            if type(value) is not int or value < 0 or value > len(EXPECTED_MARKERS):
                raise M0Error("M8 audio output failure lifecycle is invalid")
        elif type(value) is not bool:
            raise M0Error("M8 audio output failure lifecycle is invalid")
    return {
        "failureClass": result["failureClass"],
        "firstFatalTag": result["firstFatalTag"],
        "nativeFailureStage": result["nativeFailureStage"],
        "lifecycle": {field: lifecycle[field] for field in sorted(lifecycle)},
    }


def _expected_headers(content_type: str) -> dict[str, str]:
    return {
        "cache-control": "no-store",
        "content-type": content_type,
        "cross-origin-embedder-policy": "require-corp",
        "cross-origin-opener-policy": "same-origin",
        "cross-origin-resource-policy": "same-origin",
        "x-content-type-options": "nosniff",
    }


def _stream_response_digest(response: http.client.HTTPResponse) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = response.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        digest.update(chunk)
    return size, digest.hexdigest()


def verify_server_delivery(server: M8AudioManagerOutputServer) -> None:
    expected: tuple[tuple[str, bytes, str], ...] = (
        (f"{HOST_ROOT}/", server.host_html, "text/html"),
        (
            f"{HOST_ROOT}/m8_audio_manager_output_smoke.js",
            server.host_js,
            "text/javascript",
        ),
        (
            f"{HOST_ROOT}/m8_audio_manager_output_worklet.js",
            server.worklet_js,
            "text/javascript",
        ),
        (
            f"{HOST_ROOT}/artifacts/{server.module_name}.js",
            server.artifacts[f"{server.module_name}.js"],
            "text/javascript",
        ),
        (
            f"{HOST_ROOT}/artifacts/{server.module_name}.wasm",
            server.artifacts[f"{server.module_name}.wasm"],
            "application/wasm",
        ),
    )
    host, port = server.server_address[:2]
    for path, contents, content_type in expected:
        connection = http.client.HTTPConnection(host, port, timeout=10)
        try:
            connection.request("GET", path, headers={"Cache-Control": "no-store"})
            response = connection.getresponse()
            if response.status != HTTPStatus.OK:
                raise M0Error("M8 audio output snapshot delivery failed")
            headers = {key.lower(): value for key, value in response.getheaders()}
            for name, expected_value in _expected_headers(content_type).items():
                actual = headers.get(name, "")
                if name == "content-type":
                    actual = actual.split(";", 1)[0].strip().lower()
                if actual != expected_value:
                    raise M0Error("M8 audio output snapshot header is invalid")
            size, digest = _stream_response_digest(response)
            if size != len(contents) or digest != hashlib.sha256(contents).hexdigest():
                raise M0Error("M8 audio output snapshot body changed")
        finally:
            connection.close()


def _wait_for_queue(
    values: queue.Queue[dict[str, Any]],
    browser: subprocess.Popen[str],
    deadline: float,
    stage: str,
    browser_stderr: deque[str],
) -> dict[str, Any]:
    while True:
        try:
            return values.get_nowait()
        except queue.Empty:
            pass
        if browser.poll() is not None:
            raise M0Error(
                "M8 audio output browser exited at "
                f"{stage}; {len(browser_stderr)} stderr lines suppressed"
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M0Error(
                "M8 audio output timed out at "
                f"{stage}; {len(browser_stderr)} stderr lines suppressed"
            )
        time.sleep(min(0.05, remaining))


def _wait_for_ready_or_early_result(
    server: M8AudioManagerOutputServer,
    browser: subprocess.Popen[str],
    deadline: float,
    stage: str,
    browser_stderr: deque[str],
) -> tuple[str, dict[str, Any]]:
    """Wait for host readiness without losing a pre-ready accepted result."""
    while True:
        # Snapshot both HTTP-acceptance events under one lock. Their monotonic
        # orders prevent a result accepted before ready from racing between
        # independent queue polls. A page cannot legitimately complete before
        # the runner has sent its sole trusted click.
        with server.result_lock:
            ready_received = server.ready_received
            ready_order = server.ready_event_order
            ready_payload = server.ready_payload
            result_received = server.result_received
            result_order = server.result_event_order
            result_payload = server.result_payload
        if result_received and (
            not ready_received or result_order is None or ready_order is None or
            result_order < ready_order
        ):
            if result_payload is None:
                raise M0Error("M8 audio output pre-ready result is unavailable")
            return "result", result_payload
        if ready_received:
            if ready_payload is None:
                raise M0Error("M8 audio output ready payload is unavailable")
            return "ready", ready_payload
        if browser.poll() is not None:
            raise M0Error(
                "M8 audio output browser exited at "
                f"{stage}; {len(browser_stderr)} stderr lines suppressed"
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M0Error(
                "M8 audio output timed out at "
                f"{stage}; {len(browser_stderr)} stderr lines suppressed"
            )
        time.sleep(min(0.05, remaining))


def _validate_early_result_before_ready(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("status") != "fail":
        raise M0Error("M8 audio output page result preceded host-ready")
    return validate_failed_host_result_summary(value)


def _dispatch_primary_click_at_result_boundary(
    server: M8AudioManagerOutputServer, client: Any
) -> dict[str, Any] | None:
    """Atomically reject a pre-click result or send the sole trusted click."""
    # Result POST acceptance uses this same lock. Keep it through the
    # synchronous CDP dispatch so an accepted page result cannot land between
    # the ready check and physical click boundary.
    with server.result_lock:
        if server.result_received:
            if server.result_payload is None:
                raise M0Error("M8 audio output pre-click result is unavailable")
            return server.result_payload
        client.dispatch_primary_click(START_BUTTON_X, START_BUTTON_Y)
    return None


def _validate_result_before_trusted_click(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("status") != "fail":
        raise M0Error("M8 audio output page result preceded trusted click")
    return validate_failed_host_result_summary(value)


def write_failure_diagnostics(
    diagnostics_dir: Path,
    *,
    stage: str,
    browser: subprocess.Popen[str] | None,
    browser_stderr: deque[str],
    ready_received: bool,
    page_result_received: bool,
    host_failure_summary: dict[str, Any] | None,
) -> Path:
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / "m8-audio-manager-output-failure.json"
    payload = {
        "schema_version": 1,
        "runner": "run_m8_audio_manager_output_smoke.py",
        "case": CASE,
        "scope": SCOPE,
        "stage": stage,
        "limitations": list(LIMITATIONS),
        "failure": {"type": "details-suppressed"},
        "host_browser": {
            "return_code": browser.poll() if browser is not None else None,
            "stderr_line_count": len(browser_stderr),
            "stderr_suppressed": True,
        },
        "ready_received": ready_received,
        "page_result_received": page_result_received,
        "host_failure_summary": host_failure_summary,
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return path


def _failure_console_reason(summary: dict[str, Any] | None) -> str:
    if summary is None:
        return "details-suppressed"
    if summary["nativeFailureStage"] is not None:
        return "native-fixed-failure"
    return f"host-failure-class={summary['failureClass']}"


def _stop_server(
    server: M8AudioManagerOutputServer | None,
    thread: threading.Thread | None,
    started: bool,
) -> None:
    if server is not None:
        if started:
            server.shutdown()
        server.server_close()
    if started and thread is not None:
        thread.join(timeout=3)
        if thread.is_alive():
            raise M0Error("M8 audio output server did not stop")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one default low-latency AudioManager output stream through WebAudio."
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--module-name", default=DEFAULT_MODULE_NAME)
    parser.add_argument("--diagnostics-dir", type=Path)
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--timeout", type=parse_timeout, default=90.0)
    args = parser.parse_args()
    if args.timeout < 20.0 or args.timeout > 120.0:
        parser.error("--timeout must be between 20 and 120 seconds")

    out_dir = args.out_dir if args.out_dir.is_absolute() else REPO_ROOT / args.out_dir
    diagnostics_dir = args.diagnostics_dir or out_dir / "diagnostics-m8-audio-output"
    if not diagnostics_dir.is_absolute():
        diagnostics_dir = REPO_ROOT / diagnostics_dir
    server: M8AudioManagerOutputServer | None = None
    server_thread: threading.Thread | None = None
    server_started = False
    browser: subprocess.Popen[str] | None = None
    browser_stderr: deque[str] = deque(maxlen=MAX_BROWSER_STDERR_LINES)
    stderr_thread: threading.Thread | None = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    client: Any | None = None
    result: dict[str, Any] | None = None
    successful_result: dict[str, Any] | None = None
    host_failure_summary: dict[str, Any] | None = None
    stage = "check-artifacts"

    try:
        module_name = _require_module_name(args.module_name, "argument")
        for suffix in (".js", ".wasm"):
            if not (out_dir / f"{module_name}{suffix}").is_file():
                raise M0Error("M8 audio output artifact is missing")
        stage = "load-manifest"
        versions = toolchain_manifest_versions(load_manifest())
        stage = "find-browser"
        browser_path, _browser_version = find_browser(args.browser)
        token = secrets.token_urlsafe(24)
        ready_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        result_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        stage = "create-server"
        server = create_server(
            "127.0.0.1", 0, out_dir, token, ready_queue, result_queue,
            module_name=module_name,
        )
        artifact = artifact_identity(server, module_name)
        capture_harness = capture_harness_identity(server)
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m8-audio-manager-output-server",
            daemon=True,
        )
        server_thread.start()
        server_started = True
        stage = "verify-snapshot-delivery"
        verify_server_delivery(server)
        url = smoke_url(
            server,
            token,
            versions,
            artifact=artifact,
            capture_harness=capture_harness,
            module_name=module_name,
            timeout_seconds=max(20.0, args.timeout - 5.0),
        )
        profile = tempfile.TemporaryDirectory(prefix="chromium-wasm-m8-audio-output-")
        debug_port = unused_loopback_port()
        command = browser_command(
            browser_path, profile.name, url, no_sandbox=args.no_sandbox
        )
        command[1:1] = [
            "--remote-allow-origins=http://localhost",
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={debug_port}",
        ]
        stage = "launch-browser"
        browser = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        if browser.stderr is None:
            raise M0Error("M8 audio output browser stderr pipe is unavailable")
        stderr_thread = threading.Thread(
            target=drain_stream,
            args=(browser.stderr, browser_stderr),
            name="chromium-wasm-m8-audio-manager-output-browser-stderr",
            daemon=True,
        )
        stderr_thread.start()
        deadline = time.monotonic() + args.timeout
        stage = "connect-devtools"
        client = wait_for_page_client(debug_port, url.split("?", 1)[0], deadline)
        stage = "wait-host-ready"
        ready_or_result, early_value = _wait_for_ready_or_early_result(
            server, browser, deadline, stage, browser_stderr
        )
        if ready_or_result == "result":
            result = early_value
            stage = "validate-early-failed-host-result-summary"
            host_failure_summary = _validate_early_result_before_ready(result)
            raise M0Error("M8 audio output host reported a fixed failure before ready")
        ready = early_value
        if not is_ready_payload(ready):
            raise M0Error("M8 audio output ready payload is invalid")
        # Physical DevTools input only. No runtime evaluation, synthetic DOM
        # activation, or direct Wasm export initiates AudioContext.resume().
        stage = "trusted-start-click"
        pre_click_result = _dispatch_primary_click_at_result_boundary(
            server, client
        )
        if pre_click_result is not None:
            result = pre_click_result
            stage = "validate-result-before-trusted-click"
            host_failure_summary = _validate_result_before_trusted_click(result)
            raise M0Error("M8 audio output host reported a fixed failure before click")
        stage = "wait-result"
        result = _wait_for_queue(result_queue, browser, deadline, stage, browser_stderr)
        if result.get("status") != "pass":
            stage = "validate-failed-host-result-summary"
            host_failure_summary = validate_failed_host_result_summary(result)
            raise M0Error("M8 audio output host reported a fixed failure")
        stage = "validate-result"
        expected_origin = f"http://{server.server_address[0]}:{server.server_address[1]}"
        validate_result(
            result,
            expected_versions=versions,
            expected_artifact_identity=artifact,
            expected_capture_harness_identity=capture_harness,
            expected_origin=expected_origin,
        )
        stage = "stop-outer-browser-after-clean-native-exit"
        stop_browser(browser)
        if browser.poll() is None:
            raise M0Error("M8 audio output outer browser did not stop")
        successful_result = result
    except (M0Error, OSError, TypeError, ValueError) as error:
        if browser is not None:
            stop_browser(browser)
        if stderr_thread is not None:
            stderr_thread.join(timeout=1)
        try:
            diagnostic = write_failure_diagnostics(
                diagnostics_dir,
                stage=stage,
                browser=browser,
                browser_stderr=browser_stderr,
                ready_received=server.ready_received if server is not None else False,
                page_result_received=result is not None,
                host_failure_summary=host_failure_summary,
            )
            print(
                f"{SENTINEL}:DIAGNOSTICS "
                + json.dumps({"path": str(diagnostic)}, sort_keys=True),
                file=sys.stderr,
            )
        except OSError:
            print(f"{SENTINEL}:DIAGNOSTICS_FAIL", file=sys.stderr)
        print(
            f"{SENTINEL}:FAIL reason={_failure_console_reason(host_failure_summary)}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    finally:
        if client is not None:
            client.close()
        if browser is not None:
            stop_browser(browser)
        if stderr_thread is not None:
            stderr_thread.join(timeout=1)
        try:
            _stop_server(server, server_thread, server_started)
        finally:
            if profile is not None:
                profile.cleanup()

    if successful_result is None:
        raise M0Error("M8 audio output success result was not retained")
    print(
        f"{SENTINEL}:RESULT "
        + json.dumps(successful_result, sort_keys=True, separators=(",", ":")),
        flush=True,
    )
    print(f"{SENTINEL}:PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
