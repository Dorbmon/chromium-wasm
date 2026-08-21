#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the M7 two-fresh-Module Chrome Preferences acceptance."""

from __future__ import annotations

import copy
from collections import deque
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import http.client
import io
import json
from pathlib import Path
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m7_chrome_profile_persistence_dom_smoke as smoke
from tools.wasm.tests.m3_source_contract_test_support import source


VERSIONS = {
    "chromium": "a" * 40,
    "v8": "b" * 40,
    "emscripten": "c" * 40,
}
ARTIFACT_IDENTITY = {
    "artifact_delivery": smoke.ARTIFACT_DELIVERY,
    "artifact_source_provenance": smoke.ARTIFACT_SOURCE_PROVENANCE,
    "build_config": {"bytes": 81, "sha256": "9" * 64},
    "build_config_provenance": smoke.BUILD_CONFIG_PROVENANCE,
    "loader": {"bytes": 10, "sha256": "d" * 64},
    "module_name": smoke.PRODUCT_MODULE_NAME,
    "wasm": {"bytes": 20, "sha256": "e" * 64},
}
CAPTURE_HARNESS_IDENTITY = {
    "host_html": {"bytes": 11, "sha256": "f" * 64},
    "host_js": {"bytes": 12, "sha256": "0" * 64},
    "runner_source": {"bytes": 13, "sha256": "1" * 64},
    "source_snapshot_provenance": smoke.SOURCE_SNAPSHOT_PROVENANCE,
    "version_provenance": smoke.VERSION_PROVENANCE,
}
ORIGIN = "http://127.0.0.1:43127"
TOKEN_A_DIGEST = "2" * 64
TOKEN_B_DIGEST = "3" * 64


class _CleanupFailureServer:
    server_address = ("127.0.0.1", 43127)

    def serve_forever(self) -> None:
        return

    def shutdown(self) -> None:
        return

    def server_close(self) -> None:
        return


class _CleanupFailureBrowser:
    def __init__(self) -> None:
        self.stderr = io.StringIO("")

    def poll(self) -> int:
        return 0


def expected_markers(ordinal: int) -> list[str]:
    return smoke.expected_markers(
        ordinal, {"runOne": TOKEN_A_DIGEST, "runTwo": TOKEN_B_DIGEST}
    )


def passing_run(ordinal: int) -> dict[str, object]:
    markers = expected_markers(ordinal)
    return {
        "abort": None,
        "activeClearedAfterLifecycle": True,
        "expectedExitStatusObserved": True,
        "factoryError": None,
        "factorySettled": True,
        "freshModuleObject": True,
        "leaseReleasedMarkerObserved": True,
        "markerCount": len(markers),
        "markerSequenceAccepted": True,
        "markerSource": "stderr-only",
        "markers": markers,
        "mode": "write" if ordinal == 1 else "verify-and-write",
        "moduleIdentity": ("4" if ordinal == 1 else "5") * 32,
        "onExitCount": 1,
        "ordinal": ordinal,
        "postLifecycleTimerObserved": True,
        "markerDeliveryCompleteAtProcessExit": False,
        "processExitBeforeOnExit": True,
        "processExitCode": 0,
        "processExitCount": 1,
        "runtimeExitCode": 0,
        "runtimeInitialized": True,
        "sameModuleAsPrior": None if ordinal == 1 else False,
        "startKind": "initial" if ordinal == 1 else "setTimeout-0",
        "stderr": markers,
        "stdout": [],
    }


def passing_result() -> dict[str, object]:
    return {
        "protocol": 1,
        "case": smoke.CASE,
        "scope": smoke.SCOPE,
        "status": "pass",
        "m7GateComplete": False,
        "limitations": list(smoke.LIMITATIONS),
        "artifact": copy.deepcopy(ARTIFACT_IDENTITY),
        "capture_harness": copy.deepcopy(CAPTURE_HARNESS_IDENTITY),
        "versions": copy.deepcopy(VERSIONS),
        "origin": ORIGIN,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "sameOriginDocument": True,
        "preferencesRoundTripProven": True,
        "sqliteLevelDbRecoveryProven": False,
        "cookiesHistoryBookmarksSessionsProven": False,
        "webStorageAndServiceWorkerProven": False,
        "concurrentProfileContenderProven": False,
        "factoryCalls": 2,
        "bridge": {
            "protocol": 1,
            "permanent": True,
            "frozen": True,
            "installedBeforeModuleFactory": True,
            "processExitDispatches": 2,
            "noActiveProcessExitRejected": 0,
            "duplicateProcessExitRejected": 0,
            "lateProcessExitRejected": 0,
            "activeRunAtResult": None,
        },
        "transition": {
            "runTwoScheduledExactlyOnce": True,
            "runTwoScheduleMethod": "setTimeout(...,0)",
            "runTwoTimerFired": True,
            "runTwoScheduledAfterRunOneNativeExit": True,
            "runTwoScheduledAfterRunOneOnExit": True,
            "runTwoStartedAfterRunOneActiveClear": True,
        },
        "finalQuiescence": {
            "activeRunAtPreUploadCheck": None,
            "activeRunAtTaskEnd": None,
            "activeRunAtTaskStart": None,
            "bridgeRecheckedImmediatelyBeforeUpload": True,
            "callbacksAtPreUploadCheck": 17,
            "callbacksAtRunTwoActiveClear": 17,
            "callbacksAtTaskEnd": 17,
            "callbacksAtTaskStart": 17,
            "completed": True,
            "postLifecycleTimerObservedBeforeTask": True,
            "processExitDispatchesAtPreUploadCheck": 2,
            "processExitReportsAtPreUploadCheck": 2,
            "processExitReportsAtRunTwoActiveClear": 2,
            "processExitReportsAtTaskEnd": 2,
            "quiet": True,
            "quietWindowMs": smoke.FINAL_QUIESCENCE_MS,
            "rejectedProcessExitReportsAtPreUploadCheck": 0,
            "started": True,
            "startedAfterRunTwoActiveClear": True,
            "taskMethod": "setTimeout(...,0)",
            "taskScheduledExactlyOnce": True,
        },
        "tokenEvidence": {
            "algorithm": "SHA-256",
            "runOne": TOKEN_A_DIGEST,
            "runTwo": TOKEN_B_DIGEST,
            "distinct": True,
            "rawTokensExcluded": True,
            "rawTokenLeakDetected": False,
            "rawTokenRedactionCount": 0,
        },
        "hostBoundary": {
            "hostOpfsAccessAttempted": False,
            "hostWebLocksAccessAttempted": False,
            "nativeCallAttempted": False,
            "wasmDataInspectionAttempted": False,
        },
        "runs": [passing_run(1), passing_run(2)],
        "fatalErrors": [],
        "windowErrors": [],
        "unhandledRejections": [],
        "failedChecks": [],
        "error": None,
    }


