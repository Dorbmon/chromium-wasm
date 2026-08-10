#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the isolated M7 OPFS writer-exclusivity DOM smoke."""

from __future__ import annotations

import copy
from collections import deque
import http.client
import json
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
import run_m7_wasmfs_opfs_exclusivity_dom_smoke as smoke
from tools.wasm.tests.m3_source_contract_test_support import source


RESULT_TOKEN = "result-token-for-m7-opfs-exclusivity-123456"
RUN_NAMESPACE = "run-namespace-for-m7-opfs-exclusivity-123456"
ORIGIN = "http://127.0.0.1:43128"
HOLDER_MODULE_ID = "1" * 32
CONTENDER_MODULE_ID = "2" * 32
REOPEN_MODULE_ID = "3" * 32


def runtime_snapshot(role: str, module_identity: str, marker: str) -> dict[str, object]:
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
        "contenderOpenBeginObserved": role == smoke.CONTENDER_ROLE,
        "runtimeLifecycle": "live-runtime",
        "stdout": (
            [smoke.CONTENDER_OPEN_BEGIN_MARKER, marker]
            if role == smoke.CONTENDER_ROLE
            else [marker]
        ),
        "stderr": [],
    }


def passing_result(phase: str) -> dict[str, object]:
    contention = phase == smoke.CONTENTION_PHASE
    result: dict[str, object] = {
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
        "exclusivityScope": smoke.EXCLUSIVITY_SCOPE,
        "syncAccessHandleWriterExclusivityProven": contention,
        "independentModuleInstancesProven": contention,
        "holderLiveAfterContender": contention,
        "releaseAfterOuterDocumentTeardownProven": not contention,
        "sqliteLeveldbLockSemanticsProven": False,
        "atomicRecoveryProven": False,
        "gracefulRuntimeShutdownProven": False,
        "teardownMode": "outer-document",
        "timeOrigin": 1000.25 if contention else 1001.5,
        "outerReload": not contention,
        "priorTimeOrigin": None if contention else 1000.25,
        "priorHolderModuleIdentity": None if contention else HOLDER_MODULE_ID,
        "priorContenderModuleIdentity": None if contention else CONTENDER_MODULE_ID,
        "freshOuterDocument": False if contention else True,
        "holder": (
            runtime_snapshot(
                smoke.HOLDER_ROLE, HOLDER_MODULE_ID, smoke.HOLDER_READY_MARKER
            )
            if contention
            else None
        ),
        "contender": (
            runtime_snapshot(
                smoke.CONTENDER_ROLE,
                CONTENDER_MODULE_ID,
                smoke.CONTENDER_EACCES_MARKER,
            )
            if contention
            else None
        ),
        "reopen": (
            None
            if contention
            else runtime_snapshot(
                smoke.REOPEN_ROLE, REOPEN_MODULE_ID, smoke.REOPEN_OK_MARKER
            )
        ),
        "failureDiagnostics": None,
        "error": None,
    }
    return result


