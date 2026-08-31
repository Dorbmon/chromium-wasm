#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the three-document renderer IndexedDB runner."""

from __future__ import annotations

import copy
from collections import deque
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from urllib.parse import parse_qs, urlsplit


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m7_chrome_renderer_indexed_db_outer_reload_dom_smoke as smoke
from tools.wasm.tests.m3_source_contract_test_support import source


VERSIONS = {"chromium": "a" * 40, "v8": "b" * 40, "emscripten": "c" * 40}
RESULT_TOKEN = "r" * 32
SESSION = "s" * 32
ORIGIN = "http://127.0.0.1:43129"


def artifact() -> dict[str, object]:
    return {
        "artifact_delivery": smoke.ARTIFACT_DELIVERY,
        "artifact_source_provenance": smoke.ARTIFACT_SOURCE_PROVENANCE,
        "build_config": {"bytes": 71, "sha256": "d" * 64},
        "build_config_provenance": smoke.BUILD_CONFIG_PROVENANCE,
        "loader": {"bytes": 72, "sha256": "e" * 64},
        "module_name": smoke.PRODUCT_MODULE_NAME,
        "wasm": {"bytes": 73, "sha256": "f" * 64},
    }


def harness() -> dict[str, object]:
    return {
        "host_html": {"bytes": 74, "sha256": "0" * 64},
        "host_js": {"bytes": 75, "sha256": "1" * 64},
        "runner_source": {"bytes": 76, "sha256": "2" * 64},
        "source_snapshot_provenance": smoke.SOURCE_SNAPSHOT_PROVENANCE,
        "version_provenance": smoke.VERSION_PROVENANCE,
    }


def passing_result(
    ordinal: int,
    escrow: smoke.TokenEscrow,
    evidence: smoke.DocumentEvidence,
    *,
    module_identity: str,
) -> dict[str, object]:
    phase, mode = smoke.phase_for_ordinal(ordinal)
    digest_a, digest_b = smoke._expected_token_digests(ordinal, escrow)
    markers = smoke.expected_markers(ordinal, escrow)
    return {
        "artifact": artifact(),
        "bridge": {
            "activeAtResult": True,
            "frozen": True,
            "installedBeforeModuleFactory": True,
            "permanent": True,
            "processExitDispatches": 1,
            "protocol": 1,
        },
        "captureHarness": harness(),
        "case": smoke.CASE,
        "document": {
            "identity": (str(ordinal) * 32),
            "navigationType": evidence.navigation_type,
            "timeOrigin": evidence.time_origin,
        },
        "hostBoundary": {
            "hostDatabaseAccessAttempted": False,
            "hostOpfsAccessAttempted": False,
            "hostWebLocksAccessAttempted": False,
            "nativeCallAttempted": False,
            "wasmMemoryInspectionAttempted": False,
        },
        "m7GateComplete": False,
        "mode": mode,
        "ordinal": ordinal,
        "origin": ORIGIN,
        "phase": phase,
        "protocol": 1,
        "quiescence": {
            "callbacksAfterQuiescence": 7,
            "callbacksAtClear": 7,
            "quiet": True,
            "quietWindowMs": 50,
        },
        "run": {
            "abortObserved": False,
            "expectedCleanExitStatusObserved": False,
            "factoryRejected": False,
            "factoryResolved": True,
            "factorySettled": True,
            "freshLoaderImport": True,
            "freshModuleObject": True,
            "lifecycleComplete": True,
            "markerCount": len(markers),
            "markerSequenceAccepted": True,
            "markerSource": "stderr-only-fixed-renderer-database-grammar",
            "markers": markers,
            "moduleIdentity": module_identity,
            "onExitCount": 1,
            "ordinal": ordinal,
            "outputLineCount": len(markers),
            "processExitCode": 0,
            "processExitCount": 1,
            "runtimeExitCode": 0,
            "runtimeInitialized": True,
            "stdoutMarkerCount": 0,
        },
        "scope": smoke.SCOPE,
        "sharedArrayBuffer": True,
        "status": "pass",
        "tokenEvidence": {
            "algorithm": "SHA-256",
            "rawTokensExcluded": True,
            "rawTokenLeakDetected": False,
            "rawTokenRedactionCount": 0,
            "tokenADigest": digest_a,
            "tokenBDigest": digest_b,
        },
        "versions": copy.deepcopy(VERSIONS),
    }


