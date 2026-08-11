#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the isolated M7 bounded OPFS lifecycle DOM smoke."""

from __future__ import annotations

import http.client
import json
from collections import deque
from pathlib import Path
import queue
import sys
import tempfile
import threading
import unittest
from unittest import mock


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m7_wasmfs_opfs_handle_lifecycle_dom_smoke as smoke
from tools.wasm.tests.m3_source_contract_test_support import source


RESULT_TOKEN = "result-token-for-m7-opfs-handle-lifecycle-123456"
RUN_NAMESPACE = "run-namespace-for-m7-opfs-handle-lifecycle-123456"
ORIGIN = "http://127.0.0.1:43129"
HOLDER_MODULE_ID = "1" * 32
REOPEN_MODULE_ID = "2" * 32
VERIFY_MODULE_ID = "3" * 32


def passing_runtime(role: str, marker: str, module_identity: str) -> dict[str, object]:
    return {
        "role": role,
        "moduleIdentity": module_identity,
        "factorySettled": True,
        "runtimeInitialized": True,
        "runtimeExitCode": None,
        "abort": None,
        "completionObserved": True,
        "completionMarker": marker,
        "factoryError": None,
        "completionError": None,
        "nativeStartObserved": True,
        "runtimeLifecycle": "live-runtime",
        "stdout": [
            "CHROMIUM_WASM_M7_OPFS_HANDLE_LIFECYCLE:RUNTIME_START role="
            + role
            + " run_id=redacted",
            marker,
        ],
        "stderr": [],
    }


def common_result(phase: str) -> dict[str, object]:
    return {
        "protocol": 1,
        "case": smoke.CASE,
        "scope": smoke.SCOPE,
        "phase": phase,
        "runNamespace": RUN_NAMESPACE,
        "status": "pass",
        "origin": ORIGIN,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "opfsCapability": True,
        "opfsFallbackUsed": False,
        "lifecycleScope": smoke.LIFECYCLE_SCOPE,
        "boundedDistinctPathCount": smoke.PATH_COUNT,
        "holderClosedAllPathsProven": False,
        "sameDocumentReopenClosedAllPathsProven": False,
        "independentModuleInstancesProven": False,
        "holderLiveAfterSameDocumentReopen": False,
        "freshDocumentFixtureReapProven": False,
        "browserHandleLimitObserved": False,
        "handleExhaustionProven": False,
        "allocatorReuseObservable": False,
        "profilePersistenceProven": False,
        "persistentProfileIntegrationProven": False,
        "sqliteLeveldbLockSemanticsProven": False,
        "atomicRecoveryProven": False,
        "crashRecoveryProven": False,
        "gracefulRuntimeShutdownProven": False,
        "teardownMode": "outer-document",
        "timeOrigin": 1000.0 if phase == smoke.EXERCISE_PHASE else 2000.0,
        "outerReload": phase == smoke.VERIFY_PHASE,
        "priorTimeOrigin": None,
        "priorHolderModuleIdentity": None,
        "priorReopenModuleIdentity": None,
        "freshOuterDocument": phase == smoke.VERIFY_PHASE,
        "holder": None,
        "reopen": None,
        "verify": None,
        "failureDiagnostics": None,
        "error": None,
    }


def passing_exercise_result() -> dict[str, object]:
    result = common_result(smoke.EXERCISE_PHASE)
    result.update(
        {
            "holderClosedAllPathsProven": True,
            "sameDocumentReopenClosedAllPathsProven": True,
            "independentModuleInstancesProven": True,
            "holderLiveAfterSameDocumentReopen": True,
            "holder": passing_runtime(
                smoke.HOLDER_ROLE, smoke.HOLDER_CLOSED_MARKER, HOLDER_MODULE_ID
            ),
            "reopen": passing_runtime(
                smoke.REOPEN_ROLE, smoke.REOPEN_CLOSED_MARKER, REOPEN_MODULE_ID
            ),
        }
    )
    return result


def passing_verify_result() -> dict[str, object]:
    result = common_result(smoke.VERIFY_PHASE)
    result.update(
        {
            "freshDocumentFixtureReapProven": True,
            "priorTimeOrigin": 1000.0,
            "priorHolderModuleIdentity": HOLDER_MODULE_ID,
            "priorReopenModuleIdentity": REOPEN_MODULE_ID,
            "verify": passing_runtime(
                smoke.VERIFY_ROLE, smoke.VERIFY_REAP_MARKER, VERIFY_MODULE_ID
            ),
        }
    )
    return result


