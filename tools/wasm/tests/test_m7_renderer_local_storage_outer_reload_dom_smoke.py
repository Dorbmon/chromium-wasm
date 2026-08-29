#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused receipt and server-state tests for renderer LocalStorage reload."""

from __future__ import annotations

import copy
from collections import deque
import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m7_chrome_renderer_local_storage_outer_reload_dom_smoke as smoke
from tools.wasm.tests.m3_source_contract_test_support import source


VERSIONS = {"chromium": "a" * 40, "v8": "b" * 40, "emscripten": "c" * 40}
ARTIFACT = {
    "artifact_delivery": smoke.ARTIFACT_DELIVERY,
    "artifact_source_provenance": smoke.ARTIFACT_SOURCE_PROVENANCE,
    "build_config": {"bytes": 71, "sha256": "d" * 64},
    "build_config_provenance": smoke.BUILD_CONFIG_PROVENANCE,
    "loader": {"bytes": 72, "sha256": "e" * 64},
    "module_name": smoke.PRODUCT_MODULE_NAME,
    "wasm": {"bytes": 73, "sha256": "f" * 64},
}
HARNESS = {
    "host_html": {"bytes": 74, "sha256": "0" * 64},
    "host_js": {"bytes": 75, "sha256": "1" * 64},
    "runner_source": {"bytes": 76, "sha256": "2" * 64},
    "source_snapshot_provenance": smoke.SOURCE_SNAPSHOT_PROVENANCE,
    "version_provenance": smoke.VERSION_PROVENANCE,
}
ORIGIN = "http://127.0.0.1:43129"
RESULT_TOKEN = "r" * 32
WRITE_SESSION = "w" * 32
VERIFY_SESSION = "v" * 32


def passing_document(
    phase: str, escrow: smoke.TokenEscrow, *, identity: str, time_origin: float
) -> dict[str, object]:
    mode, ordinal = smoke._PHASES[phase]
    markers = smoke.expected_markers(phase, escrow)
    return {
        "artifact": copy.deepcopy(ARTIFACT),
        "bridge": {
            "activeAtResult": True,
            "frozen": True,
            "installedBeforeModuleFactory": True,
            "permanent": True,
            "processExitDispatches": 1,
            "protocol": 1,
        },
        "capture_harness": copy.deepcopy(HARNESS),
        "case": smoke.CASE,
        "crossOriginIsolated": True,
        "document": {
            "identity": identity,
            "navigationType": "navigate",
            "ordinal": ordinal,
            "phase": phase,
            "timeOrigin": time_origin,
        },
        "error": None,
        "hostBoundary": {
            "hostDomStorageAccessAttempted": False,
            "hostOpfsAccessAttempted": False,
            "hostWebLocksAccessAttempted": False,
            "nativeCallAttempted": False,
            "wasmDataInspectionAttempted": False,
        },
        "m7GateComplete": False,
        "origin": ORIGIN,
        "phase": phase,
        "protocol": 1,
        "quiescence": {
            "callbacksAfterQuiescence": 7,
            "callbacksAtClear": 7,
            "quiet": True,
            "quietWindowMs": smoke.QUIESCENCE_MS,
        },
        "run": {
            "abortObserved": False,
            "expectedCleanExitStatusObserved": False,
            "factoryRejected": False,
            "factoryResolved": True,
            "factorySettled": True,
            "freshLoaderImport": True,
            "freshModuleObject": True,
            "leaseReleasedMarkerObserved": True,
            "lifecycleComplete": True,
            "markerCount": len(markers),
            "markerSequenceAccepted": True,
            "markerSource": "stderr-only-fixed-renderer-local-storage-grammar",
            "markers": markers,
            "mode": mode,
            "moduleIdentity": identity,
            "onExitCount": 1,
            "ordinal": ordinal,
            "outputLineCount": len(markers),
            "processExitCode": 0,
            "processExitCount": 1,
            "runtimeExitCode": 0,
            "runtimeInitialized": True,
            "stdoutMarkerCount": 0,
        },
        "scope": smoke.SCOPE,
        "sharedArrayBuffer": True,
        "status": "pass",
        "tokenEvidence": {
            "algorithm": "SHA-256",
            "digest": escrow.digest,
            "rawTokenExcluded": True,
            "rawTokenLeakDetected": False,
            "rawTokenRedactionCount": 0,
        },
        "versions": copy.deepcopy(VERSIONS),
    }


