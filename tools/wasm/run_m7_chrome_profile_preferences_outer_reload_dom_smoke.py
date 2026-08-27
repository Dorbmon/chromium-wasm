#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run an optional three-outer-document Chrome Preferences/History witness.

Every document runs the dedicated Preferences mode plus a fixed real Browser
lifecycle and directly owned core HistoryService. The Browser close and the
History/Favicons backend-close marker must precede the Preferences fence.
Document one writes A and History A. After its exact, redacted lifecycle
receipt and flushed ready acknowledgement, this runner issues a DevTools
``Page.reload`` command. Document two reads A and History A before it writes B
and History B. After the same flushed ready barrier, the runner issues one
further DevTools ``Page.reload``; document three reads B and History A/B.

This is deliberately non-gating and makes no crash-recovery, normal navigation
history, desktop History UI/bookmark graph, cookies, web-storage,
service-worker, contender, or M7-complete claim. It proves only a direct core
HistoryService History/Favicons SQLite probe within the dedicated profile
mount. The private A/B values exist only in this process's in-memory escrow and
in each one-shot bootstrap response body; no URL, page receipt, diagnostic,
browser stderr, or stdout contains them.

Each later bootstrap requires all of: validated predecessor ready state,
runner arming, a fresh top-level Fetch-Metadata document navigation, and a
flushed ``reload`` document-evidence POST with a newer time origin. The
retained CDP client independently requires that each Page.reload replace the
same root frame with a new loader. No host JavaScript self-navigates.
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

from m0_common import M0Error, REPO_ROOT, load_manifest, parse_timeout
from m4_cdp import unused_loopback_port, wait_for_page_client
from m9_descriptor_snapshot import snapshot_regular_file, snapshot_regular_files
from run_browser_smoke import browser_command, drain_stream, find_browser, stop_browser


SENTINEL = "CHROMIUM_WASM_M7_CHROME_PROFILE_PREFERENCES_OUTER_RELOAD_DOM"
CASE = "chrome_profile_preferences_three_outer_document_reload_m7"
SCOPE = (
    "same-origin-three-outer-documents-chrome-wasm-m7-profile-preferences-and-"
    "history-test-modules-orderly-reload-only"
)
PRODUCT_MODULE_NAME = "chrome_wasm_m7_profile_preferences_test"
PRODUCT_GN_TARGET = "//chrome:chrome_wasm"
PRODUCT_GN_ENABLE_ARGUMENT = "enable_chromium_wasm_m7_profile_preferences_test=true"
DEFAULT_OUT_DIR = Path("out/wasm-chrome-m7-profile-preferences")
DEFAULT_GN_ARGUMENTS = (
    'import("//out/wasm-chrome-m6/args.gn") ' + PRODUCT_GN_ENABLE_ARGUMENT
)
BUILD_CONFIG_PROVENANCE = "selected-out-dir-args-gn-immutable-snapshot"
HOST_ROOT = "/__m7_chrome_profile_preferences_outer_reload__"
HOST_HTML_NAME = "chrome_wasm_profile_preferences_outer_reload_smoke.html"
HOST_JS_NAME = "chrome_wasm_profile_preferences_outer_reload_smoke.js"
ARTIFACT_DELIVERY = "immutable-in-memory-server-snapshot"
ARTIFACT_SOURCE_PROVENANCE = "unverified"
SOURCE_SNAPSHOT_PROVENANCE = (
    "on-disk-byte-snapshots-at-server-startup-not-commit-provenance"
)
VERSION_PROVENANCE = (
    "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance"
)
SUPPRESSED_NATIVE_OUTPUT = "<suppressed-native-output>"
M7_MARKER_PREFIX = "CHROMIUM_WASM_M7_PREFS:"

MAX_RESULT_BYTES = 512 * 1024
MAX_READY_BYTES = 8 * 1024
MAX_BOOTSTRAP_DOCUMENT_BYTES = 8 * 1024
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024 * 1024
MAX_OUTPUT_LINES = 128
MAX_BROWSER_STDERR_LINES = 300
FINAL_QUIESCENCE_MS = 50
MIN_TIMEOUT_SECONDS = 20.0
MAX_TIMEOUT_MS = 300_000

