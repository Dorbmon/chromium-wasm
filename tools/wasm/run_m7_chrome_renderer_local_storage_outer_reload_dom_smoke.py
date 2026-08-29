#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the two-outer-document renderer LocalStorage close/reopen witness.

Document one launches the source-selected renderer path in the isolated M7
LocalStorage artifact with
``renderer-write``. Chromium creates a real transient WebContents at its
dedicated test Chrome origin; that page's *external* script writes through
``window.localStorage``. Only after Chromium reports its map-update snapshot,
owner destruction, close fence, and profile drain does the first host document
post a redacted receipt. The runner then issues the second document URL. That
new outer document receives a separately escrowed bootstrap and launches a
fresh module with ``renderer-verify``. Its external script must reopen the
same value through Blink before the identical close fence completes.

The host never reads OPFS, Web Locks, DOM storage, native exports, or Wasm
memory. The runner snapshots the selected artifacts and harness inputs before
serving them. This proves an orderly renderer-owned LocalStorage handoff for
one test Chrome origin only. It does not claim normal-profile persistence,
other StoragePartition services, crash/power-loss recovery, or directory
durability.

Build the isolated M7 LocalStorage artifact first:

  buildtools/linux64/gn gen out/wasm-chrome-m7-default-partition-local-storage \\
      --args='import("//out/wasm-chrome-m6/args.gn") \\
      enable_chromium_wasm_m7_default_partition_local_storage_test=true' \\
      --fail-on-unused-args
  autoninja -C out/wasm-chrome-m7-default-partition-local-storage chrome_wasm
