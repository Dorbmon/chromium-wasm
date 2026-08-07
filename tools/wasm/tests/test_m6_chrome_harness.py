#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the scoped M6 Chrome foundation host harness."""

from __future__ import annotations

import copy
import http.client
import json
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest import mock


TOOLS_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import check_m6_chrome_boundary
import run_chrome_wasm_smoke


VERSIONS = {
    "chromium": "chromium-revision",
    "v8": "v8-revision",
    "emscripten": "emscripten-revision",
    "port": "port-revision",
}
PINNED_NODE = ROOT_DIR / "third_party/emsdk/node/22.16.0_64bit/bin/node"


def passing_result() -> dict[str, object]:
    """Returns the complete, intentionally non-M6-complete foundation result."""
    return {
        "protocol": 1,
        "case": run_chrome_wasm_smoke.FOUNDATION_CASE,
        "scope": run_chrome_wasm_smoke.FOUNDATION_SCOPE,
        "status": "pass",
        "m6GateComplete": False,
        "runtimeExitCode": run_chrome_wasm_smoke.FOUNDATION_EXIT_CODE,
        "processExitCode": None,
        "runtimeInitialized": True,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "foundationMarkerObserved": True,
        "abort": None,
        "fatalErrors": [],
        "windowErrors": [],
        "unhandledRejections": [],
        "versions": copy.deepcopy(VERSIONS),
        "heartbeat": {
            "anchor": "runtime-initialized",
            "elapsedMs": 100,
            "timerStartTicks": 3,
            "timerEndTicks": 5,
            "timerDelta": 2,
            "animationFrameStartTicks": 7,
            "animationFrameEndTicks": 9,
            "animationFrameDelta": 2,
            "maxTimerGapMs": 250,
        },
        "stdout": [],
        "stderr": [run_chrome_wasm_smoke.FOUNDATION_MARKER],
        "failedChecks": [],
        "error": None,
    }


