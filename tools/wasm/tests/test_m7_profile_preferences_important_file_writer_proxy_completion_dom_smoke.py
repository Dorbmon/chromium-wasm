#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the four-document Preferences replacement witness."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import sys
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m7_chrome_profile_preferences_important_file_writer_proxy_completion_dom_smoke as runner
from tools.wasm.tests.m3_source_contract_test_support import source


def _escrow() -> runner.TokenEscrow:
    values = ("a" * 64, "b" * 64, "c" * 64)
    return runner.TokenEscrow(
        token_a=values[0],
        token_b=values[1],
        token_c=values[2],
        token_a_digest=hashlib.sha256(values[0].encode("ascii")).hexdigest(),
        token_b_digest=hashlib.sha256(values[1].encode("ascii")).hexdigest(),
        token_c_digest=hashlib.sha256(values[2].encode("ascii")).hexdigest(),
    )


def _byte_identity() -> dict[str, object]:
    return {"bytes": 1, "sha256": "d" * 64}


def _artifact_identity() -> dict[str, object]:
    return {
        "artifact_delivery": runner.ARTIFACT_DELIVERY,
        "artifact_source_provenance": runner.ARTIFACT_SOURCE_PROVENANCE,
        "build_config": _byte_identity(),
        "build_config_provenance": runner.BUILD_CONFIG_PROVENANCE,
        "loader": _byte_identity(),
        "module_name": runner.PRODUCT_MODULE_NAME,
        "wasm": _byte_identity(),
    }


def _capture_harness_identity() -> dict[str, object]:
    return {
        "host_html": _byte_identity(),
        "host_js": _byte_identity(),
        "runner_source": _byte_identity(),
        "source_snapshot_provenance": runner.SOURCE_SNAPSHOT_PROVENANCE,
        "version_provenance": runner.VERSION_PROVENANCE,
    }


def _versions() -> dict[str, str]:
    return {"chromium": "1" * 40, "v8": "2" * 40, "emscripten": "3" * 40}


def _token_evidence(ordinal: int) -> dict[str, object]:
    escrow = _escrow()
    if ordinal == 1:
        token_a, token_b, distinct = escrow.token_a_digest, None, False
    elif ordinal == 2:
        token_a, token_b, distinct = escrow.token_a_digest, escrow.token_b_digest, True
    elif ordinal == 3:
        token_a, token_b, distinct = escrow.token_a_digest, escrow.token_c_digest, True
    else:
        token_a, token_b, distinct = None, escrow.token_c_digest, False
    return {
        "algorithm": "SHA-256",
        "tokenA": token_a,
        "tokenB": token_b,
        "distinct": distinct,
        "rawTokensExcluded": True,
        "rawTokenLeakDetected": False,
        "rawTokenRedactionCount": 0,
    }


def _passing_result(ordinal: int) -> dict[str, object]:
    failure = ordinal == 2
    exit_code = 19 if failure else 0
    return {
        "protocol": 1,
        "case": runner.CASE,
        "scope": runner.SCOPE,
        "status": runner.phase_status(ordinal),
        "m7GateComplete": False,
        "ordinal": ordinal,
        "mode": runner.phase_mode(ordinal),
        "origin": "http://127.0.0.1:12345",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "document": {
            "navigationType": runner.phase_navigation(ordinal),
            "timeOrigin": float(1000 + ordinal),
        },
        "artifact": _artifact_identity(),
        "captureHarness": _capture_harness_identity(),
        "versions": _versions(),
        "tokenEvidence": _token_evidence(ordinal),
        "run": {
            "abortObserved": False,
            "factoryRejectedExpectedExitStatus": False,
            "factoryRejectedUnexpected": False,
            "factoryResolved": True,
            "factorySettled": True,
            "failureRetirementMarkerObserved": failure,
            "freshLeaseReacquiredMarkerObserved": ordinal == 3,
            "importantFileWriterEioObserved": failure,
            "leaseReleasedMarkerObserved": not failure,
            "markerCount": len(runner.expected_markers(ordinal, _escrow())),
            "markerSequenceAccepted": True,
            "markerSource": "stderr-only-fixed-grammar",
            "markers": runner.expected_markers(ordinal, _escrow()),
            "mode": runner.phase_mode(ordinal),
            "moduleIdentity": f"{ordinal:x}" * 32,
            "onExitCount": 1,
            "ordinal": ordinal,
            "processExitCode": exit_code,
            "processExitCount": 1,
            "runtimeExitCode": exit_code,
            "runtimeInitialized": True,
            "stdoutMarkerCount": 0,
        },
        "bridge": {
            "protocol": 1,
            "permanent": True,
            "frozen": True,
            "installedBeforeModuleFactory": True,
            "processExitDispatches": 1,
            "activeRunAtResult": None,
        },
        "finalQuiescence": {
            "started": True,
            "completed": True,
            "quiet": True,
            "quietWindowMs": runner.FINAL_QUIESCENCE_MS,
            "callbacksAtStart": 7,
            "callbacksAtEnd": 7,
            "callbacksAtPreUploadCheck": 7,
            "processExitReportsAtStart": 1,
            "processExitReportsAtEnd": 1,
            "processExitReportsAtPreUploadCheck": 1,
            "activeRunAtResult": None,
        },
        "hostBoundary": {
            "hostOpfsAccessAttempted": False,
            "hostWebLocksAccessAttempted": False,
            "nativeCallAttempted": False,
            "wasmProfileDataInspectionAttempted": False,
            "sessionStorageAccessAttempted": False,
            "localStorageAccessAttempted": False,
            "indexedDbAccessAttempted": False,
            "cookieAccessAttempted": False,
            "historyStateAccessAttempted": False,
            "windowNameAccessAttempted": False,
        },
        "fatalErrors": [],
        "windowErrors": [],
        "unhandledRejections": [],
        "failedChecks": [],
        "error": None,
    }


