#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the M7 Preferences three-outer-document runner."""

from __future__ import annotations

import ast
import copy
from collections import deque
from contextlib import contextmanager
from http import HTTPStatus
import http.client
import json
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m7_chrome_profile_preferences_outer_reload_dom_smoke as smoke


VERSIONS = {"chromium": "a" * 40, "v8": "b" * 40, "emscripten": "c" * 40}
RESULT_CAPABILITY = "r" * 32
SESSION_CAPABILITY = "s" * 32
ORIGIN = "http://127.0.0.1:43127"
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


def escrow_token_matches(value: object, expected_digest: str) -> bool:
    return isinstance(value, str) and secrets.compare_digest(
        smoke._sha256_text(value), expected_digest
    )


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
        "artifact": copy.deepcopy(ARTIFACT_IDENTITY),
        "capture_harness": copy.deepcopy(CAPTURE_HARNESS_IDENTITY),
        "versions": copy.deepcopy(VERSIONS),
        "tokenEvidence": {
            "algorithm": "SHA-256",
            "tokenA": None if ordinal == 3 else escrow.token_a_digest,
            "tokenB": None if ordinal == 1 else escrow.token_b_digest,
            "distinct": True if ordinal == 2 else None,
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


def ready_receipt(ordinal: int, time_origin: float) -> dict[str, object]:
    return {
        "protocol": 1,
        "case": smoke.CASE,
        "scope": smoke.SCOPE,
        "ordinal": ordinal,
        "timeOrigin": time_origin,
    }


def document_receipt(navigation_type: str, time_origin: float) -> bytes:
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
def temporary_server():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        out_dir = root / "out"
        host_dir = root / "host"
        out_dir.mkdir()
        host_dir.mkdir()
        (out_dir / "args.gn").write_text(
            "enable_chromium_wasm_m7_profile_preferences_test=true\n",
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
    server: smoke.ChromeProfilePreferencesOuterReloadServer,
    method: str,
    path: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    host, port = server.server_address[:2]
    connection = http.client.HTTPConnection(host, port, timeout=5)
    try:
        all_headers = dict(headers or {})
        if body is not None:
            all_headers.setdefault("Content-Type", "application/json")
            all_headers.setdefault("Content-Length", str(len(body)))
        connection.request(method, path, body=body, headers=all_headers)
        response = connection.getresponse()
        return response.status, {name.lower(): value for name, value in response.getheaders()}, response.read()
    finally:
        connection.close()


class M7ProfilePreferencesOuterReloadDomSmokeTest(unittest.TestCase):
    def assert_token_matches_digest(
        self, value: object, digest: str, label: str
    ) -> None:
        self.assertTrue(isinstance(value, str), f"{label} type invalid")
        if not isinstance(value, str):
            return
        self.assertTrue(
            secrets.compare_digest(smoke._sha256_text(value), digest),
            f"{label} digest mismatch",
        )

    def test_uses_dedicated_preferences_artifact_and_nonclaiming_scope(self) -> None:
        self.assertEqual(
            smoke.PRODUCT_MODULE_NAME, "chrome_wasm_m7_profile_preferences_test"
        )
        self.assertEqual(
            smoke.PRODUCT_GN_ENABLE_ARGUMENT,
            "enable_chromium_wasm_m7_profile_preferences_test=true",
        )
        self.assertEqual(
            smoke.DEFAULT_OUT_DIR, Path("out/wasm-chrome-m7-profile-preferences")
        )
        self.assertIn("orderly-reload-only", smoke.SCOPE)
        self.assertNotIn("recovery", smoke.SCOPE)
        self.assertEqual(smoke.ARTIFACT_SOURCE_PROVENANCE, "unverified")

    def test_validates_each_preferences_phase_without_raw_values(self) -> None:
        escrow = smoke.new_token_escrow()
        phases = []
        for ordinal, time_origin in ((1, 100.0), (2, 101.0), (3, 102.0)):
            with self.subTest(ordinal=ordinal):
                receipt = passing_result(ordinal, escrow, time_origin)
                phase = smoke.validate_phase_result(
                    receipt,
                    ordinal=ordinal,
                    expected_versions=VERSIONS,
                    expected_artifact_identity=ARTIFACT_IDENTITY,
                    expected_capture_harness_identity=CAPTURE_HARNESS_IDENTITY,
                    expected_origin=ORIGIN,
                    expected_document=smoke.DocumentEvidence(
                        "navigate" if ordinal == 1 else "reload", time_origin
                    ),
                    escrow=escrow,
                    result_token=RESULT_CAPABILITY,
                    session=SESSION_CAPABILITY,
                )
                phases.append(phase)
                self.assertEqual(phase.ordinal, ordinal)
                self.assert_token_matches_digest(
                    escrow.token_a, escrow.token_a_digest, "token A"
                )
                self.assert_token_matches_digest(
                    escrow.token_b, escrow.token_b_digest, "token B"
                )
        smoke.validate_outer_document_transitions(*phases)

    def test_rejects_boolean_redaction_count_and_open_output_grammar(self) -> None:
        escrow = smoke.new_token_escrow()
        receipt = passing_result(1, escrow, 100.0)
        receipt["tokenEvidence"]["rawTokenRedactionCount"] = False
        with self.assertRaises(M0Error):
            smoke.validate_phase_result(
                receipt,
                ordinal=1,
                expected_versions=VERSIONS,
                expected_artifact_identity=ARTIFACT_IDENTITY,
                expected_capture_harness_identity=CAPTURE_HARNESS_IDENTITY,
                expected_origin=ORIGIN,
                expected_document=smoke.DocumentEvidence("navigate", 100.0),
                escrow=escrow,
                result_token=RESULT_CAPABILITY,
                session=SESSION_CAPABILITY,
            )
        receipt = passing_result(1, escrow, 100.0)
        receipt["run"]["stdout"] = ["unexpected native line"]
        with self.assertRaises(M0Error):
            smoke.validate_phase_result(
                receipt,
                ordinal=1,
                expected_versions=VERSIONS,
                expected_artifact_identity=ARTIFACT_IDENTITY,
                expected_capture_harness_identity=CAPTURE_HARNESS_IDENTITY,
                expected_origin=ORIGIN,
                expected_document=smoke.DocumentEvidence("navigate", 100.0),
                escrow=escrow,
                result_token=RESULT_CAPABILITY,
                session=SESSION_CAPABILITY,
            )

    def test_post_evidence_then_get_bootstrap_and_later_phase_gates(self) -> None:
        with temporary_server() as (server, escrow):
            bootstrap_path = f"{smoke.HOST_ROOT}/bootstrap/{SESSION_CAPABILITY}"
            status, headers, _body = request(
                server, "POST", bootstrap_path, document_receipt("navigate", 100.0)
            )
            self.assertEqual(status, 204)
            self.assertEqual(headers.get("cache-control"), "no-store")
            status, _headers, body = request(server, "GET", bootstrap_path)
            self.assertEqual(status, 200)
            first = json.loads(body)
            self.assertEqual(first["ordinal"], 1)
            self.assertEqual(first["mode"], "write")
            self.assert_token_matches_digest(first["tokenA"], escrow.token_a_digest, "bootstrap A")
            self.assertTrue(first["tokenB"] is None, "phase one exposed token B")

            result = passing_result(1, escrow, 100.0)
            status, _headers, _body = request(
                server,
                "POST",
                f"{smoke.HOST_ROOT}/result/{RESULT_CAPABILITY}/1",
                json.dumps(result, separators=(",", ":")).encode("utf-8"),
            )
            self.assertEqual(status, 204)
            status, _headers, _body = request(
                server,
                "POST",
                f"{smoke.HOST_ROOT}/ready/{RESULT_CAPABILITY}/1",
                json.dumps(ready_receipt(1, 100.0), separators=(",", ":")).encode("utf-8"),
            )
            self.assertEqual(status, 204)
            queued_ordinal, queued_ready = server.ready_queue.get(timeout=1)
            self.assertEqual(queued_ordinal, 1)
            self.assertEqual(queued_ready["ordinal"], 1)
            server.session.arm_phase_two(100.0)
            outer_url = smoke.smoke_url(
                server,
                RESULT_CAPABILITY,
                SESSION_CAPABILITY,
                VERSIONS,
                artifact=smoke.artifact_identity(server),
                capture_harness=smoke.capture_harness_identity(server),
                timeout_seconds=30.0,
            )
            parsed_outer_url = urlsplit(outer_url)
            root = f"{parsed_outer_url.path}?{parsed_outer_url.query}"

            # A stale phase-one fetch cannot consume B after arming.
            status, _headers, _body = request(server, "GET", bootstrap_path)
            self.assertEqual(status, 409)

            # Capabilities, destination, and mode are each independently
            # required before a root navigation can open phase two.
            wrong_capability_root = root.replace(RESULT_CAPABILITY, "x" * 32, 1)
            status, _headers, _body = request(
                server,
                "GET",
                wrong_capability_root,
                headers={"Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate"},
            )
            self.assertEqual(status, 200)
            status, _headers, _body = request(
                server, "POST", bootstrap_path, document_receipt("reload", 101.0)
            )
            self.assertEqual(status, 409)
            status, _headers, _body = request(
                server,
                "GET",
                root,
                headers={"Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "navigate"},
            )
            self.assertEqual(status, 200)
            status, _headers, _body = request(
                server, "POST", bootstrap_path, document_receipt("reload", 101.0)
            )
            self.assertEqual(status, 409)
            status, _headers, _body = request(
                server,
                "GET",
                root,
                headers={"Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "no-cors"},
            )
            self.assertEqual(status, 200)
            status, _headers, _body = request(
                server, "POST", bootstrap_path, document_receipt("reload", 101.0)
            )
            self.assertEqual(status, 409)
            status, _headers, _body = request(server, "GET", root)
            self.assertEqual(status, 200)
            status, _headers, _body = request(
                server, "POST", bootstrap_path, document_receipt("reload", 101.0)
            )
            self.assertEqual(status, 409)

            status, _headers, _body = request(
                server,
                "GET",
                root,
                headers={"Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate"},
            )
            self.assertEqual(status, 200)
            # A true top-level reload still needs a fresh, strictly newer
            # reload evidence receipt before B can be returned.
            status, _headers, _body = request(
                server, "POST", bootstrap_path, document_receipt("reload", 100.0)
            )
            self.assertEqual(status, 409)
            status, _headers, _body = request(
                server, "POST", bootstrap_path, document_receipt("reload", 101.0)
            )
            self.assertEqual(status, 204)
            status, _headers, body = request(server, "GET", bootstrap_path)
            self.assertEqual(status, 200)
            second = json.loads(body)
            self.assertEqual(second["ordinal"], 2)
            self.assertEqual(second["mode"], "verify-and-write")
            self.assert_token_matches_digest(second["tokenA"], escrow.token_a_digest, "phase two A")
            self.assert_token_matches_digest(second["tokenB"], escrow.token_b_digest, "phase two B")

            result = passing_result(2, escrow, 101.0)
            status, _headers, _body = request(
                server,
                "POST",
                f"{smoke.HOST_ROOT}/result/{RESULT_CAPABILITY}/2",
                json.dumps(result, separators=(",", ":")).encode("utf-8"),
            )
            self.assertEqual(status, 204)
            status, _headers, _body = request(
                server,
                "POST",
                f"{smoke.HOST_ROOT}/ready/{RESULT_CAPABILITY}/2",
                json.dumps(ready_receipt(2, 101.0), separators=(",", ":")).encode("utf-8"),
            )
            self.assertEqual(status, 204)
            server.session.arm_phase_three(101.0)

            # A third document cannot reuse the second phase's bootstrap and
            # still requires a new top-level reload plus newer evidence.
            status, _headers, _body = request(server, "GET", bootstrap_path)
            self.assertEqual(status, 409)
            status, _headers, _body = request(
                server, "POST", bootstrap_path, document_receipt("reload", 102.0)
            )
            self.assertEqual(status, 409)
            status, _headers, _body = request(
                server,
                "GET",
                root,
                headers={"Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate"},
            )
            self.assertEqual(status, 200)
            status, _headers, _body = request(
                server, "POST", bootstrap_path, document_receipt("reload", 101.0)
            )
            self.assertEqual(status, 409)
            status, _headers, _body = request(
                server, "POST", bootstrap_path, document_receipt("reload", 102.0)
            )
            self.assertEqual(status, 204)
            status, _headers, body = request(server, "GET", bootstrap_path)
            self.assertEqual(status, 200)
            third = json.loads(body)
            self.assertEqual(third["ordinal"], 3)
            self.assertEqual(third["mode"], "verify-b")
            self.assertIsNone(third["tokenA"], "phase three exposed token A")
            self.assertIsNone(third["tokenADigest"], "phase three exposed token A digest")
            self.assert_token_matches_digest(third["tokenB"], escrow.token_b_digest, "phase three B")

    def test_bootstrap_get_waits_for_flushed_document_acknowledgement(self) -> None:
        with temporary_server() as (server, escrow):
            bootstrap_path = f"{smoke.HOST_ROOT}/bootstrap/{SESSION_CAPABILITY}"
            entered = threading.Event()
            release = threading.Event()
            original = smoke.ChromeProfilePreferencesOuterReloadRequestHandler._send_empty

            def delayed_send_empty(handler: object, status: HTTPStatus) -> None:
                original(handler, status)
                if status == HTTPStatus.NO_CONTENT and getattr(handler, "path", "") == bootstrap_path:
                    entered.set()
                    release.wait(timeout=2)

            post_result: dict[str, object] = {}
            get_result: dict[str, object] = {}

            def post_document() -> None:
                try:
                    post_result["value"] = request(
                        server,
                        "POST",
                        bootstrap_path,
                        document_receipt("navigate", 100.0),
                    )
                except Exception:
                    post_result["failed"] = True

            def get_bootstrap() -> None:
                try:
                    get_result["value"] = request(server, "GET", bootstrap_path)
                except Exception:
                    get_result["failed"] = True

            with mock.patch.object(
                smoke.ChromeProfilePreferencesOuterReloadRequestHandler,
                "_send_empty",
                delayed_send_empty,
            ):
                post_thread = threading.Thread(target=post_document, daemon=True)
                post_thread.start()
                self.assertTrue(entered.wait(timeout=1), "document acknowledgement did not pause")
                get_thread = threading.Thread(target=get_bootstrap, daemon=True)
                get_thread.start()
                time.sleep(0.05)
                self.assertTrue(get_thread.is_alive(), "bootstrap GET bypassed flush gate")
                release.set()
                post_thread.join(timeout=2)
                get_thread.join(timeout=2)

            self.assertFalse(post_thread.is_alive(), "POST did not complete")
            self.assertFalse(get_thread.is_alive(), "GET did not complete")
            self.assertFalse(bool(post_result.get("failed")), "POST unexpectedly failed")
            self.assertFalse(bool(get_result.get("failed")), "GET unexpectedly failed")
            post_status = post_result["value"][0]
            get_status, _headers, body = get_result["value"]
            self.assertEqual(post_status, 204)
            self.assertEqual(get_status, 200)
            bootstrap = json.loads(body)
            self.assert_token_matches_digest(
                bootstrap["tokenA"], escrow.token_a_digest, "flush-gated bootstrap A"
            )

    def test_ready_flush_failure_withholds_queue_notification(self) -> None:
        with temporary_server() as (server, _escrow):
            evidence = smoke.DocumentEvidence("navigate", 100.0)
            self.assertTrue(server.session.accept_document(SESSION_CAPABILITY, evidence))
            server.session.acknowledge_document(SESSION_CAPABILITY)
            self.assertIsNotNone(server.session.bootstrap_payload(SESSION_CAPABILITY))
            self.assertTrue(server.session.accept_result(RESULT_CAPABILITY, 1))

            handler = object.__new__(
                smoke.ChromeProfilePreferencesOuterReloadRequestHandler
            )
            handler.server = server
            handler._read_json_body = lambda _maximum: ready_receipt(1, 100.0)
            handler._send_empty = lambda _status: None
            handler._conflict = lambda: self.fail("ready state conflicted")
            handler._not_found = lambda: self.fail("ready capability was rejected")

            class FlushFailure:
                def flush(self) -> None:
                    raise OSError("synthetic flush failure")

            handler.wfile = FlushFailure()
            handler._post_ready(RESULT_CAPABILITY, 1)
            self.assertTrue(server.ready_queue.empty(), "ready queue advanced after flush failure")

    def test_ready_notification_follows_flush_and_cdp_requires_new_loader(self) -> None:
        runner_source = Path(smoke.__file__).read_text(encoding="utf-8")
        module = ast.parse(runner_source)
        handler = next(
            node for node in module.body
            if isinstance(node, ast.ClassDef)
            and node.name == "ChromeProfilePreferencesOuterReloadRequestHandler"
        )
        method = next(
            node for node in handler.body
            if isinstance(node, ast.FunctionDef) and node.name == "_post_ready"
        )
        calls = [
            node for node in ast.walk(method)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        ]
        send = next(node for node in calls if node.func.attr == "_send_empty")
        flush = next(node for node in calls if node.func.attr == "flush")
        put = next(node for node in calls if node.func.attr == "put_nowait")
        self.assertLess(send.lineno, flush.lineno)
        self.assertLess(flush.lineno, put.lineno)

        baseline = smoke.RootFrameIdentity("root", "old-loader")
        self.assertIsNone(
            smoke._root_reload_event(
                {"method": "Page.frameNavigated", "params": {"frame": {
                    "id": "root", "loaderId": "old-loader", "url": "http://x/"}}},
                baseline=baseline,
                expected_page_url_prefix="http://x/",
            )
        )
        candidate = smoke._root_reload_event(
            {"method": "Page.frameNavigated", "params": {"frame": {
                "id": "root", "loaderId": "new-loader", "url": "http://x/"}}},
            baseline=baseline,
            expected_page_url_prefix="http://x/",
        )
        self.assertEqual(candidate, smoke.RootFrameIdentity("root", "new-loader"))

        class FakeClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, object]] = []
                self.events = [
                    {"method": "Page.frameNavigated", "params": {"frame": {
                        "id": "root", "loaderId": "old-loader", "url": "http://x/"}}},
                    {"method": "Page.frameNavigated", "params": {"frame": {
                        "id": "root", "loaderId": "new-loader", "url": "http://x/"}}},
                    {"method": "Page.frameNavigated", "params": {"frame": {
                        "id": "root", "loaderId": "third-loader", "url": "http://x/"}}},
                ]

            def call(self, method: str, parameters: object = None) -> object:
                self.calls.append((method, parameters))
                if method == "Page.getFrameTree":
                    return {"frameTree": {"frame": {
                        "id": "root", "loaderId": "old-loader"}}}
                return {}

            def next_event(self, _timeout: float) -> object:
                return self.events.pop(0) if self.events else None

        class RunningBrowser:
            def poll(self) -> None:
                return None

        client = FakeClient()
        root = smoke.prepare_outer_document_reload(client)
        replacement = smoke.reload_outer_document(
            client,
            RunningBrowser(),
            deque(),
            root,
            "http://x/",
            time.monotonic() + 1,
        )
        self.assertEqual(replacement.loader_id, "new-loader")
        third = smoke.reload_outer_document(
            client,
            RunningBrowser(),
            deque(),
            replacement,
            "http://x/",
            time.monotonic() + 1,
        )
        self.assertEqual(third.loader_id, "third-loader")
        self.assertEqual(
            client.calls,
            [
                ("Page.enable", None),
                ("Page.getFrameTree", None),
                ("Page.reload", {"ignoreCache": True}),
                ("Page.reload", {"ignoreCache": True}),
            ],
        )

    def test_url_has_no_raw_preference_values(self) -> None:
        with temporary_server() as (server, escrow):
            url = smoke.smoke_url(
                server,
                RESULT_CAPABILITY,
                SESSION_CAPABILITY,
                VERSIONS,
                artifact=smoke.artifact_identity(server),
                capture_harness=smoke.capture_harness_identity(server),
                timeout_seconds=30.0,
            )
            parsed = urlsplit(url)
            values = parse_qs(parsed.query, keep_blank_values=True)
            self.assertEqual(set(values), {
                "resultToken", "session", "module", "timeoutMs", "versions",
                "artifact", "captureHarness",
            })
            self.assertFalse(escrow.token_a in url, "raw token A reached URL")
            self.assertFalse(escrow.token_b in url, "raw token B reached URL")

    def test_failure_diagnostics_and_success_sentinel_keep_nonclaims_and_redact(self) -> None:
        escrow = smoke.new_token_escrow()
        with tempfile.TemporaryDirectory() as temporary:
            path = smoke.write_failure_diagnostics(
                Path(temporary),
                stage="synthetic",
                error=RuntimeError(escrow.token_a),
                browser=None,
                browser_stderr=deque(),
                result_ordinals=set(),
                ready_ordinals=set(),
            )
            contents = path.read_text(encoding="utf-8")
        self.assertFalse(escrow.token_a in contents, "raw token reached diagnostics")
        diagnostic = json.loads(contents)
        self.assertIn("not_m7_gate_complete", diagnostic["nonclaims"])
        self.assertIn("not_crash_recovery", diagnostic["nonclaims"])
        source = Path(smoke.__file__).read_text(encoding="utf-8")
        self.assertTrue("\"m7GateComplete\": False" in source,
                        "success sentinel lacks nonclaim")


if __name__ == "__main__":
    unittest.main()
