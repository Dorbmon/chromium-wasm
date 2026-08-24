#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the M6 controlled-HTTPS Chrome browser harness."""

from __future__ import annotations

import base64
import contextlib
import copy
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import queue
import struct
import sys
import tempfile
import threading
import unittest
from unittest import mock
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
import zlib


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
RELAY_FIXTURE_URL = "https://a.test:43211/m5/m6-ui"
TRANSCRIPT_URL = "http://127.0.0.1:43210/status"


def png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type)
    checksum = zlib.crc32(payload, checksum) & 0xFFFFFFFF
    return (
        struct.pack(">I", len(payload))
        + chunk_type
        + payload
        + struct.pack(">I", checksum)
    )


def make_screenshot_png() -> bytes:
    width = 640
    height = 480
    row = b"\x00" + bytes((24, 32, 48, 255)) * width
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", zlib.compress(row * height, level=9))
        + png_chunk(b"IEND", b"")
    )


SCREENSHOT_PNG = make_screenshot_png()
SCREENSHOT_DATA_BASE64 = base64.b64encode(SCREENSHOT_PNG).decode("ascii")


def relay_ready_json() -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "httpsUrl": "https://a.test:43211/m5/",
            "m6UiUrl": RELAY_FIXTURE_URL,
            "transcriptUrl": TRANSCRIPT_URL,
            "wispEndpoint": WISP_ENDPOINT,
        },
        separators=(",", ":"),
    )


def passing_result() -> dict[str, object]:
    ctrl_l = [
        {
            "type": event_type,
            "code": code,
            "trusted": True,
            "cancelable": True,
            "canvasFocused": True,
            "accepted": True,
            "defaultPrevented": True,
        }
        for event_type, code in (
            ("keydown", "ControlLeft"),
            ("keydown", "KeyL"),
            ("keyup", "KeyL"),
            ("keyup", "ControlLeft"),
        )
    ]
    before_input = {
        "inputType": "insertText",
        "dataOmitted": True,
        "dataUtf16Units": len(smoke.ADDRESS_TEXT),
        "dataUtf8Bytes": len(smoke.ADDRESS_TEXT),
        "trusted": True,
        "cancelable": True,
        "isComposing": False,
        "proxyFocused": True,
        "queued": True,
        "defaultPrevented": True,
        "sequence": 1,
        "nativeDispatched": True,
        "nativeAccepted": True,
    }
    enter = [
        {
            "type": event_type,
            "code": "Enter",
            "key": "Enter",
            "trusted": True,
            "cancelable": True,
            "proxyFocused": True,
            "accepted": True,
            "defaultPrevented": True,
        }
        for event_type in ("keydown", "keyup")
    ]
    ctrl_r = [
        {
            "type": event_type,
            "code": code,
            "trusted": True,
            "cancelable": True,
            "canvasFocused": True,
            "accepted": True,
            "defaultPrevented": True,
        }
        for event_type, code in (
            ("keydown", "ControlLeft"),
            ("keydown", "KeyR"),
            ("keyup", "KeyR"),
            ("keyup", "ControlLeft"),
        )
    ]
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
        "canvasFocusedAtStart": True,
        "proxyFocusedForText": True,
        "canvasFocusedForReload": True,
        "controlledHttps": {
            "wispConfigured": True,
            "runtimeArgumentsConfigured": True,
            "configurationPrecededFactory": True,
            "readyMarkerObserved": True,
            "navigatedMarkerObserved": True,
            "frameIdAtNavigatedMarker": 1,
            "navigatedMarkerObservationSequence": 1,
            "postNavigatedFrameObserved": True,
            "firstVisuallyNonEmptyPaintReportObserved": True,
            "firstVisuallyNonEmptyPaintObservationSequence": 4,
            "initialTargetFirstVisuallyNonEmptyPaintSignalObserved": True,
            "initialTargetFirstVisuallyNonEmptyPaintSignalObservationSequence": 3,
            "postNavigatedFrameAfterFirstVisuallyNonEmptyPaintObserved": True,
            "reloadReadyMarkerObserved": True,
            "reloadedMarkerObserved": True,
            "frameIdAtReloadedMarker": 2,
            "reloadedMarkerObservationSequence": 6,
            "postReloadFrameObserved": True,
            "reloadTargetFirstVisuallyNonEmptyPaintSignalObserved": True,
            "reloadTargetFirstVisuallyNonEmptyPaintSignalObservationSequence": 7,
            "postReloadFrameAfterFirstVisuallyNonEmptyPaintObserved": True,
            "firstEligibleScreenshotFrameId": 3,
            "screenshotCaptureAttempted": True,
            "screenshotFrameId": 3,
            "screenshotObservationSequence": 8,
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
            {"id": 3, "width": 640, "height": 480, "timestampMs": 3.0},
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
        "ozoneTextInputStates": [
            {
                "focusedClientPresent": True,
                "editable": True,
                "canComposeInline": True,
            }
        ],
        "ozoneTextInputDeliveries": [],
        "ozoneCursorReports": [],
        "hostInput": {
            "attached": True,
            "editable": True,
            "shortcutComplete": True,
            "proxyFocused": True,
            "textQueued": True,
            "deliveryAccepted": True,
            "deliveryRejected": False,
            "focusGeneration": 1,
            "acceptedDeliveryFocusGeneration": 1,
            "proxySessionCleared": False,
            "pendingDeliveryCount": 0,
            "pendingTextUtf8Bytes": 0,
            "tombstonedDeliveryCount": 0,
            "proxyTextEmpty": True,
            "readyObserved": True,
            "nativeTextAdmissionCount": 1,
            "nativeTextDeliveryCount": 1,
            "nativeTextDeliverySequences": [1],
            "ctrlLComplete": True,
            "proxyFocusedAfterCtrlL": True,
            "textDeliveryAccepted": True,
            "enterComplete": True,
            "navigatedObserved": True,
            "reloadReadyObserved": True,
            "ctrlRComplete": True,
            "reloadCanvasFocused": True,
            "reloadedObserved": True,
            "screenshotObserved": True,
            "passObserved": True,
            "navigationMarkerFrameId": 1,
            "reloadMarkerFrameId": 2,
            "screenshotFrameId": 3,
            "ctrlLRecords": ctrl_l,
            "beforeInputRecords": [before_input],
            "browserTextDeliveryReports": [
                {"action": 4, "sessionId": 0, "sequence": 1, "accepted": True}
            ],
            "enterRecords": enter,
            "ctrlRRecords": ctrl_r,
            "rejectedRecords": [],
            "cleanupRecords": [],
            "reloadRejectedRecords": [],
            "reloadCleanupRecords": [],
        },
        "screenshot": {
            "mimeType": "image/png",
            "dataBase64": SCREENSHOT_DATA_BASE64,
            "width": 640,
            "height": 480,
            "frameId": 3,
            "timestampMs": 3.0,
            "observationSequence": 8,
        },
        "canvasBackingStore": {"width": 640, "height": 480},
        "stdout": [
            smoke.READY_MARKER,
            smoke.NAVIGATED_MARKER,
            smoke.RELOAD_READY_MARKER,
            smoke.RELOADED_MARKER,
        ],
        "stderr": [smoke.PASS_MARKER],
        "failedChecks": [],
        "error": None,
    }


