#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the three-fresh-Module Chrome database graceful-close/reopen acceptance.

This runner snapshots the selected loader, Wasm binary, selected output
``args.gn``, host files, and its own source before serving any bytes. The page
creates three distinct ``chrome_wasm_m7_profile_database_test`` Modules
sequentially in one document. Chromium owns OPFS,
the profile lease, bounded SQLite and LevelDB close/reopen work, profile
lifecycle fence, and orderly lifecycle cleanup; the
outer host only transports opaque command-line values and checks redacted
native lifecycle markers.

The selected artifacts are built from ``//chrome:chrome_wasm`` in a dedicated
M7 GN output directory with
``enable_chromium_wasm_m7_profile_database_test=true`` and an output-name
override. They are not produced by a second production-equivalent GN target.
For the default configuration, generate that directory with:

``buildtools/linux64/gn gen out/wasm-chrome-m7-profile-database --args='import("//out/wasm-chrome-m6/args.gn") enable_chromium_wasm_m7_profile_database_test=true' --fail-on-unused-args``

then build ``autoninja -C out/wasm-chrome-m7-profile-database chrome_wasm``.

The narrow acceptance proves SQLite and LevelDB values survive graceful
close/reopen across three fresh Module lifetimes. It deliberately does not
claim crash/interrupted-write recovery, directory/page-reload durability,
preferences, cookies, history, Web storage, service workers, or concurrent
profile contender semantics.

The explicit ``abort-pc`` diagnostic mode selects a distinct, default-off
artifact that reports one fixed native-abort program-counter marker. It is not
an M7 acceptance: the runner retains its nonzero failure result, snapshots the
matching symbol sidecar locally, and writes only bounded structured PC data
plus artifact/config/symbol hashes to failure diagnostics.
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


