#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the two-fresh-Module Chrome Preferences persistence acceptance.

This runner snapshots the selected loader, Wasm binary, selected output
``args.gn``, host files, and its own source before serving any bytes. The page
creates two distinct ``chrome_wasm_m7_profile_preferences_test`` Modules
sequentially in one document. Chromium owns OPFS,
the profile lease, the registered test preference, and durable cleanup; the
outer host only transports opaque command-line values and checks redacted
native lifecycle markers.

The selected artifacts are built from ``//chrome:chrome_wasm`` in a dedicated
M7 GN output directory with
``enable_chromium_wasm_m7_profile_preferences_test=true`` and an output-name
override. They are not produced by a second production-equivalent GN target.
For the default configuration, generate that directory with:

``buildtools/linux64/gn gen out/wasm-chrome-m7-profile-preferences --args='import("//out/wasm-chrome-m6/args.gn") enable_chromium_wasm_m7_profile_preferences_test=true' --fail-on-unused-args``

then build ``autoninja -C out/wasm-chrome-m7-profile-preferences chrome_wasm``.

The narrow acceptance proves one registered JSON preference survives the
first normal Chrome lifetime and is read during a second fresh Module lifetime.
It deliberately does not claim database recovery, cookies, history, Web
storage, service workers, or concurrent-profile contender semantics.
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
from m9_descriptor_snapshot import snapshot_regular_file, snapshot_regular_files
from run_browser_smoke import browser_command, drain_stream, find_browser, stop_browser


SENTINEL = "CHROMIUM_WASM_M7_CHROME_PROFILE_PREFERENCES_DOM"
CASE = "chrome_profile_preferences_two_fresh_modules_m7"
SCOPE = (
    "same-origin-same-document-two-fresh-chrome-wasm-m7-profile-preferences-test-"
    "modules-preferences-only"
)
PRODUCT_MODULE_NAME = "chrome_wasm_m7_profile_preferences_test"
DEFAULT_MODULE_NAME = PRODUCT_MODULE_NAME
PRODUCT_GN_TARGET = "//chrome:chrome_wasm"
PRODUCT_GN_ENABLE_ARGUMENT = "enable_chromium_wasm_m7_profile_preferences_test=true"
DEFAULT_OUT_DIR = Path("out/wasm-chrome-m7-profile-preferences")
DEFAULT_GN_ARGUMENTS = (
    'import("//out/wasm-chrome-m6/args.gn") '
    + PRODUCT_GN_ENABLE_ARGUMENT
)
BUILD_CONFIG_PROVENANCE = "selected-out-dir-args-gn-immutable-snapshot"
HOST_ROOT = "/__m7_chrome_profile_preferences__"
MAX_RESULT_BYTES = 512 * 1024
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024 * 1024
MAX_OUTPUT_LINES = 128
MAX_BROWSER_STDERR_LINES = 300
FINAL_QUIESCENCE_MS = 50
MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
GIT_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
M7_GN_ENABLE_ASSIGNMENT_RE = re.compile(
    r"^[ \t]*enable_chromium_wasm_m7_profile_preferences_test[ \t]*="
    r"[ \t]*(true|false)[ \t]*(?:#.*)?$",
    re.MULTILINE,
)
M7_MARKER_PREFIX = "CHROMIUM_WASM_M7_PREFS:"
# The M7 private arguments are exact lowercase 64-hex values. Failure
# diagnostics deliberately redact every value with that grammar: a SHA-256
# witness may be hidden there too, but no private value can escape a failed
# run through browser stderr, malformed result JSON, or an exception string.
OPAQUE_TOKEN_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
LIMITATIONS = (
    "proves_only_registered_json_pref_round_trip_across_two_fresh_modules",
    "does_not_prove_sqlite_leveldb_or_database_recovery",
    "does_not_prove_cookies_history_bookmarks_or_sessions",
    "does_not_prove_localstorage_indexeddb_cache_or_service_workers",
    "does_not_prove_concurrent_profile_contender_semantics",
    "does_not_use_host_profile_filesystem_locks_native_calls_or_memory_inspection",
    "does_not_claim_m7_complete_or_m8_feature_compatibility",
)
ARTIFACT_DELIVERY = "immutable-in-memory-server-snapshot"
ARTIFACT_SOURCE_PROVENANCE = "unverified"
SOURCE_SNAPSHOT_PROVENANCE = (
    "on-disk-byte-snapshots-at-server-startup-not-commit-provenance"
)
VERSION_PROVENANCE = (
    "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance"
)