def passing_failure_result(
    *,
    native_failure_stage: str | None = None,
    first_fatal_tag: str | None = "factory-rejected",
    abort_reason_kind: str | None = None,
    abort_observation_order: str | None = None,
) -> dict[str, object]:
    return {
        "protocol": 1,
        "case": smoke.CASE,
        "scope": smoke.SCOPE,
        "status": "fail",
        "failureClass": (
            "native-fixed-failure"
            if native_failure_stage is not None
            else "host-lifecycle"
        ),
        "firstFatalTag": (
            "marker-native-failure"
            if native_failure_stage is not None and first_fatal_tag == "factory-rejected"
            else first_fatal_tag
        ),
        "abortReasonKind": abort_reason_kind,
        "abortObservationOrder": abort_observation_order,
        "nativeFailureStage": native_failure_stage,
        "lifecycle": {
            "acceptedProcessExitCount": 1,
            "activeRunPresent": True,
            "bridgeInstalled": True,
            "bridgeInstalledBeforeModuleFactory": True,
            "callbackCount": 12,
            "factoryCalls": 1,
            "finalQuiescenceCompleted": False,
            "lastProcessExitCode": 1,
            "lastRuntimeExitCode": None,
            "leaseReleasedRunCount": 0,
            "onExitCount": 0,
            "processExitReportCount": 1,
            "rawTokenLeakDetected": False,
            "runCount": 1,
            "unhandledRejectionObserved": False,
            "windowErrorObserved": False,
        },
    }


def validate(result: dict[str, object]) -> None:
    smoke.validate_result(
        result,
        expected_versions=VERSIONS,
        expected_artifact_identity=ARTIFACT_IDENTITY,
        expected_capture_harness_identity=CAPTURE_HARNESS_IDENTITY,
        expected_origin=ORIGIN,
    )


