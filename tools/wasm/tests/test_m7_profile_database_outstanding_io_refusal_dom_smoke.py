#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the M7 outstanding-profile-I/O refusal DOM smoke."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import sys
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m7_chrome_profile_database_outstanding_io_refusal_dom_smoke as runner
from tools.wasm.tests.m3_source_contract_test_support import source


def _byte_identity() -> dict[str, object]:
    return {"bytes": 1, "sha256": "a" * 64}


def _artifact_identity() -> dict[str, object]:
    return {
        "artifact_delivery": runner._delivery.ARTIFACT_DELIVERY,
        "artifact_source_provenance": runner._delivery.ARTIFACT_SOURCE_PROVENANCE,
        "build_config": _byte_identity(),
        "build_config_provenance": runner._delivery.BUILD_CONFIG_PROVENANCE,
        "loader": _byte_identity(),
        "module_name": runner.PRODUCT_MODULE_NAME,
        "wasm": _byte_identity(),
    }


def _capture_harness_identity() -> dict[str, object]:
    return {
        "host_html": _byte_identity(),
        "host_js": _byte_identity(),
        "runner_source": _byte_identity(),
        "source_snapshot_provenance": runner._delivery.SOURCE_SNAPSHOT_PROVENANCE,
        "version_provenance": runner._delivery.VERSION_PROVENANCE,
    }


def _versions() -> dict[str, str]:
    return {"chromium": "1" * 40, "v8": "2" * 40, "emscripten": "3" * 40}


