#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Prove a bounded canonical Preferences replacement-failure recovery path.

This runner owns four *top-level documents*, not four invocations in one
document.  D1 writes A through the real ``WasmProfile`` JsonPrefStore.  D2
reads A, injects the source-selected V4 proxy-completion loss immediately
after ImportantFileWriter has flushed and closed its temporary Preferences
file, observes the redacted replacement ``EIO`` receipt, and verifies the
ordinary failure-retirement path exits cleanly but nonzero.  Only after that
receipt is quiet does this runner issue DevTools ``Page.reload``.  D3 is a
fresh document that reads A and writes C; D4 is a second fresh document that
reads C.

The host does not inspect OPFS, Web Locks, IndexedDB, Cookies, profile files,
Wasm memory, or native state.  It receives opaque A/B/C values only in a
one-shot bootstrap response, passes them to Chromium command-line arguments,
and returns digests plus fixed markers.  No opaque value is placed in a URL,
result receipt, stdout, diagnostics, or browser stderr retained by this
runner.

This is deliberately a narrow controlled-loss witness.  It proves neither a
power-loss model, directory durability, generic crash recovery, live lock
contention, default profile completeness, nor M7 completion.
"""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
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
from run_browser_smoke import browser_command, find_browser, stop_browser


SENTINEL = (
    "CHROMIUM_WASM_M7_CHROME_PROFILE_PREFERENCES_IMPORTANT_FILE_WRITER_"
    "PROXY_COMPLETION_DOM"
)
CASE = "chrome_profile_preferences_important_file_writer_proxy_completion_four_outer_document_reload_m7"
SCOPE = (
    "same-origin-four-outer-documents-canonical-chrome-preferences-"
    "important-file-writer-post-flush-v4-proxy-completion-failure-and-"
    "fresh-document-recovery-only"
)
PRODUCT_MODULE_NAME = (
    "chrome_wasm_m7_profile_preferences_important_file_writer_proxy_completion_test"
)
PRODUCT_GN_TARGET = "//chrome:chrome_wasm"
PRODUCT_GN_ENABLE_ARGUMENT = "enable_chromium_wasm_m7_profile_preferences_test=true"
PRODUCT_GN_FAILURE_ENABLE_ARGUMENT = (
    "enable_chromium_wasm_m7_profile_preferences_important_file_writer_"
    "proxy_completion_test=true"
)
DEFAULT_OUT_DIR = Path(
    "out/wasm-chrome-m7-profile-preferences-important-file-writer-proxy-completion"
)
DEFAULT_GN_ARGUMENTS = (
    'import("//out/wasm-chrome-m6/args.gn")\n'
    + PRODUCT_GN_ENABLE_ARGUMENT
    + "\n"
    + PRODUCT_GN_FAILURE_ENABLE_ARGUMENT
)
BUILD_CONFIG_PROVENANCE = "selected-out-dir-args-gn-immutable-snapshot"
HOST_ROOT = "/__m7_chrome_profile_preferences_important_file_writer_proxy_completion__"
HOST_HTML_NAME = "chrome_wasm_profile_preferences_important_file_writer_proxy_completion_smoke.html"
HOST_JS_NAME = "chrome_wasm_profile_preferences_important_file_writer_proxy_completion_smoke.js"
ARTIFACT_DELIVERY = "immutable-in-memory-server-snapshot"
ARTIFACT_SOURCE_PROVENANCE = "unverified"
SOURCE_SNAPSHOT_PROVENANCE = "on-disk-byte-snapshots-at-server-startup-not-commit-provenance"
VERSION_PROVENANCE = (
    "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance"
)
M7_MARKER_PREFIX = "CHROMIUM_WASM_M7_PREFS:"
FAILURE_RETIREMENT_MARKER = (
    "CHROMIUM_WASM_M7_PROFILE_FAILURE_RETIREMENT:SEALED_LEASE_RETAINED"
)
IMPORTANT_FILE_WRITER_EIO_MARKER = (
    f"{M7_MARKER_PREFIX}IMPORTANT_FILE_WRITER_REPLACE_EIO_POST_FLUSH_UNPUBLISHED"
)
LEASE_REACQUIRED_MARKER = f"{M7_MARKER_PREFIX}LEASE_REACQUIRED"

MAX_RESULT_BYTES = 512 * 1024
MAX_READY_BYTES = 8 * 1024
MAX_BOOTSTRAP_DOCUMENT_BYTES = 8 * 1024
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024 * 1024
MAX_BROWSER_STDERR_LINES = 300
MAX_TIMEOUT_MS = 300_000
MIN_TIMEOUT_SECONDS = 20.0
FINAL_QUIESCENCE_MS = 50
# The page evaluates its own bounded lifecycle through |timeoutMs| and posts a
# fully redacted receipt immediately afterwards. Keep a small runner-side
# allowance so a terminal failure receipt emitted at that boundary is observed
# and classified instead of being mistaken for an absent document. The shared
# runner deadline also covers CDP setup and reload waits; this allowance does
# not change any page-side lifecycle, reload, or persistence operation.
RESULT_RECEIPT_GRACE_SECONDS = 5.0

CAPABILITY_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
GIT_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MODULE_ID_RE = re.compile(r"^[0-9a-f]{32}$")


@dataclass(frozen=True)
class TokenEscrow:
    token_a: str
    token_b: str
    token_c: str
    token_a_digest: str
    token_b_digest: str
    token_c_digest: str


@dataclass(frozen=True)
class DocumentEvidence:
    navigation_type: str
    time_origin: float


@dataclass(frozen=True)
class PhaseResult:
    ordinal: int
    navigation_type: str
    time_origin: float
    module_identity: str


@dataclass(frozen=True)
class RootFrameIdentity:
    frame_id: str
    loader_id: str


class ProtocolStateError(M0Error):
    """A peer attempted to advance the one-shot document protocol incorrectly."""


def parse_proxy_completion_timeout(value: str) -> float:
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
            f"timeout must be finite and in (0, {MAX_TIMEOUT_MS / 1000:g}]"
        )
    return timeout


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def new_token_escrow() -> TokenEscrow:
    values: set[str] = set()
    while len(values) != 3:
        values.add(secrets.token_hex(32))
    token_a, token_b, token_c = sorted(values)
    return TokenEscrow(
        token_a=token_a,
        token_b=token_b,
        token_c=token_c,
        token_a_digest=_sha256_text(token_a),
        token_b_digest=_sha256_text(token_b),
        token_c_digest=_sha256_text(token_c),
    )


def new_capability_pair() -> tuple[str, str]:
    result_token = secrets.token_urlsafe(24)
    session = secrets.token_urlsafe(24)
    while session == result_token:
        session = secrets.token_urlsafe(24)
    if not CAPABILITY_RE.fullmatch(result_token) or not CAPABILITY_RE.fullmatch(session):
        raise M0Error("proxy-completion capability generation is invalid")
    return result_token, session


def phase_mode(ordinal: int) -> str:
    if ordinal == 1:
        return "write"
    if ordinal in (2, 3):
        return "verify-and-write"
    if ordinal == 4:
        return "verify-b"
    raise M0Error("proxy-completion phase ordinal is invalid")


def phase_status(ordinal: int) -> str:
    if ordinal == 1:
        return "seeded"
    if ordinal == 2:
        return "replacement-failed"
    if ordinal == 3:
        return "recovered"
    if ordinal == 4:
        return "verified"
    raise M0Error("proxy-completion phase ordinal is invalid")


def phase_navigation(ordinal: int) -> str:
    if ordinal == 1:
        return "navigate"
    if ordinal in (2, 3, 4):
        return "reload"
    raise M0Error("proxy-completion phase ordinal is invalid")


def expected_markers(ordinal: int, escrow: TokenEscrow) -> list[str]:
    if ordinal == 1:
        return [
            f"{M7_MARKER_PREFIX}READY",
            f"{M7_MARKER_PREFIX}WRITE_ACCEPTED sha256={escrow.token_a_digest}",
            f"{M7_MARKER_PREFIX}FENCE_OK sha256={escrow.token_a_digest}",
            f"{M7_MARKER_PREFIX}LEASE_RELEASED",
        ]
    if ordinal == 2:
        return [
            f"{M7_MARKER_PREFIX}READY",
            f"{M7_MARKER_PREFIX}READ_A_OK sha256={escrow.token_a_digest}",
            IMPORTANT_FILE_WRITER_EIO_MARKER,
            f"{M7_MARKER_PREFIX}FAIL stage=fence",
        ]
    if ordinal == 3:
        return [
            f"{M7_MARKER_PREFIX}READY",
            LEASE_REACQUIRED_MARKER,
            f"{M7_MARKER_PREFIX}READ_A_OK sha256={escrow.token_a_digest}",
            f"{M7_MARKER_PREFIX}WRITE_ACCEPTED sha256={escrow.token_c_digest}",
            f"{M7_MARKER_PREFIX}FENCE_OK sha256={escrow.token_c_digest}",
            f"{M7_MARKER_PREFIX}LEASE_RELEASED",
        ]
    if ordinal == 4:
        return [
            f"{M7_MARKER_PREFIX}READY",
            f"{M7_MARKER_PREFIX}READ_B_OK sha256={escrow.token_c_digest}",
            f"{M7_MARKER_PREFIX}FENCE_OK sha256={escrow.token_c_digest}",
            f"{M7_MARKER_PREFIX}LEASE_RELEASED",
        ]
    raise M0Error("proxy-completion marker ordinal is invalid")


def _valid_document_evidence(value: object) -> bool:
    return (
        isinstance(value, DocumentEvidence)
        and value.navigation_type in ("navigate", "reload")
        and isinstance(value.time_origin, float)
        and math.isfinite(value.time_origin)
        and value.time_origin > 0
    )


class ProxyCompletionSession:
    """One-shot four-document state with independent reload gates.

    A replacement bootstrap requires three facts from different trust
    boundaries: the previous redacted result and ready receipt were accepted,
    the runner armed the next ordinal after validating them, and the server
    observed a fresh root navigation with Fetch Metadata before accepting the
    replacement document's flushed evidence receipt.
    """

    def __init__(self, result_token: str, session: str, escrow: TokenEscrow):
        tokens = (escrow.token_a, escrow.token_b, escrow.token_c)
        digests = (escrow.token_a_digest, escrow.token_b_digest, escrow.token_c_digest)
        if (
            not isinstance(result_token, str)
            or not isinstance(session, str)
            or not CAPABILITY_RE.fullmatch(result_token)
            or not CAPABILITY_RE.fullmatch(session)
            or result_token == session
            or len(set(tokens)) != 3
            or not all(SHA256_RE.fullmatch(token) for token in tokens)
            or tuple(_sha256_text(token) for token in tokens) != digests
        ):
            raise M0Error("proxy-completion session escrow is invalid")
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
        self._root_navigation_seen: set[int] = set()
        self._pending_document: tuple[int, DocumentEvidence] | None = None

    @property
    def escrow(self) -> TokenEscrow:
        return self._escrow

    def matches_result_token(self, value: str | None) -> bool:
        return isinstance(value, str) and secrets.compare_digest(value, self._result_token)

    def matches_session(self, value: str | None) -> bool:
        return isinstance(value, str) and secrets.compare_digest(value, self._session)

    def bootstrap_acknowledgement_gate(self) -> threading.Lock:
        return self._bootstrap_acknowledgement_gate

    def _next_expected_document(self) -> int:
        if not self._documents:
            return 1
        if self._armed_ordinal in (2, 3, 4):
            return self._armed_ordinal
        raise ProtocolStateError("proxy-completion bootstrap document conflict")

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
            ordinal = self._next_expected_document()
            if ordinal in self._root_navigation_seen:
                return False
            self._root_navigation_seen.add(ordinal)
            return True

    def accept_bootstrap_document(self, session: str, evidence: DocumentEvidence) -> bool:
        if not self.matches_session(session):
            return False
        if not _valid_document_evidence(evidence):
            raise ProtocolStateError("proxy-completion bootstrap document is invalid")
        with self._lock:
            ordinal = self._next_expected_document()
            if (
                ordinal in self._documents
                or ordinal in self._bootstrap_served
                or ordinal not in self._root_navigation_seen
                or self._pending_document is not None
                or evidence.navigation_type != phase_navigation(ordinal)
            ):
                raise ProtocolStateError("proxy-completion bootstrap document conflict")
            if ordinal > 1:
                previous_time = self._validated_times.get(ordinal - 1)
                if previous_time is None or evidence.time_origin <= previous_time:
                    raise ProtocolStateError("proxy-completion bootstrap document conflict")
            self._pending_document = (ordinal, evidence)
            return True

    def acknowledge_bootstrap_document(self, session: str) -> bool:
        if not self.matches_session(session):
            return False
        with self._lock:
            if self._pending_document is None:
                raise ProtocolStateError("proxy-completion bootstrap acknowledgement conflict")
            ordinal, evidence = self._pending_document
            if ordinal in self._documents:
                raise ProtocolStateError("proxy-completion bootstrap acknowledgement conflict")
            self._documents[ordinal] = evidence
            self._pending_document = None
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
                    raise ProtocolStateError("proxy-completion bootstrap state conflict")
                ordinal = candidates[0]
                self._bootstrap_served.add(ordinal)
        token_a: str | None = self._escrow.token_a if ordinal != 4 else None
        token_a_digest: str | None = (
            self._escrow.token_a_digest if ordinal != 4 else None
        )
        if ordinal == 1:
            token_b = None
            token_b_digest = None
        elif ordinal == 2:
            token_b = self._escrow.token_b
            token_b_digest = self._escrow.token_b_digest
        else:
            token_b = self._escrow.token_c
            token_b_digest = self._escrow.token_c_digest
        return {
            "protocol": 1,
            "case": CASE,
            "scope": SCOPE,
            "ordinal": ordinal,
            "mode": phase_mode(ordinal),
            "faultProxyCompletion": ordinal == 2,
            "tokenA": token_a,
            "tokenB": token_b,
            "tokenADigest": token_a_digest,
            "tokenBDigest": token_b_digest,
        }

    def accept_result(self, result_token: str, ordinal: int) -> bool:
        if not self.matches_result_token(result_token):
            return False
        with self._lock:
            if (
                ordinal not in self._documents
                or ordinal not in self._bootstrap_served
                or ordinal in self._results_accepted
                or ordinal != len(self._results_accepted) + 1
            ):
                raise ProtocolStateError("proxy-completion result state conflict")
            self._results_accepted.add(ordinal)
            return True

    def accept_ready(self, result_token: str, ordinal: int) -> bool:
        if not self.matches_result_token(result_token):
            return False
        with self._lock:
            if (
                ordinal not in self._results_accepted
                or ordinal in self._ready_accepted
                or ordinal != len(self._ready_accepted) + 1
            ):
                raise ProtocolStateError("proxy-completion ready state conflict")
            self._ready_accepted.add(ordinal)
            return True

    def arm_next_document(self, previous: int, time_origin: float) -> None:
        if (
            previous not in (1, 2, 3)
            or not isinstance(time_origin, (int, float))
            or isinstance(time_origin, bool)
            or not math.isfinite(float(time_origin))
            or time_origin <= 0
        ):
            raise M0Error("proxy-completion next-document arm is invalid")
        next_ordinal = previous + 1
        with self._lock:
            prior = self._documents.get(previous)
            if (
                prior is None
                or previous not in self._bootstrap_served
                or previous not in self._results_accepted
                or previous not in self._ready_accepted
                or self._armed_ordinal is not None
                or next_ordinal in self._documents
                or float(time_origin) != prior.time_origin
            ):
                raise ProtocolStateError("proxy-completion next-document arm conflict")
            self._validated_times[previous] = float(time_origin)
            self._armed_ordinal = next_ordinal

    def document_evidence(self, ordinal: int) -> DocumentEvidence:
        with self._lock:
            evidence = self._documents.get(ordinal)
        if evidence is None:
            raise M0Error("proxy-completion document evidence is unavailable")
        return evidence


class ChromeProfilePreferencesImportantFileWriterProxyCompletionServer(
    ThreadingHTTPServer
):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, _request: object, _address: object) -> None:
        # Result/session capabilities are path components.  Never let the
        # stock HTTP server write them to stderr.
        return


def _reject_duplicate_object_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("JSON constant is forbidden")


def _parse_json_object(payload: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_object_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _parse_document_evidence(value: object) -> DocumentEvidence | None:
    if not isinstance(value, dict) or set(value) != {
        "protocol",
        "case",
        "scope",
        "navigationType",
        "timeOrigin",
    }:
        return None
    time_origin = value.get("timeOrigin")
    if (
        type(value.get("protocol")) is not int
        or value.get("protocol") != 1
        or value.get("case") != CASE
        or value.get("scope") != SCOPE
        or value.get("navigationType") not in ("navigate", "reload")
        or not isinstance(time_origin, (int, float))
        or isinstance(time_origin, bool)
        or not math.isfinite(float(time_origin))
        or float(time_origin) <= 0
    ):
        return None
    return DocumentEvidence(str(value["navigationType"]), float(time_origin))


def _receipt_identity(value: object, ordinal: int) -> bool:
    return (
        isinstance(value, dict)
        and type(value.get("protocol")) is int
        and value.get("protocol") == 1
        and value.get("case") == CASE
        and value.get("scope") == SCOPE
        and type(value.get("ordinal")) is int
        and value.get("ordinal") == ordinal
        and value.get("m7GateComplete") is False
    )


def _ready_identity(value: object, ordinal: int) -> bool:
    return (
        isinstance(value, dict)
        and type(value.get("protocol")) is int
        and value.get("protocol") == 1
        and value.get("case") == CASE
        and value.get("scope") == SCOPE
        and type(value.get("ordinal")) is int
        and value.get("ordinal") == ordinal
    )


class ChromeProfilePreferencesImportantFileWriterProxyCompletionRequestHandler(
    BaseHTTPRequestHandler
):
    server: ChromeProfilePreferencesImportantFileWriterProxyCompletionServer

    def log_message(self, _format: str, *_args: object) -> None:
        # Do not echo bearer paths in diagnostics.
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
            b"proxy-completion endpoint state conflict\n",
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
        if not isinstance(expected, dict) or set(query) != set(expected):
            return False
        return all(
            isinstance(query.get(name), list)
            and len(query[name]) == 1
            and isinstance(value, str)
            and query[name][0] == value
            for name, value in expected.items()
        )

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path
        if path in (HOST_ROOT, f"{HOST_ROOT}/"):
            query = parse_qs(parsed.query, keep_blank_values=True)
            if self._matches_expected_root_query(query):
                observed = self.server.session.observe_top_level_root_navigation(
                    result_token=self._one_query_value(query, "resultToken"),
                    session=self._one_query_value(query, "session"),
                    fetch_destination=self.headers.get("Sec-Fetch-Dest"),
                    fetch_mode=self.headers.get("Sec-Fetch-Mode"),
                )
                if not observed:
                    self._conflict()
                    return
            # Serving a malformed/unarmed root request is harmless: it cannot
            # obtain a bootstrap body because document acceptance independently
            # requires an observed valid root navigation.
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
                content_type = (
                    "application/wasm"
                    if name.endswith(".wasm")
                    else "text/javascript; charset=utf-8"
                )
                self._send_bytes(HTTPStatus.OK, content_type, artifact)
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
        capability, slash, ordinal_text = path[len(prefix) :].partition("/")
        if (
            not slash
            or "/" in ordinal_text
            or not CAPABILITY_RE.fullmatch(capability)
            or ordinal_text not in ("1", "2", "3", "4")
        ):
            return None
        return capability, int(ordinal_text)

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
                b"invalid proxy-completion document\n",
            )
            return
        outcome = "accepted"
        # Do not make raw bootstrap material eligible until the prior document
        # evidence's 204 response is peer-visible and flushed.
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
        if value is None or not _receipt_identity(value, ordinal):
            self._send_bytes(
                HTTPStatus.BAD_REQUEST,
                "text/plain; charset=utf-8",
                b"invalid proxy-completion result\n",
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
        if value is None or not _ready_identity(value, ordinal):
            self._send_bytes(
                HTTPStatus.BAD_REQUEST,
                "text/plain; charset=utf-8",
                b"invalid proxy-completion ready receipt\n",
            )
            return
        with self.server.receipt_lock:
            if self.server.ready_queue.full():
                self._conflict()
                return
            try:
                accepted = self.server.session.accept_ready(result_token, ordinal)
            except ProtocolStateError:
                self._conflict()
                return
            if not accepted:
                self._not_found()
                return
            self.server.ready_queue.put_nowait((ordinal, value))
        self._send_empty(HTTPStatus.NO_CONTENT)


def _require_product_module_name(module_name: object, boundary: str) -> str:
    if not isinstance(module_name, str) or module_name != PRODUCT_MODULE_NAME:
        raise M0Error(f"proxy-completion {boundary} module is invalid")
    return module_name


def _strict_gn_boolean_values(text: str, name: str) -> list[str]:
    """Extract one-line literal assignments and reject disguised values.

    The diagnostic link setting changes Emscripten system-library source
    selection.  A comment, duplicate, variable interpolation, or multiline GN
    expression is not sufficient proof of the selected artifact, so this is
    intentionally stricter than a substring search.
    """

    values: list[str] = []
    prefix = re.compile(rf"^[ \t]*{re.escape(name)}(?:[ \t=]|$)")
    literal = re.compile(rf"^[ \t]*{re.escape(name)}[ \t]*=[ \t]*(true|false)[ \t]*$")
    for source_line in text.splitlines():
        line = source_line.split("#", 1)[0]
        if not prefix.match(line):
            continue
        match = literal.fullmatch(line)
        if match is None:
            raise M0Error(f"proxy-completion args.gn {name} is not a literal boolean")
        values.append(match.group(1))
    return values


def validate_m7_output_configuration(args_gn: bytes) -> None:
    """Require the exact isolated Preferences source-selection pair."""

    try:
        text = args_gn.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError as exc:
        raise M0Error("proxy-completion args.gn is not UTF-8") from exc
    required = (
        "enable_chromium_wasm_m7_profile_preferences_test",
        "enable_chromium_wasm_m7_profile_preferences_important_file_writer_proxy_completion_test",
    )
    for name in required:
        values = _strict_gn_boolean_values(text, name)
        if len(values) != 1 or values[0] != "true":
            raise M0Error(f"proxy-completion args.gn lacks exactly one {name}=true")

    # Do not accidentally use an aggregate or another failure-injection
    # output.  Values of unrelated ordinary feature flags are irrelevant, but
    # every M7 source selector must be literal and false unless it is one of
    # the exact two selections above.
    selector_prefix = "enable_chromium_wasm_m7_"
    for source_line in text.splitlines():
        line = source_line.split("#", 1)[0]
        if re.match(r"[ \t]*enable_chromium_wasm_m7_[A-Za-z0-9_]+(?:[ \t=]|$)", line):
            if not re.fullmatch(
                r"[ \t]*enable_chromium_wasm_m7_[A-Za-z0-9_]+[ \t]*=[ \t]*(true|false)[ \t]*",
                line,
            ):
                raise M0Error("proxy-completion args.gn selector is not literal")
        match = re.fullmatch(
            r"[ \t]*(enable_chromium_wasm_m7_[A-Za-z0-9_]+)[ \t]*=[ \t]*(true|false)[ \t]*",
            line,
        )
        if match is None:
            continue
        name, value = match.groups()
        if name not in required and value == "true":
            raise M0Error("proxy-completion args.gn enables an incompatible selector")
        if name not in required and value not in ("true", "false"):
            raise M0Error("proxy-completion args.gn selector is not literal")
        if not name.startswith(selector_prefix):
            raise M0Error("proxy-completion args.gn selector is invalid")


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
) -> ChromeProfilePreferencesImportantFileWriterProxyCompletionServer:
    """Take immutable byte snapshots before accepting any connection."""

    module_name = _require_product_module_name(module_name, "server")
    artifacts = snapshot_regular_files(
        out_dir,
        (f"{module_name}.js", f"{module_name}.wasm"),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="proxy-completion Preferences artifacts",
    )
    args_gn = snapshot_regular_file(
        out_dir / "args.gn",
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="proxy-completion selected args.gn",
    )
    validate_m7_output_configuration(args_gn)
    selected_host_dir = host_dir or Path(__file__).with_name("host")
    host_snapshots = snapshot_regular_files(
        selected_host_dir,
        (HOST_HTML_NAME, HOST_JS_NAME),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="proxy-completion host resources",
    )
    runner_source = snapshot_regular_file(
        runner_source_path or Path(__file__),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="proxy-completion runner source",
    )
    server = ChromeProfilePreferencesImportantFileWriterProxyCompletionServer(
        (host, port),
        ChromeProfilePreferencesImportantFileWriterProxyCompletionRequestHandler,
    )
    server.args_gn = args_gn
    server.artifacts = artifacts
    server.host_html = host_snapshots[HOST_HTML_NAME]
    server.host_js = host_snapshots[HOST_JS_NAME]
    server.module_name = module_name
    server.ready_queue = queue.Queue(maxsize=4)
    server.receipt_lock = threading.Lock()
    server.result_queue = queue.Queue(maxsize=4)
    server.runner_source = runner_source
    server.session = ProxyCompletionSession(result_token, session, escrow)
    # Filled only by smoke_url().  Static snapshot verification before a URL
    # exists must not consume a top-level-navigation gate.
    server.expected_root_query: dict[str, str] | None = None
    return server


def _byte_identity(contents: bytes) -> dict[str, object]:
    return {"bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}


def artifact_identity(
    server: ChromeProfilePreferencesImportantFileWriterProxyCompletionServer,
    *,
    module_name: str = PRODUCT_MODULE_NAME,
) -> dict[str, object]:
    module_name = _require_product_module_name(module_name, "artifact")
    if server.module_name != module_name:
        raise M0Error("proxy-completion artifact module disagrees with server")
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
    server: ChromeProfilePreferencesImportantFileWriterProxyCompletionServer,
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
        raise M0Error("proxy-completion manifest lacks version metadata") from exc
    if not all(
        isinstance(value, str) and GIT_REVISION_RE.fullmatch(value)
        for value in versions.values()
    ):
        raise M0Error("proxy-completion manifest version metadata is invalid")
    return versions


def smoke_url(
    server: ChromeProfilePreferencesImportantFileWriterProxyCompletionServer,
    result_token: str,
    session: str,
    versions: dict[str, str],
    *,
    artifact: dict[str, object],
    capture_harness: dict[str, object],
    timeout_seconds: float,
    module_name: str = PRODUCT_MODULE_NAME,
) -> str:
    """Build the only outer-navigation URL; no opaque A/B/C is present."""

    module_name = _require_product_module_name(module_name, "URL")
    if server.module_name != module_name:
        raise M0Error("proxy-completion URL module disagrees with server")
    if not server.session.matches_result_token(result_token) or not server.session.matches_session(
        session
    ):
        raise M0Error("proxy-completion URL capability disagrees with server")
    if (
        not isinstance(timeout_seconds, (int, float))
        or isinstance(timeout_seconds, bool)
        or not math.isfinite(float(timeout_seconds))
    ):
        raise M0Error("proxy-completion URL timeout is invalid")
    timeout_ms = int(float(timeout_seconds) * 1000)
    if timeout_ms < 1000 or timeout_ms > MAX_TIMEOUT_MS:
        raise M0Error("proxy-completion URL timeout is invalid")
    query = {
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
    if any(secret in urlencode(query) for secret in (
        server.session.escrow.token_a,
        server.session.escrow.token_b,
        server.session.escrow.token_c,
    )):
        raise M0Error("proxy-completion URL contains an opaque token")
    server.expected_root_query = query.copy()
    return (
        f"http://{server.server_address[0]}:{server.server_address[1]}{HOST_ROOT}/?"
        + urlencode(query)
    )


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


def verify_server_delivery(
    server: ChromeProfilePreferencesImportantFileWriterProxyCompletionServer,
) -> None:
    """Verify that all executable input bytes come from frozen server snapshots."""

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
                raise M0Error("proxy-completion snapshot request failed")
            headers = {key.lower(): value for key, value in response.getheaders()}
            for name, expected_value in _expected_headers(content_type).items():
                actual = headers.get(name, "")
                if name == "content-type":
                    actual = actual.split(";", 1)[0].strip().lower()
                if actual != expected_value:
                    raise M0Error("proxy-completion snapshot response header is invalid")
            count, digest = _stream_response_digest(response)
            if count != len(contents) or digest != hashlib.sha256(contents).hexdigest():
                raise M0Error("proxy-completion snapshot body changed")
        finally:
            connection.close()


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
        "abortObserved",
        "factoryRejectedExpectedExitStatus",
        "factoryRejectedUnexpected",
        "factoryResolved",
        "factorySettled",
        "failureRetirementMarkerObserved",
        "freshLeaseReacquiredMarkerObserved",
        "importantFileWriterEioObserved",
        "leaseReleasedMarkerObserved",
        "markerCount",
        "markerSequenceAccepted",
        "markerSource",
        "markers",
        "mode",
        "moduleIdentity",
        "onExitCount",
        "ordinal",
        "processExitCode",
        "processExitCount",
        "runtimeExitCode",
        "runtimeInitialized",
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
        "started",
        "completed",
        "quiet",
        "quietWindowMs",
        "callbacksAtStart",
        "callbacksAtEnd",
        "callbacksAtPreUploadCheck",
        "processExitReportsAtStart",
        "processExitReportsAtEnd",
        "processExitReportsAtPreUploadCheck",
        "activeRunAtResult",
    )
)
_HOST_BOUNDARY_FIELDS = frozenset(
    (
        "hostOpfsAccessAttempted",
        "hostWebLocksAccessAttempted",
        "nativeCallAttempted",
        "wasmProfileDataInspectionAttempted",
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
        "captureHarness",
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


def _require_exact_fields(value: object, fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise M0Error(f"proxy-completion {name} is invalid")
    return value


def _exact_json_equal(left: object, right: object) -> bool:
    return json.dumps(left, sort_keys=True, separators=(",", ":")) == json.dumps(
        right, sort_keys=True, separators=(",", ":")
    )


def _contains_prohibited_strings(value: object, prohibited: tuple[str, ...]) -> bool:
    if isinstance(value, str):
        return any(secret in value for secret in prohibited)
    if isinstance(value, list):
        return any(_contains_prohibited_strings(item, prohibited) for item in value)
    if isinstance(value, dict):
        return any(
            _contains_prohibited_strings(key, prohibited)
            or _contains_prohibited_strings(item, prohibited)
            for key, item in value.items()
        )
    return False


def _validate_byte_identity(value: object, description: str) -> None:
    value = _require_exact_fields(value, _BYTE_IDENTITY_FIELDS, description)
    if (
        type(value.get("bytes")) is not int
        or value["bytes"] < 1
        or not isinstance(value.get("sha256"), str)
        or not SHA256_RE.fullmatch(value["sha256"])
    ):
        raise M0Error(f"proxy-completion {description} is invalid")


def _validate_artifact_identity(value: object, expected: dict[str, object]) -> None:
    value = _require_exact_fields(value, _ARTIFACT_FIELDS, "artifact identity")
    if not _exact_json_equal(value, expected):
        raise M0Error("proxy-completion artifact identity is invalid")
    for field in ("build_config", "loader", "wasm"):
        _validate_byte_identity(value[field], f"artifact {field}")


def _validate_capture_harness_identity(value: object, expected: dict[str, object]) -> None:
    value = _require_exact_fields(value, _CAPTURE_HARNESS_FIELDS, "capture harness")
    if not _exact_json_equal(value, expected):
        raise M0Error("proxy-completion capture harness is invalid")
    for field in ("host_html", "host_js", "runner_source"):
        _validate_byte_identity(value[field], f"capture harness {field}")


def _validate_document(
    value: object, ordinal: int, expected: DocumentEvidence
) -> DocumentEvidence:
    value = _require_exact_fields(value, _DOCUMENT_FIELDS, "document")
    time_origin = value.get("timeOrigin")
    if (
        value.get("navigationType") != phase_navigation(ordinal)
        or not isinstance(time_origin, (int, float))
        or isinstance(time_origin, bool)
        or not math.isfinite(float(time_origin))
        or float(time_origin) <= 0
    ):
        raise M0Error("proxy-completion document is invalid")
    actual = DocumentEvidence(str(value["navigationType"]), float(time_origin))
    if actual != expected:
        raise M0Error("proxy-completion document disagrees with bootstrap")
    return actual


def _validate_token_evidence(value: object, ordinal: int, escrow: TokenEscrow) -> None:
    value = _require_exact_fields(value, _TOKEN_EVIDENCE_FIELDS, "token evidence")
    expected_a = None if ordinal == 4 else escrow.token_a_digest
    expected_b = None if ordinal == 1 else (
        escrow.token_b_digest if ordinal == 2 else escrow.token_c_digest
    )
    if (
        value.get("algorithm") != "SHA-256"
        or value.get("tokenA") != expected_a
        or value.get("tokenB") != expected_b
        or value.get("distinct") is not (ordinal in (2, 3))
        or value.get("rawTokensExcluded") is not True
        or value.get("rawTokenLeakDetected") is not False
        or type(value.get("rawTokenRedactionCount")) is not int
        or value["rawTokenRedactionCount"] != 0
    ):
        raise M0Error("proxy-completion token evidence is invalid")


def _validate_marker_array(value: object) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) > 16
        or not all(isinstance(item, str) and len(item) <= 160 for item in value)
    ):
        raise M0Error("proxy-completion run markers are invalid")
    return value


def _validate_run(value: object, ordinal: int, escrow: TokenEscrow) -> str:
    value = _require_exact_fields(value, _RUN_FIELDS, "run receipt")
    markers = _validate_marker_array(value.get("markers"))
    module_identity = value.get("moduleIdentity")
    expected = expected_markers(ordinal, escrow)
    if (
        value.get("mode") != phase_mode(ordinal)
        or type(value.get("ordinal")) is not int
        or value["ordinal"] != ordinal
        or not isinstance(module_identity, str)
        or not MODULE_ID_RE.fullmatch(module_identity)
        or value.get("markerSource") != "stderr-only-fixed-grammar"
        or value.get("markers") != expected
        or value.get("markerCount") != len(expected)
        or value.get("markerSequenceAccepted") is not True
        or value.get("stdoutMarkerCount") != 0
        or value.get("runtimeInitialized") is not True
        or value.get("factorySettled") is not True
        or value.get("factoryRejectedUnexpected") is not False
        or value.get("abortObserved") is not False
    ):
        raise M0Error("proxy-completion run receipt is invalid")

    is_failure = ordinal == 2
    expected_lease_release = not is_failure
    if (
        value.get("leaseReleasedMarkerObserved") is not expected_lease_release
        or value.get("importantFileWriterEioObserved") is not is_failure
        or value.get("failureRetirementMarkerObserved") is not is_failure
        or value.get("freshLeaseReacquiredMarkerObserved") is not (ordinal == 3)
    ):
        raise M0Error("proxy-completion run marker classification is invalid")
    if is_failure:
        process_exit = value.get("processExitCode")
        if (
            type(process_exit) is not int
            or process_exit <= 0
            or process_exit > 255
            or value.get("processExitCount") != 1
            or value.get("onExitCount") != 1
            or value.get("runtimeExitCode") != process_exit
            or (
                (value.get("factoryResolved") is not True
                 or value.get("factoryRejectedExpectedExitStatus") is not False)
                and (value.get("factoryResolved") is not False
                     or value.get("factoryRejectedExpectedExitStatus") is not True)
            )
        ):
            raise M0Error("proxy-completion clean nonzero failure exit is invalid")
    elif (
        value.get("processExitCount") != 1
        or value.get("processExitCode") != 0
        or value.get("onExitCount") != 1
        or value.get("runtimeExitCode") != 0
        or value.get("factoryResolved") is not True
        or value.get("factoryRejectedExpectedExitStatus") is not False
    ):
        raise M0Error("proxy-completion clean success exit is invalid")
    return module_identity


def _validate_bridge(value: object, ordinal: int) -> None:
    value = _require_exact_fields(value, _BRIDGE_FIELDS, "bridge")
    if (
        value.get("protocol") != 1
        or value.get("permanent") is not True
        or value.get("frozen") is not True
        or value.get("installedBeforeModuleFactory") is not True
        or value.get("processExitDispatches") != 1
        or value.get("activeRunAtResult") is not None
    ):
        raise M0Error("proxy-completion bridge is invalid")


def _validate_final_quiescence(value: object) -> None:
    value = _require_exact_fields(value, _FINAL_QUIESCENCE_FIELDS, "final quiescence")
    if (
        value.get("started") is not True
        or value.get("completed") is not True
        or value.get("quiet") is not True
        or value.get("quietWindowMs") != FINAL_QUIESCENCE_MS
        or value.get("activeRunAtResult") is not None
    ):
        raise M0Error("proxy-completion final quiescence is invalid")
    counter_fields = (
        "callbacksAtStart",
        "callbacksAtEnd",
        "callbacksAtPreUploadCheck",
        "processExitReportsAtStart",
        "processExitReportsAtEnd",
        "processExitReportsAtPreUploadCheck",
    )
    if any(type(value.get(field)) is not int or value[field] < 0 for field in counter_fields):
        raise M0Error("proxy-completion final quiescence counters are invalid")
    if len({value[field] for field in counter_fields[:3]}) != 1 or len(
        {value[field] for field in counter_fields[3:]}
    ) != 1:
        raise M0Error("proxy-completion final callbacks were not quiet")


def _validate_host_boundary(value: object) -> None:
    value = _require_exact_fields(value, _HOST_BOUNDARY_FIELDS, "host boundary")
    if any(field_value is not False for field_value in value.values()):
        raise M0Error("proxy-completion host crossed a prohibited boundary")


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
    """Validate one fully redacted fixed receipt before a CDP reload."""

    if _contains_prohibited_strings(
        result,
        (
            escrow.token_a,
            escrow.token_b,
            escrow.token_c,
            result_token,
            session,
        ),
    ):
        raise M0Error("proxy-completion receipt contains an opaque value")
    result = _require_exact_fields(result, _RESULT_FIELDS, "result")
    fixed = {
        "protocol": 1,
        "case": CASE,
        "scope": SCOPE,
        "status": phase_status(ordinal),
        "m7GateComplete": False,
        "ordinal": ordinal,
        "mode": phase_mode(ordinal),
        "origin": expected_origin,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "fatalErrors": [],
        "windowErrors": [],
        "unhandledRejections": [],
        "failedChecks": [],
        "error": None,
    }
    if any(result.get(name) != expected for name, expected in fixed.items()):
        raise M0Error("proxy-completion result identity is invalid")
    if result.get("versions") != expected_versions:
        raise M0Error("proxy-completion result versions are invalid")
    _validate_artifact_identity(result.get("artifact"), expected_artifact_identity)
    _validate_capture_harness_identity(
        result.get("captureHarness"), expected_capture_harness_identity
    )
    document = _validate_document(result.get("document"), ordinal, expected_document)
    _validate_token_evidence(result.get("tokenEvidence"), ordinal, escrow)
    module_identity = _validate_run(result.get("run"), ordinal, escrow)
    _validate_bridge(result.get("bridge"), ordinal)
    _validate_final_quiescence(result.get("finalQuiescence"))
    _validate_host_boundary(result.get("hostBoundary"))
    return PhaseResult(ordinal, document.navigation_type, document.time_origin, module_identity)


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
        raise M0Error("proxy-completion ready receipt is invalid")


def validate_four_document_transition(
    first: PhaseResult,
    second: PhaseResult,
    third: PhaseResult,
    fourth: PhaseResult,
) -> None:
    results = (first, second, third, fourth)
    if (
        tuple(result.ordinal for result in results) != (1, 2, 3, 4)
        or tuple(result.navigation_type for result in results)
        != ("navigate", "reload", "reload", "reload")
        or not (
            first.time_origin < second.time_origin < third.time_origin < fourth.time_origin
        )
        or len({result.module_identity for result in results}) != 4
    ):
        raise M0Error("proxy-completion four-document transition is invalid")


def _wait_for_receipt(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    raw_token_leak: threading.Event,
    receipts: queue.Queue[tuple[int, dict[str, Any]]],
    ordinal: int,
    deadline: float,
    kind: str,
) -> dict[str, Any]:
    while True:
        if raw_token_leak.is_set():
            raise M0Error("proxy-completion browser stderr contained an opaque token")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M0Error(
                f"proxy-completion {kind} timed out "
                f"({len(browser_stderr)} browser stderr lines suppressed)"
            )
        try:
            receipt_ordinal, receipt = receipts.get(timeout=min(0.1, remaining))
        except queue.Empty:
            if browser.poll() is not None:
                raise M0Error(
                    f"proxy-completion browser exited before {kind} "
                    f"({len(browser_stderr)} browser stderr lines suppressed)"
                )
            continue
        if receipt_ordinal != ordinal:
            raise M0Error("proxy-completion receipt order is invalid")
        return receipt


def wait_for_phase_result(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    raw_token_leak: threading.Event,
    server: ChromeProfilePreferencesImportantFileWriterProxyCompletionServer,
    ordinal: int,
    deadline: float,
) -> dict[str, Any]:
    return _wait_for_receipt(
        browser,
        browser_stderr,
        raw_token_leak,
        server.result_queue,
        ordinal,
        deadline,
        "result",
    )


def wait_for_ready_receipt(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    raw_token_leak: threading.Event,
    server: ChromeProfilePreferencesImportantFileWriterProxyCompletionServer,
    ordinal: int,
    deadline: float,
) -> dict[str, Any]:
    return _wait_for_receipt(
        browser,
        browser_stderr,
        raw_token_leak,
        server.ready_queue,
        ordinal,
        deadline,
        "ready receipt",
    )


def _root_frame_identity(value: object) -> RootFrameIdentity:
    if not isinstance(value, dict):
        raise M0Error("proxy-completion DevTools frame tree is invalid")
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
        raise M0Error("proxy-completion DevTools root frame is invalid")
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
    frame = params.get("frame") if isinstance(params, dict) else None
    if not isinstance(frame, dict):
        raise M0Error("proxy-completion DevTools navigation event is invalid")
    if frame.get("id") != baseline.frame_id:
        return None
    if "parentId" in frame:
        raise M0Error("proxy-completion DevTools root frame changed parent")
    loader_id = frame.get("loaderId")
    url = frame.get("url")
    if not isinstance(loader_id, str) or not loader_id:
        raise M0Error("proxy-completion DevTools navigation loader is invalid")
    if loader_id == baseline.loader_id:
        return None
    if not isinstance(url, str) or not url.startswith(expected_page_url_prefix):
        raise M0Error("proxy-completion DevTools navigation URL is invalid")
    return RootFrameIdentity(baseline.frame_id, loader_id)


def wait_for_root_reload_navigation(
    client: Any,
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    raw_token_leak: threading.Event,
    baseline: RootFrameIdentity,
    expected_page_url_prefix: str,
    deadline: float,
) -> RootFrameIdentity:
    while True:
        if raw_token_leak.is_set():
            raise M0Error("proxy-completion browser stderr contained an opaque token")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M0Error(
                "proxy-completion DevTools navigation timed out "
                f"({len(browser_stderr)} browser stderr lines suppressed)"
            )
        if browser.poll() is not None:
            raise M0Error(
                "proxy-completion browser exited before DevTools navigation "
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
    raw_token_leak: threading.Event,
    baseline: RootFrameIdentity,
    expected_page_url_prefix: str,
    deadline: float,
) -> RootFrameIdentity:
    """Perform exactly one trusted top-level document replacement via CDP."""

    client.call("Page.reload", {"ignoreCache": True})
    return wait_for_root_reload_navigation(
        client,
        browser,
        browser_stderr,
        raw_token_leak,
        baseline,
        expected_page_url_prefix,
        deadline,
    )


def _drain_browser_stderr(
    stream: Any,
    sink: deque[str],
    raw_token_leak: threading.Event,
    prohibited: tuple[str, ...],
) -> None:
    try:
        for line in iter(stream.readline, ""):
            if any(value in line for value in prohibited):
                raw_token_leak.set()
                sink.append("<suppressed-browser-stderr-token>")
            else:
                sink.append(line.rstrip("\n"))
    finally:
        try:
            stream.close()
        except OSError:
            pass


def write_failure_diagnostics(
    diagnostics_dir: Path,
    *,
    stage: str,
    error: Exception,
    browser: subprocess.Popen[str] | None,
    browser_stderr: deque[str],
    result_ordinals_received: set[int],
    ready_ordinals_received: set[int],
    reload_count: int,
) -> Path:
    """Persist runner-owned redacted failure state, never opaque evidence."""

    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / "chrome-profile-preferences-important-file-writer-proxy-completion-m7-failure.json"
    payload = {
        "schema_version": 1,
        "runner": Path(__file__).name,
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
        "cdp_page_reload_count": reload_count,
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return path


def _stop_server(
    server: ChromeProfilePreferencesImportantFileWriterProxyCompletionServer | None,
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
            raise M0Error("proxy-completion server did not stop")


def _summary() -> dict[str, object]:
    return {
        "case": CASE,
        "documents": 4,
        "cdpTopLevelReloads": 3,
        "canonicalPreferencesImportantFileWriterPostFlushEioProven": True,
        "failedBWasNotPublishedBeforeFreshDocumentRecovery": True,
        "freshDocumentLeaseReacquisitionObserved": True,
        "normalProfilePersistenceProven": False,
        "physicalCrashBehaviorProven": False,
        "directoryDurabilityProven": False,
        "liveLockContentionProven": False,
        "fullChromiumProfileProven": False,
        "m7GateComplete": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prove a four-document canonical Chrome Preferences "
            "ImportantFileWriter post-flush proxy-completion failure path."
        ),
        epilog=(
            "Build the isolated artifact with: buildtools/linux64/gn gen "
            + str(DEFAULT_OUT_DIR)
            + " --args='"
            + DEFAULT_GN_ARGUMENTS.replace("\n", " ")
            + "' --fail-on-unused-args; autoninja -C "
            + str(DEFAULT_OUT_DIR)
            + " chrome_wasm"
        ),
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--diagnostics-dir", type=Path)
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--timeout", type=parse_proxy_completion_timeout, default=180.0)
    args = parser.parse_args()
    if args.timeout < MIN_TIMEOUT_SECONDS:
        parser.error(f"--timeout must be at least {MIN_TIMEOUT_SECONDS:g} seconds")

    browser: subprocess.Popen[str] | None = None
    browser_stderr: deque[str] = deque(maxlen=MAX_BROWSER_STDERR_LINES)
    browser_stderr_thread: threading.Thread | None = None
    raw_token_leak = threading.Event()
    client: Any | None = None
    outer_profile: tempfile.TemporaryDirectory[str] | None = None
    server: ChromeProfilePreferencesImportantFileWriterProxyCompletionServer | None = None
    server_thread: threading.Thread | None = None
    server_thread_started = False
    result_ordinals_received: set[int] = set()
    ready_ordinals_received: set[int] = set()
    reload_count = 0
    stage = "initialize"
    accepted_summary: dict[str, object] | None = None

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
        url = smoke_url(
            server,
            result_token,
            session,
            versions,
            artifact=artifact,
            capture_harness=capture_harness,
            timeout_seconds=args.timeout,
        )
        server_thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.05},
            name="chromium-wasm-m7-preferences-important-file-writer-server",
            daemon=True,
        )
        server_thread.start()
        server_thread_started = True
        stage = "verify-server-delivery"
        verify_server_delivery(server)
        expected_origin = f"http://{server.server_address[0]}:{server.server_address[1]}"
        stage = "find-browser"
        browser_path, _browser_version = find_browser(args.browser)
        outer_profile = tempfile.TemporaryDirectory(
            prefix="chromium-wasm-m7-preferences-important-file-writer-"
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
            target=_drain_browser_stderr,
            args=(
                browser.stderr,
                browser_stderr,
                raw_token_leak,
                (escrow.token_a, escrow.token_b, escrow.token_c),
            ),
            name="chromium-wasm-m7-preferences-important-file-writer-stderr",
            daemon=True,
        )
        browser_stderr_thread.start()
        # The page owns the actual lifecycle deadline passed through its query
        # parameter. Keep a short runner-side allowance after that bound so a
        # terminal page receipt remains diagnosable when it races the outer
        # protocol deadline.
        deadline = time.monotonic() + args.timeout + RESULT_RECEIPT_GRACE_SECONDS
        expected_page_url_prefix = url.split("?", 1)[0]

        stage = "connect-devtools-document-one"
        client = wait_for_page_client(debug_port, expected_page_url_prefix, deadline)
        root_frame = prepare_outer_document_reload(client)
        root_frame_id = root_frame.frame_id
        loader_ids = {root_frame.loader_id}

        stage = "wait-document-one-result"
        first_result = wait_for_phase_result(
            browser, browser_stderr, raw_token_leak, server, 1, deadline
        )
        result_ordinals_received.add(1)
        stage = "validate-document-one-result"
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
        stage = "wait-document-one-ready"
        first_ready = wait_for_ready_receipt(
            browser, browser_stderr, raw_token_leak, server, 1, deadline
        )
        ready_ordinals_received.add(1)
        validate_ready_receipt(first_ready, expected=first)
        stage = "arm-document-two"
        server.session.arm_next_document(1, first.time_origin)
        stage = "reload-document-two"
        root_frame = reload_outer_document(
            client,
            browser,
            browser_stderr,
            raw_token_leak,
            root_frame,
            expected_page_url_prefix,
            deadline,
        )
        reload_count += 1
        if root_frame.frame_id != root_frame_id or root_frame.loader_id in loader_ids:
            raise M0Error("proxy-completion first reload did not replace the root document")
        loader_ids.add(root_frame.loader_id)

        stage = "wait-document-two-result"
        second_result = wait_for_phase_result(
            browser, browser_stderr, raw_token_leak, server, 2, deadline
        )
        result_ordinals_received.add(2)
        stage = "validate-document-two-result"
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
        stage = "wait-document-two-ready"
        second_ready = wait_for_ready_receipt(
            browser, browser_stderr, raw_token_leak, server, 2, deadline
        )
        ready_ordinals_received.add(2)
        validate_ready_receipt(second_ready, expected=second)
        stage = "arm-document-three-after-retained-failure-lease"
        server.session.arm_next_document(2, second.time_origin)
        stage = "reload-document-three"
        root_frame = reload_outer_document(
            client,
            browser,
            browser_stderr,
            raw_token_leak,
            root_frame,
            expected_page_url_prefix,
            deadline,
        )
        reload_count += 1
        if root_frame.frame_id != root_frame_id or root_frame.loader_id in loader_ids:
            raise M0Error("proxy-completion second reload did not replace the root document")
        loader_ids.add(root_frame.loader_id)

        stage = "wait-document-three-result"
        third_result = wait_for_phase_result(
            browser, browser_stderr, raw_token_leak, server, 3, deadline
        )
        result_ordinals_received.add(3)
        stage = "validate-document-three-result"
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
        stage = "wait-document-three-ready"
        third_ready = wait_for_ready_receipt(
            browser, browser_stderr, raw_token_leak, server, 3, deadline
        )
        ready_ordinals_received.add(3)
        validate_ready_receipt(third_ready, expected=third)
        stage = "arm-document-four"
        server.session.arm_next_document(3, third.time_origin)
        stage = "reload-document-four"
        root_frame = reload_outer_document(
            client,
            browser,
            browser_stderr,
            raw_token_leak,
            root_frame,
            expected_page_url_prefix,
            deadline,
        )
        reload_count += 1
        if root_frame.frame_id != root_frame_id or root_frame.loader_id in loader_ids:
            raise M0Error("proxy-completion third reload did not replace the root document")
        loader_ids.add(root_frame.loader_id)

        stage = "wait-document-four-result"
        fourth_result = wait_for_phase_result(
            browser, browser_stderr, raw_token_leak, server, 4, deadline
        )
        result_ordinals_received.add(4)
        stage = "validate-document-four-result"
        fourth = validate_phase_result(
            fourth_result,
            ordinal=4,
            expected_versions=versions,
            expected_artifact_identity=artifact,
            expected_capture_harness_identity=capture_harness,
            expected_origin=expected_origin,
            expected_document=server.session.document_evidence(4),
            escrow=escrow,
            result_token=result_token,
            session=session,
        )
        stage = "wait-document-four-ready"
        fourth_ready = wait_for_ready_receipt(
            browser, browser_stderr, raw_token_leak, server, 4, deadline
        )
        ready_ordinals_received.add(4)
        validate_ready_receipt(fourth_ready, expected=fourth)
        stage = "validate-four-document-transition"
        validate_four_document_transition(first, second, third, fourth)
        if reload_count != 3 or len(loader_ids) != 4 or raw_token_leak.is_set():
            raise M0Error("proxy-completion reload or opaque-token evidence is invalid")
        accepted_summary = _summary()
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
                    reload_count=reload_count,
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
            accepted_summary = None
        if outer_profile is not None:
            outer_profile.cleanup()

    if accepted_summary is not None and not raw_token_leak.is_set():
        print(
            SENTINEL
            + ":PASS "
            + json.dumps(accepted_summary, sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
