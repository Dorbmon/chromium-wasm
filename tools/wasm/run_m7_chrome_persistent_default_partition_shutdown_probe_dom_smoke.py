#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the narrow live persistent-default-partition shutdown probe.

This runner admits only the fresh source-selected
``chrome_wasm_m7_persistent_default_partition_shutdown_probe`` artifact. It
starts one isolated host document with exactly this native argument:

  --wasm-persistent-default-partition-shutdown-probe=

The host accepts only the fixed stderr sequence ``DEFAULT_PARTITION_CREATED``,
``PROFILE_DIRECTORY_FSYNC_OK``,
``PERSISTENT_LOCAL_STORAGE_ON_DISK_MAP_UPDATE_AND_CLOSE_OK``,
``RENDERER_DEFAULT_PARTITION_CONFIG_REUSE_WITNESS_OK``,
``PERSISTENT_INDEXED_DB_RENDERER_WRITE_AND_CLOSE_OK``,
``PERSISTENT_CACHE_API_RENDERER_WRITE_AND_READBACK_OK``,
``PERSISTENT_CACHE_API_SELECTED_BACKEND_CLOSE_AND_INDEX_REPLACED_OK``,
``PERSISTENT_INDEXED_DB_CONTEXT_CLOSED``,
``PERSISTENT_COOKIE_WRITE_ACCEPTED``,
``PERSISTENT_COOKIE_STORE_FLUSH_ACKNOWLEDGED``,
``PERSISTENT_COOKIE_SQLITE_ROW_READBACK_OK``,
``PERSISTENT_COOKIE_STORE_CLOSED``,
``PARTITION_CREATION_SEALED``,
``LATE_PARTITION_CREATION_REJECTED``,
``PARTITION_DESTROY_NOTIFICATION_DISPATCHED`` (the real default partition's
destruction notification returned), ``PARTITION_MAP_DROPPED`` (an immediate
post-shutdown observation),
``PREFERENCES_FENCE_OK``, the generic sealed/lease-retained
failure-retirement receipt, and
``FAIL_CLOSED_RETIREMENT``. It also requires the native positive nonzero
process-exit import and Emscripten's matching ``onExit`` callback.

This is a LocalStorage-plus-renderer-IndexedDB-plus-Cache-API-operation-plus-
Cookie selected-owner structural shutdown witness. It does not claim a Cache
Storage close/flush, aggregate StoragePartition close, durable profile flush,
a clean profile handoff, fresh-document persistence, crash recovery, or
permanent map absence.

Build the dedicated artifact first:

  buildtools/linux64/gn gen \
      out/wasm-chrome-m7-persistent-default-partition-shutdown-probe \
      --args='import("//out/wasm-chrome-m6/args.gn") \
      enable_chromium_wasm_m7_persistent_default_partition_shutdown_probe=true' \
      --fail-on-unused-args
  autoninja -C out/wasm-chrome-m7-persistent-default-partition-shutdown-probe \
      chrome_wasm
