#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Prove the M7 database failure path retires its OPFS backend fail-closed.

The page launches exactly one fresh instance of the ordinary, source-selected
M7 database artifact in ``verify-b`` mode.  The runner supplies a random
token that no module has written, so the first SQLite read deterministically
fails.  A passing receipt requires the fixed database failure, the exact
sealed/lease-retained retirement marker, one nonzero clean process exit, one
matching ``onExit`` callback, no abort, no ``LEASE_RELEASED`` marker, and a
quiet callback window.  It is a failure-path lifecycle proof only: it does
not establish database durability, physical crash recovery, cross-document
lease exclusion, or normal Chromium profile persistence.

The raw token lives only in the runner's one-use bootstrap response and the
module's command line.  It is excluded from URLs, receipts, diagnostics, and
browser output retained by this runner.
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
from urllib.parse import urlencode, urlsplit

from m0_common import M0Error, REPO_ROOT, load_manifest
from m9_descriptor_snapshot import snapshot_regular_file, snapshot_regular_files
from run_browser_smoke import browser_command, drain_stream, find_browser, stop_browser


SENTINEL = "CHROMIUM_WASM_M7_CHROME_PROFILE_DATABASE_FAIL_CLOSED_RETIREMENT_DOM"
CASE = "chrome_profile_database_fail_closed_retirement_m7"
SCOPE = (
    "same-origin-same-document-one-fresh-chrome-wasm-m7-profile-database-"
    "verify-b-never-written-token-fail-closed-retirement"
)
PRODUCT_MODULE_NAME = "chrome_wasm_m7_profile_database_test"
PRODUCT_GN_TARGET = "//chrome:chrome_wasm"
PRODUCT_GN_ENABLE_ARGUMENT = "enable_chromium_wasm_m7_profile_database_test=true"
DEFAULT_OUT_DIR = Path("out/wasm-chrome-m7-profile-database")
DEFAULT_GN_ARGUMENTS = (
    'import("//out/wasm-chrome-m6/args.gn") ' + PRODUCT_GN_ENABLE_ARGUMENT
)
HOST_ROOT = "/__m7_chrome_profile_database_fail_closed_retirement__"
HOST_HTML_NAME = "chrome_wasm_profile_database_fail_closed_retirement_smoke.html"
HOST_JS_NAME = "chrome_wasm_profile_database_fail_closed_retirement_smoke.js"

M7_DATABASE_MARKER_PREFIX = "CHROMIUM_WASM_M7_DATABASE:"
FAILURE_RETIREMENT_MARKER = (
    "CHROMIUM_WASM_M7_PROFILE_FAILURE_RETIREMENT:SEALED_LEASE_RETAINED"
)
EXPECTED_DATABASE_MARKERS = (
    f"{M7_DATABASE_MARKER_PREFIX}READY",
    f"{M7_DATABASE_MARKER_PREFIX}FAIL stage=database",
)
EXPECTED_DATABASE_PHASES = ("task-post", "task-started", "sqlite-read", "task-complete")

MAX_RESULT_BYTES = 256 * 1024
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024 * 1024
MAX_OUTPUT_LINES = 128
MAX_BROWSER_STDERR_LINES = 300
MIN_TIMEOUT_SECONDS = 20.0
MAX_TIMEOUT_MS = 300_000
FINAL_QUIESCENCE_MS = 50

ARTIFACT_DELIVERY = "immutable-in-memory-server-snapshot"
ARTIFACT_SOURCE_PROVENANCE = "unverified"
BUILD_CONFIG_PROVENANCE = "selected-out-dir-args-gn-immutable-snapshot"
SOURCE_SNAPSHOT_PROVENANCE = (
    "on-disk-byte-snapshots-at-server-startup-not-commit-provenance"
)
VERSION_PROVENANCE = "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance"

