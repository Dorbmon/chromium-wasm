#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the isolated M7 OPFS normal-shutdown DOM smoke."""

from __future__ import annotations

import copy
import http.client
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m7_wasmfs_opfs_shutdown_dom_smoke as smoke
from tools.wasm.tests.m3_source_contract_test_support import source


RESULT_TOKEN = "result-token-for-m7-opfs-shutdown-123456"
RUN_NAMESPACE = "run-namespace-for-m7-opfs-shutdown-123456"
ORIGIN = "http://127.0.0.1:43129"


def passing_runtime() -> dict[str, object]:
    return {
        "factorySettled": True,
        "runtimeInitialized": True,
        "runtimeExitCode": 0,
        "onExitObserved": True,
        "abort": None,
        "onAbortObserved": False,
        "factoryError": None,
        "workerError": None,
        "workerHosted": True,
        "opfsCapability": True,
        "nativeStartObserved": True,
        "completionObserved": True,
        "completionMarker": smoke.COMPLETION_MARKER,
        "completionError": None,
        "atexitObserved": True,
        "atexitMarker": smoke.ATEXIT_MARKER,
        "atexitError": None,
        "terminalReason": "on-exit",
        "postExitBarrierObserved": True,
        "postExitBarrierTurns": smoke.PRE_TERMINAL_WORKER_SETTLEMENT_TURNS,
        "postExitError": None,
        "expectedExitStatusObserved": False,
        "noExitRuntimeRequested": False,
        "noExitRuntimeWorkerObservationObserved": False,
        "noExitRuntimeWorkerObservationTurns": 0,
        "runtimeLifecycle": "normal-exit",
        "stdout": [
            smoke.RUNTIME_START_MARKER,
            smoke.COMPLETION_MARKER,
            smoke.ATEXIT_MARKER,
        ],
        "stderr": [],
    }


def passing_result() -> dict[str, object]:
    return {
        "protocol": 1,
        "case": smoke.CASE,
        "scope": smoke.SCOPE,
        "shutdownScope": smoke.SHUTDOWN_SCOPE,
        "runNamespace": RUN_NAMESPACE,
        "status": "pass",
        "origin": ORIGIN,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "opfsCapability": True,
        "opfsFallbackUsed": False,
        "normalRuntimeShutdownProven": True,
        "runtimeLifecycle": "normal-exit",
        "outerPageResponsive": True,
        "pageTickDelta": 2,
        "pageFrameDelta": 3,
        "pageHeartbeatAnchor": smoke.PAGE_HEARTBEAT_ANCHOR,
        "pageTimerMaxGapMs": 24,
        "pageFrameMaxGapMs": 19,
        "pageHeartbeatMaxGapMs": 24,
        "pageHeartbeatGapLimitMs": smoke.MAX_PAGE_HEARTBEAT_GAP_MS,
        "pageHeartbeatTerminalObserved": True,
        "workerPreTerminalSettlementObserved": True,
        "workerPreTerminalSettlementTurns": smoke.PRE_TERMINAL_WORKER_SETTLEMENT_TURNS,
        "workerPostTerminalMicrotaskObserved": True,
        "workerSelfCloseInitiated": True,
        "workerSelfCloseInitiatedBeforeDisposal": True,
        "postExitPageBarrierObserved": True,
        "postExitPageBarrierTurns": smoke.POST_EXIT_PAGE_BARRIER_TURNS,
        "noExitRuntimeNegativeControlProven": False,
        "noExitRuntimeWorkerObservationObserved": False,
        "noExitRuntimeWorkerObservationTurns": 0,
        "noExitRuntimePageObservationObserved": False,
        "noExitRuntimePageObservationTurns": 0,
        "workerTerminationRequested": True,
        "workerTerminationRequestedAfterCleanResult": True,
        "workerTerminationRequestedForNoExitRuntimeControl": False,
        "profilePersistenceProven": False,
        "fileLockSemanticsProven": False,
        "atomicRecoveryProven": False,
        "databaseRecoveryProven": False,
        "runtime": passing_runtime(),
        "failureDiagnostics": None,
        "error": None,
    }


