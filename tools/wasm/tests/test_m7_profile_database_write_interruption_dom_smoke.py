#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused runner contracts for the non-gating post-Sync observation."""

from __future__ import annotations

import copy
from collections import deque
from pathlib import Path
import secrets
import sys
import time
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m7_chrome_profile_database_write_interruption_dom_smoke as smoke


VERSIONS = {"chromium": "a" * 40, "v8": "b" * 40, "emscripten": "c" * 40}
ARTIFACT_IDENTITY = {
    "artifact_delivery": smoke.ARTIFACT_DELIVERY,
    "artifact_source_provenance": smoke.ARTIFACT_SOURCE_PROVENANCE,
    "build_config": {"bytes": 71, "sha256": "d" * 64},
    "build_config_provenance": smoke.BUILD_CONFIG_PROVENANCE,
    "loader": {"bytes": 72, "sha256": "e" * 64},
    "module_name": smoke.PRODUCT_MODULE_NAME,
    "wasm": {"bytes": 73, "sha256": "f" * 64},
}
CAPTURE_HARNESS_IDENTITY = {
    "host_html": {"bytes": 74, "sha256": "0" * 64},
    "host_js": {"bytes": 75, "sha256": "1" * 64},
    "runner_source": {"bytes": 76, "sha256": "2" * 64},
    "source_snapshot_provenance": smoke.SOURCE_SNAPSHOT_PROVENANCE,
    "version_provenance": smoke.VERSION_PROVENANCE,
}
ORIGIN = "http://127.0.0.1:43128"
RESULT_CAPABILITY = "r" * 128
SESSION_CAPABILITY = "s" * 128


def escrow_matches(value: object, expected: str) -> bool:
    """Avoid asking unittest to render a raw opaque value on failure."""

    return isinstance(value, str) and secrets.compare_digest(value, expected)


def document_for(ordinal: int) -> smoke.DocumentEvidence:
    return smoke.DocumentEvidence(
        "navigate" if ordinal == 1 else "reload", 1700000000000.0 + ordinal
    )


def host_boundary() -> dict[str, bool]:
    return {
        "hostOpfsAccessAttempted": False,
        "hostWebLocksAccessAttempted": False,
        "nativeCallAttempted": False,
        "wasmDataInspectionAttempted": False,
        "sessionStorageAccessAttempted": False,
        "localStorageAccessAttempted": False,
        "indexedDbAccessAttempted": False,
        "cookieAccessAttempted": False,
        "historyStateAccessAttempted": False,
        "windowNameAccessAttempted": False,
    }


def final_quiescence(ordinal: int) -> dict[str, object]:
    exit_count = 0 if ordinal == 2 else 1
    return {
        "activeRunAtEnd": ordinal,
        "activeRunAtStart": ordinal,
        "activeRunAtPreUploadCheck": None,
        "bridgeRecheckedImmediatelyBeforeUpload": True,
        "callbacksAtEnd": 11,
        "callbacksAtPreUploadCheck": 11,
        "callbacksAtStart": 11,
        "completed": True,
        "processExitReportsAtEnd": exit_count,
        "processExitReportsAtPreUploadCheck": exit_count,
        "processExitReportsAtStart": exit_count,
        "quiet": True,
        "quietWindowMs": smoke.FINAL_QUIESCENCE_MS,
        "started": True,
    }


def passing_run(ordinal: int, escrow: smoke.TokenEscrow) -> dict[str, object]:
    outcome = "b" if ordinal == 3 else None
    interrupted = ordinal == 2
    return {
        "abortCount": 1 if interrupted else 0,
        "abortObserved": interrupted,
        "cleanExitObserved": False if interrupted else True,
        "controlledAbortWindowErrorCount": 2 if interrupted else 0,
        "expectedCleanExitStatusObserved": False,
        "factoryRejected": False,
        "factoryResolved": True,
        "factorySettled": True,
        "markerCount": len(smoke.expected_markers(ordinal, escrow, outcome)),
        "markerSequenceAccepted": True,
        "markerSource": "stderr-only-fixed-grammar",
        "markers": smoke.expected_markers(ordinal, escrow, outcome),
        "mode": smoke._phase_mode(ordinal),
        "moduleIdentity": str(ordinal) * 32,
        "onExitCount": 0 if interrupted else 1,
        "ordinal": ordinal,
        "phaseCount": 1 if interrupted else 0,
        "phaseObserved": interrupted,
        "processExitCode": None if interrupted else 0,
        "processExitCount": 0 if interrupted else 1,
        "postSyncObservation": outcome,
        "runtimeExitCode": None if interrupted else 0,
        "runtimeInitialized": True,
        "settleComplete": True,
        "settleWindowMs": (
            smoke.INTERRUPTION_SETTLE_MS + smoke.FINAL_QUIESCENCE_MS
            if interrupted
            else smoke.CLEAN_SETTLE_MS + smoke.FINAL_QUIESCENCE_MS
        ),
        "stdoutMarkerCount": 0,
    }