CAPABILITY_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
GIT_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MODULE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
M7_GN_ENABLE_ASSIGNMENT_RE = re.compile(
    r"^[ \t]*enable_chromium_wasm_m7_profile_preferences_test[ \t]*="
    r"[ \t]*(true|false)[ \t]*(?:#.*)?$",
    re.MULTILINE,
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
_ROOT_QUERY_FIELDS = frozenset(
    (
        "resultToken",
        "session",
        "module",
        "timeoutMs",
        "versions",
        "artifact",
        "captureHarness",
    )
)


@dataclass(frozen=True)
class TokenEscrow:
    """Raw values are intentionally excluded from dataclass representations."""

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


@dataclass(frozen=True)
class RootFrameIdentity:
    frame_id: str
    loader_id: str


class ProtocolStateError(M0Error):
    """Fixed server state conflict; callers must never expose capability data."""


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def new_token_escrow() -> TokenEscrow:
    token_a = secrets.token_hex(32)
    token_b = secrets.token_hex(32)
    while secrets.compare_digest(token_a, token_b):
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
    while secrets.compare_digest(result_token, session):
        session = secrets.token_urlsafe(24)
    if not CAPABILITY_RE.fullmatch(result_token) or not CAPABILITY_RE.fullmatch(session):
        raise M0Error("outer-reload capability generation is invalid")
    return result_token, session


def _phase_mode(ordinal: int) -> str:
    if ordinal == 1:
        return "write"
    if ordinal == 2:
        return "verify-and-write"
    if ordinal == 3:
        return "verify-b"
    raise M0Error("outer-reload phase ordinal is invalid")


def _valid_document(value: object) -> bool:
    return (
        isinstance(value, DocumentEvidence)
        and value.navigation_type in ("navigate", "reload")
        and isinstance(value.time_origin, float)
        and math.isfinite(value.time_origin)
        and value.time_origin > 0
    )


class OuterReloadSession:
    """In-memory escrow and phase machine for one browser lifetime."""

    def __init__(self, result_token: str, session: str, escrow: TokenEscrow):
        if (
            not CAPABILITY_RE.fullmatch(result_token)
            or not CAPABILITY_RE.fullmatch(session)
            or secrets.compare_digest(result_token, session)
            or not SHA256_RE.fullmatch(escrow.token_a)
            or not SHA256_RE.fullmatch(escrow.token_b)
            or secrets.compare_digest(escrow.token_a, escrow.token_b)
            or escrow.token_a_digest != _sha256_text(escrow.token_a)
            or escrow.token_b_digest != _sha256_text(escrow.token_b)
        ):
            raise M0Error("outer-reload escrow is invalid")
        self._result_token = result_token
        self._session = session
        self.escrow = escrow
        self._lock = threading.Lock()
        # Held by POST from acceptance through 204 flush and state commit.
        self._ack_gate = threading.Lock()
        self._bootstrap_served: set[int] = set()
        self._results: set[int] = set()
        self._ready: set[int] = set()
        self._phase_one: DocumentEvidence | None = None
        self._phase_two: DocumentEvidence | None = None
        self._phase_three: DocumentEvidence | None = None
        self._pending: tuple[int, DocumentEvidence] | None = None
        self._phase_one_validated_time: float | None = None
        self._phase_two_validated_time: float | None = None
        self._phase_two_armed = False
        self._phase_three_armed = False
        self._top_level_reload_seen_for: int | None = None

    def matches_result_token(self, value: object) -> bool:
        return isinstance(value, str) and secrets.compare_digest(value, self._result_token)

    def matches_session(self, value: object) -> bool:
        return isinstance(value, str) and secrets.compare_digest(value, self._session)

    def acknowledgement_gate(self) -> threading.Lock:
        return self._ack_gate

    def accept_document(self, session: str, evidence: DocumentEvidence) -> bool:
        if not self.matches_session(session):
            return False
        if not _valid_document(evidence):
            raise ProtocolStateError("outer-reload document evidence is invalid")
        with self._lock:
            if self._phase_one is None:
                if (
                    evidence.navigation_type != "navigate"
                    or self._bootstrap_served
                    or self._pending is not None
                ):
                    raise ProtocolStateError("outer-reload document state conflict")
                self._pending = (1, evidence)
                return True
            if self._phase_two is None:
                if (
                    not self._phase_two_armed
                    or self._top_level_reload_seen_for != 2
                    or self._pending is not None
                    or 2 in self._bootstrap_served
                    or evidence.navigation_type != "reload"
                    or self._phase_one_validated_time is None
                    or evidence.time_origin <= self._phase_one_validated_time
                ):
                    raise ProtocolStateError("outer-reload document state conflict")
                self._pending = (2, evidence)
                return True
            if (
                not self._phase_three_armed
                or self._top_level_reload_seen_for != 3
                or self._phase_three is not None
                or self._pending is not None
                or 3 in self._bootstrap_served
                or evidence.navigation_type != "reload"
                or self._phase_two_validated_time is None
                or evidence.time_origin <= self._phase_two_validated_time
            ):
                raise ProtocolStateError("outer-reload document state conflict")
            self._pending = (3, evidence)
            return True

    def acknowledge_document(self, session: str) -> None:
        if not self.matches_session(session):
            raise ProtocolStateError("outer-reload acknowledgement conflict")
        with self._lock:
            if self._pending is None:
                raise ProtocolStateError("outer-reload acknowledgement conflict")
            ordinal, evidence = self._pending
            if ordinal == 1 and self._phase_one is None:
                self._phase_one = evidence
            elif ordinal == 2 and self._phase_two is None:
                self._phase_two = evidence
            elif ordinal == 3 and self._phase_three is None:
                self._phase_three = evidence
            else:
                raise ProtocolStateError("outer-reload acknowledgement conflict")
            self._pending = None

    def bootstrap_payload(self, session: str) -> dict[str, object] | None:
        """Claim a raw bootstrap body only after the flushed POST boundary."""

        if not self.matches_session(session):
            return None
        with self._ack_gate:
            with self._lock:
                if self._phase_one is not None and 1 not in self._bootstrap_served:
                    ordinal = 1
                elif self._phase_two is not None and 2 not in self._bootstrap_served:
                    ordinal = 2
                elif self._phase_three is not None and 3 not in self._bootstrap_served:
                    ordinal = 3
                else:
                    raise ProtocolStateError("outer-reload bootstrap state conflict")
                self._bootstrap_served.add(ordinal)
        return {
            "protocol": 1,
            "case": CASE,
            "scope": SCOPE,
            "ordinal": ordinal,
            "mode": _phase_mode(ordinal),
            "tokenA": None if ordinal == 3 else self.escrow.token_a,
            "tokenB": None if ordinal == 1 else self.escrow.token_b,
            "tokenADigest": None if ordinal == 3 else self.escrow.token_a_digest,
            "tokenBDigest": None if ordinal == 1 else self.escrow.token_b_digest,
        }

    def observe_top_level_root_navigation(
        self,
        result_token: object,
        session: object,
        fetch_destination: object,
        fetch_mode: object,
    ) -> bool:
        if (
            not self.matches_result_token(result_token)
            or not self.matches_session(session)
            or fetch_destination != "document"
            or fetch_mode != "navigate"
        ):
            return False
        with self._lock:
            if (
                self._phase_two_armed
                and self._top_level_reload_seen_for is None
                and self._phase_two is None
                and self._pending is None
                and 2 not in self._bootstrap_served
            ):
                self._top_level_reload_seen_for = 2
                return True
            if (
                self._phase_three_armed
                and self._top_level_reload_seen_for is None
                and self._phase_three is None
                and self._pending is None
                and 3 not in self._bootstrap_served
            ):
                self._top_level_reload_seen_for = 3
                return True
            return False

    def document_evidence(self, ordinal: int) -> DocumentEvidence:
        with self._lock:
            if ordinal == 1:
                evidence = self._phase_one
            elif ordinal == 2:
                evidence = self._phase_two
            elif ordinal == 3:
                evidence = self._phase_three
            else:
                raise ProtocolStateError("outer-reload document evidence is unavailable")
            if evidence is None:
                raise ProtocolStateError("outer-reload document evidence is unavailable")
            return evidence

    def accept_result(self, result_token: str, ordinal: int) -> bool:
        if not self.matches_result_token(result_token):
            return False
        with self._lock:
            if (
                ordinal not in (1, 2, 3)
                or ordinal not in self._bootstrap_served
                or ordinal in self._results
            ):
                raise ProtocolStateError("outer-reload result state conflict")
            self._results.add(ordinal)
            return True

    def accept_ready(self, result_token: str, ordinal: int) -> bool:
        if not self.matches_result_token(result_token):
            return False
        with self._lock:
            if (
                ordinal not in self._results
                or ordinal in self._ready
                or ordinal not in (1, 2, 3)
            ):
                raise ProtocolStateError("outer-reload ready state conflict")
            self._ready.add(ordinal)
            return True

    def arm_phase_two(self, phase_one_time_origin: float) -> None:
        if (
            not isinstance(phase_one_time_origin, (int, float))
            or isinstance(phase_one_time_origin, bool)
            or not math.isfinite(float(phase_one_time_origin))
            or float(phase_one_time_origin) <= 0
        ):
            raise M0Error("outer-reload phase-one document time is invalid")
        with self._lock:
            if (
                self._phase_one is None
                or 1 not in self._bootstrap_served
                or 1 not in self._results
                or 1 not in self._ready
                or self._phase_two_armed
                or self._phase_two is not None
                or self._pending is not None
                or self._top_level_reload_seen_for is not None
                or self._phase_one.time_origin != float(phase_one_time_origin)
            ):
                raise ProtocolStateError("outer-reload phase authorization conflict")
            self._phase_one_validated_time = float(phase_one_time_origin)
            self._phase_two_armed = True

    def arm_phase_three(self, phase_two_time_origin: float) -> None:
        if (
            not isinstance(phase_two_time_origin, (int, float))
            or isinstance(phase_two_time_origin, bool)
            or not math.isfinite(float(phase_two_time_origin))
            or float(phase_two_time_origin) <= 0
        ):
            raise M0Error("outer-reload phase-two document time is invalid")
        with self._lock:
            if (
                self._phase_two is None
                or 2 not in self._bootstrap_served
                or 2 not in self._results
                or 2 not in self._ready
                or self._phase_three_armed
                or self._phase_three is not None
                or self._pending is not None
                or self._top_level_reload_seen_for != 2
                or self._phase_two.time_origin != float(phase_two_time_origin)
            ):
                raise ProtocolStateError("outer-reload phase authorization conflict")
            self._phase_two_validated_time = float(phase_two_time_origin)
            self._phase_three_armed = True
            self._top_level_reload_seen_for = None


class ChromeProfilePreferencesOuterReloadServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, _request: object, _address: object) -> None:
        # socketserver would log a request URL containing a bearer capability.
        return