def validate_document(
    document: dict[str, object], phase: str, escrow: smoke.TokenEscrow
) -> None:
    smoke.validate_document_result(
        document,
        phase=phase,
        expected_versions=VERSIONS,
        expected_artifact=ARTIFACT,
        expected_capture_harness=HARNESS,
        expected_origin=ORIGIN,
        escrow=escrow,
        prohibited=(escrow.token, RESULT_TOKEN, "http://next.invalid/"),
    )


def failed_run_snapshot() -> dict[str, object]:
    return {
        "abortObserved": False,
        "expectedCleanExitStatusObserved": False,
        "factoryRejected": True,
        "factoryResolved": False,
        "factorySettled": True,
        "freshLoaderImport": True,
        "freshModuleObject": False,
        "leaseReleasedMarkerObserved": False,
        "lifecycleComplete": False,
        "markerCount": 2,
        "markerSequenceAccepted": True,
        "nativeFailureStage": "close",
        "onExitCount": 0,
        "outputLineCount": 3,
        "processExitCode": None,
        "processExitCount": 0,
        "runtimeExitCode": None,
        "runtimeInitialized": True,
        "stdoutMarkerCount": 0,
    }


def host_failure_diagnostic(
    phase: str, run: dict[str, object] | None = None
) -> dict[str, object]:
    return {
        "case": smoke.CASE,
        "failureClass": smoke.HOST_FAILURE_CLASS,
        "hostBoundary": {
            "hostDomStorageAccessAttempted": False,
            "hostOpfsAccessAttempted": False,
            "hostWebLocksAccessAttempted": False,
            "nativeCallAttempted": False,
            "wasmDataInspectionAttempted": False,
        },
        "m7GateComplete": False,
        "phase": phase,
        "protocol": 1,
        "run": failed_run_snapshot() if run is None else run,
        "scope": smoke.SCOPE,
        "status": "fail",
    }