def passing_result(
    ordinal: int, escrow: smoke.TokenEscrow, time_origin: float
) -> dict[str, object]:
    return {
        "protocol": 1,
        "case": smoke.CASE,
        "scope": smoke.SCOPE,
        "status": smoke._phase_status(ordinal),
        "m7GateComplete": False,
        "ordinal": ordinal,
        "mode": smoke._phase_mode(ordinal),
        "origin": ORIGIN,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "document": {
            "navigationType": "navigate" if ordinal == 1 else "reload",
            "timeOrigin": time_origin,
        },
        "artifact": copy.deepcopy(ARTIFACT_IDENTITY),
        "capture_harness": copy.deepcopy(CAPTURE_HARNESS_IDENTITY),
        "versions": copy.deepcopy(VERSIONS),
        "tokenEvidence": {
            "algorithm": "SHA-256",
            "tokenA": escrow.token_a_digest,
            "tokenB": None if ordinal == 1 else escrow.token_b_digest,
            "distinct": None if ordinal == 1 else True,
            "rawTokensExcluded": True,
            "rawTokenLeakDetected": False,
            "rawTokenRedactionCount": 0,
        },
        "run": passing_run(ordinal, escrow),
        "bridge": {
            "protocol": 1,
            "permanent": True,
            "frozen": True,
            "installedBeforeModuleFactory": True,
            "processExitDispatches": 0 if ordinal == 2 else 1,
            "activeRunAtResult": None,
        },
        "finalQuiescence": final_quiescence(ordinal),
        "hostBoundary": host_boundary(),
        "fatalErrors": [],
        "windowErrors": [],
        "unhandledRejections": [],
        "failedChecks": [],
        "error": None,
    }


def validate_result(
    result: dict[str, object],
    escrow: smoke.TokenEscrow,
    ordinal: int,
) -> smoke.PhaseResult:
    return smoke.validate_phase_result(
        result,
        ordinal=ordinal,
        expected_versions=VERSIONS,
        expected_artifact_identity=ARTIFACT_IDENTITY,
        expected_capture_harness_identity=CAPTURE_HARNESS_IDENTITY,
        expected_origin=ORIGIN,
        expected_document=document_for(ordinal),
        escrow=escrow,
        result_token=RESULT_CAPABILITY,
        session=SESSION_CAPABILITY,
    )


def ready_receipt(ordinal: int) -> dict[str, object]:
    return {
        "protocol": 1,
        "case": smoke.CASE,
        "scope": smoke.SCOPE,
        "ordinal": ordinal,
        "timeOrigin": document_for(ordinal).time_origin,
    }


class FakeReloadClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object] | None]] = []
        self.events: list[dict[str, object]] = [
            {
                "method": "Page.frameNavigated",
                "params": {
                    "frame": {
                        "id": "root-frame",
                        "loaderId": "loader-one",
                        "url": f"{ORIGIN}{smoke.HOST_ROOT}/",
                    }
                },
            },
            {
                "method": "Page.frameNavigated",
                "params": {
                    "frame": {
                        "id": "root-frame",
                        "loaderId": "loader-two",
                        "url": f"{ORIGIN}{smoke.HOST_ROOT}/?opaque-query",
                    }
                },
            },
        ]

    def call(self, method: str, params: dict[str, object] | None = None) -> object:
        self.calls.append((method, params))
        if method == "Page.getFrameTree":
            return {
                "frameTree": {
                    "frame": {
                        "id": "root-frame",
                        "loaderId": "loader-one",
                        "url": f"{ORIGIN}{smoke.HOST_ROOT}/",
                    }
                }
            }
        if method == "Page.enable" or method == "Page.reload":
            return {}
        raise AssertionError("unexpected CDP call")

    def next_event(self, _timeout: float) -> dict[str, object] | None:
        return self.events.pop(0) if self.events else None


