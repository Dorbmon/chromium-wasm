#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Prove one bounded post-LevelDB-log-Sync recovery boundary.

This separate test passes only when its three fresh outer documents prove a
stable pre- or post-write LevelDB value across two independently reopened,
checksum-verified, paranoid-check handles and two SQLite A full-integrity
controls. It is not the M7 gate: it makes no claim about physical power loss,
directory durability, SQLite interruption recovery, cross-store atomicity,
or normal Chromium profile persistence.

The runner owns opaque token escrow. Raw token A/B values occur only in the
body of one same-origin no-store bootstrap response per document. They never
occur in a URL, receipt, diagnostic, stdout, stderr, or failure message.

Protocol:

* document 1 cleanly seeds A using the dedicated bounded recovery module;
* document 2 freshly verifies A, reports the fixed post-Sync phase, then
  aborts without a clean terminal marker, onExit, process-exit report, or
  lease release; phase and abort delivery have no ordering dependency;
* only after document 2's bounded host settle receipt does the runner issue
  the actual DevTools ``Page.reload`` command;
* document 3 is fresh, proves the test lease was reacquired, and accepts only
  a matching A or B value from two independently reopened checksum/paranoid
  LevelDB handles, plus SQLite A's two close/reopen full-integrity controls.

Every top-level replacement requires both the server's Fetch Metadata
``document``/``navigate`` observation and a same-frame, changed-loader CDP
``Page.frameNavigated`` event. The host may not script either navigation.
"""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass, field
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
from urllib.parse import parse_qs, urlencode, urlsplit

from m0_common import M0Error, REPO_ROOT, load_manifest
from m4_cdp import unused_loopback_port, wait_for_page_client
from m9_descriptor_snapshot import snapshot_regular_file, snapshot_regular_files
from run_browser_smoke import browser_command, drain_stream, find_browser, stop_browser


SENTINEL = "CHROMIUM_WASM_M7_CHROME_PROFILE_DATABASE_RECOVERY_DOM"
CASE = "chrome_profile_database_recovery_m7"
SCOPE = (
    "same-origin-three-outer-documents-chrome-wasm-m7-profile-database-"
    "bounded-leveldb-post-sync-recovery"
)
PRODUCT_MODULE_NAME = "chrome_wasm_m7_profile_database_recovery_test"
PRODUCT_GN_TARGET = "//chrome:chrome_wasm"
PRODUCT_GN_ENABLE_ARGUMENT = (
    "enable_chromium_wasm_m7_profile_database_recovery_test=true"
)
DEFAULT_OUT_DIR = Path("out/wasm-chrome-m7-profile-database-recovery")
DEFAULT_GN_ARGUMENTS = (
    'import("//out/wasm-chrome-m6/args.gn") '
    "enable_chromium_wasm_m7_profile_database_test=true "
    + PRODUCT_GN_ENABLE_ARGUMENT
)
HOST_ROOT = "/__m7_chrome_profile_database_recovery__"
HOST_HTML_NAME = "chrome_wasm_profile_database_recovery_smoke.html"
HOST_JS_NAME = "chrome_wasm_profile_database_recovery_smoke.js"

MAX_RESULT_BYTES = 512 * 1024
MAX_READY_BYTES = 8 * 1024
MAX_BOOTSTRAP_DOCUMENT_BYTES = 8 * 1024
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024 * 1024
MAX_BROWSER_STDERR_LINES = 300
MIN_TIMEOUT_SECONDS = 20.0
MAX_TIMEOUT_MS = 300_000
CLEAN_SETTLE_MS = 50
INTERRUPTION_SETTLE_MS = 75
FINAL_QUIESCENCE_MS = 50


def parse_recovery_timeout(value: str) -> float:
    """Parses the deliberately larger cap needed for a cold Wasm module."""
    try:
        timeout = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timeout must be a number") from exc
    if (
        not math.isfinite(timeout)
        or timeout <= 0
        or timeout > MAX_TIMEOUT_MS / 1000
    ):
        raise argparse.ArgumentTypeError(
            "timeout must be finite and in "
            f"(0, {MAX_TIMEOUT_MS / 1000:g}]"
        )
    return timeout


CAPABILITY_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
GIT_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MODULE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
M7_DATABASE_GN_ENABLE_ASSIGNMENT_RE = re.compile(
    r"^[ \t]*enable_chromium_wasm_m7_profile_database_test[ \t]*="
    r"[ \t]*(true|false)[ \t]*(?:#.*)?$",
    re.MULTILINE,
)
M7_RECOVERY_GN_ENABLE_ASSIGNMENT_RE = re.compile(
    r"^[ \t]*enable_chromium_wasm_m7_profile_database_recovery_test"
    r"[ \t]*=[ \t]*(true|false)[ \t]*(?:#.*)?$",
    re.MULTILINE,
)
M7_DATABASE_ABORT_PC_GN_ENABLE_ASSIGNMENT_RE = re.compile(
    r"^[ \t]*enable_chromium_wasm_m7_profile_database_abort_pc_diagnostic"
    r"[ \t]*=[ \t]*(true|false)[ \t]*(?:#.*)?$",
    re.MULTILINE,
)
M7_DATABASE_WRITE_INTERRUPTION_GN_ENABLE_ASSIGNMENT_RE = re.compile(
    r"^[ \t]*enable_chromium_wasm_m7_profile_database_write_interruption_diagnostic"
    r"[ \t]*=[ \t]*(true|false)[ \t]*(?:#.*)?$",
    re.MULTILINE,
)

M7_DATABASE_MARKER_PREFIX = "CHROMIUM_WASM_M7_DATABASE:"
M7_DATABASE_PHASE_PREFIX = "CHROMIUM_WASM_M7_DATABASE_PHASE:"
INTERRUPTION_PHASE = "leveldb-write-log-sync-returned"
RECOVERED_LEVELDB_VALUES = frozenset(("a", "b"))
RECOVERY_LEASE_REACQUIRED_MARKER = (
    f"{M7_DATABASE_MARKER_PREFIX}RECOVERY_LEASE_REACQUIRED"
)
RECOVERY_CLEAN_MARKERS = (
    f"{M7_DATABASE_MARKER_PREFIX}RECOVERY_DATABASES_CLOSED",
    f"{M7_DATABASE_MARKER_PREFIX}RECOVERY_FENCE_OK",
    f"{M7_DATABASE_MARKER_PREFIX}RECOVERY_LEASE_RELEASED",
)
RECOVERY_SQLITE_A_INTEGRITY_MARKER = (
    f"{M7_DATABASE_MARKER_PREFIX}SQLITE_RECOVERY_A_INTEGRITY_OK"
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
_BOOTSTRAP_DOCUMENT_FIELDS = frozenset(
    ("protocol", "case", "scope", "navigationType", "timeOrigin")
)
_DOCUMENT_FIELDS = frozenset(("navigationType", "timeOrigin"))
_TOKEN_EVIDENCE_FIELDS = frozenset(
    (
        "algorithm",
        "tokenA",
        "tokenB",
        "distinct",
        "rawTokensExcluded",
        "rawTokenLeakDetected",
        "rawTokenRedactionCount",
    )
)
_RUN_FIELDS = frozenset(
    (
        "abortCount",
        "abortObserved",
        "cleanExitObserved",
        "controlledAbortWindowErrorCount",
        "expectedCleanExitStatusObserved",
        "factoryRejected",
        "factoryResolved",
        "factorySettled",
        "markerCount",
        "markerSequenceAccepted",
        "markerSource",
        "markers",
        "mode",
        "moduleIdentity",
        "onExitCount",
        "ordinal",
        "phaseCount",
        "phaseObserved",
        "processExitCode",
        "processExitCount",
        "recoveredLevelDBValue",
        "runtimeExitCode",
        "runtimeInitialized",
        "settleComplete",
        "settleWindowMs",
        "stdoutMarkerCount",
    )
)
_BRIDGE_FIELDS = frozenset(
    (
        "protocol",
        "permanent",
        "frozen",
        "installedBeforeModuleFactory",
        "processExitDispatches",
        "activeRunAtResult",
    )
)
_FINAL_QUIESCENCE_FIELDS = frozenset(
    (
        "activeRunAtEnd",
        "activeRunAtStart",
        "activeRunAtPreUploadCheck",
        "bridgeRecheckedImmediatelyBeforeUpload",
        "callbacksAtEnd",
        "callbacksAtPreUploadCheck",
        "callbacksAtStart",
        "completed",
        "processExitReportsAtEnd",
        "processExitReportsAtPreUploadCheck",
        "processExitReportsAtStart",
        "quiet",
        "quietWindowMs",
        "started",
    )
)
_HOST_BOUNDARY_FIELDS = frozenset(
    (
        "hostOpfsAccessAttempted",
        "hostWebLocksAccessAttempted",
        "nativeCallAttempted",
        "wasmDataInspectionAttempted",
        "sessionStorageAccessAttempted",
        "localStorageAccessAttempted",
        "indexedDbAccessAttempted",
        "cookieAccessAttempted",
        "historyStateAccessAttempted",
        "windowNameAccessAttempted",
    )
)
_RESULT_FIELDS = frozenset(
    (
        "protocol",
        "case",
        "scope",
        "status",
        "m7GateComplete",
        "ordinal",
        "mode",
        "origin",
        "crossOriginIsolated",
        "sharedArrayBuffer",
        "document",
        "artifact",
        "capture_harness",
        "versions",
        "tokenEvidence",
        "run",
        "bridge",
        "finalQuiescence",
        "hostBoundary",
        "fatalErrors",
        "windowErrors",
        "unhandledRejections",
        "failedChecks",
        "error",
    )
)
_READY_FIELDS = frozenset(("protocol", "case", "scope", "ordinal", "timeOrigin"))


@dataclass(frozen=True)
class TokenEscrow:
    """Raw values retained only in the runner's in-memory escrow."""

    token_a: str = field(repr=False)
    token_b: str = field(repr=False)
    token_a_digest: str
    token_b_digest: str