class M7ProfilePreferencesTwoModuleDomSmokeTest(unittest.TestCase):
    def test_uses_only_the_dedicated_m7_profile_preferences_artifact(self) -> None:
        self.assertEqual(
            smoke.PRODUCT_MODULE_NAME, "chrome_wasm_m7_profile_preferences_test"
        )
        self.assertEqual(smoke.DEFAULT_MODULE_NAME, smoke.PRODUCT_MODULE_NAME)
        self.assertEqual(
            smoke.DEFAULT_OUT_DIR, Path("out/wasm-chrome-m7-profile-preferences")
        )
        self.assertEqual(smoke.PRODUCT_GN_TARGET, "//chrome:chrome_wasm")
        self.assertEqual(
            smoke.PRODUCT_GN_ENABLE_ARGUMENT,
            "enable_chromium_wasm_m7_profile_preferences_test=true",
        )
        self.assertEqual(
            smoke.DEFAULT_GN_ARGUMENTS,
            'import("//out/wasm-chrome-m6/args.gn") '
            "enable_chromium_wasm_m7_profile_preferences_test=true",
        )
        self.assertNotEqual(smoke.PRODUCT_MODULE_NAME, "chrome_wasm")
        with self.assertRaises(M0Error):
            smoke._require_product_module_name("chrome_wasm", "test")

    def test_accepts_two_fresh_module_preferences_evidence(self) -> None:
        validate(passing_result())

    def test_rejects_m7_complete_or_out_of_scope_claims(self) -> None:
        for field, value in (
            ("m7GateComplete", True),
            ("sqliteLevelDbRecoveryProven", True),
            ("cookiesHistoryBookmarksSessionsProven", True),
            ("webStorageAndServiceWorkerProven", True),
            ("concurrentProfileContenderProven", True),
        ):
            with self.subTest(field=field):
                result = passing_result()
                result[field] = value
                with self.assertRaises(M0Error):
                    validate(result)

    def test_rejects_missing_or_mismatched_snapshot_identities(self) -> None:
        for field, value in (
            ("versions", {**VERSIONS, "v8": "9" * 40}),
            ("artifact", {**ARTIFACT_IDENTITY, "module_name": "not_chrome"}),
            (
                "artifact",
                {
                    **ARTIFACT_IDENTITY,
                    "build_config": {"bytes": 81, "sha256": "8" * 64},
                },
            ),
            (
                "capture_harness",
                {**CAPTURE_HARNESS_IDENTITY, "host_js": {"bytes": 12, "sha256": "9" * 64}},
            ),
        ):
            with self.subTest(field=field):
                result = passing_result()
                result[field] = value
                with self.assertRaises(M0Error):
                    validate(result)

    def test_rejects_marker_reordering_duplication_and_failure(self) -> None:
        mutations = (
            lambda result: result["runs"][0]["markers"].reverse(),
            lambda result: result["runs"][1]["stderr"].append(
                f"{smoke.M7_MARKER_PREFIX}LEASE_RELEASED"
            ),
            lambda result: result["runs"][0]["stdout"].append(
                result["runs"][0]["markers"][0]
            ),
            lambda result: result["runs"][1]["stderr"].append(
                "prefix " + result["runs"][1]["markers"][0]
            ),
            lambda result: result["runs"][1]["stderr"].__setitem__(
                0, f"{smoke.M7_MARKER_PREFIX}FAIL stage=write"
            ),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                result = passing_result()
                mutation(result)
                with self.assertRaises(M0Error):
                    validate(result)

    def test_rejects_private_token_switch_or_redaction_witness(self) -> None:
        for mutation in (
            lambda result: result["runs"][0]["stderr"].append(
                "--wasm-profile-preferences-token-a=not-allowed"
            ),
            lambda result: result["runs"][1]["stdout"].append("<redacted>"),
            lambda result: result["tokenEvidence"].__setitem__(
                "rawTokenLeakDetected", True
            ),
            lambda result: result["tokenEvidence"].__setitem__(
                "rawTokenRedactionCount", 1
            ),
        ):
            with self.subTest(mutation=mutation):
                result = passing_result()
                mutation(result)
                with self.assertRaises(M0Error):
                    validate(result)

    def test_rejects_nonunique_digest_or_missing_sha_only_evidence(self) -> None:
        mutations = (
            lambda result: result["tokenEvidence"].__setitem__(
                "runTwo", TOKEN_A_DIGEST
            ),
            lambda result: result["tokenEvidence"].__setitem__("algorithm", "sha256"),
            lambda result: result["tokenEvidence"].__setitem__(
                "rawTokensExcluded", False
            ),
            lambda result: result["tokenEvidence"].__setitem__("raw", "not-allowed"),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                result = passing_result()
                mutation(result)
                with self.assertRaises(M0Error):
                    validate(result)

    def test_rejects_second_module_not_timer_gated_after_run_one_lifecycle(self) -> None:
        for field, value in (
            ("runTwoScheduledExactlyOnce", False),
            ("runTwoScheduleMethod", "promise"),
            ("runTwoTimerFired", False),
            ("runTwoScheduledAfterRunOneNativeExit", False),
            ("runTwoScheduledAfterRunOneOnExit", False),
            ("runTwoStartedAfterRunOneActiveClear", False),
        ):
            with self.subTest(field=field):
                result = passing_result()
                result["transition"][field] = value
                with self.assertRaises(M0Error):
                    validate(result)

    def test_rejects_final_quiescence_or_pre_upload_bridge_mutations(self) -> None:
        mutations = (
            lambda result: result["finalQuiescence"].__setitem__("quiet", False),
            lambda result: result["finalQuiescence"].__setitem__(
                "taskMethod", "promise"
            ),
            lambda result: result["finalQuiescence"].__setitem__(
                "callbacksAtPreUploadCheck", 18
            ),
            lambda result: result["finalQuiescence"].__setitem__(
                "processExitReportsAtTaskEnd", 3
            ),
            lambda result: result["finalQuiescence"].__setitem__(
                "bridgeRecheckedImmediatelyBeforeUpload", False
            ),
            lambda result: result["finalQuiescence"].__setitem__(
                "activeRunAtPreUploadCheck", 2
            ),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                result = passing_result()
                mutation(result)
                with self.assertRaises(M0Error):
                    validate(result)

    def test_rejects_duplicate_late_or_unbound_process_exit(self) -> None:
        for field, value in (
            ("processExitDispatches", 3),
            ("noActiveProcessExitRejected", 1),
            ("duplicateProcessExitRejected", 1),
            ("lateProcessExitRejected", 1),
            ("activeRunAtResult", 2),
        ):
            with self.subTest(field=field):
                result = passing_result()
                result["bridge"][field] = value
                with self.assertRaises(M0Error):
                    validate(result)

    def test_rejects_run_lifecycle_or_module_reuse(self) -> None:
        mutations = (
            lambda result: result["runs"][0].__setitem__("onExitCount", 2),
            lambda result: result["runs"][0].__setitem__(
                "markerDeliveryCompleteAtProcessExit", "not-a-boolean"
            ),
            lambda result: result["runs"][0].__setitem__(
                "markerDeliveryCompleteAtProcessExit", 0
            ),
            lambda result: result["runs"][1].__setitem__("sameModuleAsPrior", True),
            lambda result: result["runs"][1].__setitem__(
                "moduleIdentity", result["runs"][0]["moduleIdentity"]
            ),
            lambda result: result["runs"][1].__setitem__("startKind", "initial"),
            lambda result: result["runs"][0].__setitem__(
                "postLifecycleTimerObserved", False
            ),
            lambda result: result["runs"][1].__setitem__(
                "processExitBeforeOnExit", False
            ),
            lambda result: result["runs"][0].__setitem__(
                "expectedExitStatusObserved", 0
            ),
            lambda result: result["runs"][1].__setitem__(
                "expectedExitStatusObserved", 1
            ),
            lambda result: result["runs"][0].pop("expectedExitStatusObserved"),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                result = passing_result()
                mutation(result)
                with self.assertRaises(M0Error):
                    validate(result)

    def test_accepts_caught_normal_exit_status_observation(self) -> None:
        result = passing_result()
        for run in result["runs"]:
            run["expectedExitStatusObserved"] = False
        validate(result)

    def test_rejects_numeric_false_for_second_module_identity(self) -> None:
        result = passing_result()
        result["runs"][1]["sameModuleAsPrior"] = 0
        with self.assertRaises(M0Error):
            validate(result)

    def test_requires_explicit_m7_output_configuration(self) -> None:
        smoke.validate_m7_output_configuration(
            b'import("//out/wasm-chrome-m6/args.gn")\n'
            b"enable_chromium_wasm_m7_profile_preferences_test = true\n"
        )
        for args_gn in (
            b"",
            b"enable_chromium_wasm_m7_profile_preferences_test = false\n",
            b"# enable_chromium_wasm_m7_profile_preferences_test = true\n",
            b"enable_chromium_wasm_m7_profile_preferences_test = true\n"
            b"enable_chromium_wasm_m7_profile_preferences_test = false\n",
        ):
            with self.subTest(args_gn=args_gn):
                with self.assertRaises(M0Error):
                    smoke.validate_m7_output_configuration(args_gn)

    def test_rejects_host_storage_or_native_data_boundary_crossing(self) -> None:
        for field in (
            "hostOpfsAccessAttempted",
            "hostWebLocksAccessAttempted",
            "nativeCallAttempted",
            "wasmDataInspectionAttempted",
        ):
            with self.subTest(field=field):
                result = passing_result()
                result["hostBoundary"][field] = True
                with self.assertRaises(M0Error):
                    validate(result)

    def test_rejects_extra_result_or_run_fields_and_wrong_types(self) -> None:
        mutations = (
            lambda result: result.__setitem__("unexpected", True),
            lambda result: result["runs"][0].__setitem__("unexpected", True),
            lambda result: result.__setitem__("factoryCalls", True),
            lambda result: result["runs"][0].__setitem__("runtimeExitCode", False),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                result = passing_result()
                mutation(result)
                with self.assertRaises(M0Error):
                    validate(result)

    def test_result_parser_rejects_duplicate_keys_and_wrong_headers(self) -> None:
        minimal = {
            "protocol": 1,
            "case": smoke.CASE,
            "scope": smoke.SCOPE,
        }
        self.assertEqual(
            smoke.parse_result_payload(json.dumps(minimal).encode("utf-8")), minimal
        )
        duplicate = (
            b'{"protocol":1,"protocol":1,"case":"'
            + smoke.CASE.encode("utf-8")
            + b'","scope":"'
            + smoke.SCOPE.encode("utf-8")
            + b'"}'
        )
        self.assertIsNone(smoke.parse_result_payload(duplicate))
        self.assertIsNone(
            smoke.parse_result_payload(
                json.dumps({**minimal, "scope": "wrong"}).encode("utf-8")
            )
        )

    def test_failure_diagnostics_store_only_reconstructed_summary(self) -> None:
        raw_token = "a" * 64
        summary = smoke.validate_failed_host_result_summary(
            passing_failure_result(native_failure_stage="drain")
        )
        with tempfile.TemporaryDirectory() as temporary:
            diagnostic = smoke.write_failure_diagnostics(
                Path(temporary),
                stage="test",
                error=M0Error(f"failure carried {raw_token}"),
                browser_path=None,
                browser_version=None,
                browser=None,
                browser_stderr=deque([f"--wasm-profile-preferences-token-a={raw_token}"]),
                page_result_received=True,
                host_failure_summary=summary,
            )
            text = diagnostic.read_text(encoding="utf-8")
            payload = json.loads(text)
        self.assertNotIn(raw_token, text)
        self.assertNotIn("failure carried", text)
        self.assertNotIn("stderr_tail", payload["host_browser"])
        self.assertEqual(payload["host_browser"]["stderr_line_count"], 1)
        self.assertTrue(
            payload["host_browser"]["stderr_suppressed_for_opaque_token_hygiene"]
        )
        self.assertTrue(payload["page_result_received"])
        self.assertEqual(
            payload["failure"]["message"],
            "details-suppressed-for-opaque-token-hygiene",
        )
        self.assertEqual(payload["host_failure_summary"], summary)

    def test_failed_host_result_accepts_fixed_native_stage_through_wait_path(self) -> None:
        failure_result = passing_failure_result(native_failure_stage="drain")
        result_queue: queue.Queue[dict[str, object]] = queue.Queue(maxsize=1)
        result_queue.put(copy.deepcopy(failure_result))
        received = smoke.wait_for_result(
            _CleanupFailureBrowser(), deque(), result_queue, time.monotonic() + 1
        )
        summary = smoke.validate_failed_host_result_summary(received)
        self.assertEqual(summary["failureClass"], "native-fixed-failure")
        self.assertEqual(summary["firstFatalTag"], "marker-native-failure")
        self.assertEqual(summary["nativeFailureStage"], "drain")
        self.assertEqual(summary["lifecycle"]["factoryCalls"], 1)
        self.assertEqual(
            smoke._failure_console_reason(summary), "native-fixed-failure stage=drain"
        )

    def test_failure_first_fatal_tag_is_nullable_allowlisted_and_reconstructed(self) -> None:
        tagged = smoke.validate_failed_host_result_summary(
            passing_failure_result(first_fatal_tag="factory-module-mismatch")
        )
        self.assertEqual(tagged["firstFatalTag"], "factory-module-mismatch")
        untagged = smoke.validate_failed_host_result_summary(
            passing_failure_result(first_fatal_tag=None)
        )
        self.assertIsNone(untagged["firstFatalTag"])
        for value in (
            "not-an-allowlisted-fatal-tag",
            "a" * 64,
            ["a" * 32, "a" * 32],
            0,
            False,
        ):
            with self.subTest(value=value):
                result = passing_failure_result()
                result["firstFatalTag"] = value
                with self.assertRaisesRegex(
                    M0Error, "failed host failure class is invalid"
                ):
                    smoke.validate_failed_host_result_summary(result)

    def test_first_fatal_tag_contract_is_exhaustive_and_first_wins(self) -> None:
        host = source("tools/wasm/host/chrome_wasm_profile_persistence_smoke.js")
        start = host.index("const FATAL_TAG = Object.freeze({")
        end = host.index("const HOST_FATAL_TAGS", start)
        tag_block = host[start:end]
        declared = dict(
            re.findall(r'^  ([A-Z_]+): "([a-z0-9-]+)",$', tag_block, re.MULTILINE)
        )
        call_tags = re.findall(
            r"(?:this|host)\.#recordFatal\(\s*FATAL_TAG\.([A-Z_]+)", host
        )
        self.assertEqual(len(call_tags), host.count(".#recordFatal("))
        self.assertEqual(set(call_tags), set(declared))
        self.assertEqual(set(declared.values()), smoke._HOST_FATAL_TAGS)
        record_fatal = host[
            host.index("  #recordFatal(tag, message") : host.index(
                "\n  #noteExternalCallback", host.index("  #recordFatal(tag, message")
            )
        ]
        self.assertIn("if (!HOST_FATAL_TAGS.includes(tag))", record_fatal)
        self.assertIn(
            "if (this.#firstFatalTag === null) this.#firstFatalTag = tag;",
            record_fatal,
        )
        self.assertLess(
            record_fatal.index("this.#firstFatalTag = tag"),
            record_fatal.index('this.#recordFailureClass("host-lifecycle")'),
        )
        failure_summary = host[
            host.index("  failureSummary(failureClass = null)") : host.index(
                "\n  #result(status, error)", host.index("  failureSummary(failureClass = null)")
            )
        ]
        self.assertIn("firstFatalTag: this.#firstFatalTag", failure_summary)
        success_result = host[
            host.index("  #result(status, error)") : host.index(
                "\n  async run(context)", host.index("  #result(status, error)")
            )
        ]
        self.assertNotIn("firstFatalTag", success_result)

    def test_abort_classifier_is_paired_allowlisted_and_failure_only(self) -> None:
        classified = smoke.validate_failed_host_result_summary(
            passing_failure_result(
                first_fatal_tag="abort-reported",
                abort_reason_kind="native-code-abort",
                abort_observation_order="after-onexit",
            )
        )
        self.assertEqual(classified["abortReasonKind"], "native-code-abort")
        self.assertEqual(classified["abortObservationOrder"], "after-onexit")
        unobserved = smoke.validate_failed_host_result_summary(
            passing_failure_result()
        )
        self.assertIsNone(unobserved["abortReasonKind"])
        self.assertIsNone(unobserved["abortObservationOrder"])
        raw_token = "a" * 64
        mutations = (
            ("abortReasonKind", raw_token),
            ("abortReasonKind", [raw_token[:32], raw_token[32:]]),
            ("abortReasonKind", False),
            ("abortReasonKind", "native-code-abort"),
            ("abortObservationOrder", "after-onexit"),
            ("abortObservationOrder", raw_token),
            ("abortObservationOrder", [raw_token[:32], raw_token[32:]]),
        )
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                result = passing_failure_result(
                    first_fatal_tag="abort-reported",
                    abort_reason_kind="native-code-abort",
                    abort_observation_order="after-onexit",
                )
                if field == "abortReasonKind" and value == "native-code-abort":
                    result["abortObservationOrder"] = None
                elif field == "abortObservationOrder" and value == "after-onexit":
                    result["abortReasonKind"] = None
                else:
                    result[field] = value
                with self.assertRaisesRegex(
                    M0Error, "failed host failure class is invalid"
                ):
                    smoke.validate_failed_host_result_summary(result)

    def test_abort_classifier_never_accepts_or_serializes_reason_data(self) -> None:
        host = source("tools/wasm/host/chrome_wasm_profile_persistence_smoke.js")
        runner = source("tools/wasm/run_m7_chrome_profile_persistence_dom_smoke.py")
        classifier_start = host.index("function classifyAbortReason(reason)")
        classifier = host[
            classifier_start : host.index("\nfunction abortObservationOrder", classifier_start)
        ]
        report_abort_start = host.index("  #reportAbort(run, reason)")
        report_abort = host[
            report_abort_start : host.index("\n  #factorySettled", report_abort_start)
        ]
        run_snapshot_start = host.index("  #runSnapshot(run)")
        run_snapshot = host[
            run_snapshot_start : host.index("\n  #bridgeSnapshot", run_snapshot_start)
        ]
        failure_summary_start = host.index("  failureSummary(failureClass = null)")
        failure_summary = host[
            failure_summary_start : host.index(
                "\n  #result(status, error)", failure_summary_start
            )
        ]
        success_result_start = host.index("  #result(status, error)")
        success_result = host[
            success_result_start : host.index("\n  async run(context)", success_result_start)
        ]

        self.assertIn("isExactNormalEmscriptenExitStatus(reason)", classifier)
        self.assertIn('reason.startsWith("Assertion failed")', classifier)
        self.assertIn('reason === "native code called abort()"', classifier)
        self.assertIn("return \"other-primitive-string\"", classifier)
        self.assertIn("return \"nonprimitive\"", classifier)
        self.assertIn("return \"unreadable\"", classifier)
        self.assertNotIn("String(reason)", classifier)
        self.assertNotIn("Object.getOwnPropertyDescriptors(reason)", classifier)
        self.assertIn("run.abortReasonKind = classifyAbortReason(reason);", report_abort)
        self.assertIn("run.abortObservationOrder = abortObservationOrder(run);", report_abort)
        self.assertLess(
            report_abort.index("run.abortReasonKind ="),
            report_abort.index("FATAL_TAG.ABORT_REPORTED"),
        )
        self.assertNotIn("#acceptExpectedNormalExitRejection", report_abort)
        self.assertNotIn("expectedExitStatusObserved = true", report_abort)
        self.assertNotIn("abortReasonKind", run_snapshot)
        self.assertNotIn("abortObservationOrder", run_snapshot)
        self.assertIn("abortReasonKind: latestRun?.abortReasonKind ?? null", failure_summary)
        self.assertIn(
            "abortObservationOrder: latestRun?.abortObservationOrder ?? null",
            failure_summary,
        )
        self.assertNotIn("abortReasonKind", success_result)
        self.assertNotIn("abortObservationOrder", success_result)
        self.assertIn("_ABORT_REASON_KINDS", runner)
        self.assertIn("_ABORT_OBSERVATION_ORDERS", runner)

    def test_malformed_failed_host_result_is_omitted_without_token_fragments(self) -> None:
        raw_token = "a" * 64
        unsafe_results = []
        extra_field = passing_failure_result(native_failure_stage="drain")
        extra_field["unexpectedOutput"] = [raw_token[:32], raw_token[32:]]
        unsafe_results.append((extra_field, "failed host result schema is invalid"))
        unsafe_counter = passing_failure_result(native_failure_stage="drain")
        unsafe_counter["lifecycle"]["callbackCount"] = raw_token
        unsafe_results.append((unsafe_counter, "failed host lifecycle counts are invalid"))
        unsafe_class = passing_failure_result(native_failure_stage="drain")
        unsafe_class["failureClass"] = raw_token
        unsafe_results.append((unsafe_class, "failed host failure class is invalid"))
        unsafe_first_fatal_tag = passing_failure_result()
        unsafe_first_fatal_tag["firstFatalTag"] = raw_token
        unsafe_results.append(
            (unsafe_first_fatal_tag, "failed host failure class is invalid")
        )
        unsafe_split_first_fatal_tag = passing_failure_result()
        unsafe_split_first_fatal_tag["firstFatalTag"] = [
            raw_token[:32],
            raw_token[32:],
        ]
        unsafe_results.append(
            (unsafe_split_first_fatal_tag, "failed host failure class is invalid")
        )
        for unsafe, message in unsafe_results:
            with self.subTest(message=message):
                with self.assertRaisesRegex(M0Error, message):
                    smoke.validate_failed_host_result_summary(unsafe)
        with tempfile.TemporaryDirectory() as temporary:
            diagnostic = smoke.write_failure_diagnostics(
                Path(temporary),
                stage="validate-failed-host-result-summary",
                error=M0Error("profile Preferences failed host result schema is invalid"),
                browser_path=None,
                browser_version=None,
                browser=None,
                browser_stderr=deque(),
                page_result_received=True,
                host_failure_summary=None,
            )
            text = diagnostic.read_text(encoding="utf-8")
            payload = json.loads(text)
        self.assertNotIn(raw_token, text)
        self.assertNotIn(raw_token[:32], text)
        self.assertNotIn(raw_token[32:], text)
        self.assertNotIn("unexpectedOutput", text)
        self.assertTrue(payload["page_result_received"])
        self.assertIsNone(payload["host_failure_summary"])
        self.assertEqual(
            smoke._failure_console_reason(None),
            "details-suppressed-for-opaque-token-hygiene",
        )

    def test_main_records_only_validated_native_failure_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            out_dir = Path(temporary) / "out"
            diagnostics_dir = Path(temporary) / "diagnostics"
            out_dir.mkdir()
            for suffix, contents in ((".js", b"loader"), (".wasm", b"\x00asm")):
                (out_dir / f"{smoke.PRODUCT_MODULE_NAME}{suffix}").write_bytes(
                    contents
                )
            captured_stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "run_m7_chrome_profile_persistence_dom_smoke.py",
                        "--out-dir",
                        str(out_dir),
                        "--diagnostics-dir",
                        str(diagnostics_dir),
                        "--timeout",
                        "20",
                    ],
                ),
                mock.patch.object(smoke, "load_manifest", return_value={}),
                mock.patch.object(
                    smoke, "toolchain_manifest_versions", return_value=VERSIONS
                ),
                mock.patch.object(
                    smoke, "find_browser", return_value=(Path("/browser"), "test")
                ),
                mock.patch.object(
                    smoke, "create_server", return_value=_CleanupFailureServer()
                ),
                mock.patch.object(
                    smoke,
                    "artifact_identity",
                    return_value=copy.deepcopy(ARTIFACT_IDENTITY),
                ),
                mock.patch.object(
                    smoke,
                    "capture_harness_identity",
                    return_value=copy.deepcopy(CAPTURE_HARNESS_IDENTITY),
                ),
                mock.patch.object(smoke, "verify_server_delivery"),
                mock.patch.object(smoke, "smoke_url", return_value="http://test/"),
                mock.patch.object(
                    smoke, "browser_command", return_value=["test-browser"]
                ),
                mock.patch.object(smoke, "subprocess") as mocked_subprocess,
                mock.patch.object(
                    smoke,
                    "wait_for_result",
                    return_value=passing_failure_result(native_failure_stage="drain"),
                ),
                mock.patch.object(smoke, "stop_browser"),
                redirect_stderr(captured_stderr),
            ):
                mocked_subprocess.DEVNULL = object()
                mocked_subprocess.PIPE = object()
                mocked_subprocess.Popen.return_value = _CleanupFailureBrowser()
                self.assertEqual(smoke.main(), 1)
            payload = json.loads(
                (
                    diagnostics_dir / "chrome-profile-preferences-m7-failure.json"
                ).read_text(encoding="utf-8")
            )
        self.assertEqual(payload["stage"], "validate-failed-host-result-summary")
        self.assertEqual(
            payload["host_failure_summary"]["failureClass"],
            "native-fixed-failure",
        )
        self.assertEqual(
            payload["host_failure_summary"]["nativeFailureStage"], "drain"
        )
        self.assertTrue(payload["page_result_received"])
        self.assertIn("native-fixed-failure stage=drain", captured_stderr.getvalue())

    def test_cleanup_failure_cannot_emit_result_or_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            out_dir = Path(temporary) / "out"
            out_dir.mkdir()
            for suffix, contents in (
                (".js", b"loader"),
                (".wasm", b"\x00asm"),
            ):
                (out_dir / f"{smoke.PRODUCT_MODULE_NAME}{suffix}").write_bytes(
                    contents
                )
            captured_stdout = io.StringIO()
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "run_m7_chrome_profile_persistence_dom_smoke.py",
                        "--out-dir",
                        str(out_dir),
                        "--timeout",
                        "20",
                    ],
                ),
                mock.patch.object(smoke, "load_manifest", return_value={}),
                mock.patch.object(
                    smoke, "toolchain_manifest_versions", return_value=VERSIONS
                ),
                mock.patch.object(
                    smoke, "find_browser", return_value=(Path("/browser"), "test")
                ),
                mock.patch.object(
                    smoke, "create_server", return_value=_CleanupFailureServer()
                ),
                mock.patch.object(
                    smoke,
                    "artifact_identity",
                    return_value=copy.deepcopy(ARTIFACT_IDENTITY),
                ),
                mock.patch.object(
                    smoke,
                    "capture_harness_identity",
                    return_value=copy.deepcopy(CAPTURE_HARNESS_IDENTITY),
                ),
                mock.patch.object(smoke, "verify_server_delivery"),
                mock.patch.object(smoke, "smoke_url", return_value="http://test/"),
                mock.patch.object(
                    smoke, "browser_command", return_value=["test-browser"]
                ),
                mock.patch.object(
                    smoke, "subprocess"
                ) as mocked_subprocess,
                mock.patch.object(
                    smoke, "wait_for_result", return_value=passing_result()
                ),
                mock.patch.object(smoke, "validate_result"),
                mock.patch.object(smoke, "stop_browser"),
                mock.patch.object(
                    smoke,
                    "_stop_server",
                    side_effect=M0Error("cleanup failed"),
                ),
                redirect_stdout(captured_stdout),
            ):
                mocked_subprocess.DEVNULL = object()
                mocked_subprocess.PIPE = object()
                mocked_subprocess.Popen.return_value = _CleanupFailureBrowser()
                with self.assertRaisesRegex(M0Error, "cleanup failed"):
                    smoke.main()
        self.assertNotIn(f"{smoke.SENTINEL}:RESULT", captured_stdout.getvalue())
        self.assertNotIn(f"{smoke.SENTINEL}:PASS", captured_stdout.getvalue())

    def test_server_snapshots_headers_mime_and_result_single_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            out_dir = root / "out"
            host_dir = root / "host"
            out_dir.mkdir()
            host_dir.mkdir()
            (out_dir / f"{smoke.PRODUCT_MODULE_NAME}.js").write_bytes(
                b"module-loader"
            )
            (out_dir / f"{smoke.PRODUCT_MODULE_NAME}.wasm").write_bytes(
                b"\x00asm-test-module"
            )
            (out_dir / "args.gn").write_text(
                "enable_chromium_wasm_m7_profile_preferences_test = true\n",
                encoding="utf-8",
            )
            (host_dir / "chrome_wasm_profile_persistence_smoke.html").write_bytes(
                b"<main>profile test</main>"
            )
            (host_dir / "chrome_wasm_profile_persistence_smoke.js").write_bytes(
                b"export {}"
            )
            result_queue: queue.Queue[dict[str, object]] = queue.Queue(maxsize=1)
            token = "result-token-for-m7-preferences-123456"
            server = smoke.create_server(
                "127.0.0.1",
                0,
                out_dir,
                token,
                result_queue,
                host_dir=host_dir,
                runner_source_path=Path(__file__),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                smoke.verify_server_delivery(server)
                self.assertEqual(
                    smoke.artifact_identity(
                        server, module_name=smoke.PRODUCT_MODULE_NAME
                    )["build_config"],
                    {
                        "bytes": len((out_dir / "args.gn").read_bytes()),
                        "sha256": hashlib.sha256(
                            (out_dir / "args.gn").read_bytes()
                        ).hexdigest(),
                    },
                )
                connection = http.client.HTTPConnection(*server.server_address)
                try:
                    payload = json.dumps(
                        {
                            "protocol": 1,
                            "case": smoke.CASE,
                            "scope": smoke.SCOPE,
                        }
                    ).encode("utf-8")
                    path = f"{smoke.HOST_ROOT}/result/{token}"
                    connection.request(
                        "POST",
                        path,
                        body=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    self.assertEqual(connection.getresponse().status, 204)
                    connection.request(
                        "POST",
                        path,
                        body=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    self.assertEqual(connection.getresponse().status, 409)
                finally:
                    connection.close()
                self.assertEqual(result_queue.get_nowait()["case"], smoke.CASE)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
                self.assertFalse(thread.is_alive())

    def test_host_and_runner_keep_the_permanent_dispatch_and_narrow_boundary(self) -> None:
        host = source("tools/wasm/host/chrome_wasm_profile_persistence_smoke.js")
        runner = source("tools/wasm/run_m7_chrome_profile_persistence_dom_smoke.py")
        html = source("tools/wasm/host/chrome_wasm_profile_persistence_smoke.html")

        self.assertIn("Object.defineProperty(globalThis, \"__chromiumWasmHostBridgeV1\"", host)
        self.assertIn("Object.freeze({", host)
        self.assertIn("#routeProcessExit(value)", host)
        self.assertIn("this.#activeRun = null;", host)
        self.assertIn("#scheduleFinalQuiescenceTask(runTwo)", host)
        self.assertIn("FINAL_QUIESCENCE_MS", host)
        self.assertIn("recheckBeforeResultUpload(result)", host)
        self.assertIn("bridgeRecheckedImmediatelyBeforeUpload", host)

        self.assertIn("#opaqueTokenTail", host)
        self.assertIn("#scrubCapturedFields()", host)
        self.assertIn("const combined = trackAcrossCapturedCallbacks", host)
        self.assertIn("combined.includes(token)", host)
        self.assertIn("#safeText(line, true)", host)
        self.assertIn("<suppressed-native-output>", host)
        self.assertIn("appendOutputPreservingM7Markers", host)
        self.assertIn("onExit(code) { host.#reportRuntimeExit(run, code); }", host)
        self.assertNotIn("host.#reportRuntimeExit(run, Number(code))", host)
        self.assertIn("URL.revokeObjectURL", host)
        self.assertIn('this.#runTwoScheduleMethod = "setTimeout(...,0)";', host)
        schedule = host[host.index("#scheduleRunTwo(runOne)") : host.index("#locateFileForWasm")]
        self.assertIn("runOne.processExitCode === 0", schedule)
        self.assertIn("runOne.runtimeExitCode === 0", schedule)
        self.assertIn("setTimeout(() => {", schedule)
        self.assertLess(schedule.index("setTimeout(() => {"),
                        schedule.index('this.#startRun(2, "setTimeout-0")'))
        for marker in (
            "READY",
            "WRITE_ACCEPTED",
            "READ_A_OK",
            "FENCE_OK",
            "LEASE_RELEASED",
        ):
            self.assertIn(marker, host)
        for forbidden in (
            "navigator.storage",
            "navigator.locks",
            ".ccall(",
            "getDirectory",
            "HEAPU8",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, host)
        self.assertIn("snapshot_regular_files", runner)
        self.assertIn("snapshot_regular_file", runner)
        self.assertIn("validate_m7_output_configuration", runner)
        self.assertIn("selected-out-dir-args-gn-immutable-snapshot", runner)
        self.assertIn('"application/wasm"', runner)
        self.assertIn('"Cross-Origin-Opener-Policy", "same-origin"', runner)
        self.assertIn('"Cross-Origin-Embedder-Policy", "require-corp"', runner)
        self.assertIn("verify_server_delivery(server)", runner)
        self.assertIn("validate_result(", runner)
        self.assertIn("fetchVerifiedArtifact", host)
        self.assertIn("URL.createObjectURL(blob)", host)
        self.assertIn("wasmBinary: this.#wasmBinary", host)
        self.assertIn("Cross-Origin-Resource-Policy", host)
        self.assertIn("m7GateComplete", host)
        self.assertIn("//chrome:chrome_wasm", runner)
        self.assertIn(
            "enable_chromium_wasm_m7_profile_preferences_test=true", runner
        )
        self.assertIn("autoninja -C out/wasm-chrome-m7-profile-preferences", runner)
        self.assertNotIn("assert browser.stderr", runner)
        self.assertIn(
            "profile Preferences browser stderr pipe is unavailable", runner
        )
        self.assertIn("validate_failed_host_result_summary", runner)
        self.assertIn("host_failure_summary", runner)
        self.assertIn("failureSummary()", host)
        self.assertIn(
            "validateChromeWasmProfilePersistenceFailureSummary", host
        )
        failure_upload = host[
            host.index("export async function runChromeWasmProfilePersistenceFromQuery") :
        ]
        self.assertIn("result = host.failureSummary();", failure_upload)
        self.assertIn(
            "result = validateChromeWasmProfilePersistenceFailureSummary(result);",
            failure_upload,
        )
        self.assertLess(
            failure_upload.index("result = host.failureSummary();"),
            failure_upload.index(
                "result = validateChromeWasmProfilePersistenceFailureSummary(result);"
            ),
        )
        finally_block = runner.index("    finally:\n")
        pass_output = runner.rindex(f'print(f"{{SENTINEL}}:PASS", flush=True)')
        self.assertLess(finally_block, pass_output)
        self.assertIn("chrome_wasm_profile_persistence_smoke.js", html)

    def test_native_marker_emission_and_host_delivery_are_distinct(self) -> None:
        """Keeps emitted-marker ordering separate from pthread callback delivery."""
        host = source("tools/wasm/host/chrome_wasm_profile_persistence_smoke.js")
        runner = source("tools/wasm/run_m7_chrome_profile_persistence_dom_smoke.py")
        preferences_smoke = source(
            "chrome/browser/wasm/wasm_profile_preferences_smoke.cc"
        )
        chrome_main = source("chrome/app/chrome_main_wasm.cc")

        drain_start = preferences_smoke.index("  void NotifyBackendDrain(bool success)")
        drain_end = preferences_smoke.index("\n  void ReportFailure", drain_start)
        drain = preferences_smoke[drain_start:drain_end]
        self.assertLess(
            drain.index("!storage_lifecycle_succeeded_"),
            drain.index("lease_released_ = true;"),
        )
        self.assertLess(
            drain.index("lease_released_ = true;"),
            drain.index('EmitMarker("LEASE_RELEASED");'),
        )
        emit_marker_start = preferences_smoke.index(
            "  void EmitMarker(const char* marker)"
        )
        emit_marker_end = preferences_smoke.index(
            "\n  void EmitDigestMarker", emit_marker_start
        )
        self.assertIn(
            "std::fflush(stderr);",
            preferences_smoke[emit_marker_start:emit_marker_end],
        )
        self.assertLess(
            chrome_main.index(
                "chrome::NotifyWasmProfilePreferencesSmokeBackendDrain("
            ),
            chrome_main.index("chromium_wasm_report_process_exit(exit_code)"),
        )

        capture_start = host.index("  #captureOutput(run, destination, line)")
        route_exit_start = host.index("  #routeProcessExit(value)")
        runtime_exit_start = host.index("  #reportRuntimeExit(run, code)")
        completion_start = host.index("  #runIsCleanlyComplete(run)")
        capture = host[capture_start : host.index("\n  #markersComplete", capture_start)]
        route_exit = host[
            route_exit_start : host.index("\n  #reportAbort", route_exit_start)
        ]
        runtime_exit = host[
            runtime_exit_start : host.index("\n  #routeProcessExit", runtime_exit_start)
        ]
        completion = host[
            completion_start : host.index("\n  #maybeCompleteRun", completion_start)
        ]
        self.assertIn("this.#maybeCompleteRun(run);", capture)
        self.assertIn(
            "run.markerDeliveryCompleteAtProcessExit = this.#markersComplete(run);",
            route_exit,
        )
        self.assertNotIn("!this.#markersComplete(run)", route_exit)
        self.assertIn("run.processExitCount !== 1", runtime_exit)
        self.assertIn("run.processExitBeforeOnExit = true;", runtime_exit)
        self.assertIn("this.#markersComplete(run)", completion)
        self.assertIn("run.processExitCount === 1", completion)
        self.assertIn("run.onExitCount === 1", completion)
        self.assertNotIn("processExitAfterMarkers", host)
        self.assertNotIn("processExitAfterMarkers", runner)
        self.assertIn("markerDeliveryCompleteAtProcessExit", runner)

    def test_expected_normal_exit_status_requires_exact_own_data_triple(self) -> None:
        script = r'''
import {isExactNormalEmscriptenExitStatus,
  validateChromeWasmProfilePersistenceFailureSummary} from
  "./tools/wasm/host/chrome_wasm_profile_persistence_smoke.js";

const exact = {
  name: "ExitStatus",
  status: 0,
  message: "Program terminated with exit(0)",
};
const cases = [
  [exact, true, "exact"],
  ["Program terminated with exit(0)", false, "string fallback"],
  [{...exact, status: 1}, false, "nonzero status"],
  [{...exact, name: "Error"}, false, "wrong name"],
  [{...exact, message: "Program terminated with exit(1)"}, false,
   "wrong message"],
  [{...exact, extra: true}, false, "extra field"],
];
const hiddenExtra = {...exact};
Object.defineProperty(hiddenExtra, "hidden", {value: true});
cases.push([hiddenExtra, false, "hidden extra field"]);
const symbolExtra = {...exact};
symbolExtra[Symbol("extra")] = true;
cases.push([symbolExtra, false, "symbol extra field"]);
for (const [value, expected, label] of cases) {
  if (isExactNormalEmscriptenExitStatus(value) !== expected) {
    throw new Error(`unexpected ${label} classification`);
  }
}

let getterReads = 0;
const accessor = {status: 0, message: "Program terminated with exit(0)"};
Object.defineProperty(accessor, "name", {
  enumerable: true,
  get() {
    ++getterReads;
    return "ExitStatus";
  },
});
if (isExactNormalEmscriptenExitStatus(accessor) || getterReads !== 0) {
  throw new Error("accessor was accepted or executed");
}

let proxyTraps = 0;
const throwingProxy = new Proxy({}, {
  ownKeys() {
    ++proxyTraps;
    throw new Error("reflection denied");
  },
});
if (isExactNormalEmscriptenExitStatus(throwingProxy) || proxyTraps !== 1) {
  throw new Error("reflection-faulting proxy was accepted or escaped");
}

const revoked = Proxy.revocable({}, {});
revoked.revoke();
if (isExactNormalEmscriptenExitStatus(revoked.proxy)) {
  throw new Error("revoked proxy was accepted");
}

const failureSummary = {
  protocol: 1,
  case: "chrome_profile_preferences_two_fresh_modules_m7",
  scope: "same-origin-same-document-two-fresh-chrome-wasm-m7-profile-preferences-test-modules-preferences-only",
  status: "fail",
  failureClass: "host-lifecycle",
  firstFatalTag: "factory-rejected",
  abortReasonKind: null,
  abortObservationOrder: null,
  nativeFailureStage: null,
  lifecycle: {
    acceptedProcessExitCount: 1,
    activeRunPresent: true,
    bridgeInstalled: true,
    bridgeInstalledBeforeModuleFactory: true,
    callbackCount: 12,
    factoryCalls: 1,
    finalQuiescenceCompleted: false,
    lastProcessExitCode: 0,
    lastRuntimeExitCode: 0,
    leaseReleasedRunCount: 1,
    onExitCount: 1,
    processExitReportCount: 1,
    rawTokenLeakDetected: false,
    runCount: 1,
    unhandledRejectionObserved: false,
    windowErrorObserved: false,
  },
};
validateChromeWasmProfilePersistenceFailureSummary(failureSummary);
for (const invalid of [
  {...failureSummary, firstFatalTag: "not-an-allowlisted-fatal-tag"},
  {...failureSummary, firstFatalTag: "a".repeat(64)},
  {...failureSummary, firstFatalTag: ["a".repeat(32), "a".repeat(32)]},
  {...failureSummary, abortReasonKind: "a".repeat(64),
   abortObservationOrder: "after-onexit"},
  {...failureSummary, abortReasonKind: ["a".repeat(32), "a".repeat(32)],
   abortObservationOrder: "after-onexit"},
  {...failureSummary, abortReasonKind: "native-code-abort"},
  {...failureSummary, unexpectedOutput: ["a".repeat(64)]},
]) {
  let rejected = false;
  try {
    validateChromeWasmProfilePersistenceFailureSummary(invalid);
  } catch (_error) {
    rejected = true;
  }
  if (!rejected) throw new Error("unsafe failure summary was accepted");
}
validateChromeWasmProfilePersistenceFailureSummary({
  ...failureSummary,
  firstFatalTag: "abort-reported",
  abortReasonKind: "exact-own-data-zero-exit-status",
  abortObservationOrder: "after-onexit",
});
'''
        completed = subprocess.run(
            ["node", "--input-type=module", "--eval", script],
            capture_output=True,
            check=False,
            cwd=TOOLS_DIR.parents[1],
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_expected_normal_exit_rejection_is_tightly_lifecycle_bound(self) -> None:
        host = source("tools/wasm/host/chrome_wasm_profile_persistence_smoke.js")
        handler_start = host.index("  #captureWindowErrors()")
        handler = host[handler_start : host.index("\n  #releaseWindowErrors", handler_start)]
        acceptance_start = host.index(
            "  #acceptExpectedNormalExitRejection(event, reason)"
        )
        acceptance = host[
            acceptance_start : host.index("\n  #routeProcessExit", acceptance_start)
        ]
        classifier_start = host.index(
            "export function isExactNormalEmscriptenExitStatus(value)"
        )
        classifier = host[
            classifier_start : host.index("\nfunction hasBoundedFailureCount", classifier_start)
        ]
        completion_start = host.index("  #runIsCleanlyComplete(run)")
        completion = host[
            completion_start : host.index("\n  #maybeCompleteRun", completion_start)
        ]
        factory_rejected_start = host.index("  #factoryRejected(run, error)")
        factory_rejected = host[
            factory_rejected_start : host.index("\n  #runIsCleanlyComplete", factory_rejected_start)
        ]

        self.assertIn("isExactNormalEmscriptenExitStatus(reason)", acceptance)
        self.assertIn("Object.getOwnPropertyDescriptors(value)", classifier)
        self.assertIn("Reflect.ownKeys(descriptors)", classifier)
        self.assertIn("Object.hasOwn(descriptor, \"value\")", classifier)
        self.assertNotIn('value === "Program terminated with exit(0)"', classifier)
        self.assertLess(classifier.index("try {"),
                        classifier.index("Array.isArray(value)"))
        self.assertIn("run === null || run.expectedExitStatusObserved", acceptance)
        self.assertIn("this.#fatalErrors.length !== 0", acceptance)
        self.assertIn("this.#nativeFailureStage !== null", acceptance)
        self.assertIn("this.#windowErrors.length !== 0", acceptance)
        self.assertIn("this.#unhandledRejections.length !== 0", acceptance)
        self.assertIn("run.abort !== null", acceptance)
        self.assertIn("run.factorySettled", acceptance)
        self.assertIn("run.processExitCount !== 1", acceptance)
        self.assertIn("run.processExitCode !== 0", acceptance)
        self.assertIn("run.onExitCount !== 1", acceptance)
        self.assertIn("run.runtimeExitCode !== 0", acceptance)
        self.assertIn("event.preventDefault();", acceptance)
        self.assertIn("run.expectedExitStatusObserved = true;", acceptance)
        self.assertIn("this.#maybeCompleteRun(run);", acceptance)
        self.assertNotIn("#markersComplete", acceptance)
        self.assertLess(
            handler.index("this.#acceptExpectedNormalExitRejection(event, reason)"),
            handler.index('this.#recordFailureClass("host-unhandled-rejection")'),
        )
        self.assertIn(
            'typeof run.expectedExitStatusObserved === "boolean"', completion
        )
        self.assertNotIn("run.expectedExitStatusObserved === true", completion)
        self.assertIn("this.#markersComplete(run)", completion)
        self.assertIn("FATAL_TAG.FACTORY_REJECTED", factory_rejected)
        self.assertNotIn("isExactNormalEmscriptenExitStatus", factory_rejected)
        self.assertIn("expectedExitStatusObserved", smoke._RUN_FIELDS)
        self.assertIn(
            'type(run.get("expectedExitStatusObserved")) is not bool',
            source("tools/wasm/run_m7_chrome_profile_persistence_dom_smoke.py"),
        )

    def test_post_lifecycle_timer_marks_the_second_run(self) -> None:
        host = source("tools/wasm/host/chrome_wasm_profile_persistence_smoke.js")
        quiescence_timer = host[
            host.index("#schedulePostLifecycleQuiescence(runTwo)") : host.index(
                "#scheduleFinalQuiescenceTask(runTwo)"
            )
        ]
        self.assertIn("runTwo.postLifecycleTimerObserved = true;", quiescence_timer)
        self.assertNotIn("run.postLifecycleTimerObserved", quiescence_timer)


if __name__ == "__main__":
    unittest.main()
