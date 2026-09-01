#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the two-outer-document Chrome database persistence smoke.

This is deliberately a narrow, clean-lifecycle witness.  Document one runs
the existing ``write-a`` database mode.  After it has posted a complete,
validated lifecycle receipt and a post-upload ready receipt, the default
runner uses the browser DevTools ``Page.reload`` command. Its explicit
fresh-outer-browser mode instead proves a clean host-browser exit before
document two starts in a distinct host Chrome process. Document two then runs
the existing ``verify-a-write-b`` mode. The second mode reads token A through
both SQLite and LevelDB before it writes token B. Thus the two receipts prove
only this narrow source-selected test-artifact database witness across a real
same-origin document replacement, and in the explicit mode across a fresh
outer Chrome process; they do not claim normal Chrome profile persistence,
crash recovery, or a completed M7 profile gate.

Protocol, intentionally kept here with the runner because it is a security
boundary:

* The initial page URL is ``HOST_ROOT/`` and has exactly the query keys
  ``resultToken``, ``session``, ``module``, ``timeoutMs``, ``versions``,
  ``artifact``, and ``captureHarness``.  ``resultToken`` and ``session`` are
  unrelated URL-safe bearer capabilities.  Database values never appear in a
  URL, storage API, browser history, or DevTools command.
* The host posts one pre-bootstrap document receipt to
  ``POST ./bootstrap/<session>``.  Its exact JSON keys are ``protocol``,
  ``case``, ``scope``, ``navigationType``, and ``timeOrigin``.  After the
  no-content acknowledgement is flushed, the host makes its sole
  ``GET ./bootstrap/<session>``.  That response is the one no-store bootstrap
  JSON object with exact keys ``protocol``, ``case``, ``scope``, ``ordinal``,
  ``mode``, ``tokenA``, ``tokenB``, ``tokenADigest``, ``tokenBDigest``, and
  ``expectedNavigationType``.
  Raw tokens exist only in the GET response body and are held by the runner's
  in-memory escrow.  Phase one must report ``navigate`` and has null B fields.
  Phase two must report the server-owned expected navigation type with a
  strictly newer time origin after the runner has validated phase one and the
  server has seen a fresh top-level document navigation; only then can the
  server return B.
* A page posts its receipt to
  ``POST ./result/<resultToken>/<ordinal>`` and, after one zero-delay task,
  posts its ready barrier to ``POST ./ready/<resultToken>/<ordinal>``.  Each
  endpoint accepts JSON only once and only after that phase's bootstrap.
  Neither endpoint advances the phase itself.  The runner owns that action.
* A passing phase receipt has exactly the top-level keys listed in
  ``_RESULT_FIELDS`` below.  It contains SHA-256 witnesses but not raw values,
  URLs, paths, capabilities, or host-storage observations.  The ready receipt
  has exactly ``protocol``, ``case``, ``scope``, ``ordinal``, and
  ``timeOrigin``. The document receipt must call the first navigation
  ``navigate`` and the server-owned second navigation type; its second
  ``timeOrigin`` must be strictly newer.

The Python process retains both raw database values and both bearer
capabilities.  It never serializes page receipts, browser stderr, exception
text, or those values into stdout/stderr or failure diagnostics.
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
from urllib.request import urlopen

from m0_common import M0Error, REPO_ROOT, load_manifest, parse_timeout
from m4_cdp import DevToolsClient, unused_loopback_port, wait_for_page_client
from m9_browser_cleanup import (
    BrowserStderrReader,
    abort_browser_group,
    wait_for_browser_group_exit,
)
from m9_descriptor_snapshot import snapshot_regular_file, snapshot_regular_files
from run_browser_smoke import browser_command, find_browser


SENTINEL = "CHROMIUM_WASM_M7_CHROME_PROFILE_DATABASE_OUTER_RELOAD_DOM"
CASE = "chrome_profile_database_outer_document_persistence_m7"
SCOPE = (
    "same-origin-two-outer-documents-chrome-wasm-m7-profile-database-test-"
    "modules-orderly-handoff-only"
)
PRODUCT_MODULE_NAME = "chrome_wasm_m7_profile_database_test"
PRODUCT_GN_TARGET = "//chrome:chrome_wasm"
PRODUCT_GN_ENABLE_ARGUMENT = "enable_chromium_wasm_m7_profile_database_test=true"
DEFAULT_OUT_DIR = Path("out/wasm-chrome-m7-profile-database")
DEFAULT_GN_ARGUMENTS = (
    'import("//out/wasm-chrome-m6/args.gn") ' + PRODUCT_GN_ENABLE_ARGUMENT
)
BUILD_CONFIG_PROVENANCE = "selected-out-dir-args-gn-immutable-snapshot"
HOST_ROOT = "/__m7_chrome_profile_database_outer_reload__"
HOST_HTML_NAME = "chrome_wasm_profile_database_outer_reload_smoke.html"
HOST_JS_NAME = "chrome_wasm_profile_database_outer_reload_smoke.js"

MAX_RESULT_BYTES = 512 * 1024
MAX_READY_BYTES = 8 * 1024
MAX_BOOTSTRAP_DOCUMENT_BYTES = 8 * 1024
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024 * 1024
MAX_OUTPUT_LINES = 128
MAX_BROWSER_STDERR_LINES = 300
FINAL_QUIESCENCE_MS = 50
OUTER_BROWSER_CLOSE_TIMEOUT_SECONDS = 10.0
MIN_TIMEOUT_SECONDS = 20.0