class M7WasmfsOpfsHandleLifecycleDomSmokeTest(unittest.TestCase):
    def test_validate_result_pair_accepts_bounded_lifecycle_only(self) -> None:
        smoke.validate_result_pair(
            passing_exercise_result(),
            passing_verify_result(),
            expected_run_namespace=RUN_NAMESPACE,
            expected_origin=ORIGIN,
        )

    def test_validate_result_pair_rejects_false_capacity_or_persistence_claims(self) -> None:
        for phase, field in (
            (smoke.EXERCISE_PHASE, "browserHandleLimitObserved"),
            (smoke.EXERCISE_PHASE, "handleExhaustionProven"),
            (smoke.EXERCISE_PHASE, "allocatorReuseObservable"),
            (smoke.EXERCISE_PHASE, "profilePersistenceProven"),
            (smoke.EXERCISE_PHASE, "persistentProfileIntegrationProven"),
            (smoke.VERIFY_PHASE, "sqliteLeveldbLockSemanticsProven"),
            (smoke.VERIFY_PHASE, "atomicRecoveryProven"),
            (smoke.VERIFY_PHASE, "crashRecoveryProven"),
            (smoke.VERIFY_PHASE, "gracefulRuntimeShutdownProven"),
        ):
            with self.subTest(phase=phase, field=field):
                exercise = passing_exercise_result()
                verify = passing_verify_result()
                target = exercise if phase == smoke.EXERCISE_PHASE else verify
                target[field] = True
                with self.assertRaises(M0Error):
                    smoke.validate_result_pair(
                        exercise,
                        verify,
                        expected_run_namespace=RUN_NAMESPACE,
                        expected_origin=ORIGIN,
                    )

    def test_validate_result_pair_requires_independent_live_modules_and_fresh_reap(self) -> None:
        for phase, field, value in (
            (smoke.EXERCISE_PHASE, "reopen.moduleIdentity", HOLDER_MODULE_ID),
            (smoke.EXERCISE_PHASE, "holder.runtimeExitCode", 0),
            (smoke.EXERCISE_PHASE, "holderLiveAfterSameDocumentReopen", False),
            (smoke.VERIFY_PHASE, "freshOuterDocument", False),
            (smoke.VERIFY_PHASE, "verify.moduleIdentity", HOLDER_MODULE_ID),
            (smoke.VERIFY_PHASE, "freshDocumentFixtureReapProven", False),
        ):
            with self.subTest(phase=phase, field=field):
                exercise = passing_exercise_result()
                verify = passing_verify_result()
                target = exercise if phase == smoke.EXERCISE_PHASE else verify
                if "." in field:
                    parent, child = field.split(".")
                    nested = target[parent]
                    assert isinstance(nested, dict)
                    nested[child] = value
                else:
                    target[field] = value
                with self.assertRaises(M0Error):
                    smoke.validate_result_pair(
                        exercise,
                        verify,
                        expected_run_namespace=RUN_NAMESPACE,
                        expected_origin=ORIGIN,
                    )

    def test_result_payload_parser_rejects_duplicate_and_wrong_namespace(self) -> None:
        payload = {
            "protocol": 1,
            "case": smoke.CASE,
            "scope": smoke.SCOPE,
            "phase": smoke.EXERCISE_PHASE,
            "runNamespace": RUN_NAMESPACE,
        }
        self.assertEqual(
            smoke.parse_result_payload(
                json.dumps(payload).encode("utf-8"),
                smoke.EXERCISE_PHASE,
                RUN_NAMESPACE,
            ),
            payload,
        )
        self.assertIsNone(
            smoke.parse_result_payload(
                json.dumps({**payload, "runNamespace": "wrong-namespace-123456"}).encode(
                    "utf-8"
                ),
                smoke.EXERCISE_PHASE,
                RUN_NAMESPACE,
            )
        )
        duplicate = (
            b'{"protocol":1,"protocol":1,"case":"'
            + smoke.CASE.encode("utf-8")
            + b'","scope":"'
            + smoke.SCOPE.encode("utf-8")
            + b'","phase":"exercise","runNamespace":"'
            + RUN_NAMESPACE.encode("utf-8")
            + b'"}'
        )
        self.assertIsNone(
            smoke.parse_result_payload(
                duplicate, smoke.EXERCISE_PHASE, RUN_NAMESPACE
            )
        )

    def test_terminal_host_failure_reports_bounded_progress(self) -> None:
        results: dict[str, dict[str, object]] = {}
        result_queue: queue.Queue[tuple[str, dict[str, object]]] = queue.Queue()
        failed = passing_exercise_result()
        failed["status"] = "fail"
        failed["error"] = "shared phase deadline"
        failed["failureDiagnostics"] = {
            "stage": "reopen-marker",
            "timedOut": True,
            "holderRegistered": True,
            "holderClosedObserved": True,
            "reopenRegistered": True,
            "reopenClosedObserved": False,
            "verifyRegistered": False,
            "verifyReapObserved": False,
        }
        result_queue.put((smoke.EXERCISE_PHASE, failed))
        browser = mock.Mock()
        browser.poll.return_value = None
        with self.assertRaisesRegex(
            M0Error,
            r"stage=reopen-marker timed_out=True opfs_capability=True "
            r"holder_registered=True holder_closed=True reopen_registered=True "
            r"reopen_closed=False verify_registered=False verify_reap=False",
        ):
            smoke.wait_for_result_pair(
                browser,
                deque(),
                result_queue,
                deadline=smoke.time.monotonic() + 1,
                results=results,
            )

    def test_redacts_run_credentials_from_diagnostics_and_output(self) -> None:
        value = {
            RUN_NAMESPACE: f"native argument {RUN_NAMESPACE}",
            "nested": {"token": RESULT_TOKEN},
        }
        redacted = smoke.redact_opaque_value(value, RESULT_TOKEN, RUN_NAMESPACE)
        rendered = json.dumps(redacted, sort_keys=True)
        self.assertNotIn(RESULT_TOKEN, rendered)
        self.assertNotIn(RUN_NAMESPACE, rendered)
        self.assertIn("<redacted>", rendered)

    def test_fixed_server_routes_are_isolated_and_coep(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            out_dir = Path(temporary_directory)
            (out_dir / f"{smoke.MODULE_NAME}.js").write_text(
                "export default function() {}\n", encoding="utf-8"
            )
            (out_dir / f"{smoke.MODULE_NAME}.wasm").write_bytes(b"\0asm")
            result_queue: queue.Queue[tuple[str, dict[str, object]]] = queue.Queue(
                maxsize=2
            )
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
                self.assertEqual(headers["Referrer-Policy"], "no-referrer")
                status, headers, _ = request(
                    "GET", f"{smoke.HOST_ROOT}/artifacts/{smoke.MODULE_NAME}.wasm"
                )
                self.assertEqual(status, 200)
                self.assertEqual(headers["Content-Type"], "application/wasm")
                status, _, _ = request(
                    "GET", f"{smoke.HOST_ROOT}/artifacts/not-the-m7-target.js"
                )
                self.assertEqual(status, 404)

                result = {
                    "protocol": 1,
                    "case": smoke.CASE,
                    "scope": smoke.SCOPE,
                    "phase": smoke.EXERCISE_PHASE,
                    "runNamespace": RUN_NAMESPACE,
                }
                body = json.dumps(result).encode("utf-8")
                endpoint = (
                    f"{smoke.HOST_ROOT}/result/{RESULT_TOKEN}/{smoke.EXERCISE_PHASE}"
                )
                status, _, _ = request(
                    "POST", endpoint, body, {"Content-Type": "application/json"}
                )
                self.assertEqual(status, 204)
                status, _, _ = request(
                    "POST", endpoint, body, {"Content-Type": "application/json"}
                )
                self.assertEqual(status, 409)
                self.assertEqual(
                    result_queue.get_nowait(), (smoke.EXERCISE_PHASE, result)
                )
            finally:
                server.shutdown()
                server.server_close()
                server_thread.join(timeout=5)

    def test_host_and_runner_static_contracts_keep_scope_bounded(self) -> None:
        host = source("tools/wasm/host/m7_wasmfs_opfs_handle_lifecycle_smoke.js")
        runner = source("tools/wasm/run_m7_wasmfs_opfs_handle_lifecycle_dom_smoke.py")
        self.assertIn("function createPhaseDeadline(context)", host)
        self.assertIn("function remainingDeadlineMs(deadline, stage, progress)", host)
        self.assertIn("function retainLiveRuntime(runtime)", host)
        self.assertIn("location.replace(verifyUrl.href);", host)
        self.assertIn('"browserHandleLimitObserved": False', runner)
        self.assertIn('"handleExhaustionProven": False', runner)
        self.assertIn('"allocatorReuseObservable": False', runner)
        self.assertIn('"profilePersistenceProven": False', runner)
        self.assertIn('"sqliteLeveldbLockSemanticsProven": False', runner)
        self.assertIn('"crashRecoveryProven": False', runner)
        self.assertIn('TemporaryDirectory(\n            prefix="chromium-wasm-m7-opfs-handle-lifecycle-outer-"', runner)
        self.assertIn("redact_opaque_value(results, result_token, run_namespace)", runner)


if __name__ == "__main__":
    unittest.main()
