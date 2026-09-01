#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the M7 fail-closed database-retirement DOM smoke."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import sys
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m7_chrome_profile_database_fail_closed_retirement_dom_smoke as runner
from tools.wasm.tests.m3_source_contract_test_support import source


def _byte_identity() -> dict[str, object]:
    return {"bytes": 1, "sha256": "a" * 64}


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


def _escrow() -> runner.TokenEscrow:
    token_b = "b" * 64
    return runner.TokenEscrow(
        token_b=token_b,
        token_b_digest=hashlib.sha256(token_b.encode("ascii")).hexdigest(),
    )


def _passing_result() -> dict[str, object]:
    return {
        "protocol": 1,
        "case": runner.CASE,
        "scope": runner.SCOPE,
        "status": "pass",
        "m7GateComplete": False,
        "origin": "http://127.0.0.1:12345",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "artifact": _artifact_identity(),
        "capture_harness": _capture_harness_identity(),
        "versions": _versions(),
        "tokenEvidence": {
            "algorithm": "SHA-256",
            "tokenB": _escrow().token_b_digest,
            "rawTokensExcluded": True,
            "rawTokenLeakDetected": False,
            "rawTokenRedactionCount": 0,
        },
        "fixedDatabaseFailureObserved": True,
        "sealedLeaseRetainedReceiptObserved": True,
        "cleanNonzeroProcessExitObserved": True,
        "normalProfilePersistenceProven": False,
        "hostBoundary": {
            "hostOpfsAccessAttempted": False,
            "hostWebLocksAccessAttempted": False,
            "nativeCallAttempted": False,
            "wasmDataInspectionAttempted": False,
        },
        "run": {
            "abortObserved": False,
            "databaseFailureMarkerObserved": True,
            "factoryRejectedExpectedExitStatus": False,
            "factoryRejectedUnexpected": False,
            "factoryResolved": True,
            "factorySettled": True,
            "leaseReleasedMarkerObserved": False,
            "markerCount": len(runner.EXPECTED_DATABASE_MARKERS),
            "markerSequenceAccepted": True,
            "markerSource": "stderr-only-fixed-grammar",
            "markers": list(runner.EXPECTED_DATABASE_MARKERS),
            "mode": "verify-b",
            "moduleIdentity": "c" * 32,
            "onExitCount": 1,
            "outputLineCount": 6,
            "phaseCount": len(runner.EXPECTED_DATABASE_PHASES),
            "phases": list(runner.EXPECTED_DATABASE_PHASES),
            "processExitCode": 17,
            "processExitCount": 1,
            "retirementMarkerCount": 1,
            "retirementMarkerObserved": True,
            "runtimeExitCode": 17,
            "runtimeInitialized": True,
            "stdoutMarkerCount": 0,
        },
        "bridge": {
            "protocol": 1,
            "permanent": True,
            "frozen": True,
            "installedBeforeModuleFactory": True,
            "processExitDispatches": 1,
        },
        "finalQuiescence": {
            "callbacksAtEnd": 12,
            "callbacksAtPreUploadCheck": 12,
            "callbacksAtStart": 12,
            "completed": True,
            "quiet": True,
            "quietWindowMs": runner.FINAL_QUIESCENCE_MS,
            "started": True,
        },
        "fatalCallbackCount": 0,
        "windowErrorCount": 0,
        "unhandledRejectionCount": 0,
        "error": None,
    }


