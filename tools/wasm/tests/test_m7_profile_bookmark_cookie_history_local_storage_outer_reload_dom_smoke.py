#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the aggregate Bookmark + Cookie + History + LocalStorage reload runner."""

from __future__ import annotations

import copy
from collections import deque
import json
from pathlib import Path
import sys
import threading
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m7_chrome_profile_bookmark_cookie_history_local_storage_outer_reload_dom_smoke as smoke


VERSIONS = {"chromium": "a" * 40, "v8": "b" * 40, "emscripten": "c" * 40}
RESULT_CAPABILITY = "r" * 32
SESSION_CAPABILITY = "s" * 32
ORIGIN = "http://127.0.0.1:43127"
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


def passing_quiescence() -> dict[str, object]:
    return {
        "taskScheduledExactlyOnce": True,
        "taskMethod": "setTimeout(...,0)",
        "postLifecycleTimerObservedBeforeTask": True,
        "started": True,
        "startedAfterActiveClear": True,
        "completed": True,
        "quietWindowMs": smoke.FINAL_QUIESCENCE_MS,
        "quiet": True,
        "callbacksAtActiveClear": 17,
        "callbacksAtTaskStart": 17,
        "callbacksAtTaskEnd": 17,
        "callbacksAtPreUploadCheck": 17,
        "processExitReportsAtActiveClear": 1,
        "processExitReportsAtTaskStart": 1,
        "processExitReportsAtTaskEnd": 1,
        "processExitReportsAtPreUploadCheck": 1,
        "activeRunAtActiveClear": None,
        "activeRunAtTaskStart": None,
        "activeRunAtTaskEnd": None,
        "activeRunAtPreUploadCheck": None,
        "bridgeRecheckedImmediatelyBeforeUpload": True,
    }


def passing_result(
    ordinal: int, escrow: smoke.TokenEscrow, time_origin: float
) -> dict[str, object]:
    markers = smoke.expected_markers(ordinal, escrow)
    return {
        "protocol": 1,
        "case": smoke.CASE,
        "scope": smoke.SCOPE,
        "status": "pass",
        "ordinal": ordinal,
        "mode": smoke._phase_mode(ordinal),
        "origin": ORIGIN,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "document": {
            "navigationType": "navigate" if ordinal == 1 else "reload",
            "timeOrigin": time_origin,
        },
        "artifact": copy.deepcopy(ARTIFACT),
        "capture_harness": copy.deepcopy(HARNESS),
        "versions": copy.deepcopy(VERSIONS),
        "tokenEvidence": {
            "algorithm": "SHA-256",
            "preferenceA": (
                None if ordinal == 3 else escrow.preference_a_digest
            ),
            "preferenceB": (
                None if ordinal == 1 else escrow.preference_b_digest
            ),
            "localStorage": escrow.local_storage_digest,
            "distinct": True if ordinal in (2, 3) else None,
            "rawTokensExcluded": True,
            "rawTokenLeakDetected": False,
            "rawTokenRedactionCount": 0,
        },
        "run": {
            "abort": None,
            "activeClearedAfterLifecycle": True,
            "expectedExitStatusObserved": False,
            "factoryError": None,
            "factorySettled": True,
            "freshLoaderImport": True,
            "freshModuleObject": True,
            "loaderIdentity": str(ordinal + 1) * 32,
            "bookmarkTransportModeFeatureDisabled": True,
            "preferenceLeaseReleasedMarkerObserved": True,
            "localStorageLeaseReleasedMarkerObserved": True,
            "sharedDrainReceiptsAccepted": True,
            "markerCount": len(markers),
            "markerDeliveryCompleteAtProcessExit": False,
            "markerSequenceAccepted": True,
            "markerSource": "stderr-only",
            "markers": markers,
            "mode": smoke._phase_mode(ordinal),
            "moduleIdentity": str(ordinal + 3) * 32,
            "onExitCount": 1,
            "ordinal": ordinal,
            "postLifecycleTimerObserved": True,
            "processExitBeforeOnExit": True,
            "processExitCode": 0,
            "processExitCount": 1,
            "runtimeExitCode": 0,
            "runtimeInitialized": True,
            "stderr": markers,
            "stdout": [],
        },
        "bridge": {
            "protocol": 1,
            "permanent": True,
            "frozen": True,
            "installedBeforeModuleFactory": True,
            "processExitDispatches": 1,
            "noActiveProcessExitRejected": 0,
            "duplicateProcessExitRejected": 0,
            "lateProcessExitRejected": 0,
            "activeRunAtResult": None,
        },
        "finalQuiescence": passing_quiescence(),
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


def validate_result(
    value: dict[str, object], ordinal: int, escrow: smoke.TokenEscrow,
    time_origin: float
) -> smoke.PhaseResult:
    return smoke.validate_phase_result(
        value,
        ordinal=ordinal,
        expected_versions=VERSIONS,
        expected_artifact_identity=ARTIFACT,
        expected_capture_harness_identity=HARNESS,
        expected_origin=ORIGIN,
        expected_document=smoke.DocumentEvidence(
            "navigate" if ordinal == 1 else "reload", time_origin
        ),
        escrow=escrow,
        result_token=RESULT_CAPABILITY,
        session=SESSION_CAPABILITY,
    )


class FakeBrowser:
    def poll(self) -> None:
        return None


class FakeCdpClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object | None]] = []
        self.events = deque(
            [
                {
                    "method": "Page.frameNavigated",
                    "params": {
                        "frame": {
                            "id": "root",
                            "loaderId": "loader-b",
                            "url": "http://127.0.0.1/smoke/?fixed",
                        }
                    },
                }
            ]
        )

    def call(self, method: str, params: object | None = None) -> dict[str, object]:
        self.calls.append((method, params))
        if method == "Page.getFrameTree":
            return {
                "frameTree": {
                    "frame": {"id": "root", "loaderId": "loader-a"}
                }
            }
        return {}

    def next_event(self, _timeout: float) -> object | None:
        return self.events.popleft() if self.events else None


