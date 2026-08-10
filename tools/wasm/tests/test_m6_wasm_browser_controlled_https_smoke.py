#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the M6 controlled-HTTPS Chrome browser harness."""

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
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m6_wasm_browser_controlled_https_smoke as smoke
from tools.wasm.tests.m3_source_contract_test_support import source


VERSIONS = {
    "chromium": "chromium-revision",
    "v8": "v8-revision",
    "emscripten": "emscripten-revision",
    "port": "port-revision",
}
WISP_ENDPOINT = "ws://127.0.0.1:43210/wisp/"
FIXTURE_URL = "https://a.test:43211/m5/m6-ui"
TRANSCRIPT_URL = "http://127.0.0.1:43210/status"


def relay_ready_json() -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "httpsUrl": "https://a.test:43211/m5/",
            "m6UiUrl": FIXTURE_URL,
            "transcriptUrl": TRANSCRIPT_URL,
            "wispEndpoint": WISP_ENDPOINT,
        },
        separators=(",", ":"),
    )


def passing_result() -> dict[str, object]:
    return {
        "protocol": 1,
        "case": smoke.CASE,
        "scope": smoke.SCOPE,
        "status": "pass",
        "m6GateComplete": False,
        "runtimeExitCode": 0,
        "processExitCode": 0,
        "runtimeInitialized": True,
        "factorySettled": True,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "controlledHttps": {
            "wispConfigured": True,
            "runtimeArgumentsConfigured": True,
            "configurationPrecededFactory": True,
            "readyMarkerObserved": True,
            "navigatedMarkerObserved": True,
            "frameIdAtNavigatedMarker": 1,
            "postNavigatedFrameObserved": True,
            "firstVisuallyNonEmptyPaintReportObserved": True,
            "postNavigatedFrameAfterFirstVisuallyNonEmptyPaintObserved": True,
            "passMarkerObserved": True,
        },
        "abort": None,
        "fatalErrors": [],
        "windowErrors": [],
        "unhandledRejections": [],
        "versions": copy.deepcopy(VERSIONS),
        "frameReports": [
            {"id": 1, "width": 640, "height": 480, "timestampMs": 1.0},
            {"id": 2, "width": 640, "height": 480, "timestampMs": 2.0},
        ],
        "readiness": {
            "shellReady": True,
            "surfaceReady": True,
            "firstVisuallyNonEmptyPaint": True,
        },
        "readinessReports": [
            {
                "shellReady": True,
                "surfaceReady": True,
                "firstVisuallyNonEmptyPaint": True,
            }
        ],
        "ozoneFocusReports": [{"keyboardTargetPresent": True, "active": True}],
        "ozoneTextInputStates": [],
        "ozoneTextInputDeliveries": [],
        "ozoneCursorReports": [],
        "canvasBackingStore": {"width": 640, "height": 480},
        "stdout": [smoke.READY_MARKER, smoke.NAVIGATED_MARKER],
        "stderr": [smoke.PASS_MARKER],
        "failedChecks": [],
        "error": None,
    }