class M7PreferencesImportantFileWriterProxyCompletionDomSmokeTest(unittest.TestCase):
    def _validate(self, ordinal: int, result: dict[str, object] | None = None):
        result = _passing_result(ordinal) if result is None else result
        return runner.validate_phase_result(
            result,
            ordinal=ordinal,
            expected_versions=_versions(),
            expected_artifact_identity=_artifact_identity(),
            expected_capture_harness_identity=_capture_harness_identity(),
            expected_origin="http://127.0.0.1:12345",
            expected_document=runner.DocumentEvidence(
                runner.phase_navigation(ordinal), float(1000 + ordinal)
            ),
            escrow=_escrow(),
            result_token="result-capability-abcdefghijklmnopqrstuvwxyz",
            session="session-capability-abcdefghijklmnopqrstuvwxyz",
        )

    def test_accepts_the_four_fixed_redacted_receipts(self) -> None:
        phases = tuple(self._validate(ordinal) for ordinal in (1, 2, 3, 4))
        runner.validate_four_document_transition(*phases)

    def test_rejects_abort_lease_release_and_zero_exit_in_failure_document(self) -> None:
        cases = (
            ("abort", "abortObserved", True, "run receipt"),
            ("lease-release", "leaseReleasedMarkerObserved", True, "marker classification"),
            ("zero-exit", "processExitCode", 0, "clean nonzero"),
            ("missing-retirement", "failureRetirementMarkerObserved", False, "marker classification"),
            ("wrong-marker", "markers", [runner.M7_MARKER_PREFIX + "READY"], "run receipt"),
        )
        for name, field, value, fragment in cases:
            with self.subTest(name=name):
                result = _passing_result(2)
                run = result["run"]
                self.assertIsInstance(run, dict)
                run[field] = value
                with self.assertRaisesRegex(M0Error, fragment):
                    self._validate(2, result)

    def test_rejects_raw_value_or_nonfresh_four_document_transition(self) -> None:
        result = _passing_result(3)
        result["error"] = _escrow().token_c
        with self.assertRaisesRegex(M0Error, "opaque"):
            self._validate(3, result)
        phases = [self._validate(ordinal) for ordinal in (1, 2, 3, 4)]
        phases[3] = runner.PhaseResult(4, "reload", phases[4 - 1].time_origin,
                                       phases[2].module_identity)
        with self.assertRaisesRegex(M0Error, "four-document"):
            runner.validate_four_document_transition(*phases)

    def test_session_requires_fetch_metadata_and_flushed_document_before_bootstrap(self) -> None:
        result_token = "result-capability-abcdefghijklmnopqrstuvwxyz"
        session_token = "session-capability-abcdefghijklmnopqrstuvwxyz"
        session = runner.ProxyCompletionSession(result_token, session_token, _escrow())
        with self.assertRaises(runner.ProtocolStateError):
            session.accept_bootstrap_document(
                session_token, runner.DocumentEvidence("navigate", 1.0)
            )
        self.assertFalse(session.observe_top_level_root_navigation(
            result_token=result_token, session=session_token,
            fetch_destination="iframe", fetch_mode="navigate"))
        self.assertTrue(session.observe_top_level_root_navigation(
            result_token=result_token, session=session_token,
            fetch_destination="document", fetch_mode="navigate"))
        self.assertTrue(session.accept_bootstrap_document(
            session_token, runner.DocumentEvidence("navigate", 1.0)))
        self.assertTrue(session.acknowledge_bootstrap_document(session_token))
        bootstrap = session.bootstrap_payload(session_token)
        self.assertIsNotNone(bootstrap)
        self.assertEqual(bootstrap["ordinal"], 1)
        self.assertTrue(session.accept_result(result_token, 1))
        self.assertTrue(session.accept_ready(result_token, 1))
        session.arm_next_document(1, 1.0)
        self.assertFalse(session.observe_top_level_root_navigation(
            result_token=result_token, session=session_token,
            fetch_destination="document", fetch_mode="no-cors"))
        self.assertTrue(session.observe_top_level_root_navigation(
            result_token=result_token, session=session_token,
            fetch_destination="document", fetch_mode="navigate"))

    def test_gn_source_selection_requires_exact_literal_isolated_pair(self) -> None:
        valid = (
            runner.PRODUCT_GN_ENABLE_ARGUMENT
            + "\n"
            + runner.PRODUCT_GN_FAILURE_ENABLE_ARGUMENT
            + "\n"
        ).encode("utf-8")
        runner.validate_m7_output_configuration(valid)
        cases = (
            (b"", "lacks exactly one"),
            (valid + runner.PRODUCT_GN_FAILURE_ENABLE_ARGUMENT.encode("utf-8"), "lacks exactly one"),
            (runner.PRODUCT_GN_ENABLE_ARGUMENT.encode("utf-8") + b"\n"
             b"enable_chromium_wasm_m7_profile_preferences_important_file_writer_proxy_completion_test=$flag\n",
             "not a literal"),
            (valid + b"enable_chromium_wasm_m7_profile_database_test=true\n", "incompatible"),
        )
        for args_gn, fragment in cases:
            with self.subTest(args_gn=args_gn):
                with self.assertRaisesRegex(M0Error, fragment):
                    runner.validate_m7_output_configuration(args_gn)

    def test_harness_uses_only_cdp_reloads_and_no_host_storage_api(self) -> None:
        runner_source = source(
            "tools/wasm/run_m7_chrome_profile_preferences_important_file_writer_proxy_completion_dom_smoke.py"
        )
        host = source(
            "tools/wasm/host/chrome_wasm_profile_preferences_important_file_writer_proxy_completion_smoke.js"
        )
        self.assertEqual(runner_source.count('client.call("Page.reload"'), 1)
        self.assertEqual(runner_source.count("reload_count += 1"), 3)
        self.assertIn("RESULT_RECEIPT_GRACE_SECONDS = 5.0", runner_source)
        self.assertIn(
            "deadline = time.monotonic() + args.timeout + RESULT_RECEIPT_GRACE_SECONDS",
            runner_source,
        )
        self.assertIn("timeout_seconds=args.timeout", runner_source)
        for token in (
            "Sec-Fetch-Dest", "Sec-Fetch-Mode", "IMPORTANT_FILE_WRITER_EIO_MARKER",
            "FAILURE_RETIREMENT_MARKER", "validate_four_document_transition",
        ):
            with self.subTest(token=token):
                self.assertIn(token, runner_source)
        for token in (
            "--wasm-profile-preferences-important-file-writer-proxy-completion",
            "IMPORTANT_FILE_WRITER_REPLACE_EIO_POST_FLUSH_UNPUBLISHED",
            "LEASE_REACQUIRED", "exactNonzeroExitStatus", "reportProcessExit",
        ):
            with self.subTest(token=token):
                self.assertIn(token, host)
        for forbidden in (
            "navigator.storage.getDirectory", "navigator.locks", "indexedDB.",
            "sessionStorage.", "localStorage.", "document.cookie", "window.name",
            "location.reload(", "location.assign(", "location.replace(", "ccall(", "HEAPU8",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, host)


if __name__ == "__main__":
    unittest.main()