SENTINEL = "CHROMIUM_WASM_M7_CHROME_PROFILE_DATABASE_DOM"
CASE = "chrome_profile_database_three_fresh_modules_m7"
SCOPE = (
    "same-origin-same-document-three-fresh-chrome-wasm-m7-profile-database-test-"
    "modules-graceful-close-reopen-only"
)
PRODUCT_MODULE_NAME = "chrome_wasm_m7_profile_database_test"
DEFAULT_MODULE_NAME = PRODUCT_MODULE_NAME
ABORT_PC_DIAGNOSTIC_MODULE_NAME = (
    "chrome_wasm_m7_profile_database_abort_pc_diagnostic"
)
PRODUCT_GN_TARGET = "//chrome:chrome_wasm"
PRODUCT_GN_ENABLE_ARGUMENT = "enable_chromium_wasm_m7_profile_database_test=true"
ABORT_PC_DIAGNOSTIC_GN_ENABLE_ARGUMENT = (
    "enable_chromium_wasm_m7_profile_database_abort_pc_diagnostic=true"
)
DEFAULT_OUT_DIR = Path("out/wasm-chrome-m7-profile-database")
DEFAULT_ABORT_PC_DIAGNOSTIC_OUT_DIR = Path(
    "out/wasm-chrome-m7-profile-database-abort-pc"
)
DEFAULT_GN_ARGUMENTS = (
    'import("//out/wasm-chrome-m6/args.gn") '
    + PRODUCT_GN_ENABLE_ARGUMENT
)
DEFAULT_ABORT_PC_DIAGNOSTIC_GN_ARGUMENTS = (
    'import("//out/wasm-chrome-m6/args.gn") '
    + PRODUCT_GN_ENABLE_ARGUMENT
    + " "
    + ABORT_PC_DIAGNOSTIC_GN_ENABLE_ARGUMENT
)
BUILD_CONFIG_PROVENANCE = "selected-out-dir-args-gn-immutable-snapshot"
HOST_ROOT = "/__m7_chrome_profile_database__"
MAX_RESULT_BYTES = 512 * 1024
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024 * 1024
MAX_OUTPUT_LINES = 128
MAX_BROWSER_STDERR_LINES = 300
FINAL_QUIESCENCE_MS = 50
MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
GIT_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
M7_DATABASE_GN_ENABLE_ASSIGNMENT_RE = re.compile(
    r"^[ \t]*enable_chromium_wasm_m7_profile_database_test[ \t]*="
    r"[ \t]*(true|false)[ \t]*(?:#.*)?$",
    re.MULTILINE,
)
M7_DATABASE_ABORT_PC_GN_ENABLE_ASSIGNMENT_RE = re.compile(
    r"^[ \t]*enable_chromium_wasm_m7_profile_database_abort_pc_diagnostic"
    r"[ \t]*=[ \t]*(true|false)[ \t]*(?:#.*)?$",
    re.MULTILINE,
)
M7_DATABASE_SQLITE_RECOVERY_GN_ENABLE_ASSIGNMENT_RE = re.compile(
    r"^[ \t]*enable_chromium_wasm_m7_profile_database_sqlite_recovery_test"
    r"[ \t]*=[ \t]*(true|false)[ \t]*(?:#.*)?$",
    re.MULTILINE,
)
M7_DATABASE_MARKER_PREFIX = "CHROMIUM_WASM_M7_DATABASE:"
# Failure-only fixed database-task telemetry. It is never an acceptance
# marker and successful evidence must not contain its prefix.
M7_DATABASE_PHASE_PREFIX = "CHROMIUM_WASM_M7_DATABASE_PHASE:"
M7_ABORT_PC_PREFIX = "CHROMIUM_WASM_M7_ABORT_PC:"
DIAGNOSTIC_MODE_NORMAL = "normal"
DIAGNOSTIC_MODE_ABORT_PC = "abort-pc"
DIAGNOSTIC_MODES = frozenset((DIAGNOSTIC_MODE_NORMAL, DIAGNOSTIC_MODE_ABORT_PC))
ABORT_PC_CALLER_CALLER_FRAME = "caller-caller"
ABORT_PC_PROVENANCE_MAPPING = (
    "deferred-caller-caller-frame-no-raw-symbol-sidecar-served"
)
FATAL_HEADLINE_PROVENANCE = (
    "fixed-active-stderr-logger-logv-fatal-headline-v1"
)
FATAL_HEADLINE_FAMILIES = frozenset(
    (
        "wasm-time",
        "time-formatting",
        "leveldb",
        "base-file",
        # Reserved enum slots have no v1 raw-output producer. They remain
        # schema-bounded only until a later separately audited protocol adds
        # complete fixed headline literals.
        "base-logging",
        "other-fatal",
        "ambiguous",
    )
)
EXPORTED_FATAL_HEADLINE_FAMILIES = frozenset(
    (
        "wasm-time",
        "time-formatting",
        "leveldb",
        "base-file",
        "ambiguous",
    )
)
MAX_ABORT_PC_FUNCTION_INDEX = 0xFFFFFFFF
ABORT_PC_OFFSET_RE = re.compile(r"^0x(?:0|[1-9a-f][0-9a-f]{0,7})$")
# Emscripten appends this sidecar to the JavaScript target name (rather than
# replacing `.js`) for the non-minimal modularized runtime used by Chrome.
ABORT_PC_SYMBOL_SUFFIX = ".js.symbols"
MAX_ABORT_PC_SYMBOL_SNAPSHOT_BYTES = 1024 * 1024 * 1024
# The M7 private arguments are exact lowercase 64-hex values. Failure
# diagnostics deliberately redact every value with that grammar: a SHA-256
# witness may be hidden there too, but no private value can escape a failed
# run through browser stderr, malformed result JSON, or an exception string.
OPAQUE_TOKEN_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
LIMITATIONS = (
    "proves_only_sqlite_and_leveldb_graceful_close_reopen_across_three_fresh_modules",
    "does_not_prove_sqlite_or_leveldb_crash_or_interrupted_write_recovery",
    "does_not_prove_directory_durability_or_page_reload_durability",
    "does_not_prove_registered_preferences_or_profile_service_persistence",
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
_FATAL_HEADLINE_FIELDS = frozenset(("family", "provenance"))
_ABORT_PC_PROVENANCE_FIELDS = frozenset(
    ("mode", "mapping", "artifact", "args_gn", "symbols")
)
_ABORT_PC_PROVENANCE_ARTIFACT_FIELDS = frozenset(("loader", "wasm"))
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
        "runThreeScheduledExactlyOnce",
        "runThreeScheduleMethod",
        "runThreeTimerFired",
        "runThreeScheduledAfterRunTwoNativeExit",
        "runThreeScheduledAfterRunTwoOnExit",
        "runThreeStartedAfterRunTwoActiveClear",
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
        "callbacksAtRunThreeActiveClear",
        "callbacksAtTaskEnd",
        "callbacksAtTaskStart",
        "completed",
        "postLifecycleTimerObservedBeforeTask",
        "processExitDispatchesAtPreUploadCheck",
        "processExitReportsAtPreUploadCheck",
        "processExitReportsAtRunThreeActiveClear",
        "processExitReportsAtTaskEnd",
        "quiet",
        "quietWindowMs",
        "rejectedProcessExitReportsAtPreUploadCheck",
        "started",
        "startedAfterRunThreeActiveClear",
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
        "sqliteLevelDbGracefulCloseReopenProven",
        "sqliteLevelDbCrashRecoveryProven",
        "directoryDurabilityProven",
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
        "abortPc",
        "fatalHeadline",
        "abortReasonKind",
        "abortObservationOrder",
        "nativeFailureStage",
        "nativeDatabasePhase",
        "preDbImplConstructionObservedBeforeSecondFileExistsPost",
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
        "abort-pc-after-abort",
        "abort-pc-duplicate",
        "abort-pc-inactive",
        "abort-pc-invalid",
        "abort-pc-missing-before-abort",
        "abort-pc-outside-stderr",
        "abort-pc-unexpected",
        "abort-pc-unexpected-clean-exit",
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
        "phase-inactive",
        "phase-outside-stderr",
        "phase-unexpected",
        "process-exit-duplicate",
        "process-exit-no-active",
        "process-exit-schema",
        "quiescence-activity-before-start",
        "quiescence-completion",
        "quiescence-not-quiet",
        "quiescence-run-three-lifecycle",
        "quiescence-task-scheduling",
        "quiescence-task-start",
        "result-upload-recheck",
        "run-start-invalid",
        "run-next-before-lifecycle",
        "run-next-scheduling",
        "run-next-timer-before-clear",
        "runtime-init-invalid",
        "runtime-module-reused",
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
        "database",
        "fence",
        "lifecycle",
        "content",
        "drain",
    )
)
_NATIVE_DATABASE_PHASES = frozenset(
    (
        "task-post",
        "task-started",
        "sqlite-write",
        "sqlite-read",
        "leveldb-write",
        "leveldb-write-open",
        "leveldb-write-pre-dbimpl-construction",
        "leveldb-write-put",
        "leveldb-write-compact",
        "leveldb-write-close",
        "leveldb-write-tracker",
        # FileExists emits bounded call-ordinal pairs. The names intentionally
        # carry no path, result, or other database data.
        "leveldb-write-env-file-exists-first-pre",
        "leveldb-write-env-file-exists-first-post",
        "leveldb-write-env-file-exists-second-pre",
        "leveldb-write-env-file-exists-second-post",
        "leveldb-write-env-file-exists-later-pre",
        "leveldb-write-env-file-exists-later-post",
        "leveldb-write-env-create-dir",
        "leveldb-write-env-rename-file",
        "leveldb-write-env-new-logger",
        # The native diagnostic wrapper exposes only fixed boundaries around
        # its first owner-thread Logv during the active interval, never its
        # formatted logger message.
        "leveldb-write-logger-logv-first-pre",
        "leveldb-write-logger-logv-first-post",
        # The abort-PC artifact's in-process log observer can emit one of
        # these fixed source-family checkpoints. They never carry a path,
        # line, message, or database-success signal.
        "leveldb-write-logger-fatal-source-wasm-time",
        "leveldb-write-logger-fatal-source-time-formatting",
        "leveldb-write-logger-fatal-source-leveldb",
        "leveldb-write-logger-fatal-source-base-file",
        "leveldb-write-env-lock-file",
        "leveldb-write-env-new-writable-file",
        "leveldb-read",
        "leveldb-read-open",
        "leveldb-read-get",
        "leveldb-read-close",
        "task-complete",
    )
)
# These are produced only by the distinct abort-PC artifact's scoped fatal
# observer. They are not ordinary progress phases and must retain the stronger
# failure-only diagnostic receipt below.
_FATAL_SOURCE_DATABASE_PHASES = frozenset(
    (
        "leveldb-write-logger-fatal-source-wasm-time",
        "leveldb-write-logger-fatal-source-time-formatting",
        "leveldb-write-logger-fatal-source-leveldb",
        "leveldb-write-logger-fatal-source-base-file",
    )
)
_FAILURE_COUNT_LIMITS = {
    "acceptedProcessExitCount": 3,
    "callbackCount": 255,
    "factoryCalls": 3,
    "leaseReleasedRunCount": 3,
    "onExitCount": 3,
    "processExitReportCount": 4,
    "runCount": 3,
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


class ChromeProfileDatabaseServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    abort_pc_symbols: bytes | None
    args_gn: bytes
    artifacts: dict[str, bytes]
    diagnostic_mode: str
    host_html: bytes
    host_js: bytes
    module_name: str
    result_lock: threading.Lock
    result_queue: queue.Queue[dict[str, Any]]
    result_received: bool
    result_token: str
    runner_source: bytes


class ChromeProfileDatabaseRequestHandler(BaseHTTPRequestHandler):
    server: ChromeProfileDatabaseServer

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
        if path == f"{HOST_ROOT}/chrome_wasm_profile_database_smoke.js":
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
                b"invalid profile database result size\n",
            )
            return
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0]
        if content_type.strip().lower() != "application/json":
            self._send_bytes(
                HTTPStatus.BAD_REQUEST,
                "text/plain; charset=utf-8",
                b"profile database result must be JSON\n",
            )
            return
        result = parse_result_payload(self.rfile.read(length))
        if result is None:
            self._send_bytes(
                HTTPStatus.BAD_REQUEST,
                "text/plain; charset=utf-8",
                b"invalid profile database result\n",
            )
            return
        with self.server.result_lock:
            if self.server.result_received:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"duplicate profile database result\n",
                )
                return
            try:
                self.server.result_queue.put_nowait(result)
            except queue.Full:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"profile database result queue is full\n",
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