def no_exit_runtime_negative_control_result() -> dict[str, object]:
    result = passing_result()
    result.update(
        {
            "normalRuntimeShutdownProven": False,
            "noExitRuntimeNegativeControlProven": True,
            "runtimeLifecycle": smoke.NO_EXIT_RUNTIME_LIFECYCLE,
            "workerPreTerminalSettlementObserved": False,
            "workerPreTerminalSettlementTurns": 0,
            "workerPostTerminalMicrotaskObserved": False,
            "workerSelfCloseInitiated": False,
            "workerSelfCloseInitiatedBeforeDisposal": False,
            "postExitPageBarrierObserved": False,
            "postExitPageBarrierTurns": 0,
            "noExitRuntimeWorkerObservationObserved": True,
            "noExitRuntimeWorkerObservationTurns": (
                smoke.NO_EXIT_RUNTIME_WORKER_OBSERVATION_TURNS
            ),
            "noExitRuntimePageObservationObserved": True,
            "noExitRuntimePageObservationTurns": (
                smoke.NO_EXIT_RUNTIME_PAGE_OBSERVATION_TURNS
            ),
            "workerTerminationRequested": True,
            "workerTerminationRequestedAfterCleanResult": False,
            "workerTerminationRequestedForNoExitRuntimeControl": True,
        }
    )
    runtime = result["runtime"]
    assert isinstance(runtime, dict)
    runtime.update(
        {
            "runtimeExitCode": None,
            "onExitObserved": False,
            "atexitObserved": False,
            "atexitMarker": None,
            "terminalReason": smoke.NO_EXIT_RUNTIME_LIFECYCLE,
            "postExitBarrierObserved": False,
            "postExitBarrierTurns": 0,
            "expectedExitStatusObserved": False,
            "noExitRuntimeRequested": True,
            "noExitRuntimeWorkerObservationObserved": True,
            "noExitRuntimeWorkerObservationTurns": (
                smoke.NO_EXIT_RUNTIME_WORKER_OBSERVATION_TURNS
            ),
            "runtimeLifecycle": smoke.NO_EXIT_RUNTIME_LIFECYCLE,
            "stdout": [smoke.RUNTIME_START_MARKER, smoke.COMPLETION_MARKER],
        }
    )
    return result