class ChromeM6ServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.temporary_directory.name) / "out"
        self.out_dir.mkdir()
        self.js_bytes = b"export default function ChromeWasm() {}\n"
        self.wasm_bytes = b"\x00asm\x01\x00\x00\x00"
        (self.out_dir / "chrome_wasm.js").write_bytes(self.js_bytes)
        (self.out_dir / "chrome_wasm.wasm").write_bytes(self.wasm_bytes)
        self.result_queue: queue.Queue[dict[str, object]] = queue.Queue(maxsize=1)
        self.result_token = "test-foundation-result-token"
        self.server = run_chrome_wasm_smoke.create_chrome_m6_server(
            "127.0.0.1",
            0,
            self.out_dir,
            self.result_token,
            self.result_queue,
            module_name="chrome_wasm",
        )
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            name="test-m6-chrome-server",
            daemon=True,
        )
        self.server_thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=5)
        self.temporary_directory.cleanup()

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, http.client.HTTPMessage, bytes]:
        host, port = self.server.server_address[:2]
        connection = http.client.HTTPConnection(host, port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.headers, response.read()
        finally:
            connection.close()

    def _assert_host_security_headers(self, headers: http.client.HTTPMessage) -> None:
        self.assertEqual(headers.get("Cross-Origin-Opener-Policy"), "same-origin")
        self.assertEqual(
            headers.get("Cross-Origin-Embedder-Policy"), "require-corp"
        )
        self.assertEqual(
            headers.get("Cross-Origin-Resource-Policy"), "same-origin"
        )
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")

    def test_serves_loader_and_artifacts_with_isolation_and_exact_mime_types(
        self,
    ) -> None:
        expectations = (
            ("/__m6__/", "text/html; charset=utf-8", b"browser-canvas"),
            (
                "/__m6__/chrome_wasm_host.js",
                "text/javascript; charset=utf-8",
                b"runChromeWasmFoundationFromQuery",
            ),
            (
                "/__m6__/artifacts/chrome_wasm.js",
                "text/javascript; charset=utf-8",
                self.js_bytes,
            ),
            (
                "/__m6__/artifacts/chrome_wasm.wasm",
                "application/wasm",
                self.wasm_bytes,
            ),
        )

        for path, content_type, expected_body in expectations:
            with self.subTest(path=path):
                status, headers, body = self._request("GET", path)
                self.assertEqual(status, http.client.OK)
                self._assert_host_security_headers(headers)
                self.assertEqual(headers.get("Content-Type"), content_type)
                self.assertIn(expected_body, body)

    def test_rejects_nonexact_artifacts_and_traversal(self) -> None:
        outside = self.out_dir.parent / "outside.js"
        outside.write_text("not an artifact", encoding="utf-8")

        for path in (
            "/__m6__/artifacts/chrome_wasm.data",
            "/__m6__/artifacts/other_module.js",
            "/__m6__/artifacts/chrome_wasm.js/extra",
            "/__m6__/artifacts/../chrome_wasm.js",
            "/__m6__/artifacts/%2e%2e/outside.js",
            "/__m6__/not-a-route",
        ):
            with self.subTest(path=path):
                status, headers, body = self._request("GET", path)
                self.assertEqual(status, http.client.NOT_FOUND)
                self._assert_host_security_headers(headers)
                self.assertEqual(headers.get("Content-Type"), "text/plain; charset=utf-8")
                self.assertEqual(body, b"not found\n")

    def test_accepts_only_the_exact_result_token_once(self) -> None:
        result_path = f"/__m6__/result/{self.result_token}"
        payload = {
            "protocol": 1,
            "case": run_chrome_wasm_smoke.FOUNDATION_CASE,
            "scope": run_chrome_wasm_smoke.FOUNDATION_SCOPE,
        }
        encoded_payload = json.dumps(payload).encode("utf-8")

        status, headers, _ = self._request(
            "POST",
            "/__m6__/result/wrong-token",
            body=encoded_payload,
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, http.client.NOT_FOUND)
        self._assert_host_security_headers(headers)
        self.assertTrue(self.result_queue.empty())
        self.assertFalse(self.server.result_received)

        invalid_payloads = (
            b"not-json",
            json.dumps({**payload, "protocol": True}).encode("utf-8"),
            json.dumps({**payload, "case": "not-foundation"}).encode("utf-8"),
            (
                b'{"protocol":1,"protocol":1,"case":"'
                + run_chrome_wasm_smoke.FOUNDATION_CASE.encode("utf-8")
                + b'","scope":"'
                + run_chrome_wasm_smoke.FOUNDATION_SCOPE.encode("utf-8")
                + b'"}'
            ),
        )
        for invalid_payload in invalid_payloads:
            with self.subTest(invalid_payload=invalid_payload):
                status, headers, _ = self._request(
                    "POST",
                    result_path,
                    body=invalid_payload,
                    headers={"Content-Type": "application/json"},
                )
                self.assertEqual(status, http.client.BAD_REQUEST)
                self._assert_host_security_headers(headers)
                self.assertTrue(self.result_queue.empty())
                self.assertFalse(self.server.result_received)

        status, headers, body = self._request(
            "POST",
            result_path,
            body=encoded_payload,
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, http.client.NO_CONTENT)
        self._assert_host_security_headers(headers)
        self.assertEqual(body, b"")
        self.assertTrue(self.server.result_received)
        self.assertEqual(self.result_queue.get_nowait(), payload)

        status, headers, _ = self._request(
            "POST",
            result_path,
            body=encoded_payload,
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, http.client.CONFLICT)
        self._assert_host_security_headers(headers)

    def test_one_shot_result_acceptance_is_atomic(self) -> None:
        class ResultState:
            result_queue: queue.Queue[dict[str, object]]
            result_received: bool
            result_lock: threading.Lock

            def __init__(self) -> None:
                self.result_queue = queue.Queue(maxsize=1)
                self.result_received = False
                self.result_lock = threading.Lock()

        state = ResultState()
        first = {
            "protocol": 1,
            "case": run_chrome_wasm_smoke.FOUNDATION_CASE,
            "scope": run_chrome_wasm_smoke.FOUNDATION_SCOPE,
        }
        second = {**first, "status": "second"}
        self.assertTrue(run_chrome_wasm_smoke._accept_foundation_result(state, first))
        self.assertFalse(run_chrome_wasm_smoke._accept_foundation_result(state, second))
        self.assertEqual(state.result_queue.get_nowait(), first)

    def test_chrome_url_scopes_token_module_and_manifest_versions(self) -> None:
        url = run_chrome_wasm_smoke.chrome_m6_url(
            self.server,
            self.result_token,
            VERSIONS,
            module_name="chrome_wasm",
            timeout_seconds=12.75,
        )
        parsed = urlsplit(url)
        query = parse_qs(parsed.query, strict_parsing=True)

        self.assertEqual(parsed.scheme, "http")
        self.assertEqual(parsed.path, "/__m6__/")
        self.assertEqual(query["token"], [self.result_token])
        self.assertEqual(query["module"], ["chrome_wasm"])
        self.assertEqual(query["timeoutMs"], ["12750"])
        self.assertEqual(json.loads(query["versions"][0]), VERSIONS)


class ChromeM6ResultValidationTest(unittest.TestCase):
    def test_accepts_complete_foundation_evidence(self) -> None:
        run_chrome_wasm_smoke.validate_chrome_foundation_result(
            passing_result(), expected_versions=VERSIONS
        )

    def test_accepts_matching_bridge_process_exit(self) -> None:
        result = passing_result()
        result["processExitCode"] = run_chrome_wasm_smoke.FOUNDATION_EXIT_CODE
        run_chrome_wasm_smoke.validate_chrome_foundation_result(
            result, expected_versions=VERSIONS
        )

    def test_rejects_nonfoundation_or_incomplete_evidence(self) -> None:
        cases: tuple[tuple[str, object, str], ...] = (
            ("protocol", True, "protocol mismatch"),
            ("m6GateComplete", 0, "m6GateComplete mismatch"),
            ("m6GateComplete", True, "m6GateComplete mismatch"),
            ("runtimeExitCode", 0, "runtimeExitCode mismatch"),
            ("runtimeInitialized", 1, "runtimeInitialized mismatch"),
            ("processExitCode", 0, "bridge process exit"),
            ("processExitCode", True, "bridge process exit"),
            ("foundationMarkerObserved", False, "foundationMarkerObserved mismatch"),
            ("versions", {"chromium": "wrong"}, "versions do not match"),
            ("fatalErrors", ["abort"], "fatalErrors is not empty"),
            ("failedChecks", ["fake pass"], "failedChecks mismatch"),
        )
        for field, invalid_value, error in cases:
            with self.subTest(field=field):
                result = passing_result()
                result[field] = invalid_value
                with self.assertRaisesRegex(M0Error, error):
                    run_chrome_wasm_smoke.validate_chrome_foundation_result(
                        result, expected_versions=VERSIONS
                    )

        for field, invalid_value, error in (
            ("elapsedMs", 99, "heartbeat interval was too short"),
            ("timerStartTicks", True, "timerStartTicks is not an integer"),
            ("timerDelta", 1, "timerDelta did not advance"),
            ("animationFrameDelta", True, "animationFrameDelta did not advance"),
            ("timerDelta", 3, "timerDelta is inconsistent"),
            ("maxTimerGapMs", -1, "heartbeat gap exceeded"),
            ("maxTimerGapMs", 251, "heartbeat gap exceeded"),
        ):
            with self.subTest(heartbeat_field=field):
                result = passing_result()
                heartbeat = result["heartbeat"]
                assert isinstance(heartbeat, dict)
                heartbeat[field] = invalid_value
                with self.assertRaisesRegex(M0Error, error):
                    run_chrome_wasm_smoke.validate_chrome_foundation_result(
                        result, expected_versions=VERSIONS
                    )

        result = passing_result()
        result["stderr"] = []
        with self.assertRaisesRegex(M0Error, "lifecycle marker"):
            run_chrome_wasm_smoke.validate_chrome_foundation_result(
                result, expected_versions=VERSIONS
            )


class ChromeM6HostSourceContractTest(unittest.TestCase):
    def test_host_assets_expose_the_scoped_foundation_contract(self) -> None:
        html = (ROOT_DIR / "tools/wasm/host/chrome_wasm.html").read_text(
            encoding="utf-8"
        )
        host = (ROOT_DIR / "tools/wasm/host/chrome_wasm_host.js").read_text(
            encoding="utf-8"
        )
        runner = (ROOT_DIR / "tools/wasm/run_chrome_wasm_smoke.py").read_text(
            encoding="utf-8"
        )

        for token in (
            'id="browser-canvas"',
            'tabindex="0"',
            'id="versions"',
            'id="chrome-status"',
            'import {runChromeWasmFoundationFromQuery}',
        ):
            with self.subTest(html_token=token):
                self.assertIn(token, html)

        for token in (
            "const HOST_PROTOCOL = 1;",
            "__chromiumWasmHostBridgeV1",
            "protocol: HOST_PROTOCOL,",
            "onRuntimeInitialized:",
            "onExit:",
            "onAbort:",
            "#markRuntimeInitialized()",
            "MAX_FOUNDATION_TIMEOUT_MS = 120000",
            "requestAnimationFrame",
            "validateFoundationResult",
            "encodeURIComponent(token)",
            "m6GateComplete: false",
        ):
            with self.subTest(host_token=token):
                self.assertIn(token, host)
        self.assertNotIn("m6GateComplete: true", host)

        for token in (
            '"Cross-Origin-Opener-Policy", "same-origin"',
            '"Cross-Origin-Embedder-Policy", "require-corp"',
            '"application/wasm"',
            "result_token",
            "check_boundary(out_dir)",
            "validate_chrome_foundation_result",
            "FOUNDATION_EXIT_CODE = 13",
        ):
            with self.subTest(runner_token=token):
                self.assertIn(token, runner)

    def test_host_javascript_parses_with_the_pinned_node(self) -> None:
        node = str(PINNED_NODE) if PINNED_NODE.is_file() else shutil.which("node")
        if node is None:
            self.skipTest("Node is unavailable")

        host = ROOT_DIR / "tools/wasm/host/chrome_wasm_host.js"
        completed = subprocess.run(
            [node, "--check", str(host)],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            "Node rejected the Chrome foundation host:\n"
            + completed.stdout
            + completed.stderr,
        )


class ChromeM6BoundaryCheckerTest(unittest.TestCase):
    def test_accepts_no_path_for_every_forbidden_target(self) -> None:
        no_path = "No non-data paths found between these two targets.\n"
        completed = subprocess.CompletedProcess([], 0, stdout=no_path, stderr="")
        with tempfile.TemporaryDirectory() as temporary_directory:
            with mock.patch(
                "check_m6_chrome_boundary.subprocess.run",
                return_value=completed,
            ) as run:
                check_m6_chrome_boundary.check_boundary(Path(temporary_directory))

        self.assertEqual(
            run.call_count, len(check_m6_chrome_boundary._FORBIDDEN_TARGETS)
        )

    def test_rejects_a_found_path_or_gn_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            found_path = subprocess.CompletedProcess(
                [], 0, stdout="//chrome:chrome_wasm -> forbidden\n", stderr=""
            )
            with mock.patch(
                "check_m6_chrome_boundary.subprocess.run", return_value=found_path
            ):
                with self.assertRaisesRegex(M0Error, "forbidden target"):
                    check_m6_chrome_boundary.check_boundary(Path(temporary_directory))

            failed = subprocess.CompletedProcess([], 1, stdout="", stderr="gn failed")
            with mock.patch(
                "check_m6_chrome_boundary.subprocess.run", return_value=failed
            ):
                with self.assertRaisesRegex(M0Error, "gn path failed"):
                    check_m6_chrome_boundary.check_boundary(Path(temporary_directory))


if __name__ == "__main__":
    unittest.main()
