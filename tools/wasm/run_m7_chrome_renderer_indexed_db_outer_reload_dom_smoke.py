#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the renderer IndexedDB witness across two real outer Page.reload calls.

The three documents load three fresh instances of the source-selected
``chrome_wasm_m7_profile_indexed_db_test`` module.  Raw A/B values exist only
in this process's in-memory escrow, one-shot same-origin bootstrap responses,
and the module argv.  The outer host never uses a storage, lock, native-call,
or Wasm-memory API.  The browser-owned ``chrome://m7-indexed-db/`` page is the
only code that uses IndexedDB.

This is an orderly close/reopen smoke, not a claim of M7 completion, crash
durability, broad profile persistence, or general StoragePartition behavior.
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
from run_browser_smoke import browser_command, find_browser, stop_browser


SENTINEL = "CHROMIUM_WASM_M7_RENDERER_INDEXED_DB_OUTER_RELOAD_DOM"
CASE = "chrome_renderer_indexed_db_three_outer_document_reload_m7"
SCOPE = (
    "same-origin-three-outer-documents-chrome-wasm-m7-renderer-database-"
    "test-modules-orderly-close-reopen-only"
)
PRODUCT_MODULE_NAME = "chrome_wasm_m7_profile_indexed_db_test"
PRODUCT_GN_TARGET = "//chrome:chrome_wasm"
PRODUCT_GN_ENABLE_ARGUMENT = "enable_chromium_wasm_m7_profile_indexed_db_test=true"
DEFAULT_OUT_DIR = Path("out/wasm-chrome-m7-profile-indexed-db")
DEFAULT_GN_ARGUMENTS = (
    'import("//out/wasm-chrome-m6/args.gn") ' + PRODUCT_GN_ENABLE_ARGUMENT
)
HOST_ROOT = "/__m7_renderer_indexed_db_outer_reload__"
HOST_HTML_NAME = "chrome_wasm_renderer_indexed_db_outer_reload_smoke.html"
HOST_JS_NAME = "chrome_wasm_renderer_indexed_db_outer_reload_smoke.js"
MARKER_PREFIX = "CHROMIUM_WASM_M7_INDEXED_DB:"
ARTIFACT_DELIVERY = "immutable-in-memory-server-snapshot"
ARTIFACT_SOURCE_PROVENANCE = "unverified"
BUILD_CONFIG_PROVENANCE = "selected-out-dir-args-gn-immutable-snapshot"
SOURCE_SNAPSHOT_PROVENANCE = (
    "on-disk-byte-snapshots-at-server-startup-not-commit-provenance"
)
VERSION_PROVENANCE = (
    "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance"
)
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024 * 1024
MAX_RESULT_BYTES = 256 * 1024
MAX_RECEIPT_BYTES = 8 * 1024
MAX_BROWSER_STDERR_LINES = 300
MAX_OUTPUT_LINES = 128
MIN_TIMEOUT_SECONDS = 20.0
MAX_TIMEOUT_MS = 300_000
DEFAULT_TIMEOUT_SECONDS = 300.0
OPAQUE_TOKEN_TAIL_CHARS = 63
SUPPRESSED_BROWSER_STDERR_TOKEN = "<suppressed-browser-stderr-token>"

CAPABILITY_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
MODULE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
M7_GN_ASSIGNMENT_RE = re.compile(
    r"^[ \t]*(enable_chromium_wasm_m7_[a-z0-9_]+)[ \t]*="
    r"[ \t]*(true|false)[ \t]*(?:#.*)?$",
    re.MULTILINE,
)

_ROOT_QUERY_FIELDS = frozenset(
    (
        "artifact",
        "captureHarness",
        "module",
        "resultToken",
        "session",
        "timeoutMs",
        "versions",
    )
)
_IDENTITY_FIELDS = frozenset(("bytes", "sha256"))
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
_HARNESS_FIELDS = frozenset(
    (
        "host_html",
        "host_js",
        "runner_source",
        "source_snapshot_provenance",
        "version_provenance",
    )
)
_RESULT_FIELDS = frozenset(
    (
        "artifact",
        "bridge",
        "captureHarness",
        "case",
        "document",
        "hostBoundary",
        "m7GateComplete",
        "mode",
        "ordinal",
        "origin",
        "phase",
        "protocol",
        "quiescence",
        "run",
        "scope",
        "sharedArrayBuffer",
        "status",
        "tokenEvidence",
        "versions",
    )
)
_DOCUMENT_FIELDS = frozenset(("identity", "navigationType", "timeOrigin"))
_POST_DOCUMENT_FIELDS = frozenset(
    ("case", "navigationType", "protocol", "scope", "timeOrigin")
)
_READY_FIELDS = frozenset(("case", "ordinal", "protocol", "scope", "timeOrigin"))
_TOKEN_EVIDENCE_FIELDS = frozenset(
    (
        "algorithm",
        "rawTokensExcluded",
        "rawTokenLeakDetected",
        "rawTokenRedactionCount",
        "tokenADigest",
        "tokenBDigest",
    )
)
_HOST_BOUNDARY_FIELDS = frozenset(
    (
        "hostDatabaseAccessAttempted",
        "hostOpfsAccessAttempted",
        "hostWebLocksAccessAttempted",
        "nativeCallAttempted",
        "wasmMemoryInspectionAttempted",
    )
)
_BRIDGE_FIELDS = frozenset(
    (
        "activeAtResult",
        "frozen",
        "installedBeforeModuleFactory",
        "permanent",
        "processExitDispatches",
        "protocol",
    )
)
_QUIESCENCE_FIELDS = frozenset(
    ("callbacksAfterQuiescence", "callbacksAtClear", "quiet", "quietWindowMs")
)
_RUN_FIELDS = frozenset(
    (
        "abortObserved",
        "expectedCleanExitStatusObserved",
        "factoryRejected",
        "factoryResolved",
        "factorySettled",
        "freshLoaderImport",
        "freshModuleObject",
        "lifecycleComplete",
        "markerCount",
        "markerSequenceAccepted",
        "markerSource",
        "markers",
        "moduleIdentity",
        "onExitCount",
        "ordinal",
        "outputLineCount",
        "processExitCode",
        "processExitCount",
        "runtimeExitCode",
        "runtimeInitialized",
        "stdoutMarkerCount",
    )
)


