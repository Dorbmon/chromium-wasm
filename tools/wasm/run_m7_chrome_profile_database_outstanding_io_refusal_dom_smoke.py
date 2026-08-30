#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Prove Chrome refuses an OPFS profile drain while an admission is outstanding.

The page launches one fresh, dedicated M7 database artifact in ``verify-b``
mode with a token that was never written.  The source-selected control-plane
diagnostic intentionally retains the admission after that operation completes,
through profile shutdown. The only accepted receipt is the fixed database
failure, ChromeMain's fixed ``OUTSTANDING_IO`` drain refusal, and then a
separate sealed/lease-retained fail-closed cleanup. The first refusal must
occur before any outer backend transaction; the later cleanup is required so
ordinary runtime exit cannot destroy live OPFS wrappers.

This is a negative lifecycle proof.  It does not establish persistence,
durability, recovery, or full-profile storage behavior.
"""

from __future__ import annotations

import argparse
import base64
from collections import deque
import importlib.util
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
from types import ModuleType
from typing import Any
from urllib.parse import urlencode

from m0_common import M0Error, REPO_ROOT


SENTINEL = "CHROMIUM_WASM_M7_CHROME_PROFILE_DATABASE_OUTSTANDING_IO_REFUSAL_DOM"
CASE = "chrome_profile_database_outstanding_io_refusal_m7"
SCOPE = (
    "same-origin-same-document-one-fresh-chrome-wasm-m7-profile-database-"
    "outstanding-io-refusal-"
    "verify-b-outstanding-profile-io-refusal-then-fail-closed-cleanup"
)
PRODUCT_MODULE_NAME = "chrome_wasm_m7_profile_database_outstanding_io_refusal_test"
PRODUCT_GN_TARGET = "//chrome:chrome_wasm"
PARENT_PRODUCT_GN_ENABLE_ARGUMENT = "enable_chromium_wasm_m7_profile_database_test=true"
PRODUCT_GN_ENABLE_ARGUMENT = (
    "enable_chromium_wasm_m7_profile_database_outstanding_io_refusal_test=true"
)
DEFAULT_OUT_DIR = Path("out/wasm-chrome-m7-profile-database-outstanding-io-refusal")
DEFAULT_GN_ARGUMENTS = (
    'import("//out/wasm-chrome-m6/args.gn") '
    + PARENT_PRODUCT_GN_ENABLE_ARGUMENT
    + " "
    + PRODUCT_GN_ENABLE_ARGUMENT
)
HOST_ROOT = "/__m7_chrome_profile_database_outstanding_io_refusal__"
HOST_HTML_NAME = "chrome_wasm_profile_database_outstanding_io_refusal_smoke.html"
HOST_JS_NAME = "chrome_wasm_profile_database_outstanding_io_refusal_smoke.js"

M7_DATABASE_MARKER_PREFIX = "CHROMIUM_WASM_M7_DATABASE:"
M7_DATABASE_PHASE_PREFIX = "CHROMIUM_WASM_M7_DATABASE_PHASE:"
DRAIN_REFUSAL_MARKER = "CHROMIUM_WASM_M7_PROFILE_DRAIN_REFUSED:OUTSTANDING_IO"
FAILURE_RETIREMENT_MARKER = (
    "CHROMIUM_WASM_M7_PROFILE_FAILURE_RETIREMENT:SEALED_LEASE_RETAINED"
)
EXPECTED_DATABASE_MARKERS = (
    f"{M7_DATABASE_MARKER_PREFIX}READY",
    f"{M7_DATABASE_MARKER_PREFIX}FAIL stage=database",
)
EXPECTED_DATABASE_PHASES = ("task-post", "task-started", "sqlite-read", "task-complete")
EXPECTED_EVENT_SEQUENCE = (
    EXPECTED_DATABASE_MARKERS[0],
    *(f"{M7_DATABASE_PHASE_PREFIX}{phase}" for phase in EXPECTED_DATABASE_PHASES),
    EXPECTED_DATABASE_MARKERS[1],
    DRAIN_REFUSAL_MARKER,
    FAILURE_RETIREMENT_MARKER,
)

MAX_OUTPUT_LINES = 128
MAX_BROWSER_STDERR_LINES = 300
MIN_TIMEOUT_SECONDS = 20.0
MAX_TIMEOUT_MS = 300_000
FINAL_QUIESCENCE_MS = 50
MAX_BUILD_CONFIG_BYTES = 64 * 1024


def _load_isolated_base_runner() -> ModuleType:
    """Load the shared delivery implementation under a private module name.

    The parent runner intentionally exposes its case constants as module
    globals to its request handler.  A normal import followed by substitution
    would alter the published failure-retirement runner in a multi-test Python
    process.  A private import retains the identical delivery implementation
    without sharing its mutable protocol globals.
    """

    source_path = Path(__file__).with_name(
        "run_m7_chrome_profile_database_fail_closed_retirement_dom_smoke.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_m7_outstanding_io_refusal_delivery", source_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load M7 outstanding-I/O delivery support")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    return module


_delivery = _load_isolated_base_runner()
_delivery.CASE = CASE
_delivery.SCOPE = SCOPE
_delivery.PRODUCT_MODULE_NAME = PRODUCT_MODULE_NAME
_delivery.HOST_ROOT = HOST_ROOT
_delivery.HOST_HTML_NAME = HOST_HTML_NAME
_delivery.HOST_JS_NAME = HOST_JS_NAME

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
        "drainRefusalMarkerCount",
        "drainRefusalMarkerObserved",
        "eventCount",
        "eventSequence",
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
        "buildConfigSnapshotValidated",
        "artifact",
        "capture_harness",
        "versions",
        "tokenEvidence",
        "fixedDatabaseFailureObserved",
        "outstandingProfileIORefusalObserved",
        "firstRefusalPrecededOuterBackendTransaction",
        "failClosedCleanupAfterRefusalObserved",
        "safeFailClosedRuntimeExitObserved",
        "normalProfilePersistenceProven",
        "databaseDurabilityProven",
        "physicalCrashBehaviorProven",
        "fullStoragePartitionPersistenceProven",
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


def _encode_build_config_for_host(args_gn: bytes) -> str:
    """Encode the immutable served args snapshot for browser-side validation."""

    if not 0 < len(args_gn) <= MAX_BUILD_CONFIG_BYTES:
        raise M0Error("outstanding-I/O refusal args.gn snapshot is invalid")
    validate_m7_output_configuration(args_gn)
    return base64.urlsafe_b64encode(args_gn).decode("ascii").rstrip("=")


def smoke_url(
    server: Any,
    result_token: str,
    session: str,
    versions: dict[str, str],
    *,
    artifact: dict[str, object],
    capture_harness: dict[str, object],
    timeout_seconds: float,
) -> str:
    """Add the exact immutable args snapshot to the capability-bound context."""

    base_url = _delivery.smoke_url(
        server,
        result_token,
        session,
        versions,
        artifact=artifact,
        capture_harness=capture_harness,
        timeout_seconds=timeout_seconds,
    )
    return base_url + "&" + urlencode(
        {"buildConfig": _encode_build_config_for_host(server.args_gn)}
    )


def _require_exact_fields(value: object, fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise M0Error(f"outstanding-I/O refusal {name} schema is invalid")
    return value


def _require_equal(value: dict[str, Any], field: str, expected: object) -> None:
    if type(value.get(field)) is not type(expected) or value.get(field) != expected:
        raise M0Error(f"outstanding-I/O refusal result {field} is invalid")


def _validate_byte_identity(value: object, description: str) -> None:
    identity = _require_exact_fields(value, _BYTE_IDENTITY_FIELDS, description)
    if (
        type(identity.get("bytes")) is not int
        or identity["bytes"] < 1
        or not isinstance(identity.get("sha256"), str)
        or _delivery.SHA256_RE.fullmatch(identity["sha256"]) is None
    ):
        raise M0Error(f"outstanding-I/O refusal {description} is invalid")


def _validate_artifact_identity(value: object, expected: dict[str, object]) -> None:
    artifact = _require_exact_fields(value, _ARTIFACT_FIELDS, "artifact")
    for field in ("build_config", "loader", "wasm"):
        _validate_byte_identity(artifact.get(field), f"artifact {field}")
    if artifact != expected:
        raise M0Error("outstanding-I/O refusal artifact identity is invalid")


def _validate_capture_harness_identity(value: object, expected: dict[str, object]) -> None:
    harness = _require_exact_fields(value, _CAPTURE_HARNESS_FIELDS, "capture harness")
    for field in ("host_html", "host_js", "runner_source"):
        _validate_byte_identity(harness.get(field), f"capture harness {field}")
    if harness != expected:
        raise M0Error("outstanding-I/O refusal capture harness identity is invalid")


def _validate_token_evidence(value: object, escrow: Any) -> None:
    evidence = _require_exact_fields(value, _TOKEN_EVIDENCE_FIELDS, "token evidence")
    if (
        evidence.get("algorithm") != "SHA-256"
        or evidence.get("tokenB") != escrow.token_b_digest
        or evidence.get("rawTokensExcluded") is not True
        or evidence.get("rawTokenLeakDetected") is not False
        or evidence.get("rawTokenRedactionCount") != 0
    ):
        raise M0Error("outstanding-I/O refusal token evidence is invalid")


def _validate_run(value: object) -> None:
    run = _require_exact_fields(value, _RUN_FIELDS, "run")
    process_exit = run.get("processExitCode")
    if (
        run.get("mode") != "verify-b"
        or not isinstance(run.get("moduleIdentity"), str)
        or _delivery.MODULE_ID_RE.fullmatch(run["moduleIdentity"]) is None
        or run.get("runtimeInitialized") is not True
        or run.get("factorySettled") is not True
        or type(run.get("factoryResolved")) is not bool
        or type(run.get("factoryRejectedExpectedExitStatus")) is not bool
        or run.get("factoryRejectedUnexpected") is not False
        or (run["factoryResolved"] == run["factoryRejectedExpectedExitStatus"])
        or run.get("abortObserved") is not False
        or run.get("processExitCount") != 1
        or type(process_exit) is not int
        or not 0 < process_exit <= 255
        or run.get("onExitCount") != 1
        or run.get("runtimeExitCode") != process_exit
        or run.get("markerSource") != "stderr-only-fixed-grammar"
        or run.get("markerSequenceAccepted") is not True
        or run.get("markers") != list(EXPECTED_DATABASE_MARKERS)
        or run.get("markerCount") != len(EXPECTED_DATABASE_MARKERS)
        or run.get("phases") != list(EXPECTED_DATABASE_PHASES)
        or run.get("phaseCount") != len(EXPECTED_DATABASE_PHASES)
        or run.get("eventSequence") != list(EXPECTED_EVENT_SEQUENCE)
        or run.get("eventCount") != len(EXPECTED_EVENT_SEQUENCE)
        or run.get("databaseFailureMarkerObserved") is not True
        or run.get("drainRefusalMarkerObserved") is not True
        or run.get("drainRefusalMarkerCount") != 1
        or run.get("retirementMarkerObserved") is not True
        or run.get("retirementMarkerCount") != 1
        or run.get("leaseReleasedMarkerObserved") is not False
        or run.get("stdoutMarkerCount") != 0
        or type(run.get("outputLineCount")) is not int
        or not len(EXPECTED_EVENT_SEQUENCE) <= run["outputLineCount"] <= MAX_OUTPUT_LINES
    ):
        raise M0Error("outstanding-I/O refusal run receipt is invalid")


def _validate_bridge(value: object) -> None:
    bridge = _require_exact_fields(value, _BRIDGE_FIELDS, "bridge")
    if (
        bridge.get("protocol") != 1
        or bridge.get("permanent") is not True
        or bridge.get("frozen") is not True
        or bridge.get("installedBeforeModuleFactory") is not True
        or bridge.get("processExitDispatches") != 1
    ):
        raise M0Error("outstanding-I/O refusal bridge receipt is invalid")


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
        raise M0Error("outstanding-I/O refusal callbacks were not quiet")


def _validate_host_boundary(value: object) -> None:
    boundary = _require_exact_fields(value, _HOST_BOUNDARY_FIELDS, "host boundary")
    if any(field_value is not False for field_value in boundary.values()):
        raise M0Error("outstanding-I/O refusal host crossed a prohibited boundary")


def validate_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
    expected_artifact_identity: dict[str, object],
    expected_capture_harness_identity: dict[str, object],
    expected_origin: str,
    escrow: Any,
    result_token: str,
    session: str,
) -> None:
    """Accept only a first refusal followed by fail-closed runtime cleanup."""

    if _delivery._contains_prohibited_strings(result, (escrow.token_b, result_token, session)):
        raise M0Error("outstanding-I/O refusal receipt contains an opaque value")
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
        "buildConfigSnapshotValidated": True,
        "fixedDatabaseFailureObserved": True,
        "outstandingProfileIORefusalObserved": True,
        "firstRefusalPrecededOuterBackendTransaction": True,
        "failClosedCleanupAfterRefusalObserved": True,
        "safeFailClosedRuntimeExitObserved": True,
        "normalProfilePersistenceProven": False,
        "databaseDurabilityProven": False,
        "physicalCrashBehaviorProven": False,
        "fullStoragePartitionPersistenceProven": False,
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


def create_server(
    host: str,
    port: int,
    out_dir: Path,
    result_token: str,
    session: str,
    escrow: Any,
):
    server = _delivery.create_server(
        host,
        port,
        out_dir,
        result_token,
        session,
        escrow,
        host_dir=Path(__file__).with_name("host"),
        runner_source_path=Path(__file__),
        module_name=PRODUCT_MODULE_NAME,
    )
    # The inherited delivery helper validates its ordinary database opt-in as
    # it snapshots this file. Validate the exact same immutable snapshot for
    # this diagnostic's extra source-selection capability before a browser can
    # be served from it.
    try:
        validate_m7_output_configuration(server.args_gn)
    except Exception:
        server.server_close()
        raise
    return server


def validate_m7_output_configuration(args_gn: bytes) -> None:
    """Require the dedicated outstanding-I/O source-selected artifact."""

    _delivery.validate_m7_output_configuration(args_gn)
    try:
        text = args_gn.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError as exc:
        raise M0Error("outstanding-I/O refusal args.gn is not UTF-8") from exc
    assignment = (
        "enable_chromium_wasm_m7_profile_database_outstanding_io_refusal_test"
    )
    values = re.findall(
        rf"^[ \t]*{assignment}[ \t]*=[ \t]*(true|false)[ \t]*(?:#.*)?$",
        text,
        re.MULTILINE,
    )
    if not values or any(value != "true" for value in values):
        raise M0Error("outstanding-I/O refusal args.gn lacks its dedicated opt-in")


def outstanding_io_refusal_summary() -> dict[str, object]:
    return {
        "case": CASE,
        "fixedDatabaseFailureObserved": True,
        "outstandingProfileIORefusalObserved": True,
        "firstRefusalPrecededOuterBackendTransaction": True,
        "failClosedCleanupAfterRefusalObserved": True,
        "safeFailClosedRuntimeExitObserved": True,
        "sealedLeaseRetainedCleanupMarkerObserved": True,
        "noLeaseReleaseMarkerObserved": True,
        "databaseDurabilityProven": False,
        "physicalCrashBehaviorProven": False,
        "fullStoragePartitionPersistenceProven": False,
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


def _write_failure_diagnostics(
    diagnostics_dir: Path,
    *,
    stage: str,
    browser: subprocess.Popen[str] | None,
    browser_stderr: deque[str],
) -> None:
    """Persist only fixed local diagnostics; the token remains unreported."""

    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / "chrome-profile-database-outstanding-io-refusal-m7-failure.json"
    payload = {
        "schema_version": 1,
        "runner": Path(__file__).name,
        "case": CASE,
        "scope": SCOPE,
        "m7GateComplete": False,
        "stage": stage,
        "host_browser": {
            "started": browser is not None,
            "return_code": browser.poll() if browser is not None else None,
            "stderr_line_count": len(browser_stderr),
            "stderr_suppressed_for_opaque_token_hygiene": True,
        },
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prove one retained registered profile-I/O admission refuses the "
            "post-ContentMain M7 OPFS drain before an outer backend-drain or "
            "retirement transaction begins, then receives explicit "
            "fail-closed cleanup before runtime exit."
        ),
        epilog=(
            "Build the dedicated refusal artifact with: buildtools/linux64/gn gen "
            "out/wasm-chrome-m7-profile-database-outstanding-io-refusal --args='"
            + DEFAULT_GN_ARGUMENTS
            + "' --fail-on-unused-args; autoninja -C "
            "out/wasm-chrome-m7-profile-database-outstanding-io-refusal chrome_wasm"
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
    server: Any = None
    server_thread: threading.Thread | None = None
    server_thread_started = False
    stage = "initialize"
    summary: dict[str, object] | None = None

    try:
        stage = "load-manifest"
        versions = _delivery.toolchain_manifest_versions(_delivery.load_manifest())
        stage = "create-token-escrow"
        result_token, session = _delivery.new_capability_pair()
        escrow = _delivery.new_token_escrow()
        stage = "create-server"
        server = create_server("127.0.0.1", 0, args.out_dir, result_token, session, escrow)
        artifact = _delivery.artifact_identity(server)
        capture_harness = _delivery.capture_harness_identity(server)
        server_thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.05},
            name="chromium-wasm-m7-profile-database-outstanding-io-refusal-server",
            daemon=True,
        )
        server_thread.start()
        server_thread_started = True
        stage = "verify-server-delivery"
        _delivery.verify_server_delivery(server)
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
        browser_path, _browser_version = _delivery.find_browser(args.browser)
        outer_profile = tempfile.TemporaryDirectory(
            prefix="chromium-wasm-m7-profile-database-outstanding-io-refusal-"
        )
        stage = "launch-browser"
        command = _delivery.browser_command(
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
            target=_delivery.drain_stream,
            args=(browser.stderr, browser_stderr),
            name="chromium-wasm-m7-profile-database-outstanding-io-refusal-browser-stderr",
            daemon=True,
        )
        browser_stderr_thread.start()
        deadline = time.monotonic() + args.timeout
        stage = "wait-result"
        result = _delivery.wait_for_result(browser, browser_stderr, server, deadline)
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
        summary = outstanding_io_refusal_summary()
    except Exception:
        if args.diagnostics_dir is not None:
            try:
                _write_failure_diagnostics(
                    args.diagnostics_dir,
                    stage=stage,
                    browser=browser,
                    browser_stderr=browser_stderr,
                )
            except OSError:
                pass
        print(f"{SENTINEL}:FAIL stage={stage}", file=sys.stderr, flush=True)
    finally:
        if browser is not None:
            _delivery.stop_browser(browser)
        if browser_stderr_thread is not None:
            browser_stderr_thread.join(timeout=3)
        try:
            _delivery._stop_server(server, server_thread, server_thread_started)
        except M0Error:
            summary = None
        if outer_profile is not None:
            outer_profile.cleanup()

    if summary is not None:
        print(SENTINEL + ":PASS " + json.dumps(summary, sort_keys=True, separators=(",", ":")), flush=True)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