class M7ProfileBookmarkCookieHistoryLocalStorageOuterReloadDomSmokeTest(unittest.TestCase):
    def test_uses_a_dedicated_three_document_aggregate_artifact(self) -> None:
        self.assertEqual(
            smoke.CASE,
            "chrome_profile_bookmark_cookie_history_local_storage_"
            "three_outer_document_reload_m7",
        )
        self.assertEqual(
            smoke.SCOPE,
            "same-origin-three-outer-documents-chrome-wasm-m7-preferences-"
            "bookmark-model-cookie-manager-history-service-renderer-local-"
            "storage-one-shared-drain-per-module-orderly-reload-only",
        )
        self.assertEqual(
            smoke.HOST_ROOT,
            "/__m7_chrome_profile_bookmark_cookie_history_local_storage_"
            "outer_reload__",
        )
        self.assertEqual(
            smoke.PRODUCT_MODULE_NAME,
            "chrome_wasm_m7_profile_bookmark_cookie_history_local_storage_test",
        )
        self.assertEqual(
            smoke.PRODUCT_GN_ENABLE_ARGUMENT,
            "enable_chromium_wasm_m7_profile_bookmark_cookie_history_local_storage_test=true",
        )
        self.assertEqual(
            smoke.DEFAULT_OUT_DIR,
            Path("out/wasm-chrome-m7-profile-bookmark-cookie-history-local-storage"),
        )
        self.assertIn("three-outer-documents", smoke.SCOPE)
        self.assertIn("bookmark-model", smoke.SCOPE)
        self.assertIn("history-service", smoke.SCOPE)
        self.assertIn("one-shared-drain-per-module", smoke.SCOPE)
        self.assertIn("orderly-reload-only", smoke.SCOPE)
        self.assertEqual(smoke.MAX_TIMEOUT_MS, 600_000)

    def test_http_receipt_path_admits_all_three_documents_only(self) -> None:
        handler = (
            smoke.ChromeProfileBookmarkCookieHistoryLocalStorageOuterReloadRequestHandler
        )
        runner_source = Path(smoke.__file__).read_text(encoding="utf-8")
        self.assertEqual(runner_source.count("queue.Queue(maxsize=3)"), 2)
        for kind in ("result", "ready"):
            prefix = f"{smoke.HOST_ROOT}/{kind}/"
            for ordinal in (1, 2, 3):
                with self.subTest(kind=kind, ordinal=ordinal):
                    self.assertEqual(
                        handler._receipt_path(
                            f"{prefix}{RESULT_CAPABILITY}/{ordinal}", prefix
                        ),
                        (RESULT_CAPABILITY, ordinal),
                    )
            self.assertIsNone(
                handler._receipt_path(
                    f"{prefix}{RESULT_CAPABILITY}/4", prefix
                )
            )

    def test_escrows_three_distinct_values_and_exposes_only_digests(self) -> None:
        escrow = smoke.new_token_escrow()
        raw = {escrow.preference_a, escrow.preference_b, escrow.local_storage}
        digests = {
            escrow.preference_a_digest,
            escrow.preference_b_digest,
            escrow.local_storage_digest,
        }
        self.assertEqual(len(raw), 3)
        self.assertEqual(len(digests), 3)
        self.assertEqual(smoke._sha256_text(escrow.preference_a), escrow.preference_a_digest)
        self.assertEqual(smoke._sha256_text(escrow.preference_b), escrow.preference_b_digest)
        self.assertEqual(smoke._sha256_text(escrow.local_storage), escrow.local_storage_digest)
        self.assertNotIn(escrow.preference_a, repr(escrow))
        self.assertNotIn(escrow.preference_b, repr(escrow))
        self.assertNotIn(escrow.local_storage, repr(escrow))

    def test_accepts_all_three_strict_aggregate_marker_sequences(self) -> None:
        escrow = smoke.new_token_escrow()
        first = validate_result(passing_result(1, escrow, 100.0), 1, escrow, 100.0)
        second = validate_result(
            passing_result(2, escrow, 101.0), 2, escrow, 101.0
        )
        third = validate_result(
            passing_result(3, escrow, 102.0), 3, escrow, 102.0
        )
        smoke.validate_outer_document_transitions(first, second, third)
        for ordinal in (1, 2, 3):
            markers = smoke.expected_markers(ordinal, escrow)
            self.assertEqual(markers[-2:], [
                f"{smoke.M7_PREFS_MARKER_PREFIX}LEASE_RELEASED",
                f"{smoke.M7_LOCAL_STORAGE_MARKER_PREFIX}LEASE_RELEASED",
            ])
            self.assertLess(
                markers.index(f"{smoke.M7_PREFS_MARKER_PREFIX}BOOKMARK_MODEL_CLOSED"),
                markers.index(f"{smoke.M7_PREFS_MARKER_PREFIX}COOKIE_BACKEND_CLOSED"),
            )
            self.assertLess(
                markers.index(f"{smoke.M7_PREFS_MARKER_PREFIX}COOKIE_BACKEND_CLOSED"),
                markers.index(f"{smoke.M7_PREFS_MARKER_PREFIX}HISTORY_BACKEND_CLOSED"),
            )
            self.assertLess(
                markers.index(f"{smoke.M7_PREFS_MARKER_PREFIX}HISTORY_BACKEND_CLOSED"),
                markers.index(f"{smoke.M7_LOCAL_STORAGE_MARKER_PREFIX}READY"),
            )
            if ordinal == 1:
                bookmark_progress = [
                    f"{smoke.M7_PREFS_MARKER_PREFIX}BOOKMARK_A_WRITE_FLUSHED "
                    f"sha256={escrow.preference_a_digest}",
                ]
                history_progress = [
                    f"{smoke.M7_PREFS_MARKER_PREFIX}HISTORY_A_WRITE_ACCEPTED",
                ]
            elif ordinal == 2:
                bookmark_progress = [
                    f"{smoke.M7_PREFS_MARKER_PREFIX}BOOKMARK_A_READ_OK "
                    f"sha256={escrow.preference_a_digest}",
                    f"{smoke.M7_PREFS_MARKER_PREFIX}BOOKMARK_B_WRITE_FLUSHED "
                    f"sha256={escrow.preference_b_digest}",
                ]
                history_progress = [
                    f"{smoke.M7_PREFS_MARKER_PREFIX}HISTORY_A_READ_OK",
                    f"{smoke.M7_PREFS_MARKER_PREFIX}HISTORY_B_WRITE_ACCEPTED",
                ]
            else:
                bookmark_progress = [
                    f"{smoke.M7_PREFS_MARKER_PREFIX}BOOKMARK_B_READ_OK "
                    f"sha256={escrow.preference_b_digest}",
                    f"{smoke.M7_PREFS_MARKER_PREFIX}BOOKMARK_CLEANUP_FLUSHED",
                ]
                history_progress = [
                    f"{smoke.M7_PREFS_MARKER_PREFIX}HISTORY_A_READ_OK",
                    f"{smoke.M7_PREFS_MARKER_PREFIX}HISTORY_B_READ_OK",
                ]
            browser_close = markers.index(
                f"{smoke.M7_PREFS_MARKER_PREFIX}BROWSER_SMOKE_CLOSED"
            )
            bookmark_close = markers.index(
                f"{smoke.M7_PREFS_MARKER_PREFIX}BOOKMARK_MODEL_CLOSED"
            )
            self.assertEqual(
                markers[browser_close + 1 : bookmark_close], bookmark_progress
            )
            cookie_close = markers.index(
                f"{smoke.M7_PREFS_MARKER_PREFIX}COOKIE_BACKEND_CLOSED"
            )
            history_close = markers.index(
                f"{smoke.M7_PREFS_MARKER_PREFIX}HISTORY_BACKEND_CLOSED"
            )
            self.assertEqual(
                markers[cookie_close + 1 : history_close], history_progress
            )
            self.assertLess(
                next(i for i, marker in enumerate(markers) if "DB_CLOSE_OK" in marker),
                next(i for i, marker in enumerate(markers) if "PREFS:FENCE_OK" in marker),
            )

    def test_rejects_reordered_or_duplicate_cross_protocol_drain_receipts(self) -> None:
        escrow = smoke.new_token_escrow()
        for mutation in ("swap", "duplicate", "false-shared"):
            receipt = passing_result(1, escrow, 100.0)
            run = receipt["run"]
            assert isinstance(run, dict)
            markers = list(run["markers"])
            if mutation == "swap":
                markers[-2], markers[-1] = markers[-1], markers[-2]
            elif mutation == "duplicate":
                markers[-1] = markers[-2]
            else:
                run["sharedDrainReceiptsAccepted"] = False
            run["markers"] = markers
            run["stderr"] = markers
            with self.subTest(mutation=mutation), self.assertRaises(M0Error):
                validate_result(receipt, 1, escrow, 100.0)

    def test_rejects_reordered_or_missing_bookmark_model_boundary(self) -> None:
        escrow = smoke.new_token_escrow()
        for mutation in ("move-after-cookie", "drop-close", "duplicate-progress"):
            receipt = passing_result(2, escrow, 101.0)
            run = receipt["run"]
            assert isinstance(run, dict)
            markers = list(run["markers"])
            bookmark_close = (
                f"{smoke.M7_PREFS_MARKER_PREFIX}BOOKMARK_MODEL_CLOSED"
            )
            if mutation == "move-after-cookie":
                markers.remove(bookmark_close)
                markers.insert(
                    markers.index(
                        f"{smoke.M7_PREFS_MARKER_PREFIX}COOKIE_BACKEND_CLOSED"
                    ) + 1,
                    bookmark_close,
                )
            elif mutation == "drop-close":
                markers.remove(bookmark_close)
            else:
                markers.insert(
                    markers.index(bookmark_close),
                    f"{smoke.M7_PREFS_MARKER_PREFIX}BOOKMARK_A_READ_OK "
                    f"sha256={escrow.preference_a_digest}",
                )
            run["markers"] = markers
            run["markerCount"] = len(markers)
            run["stderr"] = markers
            with self.subTest(mutation=mutation), self.assertRaises(M0Error):
                validate_result(receipt, 2, escrow, 101.0)

    def test_requires_bookmark_transport_mode_feature_disablement(self) -> None:
        escrow = smoke.new_token_escrow()
        receipt = passing_result(1, escrow, 100.0)
        run = receipt["run"]
        assert isinstance(run, dict)
        run["bookmarkTransportModeFeatureDisabled"] = False
        with self.assertRaises(M0Error):
            validate_result(receipt, 1, escrow, 100.0)

        host = (
            TOOLS_DIR
            / "host"
            / "chrome_wasm_profile_bookmark_cookie_history_local_storage_outer_reload_smoke.js"
        ).read_text(encoding="utf-8")
        self.assertIn("--wasm-profile-preferences-bookmark-smoke", host)
        self.assertIn(
            "--disable-features=SyncEnableBookmarksInTransportMode", host
        )

    def test_rejects_reordered_or_missing_history_backend_boundary(self) -> None:
        escrow = smoke.new_token_escrow()
        for mutation in ("move-after-local-storage", "drop-close", "duplicate-progress"):
            receipt = passing_result(2, escrow, 101.0)
            run = receipt["run"]
            assert isinstance(run, dict)
            markers = list(run["markers"])
            history_close = (
                f"{smoke.M7_PREFS_MARKER_PREFIX}HISTORY_BACKEND_CLOSED"
            )
            if mutation == "move-after-local-storage":
                markers.remove(history_close)
                markers.insert(
                    markers.index(f"{smoke.M7_LOCAL_STORAGE_MARKER_PREFIX}READY") + 1,
                    history_close,
                )
            elif mutation == "drop-close":
                markers.remove(history_close)
            else:
                markers.insert(
                    markers.index(history_close),
                    f"{smoke.M7_PREFS_MARKER_PREFIX}HISTORY_A_READ_OK",
                )
            run["markers"] = markers
            run["markerCount"] = len(markers)
            run["stderr"] = markers
            with self.subTest(mutation=mutation), self.assertRaises(M0Error):
                validate_result(receipt, 2, escrow, 101.0)

    def test_rejects_reused_loader_or_module_and_nonincreasing_time(self) -> None:
        first = smoke.PhaseResult(1, ORIGIN, "navigate", 100.0, "1" * 32, "2" * 32)
        second = smoke.PhaseResult(2, ORIGIN, "reload", 101.0, "3" * 32, "4" * 32)
        valid = smoke.PhaseResult(3, ORIGIN, "reload", 102.0, "5" * 32, "6" * 32)
        smoke.validate_outer_document_transitions(first, second, valid)
        for invalid_second in (
            smoke.PhaseResult(2, ORIGIN, "reload", 101.0, "1" * 32, "4" * 32),
            smoke.PhaseResult(2, ORIGIN, "reload", 101.0, "3" * 32, "2" * 32),
            smoke.PhaseResult(2, ORIGIN, "reload", 100.0, "3" * 32, "4" * 32),
            smoke.PhaseResult(
                2, "http://other.test", "reload", 101.0, "3" * 32, "4" * 32
            ),
        ):
            with self.subTest(second=invalid_second), self.assertRaises(M0Error):
                smoke.validate_outer_document_transitions(
                    first, invalid_second, valid
                )
        for third in (
            smoke.PhaseResult(3, ORIGIN, "reload", 102.0, "1" * 32, "6" * 32),
            smoke.PhaseResult(3, ORIGIN, "reload", 102.0, "3" * 32, "6" * 32),
            smoke.PhaseResult(3, ORIGIN, "reload", 102.0, "5" * 32, "2" * 32),
            smoke.PhaseResult(3, ORIGIN, "reload", 102.0, "5" * 32, "4" * 32),
            smoke.PhaseResult(3, ORIGIN, "reload", 101.0, "5" * 32, "6" * 32),
            smoke.PhaseResult(
                3, "http://other.test", "reload", 102.0, "5" * 32, "6" * 32
            ),
        ):
            with self.subTest(third=third), self.assertRaises(M0Error):
                smoke.validate_outer_document_transitions(first, second, third)

    def test_session_authorizes_exactly_two_real_reloads_and_three_phases(self) -> None:
        escrow = smoke.new_token_escrow()
        session = smoke.OuterReloadSession(
            RESULT_CAPABILITY, SESSION_CAPABILITY, escrow
        )
        first_evidence = smoke.DocumentEvidence("navigate", 100.0)
        self.assertTrue(session.accept_document(SESSION_CAPABILITY, first_evidence))
        session.acknowledge_document(SESSION_CAPABILITY)
        first_bootstrap = session.bootstrap_payload(SESSION_CAPABILITY)
        self.assertEqual(first_bootstrap["ordinal"], 1)
        self.assertEqual(
            first_bootstrap["localStorageToken"], escrow.local_storage
        )
        self.assertIsNone(first_bootstrap["preferenceTokenB"])
        self.assertTrue(session.accept_result(RESULT_CAPABILITY, 1))
        self.assertTrue(session.accept_ready(RESULT_CAPABILITY, 1))
        session.arm_phase_two(100.0)
        self.assertTrue(
            session.observe_top_level_root_navigation(
                RESULT_CAPABILITY,
                SESSION_CAPABILITY,
                "document",
                "navigate",
            )
        )
        second_evidence = smoke.DocumentEvidence("reload", 101.0)
        self.assertTrue(session.accept_document(SESSION_CAPABILITY, second_evidence))
        session.acknowledge_document(SESSION_CAPABILITY)
        second_bootstrap = session.bootstrap_payload(SESSION_CAPABILITY)
        self.assertEqual(second_bootstrap["ordinal"], 2)
        self.assertEqual(
            second_bootstrap["localStorageToken"], escrow.local_storage
        )
        self.assertEqual(
            second_bootstrap["preferenceTokenB"], escrow.preference_b
        )
        self.assertTrue(session.accept_result(RESULT_CAPABILITY, 2))
        self.assertTrue(session.accept_ready(RESULT_CAPABILITY, 2))
        session.arm_phase_three(101.0)
        self.assertTrue(
            session.observe_top_level_root_navigation(
                RESULT_CAPABILITY,
                SESSION_CAPABILITY,
                "document",
                "navigate",
            )
        )
        third_evidence = smoke.DocumentEvidence("reload", 102.0)
        self.assertTrue(session.accept_document(SESSION_CAPABILITY, third_evidence))
        session.acknowledge_document(SESSION_CAPABILITY)
        third_bootstrap = session.bootstrap_payload(SESSION_CAPABILITY)
        self.assertEqual(third_bootstrap["ordinal"], 3)
        self.assertIsNone(third_bootstrap["preferenceTokenA"])
        self.assertEqual(third_bootstrap["preferenceTokenB"], escrow.preference_b)
        self.assertEqual(third_bootstrap["localStorageToken"], escrow.local_storage)
        with self.assertRaises(smoke.ProtocolStateError):
            session.accept_document(
                SESSION_CAPABILITY, smoke.DocumentEvidence("reload", 103.0)
            )
        self.assertTrue(session.accept_result(RESULT_CAPABILITY, 3))
        self.assertTrue(session.accept_ready(RESULT_CAPABILITY, 3))
        with self.assertRaises(smoke.ProtocolStateError):
            session.accept_result(RESULT_CAPABILITY, 4)

    def test_cdp_issues_only_page_reload_and_requires_a_new_root_loader(self) -> None:
        client = FakeCdpClient()
        baseline = smoke.prepare_outer_document_reload(client)
        replacement = smoke.reload_outer_document(
            client,
            FakeBrowser(),
            deque(),
            baseline,
            "http://127.0.0.1/smoke/",
            __import__("time").monotonic() + 1,
        )
        self.assertEqual(baseline, smoke.RootFrameIdentity("root", "loader-a"))
        self.assertEqual(replacement, smoke.RootFrameIdentity("root", "loader-b"))
        self.assertIsNone(
            smoke._root_reload_event(
                {
                    "method": "Page.frameNavigated",
                    "params": {
                        "frame": {
                            "id": "other-root",
                            "loaderId": "loader-c",
                            "url": "http://127.0.0.1/smoke/?fixed",
                        }
                    },
                },
                baseline=baseline,
                expected_page_url_prefix="http://127.0.0.1/smoke/",
            )
        )
        self.assertEqual(
            client.calls,
            [
                ("Page.enable", None),
                ("Page.getFrameTree", None),
                ("Page.reload", {"ignoreCache": True}),
            ],
        )

    def test_host_and_runner_never_use_host_profile_storage_or_self_navigation(self) -> None:
        host = (
            TOOLS_DIR
            / "host"
            / "chrome_wasm_profile_bookmark_cookie_history_local_storage_outer_reload_smoke.js"
        ).read_text(encoding="utf-8")
        runner = Path(smoke.__file__).read_text(encoding="utf-8")
        for forbidden in (
            "navigator.storage",
            "navigator.locks",
            "window.localStorage",
            "localStorage.",
            "sessionStorage.",
            "indexedDB.",
            "document.cookie",
            "location.reload(",
            "location.replace(",
            "location.assign(",
            "ccall(",
            "getValue(",
            "HEAPU8",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, host)
        self.assertEqual(runner.count('client.call("Page.reload"'), 1)
        self.assertEqual(runner.count("reload_outer_document("), 3)
        self.assertEqual(runner.count("wait_for_page_client("), 1)
        self.assertNotIn("Page.navigate", runner)
        self.assertIn("ordinal == 3", runner)
        self.assertIn("ordinal === 3", host)

    def test_browser_stderr_scans_all_three_raw_escrow_values(self) -> None:
        escrow = smoke.new_token_escrow()
        for raw in (
            escrow.preference_a,
            escrow.preference_b,
            escrow.local_storage,
        ):
            destination: deque[str] = deque()
            seen = threading.Event()
            smoke.drain_browser_stderr([f"prefix {raw} suffix\n"], destination, escrow, seen)
            self.assertTrue(seen.is_set())
            self.assertEqual(list(destination), [smoke.SUPPRESSED_BROWSER_STDERR_TOKEN])

    def test_configuration_requires_the_aggregate_opt_in(self) -> None:
        for valid in (
            b"enable_chromium_wasm_m7_profile_bookmark_cookie_history_local_storage_test=true\n",
            b"enable_chromium_wasm_m7_profile_bookmark_cookie_history_local_storage_test =\n"
            b"    true\n",
        ):
            with self.subTest(valid=valid):
                smoke.validate_m7_output_configuration(valid)
        for invalid in (
            b"",
            b"enable_chromium_wasm_m7_profile_bookmark_cookie_history_local_storage_test=false\n",
            b"enable_chromium_wasm_m7_profile_bookmark_cookie_history_local_storage_test =\n"
            b"    false\n",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(M0Error):
                smoke.validate_m7_output_configuration(invalid)

    def test_final_receipt_is_explicitly_non_gating(self) -> None:
        runner = Path(smoke.__file__).read_text(encoding="utf-8")
        for claim in (
            '"m7GateComplete": False',
            '"crashRecoveryProven": False',
            '"powerLossDurabilityProven": False',
            '"fullProfilePersistenceProven": False',
            '"generalStoragePartitionPersistenceProven": False',
            '"bookmarkModelAReopenReadAndBWriteWithModelClose": True',
            '"bookmarkTransportModeFeatureDisabled": True',
            '"bookmarkBReopenAndCleanupWriteFlushed": True',
            '"bookmarkCleanupFourthReopenProven": False',
            '"bookmarkModelFullServicePersistenceProven": False',
            '"generalCookieRequestPathProven": False',
            '"historyServiceFlushReopenAndBackendClose": True',
            '"normalNavigationHistoryOrHistoryUiProven": False',
            '"historyServiceFullPersistenceProven": False',
            '"sharedActualDrainPerModule": True',
            '"tokenDigests"',
        ):
            with self.subTest(claim=claim):
                self.assertIn(claim, runner)


if __name__ == "__main__":
    unittest.main()