def _escrow():
    token_b = "b" * 64
    return runner._delivery.TokenEscrow(
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
        "buildConfigSnapshotValidated": True,
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
        "outstandingProfileIORefusalObserved": True,
        "firstRefusalPrecededOuterBackendTransaction": True,
        "failClosedCleanupAfterRefusalObserved": True,
        "safeFailClosedRuntimeExitObserved": True,
        "normalProfilePersistenceProven": False,
        "databaseDurabilityProven": False,
        "physicalCrashBehaviorProven": False,
        "fullStoragePartitionPersistenceProven": False,
        "hostBoundary": {
            "hostOpfsAccessAttempted": False,
            "hostWebLocksAccessAttempted": False,
            "nativeCallAttempted": False,
            "wasmDataInspectionAttempted": False,
        },
        "run": {
            "abortObserved": False,
            "databaseFailureMarkerObserved": True,
            "drainRefusalMarkerCount": 1,
            "drainRefusalMarkerObserved": True,
            "eventCount": len(runner.EXPECTED_EVENT_SEQUENCE),
            "eventSequence": list(runner.EXPECTED_EVENT_SEQUENCE),
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
            "outputLineCount": len(runner.EXPECTED_EVENT_SEQUENCE),
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


class M7ProfileDatabaseOutstandingIORefusalDomSmokeTest(unittest.TestCase):
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

    def test_validate_result_accepts_only_the_fixed_two_phase_lifecycle(self) -> None:
        self._validate(_passing_result())

    def test_validate_result_requires_browser_build_config_validation(self) -> None:
        result = copy.deepcopy(_passing_result())
        result["buildConfigSnapshotValidated"] = False
        with self.assertRaisesRegex(M0Error, "buildConfigSnapshotValidated"):
            self._validate(result)

    def test_validate_result_requires_fail_closed_cleanup_and_safe_exit(self) -> None:
        cases: tuple[tuple[str, str, object, str], ...] = (
            ("missing-retirement", "retirementMarkerObserved", False, "run receipt"),
            ("duplicate-retirement", "retirementMarkerCount", 2, "run receipt"),
            ("lease-release", "leaseReleasedMarkerObserved", True, "run receipt"),
            ("zero-exit", "processExitCode", 0, "run receipt"),
            ("abort", "abortObserved", True, "run receipt"),
            ("duplicate-exit", "onExitCount", 2, "run receipt"),
            ("missing-refusal", "drainRefusalMarkerCount", 0, "run receipt"),
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

    def test_validate_result_requires_database_then_refusal_then_cleanup_order(self) -> None:
        result = copy.deepcopy(_passing_result())
        run = result["run"]
        self.assertIsInstance(run, dict)
        run["eventSequence"] = [
            runner.EXPECTED_DATABASE_MARKERS[0],
            runner.EXPECTED_DATABASE_MARKERS[1],
            runner.DRAIN_REFUSAL_MARKER,
            runner.FAILURE_RETIREMENT_MARKER,
        ]
        run["eventCount"] = len(run["eventSequence"])
        with self.assertRaisesRegex(M0Error, "run receipt"):
            self._validate(result)

    def test_output_configuration_selects_only_the_dedicated_refusal_artifact(self) -> None:
        runner.validate_m7_output_configuration(
            (
                runner.PARENT_PRODUCT_GN_ENABLE_ARGUMENT
                + "\n"
                + runner.PRODUCT_GN_ENABLE_ARGUMENT
                + "\n"
            ).encode("utf-8")
        )
        self.assertEqual(
            runner.DEFAULT_OUT_DIR,
            Path("out/wasm-chrome-m7-profile-database-outstanding-io-refusal"),
        )
        for args_gn, fragment in (
            (b"", "lacks the database test opt-in"),
            (
                (runner.PARENT_PRODUCT_GN_ENABLE_ARGUMENT + "\n").encode("utf-8"),
                "lacks its dedicated opt-in",
            ),
            (
                (
                    runner.PARENT_PRODUCT_GN_ENABLE_ARGUMENT
                    + "\n"
                    + "enable_chromium_wasm_m7_profile_database_outstanding_io_refusal_test=false\n"
                ).encode("utf-8"),
                "lacks its dedicated opt-in",
            ),
            (
                (
                    runner.PARENT_PRODUCT_GN_ENABLE_ARGUMENT
                    + "\n"
                    + runner.PRODUCT_GN_ENABLE_ARGUMENT
                    + "\nenable_chromium_wasm_m7_profile_database_recovery_test=true\n"
                ).encode("utf-8"),
                "incompatible diagnostic",
            ),
        ):
            with self.subTest(args_gn=args_gn):
                with self.assertRaisesRegex(M0Error, fragment):
                    runner.validate_m7_output_configuration(args_gn)

    def test_browser_context_carries_the_exact_immutable_args_snapshot(self) -> None:
        args_gn = (
            runner.PARENT_PRODUCT_GN_ENABLE_ARGUMENT
            + "\n"
            + runner.PRODUCT_GN_ENABLE_ARGUMENT
            + "\n"
        ).encode("utf-8")
        encoded = runner._encode_build_config_for_host(args_gn)
        self.assertTrue(encoded)
        self.assertNotIn("=", encoded)
        self.assertLessEqual(len(encoded), runner.MAX_BUILD_CONFIG_BYTES * 2)

        server = type("Server", (), {"args_gn": args_gn})()
        with mock.patch.object(
            runner._delivery,
            "smoke_url",
            return_value="http://127.0.0.1:1/test/?existing=value",
        ):
            url = runner.smoke_url(
                server,
                "result-capability-token-abcdefghijklmnop",
                "session-capability-token-abcdefghijklmnop",
                _versions(),
                artifact=_artifact_identity(),
                capture_harness=_capture_harness_identity(),
                timeout_seconds=120,
            )
        self.assertEqual(
            parse_qs(urlsplit(url).query, strict_parsing=True)["buildConfig"],
            [encoded],
        )

    def test_create_server_validates_the_served_args_snapshot(self) -> None:
        class FakeServer:
            def __init__(self, args_gn: bytes) -> None:
                self.args_gn = args_gn
                self.closed = False

            def server_close(self) -> None:
                self.closed = True

        valid_server = FakeServer(
            (
                runner.PARENT_PRODUCT_GN_ENABLE_ARGUMENT
                + "\n"
                + runner.PRODUCT_GN_ENABLE_ARGUMENT
                + "\n"
            ).encode("utf-8")
        )
        with mock.patch.object(
            runner._delivery, "create_server", return_value=valid_server
        ) as create_server:
            self.assertIs(
                runner.create_server(
                    "127.0.0.1", 0, Path("out/test"), "result", "session", object()
                ),
                valid_server,
            )
        self.assertFalse(valid_server.closed)
        self.assertEqual(create_server.call_count, 1)

        invalid_server = FakeServer(
            (runner.PARENT_PRODUCT_GN_ENABLE_ARGUMENT + "\n").encode("utf-8")
        )
        with mock.patch.object(
            runner._delivery, "create_server", return_value=invalid_server
        ):
            with self.assertRaisesRegex(M0Error, "dedicated opt-in"):
                runner.create_server(
                    "127.0.0.1", 0, Path("out/test"), "result", "session", object()
                )
        self.assertTrue(invalid_server.closed)

    def test_host_is_a_redacted_verify_b_refusal_probe_without_storage_access(self) -> None:
        host = source(
            "tools/wasm/host/"
            "chrome_wasm_profile_database_outstanding_io_refusal_smoke.js"
        )
        for token in (
            '"--wasm-profile-database-smoke=verify-b"',
            "--wasm-profile-database-token-b=${this.#rawToken}",
            "FAIL stage=database",
            "DRAIN_REFUSAL_MARKER",
            '"buildConfig"',
            "parseBuildConfig",
            "hasEnabledGnAssignment",
            "PARENT_PRODUCT_GN_ENABLE_ASSIGNMENT",
            "PRODUCT_GN_ENABLE_ASSIGNMENT",
            "#validateBuildConfig",
            "buildConfigSnapshotValidated",
            "FAILURE_RETIREMENT_MARKER_PREFIX",
            "FAILURE_RETIREMENT_MARKER",
            "line.startsWith(FAILURE_RETIREMENT_MARKER_PREFIX)",
            "#expectedTwoPhaseLifecycleReady()",
            "firstRefusalPrecededOuterBackendTransaction",
            "failClosedCleanupAfterRefusalObserved",
            "safeFailClosedRuntimeExitObserved",
            "exactNonzeroExitStatus",
            "finalQuiescence",
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