@dataclass(frozen=True)
class TokenEscrow:
    """Raw values are intentionally absent from reprs and diagnostics."""

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
    """A capability-bound outer-document protocol conflict."""


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
    if not all(CAPABILITY_RE.fullmatch(value) for value in (result_token, session)):
        raise M0Error("renderer IndexedDB capability generation is invalid")
    return result_token, session


def phase_for_ordinal(ordinal: int) -> tuple[str, str]:
    phases = {
        1: ("write-a", "renderer-write"),
        2: ("verify-a-write-b", "renderer-verify-a-write-b"),
        3: ("verify-b", "renderer-verify-b"),
    }
    try:
        return phases[ordinal]
    except KeyError as exc:
        raise M0Error("renderer IndexedDB ordinal is invalid") from exc


def expected_markers(ordinal: int, escrow: TokenEscrow) -> list[str]:
    if ordinal == 1:
        return [
            f"{MARKER_PREFIX}READY",
            f"{MARKER_PREFIX}RENDERER_WRITE_OK sha256={escrow.token_a_digest}",
            f"{MARKER_PREFIX}BACKING_STORES_CLOSED sha256={escrow.token_a_digest}",
            f"{MARKER_PREFIX}FENCE_OK sha256={escrow.token_a_digest}",
            f"{MARKER_PREFIX}LEASE_RELEASED",
        ]
    if ordinal == 2:
        return [
            f"{MARKER_PREFIX}READY",
            f"{MARKER_PREFIX}RENDERER_REOPEN_READ_A_OK sha256={escrow.token_a_digest}",
            f"{MARKER_PREFIX}RENDERER_WRITE_B_OK sha256={escrow.token_b_digest}",
            f"{MARKER_PREFIX}BACKING_STORES_CLOSED sha256={escrow.token_b_digest}",
            f"{MARKER_PREFIX}FENCE_OK sha256={escrow.token_b_digest}",
            f"{MARKER_PREFIX}LEASE_RELEASED",
        ]
    if ordinal == 3:
        return [
            f"{MARKER_PREFIX}READY",
            f"{MARKER_PREFIX}RENDERER_REOPEN_READ_B_OK sha256={escrow.token_b_digest}",
            f"{MARKER_PREFIX}BACKING_STORES_CLOSED sha256={escrow.token_b_digest}",
            f"{MARKER_PREFIX}FENCE_OK sha256={escrow.token_b_digest}",
            f"{MARKER_PREFIX}LEASE_RELEASED",
        ]
    raise M0Error("renderer IndexedDB marker ordinal is invalid")


def _valid_document(value: object) -> bool:
    return (
        isinstance(value, DocumentEvidence)
        and value.navigation_type in ("navigate", "reload")
        and math.isfinite(value.time_origin)
        and value.time_origin > 0
    )


