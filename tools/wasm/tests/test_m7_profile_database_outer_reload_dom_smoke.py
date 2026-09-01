#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the M7 two-outer-document database smoke runner."""

from __future__ import annotations

import ast
import copy
from collections import deque
from contextlib import contextmanager
import http.client
import io
import json
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest import mock


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m7_chrome_profile_database_outer_reload_dom_smoke as smoke


VERSIONS = {
    "chromium": "a" * 40,
    "v8": "b" * 40,
    "emscripten": "c" * 40,
}
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
ORIGIN = "http://127.0.0.1:43127"
RESULT_CAPABILITY = "r" * 32
SESSION_CAPABILITY = "s" * 32


def escrow_token_matches(value: object, expected: str) -> bool:
    """Compare an escrow value without letting unittest render either token."""

    return isinstance(value, str) and secrets.compare_digest(value, expected)


def passing_run(ordinal: int, escrow: smoke.TokenEscrow) -> dict[str, object]:
    markers = smoke.expected_markers(ordinal, escrow)
    return {
        "abort": None,
        "activeClearedAfterLifecycle": True,
        "expectedExitStatusObserved": False,
        "factoryError": None,
        "factorySettled": True,
        "freshModuleObject": True,
        "leaseReleasedMarkerObserved": True,
        "markerCount": len(markers),
        # Delivery can lag the synchronous native process-exit report.
        "markerDeliveryCompleteAtProcessExit": False,
        "markerSequenceAccepted": True,
        "markerSource": "stderr-only",
        "markers": markers,
        "mode": "write-a" if ordinal == 1 else "verify-a-write-b",
        "moduleIdentity": ("4" if ordinal == 1 else "5") * 32,
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
    ordinal: int,
    escrow: smoke.TokenEscrow,
    time_origin: float,
    *,
    navigation_type: str | None = None,
) -> dict[str, object]:
    return {
        "protocol": 1,
        "case": smoke.CASE,
        "scope": smoke.SCOPE,
        "status": "pass",
        "ordinal": ordinal,
        "mode": "write-a" if ordinal == 1 else "verify-a-write-b",
        "origin": ORIGIN,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "document": {
            "navigationType": navigation_type or (
                "navigate" if ordinal == 1 else "reload"
            ),
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
            "wasmDataInspectionAttempted": False,
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
    result: dict[str, object],
    escrow: smoke.TokenEscrow,
    ordinal: int,
    *,
    expected_document: smoke.DocumentEvidence | None = None,
) -> smoke.PhaseResult:
    document = result["document"]
    assert isinstance(document, dict)
    if expected_document is None:
        expected_document = smoke.DocumentEvidence(
            "navigate" if ordinal == 1 else "reload",
            float(document["timeOrigin"]),
        )
    return smoke.validate_phase_result(
        result,
        ordinal=ordinal,
        expected_versions=VERSIONS,
        expected_artifact_identity=ARTIFACT_IDENTITY,
        expected_capture_harness_identity=CAPTURE_HARNESS_IDENTITY,
        expected_origin=ORIGIN,
        expected_document=expected_document,
        escrow=escrow,
        result_token=RESULT_CAPABILITY,
        session=SESSION_CAPABILITY,
    )


def ready_receipt(ordinal: int, time_origin: float) -> dict[str, object]:
    return {
        "protocol": 1,
        "case": smoke.CASE,
        "scope": smoke.SCOPE,
        "ordinal": ordinal,
        "timeOrigin": time_origin,
    }


def bootstrap_document_receipt(navigation_type: str, time_origin: float) -> bytes:
    return json.dumps(
        {
            "protocol": 1,
            "case": smoke.CASE,
            "scope": smoke.SCOPE,
            "navigationType": navigation_type,
            "timeOrigin": time_origin,
        },
        separators=(",", ":"),
    ).encode("utf-8")


@contextmanager
def temporary_server(*, phase_two_navigation_type: str = "reload"):
    """Start a fully snapshotted server with tiny regular-file fixtures."""

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        out_dir = root / "out"
        host_dir = root / "host"
        out_dir.mkdir()
        host_dir.mkdir()
        (out_dir / "args.gn").write_text(
            "enable_chromium_wasm_m7_profile_database_test=true\n",
            encoding="utf-8",
        )
        (out_dir / f"{smoke.PRODUCT_MODULE_NAME}.js").write_bytes(b"export{}\n")
        (out_dir / f"{smoke.PRODUCT_MODULE_NAME}.wasm").write_bytes(
            b"\x00asm\x01\x00\x00\x00"
        )
        (host_dir / smoke.HOST_HTML_NAME).write_bytes(b"<!doctype html>\n")
        (host_dir / smoke.HOST_JS_NAME).write_bytes(b"export {};\n")
        runner_source = root / "runner.py"
        runner_source.write_bytes(b"# test runner source\n")
        escrow = smoke.new_token_escrow()
        server = smoke.create_server(
            "127.0.0.1",
            0,
            out_dir,
            RESULT_CAPABILITY,
            SESSION_CAPABILITY,
            escrow,
            host_dir=host_dir,
            runner_source_path=runner_source,
            phase_two_navigation_type=phase_two_navigation_type,
        )
        thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        thread.start()
        try:
            yield server, escrow
        finally:
            smoke._stop_server(server, thread, True)


def request(
    server: smoke.ChromeProfileDatabaseOuterReloadServer,
    method: str,
    path: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    host, port = server.server_address[:2]
    connection = http.client.HTTPConnection(host, port, timeout=5)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return (
            response.status,
            {name.lower(): value for name, value in response.getheaders()},
            response.read(),
        )
    finally:
        connection.close()


def minimal_receipt(ordinal: int) -> bytes:
    return json.dumps(
        {
            "protocol": 1,
            "case": smoke.CASE,
            "scope": smoke.SCOPE,
            "ordinal": ordinal,
        },
        separators=(",", ":"),
    ).encode("utf-8")


class FakeReloadClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object] | None]] = []
        self.events: list[dict[str, object]] = [
            {
                "method": "Page.frameNavigated",
                "params": {
                    "frame": {
                        "id": "root-frame",
                        # Page.enable can leave a same-document event queued.
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
        self.closed = False

    def call(
        self, method: str, params: dict[str, object] | None = None
    ) -> dict[str, object]:
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
        return {}

    def next_event(self, _idle_timeout_seconds: float) -> dict[str, object] | None:
        return self.events.pop(0) if self.events else None

    def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def poll(self) -> None:
        return None


class M7ProfileDatabaseOuterReloadDomSmokeTest(unittest.TestCase):
    def assert_security_headers(self, headers: dict[str, str]) -> None:
        self.assertEqual(headers.get("cache-control"), "no-store")
        self.assertEqual(headers.get("referrer-policy"), "no-referrer")
        self.assertEqual(headers.get("cross-origin-opener-policy"), "same-origin")
        self.assertEqual(
            headers.get("cross-origin-embedder-policy"), "require-corp"
        )
        self.assertEqual(
            headers.get("cross-origin-resource-policy"), "same-origin"
        )
        self.assertEqual(headers.get("x-content-type-options"), "nosniff")

    def test_output_configuration_rejects_sqlite_recovery_artifact(self) -> None:
        valid = (
            b"enable_chromium_wasm_m7_profile_database_test=true\n"
            b"enable_chromium_wasm_m7_profile_database_abort_pc_diagnostic=false\n"
            b"enable_chromium_wasm_m7_profile_database_sqlite_recovery_test=false\n"
        )
        smoke.validate_m7_output_configuration(valid)
        with self.assertRaises(M0Error):
            smoke.validate_m7_output_configuration(
                valid.replace(
                    b"enable_chromium_wasm_m7_profile_database_sqlite_recovery_test=false",
                    b"enable_chromium_wasm_m7_profile_database_sqlite_recovery_test=true",
                )
            )

    def test_escrow_requires_document_evidence_and_both_phase_two_gates(self) -> None:
        escrow = smoke.new_token_escrow()
        state = smoke.OuterReloadSession(
            RESULT_CAPABILITY, SESSION_CAPABILITY, escrow
        )

        first_evidence = smoke.DocumentEvidence("navigate", 1000.0)
        self.assertFalse(
            state.accept_bootstrap_document("not-a-session-capability", first_evidence)
        )
        self.assertTrue(
            state.accept_bootstrap_document(SESSION_CAPABILITY, first_evidence)
        )
        # The POST acknowledgement boundary must finish before GET can obtain A.
        with self.assertRaises(smoke.ProtocolStateError):
            state.bootstrap_payload(SESSION_CAPABILITY)
        self.assertTrue(state.acknowledge_bootstrap_document(SESSION_CAPABILITY))
        first = state.bootstrap_payload(SESSION_CAPABILITY)
        self.assertTrue(isinstance(first, dict), "phase-one bootstrap was absent")
        assert isinstance(first, dict)
        self.assertTrue(first["ordinal"] == 1, "phase-one ordinal was invalid")
        self.assertTrue(first["mode"] == "write-a", "phase-one mode was invalid")
        self.assertTrue(
            escrow_token_matches(first["tokenA"], escrow.token_a),
            "phase-one escrow token did not match",
        )
        self.assertTrue(first["tokenB"] is None, "phase-one token B was present")
        self.assertTrue(
            first["tokenADigest"] == escrow.token_a_digest,
            "phase-one token A digest was invalid",
        )
        self.assertTrue(
            first["tokenBDigest"] is None, "phase-one token B digest was present"
        )
        self.assertTrue(
            state.bootstrap_payload("not-a-session-capability") is None,
            "unknown session received a bootstrap body",
        )
        with self.assertRaises(smoke.ProtocolStateError):
            state.bootstrap_payload(SESSION_CAPABILITY)
        with self.assertRaises(smoke.ProtocolStateError):
            state.accept_result(RESULT_CAPABILITY, 2)

        self.assertTrue(state.accept_result(RESULT_CAPABILITY, 1))
        with self.assertRaises(smoke.ProtocolStateError):
            state.accept_result(RESULT_CAPABILITY, 1)
        self.assertTrue(state.accept_ready(RESULT_CAPABILITY, 1))
        with self.assertRaises(smoke.ProtocolStateError):
            state.bootstrap_payload(SESSION_CAPABILITY)

        state.arm_phase_two_document_evidence(first_evidence.time_origin)
        # The armed state alone cannot let document one take B.
        with self.assertRaises(smoke.ProtocolStateError):
            state.bootstrap_payload(SESSION_CAPABILITY)
        with self.assertRaises(smoke.ProtocolStateError):
            state.accept_bootstrap_document(
                SESSION_CAPABILITY, smoke.DocumentEvidence("reload", 1001.0)
            )
        self.assertFalse(
            state.observe_top_level_root_navigation(
                result_token=RESULT_CAPABILITY,
                session=SESSION_CAPABILITY,
                fetch_destination="empty",
                fetch_mode="navigate",
            )
        )
        self.assertFalse(
            state.observe_top_level_root_navigation(
                result_token=RESULT_CAPABILITY,
                session=SESSION_CAPABILITY,
                fetch_destination="document",
                fetch_mode="same-origin",
            )
        )
        self.assertFalse(
            state.observe_top_level_root_navigation(
                result_token="unrelated-result-token",
                session=SESSION_CAPABILITY,
                fetch_destination="document",
                fetch_mode="navigate",
            )
        )
        self.assertTrue(
            state.observe_top_level_root_navigation(
                result_token=RESULT_CAPABILITY,
                session=SESSION_CAPABILITY,
                fetch_destination="document",
                fetch_mode="navigate",
            )
        )
        with self.assertRaises(smoke.ProtocolStateError):
            state.accept_bootstrap_document(
                SESSION_CAPABILITY, smoke.DocumentEvidence("navigate", 1001.0)
            )
        with self.assertRaises(smoke.ProtocolStateError):
            state.accept_bootstrap_document(
                SESSION_CAPABILITY, smoke.DocumentEvidence("reload", 1000.0)
            )
        second_evidence = smoke.DocumentEvidence("reload", 1001.0)
        self.assertTrue(
            state.accept_bootstrap_document(SESSION_CAPABILITY, second_evidence)
        )
        with self.assertRaises(smoke.ProtocolStateError):
            state.bootstrap_payload(SESSION_CAPABILITY)
        self.assertTrue(state.acknowledge_bootstrap_document(SESSION_CAPABILITY))
        second = state.bootstrap_payload(SESSION_CAPABILITY)
        self.assertTrue(isinstance(second, dict), "phase-two bootstrap was absent")
        assert isinstance(second, dict)
        self.assertTrue(second["ordinal"] == 2, "phase-two ordinal was invalid")
        self.assertTrue(
            second["mode"] == "verify-a-write-b", "phase-two mode was invalid"
        )
        self.assertTrue(
            escrow_token_matches(second["tokenA"], escrow.token_a),
            "phase-two token A did not match",
        )
        self.assertTrue(
            escrow_token_matches(second["tokenB"], escrow.token_b),
            "phase-two token B did not match",
        )
        self.assertTrue(
            second["tokenBDigest"] == escrow.token_b_digest,
            "phase-two token B digest was invalid",
        )

    def test_accepts_fresh_outer_browser_phase_two_navigation(self) -> None:
        with temporary_server(phase_two_navigation_type="navigate") as (server, escrow):
            session = server.session
            self.assertTrue(
                session.accept_bootstrap_document(
                    SESSION_CAPABILITY, smoke.DocumentEvidence("navigate", 100.0)
                )
            )
            session.acknowledge_bootstrap_document(SESSION_CAPABILITY)
            first_bootstrap = session.bootstrap_payload(SESSION_CAPABILITY)
            assert isinstance(first_bootstrap, dict)
            self.assertEqual(first_bootstrap["expectedNavigationType"], "navigate")
            self.assertTrue(session.accept_result(RESULT_CAPABILITY, 1))
            self.assertTrue(session.accept_ready(RESULT_CAPABILITY, 1))
            session.arm_phase_two_document_evidence(100.0)
            self.assertTrue(
                session.observe_top_level_root_navigation(
                    result_token=RESULT_CAPABILITY,
                    session=SESSION_CAPABILITY,
                    fetch_destination="document",
                    fetch_mode="navigate",
                )
            )
            self.assertTrue(
                session.accept_bootstrap_document(
                    SESSION_CAPABILITY, smoke.DocumentEvidence("navigate", 101.0)
                )
            )
            session.acknowledge_bootstrap_document(SESSION_CAPABILITY)
            bootstrap = session.bootstrap_payload(SESSION_CAPABILITY)
            assert isinstance(bootstrap, dict)
            self.assertEqual(bootstrap["ordinal"], 2)
            self.assertEqual(bootstrap["expectedNavigationType"], "navigate")

            phase = validate_result(
                passing_result(2, escrow, 101.0, navigation_type="navigate"),
                escrow,
                2,
                expected_document=smoke.DocumentEvidence("navigate", 101.0),
            )
            self.assertEqual(phase.navigation_type, "navigate")
            smoke.validate_outer_document_transition(
                smoke.PhaseResult(1, ORIGIN, "navigate", 100.0, "1" * 32),
                phase,
                phase_two_navigation_type="navigate",
            )

    def test_fresh_outer_browser_mode_rejects_reload_phase_two_evidence(self) -> None:
        with temporary_server(phase_two_navigation_type="navigate") as (server, _escrow):
            session = server.session
            self.assertTrue(
                session.accept_bootstrap_document(
                    SESSION_CAPABILITY, smoke.DocumentEvidence("navigate", 100.0)
                )
            )
            session.acknowledge_bootstrap_document(SESSION_CAPABILITY)
            self.assertIsNotNone(session.bootstrap_payload(SESSION_CAPABILITY))
            self.assertTrue(session.accept_result(RESULT_CAPABILITY, 1))
            self.assertTrue(session.accept_ready(RESULT_CAPABILITY, 1))
            session.arm_phase_two_document_evidence(100.0)
            self.assertTrue(
                session.observe_top_level_root_navigation(
                    result_token=RESULT_CAPABILITY,
                    session=SESSION_CAPABILITY,
                    fetch_destination="document",
                    fetch_mode="navigate",
                )
            )
            with self.assertRaises(smoke.ProtocolStateError):
                session.accept_bootstrap_document(
                    SESSION_CAPABILITY, smoke.DocumentEvidence("reload", 101.0)
                )

    def test_rejects_invalid_or_mismatched_phase_two_navigation_contract(self) -> None:
        escrow = smoke.new_token_escrow()
        with self.assertRaises(M0Error):
            smoke.OuterReloadSession(
                RESULT_CAPABILITY,
                SESSION_CAPABILITY,
                escrow,
                phase_two_navigation_type="back_forward",
            )
        with self.assertRaises(M0Error):
            smoke.validate_outer_document_transition(
                smoke.PhaseResult(1, ORIGIN, "navigate", 100.0, "1" * 32),
                smoke.PhaseResult(2, ORIGIN, "reload", 101.0, "2" * 32),
                phase_two_navigation_type="navigate",
            )

    def test_fresh_outer_browser_persistence_claim_requires_every_evidence_edge(
        self,
    ) -> None:
        complete = {
            "outer_browser_processes_started": 2,
            "first_outer_browser_close": smoke.OuterBrowserCloseEvidence(
                True, True, True, True
            ),
            "second_outer_browser_identity_distinct": True,
            "same_outer_profile_for_phase_two": True,
            "same_origin_for_phase_two": True,
            "phase_two_navigation_type": "navigate",
            "phase_two": smoke.PhaseResult(
                2, ORIGIN, "navigate", 101.0, "2" * 32
            ),
            "phase_two_sqlite_and_leveldb_read_a_validated": True,
            "phase_two_fresh_document_time_origin": True,
        }
        self.assertTrue(
            smoke.has_fresh_outer_browser_database_persistence_evidence(**complete)
        )
        incomplete_cases = {
            "one-process": {"outer_browser_processes_started": 1},
            "no-close": {"first_outer_browser_close": None},
            "no-close-ack": {
                "first_outer_browser_close": smoke.OuterBrowserCloseEvidence(
                    False, True, True, True
                )
            },
            "nonzero-exit": {
                "first_outer_browser_close": smoke.OuterBrowserCloseEvidence(
                    True, False, True, True
                )
            },
            "stderr-not-eof": {
                "first_outer_browser_close": smoke.OuterBrowserCloseEvidence(
                    True, True, False, True
                )
            },
            "process-group-remains": {
                "first_outer_browser_close": smoke.OuterBrowserCloseEvidence(
                    True, True, True, False
                )
            },
            "same-pid": {"second_outer_browser_identity_distinct": False},
            "different-profile": {"same_outer_profile_for_phase_two": False},
            "different-origin": {"same_origin_for_phase_two": False},
            "reload-contract": {"phase_two_navigation_type": "reload"},
            "reload-document": {
                "phase_two": smoke.PhaseResult(
                    2, ORIGIN, "reload", 101.0, "2" * 32
                )
            },
            "no-sqlite-leveldb-read-a": {
                "phase_two_sqlite_and_leveldb_read_a_validated": False
            },
            "no-fresh-time-origin": {"phase_two_fresh_document_time_origin": False},
        }
        for label, replacement in incomplete_cases.items():
            with self.subTest(label=label):
                candidate = dict(complete)
                candidate.update(replacement)
                self.assertFalse(
                    smoke.has_fresh_outer_browser_database_persistence_evidence(
                        **candidate
                    )
                )

    def test_fresh_outer_pass_claim_is_source_selected_and_non_gating(self) -> None:
        source = (
            TOOLS_DIR / "run_m7_chrome_profile_database_outer_reload_dom_smoke.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "freshOuterBrowserProcessSourceSelectedSqliteLevelDbPersistenceProven",
            source,
        )
        self.assertNotIn(
            "normalDatabasePersistenceAcrossFreshOuterBrowserProven", source
        )
        self.assertIn('"m7GateComplete": False', source)
        self.assertIn('"fullChromiumProfileProven": False', source)
        self.assertIn('"physicalCrashBehaviorProven": False', source)

    def test_bootstrap_get_waits_for_acknowledgement_gate_commit(self) -> None:
        escrow = smoke.new_token_escrow()
        state = smoke.OuterReloadSession(
            RESULT_CAPABILITY, SESSION_CAPABILITY, escrow
        )
        attempted = threading.Event()
        received: list[object] = []
        errors: list[BaseException] = []

        def claim_bootstrap() -> None:
            attempted.set()
            try:
                received.append(state.bootstrap_payload(SESSION_CAPABILITY))
            except Exception as error:  # pragma: no cover - diagnostic only.
                errors.append(error)

        with state.bootstrap_acknowledgement_gate():
            self.assertTrue(
                state.accept_bootstrap_document(
                    SESSION_CAPABILITY, smoke.DocumentEvidence("navigate", 1000.0)
                )
            )
            getter = threading.Thread(target=claim_bootstrap)
            getter.start()
            self.assertTrue(attempted.wait(1.0), "GET worker did not start")
            self.assertTrue(
                not received, "GET resolved before bootstrap acknowledgement commit"
            )
            self.assertTrue(
                state.acknowledge_bootstrap_document(SESSION_CAPABILITY)
            )
        getter.join(timeout=1.0)
        self.assertFalse(getter.is_alive(), "GET worker did not finish")
        self.assertTrue(not errors, "GET worker raised")
        self.assertEqual(len(received), 1)
        payload = received[0]
        self.assertTrue(isinstance(payload, dict), "GET did not receive a payload")
        assert isinstance(payload, dict)
        self.assertTrue(
            escrow_token_matches(payload.get("tokenA"), escrow.token_a),
            "gated bootstrap token did not match",
        )

    def test_server_bootstrap_get_cannot_race_a_flushed_acknowledgement(self) -> None:
        with temporary_server() as (server, escrow):
            bootstrap_path = f"{smoke.HOST_ROOT}/bootstrap/{SESSION_CAPABILITY}"
            json_headers = {"Content-Type": "application/json"}
            acknowledgement_entered = threading.Event()
            release_acknowledgement = threading.Event()
            payload_entered = threading.Event()
            get_finished = threading.Event()
            post_responses: list[tuple[int, dict[str, str], bytes]] = []
            get_responses: list[tuple[int, dict[str, str], bytes]] = []
            errors: list[Exception] = []
            original_acknowledgement = server.session.acknowledge_bootstrap_document
            original_payload = server.session.bootstrap_payload

            def delayed_acknowledgement(session: str) -> bool:
                acknowledgement_entered.set()
                if not release_acknowledgement.wait(1.0):
                    raise RuntimeError("bootstrap acknowledgement release timed out")
                return original_acknowledgement(session)

            def observed_payload(session: str) -> dict[str, object] | None:
                payload_entered.set()
                return original_payload(session)

            server.session.acknowledge_bootstrap_document = delayed_acknowledgement
            server.session.bootstrap_payload = observed_payload

            def post_evidence() -> None:
                try:
                    post_responses.append(
                        request(
                            server,
                            "POST",
                            bootstrap_path,
                            bootstrap_document_receipt("navigate", 1000.0),
                            json_headers,
                        )
                    )
                except Exception as error:  # pragma: no cover - diagnostic only.
                    errors.append(error)

            def get_bootstrap() -> None:
                try:
                    get_responses.append(request(server, "GET", bootstrap_path))
                except Exception as error:  # pragma: no cover - diagnostic only.
                    errors.append(error)
                finally:
                    get_finished.set()

            post_thread = threading.Thread(target=post_evidence)
            get_thread: threading.Thread | None = None
            post_thread.start()
            try:
                self.assertTrue(
                    acknowledgement_entered.wait(1.0),
                    "POST did not reach the post-flush acknowledgement seam",
                )
                get_thread = threading.Thread(target=get_bootstrap)
                get_thread.start()
                self.assertTrue(
                    payload_entered.wait(1.0), "concurrent GET did not reach gate"
                )
                self.assertTrue(
                    not get_finished.is_set(),
                    "concurrent GET returned before acknowledgement commit",
                )
                self.assertTrue(
                    not get_responses,
                    "concurrent GET received a precommit bootstrap response",
                )
            finally:
                release_acknowledgement.set()
                post_thread.join(timeout=1.0)
                if get_thread is not None:
                    get_thread.join(timeout=1.0)

            self.assertFalse(post_thread.is_alive(), "POST worker did not finish")
            assert get_thread is not None
            self.assertFalse(get_thread.is_alive(), "GET worker did not finish")
            self.assertTrue(not errors, "bootstrap race worker raised")
            self.assertTrue(
                len(post_responses) == 1, "POST did not receive one acknowledgement"
            )
            self.assertTrue(
                len(get_responses) == 1, "GET did not receive one bootstrap response"
            )
            post_status, post_headers, post_body = post_responses[0]
            self.assertTrue(post_status == 204, "evidence POST was not acknowledged")
            self.assertTrue(post_body == b"", "evidence POST response had a body")
            self.assert_security_headers(post_headers)
            get_status, get_headers, get_body = get_responses[0]
            self.assertTrue(get_status == 200, "GET did not wait for committed bootstrap")
            self.assert_security_headers(get_headers)
            payload = json.loads(get_body)
            self.assertTrue(isinstance(payload, dict), "committed bootstrap was invalid")
            assert isinstance(payload, dict)
            self.assertTrue(
                escrow_token_matches(payload.get("tokenA"), escrow.token_a),
                "post-commit bootstrap token did not match",
            )

    def test_server_routes_enforce_one_shot_two_phase_receipts_and_headers(self) -> None:
        with temporary_server() as (server, escrow):
            smoke.verify_server_delivery(server)
            bootstrap_path = f"{smoke.HOST_ROOT}/bootstrap/{SESSION_CAPABILITY}"
            json_headers = {"Content-Type": "application/json"}

            # Bootstrap is POST evidence followed by GET body, never a
            # capability-only GET that could be consumed by document one.
            status, headers, body = request(server, "GET", bootstrap_path)
            self.assertEqual(status, 409)
            self.assert_security_headers(headers)
            self.assertTrue(
                body == b"outer-reload endpoint state conflict\n",
                "initial bootstrap conflict body was invalid",
            )
            status, headers, body = request(
                server,
                "POST",
                bootstrap_path,
                bootstrap_document_receipt("navigate", 1000.0),
                json_headers,
            )
            self.assertEqual(status, 204)
            self.assertTrue(body == b"", "phase-one evidence response had a body")
            self.assert_security_headers(headers)
            status, headers, body = request(server, "GET", bootstrap_path)
            self.assertEqual(status, 200)
            self.assert_security_headers(headers)
            first = json.loads(body)
            self.assertTrue(isinstance(first, dict), "phase-one bootstrap was invalid")
            assert isinstance(first, dict)
            self.assertTrue(
                escrow_token_matches(first["tokenA"], escrow.token_a),
                "phase-one server token did not match",
            )
            self.assertTrue(first["tokenB"] is None, "phase-one server token B was present")

            status, _, _ = request(server, "GET", bootstrap_path)
            self.assertEqual(status, 409)
            result_path = f"{smoke.HOST_ROOT}/result/{RESULT_CAPABILITY}/1"
            status, headers, _ = request(
                server, "POST", result_path, minimal_receipt(1), json_headers
            )
            self.assertEqual(status, 204)
            self.assert_security_headers(headers)
            status, _, _ = request(
                server, "POST", result_path, minimal_receipt(1), json_headers
            )
            self.assertEqual(status, 409)

            ready_path = f"{smoke.HOST_ROOT}/ready/{RESULT_CAPABILITY}/1"
            status, headers, _ = request(
                server, "POST", ready_path, minimal_receipt(1), json_headers
            )
            self.assertEqual(status, 204)
            self.assert_security_headers(headers)

            # Runner validation arms only the second document's evidence.  B
            # remains unavailable until a fresh browser top-level navigation.
            server.session.arm_phase_two_document_evidence(1000.0)
            matching_root_path = (
                f"{smoke.HOST_ROOT}/?resultToken={RESULT_CAPABILITY}"
                f"&session={SESSION_CAPABILITY}"
            )
            unrelated_root_path = (
                f"{smoke.HOST_ROOT}/?resultToken={'u' * 32}"
                f"&session={SESSION_CAPABILITY}"
            )
            status, _, _ = request(server, "GET", bootstrap_path)
            self.assertEqual(status, 409)
            status, _, _ = request(
                server,
                "POST",
                bootstrap_path,
                bootstrap_document_receipt("reload", 1001.0),
                json_headers,
            )
            self.assertEqual(status, 409)
            status, headers, _ = request(
                server,
                "GET",
                matching_root_path,
                headers={
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "same-origin",
                },
            )
            self.assertEqual(status, 200)
            self.assert_security_headers(headers)
            status, _, _ = request(server, "GET", bootstrap_path)
            self.assertEqual(status, 409)
            status, headers, _ = request(
                server,
                "GET",
                unrelated_root_path,
                headers={
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                },
            )
            self.assertEqual(status, 200)
            self.assert_security_headers(headers)
            status, _, _ = request(server, "GET", bootstrap_path)
            self.assertEqual(status, 409)
            status, headers, _ = request(
                server,
                "GET",
                matching_root_path,
                headers={
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                },
            )
            self.assertEqual(status, 200)
            self.assert_security_headers(headers)
            status, headers, body = request(
                server,
                "POST",
                bootstrap_path,
                bootstrap_document_receipt("reload", 1001.0),
                json_headers,
            )
            self.assertEqual(status, 204)
            self.assertTrue(body == b"", "phase-two evidence response had a body")
            self.assert_security_headers(headers)
            status, headers, body = request(server, "GET", bootstrap_path)
            self.assertEqual(status, 200)
            self.assert_security_headers(headers)
            second = json.loads(body)
            self.assertTrue(isinstance(second, dict), "phase-two bootstrap was invalid")
            assert isinstance(second, dict)
            self.assertTrue(second["ordinal"] == 2, "phase-two ordinal was invalid")
            self.assertTrue(
                escrow_token_matches(second["tokenA"], escrow.token_a),
                "phase-two server token A did not match",
            )
            self.assertTrue(
                escrow_token_matches(second["tokenB"], escrow.token_b),
                "phase-two server token B did not match",
            )

            unknown = f"{smoke.HOST_ROOT}/result/{'x' * 32}/2"
            status, _, _ = request(
                server, "POST", unknown, minimal_receipt(2), json_headers
            )
            self.assertEqual(status, 404)

    def test_url_transports_only_capabilities_and_not_database_values(self) -> None:
        with temporary_server() as (server, escrow):
            artifact = smoke.artifact_identity(server)
            capture = smoke.capture_harness_identity(server)
            url = smoke.smoke_url(
                server,
                RESULT_CAPABILITY,
                SESSION_CAPABILITY,
                VERSIONS,
                artifact=artifact,
                capture_harness=capture,
                timeout_seconds=30.0,
            )
            parsed = urlsplit(url)
            query = parse_qs(parsed.query, keep_blank_values=True)
            self.assertEqual(
                set(query),
                {
                    "resultToken",
                    "session",
                    "module",
                    "timeoutMs",
                    "versions",
                    "artifact",
                    "captureHarness",
                },
            )
            self.assertEqual(query["resultToken"], [RESULT_CAPABILITY])
            self.assertEqual(query["session"], [SESSION_CAPABILITY])
            self.assertTrue(
                escrow.token_a not in url, "token A appeared in the smoke URL"
            )
            self.assertTrue(
                escrow.token_b not in url, "token B appeared in the smoke URL"
            )
            self.assertNotIn("ordinal", query)
            self.assertNotIn("mode", query)

    def test_phase_validator_requires_reload_and_redacts_raw_database_values(self) -> None:
        escrow = smoke.new_token_escrow()
        first = passing_result(1, escrow, 1000.25)
        second = passing_result(2, escrow, 1001.25)
        first_receipt = validate_result(first, escrow, 1)
        second_receipt = validate_result(second, escrow, 2)
        smoke.validate_ready_receipt(ready_receipt(1, 1000.25), expected=first_receipt)
        smoke.validate_ready_receipt(ready_receipt(2, 1001.25), expected=second_receipt)
        smoke.validate_outer_document_transition(first_receipt, second_receipt)

        wrong_navigation = copy.deepcopy(second)
        wrong_navigation["document"]["navigationType"] = "navigate"
        with self.assertRaises(M0Error):
            validate_result(wrong_navigation, escrow, 2)

        with self.assertRaises(M0Error):
            validate_result(
                second,
                escrow,
                2,
                expected_document=smoke.DocumentEvidence("reload", 1002.25),
            )

        raw_output = copy.deepcopy(first)
        raw_output["run"]["stdout"].append(escrow.token_a)
        with self.assertRaises(M0Error):
            validate_result(raw_output, escrow, 1)

        forged_stdout = copy.deepcopy(first)
        forged_stdout["run"]["stdout"].append("ordinary-native-stdout")
        with self.assertRaises(M0Error):
            validate_result(forged_stdout, escrow, 1)

        forged_native_output = copy.deepcopy(second)
        forged_native_output["run"]["stderr"].append(
            "/untrusted/native/database-output"
        )
        with self.assertRaises(M0Error):
            validate_result(forged_native_output, escrow, 2)

        wrong_marker = copy.deepcopy(second)
        wrong_marker["run"]["markers"][1] = (
            f"{smoke.M7_DATABASE_MARKER_PREFIX}LEVELDB_READ_A_OK sha256="
            + "0" * 64
        )
        with self.assertRaises(M0Error):
            validate_result(wrong_marker, escrow, 2)

    def test_browser_stderr_scanner_rejects_raw_tokens_without_retaining_them(
        self,
    ) -> None:
        escrow = smoke.new_token_escrow()
        captured: deque[str] = deque()
        raw_token_seen = threading.Event()
        smoke.drain_browser_stderr(
            io.StringIO(f"ordinary browser line\n{escrow.token_a}\n"),
            captured,
            escrow,
            raw_token_seen,
        )
        self.assertTrue(raw_token_seen.is_set())
        self.assertNotIn(escrow.token_a, captured)
        self.assertNotIn(escrow.token_b, captured)
        self.assertEqual(
            list(captured),
            ["ordinary browser line", smoke.SUPPRESSED_BROWSER_STDERR_TOKEN],
        )

    def test_browser_stderr_reader_redacts_before_retaining_a_raw_token(self) -> None:
        escrow = smoke.new_token_escrow()
        captured: deque[str] = deque()
        raw_token_seen = threading.Event()
        reader = smoke.BrowserStderrReader(
            io.StringIO(f"ordinary browser line\n{escrow.token_a}\n"),
            captured,
            name="m7-profile-database-token-hygiene",
            transform_record=lambda record: smoke.redact_browser_stderr_record(
                record, escrow, raw_token_seen
            ),
        )
        reader.start()
        reader.join(timeout=1)

        self.assertTrue(raw_token_seen.is_set())
        self.assertTrue(reader.reached_eof)
        self.assertIsNone(reader.error)
        self.assertNotIn(escrow.token_a, captured)
        self.assertNotIn(escrow.token_b, captured)
        self.assertEqual(
            list(captured),
            ["ordinary browser line", smoke.SUPPRESSED_BROWSER_STDERR_TOKEN],
        )

    def test_clean_outer_browser_close_requires_cdp_ack_and_quiescence(self) -> None:
        browser = mock.Mock()
        browser.poll.return_value = None
        browser.returncode = 0
        reader = mock.Mock()
        reader.reached_eof = True
        launch = smoke.OuterBrowserLaunch(
            browser=browser,
            debug_port=43128,
            profile_path="/tmp/profile",
            url="http://127.0.0.1:43127/",
            stderr_reader=reader,
        )
        page_client = mock.Mock()
        browser_client = mock.Mock()
        browser_client.call.return_value = {}
        with (
            mock.patch.object(
                smoke, "wait_for_browser_client", return_value=browser_client
            ) as wait_for_client,
            mock.patch.object(smoke, "wait_for_browser_group_exit") as wait_for_exit,
        ):
            evidence = smoke.close_outer_browser_cleanly(
                launch, page_client, time.monotonic() + 1
            )

        self.assertEqual(
            evidence,
            smoke.OuterBrowserCloseEvidence(True, True, True, True),
        )
        wait_for_client.assert_called_once_with(43128, mock.ANY)
        browser_client.call.assert_called_once_with("Browser.close")
        browser_client.close.assert_called_once_with()
        page_client.close.assert_called_once_with()
        wait_for_exit.assert_called_once_with(
            browser,
            reader,
            mock.ANY,
            description="outer-reload browser",
        )

    def test_clean_outer_browser_close_rejects_a_nonacknowledgement(self) -> None:
        browser = mock.Mock()
        browser.poll.return_value = None
        reader = mock.Mock()
        launch = smoke.OuterBrowserLaunch(
            browser=browser,
            debug_port=43128,
            profile_path="/tmp/profile",
            url="http://127.0.0.1:43127/",
            stderr_reader=reader,
        )
        page_client = mock.Mock()
        browser_client = mock.Mock()
        browser_client.call.return_value = None
        with (
            mock.patch.object(
                smoke, "wait_for_browser_client", return_value=browser_client
            ),
            mock.patch.object(smoke, "wait_for_browser_group_exit") as wait_for_exit,
            self.assertRaisesRegex(M0Error, "acknowledgement is invalid"),
        ):
            smoke.close_outer_browser_cleanly(
                launch, page_client, time.monotonic() + 1
            )

        browser_client.close.assert_called_once_with()
        page_client.close.assert_called_once_with()
        wait_for_exit.assert_not_called()

    def test_ready_and_transition_validation_fail_closed(self) -> None:
        escrow = smoke.new_token_escrow()
        first = validate_result(passing_result(1, escrow, 2000.0), escrow, 1)
        second = validate_result(passing_result(2, escrow, 2001.0), escrow, 2)
        with self.assertRaises(M0Error):
            smoke.validate_ready_receipt(ready_receipt(1, 1999.0), expected=first)

        stale = smoke.PhaseResult(
            ordinal=2,
            origin=ORIGIN,
            navigation_type="reload",
            time_origin=first.time_origin,
            module_identity=second.module_identity,
        )
        with self.assertRaises(M0Error):
            smoke.validate_outer_document_transition(first, stale)
        reused_module = smoke.PhaseResult(
            ordinal=2,
            origin=ORIGIN,
            navigation_type="reload",
            time_origin=second.time_origin,
            module_identity=first.module_identity,
        )
        with self.assertRaises(M0Error):
            smoke.validate_outer_document_transition(first, reused_module)

    def test_reload_boundary_retains_cdp_and_requires_new_root_loader(self) -> None:
        client = FakeReloadClient()
        baseline = smoke.prepare_outer_document_reload(client)
        observed = smoke.reload_outer_document(
            client,
            FakeBrowser(),
            deque(),
            baseline,
            f"{ORIGIN}{smoke.HOST_ROOT}/",
            time.monotonic() + 1.0,
        )
        self.assertEqual(baseline.frame_id, "root-frame")
        self.assertEqual(baseline.loader_id, "loader-one")
        self.assertEqual(observed.frame_id, baseline.frame_id)
        self.assertEqual(observed.loader_id, "loader-two")
        self.assertEqual(
            client.calls,
            [
                ("Page.enable", None),
                ("Page.getFrameTree", None),
                ("Page.reload", {"ignoreCache": True}),
            ],
        )
        self.assertFalse(client.closed)
        source = (
            TOOLS_DIR / "run_m7_chrome_profile_database_outer_reload_dom_smoke.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("Runtime.evaluate", source)
        self.assertNotIn("Page.navigate", source)

    def test_bootstrap_acknowledgement_flushes_then_commits_under_get_gate(self) -> None:
        source = (
            TOOLS_DIR / "run_m7_chrome_profile_database_outer_reload_dom_smoke.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        handler = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "ChromeProfileDatabaseOuterReloadRequestHandler"
        )
        post_bootstrap = next(
            node
            for node in handler.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_post_bootstrap_document"
        )
        acknowledgement_gate = next(
            node
            for node in post_bootstrap.body
            if isinstance(node, ast.With)
            and isinstance(node.items[0].context_expr, ast.Call)
            and isinstance(node.items[0].context_expr.func, ast.Attribute)
            and node.items[0].context_expr.func.attr
            == "bootstrap_acknowledgement_gate"
        )

        def gate_call(attribute: str) -> ast.Call:
            return next(
                node
                for node in ast.walk(acknowledgement_gate)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == attribute
            )

        send = gate_call("_send_empty")
        flush = gate_call("flush")
        acknowledge = gate_call("acknowledge_bootstrap_document")
        self.assertLess(send.lineno, flush.lineno)
        self.assertLess(flush.lineno, acknowledge.lineno)
        self.assertLess(acknowledge.lineno, acknowledgement_gate.end_lineno)

        session_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "OuterReloadSession"
        )
        bootstrap_payload = next(
            node
            for node in session_class.body
            if isinstance(node, ast.FunctionDef) and node.name == "bootstrap_payload"
        )
        self.assertTrue(
            any(
                isinstance(node, ast.With)
                and isinstance(node.items[0].context_expr, ast.Attribute)
                and node.items[0].context_expr.attr
                == "_bootstrap_acknowledgement_gate"
                for node in bootstrap_payload.body
            ),
            "bootstrap GET no longer waits for the acknowledgement gate",
        )

    def test_ready_claim_flushes_before_queue_notification_outside_lock(self) -> None:
        source = (
            TOOLS_DIR / "run_m7_chrome_profile_database_outer_reload_dom_smoke.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        handler = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "ChromeProfileDatabaseOuterReloadRequestHandler"
        )
        method = next(
            node
            for node in handler.body
            if isinstance(node, ast.FunctionDef) and node.name == "_post_ready"
        )
        receipt_lock = next(
            node for node in method.body if isinstance(node, ast.With)
        )
        accepted_send = next(
            node
            for node in method.body
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "_send_empty"
        )
        flush = next(
            node
            for node in method.body
            if isinstance(node, ast.Try)
            and any(
                isinstance(child, ast.Expr)
                and isinstance(child.value, ast.Call)
                and isinstance(child.value.func, ast.Attribute)
                and child.value.func.attr == "flush"
                for child in node.body
            )
        )
        enqueue = next(
            node
            for node in method.body
            if isinstance(node, ast.Try)
            and any(
                isinstance(child, ast.Expr)
                and isinstance(child.value, ast.Call)
                and isinstance(child.value.func, ast.Attribute)
                and child.value.func.attr == "put_nowait"
                for child in node.body
            )
        )
        lock_call_names = {
            node.func.attr
            for node in ast.walk(receipt_lock)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertFalse(
            {
                "_send_empty",
                "_send_bytes",
                "_conflict",
                "_not_found",
                "flush",
                "write",
            }
            & lock_call_names
        )
        self.assertGreater(accepted_send.lineno, receipt_lock.end_lineno)
        self.assertGreater(flush.lineno, accepted_send.lineno)
        self.assertGreater(enqueue.lineno, flush.end_lineno)


if __name__ == "__main__":
    unittest.main()