def _require_diagnostic_mode(diagnostic_mode: object, boundary: str) -> str:
    if not isinstance(diagnostic_mode, str) or diagnostic_mode not in DIAGNOSTIC_MODES:
        raise M0Error(f"profile database {boundary} diagnostic mode is invalid")
    return diagnostic_mode


def _module_name_for_diagnostic_mode(diagnostic_mode: str) -> str:
    diagnostic_mode = _require_diagnostic_mode(diagnostic_mode, "module")
    return (
        PRODUCT_MODULE_NAME
        if diagnostic_mode == DIAGNOSTIC_MODE_NORMAL
        else ABORT_PC_DIAGNOSTIC_MODULE_NAME
    )


def _out_dir_for_diagnostic_mode(diagnostic_mode: str) -> Path:
    diagnostic_mode = _require_diagnostic_mode(diagnostic_mode, "output")
    return (
        DEFAULT_OUT_DIR
        if diagnostic_mode == DIAGNOSTIC_MODE_NORMAL
        else DEFAULT_ABORT_PC_DIAGNOSTIC_OUT_DIR
    )


def _require_product_module_name(
    module_name: object,
    boundary: str,
    *,
    diagnostic_mode: str = DIAGNOSTIC_MODE_NORMAL,
) -> str:
    diagnostic_mode = _require_diagnostic_mode(diagnostic_mode, boundary)
    if not isinstance(module_name, str) or not MODULE_NAME_RE.fullmatch(module_name):
        raise M0Error(f"profile database {boundary} module name is invalid")
    expected_module_name = _module_name_for_diagnostic_mode(diagnostic_mode)
    if module_name != expected_module_name:
        raise M0Error(
            "profile database "
            f"{boundary} only supports the {expected_module_name} product module"
        )
    return module_name


def validate_m7_output_configuration(
    args_gn: bytes, *, diagnostic_mode: str = DIAGNOSTIC_MODE_NORMAL
) -> None:
    """Requires the selected output directory's explicit M7 test opt-in."""

    diagnostic_mode = _require_diagnostic_mode(diagnostic_mode, "output")
    try:
        text = args_gn.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError as error:
        raise M0Error("profile database args.gn is not UTF-8") from error
    values = M7_DATABASE_GN_ENABLE_ASSIGNMENT_RE.findall(text)
    if not values or any(value != "true" for value in values):
        raise M0Error(
            "profile database selected out-dir args.gn must explicitly set "
            "enable_chromium_wasm_m7_profile_database_test=true"
        )
    abort_pc_values = M7_DATABASE_ABORT_PC_GN_ENABLE_ASSIGNMENT_RE.findall(text)
    sqlite_recovery_values = (
        M7_DATABASE_SQLITE_RECOVERY_GN_ENABLE_ASSIGNMENT_RE.findall(text)
    )
    if any(value == "true" for value in sqlite_recovery_values):
        raise M0Error(
            "profile database args.gn enables the separate SQLite recovery "
            "artifact"
        )
    if diagnostic_mode == DIAGNOSTIC_MODE_ABORT_PC:
        if not abort_pc_values or any(value != "true" for value in abort_pc_values):
            raise M0Error(
                "profile database abort-PC diagnostic args.gn must explicitly set "
                "enable_chromium_wasm_m7_profile_database_abort_pc_diagnostic=true"
            )
    elif any(value != "false" for value in abort_pc_values):
        raise M0Error(
            "profile database normal M7 args.gn must not enable the abort-PC "
            "diagnostic artifact"
        )


def create_server(
    host: str,
    port: int,
    out_dir: Path,
    token: str,
    result_queue: queue.Queue[dict[str, Any]],
    *,
    module_name: str = DEFAULT_MODULE_NAME,
    diagnostic_mode: str = DIAGNOSTIC_MODE_NORMAL,
    host_dir: Path | None = None,
    runner_source_path: Path | None = None,
) -> ChromeProfileDatabaseServer:
    diagnostic_mode = _require_diagnostic_mode(diagnostic_mode, "server")
    module_name = _require_product_module_name(
        module_name, "server", diagnostic_mode=diagnostic_mode
    )
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", token):
        raise M0Error("profile database result token is invalid")
    artifacts = snapshot_regular_files(
        out_dir,
        (f"{module_name}.js", f"{module_name}.wasm"),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="profile database artifacts",
    )
    args_gn = snapshot_regular_file(
        out_dir / "args.gn",
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="profile database selected out-dir args.gn",
    )
    validate_m7_output_configuration(args_gn, diagnostic_mode=diagnostic_mode)
    abort_pc_symbols = None
    if diagnostic_mode == DIAGNOSTIC_MODE_ABORT_PC:
        # The generated symbol sidecar is evidence for an offline mapping
        # experiment only. It is never a web artifact and never reaches the
        # page, loader, or host result protocol.
        abort_pc_symbols = snapshot_regular_file(
            out_dir / f"{module_name}{ABORT_PC_SYMBOL_SUFFIX}",
            maximum_bytes=MAX_ABORT_PC_SYMBOL_SNAPSHOT_BYTES,
            description="profile database abort-PC symbol sidecar",
        )
    selected_host_dir = host_dir or Path(__file__).with_name("host")
    host_snapshots = snapshot_regular_files(
        selected_host_dir,
        (
            "chrome_wasm_profile_database_smoke.html",
            "chrome_wasm_profile_database_smoke.js",
        ),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="profile database host resources",
    )
    runner_source = snapshot_regular_file(
        runner_source_path or Path(__file__),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="profile database runner source",
    )
    server = ChromeProfileDatabaseServer(
        (host, port), ChromeProfileDatabaseRequestHandler
    )
    server.abort_pc_symbols = abort_pc_symbols
    server.args_gn = args_gn
    server.artifacts = artifacts
    server.diagnostic_mode = diagnostic_mode
    server.host_html = host_snapshots["chrome_wasm_profile_database_smoke.html"]
    server.host_js = host_snapshots["chrome_wasm_profile_database_smoke.js"]
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
    server: ChromeProfileDatabaseServer,
    *,
    module_name: str,
    diagnostic_mode: str = DIAGNOSTIC_MODE_NORMAL,
) -> dict[str, object]:
    diagnostic_mode = _require_diagnostic_mode(diagnostic_mode, "artifact")
    if server.diagnostic_mode != diagnostic_mode:
        raise M0Error("profile database artifact diagnostic mode disagrees with server")
    module_name = _require_product_module_name(
        module_name, "artifact", diagnostic_mode=diagnostic_mode
    )
    _require_product_module_name(
        server.module_name, "artifact server", diagnostic_mode=diagnostic_mode
    )
    return {
        "artifact_delivery": ARTIFACT_DELIVERY,
        "artifact_source_provenance": ARTIFACT_SOURCE_PROVENANCE,
        "build_config": _byte_identity(server.args_gn),
        "build_config_provenance": BUILD_CONFIG_PROVENANCE,
        "loader": _byte_identity(server.artifacts[f"{module_name}.js"]),
        "module_name": module_name,
        "wasm": _byte_identity(server.artifacts[f"{module_name}.wasm"]),
    }