class M7WasmfsOpfsExclusivityDomSmokeTest(unittest.TestCase):
    def test_validate_result_pair_accepts_contention_and_fresh_reopen(self) -> None:
        smoke.validate_result_pair(
            passing_result(smoke.CONTENTION_PHASE),
            passing_result(smoke.REOPEN_PHASE),
            expected_run_namespace=RUN_NAMESPACE,
            expected_origin=ORIGIN,
        )

    def test_validate_result_pair_rejects_broader_lock_or_shutdown_claims(self) -> None:
        for field in (
            "sqliteLeveldbLockSemanticsProven",
            "atomicRecoveryProven",
            "gracefulRuntimeShutdownProven",
        ):
            with self.subTest(field=field):
                contention = passing_result(smoke.CONTENTION_PHASE)
                contention[field] = True
                with self.assertRaises(M0Error):
                    smoke.validate_result_pair(
                        contention,
                        passing_result(smoke.REOPEN_PHASE),
                        expected_run_namespace=RUN_NAMESPACE,
                        expected_origin=ORIGIN,
                    )

    def test_validate_result_pair_requires_direct_eacces_marker(self) -> None:
        contention = passing_result(smoke.CONTENTION_PHASE)
        contender = copy.deepcopy(contention["contender"])
        assert isinstance(contender, dict)
        contender["completionMarker"] = smoke.HOLDER_READY_MARKER
        contender["stdout"] = [smoke.HOLDER_READY_MARKER]
        contention["contender"] = contender
        with self.assertRaises(M0Error):
            smoke.validate_result_pair(
                contention,
                passing_result(smoke.REOPEN_PHASE),
                expected_run_namespace=RUN_NAMESPACE,
                expected_origin=ORIGIN,
            )

    def test_validate_result_pair_requires_holder_to_remain_live(self) -> None:
        contention = passing_result(smoke.CONTENTION_PHASE)
        holder = copy.deepcopy(contention["holder"])
        assert isinstance(holder, dict)
        holder["runtimeExitCode"] = 0
        holder["runtimeLifecycle"] = "not-live-runtime"
        contention["holder"] = holder
        with self.assertRaises(M0Error):
            smoke.validate_result_pair(
                contention,
                passing_result(smoke.REOPEN_PHASE),
                expected_run_namespace=RUN_NAMESPACE,
                expected_origin=ORIGIN,
            )

    def test_validate_result_pair_requires_independent_modules_and_fresh_reopen(self) -> None:
        for phase, field, value in (
            (smoke.CONTENTION_PHASE, "contender.moduleIdentity", HOLDER_MODULE_ID),
            (smoke.REOPEN_PHASE, "reopen.moduleIdentity", HOLDER_MODULE_ID),
            (smoke.REOPEN_PHASE, "freshOuterDocument", False),
        ):
            with self.subTest(phase=phase, field=field):
                contention = passing_result(smoke.CONTENTION_PHASE)
                reopen = passing_result(smoke.REOPEN_PHASE)
                target = contention if phase == smoke.CONTENTION_PHASE else reopen
                if "." in field:
                    parent, child = field.split(".")
                    nested = target[parent]
                    assert isinstance(nested, dict)
                    nested[child] = value
                else:
                    target[field] = value
                with self.assertRaises(M0Error):
                    smoke.validate_result_pair(
                        contention,
                        reopen,
                        expected_run_namespace=RUN_NAMESPACE,
                        expected_origin=ORIGIN,
                    )

    def test_result_payload_parser_rejects_duplicate_and_wrong_namespace(self) -> None:
        payload = {
            "protocol": 1,
            "case": smoke.CASE,
            "scope": smoke.SCOPE,
            "phase": smoke.CONTENTION_PHASE,
            "runNamespace": RUN_NAMESPACE,
        }
        self.assertEqual(
            smoke.parse_result_payload(
                json.dumps(payload).encode("utf-8"),
                smoke.CONTENTION_PHASE,
                RUN_NAMESPACE,
            ),
            payload,
        )
        self.assertIsNone(
            smoke.parse_result_payload(
                json.dumps({**payload, "runNamespace": "wrong-namespace-123456"}).encode(
                    "utf-8"
                ),
                smoke.CONTENTION_PHASE,
                RUN_NAMESPACE,
            )
        )
        duplicate = (
            b'{"protocol":1,"protocol":1,"case":"'
            + smoke.CASE.encode("utf-8")
            + b'","scope":"'
            + smoke.SCOPE.encode("utf-8")
            + b'","phase":"contention","runNamespace":"'
            + RUN_NAMESPACE.encode("utf-8")
            + b'"}'
        )
        self.assertIsNone(
            smoke.parse_result_payload(
                duplicate, smoke.CONTENTION_PHASE, RUN_NAMESPACE
            )
        )

    def test_terminal_host_failure_is_reported_without_waiting_for_reopen(self) -> None:
        results: dict[str, dict[str, object]] = {}
        result_queue: queue.Queue[tuple[str, dict[str, object]]] = queue.Queue()
        failed = passing_result(smoke.CONTENTION_PHASE)
        failed["status"] = "fail"
        failed["error"] = "holder exited"
        result_queue.put((smoke.CONTENTION_PHASE, failed))
        browser = mock.Mock()
        browser.poll.return_value = None
        with self.assertRaisesRegex(M0Error, "contention host reported failure"):
            smoke.wait_for_result_pair(
                browser,
                deque(),
                result_queue,
                deadline=smoke.time.monotonic() + 1,
                results=results,
            )
        self.assertEqual(results[smoke.CONTENTION_PHASE], failed)

    def test_terminal_failure_reports_bounded_contention_progress(self) -> None:
        results: dict[str, dict[str, object]] = {}
        result_queue: queue.Queue[tuple[str, dict[str, object]]] = queue.Queue()
        failed = passing_result(smoke.CONTENTION_PHASE)
        failed["status"] = "fail"
        failed["error"] = "shared phase deadline"
        failed["opfsCapability"] = True
        failed["failureDiagnostics"] = {
            "stage": "contender-marker",
            "timedOut": True,
            "holderRegistered": True,
            "contenderRegistered": True,
            "reopenRegistered": False,
            "holderNativeStartObserved": True,
            "holderReadyObserved": True,
            "contenderNativeStartObserved": True,
            "nativeStartObserved": True,
            "contenderOpenBeginObserved": True,
            "contenderEaccesObserved": False,
            "reopenNativeStartObserved": False,
            "reopenOkObserved": False,
            "holder": failed["holder"],
            "contender": failed["contender"],
            "reopen": None,
        }
        result_queue.put((smoke.CONTENTION_PHASE, failed))
        browser = mock.Mock()
        browser.poll.return_value = None
        with self.assertRaisesRegex(
            M0Error,
            r"stage=contender-marker timed_out=True "
            r"opfs_capability=True holder_registered=True "
            r"holder_native_start=True holder_ready=True "
            r"contender_registered=True contender_native_start=True "
            r"contender_open_begin=True contender_eacces=False "
            r"reopen_registered=False reopen_native_start=False reopen_ok=False",
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
            "runNamespace": RUN_NAMESPACE,
            "stdout": [f"native argument {RUN_NAMESPACE}"],
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
                    "phase": smoke.CONTENTION_PHASE,
                    "runNamespace": RUN_NAMESPACE,
                }
                body = json.dumps(result).encode("utf-8")
                endpoint = (
                    f"{smoke.HOST_ROOT}/result/{RESULT_TOKEN}/{smoke.CONTENTION_PHASE}"
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
                    result_queue.get_nowait(), (smoke.CONTENTION_PHASE, result)
                )
            finally:
                server.shutdown()
                server.server_close()
                server_thread.join(timeout=5)

    def test_host_static_contract_keeps_opfs_in_wasmfs_and_stages_two_modules(self) -> None:
        host = source("tools/wasm/host/m7_wasmfs_opfs_exclusivity_smoke.js")
        self.assertIn(
            'const MODULE_NAME = "m7_wasmfs_opfs_exclusivity_smoke";', host
        )
        self.assertIn('const CONTENTION_PHASE = "contention";', host)
        self.assertIn('const REOPEN_PHASE = "reopen";', host)
        self.assertIn("const CAPABILITY_PROBE_SOURCE = `", host)
        self.assertIn("const CONTENDER_OPEN_BEGIN_MARKER =", host)
        self.assertIn("new Worker(workerUrl, {", host)
        self.assertIn("async function probeRequiredOpfsCapability(deadline, progress)", host)
        self.assertIn("probeRequiredOpfsCapability(deadline, progress)", host)
        self.assertNotIn("CAPABILITY_PROBE_TIMEOUT_MS", host)
        self.assertIn("function createPhaseDeadline(context)", host)
        self.assertIn("function remainingDeadlineMs(deadline, stage, progress)", host)
        self.assertIn("async function awaitBeforeDeadline", host)
        self.assertIn("onRuntimeCreated(runtime);", host)
        self.assertIn("const holder = startRuntime", host)
        self.assertIn("await requireLiveCompletion(holder, deadline, \"holder-marker\"", host)
        self.assertIn("const contender = startRuntime", host)
        self.assertIn("await requireLiveCompletion(contender, deadline, \"contender-marker\"", host)
        self.assertIn("failureDiagnostics(progress, context)", host)
        self.assertIn("copyPartialRuntimeSnapshots(result, progress, context);", host)
        self.assertIn("function recordFailure(result, progress, context, error)", host)
        self.assertIn("contenderOpenBeginObserved", host)
        self.assertIn("contenderEaccesObserved", host)
        self.assertLess(
            host.index("await requireLiveCompletion(holder, deadline, \"holder-marker\""),
            host.index("const contender = startRuntime"),
        )
        self.assertIn("holder.module === contender.module", host)
        self.assertIn("holderLiveAfterContender = true", host)
        self.assertIn("const ACTIVE_RUNTIMES_PROPERTY =", host)
        self.assertIn("activeRuntimes.push(runtime);", host)
        self.assertLess(
            host.index("onRuntimeCreated(runtime);"),
            host.index("const factory = loader.namespace.default({"),
        )
        self.assertLess(
            host.index("const deadline = createPhaseDeadline(context);"),
            host.index("const result = baseResult(context);"),
        )
        self.assertIn("location.replace(reopenUrl.href);", host)
        self.assertLess(
            host.index("await postResult(context, result);"),
            host.index("location.replace(reopenUrl.href);"),
        )
        self.assertIn('runtimeLifecycle: liveRuntimeFailure(runtime) === null ?', host)
        self.assertIn('teardownMode: "outer-document"', host)
        self.assertIn("runtime.runtimeExitCode !== null", host)
        self.assertIn("runtime.abort !== null", host)
        self.assertNotIn("location.reload(", host)
        for forbidden in (
            "navigator.storage.getDirectory(",
            ".createSyncAccessHandle(",
            ".getFile(",
            ".createWritable(",
            ".removeEntry(",
            "localStorage",
            "sessionStorage",
            "indexedDB",
            "IDBFS",
            "MEMFS",
            "FS.syncfs",
        ):
            self.assertNotIn(forbidden, host)

    def test_runner_static_contract_uses_outer_document_teardown(self) -> None:
        runner = source("tools/wasm/run_m7_wasmfs_opfs_exclusivity_dom_smoke.py")
        self.assertIn('MODULE_NAME = "m7_wasmfs_opfs_exclusivity_smoke"', runner)
        self.assertNotIn("--module-name", runner)
        self.assertIn('"Cross-Origin-Opener-Policy", "same-origin"', runner)
        self.assertIn('"Cross-Origin-Embedder-Policy", "require-corp"', runner)
        self.assertIn(
            'TemporaryDirectory(\n            prefix="chromium-wasm-m7-opfs-exclusivity-outer-"',
            runner,
        )
        self.assertIn('"syncAccessHandleWriterExclusivityProven": True', runner)
        self.assertIn('"sqliteLeveldbLockSemanticsProven": False', runner)
        self.assertIn('"gracefulRuntimeShutdownProven": False', runner)
        self.assertIn('"runtimeLifecycle": "live-runtime"', runner)
        self.assertIn('"teardownMode": "outer-document"', runner)
        self.assertIn("redact_opaque_value(results, result_token, run_namespace)", runner)
        self.assertIn("def _failure_progress_summary", runner)
        self.assertIn("holder_registered=", runner)
        self.assertIn("contender_open_begin=", runner)


if __name__ == "__main__":
    unittest.main()