"""

from __future__ import annotations

import argparse
from collections import deque
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import json
import math
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

from m0_common import M0Error, REPO_ROOT, load_manifest
from m9_descriptor_snapshot import snapshot_regular_file, snapshot_regular_files
from run_browser_smoke import browser_command, drain_stream, find_browser, stop_browser


SENTINEL = "CHROMIUM_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE_DOM"
CASE = "chrome_persistent_default_partition_shutdown_probe_m7"
SCOPE = (
    "one-fresh-source-selected-chrome-wasm-persistent-default-partition-"
    "local-storage-map-update-close-renderer-indexed-db-write-close-cache-api-"
    "write-readback-context-close-"
    "cookie-write-flush-sqlite-row-readback-"
    "close-destruction-notification-"
    "return-map-fail-closed-retirement-"
    "observation-only-no-durable-profile-claim"
)
PRODUCT_MODULE_NAME = "chrome_wasm_m7_persistent_default_partition_shutdown_probe"
PRODUCT_GN_TARGET = "//chrome:chrome_wasm"
PRODUCT_GN_ENABLE_ARGUMENT = (
    "enable_chromium_wasm_m7_persistent_default_partition_shutdown_probe=true"
)
DEFAULT_OUT_DIR = Path(
    "out/wasm-chrome-m7-persistent-default-partition-shutdown-probe"
)
DEFAULT_GN_ARGUMENTS = (
    'import("//out/wasm-chrome-m6/args.gn") ' + PRODUCT_GN_ENABLE_ARGUMENT
)
EXACT_EMPTY_PROBE_SWITCH = "--wasm-persistent-default-partition-shutdown-probe="
HOST_ROOT = "/__m7_persistent_default_partition_shutdown_probe__"
HOST_HTML_NAME = "chrome_wasm_persistent_default_partition_shutdown_probe_smoke.html"
HOST_JS_NAME = "chrome_wasm_persistent_default_partition_shutdown_probe_smoke.js"
BUILD_CONFIG_PROVENANCE = "selected-out-dir-args-gn-immutable-snapshot"
ARTIFACT_DELIVERY = "immutable-in-memory-server-snapshot"
ARTIFACT_SOURCE_PROVENANCE = "unverified"
SOURCE_SNAPSHOT_PROVENANCE = (
    "on-disk-byte-snapshots-at-server-startup-not-commit-provenance"
)
VERSION_PROVENANCE = (
    "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance"
)
M7_SHUTDOWN_MARKER_PREFIX = "CHROMIUM_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN:"
M7_SHUTDOWN_FAIL_PREFIX = M7_SHUTDOWN_MARKER_PREFIX + "FAIL stage="
M7_FAILURE_RETIREMENT_PREFIX = "CHROMIUM_WASM_M7_PROFILE_FAILURE_RETIREMENT:"
SEALED_LEASE_RETAINED_MARKER = M7_FAILURE_RETIREMENT_PREFIX + "SEALED_LEASE_RETAINED"
LEASE_RELEASED_MARKER = M7_FAILURE_RETIREMENT_PREFIX + "LEASE_RELEASED"
EXPECTED_MARKERS = (
    M7_SHUTDOWN_MARKER_PREFIX + "DEFAULT_PARTITION_CREATED",
    M7_SHUTDOWN_MARKER_PREFIX + "PROFILE_DIRECTORY_FSYNC_OK",
    M7_SHUTDOWN_MARKER_PREFIX
    + "PERSISTENT_LOCAL_STORAGE_ON_DISK_MAP_UPDATE_AND_CLOSE_OK",
    M7_SHUTDOWN_MARKER_PREFIX
    + "RENDERER_DEFAULT_PARTITION_CONFIG_REUSE_WITNESS_OK",
    M7_SHUTDOWN_MARKER_PREFIX
    + "PERSISTENT_INDEXED_DB_RENDERER_WRITE_AND_CLOSE_OK",
    M7_SHUTDOWN_MARKER_PREFIX
    + "PERSISTENT_CACHE_API_RENDERER_WRITE_AND_READBACK_OK",
    M7_SHUTDOWN_MARKER_PREFIX
    + "PERSISTENT_CACHE_API_SELECTED_BACKEND_CLOSE_AND_INDEX_REPLACED_OK",
    M7_SHUTDOWN_MARKER_PREFIX + "PERSISTENT_INDEXED_DB_CONTEXT_CLOSED",
    M7_SHUTDOWN_MARKER_PREFIX + "PERSISTENT_COOKIE_WRITE_ACCEPTED",
    M7_SHUTDOWN_MARKER_PREFIX + "PERSISTENT_COOKIE_STORE_FLUSH_ACKNOWLEDGED",
    M7_SHUTDOWN_MARKER_PREFIX + "PERSISTENT_COOKIE_SQLITE_ROW_READBACK_OK",
    M7_SHUTDOWN_MARKER_PREFIX + "PERSISTENT_COOKIE_STORE_CLOSED",
    M7_SHUTDOWN_MARKER_PREFIX + "PARTITION_CREATION_SEALED",
    M7_SHUTDOWN_MARKER_PREFIX + "LATE_PARTITION_CREATION_REJECTED",
    M7_SHUTDOWN_MARKER_PREFIX + "PARTITION_DESTROY_NOTIFICATION_DISPATCHED",
    M7_SHUTDOWN_MARKER_PREFIX + "PARTITION_MAP_DROPPED",
    M7_SHUTDOWN_MARKER_PREFIX + "PREFERENCES_FENCE_OK",
    SEALED_LEASE_RETAINED_MARKER,
    M7_SHUTDOWN_MARKER_PREFIX + "FAIL_CLOSED_RETIREMENT",
)

MAX_RESULT_BYTES = 64 * 1024
MAX_ACK_BYTES = 1024
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024 * 1024
MAX_BROWSER_STDERR_LINES = 300
MIN_TIMEOUT_SECONDS = 20.0
MAX_TIMEOUT_MS = 300_000
FINAL_QUIESCENCE_MS = 50

CAPABILITY_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
GIT_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SHUTDOWN_GN_ENABLE_ASSIGNMENT_RE = re.compile(
    r"^[ \t]*enable_chromium_wasm_m7_persistent_default_partition_shutdown_probe"
    r"[ \t]*=[ \t]*(true|false)[ \t]*(?:#.*)?$",
    re.MULTILINE,
)
INCOMPATIBLE_M7_ENABLE_ARGUMENTS = (
    "enable_chromium_wasm_m7_profile_preferences_test",
    "enable_chromium_wasm_m7_profile_database_test",
    "enable_chromium_wasm_m7_default_partition_local_storage_test",
    "enable_chromium_wasm_m7_profile_cookie_local_storage_test",
    "enable_chromium_wasm_m7_profile_cookie_history_local_storage_test",
    "enable_chromium_wasm_m7_profile_bookmark_cookie_history_local_storage_test",
    "enable_chromium_wasm_m7_profile_bookmark_cookie_history_database_local_storage_test",
    "enable_chromium_wasm_m7_profile_indexed_db_test",
    "enable_chromium_wasm_m7_persistent_default_partition_policy_probe",
    "enable_chromium_wasm_m7_normal_profile_fence_failure_diagnostic",
)
INCOMPATIBLE_M7_ENABLE_ASSIGNMENT_RES = tuple(
    re.compile(
        rf"^[ \t]*{re.escape(argument)}[ \t]*=[ \t]*(true|false)"
        r"[ \t]*(?:#.*)?$",
        re.MULTILINE,
    )
    for argument in INCOMPATIBLE_M7_ENABLE_ARGUMENTS
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
_HOST_BOUNDARY_FIELDS = frozenset(
    (
        "hostDomStorageAccessAttempted",
        "hostOpfsAccessAttempted",
        "hostWebLocksAccessAttempted",
        "nativeCallAttempted",
        "wasmDataInspectionAttempted",
    )
)
_RUN_FIELDS = frozenset(
    (
        "arguments",
        "abortObserved",
        "factoryOutcome",
        "factorySettled",
        "freshModuleObject",
        "leaseReleasedMarkerObserved",
        "markerCount",
        "markerSequenceAccepted",
        "markerSource",
        "markers",
        "noFailMarkerObserved",
        "nonzeroProcessExitAndAckReceived",
        "onExitCount",
        "processExitBeforeOnExit",
        "processExitCode",
        "processExitCount",
        "runtimeExitCode",
        "runtimeInitialized",
        "stdoutMarkerCount",
        "unexpectedMarkerObserved",
    )
)
_BRIDGE_FIELDS = frozenset(
    (
        "activeAtResult",
        "duplicateProcessExitRejected",
        "frozen",
        "installedBeforeModuleFactory",
        "noActiveProcessExitRejected",
        "permanent",
        "processExitDispatches",
        "protocol",
    )
)
_QUIESCENCE_FIELDS = frozenset(
    (
        "callbacksAfterQuietWindow",
        "callbacksAtLifecycleComplete",
        "quiet",
        "quietWindowMs",
    )
)
_RESULT_FIELDS = frozenset(
    (
        "actualPersistentDefaultPartitionCreatedProven",
        "aggregatePartitionCloseProven",
        "artifact",
        "bridge",
        "capture_harness",
        "case",
        "crashRecoveryProven",
        "creationSealProven",
        "crossOriginIsolated",
        "durableProfileFlushProven",
        "error",
        "exactEmptyProbeSwitchPassed",
        "failClosedRetirementProven",
        "freshDocumentReloadProven",
        "freshSourceSelectedShutdownArtifactProven",
        "hostBoundary",
        "m7GateComplete",
        "nonzeroProcessExitAndAckProven",
        "partitionDestroyNotificationDispatchedProven",
        "partitionMapDroppedProven",
        "persistentDefaultPartitionCacheAPIWriteAndReadbackReceiptProven",
        "persistentDefaultPartitionCacheAPISelectedBackendCloseAndIndexReplacementReceiptProven",
        "persistentDefaultPartitionCookieSQLiteRowReadbackProven",
        "persistentDefaultPartitionCookieStoreCloseReceiptProven",
        "persistentDefaultPartitionCookieStoreFlushAcknowledgedProven",
        "persistentDefaultPartitionCookieWriteAcceptedProven",
        "persistentDefaultPartitionIndexedDBContextCloseReceiptProven",
        "persistentDefaultPartitionIndexedDBRendererWriteAndCloseReceiptProven",
        "persistentDefaultPartitionLocalStorageMapUpdateAndCloseReceiptProven",
        "persistentDefaultPartitionRendererConfigReuseWitnessProven",
        "preferencesFenceProven",
        "profileDirectoryFsyncProven",
        "profilePersistenceProven",
        "profileStorageLeaseReleasedProven",
        "protocol",
        "quiescence",
        "run",
        "scope",
        "sealedLeaseRetainedReceiptProven",
        "sharedArrayBuffer",
        "status",
        "structuralShutdownWitnessProven",
        "versions",
        "origin",
    )
)
_ACK_FIELDS = frozenset(("case", "protocol", "scope"))


class ProtocolStateError(M0Error):
    """A one-use structural-shutdown receipt state conflict."""


class PersistentDefaultPartitionShutdownProbeSession:
    """Stages one result and releases it only after host acknowledgement."""

    def __init__(self, result_token: str):
        if not CAPABILITY_RE.fullmatch(result_token):
            raise M0Error("structural shutdown result capability is invalid")
        self._result_token = result_token
        self._result: dict[str, Any] | None = None
        self._acknowledged = False
        self._lock = threading.Lock()

    def matches_result_token(self, value: str | None) -> bool:
        return isinstance(value, str) and secrets.compare_digest(
            value, self._result_token
        )

    def stage_result(self, result_token: str, value: dict[str, Any]) -> bool:
        if not self.matches_result_token(result_token):
            return False
        with self._lock:
            if self._result is not None:
                raise ProtocolStateError("structural shutdown result state conflict")
            self._result = value
            return True

    def acknowledge_result(self, result_token: str) -> dict[str, Any] | None:
        if not self.matches_result_token(result_token):
            return None
        with self._lock:
            if self._result is None or self._acknowledged:
                raise ProtocolStateError(
                    "structural shutdown acknowledgement conflict"
                )
            self._acknowledged = True
            return self._result


class PersistentDefaultPartitionShutdownProbeServer(ThreadingHTTPServer):
    """In-memory immutable source-selected shutdown-probe delivery."""


class PersistentDefaultPartitionShutdownProbeRequestHandler(BaseHTTPRequestHandler):
    server: PersistentDefaultPartitionShutdownProbeServer

    def log_message(self, _format: str, *_args: object) -> None:
        # Browser requests are captured only through strict protocol state.
        return

    def _send_headers(self, content_type: str, content_length: int) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(content_length))
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")

    def _send_bytes(
        self, status: HTTPStatus, content_type: str, body: bytes
    ) -> None:
        self.send_response(status)
        self._send_headers(content_type, len(body))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _send_empty(self, status: HTTPStatus) -> None:
        self.send_response(status)
        self._send_headers("text/plain; charset=utf-8", 0)
        self.end_headers()

    def _not_found(self) -> None:
        self._send_bytes(
            HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found\n"
        )

    def _conflict(self) -> None:
        self._send_bytes(
            HTTPStatus.CONFLICT,
            "text/plain; charset=utf-8",
            b"structural shutdown endpoint state conflict\n",
        )

    @staticmethod
    def _result_token_from_path(path: str, endpoint: str) -> str | None:
        prefix = f"{HOST_ROOT}/{endpoint}/"
        if not path.startswith(prefix):
            return None
        token = path[len(prefix) :]
        if "/" in token or not CAPABILITY_RE.fullmatch(token):
            return None
        return token

    def _read_json_body(self, maximum_bytes: int) -> dict[str, Any] | None:
        if self.headers.get("Transfer-Encoding"):
            return None
        length_text = self.headers.get("Content-Length")
        if length_text is None or not re.fullmatch(r"[0-9]+", length_text.strip()):
            return None
        length = int(length_text)
        if length <= 0 or length > maximum_bytes:
            return None
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0]
        if content_type.strip().lower() != "application/json":
            return None
        payload = self.rfile.read(length)
        if len(payload) != length:
            return None
        return _parse_json_object(payload)

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path
        if path in (HOST_ROOT, f"{HOST_ROOT}/"):
            self._send_bytes(
                HTTPStatus.OK, "text/html; charset=utf-8", self.server.host_html
            )
            return
        if parsed.query:
            self._not_found()
            return
        if path == f"{HOST_ROOT}/{HOST_JS_NAME}":
            self._send_bytes(
                HTTPStatus.OK,
                "text/javascript; charset=utf-8",
                self.server.host_js,
            )
            return
        artifact_prefix = f"{HOST_ROOT}/artifacts/"
        if path.startswith(artifact_prefix):
            name = path[len(artifact_prefix) :]
            artifact = self.server.artifacts.get(name)
            if artifact is not None and "/" not in name:
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
        parsed = urlsplit(self.path)
        if parsed.query:
            self._not_found()
            return
        result_token = self._result_token_from_path(parsed.path, "result")
        if result_token is not None:
            self._post_result(result_token)
            return
        acknowledgement_token = self._result_token_from_path(parsed.path, "ack")
        if acknowledgement_token is not None:
            self._post_acknowledgement(acknowledgement_token)
            return
        self._not_found()

    def _post_result(self, result_token: str) -> None:
        value = self._read_json_body(MAX_RESULT_BYTES)
        if (
            value is None
            or value.get("protocol") != 1
            or value.get("case") != CASE
            or value.get("scope") != SCOPE
        ):
            self._send_bytes(
                HTTPStatus.BAD_REQUEST,
                "text/plain; charset=utf-8",
                b"invalid structural shutdown result\n",
            )
            return
        try:
            accepted = self.server.session.stage_result(result_token, value)
        except ProtocolStateError:
            self._conflict()
            return
        if not accepted:
            self._not_found()
            return
        self._send_empty(HTTPStatus.NO_CONTENT)
        try:
            self.wfile.flush()
        except OSError:
            return

    def _post_acknowledgement(self, result_token: str) -> None:
        value = self._read_json_body(MAX_ACK_BYTES)
        if (
            value is None
            or set(value) != _ACK_FIELDS
            or value.get("protocol") != 1
            or value.get("case") != CASE
            or value.get("scope") != SCOPE
        ):
            self._send_bytes(
                HTTPStatus.BAD_REQUEST,
                "text/plain; charset=utf-8",
                b"invalid structural shutdown acknowledgement\n",
            )
            return
        try:
            result = self.server.session.acknowledge_result(result_token)
        except ProtocolStateError:
            self._conflict()
            return
        if result is None:
            self._not_found()
            return
        self._send_empty(HTTPStatus.NO_CONTENT)
        try:
            self.wfile.flush()
        except OSError:
            return
        try:
            self.server.result_queue.put_nowait(result)
        except queue.Full:
            return


def _reject_duplicate_object_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON constant")


def _parse_json_object(payload: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_object_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _require_product_module_name(module_name: object, boundary: str) -> str:
    if not isinstance(module_name, str) or module_name != PRODUCT_MODULE_NAME:
        raise M0Error(f"structural shutdown {boundary} module is invalid")
    return module_name


def validate_m7_output_configuration(args_gn: bytes, out_dir: Path) -> None:
    """Accept only the dedicated source-selected shutdown-probe config."""

    if out_dir.name != DEFAULT_OUT_DIR.name:
        raise M0Error("shutdown probe runner requires its dedicated output directory")
    try:
        text = args_gn.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError as exc:
        raise M0Error("shutdown probe args.gn is not UTF-8") from exc
    values = SHUTDOWN_GN_ENABLE_ASSIGNMENT_RE.findall(text)
    if values != ["true"]:
        raise M0Error("shutdown probe args.gn lacks its exact test opt-in")
    if any(
        value == "true"
        for assignment_re in INCOMPATIBLE_M7_ENABLE_ASSIGNMENT_RES
        for value in assignment_re.findall(text)
    ):
        raise M0Error("shutdown probe args.gn enables an incompatible M7 target")


def create_server(
    host: str,
    port: int,
    out_dir: Path,
    result_token: str,
    *,
    host_dir: Path | None = None,
    runner_source_path: Path | None = None,
) -> PersistentDefaultPartitionShutdownProbeServer:
    """Snapshot the exact shutdown artifact and harness before serving it."""

    module_name = _require_product_module_name(PRODUCT_MODULE_NAME, "server")
    artifacts = snapshot_regular_files(
        out_dir,
        (f"{module_name}.js", f"{module_name}.wasm"),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="persistent-default-partition shutdown-probe artifacts",
    )
    args_gn = snapshot_regular_file(
        out_dir / "args.gn",
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="persistent-default-partition shutdown-probe args.gn",
    )
    validate_m7_output_configuration(args_gn, out_dir)
    selected_host_dir = host_dir or Path(__file__).with_name("host")
    host_snapshots = snapshot_regular_files(
        selected_host_dir,
        (HOST_HTML_NAME, HOST_JS_NAME),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="persistent-default-partition shutdown-probe host resources",
    )
    runner_source = snapshot_regular_file(
        runner_source_path or Path(__file__),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="persistent-default-partition shutdown-probe runner source",
    )
    server = PersistentDefaultPartitionShutdownProbeServer(
        (host, port), PersistentDefaultPartitionShutdownProbeRequestHandler
    )
    server.args_gn = args_gn
    server.artifacts = artifacts
    server.host_html = host_snapshots[HOST_HTML_NAME]
    server.host_js = host_snapshots[HOST_JS_NAME]
    server.module_name = module_name
    server.result_queue = queue.Queue(maxsize=1)
    server.runner_source = runner_source
    server.session = PersistentDefaultPartitionShutdownProbeSession(result_token)
    return server


def _byte_identity(contents: bytes) -> dict[str, object]:
    return {"bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}


def artifact_identity(
    server: PersistentDefaultPartitionShutdownProbeServer,
) -> dict[str, object]:
    if server.module_name != PRODUCT_MODULE_NAME:
        raise M0Error("shutdown probe server module disagrees with its artifact")
    return {
        "artifact_delivery": ARTIFACT_DELIVERY,
        "artifact_source_provenance": ARTIFACT_SOURCE_PROVENANCE,
        "build_config": _byte_identity(server.args_gn),
        "build_config_provenance": BUILD_CONFIG_PROVENANCE,
        "loader": _byte_identity(server.artifacts[f"{PRODUCT_MODULE_NAME}.js"]),
        "module_name": PRODUCT_MODULE_NAME,
        "wasm": _byte_identity(server.artifacts[f"{PRODUCT_MODULE_NAME}.wasm"]),
    }


def capture_harness_identity(
    server: PersistentDefaultPartitionShutdownProbeServer,
) -> dict[str, object]:
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
    except (KeyError, TypeError) as exc:
        raise M0Error("shutdown probe manifest lacks version metadata") from exc
    if not all(
        isinstance(value, str) and GIT_REVISION_RE.fullmatch(value)
        for value in versions.values()
    ):
        raise M0Error("shutdown probe manifest version metadata is invalid")
    return versions


def new_result_token() -> str:
    while True:
        token = secrets.token_urlsafe(24)
        if CAPABILITY_RE.fullmatch(token):
            return token


def smoke_url(
    server: PersistentDefaultPartitionShutdownProbeServer,
    result_token: str,
    versions: dict[str, str],
    *,
    artifact: dict[str, object],
    capture_harness: dict[str, object],
    timeout_seconds: float,
) -> str:
    """Build the fixed one-artifact host URL without native arguments."""

    if (
        server.module_name != PRODUCT_MODULE_NAME
        or not server.session.matches_result_token(result_token)
    ):
        raise M0Error("shutdown probe URL state is invalid")
    timeout_ms = int(float(timeout_seconds) * 1000)
    if timeout_ms < int(MIN_TIMEOUT_SECONDS * 1000) or timeout_ms > MAX_TIMEOUT_MS:
        raise M0Error("shutdown probe URL timeout is invalid")
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "resultToken": result_token,
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
    value: object, fields: frozenset[str], name: str
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise M0Error(f"shutdown probe {name} schema is invalid")
    return value


def _exact_json_equal(left: object, right: object) -> bool:
    return type(left) is type(right) and left == right


def _require_equal(value: dict[str, Any], field: str, expected: object) -> None:
    if not _exact_json_equal(value.get(field), expected):
        raise M0Error(f"shutdown probe result {field} is invalid")


def _validate_byte_identity(value: object, description: str) -> None:
    identity = _require_exact_fields(value, _BYTE_IDENTITY_FIELDS, description)
    if (
        type(identity.get("bytes")) is not int
        or identity["bytes"] < 1
        or not isinstance(identity.get("sha256"), str)
        or not SHA256_RE.fullmatch(identity["sha256"])
    ):
        raise M0Error(f"shutdown probe {description} is invalid")


def _validate_artifact_identity(value: object, expected: dict[str, object]) -> None:
    artifact = _require_exact_fields(value, _ARTIFACT_FIELDS, "artifact")
    if (
        artifact.get("artifact_delivery") != ARTIFACT_DELIVERY
        or artifact.get("artifact_source_provenance") != ARTIFACT_SOURCE_PROVENANCE
        or artifact.get("build_config_provenance") != BUILD_CONFIG_PROVENANCE
        or artifact.get("module_name") != PRODUCT_MODULE_NAME
    ):
        raise M0Error("shutdown probe artifact identity is invalid")
    for field_name in ("build_config", "loader", "wasm"):
        _validate_byte_identity(artifact.get(field_name), f"artifact {field_name}")
    if artifact != expected:
        raise M0Error("shutdown probe artifact identity disagrees with snapshot")


def _validate_capture_harness_identity(
    value: object, expected: dict[str, object]
) -> None:
    harness = _require_exact_fields(value, _CAPTURE_HARNESS_FIELDS, "capture harness")
    if (
        harness.get("source_snapshot_provenance") != SOURCE_SNAPSHOT_PROVENANCE
        or harness.get("version_provenance") != VERSION_PROVENANCE
    ):
        raise M0Error("shutdown probe capture harness identity is invalid")
    for field_name in ("host_html", "host_js", "runner_source"):
        _validate_byte_identity(harness.get(field_name), f"capture {field_name}")
    if harness != expected:
        raise M0Error("shutdown probe capture harness disagrees with snapshot")


def _validate_run(value: object) -> None:
    run = _require_exact_fields(value, _RUN_FIELDS, "run")
    exit_code = run.get("processExitCode")
    if (
        run.get("arguments") != [EXACT_EMPTY_PROBE_SWITCH]
        or run.get("abortObserved") is not False
        or run.get("factoryOutcome")
        not in ("resolved", "expected-nonzero-exit-status")
        or run.get("factorySettled") is not True
        or run.get("freshModuleObject") is not True
        or run.get("leaseReleasedMarkerObserved") is not False
        or run.get("markerCount") != len(EXPECTED_MARKERS)
        or run.get("markerSequenceAccepted") is not True
        or run.get("markerSource")
        != "stderr-only-fixed-profile-directory-fsync-selected-local-storage-renderer-indexed-db-cache-api-context-and-cookie-shutdown-grammar"
        or run.get("markers") != list(EXPECTED_MARKERS)
        or run.get("noFailMarkerObserved") is not True
        or run.get("nonzeroProcessExitAndAckReceived") is not True
        or run.get("onExitCount") != 1
        or run.get("processExitBeforeOnExit") is not True
        or type(exit_code) is not int
        or exit_code <= 0
        or exit_code > 255
        or run.get("processExitCount") != 1
        or run.get("runtimeExitCode") != exit_code
        or run.get("runtimeInitialized") is not True
        or run.get("stdoutMarkerCount") != 0
        or run.get("unexpectedMarkerObserved") is not False
    ):
        raise M0Error("shutdown probe run receipt is invalid")


def _validate_bridge(value: object) -> None:
    bridge = _require_exact_fields(value, _BRIDGE_FIELDS, "bridge")
    expected = {
        "activeAtResult": False,
        "duplicateProcessExitRejected": 0,
        "frozen": True,
        "installedBeforeModuleFactory": True,
        "noActiveProcessExitRejected": 0,
        "permanent": True,
        "processExitDispatches": 1,
        "protocol": 1,
    }
    if bridge != expected:
        raise M0Error("shutdown probe bridge receipt is invalid")


def _validate_quiescence(value: object) -> None:
    quiescence = _require_exact_fields(value, _QUIESCENCE_FIELDS, "quiescence")
    if (
        quiescence.get("quiet") is not True
        or quiescence.get("quietWindowMs") != FINAL_QUIESCENCE_MS
        or type(quiescence.get("callbacksAtLifecycleComplete")) is not int
        or type(quiescence.get("callbacksAfterQuietWindow")) is not int
        or quiescence["callbacksAtLifecycleComplete"] < 0
        or quiescence["callbacksAfterQuietWindow"]
        != quiescence["callbacksAtLifecycleComplete"]
    ):
        raise M0Error("shutdown probe quiescence receipt is invalid")


def _validate_host_boundary(value: object) -> None:
    boundary = _require_exact_fields(value, _HOST_BOUNDARY_FIELDS, "host boundary")
    if any(item is not False for item in boundary.values()):
        raise M0Error("shutdown probe host crossed a prohibited boundary")


def _contains_prohibited_value(value: object, prohibited: str) -> bool:
    try:
        serialized = json.dumps(value, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return True
    return prohibited in serialized


def validate_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
    expected_artifact_identity: dict[str, object],
    expected_capture_harness_identity: dict[str, object],
    expected_origin: str,
    result_token: str,
) -> None:
    """Accept only the fixed selected-owner and structural shutdown receipt."""

    if _contains_prohibited_value(result, result_token):
        raise M0Error("shutdown probe receipt contains its result capability")
    result = _require_exact_fields(result, _RESULT_FIELDS, "result")
    for field, expected in {
        "case": CASE,
        "status": "pass",
        "scope": SCOPE,
        "protocol": 1,
        "m7GateComplete": False,
        "origin": expected_origin,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "exactEmptyProbeSwitchPassed": True,
        "freshSourceSelectedShutdownArtifactProven": True,
        "actualPersistentDefaultPartitionCreatedProven": True,
        "profileDirectoryFsyncProven": True,
        "persistentDefaultPartitionLocalStorageMapUpdateAndCloseReceiptProven": True,
        "persistentDefaultPartitionRendererConfigReuseWitnessProven": True,
        "persistentDefaultPartitionIndexedDBRendererWriteAndCloseReceiptProven": True,
        "persistentDefaultPartitionCacheAPIWriteAndReadbackReceiptProven": True,
        "persistentDefaultPartitionCacheAPISelectedBackendCloseAndIndexReplacementReceiptProven": True,
        "persistentDefaultPartitionIndexedDBContextCloseReceiptProven": True,
        "persistentDefaultPartitionCookieWriteAcceptedProven": True,
        "persistentDefaultPartitionCookieStoreFlushAcknowledgedProven": True,
        "persistentDefaultPartitionCookieSQLiteRowReadbackProven": True,
        "persistentDefaultPartitionCookieStoreCloseReceiptProven": True,
        "creationSealProven": True,
        "partitionDestroyNotificationDispatchedProven": True,
        "partitionMapDroppedProven": True,
        "preferencesFenceProven": True,
        "sealedLeaseRetainedReceiptProven": True,
        "failClosedRetirementProven": True,
        "structuralShutdownWitnessProven": True,
        "nonzeroProcessExitAndAckProven": True,
        "aggregatePartitionCloseProven": False,
        "durableProfileFlushProven": False,
        "profilePersistenceProven": False,
        "profileStorageLeaseReleasedProven": False,
        "freshDocumentReloadProven": False,
        "crashRecoveryProven": False,
        "error": None,
    }.items():
        _require_equal(result, field, expected)
    _require_equal(result, "versions", expected_versions)
    _validate_artifact_identity(result.get("artifact"), expected_artifact_identity)
    _validate_capture_harness_identity(
        result.get("capture_harness"), expected_capture_harness_identity
    )
    _validate_run(result.get("run"))
    _validate_bridge(result.get("bridge"))
    _validate_quiescence(result.get("quiescence"))
    _validate_host_boundary(result.get("hostBoundary"))


def _expected_headers(content_type: str) -> dict[str, str]:
    return {
        "cache-control": "no-store",
        "content-type": content_type,
        "cross-origin-embedder-policy": "require-corp",
        "cross-origin-opener-policy": "same-origin",
        "cross-origin-resource-policy": "same-origin",
        "referrer-policy": "no-referrer",
        "x-content-type-options": "nosniff",
    }


def _stream_response_digest(response: http.client.HTTPResponse) -> tuple[int, str]:
    digest = hashlib.sha256()
    count = 0
    while True:
        chunk = response.read(1024 * 1024)
        if not chunk:
            break
        count += len(chunk)
        digest.update(chunk)
    return count, digest.hexdigest()


def verify_server_delivery(server: PersistentDefaultPartitionShutdownProbeServer) -> None:
    """Check all delivered executable bytes are startup snapshots."""

    host, port = server.server_address[:2]
    expected: tuple[tuple[str, bytes, str], ...] = (
        (f"{HOST_ROOT}/", server.host_html, "text/html"),
        (f"{HOST_ROOT}/{HOST_JS_NAME}", server.host_js, "text/javascript"),
        (
            f"{HOST_ROOT}/artifacts/{PRODUCT_MODULE_NAME}.js",
            server.artifacts[f"{PRODUCT_MODULE_NAME}.js"],
            "text/javascript",
        ),
        (
            f"{HOST_ROOT}/artifacts/{PRODUCT_MODULE_NAME}.wasm",
            server.artifacts[f"{PRODUCT_MODULE_NAME}.wasm"],
            "application/wasm",
        ),
    )
    for path, contents, content_type in expected:
        connection = http.client.HTTPConnection(host, port, timeout=10)
        try:
            connection.request("GET", path, headers={"Cache-Control": "no-store"})
            response = connection.getresponse()
            if response.status != HTTPStatus.OK:
                raise M0Error("shutdown probe snapshot request failed")
            headers = {key.lower(): value for key, value in response.getheaders()}
            for name, expected_value in _expected_headers(content_type).items():
                actual = headers.get(name, "")
                if name == "content-type":
                    actual = actual.split(";", 1)[0].strip().lower()
                if actual != expected_value:
                    raise M0Error("shutdown probe snapshot response header is invalid")
            count, digest = _stream_response_digest(response)
            if count != len(contents) or digest != hashlib.sha256(contents).hexdigest():
                raise M0Error("shutdown probe snapshot body changed")
        finally:
            connection.close()


def wait_for_result(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    server: PersistentDefaultPartitionShutdownProbeServer,
    deadline: float,
) -> dict[str, Any]:
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M0Error(
                "shutdown probe result timed out "
                f"({len(browser_stderr)} browser stderr lines suppressed)"
            )
        try:
            return server.result_queue.get(timeout=min(0.1, remaining))
        except queue.Empty:
            if browser.poll() is not None:
                raise M0Error(
                    "browser exited before shutdown probe receipt acknowledgement "
                    f"({len(browser_stderr)} browser stderr lines suppressed)"
                )


def shutdown_probe_summary() -> dict[str, object]:
    return {
        "actualPersistentDefaultPartitionCreatedProven": True,
        "profileDirectoryFsyncProven": True,
        "aggregatePartitionCloseProven": False,
        "creationSealProven": True,
        "partitionDestroyNotificationDispatchedProven": True,
        "crashRecoveryProven": False,
        "durableProfileFlushProven": False,
        "failClosedRetirementProven": True,
        "freshDocumentReloadProven": False,
        "m7GateComplete": False,
        "nonzeroProcessExitAndResultAckProven": True,
        "partitionMapDroppedProven": True,
        "persistentDefaultPartitionLocalStorageMapUpdateAndCloseReceiptProven": True,
        "persistentDefaultPartitionRendererConfigReuseWitnessProven": True,
        "persistentDefaultPartitionIndexedDBRendererWriteAndCloseReceiptProven": True,
        "persistentDefaultPartitionCacheAPIWriteAndReadbackReceiptProven": True,
        "persistentDefaultPartitionCacheAPISelectedBackendCloseAndIndexReplacementReceiptProven": True,
        "persistentDefaultPartitionIndexedDBContextCloseReceiptProven": True,
        "persistentDefaultPartitionCookieSQLiteRowReadbackProven": True,
        "persistentDefaultPartitionCookieStoreCloseReceiptProven": True,
        "persistentDefaultPartitionCookieStoreFlushAcknowledgedProven": True,
        "persistentDefaultPartitionCookieWriteAcceptedProven": True,
        "preferencesFenceProven": True,
        "profilePersistenceProven": False,
        "sealedLeaseRetainedReceiptProven": True,
        "structuralShutdownWitnessProven": True,
    }


def write_failure_diagnostics(
    diagnostics_dir: Path,
    *,
    stage: str,
    error: Exception,
    browser: subprocess.Popen[str] | None,
    browser_stderr: deque[str],
) -> Path:
    """Write bounded runner state without capability-bearing details."""

    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / "persistent-default-partition-shutdown-probe-failure.json"
    payload = {
        "schema_version": 1,
        "runner": Path(__file__).name,
        "case": CASE,
        "scope": SCOPE,
        "stage": stage,
        "failure": {"type": type(error).__name__, "message": "suppressed"},
        "host_browser": {
            "started": browser is not None,
            "return_code": browser.poll() if browser is not None else None,
            "stderr_line_count": len(browser_stderr),
        },
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return path


def _stop_server(
    server: PersistentDefaultPartitionShutdownProbeServer | None,
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
            raise M0Error("shutdown probe server did not stop")


def parse_shutdown_probe_timeout(value: str) -> float:
    try:
        timeout = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timeout must be a number") from exc
    if (
        not math.isfinite(timeout)
        or timeout < MIN_TIMEOUT_SECONDS
        or timeout > MAX_TIMEOUT_MS / 1000
    ):
        raise argparse.ArgumentTypeError(
            "timeout must be finite and in "
            f"[{MIN_TIMEOUT_SECONDS:g}, {MAX_TIMEOUT_MS / 1000:g}]"
        )
    return timeout


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the one-artifact persistent-default-partition structural "
            "shutdown probe; this makes no durable profile claim."
        ),
        epilog=(
            "Build only the dedicated artifact with: buildtools/linux64/gn gen "
            "out/wasm-chrome-m7-persistent-default-partition-shutdown-probe "
            "--args='"
            + DEFAULT_GN_ARGUMENTS
            + "' --fail-on-unused-args; autoninja -C "
            "out/wasm-chrome-m7-persistent-default-partition-shutdown-probe "
            "chrome_wasm"
        ),
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--diagnostics-dir", type=Path)
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--timeout", type=parse_shutdown_probe_timeout, default=120.0)
    args = parser.parse_args()

    browser: subprocess.Popen[str] | None = None
    browser_stderr: deque[str] = deque(maxlen=MAX_BROWSER_STDERR_LINES)
    browser_stderr_thread: threading.Thread | None = None
    outer_profile: tempfile.TemporaryDirectory[str] | None = None
    server: PersistentDefaultPartitionShutdownProbeServer | None = None
    server_thread: threading.Thread | None = None
    server_thread_started = False
    stage = "initialize"
    summary: dict[str, object] | None = None

    try:
        stage = "load-manifest"
        versions = toolchain_manifest_versions(load_manifest())
        stage = "create-result-capability"
        result_token = new_result_token()
        stage = "create-server"
        server = create_server("127.0.0.1", 0, args.out_dir, result_token)
        artifact = artifact_identity(server)
        capture_harness = capture_harness_identity(server)
        server_thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.05},
            name="chromium-wasm-m7-persistent-default-shutdown-probe-server",
            daemon=True,
        )
        server_thread.start()
        server_thread_started = True
        stage = "verify-server-delivery"
        verify_server_delivery(server)
        url = smoke_url(
            server,
            result_token,
            versions,
            artifact=artifact,
            capture_harness=capture_harness,
            timeout_seconds=args.timeout,
        )
        expected_origin = f"http://{server.server_address[0]}:{server.server_address[1]}"
        stage = "find-browser"
        browser_path, _browser_version = find_browser(args.browser)
        outer_profile = tempfile.TemporaryDirectory(
            prefix="chromium-wasm-m7-persistent-default-shutdown-probe-"
        )
        stage = "launch-browser"
        command = browser_command(
            browser_path, outer_profile.name, url, no_sandbox=args.no_sandbox
        )
        browser = subprocess.Popen(
            command,
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
            name="chromium-wasm-m7-persistent-default-shutdown-probe-browser-stderr",
            daemon=True,
        )
        browser_stderr_thread.start()
        deadline = time.monotonic() + args.timeout
        stage = "wait-result-acknowledgement"
        result = wait_for_result(browser, browser_stderr, server, deadline)
        stage = "validate-result"
        validate_result(
            result,
            expected_versions=versions,
            expected_artifact_identity=artifact,
            expected_capture_harness_identity=capture_harness,
            expected_origin=expected_origin,
            result_token=result_token,
        )
        summary = shutdown_probe_summary()
    except Exception as error:
        if args.diagnostics_dir is not None:
            try:
                write_failure_diagnostics(
                    args.diagnostics_dir,
                    stage=stage,
                    error=error,
                    browser=browser,
                    browser_stderr=browser_stderr,
                )
            except OSError:
                pass
        print(f"{SENTINEL}:FAIL stage={stage}", file=sys.stderr, flush=True)
    finally:
        if browser is not None:
            stop_browser(browser)
        if browser_stderr_thread is not None:
            browser_stderr_thread.join(timeout=3)
        try:
            _stop_server(server, server_thread, server_thread_started)
        except M0Error:
            summary = None
        if outer_profile is not None:
            outer_profile.cleanup()

    if summary is not None:
        print(
            SENTINEL
            + ":PASS "
            + json.dumps(summary, sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