_BYTE_IDENTITY_FIELDS = frozenset(("bytes", "sha256"))
_ARTIFACT_FIELDS = frozenset(
    (
        "artifact_delivery",
        "artifact_source_provenance",
        "build_config",
        "build_config_provenance",
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
_BRIDGE_FIELDS = frozenset(
    (
        "protocol",
        "permanent",
        "frozen",
        "installedBeforeModuleFactory",
        "processExitDispatches",
        "noActiveProcessExitRejected",
        "duplicateProcessExitRejected",
        "lateProcessExitRejected",
        "activeRunAtResult",
    )
)
_TRANSITION_FIELDS = frozenset(
    (
        "runTwoScheduledExactlyOnce",
        "runTwoScheduleMethod",
        "runTwoTimerFired",
        "runTwoScheduledAfterRunOneNativeExit",
        "runTwoScheduledAfterRunOneOnExit",
        "runTwoStartedAfterRunOneActiveClear",
    )
)
_TOKEN_EVIDENCE_FIELDS = frozenset(
    (
        "algorithm",
        "runOne",
        "runTwo",
        "distinct",
        "rawTokensExcluded",
        "rawTokenLeakDetected",
        "rawTokenRedactionCount",
    )
)
_HOST_BOUNDARY_FIELDS = frozenset(
    (
        "hostOpfsAccessAttempted",
        "hostWebLocksAccessAttempted",
        "nativeCallAttempted",
        "wasmDataInspectionAttempted",
    )
)
_RUN_FIELDS = frozenset(
    (
        "abort",
        "activeClearedAfterLifecycle",
        "expectedExitStatusObserved",
        "factoryError",
        "factorySettled",
        "freshModuleObject",
        "leaseReleasedMarkerObserved",
        "markerCount",
        "markerSequenceAccepted",
        "markerSource",
        "markers",
        "mode",
        "moduleIdentity",
        "onExitCount",
        "ordinal",
        "postLifecycleTimerObserved",
        "markerDeliveryCompleteAtProcessExit",
        "processExitBeforeOnExit",
        "processExitCode",
        "processExitCount",
        "runtimeExitCode",
        "runtimeInitialized",
        "sameModuleAsPrior",
        "startKind",
        "stderr",
        "stdout",
    )
)
_FINAL_QUIESCENCE_FIELDS = frozenset(
    (
        "activeRunAtPreUploadCheck",
        "activeRunAtTaskEnd",
        "activeRunAtTaskStart",
        "bridgeRecheckedImmediatelyBeforeUpload",
        "callbacksAtPreUploadCheck",
        "callbacksAtRunTwoActiveClear",
        "callbacksAtTaskEnd",
        "callbacksAtTaskStart",
        "completed",
        "postLifecycleTimerObservedBeforeTask",
        "processExitDispatchesAtPreUploadCheck",
        "processExitReportsAtPreUploadCheck",
        "processExitReportsAtRunTwoActiveClear",
        "processExitReportsAtTaskEnd",
        "quiet",
        "quietWindowMs",
        "rejectedProcessExitReportsAtPreUploadCheck",
        "started",
        "startedAfterRunTwoActiveClear",
        "taskMethod",
        "taskScheduledExactlyOnce",
    )
)
_RESULT_FIELDS = frozenset(
    (
        "protocol",
        "case",
        "scope",
        "status",
        "m7GateComplete",
        "limitations",
        "artifact",
        "capture_harness",
        "versions",
        "origin",
        "crossOriginIsolated",
        "sharedArrayBuffer",
        "sameOriginDocument",
        "preferencesRoundTripProven",
        "sqliteLevelDbRecoveryProven",
        "cookiesHistoryBookmarksSessionsProven",
        "webStorageAndServiceWorkerProven",
        "concurrentProfileContenderProven",
        "factoryCalls",
        "bridge",
        "transition",
        "finalQuiescence",
        "tokenEvidence",
        "hostBoundary",
        "runs",
        "fatalErrors",
        "windowErrors",
        "unhandledRejections",
        "failedChecks",
        "error",
    )
)
_FAILURE_SUMMARY_FIELDS = frozenset(
    (
        "protocol",
        "case",
        "scope",
        "status",
        "failureClass",
        "firstFatalTag",
        "abortReasonKind",
        "abortObservationOrder",
        "nativeFailureStage",
        "lifecycle",
    )
)
_FAILURE_LIFECYCLE_FIELDS = frozenset(
    (
        "acceptedProcessExitCount",
        "activeRunPresent",
        "bridgeInstalled",
        "bridgeInstalledBeforeModuleFactory",
        "callbackCount",
        "factoryCalls",
        "finalQuiescenceCompleted",
        "lastProcessExitCode",
        "lastRuntimeExitCode",
        "leaseReleasedRunCount",
        "onExitCount",
        "processExitReportCount",
        "rawTokenLeakDetected",
        "runCount",
        "unhandledRejectionObserved",
        "windowErrorObserved",
    )
)
_FAILURE_CLASSES = frozenset(
    (
        "host-exception",
        "host-lifecycle",
        "host-window-error",
        "host-unhandled-rejection",
        "host-timeout",
        "opaque-token-leak",
        "native-fixed-failure",
        "host-result-validation",
    )
)
_HOST_FATAL_TAGS = frozenset(
    (
        "abort-invalid",
        "abort-reported",
        "bridge-report-fatal",
        "factory-double-settle",
        "factory-module-mismatch",
        "factory-no-module",
        "factory-rejected",
        "marker-inactive",
        "marker-native-failure",
        "marker-outside-stderr",
        "marker-unexpected",
        "on-exit-invalid",
        "process-exit-duplicate",
        "process-exit-no-active",
        "process-exit-schema",
        "quiescence-activity-before-start",
        "quiescence-completion",
        "quiescence-not-quiet",
        "quiescence-run-two-lifecycle",
        "quiescence-task-scheduling",
        "quiescence-task-start",
        "result-upload-recheck",
        "run-start-invalid",
        "run-two-before-lifecycle",
        "run-two-scheduling",
        "run-two-timer-before-clear",
        "runtime-init-invalid",
        "runtime-module-reused",
        "runtime-run-two-module-reused",
    )
)
_ABORT_REASON_KINDS = frozenset(
    (
        "unreadable",
        "exact-own-data-zero-exit-status",
        "assertion-prefix",
        "native-code-abort",
        "blocking-main-thread",
        "other-primitive-string",
        "primitive-nonstring",
        "nonprimitive",
    )
)
_ABORT_OBSERVATION_ORDERS = frozenset(
    (
        "before-process-exit",
        "after-process-exit-before-onexit",
        "after-onexit",
    )
)
_NATIVE_FAILURE_STAGES = frozenset(
    (
        "arguments",
        "capability",
        "storage",
        "profile",
        "read",
        "fence",
        "lifecycle",
        "content",
        "drain",
    )
)
_FAILURE_COUNT_LIMITS = {
    "acceptedProcessExitCount": 2,
    "callbackCount": 255,
    "factoryCalls": 2,
    "leaseReleasedRunCount": 2,
    "onExitCount": 2,
    "processExitReportCount": 3,
    "runCount": 2,
}
_FAILURE_BOOLEAN_FIELDS = frozenset(
    (
        "activeRunPresent",
        "bridgeInstalled",
        "bridgeInstalledBeforeModuleFactory",
        "finalQuiescenceCompleted",
        "rawTokenLeakDetected",
        "unhandledRejectionObserved",
        "windowErrorObserved",
    )
)
_MAX_FAILURE_EXIT_CODE = 255


class ChromeProfilePreferencesServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    args_gn: bytes
    artifacts: dict[str, bytes]
    host_html: bytes
    host_js: bytes
    module_name: str
    result_lock: threading.Lock
    result_queue: queue.Queue[dict[str, Any]]
    result_received: bool
    result_token: str
    runner_source: bytes


class ChromeProfilePreferencesRequestHandler(BaseHTTPRequestHandler):
    server: ChromeProfilePreferencesServer

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
        if path == f"{HOST_ROOT}/chrome_wasm_profile_persistence_smoke.js":
            self._send_bytes(
                HTTPStatus.OK,
                "text/javascript; charset=utf-8",
                self.server.host_js,
            )
            return
        prefix = f"{HOST_ROOT}/artifacts/"
        if path.startswith(prefix):
            name = path[len(prefix) :]
            artifact = self.server.artifacts.get(name)
            if artifact is not None:
                self._send_bytes(
                    HTTPStatus.OK,
                    "application/wasm"
                    if name.endswith(".wasm")
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
                b"invalid profile Preferences result size\n",
            )
            return
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0]
        if content_type.strip().lower() != "application/json":
            self._send_bytes(
                HTTPStatus.BAD_REQUEST,
                "text/plain; charset=utf-8",
                b"profile Preferences result must be JSON\n",
            )
            return
        result = parse_result_payload(self.rfile.read(length))
        if result is None:
            self._send_bytes(
                HTTPStatus.BAD_REQUEST,
                "text/plain; charset=utf-8",
                b"invalid profile Preferences result\n",
            )
            return
        with self.server.result_lock:
            if self.server.result_received:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"duplicate profile Preferences result\n",
                )
                return
            try:
                self.server.result_queue.put_nowait(result)
            except queue.Full:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"profile Preferences result queue is full\n",
                )
                return
            self.server.result_received = True
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()