def abort_pc_diagnostic_provenance(
    server: ChromeProfileDatabaseServer, *, module_name: str
) -> dict[str, object]:
    """Returns hashes for an offline abort-PC mapping attempt.

    The raw symbol sidecar remains solely in the runner's in-memory snapshot.
    It is deliberately neither served nor sent to the page. A future mapper
    must opt in separately after it establishes a safe fixed category.
    """

    if server.diagnostic_mode != DIAGNOSTIC_MODE_ABORT_PC:
        raise M0Error("profile database abort-PC provenance requires diagnostic mode")
    module_name = _require_product_module_name(
        module_name, "abort-PC provenance", diagnostic_mode=server.diagnostic_mode
    )
    if server.abort_pc_symbols is None:
        raise M0Error("profile database abort-PC symbol sidecar was not snapshotted")
    return {
        "mode": DIAGNOSTIC_MODE_ABORT_PC,
        "mapping": ABORT_PC_PROVENANCE_MAPPING,
        "artifact": {
            "loader": _byte_identity(server.artifacts[f"{module_name}.js"]),
            "wasm": _byte_identity(server.artifacts[f"{module_name}.wasm"]),
        },
        "args_gn": _byte_identity(server.args_gn),
        "symbols": _byte_identity(server.abort_pc_symbols),
    }


def capture_harness_identity(server: ChromeProfileDatabaseServer) -> dict[str, object]:
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
        raise M0Error("profile database manifest lacks version metadata") from error
    if not all(isinstance(value, str) and GIT_REVISION_RE.fullmatch(value)
               for value in versions.values()):
        raise M0Error("profile database manifest version metadata is invalid")
    return versions


def smoke_url(
    server: ChromeProfileDatabaseServer,
    token: str,
    versions: dict[str, str],
    *,
    artifact: dict[str, object],
    capture_harness: dict[str, object],
    module_name: str,
    timeout_seconds: float,
    diagnostic_mode: str = DIAGNOSTIC_MODE_NORMAL,
) -> str:
    diagnostic_mode = _require_diagnostic_mode(diagnostic_mode, "URL")
    if server.diagnostic_mode != diagnostic_mode:
        raise M0Error("profile database URL diagnostic mode disagrees with server")
    module_name = _require_product_module_name(
        module_name, "URL", diagnostic_mode=diagnostic_mode
    )
    _require_product_module_name(
        server.module_name, "URL server", diagnostic_mode=diagnostic_mode
    )
    if token != server.result_token:
        raise M0Error("profile database URL token does not match its server")
    timeout_ms = int(timeout_seconds * 1000)
    if timeout_ms < 1000 or timeout_ms > 120000:
        raise M0Error("profile database URL timeout is invalid")
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "token": token,
            "module": module_name,
            "timeoutMs": str(timeout_ms),
            "diagnosticMode": diagnostic_mode,
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
            f"profile database {description} schema is invalid: "
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
            "profile database result "
            f"{field} mismatch: expected {expected!r}, got {result.get(field)!r}"
        )


def _validate_byte_identity(value: object, description: str) -> None:
    identity = _require_exact_fields(value, _BYTE_IDENTITY_FIELDS, description)
    if type(identity.get("bytes")) is not int or identity["bytes"] < 1:
        raise M0Error(f"profile database {description} byte count is invalid")
    digest = identity.get("sha256")
    if type(digest) is not str or not SHA256_RE.fullmatch(digest):
        raise M0Error(f"profile database {description} SHA-256 is invalid")


def _validate_artifact_identity(
    value: object, expected_identity: dict[str, object]
) -> None:
    artifact = _require_exact_fields(value, _ARTIFACT_FIELDS, "artifact identity")
    if artifact.get("artifact_delivery") != ARTIFACT_DELIVERY:
        raise M0Error("profile database artifact delivery is invalid")
    if artifact.get("artifact_source_provenance") != ARTIFACT_SOURCE_PROVENANCE:
        raise M0Error("profile database artifact provenance is invalid")
    if artifact.get("build_config_provenance") != BUILD_CONFIG_PROVENANCE:
        raise M0Error("profile database build config provenance is invalid")
    _require_product_module_name(artifact.get("module_name"), "artifact")
    for field in ("build_config", "loader", "wasm"):
        _validate_byte_identity(artifact.get(field), f"artifact {field}")
    if not _exact_json_equal(artifact, expected_identity):
        raise M0Error("profile database artifact identity disagrees with snapshot")


def _validate_capture_harness_identity(
    value: object, expected_identity: dict[str, object]
) -> None:
    harness = _require_exact_fields(
        value, _CAPTURE_HARNESS_FIELDS, "capture harness identity"
    )
    if harness.get("source_snapshot_provenance") != SOURCE_SNAPSHOT_PROVENANCE:
        raise M0Error("profile database source snapshot provenance is invalid")
    if harness.get("version_provenance") != VERSION_PROVENANCE:
        raise M0Error("profile database version provenance is invalid")
    for field in ("host_html", "host_js", "runner_source"):
        _validate_byte_identity(harness.get(field), f"capture harness {field}")
    if not _exact_json_equal(harness, expected_identity):
        raise M0Error("profile database capture harness disagrees with snapshot")