class OuterReloadSession:
    """Server-only escrow and ordered three-document reload state."""

    def __init__(self, result_token: str, session: str, escrow: TokenEscrow):
        if (
            not all(CAPABILITY_RE.fullmatch(value) for value in (result_token, session))
            or secrets.compare_digest(result_token, session)
            or not all(SHA256_RE.fullmatch(value) for value in (escrow.token_a, escrow.token_b))
            or secrets.compare_digest(escrow.token_a, escrow.token_b)
            or escrow.token_a_digest != _sha256_text(escrow.token_a)
            or escrow.token_b_digest != _sha256_text(escrow.token_b)
        ):
            raise M0Error("renderer IndexedDB session escrow is invalid")
        self._result_token = result_token
        self._session = session
        self.escrow = escrow
        self._lock = threading.Lock()
        self._acknowledgement_gate = threading.Lock()
        self._documents: dict[int, DocumentEvidence] = {}
        self._pending_document: tuple[int, DocumentEvidence] | None = None
        self._bootstraps: set[int] = set()
        self._results: set[int] = set()
        self._ready: set[int] = set()
        self._armed_ordinal = 1
        self._root_navigation_ordinal: int | None = None
        self._failure_ordinal: int | None = None

    def matches_result_token(self, value: object) -> bool:
        return isinstance(value, str) and secrets.compare_digest(value, self._result_token)

    def matches_session(self, value: object) -> bool:
        return isinstance(value, str) and secrets.compare_digest(value, self._session)

    def acknowledgement_gate(self) -> threading.Lock:
        return self._acknowledgement_gate

    def prohibited_values(self) -> tuple[str, str, str, str]:
        return self.escrow.token_a, self.escrow.token_b, self._result_token, self._session

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
            ordinal = self._armed_ordinal
            if (
                ordinal not in (1, 2, 3)
                or self._root_navigation_ordinal is not None
                or ordinal in self._documents
                or ordinal in self._bootstraps
                or self._pending_document is not None
                or self._failure_ordinal is not None
            ):
                return False
            self._root_navigation_ordinal = ordinal
            return True

    def accept_document(self, session: object, evidence: DocumentEvidence) -> bool:
        if not self.matches_session(session):
            return False
        if not _valid_document(evidence):
            raise ProtocolStateError("renderer IndexedDB document evidence is invalid")
        with self._lock:
            ordinal = self._armed_ordinal
            expected_navigation = "navigate" if ordinal == 1 else "reload"
            prior = self._documents.get(ordinal - 1)
            if (
                ordinal not in (1, 2, 3)
                or self._root_navigation_ordinal != ordinal
                or self._pending_document is not None
                or ordinal in self._documents
                or ordinal in self._bootstraps
                or evidence.navigation_type != expected_navigation
                or (prior is not None and evidence.time_origin <= prior.time_origin)
                or (ordinal > 1 and prior is None)
            ):
                raise ProtocolStateError("renderer IndexedDB document state conflict")
            self._pending_document = (ordinal, evidence)
            return True

    def acknowledge_document(self, session: object) -> None:
        if not self.matches_session(session):
            raise ProtocolStateError("renderer IndexedDB document acknowledgement is invalid")
        with self._lock:
            if self._pending_document is None:
                raise ProtocolStateError("renderer IndexedDB document acknowledgement conflict")
            ordinal, evidence = self._pending_document
            if ordinal != self._armed_ordinal or ordinal in self._documents:
                raise ProtocolStateError("renderer IndexedDB document acknowledgement conflict")
            self._documents[ordinal] = evidence
            self._pending_document = None

    def bootstrap_payload(self, session: object) -> dict[str, object] | None:
        if not self.matches_session(session):
            return None
        with self._acknowledgement_gate:
            with self._lock:
                ordinal = self._armed_ordinal
                if (
                    ordinal not in self._documents
                    or ordinal in self._bootstraps
                    or self._root_navigation_ordinal != ordinal
                    or self._failure_ordinal is not None
                ):
                    raise ProtocolStateError("renderer IndexedDB bootstrap state conflict")
                self._bootstraps.add(ordinal)
        phase, mode = phase_for_ordinal(ordinal)
        return {
            "case": CASE,
            "mode": mode,
            "ordinal": ordinal,
            "phase": phase,
            "protocol": 1,
            "scope": SCOPE,
            "tokenA": None if ordinal == 3 else self.escrow.token_a,
            "tokenADigest": None if ordinal == 3 else self.escrow.token_a_digest,
            "tokenB": None if ordinal == 1 else self.escrow.token_b,
            "tokenBDigest": None if ordinal == 1 else self.escrow.token_b_digest,
        }

    def accept_result(self, result_token: object, ordinal: int) -> bool:
        if not self.matches_result_token(result_token):
            return False
        with self._lock:
            if (
                ordinal != self._armed_ordinal
                or ordinal not in self._bootstraps
                or ordinal in self._results
                or self._failure_ordinal is not None
            ):
                raise ProtocolStateError("renderer IndexedDB result state conflict")
            self._results.add(ordinal)
            return True

    def accept_ready(self, result_token: object, ordinal: int) -> bool:
        if not self.matches_result_token(result_token):
            return False
        with self._lock:
            if (
                ordinal != self._armed_ordinal
                or ordinal not in self._results
                or ordinal in self._ready
                or self._failure_ordinal is not None
            ):
                raise ProtocolStateError("renderer IndexedDB ready state conflict")
            self._ready.add(ordinal)
            return True

    def accept_failure(self, result_token: object, ordinal: int) -> bool:
        if not self.matches_result_token(result_token):
            return False
        with self._lock:
            if (
                ordinal != self._armed_ordinal
                or ordinal not in self._bootstraps
                or ordinal in self._results
                or self._failure_ordinal is not None
            ):
                raise ProtocolStateError("renderer IndexedDB failure state conflict")
            self._failure_ordinal = ordinal
            return True

    def arm_next_reload(self, completed_ordinal: int, time_origin: float) -> None:
        if (
            completed_ordinal not in (1, 2)
            or not isinstance(time_origin, (int, float))
            or isinstance(time_origin, bool)
            or not math.isfinite(float(time_origin))
        ):
            raise M0Error("renderer IndexedDB reload authorization is invalid")
        with self._lock:
            document = self._documents.get(completed_ordinal)
            if (
                self._armed_ordinal != completed_ordinal
                or document is None
                or document.time_origin != float(time_origin)
                or completed_ordinal not in self._bootstraps
                or completed_ordinal not in self._results
                or completed_ordinal not in self._ready
                or self._root_navigation_ordinal != completed_ordinal
                or self._pending_document is not None
                or self._failure_ordinal is not None
            ):
                raise ProtocolStateError("renderer IndexedDB reload authorization conflict")
            self._armed_ordinal += 1
            self._root_navigation_ordinal = None

    def document_evidence(self, ordinal: int) -> DocumentEvidence:
        with self._lock:
            try:
                return self._documents[ordinal]
            except KeyError as exc:
                raise ProtocolStateError("renderer IndexedDB document is unavailable") from exc


def parse_timeout(value: str) -> float:
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
            f"timeout must be finite in [{MIN_TIMEOUT_SECONDS:g}, "
            f"{MAX_TIMEOUT_MS / 1000:g}]"
        )
    return timeout


def validate_m7_output_configuration(args_gn: bytes, out_dir: Path) -> None:
    """Require only the dedicated source-selected IndexedDB artifact."""

    if out_dir.name != DEFAULT_OUT_DIR.name:
        raise M0Error("renderer IndexedDB runner requires its isolated output")
    try:
        text = args_gn.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError as exc:
        raise M0Error("renderer IndexedDB args.gn is not UTF-8") from exc
    assignments = M7_GN_ASSIGNMENT_RE.findall(text)
    own = [value for name, value in assignments if name == PRODUCT_GN_ENABLE_ARGUMENT[:-5]]
    if not own or any(value != "true" for value in own):
        raise M0Error("renderer IndexedDB args.gn lacks its dedicated test opt-in")
    if any(name != PRODUCT_GN_ENABLE_ARGUMENT[:-5] and value == "true" for name, value in assignments):
        raise M0Error("renderer IndexedDB args.gn enables another M7 artifact")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON constant")


