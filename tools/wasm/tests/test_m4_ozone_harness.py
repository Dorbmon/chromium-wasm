#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused unit tests for the M4 trusted-pointer host harness."""

from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest
from unittest import mock


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import m3_content_server
import m4_cdp
import run_m4_ozone_smoke


def passing_result() -> tuple[dict[str, object], dict[str, str]]:
    versions = {
        "chromium": "chromium-revision",
        "v8": "v8-revision",
        "emscripten": "emscripten-revision",
        "port": "port-revision",
    }
    pointer_input = {
        "enabled": True,
        "receivedCount": 3,
        "trustedCount": 3,
        "queuedCount": 3,
        "lastQueued": {
            "type": "up",
            "trusted": True,
            "queued": True,
            "canvasFocused": True,
            "sequence": 3,
            "x": 285,
            "y": 229,
            "frameIdBefore": 6,
        },
    }
    result: dict[str, object] = {
        "protocol": 1,
        "case": "ozone_pointer_m4",
        "status": "pass",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "versions": versions,
        "readiness": {
            "baseReady": True,
            "runtimeInitialized": True,
            "shellReady": True,
            "surfaceReady": True,
            "navigationCommitted": True,
            "firstVisuallyNonEmptyPaint": True,
            "pageReady": True,
            "fatalErrors": [],
            "heartbeat": {
                "anchor": "data-navigation-committed",
                "elapsedMs": 1200,
            },
            "frame": {
                "id": 7,
                "timestampMs": 1180,
                "width": 800,
                "height": 600,
            },
            "pageProbe": {
                "fontReady": True,
                "protocol": 1,
                "fixture": "chromium-wasm-m4-ozone-pointer-v2",
                "ready": True,
                "activationCount": 1,
                "clickTrusted": True,
                "clickDefaultPrevented": False,
                "navigationFrameLoadCount": 2,
                "navigationFrameLastLoadTrusted": True,
                "navigationFrameLoadCountBeforeActivation": 1,
                "resultText": "ACTIVATED",
                "targetCenterX": 285,
                "targetCenterY": 229,
                "timerTicks": 3,
                "pointerMoveTrace": [
                    {
                        "type": "pointermove",
                        "trusted": True,
                        "targetId": "m4-link",
                        "clientX": 285,
                        "clientY": 229,
                    }
                ],
                "pointerEvents": {
                    "mousemove": 3,
                    "mousedown": 1,
                    "mouseup": 1,
                    "pointermove": 3,
                    "pointerdown": 1,
                    "pointerup": 1,
                },
            },
            "ozoneCursor": {
                "sequence": 1,
                "cursorType": 2,
                "cssCursor": "pointer",
                "exact": True,
            },
            "pointerInput": pointer_input,
        },
        "pointerInput": pointer_input,
        "cursor": {
            "sequence": 1,
            "cursorType": 2,
            "cssCursor": "pointer",
            "exact": True,
        },
        "cursorReportSequenceBeforeInput": 0,
        "shutdown": {
            "ok": True,
            "accepted": True,
            "complete": True,
            "exitCode": 0,
            "runtimeExitCode": 0,
        },
        "logs": {
            "host": [
                "m4:pointer:listeners-attached",
                "m4:pointer:move:queued",
                "m4:pointer:down:queued",
                "m4:pointer:up:queued",
                "ozone:cursor:2:pointer:exact",
                "shutdown:complete",
            ],
            "stdout": [],
            "stderr": [],
        },
        "failedChecks": [],
        "error": None,
    }
    return result, versions


class M4ResultValidationTest(unittest.TestCase):
    def test_complete_queued_pointer_contract_is_accepted(self) -> None:
        result, versions = passing_result()

        self.assertIsNone(
            m3_content_server.validate_m4_result(
                result, expected_versions=versions
            )
        )

    def test_untrusted_fixture_activation_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        page_probe["clickTrusted"] = False

        with self.assertRaisesRegex(M0Error, "clickTrusted mismatch"):
            m3_content_server.validate_m4_result(
                result, expected_versions=versions
            )

    def test_suppressed_or_missing_native_link_navigation_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        page_probe["clickDefaultPrevented"] = True

        with self.assertRaisesRegex(M0Error, "clickDefaultPrevented mismatch"):
            m3_content_server.validate_m4_result(
                result, expected_versions=versions
            )

        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        page_probe["navigationFrameLoadCountBeforeActivation"] = 2

        with self.assertRaisesRegex(
            M0Error, "navigation target did not load exactly once"
        ):
            m3_content_server.validate_m4_result(
                result, expected_versions=versions
            )

    def test_untrusted_queued_pointer_is_rejected(self) -> None:
        result, versions = passing_result()
        pointer_input = result["pointerInput"]
        assert isinstance(pointer_input, dict)
        last_queued = pointer_input["lastQueued"]
        assert isinstance(last_queued, dict)
        last_queued["trusted"] = False

        with self.assertRaisesRegex(M0Error, "was not a trusted DOM event"):
            m3_content_server.validate_m4_result(
                result, expected_versions=versions
            )

    def test_missing_inner_pointer_evidence_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        pointer_events = page_probe["pointerEvents"]
        assert isinstance(pointer_events, dict)
        del pointer_events["pointerup"]

        with self.assertRaisesRegex(M0Error, "inner pointerup count"):
            m3_content_server.validate_m4_result(
                result, expected_versions=versions
            )

    def test_mismatched_readiness_pointer_evidence_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        readiness["pointerInput"] = copy.deepcopy(result["pointerInput"])
        readiness_pointer = readiness["pointerInput"]
        assert isinstance(readiness_pointer, dict)
        readiness_pointer["queuedCount"] = 2

        with self.assertRaisesRegex(
            M0Error, "pointer evidence differs from readiness evidence"
        ):
            m3_content_server.validate_m4_result(
                result, expected_versions=versions
            )

    def test_queued_pointer_target_mismatch_is_rejected(self) -> None:
        result, versions = passing_result()
        pointer_input = result["pointerInput"]
        assert isinstance(pointer_input, dict)
        last_queued = pointer_input["lastQueued"]
        assert isinstance(last_queued, dict)
        last_queued["x"] = 284

        with self.assertRaisesRegex(
            M0Error, "pointer x does not match the fixture target"
        ):
            m3_content_server.validate_m4_result(
                result, expected_versions=versions
            )

    def test_nonexact_or_stale_cursor_report_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        cursor = readiness["ozoneCursor"]
        assert isinstance(cursor, dict)
        cursor["exact"] = False
        result_cursor = result["cursor"]
        assert isinstance(result_cursor, dict)
        result_cursor["exact"] = False

        with self.assertRaisesRegex(M0Error, "exact pointer mapping"):
            m3_content_server.validate_m4_result(
                result, expected_versions=versions
            )

        result, versions = passing_result()
        result["cursorReportSequenceBeforeInput"] = 1
        with self.assertRaisesRegex(
            M0Error, "did not update after trusted hover"
        ):
            m3_content_server.validate_m4_result(
                result, expected_versions=versions
            )