class ControlledHttpsRelayContractTest(unittest.TestCase):
    def test_parses_only_the_exact_relay_m6_ui_fixture(self) -> None:
        ready = smoke.parse_relay_ready_line(relay_ready_json())
        self.assertEqual(ready.wisp_endpoint, WISP_ENDPOINT)
        self.assertEqual(ready.m6_ui_url, FIXTURE_URL)
        self.assertEqual(ready.transcript_url, TRANSCRIPT_URL)

        for mutate, expression in (
            (
                lambda payload: payload.pop("m6UiUrl"),
                "m6UiUrl",
            ),
            (
                lambda payload: payload.__setitem__(
                    "m6UiUrl", "https://a.test:43211/m5/"
                ),
                "fixture policy",
            ),
            (
                lambda payload: payload.__setitem__(
                    "m6UiUrl", "https://a.test:43212/m5/m6-ui"
                ),
                "H2 fixture port",
            ),
            (
                lambda payload: payload.__setitem__(
                    "wispEndpoint", "ws://example.invalid:43210/wisp/"
                ),
                "loopback",
            ),
            (
                lambda payload: payload.__setitem__(
                    "wispEndpoint", "wss://example.invalid:43210/wisp/"
                ),
                "loopback",
            ),
            (
                lambda payload: payload.__setitem__(
                    "wispEndpoint", "ws://127.0.0.1:43210/not-wisp/"
                ),
                "/wisp/",
            ),
        ):
            with self.subTest(expression=expression):
                payload = json.loads(relay_ready_json())
                mutate(payload)
                with self.assertRaisesRegex(M0Error, expression):
                    smoke.parse_relay_ready_line(json.dumps(payload))

    def test_rejects_duplicate_relay_ready_keys(self) -> None:
        duplicate = (
            '{"httpsUrl":"https://a.test:43211/m5/",'
            '"m6UiUrl":"https://a.test:43211/m5/m6-ui",'
            '"m6UiUrl":"https://a.test:43211/m5/m6-ui",'
            '"transcriptUrl":"http://127.0.0.1:43210/status",'
            '"wispEndpoint":"ws://127.0.0.1:43210/wisp/"}'
        )
        with self.assertRaisesRegex(M0Error, "not valid JSON"):
            smoke.parse_relay_ready_line(duplicate)

    def test_smoke_url_carries_only_the_validated_wisp_and_fixture_values(self) -> None:
        ready = smoke.parse_relay_ready_line(relay_ready_json())
        server = SimpleNamespace(server_address=("127.0.0.1", 8000))
        url = smoke.smoke_url(
            server,
            "result-token",
            VERSIONS,
            relay_ready=ready,
            module_name="chrome_wasm_m6_https_test",
            timeout_seconds=90,
        )
        parsed = urlsplit(url)
        self.assertEqual(parsed.path, smoke.HOST_ROOT + "/")
        query = parse_qs(parsed.query, strict_parsing=True)
        self.assertEqual(query["wispEndpoint"], [WISP_ENDPOINT])
        self.assertEqual(query["fixtureUrl"], [FIXTURE_URL])
        self.assertEqual(query["module"], ["chrome_wasm_m6_https_test"])
        self.assertNotIn("m5_url", query)

    def test_accepts_only_loopback_ws_or_wss_wisp_paths(self) -> None:
        self.assertEqual(
            smoke.validate_controlled_wisp_endpoint(WISP_ENDPOINT), WISP_ENDPOINT
        )
        self.assertEqual(
            smoke.validate_controlled_wisp_endpoint(
                "wss://localhost:43210/wisp/"
            ),
            "wss://localhost:43210/wisp/",
        )
        for endpoint, expression in (
            ("ws://127.0.0.1/wisp/", "port"),
            ("wss://[::1]:70000/wisp/", "port"),
            ("ws://127.0.0.1:43210/wisp/?query=1", "safe loopback"),
            ("ws://user@127.0.0.1:43210/wisp/", "safe loopback"),
        ):
            with self.subTest(endpoint=endpoint):
                with self.assertRaisesRegex(M0Error, expression):
                    smoke.validate_controlled_wisp_endpoint(endpoint)

    def test_requires_one_h2_fixture_delivery_event(self) -> None:
        status = {
            "fixture": smoke.RELAY_FIXTURE,
            "protocol": 1,
            "ready": True,
            "m6UiRequests": 1,
            "h2Requests": {"protocol": "h2", "count": 1},
            "transcript": [
                {"sequence": 1, "event": "fixture-ready"},
                {"sequence": 2, "event": "h2-m6-ui"},
            ],
        }
        smoke.validate_relay_status(status)

        for mutate, expression in (
            (
                lambda payload: payload.__setitem__("m6UiRequests", 0),
                "exactly one",
            ),
            (
                lambda payload: payload.__setitem__("m6UiRequests", 2),
                "exactly one",
            ),
            (
                lambda payload: payload.__setitem__("fixture", "wrong-fixture"),
                "not ready",
            ),
            (
                lambda payload: payload.__setitem__(
                    "transcript", [{"sequence": 1, "event": "fixture-ready"}]
                ),
                "M6 UI event",
            ),
            (
                lambda payload: payload.__setitem__(
                    "h2Requests", {"protocol": "http/1.1", "count": 1}
                ),
                "HTTP/2",
            ),
            (
                lambda payload: payload.__setitem__(
                    "h2Requests", {"protocol": "h2", "count": 2}
                ),
                "exactly one HTTP/2",
            ),
            (
                lambda payload: payload.__setitem__(
                    "transcript",
                    [
                        {"sequence": 1, "event": "h2-m6-ui"},
                        {"sequence": 2, "event": "h2-m6-ui"},
                    ],
                ),
                "exactly one M6 UI event",
            ),
            (
                lambda payload: payload.__setitem__(
                    "transcript",
                    [
                        {"sequence": index + 1, "event": "fixture-ready"}
                        for index in range(smoke.MAX_RELAY_TRANSCRIPT_ENTRIES + 1)
                    ],
                ),
                "outside its bounds",
            ),
        ):
            with self.subTest(expression=expression):
                candidate = copy.deepcopy(status)
                mutate(candidate)
                with self.assertRaisesRegex(M0Error, expression):
                    smoke.validate_relay_status(candidate)


class ControlledHttpsHostServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.temporary_directory.name) / "out"
        self.out_dir.mkdir()
        self.js_bytes = b"export default function ChromeWasm() {}\n"
        self.wasm_bytes = b"\x00asm\x01\x00\x00\x00"
        (self.out_dir / "chrome_wasm_m6_https_test.js").write_bytes(self.js_bytes)
        (self.out_dir / "chrome_wasm_m6_https_test.wasm").write_bytes(
            self.wasm_bytes
        )
        self.result_queue: queue.Queue[dict[str, object]] = queue.Queue(maxsize=1)
        self.result_token = "controlled-https-result-token"
        self.server = smoke.create_server(
            "127.0.0.1",
            0,
            self.out_dir,
            self.result_token,
            self.result_queue,
            module_name="chrome_wasm_m6_https_test",
        )
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            name="test-m6-controlled-https-server",
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

    def _assert_security_headers(self, headers: http.client.HTTPMessage) -> None:
        self.assertEqual(headers.get("Cross-Origin-Opener-Policy"), "same-origin")
        self.assertEqual(
            headers.get("Cross-Origin-Embedder-Policy"), "require-corp"
        )
        self.assertEqual(
            headers.get("Cross-Origin-Resource-Policy"), "same-origin"
        )
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")

    def test_serves_only_its_loader_host_and_two_artifacts(self) -> None:
        expectations = (
            (
                smoke.HOST_ROOT + "/",
                "text/html; charset=utf-8",
                b"browser-controlled-https-root",
            ),
            (
                smoke.HOST_ROOT
                + "/chrome_wasm_browser_controlled_https_smoke_host.js",
                "text/javascript; charset=utf-8",
                b"chromiumWasmWisp",
            ),
            (
                smoke.HOST_ROOT + "/artifacts/chrome_wasm_m6_https_test.js",
                "text/javascript; charset=utf-8",
                self.js_bytes,
            ),
            (
                smoke.HOST_ROOT + "/artifacts/chrome_wasm_m6_https_test.wasm",
                "application/wasm",
                self.wasm_bytes,
            ),
        )
        for path, content_type, expected_body in expectations:
            with self.subTest(path=path):
                status, headers, body = self._request("GET", path)
                self.assertEqual(status, http.client.OK)
                self._assert_security_headers(headers)
                self.assertEqual(headers.get("Content-Type"), content_type)
                self.assertIn(expected_body, body)

        for path in (
            smoke.HOST_ROOT + "/artifacts/chrome_wasm_m6_https_test.data",
            smoke.HOST_ROOT + "/artifacts/other.js",
            smoke.HOST_ROOT + "/artifacts/../chrome_wasm_m6_https_test.js",
            smoke.HOST_ROOT + "/not-found",
        ):
            with self.subTest(path=path):
                status, headers, body = self._request("GET", path)
                self.assertEqual(status, http.client.NOT_FOUND)
                self._assert_security_headers(headers)
                self.assertEqual(body, b"not found\n")

    def test_accepts_one_schema_valid_result_and_rejects_duplicates(self) -> None:
        result_path = smoke.HOST_ROOT + "/result/" + self.result_token
        body = json.dumps(passing_result(), separators=(",", ":")).encode()
        headers = {"Content-Type": "application/json"}
        status, response_headers, response_body = self._request(
            "POST", result_path, body=body, headers=headers
        )
        self.assertEqual(status, http.client.NO_CONTENT)
        self._assert_security_headers(response_headers)
        self.assertEqual(response_body, b"")
        self.assertEqual(self.result_queue.get(timeout=1), passing_result())

        status, _, body = self._request(
            "POST", result_path, body=body, headers=headers
        )
        self.assertEqual(status, http.client.CONFLICT)
        self.assertIn(b"already received", body)

    def test_rejects_wrong_or_duplicate_json_results(self) -> None:
        headers = {"Content-Type": "application/json"}
        wrong_path = smoke.HOST_ROOT + "/result/not-the-token"
        status, _, _ = self._request(
            "POST",
            wrong_path,
            body=json.dumps(passing_result()).encode(),
            headers=headers,
        )
        self.assertEqual(status, http.client.NOT_FOUND)

        duplicate_key = (
            b'{"protocol":1,"protocol":1,"case":"browser_controlled_https_m6"}'
        )
        status, _, body = self._request(
            "POST",
            smoke.HOST_ROOT + "/result/" + self.result_token,
            body=duplicate_key,
            headers=headers,
        )
        self.assertEqual(status, http.client.BAD_REQUEST)
        self.assertIn(b"invalid controlled-HTTPS result", body)