def _parse_json_object(payload: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
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


def _exact_fields(value: object, fields: frozenset[str], description: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise M0Error(f"renderer IndexedDB {description} schema is invalid")
    return value


def _byte_identity(contents: bytes) -> dict[str, object]:
    return {"bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}


def _validate_identity(value: object, expected: dict[str, object], description: str) -> None:
    fields = _ARTIFACT_FIELDS if description == "artifact" else _HARNESS_FIELDS
    actual = _exact_fields(value, fields, description)
    identity_fields = ("build_config", "loader", "wasm") if description == "artifact" else (
        "host_html",
        "host_js",
        "runner_source",
    )
    for name in identity_fields:
        identity = _exact_fields(actual.get(name), _IDENTITY_FIELDS, f"{description} {name}")
        if (
            type(identity.get("bytes")) is not int
            or identity["bytes"] < 1
            or not isinstance(identity.get("sha256"), str)
            or not SHA256_RE.fullmatch(identity["sha256"])
        ):
            raise M0Error(f"renderer IndexedDB {description} identity is invalid")
    if actual != expected:
        raise M0Error(f"renderer IndexedDB {description} differs from its snapshot")


class RendererIndexedDBOuterReloadServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, _request: object, _address: object) -> None:
        # Request paths carry capabilities; never let socketserver print them.
        return


class RendererIndexedDBOuterReloadRequestHandler(BaseHTTPRequestHandler):
    server: RendererIndexedDBOuterReloadServer

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
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

    @staticmethod
    def _one(query: dict[str, list[str]], name: str) -> str | None:
        values = query.get(name)
        return values[0] if isinstance(values, list) and len(values) == 1 else None

    def _matches_expected_root_query(self, query: dict[str, list[str]]) -> bool:
        expected = self.server.expected_root_query
        return (
            isinstance(expected, dict)
            and set(query) == _ROOT_QUERY_FIELDS
            and set(expected) == _ROOT_QUERY_FIELDS
            and all(query.get(name) == [expected[name]] for name in _ROOT_QUERY_FIELDS)
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
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip()
        if content_type.lower() != "application/json":
            return None
        payload = self.rfile.read(length)
        return _parse_json_object(payload) if len(payload) == length else None

    @staticmethod
    def _capability_path(path: str, prefix: str) -> str | None:
        if not path.startswith(prefix):
            return None
        token = path[len(prefix) :]
        return token if "/" not in token and CAPABILITY_RE.fullmatch(token) else None

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

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path in (HOST_ROOT, f"{HOST_ROOT}/"):
            if parsed.query:
                query = parse_qs(parsed.query, keep_blank_values=True)
                if not self._matches_expected_root_query(query) or not self.server.session.observe_top_level_root_navigation(
                    self._one(query, "resultToken"),
                    self._one(query, "session"),
                    self.headers.get("Sec-Fetch-Dest"),
                    self.headers.get("Sec-Fetch-Mode"),
                ):
                    self._conflict()
                    return
            self._send_bytes(HTTPStatus.OK, "text/html; charset=utf-8", self.server.host_html)
            return
        if parsed.query:
            self._not_found()
            return
        if parsed.path == f"{HOST_ROOT}/{HOST_JS_NAME}":
            self._send_bytes(
                HTTPStatus.OK, "text/javascript; charset=utf-8", self.server.host_js
            )
            return
        artifact_prefix = f"{HOST_ROOT}/artifacts/"
        if parsed.path.startswith(artifact_prefix):
            name = parsed.path[len(artifact_prefix) :]
            artifact = self.server.artifacts.get(name)
            if artifact is not None and "/" not in name:
                content_type = "application/wasm" if name.endswith(".wasm") else "text/javascript; charset=utf-8"
                self._send_bytes(HTTPStatus.OK, content_type, artifact)
                return
        session = self._capability_path(parsed.path, f"{HOST_ROOT}/bootstrap/")
        if session is not None:
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

    def do_POST(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.query:
            self._not_found()
            return
        session = self._capability_path(parsed.path, f"{HOST_ROOT}/bootstrap/")
        if session is not None:
            self._post_document(session)
            return
        for prefix, handler in (
            (f"{HOST_ROOT}/result/", self._post_result),
            (f"{HOST_ROOT}/ready/", self._post_ready),
            (f"{HOST_ROOT}/failure/", self._post_failure),
        ):
            receipt = self._receipt_path(parsed.path, prefix)
            if receipt is not None:
                handler(*receipt)
                return
        self._not_found()

    def _post_document(self, session: str) -> None:
        if not self.server.session.matches_session(session):
            self._not_found()
            return
        value = self._read_json_body(MAX_RECEIPT_BYTES)
        evidence = _parse_document_evidence(value)
        if evidence is None:
            self._send_bytes(HTTPStatus.BAD_REQUEST, "text/plain; charset=utf-8", b"invalid document\n")
            return
        with self.server.session.acknowledgement_gate():
            try:
                accepted = self.server.session.accept_document(session, evidence)
            except ProtocolStateError:
                self._conflict()
                return
            if not accepted:
                self._not_found()
                return
            # A raw bootstrap cannot become available before this visible 204.
            self._send_empty(HTTPStatus.NO_CONTENT)
            try:
                self.wfile.flush()
            except OSError:
                return
            try:
                self.server.session.acknowledge_document(session)
            except ProtocolStateError:
                return

    def _post_result(self, result_token: str, ordinal: int) -> None:
        value = self._read_json_body(MAX_RESULT_BYTES)
        if (
            value is None
            or _contains_prohibited_strings(value, self.server.session.prohibited_values())
            or not _receipt_identity(value, ordinal)
        ):
            self._send_bytes(HTTPStatus.BAD_REQUEST, "text/plain; charset=utf-8", b"invalid result\n")
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
        value = self._read_json_body(MAX_RECEIPT_BYTES)
        if (
            value is None
            or _contains_prohibited_strings(value, self.server.session.prohibited_values())
            or not _receipt_identity(value, ordinal)
        ):
            self._send_bytes(HTTPStatus.BAD_REQUEST, "text/plain; charset=utf-8", b"invalid ready\n")
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
        # Notification after send + flush is the only reload authorization.
        self._send_empty(HTTPStatus.NO_CONTENT)
        try:
            self.wfile.flush()
            self.server.ready_queue.put_nowait((ordinal, value))
        except (OSError, queue.Full):
            return

    def _post_failure(self, result_token: str, ordinal: int) -> None:
        value = self._read_json_body(MAX_RECEIPT_BYTES)
        if (
            value is None
            or _contains_prohibited_strings(value, self.server.session.prohibited_values())
            or set(value) != frozenset(("case", "ordinal", "protocol", "status"))
            or value.get("case") != CASE
            or value.get("ordinal") != ordinal
            or value.get("protocol") != 1
            or value.get("status") != "fail"
        ):
            self._send_bytes(HTTPStatus.BAD_REQUEST, "text/plain; charset=utf-8", b"invalid failure\n")
            return
        try:
            accepted = self.server.session.accept_failure(result_token, ordinal)
        except ProtocolStateError:
            self._conflict()
            return
        if not accepted:
            self._not_found()
            return
        self._send_empty(HTTPStatus.NO_CONTENT)
        try:
            self.wfile.flush()
            self.server.failure_queue.put_nowait(ordinal)
        except (OSError, queue.Full):
            return


def _parse_document_evidence(value: object) -> DocumentEvidence | None:
    if not isinstance(value, dict) or set(value) != _POST_DOCUMENT_FIELDS:
        return None
    time_origin = value.get("timeOrigin")
    if (
        value.get("case") != CASE
        or value.get("protocol") != 1
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
        and value.get("case") == CASE
        and value.get("protocol") == 1
        and value.get("scope") == SCOPE
        and type(value.get("ordinal")) is int
        and value.get("ordinal") == ordinal
    )


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
) -> RendererIndexedDBOuterReloadServer:
    """Snapshot the selected module, args, and host before serving any bytes."""

    artifacts = snapshot_regular_files(
        out_dir,
        (f"{PRODUCT_MODULE_NAME}.js", f"{PRODUCT_MODULE_NAME}.wasm"),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="renderer IndexedDB outer-reload artifacts",
    )
    args_gn = snapshot_regular_file(
        out_dir / "args.gn",
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="renderer IndexedDB selected args.gn",
    )
    validate_m7_output_configuration(args_gn, out_dir)
    host_files = snapshot_regular_files(
        host_dir or Path(__file__).with_name("host"),
        (HOST_HTML_NAME, HOST_JS_NAME),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="renderer IndexedDB outer-reload host",
    )
    runner_source = snapshot_regular_file(
        runner_source_path or Path(__file__),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="renderer IndexedDB outer-reload runner",
    )
    server = RendererIndexedDBOuterReloadServer(
        (host, port), RendererIndexedDBOuterReloadRequestHandler
    )
    server.args_gn = args_gn
    server.artifacts = artifacts
    server.host_html = host_files[HOST_HTML_NAME]
    server.host_js = host_files[HOST_JS_NAME]
    server.runner_source = runner_source
    server.session = OuterReloadSession(result_token, session, escrow)
    server.result_queue: queue.Queue[tuple[int, dict[str, Any]]] = queue.Queue(maxsize=3)
    server.ready_queue: queue.Queue[tuple[int, dict[str, Any]]] = queue.Queue(maxsize=3)
    server.failure_queue: queue.Queue[int] = queue.Queue(maxsize=1)
    server.receipt_lock = threading.Lock()
    server.expected_root_query: dict[str, str] | None = None
    return server


def artifact_identity(server: RendererIndexedDBOuterReloadServer) -> dict[str, object]:
    return {
        "artifact_delivery": ARTIFACT_DELIVERY,
        "artifact_source_provenance": ARTIFACT_SOURCE_PROVENANCE,
        "build_config": _byte_identity(server.args_gn),
        "build_config_provenance": BUILD_CONFIG_PROVENANCE,
        "loader": _byte_identity(server.artifacts[f"{PRODUCT_MODULE_NAME}.js"]),
        "module_name": PRODUCT_MODULE_NAME,
        "wasm": _byte_identity(server.artifacts[f"{PRODUCT_MODULE_NAME}.wasm"]),
    }


def capture_harness_identity(server: RendererIndexedDBOuterReloadServer) -> dict[str, object]:
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
        raise M0Error("renderer IndexedDB manifest lacks version metadata") from exc
    if not all(isinstance(value, str) and GIT_REVISION_RE.fullmatch(value) for value in versions.values()):
        raise M0Error("renderer IndexedDB manifest version metadata is invalid")
    return versions


def smoke_url(
    server: RendererIndexedDBOuterReloadServer,
    result_token: str,
    session: str,
    versions: dict[str, str],
    *,
    artifact: dict[str, object],
    capture_harness: dict[str, object],
    timeout_seconds: float,
) -> str:
    if (
        not server.session.matches_result_token(result_token)
        or not server.session.matches_session(session)
        or not isinstance(timeout_seconds, (int, float))
        or isinstance(timeout_seconds, bool)
    ):
        raise M0Error("renderer IndexedDB URL inputs are invalid")
    timeout_ms = int(float(timeout_seconds) * 1000)
    if timeout_ms < 1000 or timeout_ms > MAX_TIMEOUT_MS:
        raise M0Error("renderer IndexedDB URL timeout is invalid")
    query = urlencode(
        {
            "artifact": json.dumps(artifact, sort_keys=True, separators=(",", ":")),
            "captureHarness": json.dumps(capture_harness, sort_keys=True, separators=(",", ":")),
            "module": PRODUCT_MODULE_NAME,
            "resultToken": result_token,
            "session": session,
            "timeoutMs": str(timeout_ms),
            "versions": json.dumps(versions, sort_keys=True, separators=(",", ":")),
        }
    )
    parsed = parse_qs(query, keep_blank_values=True)
    if set(parsed) != _ROOT_QUERY_FIELDS or any(len(value) != 1 for value in parsed.values()):
        raise M0Error("renderer IndexedDB URL query is invalid")
    server.expected_root_query = {name: values[0] for name, values in parsed.items()}
    host, port = server.server_address[:2]
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


def verify_server_delivery(server: RendererIndexedDBOuterReloadServer) -> None:
    """Check the server serves only its captured in-memory static bytes."""

    host, port = server.server_address[:2]
    expected = (
        (f"{HOST_ROOT}/", server.host_html, "text/html"),
        (f"{HOST_ROOT}/{HOST_JS_NAME}", server.host_js, "text/javascript"),
        (f"{HOST_ROOT}/artifacts/{PRODUCT_MODULE_NAME}.js", server.artifacts[f"{PRODUCT_MODULE_NAME}.js"], "text/javascript"),
        (f"{HOST_ROOT}/artifacts/{PRODUCT_MODULE_NAME}.wasm", server.artifacts[f"{PRODUCT_MODULE_NAME}.wasm"], "application/wasm"),
    )
    for path, contents, content_type in expected:
        connection = http.client.HTTPConnection(host, port, timeout=10)
        try:
            connection.request("GET", path, headers={"Cache-Control": "no-store"})
            response = connection.getresponse()
            if response.status != HTTPStatus.OK:
                raise M0Error("renderer IndexedDB snapshot request failed")
            headers = {name.lower(): value for name, value in response.getheaders()}
            for name, wanted in _expected_headers(content_type).items():
                actual = headers.get(name, "")
                if name == "content-type":
                    actual = actual.split(";", 1)[0].strip().lower()
                if actual != wanted:
                    raise M0Error("renderer IndexedDB snapshot response header is invalid")
            body = response.read()
            if body != contents:
                raise M0Error("renderer IndexedDB snapshot body changed")
        finally:
            connection.close()


def _expected_token_digests(ordinal: int, escrow: TokenEscrow) -> tuple[str | None, str | None]:
    if ordinal == 1:
        return escrow.token_a_digest, None
    if ordinal == 2:
        return escrow.token_a_digest, escrow.token_b_digest
    if ordinal == 3:
        return None, escrow.token_b_digest
    raise M0Error("renderer IndexedDB token ordinal is invalid")


def _validate_run(value: object, ordinal: int, escrow: TokenEscrow) -> str:
    run = _exact_fields(value, _RUN_FIELDS, "run")
    expected = expected_markers(ordinal, escrow)
    required = {
        "abortObserved": False,
        "factoryRejected": False,
        "factoryResolved": True,
        "factorySettled": True,
        "freshLoaderImport": True,
        "freshModuleObject": True,
        "lifecycleComplete": True,
        "markerCount": len(expected),
        "markerSequenceAccepted": True,
        "markerSource": "stderr-only-fixed-renderer-database-grammar",
        "markers": expected,
        "onExitCount": 1,
        "ordinal": ordinal,
        "processExitCode": 0,
        "processExitCount": 1,
        "runtimeExitCode": 0,
        "runtimeInitialized": True,
        "stdoutMarkerCount": 0,
    }
    if any(run.get(name) != wanted for name, wanted in required.items()):
        raise M0Error("renderer IndexedDB module lifecycle is invalid")
    if (
        type(run.get("expectedCleanExitStatusObserved")) is not bool
        or type(run.get("outputLineCount")) is not int
        or run["outputLineCount"] < len(expected)
        or run["outputLineCount"] > MAX_OUTPUT_LINES
        or not isinstance(run.get("moduleIdentity"), str)
        or not MODULE_ID_RE.fullmatch(run["moduleIdentity"])
    ):
        raise M0Error("renderer IndexedDB module receipt is invalid")
    return run["moduleIdentity"]


def validate_phase_result(
    value: dict[str, Any],
    *,
    ordinal: int,
    expected_versions: dict[str, str],
    expected_artifact: dict[str, object],
    expected_capture_harness: dict[str, object],
    expected_origin: str,
    expected_document: DocumentEvidence,
    escrow: TokenEscrow,
    prohibited: tuple[str, ...],
) -> PhaseResult:
    if _contains_prohibited_strings(value, prohibited):
        raise M0Error("renderer IndexedDB receipt contains an opaque value")
    result = _exact_fields(value, _RESULT_FIELDS, "result")
    phase, mode = phase_for_ordinal(ordinal)
    fixed = {
        "case": CASE,
        "m7GateComplete": False,
        "mode": mode,
        "ordinal": ordinal,
        "origin": expected_origin,
        "phase": phase,
        "protocol": 1,
        "scope": SCOPE,
        "sharedArrayBuffer": True,
        "status": "pass",
        "versions": expected_versions,
    }
    if any(result.get(name) != wanted for name, wanted in fixed.items()):
        raise M0Error("renderer IndexedDB fixed receipt field is invalid")
    _validate_identity(result.get("artifact"), expected_artifact, "artifact")
    _validate_identity(result.get("captureHarness"), expected_capture_harness, "capture harness")
    document = _exact_fields(result.get("document"), _DOCUMENT_FIELDS, "document")
    if (
        document.get("navigationType") != expected_document.navigation_type
        or document.get("timeOrigin") != expected_document.time_origin
        or not isinstance(document.get("identity"), str)
        or not MODULE_ID_RE.fullmatch(document["identity"])
    ):
        raise M0Error("renderer IndexedDB document receipt is invalid")
    token_evidence = _exact_fields(result.get("tokenEvidence"), _TOKEN_EVIDENCE_FIELDS, "token evidence")
    expected_a, expected_b = _expected_token_digests(ordinal, escrow)
    if (
        token_evidence.get("algorithm") != "SHA-256"
        or token_evidence.get("tokenADigest") != expected_a
        or token_evidence.get("tokenBDigest") != expected_b
        or token_evidence.get("rawTokensExcluded") is not True
        or token_evidence.get("rawTokenLeakDetected") is not False
        or token_evidence.get("rawTokenRedactionCount") != 0
    ):
        raise M0Error("renderer IndexedDB token evidence is invalid")
    boundary = _exact_fields(result.get("hostBoundary"), _HOST_BOUNDARY_FIELDS, "host boundary")
    if any(boundary.get(name) is not False for name in _HOST_BOUNDARY_FIELDS):
        raise M0Error("renderer IndexedDB host crossed the storage boundary")
    bridge = _exact_fields(result.get("bridge"), _BRIDGE_FIELDS, "bridge")
    if bridge != {
        "activeAtResult": True,
        "frozen": True,
        "installedBeforeModuleFactory": True,
        "permanent": True,
        "processExitDispatches": 1,
        "protocol": 1,
    }:
        raise M0Error("renderer IndexedDB bridge receipt is invalid")
    quiescence = _exact_fields(result.get("quiescence"), _QUIESCENCE_FIELDS, "quiescence")
    if (
        quiescence.get("quiet") is not True
        or quiescence.get("quietWindowMs") != 50
        or type(quiescence.get("callbacksAtClear")) is not int
        or quiescence.get("callbacksAfterQuiescence") != quiescence.get("callbacksAtClear")
    ):
        raise M0Error("renderer IndexedDB quiescence receipt is invalid")
    return PhaseResult(
        ordinal=ordinal,
        origin=expected_origin,
        navigation_type=expected_document.navigation_type,
        time_origin=expected_document.time_origin,
        module_identity=_validate_run(result.get("run"), ordinal, escrow),
    )


def validate_ready_receipt(value: dict[str, Any], expected: PhaseResult) -> None:
    ready = _exact_fields(value, _READY_FIELDS, "ready receipt")
    if (
        ready.get("case") != CASE
        or ready.get("ordinal") != expected.ordinal
        or ready.get("protocol") != 1
        or ready.get("scope") != SCOPE
        or ready.get("timeOrigin") != expected.time_origin
    ):
        raise M0Error("renderer IndexedDB ready receipt is invalid")


def validate_outer_document_transitions(
    first: PhaseResult, second: PhaseResult, third: PhaseResult
) -> None:
    if (
        [first.ordinal, second.ordinal, third.ordinal] != [1, 2, 3]
        or len({first.origin, second.origin, third.origin}) != 1
        or [first.navigation_type, second.navigation_type, third.navigation_type]
        != ["navigate", "reload", "reload"]
        or not first.time_origin < second.time_origin < third.time_origin
        or len({first.module_identity, second.module_identity, third.module_identity}) != 3
    ):
        raise M0Error("renderer IndexedDB outer-document transition is invalid")


def _root_frame_identity(value: object) -> RootFrameIdentity:
    tree = value.get("frameTree") if isinstance(value, dict) else None
    frame = tree.get("frame") if isinstance(tree, dict) else None
    if (
        not isinstance(frame, dict)
        or "parentId" in frame
        or not isinstance(frame.get("id"), str)
        or not frame["id"]
        or not isinstance(frame.get("loaderId"), str)
        or not frame["loaderId"]
    ):
        raise M0Error("renderer IndexedDB DevTools root frame is invalid")
    return RootFrameIdentity(frame["id"], frame["loaderId"])


def prepare_outer_document_reload(client: Any) -> RootFrameIdentity:
    """Record the root frame immediately before a DevTools-only reload."""

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
        raise M0Error("renderer IndexedDB DevTools navigation event is invalid")
    if frame.get("id") != baseline.frame_id:
        return None
    if "parentId" in frame:
        raise M0Error("renderer IndexedDB DevTools root frame changed parent")
    loader_id = frame.get("loaderId")
    url = frame.get("url")
    if not isinstance(loader_id, str) or not loader_id:
        raise M0Error("renderer IndexedDB DevTools navigation loader is invalid")
    if loader_id == baseline.loader_id:
        return None
    if not isinstance(url, str) or not url.startswith(expected_page_url_prefix):
        raise M0Error("renderer IndexedDB DevTools navigation URL is invalid")
    return RootFrameIdentity(baseline.frame_id, loader_id)


def reload_outer_document(
    client: Any,
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    baseline: RootFrameIdentity,
    expected_page_url_prefix: str,
    deadline: float,
) -> RootFrameIdentity:
    """Issue only Page.reload and await a new same-root loader event."""

    client.call("Page.reload", {"ignoreCache": True})
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M0Error(
                "renderer IndexedDB DevTools reload timed out "
                f"({len(browser_stderr)} browser stderr lines suppressed)"
            )
        if browser.poll() is not None:
            raise M0Error("renderer IndexedDB browser exited before DevTools reload")
        event = client.next_event(min(0.1, remaining))
        candidate = _root_reload_event(
            event,
            baseline=baseline,
            expected_page_url_prefix=expected_page_url_prefix,
        ) if event is not None else None
        if candidate is not None:
            return candidate


def validate_cdp_root_loaders(
    first: RootFrameIdentity, second: RootFrameIdentity, third: RootFrameIdentity
) -> None:
    if (
        first.frame_id != second.frame_id
        or second.frame_id != third.frame_id
        or len({first.loader_id, second.loader_id, third.loader_id}) != 3
    ):
        raise M0Error("renderer IndexedDB DevTools loader transition is invalid")


def drain_browser_stderr(
    stream: Any,
    destination: deque[str],
    escrow: TokenEscrow,
    raw_token_seen: threading.Event,
) -> None:
    """Detect raw escrow leakage even if it crosses a stderr line boundary."""

    tail = ""
    for line in stream:
        normalized = line.rstrip()
        combined = tail + normalized
        if escrow.token_a in combined or escrow.token_b in combined:
            raw_token_seen.set()
            destination.append(SUPPRESSED_BROWSER_STDERR_TOKEN)
        else:
            destination.append(normalized)
        tail = combined[-OPAQUE_TOKEN_TAIL_CHARS:]


def _wait_for_receipt(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    server: RendererIndexedDBOuterReloadServer,
    receipts: queue.Queue[tuple[int, dict[str, Any]]],
    ordinal: int,
    deadline: float,
    kind: str,
) -> dict[str, Any]:
    while True:
        try:
            failed_ordinal = server.failure_queue.get_nowait()
        except queue.Empty:
            failed_ordinal = None
        if failed_ordinal is not None:
            raise M0Error(f"renderer IndexedDB host reported failure for phase {failed_ordinal}")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M0Error(f"renderer IndexedDB {kind} timed out")
        try:
            actual, value = receipts.get(timeout=min(0.1, remaining))
        except queue.Empty:
            if browser.poll() is not None:
                raise M0Error(f"renderer IndexedDB browser exited before {kind}")
            continue
        if actual != ordinal:
            raise M0Error("renderer IndexedDB receipt order is invalid")
        return value


def wait_for_phase_result(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    server: RendererIndexedDBOuterReloadServer,
    ordinal: int,
    deadline: float,
) -> dict[str, Any]:
    return _wait_for_receipt(browser, browser_stderr, server, server.result_queue, ordinal, deadline, "result")


def wait_for_ready_receipt(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    server: RendererIndexedDBOuterReloadServer,
    ordinal: int,
    deadline: float,
) -> dict[str, Any]:
    return _wait_for_receipt(browser, browser_stderr, server, server.ready_queue, ordinal, deadline, "ready receipt")


def _stop_server(
    server: RendererIndexedDBOuterReloadServer | None,
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
            raise M0Error("renderer IndexedDB server did not stop")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run three renderer IndexedDB modules separated by two DevTools Page.reload calls.",
        epilog=(
            "Build with: buildtools/linux64/gn gen "
            f"{DEFAULT_OUT_DIR} --args='{DEFAULT_GN_ARGUMENTS}' --fail-on-unused-args; "
            f"autoninja -C {DEFAULT_OUT_DIR} chrome_wasm"
        ),
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--timeout", type=parse_timeout, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args()

    browser: subprocess.Popen[str] | None = None
    browser_stderr: deque[str] = deque(maxlen=MAX_BROWSER_STDERR_LINES)
    raw_token_seen = threading.Event()
    stderr_thread: threading.Thread | None = None
    client: Any | None = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    server: RendererIndexedDBOuterReloadServer | None = None
    server_thread: threading.Thread | None = None
    server_started = False
    stage = "initialize"
    succeeded = False
    try:
        stage = "load-manifest"
        versions = toolchain_manifest_versions(load_manifest())
        stage = "create-escrow"
        result_token, session = new_capability_pair()
        escrow = new_token_escrow()
        out_dir = args.out_dir if args.out_dir.is_absolute() else REPO_ROOT / args.out_dir
        stage = "create-server"
        server = create_server("127.0.0.1", 0, out_dir, result_token, session, escrow)
        artifact = artifact_identity(server)
        harness = capture_harness_identity(server)
        server_thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.05},
            name="chromium-wasm-m7-renderer-indexed-db-outer-reload-server",
            daemon=True,
        )
        server_thread.start()
        server_started = True
        stage = "verify-server-delivery"
        verify_server_delivery(server)
        url = smoke_url(
            server,
            result_token,
            session,
            versions,
            artifact=artifact,
            capture_harness=harness,
            timeout_seconds=args.timeout,
        )
        origin = f"http://{server.server_address[0]}:{server.server_address[1]}"
        stage = "find-browser"
        browser_path, _ = find_browser(args.browser)
        profile = tempfile.TemporaryDirectory(prefix="chromium-wasm-m7-renderer-indexed-db-")
        debug_port = unused_loopback_port()
        stage = "launch-browser"
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
            target=drain_browser_stderr,
            args=(browser.stderr, browser_stderr, escrow, raw_token_seen),
            name="chromium-wasm-m7-renderer-indexed-db-browser-stderr",
            daemon=True,
        )
        stderr_thread.start()
        deadline = time.monotonic() + args.timeout
        expected_page_url_prefix = url.split("?", 1)[0]

        stage = "connect-devtools-phase-one"
        client = wait_for_page_client(debug_port, expected_page_url_prefix, deadline)
        stage = "phase-one-result"
        first = validate_phase_result(
            wait_for_phase_result(browser, browser_stderr, server, 1, deadline),
            ordinal=1,
            expected_versions=versions,
            expected_artifact=artifact,
            expected_capture_harness=harness,
            expected_origin=origin,
            expected_document=server.session.document_evidence(1),
            escrow=escrow,
            prohibited=server.session.prohibited_values(),
        )
        stage = "phase-one-ready"
        validate_ready_receipt(wait_for_ready_receipt(browser, browser_stderr, server, 1, deadline), first)
        first_root = prepare_outer_document_reload(client)
        server.session.arm_next_reload(1, first.time_origin)

        stage = "reload-phase-two"
        second_root = reload_outer_document(client, browser, browser_stderr, first_root, expected_page_url_prefix, deadline)
        stage = "phase-two-result"
        second = validate_phase_result(
            wait_for_phase_result(browser, browser_stderr, server, 2, deadline),
            ordinal=2,
            expected_versions=versions,
            expected_artifact=artifact,
            expected_capture_harness=harness,
            expected_origin=origin,
            expected_document=server.session.document_evidence(2),
            escrow=escrow,
            prohibited=server.session.prohibited_values(),
        )
        stage = "phase-two-ready"
        validate_ready_receipt(wait_for_ready_receipt(browser, browser_stderr, server, 2, deadline), second)
        current_root = prepare_outer_document_reload(client)
        if current_root != second_root:
            raise M0Error("renderer IndexedDB phase-two root changed before phase three")
        server.session.arm_next_reload(2, second.time_origin)

        stage = "reload-phase-three"
        third_root = reload_outer_document(client, browser, browser_stderr, current_root, expected_page_url_prefix, deadline)
        stage = "phase-three-result"
        third = validate_phase_result(
            wait_for_phase_result(browser, browser_stderr, server, 3, deadline),
            ordinal=3,
            expected_versions=versions,
            expected_artifact=artifact,
            expected_capture_harness=harness,
            expected_origin=origin,
            expected_document=server.session.document_evidence(3),
            escrow=escrow,
            prohibited=server.session.prohibited_values(),
        )
        stage = "phase-three-ready"
        validate_ready_receipt(wait_for_ready_receipt(browser, browser_stderr, server, 3, deadline), third)
        validate_outer_document_transitions(first, second, third)
        validate_cdp_root_loaders(first_root, second_root, third_root)
        if raw_token_seen.is_set():
            raise M0Error("renderer IndexedDB raw token reached browser stderr")
        succeeded = True
    except Exception:
        print(f"{SENTINEL}:FAIL stage={stage}", file=sys.stderr, flush=True)
    finally:
        if client is not None:
            client.close()
        if browser is not None:
            stop_browser(browser)
        if stderr_thread is not None:
            stderr_thread.join(timeout=3)
        try:
            _stop_server(server, server_thread, server_started)
        except M0Error:
            succeeded = False
        if profile is not None:
            profile.cleanup()
    if raw_token_seen.is_set():
        succeeded = False
    if not succeeded:
        return 1
    print(
        f"{SENTINEL}:PASS modules=3 outer_page_reloads=2 "
        "m7_gate_complete=false",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