class M4CanvasGeometryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = {"targetX": 100, "targetY": 50}
        self.geometry = {
            "left": 10.0,
            "top": 20.0,
            "clientLeft": 2,
            "clientTop": 3,
            "clientWidth": 400,
            "clientHeight": 300,
            "width": 800,
            "height": 600,
        }

    def test_click_position_accounts_for_border_and_backing_scale(self) -> None:
        self.assertEqual(
            run_m4_ozone_smoke.canvas_click_position(
                self.state, self.geometry
            ),
            (62.25, 48.25),
        )

    def test_invalid_geometry_is_rejected(self) -> None:
        cases = (
            (
                "boolean target",
                {"targetX": True, "targetY": 50},
                self.geometry,
                "invalid fixture target coordinates",
            ),
            (
                "nonfinite canvas left",
                self.state,
                {**self.geometry, "left": float("nan")},
                "canvas left must be a finite number",
            ),
            (
                "nonpositive client width",
                self.state,
                {**self.geometry, "clientWidth": 0},
                "canvas has nonpositive dimensions",
            ),
            (
                "outside backing canvas",
                {"targetX": 800, "targetY": 50},
                self.geometry,
                "fixture target is outside the backing canvas",
            ),
        )
        for name, state, geometry, error in cases:
            with self.subTest(name=name):
                with self.assertRaisesRegex(M0Error, error):
                    run_m4_ozone_smoke.canvas_click_position(state, geometry)


class M4BrowserCommandTest(unittest.TestCase):
    def test_runner_uses_a_viewport_that_contains_the_fixed_canvas(self) -> None:
        command = run_m4_ozone_smoke.m4_browser_command(
            Path("/browser"),
            "/profile",
            "http://127.0.0.1/",
            no_sandbox=True,
        )

        self.assertIn("--window-size=1280,800", command)
        self.assertLess(
            command.index("--window-size=1280,800"),
            command.index("--headless=new"),
        )
        self.assertIn("--no-sandbox", command)
        self.assertEqual(command[-1], "http://127.0.0.1/")


class RecordingDevToolsClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    def call(
        self, method: str, params: dict[str, object] | None = None
    ) -> dict[str, object]:
        self.calls.append((method, params))
        return {}


class RecordingConnection:
    def __init__(self) -> None:
        self.frames: list[bytes] = []

    def sendall(self, frame: bytes) -> None:
        self.frames.append(frame)


class M4DevToolsClientTest(unittest.TestCase):
    def test_primary_click_uses_three_trusted_mouse_input_messages(self) -> None:
        recording = RecordingDevToolsClient()
        client = object.__new__(m4_cdp.DevToolsClient)
        client.call = recording.call  # type: ignore[method-assign]

        client.dispatch_primary_click(12.5, 34.75)

        self.assertEqual(
            recording.calls,
            [
                (
                    "Input.dispatchMouseEvent",
                    {
                        "type": "mouseMoved",
                        "x": 12.5,
                        "y": 34.75,
                        "pointerType": "mouse",
                    },
                ),
                (
                    "Input.dispatchMouseEvent",
                    {
                        "type": "mousePressed",
                        "x": 12.5,
                        "y": 34.75,
                        "button": "left",
                        "pointerType": "mouse",
                        "clickCount": 1,
                    },
                ),
                (
                    "Input.dispatchMouseEvent",
                    {
                        "type": "mouseReleased",
                        "x": 12.5,
                        "y": 34.75,
                        "button": "left",
                        "pointerType": "mouse",
                        "clickCount": 1,
                    },
                ),
            ],
        )

    def test_client_websocket_frames_are_masked(self) -> None:
        connection = RecordingConnection()
        client = object.__new__(m4_cdp.DevToolsClient)
        client._connection = connection  # type: ignore[assignment]

        with mock.patch.object(
            m4_cdp.os, "urandom", return_value=b"\x01\x02\x03\x04"
        ):
            client._send_frame(0x1, b"hello")

        self.assertEqual(len(connection.frames), 1)
        frame = connection.frames[0]
        self.assertEqual(frame[:2], b"\x81\x85")
        mask = frame[2:6]
        self.assertEqual(mask, b"\x01\x02\x03\x04")
        payload = bytes(
            value ^ mask[index % len(mask)]
            for index, value in enumerate(frame[6:])
        )
        self.assertEqual(payload, b"hello")


if __name__ == "__main__":
    unittest.main()