def expected_markers(ordinal: int, token_evidence: dict[str, Any]) -> list[str]:
    # FENCE_OK follows DATABASES_CLOSED as lifecycle sequencing evidence only.
    # It does not claim database, directory, page-reload, or power-loss
    # durability.
    digest_a = token_evidence["runOne"]
    digest_b = token_evidence["runTwo"]
    if ordinal == 1:
        return [
            f"{M7_DATABASE_MARKER_PREFIX}READY",
            f"{M7_DATABASE_MARKER_PREFIX}SQLITE_WRITE_ACCEPTED sha256={digest_a}",
            f"{M7_DATABASE_MARKER_PREFIX}LEVELDB_WRITE_ACCEPTED sha256={digest_a}",
            f"{M7_DATABASE_MARKER_PREFIX}DATABASES_CLOSED sha256={digest_a}",
            f"{M7_DATABASE_MARKER_PREFIX}FENCE_OK sha256={digest_a}",
            f"{M7_DATABASE_MARKER_PREFIX}LEASE_RELEASED",
        ]
    if ordinal == 2:
        return [
            f"{M7_DATABASE_MARKER_PREFIX}READY",
            f"{M7_DATABASE_MARKER_PREFIX}SQLITE_READ_A_OK sha256={digest_a}",
            f"{M7_DATABASE_MARKER_PREFIX}LEVELDB_READ_A_OK sha256={digest_a}",
            f"{M7_DATABASE_MARKER_PREFIX}SQLITE_WRITE_ACCEPTED sha256={digest_b}",
            f"{M7_DATABASE_MARKER_PREFIX}LEVELDB_WRITE_ACCEPTED sha256={digest_b}",
            f"{M7_DATABASE_MARKER_PREFIX}DATABASES_CLOSED sha256={digest_b}",
            f"{M7_DATABASE_MARKER_PREFIX}FENCE_OK sha256={digest_b}",
            f"{M7_DATABASE_MARKER_PREFIX}LEASE_RELEASED",
        ]
    if ordinal == 3:
        return [
            f"{M7_DATABASE_MARKER_PREFIX}READY",
            f"{M7_DATABASE_MARKER_PREFIX}SQLITE_READ_B_OK sha256={digest_b}",
            f"{M7_DATABASE_MARKER_PREFIX}LEVELDB_READ_B_OK sha256={digest_b}",
            f"{M7_DATABASE_MARKER_PREFIX}DATABASES_CLOSED sha256={digest_b}",
            f"{M7_DATABASE_MARKER_PREFIX}FENCE_OK sha256={digest_b}",
            f"{M7_DATABASE_MARKER_PREFIX}LEASE_RELEASED",
        ]
    raise M0Error("profile database run ordinal is invalid")


def _validate_output(value: object, description: str) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_OUTPUT_LINES:
        raise M0Error(f"profile database {description} is invalid")
    if any(type(line) is not str for line in value):
        raise M0Error(f"profile database {description} contains a non-string")
    return value


def _validate_run(run: object, ordinal: int, token_evidence: dict[str, Any]) -> None:
    run = _require_exact_fields(run, _RUN_FIELDS, f"run {ordinal}")
    expected_mode = ("write-a", "verify-a-write-b", "verify-b")[ordinal - 1]
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
        raise M0Error(f"profile database run {ordinal} lifecycle is invalid")
    expected = expected_markers(ordinal, token_evidence)
    if (
        type(run.get("markerCount")) is not int
        or run.get("markerCount") != len(expected)
        or run.get("markers") != expected
    ):
        raise M0Error(f"profile database run {ordinal} marker sequence is invalid")
    stdout = _validate_output(run.get("stdout"), f"run {ordinal} stdout")
    stderr = _validate_output(run.get("stderr"), f"run {ordinal} stderr")
    if any(M7_DATABASE_MARKER_PREFIX in line for line in stdout):
        raise M0Error(f"profile database run {ordinal} emitted an M7 marker on stdout")
    if any(M7_DATABASE_PHASE_PREFIX in line for line in stdout + stderr):
        raise M0Error(
            f"profile database run {ordinal} serialized database phase telemetry"
        )
    if any(M7_ABORT_PC_PREFIX in line for line in stdout + stderr):
        raise M0Error(
            f"profile database run {ordinal} serialized abort-PC telemetry"
        )
    stderr_markers = [line for line in stderr if line.startswith(M7_DATABASE_MARKER_PREFIX)]
    if stderr_markers != expected:
        raise M0Error(f"profile database run {ordinal} stderr markers are invalid")
    if any(
        M7_DATABASE_MARKER_PREFIX in line and line not in expected for line in stderr
    ):
        raise M0Error(
            f"profile database run {ordinal} emitted an unknown or malformed M7 marker"
        )
    output = stdout + stderr
    if any(
        f"{M7_DATABASE_MARKER_PREFIX}FAIL" in line
        or "--wasm-profile-database-token" in line
        or "<redacted>" in line
        for line in output
    ):
        raise M0Error(f"profile database run {ordinal} leaked private data or failed")