class M7WasmfsOpfsShutdownDomSmokeTest(unittest.TestCase):
    def test_validate_result_accepts_bounded_normal_exit(self) -> None:
        smoke.validate_result(
            passing_result(),
            expected_run_namespace=RUN_NAMESPACE,
            expected_origin=ORIGIN,
        )

    def test_no_exit_runtime_negative_control_requires_absence_of_teardown(self) -> None:
        result = no_exit_runtime_negative_control_result()
        smoke.validate_no_exit_runtime_negative_control_result(
            result,
            expected_run_namespace=RUN_NAMESPACE,
            expected_origin=ORIGIN,
        )
        with self.assertRaises(M0Error):
            smoke.validate_result(
                result,
                expected_run_namespace=RUN_NAMESPACE,
                expected_origin=ORIGIN,
            )

        for field, value in (
            ("runtime.onExitObserved", True),
            ("runtime.runtimeExitCode", 0),
            ("runtime.atexitObserved", True),
            ("runtime.atexitMarker", smoke.ATEXIT_MARKER),
            (
                "runtime.stdout",
                [
                    smoke.RUNTIME_START_MARKER,
                    smoke.COMPLETION_MARKER,
                    smoke.ATEXIT_MARKER,
                ],
            ),
            ("runtime.abort", "unexpected abort"),
            ("runtime.workerError", "unexpected Worker error"),
            ("runtime.noExitRuntimeWorkerObservationTurns", 1),
            ("noExitRuntimePageObservationObserved", False),
            ("workerTerminationRequestedForNoExitRuntimeControl", False),
        ):
            with self.subTest(field=field):
                invalid = no_exit_runtime_negative_control_result()
                if "." in field:
                    parent, child = field.split(".")
                    nested = invalid[parent]
                    assert isinstance(nested, dict)
                    nested[child] = value
                else:
                    invalid[field] = value
                with self.assertRaises(M0Error):
                    smoke.validate_no_exit_runtime_negative_control_result(
                        invalid,
                        expected_run_namespace=RUN_NAMESPACE,
                        expected_origin=ORIGIN,
                    )

    def test_validate_result_rejects_abort_worker_error_or_missing_shutdown_evidence(self) -> None:
        for field, value in (
            ("runtime.abort", "join failed"),
            ("runtime.workerError", "worker error"),
            ("runtime.runtimeExitCode", 1),
            ("runtime.postExitBarrierObserved", False),
            ("runtime.postExitError", "trailing worker failure"),
            ("runtime.atexitObserved", False),
            ("runtime.atexitError", "late atexit failure"),
            ("workerPreTerminalSettlementObserved", False),
            ("workerPreTerminalSettlementTurns", 1),
            ("workerPostTerminalMicrotaskObserved", False),
            ("workerSelfCloseInitiated", False),
            ("workerSelfCloseInitiatedBeforeDisposal", False),
            ("workerTerminationRequestedAfterCleanResult", False),
            ("noExitRuntimeNegativeControlProven", True),
            ("workerTerminationRequestedForNoExitRuntimeControl", True),
            ("outerPageResponsive", False),
            ("postExitPageBarrierObserved", False),
        ):
            with self.subTest(field=field):
                result = passing_result()
                if "." in field:
                    parent, child = field.split(".")
                    nested = result[parent]
                    assert isinstance(nested, dict)
                    nested[child] = value
                    if child in {
                        "abort",
                        "workerError",
                        "runtimeExitCode",
                        "postExitBarrierObserved",
                        "postExitError",
                        "atexitObserved",
                        "atexitError",
                    }:
                        nested["runtimeLifecycle"] = "not-normal-exit"
                else:
                    result[field] = value
                with self.assertRaises(M0Error):
                    smoke.validate_result(
                        result,
                        expected_run_namespace=RUN_NAMESPACE,
                        expected_origin=ORIGIN,
                    )

    def test_validate_result_rejects_unbounded_terminal_heartbeat(self) -> None:
        for field, value in (
            ("pageTimerMaxGapMs", smoke.MAX_PAGE_HEARTBEAT_GAP_MS + 1),
            ("pageFrameMaxGapMs", smoke.MAX_PAGE_HEARTBEAT_GAP_MS + 1),
            ("pageHeartbeatMaxGapMs", smoke.MAX_PAGE_HEARTBEAT_GAP_MS + 1),
            ("pageHeartbeatTerminalObserved", False),
            ("pageHeartbeatAnchor", "after-worker-launch-only"),
        ):
            with self.subTest(field=field):
                result = passing_result()
                result[field] = value
                if field == "pageTimerMaxGapMs":
                    result["pageHeartbeatMaxGapMs"] = value
                if field == "pageFrameMaxGapMs":
                    result["pageHeartbeatMaxGapMs"] = value
                with self.assertRaises(M0Error):
                    smoke.validate_result(
                        result,
                        expected_run_namespace=RUN_NAMESPACE,
                        expected_origin=ORIGIN,
                    )

    def test_validate_result_rejects_missing_or_unordered_atexit_marker(self) -> None:
        for stdout in (
            [smoke.RUNTIME_START_MARKER, smoke.COMPLETION_MARKER],
            [
                smoke.RUNTIME_START_MARKER,
                smoke.ATEXIT_MARKER,
                smoke.COMPLETION_MARKER,
            ],
        ):
            with self.subTest(stdout=stdout):
                result = passing_result()
                runtime = result["runtime"]
                assert isinstance(runtime, dict)
                runtime["stdout"] = stdout
                with self.assertRaises(M0Error):
                    smoke.validate_result(
                        result,
                        expected_run_namespace=RUN_NAMESPACE,
                        expected_origin=ORIGIN,
                    )

    def test_adversarial_delayed_post_terminal_error_requires_failed_close(self) -> None:
        result = passing_result()
        result.update(
            {
                "status": "fail",
                "normalRuntimeShutdownProven": False,
                "workerPreTerminalSettlementObserved": True,
                "workerPreTerminalSettlementTurns": smoke.PRE_TERMINAL_WORKER_SETTLEMENT_TURNS,
                "workerPostTerminalMicrotaskObserved": False,
                "workerSelfCloseInitiated": False,
                "workerSelfCloseInitiatedBeforeDisposal": False,
                "postExitPageBarrierObserved": False,
                "postExitPageBarrierTurns": 0,
                "workerTerminationRequested": True,
                "workerTerminationRequestedAfterCleanResult": False,
                "failureDiagnostics": {
                    "terminalReceived": True,
                    "workerPreTerminalSettlementObserved": True,
                    "workerPostTerminalMicrotaskObserved": False,
                    "workerSelfCloseInitiated": False,
                    "workerSelfCloseInitiatedBeforeDisposal": False,
                    "workerTerminationRequested": True,
                    "workerTerminationRequestedAfterCleanResult": False,
                    "pageWorkerError": (
                        "M7 OPFS shutdown Worker reported a post-terminal error: "
                        + smoke.ADVERSARIAL_DELAYED_POST_TERMINAL_ERROR
                    ),
                },
                "error": (
                    "M7 OPFS shutdown Worker reported a post-exit error: "
                    + smoke.ADVERSARIAL_DELAYED_POST_TERMINAL_ERROR
                ),
            }
        )
        smoke.validate_adversarial_delayed_post_terminal_error_result(
            result,
            expected_run_namespace=RUN_NAMESPACE,
            expected_origin=ORIGIN,
        )

        result["workerSelfCloseInitiated"] = True
        with self.assertRaises(M0Error):
            smoke.validate_adversarial_delayed_post_terminal_error_result(
                result,
                expected_run_namespace=RUN_NAMESPACE,
                expected_origin=ORIGIN,
            )

    def test_validate_result_rejects_broader_persistence_lock_and_recovery_claims(self) -> None:
        for field in (
            "profilePersistenceProven",
            "fileLockSemanticsProven",
            "atomicRecoveryProven",
            "databaseRecoveryProven",
        ):
            with self.subTest(field=field):
                result = passing_result()
                result[field] = True
                with self.assertRaises(M0Error):
                    smoke.validate_result(
                        result,
                        expected_run_namespace=RUN_NAMESPACE,
                        expected_origin=ORIGIN,
                    )

    def test_result_payload_parser_rejects_duplicate_or_wrong_namespace(self) -> None:
        payload = {
            "protocol": 1,
            "case": smoke.CASE,
            "scope": smoke.SCOPE,
            "runNamespace": RUN_NAMESPACE,
        }
        self.assertEqual(
            smoke.parse_result_payload(
                json.dumps(payload).encode("utf-8"), RUN_NAMESPACE
            ),
            payload,
        )
        self.assertIsNone(
            smoke.parse_result_payload(
                json.dumps({**payload, "runNamespace": "wrong-namespace-123456"}).encode(
                    "utf-8"
                ),
                RUN_NAMESPACE,
            )
        )
        duplicate = (
            b'{"protocol":1,"protocol":1,"case":"'
            + smoke.CASE.encode("utf-8")
            + b'","scope":"'
            + smoke.SCOPE.encode("utf-8")
            + b'","runNamespace":"'
            + RUN_NAMESPACE.encode("utf-8")
            + b'"}'
        )
        self.assertIsNone(smoke.parse_result_payload(duplicate, RUN_NAMESPACE))

    def test_fixed_server_routes_are_isolated_and_coep(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            out_dir = Path(temporary_directory)
            (out_dir / f"{smoke.MODULE_NAME}.js").write_text(
                "export default function() {}\n", encoding="utf-8"
            )
            (out_dir / f"{smoke.MODULE_NAME}.wasm").write_bytes(b"\0asm")
            result_queue: queue.Queue[dict[str, object]] = queue.Queue(maxsize=1)
            server = smoke.create_server(
                "127.0.0.1",
                0,
                out_dir,
                RESULT_TOKEN,
                RUN_NAMESPACE,
                result_queue,
            )
            server_thread = threading.Thread(target=server.serve_forever)
            server_thread.start()
            try:
                host, port = server.server_address[:2]

                def request(
                    method: str,
                    path: str,
                    body: bytes | None = None,
                    headers: dict[str, str] | None = None,
                ) -> tuple[int, dict[str, str], bytes]:
                    connection = http.client.HTTPConnection(host, port, timeout=5)
                    connection.request(method, path, body=body, headers=headers or {})
                    response = connection.getresponse()
                    response_body = response.read()
                    response_headers = dict(response.getheaders())
                    connection.close()
                    return response.status, response_headers, response_body

                status, headers, _ = request("GET", f"{smoke.HOST_ROOT}/")
                self.assertEqual(status, 200)
                self.assertEqual(headers["Cross-Origin-Opener-Policy"], "same-origin")
                self.assertEqual(
                    headers["Cross-Origin-Embedder-Policy"], "require-corp"
                )
                for path in (
                    f"{smoke.HOST_ROOT}/m7_wasmfs_opfs_shutdown_smoke.js",
                    f"{smoke.HOST_ROOT}/m7_wasmfs_opfs_shutdown_smoke_worker.js",
                ):
                    status, headers, _ = request("GET", path)
                    self.assertEqual(status, 200)
                    self.assertEqual(headers["Content-Type"], "text/javascript; charset=utf-8")
                status, headers, _ = request(
                    "GET", f"{smoke.HOST_ROOT}/artifacts/{smoke.MODULE_NAME}.wasm"
                )
                self.assertEqual(status, 200)
                self.assertEqual(headers["Content-Type"], "application/wasm")
                status, _, _ = request(
                    "GET", f"{smoke.HOST_ROOT}/artifacts/not-the-m7-target.js"
                )
                self.assertEqual(status, 404)

                adversarial_url = smoke.smoke_url(
                    server,
                    RESULT_TOKEN,
                    RUN_NAMESPACE,
                    timeout_seconds=30,
                    test_fault=smoke.TEST_FAULT_DELAYED_POST_TERMINAL_ERROR,
                )
                self.assertIn(
                    "testFault=delayed-post-terminal-error", adversarial_url
                )
                no_exit_runtime_url = smoke.smoke_url(
                    server,
                    RESULT_TOKEN,
                    RUN_NAMESPACE,
                    timeout_seconds=30,
                    test_fault=smoke.TEST_FAULT_NO_EXIT_RUNTIME,
                )
                self.assertIn("testFault=no-exit-runtime", no_exit_runtime_url)
                with self.assertRaises(M0Error):
                    smoke.smoke_url(
                        server,
                        RESULT_TOKEN,
                        RUN_NAMESPACE,
                        timeout_seconds=30,
                        test_fault="not-a-supported-test-fault",
                    )

                body = json.dumps(
                    {
                        "protocol": 1,
                        "case": smoke.CASE,
                        "scope": smoke.SCOPE,
                        "runNamespace": RUN_NAMESPACE,
                    }
                ).encode("utf-8")
                endpoint = f"{smoke.HOST_ROOT}/result/{RESULT_TOKEN}"
                status, _, _ = request(
                    "POST", endpoint, body, {"Content-Type": "application/json"}
                )
                self.assertEqual(status, 204)
                status, _, _ = request(
                    "POST", endpoint, body, {"Content-Type": "application/json"}
                )
                self.assertEqual(status, 409)
                self.assertEqual(
                    result_queue.get_nowait(),
                    {
                        "protocol": 1,
                        "case": smoke.CASE,
                        "scope": smoke.SCOPE,
                        "runNamespace": RUN_NAMESPACE,
                    },
                )
            finally:
                server.shutdown()
                server.server_close()
                server_thread.join(timeout=5)

    def test_host_and_worker_keep_opfs_inside_wasmfs_and_dispose_after_onexit(self) -> None:
        host = source("tools/wasm/host/m7_wasmfs_opfs_shutdown_smoke.js")
        worker = source("tools/wasm/host/m7_wasmfs_opfs_shutdown_smoke_worker.js")
        runner = source("tools/wasm/run_m7_wasmfs_opfs_shutdown_dom_smoke.py")

        self.assertIn('const MODULE_NAME = "m7_wasmfs_opfs_shutdown_smoke";', host)
        self.assertIn('new Worker(workerUrl, {name: WORKER_NAME, type: "module"})', host)
        self.assertIn("requestAnimationFrame", host)
        self.assertIn("setInterval", host)
        self.assertIn("MAX_PAGE_HEARTBEAT_GAP_MS = 250", host)
        self.assertIn('anchor: "before-worker-launch-through-terminal"', host)
        self.assertIn("function terminalHeartbeatFailure(heartbeat)", host)
        self.assertIn(
            'for (const field of ["timerMaxGapMs", "frameMaxGapMs", "maxGapMs"])',
            host,
        )
        self.assertIn("activity.observeTerminal()", host)
        self.assertIn("function requirePostExitPageBarrier", host)
        self.assertIn("function requireNoExitRuntimePageObservation", host)
        self.assertIn("function noExitRuntimeNegativeControlFailure(snapshot)", host)
        self.assertIn("function executeNoExitRuntimeNegativeControl(context)", host)
        self.assertIn("NO_EXIT_RUNTIME_WORKER_OBSERVATION_TURNS = 2", host)
        self.assertIn("NO_EXIT_RUNTIME_PAGE_OBSERVATION_TURNS = 1", host)
        self.assertIn('const TEST_FAULT_NO_EXIT_RUNTIME = "no-exit-runtime"', host)
        self.assertIn("function validPostTerminalError(value, context)", host)
        self.assertIn("function validWorkerCloseConfirmation(value, context)", host)
        self.assertIn("progress.runtime.closeConfirmation, deadline", host)
        self.assertIn("workerSelfCloseInitiatedBeforeDisposal", host)
        self.assertIn(smoke.ATEXIT_MARKER, host)
        self.assertIn("function normalRuntimeFailure(snapshot)", host)
        self.assertIn("disposeWorker(progress.runtime, /*afterCleanResult=*/true);", host)
        self.assertLess(
            host.index("const runtimeFailure = normalRuntimeFailure(snapshot);"),
            host.index("disposeWorker(progress.runtime, /*afterCleanResult=*/true);"),
        )
        self.assertIn("onExit(code)", worker)
        self.assertIn("onAbort(reason)", worker)
        self.assertIn(
            "function observeNoExitRuntimeBeforeTerminal(state)", worker
        )
        self.assertIn("function scheduleNoExitRuntimeObservation(state)", worker)
        self.assertIn("NO_EXIT_RUNTIME_WORKER_OBSERVATION_TURNS = 2", worker)
        self.assertIn(
            "noExitRuntime: state.testFault === TEST_FAULT_NO_EXIT_RUNTIME", worker
        )
        self.assertIn("scheduleNoExitRuntimeObservation(state);", worker)
        self.assertIn("postTerminal(state, \"on-exit\");", worker)
        self.assertIn("function settleBeforeTerminal(state)", worker)
        self.assertIn("function closeAfterTerminal(state)", worker)
        self.assertIn("function waitForWorkerTurn()", worker)
        self.assertIn("isExpectedNormalEmscriptenExitStatus", worker)
        self.assertIn("postExitError", worker)
        self.assertIn("function postTerminalError(state, error)", worker)
        self.assertIn('type: "post-terminal-error"', worker)
        self.assertIn('type: "terminal-close-confirmed"', worker)
        self.assertIn("self.close();", worker)
        self.assertIn("PRE_TERMINAL_SETTLEMENT_TURNS = 2", worker)
        self.assertIn("queueMicrotask(() => {", worker)
        self.assertIn("reportTestDelayedPostTerminalError", worker)
        self.assertIn(smoke.ATEXIT_MARKER, worker)
        self.assertIn("onRuntimeInitialized()", worker)
        self.assertIn("mainScriptUrlOrBlob", worker)
        self.assertNotIn("state === null || state.terminalSent", worker)
        self.assertLess(
            worker.index("await waitForWorkerTurn();"),
            worker.index('postTerminal(state, "on-exit");'),
        )
        self.assertLess(
            worker.index("if (captured === COMPLETION_MARKER)"),
            worker.index("scheduleNoExitRuntimeObservation(state);"),
        )
        self.assertNotIn("terminal-received", host + worker)
        self.assertNotIn("terminal-settled-ack", host + worker)
        self.assertNotIn("emscripten_exit_with_live_runtime", host + worker)
        self.assertNotIn("location.replace(", host)
        for forbidden in (
            "navigator.storage.getDirectory(",
            ".createSyncAccessHandle(",
            ".createWritable(",
            ".removeEntry(",
            "localStorage",
            "sessionStorage",
            "indexedDB",
            "IDBFS",
            "FS.syncfs",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, host + worker)

        self.assertIn('"Cross-Origin-Opener-Policy", "same-origin"', runner)
        self.assertIn('"Cross-Origin-Embedder-Policy", "require-corp"', runner)
        self.assertIn('"normalRuntimeShutdownProven": True', runner)
        self.assertIn('"workerSelfCloseInitiatedBeforeDisposal": True', runner)
        self.assertIn("validate_adversarial_delayed_post_terminal_error_result", runner)
        self.assertIn("validate_no_exit_runtime_negative_control_result", runner)
        self.assertIn("--test-delayed-post-terminal-error", runner)
        self.assertIn("--test-no-exit-runtime", runner)
        self.assertIn("TEST_FAULT_DELAYED_POST_TERMINAL_ERROR", runner)
        self.assertIn("TEST_FAULT_NO_EXIT_RUNTIME", runner)
        self.assertIn("NO_EXIT_RUNTIME_NEGATIVE_CONTROL_PASS", runner)
        self.assertIn("ATEXIT_MARKER", runner)
        self.assertIn('"workerPreTerminalSettlementObserved": True', runner)
        self.assertIn('"workerPostTerminalMicrotaskObserved": True', runner)
        self.assertIn('"postExitPageBarrierObserved": True', runner)
        self.assertIn("MAX_PAGE_HEARTBEAT_GAP_MS = 250", runner)
        self.assertIn('"workerTerminationRequestedAfterCleanResult": True', runner)
        self.assertIn('"profilePersistenceProven": False', runner)
        self.assertIn('"fileLockSemanticsProven": False', runner)
        self.assertIn('"atomicRecoveryProven": False', runner)
        self.assertIn('"databaseRecoveryProven": False', runner)
        self.assertNotIn("--remote-debugging", runner)


if __name__ == "__main__":
    unittest.main()