class M7ProfileDatabaseFailClosedRetirementDomSmokeTest(unittest.TestCase):
    def _validate(self, result: dict[str, object]) -> None:
        runner.validate_result(
            result,
            expected_versions=_versions(),
            expected_artifact_identity=_artifact_identity(),
            expected_capture_harness_identity=_capture_harness_identity(),
            expected_origin="http://127.0.0.1:12345",
            escrow=_escrow(),
            result_token="result-capability-token-abcdefghijklmnop",
            session="session-capability-token-abcdefghijklmnop",
        )

    def test_validate_result_accepts_only_clean_nonzero_failure_retirement(self) -> None:
        self._validate(_passing_result())

    def test_validate_result_rejects_lease_release_abort_or_nonterminal_failure(self) -> None:
        cases: tuple[tuple[str, str, object, str], ...] = (
            ("lease-marker", "leaseReleasedMarkerObserved", True, "run receipt"),
            ("abort", "abortObserved", True, "run receipt"),
            ("zero-exit", "processExitCode", 0, "run receipt"),
            ("duplicate-on-exit", "onExitCount", 2, "run receipt"),
            ("missing-retirement", "retirementMarkerCount", 0, "run receipt"),
            ("not-quiet", "finalQuiescence.quiet", False, "callbacks were not quiet"),
        )
        for name, field, value, fragment in cases:
            with self.subTest(name=name):
                result = copy.deepcopy(_passing_result())
                if "." in field:
                    parent, child = field.split(".", 1)
                    nested = result[parent]
                    self.assertIsInstance(nested, dict)
                    nested[child] = value
                else:
                    run = result["run"]
                    self.assertIsInstance(run, dict)
                    run[field] = value
                with self.assertRaisesRegex(M0Error, fragment):
                    self._validate(result)

    def test_validate_result_rejects_wrong_fixed_database_or_retirement_receipt(self) -> None:
        for field, value in (
            ("markers", [runner.EXPECTED_DATABASE_MARKERS[0]]),
            ("phases", ["task-post", "task-started"]),
            ("databaseFailureMarkerObserved", False),
            ("retirementMarkerObserved", False),
        ):
            with self.subTest(field=field):
                result = copy.deepcopy(_passing_result())
                run = result["run"]
                self.assertIsInstance(run, dict)
                run[field] = value
                with self.assertRaisesRegex(M0Error, "run receipt"):
                    self._validate(result)

    def test_output_configuration_selects_only_the_ordinary_database_artifact(self) -> None:
        runner.validate_m7_output_configuration(
            (runner.PRODUCT_GN_ENABLE_ARGUMENT + "\n").encode("utf-8")
        )
        for args_gn, fragment in (
            (b"", "lacks the database test opt-in"),
            (
                b"enable_chromium_wasm_m7_profile_database_test=false\n",
                "lacks the database test opt-in",
            ),
            (
                (
                    runner.PRODUCT_GN_ENABLE_ARGUMENT
                    + "\nenable_chromium_wasm_m7_profile_database_recovery_test=true\n"
                ).encode("utf-8"),
                "incompatible diagnostic",
            ),
            (
                (
                    runner.PRODUCT_GN_ENABLE_ARGUMENT
                    + "\nenable_chromium_wasm_m7_profile_database_sqlite_recovery_test=true\n"
                ).encode("utf-8"),
                "incompatible diagnostic",
            ),
        ):
            with self.subTest(args_gn=args_gn):
                with self.assertRaisesRegex(M0Error, fragment):
                    runner.validate_m7_output_configuration(args_gn)

    def test_host_is_one_fresh_verify_b_failure_probe_with_no_host_storage_access(self) -> None:
        host = source(
            "tools/wasm/host/"
            "chrome_wasm_profile_database_fail_closed_retirement_smoke.js"
        )
        for token in (
            '"--wasm-profile-database-smoke=verify-b"',
            "--wasm-profile-database-token-b=${this.#rawToken}",
            "FAIL stage=database",
            "FAILURE_RETIREMENT_MARKER",
            "#startFinalQuiescence()",
            "exactNonzeroExitStatus",
            "leaseReleasedMarkerObserved: false",
        ):
            with self.subTest(token=token):
                self.assertIn(token, host)
        for forbidden in (
            "navigator.storage.getDirectory",
            "navigator.locks",
            "ccall(",
            "HEAPU8",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, host)


if __name__ == "__main__":
    unittest.main()