def _validate_final_quiescence(value: object, bridge: dict[str, Any]) -> None:
    quiescence = _require_exact_fields(
        value, _FINAL_QUIESCENCE_FIELDS, "final bridge quiescence"
    )
    for field, expected in {
        "taskScheduledExactlyOnce": True,
        "taskMethod": "setTimeout(...,0)",
        "postLifecycleTimerObservedBeforeTask": True,
        "started": True,
        "startedAfterRunThreeActiveClear": True,
        "completed": True,
        "quietWindowMs": FINAL_QUIESCENCE_MS,
        "quiet": True,
        "bridgeRecheckedImmediatelyBeforeUpload": True,
        "activeRunAtTaskStart": None,
        "activeRunAtTaskEnd": None,
        "activeRunAtPreUploadCheck": None,
        "processExitReportsAtRunThreeActiveClear": 3,
        "processExitReportsAtTaskEnd": 3,
        "processExitReportsAtPreUploadCheck": 3,
        "processExitDispatchesAtPreUploadCheck": 3,
        "rejectedProcessExitReportsAtPreUploadCheck": 0,
    }.items():
        if not _exact_json_equal(quiescence.get(field), expected):
            raise M0Error(f"profile database final quiescence {field} is invalid")
    callback_fields = (
        "callbacksAtRunThreeActiveClear",
        "callbacksAtTaskStart",
        "callbacksAtTaskEnd",
        "callbacksAtPreUploadCheck",
    )
    if any(
        type(quiescence.get(field)) is not int or quiescence[field] < 0
        for field in callback_fields
    ):
        raise M0Error("profile database final quiescence callback evidence is invalid")
    if len({quiescence[field] for field in callback_fields}) != 1:
        raise M0Error("profile database final quiescence was not quiet")
    if (
        quiescence["processExitDispatchesAtPreUploadCheck"]
        != bridge["processExitDispatches"]
        or quiescence["rejectedProcessExitReportsAtPreUploadCheck"]
        != bridge["noActiveProcessExitRejected"]
        + bridge["duplicateProcessExitRejected"]
        + bridge["lateProcessExitRejected"]
    ):
        raise M0Error("profile database final quiescence bridge evidence disagrees")


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
        "preferencesRoundTripProven": False,
        "sqliteLevelDbGracefulCloseReopenProven": True,
        "sqliteLevelDbCrashRecoveryProven": False,
        "directoryDurabilityProven": False,
        "cookiesHistoryBookmarksSessionsProven": False,
        "webStorageAndServiceWorkerProven": False,
        "concurrentProfileContenderProven": False,
        "factoryCalls": 3,
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
        "processExitDispatches": 3,
        "noActiveProcessExitRejected": 0,
        "duplicateProcessExitRejected": 0,
        "lateProcessExitRejected": 0,
        "activeRunAtResult": None,
    }.items():
        if not _exact_json_equal(bridge.get(field), expected):
            raise M0Error(f"profile database bridge {field} is invalid")
    transition = _require_exact_fields(
        result.get("transition"), _TRANSITION_FIELDS, "three-module transition"
    )
    for field, expected in {
        "runTwoScheduledExactlyOnce": True,
        "runTwoScheduleMethod": "setTimeout(...,0)",
        "runTwoTimerFired": True,
        "runTwoScheduledAfterRunOneNativeExit": True,
        "runTwoScheduledAfterRunOneOnExit": True,
        "runTwoStartedAfterRunOneActiveClear": True,
        "runThreeScheduledExactlyOnce": True,
        "runThreeScheduleMethod": "setTimeout(...,0)",
        "runThreeTimerFired": True,
        "runThreeScheduledAfterRunTwoNativeExit": True,
        "runThreeScheduledAfterRunTwoOnExit": True,
        "runThreeStartedAfterRunTwoActiveClear": True,
    }.items():
        if not _exact_json_equal(transition.get(field), expected):
            raise M0Error(f"profile database transition {field} is invalid")
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
        raise M0Error("profile database token evidence is invalid")
    boundary = _require_exact_fields(
        result.get("hostBoundary"), _HOST_BOUNDARY_FIELDS, "host boundary"
    )
    if any(value is not False for value in boundary.values()):
        raise M0Error("profile database host crossed a prohibited boundary")
    runs = result.get("runs")
    if not isinstance(runs, list) or len(runs) != 3:
        raise M0Error("profile database result does not contain three runs")
    _validate_run(runs[0], 1, tokens)
    _validate_run(runs[1], 2, tokens)
    _validate_run(runs[2], 3, tokens)
    if len({run["moduleIdentity"] for run in runs}) != 3:
        raise M0Error("profile database result reused a module identity")


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