class FakeBrowser:
    def poll(self) -> None:
        return None


class M7ProfileDatabaseWriteInterruptionDomSmokeTest(unittest.TestCase):
    def test_validates_three_non_gating_phase_receipts(self) -> None:
        escrow = smoke.new_token_escrow()
        first = validate_result(passing_result(1, escrow, document_for(1).time_origin), escrow, 1)
        second = validate_result(passing_result(2, escrow, document_for(2).time_origin), escrow, 2)
        third = validate_result(passing_result(3, escrow, document_for(3).time_origin), escrow, 3)
        for phase in (first, second, third):
            smoke.validate_ready_receipt(ready_receipt(phase.ordinal), expected=phase)
        smoke.validate_three_document_transition(first, second, third)
        self.assertEqual(third.post_sync_observation, "b")

    def test_rejects_gate_claims_raw_values_and_terminal_interruption(self) -> None:
        escrow = smoke.new_token_escrow()
        result = passing_result(2, escrow, document_for(2).time_origin)
        result["m7GateComplete"] = True
        with self.assertRaises(M0Error):
            validate_result(result, escrow, 2)
        raw = passing_result(1, escrow, document_for(1).time_origin)
        raw["error"] = escrow.token_a
        with self.assertRaises(M0Error):
            validate_result(raw, escrow, 1)
        terminal = passing_result(2, escrow, document_for(2).time_origin)
        run = terminal["run"]
        assert isinstance(run, dict)
        run["onExitCount"] = 1
        with self.assertRaises(M0Error):
            validate_result(terminal, escrow, 2)
        for field, value in (
            ("factoryResolved", False),
            ("factoryRejected", True),
            ("factorySettled", False),
            ("controlledAbortWindowErrorCount", 1),
        ):
            with self.subTest(field=field):
                invalid_factory = passing_result(
                    2, escrow, document_for(2).time_origin
                )
                invalid_run = invalid_factory["run"]
                assert isinstance(invalid_run, dict)
                invalid_run[field] = value
                with self.assertRaises(M0Error):
                    validate_result(invalid_factory, escrow, 2)

    def test_server_rejects_replay_out_of_order_and_raw_receipts(self) -> None:
        escrow = smoke.new_token_escrow()
        session = smoke.WriteInterruptionSession(
            RESULT_CAPABILITY, SESSION_CAPABILITY, escrow
        )
        with self.assertRaises(smoke.ProtocolStateError):
            session.bootstrap_payload(SESSION_CAPABILITY)
        with self.assertRaises(smoke.ProtocolStateError):
            session.accept_result(RESULT_CAPABILITY, 2)
        self.assertTrue(
            session.accept_bootstrap_document(SESSION_CAPABILITY, document_for(1))
        )
        self.assertTrue(session.acknowledge_bootstrap_document(SESSION_CAPABILITY))
        first_bootstrap = session.bootstrap_payload(SESSION_CAPABILITY)
        assert first_bootstrap is not None
        self.assertTrue(escrow_matches(first_bootstrap.get("tokenA"), escrow.token_a))
        self.assertIsNone(first_bootstrap.get("tokenB"))
        with self.assertRaises(smoke.ProtocolStateError):
            session.bootstrap_payload(SESSION_CAPABILITY)
        with self.assertRaises(smoke.ProtocolStateError):
            session.accept_bootstrap_document(SESSION_CAPABILITY, document_for(1))
        self.assertTrue(session.accept_result(RESULT_CAPABILITY, 1))
        self.assertTrue(session.accept_ready(RESULT_CAPABILITY, 1))
        session.arm_next_document(1, document_for(1).time_origin)
        self.assertFalse(
            session.observe_top_level_root_navigation(
                result_token=RESULT_CAPABILITY,
                session=SESSION_CAPABILITY,
                fetch_destination="iframe",
                fetch_mode="navigate",
            )
        )
        with self.assertRaises(smoke.ProtocolStateError):
            session.accept_bootstrap_document(SESSION_CAPABILITY, document_for(2))
        self.assertTrue(
            session.observe_top_level_root_navigation(
                result_token=RESULT_CAPABILITY,
                session=SESSION_CAPABILITY,
                fetch_destination="document",
                fetch_mode="navigate",
            )
        )
        self.assertTrue(
            session.accept_bootstrap_document(SESSION_CAPABILITY, document_for(2))
        )
        self.assertTrue(session.acknowledge_bootstrap_document(SESSION_CAPABILITY))
        second_bootstrap = session.bootstrap_payload(SESSION_CAPABILITY)
        assert second_bootstrap is not None
        self.assertTrue(escrow_matches(second_bootstrap.get("tokenB"), escrow.token_b))
        self.assertTrue(session.accept_result(RESULT_CAPABILITY, 2))
        self.assertTrue(session.accept_ready(RESULT_CAPABILITY, 2))
        session.arm_next_document(2, document_for(2).time_origin)
        self.assertTrue(
            session.observe_top_level_root_navigation(
                result_token=RESULT_CAPABILITY,
                session=SESSION_CAPABILITY,
                fetch_destination="document",
                fetch_mode="navigate",
            )
        )
        self.assertTrue(
            session.accept_bootstrap_document(SESSION_CAPABILITY, document_for(3))
        )
        self.assertTrue(session.acknowledge_bootstrap_document(SESSION_CAPABILITY))
        third_bootstrap = session.bootstrap_payload(SESSION_CAPABILITY)
        assert third_bootstrap is not None
        self.assertTrue(escrow_matches(third_bootstrap.get("tokenB"), escrow.token_b))
        self.assertTrue(
            smoke._contains_prohibited_strings(
                {"nested": [escrow.token_a]}, (escrow.token_a, escrow.token_b)
            )
        )
        runner_source = Path(smoke.__file__).read_text(encoding="utf-8")
        for token in (
            "Sec-Fetch-Dest",
            "Sec-Fetch-Mode",
            "_contains_prohibited_strings(",
            "_reject_duplicate_object_keys",
            "bootstrap acknowledgement",
        ):
            with self.subTest(token=token):
                self.assertIn(token, runner_source)

    def test_reload_requires_page_reload_and_changed_loader(self) -> None:
        client = FakeReloadClient()
        baseline = smoke.prepare_outer_document_reload(client)
        reloaded = smoke.reload_outer_document(
            client,
            FakeBrowser(),
            deque(),
            baseline,
            f"{ORIGIN}{smoke.HOST_ROOT}/",
            time.monotonic() + 1,
        )
        self.assertEqual(reloaded.frame_id, "root-frame")
        self.assertEqual(reloaded.loader_id, "loader-two")
        self.assertEqual(
            client.calls,
            [
                ("Page.enable", None),
                ("Page.getFrameTree", None),
                ("Page.reload", {"ignoreCache": True}),
            ],
        )

    def test_non_gating_summary_false_claims_and_nonzero_return_contract(self) -> None:
        summary = smoke._observation_summary("b")
        self.assertEqual(summary["m7GateComplete"], False)
        for field in (
            "outerReloadProven",
            "persistenceProven",
            "profilePersistenceProven",
            "durabilityProven",
            "directoryDurabilityProven",
            "leaseReleaseProven",
            "crashBehaviorProven",
        ):
            with self.subTest(field=field):
                self.assertEqual(summary[field], False)
        runner_source = Path(smoke.__file__).read_text(encoding="utf-8")
        main_body = runner_source[runner_source.index("def main() -> int:") :]
        self.assertIn('":OBSERVED "', main_body)
        self.assertIn("return 1", main_body)
        self.assertNotIn(":PASS", main_body)

    def test_default_configuration_has_direct_database_opt_in(self) -> None:
        self.assertIn(
            "enable_chromium_wasm_m7_profile_database_test=true",
            smoke.DEFAULT_GN_ARGUMENTS,
        )
        smoke.validate_m7_output_configuration(
            (
                "enable_chromium_wasm_m7_profile_database_test=true\n"
                "enable_chromium_wasm_m7_profile_database_write_interruption_diagnostic=true\n"
            ).encode("utf-8")
        )


if __name__ == "__main__":
    unittest.main()