@dataclass(frozen=True)
class DocumentEvidence:
    navigation_type: str
    time_origin: float


@dataclass(frozen=True)
class PhaseResult:
    ordinal: int
    origin: str
    navigation_type: str
    time_origin: float
    module_identity: str
    recovered_leveldb_value: str | None


@dataclass(frozen=True)
class RootFrameIdentity:
    frame_id: str
    loader_id: str


class ProtocolStateError(M0Error):
    """A fixed state conflict that must never disclose an opaque capability."""


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def new_token_escrow() -> TokenEscrow:
    token_a = secrets.token_hex(32)
    token_b = secrets.token_hex(32)
    while token_b == token_a:
        token_b = secrets.token_hex(32)
    return TokenEscrow(
        token_a=token_a,
        token_b=token_b,
        token_a_digest=_sha256_text(token_a),
        token_b_digest=_sha256_text(token_b),
    )


def new_capability_pair() -> tuple[str, str]:
    result_token = secrets.token_urlsafe(24)
    session = secrets.token_urlsafe(24)
    while session == result_token:
        session = secrets.token_urlsafe(24)
    if not CAPABILITY_RE.fullmatch(result_token) or not CAPABILITY_RE.fullmatch(session):
        raise M0Error("recovery capability generation is invalid")
    return result_token, session


def _phase_mode(ordinal: int) -> str:
    if ordinal == 1:
        return "write-a"
    if ordinal == 2:
        return "interrupt-leveldb-write-b"
    if ordinal == 3:
        return "recover-leveldb-write-b"
    raise M0Error("recovery phase ordinal is invalid")


def _phase_status(ordinal: int) -> str:
    if ordinal == 1:
        return "seeded"
    if ordinal == 2:
        return "interrupted"
    if ordinal == 3:
        return "recovered"
    raise M0Error("recovery phase ordinal is invalid")


def _phase_navigation(ordinal: int) -> str:
    if ordinal == 1:
        return "navigate"
    if ordinal in (2, 3):
        return "reload"
    raise M0Error("recovery phase ordinal is invalid")


def _is_valid_document_evidence(value: object) -> bool:
    return (
        isinstance(value, DocumentEvidence)
        and value.navigation_type in ("navigate", "reload")
        and isinstance(value.time_origin, float)
        and math.isfinite(value.time_origin)
        and value.time_origin > 0
    )