def _reject_duplicate_object_keys(
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


def _require_product_module_name(module_name: object, boundary: str) -> str:
    if not isinstance(module_name, str) or not MODULE_NAME_RE.fullmatch(module_name):
        raise M0Error(f"profile Preferences {boundary} module name is invalid")
    if module_name != PRODUCT_MODULE_NAME:
        raise M0Error(
            "profile Preferences "
            f"{boundary} only supports the {PRODUCT_MODULE_NAME} product module"
        )
    return module_name


def validate_m7_output_configuration(args_gn: bytes) -> None:
    """Requires the selected output directory's explicit M7 test opt-in."""

    try:
        text = args_gn.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError as error:
        raise M0Error("profile Preferences args.gn is not UTF-8") from error
    values = M7_GN_ENABLE_ASSIGNMENT_RE.findall(text)
    if not values or any(value != "true" for value in values):
        raise M0Error(
            "profile Preferences selected out-dir args.gn must explicitly set "
            "enable_chromium_wasm_m7_profile_preferences_test=true"
        )


def create_server(
    host: str,
    port: int,
    out_dir: Path,
    token: str,
    result_queue: queue.Queue[dict[str, Any]],
    *,
    module_name: str = DEFAULT_MODULE_NAME,
    host_dir: Path | None = None,
    runner_source_path: Path | None = None,
) -> ChromeProfilePreferencesServer:
    module_name = _require_product_module_name(module_name, "server")
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", token):
        raise M0Error("profile Preferences result token is invalid")
    artifacts = snapshot_regular_files(
        out_dir,
        (f"{module_name}.js", f"{module_name}.wasm"),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="profile Preferences artifacts",
    )
    args_gn = snapshot_regular_file(
        out_dir / "args.gn",
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="profile Preferences selected out-dir args.gn",
    )
    validate_m7_output_configuration(args_gn)
    selected_host_dir = host_dir or Path(__file__).with_name("host")
    host_snapshots = snapshot_regular_files(
        selected_host_dir,
        (
            "chrome_wasm_profile_persistence_smoke.html",
            "chrome_wasm_profile_persistence_smoke.js",
        ),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="profile Preferences host resources",
    )
    runner_source = snapshot_regular_file(
        runner_source_path or Path(__file__),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="profile Preferences runner source",
    )
    server = ChromeProfilePreferencesServer(
        (host, port), ChromeProfilePreferencesRequestHandler
    )
    server.args_gn = args_gn
    server.artifacts = artifacts
    server.host_html = host_snapshots["chrome_wasm_profile_persistence_smoke.html"]
    server.host_js = host_snapshots["chrome_wasm_profile_persistence_smoke.js"]
    server.module_name = module_name
    server.result_lock = threading.Lock()
    server.result_queue = result_queue
    server.result_received = False
    server.result_token = token
    server.runner_source = runner_source
    return server


def _byte_identity(contents: bytes) -> dict[str, object]:
    return {"bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}


def artifact_identity(
    server: ChromeProfilePreferencesServer, *, module_name: str
) -> dict[str, object]:
    module_name = _require_product_module_name(module_name, "artifact")
    _require_product_module_name(server.module_name, "artifact server")
    return {
        "artifact_delivery": ARTIFACT_DELIVERY,
        "artifact_source_provenance": ARTIFACT_SOURCE_PROVENANCE,
        "build_config": _byte_identity(server.args_gn),
        "build_config_provenance": BUILD_CONFIG_PROVENANCE,
        "loader": _byte_identity(server.artifacts[f"{module_name}.js"]),
        "module_name": module_name,
        "wasm": _byte_identity(server.artifacts[f"{module_name}.wasm"]),
    }


def capture_harness_identity(server: ChromeProfilePreferencesServer) -> dict[str, object]:
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
        raise M0Error("profile Preferences manifest lacks version metadata") from error
    if not all(isinstance(value, str) and GIT_REVISION_RE.fullmatch(value)
               for value in versions.values()):
        raise M0Error("profile Preferences manifest version metadata is invalid")
    return versions


def smoke_url(
    server: ChromeProfilePreferencesServer,
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
    if token != server.result_token:
        raise M0Error("profile Preferences URL token does not match its server")
    timeout_ms = int(timeout_seconds * 1000)
    if timeout_ms < 1000 or timeout_ms > 120000:
        raise M0Error("profile Preferences URL timeout is invalid")
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


def _require_exact_fields(
    value: object, expected: frozenset[str], description: str
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        actual = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise M0Error(
            f"profile Preferences {description} schema is invalid: "
            f"expected {sorted(expected)!r}, got {actual!r}"
        )
    return value


def _exact_json_equal(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return set(left) == set(right) and all(
            _exact_json_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _exact_json_equal(first, second) for first, second in zip(left, right)
        )
    return left == right


def _require_equal(result: dict[str, Any], field: str, expected: object) -> None:
    if not _exact_json_equal(result.get(field), expected):
        raise M0Error(
            "profile Preferences result "
            f"{field} mismatch: expected {expected!r}, got {result.get(field)!r}"
        )


def _validate_byte_identity(value: object, description: str) -> None:
    identity = _require_exact_fields(value, _BYTE_IDENTITY_FIELDS, description)
    if type(identity.get("bytes")) is not int or identity["bytes"] < 1:
        raise M0Error(f"profile Preferences {description} byte count is invalid")
    digest = identity.get("sha256")
    if type(digest) is not str or not SHA256_RE.fullmatch(digest):
        raise M0Error(f"profile Preferences {description} SHA-256 is invalid")


def _validate_artifact_identity(
    value: object, expected_identity: dict[str, object]
) -> None:
    artifact = _require_exact_fields(value, _ARTIFACT_FIELDS, "artifact identity")
    if artifact.get("artifact_delivery") != ARTIFACT_DELIVERY:
        raise M0Error("profile Preferences artifact delivery is invalid")
    if artifact.get("artifact_source_provenance") != ARTIFACT_SOURCE_PROVENANCE:
        raise M0Error("profile Preferences artifact provenance is invalid")
    if artifact.get("build_config_provenance") != BUILD_CONFIG_PROVENANCE:
        raise M0Error("profile Preferences build config provenance is invalid")
    _require_product_module_name(artifact.get("module_name"), "artifact")
    for field in ("build_config", "loader", "wasm"):
        _validate_byte_identity(artifact.get(field), f"artifact {field}")
    if not _exact_json_equal(artifact, expected_identity):
        raise M0Error("profile Preferences artifact identity disagrees with snapshot")


def _validate_capture_harness_identity(
    value: object, expected_identity: dict[str, object]
) -> None:
    harness = _require_exact_fields(
        value, _CAPTURE_HARNESS_FIELDS, "capture harness identity"
    )
    if harness.get("source_snapshot_provenance") != SOURCE_SNAPSHOT_PROVENANCE:
        raise M0Error("profile Preferences source snapshot provenance is invalid")
    if harness.get("version_provenance") != VERSION_PROVENANCE:
        raise M0Error("profile Preferences version provenance is invalid")
    for field in ("host_html", "host_js", "runner_source"):
        _validate_byte_identity(harness.get(field), f"capture harness {field}")
    if not _exact_json_equal(harness, expected_identity):
        raise M0Error("profile Preferences capture harness disagrees with snapshot")


def expected_markers(ordinal: int, token_evidence: dict[str, Any]) -> list[str]:
    digest_a = token_evidence["runOne"]
    digest_b = token_evidence["runTwo"]
    if ordinal == 1:
        return [
            f"{M7_MARKER_PREFIX}READY",
            f"{M7_MARKER_PREFIX}WRITE_ACCEPTED sha256={digest_a}",
            f"{M7_MARKER_PREFIX}FENCE_OK sha256={digest_a}",
            f"{M7_MARKER_PREFIX}LEASE_RELEASED",
        ]
    if ordinal == 2:
        return [
            f"{M7_MARKER_PREFIX}READY",
            f"{M7_MARKER_PREFIX}READ_A_OK sha256={digest_a}",
            f"{M7_MARKER_PREFIX}WRITE_ACCEPTED sha256={digest_b}",
            f"{M7_MARKER_PREFIX}FENCE_OK sha256={digest_b}",
            f"{M7_MARKER_PREFIX}LEASE_RELEASED",
        ]
    raise M0Error("profile Preferences run ordinal is invalid")


def _validate_output(value: object, description: str) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_OUTPUT_LINES:
        raise M0Error(f"profile Preferences {description} is invalid")
    if any(type(line) is not str for line in value):
        raise M0Error(f"profile Preferences {description} contains a non-string")
    return value


def _validate_run(run: object, ordinal: int, token_evidence: dict[str, Any]) -> None:
    run = _require_exact_fields(run, _RUN_FIELDS, f"run {ordinal}")
    expected_mode = "write" if ordinal == 1 else "verify-and-write"
    expected_start = "initial" if ordinal == 1 else "setTimeout-0"
    same_module_as_prior = run.get("sameModuleAsPrior")
    same_module_as_prior_is_valid = (
        same_module_as_prior is None
        if ordinal == 1
        else type(same_module_as_prior) is bool and same_module_as_prior is False
    )
    if (
        type(run.get("ordinal")) is not int
        or run["ordinal"] != ordinal
        or run.get("mode") != expected_mode
        or type(run.get("moduleIdentity")) is not str
        or not re.fullmatch(r"[0-9a-f]{32}", run["moduleIdentity"])
        or run.get("freshModuleObject") is not True
        or not same_module_as_prior_is_valid
        or run.get("runtimeInitialized") is not True
        or run.get("factorySettled") is not True
        or run.get("factoryError") is not None
        or run.get("abort") is not None
        or type(run.get("expectedExitStatusObserved")) is not bool
        or type(run.get("runtimeExitCode")) is not int
        or run.get("runtimeExitCode") != 0
        or type(run.get("onExitCount")) is not int
        or run.get("onExitCount") != 1
        or type(run.get("processExitCode")) is not int
        or run.get("processExitCode") != 0
        or type(run.get("processExitCount")) is not int
        or run.get("processExitCount") != 1
        # Native C++ emits the markers before its synchronous exit report, but
        # pthread printErr delivery is asynchronous. This observation records
        # whether delivery had caught up at exit; either boolean is valid.
        or type(run.get("markerDeliveryCompleteAtProcessExit")) is not bool
        or run.get("processExitBeforeOnExit") is not True
        or run.get("markerSource") != "stderr-only"
        or run.get("markerSequenceAccepted") is not True
        or run.get("leaseReleasedMarkerObserved") is not True
        or run.get("activeClearedAfterLifecycle") is not True
        or run.get("postLifecycleTimerObserved") is not True
        or run.get("startKind") != expected_start
    ):
        raise M0Error(f"profile Preferences run {ordinal} lifecycle is invalid")
    expected = expected_markers(ordinal, token_evidence)
    if (
        type(run.get("markerCount")) is not int
        or run.get("markerCount") != len(expected)
        or run.get("markers") != expected
    ):
        raise M0Error(f"profile Preferences run {ordinal} marker sequence is invalid")
    stdout = _validate_output(run.get("stdout"), f"run {ordinal} stdout")
    stderr = _validate_output(run.get("stderr"), f"run {ordinal} stderr")
    if any(M7_MARKER_PREFIX in line for line in stdout):
        raise M0Error(f"profile Preferences run {ordinal} emitted an M7 marker on stdout")
    stderr_markers = [line for line in stderr if line.startswith(M7_MARKER_PREFIX)]
    if stderr_markers != expected:
        raise M0Error(f"profile Preferences run {ordinal} stderr markers are invalid")
    if any(
        M7_MARKER_PREFIX in line and line not in expected for line in stderr
    ):
        raise M0Error(
            f"profile Preferences run {ordinal} emitted an unknown or malformed M7 marker"
        )
    output = stdout + stderr
    if any(
        f"{M7_MARKER_PREFIX}FAIL" in line
        or "--wasm-profile-preferences-token" in line
        or "<redacted>" in line
        for line in output
    ):
        raise M0Error(f"profile Preferences run {ordinal} leaked private data or failed")


def _validate_final_quiescence(value: object, bridge: dict[str, Any]) -> None:
    quiescence = _require_exact_fields(
        value, _FINAL_QUIESCENCE_FIELDS, "final bridge quiescence"
    )
    for field, expected in {
        "taskScheduledExactlyOnce": True,
        "taskMethod": "setTimeout(...,0)",
        "postLifecycleTimerObservedBeforeTask": True,
        "started": True,
        "startedAfterRunTwoActiveClear": True,
        "completed": True,
        "quietWindowMs": FINAL_QUIESCENCE_MS,
        "quiet": True,
        "bridgeRecheckedImmediatelyBeforeUpload": True,
        "activeRunAtTaskStart": None,
        "activeRunAtTaskEnd": None,
        "activeRunAtPreUploadCheck": None,
        "processExitReportsAtRunTwoActiveClear": 2,
        "processExitReportsAtTaskEnd": 2,
        "processExitReportsAtPreUploadCheck": 2,
        "processExitDispatchesAtPreUploadCheck": 2,
        "rejectedProcessExitReportsAtPreUploadCheck": 0,
    }.items():
        if not _exact_json_equal(quiescence.get(field), expected):
            raise M0Error(f"profile Preferences final quiescence {field} is invalid")
    callback_fields = (
        "callbacksAtRunTwoActiveClear",
        "callbacksAtTaskStart",
        "callbacksAtTaskEnd",
        "callbacksAtPreUploadCheck",
    )
    if any(
        type(quiescence.get(field)) is not int or quiescence[field] < 0
        for field in callback_fields
    ):
        raise M0Error("profile Preferences final quiescence callback evidence is invalid")
    if len({quiescence[field] for field in callback_fields}) != 1:
        raise M0Error("profile Preferences final quiescence was not quiet")
    if (
        quiescence["processExitDispatchesAtPreUploadCheck"]
        != bridge["processExitDispatches"]
        or quiescence["rejectedProcessExitReportsAtPreUploadCheck"]
        != bridge["noActiveProcessExitRejected"]
        + bridge["duplicateProcessExitRejected"]
        + bridge["lateProcessExitRejected"]
    ):
        raise M0Error("profile Preferences final quiescence bridge evidence disagrees")


def validate_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
    expected_artifact_identity: dict[str, object],
    expected_capture_harness_identity: dict[str, object],
    expected_origin: str,
) -> None:
    result = _require_exact_fields(result, _RESULT_FIELDS, "result")
    for field, expected in {
        "protocol": 1,
        "case": CASE,
        "scope": SCOPE,
        "status": "pass",
        "m7GateComplete": False,
        "origin": expected_origin,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "sameOriginDocument": True,
        "preferencesRoundTripProven": True,
        "sqliteLevelDbRecoveryProven": False,
        "cookiesHistoryBookmarksSessionsProven": False,
        "webStorageAndServiceWorkerProven": False,
        "concurrentProfileContenderProven": False,
        "factoryCalls": 2,
        "fatalErrors": [],
        "windowErrors": [],
        "unhandledRejections": [],
        "failedChecks": [],
        "error": None,
    }.items():
        _require_equal(result, field, expected)
    _require_equal(result, "limitations", list(LIMITATIONS))
    _require_equal(result, "versions", expected_versions)
    _validate_artifact_identity(result.get("artifact"), expected_artifact_identity)
    _validate_capture_harness_identity(
        result.get("capture_harness"), expected_capture_harness_identity
    )
    bridge = _require_exact_fields(result.get("bridge"), _BRIDGE_FIELDS, "bridge")
    for field, expected in {
        "protocol": 1,
        "permanent": True,
        "frozen": True,
        "installedBeforeModuleFactory": True,
        "processExitDispatches": 2,
        "noActiveProcessExitRejected": 0,
        "duplicateProcessExitRejected": 0,
        "lateProcessExitRejected": 0,
        "activeRunAtResult": None,
    }.items():
        if not _exact_json_equal(bridge.get(field), expected):
            raise M0Error(f"profile Preferences bridge {field} is invalid")
    transition = _require_exact_fields(
        result.get("transition"), _TRANSITION_FIELDS, "two-module transition"
    )
    for field, expected in {
        "runTwoScheduledExactlyOnce": True,
        "runTwoScheduleMethod": "setTimeout(...,0)",
        "runTwoTimerFired": True,
        "runTwoScheduledAfterRunOneNativeExit": True,
        "runTwoScheduledAfterRunOneOnExit": True,
        "runTwoStartedAfterRunOneActiveClear": True,
    }.items():
        if not _exact_json_equal(transition.get(field), expected):
            raise M0Error(f"profile Preferences transition {field} is invalid")
    _validate_final_quiescence(result.get("finalQuiescence"), bridge)
    tokens = _require_exact_fields(
        result.get("tokenEvidence"), _TOKEN_EVIDENCE_FIELDS, "token evidence"
    )
    if (
        tokens.get("algorithm") != "SHA-256"
        or type(tokens.get("runOne")) is not str
        or type(tokens.get("runTwo")) is not str
        or not SHA256_RE.fullmatch(tokens["runOne"])
        or not SHA256_RE.fullmatch(tokens["runTwo"])
        or tokens["runOne"] == tokens["runTwo"]
        or tokens.get("distinct") is not True
        or tokens.get("rawTokensExcluded") is not True
        or tokens.get("rawTokenLeakDetected") is not False
        or type(tokens.get("rawTokenRedactionCount")) is not int
        or tokens.get("rawTokenRedactionCount") != 0
    ):
        raise M0Error("profile Preferences token evidence is invalid")
    boundary = _require_exact_fields(
        result.get("hostBoundary"), _HOST_BOUNDARY_FIELDS, "host boundary"
    )
    if any(value is not False for value in boundary.values()):
        raise M0Error("profile Preferences host crossed a prohibited boundary")
    runs = result.get("runs")
    if not isinstance(runs, list) or len(runs) != 2:
        raise M0Error("profile Preferences result does not contain two runs")
    _validate_run(runs[0], 1, tokens)
    _validate_run(runs[1], 2, tokens)
    if runs[0]["moduleIdentity"] == runs[1]["moduleIdentity"]:
        raise M0Error("profile Preferences result reused a module identity")


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
    byte_count = 0
    while True:
        chunk = response.read(1024 * 1024)
        if not chunk:
            break
        byte_count += len(chunk)
        digest.update(chunk)
    return byte_count, digest.hexdigest()


def verify_server_delivery(server: ChromeProfilePreferencesServer) -> None:
    """Prove every execution input is served from its immutable snapshot."""

    host, port = server.server_address[:2]
    expected: tuple[tuple[str, bytes, str], ...] = (
        (f"{HOST_ROOT}/", server.host_html, "text/html"),
        (
            f"{HOST_ROOT}/chrome_wasm_profile_persistence_smoke.js",
            server.host_js,
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
    for path, contents, content_type in expected:
        connection = http.client.HTTPConnection(host, port, timeout=10)
        try:
            connection.request("GET", path, headers={"Cache-Control": "no-store"})
            response = connection.getresponse()
            if response.status != HTTPStatus.OK:
                raise M0Error(f"profile Preferences snapshot request failed: {path}")
            headers = {key.lower(): value for key, value in response.getheaders()}
            for name, expected_value in _expected_headers(content_type).items():
                actual = headers.get(name, "")
                if name == "content-type":
                    actual = actual.split(";", 1)[0].strip().lower()
                if actual != expected_value:
                    raise M0Error(
                        "profile Preferences snapshot response header is invalid: "
                        f"{path} {name}"
                    )
            byte_count, digest = _stream_response_digest(response)
            if byte_count != len(contents) or digest != hashlib.sha256(contents).hexdigest():
                raise M0Error(f"profile Preferences snapshot body changed: {path}")
        finally:
            connection.close()


def wait_for_result(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    result_queue: queue.Queue[dict[str, Any]],
    deadline: float,
) -> dict[str, Any]:
    """Returns one page result; callers validate success or failure separately."""

    while True:
        try:
            result = result_queue.get_nowait()
        except queue.Empty:
            result = None
        if result is not None:
            return result
        if browser.poll() is not None:
            raise M0Error(
                "host browser exited before profile Preferences result "
                f"({len(browser_stderr)} browser stderr lines suppressed for "
                "opaque-token hygiene)"
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M0Error(
                "profile Preferences smoke timed out "
                f"({len(browser_stderr)} browser stderr lines suppressed for "
                "opaque-token hygiene)"
            )
        time.sleep(min(0.05, remaining))


def validate_failed_host_result_summary(result: object) -> dict[str, Any]:
    """Reconstructs only fixed, structural telemetry from a failed page result."""

    if not isinstance(result, dict) or set(result) != _FAILURE_SUMMARY_FIELDS:
        raise M0Error("profile Preferences failed host result schema is invalid")
    if (
        type(result.get("protocol")) is not int
        or result.get("protocol") != 1
        or result.get("case") != CASE
        or result.get("scope") != SCOPE
        or result.get("status") != "fail"
    ):
        raise M0Error("profile Preferences failed host result identity is invalid")
    failure_class = result.get("failureClass")
    first_fatal_tag = result.get("firstFatalTag")
    abort_reason_kind = result.get("abortReasonKind")
    abort_observation_order = result.get("abortObservationOrder")
    native_failure_stage = result.get("nativeFailureStage")
    if (
        type(failure_class) is not str
        or failure_class not in _FAILURE_CLASSES
        or not (
            first_fatal_tag is None
            or (
                type(first_fatal_tag) is str
                and first_fatal_tag in _HOST_FATAL_TAGS
            )
        )
        or not (
            (abort_reason_kind is None and abort_observation_order is None)
            or (
                type(abort_reason_kind) is str
                and abort_reason_kind in _ABORT_REASON_KINDS
                and type(abort_observation_order) is str
                and abort_observation_order in _ABORT_OBSERVATION_ORDERS
            )
        )
        or not (
            native_failure_stage is None
            or (
                type(native_failure_stage) is str
                and native_failure_stage in _NATIVE_FAILURE_STAGES
            )
        )
        or (failure_class == "native-fixed-failure")
        != (native_failure_stage is not None)
    ):
        raise M0Error("profile Preferences failed host failure class is invalid")
    lifecycle = result.get("lifecycle")
    if not isinstance(lifecycle, dict) or set(lifecycle) != _FAILURE_LIFECYCLE_FIELDS:
        raise M0Error("profile Preferences failed host lifecycle schema is invalid")
    if any(type(lifecycle.get(field)) is not bool for field in _FAILURE_BOOLEAN_FIELDS):
        raise M0Error("profile Preferences failed host lifecycle flags are invalid")
    for field, maximum in _FAILURE_COUNT_LIMITS.items():
        value = lifecycle.get(field)
        if type(value) is not int or value < 0 or value > maximum:
            raise M0Error("profile Preferences failed host lifecycle counts are invalid")
    for field in ("lastProcessExitCode", "lastRuntimeExitCode"):
        value = lifecycle.get(field)
        if value is not None and (
            type(value) is not int or value < 0 or value > _MAX_FAILURE_EXIT_CODE
        ):
            raise M0Error("profile Preferences failed host exit code is invalid")
    return {
        "failureClass": failure_class,
        "firstFatalTag": first_fatal_tag,
        "abortReasonKind": abort_reason_kind,
        "abortObservationOrder": abort_observation_order,
        "nativeFailureStage": native_failure_stage,
        "lifecycle": {
            field: lifecycle[field] for field in sorted(_FAILURE_LIFECYCLE_FIELDS)
        },
    }


def _failure_console_reason(host_failure_summary: dict[str, Any] | None) -> str:
    """Returns only fixed failure labels for stderr output."""

    if host_failure_summary is not None:
        native_failure_stage = host_failure_summary["nativeFailureStage"]
        if native_failure_stage is not None:
            return f"native-fixed-failure stage={native_failure_stage}"
        return f"host-failure-class={host_failure_summary['failureClass']}"
    return "details-suppressed-for-opaque-token-hygiene"


def _redact_diagnostic_value(value: object) -> object:
    """Returns a JSON-safe value that cannot contain an M7 raw token.

    This is intentionally applied only to failure diagnostics. Successful
    evidence retains the native SHA-256 values used to check marker ordering;
    failed runs prefer redaction over differentiating an opaque raw token from
    a digest-shaped value supplied by an untrusted result.
    """

    if isinstance(value, str):
        return OPAQUE_TOKEN_RE.sub("<redacted>", value)
    if isinstance(value, dict):
        return {
            str(_redact_diagnostic_value(key)): _redact_diagnostic_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_diagnostic_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact_diagnostic_value(str(value))


def write_failure_diagnostics(
    diagnostics_dir: Path,
    *,
    stage: str,
    error: Exception,
    browser_path: Path | None,
    browser_version: str | None,
    browser: subprocess.Popen[str] | None,
    browser_stderr: deque[str],
    page_result_received: bool,
    host_failure_summary: dict[str, Any] | None,
) -> Path:
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / "chrome-profile-preferences-m7-failure.json"
    payload = {
        "schema_version": 1,
        "runner": "run_m7_chrome_profile_persistence_dom_smoke.py",
        "case": CASE,
        "scope": SCOPE,
        "stage": stage,
        "limitations": list(LIMITATIONS),
        # Do not serialize arbitrary exception text. A malformed page result
        # could split a raw opaque token across values that ordinary regex
        # redaction would not recognize.
        "failure": {
            "type": type(error).__name__,
            "message": "details-suppressed-for-opaque-token-hygiene",
        },
        "host_browser": {
            "path": str(browser_path) if browser_path is not None else None,
            "version": browser_version,
            "return_code": browser.poll() if browser is not None else None,
            "stderr_line_count": len(browser_stderr),
            "stderr_suppressed_for_opaque_token_hygiene": True,
        },
        # A page result is untrusted. The independently reconstructed summary
        # above is the only page-controlled data that diagnostics may retain.
        "page_result_received": page_result_received,
        "host_failure_summary": host_failure_summary,
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(
            _redact_diagnostic_value(payload), indent=2, sort_keys=True
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def _stop_server(
    server: ChromeProfilePreferencesServer | None,
    server_thread: threading.Thread | None,
    server_thread_started: bool,
) -> None:
    if server is not None:
        if server_thread_started:
            server.shutdown()
        server.server_close()
    if server_thread_started and server_thread is not None:
        server_thread.join(timeout=3)
        if server_thread.is_alive():
            raise M0Error("profile Preferences server did not stop")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run two fresh Chrome Wasm Modules through Preferences persistence.",
        epilog=(
            "Build the default artifacts with: buildtools/linux64/gn gen "
            "out/wasm-chrome-m7-profile-preferences --args='"
            + DEFAULT_GN_ARGUMENTS
            + "' --fail-on-unused-args; autoninja -C "
            "out/wasm-chrome-m7-profile-preferences chrome_wasm"
        ),
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=(
            "dedicated M7 //chrome:chrome_wasm GN output directory; it must "
            f"contain {PRODUCT_MODULE_NAME}.js, {PRODUCT_MODULE_NAME}.wasm, "
            "and an args.gn that explicitly enables "
            "enable_chromium_wasm_m7_profile_preferences_test=true"
        ),
    )
    parser.add_argument("--module-name", default=DEFAULT_MODULE_NAME)
    parser.add_argument("--diagnostics-dir", type=Path)
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--timeout", type=parse_timeout, default=120.0)
    args = parser.parse_args()
    if args.timeout < 20.0:
        parser.error("--timeout must be at least twenty seconds")
    if args.module_name != PRODUCT_MODULE_NAME:
        parser.error(
            "--module-name must be chrome_wasm_m7_profile_preferences_test "
            "for this product smoke"
        )

    out_dir = args.out_dir if args.out_dir.is_absolute() else REPO_ROOT / args.out_dir
    diagnostics_dir = args.diagnostics_dir or out_dir / "diagnostics"
    if not diagnostics_dir.is_absolute():
        diagnostics_dir = REPO_ROOT / diagnostics_dir
    server: ChromeProfilePreferencesServer | None = None
    server_thread: threading.Thread | None = None
    server_thread_started = False
    browser: subprocess.Popen[str] | None = None
    browser_path: Path | None = None
    browser_version: str | None = None
    browser_stderr: deque[str] = deque(maxlen=MAX_BROWSER_STDERR_LINES)
    stderr_thread: threading.Thread | None = None
    outer_profile: tempfile.TemporaryDirectory[str] | None = None
    result: dict[str, Any] | None = None
    host_failure_summary: dict[str, Any] | None = None
    successful_result: dict[str, Any] | None = None
    stage = "check-artifacts"

    try:
        module_name = _require_product_module_name(args.module_name, "argument")
        for suffix in (".js", ".wasm"):
            if not (out_dir / f"{module_name}{suffix}").is_file():
                raise M0Error(
                    "profile Preferences artifact is missing: "
                    f"{module_name}{suffix}; build {PRODUCT_GN_TARGET} with "
                    f"{PRODUCT_GN_ENABLE_ARGUMENT} in the selected M7 output "
                    "directory"
                )
        stage = "load-manifest"
        versions = toolchain_manifest_versions(load_manifest())
        stage = "find-browser"
        browser_path, browser_version = find_browser(args.browser)
        result_token = secrets.token_urlsafe(24)
        result_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        stage = "create-server"
        server = create_server(
            "127.0.0.1", 0, out_dir, result_token, result_queue,
            module_name=module_name,
        )
        artifact = artifact_identity(server, module_name=module_name)
        capture_harness = capture_harness_identity(server)
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m7-profile-preferences-server",
            daemon=True,
        )
        server_thread.start()
        server_thread_started = True
        stage = "verify-snapshot-delivery"
        verify_server_delivery(server)
        url = smoke_url(
            server,
            result_token,
            versions,
            artifact=artifact,
            capture_harness=capture_harness,
            module_name=module_name,
            timeout_seconds=max(20.0, args.timeout - 5.0),
        )
        outer_profile = tempfile.TemporaryDirectory(
            prefix="chromium-wasm-m7-profile-preferences-outer-"
        )
        stage = "launch-browser"
        browser = subprocess.Popen(
            browser_command(
                browser_path, outer_profile.name, url, no_sandbox=args.no_sandbox
            ),
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        browser_stderr_pipe = browser.stderr
        if browser_stderr_pipe is None:
            raise M0Error("profile Preferences browser stderr pipe is unavailable")
        stderr_thread = threading.Thread(
            target=drain_stream,
            args=(browser_stderr_pipe, browser_stderr),
            name="chromium-wasm-m7-profile-preferences-browser-stderr",
            daemon=True,
        )
        stderr_thread.start()
        stage = "wait-for-two-module-result"
        result = wait_for_result(
            browser, browser_stderr, result_queue, time.monotonic() + args.timeout
        )
        if result.get("status") != "pass":
            stage = "validate-failed-host-result-summary"
            host_failure_summary = validate_failed_host_result_summary(result)
            if host_failure_summary["nativeFailureStage"] is not None:
                raise M0Error(
                    "profile Preferences host reported native fixed failure stage="
                    + host_failure_summary["nativeFailureStage"]
                )
            raise M0Error(
                "profile Preferences host reported failure class="
                + host_failure_summary["failureClass"]
            )
        stage = "validate-result"
        expected_origin = f"http://{server.server_address[0]}:{server.server_address[1]}"
        validate_result(
            result,
            expected_versions=versions,
            expected_artifact_identity=artifact,
            expected_capture_harness_identity=capture_harness,
            expected_origin=expected_origin,
        )
        # A result is not accepted until the outer process can be stopped after
        # the page's two inner Module lifecycles have completed. The Chrome
        # browser hosting this test page intentionally remains open otherwise.
        stage = "stop-outer-browser-after-clean-inner-lifecycles"
        stop_browser(browser)
        if browser.poll() is None:
            raise M0Error("profile Preferences outer browser did not stop")
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
                error=error,
                browser_path=browser_path,
                browser_version=browser_version,
                browser=browser,
                browser_stderr=browser_stderr,
                page_result_received=result is not None,
                host_failure_summary=host_failure_summary,
            )
            print(
                f"{SENTINEL}:DIAGNOSTICS "
                + json.dumps(
                    {"path": _redact_diagnostic_value(str(diagnostic))},
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
        except (OSError, TypeError, ValueError) as diagnostic_error:
            print(
                f"{SENTINEL}:DIAGNOSTICS_FAIL "
                f"type={type(diagnostic_error).__name__}",
                file=sys.stderr,
            )
        print(
            f"{SENTINEL}:FAIL reason={_failure_console_reason(host_failure_summary)}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    finally:
        if browser is not None:
            stop_browser(browser)
        if stderr_thread is not None:
            stderr_thread.join(timeout=1)
        try:
            _stop_server(server, server_thread, server_thread_started)
        finally:
            if outer_profile is not None:
                outer_profile.cleanup()

    if successful_result is None:
        raise M0Error("profile Preferences success result was not retained")
    print(
        f"{SENTINEL}:RESULT "
        + json.dumps(successful_result, sort_keys=True, separators=(",", ":")),
        flush=True,
    )
    print(f"{SENTINEL}:PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