class ChromeProfilePreferencesOuterReloadRequestHandler(BaseHTTPRequestHandler):
    server: ChromeProfilePreferencesOuterReloadServer

    def log_message(self, _format: str, *_args: object) -> None:
        # Never log request paths: result and session capabilities live there.
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
            b"outer-reload endpoint state conflict\n",
        )

    def _read_json_body(self, maximum: int) -> dict[str, Any] | None:
        if self.headers.get("Transfer-Encoding"):
            return None
        length_text = self.headers.get("Content-Length")
        if length_text is None or not re.fullmatch(r"[0-9]+", length_text.strip()):
            return None
        length = int(length_text)
        if length <= 0 or length > maximum:
            return None
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0]
        if content_type.strip().lower() != "application/json":
            return None
        payload = self.rfile.read(length)
        return _parse_json_object(payload) if len(payload) == length else None

    @staticmethod
    def _one_query_value(query: dict[str, list[str]], name: str) -> str | None:
        values = query.get(name)
        return values[0] if isinstance(values, list) and len(values) == 1 else None

    def _matches_expected_root_query(self, query: dict[str, list[str]]) -> bool:
        expected = self.server.expected_root_query
        if not isinstance(expected, dict) or set(query) != _ROOT_QUERY_FIELDS:
            return False
        if set(expected) != _ROOT_QUERY_FIELDS:
            return False
        for name in _ROOT_QUERY_FIELDS:
            actual_values = query.get(name)
            expected_value = expected.get(name)
            if (
                not isinstance(actual_values, list)
                or len(actual_values) != 1
                or not isinstance(expected_value, str)
                or actual_values[0] != expected_value
            ):
                return False
        return True

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path
        if path in (HOST_ROOT, f"{HOST_ROOT}/"):
            query = parse_qs(parsed.query, keep_blank_values=True)
            if self._matches_expected_root_query(query):
                self.server.session.observe_top_level_root_navigation(
                    self._one_query_value(query, "resultToken"),
                    self._one_query_value(query, "session"),
                    self.headers.get("Sec-Fetch-Dest"),
                    self.headers.get("Sec-Fetch-Mode"),
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
                HTTPStatus.OK, "text/javascript; charset=utf-8", self.server.host_js
            )
            return
        artifact_prefix = f"{HOST_ROOT}/artifacts/"
        if path.startswith(artifact_prefix):
            name = path[len(artifact_prefix) :]
            artifact = self.server.artifacts.get(name)
            if artifact is not None and "/" not in name:
                self._send_bytes(
                    HTTPStatus.OK,
                    "application/wasm" if name.endswith(".wasm")
                    else "text/javascript; charset=utf-8",
                    artifact,
                )
                return
        prefix = f"{HOST_ROOT}/bootstrap/"
        if path.startswith(prefix):
            session = path[len(prefix) :]
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
    def _bootstrap_path(path: str) -> str | None:
        prefix = f"{HOST_ROOT}/bootstrap/"
        if not path.startswith(prefix):
            return None
        session = path[len(prefix) :]
        return session if "/" not in session and CAPABILITY_RE.fullmatch(session) else None

    @staticmethod
    def _receipt_path(path: str, prefix: str) -> tuple[str, int] | None:
        if not path.startswith(prefix):
            return None
        token, separator, ordinal_text = path[len(prefix) :].partition("/")
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
        session = self._bootstrap_path(parsed.path)
        if session is not None:
            self._post_document(session)
            return
        receipt = self._receipt_path(parsed.path, f"{HOST_ROOT}/result/")
        if receipt is not None:
            self._post_result(*receipt)
            return
        receipt = self._receipt_path(parsed.path, f"{HOST_ROOT}/ready/")
        if receipt is not None:
            self._post_ready(*receipt)
            return
        self._not_found()

    def _post_document(self, session: str) -> None:
        if not self.server.session.matches_session(session):
            self._not_found()
            return
        evidence = _parse_document_evidence(
            self._read_json_body(MAX_BOOTSTRAP_DOCUMENT_BYTES)
        )
        if evidence is None:
            self._send_bytes(
                HTTPStatus.BAD_REQUEST,
                "text/plain; charset=utf-8",
                b"invalid outer-reload document\n",
            )
            return
        outcome = "accepted"
        # Do not make a raw bootstrap body eligible until peer-visible 204.
        with self.server.session.acknowledgement_gate():
            try:
                accepted = self.server.session.accept_document(session, evidence)
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
                    self.server.session.acknowledge_document(session)
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
        if value is None or not _receipt_identity(value, ordinal):
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
        if value is None or not _receipt_identity(value, ordinal):
            self._send_bytes(
                HTTPStatus.BAD_REQUEST,
                "text/plain; charset=utf-8",
                b"invalid outer-reload ready\n",
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
        # This flush is the reload barrier: notification happens strictly after
        # the host has a successful ready acknowledgement.
        self._send_empty(HTTPStatus.NO_CONTENT)
        try:
            self.wfile.flush()
        except OSError:
            return
        try:
            self.server.ready_queue.put_nowait((ordinal, value))
        except queue.Full:
            # The state was claimed; safely withhold notification rather than
            # allow a duplicate receipt to become a reload authorization.
            return


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON constant")


def _parse_json_object(payload: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _parse_document_evidence(value: dict[str, Any] | None) -> DocumentEvidence | None:
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


def _receipt_identity(value: dict[str, Any], ordinal: int) -> bool:
    return (
        type(value.get("protocol")) is int
        and value.get("protocol") == 1
        and value.get("case") == CASE
        and value.get("scope") == SCOPE
        and type(value.get("ordinal")) is int
        and value.get("ordinal") == ordinal
    )


def _require_module_name(value: object, boundary: str) -> str:
    if not isinstance(value, str) or value != PRODUCT_MODULE_NAME:
        raise M0Error(f"outer-reload {boundary} module is invalid")
    return value


def validate_m7_output_configuration(args_gn: bytes) -> None:
    try:
        text = args_gn.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError as exc:
        raise M0Error("outer-reload args.gn is not UTF-8") from exc
    values = M7_GN_ENABLE_ASSIGNMENT_RE.findall(text)
    if not values or any(value != "true" for value in values):
        raise M0Error("outer-reload args.gn lacks the Preferences test opt-in")


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
) -> ChromeProfilePreferencesOuterReloadServer:
    """Snapshot every served input before accepting a browser connection."""

    artifacts = snapshot_regular_files(
        out_dir,
        (f"{PRODUCT_MODULE_NAME}.js", f"{PRODUCT_MODULE_NAME}.wasm"),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="outer-reload profile Preferences artifacts",
    )
    args_gn = snapshot_regular_file(
        out_dir / "args.gn",
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="outer-reload selected args.gn",
    )
    validate_m7_output_configuration(args_gn)
    selected_host_dir = host_dir or Path(__file__).with_name("host")
    host_files = snapshot_regular_files(
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
    server = ChromeProfilePreferencesOuterReloadServer(
        (host, port), ChromeProfilePreferencesOuterReloadRequestHandler
    )
    server.args_gn = args_gn
    server.artifacts = artifacts
    server.host_html = host_files[HOST_HTML_NAME]
    server.host_js = host_files[HOST_JS_NAME]
    server.module_name = PRODUCT_MODULE_NAME
    server.runner_source = runner_source
    server.result_queue = queue.Queue(maxsize=3)
    server.ready_queue = queue.Queue(maxsize=3)
    server.receipt_lock = threading.Lock()
    server.session = OuterReloadSession(result_token, session, escrow)
    # ``smoke_url`` installs the one exact navigated query before browser
    # launch.  Static snapshot requests have no query and cannot arm phase 2.
    server.expected_root_query: dict[str, str] | None = None
    return server


def _byte_identity(contents: bytes) -> dict[str, object]:
    return {"bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}


def artifact_identity(server: ChromeProfilePreferencesOuterReloadServer) -> dict[str, object]:
    if server.module_name != PRODUCT_MODULE_NAME:
        raise M0Error("outer-reload artifact module disagrees with server")
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
    server: ChromeProfilePreferencesOuterReloadServer,
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
    server: ChromeProfilePreferencesOuterReloadServer,
    result_token: str,
    session: str,
    versions: dict[str, str],
    *,
    artifact: dict[str, object],
    capture_harness: dict[str, object],
    timeout_seconds: float,
) -> str:
    if (
        server.module_name != PRODUCT_MODULE_NAME
        or not server.session.matches_result_token(result_token)
        or not server.session.matches_session(session)
        or not isinstance(timeout_seconds, (int, float))
        or isinstance(timeout_seconds, bool)
    ):
        raise M0Error("outer-reload URL inputs are invalid")
    timeout_ms = int(float(timeout_seconds) * 1000)
    if timeout_ms < 1000 or timeout_ms > MAX_TIMEOUT_MS:
        raise M0Error("outer-reload URL timeout is invalid")
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "resultToken": result_token,
            "session": session,
            "module": PRODUCT_MODULE_NAME,
            "timeoutMs": str(timeout_ms),
            "versions": json.dumps(versions, sort_keys=True, separators=(",", ":")),
            "artifact": json.dumps(artifact, sort_keys=True, separators=(",", ":")),
            "captureHarness": json.dumps(
                capture_harness, sort_keys=True, separators=(",", ":")
            ),
        }
    )
    parsed = parse_qs(query, keep_blank_values=True)
    if set(parsed) != _ROOT_QUERY_FIELDS or any(len(values) != 1 for values in parsed.values()):
        raise M0Error("outer-reload URL query is invalid")
    server.expected_root_query = {name: values[0] for name, values in parsed.items()}
    return f"http://{host}:{port}{HOST_ROOT}/?{query}"


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
    length = 0
    while True:
        block = response.read(1024 * 1024)
        if not block:
            break
        length += len(block)
        digest.update(block)
    return length, digest.hexdigest()