class ControlledHttpsResultContractTest(unittest.TestCase):
    def test_accepts_complete_cxx_marker_wisp_and_presentation_evidence(self) -> None:
        smoke.validate_result(passing_result(), expected_versions=VERSIONS)

    def test_rejects_missing_terminal_or_host_setup_evidence(self) -> None:
        for mutate, expression in (
            (
                lambda result: result["stdout"].clear(),
                smoke.READY_MARKER,
            ),
            (
                lambda result: result["controlledHttps"].__setitem__(
                    "wispConfigured", False
                ),
                "wispConfigured",
            ),
            (
                lambda result: result["controlledHttps"].__setitem__(
                    "configurationPrecededFactory", False
                ),
                "configurationPrecededFactory",
            ),
            (
                lambda result: result["controlledHttps"].__setitem__(
                    "postNavigatedFrameObserved", False
                ),
                "postNavigatedFrameObserved",
            ),
            (
                lambda result: result["controlledHttps"].__setitem__(
                    "frameIdAtNavigatedMarker", 2
                ),
                "canvas frame after the NAVIGATED marker",
            ),
            (
                lambda result: result["controlledHttps"].__setitem__(
                    "postNavigatedFrameAfterFirstVisuallyNonEmptyPaintObserved",
                    False,
                ),
                "postNavigatedFrameAfterFirstVisuallyNonEmptyPaintObserved",
            ),
            (
                lambda result: (
                    result["readiness"].__setitem__(
                        "firstVisuallyNonEmptyPaint", False
                    ),
                    result["readinessReports"][0].__setitem__(
                        "firstVisuallyNonEmptyPaint", False
                    ),
                ),
                "first visually non-empty paint",
            ),
            (
                lambda result: result["ozoneFocusReports"].clear(),
                "active Ozone",
            ),
        ):
            with self.subTest(expression=expression):
                result = passing_result()
                mutate(result)
                with self.assertRaisesRegex(M0Error, expression):
                    smoke.validate_result(result, expected_versions=VERSIONS)

    def test_parser_rejects_duplicate_or_wrong_scope_results(self) -> None:
        encoded = json.dumps(passing_result(), separators=(",", ":")).encode()
        self.assertEqual(smoke.parse_result_payload(encoded), passing_result())
        self.assertIsNone(
            smoke.parse_result_payload(
                b'{"protocol":1,"protocol":1,"case":"browser_controlled_https_m6"}'
            )
        )
        wrong_scope = passing_result()
        wrong_scope["scope"] = "wrong"
        self.assertIsNone(
            smoke.parse_result_payload(json.dumps(wrong_scope).encode())
        )


