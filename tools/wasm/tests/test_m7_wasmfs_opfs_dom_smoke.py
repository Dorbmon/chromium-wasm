#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the isolated M7 WasmFS/OPFS outer-reload smoke."""

from __future__ import annotations

import copy
import http.client
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
from collections import deque
import unittest
from unittest import mock


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m7_wasmfs_opfs_dom_smoke as smoke
from tools.wasm.tests.m3_source_contract_test_support import source


RESULT_TOKEN = "result-token-for-m7-opfs-123456"
RUN_NAMESPACE = "run-namespace-for-m7-opfs-123456"
ORIGIN = "http://127.0.0.1:43127"
WRITE_MODULE_ID = "1" * 32
VERIFY_MODULE_ID = "2" * 32


def passing_result(phase: str) -> dict[str, object]:
    is_write = phase == smoke.WRITE_PHASE
    marker = smoke.WRITE_READY_MARKER if is_write else smoke.VERIFY_STARTED_MARKER
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
        "persistenceScope": smoke.PERSISTENCE_SCOPE,
        "fileLockSemanticsProven": False,
        "concurrentAccessHandleSemanticsProven": False,
        "outerReload": not is_write,
        "timeOrigin": 1000.25 if is_write else 1001.5,
        "priorTimeOrigin": None if is_write else 1000.25,
        "moduleIdentity": WRITE_MODULE_ID if is_write else VERIFY_MODULE_ID,
        "priorModuleIdentity": None if is_write else WRITE_MODULE_ID,
        "freshOuterDocument": False if is_write else True,
        "freshModuleIdentity": False if is_write else True,
        # The two documents intentionally tear down their still-live runtimes
        # through outer navigation, rather than exercising native shutdown.
        "runtimeExitCode": None,
        "completionObserved": True,
        "completionMarker": f"{smoke.PASS_MARKER} phase={phase}",
        "runtimeLifecycle": "live-runtime",
        "teardownMode": "outer-document",
        "factorySettled": True,
        "runtimeInitialized": True,
        "abort": None,
        "stdout": [marker, f"{smoke.PASS_MARKER} phase={phase}"],
        "stderr": [],
        "error": None,
    }