class ControlledHttpsRelayContractTest(unittest.TestCase):
    def test_parses_only_the_exact_relay_m6_ui_fixture(self) -> None:
        ready = smoke.parse_relay_ready_line(relay_ready_json())
        self.assertEqual(ready.wisp_endpoint, WISP_ENDPOINT)
        self.assertEqual(ready.m6_ui_url, RELAY_FIXTURE_URL)
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

    def test_stdout_callbacks_retain_only_the_first_readiness_line(self) -> None:
        latch = smoke.RelayReadinessLatch()

        smoke._queue_relay_ready_line(latch, "")
        smoke._queue_relay_ready_line(latch, relay_ready_json())
        smoke._queue_relay_ready_line(latch, "later relay output")
        smoke._queue_relay_ready_eof(latch)

        self.assertEqual(relay_ready_json(), latch.get(block=False))

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

    def test_smoke_url_uses_the_stable_gateway_not_the_relay_backend(self) -> None:
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
        self.assertEqual(query["fixtureUrl"], [smoke.GATEWAY_FIXTURE_URL])
        self.assertNotEqual(query["fixtureUrl"], [ready.m6_ui_url])
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

    def test_requires_two_h2_fixture_delivery_events_across_one_or_two_streams(
        self,
    ) -> None:
        status = {
            "fixture": smoke.RELAY_FIXTURE,
            "protocol": 1,
            "ready": True,
            "m6UiRequests": 2,
            "h2Requests": {"protocol": "h2", "count": 2},
            "localGateway443StreamsOpened": 1,
            "localGateway443Requests": 0,
            "requestedDestinations": [
                {"hostname": "a.test", "port": smoke.GATEWAY_LOGICAL_PORT}
            ],
            "transcript": [
                {"sequence": 1, "event": "fixture-ready"},
                {"sequence": 2, "event": "h2-m6-ui"},
                {"sequence": 3, "event": "h2-m6-ui"},
            ],
        }
        smoke.validate_relay_status(status)

        # Reload may legitimately reuse the first H2 stream or reconnect once,
        # but every observed WISP destination remains the canonical gateway.
        two_streams = copy.deepcopy(status)
        two_streams["localGateway443StreamsOpened"] = 2
        two_streams["requestedDestinations"].append(
            {"hostname": "a.test", "port": smoke.GATEWAY_LOGICAL_PORT}
        )
        smoke.validate_relay_status(two_streams)

        for mutate, expression in (
            (
                lambda payload: payload.__setitem__("m6UiRequests", 0),
                "exactly two",
            ),
            (
                lambda payload: payload.__setitem__("m6UiRequests", 1),
                "exactly two",
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
                    "h2Requests", {"protocol": "http/1.1", "count": 2}
                ),
                "HTTP/2",
            ),
            (
                lambda payload: payload.__setitem__(
                    "h2Requests", {"protocol": "h2", "count": 1}
                ),
                "exactly two HTTP/2",
            ),
            (
                lambda payload: payload.__setitem__(
                    "localGateway443StreamsOpened", 0
                ),
                "one or two mapped",
            ),
            (
                lambda payload: payload.__setitem__(
                    "localGateway443StreamsOpened", 3
                ),
                "one or two mapped",
            ),
            (
                lambda payload: payload.__setitem__(
                    "localGateway443Requests", 1
                ),
                "unexpected local-gateway",
            ),
            (
                lambda payload: payload.__setitem__(
                    "requestedDestinations",
                    [{"hostname": "a.test", "port": 43211}],
                ),
                "exact WISP CONNECT records",
            ),
            (
                lambda payload: payload.__setitem__(
                    "transcript",
                    [
                        {"sequence": 1, "event": "h2-m6-ui"},
                        {"sequence": 2, "event": "fixture-ready"},
                    ],
                ),
                "exactly two M6 UI events",
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

    def test_serves_only_its_loader_host_shared_text_adapter_and_artifacts(self) -> None:
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
                smoke.HOST_ROOT + "/chrome_wasm_text_input.js",
                "text/javascript; charset=utf-8",
                b"ChromiumWasmTrustedTextInput",
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

    def test_server_serves_snapshot_after_artifact_files_change(self) -> None:
        (self.out_dir / "chrome_wasm_m6_https_test.js").write_bytes(
            b"mutated Chrome loader"
        )
        (self.out_dir / "chrome_wasm_m6_https_test.wasm").write_bytes(
            b"mutated Chrome Wasm"
        )

        for suffix, expected in ((".js", self.js_bytes), (".wasm", self.wasm_bytes)):
            with self.subTest(suffix=suffix):
                status, _headers, body = self._request(
                    "GET",
                    smoke.HOST_ROOT
                    + f"/artifacts/chrome_wasm_m6_https_test{suffix}",
                )
                self.assertEqual(http.client.OK, status)
                self.assertEqual(expected, body)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires POSIX named pipes")
    def test_artifact_capture_rejects_fifo_without_blocking(self) -> None:
        artifact = self.out_dir / "chrome_wasm_m6_https_test.wasm"
        artifact.unlink()
        os.mkfifo(artifact)

        with self.assertRaisesRegex(M0Error, "regular file"):
            smoke.snapshot_wisp_artifacts(
                self.out_dir, "chrome_wasm_m6_https_test"
            )

    def test_host_snapshot_rejects_private_key_markers_before_server_creation(self) -> None:
        with self.assertRaisesRegex(M0Error, "private-key header"):
            smoke.validate_controlled_https_host_snapshots(
                {
                    "host_html": b"<html>host</html>",
                    "host_js": b"// host bridge",
                    "text_input_js": b"// -----BEGIN EC PRIVATE KEY-----",
                }
            )

    def test_server_serves_captured_host_resources_after_source_mutation(self) -> None:
        original = {
            "host_html": b"<html>captured M6 host</html>",
            "host_js": b"export const capturedHost = true;",
            "text_input_js": b"export const capturedText = true;",
        }
        host_dir = self.out_dir.parent / "host"
        host_dir.mkdir()
        file_names = {
            "host_html": "chrome_wasm_browser_controlled_https_smoke.html",
            "host_js": "chrome_wasm_browser_controlled_https_smoke_host.js",
            "text_input_js": "chrome_wasm_text_input.js",
        }
        for key, name in file_names.items():
            (host_dir / name).write_bytes(original[key])
        snapshots = smoke.snapshot_controlled_https_host_resources(host_dir)
        identity = smoke.controlled_https_host_delivery_identity(snapshots)
        server = smoke.create_server(
            "127.0.0.1",
            0,
            self.out_dir,
            "captured-host-token",
            queue.Queue(maxsize=1),
            module_name="chrome_wasm_m6_https_test",
            host_snapshots=snapshots,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for name in file_names.values():
                (host_dir / name).write_bytes(b"mutated after server creation")
            host, port = server.server_address[:2]
            expected_paths = {
                smoke.HOST_ROOT + "/": original["host_html"],
                smoke.HOST_ROOT
                + "/chrome_wasm_browser_controlled_https_smoke_host.js": original[
                    "host_js"
                ],
                smoke.HOST_ROOT + "/chrome_wasm_text_input.js": original[
                    "text_input_js"
                ],
            }
            for path, expected in expected_paths.items():
                with self.subTest(path=path):
                    connection = http.client.HTTPConnection(host, port, timeout=5)
                    try:
                        connection.request("GET", path)
                        response = connection.getresponse()
                        self.assertEqual(http.client.OK, response.status)
                        self.assertEqual(expected, response.read())
                    finally:
                        connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        for key, contents in original.items():
            with self.subTest(key=key):
                self.assertEqual(
                    hashlib.sha256(contents).hexdigest(), identity[key]["sha256"]
                )

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
        self.assertEqual(
            smoke.validate_result(
                passing_result(), expected_versions=VERSIONS
            ),
            SCREENSHOT_PNG,
        )

    def test_screenshot_comparison_uses_the_full_contract_image(self) -> None:
        contract = smoke.load_controlled_https_screenshot_contract()
        comparison = smoke.compare_screenshots(
            SCREENSHOT_PNG,
            SCREENSHOT_PNG,
            channel_tolerance=contract["channel_tolerance"],
            maximum_different_pixel_ratio=contract[
                "maximum_different_pixel_ratio"
            ],
        )
        self.assertTrue(comparison.matches)
        self.assertEqual((comparison.width, comparison.height), (640, 480))
        self.assertEqual(comparison.different_pixels, 0)

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
                    "frameIdAtReloadedMarker", 3
                ),
                "first post-RELOADED frame eligible after reload FVP",
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
                    result["readiness"].__setitem__("shellReady", False),
                    result["readinessReports"][0].__setitem__("shellReady", False),
                ),
                "shell was not ready",
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
            (
                lambda result: result.__setitem__("canvasFocusedAtStart", False),
                "canvasFocusedAtStart",
            ),
            (
                lambda result: result["hostInput"].__setitem__(
                    "deliveryAccepted", False
                ),
                "deliveryAccepted",
            ),
            (
                lambda result: result["hostInput"].__setitem__(
                    "textareaValue", "https://a.test/m5/m6-ui"
                ),
                "retained textarea text",
            ),
            (
                lambda result: result["hostInput"]["beforeInputRecords"][0].__setitem__(
                    "data", "https://a.test/m5/m6-ui"
                ),
                "beforeinput evidence",
            ),
            (
                lambda result: result["controlledHttps"].__setitem__(
                    "screenshotCaptureAttempted", False
                ),
                "screenshotCaptureAttempted",
            ),
            (
                lambda result: result["controlledHttps"].__setitem__(
                    "reloadTargetFirstVisuallyNonEmptyPaintSignalObservationSequence",
                    6,
                ),
                "reload target first visually non-empty paint signal was not "
                "observed after RELOADED",
            ),
            (
                lambda result: result["controlledHttps"].__setitem__(
                    "postReloadFrameAfterFirstVisuallyNonEmptyPaintObserved",
                    False,
                ),
                "postReloadFrameAfterFirstVisuallyNonEmptyPaintObserved",
            ),
            (
                lambda result: result["hostInput"].__setitem__(
                    "ctrlRComplete", False
                ),
                "ctrlRComplete",
            ),
            (
                lambda result: result["hostInput"]["ctrlRRecords"][1].__setitem__(
                    "trusted", False
                ),
                "Ctrl\\+R record 1",
            ),
            (
                lambda result: result["hostInput"].__setitem__(
                    "reloadMarkerFrameId", 1
                ),
                "input frame evidence disagrees",
            ),
            (
                lambda result: result["screenshot"].__setitem__(
                    "dataBase64", "not-valid-base64"
                ),
                "base64",
            ),
            (
                lambda result: result["screenshot"].__setitem__(
                    "frameId", 1
                ),
                "not bound to its first eligible reload frame",
            ),
        ):
            with self.subTest(expression=expression):
                result = passing_result()
                mutate(result)
                with self.assertRaisesRegex(M0Error, expression):
                    smoke.validate_result(result, expected_versions=VERSIONS)

    def test_rejects_target_fvp_signal_before_navigation(self) -> None:
        result = passing_result()
        controlled = result["controlledHttps"]
        controlled["navigatedMarkerObservationSequence"] = 2
        # Even the dedicated signal cannot be credited before NAVIGATED.
        controlled["firstVisuallyNonEmptyPaintObservationSequence"] = 1
        controlled[
            "initialTargetFirstVisuallyNonEmptyPaintSignalObservationSequence"
        ] = 1
        with self.assertRaisesRegex(
            M0Error,
            "initial target first visually non-empty paint signal was not observed "
            "after NAVIGATED",
        ):
            smoke.validate_result(result, expected_versions=VERSIONS)

    def test_rejects_sticky_pre_navigation_fvp_without_target_signal(
        self,
    ) -> None:
        result = passing_result()
        controlled = result["controlledHttps"]
        # The generic readiness FVP can remain true from an initial page. It
        # must not substitute for the separate C++ target-FVP protocol signal.
        controlled["navigatedMarkerObservationSequence"] = 2
        controlled["firstVisuallyNonEmptyPaintObservationSequence"] = 1
        controlled["initialTargetFirstVisuallyNonEmptyPaintSignalObserved"] = False
        controlled[
            "initialTargetFirstVisuallyNonEmptyPaintSignalObservationSequence"
        ] = 0
        with self.assertRaisesRegex(
            M0Error,
            "initialTargetFirstVisuallyNonEmptyPaintSignalObserved is not true",
        ):
            smoke.validate_result(result, expected_versions=VERSIONS)