CAPABILITY_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
GIT_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MODULE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
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
M7_DATABASE_PHASE_PREFIX = "CHROMIUM_WASM_M7_DATABASE_PHASE:"
M7_ABORT_PC_PREFIX = "CHROMIUM_WASM_M7_ABORT_PC:"
SUPPRESSED_NATIVE_OUTPUT = "<suppressed-native-output>"
SUPPRESSED_BROWSER_STDERR_TOKEN = "<suppressed-browser-stderr-token>"

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
_DOCUMENT_FIELDS = frozenset(("navigationType", "timeOrigin"))
_BOOTSTRAP_DOCUMENT_FIELDS = frozenset(
    ("protocol", "case", "scope", "navigationType", "timeOrigin")
)
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
        "abort",
        "activeClearedAfterLifecycle",
        "expectedExitStatusObserved",
        "factoryError",
        "factorySettled",
        "freshModuleObject",
        "leaseReleasedMarkerObserved",
        "markerCount",
        "markerDeliveryCompleteAtProcessExit",
        "markerSequenceAccepted",
        "markerSource",
        "markers",
        "mode",
        "moduleIdentity",
        "onExitCount",
        "ordinal",
        "postLifecycleTimerObserved",
        "processExitBeforeOnExit",
        "processExitCode",
        "processExitCount",
        "runtimeExitCode",
        "runtimeInitialized",
        "stderr",
        "stdout",
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
_FINAL_QUIESCENCE_FIELDS = frozenset(
    (
        "taskScheduledExactlyOnce",
        "taskMethod",
        "postLifecycleTimerObservedBeforeTask",
        "started",
        "startedAfterActiveClear",
        "completed",
        "quietWindowMs",
        "quiet",
        "callbacksAtActiveClear",
        "callbacksAtTaskStart",
        "callbacksAtTaskEnd",
        "callbacksAtPreUploadCheck",
        "processExitReportsAtActiveClear",
        "processExitReportsAtTaskStart",
        "processExitReportsAtTaskEnd",
        "processExitReportsAtPreUploadCheck",
        "activeRunAtActiveClear",
        "activeRunAtTaskStart",
        "activeRunAtTaskEnd",
        "activeRunAtPreUploadCheck",
        "bridgeRecheckedImmediatelyBeforeUpload",
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
    """Raw private arguments retained only by the Python runner."""

    token_a: str = field(repr=False)
    token_b: str = field(repr=False)
    token_a_digest: str
    token_b_digest: str


def redact_browser_stderr_record(
    record: str,
    escrow: TokenEscrow,
    raw_token_seen: threading.Event,
) -> str:
    """Suppress an unsafe record before it reaches a retained diagnostic queue."""

    normalized = record.rstrip()
    if escrow.token_a in normalized or escrow.token_b in normalized:
        raw_token_seen.set()
        return SUPPRESSED_BROWSER_STDERR_TOKEN
    return normalized


def drain_browser_stderr(
    stream: Any,
    destination: deque[str],
    escrow: TokenEscrow,
    raw_token_seen: threading.Event,
) -> None:
    """Legacy stream adapter retained for focused token-hygiene coverage."""

    for line in stream:
        destination.append(
            redact_browser_stderr_record(line, escrow, raw_token_seen)
        )


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


@dataclass(frozen=True)
class RootFrameIdentity:
    frame_id: str
    loader_id: str


@dataclass(frozen=True)
class OuterBrowserLaunch:
    """One independently launched host Chrome process and owned resources."""

    browser: subprocess.Popen[str]
    debug_port: int
    profile_path: str
    url: str
    stderr_reader: BrowserStderrReader


@dataclass(frozen=True)
class OuterBrowserCloseEvidence:
    """Evidence needed before a temporary outer Chrome profile is reused."""

    browser_close_acknowledged: bool
    zero_exit_status: bool
    stderr_eof: bool
    process_group_gone: bool


def has_fresh_outer_browser_database_persistence_evidence(
    *,
    outer_browser_processes_started: int,
    first_outer_browser_close: OuterBrowserCloseEvidence | None,
    second_outer_browser_identity_distinct: bool,
    same_outer_profile_for_phase_two: bool,
    same_origin_for_phase_two: bool,
    phase_two_navigation_type: str,
    phase_two: PhaseResult,
    phase_two_sqlite_and_leveldb_read_a_validated: bool,
    phase_two_fresh_document_time_origin: bool,
) -> bool:
    """Return only the complete narrow fresh-host-process database witness."""

    return (
        outer_browser_processes_started == 2
        and first_outer_browser_close is not None
        and first_outer_browser_close.browser_close_acknowledged
        and first_outer_browser_close.zero_exit_status
        and first_outer_browser_close.stderr_eof
        and first_outer_browser_close.process_group_gone
        and second_outer_browser_identity_distinct
        and same_outer_profile_for_phase_two
        and same_origin_for_phase_two
        and phase_two_navigation_type == "navigate"
        and phase_two.navigation_type == "navigate"
        and phase_two_sqlite_and_leveldb_read_a_validated
        and phase_two_fresh_document_time_origin
    )


def _is_valid_document_evidence(value: object) -> bool:
    return (
        isinstance(value, DocumentEvidence)
        and value.navigation_type in ("navigate", "reload")
        and isinstance(value.time_origin, float)
        and math.isfinite(value.time_origin)
        and value.time_origin > 0
    )


class ProtocolStateError(M0Error):
    """A fixed state conflict that must never disclose a capability."""


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def new_token_escrow() -> TokenEscrow:
    """Generate two non-equal 256-bit values and their public witnesses."""

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
    """Return unrelated result and bootstrap bearer capabilities."""

    result_token = secrets.token_urlsafe(24)
    session = secrets.token_urlsafe(24)
    while session == result_token:
        session = secrets.token_urlsafe(24)
    if not CAPABILITY_RE.fullmatch(result_token) or not CAPABILITY_RE.fullmatch(session):
        raise M0Error("outer-reload capability generation is invalid")
    return result_token, session


def _phase_mode(ordinal: int) -> str:
    if ordinal == 1:
        return "write-a"
    if ordinal == 2:
        return "verify-a-write-b"
    raise M0Error("outer-reload phase ordinal is invalid")


class OuterReloadSession:
    """Server-side phase machine and token escrow.

    Phase two is deliberately split into three independent gates: the runner
    arms only document evidence after validating phase one; the HTTP server
    then observes a fresh top-level document navigation; and the new document
    posts the server-owned navigation evidence. No gate alone can expose
    token B.
    """

    def __init__(
        self,
        result_token: str,
        session: str,
        escrow: TokenEscrow,
        *,
        phase_two_navigation_type: str = "reload",
    ):
        if (
            not isinstance(result_token, str)
            or not isinstance(session, str)
            or not CAPABILITY_RE.fullmatch(result_token)
            or not CAPABILITY_RE.fullmatch(session)
            or result_token == session
        ):
            raise M0Error("outer-reload session capability is invalid")
        if (
            not SHA256_RE.fullmatch(escrow.token_a)
            or not SHA256_RE.fullmatch(escrow.token_b)
            or escrow.token_a == escrow.token_b
            or escrow.token_a_digest != _sha256_text(escrow.token_a)
            or escrow.token_b_digest != _sha256_text(escrow.token_b)
            or phase_two_navigation_type not in ("navigate", "reload")
        ):
            raise M0Error("outer-reload token escrow is invalid")
        self._result_token = result_token
        self._session = session
        self._escrow = escrow
        self._phase_two_navigation_type = phase_two_navigation_type
        self._lock = threading.Lock()
        # The request handler holds this gate from the moment it accepts
        # document evidence through the acknowledgement's socket flush and
        # state commit.  A concurrent GET must wait for that atomic boundary
        # instead of treating an already-acknowledged POST as a 409 race.
        self._bootstrap_acknowledgement_gate = threading.Lock()
        self._bootstrap_served: set[int] = set()
        self._results_accepted: set[int] = set()
        self._ready_accepted: set[int] = set()
        self._phase_one_document: DocumentEvidence | None = None
        self._phase_one_validated_time_origin: float | None = None
        self._phase_two_document: DocumentEvidence | None = None
        self._phase_two_document_evidence_armed = False
        self._phase_two_top_level_transition_seen = False
        self._pending_bootstrap_document: tuple[int, DocumentEvidence] | None = None

    @property
    def escrow(self) -> TokenEscrow:
        return self._escrow

    def matches_result_token(self, value: str) -> bool:
        return isinstance(value, str) and secrets.compare_digest(
            value, self._result_token
        )

    def matches_session(self, value: str) -> bool:
        return isinstance(value, str) and secrets.compare_digest(value, self._session)

    def bootstrap_acknowledgement_gate(self) -> Any:
        """Serialize a POST acknowledgement flush and the following GET."""

        return self._bootstrap_acknowledgement_gate

    def expected_navigation_type(self, ordinal: int) -> str:
        if ordinal == 1:
            return "navigate"
        if ordinal == 2:
            return self._phase_two_navigation_type
        raise M0Error("outer-reload phase ordinal is invalid")

    def accept_bootstrap_document(
        self, session: str, evidence: DocumentEvidence
    ) -> bool:
        """Accept one authenticated, pre-bootstrap outer-document receipt."""

        if not self.matches_session(session):
            return False
        if not _is_valid_document_evidence(evidence):
            raise ProtocolStateError("outer-reload bootstrap document is invalid")
        with self._lock:
            if self._phase_one_document is None:
                if (
                    evidence.navigation_type != "navigate"
                    or self._bootstrap_served
                    or self._pending_bootstrap_document is not None
                ):
                    raise ProtocolStateError(
                        "outer-reload bootstrap document state conflict"
                    )
                self._pending_bootstrap_document = (1, evidence)
                return True
            if (
                not self._phase_two_document_evidence_armed
                or not self._phase_two_top_level_transition_seen
                or self._phase_two_document is not None
                or self._pending_bootstrap_document is not None
                or 2 in self._bootstrap_served
                or evidence.navigation_type != self.expected_navigation_type(2)
                or self._phase_one_validated_time_origin is None
                or evidence.time_origin <= self._phase_one_validated_time_origin
            ):
                raise ProtocolStateError("outer-reload bootstrap document state conflict")
            self._pending_bootstrap_document = (2, evidence)
            return True

    def acknowledge_bootstrap_document(self, session: str) -> bool:
        """Make an evidence receipt usable only after its 204 was flushed."""

        if not self.matches_session(session):
            return False
        with self._lock:
            pending = self._pending_bootstrap_document
            if pending is None:
                raise ProtocolStateError("outer-reload bootstrap acknowledgement conflict")
            ordinal, evidence = pending
            if ordinal == 1 and self._phase_one_document is None:
                self._phase_one_document = evidence
            elif ordinal == 2 and self._phase_two_document is None:
                self._phase_two_document = evidence
            else:
                raise ProtocolStateError("outer-reload bootstrap acknowledgement conflict")
            self._pending_bootstrap_document = None
            return True

    def bootstrap_payload(self, session: str) -> dict[str, object] | None:
        """Claim a raw-token body only after its document receipt was accepted."""

        if not self.matches_session(session):
            return None
        # The POST handler retains this gate across its 204 flush and
        # acknowledgement.  Do not let a GET observe the transient pending
        # state after the peer has received a successful acknowledgement.
        with self._bootstrap_acknowledgement_gate:
            with self._lock:
                if (
                    self._phase_one_document is not None
                    and 1 not in self._bootstrap_served
                ):
                    ordinal = 1
                elif (
                    self._phase_two_document is not None
                    and 2 not in self._bootstrap_served
                ):
                    ordinal = 2
                else:
                    raise ProtocolStateError("outer-reload bootstrap state conflict")
                self._bootstrap_served.add(ordinal)
        first = ordinal == 1
        return {
            "protocol": 1,
            "case": CASE,
            "scope": SCOPE,
            "ordinal": ordinal,
            "mode": _phase_mode(ordinal),
            "expectedNavigationType": self.expected_navigation_type(ordinal),
            "tokenA": self._escrow.token_a,
            "tokenB": None if first else self._escrow.token_b,
            "tokenADigest": self._escrow.token_a_digest,
            "tokenBDigest": None if first else self._escrow.token_b_digest,
        }

    def observe_top_level_root_navigation(
        self,
        *,
        result_token: str | None,
        session: str | None,
        fetch_destination: str | None,
        fetch_mode: str | None,
    ) -> bool:
        """Record only the post-arm top-level document navigation boundary."""

        if (
            not self.matches_result_token(result_token)
            or not self.matches_session(session)
            or fetch_destination != "document"
            or fetch_mode != "navigate"
        ):
            return False
        with self._lock:
            if (
                not self._phase_two_document_evidence_armed
                or self._phase_two_top_level_transition_seen
                or self._phase_two_document is not None
                or self._pending_bootstrap_document is not None
                or 2 in self._bootstrap_served
            ):
                return False
            self._phase_two_top_level_transition_seen = True
            return True

    def document_evidence(self, ordinal: int) -> DocumentEvidence:
        with self._lock:
            evidence = (
                self._phase_one_document
                if ordinal == 1
                else self._phase_two_document
                if ordinal == 2
                else None
            )
            if evidence is None:
                raise ProtocolStateError("outer-reload document evidence is unavailable")
            return evidence

    def accept_result(self, result_token: str, ordinal: int) -> bool:
        """Reserve one receipt after its phase-specific bootstrap was served."""

        if not self.matches_result_token(result_token):
            return False
        with self._lock:
            if (
                ordinal not in (1, 2)
                or ordinal not in self._bootstrap_served
                or ordinal in self._results_accepted
            ):
                raise ProtocolStateError("outer-reload result state conflict")
            self._results_accepted.add(ordinal)
        return True

    def accept_ready(self, result_token: str, ordinal: int) -> bool:
        """Reserve a ready barrier only after its corresponding receipt."""

        if not self.matches_result_token(result_token):
            return False
        with self._lock:
            if (
                ordinal not in (1, 2)
                or ordinal not in self._results_accepted
                or ordinal in self._ready_accepted
            ):
                raise ProtocolStateError("outer-reload ready state conflict")
            self._ready_accepted.add(ordinal)
        return True

    def arm_phase_two_document_evidence(self, phase_one_time_origin: float) -> None:
        """Permit evidence, never B, after runner validation of phase one."""

        if (
            not isinstance(phase_one_time_origin, (int, float))
            or isinstance(phase_one_time_origin, bool)
            or not math.isfinite(float(phase_one_time_origin))
            or float(phase_one_time_origin) <= 0
        ):
            raise M0Error("outer-reload phase-one document time is invalid")
        with self._lock:
            if (
                self._phase_one_document is None
                or 1 not in self._bootstrap_served
                or 1 not in self._results_accepted
                or 1 not in self._ready_accepted
                or self._phase_two_document_evidence_armed
                or self._phase_two_document is not None
                or self._pending_bootstrap_document is not None
                or float(phase_one_time_origin)
                != self._phase_one_document.time_origin
            ):
                raise ProtocolStateError("outer-reload phase authorization conflict")
            self._phase_one_validated_time_origin = float(phase_one_time_origin)
            self._phase_two_document_evidence_armed = True


class ChromeProfileDatabaseOuterReloadServer(ThreadingHTTPServer):
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
    session: OuterReloadSession

    def handle_error(self, _request: object, _client_address: object) -> None:
        # socketserver's default traceback may retain a request path, and a
        # request path contains one of the bearer capabilities.  The runner
        # notices a failed receipt by timeout; do not turn a transport failure
        # into a capability-bearing server log.
        return


class ChromeProfileDatabaseOuterReloadRequestHandler(BaseHTTPRequestHandler):
    server: ChromeProfileDatabaseOuterReloadServer

    def log_message(self, _format: str, *_args: object) -> None:
        # Request paths carry bearer capabilities.  Never place them in a log.
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
        self._send_bytes(
            HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found\n"
        )

    def _conflict(self) -> None:
        self._send_bytes(
            HTTPStatus.CONFLICT,
            "text/plain; charset=utf-8",
            b"outer-reload endpoint state conflict\n",
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
        return _parse_json_object(payload)

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
                bootstrap = self.server.session.bootstrap_payload(session)
            except ProtocolStateError:
                self._conflict()
                return
            if bootstrap is None:
                self._not_found()
                return
            body = json.dumps(bootstrap, separators=(",", ":")).encode("utf-8")
            self._send_bytes(HTTPStatus.OK, "application/json; charset=utf-8", body)
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
    def _receipt_path(
        path: str, prefix: str
    ) -> tuple[str, int] | None:
        if not path.startswith(prefix):
            return None
        suffix = path[len(prefix) :]
        token, separator, ordinal_text = suffix.partition("/")
        if (
            not separator
            or "/" in ordinal_text
            or not CAPABILITY_RE.fullmatch(token)
            or ordinal_text not in ("1", "2")
        ):
            return None
        return token, int(ordinal_text)

    def do_POST(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.query:
            self._not_found()
            return
        bootstrap_session = self._bootstrap_session_path(parsed.path)
        if bootstrap_session is not None:
            self._post_bootstrap_document(bootstrap_session)
            return
        result_path = self._receipt_path(parsed.path, f"{HOST_ROOT}/result/")
        if result_path is not None:
            self._post_result(*result_path)
            return
        ready_path = self._receipt_path(parsed.path, f"{HOST_ROOT}/ready/")
        if ready_path is not None:
            self._post_ready(*ready_path)
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
                b"invalid outer-reload bootstrap document\n",
            )
            return
        outcome = "accepted"
        # Keep a concurrent GET outside this boundary until the successful
        # acknowledgement has both reached the peer and become committed
        # session state.  Evidence stays pending until after flush, so a
        # failed acknowledgement cannot expose either raw bootstrap body.
        with self.server.session.bootstrap_acknowledgement_gate():
            try:
                accepted = self.server.session.accept_bootstrap_document(
                    session, evidence
                )
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
                    # Do not expose a bootstrap body after a failed
                    # acknowledgement; pending evidence remains unusable.
                    return
                try:
                    self.server.session.acknowledge_bootstrap_document(session)
                except ProtocolStateError:
                    return
                return
        if outcome == "conflict":
            self._conflict()
            return
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
                b"invalid outer-reload result\n",
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
                b"invalid outer-reload ready receipt\n",
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
        # A queued ready receipt permits the runner to reload the outer
        # document.  Do not retain receipt_lock during socket I/O: the state
        # claim above rejects duplicates, and queue notification follows only
        # a flushed acknowledgement boundary.
        self._send_empty(HTTPStatus.NO_CONTENT)
        try:
            self.wfile.flush()
        except OSError:
            return
        try:
            self.server.ready_queue.put_nowait((ordinal, value))
        except queue.Full:
            # The state is already terminal for this receipt.  Fail by
            # withholding the queue notification rather than admitting a
            # duplicate or allowing an unacknowledged reload.
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


def _parse_bootstrap_document_evidence(
    value: dict[str, Any] | None,
) -> DocumentEvidence | None:
    if not isinstance(value, dict) or set(value) != _BOOTSTRAP_DOCUMENT_FIELDS:
        return None
    time_origin = value.get("timeOrigin")
    navigation_type = value.get("navigationType")
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
    )


def _is_ready_identity(value: dict[str, Any], ordinal: int) -> bool:
    return _is_receipt_identity(value, ordinal)


def _require_product_module_name(module_name: object, boundary: str) -> str:
    if not isinstance(module_name, str) or module_name != PRODUCT_MODULE_NAME:
        raise M0Error(f"outer-reload {boundary} module is invalid")
    return module_name


def validate_m7_output_configuration(args_gn: bytes) -> None:
    """Require the normal dedicated M7 database artifact, never its diagnostic."""

    try:
        text = args_gn.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError as exc:
        raise M0Error("outer-reload args.gn is not UTF-8") from exc
    values = M7_DATABASE_GN_ENABLE_ASSIGNMENT_RE.findall(text)
    if not values or any(value != "true" for value in values):
        raise M0Error("outer-reload args.gn lacks the database test opt-in")
    diagnostic_values = M7_DATABASE_ABORT_PC_GN_ENABLE_ASSIGNMENT_RE.findall(text)
    if any(value == "true" for value in diagnostic_values):
        raise M0Error("outer-reload args.gn enables an unsupported diagnostic")
    sqlite_recovery_values = (
        M7_DATABASE_SQLITE_RECOVERY_GN_ENABLE_ASSIGNMENT_RE.findall(text)
    )
    if any(value == "true" for value in sqlite_recovery_values):
        raise M0Error("outer-reload args.gn enables the SQLite recovery artifact")


def create_server(
    host: str,
    port: int,
    out_dir: Path,
    result_token: str,
    session: str,
    escrow: TokenEscrow,
    *,
    module_name: str = PRODUCT_MODULE_NAME,
    host_dir: Path | None = None,
    runner_source_path: Path | None = None,
    phase_two_navigation_type: str = "reload",
) -> ChromeProfileDatabaseOuterReloadServer:
    """Snapshot all served inputs before accepting a browser connection."""

    module_name = _require_product_module_name(module_name, "server")
    artifacts = snapshot_regular_files(
        out_dir,
        (f"{module_name}.js", f"{module_name}.wasm"),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="outer-reload profile database artifacts",
    )
    args_gn = snapshot_regular_file(
        out_dir / "args.gn",
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="outer-reload selected args.gn",
    )
    validate_m7_output_configuration(args_gn)
    selected_host_dir = host_dir or Path(__file__).with_name("host")
    host_snapshots = snapshot_regular_files(
        selected_host_dir,
        (HOST_HTML_NAME, HOST_JS_NAME),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="outer-reload host resources",
    )
    runner_source = snapshot_regular_file(
        runner_source_path or Path(__file__),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="outer-reload runner source",
    )
    server = ChromeProfileDatabaseOuterReloadServer(
        (host, port), ChromeProfileDatabaseOuterReloadRequestHandler
    )
    server.args_gn = args_gn
    server.artifacts = artifacts
    server.host_html = host_snapshots[HOST_HTML_NAME]
    server.host_js = host_snapshots[HOST_JS_NAME]
    server.module_name = module_name
    server.ready_queue = queue.Queue(maxsize=2)
    server.receipt_lock = threading.Lock()
    server.result_queue = queue.Queue(maxsize=2)
    server.runner_source = runner_source
    server.session = OuterReloadSession(
        result_token,
        session,
        escrow,
        phase_two_navigation_type=phase_two_navigation_type,
    )
    return server


def _byte_identity(contents: bytes) -> dict[str, object]:
    return {"bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}


def artifact_identity(
    server: ChromeProfileDatabaseOuterReloadServer,
    *,
    module_name: str = PRODUCT_MODULE_NAME,
) -> dict[str, object]:
    module_name = _require_product_module_name(module_name, "artifact")
    if server.module_name != module_name:
        raise M0Error("outer-reload artifact module disagrees with server")
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
    server: ChromeProfileDatabaseOuterReloadServer,
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
        raise M0Error("outer-reload manifest lacks version metadata") from exc
    if not all(
        isinstance(value, str) and GIT_REVISION_RE.fullmatch(value)
        for value in versions.values()
    ):
        raise M0Error("outer-reload manifest version metadata is invalid")
    return versions


def smoke_url(
    server: ChromeProfileDatabaseOuterReloadServer,
    result_token: str,
    session: str,
    versions: dict[str, str],
    *,
    artifact: dict[str, object],
    capture_harness: dict[str, object],
    module_name: str = PRODUCT_MODULE_NAME,
    timeout_seconds: float,
) -> str:
    """Build the sole navigated URL without exposing a database value."""

    module_name = _require_product_module_name(module_name, "URL")
    if server.module_name != module_name:
        raise M0Error("outer-reload URL module disagrees with server")
    if not server.session.matches_result_token(result_token) or not server.session.matches_session(
        session
    ):
        raise M0Error("outer-reload URL capability disagrees with server")
    if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool):
        raise M0Error("outer-reload URL timeout is invalid")
    timeout_ms = int(float(timeout_seconds) * 1000)
    if timeout_ms < 1000 or timeout_ms > 120000:
        raise M0Error("outer-reload URL timeout is invalid")
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


def _require_exact_fields(
    value: object, expected: frozenset[str], description: str
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise M0Error(f"outer-reload {description} schema is invalid")
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


def _require_equal(value: dict[str, Any], field: str, expected: object) -> None:
    if not _exact_json_equal(value.get(field), expected):
        raise M0Error(f"outer-reload result {field} is invalid")


def _validate_byte_identity(value: object, description: str) -> None:
    identity = _require_exact_fields(value, _BYTE_IDENTITY_FIELDS, description)
    if type(identity.get("bytes")) is not int or identity["bytes"] < 1:
        raise M0Error(f"outer-reload {description} byte count is invalid")
    digest = identity.get("sha256")
    if type(digest) is not str or not SHA256_RE.fullmatch(digest):
        raise M0Error(f"outer-reload {description} SHA-256 is invalid")


def _validate_artifact_identity(
    value: object, expected_identity: dict[str, object]
) -> None:
    artifact = _require_exact_fields(value, _ARTIFACT_FIELDS, "artifact identity")
    if (
        artifact.get("artifact_delivery") != ARTIFACT_DELIVERY
        or artifact.get("artifact_source_provenance") != ARTIFACT_SOURCE_PROVENANCE
        or artifact.get("build_config_provenance") != BUILD_CONFIG_PROVENANCE
    ):
        raise M0Error("outer-reload artifact identity is invalid")
    _require_product_module_name(artifact.get("module_name"), "artifact")
    for field_name in ("build_config", "loader", "wasm"):
        _validate_byte_identity(artifact.get(field_name), f"artifact {field_name}")
    if not _exact_json_equal(artifact, expected_identity):
        raise M0Error("outer-reload artifact identity disagrees with snapshot")


def _validate_capture_harness_identity(
    value: object, expected_identity: dict[str, object]
) -> None:
    harness = _require_exact_fields(
        value, _CAPTURE_HARNESS_FIELDS, "capture harness identity"
    )
    if (
        harness.get("source_snapshot_provenance") != SOURCE_SNAPSHOT_PROVENANCE
        or harness.get("version_provenance") != VERSION_PROVENANCE
    ):
        raise M0Error("outer-reload capture harness identity is invalid")
    for field_name in ("host_html", "host_js", "runner_source"):
        _validate_byte_identity(harness.get(field_name), f"capture {field_name}")
    if not _exact_json_equal(harness, expected_identity):
        raise M0Error("outer-reload capture harness disagrees with snapshot")


def expected_markers(ordinal: int, escrow: TokenEscrow) -> list[str]:
    if ordinal == 1:
        return [
            f"{M7_DATABASE_MARKER_PREFIX}READY",
            f"{M7_DATABASE_MARKER_PREFIX}SQLITE_WRITE_ACCEPTED sha256="
            f"{escrow.token_a_digest}",
            f"{M7_DATABASE_MARKER_PREFIX}LEVELDB_WRITE_ACCEPTED sha256="
            f"{escrow.token_a_digest}",
            f"{M7_DATABASE_MARKER_PREFIX}DATABASES_CLOSED sha256="
            f"{escrow.token_a_digest}",
            f"{M7_DATABASE_MARKER_PREFIX}FENCE_OK sha256={escrow.token_a_digest}",
            f"{M7_DATABASE_MARKER_PREFIX}LEASE_RELEASED",
        ]
    if ordinal == 2:
        return [
            f"{M7_DATABASE_MARKER_PREFIX}READY",
            f"{M7_DATABASE_MARKER_PREFIX}SQLITE_READ_A_OK sha256="
            f"{escrow.token_a_digest}",
            f"{M7_DATABASE_MARKER_PREFIX}LEVELDB_READ_A_OK sha256="
            f"{escrow.token_a_digest}",
            f"{M7_DATABASE_MARKER_PREFIX}SQLITE_WRITE_ACCEPTED sha256="
            f"{escrow.token_b_digest}",
            f"{M7_DATABASE_MARKER_PREFIX}LEVELDB_WRITE_ACCEPTED sha256="
            f"{escrow.token_b_digest}",
            f"{M7_DATABASE_MARKER_PREFIX}DATABASES_CLOSED sha256="
            f"{escrow.token_b_digest}",
            f"{M7_DATABASE_MARKER_PREFIX}FENCE_OK sha256={escrow.token_b_digest}",
            f"{M7_DATABASE_MARKER_PREFIX}LEASE_RELEASED",
        ]
    raise M0Error("outer-reload marker ordinal is invalid")


def _validate_output(value: object, description: str) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_OUTPUT_LINES:
        raise M0Error(f"outer-reload {description} is invalid")
    if any(type(line) is not str for line in value):
        raise M0Error(f"outer-reload {description} contains a non-string")
    return value


def _validate_run(run: object, ordinal: int, escrow: TokenEscrow) -> str:
    run = _require_exact_fields(run, _RUN_FIELDS, f"run {ordinal}")
    expected = expected_markers(ordinal, escrow)
    if (
        type(run.get("ordinal")) is not int
        or run["ordinal"] != ordinal
        or run.get("mode") != _phase_mode(ordinal)
        or type(run.get("moduleIdentity")) is not str
        or not MODULE_ID_RE.fullmatch(run["moduleIdentity"])
        or run.get("freshModuleObject") is not True
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
        # The native lifecycle reports process exit synchronously, whereas
        # pthread printErr delivery can catch up afterwards.  The complete
        # marker sequence and the later quiet receipt are the acceptance
        # boundary; this field intentionally preserves the timing observation.
        or type(run.get("markerDeliveryCompleteAtProcessExit")) is not bool
        or run.get("processExitBeforeOnExit") is not True
        or run.get("markerSource") != "stderr-only"
        or run.get("markerSequenceAccepted") is not True
        or run.get("leaseReleasedMarkerObserved") is not True
        or run.get("activeClearedAfterLifecycle") is not True
        or run.get("postLifecycleTimerObserved") is not True
    ):
        raise M0Error(f"outer-reload run {ordinal} lifecycle is invalid")
    if (
        type(run.get("markerCount")) is not int
        or run["markerCount"] != len(expected)
        or run.get("markers") != expected
    ):
        raise M0Error(f"outer-reload run {ordinal} marker sequence is invalid")
    stdout = _validate_output(run.get("stdout"), f"run {ordinal} stdout")
    stderr = _validate_output(run.get("stderr"), f"run {ordinal} stderr")
    if any(line != SUPPRESSED_NATIVE_OUTPUT for line in stdout):
        raise M0Error(f"outer-reload run {ordinal} stdout grammar is invalid")
    if any(
        line != SUPPRESSED_NATIVE_OUTPUT and line not in expected for line in stderr
    ):
        raise M0Error(f"outer-reload run {ordinal} stderr grammar is invalid")
    if any(M7_DATABASE_MARKER_PREFIX in line for line in stdout):
        raise M0Error(f"outer-reload run {ordinal} emitted a marker on stdout")
    output = stdout + stderr
    if any(
        M7_DATABASE_PHASE_PREFIX in line
        or M7_ABORT_PC_PREFIX in line
        or "--wasm-profile-database-token" in line
        or "<redacted>" in line
        for line in output
    ):
        raise M0Error(f"outer-reload run {ordinal} leaked forbidden output")
    stderr_markers = [
        line for line in stderr if line.startswith(M7_DATABASE_MARKER_PREFIX)
    ]
    if stderr_markers != expected:
        raise M0Error(f"outer-reload run {ordinal} stderr markers are invalid")
    if any(
        M7_DATABASE_MARKER_PREFIX in line and line not in expected for line in stderr
    ):
        raise M0Error(f"outer-reload run {ordinal} marker is malformed")
    return run["moduleIdentity"]


def _validate_bridge(value: object) -> dict[str, Any]:
    bridge = _require_exact_fields(value, _BRIDGE_FIELDS, "bridge")
    for field_name, expected in {
        "protocol": 1,
        "permanent": True,
        "frozen": True,
        "installedBeforeModuleFactory": True,
        "processExitDispatches": 1,
        "noActiveProcessExitRejected": 0,
        "duplicateProcessExitRejected": 0,
        "lateProcessExitRejected": 0,
        "activeRunAtResult": None,
    }.items():
        if not _exact_json_equal(bridge.get(field_name), expected):
            raise M0Error(f"outer-reload bridge {field_name} is invalid")
    return bridge


def _validate_final_quiescence(value: object, bridge: dict[str, Any]) -> None:
    quiescence = _require_exact_fields(
        value, _FINAL_QUIESCENCE_FIELDS, "final quiescence"
    )
    for field_name, expected in {
        "taskScheduledExactlyOnce": True,
        "taskMethod": "setTimeout(...,0)",
        "postLifecycleTimerObservedBeforeTask": True,
        "started": True,
        "startedAfterActiveClear": True,
        "completed": True,
        "quietWindowMs": FINAL_QUIESCENCE_MS,
        "quiet": True,
        "processExitReportsAtActiveClear": 1,
        "processExitReportsAtTaskStart": 1,
        "processExitReportsAtTaskEnd": 1,
        "processExitReportsAtPreUploadCheck": 1,
        "activeRunAtActiveClear": None,
        "activeRunAtTaskStart": None,
        "activeRunAtTaskEnd": None,
        "activeRunAtPreUploadCheck": None,
        "bridgeRecheckedImmediatelyBeforeUpload": True,
    }.items():
        if not _exact_json_equal(quiescence.get(field_name), expected):
            raise M0Error(f"outer-reload final quiescence {field_name} is invalid")
    callback_fields = (
        "callbacksAtActiveClear",
        "callbacksAtTaskStart",
        "callbacksAtTaskEnd",
        "callbacksAtPreUploadCheck",
    )
    if any(
        type(quiescence.get(field_name)) is not int or quiescence[field_name] < 0
        for field_name in callback_fields
    ):
        raise M0Error("outer-reload final quiescence callback evidence is invalid")
    if len({quiescence[field_name] for field_name in callback_fields}) != 1:
        raise M0Error("outer-reload final quiescence is not quiet")
    if (
        quiescence["processExitReportsAtPreUploadCheck"]
        != bridge["processExitDispatches"]
    ):
        raise M0Error("outer-reload final quiescence bridge evidence disagrees")


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
        raise M0Error("outer-reload token evidence is invalid")


def _validate_host_boundary(value: object) -> None:
    boundary = _require_exact_fields(value, _HOST_BOUNDARY_FIELDS, "host boundary")
    if any(field_value is not False for field_value in boundary.values()):
        raise M0Error("outer-reload host crossed a prohibited boundary")


def _validate_document(
    value: object, ordinal: int, expected_document: DocumentEvidence
) -> DocumentEvidence:
    document = _require_exact_fields(value, _DOCUMENT_FIELDS, "document receipt")
    time_origin = document.get("timeOrigin")
    if (
        document.get("navigationType") != expected_document.navigation_type
        or not isinstance(time_origin, (int, float))
        or isinstance(time_origin, bool)
        or not math.isfinite(float(time_origin))
        or float(time_origin) <= 0
    ):
        raise M0Error("outer-reload document receipt is invalid")
    actual = DocumentEvidence(document["navigationType"], float(time_origin))
    if actual != expected_document:
        raise M0Error("outer-reload document receipt disagrees with bootstrap")
    return actual


def _validate_no_prohibited_strings(value: object, prohibited: tuple[str, ...]) -> None:
    """Reject secrets even when a hostile receipt puts them in an unused field."""

    def visit(item: object, depth: int) -> None:
        if depth > 32:
            raise M0Error("outer-reload receipt nesting is invalid")
        if isinstance(item, str):
            if any(secret in item for secret in prohibited):
                raise M0Error("outer-reload receipt contains a prohibited value")
            return
        if isinstance(item, list):
            for child in item:
                visit(child, depth + 1)
            return
        if isinstance(item, dict):
            for key, child in item.items():
                visit(key, depth + 1)
                visit(child, depth + 1)

    visit(value, 0)


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
    """Validate one redacted phase receipt without retaining its raw payload."""

    _validate_no_prohibited_strings(
        result, (escrow.token_a, escrow.token_b, result_token, session)
    )
    result = _require_exact_fields(result, _RESULT_FIELDS, "result")
    for field_name, expected in {
        "protocol": 1,
        "case": CASE,
        "scope": SCOPE,
        "status": "pass",
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
    document = _validate_document(
        result.get("document"), ordinal, expected_document
    )
    _validate_token_evidence(result.get("tokenEvidence"), ordinal, escrow)
    module_identity = _validate_run(result.get("run"), ordinal, escrow)
    bridge = _validate_bridge(result.get("bridge"))
    _validate_final_quiescence(result.get("finalQuiescence"), bridge)
    _validate_host_boundary(result.get("hostBoundary"))
    return PhaseResult(
        ordinal=ordinal,
        origin=expected_origin,
        navigation_type=document.navigation_type,
        time_origin=document.time_origin,
        module_identity=module_identity,
    )


def validate_ready_receipt(
    ready: dict[str, Any], *, expected: PhaseResult
) -> None:
    ready = _require_exact_fields(ready, _READY_FIELDS, "ready receipt")
    if (
        type(ready.get("protocol")) is not int
        or ready.get("protocol") != 1
        or ready.get("case") != CASE
        or ready.get("scope") != SCOPE
        or type(ready.get("ordinal")) is not int
        or ready.get("ordinal") != expected.ordinal
    ):
        raise M0Error("outer-reload ready receipt identity is invalid")
    time_origin = ready.get("timeOrigin")
    if (
        not isinstance(time_origin, (int, float))
        or isinstance(time_origin, bool)
        or not math.isfinite(float(time_origin))
        or float(time_origin) != expected.time_origin
    ):
        raise M0Error("outer-reload ready receipt time origin is invalid")


def validate_outer_document_transition(
    first: PhaseResult,
    second: PhaseResult,
    *,
    phase_two_navigation_type: str = "reload",
) -> None:
    if (
        phase_two_navigation_type not in ("navigate", "reload")
        or
        first.ordinal != 1
        or second.ordinal != 2
        or first.origin != second.origin
        or first.navigation_type != "navigate"
        or second.navigation_type != phase_two_navigation_type
        or second.time_origin <= first.time_origin
        or first.module_identity == second.module_identity
    ):
        raise M0Error("outer-reload two-document transition is invalid")


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
    byte_count = 0
    while True:
        chunk = response.read(1024 * 1024)
        if not chunk:
            break
        byte_count += len(chunk)
        digest.update(chunk)
    return byte_count, digest.hexdigest()


def verify_server_delivery(server: ChromeProfileDatabaseOuterReloadServer) -> None:
    """Verify static execution inputs come from immutable in-memory copies.

    Bootstrap is intentionally excluded: it is a one-shot secret-bearing body
    and must only be consumed by the page that needs it.
    """

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
                raise M0Error("outer-reload snapshot request failed")
            headers = {key.lower(): value for key, value in response.getheaders()}
            for name, expected_value in _expected_headers(content_type).items():
                actual = headers.get(name, "")
                if name == "content-type":
                    actual = actual.split(";", 1)[0].strip().lower()
                if actual != expected_value:
                    raise M0Error("outer-reload snapshot response header is invalid")
            byte_count, digest = _stream_response_digest(response)
            if byte_count != len(contents) or digest != hashlib.sha256(contents).hexdigest():
                raise M0Error("outer-reload snapshot body changed")
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
                f"outer-reload {kind} timed out "
                f"({len(browser_stderr)} browser stderr lines suppressed)"
            )
        try:
            receipt_ordinal, receipt = receipts.get(timeout=min(0.1, remaining))
        except queue.Empty:
            if browser.poll() is not None:
                raise M0Error(
                    f"outer-reload browser exited before {kind} "
                    f"({len(browser_stderr)} browser stderr lines suppressed)"
                )
            continue
        if receipt_ordinal != ordinal:
            raise M0Error("outer-reload receipt order is invalid")
        return receipt


def wait_for_phase_result(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    server: ChromeProfileDatabaseOuterReloadServer,
    ordinal: int,
    deadline: float,
) -> dict[str, Any]:
    return _wait_for_receipt(
        browser, browser_stderr, server.result_queue, ordinal, deadline, "result"
    )


def wait_for_ready_receipt(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    server: ChromeProfileDatabaseOuterReloadServer,
    ordinal: int,
    deadline: float,
) -> dict[str, Any]:
    return _wait_for_receipt(
        browser, browser_stderr, server.ready_queue, ordinal, deadline, "ready receipt"
    )


def _root_frame_identity(value: object) -> RootFrameIdentity:
    if not isinstance(value, dict):
        raise M0Error("outer-reload DevTools frame tree is invalid")
    tree = value.get("frameTree")
    if not isinstance(tree, dict):
        raise M0Error("outer-reload DevTools frame tree is invalid")
    frame = tree.get("frame")
    if (
        not isinstance(frame, dict)
        or "parentId" in frame
        or not isinstance(frame.get("id"), str)
        or not frame["id"]
        or not isinstance(frame.get("loaderId"), str)
        or not frame["loaderId"]
    ):
        raise M0Error("outer-reload DevTools root frame is invalid")
    return RootFrameIdentity(frame["id"], frame["loaderId"])


def prepare_outer_document_reload(client: Any) -> RootFrameIdentity:
    """Enable Page events and capture the pre-reload root-frame identity."""

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
        raise M0Error("outer-reload DevTools navigation event is invalid")
    frame = params.get("frame")
    if not isinstance(frame, dict):
        raise M0Error("outer-reload DevTools navigation event is invalid")
    if frame.get("id") != baseline.frame_id:
        return None
    if "parentId" in frame:
        raise M0Error("outer-reload DevTools root frame changed parent")
    loader_id = frame.get("loaderId")
    url = frame.get("url")
    if not isinstance(loader_id, str) or not loader_id:
        raise M0Error("outer-reload DevTools navigation loader is invalid")
    if loader_id == baseline.loader_id:
        # Page.enable may queue an event for the already-loaded document.
        return None
    if not isinstance(url, str) or not url.startswith(expected_page_url_prefix):
        raise M0Error("outer-reload DevTools navigation URL is invalid")
    return RootFrameIdentity(baseline.frame_id, loader_id)


def wait_for_root_reload_navigation(
    client: Any,
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    baseline: RootFrameIdentity,
    expected_page_url_prefix: str,
    deadline: float,
) -> RootFrameIdentity:
    """Require a same-frame, changed-loader Page.frameNavigated event."""

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M0Error(
                "outer-reload DevTools navigation timed out "
                f"({len(browser_stderr)} browser stderr lines suppressed)"
            )
        if browser.poll() is not None:
            raise M0Error(
                "outer-reload browser exited before DevTools navigation "
                f"({len(browser_stderr)} browser stderr lines suppressed)"
            )
        event = client.next_event(min(0.1, remaining))
        candidate = _root_reload_event(
            event,
            baseline=baseline,
            expected_page_url_prefix=expected_page_url_prefix,
        ) if event is not None else None
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
    """Reload once and retain CDP until the replacement frame is observed."""

    client.call("Page.reload", {"ignoreCache": True})
    return wait_for_root_reload_navigation(
        client,
        browser,
        browser_stderr,
        baseline,
        expected_page_url_prefix,
        deadline,
    )


def _browser_devtools_websocket_url(port: int, deadline: float) -> str:
    """Return only the browser-wide loopback DevTools endpoint."""

    endpoint = f"http://127.0.0.1:{port}/json/version"
    last_error = "outer-reload browser DevTools endpoint did not become ready"
    while time.monotonic() < deadline:
        try:
            with urlopen(endpoint, timeout=1) as response:
                value = json.loads(response.read().decode("utf-8"))
            websocket_url = (
                value.get("webSocketDebuggerUrl") if isinstance(value, dict) else None
            )
            parsed = urlsplit(websocket_url) if isinstance(websocket_url, str) else None
            if (
                parsed is None
                or parsed.scheme != "ws"
                or parsed.hostname != "127.0.0.1"
                or parsed.port != port
                or not parsed.path.startswith("/devtools/browser/")
                or parsed.query
                or parsed.fragment
            ):
                raise M0Error("outer-reload browser DevTools endpoint is invalid")
            return websocket_url
        except (OSError, UnicodeDecodeError, ValueError, M0Error) as error:
            last_error = str(error)
        time.sleep(0.05)
    raise M0Error(last_error)


def wait_for_browser_client(port: int, deadline: float) -> DevToolsClient:
    """Connect to Chrome's browser-wide DevTools target on one loopback port."""

    return DevToolsClient(_browser_devtools_websocket_url(port, deadline))


def close_outer_browser_cleanly(
    launch: OuterBrowserLaunch,
    page_client: Any,
    deadline: float,
) -> OuterBrowserCloseEvidence:
    """Close one host Chrome through CDP and prove its group is fully gone."""

    browser = launch.browser
    if browser.poll() is not None:
        raise M0Error("outer-reload browser exited before its requested clean close")
    browser_client: DevToolsClient | None = None
    try:
        browser_client = wait_for_browser_client(launch.debug_port, deadline)
        acknowledgement = browser_client.call("Browser.close")
        if not isinstance(acknowledgement, dict):
            raise M0Error("outer-reload Browser.close acknowledgement is invalid")
    finally:
        if browser_client is not None:
            browser_client.close()
        page_client.close()

    close_deadline = min(
        deadline, time.monotonic() + OUTER_BROWSER_CLOSE_TIMEOUT_SECONDS
    )
    remaining = close_deadline - time.monotonic()
    if remaining <= 0:
        raise M0Error("outer-reload browser clean close timed out")
    wait_for_browser_group_exit(
        browser,
        launch.stderr_reader,
        remaining,
        description="outer-reload browser",
    )
    return OuterBrowserCloseEvidence(
        browser_close_acknowledged=True,
        zero_exit_status=browser.returncode == 0,
        stderr_eof=launch.stderr_reader.reached_eof,
        process_group_gone=True,
    )


def launch_outer_browser(
    browser_path: Path,
    profile_path: str,
    url: str,
    *,
    no_sandbox: bool,
    browser_stderr: deque[str],
    escrow: TokenEscrow,
    raw_token_seen: threading.Event,
) -> OuterBrowserLaunch:
    """Start one independently observable outer Chrome process."""

    debug_port = unused_loopback_port()
    command = browser_command(browser_path, profile_path, url, no_sandbox=no_sandbox)
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
        name="chromium-wasm-m7-profile-database-outer-reload-browser-stderr",
        transform_record=lambda record: redact_browser_stderr_record(
            record, escrow, raw_token_seen
        ),
    )
    try:
        stderr_reader.start()
    except BaseException:
        abort_browser_group(browser, stderr_reader)
        raise
    return OuterBrowserLaunch(
        browser=browser,
        debug_port=debug_port,
        profile_path=profile_path,
        url=url,
        stderr_reader=stderr_reader,
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
    """Write only runner-owned, non-secret failure state when requested."""

    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / "chrome-profile-database-outer-reload-m7-failure.json"
    payload = {
        "schema_version": 1,
        "runner": "run_m7_chrome_profile_database_outer_reload_dom_smoke.py",
        "case": CASE,
        "scope": SCOPE,
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
    server: ChromeProfileDatabaseOuterReloadServer | None,
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
            raise M0Error("outer-reload server did not stop")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run two Chrome Wasm profile-database documents separated by a "
            "real DevTools page transition."
        ),
        epilog=(
            "Build the normal artifact with: buildtools/linux64/gn gen "
            "out/wasm-chrome-m7-profile-database --args='"
            + DEFAULT_GN_ARGUMENTS
            + "' --fail-on-unused-args; autoninja -C "
            "out/wasm-chrome-m7-profile-database chrome_wasm"
        ),
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--diagnostics-dir", type=Path)
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument(
        "--fresh-outer-browser-after-phase-one",
        action="store_true",
        help=(
            "require a clean first outer Chrome exit, then run phase two in "
            "a distinct Chrome process using the same temporary user-data "
            "directory and same-origin server"
        ),
    )
    parser.add_argument("--timeout", type=parse_timeout, default=120.0)
    args = parser.parse_args()
    if args.timeout < MIN_TIMEOUT_SECONDS:
        parser.error(f"--timeout must be at least {MIN_TIMEOUT_SECONDS:g} seconds")

    active_launch: OuterBrowserLaunch | None = None
    browser_stderr: deque[str] = deque(maxlen=MAX_BROWSER_STDERR_LINES)
    browser_stderr_raw_token_seen = threading.Event()
    client: Any | None = None
    outer_profile: tempfile.TemporaryDirectory[str] | None = None
    server: ChromeProfileDatabaseOuterReloadServer | None = None
    server_thread: threading.Thread | None = None
    server_thread_started = False
    result_ordinals_received: set[int] = set()
    ready_ordinals_received: set[int] = set()
    stage = "initialize"
    successful = False
    failure_reported = False
    first_outer_launch: OuterBrowserLaunch | None = None
    first_outer_browser_close: OuterBrowserCloseEvidence | None = None
    final_outer_browser_close: OuterBrowserCloseEvidence | None = None
    outer_browser_processes_started = 0
    second_outer_browser_identity_distinct = False
    same_outer_profile_for_phase_two = False
    same_origin_for_phase_two = False
    phase_two_sqlite_and_leveldb_read_a_validated = False
    phase_two_fresh_document_time_origin = False
    fresh_outer_browser_persistence_proven = False
    phase_two_navigation_type = (
        "navigate" if args.fresh_outer_browser_after_phase_one else "reload"
    )

    try:
        stage = "load-manifest"
        versions = toolchain_manifest_versions(load_manifest())
        stage = "create-token-escrow"
        result_token, session = new_capability_pair()
        escrow = new_token_escrow()
        stage = "create-server"
        server = create_server(
            "127.0.0.1",
            0,
            args.out_dir,
            result_token,
            session,
            escrow,
            phase_two_navigation_type=phase_two_navigation_type,
        )
        artifact = artifact_identity(server)
        capture_harness = capture_harness_identity(server)
        server_thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.05},
            name="chromium-wasm-m7-profile-database-outer-reload-server",
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
            prefix="chromium-wasm-m7-profile-database-outer-reload-"
        )
        stage = "launch-browser"
        active_launch = launch_outer_browser(
            browser_path,
            outer_profile.name,
            url,
            no_sandbox=args.no_sandbox,
            browser_stderr=browser_stderr,
            escrow=escrow,
            raw_token_seen=browser_stderr_raw_token_seen,
        )
        first_outer_launch = active_launch
        outer_browser_processes_started += 1
        deadline = time.monotonic() + args.timeout
        expected_page_url_prefix = url.split("?", 1)[0]

        stage = "connect-devtools-phase-one"
        client = wait_for_page_client(
            active_launch.debug_port, expected_page_url_prefix, deadline
        )
        stage = "wait-phase-one-result"
        first_result = wait_for_phase_result(
            active_launch.browser, browser_stderr, server, 1, deadline
        )
        result_ordinals_received.add(1)
        stage = "validate-phase-one-result"
        first_document = server.session.document_evidence(1)
        first = validate_phase_result(
            first_result,
            ordinal=1,
            expected_versions=versions,
            expected_artifact_identity=artifact,
            expected_capture_harness_identity=capture_harness,
            expected_origin=expected_origin,
            expected_document=first_document,
            escrow=escrow,
            result_token=result_token,
            session=session,
        )
        stage = "wait-phase-one-ready"
        first_ready = wait_for_ready_receipt(
            active_launch.browser, browser_stderr, server, 1, deadline
        )
        ready_ordinals_received.add(1)
        stage = "validate-phase-one-ready"
        validate_ready_receipt(first_ready, expected=first)
        if args.fresh_outer_browser_after_phase_one:
            stage = "close-first-outer-browser"
            first_outer_browser_close = close_outer_browser_cleanly(
                active_launch, client, deadline
            )
            client = None
            active_launch = None
            stage = "arm-phase-two-fresh-browser-document-evidence"
            server.session.arm_phase_two_document_evidence(first.time_origin)
            stage = "launch-fresh-outer-browser-phase-two"
            next_launch = launch_outer_browser(
                browser_path,
                outer_profile.name,
                url,
                no_sandbox=args.no_sandbox,
                browser_stderr=browser_stderr,
                escrow=escrow,
                raw_token_seen=browser_stderr_raw_token_seen,
            )
            outer_browser_processes_started += 1
            active_launch = next_launch
            if (
                first_outer_launch is None
                or active_launch.browser.pid == first_outer_launch.browser.pid
                or active_launch.profile_path != first_outer_launch.profile_path
                or active_launch.url != first_outer_launch.url
            ):
                raise M0Error("outer-reload fresh browser identity is invalid")
            second_outer_browser_identity_distinct = True
            same_outer_profile_for_phase_two = True
            stage = "connect-devtools-phase-two-fresh-browser"
            client = wait_for_page_client(
                active_launch.debug_port, expected_page_url_prefix, deadline
            )
        else:
            stage = "prepare-cdp-outer-reload"
            root_frame = prepare_outer_document_reload(client)
            stage = "arm-phase-two-document-evidence"
            server.session.arm_phase_two_document_evidence(first.time_origin)
            stage = "reload-outer-document"
            reload_outer_document(
                client,
                active_launch.browser,
                browser_stderr,
                root_frame,
                expected_page_url_prefix,
                deadline,
            )
        stage = "wait-phase-two-result"
        second_result = wait_for_phase_result(
            active_launch.browser, browser_stderr, server, 2, deadline
        )
        result_ordinals_received.add(2)
        stage = "validate-phase-two-result"
        second_document = server.session.document_evidence(2)
        second = validate_phase_result(
            second_result,
            ordinal=2,
            expected_versions=versions,
            expected_artifact_identity=artifact,
            expected_capture_harness_identity=capture_harness,
            expected_origin=expected_origin,
            expected_document=second_document,
            escrow=escrow,
            result_token=result_token,
            session=session,
        )
        stage = "wait-phase-two-ready"
        second_ready = wait_for_ready_receipt(
            active_launch.browser, browser_stderr, server, 2, deadline
        )
        ready_ordinals_received.add(2)
        stage = "validate-phase-two-ready"
        validate_ready_receipt(second_ready, expected=second)
        phase_two_sqlite_and_leveldb_read_a_validated = True
        phase_two_fresh_document_time_origin = second.time_origin > first.time_origin
        if args.fresh_outer_browser_after_phase_one:
            same_origin_for_phase_two = second.origin == expected_origin
            fresh_outer_browser_persistence_proven = (
                has_fresh_outer_browser_database_persistence_evidence(
                    outer_browser_processes_started=outer_browser_processes_started,
                    first_outer_browser_close=first_outer_browser_close,
                    second_outer_browser_identity_distinct=(
                        second_outer_browser_identity_distinct
                    ),
                    same_outer_profile_for_phase_two=same_outer_profile_for_phase_two,
                    same_origin_for_phase_two=same_origin_for_phase_two,
                    phase_two_navigation_type=phase_two_navigation_type,
                    phase_two=second,
                    phase_two_sqlite_and_leveldb_read_a_validated=(
                        phase_two_sqlite_and_leveldb_read_a_validated
                    ),
                    phase_two_fresh_document_time_origin=(
                        phase_two_fresh_document_time_origin
                    ),
                )
            )
        stage = "validate-two-document-transition"
        validate_outer_document_transition(
            first, second, phase_two_navigation_type=phase_two_navigation_type
        )
        stage = "close-final-outer-browser"
        final_outer_browser_close = close_outer_browser_cleanly(
            active_launch, client, deadline
        )
        client = None
        active_launch = None
        successful = True
    except Exception as error:
        if args.diagnostics_dir is not None:
            try:
                write_failure_diagnostics(
                    args.diagnostics_dir,
                    stage=stage,
                    error=error,
                    browser=(
                        active_launch.browser if active_launch is not None else None
                    ),
                    browser_stderr=browser_stderr,
                    result_ordinals_received=result_ordinals_received,
                    ready_ordinals_received=ready_ordinals_received,
                )
            except OSError:
                pass
        print(f"{SENTINEL}:FAIL stage={stage}", file=sys.stderr, flush=True)
        failure_reported = True
    finally:
        if client is not None:
            client.close()
        if active_launch is not None:
            try:
                abort_browser_group(active_launch.browser, active_launch.stderr_reader)
            except M0Error:
                successful = False
        if browser_stderr_raw_token_seen.is_set():
            successful = False
        try:
            _stop_server(server, server_thread, server_thread_started)
        except M0Error:
            successful = False
        if outer_profile is not None:
            try:
                outer_profile.cleanup()
            except OSError:
                successful = False

    if browser_stderr_raw_token_seen.is_set():
        if not failure_reported:
            print(
                f"{SENTINEL}:FAIL stage=browser-stderr-token-hygiene",
                file=sys.stderr,
                flush=True,
            )
        return 1
    if not successful:
        return 1
    print(
        SENTINEL
        + ":PASS "
        + json.dumps(
            {
                "case": CASE,
                "documents": 2,
                "freshOuterBrowserAfterPhaseOne": args.fresh_outer_browser_after_phase_one,
                "freshOuterBrowserProcessSourceSelectedSqliteLevelDbPersistenceProven": (
                    fresh_outer_browser_persistence_proven
                ),
                "outerBrowserProcesses": outer_browser_processes_started,
                "phaseTwoTransition": (
                    "outer-browser-restart"
                    if args.fresh_outer_browser_after_phase_one
                    else "page-reload"
                ),
                "firstOuterBrowserCloseAcknowledged": (
                    first_outer_browser_close is not None
                    and first_outer_browser_close.browser_close_acknowledged
                ),
                "firstOuterBrowserGracefulClose": (
                    first_outer_browser_close is not None
                    and first_outer_browser_close.zero_exit_status
                    and first_outer_browser_close.stderr_eof
                    and first_outer_browser_close.process_group_gone
                ),
                "firstOuterBrowserForcedTermination": (
                    False if args.fresh_outer_browser_after_phase_one else None
                ),
                "sameOuterBrowserProfileDirectoryForPhaseTwo": (
                    same_outer_profile_for_phase_two
                ),
                "sameOriginForPhaseTwo": same_origin_for_phase_two,
                "phaseTwoSqliteAndLevelDbReadAValidated": (
                    phase_two_sqlite_and_leveldb_read_a_validated
                ),
                "phaseTwoFreshDocumentTimeOrigin": (
                    phase_two_fresh_document_time_origin
                ),
                "finalOuterBrowserGracefulClose": (
                    final_outer_browser_close is not None
                    and final_outer_browser_close.browser_close_acknowledged
                    and final_outer_browser_close.zero_exit_status
                    and final_outer_browser_close.stderr_eof
                    and final_outer_browser_close.process_group_gone
                ),
                "m7GateComplete": False,
                "fullChromiumProfileProven": False,
                "physicalCrashBehaviorProven": False,
                "outerDocumentReload": not args.fresh_outer_browser_after_phase_one,
                "rawDatabaseTokensSerialized": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