def accept_document(
    session: smoke.OuterReloadSession,
    ordinal: int,
    time_origin: float,
) -> smoke.DocumentEvidence:
    evidence = smoke.DocumentEvidence(
        "navigate" if ordinal == 1 else "reload", time_origin
    )
    assert session.observe_top_level_root_navigation(
        RESULT_TOKEN, SESSION, "document", "navigate"
    )
    assert session.accept_document(SESSION, evidence)
    session.acknowledge_document(SESSION)
    return evidence


class RendererIndexedDBOuterReloadDomSmokeTest(unittest.TestCase):
    def test_uses_the_dedicated_source_selected_artifact(self) -> None:
        self.assertEqual(smoke.PRODUCT_MODULE_NAME, "chrome_wasm_m7_profile_indexed_db_test")
        self.assertEqual(smoke.PRODUCT_GN_TARGET, "//chrome:chrome_wasm")
        self.assertEqual(smoke.DEFAULT_OUT_DIR, Path("out/wasm-chrome-m7-profile-indexed-db"))
        self.assertEqual(
            smoke.PRODUCT_GN_ENABLE_ARGUMENT,
            "enable_chromium_wasm_m7_profile_indexed_db_test=true",
        )
        self.assertIn(smoke.PRODUCT_GN_ENABLE_ARGUMENT, smoke.DEFAULT_GN_ARGUMENTS)

    def test_requires_only_the_dedicated_m7_gn_flag_and_output(self) -> None:
        good = b'enable_chromium_wasm_m7_profile_indexed_db_test = true\n'
        smoke.validate_m7_output_configuration(good, smoke.DEFAULT_OUT_DIR)
        with self.assertRaisesRegex(M0Error, "isolated output"):
            smoke.validate_m7_output_configuration(good, Path("out/not-indexed-db"))
        with self.assertRaisesRegex(M0Error, "dedicated test opt-in"):
            smoke.validate_m7_output_configuration(b"", smoke.DEFAULT_OUT_DIR)
        with self.assertRaisesRegex(M0Error, "another M7 artifact"):
            smoke.validate_m7_output_configuration(
                good + b"enable_chromium_wasm_m7_profile_database_test = true\n",
                smoke.DEFAULT_OUT_DIR,
            )

    def test_three_documents_require_ordered_root_navigation_bootstrap_and_ready(self) -> None:
        escrow = smoke.new_token_escrow()
        session = smoke.OuterReloadSession(RESULT_TOKEN, SESSION, escrow)
        documents: list[smoke.DocumentEvidence] = []
        results: list[smoke.PhaseResult] = []
        for ordinal, time_origin in enumerate((1.0, 2.0, 3.0), start=1):
            evidence = accept_document(session, ordinal, time_origin)
            documents.append(evidence)
            payload = session.bootstrap_payload(SESSION)
            assert payload is not None
            self.assertEqual(payload["ordinal"], ordinal)
            self.assertEqual(payload["mode"], smoke.phase_for_ordinal(ordinal)[1])
            self.assertEqual(payload["tokenA"], None if ordinal == 3 else escrow.token_a)
            self.assertEqual(payload["tokenB"], None if ordinal == 1 else escrow.token_b)
            receipt = passing_result(
                ordinal, escrow, evidence, module_identity=(str(ordinal + 3) * 32)
            )
            self.assertTrue(session.accept_result(RESULT_TOKEN, ordinal))
            results.append(
                smoke.validate_phase_result(
                    receipt,
                    ordinal=ordinal,
                    expected_versions=VERSIONS,
                    expected_artifact=artifact(),
                    expected_capture_harness=harness(),
                    expected_origin=ORIGIN,
                    expected_document=evidence,
                    escrow=escrow,
                    prohibited=session.prohibited_values(),
                )
            )
            self.assertTrue(session.accept_ready(RESULT_TOKEN, ordinal))
            smoke.validate_ready_receipt(
                {
                    "case": smoke.CASE,
                    "ordinal": ordinal,
                    "protocol": 1,
                    "scope": smoke.SCOPE,
                    "timeOrigin": time_origin,
                },
                results[-1],
            )
            if ordinal < 3:
                session.arm_next_reload(ordinal, time_origin)
        smoke.validate_outer_document_transitions(*results)
        self.assertEqual([document.navigation_type for document in documents], ["navigate", "reload", "reload"])

    def test_result_rejects_any_raw_token_and_missing_close_marker(self) -> None:
        escrow = smoke.new_token_escrow()
        evidence = smoke.DocumentEvidence("navigate", 1.0)
        receipt = passing_result(1, escrow, evidence, module_identity="4" * 32)
        receipt["run"] = copy.deepcopy(receipt["run"])
        assert isinstance(receipt["run"], dict)
        receipt["run"]["markers"] = receipt["run"]["markers"][:-2] + [
            receipt["run"]["markers"][-1]
        ]
        with self.assertRaises(M0Error):
            smoke.validate_phase_result(
                receipt,
                ordinal=1,
                expected_versions=VERSIONS,
                expected_artifact=artifact(),
                expected_capture_harness=harness(),
                expected_origin=ORIGIN,
                expected_document=evidence,
                escrow=escrow,
                prohibited=(escrow.token_a, escrow.token_b, RESULT_TOKEN, SESSION),
            )
        leaking = passing_result(1, escrow, evidence, module_identity="5" * 32)
        leaking["origin"] = ORIGIN + "/" + escrow.token_a
        with self.assertRaisesRegex(M0Error, "opaque value"):
            smoke.validate_phase_result(
                leaking,
                ordinal=1,
                expected_versions=VERSIONS,
                expected_artifact=artifact(),
                expected_capture_harness=harness(),
                expected_origin=ORIGIN,
                expected_document=evidence,
                escrow=escrow,
                prohibited=(escrow.token_a, escrow.token_b, RESULT_TOKEN, SESSION),
            )

    def test_cdp_reload_helper_uses_two_page_reload_calls_and_three_loaders(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, object]] = []
                self.events = [
                    {"method": "Page.frameNavigated", "params": {"frame": {
                        "id": "root", "loaderId": "old", "url": "http://x/"}}},
                    {"method": "Page.frameNavigated", "params": {"frame": {
                        "id": "root", "loaderId": "two", "url": "http://x/"}}},
                    {"method": "Page.frameNavigated", "params": {"frame": {
                        "id": "root", "loaderId": "three", "url": "http://x/"}}},
                ]

            def call(self, method: str, parameters: object = None) -> object:
                self.calls.append((method, parameters))
                if method == "Page.getFrameTree":
                    return {"frameTree": {"frame": {"id": "root", "loaderId": "old"}}}
                return {}

            def next_event(self, _timeout: float) -> object:
                return self.events.pop(0) if self.events else None

        class RunningBrowser:
            def poll(self) -> None:
                return None

        client = FakeClient()
        first = smoke.prepare_outer_document_reload(client)
        second = smoke.reload_outer_document(
            client, RunningBrowser(), deque(), first, "http://x/", time.monotonic() + 1
        )
        third = smoke.reload_outer_document(
            client, RunningBrowser(), deque(), second, "http://x/", time.monotonic() + 1
        )
        smoke.validate_cdp_root_loaders(first, second, third)
        self.assertEqual(
            client.calls,
            [
                ("Page.enable", None),
                ("Page.getFrameTree", None),
                ("Page.reload", {"ignoreCache": True}),
                ("Page.reload", {"ignoreCache": True}),
            ],
        )

    def test_url_has_no_raw_tokens_and_canonical_partition_source_is_selected(self) -> None:
        escrow = smoke.new_token_escrow()
        server = smoke.RendererIndexedDBOuterReloadServer(
            ("127.0.0.1", 0), smoke.RendererIndexedDBOuterReloadRequestHandler
        )
        try:
            server.session = smoke.OuterReloadSession(RESULT_TOKEN, SESSION, escrow)
            url = smoke.smoke_url(
                server,
                RESULT_TOKEN,
                SESSION,
                VERSIONS,
                artifact=artifact(),
                capture_harness=harness(),
                timeout_seconds=30,
            )
        finally:
            server.server_close()
        self.assertNotIn(escrow.token_a, url)
        self.assertNotIn(escrow.token_b, url)
        self.assertEqual(
            set(parse_qs(urlsplit(url).query, keep_blank_values=True)),
            {"artifact", "captureHarness", "module", "resultToken", "session", "timeoutMs", "versions"},
        )
        client_source = source("chrome/browser/wasm/wasm_content_browser_client.cc")
        self.assertIn("CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST", client_source)
        self.assertIn('"m7-indexed-db"', client_source)
        self.assertIn('"wasmindexeddb"', client_source)
        self.assertIn('"indexeddb"', client_source)
        self.assertIn("/*in_memory=*/false", client_source)
        smoke_source = source("chrome/browser/wasm/wasm_profile_indexed_db_smoke.cc")
        self.assertIn("chrome://m7-indexed-db/", smoke_source)
        self.assertIn('kTokenASwitch[] = "wasm-profile-indexed-db-token-a"', smoke_source)
        self.assertIn('kTokenBSwitch[] = "wasm-profile-indexed-db-token-b"', smoke_source)

    def test_ready_notification_is_flushed_before_it_can_authorize_reload(self) -> None:
        runner = source("tools/wasm/run_m7_chrome_renderer_indexed_db_outer_reload_dom_smoke.py")
        ready = runner[runner.index("    def _post_ready("):runner.index("    def _post_failure(")]
        self.assertIn('self.headers.get("Sec-Fetch-Dest")', runner)
        self.assertIn('self.headers.get("Sec-Fetch-Mode")', runner)
        self.assertLess(ready.index("self._send_empty"), ready.index("self.wfile.flush"))
        self.assertLess(ready.index("self.wfile.flush"), ready.index("ready_queue.put_nowait"))
        self.assertEqual(runner.count('client.call("Page.reload", {"ignoreCache": True})'), 1)
        self.assertEqual(runner.count("server.session.arm_next_reload("), 2)

    def test_http_bootstrap_result_and_ready_are_one_shot_and_capability_bound(self) -> None:
        escrow = smoke.new_token_escrow()
        with tempfile.TemporaryDirectory() as temporary:
            out_dir = Path(temporary) / smoke.DEFAULT_OUT_DIR.name
            out_dir.mkdir()
            (out_dir / f"{smoke.PRODUCT_MODULE_NAME}.js").write_bytes(b"export default {}\n")
            (out_dir / f"{smoke.PRODUCT_MODULE_NAME}.wasm").write_bytes(
                b"\x00asm\x01\x00\x00\x00"
            )
            (out_dir / "args.gn").write_text(
                "enable_chromium_wasm_m7_profile_indexed_db_test = true\n",
                encoding="utf-8",
            )
            server = smoke.create_server(
                "127.0.0.1", 0, out_dir, RESULT_TOKEN, SESSION, escrow
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = smoke.smoke_url(
                    server,
                    RESULT_TOKEN,
                    SESSION,
                    VERSIONS,
                    artifact=smoke.artifact_identity(server),
                    capture_harness=smoke.capture_harness_identity(server),
                    timeout_seconds=30,
                )
                parsed = urlsplit(url)
                connection = http.client.HTTPConnection(*server.server_address, timeout=5)
                connection.request(
                    "GET",
                    parsed.path + "?" + parsed.query,
                    headers={"Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate"},
                )
                self.assertEqual(connection.getresponse().status, 200)
                document = {
                    "case": smoke.CASE,
                    "navigationType": "navigate",
                    "protocol": 1,
                    "scope": smoke.SCOPE,
                    "timeOrigin": 1.0,
                }
                endpoint = f"{smoke.HOST_ROOT}/bootstrap/{SESSION}"
                connection.request(
                    "POST",
                    endpoint,
                    body=json.dumps(document),
                    headers={"Content-Type": "application/json"},
                )
                self.assertEqual(connection.getresponse().status, 204)
                connection.request("GET", endpoint)
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                payload = json.loads(response.read())
                self.assertEqual(payload["ordinal"], 1)
                self.assertEqual(payload["tokenA"], escrow.token_a)
                self.assertIsNone(payload["tokenB"])
                connection.request("GET", endpoint)
                self.assertEqual(connection.getresponse().status, 409)
                receipt = passing_result(
                    1,
                    escrow,
                    smoke.DocumentEvidence("navigate", 1.0),
                    module_identity="8" * 32,
                )
                connection.request(
                    "POST",
                    f"{smoke.HOST_ROOT}/result/{RESULT_TOKEN}/1",
                    body=json.dumps(receipt),
                    headers={"Content-Type": "application/json"},
                )
                self.assertEqual(connection.getresponse().status, 204)
                connection.request(
                    "POST",
                    f"{smoke.HOST_ROOT}/ready/{RESULT_TOKEN}/1",
                    body=json.dumps({
                        "case": smoke.CASE,
                        "ordinal": 1,
                        "protocol": 1,
                        "scope": smoke.SCOPE,
                        "timeOrigin": 1.0,
                    }),
                    headers={"Content-Type": "application/json"},
                )
                self.assertEqual(connection.getresponse().status, 204)
                self.assertEqual(server.result_queue.get_nowait()[0], 1)
                self.assertEqual(server.ready_queue.get_nowait()[0], 1)
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