class RecoverySession:
    """Three-document bootstrap state plus capability and token escrow.

    The next bootstrap body is unavailable until all three independent gates
    have happened: the runner validated and armed the prior phase, the server
    saw a fresh top-level Fetch-Metadata navigation, and the replacement
    document's evidence receipt was acknowledged and flushed.
    """

    def __init__(self, result_token: str, session: str, escrow: TokenEscrow):
        if (
            not isinstance(result_token, str)
            or not isinstance(session, str)
            or not CAPABILITY_RE.fullmatch(result_token)
            or not CAPABILITY_RE.fullmatch(session)
            or result_token == session
            or not SHA256_RE.fullmatch(escrow.token_a)
            or not SHA256_RE.fullmatch(escrow.token_b)
            or escrow.token_a == escrow.token_b
            or escrow.token_a_digest != _sha256_text(escrow.token_a)
            or escrow.token_b_digest != _sha256_text(escrow.token_b)
        ):
            raise M0Error("recovery session escrow is invalid")
        self._result_token = result_token
        self._session = session
        self._escrow = escrow
        self._lock = threading.Lock()
        self._bootstrap_acknowledgement_gate = threading.Lock()
        self._bootstrap_served: set[int] = set()
        self._results_accepted: set[int] = set()
        self._ready_accepted: set[int] = set()
        self._documents: dict[int, DocumentEvidence] = {}
        self._validated_times: dict[int, float] = {}
        self._armed_ordinal: int | None = None
        self._top_level_navigation_seen: set[int] = set()
        self._pending_document: tuple[int, DocumentEvidence] | None = None

    @property
    def escrow(self) -> TokenEscrow:
        return self._escrow

    def matches_result_token(self, value: str | None) -> bool:
        return isinstance(value, str) and secrets.compare_digest(value, self._result_token)

    def matches_session(self, value: str | None) -> bool:
        return isinstance(value, str) and secrets.compare_digest(value, self._session)

    def bootstrap_acknowledgement_gate(self) -> Any:
        return self._bootstrap_acknowledgement_gate

    def _next_expected_document(self) -> int:
        if 1 not in self._documents:
            return 1
        if self._armed_ordinal in (2, 3):
            return self._armed_ordinal
        raise ProtocolStateError("recovery bootstrap document conflict")

    def accept_bootstrap_document(self, session: str, evidence: DocumentEvidence) -> bool:
        if not self.matches_session(session):
            return False
        if not _is_valid_document_evidence(evidence):
            raise ProtocolStateError("recovery bootstrap document is invalid")
        with self._lock:
            ordinal = self._next_expected_document()
            if (
                ordinal in self._documents
                or ordinal in self._bootstrap_served
                or self._pending_document is not None
                or evidence.navigation_type != _phase_navigation(ordinal)
            ):
                raise ProtocolStateError("recovery bootstrap document conflict")
            if ordinal > 1:
                previous = ordinal - 1
                previous_time = self._validated_times.get(previous)
                if (
                    previous_time is None
                    or ordinal not in self._top_level_navigation_seen
                    or evidence.time_origin <= previous_time
                ):
                    raise ProtocolStateError("recovery bootstrap document conflict")
            self._pending_document = (ordinal, evidence)
            return True

    def acknowledge_bootstrap_document(self, session: str) -> bool:
        if not self.matches_session(session):
            return False
        with self._lock:
            if self._pending_document is None:
                raise ProtocolStateError("recovery bootstrap acknowledgement conflict")
            ordinal, evidence = self._pending_document
            if ordinal in self._documents:
                raise ProtocolStateError("recovery bootstrap acknowledgement conflict")
            self._documents[ordinal] = evidence
            self._pending_document = None
            # The armed ordinal authorizes exactly this one replacement
            # document. Clear it only after its acknowledgement commits so a
            # later bootstrap GET cannot race forward or block arming doc 3.
            if ordinal == self._armed_ordinal:
                self._armed_ordinal = None
            return True

    def bootstrap_payload(self, session: str) -> dict[str, object] | None:
        if not self.matches_session(session):
            return None
        with self._bootstrap_acknowledgement_gate:
            with self._lock:
                candidates = sorted(
                    ordinal
                    for ordinal in self._documents
                    if ordinal not in self._bootstrap_served
                )
                if len(candidates) != 1:
                    raise ProtocolStateError("recovery bootstrap state conflict")
                ordinal = candidates[0]
                self._bootstrap_served.add(ordinal)
        has_b = ordinal in (2, 3)
        return {
            "protocol": 1,
            "case": CASE,
            "scope": SCOPE,
            "ordinal": ordinal,
            "mode": _phase_mode(ordinal),
            "tokenA": self._escrow.token_a,
            "tokenB": self._escrow.token_b if has_b else None,
            "tokenADigest": self._escrow.token_a_digest,
            "tokenBDigest": self._escrow.token_b_digest if has_b else None,
        }

    def arm_next_document(self, previous: int, time_origin: float) -> None:
        if previous not in (1, 2) or not isinstance(time_origin, (int, float)):
            raise M0Error("recovery next-document arm is invalid")
        if isinstance(time_origin, bool) or not math.isfinite(float(time_origin)):
            raise M0Error("recovery next-document arm is invalid")
        next_ordinal = previous + 1
        with self._lock:
            prior_document = self._documents.get(previous)
            if (
                prior_document is None
                or previous not in self._bootstrap_served
                or previous not in self._results_accepted
                or previous not in self._ready_accepted
                or self._armed_ordinal is not None
                or next_ordinal in self._documents
                or float(time_origin) != prior_document.time_origin
            ):
                raise ProtocolStateError("recovery next-document arm conflict")
            self._validated_times[previous] = float(time_origin)
            self._armed_ordinal = next_ordinal

    def observe_top_level_root_navigation(
        self,
        *,
        result_token: str | None,
        session: str | None,
        fetch_destination: str | None,
        fetch_mode: str | None,
    ) -> bool:
        if (
            not self.matches_result_token(result_token)
            or not self.matches_session(session)
            or fetch_destination != "document"
            or fetch_mode != "navigate"
        ):
            return False
        with self._lock:
            ordinal = self._armed_ordinal
            if (
                ordinal not in (2, 3)
                or ordinal in self._top_level_navigation_seen
                or ordinal in self._documents
                or self._pending_document is not None
            ):
                return False
            self._top_level_navigation_seen.add(ordinal)
            return True

    def document_evidence(self, ordinal: int) -> DocumentEvidence:
        with self._lock:
            value = self._documents.get(ordinal)
            if value is None:
                raise ProtocolStateError("recovery document evidence unavailable")
            return value

    def accept_result(self, result_token: str, ordinal: int) -> bool:
        if not self.matches_result_token(result_token):
            return False
        with self._lock:
            if (
                ordinal not in (1, 2, 3)
                or ordinal not in self._bootstrap_served
                or ordinal in self._results_accepted
            ):
                raise ProtocolStateError("recovery result state conflict")
            self._results_accepted.add(ordinal)
        return True

    def accept_ready(self, result_token: str, ordinal: int) -> bool:
        if not self.matches_result_token(result_token):
            return False
        with self._lock:
            if (
                ordinal not in (1, 2, 3)
                or ordinal not in self._results_accepted
                or ordinal in self._ready_accepted
            ):
                raise ProtocolStateError("recovery ready state conflict")
            self._ready_accepted.add(ordinal)
        return True


class ChromeProfileDatabaseRecoveryServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    args_gn: bytes
    artifacts: dict[str, bytes]
    host_html: bytes
    host_js: bytes
    module_name: str
    ready_queue: queue.Queue[tuple[int, dict[str, Any]]]
    receipt_lock: threading.Lock
    result_queue: queue.Queue[tuple[int, dict[str, Any]]]
    runner_source: bytes
    session: RecoverySession

    def handle_error(self, _request: object, _client_address: object) -> None:
        # Request paths contain bearer capabilities. Never let socketserver log
        # a traceback that might retain one.
        return