class M7WasmfsOpfsDomSmokeTest(unittest.TestCase):
    def test_validate_result_pair_accepts_two_fresh_documents(self) -> None:
        smoke.validate_result_pair(
            passing_result(smoke.WRITE_PHASE),
            passing_result(smoke.VERIFY_PHASE),
            expected_run_namespace=RUN_NAMESPACE,
            expected_origin=ORIGIN,
        )

    def test_validate_result_pair_rejects_lock_claims(self) -> None:
        for field in (
            "fileLockSemanticsProven",
            "concurrentAccessHandleSemanticsProven",
        ):
            with self.subTest(field=field):
                write = passing_result(smoke.WRITE_PHASE)
                verify = passing_result(smoke.VERIFY_PHASE)
                verify[field] = True
                with self.assertRaises(M0Error):
                    smoke.validate_result_pair(
                        write,
                        verify,
                        expected_run_namespace=RUN_NAMESPACE,
                        expected_origin=ORIGIN,
                    )

    def test_validate_result_pair_rejects_missing_fresh_reload_evidence(self) -> None:
        for field, value in (
            ("outerReload", False),
            ("freshOuterDocument", False),
            ("freshModuleIdentity", False),
            ("timeOrigin", 1000.25),
            ("moduleIdentity", WRITE_MODULE_ID),
        ):
            with self.subTest(field=field):
                write = passing_result(smoke.WRITE_PHASE)
                verify = passing_result(smoke.VERIFY_PHASE)
                verify[field] = value
                with self.assertRaises(M0Error):
                    smoke.validate_result_pair(
                        write,
                        verify,
                        expected_run_namespace=RUN_NAMESPACE,
                        expected_origin=ORIGIN,
                    )

    def test_validate_result_pair_requires_real_runtime_initialized_signal(self) -> None:
        write = passing_result(smoke.WRITE_PHASE)
        verify = passing_result(smoke.VERIFY_PHASE)
        verify["runtimeInitialized"] = False
        with self.assertRaises(M0Error):
            smoke.validate_result_pair(
                write,
                verify,
                expected_run_namespace=RUN_NAMESPACE,
                expected_origin=ORIGIN,
            )

    def test_validate_result_pair_requires_live_runtime_completion_contract(self) -> None:
        for field, value in (
            ("runtimeExitCode", 0),
            ("completionObserved", False),
            ("completionMarker", f"{smoke.PASS_MARKER} phase=verify"),
            ("runtimeLifecycle", "not-live-runtime"),
            ("teardownMode", "graceful"),
        ):
            with self.subTest(field=field):
                write = passing_result(smoke.WRITE_PHASE)
                write[field] = value
                with self.assertRaises(M0Error):
                    smoke.validate_result_pair(
                        write,
                        passing_result(smoke.VERIFY_PHASE),
                        expected_run_namespace=RUN_NAMESPACE,
                        expected_origin=ORIGIN,
                    )

    def test_validate_result_pair_requires_exact_phase_qualified_pass_marker(self) -> None:
        write = passing_result(smoke.WRITE_PHASE)
        write["stdout"] = [smoke.WRITE_READY_MARKER, smoke.PASS_MARKER]
        with self.assertRaises(M0Error):
            smoke.validate_result_pair(
                write,
                passing_result(smoke.VERIFY_PHASE),
                expected_run_namespace=RUN_NAMESPACE,
                expected_origin=ORIGIN,
            )

    def test_result_payload_parser_rejects_duplicate_and_wrong_namespace(self) -> None:
        payload = {
            "protocol": 1,
            "case": smoke.CASE,
            "scope": smoke.SCOPE,
            "phase": smoke.WRITE_PHASE,
            "runNamespace": RUN_NAMESPACE,
        }
        self.assertEqual(
            smoke.parse_result_payload(
                json.dumps(payload).encode("utf-8"),
                smoke.WRITE_PHASE,
                RUN_NAMESPACE,
            ),
            payload,
        )
        self.assertIsNone(
            smoke.parse_result_payload(
                json.dumps({**payload, "runNamespace": "wrong-namespace-123456"}).encode(
                    "utf-8"
                ),
                smoke.WRITE_PHASE,
                RUN_NAMESPACE,
            )
        )
        duplicate = (
            b'{"protocol":1,"protocol":1,"case":"'
            + smoke.CASE.encode("utf-8")
            + b'","scope":"'
            + smoke.SCOPE.encode("utf-8")
            + b'","phase":"write","runNamespace":"'
            + RUN_NAMESPACE.encode("utf-8")
            + b'"}'
        )
        self.assertIsNone(
            smoke.parse_result_payload(
                duplicate, smoke.WRITE_PHASE, RUN_NAMESPACE
            )
        )

    def test_terminal_host_failure_is_reported_without_waiting_for_verify(self) -> None:
        results: dict[str, dict[str, object]] = {}
        result_queue: queue.Queue[tuple[str, dict[str, object]]] = queue.Queue()
        failed = passing_result(smoke.WRITE_PHASE)
        failed["status"] = "fail"
        failed["error"] = "runtime watchdog fired"
        result_queue.put((smoke.WRITE_PHASE, failed))
        browser = mock.Mock()
        browser.poll.return_value = None
        with self.assertRaisesRegex(M0Error, "write host reported failure"):
            smoke.wait_for_result_pair(
                browser,
                deque(),
                result_queue,
                deadline=smoke.time.monotonic() + 1,
                results=results,
            )
        self.assertEqual(results[smoke.WRITE_PHASE], failed)

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
            (out_dir / f"{smoke.MODULE_NAME}.wasm").write_bytes(b"\\0asm")
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
                status, _, _ = request("GET", f"{smoke.HOST_ROOT}/unexpected")
                self.assertEqual(status, 404)

                result = {
                    "protocol": 1,
                    "case": smoke.CASE,
                    "scope": smoke.SCOPE,
                    "phase": smoke.WRITE_PHASE,
                    "runNamespace": RUN_NAMESPACE,
                }
                body = json.dumps(result).encode("utf-8")
                endpoint = (
                    f"{smoke.HOST_ROOT}/result/{RESULT_TOKEN}/{smoke.WRITE_PHASE}"
                )
                status, _, _ = request(
                    "POST", endpoint, body, {"Content-Type": "application/json"}
                )
                self.assertEqual(status, 204)
                status, _, _ = request(
                    "POST", endpoint, body, {"Content-Type": "application/json"}
                )
                self.assertEqual(status, 409)
                self.assertEqual(result_queue.get_nowait(), (smoke.WRITE_PHASE, result))
            finally:
                server.shutdown()
                server.server_close()
                server_thread.join(timeout=5)

    def test_host_static_contract_has_no_opfs_file_operations_or_page_reload(self) -> None:
        host = source("tools/wasm/host/m7_wasmfs_opfs_smoke.js")
        self.assertIn('const MODULE_NAME = "m7_wasmfs_opfs_smoke";', host)
        self.assertIn('typeof navigator.storage.getDirectory === "function"', host)
        self.assertIn(
            'typeof FileSystemFileHandle.prototype.createSyncAccessHandle === "function"',
            host,
        )
        self.assertIn("const CAPABILITY_PROBE_SOURCE = `", host)
        self.assertIn("new Worker(workerUrl, {", host)
        self.assertIn("CAPABILITY_PROBE_TIMEOUT_MS", host)
        self.assertIn("probeWorker?.terminate();", host)
        self.assertIn("URL.revokeObjectURL(workerUrl);", host)
        self.assertIn(
            "result.opfsCapability = await probeRequiredOpfsCapability();", host
        )
        self.assertLess(
            host.index("result.opfsCapability = await probeRequiredOpfsCapability();"),
            host.index("const runtime = await runRuntime(context);"),
        )
        self.assertIn("if (!result.opfsCapability)", host)
        self.assertIn("opfsFallbackUsed: false", host)
        self.assertIn("persistenceScope: PERSISTENCE_SCOPE", host)
        self.assertIn("fileLockSemanticsProven: false", host)
        self.assertIn("concurrentAccessHandleSemanticsProven: false", host)
        self.assertIn("await postResult(context, result);", host)
        self.assertIn("location.replace(verifyUrl.href);", host)
        self.assertLess(
            host.index("await postResult(context, result);"),
            host.index("location.replace(verifyUrl.href);"),
        )
        self.assertIn("timeOrigin > context.priorTimeOrigin", host)
        self.assertIn("bindModuleIdentity(module, moduleIdentity);", host)
        self.assertIn("onRuntimeInitialized() { runtimeInitialized = true; }", host)
        self.assertIn("result.runtimeInitialized = runtime.runtimeInitialized;", host)
        self.assertNotIn("result.runtimeInitialized = true;", host)
        self.assertIn("const COMPLETION_SETTLE_MS = 25;", host)
        self.assertIn("function expectedPassMarker(phase)", host)
        self.assertIn("function waitForRuntimeCompletion(runtimeCompletion, timeoutMs)", host)
        self.assertIn(
            "await waitForRuntimeCompletion(runtimeCompletion, context.timeoutMs);",
            host,
        )
        self.assertIn("await delay(COMPLETION_SETTLE_MS);", host)
        self.assertIn("completionObserved: false", host)
        self.assertIn('runtimeLifecycle: "not-observed"', host)
        self.assertIn('teardownMode: "outer-document"', host)
        self.assertIn(
            "result.completionObserved = runtime.completionObserved;", host
        )
        self.assertIn(
            "result.runtimeLifecycle = runtime.completionObserved &&", host
        )
        self.assertIn("result.runtimeExitCode !== null", host)
        self.assertNotIn("waitForRuntimeExit", host)
        self.assertIn("let reportExit = null;", host)
        self.assertIn("reportExit = (code) =>", host)
        self.assertIn("onExit(code) { reportExit(code); }", host)
        self.assertNotIn("output.reportExit", host)
        self.assertIn("let factoryError = null;", host)
        self.assertIn("factoryError = formatError(error);", host)
        self.assertEqual(host.count("const factoryPromise ="), 1)
        self.assertIn('runNamespace: "<redacted>"', host)
        self.assertNotIn('oneQueryValue(query, "module")', host)
        self.assertNotIn("hasRequiredOpfsCapability", host)
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
            "location.reload(",
            "Page.reload",
        ):
            self.assertNotIn(forbidden, host)

    def test_runner_static_contract_uses_one_outer_profile_and_no_page_reload(self) -> None:
        runner = source("tools/wasm/run_m7_wasmfs_opfs_dom_smoke.py")
        self.assertIn('MODULE_NAME = "m7_wasmfs_opfs_smoke"', runner)
        self.assertNotIn("--module-name", runner)
        self.assertIn('"Cross-Origin-Opener-Policy", "same-origin"', runner)
        self.assertIn('"Cross-Origin-Embedder-Policy", "require-corp"', runner)
        self.assertIn("TemporaryDirectory(prefix=\"chromium-wasm-m7-opfs-outer-\")", runner)
        self.assertIn("browser_command(", runner)
        self.assertIn("location.replace()", runner)
        self.assertIn("redact_opaque_value(results, result_token, run_namespace)", runner)
        self.assertIn('"runtimeExitCode": None', runner)
        self.assertIn('"completionObserved": True', runner)
        self.assertIn('"runtimeLifecycle": "live-runtime"', runner)
        self.assertIn('"teardownMode": "outer-document"', runner)
        self.assertIn("def _require_exact_output", runner)
        for forbidden in (
            "Page.reload",
            "location.reload",
            "wait_for_page_client",
            "m4_cdp",
            "Runtime.evaluate",
            "subprocess.run(",
        ):
            self.assertNotIn(forbidden, runner)


if __name__ == "__main__":
    unittest.main()