def verify_server_delivery(server: ChromeProfilePreferencesOuterReloadServer) -> None:
    """Prove static execution inputs are immutable in-memory snapshots."""

    host, port = server.server_address[:2]
    expected = (
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
                raise M0Error("outer-reload snapshot request failed")
            headers = {name.lower(): value for name, value in response.getheaders()}
            for name, expected_value in _expected_headers(content_type).items():
                actual = headers.get(name, "")
                if name == "content-type":
                    actual = actual.split(";", 1)[0].strip().lower()
                if actual != expected_value:
                    raise M0Error("outer-reload snapshot response header is invalid")
            length, digest = _stream_response_digest(response)
            if length != len(contents) or digest != hashlib.sha256(contents).hexdigest():
                raise M0Error("outer-reload snapshot body changed")
        finally:
            connection.close()


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
    if type(identity.get("sha256")) is not str or not SHA256_RE.fullmatch(
        identity["sha256"]
    ):
        raise M0Error(f"outer-reload {description} SHA-256 is invalid")


def _validate_artifact_identity(value: object, expected: dict[str, object]) -> None:
    artifact = _require_exact_fields(value, _ARTIFACT_FIELDS, "artifact identity")
    if (
        artifact.get("artifact_delivery") != ARTIFACT_DELIVERY
        or artifact.get("artifact_source_provenance") != ARTIFACT_SOURCE_PROVENANCE
        or artifact.get("build_config_provenance") != BUILD_CONFIG_PROVENANCE
    ):
        raise M0Error("outer-reload artifact identity is invalid")
    _require_module_name(artifact.get("module_name"), "artifact")
    for field_name in ("build_config", "loader", "wasm"):
        _validate_byte_identity(artifact.get(field_name), f"artifact {field_name}")
    if not _exact_json_equal(artifact, expected):
        raise M0Error("outer-reload artifact identity disagrees with snapshot")


def _validate_capture_identity(value: object, expected: dict[str, object]) -> None:
    capture = _require_exact_fields(value, _CAPTURE_HARNESS_FIELDS, "capture harness")
    if (
        capture.get("source_snapshot_provenance") != SOURCE_SNAPSHOT_PROVENANCE
        or capture.get("version_provenance") != VERSION_PROVENANCE
    ):
        raise M0Error("outer-reload capture harness identity is invalid")
    for field_name in ("host_html", "host_js", "runner_source"):
        _validate_byte_identity(capture.get(field_name), f"capture {field_name}")
    if not _exact_json_equal(capture, expected):
        raise M0Error("outer-reload capture harness disagrees with snapshot")


def expected_markers(ordinal: int, escrow: TokenEscrow) -> list[str]:
    if ordinal == 1:
        return [
            f"{M7_MARKER_PREFIX}READY",
            f"{M7_MARKER_PREFIX}WRITE_ACCEPTED sha256={escrow.token_a_digest}",
            f"{M7_MARKER_PREFIX}BROWSER_SMOKE_CLOSED",
            f"{M7_MARKER_PREFIX}HISTORY_A_WRITE_ACCEPTED",
            f"{M7_MARKER_PREFIX}HISTORY_BACKEND_CLOSED",
            f"{M7_MARKER_PREFIX}FENCE_OK sha256={escrow.token_a_digest}",
            f"{M7_MARKER_PREFIX}LEASE_RELEASED",
        ]
    if ordinal == 2:
        return [
            f"{M7_MARKER_PREFIX}READY",
            f"{M7_MARKER_PREFIX}READ_A_OK sha256={escrow.token_a_digest}",
            f"{M7_MARKER_PREFIX}WRITE_ACCEPTED sha256={escrow.token_b_digest}",
            f"{M7_MARKER_PREFIX}BROWSER_SMOKE_CLOSED",
            f"{M7_MARKER_PREFIX}HISTORY_A_READ_OK",
            f"{M7_MARKER_PREFIX}HISTORY_B_WRITE_ACCEPTED",
            f"{M7_MARKER_PREFIX}HISTORY_BACKEND_CLOSED",
            f"{M7_MARKER_PREFIX}FENCE_OK sha256={escrow.token_b_digest}",
            f"{M7_MARKER_PREFIX}LEASE_RELEASED",
        ]
    if ordinal == 3:
        return [
            f"{M7_MARKER_PREFIX}READY",
            f"{M7_MARKER_PREFIX}READ_B_OK sha256={escrow.token_b_digest}",
            f"{M7_MARKER_PREFIX}BROWSER_SMOKE_CLOSED",
            f"{M7_MARKER_PREFIX}HISTORY_A_READ_OK",
            f"{M7_MARKER_PREFIX}HISTORY_B_READ_OK",
            f"{M7_MARKER_PREFIX}HISTORY_BACKEND_CLOSED",
            f"{M7_MARKER_PREFIX}FENCE_OK sha256={escrow.token_b_digest}",
            f"{M7_MARKER_PREFIX}LEASE_RELEASED",
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
    if any(line != SUPPRESSED_NATIVE_OUTPUT and line not in expected for line in stderr):
        raise M0Error(f"outer-reload run {ordinal} stderr grammar is invalid")
    output = stdout + stderr
    if any(
        M7_MARKER_PREFIX in line and line not in expected for line in stderr
    ) or any(
        M7_MARKER_PREFIX in line
        or "--wasm-profile-preferences-token" in line
        or "<redacted>" in line
        for line in stdout
    ) or any(
        "--wasm-profile-preferences-token" in line or "<redacted>" in line
        for line in output
    ):
        raise M0Error(f"outer-reload run {ordinal} output grammar is invalid")
    stderr_markers = [line for line in stderr if line.startswith(M7_MARKER_PREFIX)]
    if stderr_markers != expected:
        raise M0Error(f"outer-reload run {ordinal} stderr markers are invalid")
    return run["moduleIdentity"]


def _validate_token_evidence(value: object, ordinal: int, escrow: TokenEscrow) -> None:
    evidence = _require_exact_fields(value, _TOKEN_EVIDENCE_FIELDS, "token evidence")
    expected_a: str | None = None if ordinal == 3 else escrow.token_a_digest
    expected_b: str | None = None if ordinal == 1 else escrow.token_b_digest
    expected_distinct: bool | None = True if ordinal == 2 else None
    if (
        evidence.get("algorithm") != "SHA-256"
        or evidence.get("tokenA") != expected_a
        or evidence.get("tokenB") != expected_b
        or evidence.get("distinct") is not expected_distinct
        or evidence.get("rawTokensExcluded") is not True
        or evidence.get("rawTokenLeakDetected") is not False
        or type(evidence.get("rawTokenRedactionCount")) is not int
        or evidence.get("rawTokenRedactionCount") != 0
    ):
        raise M0Error("outer-reload token evidence is invalid")


def _validate_bridge(value: object) -> dict[str, Any]:
    bridge = _require_exact_fields(value, _BRIDGE_FIELDS, "bridge")
    expected = {
        "protocol": 1,
        "permanent": True,
        "frozen": True,
        "installedBeforeModuleFactory": True,
        "processExitDispatches": 1,
        "noActiveProcessExitRejected": 0,
        "duplicateProcessExitRejected": 0,
        "lateProcessExitRejected": 0,
        "activeRunAtResult": None,
    }
    for field_name, expected_value in expected.items():
        if not _exact_json_equal(bridge.get(field_name), expected_value):
            raise M0Error(f"outer-reload bridge {field_name} is invalid")
    return bridge


def _validate_quiescence(value: object, bridge: dict[str, Any]) -> None:
    quiescence = _require_exact_fields(value, _FINAL_QUIESCENCE_FIELDS, "quiescence")
    expected = {
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
    }
    for field_name, expected_value in expected.items():
        if not _exact_json_equal(quiescence.get(field_name), expected_value):
            raise M0Error(f"outer-reload quiescence {field_name} is invalid")
    callback_fields = (
        "callbacksAtActiveClear",
        "callbacksAtTaskStart",
        "callbacksAtTaskEnd",
        "callbacksAtPreUploadCheck",
    )
    if any(
        type(quiescence.get(field_name)) is not int or quiescence[field_name] < 0
        for field_name in callback_fields
    ) or len({quiescence[field_name] for field_name in callback_fields}) != 1:
        raise M0Error("outer-reload quiescence is not quiet")
    if quiescence["processExitReportsAtPreUploadCheck"] != bridge["processExitDispatches"]:
        raise M0Error("outer-reload quiescence bridge evidence disagrees")


def _validate_host_boundary(value: object) -> None:
    boundary = _require_exact_fields(value, _HOST_BOUNDARY_FIELDS, "host boundary")
    if any(item is not False for item in boundary.values()):
        raise M0Error("outer-reload host crossed a prohibited boundary")


def _validate_document(
    value: object, ordinal: int, expected: DocumentEvidence
) -> DocumentEvidence:
    document = _require_exact_fields(value, _DOCUMENT_FIELDS, "document receipt")
    time_origin = document.get("timeOrigin")
    navigation_type = document.get("navigationType")
    if (
        navigation_type != ("navigate" if ordinal == 1 else "reload")
        or not isinstance(time_origin, (int, float))
        or isinstance(time_origin, bool)
        or not math.isfinite(float(time_origin))
        or float(time_origin) <= 0
    ):
        raise M0Error("outer-reload document receipt is invalid")
    actual = DocumentEvidence(navigation_type, float(time_origin))
    if actual != expected:
        raise M0Error("outer-reload document receipt disagrees with bootstrap")
    return actual


def _validate_no_prohibited_strings(value: object, prohibited: tuple[str, ...]) -> None:
    def visit(item: object, depth: int) -> None:
        if depth > 32:
            raise M0Error("outer-reload receipt nesting is invalid")
        if isinstance(item, str):
            if any(secret in item for secret in prohibited):
                raise M0Error("outer-reload receipt contains a prohibited value")
        elif isinstance(item, list):
            for child in item:
                visit(child, depth + 1)
        elif isinstance(item, dict):
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
    _validate_capture_identity(result.get("capture_harness"), expected_capture_harness_identity)
    document = _validate_document(result.get("document"), ordinal, expected_document)
    _validate_token_evidence(result.get("tokenEvidence"), ordinal, escrow)
    module_identity = _validate_run(result.get("run"), ordinal, escrow)
    bridge = _validate_bridge(result.get("bridge"))
    _validate_quiescence(result.get("finalQuiescence"), bridge)
    _validate_host_boundary(result.get("hostBoundary"))
    return PhaseResult(
        ordinal=ordinal,
        origin=expected_origin,
        navigation_type=document.navigation_type,
        time_origin=document.time_origin,
        module_identity=module_identity,
    )


def validate_ready_receipt(value: dict[str, Any], expected: PhaseResult) -> None:
    value = _require_exact_fields(value, _READY_FIELDS, "ready receipt")
    if (
        type(value.get("protocol")) is not int
        or value.get("protocol") != 1
        or value.get("case") != CASE
        or value.get("scope") != SCOPE
        or type(value.get("ordinal")) is not int
        or value.get("ordinal") != expected.ordinal
        or not isinstance(value.get("timeOrigin"), (int, float))
        or isinstance(value.get("timeOrigin"), bool)
        or float(value["timeOrigin"]) != expected.time_origin
    ):
        raise M0Error("outer-reload ready receipt is invalid")


def validate_outer_document_transitions(
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
        or second.time_origin <= first.time_origin
        or third.time_origin <= second.time_origin
        or len({first.module_identity, second.module_identity, third.module_identity}) != 3
    ):
        raise M0Error("outer-reload three-document transition is invalid")


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
            received_ordinal, receipt = receipts.get(timeout=min(0.1, remaining))
        except queue.Empty:
            if browser.poll() is not None:
                raise M0Error(
                    f"outer-reload browser exited before {kind} "
                    f"({len(browser_stderr)} browser stderr lines suppressed)"
                )
            continue
        if received_ordinal != ordinal:
            raise M0Error("outer-reload receipt order is invalid")
        return receipt


def wait_for_phase_result(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    server: ChromeProfilePreferencesOuterReloadServer,
    ordinal: int,
    deadline: float,
) -> dict[str, Any]:
    return _wait_for_receipt(
        browser, browser_stderr, server.result_queue, ordinal, deadline, "result"
    )


def wait_for_ready_receipt(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    server: ChromeProfilePreferencesOuterReloadServer,
    ordinal: int,
    deadline: float,
) -> dict[str, Any]:
    return _wait_for_receipt(
        browser,
        browser_stderr,
        server.ready_queue,
        ordinal,
        deadline,
        "ready receipt",
    )


def _root_frame_identity(value: object) -> RootFrameIdentity:
    if not isinstance(value, dict):
        raise M0Error("outer-reload DevTools frame tree is invalid")
    tree = value.get("frameTree")
    frame = tree.get("frame") if isinstance(tree, dict) else None
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
    """Use the retained client and record the root frame before Page.reload."""

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
    frame = params.get("frame") if isinstance(params, dict) else None
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
        return None
    if not isinstance(url, str) or not url.startswith(expected_page_url_prefix):
        raise M0Error("outer-reload DevTools navigation URL is invalid")
    return RootFrameIdentity(baseline.frame_id, loader_id)


def reload_outer_document(
    client: Any,
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    baseline: RootFrameIdentity,
    expected_page_url_prefix: str,
    deadline: float,
) -> RootFrameIdentity:
    """Issue only Page.reload and require a same-root/new-loader event."""

    client.call("Page.reload", {"ignoreCache": True})
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


def write_failure_diagnostics(
    diagnostics_dir: Path,
    *,
    stage: str,
    error: Exception,
    browser: subprocess.Popen[str] | None,
    browser_stderr: deque[str],
    result_ordinals: set[int],
    ready_ordinals: set[int],
) -> Path:
    """Write only structural runner data; never stringify a hostile receipt."""

    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / "chrome-profile-preferences-outer-reload-m7-failure.json"
    payload = {
        "schema_version": 1,
        "runner": "run_m7_chrome_profile_preferences_outer_reload_dom_smoke.py",
        "case": CASE,
        "scope": SCOPE,
        "stage": stage,
        "nonclaims": [
            "not_m7_gate_complete",
            "not_crash_recovery",
            "not_normal_navigation_history_or_desktop_history_graph",
            "not_full_profile_or_database_service_coverage",
            "not_artifact_source_provenance",
        ],
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
        "result_ordinals_received": sorted(result_ordinals),
        "ready_ordinals_received": sorted(ready_ordinals),
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return path


def _stop_server(
    server: ChromeProfilePreferencesOuterReloadServer | None,
    server_thread: threading.Thread | None,
    started: bool,
) -> None:
    if server is not None:
        if started:
            server.shutdown()
        server.server_close()
    if started and server_thread is not None:
        server_thread.join(timeout=3)
        if server_thread.is_alive():
            raise M0Error("outer-reload server did not stop")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run three Chrome Wasm Preferences documents separated by two real "
            "DevTools page reloads."
        ),
        epilog=(
            "Build the normal artifact with: buildtools/linux64/gn gen "
            "out/wasm-chrome-m7-profile-preferences --args='"
            + DEFAULT_GN_ARGUMENTS
            + "' --fail-on-unused-args; autoninja -C "
            "out/wasm-chrome-m7-profile-preferences chrome_wasm"
        ),
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--diagnostics-dir", type=Path)
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--timeout", type=parse_timeout, default=120.0)
    args = parser.parse_args()
    if args.timeout < MIN_TIMEOUT_SECONDS:
        parser.error(f"--timeout must be at least {MIN_TIMEOUT_SECONDS:g} seconds")

    browser: subprocess.Popen[str] | None = None
    browser_stderr: deque[str] = deque(maxlen=MAX_BROWSER_STDERR_LINES)
    stderr_thread: threading.Thread | None = None
    client: Any | None = None
    outer_profile: tempfile.TemporaryDirectory[str] | None = None
    server: ChromeProfilePreferencesOuterReloadServer | None = None
    server_thread: threading.Thread | None = None
    server_thread_started = False
    result_ordinals: set[int] = set()
    ready_ordinals: set[int] = set()
    stage = "initialize"
    successful = False

    try:
        stage = "load-manifest"
        versions = toolchain_manifest_versions(load_manifest())
        stage = "create-token-escrow"
        result_token, session = new_capability_pair()
        escrow = new_token_escrow()
        out_dir = args.out_dir if args.out_dir.is_absolute() else REPO_ROOT / args.out_dir
        stage = "create-server"
        server = create_server("127.0.0.1", 0, out_dir, result_token, session, escrow)
        artifact = artifact_identity(server)
        capture_harness = capture_harness_identity(server)
        server_thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.05},
            name="chromium-wasm-m7-profile-preferences-outer-reload-server",
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
            prefix="chromium-wasm-m7-profile-preferences-outer-reload-"
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
        stderr_thread = threading.Thread(
            target=drain_stream,
            args=(browser.stderr, browser_stderr),
            name="chromium-wasm-m7-profile-preferences-outer-reload-browser-stderr",
            daemon=True,
        )
        stderr_thread.start()
        deadline = time.monotonic() + args.timeout
        expected_page_url_prefix = url.split("?", 1)[0]

        stage = "connect-devtools-phase-one"
        client = wait_for_page_client(debug_port, expected_page_url_prefix, deadline)
        stage = "wait-phase-one-result"
        first_result = wait_for_phase_result(browser, browser_stderr, server, 1, deadline)
        result_ordinals.add(1)
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
        ready_ordinals.add(1)
        stage = "validate-phase-one-ready"
        validate_ready_receipt(first_ready, first)
        stage = "prepare-cdp-outer-reload"
        root_frame = prepare_outer_document_reload(client)
        stage = "arm-phase-two-document-evidence"
        server.session.arm_phase_two(first.time_origin)
        stage = "reload-outer-document-phase-two"
        reload_outer_document(
            client,
            browser,
            browser_stderr,
            root_frame,
            expected_page_url_prefix,
            deadline,
        )
        stage = "wait-phase-two-result"
        second_result = wait_for_phase_result(browser, browser_stderr, server, 2, deadline)
        result_ordinals.add(2)
        stage = "validate-phase-two-result"
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
        stage = "wait-phase-two-ready"
        second_ready = wait_for_ready_receipt(browser, browser_stderr, server, 2, deadline)
        ready_ordinals.add(2)
        stage = "validate-phase-two-ready"
        validate_ready_receipt(second_ready, second)
        stage = "prepare-cdp-outer-reload-phase-three"
        root_frame = prepare_outer_document_reload(client)
        stage = "arm-phase-three-document-evidence"
        server.session.arm_phase_three(second.time_origin)
        stage = "reload-outer-document-phase-three"
        reload_outer_document(
            client,
            browser,
            browser_stderr,
            root_frame,
            expected_page_url_prefix,
            deadline,
        )
        stage = "wait-phase-three-result"
        third_result = wait_for_phase_result(browser, browser_stderr, server, 3, deadline)
        result_ordinals.add(3)
        stage = "validate-phase-three-result"
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
        stage = "wait-phase-three-ready"
        third_ready = wait_for_ready_receipt(browser, browser_stderr, server, 3, deadline)
        ready_ordinals.add(3)
        stage = "validate-phase-three-ready"
        validate_ready_receipt(third_ready, third)
        stage = "validate-three-document-transition"
        validate_outer_document_transitions(first, second, third)
        successful = True
    except Exception as error:
        if args.diagnostics_dir is not None:
            try:
                write_failure_diagnostics(
                    args.diagnostics_dir,
                    stage=stage,
                    error=error,
                    browser=browser,
                    browser_stderr=browser_stderr,
                    result_ordinals=result_ordinals,
                    ready_ordinals=ready_ordinals,
                )
            except OSError:
                pass
        print(f"{SENTINEL}:FAIL stage={stage}", file=sys.stderr, flush=True)
    finally:
        if client is not None:
            client.close()
        if browser is not None:
            stop_browser(browser)
        if stderr_thread is not None:
            stderr_thread.join(timeout=3)
        try:
            _stop_server(server, server_thread, server_thread_started)
        except M0Error:
            successful = False
        if outer_profile is not None:
            outer_profile.cleanup()

    if not successful:
        return 1
    print(
        SENTINEL
        + ":PASS "
        + json.dumps(
            {
                "case": CASE,
                "documents": 3,
                "m7GateComplete": False,
                "outerDocumentReload": True,
                "rawPreferencesTokensSerialized": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