CAPABILITY_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
GIT_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MODULE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
M7_DATABASE_GN_ENABLE_ASSIGNMENT_RE = re.compile(
    r"^[ \t]*enable_chromium_wasm_m7_profile_database_test[ \t]*="
    r"[ \t]*(true|false)[ \t]*(?:#.*)?$",
    re.MULTILINE,
)
_INCOMPATIBLE_GN_ENABLE_ASSIGNMENT_RES = (
    re.compile(
        r"^[ \t]*enable_chromium_wasm_m7_profile_database_lock_test[ \t]*="
        r"[ \t]*(true|false)[ \t]*(?:#.*)?$",
        re.MULTILINE,
    ),
    re.compile(
        r"^[ \t]*enable_chromium_wasm_m7_profile_database_abort_pc_diagnostic[ \t]*="
        r"[ \t]*(true|false)[ \t]*(?:#.*)?$",
        re.MULTILINE,
    ),
    re.compile(
        r"^[ \t]*enable_chromium_wasm_m7_profile_database_write_interruption_diagnostic[ \t]*="
        r"[ \t]*(true|false)[ \t]*(?:#.*)?$",
        re.MULTILINE,
    ),
    re.compile(
        r"^[ \t]*enable_chromium_wasm_m7_profile_database_recovery_test[ \t]*="
        r"[ \t]*(true|false)[ \t]*(?:#.*)?$",
        re.MULTILINE,
    ),
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
_TOKEN_EVIDENCE_FIELDS = frozenset(
    (
        "algorithm",
        "tokenB",
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
        "abortObserved",
        "databaseFailureMarkerObserved",
        "factoryRejectedExpectedExitStatus",
        "factoryRejectedUnexpected",
        "factoryResolved",
        "factorySettled",
        "leaseReleasedMarkerObserved",
        "markerCount",
        "markerSequenceAccepted",
        "markerSource",
        "markers",
        "mode",
        "moduleIdentity",
        "onExitCount",
        "outputLineCount",
        "phaseCount",
        "phases",
        "processExitCode",
        "processExitCount",
        "retirementMarkerCount",
        "retirementMarkerObserved",
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
    )
)
_FINAL_QUIESCENCE_FIELDS = frozenset(
    (
        "callbacksAtEnd",
        "callbacksAtPreUploadCheck",
        "callbacksAtStart",
        "completed",
        "quiet",
        "quietWindowMs",
        "started",
    )
)
_RESULT_FIELDS = frozenset(
    (
        "protocol",
        "case",
        "scope",
        "status",
        "m7GateComplete",
        "origin",
        "crossOriginIsolated",
        "sharedArrayBuffer",
        "artifact",
        "capture_harness",
        "versions",
        "tokenEvidence",
        "fixedDatabaseFailureObserved",
        "sealedLeaseRetainedReceiptObserved",
        "cleanNonzeroProcessExitObserved",
        "normalProfilePersistenceProven",
        "hostBoundary",
        "run",
        "bridge",
        "finalQuiescence",
        "fatalCallbackCount",
        "windowErrorCount",
        "unhandledRejectionCount",
        "error",
    )
)


@dataclass(frozen=True)
class TokenEscrow:
    """A never-written opaque database token excluded from output."""

    token_b: str = field(repr=False)
    token_b_digest: str


class ProtocolStateError(M0Error):
    """A one-use bootstrap or result state conflict."""


class FailClosedRetirementSession:
    """One bootstrap and one receipt, both guarded by opaque capabilities."""

    def __init__(self, result_token: str, session: str, escrow: TokenEscrow):
        if (
            not CAPABILITY_RE.fullmatch(result_token)
            or not CAPABILITY_RE.fullmatch(session)
            or result_token == session
            or not SHA256_RE.fullmatch(escrow.token_b)
            or escrow.token_b_digest != _sha256_text(escrow.token_b)
        ):
            raise M0Error("fail-closed retirement escrow is invalid")
        self._result_token = result_token
        self._session = session
        self._escrow = escrow
        self._bootstrap_served = False
        self._result_accepted = False
        self._lock = threading.Lock()

    @property
    def escrow(self) -> TokenEscrow:
        return self._escrow

    def matches_result_token(self, value: str | None) -> bool:
        return isinstance(value, str) and secrets.compare_digest(value, self._result_token)

    def matches_session(self, value: str | None) -> bool:
        return isinstance(value, str) and secrets.compare_digest(value, self._session)

    def bootstrap_payload(self, session: str) -> dict[str, object] | None:
        if not self.matches_session(session):
            return None
        with self._lock:
            if self._bootstrap_served:
                raise ProtocolStateError("fail-closed retirement bootstrap was already served")
            self._bootstrap_served = True
            return {
                "protocol": 1,
                "case": CASE,
                "scope": SCOPE,
                "tokenB": self._escrow.token_b,
                "tokenBDigest": self._escrow.token_b_digest,
            }

    def accept_result(self, result_token: str) -> bool:
        if not self.matches_result_token(result_token):
            return False
        with self._lock:
            if not self._bootstrap_served or self._result_accepted:
                raise ProtocolStateError("fail-closed retirement result state conflict")
            self._result_accepted = True
            return True


class ChromeProfileDatabaseFailClosedRetirementServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    args_gn: bytes
    artifacts: dict[str, bytes]
    host_html: bytes
    host_js: bytes
    module_name: str
    receipt_lock: threading.Lock
    result_queue: queue.Queue[dict[str, Any]]
    runner_source: bytes
    session: FailClosedRetirementSession

    def handle_error(self, _request: object, _client_address: object) -> None:
        # Standard server errors include request URLs, which may carry a bearer
        # capability.  This harness intentionally keeps them silent.
        return


class ChromeProfileDatabaseFailClosedRetirementRequestHandler(BaseHTTPRequestHandler):
    server: ChromeProfileDatabaseFailClosedRetirementServer

    def log_message(self, _format: str, *_args: object) -> None:
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
        self._send_bytes(HTTPStatus.CONFLICT, "text/plain; charset=utf-8", b"state conflict\n")

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
            value, (self.server.session.escrow.token_b,)
        ):
            return None
        return value

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path
        if path in (HOST_ROOT, f"{HOST_ROOT}/"):
            self._send_bytes(HTTPStatus.OK, "text/html; charset=utf-8", self.server.host_html)
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
                    "application/wasm" if name.endswith(".wasm") else "text/javascript; charset=utf-8",
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
    def _result_path(path: str) -> str | None:
        prefix = f"{HOST_ROOT}/result/"
        if not path.startswith(prefix):
            return None
        token = path[len(prefix) :]
        if "/" in token or not CAPABILITY_RE.fullmatch(token):
            return None
        return token

    def do_POST(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.query:
            self._not_found()
            return
        result_token = self._result_path(parsed.path)
        if result_token is None or not self.server.session.matches_result_token(result_token):
            self._not_found()
            return
        value = self._read_json_body(MAX_RESULT_BYTES)
        if value is None or not _is_receipt_identity(value):
            self._send_bytes(
                HTTPStatus.BAD_REQUEST,
                "text/plain; charset=utf-8",
                b"invalid fail-closed retirement result\n",
            )
            return
        with self.server.receipt_lock:
            if self.server.result_queue.full():
                self._conflict()
                return
            try:
                accepted = self.server.session.accept_result(result_token)
            except ProtocolStateError:
                self._conflict()
                return
            if not accepted:
                self._not_found()
                return
            self.server.result_queue.put_nowait(value)
        self._send_empty(HTTPStatus.NO_CONTENT)


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


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def new_token_escrow() -> TokenEscrow:
    token_b = secrets.token_hex(32)
    return TokenEscrow(token_b=token_b, token_b_digest=_sha256_text(token_b))


def new_capability_pair() -> tuple[str, str]:
    result_token = secrets.token_urlsafe(24)
    session = secrets.token_urlsafe(24)
    while session == result_token:
        session = secrets.token_urlsafe(24)
    if not CAPABILITY_RE.fullmatch(result_token) or not CAPABILITY_RE.fullmatch(session):
        raise M0Error("fail-closed retirement capability generation is invalid")
    return result_token, session


def _is_receipt_identity(value: dict[str, Any]) -> bool:
    return (
        type(value.get("protocol")) is int
        and value.get("protocol") == 1
        and value.get("case") == CASE
        and value.get("scope") == SCOPE
        and value.get("m7GateComplete") is False
    )


def validate_m7_output_configuration(args_gn: bytes) -> None:
    """Require the ordinary database artifact and reject diagnostic variants."""

    try:
        text = args_gn.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError as exc:
        raise M0Error("fail-closed retirement args.gn is not UTF-8") from exc
    database_values = M7_DATABASE_GN_ENABLE_ASSIGNMENT_RE.findall(text)
    if not database_values or any(value != "true" for value in database_values):
        raise M0Error("fail-closed retirement args.gn lacks the database test opt-in")
    if any(
        value == "true"
        for expression in _INCOMPATIBLE_GN_ENABLE_ASSIGNMENT_RES
        for value in expression.findall(text)
    ):
        raise M0Error("fail-closed retirement args.gn enables an incompatible diagnostic")


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
) -> ChromeProfileDatabaseFailClosedRetirementServer:
    """Snapshot every served input before accepting any browser request."""

    if module_name != PRODUCT_MODULE_NAME:
        raise M0Error("fail-closed retirement module is invalid")
    artifacts = snapshot_regular_files(
        out_dir,
        (f"{module_name}.js", f"{module_name}.wasm"),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="fail-closed retirement database artifacts",
    )
    args_gn = snapshot_regular_file(
        out_dir / "args.gn",
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="fail-closed retirement selected args.gn",
    )
    validate_m7_output_configuration(args_gn)
    selected_host_dir = host_dir or Path(__file__).with_name("host")
    host_snapshots = snapshot_regular_files(
        selected_host_dir,
        (HOST_HTML_NAME, HOST_JS_NAME),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="fail-closed retirement host resources",
    )
    runner_source = snapshot_regular_file(
        runner_source_path or Path(__file__),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="fail-closed retirement runner source",
    )
    server = ChromeProfileDatabaseFailClosedRetirementServer(
        (host, port), ChromeProfileDatabaseFailClosedRetirementRequestHandler
    )
    server.args_gn = args_gn
    server.artifacts = artifacts
    server.host_html = host_snapshots[HOST_HTML_NAME]
    server.host_js = host_snapshots[HOST_JS_NAME]
    server.module_name = module_name
    server.receipt_lock = threading.Lock()
    server.result_queue = queue.Queue(maxsize=1)
    server.runner_source = runner_source
    server.session = FailClosedRetirementSession(result_token, session, escrow)
    return server