"""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass, field
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
from m9_descriptor_snapshot import snapshot_regular_file, snapshot_regular_files
from run_browser_smoke import browser_command, drain_stream, find_browser, stop_browser


SENTINEL = "CHROMIUM_WASM_M7_RENDERER_LOCAL_STORAGE_OUTER_RELOAD_DOM"
CASE = "chrome_renderer_local_storage_two_outer_document_reload_m7"
SCOPE = (
    "same-origin-two-outer-documents-chrome-wasm-m7-renderer-local-storage-"
    "test-modules-orderly-close-reopen-test-chrome-origin-only"
)
PRODUCT_MODULE_NAME = "chrome_wasm_m7_default_partition_local_storage_test"
PRODUCT_GN_TARGET = "//chrome:chrome_wasm"
PRODUCT_GN_ENABLE_ARGUMENT = (
    "enable_chromium_wasm_m7_default_partition_local_storage_test=true"
)
DEFAULT_OUT_DIR = Path("out/wasm-chrome-m7-default-partition-local-storage")
DEFAULT_GN_ARGUMENTS = (
    'import("//out/wasm-chrome-m6/args.gn") '
    + PRODUCT_GN_ENABLE_ARGUMENT
)
HOST_ROOT = "/__m7_renderer_local_storage_outer_reload__"
HOST_HTML_NAME = "chrome_wasm_renderer_local_storage_outer_reload_smoke.html"
HOST_JS_NAME = "chrome_wasm_renderer_local_storage_outer_reload_smoke.js"
M7_MARKER_PREFIX = "CHROMIUM_WASM_M7_LOCAL_STORAGE:"
BUILD_CONFIG_PROVENANCE = "selected-out-dir-args-gn-immutable-snapshot"
ARTIFACT_DELIVERY = "immutable-in-memory-server-snapshot"
ARTIFACT_SOURCE_PROVENANCE = "unverified"
SOURCE_SNAPSHOT_PROVENANCE = (
    "on-disk-byte-snapshots-at-server-startup-not-commit-provenance"
)
VERSION_PROVENANCE = (
    "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance"
)
MAX_RESULT_BYTES = 512 * 1024
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024 * 1024
MAX_BROWSER_STDERR_LINES = 300
MAX_OUTPUT_LINES = 128
QUIESCENCE_MS = 50
MIN_TIMEOUT_SECONDS = 20.0
MAX_TIMEOUT_MS = 300_000

CAPABILITY_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
GIT_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
MODULE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
M7_LOCAL_STORAGE_GN_ENABLE_ASSIGNMENT_RE = re.compile(
    r"^[ \t]*enable_chromium_wasm_m7_default_partition_local_storage_test"
    r"[ \t]*=[ \t]*(true|false)[ \t]*(?:#.*)?$",
    re.MULTILINE,
)
M7_PREFERENCES_GN_ENABLE_ASSIGNMENT_RE = re.compile(
    r"^[ \t]*enable_chromium_wasm_m7_profile_preferences_test"
    r"[ \t]*=[ \t]*(true|false)[ \t]*(?:#.*)?$",
    re.MULTILINE,
)
M7_DATABASE_GN_ENABLE_ASSIGNMENT_RE = re.compile(
    r"^[ \t]*enable_chromium_wasm_m7_profile_database_test"
    r"[ \t]*=[ \t]*(true|false)[ \t]*(?:#.*)?$",
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
_DOCUMENT_FIELDS = frozenset(("identity", "navigationType", "ordinal", "phase", "timeOrigin"))
_TOKEN_EVIDENCE_FIELDS = frozenset(
    (
        "algorithm",
        "digest",
        "rawTokenExcluded",
        "rawTokenLeakDetected",
        "rawTokenRedactionCount",
    )
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
        "leaseReleasedMarkerObserved",
        "lifecycleComplete",
        "markerCount",
        "markerSequenceAccepted",
        "markerSource",
        "markers",
        "mode",
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
_HOST_BOUNDARY_FIELDS = frozenset(
    (
        "hostDomStorageAccessAttempted",
        "hostOpfsAccessAttempted",
        "hostWebLocksAccessAttempted",
        "nativeCallAttempted",
        "wasmDataInspectionAttempted",
    )
)
_FAILURE_RUN_FIELDS = frozenset(
    (
        "abortObserved",
        "expectedCleanExitStatusObserved",
        "factoryRejected",
        "factoryResolved",
        "factorySettled",
        "freshLoaderImport",
        "freshModuleObject",
        "leaseReleasedMarkerObserved",
        "lifecycleComplete",
        "markerCount",
        "markerSequenceAccepted",
        "nativeFailureStage",
        "onExitCount",
        "outputLineCount",
        "processExitCode",
        "processExitCount",
        "runtimeExitCode",
        "runtimeInitialized",
        "stdoutMarkerCount",
    )
)
NATIVE_FAILURE_STAGES = frozenset(
    (
        "arguments",
        "capability",
        "storage",
        "profile",
        "read",
        "commit",
        "close",
        "fence",
        "lifecycle",
        "content",
        "drain",
    )
)
_FAILURE_RUN_BOOLEAN_FIELDS = frozenset(
    (
        "abortObserved",
        "expectedCleanExitStatusObserved",
        "factoryRejected",
        "factoryResolved",
        "factorySettled",
        "freshLoaderImport",
        "freshModuleObject",
        "leaseReleasedMarkerObserved",
        "lifecycleComplete",
        "markerSequenceAccepted",
        "runtimeInitialized",
    )
)
_FAILURE_RUN_COUNT_LIMITS = {
    "markerCount": 6,
    "onExitCount": 1,
    "outputLineCount": MAX_OUTPUT_LINES + 1,
    "processExitCount": 1,
    "stdoutMarkerCount": MAX_OUTPUT_LINES + 1,
}
_FAILURE_DIAGNOSTIC_FIELDS = frozenset(
    (
        "case",
        "failureClass",
        "hostBoundary",
        "m7GateComplete",
        "phase",
        "protocol",
        "run",
        "scope",
        "status",
    )
)
HOST_FAILURE_CLASS = "host-lifecycle"
_RESULT_FIELDS = frozenset(
    (
        "artifact",
        "bridge",
        "capture_harness",
        "case",
        "crossOriginIsolated",
        "document",
        "error",
        "hostBoundary",
        "m7GateComplete",
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

_PHASES = {
    "write": ("renderer-write", 1),
    "verify": ("renderer-verify", 2),
}


@dataclass(frozen=True)
class TokenEscrow:
    """One raw token that never participates in a visible receipt."""

    token: str = field(repr=False)
    digest: str


class ProtocolStateError(M0Error):
    """A one-use document bootstrap or receipt state conflict."""


class HostFailureDiagnosticError(M0Error):
    """A validated, terminal host lifecycle failure receipt."""

    def __init__(self, diagnostic: dict[str, Any]) -> None:
        self.diagnostic = diagnostic
        super().__init__("renderer LocalStorage host lifecycle failure reported")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def new_token_escrow() -> TokenEscrow:
    token = secrets.token_hex(32)
    if not SHA256_RE.fullmatch(token):
        raise M0Error("renderer LocalStorage token generation is invalid")
    return TokenEscrow(token=token, digest=_sha256_text(token))


def _new_capability() -> str:
    value = secrets.token_urlsafe(24)
    if not CAPABILITY_RE.fullmatch(value):
        raise M0Error("renderer LocalStorage capability generation is invalid")
    return value


class OuterReloadSession:
    """Server-only state for the two genuinely separate host documents."""

    def __init__(
        self,
        result_token: str,
        write_session: str,
        verify_session: str,
        escrow: TokenEscrow,
    ) -> None:
        values = (result_token, write_session, verify_session)
        if (
            len(set(values)) != len(values)
            or not all(CAPABILITY_RE.fullmatch(value) for value in values)
            or not SHA256_RE.fullmatch(escrow.token)
            or _sha256_text(escrow.token) != escrow.digest
        ):
            raise M0Error("renderer LocalStorage session escrow is invalid")
        self._result_token = result_token
        self._sessions = {"write": write_session, "verify": verify_session}
        self._escrow = escrow
        self._document_requests: set[str] = set()
        self._bootstraps: set[str] = set()
        self._receipts: dict[str, dict[str, Any]] = {}
        self._failure_diagnostic: dict[str, Any] | None = None
        self._lock = threading.Lock()

    @property
    def escrow(self) -> TokenEscrow:
        return self._escrow

    @property
    def document_requests(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._document_requests)

    def matches_result_token(self, value: str | None) -> bool:
        return isinstance(value, str) and secrets.compare_digest(
            value, self._result_token
        )

    def phase_for_session(self, value: str | None) -> str | None:
        if not isinstance(value, str):
            return None
        for phase, session in self._sessions.items():
            if secrets.compare_digest(value, session):
                return phase
        return None

    def register_document_request(self, phase: str, session: str) -> bool:
        if self.phase_for_session(session) != phase:
            return False
        with self._lock:
            if self._failure_diagnostic is not None:
                return False
            if phase == "verify" and "write" not in self._receipts:
                return False
            if phase in self._document_requests:
                raise ProtocolStateError("outer document was requested twice")
            self._document_requests.add(phase)
            return True

    def bootstrap_payload(self, session: str) -> dict[str, object] | None:
        phase = self.phase_for_session(session)
        if phase is None:
            return None
        with self._lock:
            if self._failure_diagnostic is not None:
                return None
            if phase not in self._document_requests or phase in self._bootstraps:
                raise ProtocolStateError("outer document bootstrap state conflict")
            if phase == "verify" and "write" not in self._receipts:
                raise ProtocolStateError("verify bootstrap precedes write receipt")
            self._bootstraps.add(phase)
            mode, ordinal = _PHASES[phase]
            return {
                "protocol": 1,
                "case": CASE,
                "scope": SCOPE,
                "ordinal": ordinal,
                "mode": mode,
                "token": self._escrow.token,
                "tokenDigest": self._escrow.digest,
            }

    def accept_receipt(
        self, result_token: str, phase: str, value: dict[str, Any]
    ) -> bool:
        if not self.matches_result_token(result_token) or phase not in _PHASES:
            return False
        with self._lock:
            if (
                self._failure_diagnostic is not None
                or phase not in self._bootstraps
                or phase in self._receipts
            ):
                raise ProtocolStateError("outer document receipt state conflict")
            if phase == "verify" and "write" not in self._receipts:
                raise ProtocolStateError("verify receipt precedes write receipt")
            self._receipts[phase] = value
            return True

    def accept_failure_diagnostic(
        self, result_token: str, phase: str, value: dict[str, Any]
    ) -> bool:
        """Accept one terminal failure without treating it as a receipt."""

        if not self.matches_result_token(result_token) or phase not in _PHASES:
            return False
        with self._lock:
            if (
                self._failure_diagnostic is not None
                or phase not in self._bootstraps
                or phase in self._receipts
            ):
                raise ProtocolStateError("outer document failure state conflict")
            if phase == "verify" and "write" not in self._receipts:
                raise ProtocolStateError("verify failure precedes write receipt")
            self._failure_diagnostic = value
            return True

    def receipts(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return dict(self._receipts)


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
    """Accept only the isolated M7 LocalStorage output directory and flag."""

    if out_dir.name != DEFAULT_OUT_DIR.name:
        raise M0Error("renderer LocalStorage runner requires its isolated output")
    try:
        text = args_gn.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError as exc:
        raise M0Error("renderer LocalStorage args.gn is not UTF-8") from exc
    enabled = M7_LOCAL_STORAGE_GN_ENABLE_ASSIGNMENT_RE.findall(text)
    if not enabled or any(value != "true" for value in enabled):
        raise M0Error("renderer LocalStorage args.gn lacks its test opt-in")
    incompatible = (
        M7_PREFERENCES_GN_ENABLE_ASSIGNMENT_RE.findall(text)
        + M7_DATABASE_GN_ENABLE_ASSIGNMENT_RE.findall(text)
    )
    if any(value == "true" for value in incompatible):
        raise M0Error("renderer LocalStorage args.gn enables another M7 test")


def _reject_duplicate_object_keys(
    pairs: list[tuple[str, object]]
) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON object key")
        value[key] = item
    return value


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


def _byte_identity(contents: bytes) -> dict[str, object]:
    return {"bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}


def _exact_fields(value: object, fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise M0Error(f"renderer LocalStorage {name} schema is invalid")
    return value


def _validate_byte_identity(value: object, name: str) -> None:
    identity = _exact_fields(value, _BYTE_IDENTITY_FIELDS, name)
    if (
        type(identity.get("bytes")) is not int
        or identity["bytes"] < 1
        or not isinstance(identity.get("sha256"), str)
        or not SHA256_RE.fullmatch(identity["sha256"])
    ):
        raise M0Error(f"renderer LocalStorage {name} is invalid")


def expected_markers(phase: str, escrow: TokenEscrow) -> list[str]:
    mode, _ = _PHASES[phase]
    operation = (
        "RENDERER_WRITE_OK" if mode == "renderer-write" else "RENDERER_REOPEN_READ_OK"
    )
    return [
        f"{M7_MARKER_PREFIX}READY",
        f"{M7_MARKER_PREFIX}{operation} sha256={escrow.digest}",
        f"{M7_MARKER_PREFIX}ON_DISK_COMMIT_OK sha256={escrow.digest}",
        f"{M7_MARKER_PREFIX}DB_CLOSE_OK sha256={escrow.digest}",
        f"{M7_MARKER_PREFIX}FENCE_OK sha256={escrow.digest}",
        f"{M7_MARKER_PREFIX}LEASE_RELEASED",
    ]


def _validate_identity(value: object, expected: dict[str, object], name: str) -> None:
    actual = _exact_fields(value, _ARTIFACT_FIELDS if name == "artifact" else _CAPTURE_HARNESS_FIELDS, name)
    fields = ("build_config", "loader", "wasm") if name == "artifact" else (
        "host_html", "host_js", "runner_source"
    )
    for field_name in fields:
        _validate_byte_identity(actual.get(field_name), f"{name} {field_name}")
    if actual != expected:
        raise M0Error(f"renderer LocalStorage {name} identity is invalid")


def validate_document_result(
    result: dict[str, Any],
    *,
    phase: str,
    expected_versions: dict[str, str],
    expected_artifact: dict[str, object],
    expected_capture_harness: dict[str, object],
    expected_origin: str,
    escrow: TokenEscrow,
    prohibited: tuple[str, ...],
) -> None:
    """Validate one document receipt before it can unlock the next one."""

    if phase not in _PHASES or _contains_prohibited_strings(result, prohibited):
        raise M0Error("renderer LocalStorage receipt contains an opaque value")
    result = _exact_fields(result, _RESULT_FIELDS, "result")
    mode, ordinal = _PHASES[phase]
    fixed = {
        "protocol": 1,
        "case": CASE,
        "scope": SCOPE,
        "status": "pass",
        "m7GateComplete": False,
        "origin": expected_origin,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "phase": phase,
        "error": None,
        "versions": expected_versions,
    }
    if any(result.get(field) != expected for field, expected in fixed.items()):
        raise M0Error("renderer LocalStorage fixed receipt field is invalid")
    _validate_identity(result.get("artifact"), expected_artifact, "artifact")
    _validate_identity(
        result.get("capture_harness"), expected_capture_harness, "capture harness"
    )
    document = _exact_fields(result.get("document"), _DOCUMENT_FIELDS, "document")
    if (
        document.get("phase") != phase
        or document.get("ordinal") != ordinal
        or document.get("navigationType") != "navigate"
        or not isinstance(document.get("identity"), str)
        or not MODULE_ID_RE.fullmatch(document["identity"])
        or type(document.get("timeOrigin")) not in (int, float)
        or not math.isfinite(float(document["timeOrigin"]))
    ):
        raise M0Error("renderer LocalStorage document receipt is invalid")
    evidence = _exact_fields(result.get("tokenEvidence"), _TOKEN_EVIDENCE_FIELDS, "token evidence")
    if (
        evidence.get("algorithm") != "SHA-256"
        or evidence.get("digest") != escrow.digest
        or evidence.get("rawTokenExcluded") is not True
        or evidence.get("rawTokenLeakDetected") is not False
        or evidence.get("rawTokenRedactionCount") != 0
    ):
        raise M0Error("renderer LocalStorage token evidence is invalid")
    run = _exact_fields(result.get("run"), _RUN_FIELDS, "run")
    markers = run.get("markers")
    if (
        run.get("mode") != mode
        or run.get("ordinal") != ordinal
        or not isinstance(run.get("moduleIdentity"), str)
        or not MODULE_ID_RE.fullmatch(run["moduleIdentity"])
        or run.get("abortObserved") is not False
        or type(run.get("expectedCleanExitStatusObserved")) is not bool
        or run.get("factoryRejected") is not False
        or run.get("factoryResolved") is not True
        or run.get("factorySettled") is not True
        or run.get("freshLoaderImport") is not True
        or run.get("freshModuleObject") is not True
        or run.get("leaseReleasedMarkerObserved") is not True
        or run.get("lifecycleComplete") is not True
        or run.get("markerSequenceAccepted") is not True
        or run.get("markerSource")
        != "stderr-only-fixed-renderer-local-storage-grammar"
        or markers != expected_markers(phase, escrow)
        or run.get("markerCount") != len(markers)
        or run.get("onExitCount") != 1
        or run.get("processExitCode") != 0
        or run.get("processExitCount") != 1
        or run.get("runtimeExitCode") != 0
        or run.get("runtimeInitialized") is not True
        or run.get("stdoutMarkerCount") != 0
        or type(run.get("outputLineCount")) is not int
        or not len(markers) <= run["outputLineCount"] <= MAX_OUTPUT_LINES
    ):
        raise M0Error("renderer LocalStorage run receipt is invalid")
    bridge = _exact_fields(result.get("bridge"), _BRIDGE_FIELDS, "bridge")
    if (
        bridge.get("protocol") != 1
        or bridge.get("permanent") is not True
        or bridge.get("frozen") is not True
        or bridge.get("installedBeforeModuleFactory") is not True
        or bridge.get("processExitDispatches") != 1
        or bridge.get("activeAtResult") is not True
    ):
        raise M0Error("renderer LocalStorage bridge receipt is invalid")
    quiescence = _exact_fields(result.get("quiescence"), _QUIESCENCE_FIELDS, "quiescence")
    if (
        quiescence.get("quiet") is not True
        or quiescence.get("quietWindowMs") != QUIESCENCE_MS
        or type(quiescence.get("callbacksAtClear")) is not int
        or quiescence.get("callbacksAtClear") != quiescence.get("callbacksAfterQuiescence")
    ):
        raise M0Error("renderer LocalStorage quiescence receipt is invalid")
    boundary = _exact_fields(result.get("hostBoundary"), _HOST_BOUNDARY_FIELDS, "host boundary")
    if any(value is not False for value in boundary.values()):
        raise M0Error("renderer LocalStorage host crossed a prohibited boundary")


def _validate_failure_run_snapshot(value: object) -> dict[str, Any] | None:
    """Keep only bounded structural lifecycle state from a failed host."""

    if value is None:
        return None
    run = _exact_fields(value, _FAILURE_RUN_FIELDS, "failure run")
    if any(type(run.get(field)) is not bool for field in _FAILURE_RUN_BOOLEAN_FIELDS):
        raise M0Error("renderer LocalStorage failure run flags are invalid")
    for field, maximum in _FAILURE_RUN_COUNT_LIMITS.items():
        count = run.get(field)
        if type(count) is not int or count < 0 or count > maximum:
            raise M0Error("renderer LocalStorage failure run counts are invalid")
    for field in ("processExitCode", "runtimeExitCode"):
        code = run.get(field)
        if code is not None and (
            type(code) is not int or code < -(2**31) or code > 2**31 - 1
        ):
            raise M0Error("renderer LocalStorage failure run exit code is invalid")
    native_failure_stage = run.get("nativeFailureStage")
    if native_failure_stage is not None and (
        not isinstance(native_failure_stage, str)
        or native_failure_stage not in NATIVE_FAILURE_STAGES
    ):
        raise M0Error("renderer LocalStorage failure native stage is invalid")
    return {field: run[field] for field in sorted(_FAILURE_RUN_FIELDS)}


def validate_host_failure_diagnostic(
    value: object,
    *,
    phase: str,
    prohibited: tuple[str, ...],
) -> dict[str, Any]:
    """Accept only a redacted terminal failure diagnostic, never success evidence."""

    if phase not in _PHASES or _contains_prohibited_strings(value, prohibited):
        raise M0Error("renderer LocalStorage failure diagnostic contains an opaque value")
    diagnostic = _exact_fields(value, _FAILURE_DIAGNOSTIC_FIELDS, "failure diagnostic")
    fixed = {
        "protocol": 1,
        "case": CASE,
        "scope": SCOPE,
        "status": "fail",
        "m7GateComplete": False,
        "phase": phase,
        "failureClass": HOST_FAILURE_CLASS,
    }
    if any(diagnostic.get(field) != expected for field, expected in fixed.items()):
        raise M0Error("renderer LocalStorage failure diagnostic identity is invalid")
    boundary = _exact_fields(
        diagnostic.get("hostBoundary"), _HOST_BOUNDARY_FIELDS, "failure host boundary"
    )
    if any(value is not False for value in boundary.values()):
        raise M0Error("renderer LocalStorage failure host crossed a prohibited boundary")
    return {
        "case": CASE,
        "failureClass": HOST_FAILURE_CLASS,
        "hostBoundary": {field: False for field in sorted(_HOST_BOUNDARY_FIELDS)},
        "m7GateComplete": False,
        "phase": phase,
        "protocol": 1,
        "run": _validate_failure_run_snapshot(diagnostic.get("run")),
        "scope": SCOPE,
        "status": "fail",
    }


def validate_two_document_receipts(
    receipts: dict[str, dict[str, Any]], session: OuterReloadSession
) -> None:
    """Require a separate host identity and fresh module for each phase."""

    if set(receipts) != {"write", "verify"} or session.document_requests != {
        "write",
        "verify",
    }:
        raise M0Error("renderer LocalStorage did not complete two outer documents")
    write = receipts["write"]
    verify = receipts["verify"]
    write_document = write["document"]
    verify_document = verify["document"]
    write_run = write["run"]
    verify_run = verify["run"]
    if (
        write_document["identity"] == verify_document["identity"]
        or write_document["timeOrigin"] == verify_document["timeOrigin"]
        or write_run["moduleIdentity"] == verify_run["moduleIdentity"]
        or write["tokenEvidence"]["digest"] != verify["tokenEvidence"]["digest"]
    ):
        raise M0Error("renderer LocalStorage outer-document freshness is invalid")


class RendererLocalStorageServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    args_gn: bytes
    artifacts: dict[str, bytes]
    artifact_identity: dict[str, object]
    capture_harness_identity: dict[str, object]
    expected_origin: str
    failure_queue: queue.Queue[dict[str, Any]]
    host_html: bytes
    host_js: bytes
    module_name: str
    next_document_url: str
    receipt_lock: threading.Lock
    result_queue: queue.Queue[dict[str, dict[str, Any]]]
    runner_source: bytes
    session: OuterReloadSession
    versions: dict[str, str]

    def handle_error(self, _request: object, _client_address: object) -> None:
        # Capability-bearing URLs must not reach the standard server logger.
        return


class RendererLocalStorageRequestHandler(BaseHTTPRequestHandler):
    server: RendererLocalStorageServer

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

    def _read_json_body(self, result_token: str) -> dict[str, Any] | None:
        if self.headers.get("Transfer-Encoding"):
            return None
        length_text = self.headers.get("Content-Length")
        if length_text is None or not re.fullmatch(r"[0-9]+", length_text.strip()):
            return None
        length = int(length_text)
        if length <= 0 or length > MAX_RESULT_BYTES:
            return None
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            return None
        payload = self.rfile.read(length)
        if len(payload) != length:
            return None
        value = _parse_json_object(payload)
        if value is None or _contains_prohibited_strings(
            value,
            (
                self.server.session.escrow.token,
                result_token,
                self.server.next_document_url,
            ),
        ):
            return None
        return value

    @staticmethod
    def _host_query_phase(parsed_path: str, query: str) -> tuple[str, str] | None:
        if parsed_path not in (HOST_ROOT, f"{HOST_ROOT}/"):
            return None
        try:
            values = parse_qs(query, strict_parsing=True, keep_blank_values=True)
        except ValueError:
            return None
        if set(values) != {
            "artifact",
            "captureHarness",
            "module",
            "phase",
            "resultToken",
            "session",
            "timeoutMs",
            "versions",
        } or any(len(value) != 1 for value in values.values()):
            return None
        phase = values["phase"][0]
        session = values["session"][0]
        return (phase, session) if phase in _PHASES else None

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        host_query = self._host_query_phase(parsed.path, parsed.query)
        if host_query is not None:
            phase, session = host_query
            try:
                accepted = self.server.session.register_document_request(phase, session)
            except ProtocolStateError:
                self._conflict()
                return
            if not accepted:
                self._not_found()
                return
            self._send_bytes(HTTPStatus.OK, "text/html; charset=utf-8", self.server.host_html)
            return
        if parsed.query:
            self._not_found()
            return
        if parsed.path == f"{HOST_ROOT}/{HOST_JS_NAME}":
            self._send_bytes(HTTPStatus.OK, "text/javascript; charset=utf-8", self.server.host_js)
            return
        artifact_prefix = f"{HOST_ROOT}/artifacts/"
        if parsed.path.startswith(artifact_prefix):
            name = parsed.path[len(artifact_prefix) :]
            artifact = self.server.artifacts.get(name)
            if artifact is not None and "/" not in name:
                content_type = "application/wasm" if name.endswith(".wasm") else "text/javascript; charset=utf-8"
                self._send_bytes(HTTPStatus.OK, content_type, artifact)
                return
        bootstrap_prefix = f"{HOST_ROOT}/bootstrap/"
        if parsed.path.startswith(bootstrap_prefix):
            session = parsed.path[len(bootstrap_prefix) :]
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
    def _result_path(path: str) -> tuple[str, str] | None:
        prefix = f"{HOST_ROOT}/result/"
        if not path.startswith(prefix):
            return None
        parts = path[len(prefix) :].split("/")
        if len(parts) != 2 or not CAPABILITY_RE.fullmatch(parts[0]) or parts[1] not in _PHASES:
            return None
        return parts[0], parts[1]

    @staticmethod
    def _failure_path(path: str) -> tuple[str, str] | None:
        prefix = f"{HOST_ROOT}/failure/"
        if not path.startswith(prefix):
            return None
        parts = path[len(prefix) :].split("/")
        if len(parts) != 2 or not CAPABILITY_RE.fullmatch(parts[0]) or parts[1] not in _PHASES:
            return None
        return parts[0], parts[1]

    def do_POST(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.query:
            self._not_found()
            return
        result_path = self._result_path(parsed.path)
        failure_path = self._failure_path(parsed.path)
        if result_path is None and failure_path is None:
            self._not_found()
            return
        result_token, phase = result_path or failure_path
        if not self.server.session.matches_result_token(result_token):
            self._not_found()
            return
        value = self._read_json_body(result_token)
        if value is None:
            self._send_bytes(HTTPStatus.BAD_REQUEST, "text/plain; charset=utf-8", b"invalid result\n")
            return
        if failure_path is not None:
            try:
                diagnostic = validate_host_failure_diagnostic(
                    value,
                    phase=phase,
                    prohibited=(
                        self.server.session.escrow.token,
                        result_token,
                        self.server.next_document_url,
                    ),
                )
                with self.server.receipt_lock:
                    if self.server.result_queue.full() or self.server.failure_queue.full():
                        self._conflict()
                        return
                    accepted = self.server.session.accept_failure_diagnostic(
                        result_token, phase, diagnostic
                    )
                    if not accepted:
                        self._not_found()
                        return
                    self.server.failure_queue.put_nowait(diagnostic)
            except ProtocolStateError:
                self._conflict()
                return
            except M0Error:
                self._send_bytes(
                    HTTPStatus.BAD_REQUEST,
                    "text/plain; charset=utf-8",
                    b"invalid failure diagnostic\n",
                )
                return
            self._send_empty(HTTPStatus.NO_CONTENT)
            return
        try:
            validate_document_result(
                value,
                phase=phase,
                expected_versions=self.server.versions,
                expected_artifact=self.server.artifact_identity,
                expected_capture_harness=self.server.capture_harness_identity,
                expected_origin=self.server.expected_origin,
                escrow=self.server.session.escrow,
                prohibited=(
                    self.server.session.escrow.token,
                    result_token,
                    self.server.next_document_url,
                ),
            )
            accepted = self.server.session.accept_receipt(result_token, phase, value)
        except ProtocolStateError:
            self._conflict()
            return
        except M0Error:
            self._send_bytes(HTTPStatus.BAD_REQUEST, "text/plain; charset=utf-8", b"invalid result\n")
            return
        if not accepted:
            self._not_found()
            return
        if phase == "write":
            self._send_bytes(
                HTTPStatus.OK,
                "application/json; charset=utf-8",
                json.dumps({"nextDocument": self.server.next_document_url}, separators=(",", ":")).encode("utf-8"),
            )
            return
        receipts = self.server.session.receipts()
        with self.server.receipt_lock:
            if self.server.result_queue.full():
                self._conflict()
                return
            self.server.result_queue.put_nowait(receipts)
        self._send_empty(HTTPStatus.NO_CONTENT)


def toolchain_manifest_versions(manifest: dict[str, Any]) -> dict[str, str]:
    try:
        versions = {
            "chromium": manifest["chromium"]["revision"],
            "v8": manifest["git_dependencies"]["v8"]["revision"],
            "emscripten": manifest["emscripten"]["source_revision"],
        }
    except (KeyError, TypeError) as exc:
        raise M0Error("renderer LocalStorage manifest lacks version metadata") from exc
    if not all(isinstance(value, str) and GIT_REVISION_RE.fullmatch(value) for value in versions.values()):
        raise M0Error("renderer LocalStorage manifest version metadata is invalid")
    return versions


def create_server(
    host: str,
    port: int,
    out_dir: Path,
    *,
    versions: dict[str, str],
    result_token: str,
    write_session: str,
    verify_session: str,
    escrow: TokenEscrow,
    host_dir: Path | None = None,
    runner_source_path: Path | None = None,
) -> RendererLocalStorageServer:
    """Freeze all execution inputs before accepting a document request."""

    artifacts = snapshot_regular_files(
        out_dir,
        (f"{PRODUCT_MODULE_NAME}.js", f"{PRODUCT_MODULE_NAME}.wasm"),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="renderer LocalStorage artifacts",
    )
    args_gn = snapshot_regular_file(
        out_dir / "args.gn",
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="renderer LocalStorage args.gn",
    )
    validate_m7_output_configuration(args_gn, out_dir)
    host_snapshots = snapshot_regular_files(
        host_dir or Path(__file__).with_name("host"),
        (HOST_HTML_NAME, HOST_JS_NAME),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="renderer LocalStorage host resources",
    )
    runner_source = snapshot_regular_file(
        runner_source_path or Path(__file__),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="renderer LocalStorage runner source",
    )
    server = RendererLocalStorageServer(
        (host, port), RendererLocalStorageRequestHandler
    )
    server.args_gn = args_gn
    server.artifacts = artifacts
    server.artifact_identity = {
        "artifact_delivery": ARTIFACT_DELIVERY,
        "artifact_source_provenance": ARTIFACT_SOURCE_PROVENANCE,
        "build_config": _byte_identity(args_gn),
        "build_config_provenance": BUILD_CONFIG_PROVENANCE,
        "loader": _byte_identity(artifacts[f"{PRODUCT_MODULE_NAME}.js"]),
        "module_name": PRODUCT_MODULE_NAME,
        "wasm": _byte_identity(artifacts[f"{PRODUCT_MODULE_NAME}.wasm"]),
    }
    server.capture_harness_identity = {
        "host_html": _byte_identity(host_snapshots[HOST_HTML_NAME]),
        "host_js": _byte_identity(host_snapshots[HOST_JS_NAME]),
        "runner_source": _byte_identity(runner_source),
        "source_snapshot_provenance": SOURCE_SNAPSHOT_PROVENANCE,
        "version_provenance": VERSION_PROVENANCE,
    }
    server.host_html = host_snapshots[HOST_HTML_NAME]
    server.host_js = host_snapshots[HOST_JS_NAME]
    server.module_name = PRODUCT_MODULE_NAME
    server.receipt_lock = threading.Lock()
    server.failure_queue = queue.Queue(maxsize=1)
    server.result_queue = queue.Queue(maxsize=1)
    server.runner_source = runner_source
    server.session = OuterReloadSession(result_token, write_session, verify_session, escrow)
    server.versions = dict(versions)
    server.expected_origin = f"http://{server.server_address[0]}:{server.server_address[1]}"
    server.next_document_url = ""
    return server


def smoke_url(
    server: RendererLocalStorageServer,
    *,
    phase: str,
    result_token: str,
    session: str,
    timeout_seconds: float,
) -> str:
    if phase not in _PHASES or server.module_name != PRODUCT_MODULE_NAME:
        raise M0Error("renderer LocalStorage URL state is invalid")
    timeout_ms = int(timeout_seconds * 1000)
    if timeout_ms < int(MIN_TIMEOUT_SECONDS * 1000) or timeout_ms > MAX_TIMEOUT_MS:
        raise M0Error("renderer LocalStorage URL timeout is invalid")
    query = urlencode(
        {
            "artifact": json.dumps(server.artifact_identity, sort_keys=True, separators=(",", ":")),
            "captureHarness": json.dumps(server.capture_harness_identity, sort_keys=True, separators=(",", ":")),
            "module": PRODUCT_MODULE_NAME,
            "phase": phase,
            "resultToken": result_token,
            "session": session,
            "timeoutMs": str(timeout_ms),
            "versions": json.dumps(server.versions, sort_keys=True, separators=(",", ":")),
        }
    )
    return f"{server.expected_origin}{HOST_ROOT}/?{query}"


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


def verify_server_delivery(server: RendererLocalStorageServer) -> None:
    """The test reaches immutable in-memory snapshots, not mutable files."""

    import http.client

    expected = (
        (f"{HOST_ROOT}/{HOST_JS_NAME}", server.host_js, "text/javascript"),
        (f"{HOST_ROOT}/artifacts/{PRODUCT_MODULE_NAME}.js", server.artifacts[f"{PRODUCT_MODULE_NAME}.js"], "text/javascript"),
        (f"{HOST_ROOT}/artifacts/{PRODUCT_MODULE_NAME}.wasm", server.artifacts[f"{PRODUCT_MODULE_NAME}.wasm"], "application/wasm"),
    )
    host, port = server.server_address[:2]
    for path, contents, content_type in expected:
        connection = http.client.HTTPConnection(host, port, timeout=10)
        try:
            connection.request("GET", path, headers={"Cache-Control": "no-store"})
            response = connection.getresponse()
            headers = {name.lower(): value for name, value in response.getheaders()}
            if response.status != HTTPStatus.OK:
                raise M0Error("renderer LocalStorage snapshot request failed")
            for name, expected_value in _expected_headers(content_type).items():
                actual = headers.get(name, "")
                if name == "content-type":
                    actual = actual.split(";", 1)[0].strip().lower()
                if actual != expected_value:
                    raise M0Error("renderer LocalStorage snapshot response header is invalid")
            body = response.read()
            if body != contents:
                raise M0Error("renderer LocalStorage snapshot body changed")
        finally:
            connection.close()


def wait_for_receipts(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    server: RendererLocalStorageServer,
    deadline: float,
) -> dict[str, dict[str, Any]]:
    while True:
        try:
            diagnostic = server.failure_queue.get_nowait()
        except queue.Empty:
            diagnostic = None
        if diagnostic is not None:
            raise HostFailureDiagnosticError(diagnostic)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M0Error(
                "renderer LocalStorage result timed out "
                f"({len(browser_stderr)} browser stderr lines suppressed)"
            )
        try:
            return server.result_queue.get(timeout=min(0.1, remaining))
        except queue.Empty:
            if browser.poll() is not None:
                raise M0Error(
                    "browser exited before renderer LocalStorage receipt "
                    f"({len(browser_stderr)} browser stderr lines suppressed)"
                )


def renderer_local_storage_summary() -> dict[str, object]:
    return {
        "case": CASE,
        "m7GateComplete": False,
        "twoOuterDocumentsProven": True,
        "exactlyTwoFreshModulesProven": True,
        "rendererJavaScriptLocalStorageAtTestChromeOriginProven": True,
        "orderedRendererLocalStorageCloseReopenProven": True,
        "normalProfilePersistenceProven": False,
        "crashOrPowerLossDurabilityProven": False,
        "fullStoragePartitionPersistenceProven": False,
    }


def _stop_server(
    server: RendererLocalStorageServer | None,
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
            raise M0Error("renderer LocalStorage server did not stop")


def _write_failure_diagnostics(
    directory: Path,
    *,
    stage: str,
    error: Exception,
    browser: subprocess.Popen[str] | None,
    browser_stderr: deque[str],
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "chrome-renderer-local-storage-m7-failure.json"
    payload = {
        "schema_version": 1,
        "runner": Path(__file__).name,
        "case": CASE,
        "scope": SCOPE,
        "m7GateComplete": False,
        "stage": stage,
        "failure": {"type": type(error).__name__, "message": "details-suppressed"},
        "host_failure_diagnostic": (
            error.diagnostic if isinstance(error, HostFailureDiagnosticError) else None
        ),
        "host_browser": {
            "started": browser is not None,
            "return_code": browser.poll() if browser is not None else None,
            "stderr_line_count": len(browser_stderr),
            "stderr_suppressed": True,
        },
    }
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--timeout", type=parse_timeout, default=120.0)
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--diagnostics-dir", type=Path)
    args = parser.parse_args()

    browser: subprocess.Popen[str] | None = None
    browser_stderr: deque[str] = deque(maxlen=MAX_BROWSER_STDERR_LINES)
    browser_stderr_thread: threading.Thread | None = None
    outer_profile: tempfile.TemporaryDirectory[str] | None = None
    server: RendererLocalStorageServer | None = None
    server_thread: threading.Thread | None = None
    server_started = False
    stage = "initialize"
    summary: dict[str, object] | None = None
    try:
        stage = "load-manifest"
        versions = toolchain_manifest_versions(load_manifest())
        stage = "create-escrow"
        escrow = new_token_escrow()
        result_token = _new_capability()
        write_session = _new_capability()
        verify_session = _new_capability()
        while len({result_token, write_session, verify_session}) != 3:
            verify_session = _new_capability()
        stage = "create-server"
        server = create_server(
            "127.0.0.1",
            0,
            args.out_dir,
            versions=versions,
            result_token=result_token,
            write_session=write_session,
            verify_session=verify_session,
            escrow=escrow,
        )
        server.next_document_url = smoke_url(
            server,
            phase="verify",
            result_token=result_token,
            session=verify_session,
            timeout_seconds=args.timeout,
        )
        server_thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.05},
            name="chromium-wasm-m7-renderer-local-storage-server",
            daemon=True,
        )
        server_thread.start()
        server_started = True
        stage = "verify-server-delivery"
        verify_server_delivery(server)
        url = smoke_url(
            server,
            phase="write",
            result_token=result_token,
            session=write_session,
            timeout_seconds=args.timeout,
        )
        stage = "find-browser"
        browser_path, _browser_version = find_browser(args.browser)
        outer_profile = tempfile.TemporaryDirectory(
            prefix="chromium-wasm-m7-renderer-local-storage-"
        )
        stage = "launch-browser"
        browser = subprocess.Popen(
            browser_command(browser_path, outer_profile.name, url, no_sandbox=args.no_sandbox),
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
            name="chromium-wasm-m7-renderer-local-storage-browser-stderr",
            daemon=True,
        )
        browser_stderr_thread.start()
        stage = "wait-receipts"
        receipts = wait_for_receipts(
            browser, browser_stderr, server, time.monotonic() + args.timeout
        )
        stage = "validate-two-outer-documents"
        validate_two_document_receipts(receipts, server.session)
        summary = renderer_local_storage_summary()
    except Exception as error:
        if isinstance(error, HostFailureDiagnosticError):
            stage = "host-failure-receipt"
        if args.diagnostics_dir is not None:
            try:
                _write_failure_diagnostics(
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
            _stop_server(server, server_thread, server_started)
        except M0Error:
            summary = None
        if outer_profile is not None:
            outer_profile.cleanup()

    if summary is not None:
        print(
            SENTINEL + ":PASS " + json.dumps(summary, sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
