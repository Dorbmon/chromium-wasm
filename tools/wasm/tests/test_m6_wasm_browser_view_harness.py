#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the real-browser structural BrowserView smoke."""

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


TOOLS_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_wasm_browser_view_smoke


VERSIONS = {
    "chromium": "chromium-revision",
    "v8": "v8-revision",
    "emscripten": "emscripten-revision",
    "port": "port-revision",
}
PINNED_NODE = ROOT_DIR / "third_party/emsdk/node/22.16.0_64bit/bin/node"


def passing_result() -> dict[str, object]:
    """Returns complete evidence for a structural, non-M6-complete smoke."""
    frame = {
        "id": 7,
        "width": 640,
        "height": 480,
        "timestampMs": 123.5,
    }
    readiness = {
        "shellReady": False,
        "surfaceReady": True,
        "firstVisuallyNonEmptyPaint": False,
    }
    return {
        "protocol": 1,
        "case": run_wasm_browser_view_smoke.BROWSER_VIEW_CASE,
        "scope": run_wasm_browser_view_smoke.BROWSER_VIEW_SCOPE,
        "status": "pass",
        "m6GateComplete": False,
        "runtimeExitCode": run_wasm_browser_view_smoke.BROWSER_VIEW_EXIT_CODE,
        "processExitCode": None,
        "runtimeInitialized": True,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "browserViewMarkerObserved": True,
        "abort": None,
        "fatalErrors": [],
        "windowErrors": [],
        "unhandledRejections": [],
        "versions": copy.deepcopy(VERSIONS),
        "frameReports": [frame],
        "readiness": readiness,
        "readinessReports": [copy.deepcopy(readiness)],
        "ozoneFocusReports": [
            {"keyboardTargetPresent": False, "active": True},
            {"keyboardTargetPresent": True, "active": True},
        ],
        "ozoneTextInputStates": [],
        "ozoneTextInputDeliveries": [],
        "ozoneCursorReports": [],
        "canvasBackingStore": {"width": 640, "height": 480},
        "stdout": [],
        "stderr": [run_wasm_browser_view_smoke.BROWSER_VIEW_MARKER],
        "failedChecks": [],
        "error": None,
    }


class BrowserViewSmokeServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.temporary_directory.name) / "out"
        self.out_dir.mkdir()
        self.js_bytes = b"export default function ChromeWasm() {}\n"
        self.wasm_bytes = b"\x00asm\x01\x00\x00\x00"
        (self.out_dir / "chrome_wasm.js").write_bytes(self.js_bytes)
        (self.out_dir / "chrome_wasm.wasm").write_bytes(self.wasm_bytes)
        self.result_queue: queue.Queue[dict[str, object]] = queue.Queue(maxsize=1)
        self.result_token = "test-browser-view-result-token"
        self.server = run_wasm_browser_view_smoke.create_browser_view_smoke_server(
            "127.0.0.1",
            0,
            self.out_dir,
            self.result_token,
            self.result_queue,
            module_name="chrome_wasm",
        )
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            name="test-m6-browser-view-server",
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
            (
                "/__m6_browser_view__/",
                "text/html; charset=utf-8",
                b"browser-view-root",
            ),
            (
                "/__m6_browser_view__/chrome_wasm_browser_view_smoke_host.js",
                "text/javascript; charset=utf-8",
                b"runChromeWasmBrowserViewSmokeFromQuery",
            ),
            (
                "/__m6_browser_view__/artifacts/chrome_wasm.js",
                "text/javascript; charset=utf-8",
                self.js_bytes,
            ),
            (
                "/__m6_browser_view__/artifacts/chrome_wasm.wasm",
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
            "/__m6_browser_view__/artifacts/chrome_wasm.data",
            "/__m6_browser_view__/artifacts/other_module.js",
            "/__m6_browser_view__/artifacts/chrome_wasm.js/extra",
            "/__m6_browser_view__/artifacts/../chrome_wasm.js",
            "/__m6_browser_view__/artifacts/%2e%2e/outside.js",
            "/__m6_browser_view__/not-a-route",
        ):
            with self.subTest(path=path):
                status, headers, body = self._request("GET", path)
                self.assertEqual(status, http.client.NOT_FOUND)
                self._assert_host_security_headers(headers)
                self.assertEqual(
                    headers.get("Content-Type"), "text/plain; charset=utf-8"
                )
                self.assertEqual(body, b"not found\n")

    def test_accepts_only_the_exact_result_token_once(self) -> None:
        result_path = f"/__m6_browser_view__/result/{self.result_token}"
        payload = {
            "protocol": 1,
            "case": run_wasm_browser_view_smoke.BROWSER_VIEW_CASE,
            "scope": run_wasm_browser_view_smoke.BROWSER_VIEW_SCOPE,
        }
        encoded_payload = json.dumps(payload).encode("utf-8")

        status, headers, _ = self._request(
            "POST",
            "/__m6_browser_view__/result/wrong-token",
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
            json.dumps({**payload, "case": "not-browser-view"}).encode("utf-8"),
            (
                b'{"protocol":1,"protocol":1,"case":"'
                + run_wasm_browser_view_smoke.BROWSER_VIEW_CASE.encode("utf-8")
                + b'","scope":"'
                + run_wasm_browser_view_smoke.BROWSER_VIEW_SCOPE.encode("utf-8")
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
            "case": run_wasm_browser_view_smoke.BROWSER_VIEW_CASE,
            "scope": run_wasm_browser_view_smoke.BROWSER_VIEW_SCOPE,
        }
        second = {**first, "status": "second"}
        self.assertTrue(
            run_wasm_browser_view_smoke._accept_browser_view_result(state, first)
        )
        self.assertFalse(
            run_wasm_browser_view_smoke._accept_browser_view_result(state, second)
        )
        self.assertEqual(state.result_queue.get_nowait(), first)

    def test_url_scopes_token_module_and_manifest_versions(self) -> None:
        url = run_wasm_browser_view_smoke.browser_view_smoke_url(
            self.server,
            self.result_token,
            VERSIONS,
            module_name="chrome_wasm",
            timeout_seconds=12.75,
        )
        parsed = urlsplit(url)
        query = parse_qs(parsed.query, strict_parsing=True)

        self.assertEqual(parsed.scheme, "http")
        self.assertEqual(parsed.path, "/__m6_browser_view__/")
        self.assertEqual(query["token"], [self.result_token])
        self.assertEqual(query["module"], ["chrome_wasm"])
        self.assertEqual(query["timeoutMs"], ["12750"])
        self.assertEqual(json.loads(query["versions"][0]), VERSIONS)


class BrowserViewSmokeResultValidationTest(unittest.TestCase):
    def test_accepts_complete_structural_evidence(self) -> None:
        run_wasm_browser_view_smoke.validate_browser_view_smoke_result(
            passing_result(), expected_versions=VERSIONS
        )

    def test_accepts_matching_bridge_process_exit(self) -> None:
        result = passing_result()
        result["processExitCode"] = run_wasm_browser_view_smoke.BROWSER_VIEW_EXIT_CODE
        run_wasm_browser_view_smoke.validate_browser_view_smoke_result(
            result, expected_versions=VERSIONS
        )

    def test_rejects_incomplete_or_nonstructural_evidence(self) -> None:
        cases: tuple[tuple[str, object, str], ...] = (
            ("protocol", True, "protocol mismatch"),
            ("m6GateComplete", True, "m6GateComplete mismatch"),
            ("runtimeExitCode", 13, "runtimeExitCode mismatch"),
            ("runtimeInitialized", 1, "runtimeInitialized mismatch"),
            ("processExitCode", 13, "bridge process exit"),
            ("browserViewMarkerObserved", False, "browserViewMarkerObserved mismatch"),
            ("versions", {"chromium": "wrong"}, "versions do not match"),
            ("fatalErrors", ["abort"], "fatalErrors is not empty"),
            ("failedChecks", ["fake pass"], "failedChecks mismatch"),
            ("frameReports", [], "has no frame reports"),
        )
        for field, invalid_value, error in cases:
            with self.subTest(field=field):
                result = passing_result()
                result[field] = invalid_value
                with self.assertRaisesRegex(M0Error, error):
                    run_wasm_browser_view_smoke.validate_browser_view_smoke_result(
                        result, expected_versions=VERSIONS
                    )

        result = passing_result()
        frames = result["frameReports"]
        assert isinstance(frames, list)
        frames.append({**frames[0], "timestampMs": 124.0})
        with self.assertRaisesRegex(M0Error, "not monotonic"):
            run_wasm_browser_view_smoke.validate_browser_view_smoke_result(
                result, expected_versions=VERSIONS
            )

        result = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        readiness["surfaceReady"] = False
        with self.assertRaisesRegex(M0Error, "surface was not ready"):
            run_wasm_browser_view_smoke.validate_browser_view_smoke_result(
                result, expected_versions=VERSIONS
            )

        result = passing_result()
        result["ozoneFocusReports"] = []
        with self.assertRaisesRegex(M0Error, "active Ozone keyboard target"):
            run_wasm_browser_view_smoke.validate_browser_view_smoke_result(
                result, expected_versions=VERSIONS
            )

        result = passing_result()
        backing_store = result["canvasBackingStore"]
        assert isinstance(backing_store, dict)
        backing_store["width"] = 641
        with self.assertRaisesRegex(M0Error, "does not match the last frame"):
            run_wasm_browser_view_smoke.validate_browser_view_smoke_result(
                result, expected_versions=VERSIONS
            )

        result = passing_result()
        result["stderr"] = []
        with self.assertRaisesRegex(M0Error, "missing its pass marker"):
            run_wasm_browser_view_smoke.validate_browser_view_smoke_result(
                result, expected_versions=VERSIONS
            )


class BrowserViewSmokeHostSourceContractTest(unittest.TestCase):
    def test_host_assets_are_separate_from_the_foundation_lane(self) -> None:
        html = (
            ROOT_DIR / "tools/wasm/host/chrome_wasm_browser_view_smoke.html"
        ).read_text(encoding="utf-8")
        host = (
            ROOT_DIR / "tools/wasm/host/chrome_wasm_browser_view_smoke_host.js"
        ).read_text(encoding="utf-8")
        runner = (ROOT_DIR / "tools/wasm/run_wasm_browser_view_smoke.py").read_text(
            encoding="utf-8"
        )
        foundation_runner = (
            ROOT_DIR / "tools/wasm/run_chrome_wasm_smoke.py"
        ).read_text(encoding="utf-8")

        for token in (
            'id="browser-view-root"',
            'id="browser-canvas"',
            'tabindex="0"',
            'id="versions"',
            'id="browser-view-status"',
            "import {runChromeWasmBrowserViewSmokeFromQuery}",
        ):
            with self.subTest(html_token=token):
                self.assertIn(token, html)

        for token in (
            "const HOST_PROTOCOL = 1;",
            'const BROWSER_VIEW_CASE = "browser_view_structural_m6";',
            'const BROWSER_VIEW_SWITCH = "--wasm-browser-view-smoke";',
            "__chromiumWasmHostBridgeV1",
            "reportFatal(message)",
            "reportProcessExit(report)",
            "reportFrame(report)",
            "reportReadiness(report)",
            "reportOzoneFocusState(report)",
            "reportOzoneTextInputState(report)",
            "reportOzoneTextInputDelivery(report)",
            "reportOzoneCursor(report)",
            "arguments: [BROWSER_VIEW_SWITCH]",
            "canvas backing dimensions do not match frame metadata",
            "no active Ozone keyboard target was observed",
            "m6GateComplete: false",
            "runChromeWasmBrowserViewSmokeFromQuery",
        ):
            with self.subTest(host_token=token):
                self.assertIn(token, host)
        self.assertNotIn("m6GateComplete: true", host)

        for token in (
            'SENTINEL = "CHROMIUM_WASM_M6_BROWSER_VIEW"',
            'BROWSER_VIEW_CASE = "browser_view_structural_m6"',
            'BROWSER_VIEW_SWITCH = "--wasm-browser-view-smoke"',
            '"Cross-Origin-Opener-Policy", "same-origin"',
            '"Cross-Origin-Embedder-Policy", "require-corp"',
            '"application/wasm"',
            "create_browser_view_smoke_server",
            "validate_browser_view_smoke_result",
        ):
            with self.subTest(runner_token=token):
                self.assertIn(token, runner)
        self.assertNotIn("browser_view_structural_m6", foundation_runner)
        self.assertNotIn("wasm-browser-view-smoke", foundation_runner)

    def test_host_javascript_parses_with_the_pinned_node(self) -> None:
        node = str(PINNED_NODE) if PINNED_NODE.is_file() else shutil.which("node")
        if node is None:
            self.skipTest("Node is unavailable")

        host = ROOT_DIR / "tools/wasm/host/chrome_wasm_browser_view_smoke_host.js"
        completed = subprocess.run(
            [node, "--check", str(host)],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            "Node rejected the BrowserView structural host:\n"
            + completed.stdout
            + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