def _byte_identity(contents: bytes) -> dict[str, object]:
    return {"bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}


def artifact_identity(
    server: ChromeProfileDatabaseFailClosedRetirementServer,
) -> dict[str, object]:
    if server.module_name != PRODUCT_MODULE_NAME:
        raise M0Error("fail-closed retirement artifact module is invalid")
    return {
        "artifact_delivery": ARTIFACT_DELIVERY,
        "artifact_source_provenance": ARTIFACT_SOURCE_PROVENANCE,
        "build_config": _byte_identity(server.args_gn),
        "build_config_provenance": BUILD_CONFIG_PROVENANCE,
        "loader": _byte_identity(server.artifacts[f"{server.module_name}.js"]),
        "module_name": server.module_name,
        "wasm": _byte_identity(server.artifacts[f"{server.module_name}.wasm"]),
    }


def capture_harness_identity(
    server: ChromeProfileDatabaseFailClosedRetirementServer,
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
        raise M0Error("fail-closed retirement manifest lacks version metadata") from exc
    if not all(
        isinstance(value, str) and GIT_REVISION_RE.fullmatch(value)
        for value in versions.values()
    ):
        raise M0Error("fail-closed retirement manifest version metadata is invalid")
    return versions


def smoke_url(
    server: ChromeProfileDatabaseFailClosedRetirementServer,
    result_token: str,
    session: str,
    versions: dict[str, str],
    *,
    artifact: dict[str, object],
    capture_harness: dict[str, object],
    timeout_seconds: float,
) -> str:
    """Construct a host URL which deliberately contains no raw database token."""

    if (
        server.module_name != PRODUCT_MODULE_NAME
        or not server.session.matches_result_token(result_token)
        or not server.session.matches_session(session)
        or not isinstance(timeout_seconds, (int, float))
        or isinstance(timeout_seconds, bool)
    ):
        raise M0Error("fail-closed retirement URL state is invalid")
    timeout_ms = int(float(timeout_seconds) * 1000)
    if timeout_ms < int(MIN_TIMEOUT_SECONDS * 1000) or timeout_ms > MAX_TIMEOUT_MS:
        raise M0Error("fail-closed retirement URL timeout is invalid")
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "resultToken": result_token,
            "session": session,
            "module": server.module_name,
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
        raise M0Error(f"fail-closed retirement {name} schema is invalid")
    return value


def _require_equal(value: dict[str, Any], field: str, expected: object) -> None:
    if type(value.get(field)) is not type(expected) or value.get(field) != expected:
        raise M0Error(f"fail-closed retirement result {field} is invalid")


def _validate_byte_identity(value: object, description: str) -> None:
    identity = _require_exact_fields(value, _BYTE_IDENTITY_FIELDS, description)
    if (
        type(identity.get("bytes")) is not int
        or identity["bytes"] < 1
        or not isinstance(identity.get("sha256"), str)
        or not SHA256_RE.fullmatch(identity["sha256"])
    ):
        raise M0Error(f"fail-closed retirement {description} is invalid")


def _validate_artifact_identity(value: object, expected: dict[str, object]) -> None:
    artifact = _require_exact_fields(value, _ARTIFACT_FIELDS, "artifact")
    for field in ("build_config", "loader", "wasm"):
        _validate_byte_identity(artifact.get(field), f"artifact {field}")
    if artifact != expected:
        raise M0Error("fail-closed retirement artifact identity is invalid")


def _validate_capture_harness_identity(value: object, expected: dict[str, object]) -> None:
    harness = _require_exact_fields(value, _CAPTURE_HARNESS_FIELDS, "capture harness")
    for field in ("host_html", "host_js", "runner_source"):
        _validate_byte_identity(harness.get(field), f"capture harness {field}")
    if harness != expected:
        raise M0Error("fail-closed retirement capture harness identity is invalid")


def _validate_token_evidence(value: object, escrow: TokenEscrow) -> None:
    token_evidence = _require_exact_fields(value, _TOKEN_EVIDENCE_FIELDS, "token evidence")
    if (
        token_evidence.get("algorithm") != "SHA-256"
        or token_evidence.get("tokenB") != escrow.token_b_digest
        or token_evidence.get("rawTokensExcluded") is not True
        or token_evidence.get("rawTokenLeakDetected") is not False
        or token_evidence.get("rawTokenRedactionCount") != 0
    ):
        raise M0Error("fail-closed retirement token evidence is invalid")


def _validate_run(value: object) -> None:
    run = _require_exact_fields(value, _RUN_FIELDS, "run")
    process_exit = run.get("processExitCode")
    if (
        run.get("mode") != "verify-b"
        or not isinstance(run.get("moduleIdentity"), str)
        or not MODULE_ID_RE.fullmatch(run["moduleIdentity"])
        or run.get("runtimeInitialized") is not True
        or run.get("factorySettled") is not True
        or type(run.get("factoryResolved")) is not bool
        or type(run.get("factoryRejectedExpectedExitStatus")) is not bool
        or run.get("factoryRejectedUnexpected") is not False
        or (run["factoryResolved"] == run["factoryRejectedExpectedExitStatus"])
        or run.get("abortObserved") is not False
        or run.get("processExitCount") != 1
        or type(process_exit) is not int
        or process_exit <= 0
        or process_exit > 255
        or run.get("onExitCount") != 1
        or run.get("runtimeExitCode") != process_exit
        or run.get("markerSource") != "stderr-only-fixed-grammar"
        or run.get("markerSequenceAccepted") is not True
        or run.get("markers") != list(EXPECTED_DATABASE_MARKERS)
        or run.get("markerCount") != len(EXPECTED_DATABASE_MARKERS)
        or run.get("databaseFailureMarkerObserved") is not True
        or run.get("phases") != list(EXPECTED_DATABASE_PHASES)
        or run.get("phaseCount") != len(EXPECTED_DATABASE_PHASES)
        or run.get("retirementMarkerObserved") is not True
        or run.get("retirementMarkerCount") != 1
        or run.get("leaseReleasedMarkerObserved") is not False
        or run.get("stdoutMarkerCount") != 0
        or type(run.get("outputLineCount")) is not int
        or run["outputLineCount"] < len(EXPECTED_DATABASE_MARKERS)
        or run["outputLineCount"] > MAX_OUTPUT_LINES
    ):
        raise M0Error("fail-closed retirement run receipt is invalid")


def _validate_bridge(value: object) -> None:
    bridge = _require_exact_fields(value, _BRIDGE_FIELDS, "bridge")
    if (
        bridge.get("protocol") != 1
        or bridge.get("permanent") is not True
        or bridge.get("frozen") is not True
        or bridge.get("installedBeforeModuleFactory") is not True
        or bridge.get("processExitDispatches") != 1
    ):
        raise M0Error("fail-closed retirement bridge receipt is invalid")


def _validate_final_quiescence(value: object) -> None:
    quiescence = _require_exact_fields(value, _FINAL_QUIESCENCE_FIELDS, "final quiescence")
    callback_fields = (
        "callbacksAtStart",
        "callbacksAtEnd",
        "callbacksAtPreUploadCheck",
    )
    if (
        quiescence.get("started") is not True
        or quiescence.get("completed") is not True
        or quiescence.get("quiet") is not True
        or quiescence.get("quietWindowMs") != FINAL_QUIESCENCE_MS
        or any(
            type(quiescence.get(field)) is not int or quiescence[field] < 0
            for field in callback_fields
        )
        or len({quiescence[field] for field in callback_fields}) != 1
    ):
        raise M0Error("fail-closed retirement callbacks were not quiet")


def _validate_host_boundary(value: object) -> None:
    boundary = _require_exact_fields(value, _HOST_BOUNDARY_FIELDS, "host boundary")
    if any(field_value is not False for field_value in boundary.values()):
        raise M0Error("fail-closed retirement host crossed a prohibited boundary")


def validate_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
    expected_artifact_identity: dict[str, object],
    expected_capture_harness_identity: dict[str, object],
    expected_origin: str,
    escrow: TokenEscrow,
    result_token: str,
    session: str,
) -> None:
    """Accept only the expected failed database and clean retained-lease exit."""

    if _contains_prohibited_strings(result, (escrow.token_b, result_token, session)):
        raise M0Error("fail-closed retirement receipt contains an opaque value")
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
        "fixedDatabaseFailureObserved": True,
        "sealedLeaseRetainedReceiptObserved": True,
        "cleanNonzeroProcessExitObserved": True,
        "normalProfilePersistenceProven": False,
        "fatalCallbackCount": 0,
        "windowErrorCount": 0,
        "unhandledRejectionCount": 0,
        "error": None,
    }.items():
        _require_equal(result, field, expected)
    _require_equal(result, "versions", expected_versions)
    _validate_artifact_identity(result.get("artifact"), expected_artifact_identity)
    _validate_capture_harness_identity(
        result.get("capture_harness"), expected_capture_harness_identity
    )
    _validate_token_evidence(result.get("tokenEvidence"), escrow)
    _validate_run(result.get("run"))
    _validate_bridge(result.get("bridge"))
    _validate_final_quiescence(result.get("finalQuiescence"))
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