class ControlledHttpsHostSourceContractTest(unittest.TestCase):
    def test_wisp_and_exact_fixture_switches_precede_factory_invocation(self) -> None:
        host = source(
            "tools/wasm/host/chrome_wasm_browser_controlled_https_smoke_host.js"
        )
        for expected in (
            'const SWITCH = "--wasm-browser-controlled-https-smoke";',
            'const URL_SWITCH = "--wasm-browser-controlled-https-url";',
            'const READY_MARKER = "CHROMIUM_WASM_M6_CONTROLLED_HTTPS:READY";',
            'const NAVIGATED_MARKER = "CHROMIUM_WASM_M6_CONTROLLED_HTTPS:NAVIGATED";',
            'const PASS_MARKER = "CHROMIUM_WASM_M6_CONTROLLED_HTTPS:PASS";',
            'const FIXTURE_PATH = "/m5/m6-ui";',
            "moduleOptions.chromiumWasmWisp = wispConfiguration;",
            "subprotocol: WISP_SUBPROTOCOL,",
            "!isLoopbackHostname(endpoint.hostname)",
            'endpoint.pathname !== "/wisp/"',
            "endpoint.username",
            "endpoint.password",
            "endpoint.search",
            "endpoint.hash",
            "URL_SWITCH + \"=\" + controlledUrl.href",
            "namespace.default(moduleOptions)",
            "reportFrame(report)",
            "reportReadiness(report)",
            "reportOzoneFocusState(report)",
            "postNavigatedFrameObserved",
            "postNavigatedFrameAfterFirstVisuallyNonEmptyPaintObserved",
            "firstVisuallyNonEmptyPaint === true",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, host)
        self.assertLess(
            host.index("moduleOptions.chromiumWasmWisp = wispConfiguration;"),
            host.index("namespace.default(moduleOptions)"),
        )
        self.assertLess(
            host.index("URL_SWITCH + \"=\" + controlledUrl.href"),
            host.index("namespace.default(moduleOptions)"),
        )

    def test_runner_uses_fresh_relay_then_requires_exact_fixture_evidence(self) -> None:
        runner = source("tools/wasm/run_m6_wasm_browser_controlled_https_smoke.py")
        for expected in (
            "chrome_wasm_m6_https_test",
            "m6UiUrl",
            "validate_m6_ui_url",
            "--wasm-browser-controlled-https-smoke",
            "--wasm-browser-controlled-https-url",
            "validate_controlled_wisp_endpoint",
            "m6UiRequests",
            "h2-m6-ui",
            "chromium-wasm-m5-network-v1",
            "check_controlled_https_boundary(out_dir)",
            "CONTROLLED_HTTPS_GN_TARGET",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, runner)
        self.assertNotIn("ccall(", runner)


if __name__ == "__main__":
    unittest.main()