def verify_server_delivery(server: ChromeProfileDatabaseServer) -> None:
    """Prove every execution input is served from its immutable snapshot."""

    host, port = server.server_address[:2]
    expected: tuple[tuple[str, bytes, str], ...] = (
        (f"{HOST_ROOT}/", server.host_html, "text/html"),
        (
            f"{HOST_ROOT}/chrome_wasm_profile_database_smoke.js",
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
                raise M0Error(f"profile database snapshot request failed: {path}")
            headers = {key.lower(): value for key, value in response.getheaders()}
            for name, expected_value in _expected_headers(content_type).items():
                actual = headers.get(name, "")
                if name == "content-type":
                    actual = actual.split(";", 1)[0].strip().lower()
                if actual != expected_value:
                    raise M0Error(
                        "profile database snapshot response header is invalid: "
                        f"{path} {name}"
                    )
            byte_count, digest = _stream_response_digest(response)
            if byte_count != len(contents) or digest != hashlib.sha256(contents).hexdigest():
                raise M0Error(f"profile database snapshot body changed: {path}")
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
                "host browser exited before profile database result "
                f"({len(browser_stderr)} browser stderr lines suppressed for "
                "opaque-token hygiene)"
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M0Error(
                "profile database smoke timed out "
                f"({len(browser_stderr)} browser stderr lines suppressed for "
                "opaque-token hygiene)"
            )
        time.sleep(min(0.05, remaining))


def _validate_abort_pc_observation(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    observation = _require_exact_fields(
        value, frozenset(("frame", "function", "offset")), "abort-PC observation"
    )
    frame = observation.get("frame")
    function_index = observation.get("function")
    offset = observation.get("offset")
    if (
        frame != ABORT_PC_CALLER_CALLER_FRAME
        or type(frame) is not str
        or type(function_index) is not int
        or function_index < 0
        or function_index > MAX_ABORT_PC_FUNCTION_INDEX
        or type(offset) is not str
        or ABORT_PC_OFFSET_RE.fullmatch(offset) is None
    ):
        raise M0Error("profile database abort-PC observation is invalid")
    return {
        "frame": ABORT_PC_CALLER_CALLER_FRAME,
        "function": function_index,
        "offset": offset,
    }


def _validate_fatal_headline(value: object) -> dict[str, str] | None:
    """Rebuilds fixed fatal-headline provenance without raw output text."""

    if value is None:
        return None
    headline = _require_exact_fields(
        value, _FATAL_HEADLINE_FIELDS, "fatal headline observation"
    )
    family = headline.get("family")
    if (
        type(family) is not str
        or family not in EXPORTED_FATAL_HEADLINE_FAMILIES
        or headline.get("provenance") != FATAL_HEADLINE_PROVENANCE
    ):
        raise M0Error("profile database fatal headline observation is invalid")
    return {
        "family": family,
        "provenance": FATAL_HEADLINE_PROVENANCE,
    }


def validate_failed_host_result_summary(
    result: object, *, diagnostic_mode: str = DIAGNOSTIC_MODE_NORMAL
) -> dict[str, Any]:
    """Reconstructs only fixed, structural telemetry from a failed page result."""

    diagnostic_mode = _require_diagnostic_mode(diagnostic_mode, "failure")
    if not isinstance(result, dict) or set(result) != _FAILURE_SUMMARY_FIELDS:
        raise M0Error("profile database failed host result schema is invalid")
    if (
        type(result.get("protocol")) is not int
        or result.get("protocol") != 1
        or result.get("case") != CASE
        or result.get("scope") != SCOPE
        or result.get("status") != "fail"
    ):
        raise M0Error("profile database failed host result identity is invalid")
    failure_class = result.get("failureClass")
    first_fatal_tag = result.get("firstFatalTag")
    abort_pc = _validate_abort_pc_observation(result.get("abortPc"))
    fatal_headline = _validate_fatal_headline(result.get("fatalHeadline"))
    abort_reason_kind = result.get("abortReasonKind")
    abort_observation_order = result.get("abortObservationOrder")
    native_failure_stage = result.get("nativeFailureStage")
    native_database_phase = result.get("nativeDatabasePhase")
    pre_dbimpl_construction_observed_before_second_file_exists_post = result.get(
        "preDbImplConstructionObservedBeforeSecondFileExistsPost"
    )
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
        or not (
            native_database_phase is None
            or (
                type(native_database_phase) is str
                and native_database_phase in _NATIVE_DATABASE_PHASES
            )
        )
        or not (
            pre_dbimpl_construction_observed_before_second_file_exists_post is None
            or type(pre_dbimpl_construction_observed_before_second_file_exists_post)
            is bool
        )
        or (failure_class == "native-fixed-failure")
        != (native_failure_stage is not None)
    ):
        raise M0Error("profile database failed host failure class is invalid")
    if diagnostic_mode == DIAGNOSTIC_MODE_NORMAL:
        if abort_pc is not None or fatal_headline is not None:
            raise M0Error(
                "profile database normal failure unexpectedly retained diagnostic data"
            )
    elif (
        abort_reason_kind != "native-code-abort"
        or abort_observation_order != "before-process-exit"
        or first_fatal_tag != "abort-reported"
        or fatal_headline is None
    ):
        raise M0Error(
            "profile database abort-PC diagnostic did not observe a valid native "
            "abort and headline receipt"
        )
    if native_database_phase in _FATAL_SOURCE_DATABASE_PHASES:
        if (
            diagnostic_mode != DIAGNOSTIC_MODE_ABORT_PC
            or fatal_headline is None
            or fatal_headline["family"] != "ambiguous"
        ):
            raise M0Error(
                "profile database fatal-source phase lacks its scoped abort-PC "
                "diagnostic receipt"
            )
    lifecycle = result.get("lifecycle")
    if not isinstance(lifecycle, dict) or set(lifecycle) != _FAILURE_LIFECYCLE_FIELDS:
        raise M0Error("profile database failed host lifecycle schema is invalid")
    if any(type(lifecycle.get(field)) is not bool for field in _FAILURE_BOOLEAN_FIELDS):
        raise M0Error("profile database failed host lifecycle flags are invalid")
    for field, maximum in _FAILURE_COUNT_LIMITS.items():
        value = lifecycle.get(field)
        if type(value) is not int or value < 0 or value > maximum:
            raise M0Error("profile database failed host lifecycle counts are invalid")
    for field in ("lastProcessExitCode", "lastRuntimeExitCode"):
        value = lifecycle.get(field)
        if value is not None and (
            type(value) is not int or value < 0 or value > _MAX_FAILURE_EXIT_CODE
        ):
            raise M0Error("profile database failed host exit code is invalid")
    return {
        "failureClass": failure_class,
        "firstFatalTag": first_fatal_tag,
        "abortPc": abort_pc,
        "fatalHeadline": fatal_headline,
        "abortReasonKind": abort_reason_kind,
        "abortObservationOrder": abort_observation_order,
        "nativeFailureStage": native_failure_stage,
        "nativeDatabasePhase": native_database_phase,
        "preDbImplConstructionObservedBeforeSecondFileExistsPost": (
            pre_dbimpl_construction_observed_before_second_file_exists_post
        ),
        "lifecycle": {
            field: lifecycle[field] for field in sorted(_FAILURE_LIFECYCLE_FIELDS)
        },
    }


def reject_diagnostic_clean_result(
    result: object, *, diagnostic_mode: str = DIAGNOSTIC_MODE_NORMAL
) -> None:
    """Rejects a clean page result for the failure-only abort-PC mode."""

    diagnostic_mode = _require_diagnostic_mode(diagnostic_mode, "result")
    if (
        diagnostic_mode == DIAGNOSTIC_MODE_ABORT_PC
        and isinstance(result, dict)
        and result.get("status") == "pass"
    ):
        raise M0Error(
            "profile database abort-PC diagnostic unexpectedly reported status=pass"
        )


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


def _trusted_abort_pc_diagnostic_record(
    provenance: object, host_failure_summary: dict[str, Any] | None
) -> dict[str, object]:
    """Copies the runner-owned abort-PC record after generic redaction.

    The page result is untrusted even when its abort-PC observation passed the
    failure-summary schema.  Conversely, the loader, Wasm, args.gn, and
    sidecar identities are computed by this runner from pinned byte snapshots.
    Keep that deliberately tiny distinction here: generic failure-payload
    redaction stays conservative, while this typed copy retains only the
    independently computed identities, bounded caller-caller-frame/numeric/
    hex-or-null observation, and fixed fatal-headline family/provenance.
    """

    record = _require_exact_fields(
        provenance, _ABORT_PC_PROVENANCE_FIELDS, "abort-PC diagnostic provenance"
    )
    if (
        record.get("mode") != DIAGNOSTIC_MODE_ABORT_PC
        or record.get("mapping") != ABORT_PC_PROVENANCE_MAPPING
    ):
        raise M0Error("profile database abort-PC diagnostic provenance is invalid")
    artifact = _require_exact_fields(
        record.get("artifact"),
        _ABORT_PC_PROVENANCE_ARTIFACT_FIELDS,
        "abort-PC diagnostic artifact provenance",
    )

    def copy_identity(value: object, description: str) -> dict[str, object]:
        identity = _require_exact_fields(value, _BYTE_IDENTITY_FIELDS, description)
        _validate_byte_identity(identity, description)
        return {"bytes": identity["bytes"], "sha256": identity["sha256"]}

    observation = None
    fatal_headline = None
    if host_failure_summary is not None:
        if (
            "abortPc" not in host_failure_summary
            or "fatalHeadline" not in host_failure_summary
        ):
            raise M0Error("profile database abort-PC failure summary is incomplete")
        observation = _validate_abort_pc_observation(host_failure_summary["abortPc"])
        fatal_headline = _validate_fatal_headline(
            host_failure_summary["fatalHeadline"]
        )
    return {
        "mode": DIAGNOSTIC_MODE_ABORT_PC,
        "mapping": ABORT_PC_PROVENANCE_MAPPING,
        "artifact": {
            "loader": copy_identity(
                artifact["loader"], "abort-PC diagnostic loader"
            ),
            "wasm": copy_identity(artifact["wasm"], "abort-PC diagnostic Wasm"),
        },
        "args_gn": copy_identity(record["args_gn"], "abort-PC diagnostic args.gn"),
        "symbols": copy_identity(record["symbols"], "abort-PC diagnostic symbols"),
        "observation": observation,
        # This is rebuilt from the strict host schema after generic redaction.
        # It carries only the fixed family and capture-provenance literal;
        # raw source, line, suffix, message, stack, and token are unavailable.
        "fatal_headline": fatal_headline,
    }


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
    abort_pc_diagnostic_provenance: dict[str, object] | None = None,
) -> Path:
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / "chrome-profile-database-m7-failure.json"
    trusted_abort_pc_diagnostic = (
        None
        if abort_pc_diagnostic_provenance is None
        else _trusted_abort_pc_diagnostic_record(
            abort_pc_diagnostic_provenance, host_failure_summary
        )
    )
    payload = {
        "schema_version": 1,
        "runner": "run_m7_chrome_profile_database_dom_smoke.py",
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
            # A local browser path can disclose a user name or machine layout.
            # Retain only this fixed availability bit in failure diagnostics.
            "path_provided": browser_path is not None,
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
    redacted_payload = _redact_diagnostic_value(payload)
    if trusted_abort_pc_diagnostic is not None:
        # This typed record contains runner-computed byte identities only. The
        # raw .symbols snapshot is deliberately unavailable to the HTTP
        # handler and never written to diagnostics; raw mapping remains an
        # offline follow-up.  Attach it *after* generic redaction so its known
        # SHA-256 witnesses remain useful without making page data less safe.
        assert isinstance(redacted_payload, dict)
        redacted_payload["abort_pc_diagnostic"] = trusted_abort_pc_diagnostic
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(
            redacted_payload, indent=2, sort_keys=True
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def _stop_server(
    server: ChromeProfileDatabaseServer | None,
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
            raise M0Error("profile database server did not stop")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run three fresh Chrome Wasm Modules through database "
            "graceful-close/reopen."
        ),
        epilog=(
            "Build the default artifacts with: buildtools/linux64/gn gen "
            "out/wasm-chrome-m7-profile-database --args='"
            + DEFAULT_GN_ARGUMENTS
            + "' --fail-on-unused-args; autoninja -C "
            "out/wasm-chrome-m7-profile-database chrome_wasm"
            "; for the failure-only abort-PC diagnostic, use out/wasm-chrome-"
            "m7-profile-database-abort-pc with "
            + PRODUCT_GN_ENABLE_ARGUMENT
            + " and "
            + ABORT_PC_DIAGNOSTIC_GN_ENABLE_ARGUMENT
        ),
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument(
        "--diagnostic-mode",
        choices=sorted(DIAGNOSTIC_MODES),
        default=DIAGNOSTIC_MODE_NORMAL,
        help=(
            "normal M7 acceptance (default), or the separate abort-PC failure "
            "diagnostic artifact"
        ),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help=(
            "dedicated M7 //chrome:chrome_wasm GN output directory; defaults "
            "to the directory selected by --diagnostic-mode"
        ),
    )
    parser.add_argument(
        "--module-name",
        default=None,
        help="dedicated module name; defaults to the exact mode-selected artifact",
    )
    parser.add_argument("--diagnostics-dir", type=Path)
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--timeout", type=parse_timeout, default=120.0)
    args = parser.parse_args()
    if args.timeout < 20.0:
        parser.error("--timeout must be at least twenty seconds")
    diagnostic_mode = _require_diagnostic_mode(args.diagnostic_mode, "argument")
    expected_module_name = _module_name_for_diagnostic_mode(diagnostic_mode)
    module_name_argument = args.module_name or expected_module_name
    if module_name_argument != expected_module_name:
        parser.error(
            f"--module-name must be {expected_module_name} for diagnostic mode "
            f"{diagnostic_mode}"
        )

    selected_out_dir = args.out_dir or _out_dir_for_diagnostic_mode(diagnostic_mode)
    out_dir = (
        selected_out_dir
        if selected_out_dir.is_absolute()
        else REPO_ROOT / selected_out_dir
    )
    diagnostics_dir = args.diagnostics_dir or out_dir / "diagnostics"
    if not diagnostics_dir.is_absolute():
        diagnostics_dir = REPO_ROOT / diagnostics_dir
    server: ChromeProfileDatabaseServer | None = None
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
    abort_pc_provenance: dict[str, object] | None = None
    successful_result: dict[str, Any] | None = None
    stage = "check-artifacts"

    try:
        module_name = _require_product_module_name(
            module_name_argument, "argument", diagnostic_mode=diagnostic_mode
        )
        for suffix in (".js", ".wasm"):
            if not (out_dir / f"{module_name}{suffix}").is_file():
                raise M0Error(
                    "profile database artifact is missing: "
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
            diagnostic_mode=diagnostic_mode,
        )
        artifact = artifact_identity(
            server, module_name=module_name, diagnostic_mode=diagnostic_mode
        )
        if diagnostic_mode == DIAGNOSTIC_MODE_ABORT_PC:
            abort_pc_provenance = abort_pc_diagnostic_provenance(
                server, module_name=module_name
            )
        capture_harness = capture_harness_identity(server)
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m7-profile-database-server",
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
            diagnostic_mode=diagnostic_mode,
        )
        outer_profile = tempfile.TemporaryDirectory(
            prefix="chromium-wasm-m7-profile-database-outer-"
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
            raise M0Error("profile database browser stderr pipe is unavailable")
        stderr_thread = threading.Thread(
            target=drain_stream,
            args=(browser_stderr_pipe, browser_stderr),
            name="chromium-wasm-m7-profile-database-browser-stderr",
            daemon=True,
        )
        stderr_thread.start()
        stage = "wait-for-three-module-result"
        result = wait_for_result(
            browser, browser_stderr, result_queue, time.monotonic() + args.timeout
        )
        # The abort-PC artifact is a failure-only diagnostic.  Reject a clean
        # page status explicitly before the ordinary normal-mode success
        # validator can inspect its schema.
        reject_diagnostic_clean_result(result, diagnostic_mode=diagnostic_mode)
        if result.get("status") != "pass":
            stage = "validate-failed-host-result-summary"
            host_failure_summary = validate_failed_host_result_summary(
                result, diagnostic_mode=diagnostic_mode
            )
            if host_failure_summary["nativeFailureStage"] is not None:
                raise M0Error(
                    "profile database host reported native fixed failure stage="
                    + host_failure_summary["nativeFailureStage"]
                )
            raise M0Error(
                "profile database host reported failure class="
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
        # the page's three inner Module lifecycles have completed. The Chrome
        # browser hosting this test page intentionally remains open otherwise.
        stage = "stop-outer-browser-after-clean-inner-lifecycles"
        stop_browser(browser)
        if browser.poll() is None:
            raise M0Error("profile database outer browser did not stop")
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
                abort_pc_diagnostic_provenance=abort_pc_provenance,
            )
            print(
                f"{SENTINEL}:DIAGNOSTICS "
                + json.dumps(
                    {"path": _redact_diagnostic_value(str(diagnostic))},
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
        except (M0Error, OSError, TypeError, ValueError) as diagnostic_error:
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
        raise M0Error("profile database success result was not retained")
    print(
        f"{SENTINEL}:RESULT "
        + json.dumps(successful_result, sort_keys=True, separators=(",", ":")),
        flush=True,
    )
    print(f"{SENTINEL}:PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