class ControlledHttpsScreenshotPolicyTest(unittest.TestCase):
    def test_visual_policy_snapshots_survive_mutate_restore(self) -> None:
        contract = {
            "schema_version": 1,
            "fixture": "chromium-wasm-m6-controlled-https-v1",
            "gateway_url": smoke.GATEWAY_FIXTURE_URL,
            "baseline": "baseline.png",
            "baseline_policy": "reviewed",
            "visual_strategy": "full-canvas",
            "width": 640,
            "height": 480,
            "channel_tolerance": 2,
            "maximum_different_pixel_ratio": 0.0025,
            "comparison": "rgba",
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            contract_path = root / "contract.json"
            baseline_path = root / "baseline.png"
            original_contract = json.dumps(contract, sort_keys=True).encode("utf-8")
            contract_path.write_bytes(original_contract)
            baseline_path.write_bytes(SCREENSHOT_PNG)
            (
                contract_bytes,
                captured_contract,
                canonical_contract_bytes,
            ) = smoke.snapshot_controlled_https_screenshot_contract(contract_path)
            baseline_bytes = smoke.snapshot_controlled_https_baseline(baseline_path)
            contract_path.write_bytes(b'{"mutated":true}')
            baseline_path.write_bytes(b"not a PNG")
            contract_path.write_bytes(original_contract)
            baseline_path.write_bytes(SCREENSHOT_PNG)

        self.assertEqual(original_contract, contract_bytes)
        self.assertEqual(contract, captured_contract)
        self.assertEqual(
            captured_contract,
            smoke.load_controlled_https_screenshot_contract(
                contents=canonical_contract_bytes
            ),
        )
        comparison = smoke.compare_screenshots(
            SCREENSHOT_PNG,
            baseline_bytes,
            channel_tolerance=captured_contract["channel_tolerance"],
            maximum_different_pixel_ratio=captured_contract[
                "maximum_different_pixel_ratio"
            ],
        )
        self.assertTrue(comparison.matches)

    def test_contract_requires_a_full_unmasked_canonical_gateway_comparison(
        self,
    ) -> None:
        contract = smoke.load_controlled_https_screenshot_contract()
        self.assertEqual(contract["gateway_url"], smoke.GATEWAY_FIXTURE_URL)
        self.assertEqual(contract["width"], 640)
        self.assertEqual(contract["height"], 480)
        self.assertEqual(contract["channel_tolerance"], 2)
        self.assertEqual(contract["maximum_different_pixel_ratio"], 0.0025)
        self.assertTrue(contract["baseline"].endswith(".png"))
        self.assertIn("No canvas region is masked", contract["visual_strategy"])
        self.assertIn("complete 640x480 browser canvas", contract["comparison"])

    def test_contract_rejects_a_noncanonical_gateway(self) -> None:
        contract = smoke.load_controlled_https_screenshot_contract()
        contract["gateway_url"] = "https://a.test:443/m5/m6-ui"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(M0Error, "gateway URL"):
                smoke.load_controlled_https_screenshot_contract(path)

    def test_contract_snapshot_rejects_boolean_schema_version(self) -> None:
        contract = smoke.load_controlled_https_screenshot_contract()
        contract["schema_version"] = True
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(M0Error, "schema"):
                smoke.load_controlled_https_screenshot_contract(path)
            with self.assertRaisesRegex(M0Error, "schema"):
                smoke.snapshot_controlled_https_screenshot_contract(path)

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
            '"CHROMIUM_WASM_M6_CONTROLLED_HTTPS:RELOAD_READY"',
            '"CHROMIUM_WASM_M6_CONTROLLED_HTTPS:RELOADED"',
            'const PASS_MARKER = "CHROMIUM_WASM_M6_CONTROLLED_HTTPS:PASS";',
            'const FIXTURE_PATH = "/m5/m6-ui";',
            'const FIXTURE_URL = "https://a.test/m5/m6-ui";',
            "moduleOptions.chromiumWasmWisp = wispConfiguration;",
            "subprotocol: WISP_SUBPROTOCOL,",
            "!isLoopbackHostname(endpoint.hostname)",
            'endpoint.pathname !== "/wisp/"',
            "endpoint.username",
            "endpoint.password",
            "endpoint.search",
            "endpoint.hash",
            'url.port !== ""',
            "url.href !== FIXTURE_URL",
            "URL_SWITCH + \"=\" + controlledUrl.href",
            "namespace.default(moduleOptions)",
            "reportFrame(report)",
            "reportReadiness(report)",
            "reportOzoneFocusState(report)",
            "reportOzoneTextInputState(report)",
            "reportOzoneBrowserTextInputDelivery(report)",
            'import {ChromiumWasmTrustedTextInput} from "./chrome_wasm_text_input.js";',
            'const ADDRESS_TEXT_CHUNKS = Object.freeze(["https://a.test/m5/m6-ui"]);',
            "canvasFocusedAtStart",
            "proxyFocusedForText",
            "canvasFocusedForReload",
            "proxyTextEmpty",
            "textareaValue, ...textMetadata",
            "postNavigatedFrameObserved",
            "postNavigatedFrameAfterFirstVisuallyNonEmptyPaintObserved",
            "initialTargetFirstVisuallyNonEmptyPaintSignalObserved",
            "initialTargetFirstVisuallyNonEmptyPaintSignalObservationSequence",
            "reloadReadyMarkerObserved",
            "reloadedMarkerObserved",
            "frameIdAtReloadedMarker",
            "postReloadFrameObserved",
            "reloadTargetFirstVisuallyNonEmptyPaintSignalObserved",
            "reloadTargetFirstVisuallyNonEmptyPaintSignalObservationSequence",
            "postReloadFrameAfterFirstVisuallyNonEmptyPaintObserved",
            "ctrlRComplete",
            "reloadCanvasFocused",
            "ctrlRRecords",
            "chromium_wasm_browser_host_key",
            "firstEligibleScreenshotFrameId",
            "screenshotCaptureAttempted",
            "screenshotObservationSequence",
            "result.readiness?.shellReady === true",
            "shell readiness was not reported",
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
        self.assertIn("ccall(", host)
        self.assertIn('"chromium_wasm_browser_host_key"', host)
        self.assertNotIn("location.assign(", host)
        self.assertNotIn("location.replace(", host)
        self.assertNotIn("Page.reload", host)
        self.assertNotIn("NavigationController", host)
        capture_start = host.index("#captureScreenshotForFirstEligibleReloadFrame")
        capture_end = host.index("#reportFrame", capture_start)
        capture = host[capture_start:capture_end]
        self.assertIn('this.#canvas.toDataURL("image/png")', capture)
        self.assertIn("this.#screenshotCaptureAttempted = true", capture)
        report_frame_end = host.index("#reportReadiness", capture_end)
        report_frame = host[capture_end:report_frame_end]
        self.assertIn("this.#reloadedMarkerObserved", report_frame)
        self.assertIn(
            "this.#reloadTargetFirstVisuallyNonEmptyPaintSignalObserved",
            report_frame,
        )
        self.assertIn(
            "this.#captureScreenshotForFirstEligibleReloadFrame(", report_frame
        )
        target_fvp_start = host.index("#reportControlledHttpsTargetFvp")
        target_fvp_end = host.index("#reportFocus", target_fvp_start)
        target_fvp = host[target_fvp_start:target_fvp_end]
        self.assertIn("Object.keys(report).length !== 2", target_fvp)
        self.assertIn("report.phase", target_fvp)
        self.assertIn("this.#reloadedMarkerObserved", target_fvp)
        self.assertIn(
            "observationSequence <= this.#reloadedMarkerObservationSequence",
            target_fvp,
        )
        self.assertIn(
            "this.#reloadTargetFirstVisuallyNonEmptyPaintSignalObserved = true",
            target_fvp,
        )

    def test_runner_uses_fresh_relay_then_requires_exact_fixture_evidence(self) -> None:
        runner = source("tools/wasm/run_m6_wasm_browser_controlled_https_smoke.py")
        for expected in (
            "chrome_wasm_m6_https_test",
            "m6UiUrl",
            "GATEWAY_FIXTURE_URL",
            "validate_m6_ui_url",
            "--wasm-browser-controlled-https-smoke",
            "--wasm-browser-controlled-https-url",
            "validate_controlled_wisp_endpoint",
            "m6UiRequests",
            "localGateway443StreamsOpened",
            "requestedDestinations",
            "initialTargetFirstVisuallyNonEmptyPaintSignalObserved",
            "initialTargetFirstVisuallyNonEmptyPaintSignalObservationSequence",
            "reloadTargetFirstVisuallyNonEmptyPaintSignalObserved",
            "reloadTargetFirstVisuallyNonEmptyPaintSignalObservationSequence",
            "RELOAD_READY_MARKER",
            "RELOADED_MARKER",
            "controlled-HTTPS shell was not ready",
            "h2-m6-ui",
            "chromium-wasm-m5-network-v1",
            "check_controlled_https_boundary(out_dir)",
            "CONTROLLED_HTTPS_GN_TARGET",
            "--baseline",
            "--capture-baseline",
            "BASELINE_CAPTURED_REVIEW_REQUIRED",
            "compare_screenshots(",
            "redact_screenshot_data",
            "MAX_RESULT_BYTES = 8 * 1024 * 1024",
            "from m4_cdp import unused_loopback_port, wait_for_page_client",
            "wait_for_page_client(debug_port",
            "client.dispatch_control_shortcut(\"KeyL\", \"l\", 76)",
            "client.dispatch_control_shortcut(\"KeyR\", \"r\", 82)",
            "client.call(\"Input.insertText\", {\"text\": text_chunk})",
            "awaiting-trusted-dom-ctrl-r",
            "Input.dispatchKeyEvent",
            "__chromiumWasmM6ControlledHttpsHostTextState",
            "chrome_wasm_text_input.js",
            "verify_explicit_text_heap_exports",
            'Module["_chromium_wasm_browser_host_text"]',
            'Module["_chromium_wasm_browser_host_key"]',
            'Module["_malloc"]',
            'Module["_free"]',
            'Module["ccall"]',
            'Module["HEAPU8"]',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, runner)
        self.assertNotIn("ccall(", runner)
        self.assertNotIn("Input.dispatchMouseEvent", runner)
        self.assertNotIn("Runtime.evaluate", runner)
        self.assertNotIn("Page.reload", runner)
        self.assertNotIn("SCREENSHOT_CAPTURED_UNCOMPARED", runner)

    def test_target_fvp_uses_a_dedicated_nonsticky_host_bridge_signal(
        self,
    ) -> None:
        bridge = source("ui/ozone/platform/wasm/wasm_host_bridge.js")
        start = bridge.index(
            "chromium_wasm_report_controlled_https_target_fvp__deps"
        )
        end = bridge.index("chromium_wasm_report_ozone_focus_state__deps", start)
        target_fvp = bridge[start:end]
        for expected in (
            "chromium_wasm_report_controlled_https_target_fvp__proxy: 'sync'",
            "chromium_wasm_report_controlled_https_target_fvp: (phase) =>",
            "bridge.reportControlledHttpsTargetFvp({",
            "protocol: ChromiumWasmHostBridge.version",
            "phase,",
            "}) === true ? 1 : 0",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, target_fvp)
        self.assertNotIn("reportReadiness", target_fvp)


class ControlledHttpsRunnerCleanupTest(unittest.TestCase):
    """Exercise terminal-evidence ordering without launching Chrome or Node."""

    def _run_main_with_cleanup_fakes(
        self,
        *,
        browser_cleanup_error: BaseException | None = None,
        operational_error: BaseException | None = None,
        abort_browser_error: BaseException | None = None,
        abort_relay_error: BaseException | None = None,
        server_cleanup_error: BaseException | None = None,
        profile_cleanup_error: BaseException | None = None,
        mutate_visual_inputs_after_snapshot: bool = False,
    ) -> tuple[int, str, str, dict[str, mock.Mock]]:
        server = mock.Mock()
        server.server_address = ("127.0.0.1", 8123)
        server_thread = mock.Mock()
        server_thread.is_alive.return_value = False
        relay = mock.Mock()
        relay.stdout = object()
        relay.stderr = object()
        browser = mock.Mock()
        browser.stderr = object()
        relay_stdout_reader = mock.Mock()
        relay_stderr_reader = mock.Mock()
        browser_stderr_reader = mock.Mock()
        profile = mock.Mock()
        profile.name = "/fake-profile"
        profile.cleanup.side_effect = profile_cleanup_error
        artifact_snapshots = {
            "chrome_wasm_m6_https_test.js": b"fake M6 loader",
            "chrome_wasm_m6_https_test.wasm": b"\x00asm fake M6",
        }
        client = mock.Mock()
        relay_ready = smoke.RelayReady(
            wisp_endpoint=WISP_ENDPOINT,
            m6_ui_url=RELAY_FIXTURE_URL,
            transcript_url=TRANSCRIPT_URL,
        )
        comparison = mock.Mock()
        comparison.matches = True
        comparison.as_dict.return_value = {"matches": True}
        compare_screenshots = mock.Mock(return_value=comparison)
        stop_browser = mock.Mock(side_effect=browser_cleanup_error)
        stop_relay = mock.Mock()
        cleanup_server = mock.Mock(return_value=server_cleanup_error)
        abort_browser = mock.Mock(side_effect=abort_browser_error)
        abort_relay = mock.Mock(side_effect=abort_relay_error)
        wait_for_state = mock.Mock()
        if operational_error is not None:
            wait_for_state.side_effect = operational_error
        dependencies = {
            "server": server,
            "server_thread": server_thread,
            "relay": relay,
            "browser": browser,
            "relay_stdout_reader": relay_stdout_reader,
            "relay_stderr_reader": relay_stderr_reader,
            "browser_stderr_reader": browser_stderr_reader,
            "profile": profile,
            "client": client,
            "stop_browser": stop_browser,
            "stop_relay": stop_relay,
            "cleanup_server": cleanup_server,
            "abort_browser": abort_browser,
            "abort_relay": abort_relay,
            "artifact_snapshots": artifact_snapshots,
            "comparison": comparison,
            "compare_screenshots": compare_screenshots,
        }
        screenshot_contract = {
            "schema_version": 1,
            "fixture": "chromium-wasm-m6-controlled-https-v1",
            "gateway_url": smoke.GATEWAY_FIXTURE_URL,
            "baseline": "baseline.png",
            "baseline_policy": "reviewed",
            "visual_strategy": "full-canvas",
            "width": 640,
            "height": 480,
            "channel_tolerance": 2,
            "maximum_different_pixel_ratio": 0.0025,
            "comparison": "rgba",
        }
        baseline = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        baseline.write(SCREENSHOT_PNG)
        baseline.close()
        contract = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        captured_contract_bytes = json.dumps(screenshot_contract).encode("utf-8")
        contract.write(captured_contract_bytes)
        contract.close()
        visual_mutation = {"performed": False}
        dependencies.update(
            {
                "captured_baseline_bytes": SCREENSHOT_PNG,
                "captured_contract_bytes": captured_contract_bytes,
                "visual_mutation": visual_mutation,
            }
        )
        original_snapshot_baseline = smoke.snapshot_controlled_https_baseline

        def snapshot_baseline_then_optionally_mutate(path: Path) -> bytes:
            captured = original_snapshot_baseline(path)
            if mutate_visual_inputs_after_snapshot:
                path.write_bytes(b"mutated baseline after snapshot")
                Path(contract.name).write_bytes(b'{"mutated":true}')
                visual_mutation["performed"] = True
            return captured

        patches = (
            mock.patch.object(smoke, "check_controlled_https_boundary"),
            mock.patch.object(smoke, "verify_explicit_text_heap_exports"),
            mock.patch.object(
                smoke, "verify_optional_wisp_data_private_key_pem_artifact"
            ),
            mock.patch.object(
                smoke,
                "snapshot_wisp_artifacts",
                return_value=artifact_snapshots,
            ),
            mock.patch.object(smoke, "load_manifest", return_value={}),
            mock.patch.object(smoke, "checked_output", return_value="head"),
            mock.patch.object(smoke, "manifest_versions", return_value=VERSIONS),
            mock.patch.object(smoke, "print_context", return_value={}),
            mock.patch.object(
                smoke,
                "find_browser",
                return_value=(Path("/fake-browser"), "test-browser"),
            ),
            mock.patch.object(smoke, "find_node", return_value=Path("/fake-node")),
            mock.patch.object(
                smoke, "CONTROLLED_HTTPS_SCREENSHOT_CONTRACT", Path(contract.name)
            ),
            mock.patch.object(
                smoke,
                "snapshot_controlled_https_baseline",
                side_effect=snapshot_baseline_then_optionally_mutate,
            ),
            mock.patch.object(smoke, "create_server", return_value=server),
            mock.patch.object(smoke.threading, "Thread", return_value=server_thread),
            mock.patch.object(smoke, "relay_command", return_value=["relay"]),
            mock.patch.object(
                smoke,
                "materialized_wisp_relay_closure",
                return_value=contextlib.nullcontext(Path("/private-relay.mjs")),
            ),
            mock.patch.object(smoke, "m5_host_origin", return_value="http://host.test"),
            mock.patch.object(smoke, "browser_command", return_value=["browser"]),
            mock.patch.object(
                smoke.subprocess, "Popen", side_effect=[relay, browser]
            ),
            mock.patch.object(
                smoke,
                "BrowserStderrReader",
                side_effect=(
                    relay_stdout_reader,
                    relay_stderr_reader,
                    browser_stderr_reader,
                ),
            ),
            mock.patch.object(smoke, "wait_for_relay_ready", return_value=relay_ready),
            mock.patch.object(smoke, "smoke_url", return_value="http://host.test/m6"),
            mock.patch.object(
                smoke.tempfile, "TemporaryDirectory", return_value=profile
            ),
            mock.patch.object(smoke, "unused_loopback_port", return_value=9222),
            mock.patch.object(smoke, "wait_for_page_client", return_value=client),
            mock.patch.object(smoke, "wait_for_state", wait_for_state),
            mock.patch.object(smoke, "dispatch_unmodified_enter"),
            mock.patch.object(smoke, "wait_for_result", return_value=passing_result()),
            mock.patch.object(smoke, "validate_result", return_value=SCREENSHOT_PNG),
            mock.patch.object(smoke, "fetch_relay_status", return_value={}),
            mock.patch.object(smoke, "validate_relay_status"),
            mock.patch.object(smoke, "compare_screenshots", compare_screenshots),
            mock.patch.object(smoke, "stop_browser_group", stop_browser),
            mock.patch.object(smoke, "stop_process_group", stop_relay),
            mock.patch.object(
                smoke, "_cleanup_controlled_https_server", cleanup_server
            ),
            mock.patch.object(smoke, "abort_browser_group", abort_browser),
            mock.patch.object(smoke, "abort_process_group", abort_relay),
            mock.patch.object(
                smoke, "write_failure_diagnostics", return_value=Path("/diagnostic")
            ),
            mock.patch.object(
                sys,
                "argv",
                ["controlled-https-runner", "--baseline", baseline.name],
            ),
        )
        try:
            with contextlib.ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                stdout = stack.enter_context(
                    mock.patch("sys.stdout", new_callable=io.StringIO)
                )
                stderr = stack.enter_context(
                    mock.patch("sys.stderr", new_callable=io.StringIO)
                )
                result = smoke.main()
        finally:
            Path(baseline.name).unlink(missing_ok=True)
            Path(contract.name).unlink(missing_ok=True)
        return result, stdout.getvalue(), stderr.getvalue(), dependencies

    def test_main_suppresses_terminal_markers_when_cleanup_before_pass_fails(
        self,
    ) -> None:
        result, stdout, stderr, dependencies = self._run_main_with_cleanup_fakes(
            browser_cleanup_error=M0Error("browser cleanup failed")
        )

        self.assertEqual(1, result)
        self.assertIn("FAIL reason=browser cleanup failed", stderr)
        for marker in (
            "ARTIFACT_DELIVERY",
            "SCREENSHOT",
            "BROWSER_RESULT",
            "RELAY_STATUS",
            "PASS",
        ):
            with self.subTest(marker=marker):
                self.assertNotIn(f"{smoke.SENTINEL}:{marker}", stdout + stderr)
        dependencies["client"].close.assert_called_once_with()
        dependencies["stop_browser"].assert_called_once_with(
            dependencies["browser"], dependencies["browser_stderr_reader"]
        )
        dependencies["stop_relay"].assert_not_called()
        dependencies["abort_browser"].assert_called_once_with(
            dependencies["browser"],
            dependencies["browser_stderr_reader"],
            unowned_streams=(),
        )
        dependencies["abort_relay"].assert_called_once_with(
            dependencies["relay"],
            (
                dependencies["relay_stdout_reader"],
                dependencies["relay_stderr_reader"],
            ),
            description="controlled-HTTPS WISP relay",
            unowned_streams=(),
        )
        dependencies["cleanup_server"].assert_called_once()
        dependencies["profile"].cleanup.assert_called_once_with()

    def test_main_preserves_operational_failure_while_attempting_all_cleanup(
        self,
    ) -> None:
        result, stdout, stderr, dependencies = self._run_main_with_cleanup_fakes(
            operational_error=M0Error("original operational failure"),
            abort_browser_error=M0Error("abort browser cleanup failed"),
            abort_relay_error=M0Error("abort relay cleanup failed"),
            server_cleanup_error=M0Error("server cleanup failed"),
            profile_cleanup_error=M0Error("profile cleanup failed"),
        )

        self.assertEqual(1, result)
        self.assertIn("FAIL reason=original operational failure", stderr)
        for message in (
            "abort browser cleanup failed",
            "abort relay cleanup failed",
            "server cleanup failed",
            "profile cleanup failed",
        ):
            with self.subTest(message=message):
                self.assertNotIn(message, stderr)
        for marker in (
            "ARTIFACT_DELIVERY",
            "SCREENSHOT",
            "BROWSER_RESULT",
            "RELAY_STATUS",
            "PASS",
        ):
            with self.subTest(marker=marker):
                self.assertNotIn(f"{smoke.SENTINEL}:{marker}", stdout + stderr)
        dependencies["client"].close.assert_called_once_with()
        dependencies["stop_browser"].assert_not_called()
        dependencies["stop_relay"].assert_not_called()
        dependencies["abort_browser"].assert_called_once()
        dependencies["abort_relay"].assert_called_once()
        dependencies["cleanup_server"].assert_called_once()
        dependencies["profile"].cleanup.assert_called_once_with()

    def test_main_emits_snapshot_delivery_only_after_successful_cleanup(self) -> None:
        result, stdout, stderr, dependencies = self._run_main_with_cleanup_fakes()

        self.assertEqual(0, result)
        self.assertEqual("", stderr)
        delivery_prefix = f"{smoke.SENTINEL}:ARTIFACT_DELIVERY "
        screenshot_prefix = f"{smoke.SENTINEL}:SCREENSHOT "
        browser_prefix = f"{smoke.SENTINEL}:BROWSER_RESULT "
        relay_prefix = f"{smoke.SENTINEL}:RELAY_STATUS "
        terminal_prefixes = (
            delivery_prefix,
            screenshot_prefix,
            browser_prefix,
            relay_prefix,
        )
        terminal_indices = []
        for prefix in terminal_prefixes:
            matching = [
                index
                for index, line in enumerate(stdout.splitlines())
                if line.startswith(prefix)
            ]
            self.assertEqual(1, len(matching), prefix)
            terminal_indices.append(matching[0])
        self.assertEqual(sorted(terminal_indices), terminal_indices)
        pass_lines = [
            index
            for index, line in enumerate(stdout.splitlines())
            if line == smoke.PASS_MARKER
        ]
        self.assertEqual(1, len(pass_lines))
        self.assertGreater(pass_lines[0], terminal_indices[-1])
        delivery = json.loads(
            next(
                line[len(delivery_prefix) :]
                for line in stdout.splitlines()
                if line.startswith(delivery_prefix)
            )
        )
        self.assertEqual(
            "unverified",
            delivery["artifact_source_provenance"],
        )
        self.assertEqual(
            hashlib.sha256(
                dependencies["artifact_snapshots"]["chrome_wasm_m6_https_test.js"]
            ).hexdigest(),
            delivery["loader"]["sha256"],
        )

    def test_main_uses_visual_bytes_captured_before_browser_launch(self) -> None:
        result, stdout, stderr, dependencies = self._run_main_with_cleanup_fakes(
            mutate_visual_inputs_after_snapshot=True
        )

        self.assertEqual(0, result)
        self.assertEqual("", stderr)
        self.assertTrue(dependencies["visual_mutation"]["performed"])
        dependencies["compare_screenshots"].assert_called_once_with(
            SCREENSHOT_PNG,
            dependencies["captured_baseline_bytes"],
            channel_tolerance=2,
            maximum_different_pixel_ratio=0.0025,
        )
        delivery_prefix = f"{smoke.SENTINEL}:ARTIFACT_DELIVERY "
        delivery = json.loads(
            next(
                line[len(delivery_prefix) :]
                for line in stdout.splitlines()
                if line.startswith(delivery_prefix)
            )
        )
        self.assertEqual(
            hashlib.sha256(dependencies["captured_baseline_bytes"]).hexdigest(),
            delivery["screenshot_baseline"]["sha256"],
        )
        self.assertEqual(
            hashlib.sha256(dependencies["captured_contract_bytes"]).hexdigest(),
            delivery["screenshot_contract"]["sha256"],
        )
        expected_contract = json.loads(
            dependencies["captured_contract_bytes"].decode("utf-8")
        )
        expected_canonical_contract = (
            smoke.canonical_controlled_https_screenshot_contract_bytes(
                expected_contract
            )
        )
        self.assertEqual(
            hashlib.sha256(expected_canonical_contract).hexdigest(),
            delivery["screenshot_contract_canonical"]["sha256"],
        )
        self.assertEqual(
            smoke.controlled_https_screenshot_policy(expected_contract),
            delivery["screenshot_policy"],
        )

    def test_server_cleanup_uses_bounded_shutdown_and_handler_drain(self) -> None:
        server = mock.Mock()
        thread = mock.Mock()
        thread.is_alive.return_value = False

        with mock.patch.object(smoke, "shutdown_server_bounded") as shutdown:
            error = smoke._cleanup_controlled_https_server(
                server=server,
                server_thread=thread,
                server_thread_started=True,
            )

        self.assertIsNone(error)
        shutdown.assert_called_once_with(
            server,
            timeout=smoke.CLEANUP_TIMEOUT_SECONDS,
            description="controlled-HTTPS host server",
        )
        server.server_close.assert_called_once_with()
        thread.join.assert_called_once_with(timeout=smoke.CLEANUP_TIMEOUT_SECONDS)
        server.join_request_handlers.assert_called_once_with(
            timeout=smoke.CLEANUP_TIMEOUT_SECONDS,
            description="controlled-HTTPS host server",
        )


if __name__ == "__main__":
    unittest.main()