class ChromeProfileDatabaseRecoveryRequestHandler(BaseHTTPRequestHandler):
    server: ChromeProfileDatabaseRecoveryServer

    def log_message(self, _format: str, *_args: object) -> None:
        # No HTTP request logging: URLs contain bearer capabilities.
        return

    def end_headers(self) -> None:
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def _send_bytes(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, status: HTTPStatus) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _not_found(self) -> None:
        self._send_bytes(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found\n")

    def _conflict(self) -> None:
        self._send_bytes(
            HTTPStatus.CONFLICT,
            "text/plain; charset=utf-8",
            b"recovery endpoint state conflict\n",
        )

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
        value = _parse_json_object(payload)
        if value is None or _contains_prohibited_strings(
            value,
            (
                self.server.session.escrow.token_a,
                self.server.session.escrow.token_b,
            ),
        ):
            return None
        return value

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path
        if path in (HOST_ROOT, f"{HOST_ROOT}/"):
            root_query = parse_qs(parsed.query, keep_blank_values=True)
            result_tokens = root_query.get("resultToken")
            sessions = root_query.get("session")
            self.server.session.observe_top_level_root_navigation(
                result_token=(
                    result_tokens[0]
                    if isinstance(result_tokens, list) and len(result_tokens) == 1
                    else None
                ),
                session=(
                    sessions[0]
                    if isinstance(sessions, list) and len(sessions) == 1
                    else None
                ),
                fetch_destination=self.headers.get("Sec-Fetch-Dest"),
                fetch_mode=self.headers.get("Sec-Fetch-Mode"),
            )
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
        bootstrap_prefix = f"{HOST_ROOT}/bootstrap/"
        if path.startswith(bootstrap_prefix):
            session = path[len(bootstrap_prefix) :]
            if "/" in session or not CAPABILITY_RE.fullmatch(session):
                self._not_found()
                return
            try:
                payload = self.server.session.bootstrap_payload(session)
            except ProtocolStateError:
                self._conflict()
                return
            if payload is None:
                self._not_found()
                return
            self._send_bytes(
                HTTPStatus.OK,
                "application/json; charset=utf-8",
                json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            )
            return
        self._not_found()

    @staticmethod
    def _bootstrap_session_path(path: str) -> str | None:
        prefix = f"{HOST_ROOT}/bootstrap/"
        if not path.startswith(prefix):
            return None
        session = path[len(prefix) :]
        if "/" in session or not CAPABILITY_RE.fullmatch(session):
            return None
        return session

    @staticmethod
    def _receipt_path(path: str, prefix: str) -> tuple[str, int] | None:
        if not path.startswith(prefix):
            return None
        suffix = path[len(prefix) :]
        token, separator, ordinal_text = suffix.partition("/")
        if (
            not separator
            or "/" in ordinal_text
            or not CAPABILITY_RE.fullmatch(token)
            or ordinal_text not in ("1", "2", "3")
        ):
            return None
        return token, int(ordinal_text)

    def do_POST(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.query:
            self._not_found()
            return
        session = self._bootstrap_session_path(parsed.path)
        if session is not None:
            self._post_bootstrap_document(session)
            return
        result = self._receipt_path(parsed.path, f"{HOST_ROOT}/result/")
        if result is not None:
            self._post_result(*result)
            return
        ready = self._receipt_path(parsed.path, f"{HOST_ROOT}/ready/")
        if ready is not None:
            self._post_ready(*ready)
            return
        self._not_found()

    def _post_bootstrap_document(self, session: str) -> None:
        if not self.server.session.matches_session(session):
            self._not_found()
            return
        value = self._read_json_body(MAX_BOOTSTRAP_DOCUMENT_BYTES)
        evidence = _parse_bootstrap_document_evidence(value)
        if evidence is None:
            self._send_bytes(
                HTTPStatus.BAD_REQUEST,
                "text/plain; charset=utf-8",
                b"invalid recovery bootstrap document\n",
            )
            return
        outcome = "accepted"
        with self.server.session.bootstrap_acknowledgement_gate():
            try:
                accepted = self.server.session.accept_bootstrap_document(session, evidence)
            except ProtocolStateError:
                outcome = "conflict"
            else:
                if not accepted:
                    outcome = "not-found"
            if outcome == "accepted":
                self._send_empty(HTTPStatus.NO_CONTENT)
                try:
                    self.wfile.flush()
                except OSError:
                    return
                try:
                    self.server.session.acknowledge_bootstrap_document(session)
                except ProtocolStateError:
                    return
                return
        if outcome == "conflict":
            self._conflict()
        else:
            self._not_found()

    def _post_result(self, result_token: str, ordinal: int) -> None:
        if not self.server.session.matches_result_token(result_token):
            self._not_found()
            return
        value = self._read_json_body(MAX_RESULT_BYTES)
        if value is None or not _is_receipt_identity(value, ordinal):
            self._send_bytes(
                HTTPStatus.BAD_REQUEST,
                "text/plain; charset=utf-8",
                b"invalid recovery result\n",
            )
            return
        with self.server.receipt_lock:
            if self.server.result_queue.full():
                self._conflict()
                return
            try:
                accepted = self.server.session.accept_result(result_token, ordinal)
            except ProtocolStateError:
                self._conflict()
                return
            if not accepted:
                self._not_found()
                return
            self.server.result_queue.put_nowait((ordinal, value))
        self._send_empty(HTTPStatus.NO_CONTENT)

    def _post_ready(self, result_token: str, ordinal: int) -> None:
        if not self.server.session.matches_result_token(result_token):
            self._not_found()
            return
        value = self._read_json_body(MAX_READY_BYTES)
        if value is None or not _is_ready_identity(value, ordinal):
            self._send_bytes(
                HTTPStatus.BAD_REQUEST,
                "text/plain; charset=utf-8",
                b"invalid recovery ready\n",
            )
            return
        outcome = "accepted"
        with self.server.receipt_lock:
            if self.server.ready_queue.full():
                outcome = "conflict"
            else:
                try:
                    accepted = self.server.session.accept_ready(result_token, ordinal)
                except ProtocolStateError:
                    outcome = "conflict"
                else:
                    if not accepted:
                        outcome = "not-found"
        if outcome == "conflict":
            self._conflict()
            return
        if outcome == "not-found":
            self._not_found()
            return
        self._send_empty(HTTPStatus.NO_CONTENT)
        try:
            self.wfile.flush()
        except OSError:
            return
        try:
            self.server.ready_queue.put_nowait((ordinal, value))
        except queue.Full:
            return


def _reject_duplicate_object_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
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


def _contains_prohibited_strings(value: object, prohibited: tuple[str, ...]) -> bool:
    def visit(item: object, depth: int) -> bool:
        if depth > 32:
            return True
        if isinstance(item, str):
            return any(secret in item for secret in prohibited)
        if isinstance(item, list):
            return any(visit(child, depth + 1) for child in item)
        if isinstance(item, dict):
            return any(
                visit(key, depth + 1) or visit(child, depth + 1)
                for key, child in item.items()
            )
        return False

    return visit(value, 0)


def _parse_bootstrap_document_evidence(
    value: dict[str, Any] | None,
) -> DocumentEvidence | None:
    if not isinstance(value, dict) or set(value) != _BOOTSTRAP_DOCUMENT_FIELDS:
        return None
    navigation_type = value.get("navigationType")
    time_origin = value.get("timeOrigin")
    if (
        type(value.get("protocol")) is not int
        or value.get("protocol") != 1
        or value.get("case") != CASE
        or value.get("scope") != SCOPE
        or navigation_type not in ("navigate", "reload")
        or not isinstance(time_origin, (int, float))
        or isinstance(time_origin, bool)
        or not math.isfinite(float(time_origin))
        or float(time_origin) <= 0
    ):
        return None
    return DocumentEvidence(navigation_type, float(time_origin))


def _is_receipt_identity(value: dict[str, Any], ordinal: int) -> bool:
    return (
        type(value.get("protocol")) is int
        and value.get("protocol") == 1
        and value.get("case") == CASE
        and value.get("scope") == SCOPE
        and type(value.get("ordinal")) is int
        and value.get("ordinal") == ordinal
        and value.get("m7GateComplete") is False
    )


def _is_ready_identity(value: dict[str, Any], ordinal: int) -> bool:
    return (
        type(value.get("protocol")) is int
        and value.get("protocol") == 1
        and value.get("case") == CASE
        and value.get("scope") == SCOPE
        and type(value.get("ordinal")) is int
        and value.get("ordinal") == ordinal
    )


def _require_product_module_name(module_name: object, boundary: str) -> str:
    if not isinstance(module_name, str) or module_name != PRODUCT_MODULE_NAME:
        raise M0Error(f"recovery {boundary} module is invalid")
    return module_name


def validate_m7_output_configuration(args_gn: bytes) -> None:
    """Require the isolated bounded-recovery source selection."""

    try:
        text = args_gn.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError as exc:
        raise M0Error("recovery args.gn is not UTF-8") from exc
    database_values = M7_DATABASE_GN_ENABLE_ASSIGNMENT_RE.findall(text)
    recovery_values = M7_RECOVERY_GN_ENABLE_ASSIGNMENT_RE.findall(text)
    abort_pc_values = M7_DATABASE_ABORT_PC_GN_ENABLE_ASSIGNMENT_RE.findall(text)
    interruption_values = (
        M7_DATABASE_WRITE_INTERRUPTION_GN_ENABLE_ASSIGNMENT_RE.findall(text)
    )
    if not database_values or any(value != "true" for value in database_values):
        raise M0Error("recovery args.gn lacks the database test opt-in")
    if not recovery_values or any(value != "true" for value in recovery_values):
        raise M0Error("recovery args.gn lacks its recovery-test opt-in")
    if any(value == "true" for value in abort_pc_values):
        raise M0Error("recovery args.gn enables an incompatible diagnostic")
    if any(value == "true" for value in interruption_values):
        raise M0Error("recovery args.gn enables the observation-only diagnostic")


def create_server(
    host: str,
    port: int,
    out_dir: Path,
    result_token: str,
    session: str,
    escrow: TokenEscrow,
    *,
    host_dir: Path | None = None,
    runner_source_path: Path | None = None,
    module_name: str = PRODUCT_MODULE_NAME,
) -> ChromeProfileDatabaseRecoveryServer:
    """Snapshot every served execution input before serving a connection."""

    module_name = _require_product_module_name(module_name, "server")
    artifacts = snapshot_regular_files(
        out_dir,
        (f"{module_name}.js", f"{module_name}.wasm"),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="recovery profile database artifacts",
    )
    args_gn = snapshot_regular_file(
        out_dir / "args.gn",
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="recovery selected args.gn",
    )
    validate_m7_output_configuration(args_gn)
    selected_host_dir = host_dir or Path(__file__).with_name("host")
    host_snapshots = snapshot_regular_files(
        selected_host_dir,
        (HOST_HTML_NAME, HOST_JS_NAME),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="recovery host resources",
    )
    runner_source = snapshot_regular_file(
        runner_source_path or Path(__file__),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="recovery runner source",
    )
    server = ChromeProfileDatabaseRecoveryServer(
        (host, port), ChromeProfileDatabaseRecoveryRequestHandler
    )
    server.args_gn = args_gn
    server.artifacts = artifacts
    server.host_html = host_snapshots[HOST_HTML_NAME]
    server.host_js = host_snapshots[HOST_JS_NAME]
    server.module_name = module_name
    server.ready_queue = queue.Queue(maxsize=3)
    server.receipt_lock = threading.Lock()
    server.result_queue = queue.Queue(maxsize=3)
    server.runner_source = runner_source
    server.session = RecoverySession(result_token, session, escrow)
    return server


def _byte_identity(contents: bytes) -> dict[str, object]:
    return {"bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}


def artifact_identity(
    server: ChromeProfileDatabaseRecoveryServer,
    *,
    module_name: str = PRODUCT_MODULE_NAME,
) -> dict[str, object]:
    module_name = _require_product_module_name(module_name, "artifact")
    if server.module_name != module_name:
        raise M0Error("recovery artifact module disagrees with server")
    return {
        "artifact_delivery": ARTIFACT_DELIVERY,
        "artifact_source_provenance": ARTIFACT_SOURCE_PROVENANCE,
        "build_config": _byte_identity(server.args_gn),
        "build_config_provenance": BUILD_CONFIG_PROVENANCE,
        "loader": _byte_identity(server.artifacts[f"{module_name}.js"]),
        "module_name": module_name,
        "wasm": _byte_identity(server.artifacts[f"{module_name}.wasm"]),
    }


def capture_harness_identity(
    server: ChromeProfileDatabaseRecoveryServer,
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
        raise M0Error("recovery manifest lacks version metadata") from exc
    if not all(
        isinstance(value, str) and GIT_REVISION_RE.fullmatch(value)
        for value in versions.values()
    ):
        raise M0Error("recovery manifest version metadata is invalid")
    return versions


def smoke_url(
    server: ChromeProfileDatabaseRecoveryServer,
    result_token: str,
    session: str,
    versions: dict[str, str],
    *,
    artifact: dict[str, object],
    capture_harness: dict[str, object],
    timeout_seconds: float,
    module_name: str = PRODUCT_MODULE_NAME,
) -> str:
    """Build the sole navigated URL without a raw database value."""

    module_name = _require_product_module_name(module_name, "URL")
    if server.module_name != module_name:
        raise M0Error("recovery URL module disagrees with server")
    if not server.session.matches_result_token(result_token) or not server.session.matches_session(
        session
    ):
        raise M0Error("recovery URL capability disagrees with server")
    if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool):
        raise M0Error("recovery URL timeout is invalid")
    timeout_ms = int(float(timeout_seconds) * 1000)
    if timeout_ms < 1000 or timeout_ms > MAX_TIMEOUT_MS:
        raise M0Error("recovery URL timeout is invalid")
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "resultToken": result_token,
            "session": session,
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


def _require_exact_fields(value: object, fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise M0Error(f"recovery {name} schema is invalid")
    return value


def _exact_json_equal(left: object, right: object) -> bool:
    return type(left) is type(right) and left == right


def _require_equal(value: dict[str, Any], field: str, expected: object) -> None:
    if not _exact_json_equal(value.get(field), expected):
        raise M0Error(f"recovery result {field} is invalid")


def _validate_byte_identity(value: object, description: str) -> None:
    value = _require_exact_fields(value, _BYTE_IDENTITY_FIELDS, description)
    if (
        type(value.get("bytes")) is not int
        or value["bytes"] < 1
        or not isinstance(value.get("sha256"), str)
        or not SHA256_RE.fullmatch(value["sha256"])
    ):
        raise M0Error(f"recovery {description} is invalid")


def _validate_artifact_identity(value: object, expected: dict[str, object]) -> None:
    value = _require_exact_fields(value, _ARTIFACT_FIELDS, "artifact")
    _validate_byte_identity(value.get("build_config"), "artifact build config")
    _validate_byte_identity(value.get("loader"), "artifact loader")
    _validate_byte_identity(value.get("wasm"), "artifact Wasm")
    if value != expected:
        raise M0Error("recovery artifact identity is invalid")


def _validate_capture_harness_identity(value: object, expected: dict[str, object]) -> None:
    value = _require_exact_fields(value, _CAPTURE_HARNESS_FIELDS, "capture harness")
    for field_name in ("host_html", "host_js", "runner_source"):
        _validate_byte_identity(value.get(field_name), f"capture harness {field_name}")
    if value != expected:
        raise M0Error("recovery capture harness is invalid")


def expected_markers(ordinal: int, escrow: TokenEscrow, outcome: str | None = None) -> list[str]:
    if ordinal == 1:
        return [
            f"{M7_DATABASE_MARKER_PREFIX}READY",
            RECOVERY_LEASE_REACQUIRED_MARKER,
            f"{M7_DATABASE_MARKER_PREFIX}SQLITE_WRITE_ACCEPTED sha256={escrow.token_a_digest}",
            f"{M7_DATABASE_MARKER_PREFIX}LEVELDB_WRITE_ACCEPTED sha256={escrow.token_a_digest}",
            *RECOVERY_CLEAN_MARKERS,
        ]
    if ordinal == 2:
        return [
            f"{M7_DATABASE_MARKER_PREFIX}READY",
            RECOVERY_LEASE_REACQUIRED_MARKER,
            f"{M7_DATABASE_MARKER_PREFIX}SQLITE_READ_A_OK sha256={escrow.token_a_digest}",
            f"{M7_DATABASE_MARKER_PREFIX}LEVELDB_READ_A_OK sha256={escrow.token_a_digest}",
        ]
    if ordinal == 3 and outcome in RECOVERED_LEVELDB_VALUES:
        digest = escrow.token_a_digest if outcome == "a" else escrow.token_b_digest
        return [
            f"{M7_DATABASE_MARKER_PREFIX}READY",
            RECOVERY_LEASE_REACQUIRED_MARKER,
            f"{M7_DATABASE_MARKER_PREFIX}LEVELDB_RECOVERY_{outcome.upper()}_OK sha256={digest}",
            f"{RECOVERY_SQLITE_A_INTEGRITY_MARKER} sha256={escrow.token_a_digest}",
            *RECOVERY_CLEAN_MARKERS,
        ]
    raise M0Error("recovery marker expectation is invalid")


def _validate_token_evidence(value: object, ordinal: int, escrow: TokenEscrow) -> None:
    tokens = _require_exact_fields(value, _TOKEN_EVIDENCE_FIELDS, "token evidence")
    expected_b: str | None = None if ordinal == 1 else escrow.token_b_digest
    expected_distinct: bool | None = None if ordinal == 1 else True
    if (
        tokens.get("algorithm") != "SHA-256"
        or tokens.get("tokenA") != escrow.token_a_digest
        or tokens.get("tokenB") != expected_b
        or tokens.get("distinct") is not expected_distinct
        or tokens.get("rawTokensExcluded") is not True
        or tokens.get("rawTokenLeakDetected") is not False
        or type(tokens.get("rawTokenRedactionCount")) is not int
        or tokens.get("rawTokenRedactionCount") != 0
    ):
        raise M0Error("recovery token evidence is invalid")


def _validate_document(
    value: object, ordinal: int, expected: DocumentEvidence
) -> DocumentEvidence:
    document = _require_exact_fields(value, _DOCUMENT_FIELDS, "document")
    time_origin = document.get("timeOrigin")
    if (
        document.get("navigationType") != _phase_navigation(ordinal)
        or not isinstance(time_origin, (int, float))
        or isinstance(time_origin, bool)
        or not math.isfinite(float(time_origin))
        or float(time_origin) <= 0
    ):
        raise M0Error("recovery document is invalid")
    actual = DocumentEvidence(document["navigationType"], float(time_origin))
    if actual != expected:
        raise M0Error("recovery document disagrees with bootstrap")
    return actual


def _validate_string_array(value: object, description: str) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) > 16
        or not all(isinstance(item, str) and len(item) <= 128 for item in value)
    ):
        raise M0Error(f"recovery {description} is invalid")
    return value


def _validate_run(value: object, ordinal: int, escrow: TokenEscrow) -> tuple[str, str | None]:
    run = _require_exact_fields(value, _RUN_FIELDS, "run")
    markers = _validate_string_array(run.get("markers"), "run markers")
    module_identity = run.get("moduleIdentity")
    if (
        run.get("mode") != _phase_mode(ordinal)
        or type(run.get("ordinal")) is not int
        or run.get("ordinal") != ordinal
        or not isinstance(module_identity, str)
        or not MODULE_ID_RE.fullmatch(module_identity)
        or run.get("markerSource") != "stderr-only-fixed-grammar"
        or run.get("markerSequenceAccepted") is not True
        or run.get("markerCount") != len(markers)
        or run.get("stdoutMarkerCount") != 0
        or run.get("runtimeInitialized") is not True
        or run.get("settleComplete") is not True
    ):
        raise M0Error("recovery run identity is invalid")

    if ordinal == 2:
        if (
            markers != expected_markers(2, escrow)
            or run.get("phaseObserved") is not True
            or run.get("phaseCount") != 1
            or run.get("abortObserved") is not True
            or run.get("abortCount") != 1
            or run.get("controlledAbortWindowErrorCount") != 2
            or run.get("cleanExitObserved") is not False
            or run.get("onExitCount") != 0
            or run.get("processExitCount") != 0
            or run.get("processExitCode") is not None
            or run.get("runtimeExitCode") is not None
            or run.get("factoryResolved") is not True
            or run.get("factoryRejected") is not False
            or run.get("factorySettled") is not True
            or run.get("expectedCleanExitStatusObserved") is not False
            or run.get("recoveredLevelDBValue") is not None
            or run.get("settleWindowMs") != INTERRUPTION_SETTLE_MS + FINAL_QUIESCENCE_MS
        ):
            raise M0Error("recovery interrupted run is invalid")
        return module_identity, None

    outcome: str | None = None
    if ordinal == 3:
        outcome = run.get("recoveredLevelDBValue")
        if outcome not in RECOVERED_LEVELDB_VALUES:
            raise M0Error("recovery LevelDB value is invalid")
    elif run.get("recoveredLevelDBValue") is not None:
        raise M0Error("recovery non-final value receipt is invalid")
    if (
        markers != expected_markers(ordinal, escrow, outcome)
        or run.get("phaseObserved") is not False
        or run.get("phaseCount") != 0
        or run.get("abortObserved") is not False
        or run.get("abortCount") != 0
        or run.get("controlledAbortWindowErrorCount") != 0
        or run.get("cleanExitObserved") is not True
        or run.get("onExitCount") != 1
        or run.get("processExitCount") != 1
        or run.get("processExitCode") != 0
        or run.get("runtimeExitCode") != 0
        or run.get("factoryResolved") is not True
        or run.get("factoryRejected") is not False
        or run.get("factorySettled") is not True
        or type(run.get("expectedCleanExitStatusObserved")) is not bool
        or run.get("settleWindowMs") != CLEAN_SETTLE_MS + FINAL_QUIESCENCE_MS
    ):
        raise M0Error("recovery clean run is invalid")
    return module_identity, outcome


def _validate_bridge(value: object, ordinal: int) -> None:
    bridge = _require_exact_fields(value, _BRIDGE_FIELDS, "bridge")
    expected_dispatches = 0 if ordinal == 2 else 1
    if (
        bridge.get("protocol") != 1
        or bridge.get("permanent") is not True
        or bridge.get("frozen") is not True
        or bridge.get("installedBeforeModuleFactory") is not True
        or bridge.get("processExitDispatches") != expected_dispatches
        or bridge.get("activeRunAtResult") is not None
    ):
        raise M0Error("recovery bridge is invalid")


def _validate_final_quiescence(value: object, ordinal: int) -> None:
    quiescence = _require_exact_fields(
        value, _FINAL_QUIESCENCE_FIELDS, "final quiescence"
    )
    expected_process_exits = 0 if ordinal == 2 else 1
    if (
        quiescence.get("started") is not True
        or quiescence.get("completed") is not True
        or quiescence.get("quiet") is not True
        or quiescence.get("quietWindowMs") != FINAL_QUIESCENCE_MS
        or quiescence.get("bridgeRecheckedImmediatelyBeforeUpload") is not True
        or quiescence.get("activeRunAtStart") != ordinal
        or quiescence.get("activeRunAtEnd") != ordinal
        or quiescence.get("activeRunAtPreUploadCheck") is not None
    ):
        raise M0Error("recovery final quiescence state is invalid")
    callback_fields = (
        "callbacksAtStart",
        "callbacksAtEnd",
        "callbacksAtPreUploadCheck",
    )
    process_exit_fields = (
        "processExitReportsAtStart",
        "processExitReportsAtEnd",
        "processExitReportsAtPreUploadCheck",
    )
    if any(
        type(quiescence.get(field)) is not int or quiescence[field] < 0
        for field in callback_fields + process_exit_fields
    ):
        raise M0Error("recovery final quiescence counters are invalid")
    if len({quiescence[field] for field in callback_fields}) != 1 or len(
        {quiescence[field] for field in process_exit_fields}
    ) != 1:
        raise M0Error("recovery final quiescence is not quiet")
    if quiescence["processExitReportsAtStart"] != expected_process_exits:
        raise M0Error("recovery final quiescence exit count is invalid")


def _validate_host_boundary(value: object) -> None:
    boundary = _require_exact_fields(value, _HOST_BOUNDARY_FIELDS, "host boundary")
    if any(field_value is not False for field_value in boundary.values()):
        raise M0Error("recovery host crossed a prohibited boundary")


def validate_phase_result(
    result: dict[str, Any],
    *,
    ordinal: int,
    expected_versions: dict[str, str],
    expected_artifact_identity: dict[str, object],
    expected_capture_harness_identity: dict[str, object],
    expected_origin: str,
    expected_document: DocumentEvidence,
    escrow: TokenEscrow,
    result_token: str,
    session: str,
) -> PhaseResult:
    """Validate one fixed receipt in the bounded recovery protocol."""

    if _contains_prohibited_strings(
        result, (escrow.token_a, escrow.token_b, result_token, session)
    ):
        raise M0Error("recovery receipt contains an opaque value")
    result = _require_exact_fields(result, _RESULT_FIELDS, "result")
    for field_name, expected in {
        "protocol": 1,
        "case": CASE,
        "scope": SCOPE,
        "status": _phase_status(ordinal),
        "m7GateComplete": False,
        "ordinal": ordinal,
        "mode": _phase_mode(ordinal),
        "origin": expected_origin,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "fatalErrors": [],
        "windowErrors": [],
        "unhandledRejections": [],
        "failedChecks": [],
        "error": None,
    }.items():
        _require_equal(result, field_name, expected)
    _require_equal(result, "versions", expected_versions)
    _validate_artifact_identity(result.get("artifact"), expected_artifact_identity)
    _validate_capture_harness_identity(
        result.get("capture_harness"), expected_capture_harness_identity
    )
    document = _validate_document(result.get("document"), ordinal, expected_document)
    _validate_token_evidence(result.get("tokenEvidence"), ordinal, escrow)
    module_identity, outcome = _validate_run(result.get("run"), ordinal, escrow)
    _validate_bridge(result.get("bridge"), ordinal)
    _validate_final_quiescence(result.get("finalQuiescence"), ordinal)
    _validate_host_boundary(result.get("hostBoundary"))
    return PhaseResult(
        ordinal=ordinal,
        origin=expected_origin,
        navigation_type=document.navigation_type,
        time_origin=document.time_origin,
        module_identity=module_identity,
        recovered_leveldb_value=outcome,
    )


def validate_ready_receipt(ready: dict[str, Any], *, expected: PhaseResult) -> None:
    ready = _require_exact_fields(ready, _READY_FIELDS, "ready receipt")
    time_origin = ready.get("timeOrigin")
    if (
        type(ready.get("protocol")) is not int
        or ready.get("protocol") != 1
        or ready.get("case") != CASE
        or ready.get("scope") != SCOPE
        or type(ready.get("ordinal")) is not int
        or ready.get("ordinal") != expected.ordinal
        or not isinstance(time_origin, (int, float))
        or isinstance(time_origin, bool)
        or not math.isfinite(float(time_origin))
        or float(time_origin) != expected.time_origin
    ):
        raise M0Error("recovery ready receipt is invalid")


def validate_three_document_transition(
    first: PhaseResult, second: PhaseResult, third: PhaseResult
) -> None:
    if (
        first.ordinal != 1
        or second.ordinal != 2
        or third.ordinal != 3
        or first.origin != second.origin
        or second.origin != third.origin
        or first.navigation_type != "navigate"
        or second.navigation_type != "reload"
        or third.navigation_type != "reload"
        or not (first.time_origin < second.time_origin < third.time_origin)
        or len({first.module_identity, second.module_identity, third.module_identity}) != 3
        or third.recovered_leveldb_value not in RECOVERED_LEVELDB_VALUES
    ):
        raise M0Error("recovery three-document transition is invalid")


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


def verify_server_delivery(server: ChromeProfileDatabaseRecoveryServer) -> None:
    """Verify only immutable snapshotted static inputs are served."""

    host, port = server.server_address[:2]
    expected: tuple[tuple[str, bytes, str], ...] = (
        (f"{HOST_ROOT}/", server.host_html, "text/html"),
        (f"{HOST_ROOT}/{HOST_JS_NAME}", server.host_js, "text/javascript"),
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
                raise M0Error("recovery snapshot request failed")
            headers = {key.lower(): value for key, value in response.getheaders()}
            for name, expected_value in _expected_headers(content_type).items():
                actual = headers.get(name, "")
                if name == "content-type":
                    actual = actual.split(";", 1)[0].strip().lower()
                if actual != expected_value:
                    raise M0Error("recovery snapshot response header is invalid")
            count, digest = _stream_response_digest(response)
            if count != len(contents) or digest != hashlib.sha256(contents).hexdigest():
                raise M0Error("recovery snapshot body changed")
        finally:
            connection.close()


def _wait_for_receipt(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    receipts: queue.Queue[tuple[int, dict[str, Any]]],
    ordinal: int,
    deadline: float,
    kind: str,
) -> dict[str, Any]:
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M0Error(
                f"recovery {kind} timed out "
                f"({len(browser_stderr)} browser stderr lines suppressed)"
            )
        try:
            receipt_ordinal, receipt = receipts.get(timeout=min(0.1, remaining))
        except queue.Empty:
            if browser.poll() is not None:
                raise M0Error(
                    f"recovery browser exited before {kind} "
                    f"({len(browser_stderr)} browser stderr lines suppressed)"
                )
            continue
        if receipt_ordinal != ordinal:
            raise M0Error("recovery receipt order is invalid")
        return receipt


def wait_for_phase_result(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    server: ChromeProfileDatabaseRecoveryServer,
    ordinal: int,
    deadline: float,
) -> dict[str, Any]:
    return _wait_for_receipt(
        browser, browser_stderr, server.result_queue, ordinal, deadline, "result"
    )


def wait_for_ready_receipt(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    server: ChromeProfileDatabaseRecoveryServer,
    ordinal: int,
    deadline: float,
) -> dict[str, Any]:
    return _wait_for_receipt(
        browser, browser_stderr, server.ready_queue, ordinal, deadline, "ready receipt"
    )


def _root_frame_identity(value: object) -> RootFrameIdentity:
    if not isinstance(value, dict):
        raise M0Error("recovery DevTools frame tree is invalid")
    tree = value.get("frameTree")
    if not isinstance(tree, dict):
        raise M0Error("recovery DevTools frame tree is invalid")
    frame = tree.get("frame")
    if (
        not isinstance(frame, dict)
        or "parentId" in frame
        or not isinstance(frame.get("id"), str)
        or not frame["id"]
        or not isinstance(frame.get("loaderId"), str)
        or not frame["loaderId"]
    ):
        raise M0Error("recovery DevTools root frame is invalid")
    return RootFrameIdentity(frame["id"], frame["loaderId"])


def prepare_outer_document_reload(client: Any) -> RootFrameIdentity:
    client.call("Page.enable")
    return _root_frame_identity(client.call("Page.getFrameTree"))


def _root_reload_event(
    event: object,
    *,
    baseline: RootFrameIdentity,
    expected_page_url_prefix: str,
) -> RootFrameIdentity | None:
    if not isinstance(event, dict) or event.get("method") != "Page.frameNavigated":
        return None
    params = event.get("params")
    if not isinstance(params, dict):
        raise M0Error("recovery DevTools navigation event is invalid")
    frame = params.get("frame")
    if not isinstance(frame, dict):
        raise M0Error("recovery DevTools navigation event is invalid")
    if frame.get("id") != baseline.frame_id:
        return None
    if "parentId" in frame:
        raise M0Error("recovery DevTools root frame changed parent")
    loader_id = frame.get("loaderId")
    url = frame.get("url")
    if not isinstance(loader_id, str) or not loader_id:
        raise M0Error("recovery DevTools navigation loader is invalid")
    if loader_id == baseline.loader_id:
        return None
    if not isinstance(url, str) or not url.startswith(expected_page_url_prefix):
        raise M0Error("recovery DevTools navigation URL is invalid")
    return RootFrameIdentity(baseline.frame_id, loader_id)


def wait_for_root_reload_navigation(
    client: Any,
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    baseline: RootFrameIdentity,
    expected_page_url_prefix: str,
    deadline: float,
) -> RootFrameIdentity:
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M0Error(
                "recovery DevTools navigation timed out "
                f"({len(browser_stderr)} browser stderr lines suppressed)"
            )
        if browser.poll() is not None:
            raise M0Error(
                "recovery browser exited before DevTools navigation "
                f"({len(browser_stderr)} browser stderr lines suppressed)"
            )
        event = client.next_event(min(0.1, remaining))
        candidate = (
            _root_reload_event(
                event,
                baseline=baseline,
                expected_page_url_prefix=expected_page_url_prefix,
            )
            if event is not None
            else None
        )
        if candidate is not None:
            return candidate


def reload_outer_document(
    client: Any,
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    baseline: RootFrameIdentity,
    expected_page_url_prefix: str,
    deadline: float,
) -> RootFrameIdentity:
    """Perform the only two document replacements through DevTools Page.reload."""

    client.call("Page.reload", {"ignoreCache": True})
    return wait_for_root_reload_navigation(
        client,
        browser,
        browser_stderr,
        baseline,
        expected_page_url_prefix,
        deadline,
    )


def write_failure_diagnostics(
    diagnostics_dir: Path,
    *,
    stage: str,
    error: Exception,
    browser: subprocess.Popen[str] | None,
    browser_stderr: deque[str],
    result_ordinals_received: set[int],
    ready_ordinals_received: set[int],
) -> Path:
    """Write fixed runner-owned failure state without opaque request data."""

    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / "chrome-profile-database-recovery-m7-failure.json"
    payload = {
        "schema_version": 1,
        "runner": "run_m7_chrome_profile_database_recovery_dom_smoke.py",
        "case": CASE,
        "scope": SCOPE,
        "m7GateComplete": False,
        "stage": stage,
        "failure": {
            "type": type(error).__name__,
            "message": "details-suppressed-for-opaque-token-hygiene",
        },
        "host_browser": {
            "started": browser is not None,
            "return_code": browser.poll() if browser is not None else None,
            "stderr_line_count": len(browser_stderr),
            "stderr_suppressed_for_opaque_token_hygiene": True,
        },
        "result_ordinals_received": sorted(result_ordinals_received),
        "ready_ordinals_received": sorted(ready_ordinals_received),
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return path


def _stop_server(
    server: ChromeProfileDatabaseRecoveryServer | None,
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
            raise M0Error("recovery server did not stop")


def _recovery_summary(outcome: str) -> dict[str, object]:
    """Return the accepted bounded result without promoting the M7 gate."""

    if outcome not in RECOVERED_LEVELDB_VALUES:
        raise M0Error("recovery summary value is invalid")
    return {
        "case": CASE,
        "boundedDatabaseRecoveryAccepted": True,
        "controlledPostSyncInterruptionProven": True,
        "documents": 3,
        "m7GateComplete": False,
        "freshOuterDocumentReloadProven": True,
        "freshModuleLeaseReacquisitionObserved": True,
        "leveldbDoubleReopenChecksumParanoidProven": True,
        "sqliteAFullIntegrityControlsProven": True,
        "stableLevelDBPreOrPostValue": outcome,
        "outerReloadProfilePersistenceProven": False,
        "persistenceProven": False,
        "profilePersistenceProven": False,
        "durabilityProven": False,
        "directoryDurabilityProven": False,
        "physicalCrashBehaviorProven": False,
        "sqliteInterruptionRecoveryProven": False,
        "crossStoreAtomicityProven": False,
        "fullChromiumProfileProven": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prove bounded Chrome Wasm LevelDB recovery after a controlled "
            "post-log-Sync interruption."
        ),
        epilog=(
            "Build the isolated artifact with: buildtools/linux64/gn gen "
            "out/wasm-chrome-m7-profile-database-recovery --args='"
            + DEFAULT_GN_ARGUMENTS
            + "' --fail-on-unused-args; autoninja -C "
            "out/wasm-chrome-m7-profile-database-recovery chrome_wasm"
        ),
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--diagnostics-dir", type=Path)
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--timeout", type=parse_recovery_timeout, default=120.0)
    args = parser.parse_args()
    if args.timeout < MIN_TIMEOUT_SECONDS:
        parser.error(f"--timeout must be at least {MIN_TIMEOUT_SECONDS:g} seconds")

    browser: subprocess.Popen[str] | None = None
    browser_stderr: deque[str] = deque(maxlen=MAX_BROWSER_STDERR_LINES)
    browser_stderr_thread: threading.Thread | None = None
    client: Any | None = None
    outer_profile: tempfile.TemporaryDirectory[str] | None = None
    server: ChromeProfileDatabaseRecoveryServer | None = None
    server_thread: threading.Thread | None = None
    server_thread_started = False
    result_ordinals_received: set[int] = set()
    ready_ordinals_received: set[int] = set()
    stage = "initialize"
    recovery: dict[str, object] | None = None

    try:
        stage = "load-manifest"
        versions = toolchain_manifest_versions(load_manifest())
        stage = "create-token-escrow"
        result_token, session = new_capability_pair()
        escrow = new_token_escrow()
        stage = "create-server"
        server = create_server(
            "127.0.0.1", 0, args.out_dir, result_token, session, escrow
        )
        artifact = artifact_identity(server)
        capture_harness = capture_harness_identity(server)
        server_thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.05},
            name="chromium-wasm-m7-profile-database-recovery-server",
            daemon=True,
        )
        server_thread.start()
        server_thread_started = True
        stage = "verify-server-delivery"
        verify_server_delivery(server)
        url = smoke_url(
            server,
            result_token,
            session,
            versions,
            artifact=artifact,
            capture_harness=capture_harness,
            timeout_seconds=args.timeout,
        )
        expected_origin = f"http://{server.server_address[0]}:{server.server_address[1]}"
        stage = "find-browser"
        browser_path, _browser_version = find_browser(args.browser)
        outer_profile = tempfile.TemporaryDirectory(
            prefix="chromium-wasm-m7-profile-database-recovery-"
        )
        debug_port = unused_loopback_port()
        stage = "launch-browser"
        command = browser_command(
            browser_path, outer_profile.name, url, no_sandbox=args.no_sandbox
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
        browser_stderr_thread = threading.Thread(
            target=drain_stream,
            args=(browser.stderr, browser_stderr),
            name="chromium-wasm-m7-profile-database-recovery-browser-stderr",
            daemon=True,
        )
        browser_stderr_thread.start()
        deadline = time.monotonic() + args.timeout
        expected_page_url_prefix = url.split("?", 1)[0]

        stage = "connect-devtools-phase-one"
        client = wait_for_page_client(debug_port, expected_page_url_prefix, deadline)
        stage = "wait-phase-one-result"
        first_result = wait_for_phase_result(browser, browser_stderr, server, 1, deadline)
        result_ordinals_received.add(1)
        stage = "validate-phase-one-result"
        first = validate_phase_result(
            first_result,
            ordinal=1,
            expected_versions=versions,
            expected_artifact_identity=artifact,
            expected_capture_harness_identity=capture_harness,
            expected_origin=expected_origin,
            expected_document=server.session.document_evidence(1),
            escrow=escrow,
            result_token=result_token,
            session=session,
        )
        stage = "wait-phase-one-ready"
        first_ready = wait_for_ready_receipt(browser, browser_stderr, server, 1, deadline)
        ready_ordinals_received.add(1)
        stage = "validate-phase-one-ready"
        validate_ready_receipt(first_ready, expected=first)
        stage = "prepare-cdp-first-reload"
        root_frame = prepare_outer_document_reload(client)
        stage = "arm-interrupted-document"
        server.session.arm_next_document(1, first.time_origin)
        stage = "reload-to-interrupted-document"
        root_frame = reload_outer_document(
            client, browser, browser_stderr, root_frame, expected_page_url_prefix, deadline
        )

        stage = "wait-interrupted-result"
        second_result = wait_for_phase_result(browser, browser_stderr, server, 2, deadline)
        result_ordinals_received.add(2)
        stage = "validate-interrupted-result"
        second = validate_phase_result(
            second_result,
            ordinal=2,
            expected_versions=versions,
            expected_artifact_identity=artifact,
            expected_capture_harness_identity=capture_harness,
            expected_origin=expected_origin,
            expected_document=server.session.document_evidence(2),
            escrow=escrow,
            result_token=result_token,
            session=session,
        )
        stage = "wait-interrupted-ready-after-bounded-settle"
        second_ready = wait_for_ready_receipt(browser, browser_stderr, server, 2, deadline)
        ready_ordinals_received.add(2)
        stage = "validate-interrupted-ready"
        validate_ready_receipt(second_ready, expected=second)
        stage = "arm-recovery-value-document"
        server.session.arm_next_document(2, second.time_origin)
        stage = "reload-to-recovery-value-document"
        root_frame = reload_outer_document(
            client, browser, browser_stderr, root_frame, expected_page_url_prefix, deadline
        )

        stage = "wait-recovery-value-result"
        third_result = wait_for_phase_result(browser, browser_stderr, server, 3, deadline)
        result_ordinals_received.add(3)
        stage = "validate-recovery-value-result"
        third = validate_phase_result(
            third_result,
            ordinal=3,
            expected_versions=versions,
            expected_artifact_identity=artifact,
            expected_capture_harness_identity=capture_harness,
            expected_origin=expected_origin,
            expected_document=server.session.document_evidence(3),
            escrow=escrow,
            result_token=result_token,
            session=session,
        )
        stage = "wait-recovery-value-ready"
        third_ready = wait_for_ready_receipt(browser, browser_stderr, server, 3, deadline)
        ready_ordinals_received.add(3)
        stage = "validate-recovery-value-ready"
        validate_ready_receipt(third_ready, expected=third)
        stage = "validate-three-document-transition"
        validate_three_document_transition(first, second, third)
        recovery = _recovery_summary(third.recovered_leveldb_value or "")
    except Exception as error:
        if args.diagnostics_dir is not None:
            try:
                write_failure_diagnostics(
                    args.diagnostics_dir,
                    stage=stage,
                    error=error,
                    browser=browser,
                    browser_stderr=browser_stderr,
                    result_ordinals_received=result_ordinals_received,
                    ready_ordinals_received=ready_ordinals_received,
                )
            except OSError:
                pass
        print(f"{SENTINEL}:FAIL stage={stage}", file=sys.stderr, flush=True)
    finally:
        if client is not None:
            client.close()
        if browser is not None:
            stop_browser(browser)
        if browser_stderr_thread is not None:
            browser_stderr_thread.join(timeout=3)
        try:
            _stop_server(server, server_thread, server_thread_started)
        except M0Error:
            recovery = None
        if outer_profile is not None:
            outer_profile.cleanup()

    if recovery is not None:
        print(
            SENTINEL
            + ":PASS "
            + json.dumps(recovery, sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