class M7RendererLocalStorageOuterReloadDomSmokeTest(unittest.TestCase):
    def test_uses_the_existing_m7_local_storage_artifact_and_opt_in(self) -> None:
        self.assertEqual(
            smoke.PRODUCT_MODULE_NAME,
            "chrome_wasm_m7_default_partition_local_storage_test",
        )
        self.assertEqual(
            smoke.DEFAULT_OUT_DIR,
            Path("out/wasm-chrome-m7-default-partition-local-storage"),
        )
        self.assertEqual(smoke.PRODUCT_GN_TARGET, "//chrome:chrome_wasm")
        self.assertIn(smoke.PRODUCT_GN_ENABLE_ARGUMENT, smoke.DEFAULT_GN_ARGUMENTS)

    def test_accepts_two_distinct_outer_document_receipts(self) -> None:
        escrow = smoke.new_token_escrow()
        write = passing_document("write", escrow, identity="1" * 32, time_origin=1.0)
        verify = passing_document("verify", escrow, identity="2" * 32, time_origin=2.0)
        validate_document(write, "write", escrow)
        validate_document(verify, "verify", escrow)

        session = smoke.OuterReloadSession(
            RESULT_TOKEN, WRITE_SESSION, VERIFY_SESSION, escrow
        )
        self.assertTrue(session.register_document_request("write", WRITE_SESSION))
        self.assertIsNotNone(session.bootstrap_payload(WRITE_SESSION))
        self.assertTrue(session.accept_receipt(RESULT_TOKEN, "write", write))
        self.assertTrue(session.register_document_request("verify", VERIFY_SESSION))
        self.assertIsNotNone(session.bootstrap_payload(VERIFY_SESSION))
        self.assertTrue(session.accept_receipt(RESULT_TOKEN, "verify", verify))
        smoke.validate_two_document_receipts(session.receipts(), session)

    def test_host_failure_diagnostic_is_terminal_and_not_success_evidence(self) -> None:
        escrow = smoke.new_token_escrow()
        diagnostic = host_failure_diagnostic("write")
        accepted = smoke.validate_host_failure_diagnostic(
            diagnostic,
            phase="write",
            prohibited=(escrow.token, RESULT_TOKEN, "http://next.invalid/"),
        )
        self.assertEqual(accepted, diagnostic)
        run = accepted["run"]
        assert isinstance(run, dict)
        self.assertEqual(run["nativeFailureStage"], "close")

        session = smoke.OuterReloadSession(
            RESULT_TOKEN, WRITE_SESSION, VERIFY_SESSION, escrow
        )
        self.assertTrue(session.register_document_request("write", WRITE_SESSION))
        self.assertIsNotNone(session.bootstrap_payload(WRITE_SESSION))
        self.assertTrue(
            session.accept_failure_diagnostic(RESULT_TOKEN, "write", accepted)
        )
        with self.assertRaises(smoke.ProtocolStateError):
            session.accept_receipt(
                RESULT_TOKEN,
                "write",
                passing_document("write", escrow, identity="1" * 32, time_origin=1.0),
            )
        with self.assertRaises(M0Error):
            validate_document(diagnostic, "write", escrow)

    def test_failure_diagnostic_is_redacted_and_unblocks_the_runner(self) -> None:
        escrow = smoke.new_token_escrow()
        diagnostic = host_failure_diagnostic("verify")
        with self.assertRaises(M0Error):
            smoke.validate_host_failure_diagnostic(
                {
                    **diagnostic,
                    "failureClass": escrow.token,
                },
                phase="verify",
                prohibited=(escrow.token, RESULT_TOKEN, "http://next.invalid/"),
            )
        with self.assertRaises(M0Error):
            smoke.validate_host_failure_diagnostic(
                host_failure_diagnostic(
                    "verify",
                    {
                        **failed_run_snapshot(),
                        "nativeFailureStage": "not-a-native-stage",
                    },
                ),
                phase="verify",
                prohibited=(escrow.token, RESULT_TOKEN, "http://next.invalid/"),
            )

        accepted = smoke.validate_host_failure_diagnostic(
            diagnostic,
            phase="verify",
            prohibited=(escrow.token, RESULT_TOKEN, "http://next.invalid/"),
        )
        server = SimpleNamespace(
            failure_queue=queue.Queue(maxsize=1),
            result_queue=queue.Queue(maxsize=1),
        )
        server.failure_queue.put_nowait(accepted)

        class RunningBrowser:
            def poll(self) -> None:
                return None

        with self.assertRaises(smoke.HostFailureDiagnosticError) as raised:
            smoke.wait_for_receipts(
                RunningBrowser(), deque(), server, time.monotonic() + 1
            )
        self.assertEqual(raised.exception.diagnostic, accepted)

        null_stage = smoke.validate_host_failure_diagnostic(
            host_failure_diagnostic(
                "verify",
                {**failed_run_snapshot(), "nativeFailureStage": None},
            ),
            phase="verify",
            prohibited=(escrow.token, RESULT_TOKEN, "http://next.invalid/"),
        )
        null_run = null_stage["run"]
        assert isinstance(null_run, dict)
        self.assertIsNone(null_run["nativeFailureStage"])

        with tempfile.TemporaryDirectory() as temp_dir:
            smoke._write_failure_diagnostics(
                Path(temp_dir),
                stage="host-failure-receipt",
                error=raised.exception,
                browser=None,
                browser_stderr=deque(),
            )
            payload = json.loads(
                (
                    Path(temp_dir)
                    / "chrome-renderer-local-storage-m7-failure.json"
                ).read_text(encoding="utf-8")
            )
        self.assertEqual(payload["stage"], "host-failure-receipt")
        self.assertEqual(payload["host_failure_diagnostic"], accepted)
        self.assertNotIn(escrow.token, json.dumps(payload, sort_keys=True))
        self.assertNotIn(RESULT_TOKEN, json.dumps(payload, sort_keys=True))

    def test_rejects_wrong_renderer_marker_or_reused_outer_identity(self) -> None:
        escrow = smoke.new_token_escrow()
        wrong_marker = passing_document(
            "write", escrow, identity="1" * 32, time_origin=1.0
        )
        run = wrong_marker["run"]
        assert isinstance(run, dict)
        markers = run["markers"]
        assert isinstance(markers, list)
        markers[1], markers[2] = markers[2], markers[1]
        with self.assertRaises(M0Error):
            validate_document(wrong_marker, "write", escrow)

        write = passing_document("write", escrow, identity="1" * 32, time_origin=1.0)
        verify = passing_document("verify", escrow, identity="1" * 32, time_origin=2.0)
        session = smoke.OuterReloadSession(
            RESULT_TOKEN, WRITE_SESSION, VERIFY_SESSION, escrow
        )
        self.assertTrue(session.register_document_request("write", WRITE_SESSION))
        session.bootstrap_payload(WRITE_SESSION)
        session.accept_receipt(RESULT_TOKEN, "write", write)
        self.assertTrue(session.register_document_request("verify", VERIFY_SESSION))
        session.bootstrap_payload(VERIFY_SESSION)
        session.accept_receipt(RESULT_TOKEN, "verify", verify)
        with self.assertRaises(M0Error):
            smoke.validate_two_document_receipts(session.receipts(), session)

    def test_host_validator_accepts_one_runner_shaped_document(self) -> None:
        escrow = smoke.new_token_escrow()
        payload = json.dumps(
            passing_document("write", escrow, identity="1" * 32, time_origin=1.0),
            separators=(",", ":"),
        )
        script = r'''
import {validateChromeWasmRendererLocalStorageOuterReloadDocumentResult} from
  "./tools/wasm/host/chrome_wasm_renderer_local_storage_outer_reload_smoke.js";
const result = JSON.parse(process.argv[1]);
const validated =
    validateChromeWasmRendererLocalStorageOuterReloadDocumentResult(result);
if (validated.status !== "pass" || validated.phase !== "write") {
  throw new Error("host validator rejected runner-shaped receipt");
}
'''
        completed = subprocess.run(
            ["node", "--input-type=module", "--eval", script, payload],
            capture_output=True,
            check=False,
            cwd=TOOLS_DIR.parents[1],
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_host_failure_validator_rejects_a_failure_as_success(self) -> None:
        payload = json.dumps(host_failure_diagnostic("write"), separators=(",", ":"))
        script = r'''
import {
  validateChromeWasmRendererLocalStorageOuterReloadDocumentResult,
  validateChromeWasmRendererLocalStorageOuterReloadFailureDiagnostic,
} from "./tools/wasm/host/chrome_wasm_renderer_local_storage_outer_reload_smoke.js";
const diagnostic = JSON.parse(process.argv[1]);
const validated =
    validateChromeWasmRendererLocalStorageOuterReloadFailureDiagnostic(diagnostic);
if (validated.status !== "fail" || validated.phase !== "write" ||
    validated.run.markerCount !== 2 || validated.run.nativeFailureStage !== "close") {
  throw new Error("host rejected its redacted failure diagnostic");
}
let successRejected = false;
try {
  validateChromeWasmRendererLocalStorageOuterReloadDocumentResult(diagnostic);
} catch (_error) {
  successRejected = true;
}
if (!successRejected) {
  throw new Error("host accepted a failure diagnostic as success evidence");
}
'''
        completed = subprocess.run(
            ["node", "--input-type=module", "--eval", script, payload],
            capture_output=True,
            check=False,
            cwd=TOOLS_DIR.parents[1],
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_host_never_crosses_the_profile_storage_boundary(self) -> None:
        host = source(
            "tools/wasm/host/"
            "chrome_wasm_renderer_local_storage_outer_reload_smoke.js"
        )
        for expected in (
            'location.replace(next.href);',
            '"renderer-write"',
            '"renderer-verify"',
            '"./bootstrap/" + this.context.session',
            '"./result/" + context.resultToken + "/" + context.phase',
            '"./failure/" + context.resultToken + "/" + context.phase',
            "host.failureDiagnostic()",
            "validateFailureDiagnostic(diagnostic)",
            "parseNativeFailureStage(line)",
            "NATIVE_FAILURE_STAGES.includes(stage)",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, host)
        for forbidden in (
            "navigator.storage",
            "navigator.locks",
            "window.localStorage",
            "ccall(",
            "getValue(",
            "HEAPU8",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, host)
        runner = source(
            "tools/wasm/run_m7_chrome_renderer_local_storage_outer_reload_dom_smoke.py"
        )
        self.assertIn(
            '"rendererJavaScriptLocalStorageAtTestChromeOriginProven": True',
            runner,
        )


if __name__ == "__main__":
    unittest.main()