def verify_server_delivery(server: ChromeProfileDatabaseFailClosedRetirementServer) -> None:
    """Verify served non-secret inputs are immutable snapshots with COOP/COEP."""

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
                raise M0Error("fail-closed retirement snapshot request failed")
            headers = {key.lower(): value for key, value in response.getheaders()}
            for name, expected_value in _expected_headers(content_type).items():
                actual = headers.get(name, "")
                if name == "content-type":
                    actual = actual.split(";", 1)[0].strip().lower()
                if actual != expected_value:
                    raise M0Error("fail-closed retirement snapshot response header is invalid")
            count, digest = _stream_response_digest(response)
            if count != len(contents) or digest != hashlib.sha256(contents).hexdigest():
                raise M0Error("fail-closed retirement snapshot body changed")
        finally:
            connection.close()


def wait_for_result(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    server: ChromeProfileDatabaseFailClosedRetirementServer,
    deadline: float,
) -> dict[str, Any]:
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M0Error(
                "fail-closed retirement result timed out "
                f"({len(browser_stderr)} browser stderr lines suppressed)"
            )
        try:
            return server.result_queue.get(timeout=min(0.1, remaining))
        except queue.Empty:
            if browser.poll() is not None:
                raise M0Error(
                    "fail-closed retirement browser exited before result "
                    f"({len(browser_stderr)} browser stderr lines suppressed)"
                )


def write_failure_diagnostics(
    diagnostics_dir: Path,
    *,
    stage: str,
    error: Exception,
    browser: subprocess.Popen[str] | None,
    browser_stderr: deque[str],
) -> Path:
    """Write only fixed local failure state, never raw token-bearing values."""

    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / "chrome-profile-database-fail-closed-retirement-m7-failure.json"
    payload = {
        "schema_version": 1,
        "runner": "run_m7_chrome_profile_database_fail_closed_retirement_dom_smoke.py",
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
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return path


def _stop_server(
    server: ChromeProfileDatabaseFailClosedRetirementServer | None,
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
            raise M0Error("fail-closed retirement server did not stop")


def failure_retirement_summary() -> dict[str, object]:
    """Report the narrow lifecycle claim without promoting M7 completion."""

    return {
        "case": CASE,
        "fixedDatabaseFailureObserved": True,
        "sealedLeaseRetainedReceiptObserved": True,
        "cleanNonzeroProcessExitObserved": True,
        "noLeaseReleaseMarkerObserved": True,
        "crossDocumentLeaseExclusionProven": False,
        "databaseDurabilityProven": False,
        "physicalCrashBehaviorProven": False,
        "normalProfilePersistenceProven": False,
        "m7GateComplete": False,
    }


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
            "timeout must be finite and in "
            f"[{MIN_TIMEOUT_SECONDS:g}, {MAX_TIMEOUT_MS / 1000:g}]"
        )
    return timeout


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prove a fresh never-written database verify-b path seals and "
            "retains its M7 OPFS profile lease before a clean nonzero exit."
        ),
        epilog=(
            "Build the ordinary database artifact with: buildtools/linux64/gn gen "
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
    parser.add_argument("--timeout", type=parse_timeout, default=120.0)
    args = parser.parse_args()

    browser: subprocess.Popen[str] | None = None
    browser_stderr: deque[str] = deque(maxlen=MAX_BROWSER_STDERR_LINES)
    browser_stderr_thread: threading.Thread | None = None
    outer_profile: tempfile.TemporaryDirectory[str] | None = None
    server: ChromeProfileDatabaseFailClosedRetirementServer | None = None
    server_thread: threading.Thread | None = None
    server_thread_started = False
    stage = "initialize"
    summary: dict[str, object] | None = None

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
            name="chromium-wasm-m7-profile-database-fail-closed-retirement-server",
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
            prefix="chromium-wasm-m7-profile-database-fail-closed-retirement-"
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
            name="chromium-wasm-m7-profile-database-fail-closed-retirement-browser-stderr",
            daemon=True,
        )
        browser_stderr_thread.start()
        deadline = time.monotonic() + args.timeout
        stage = "wait-result"
        result = wait_for_result(browser, browser_stderr, server, deadline)
        stage = "validate-result"
        validate_result(
            result,
            expected_versions=versions,
            expected_artifact_identity=artifact,
            expected_capture_harness_identity=capture_harness,
            expected_origin=expected_origin,
            escrow=escrow,
            result_token=result_token,
            session=session,
        )
        summary = failure_retirement_summary()
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
