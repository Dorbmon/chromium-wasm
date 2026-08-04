#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused validation tests for the M4 native Blink title-tooltip smoke."""

from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest
from urllib.parse import parse_qs, urlsplit


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import m3_content_server
import m4_cdp


VERSIONS = {
    "chromium": "chromium-revision",
    "v8": "v8-revision",
    "emscripten": "emscripten-revision",
    "port": "port-revision",
}

HOVER_X = 220
HOVER_Y = 116
CONFIRM_X = 220
CONFIRM_Y = 286
CLEAR_X = 580
CLEAR_Y = 376
TOOLTIP_X = CONFIRM_X + 12
TOOLTIP_Y = CONFIRM_Y + 18


def pointer_record(
    x: int, y: int, sequence: int, frame_id: int
) -> dict[str, object]:
    return {
        "type": "move",
        "pointerId": 1,
        "trusted": True,
        "queued": True,
        "button": -1,
        "buttons": 0,
        "sequence": sequence,
        "x": x,
        "y": y,
        "frameIdBefore": frame_id,
        "canvasFocused": True,
    }


def inner_move(
    prefix: str, target_id: str, x: int, y: int, observed_at_ms: int
) -> dict[str, object]:
    return {
        "type": f"{prefix}move",
        "trusted": True,
        "button": 0 if prefix == "mouse" else -1,
        "buttons": 0,
        "clientX": x,
        "clientY": y,
        "targetId": target_id,
        "defaultPrevented": False,
        "observedAtMs": observed_at_ms,
    }


def overlay_scan() -> dict[str, object]:
    return {
        "backgroundRgba": [32, 33, 36, 255],
        "borderRgba": [95, 99, 104, 255],
        "inkRgba": [255, 255, 255, 255],
        "backgroundPixels": 1952,
        "borderPixels": 264,
        "inkPixels": 424,
        "minX": TOOLTIP_X,
        "minY": TOOLTIP_Y,
        "maxX": TOOLTIP_X + 110 - 1,
        "maxY": TOOLTIP_Y + 24 - 1,
        "width": 110,
        "height": 24,
        "anchorX": TOOLTIP_X,
        "anchorY": TOOLTIP_Y,
        "label": "SWAM TOOLTIP",
    }


def passing_result() -> tuple[dict[str, object], dict[str, str]]:
    records = [
        pointer_record(HOVER_X, HOVER_Y, 1, 10),
        pointer_record(CLEAR_X, CLEAR_Y, 2, 10),
        pointer_record(CONFIRM_X, CONFIRM_Y, 3, 11),
        pointer_record(CONFIRM_X, CONFIRM_Y, 4, 11),
        pointer_record(CLEAR_X, CLEAR_Y, 5, 13),
    ]
    pointer_input: dict[str, object] = {
        "enabled": True,
        "receivedCount": len(records),
        "trustedCount": len(records),
        "queuedCount": len(records),
        "queuedRecords": records,
        "lastQueued": copy.deepcopy(records[-1]),
    }
    page_probe: dict[str, object] = {
        "fontReady": True,
        "protocol": 1,
        "fixture": "chromium-wasm-m4-ozone-tooltip-v1",
        "ready": True,
        "timerTicks": 3,
        "hoverTargetX": HOVER_X,
        "hoverTargetY": HOVER_Y,
        "confirmTargetX": CONFIRM_X,
        "confirmTargetY": CONFIRM_Y,
        "clearTargetX": CLEAR_X,
        "clearTargetY": CLEAR_Y,
        "tooltipTitle": "WASM TOOLTIP",
        "confirmTitle": "SWAM TOOLTIP",
        "clearTitle": None,
        "mouseTrace": [
            inner_move("mouse", "tooltip-target", HOVER_X, HOVER_Y, 100),
            inner_move("mouse", "clear-target", CLEAR_X, CLEAR_Y, 115),
            inner_move("mouse", "confirm-target", CONFIRM_X, CONFIRM_Y, 1000),
            inner_move("mouse", "confirm-target", CONFIRM_X, CONFIRM_Y, 1015),
            inner_move("mouse", "clear-target", CLEAR_X, CLEAR_Y, 1100),
        ],
        "pointerTrace": [
            inner_move("pointer", "tooltip-target", HOVER_X, HOVER_Y, 101),
            inner_move("pointer", "clear-target", CLEAR_X, CLEAR_Y, 116),
            inner_move(
                "pointer", "confirm-target", CONFIRM_X, CONFIRM_Y, 1001
            ),
            inner_move(
                "pointer", "confirm-target", CONFIRM_X, CONFIRM_Y, 1016
            ),
            inner_move("pointer", "clear-target", CLEAR_X, CLEAR_Y, 1101),
        ],
        "resultText": "TRUSTED MOVE 5",
    }
    result: dict[str, object] = {
        "protocol": 1,
        "case": "ozone_tooltip_m4",
        "status": "pass",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "versions": VERSIONS,
        "readiness": {
            "ready": True,
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
                "id": 14,
                "timestampMs": 1180,
                "width": 800,
                "height": 600,
            },
            "pageProbe": page_probe,
            "pointerInput": copy.deepcopy(pointer_input),
        },
        "pointerInput": pointer_input,
        "tooltipRapidClearProof": {
            "frameId": 11,
            "backgroundPixels": 0,
            "quietForMs": m3_content_server.M4_TOOLTIP_CLEAR_QUIESCENCE_MS,
            "moveGapMs": 15,
        },
        "tooltipShowProof": {
            "frameId": 12,
            "overlay": overlay_scan(),
            "duplicateMoveGapMs": 15,
        },
        "tooltipClearProof": {
            "frameId": 14,
            "overlayAbsent": True,
            "backgroundPixels": 0,
            "quietForMs": m3_content_server.M4_TOOLTIP_CLEAR_QUIESCENCE_MS,
        },
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
                "m4:pointer:move:queued",
                "m4:pointer:move:queued",
                "m4:pointer:move:queued",
                "m4:pointer:move:queued",
                "shutdown:complete",
            ],
            "stdout": [],
            "stderr": [],
        },
        "failedChecks": [],
        "error": None,
    }
    return result, VERSIONS


class ServerStub:
    server_address = ("127.0.0.1", 34123)


class RecordingDevToolsClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    def call(
        self, method: str, params: dict[str, object] | None = None
    ) -> dict[str, object]:
        self.calls.append((method, params))
        return {}


class M4TooltipUrlTest(unittest.TestCase):
    def test_tooltip_url_binds_the_dedicated_fixture_route_and_case(self) -> None:
        url = m3_content_server.m4_tooltip_smoke_url(
            ServerStub(),  # type: ignore[arg-type]
            "tooltip-token",
            VERSIONS,
            module_name="tooltip_shell_test",
            timeout_seconds=12.5,
        )

        parsed = urlsplit(url)
        self.assertEqual(parsed.scheme, "http")
        self.assertEqual(parsed.netloc, "127.0.0.1:34123")
        self.assertEqual(
            parse_qs(parsed.query),
            {
                "case": ["ozone_tooltip_m4"],
                "chromium": [VERSIONS["chromium"]],
                "emscripten": [VERSIONS["emscripten"]],
                "fixture": ["/__m3__/m4-tooltip-fixture.html"],
                "font": ["/__m3__/Ahem.woff2"],
                "module": ["/__m3__/artifacts/tooltip_shell_test.js"],
                "port": [VERSIONS["port"]],
                "token": ["tooltip-token"],
                "timeout_ms": ["12500"],
                "v8": [VERSIONS["v8"]],
            },
        )
        self.assertEqual(
            m3_content_server.M4_TOOLTIP_FIXTURE.name,
            "m4_ozone_tooltip_page.html",
        )


class M4TooltipDevToolsClientTest(unittest.TestCase):
    def test_mouse_move_uses_one_trusted_mouse_input_message(self) -> None:
        recording = RecordingDevToolsClient()
        client = object.__new__(m4_cdp.DevToolsClient)
        client.call = recording.call  # type: ignore[method-assign]

        client.dispatch_mouse_move(220.5, 116.25)

        self.assertEqual(
            recording.calls,
            [
                (
                    "Input.dispatchMouseEvent",
                    {
                        "type": "mouseMoved",
                        "x": 220.5,
                        "y": 116.25,
                        "pointerType": "mouse",
                    },
                ),
            ],
        )


class M4TooltipResultValidationTest(unittest.TestCase):
    def assert_valid(
        self, result: dict[str, object], versions: dict[str, str]
    ) -> None:
        self.assertIsNone(
            m3_content_server.validate_m4_tooltip_result(
                result, expected_versions=versions
            )
        )

    def page_probe(self, result: dict[str, object]) -> dict[str, object]:
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        return page_probe

    def pointer_records(self, result: dict[str, object]) -> list[dict[str, object]]:
        pointer = result["pointerInput"]
        assert isinstance(pointer, dict)
        records = pointer["queuedRecords"]
        assert isinstance(records, list)
        return records  # type: ignore[return-value]

    def test_complete_native_title_tooltip_contract_is_accepted(self) -> None:
        result, versions = passing_result()

        self.assert_valid(result, versions)

    def test_tooltip_requires_five_exact_trusted_unpressed_moves(self) -> None:
        result, versions = passing_result()
        self.pointer_records(result)[1]["button"] = 0
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        self.pointer_records(result)[1]["x"] = CLEAR_X - 1
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        self.pointer_records(result)[1]["trusted"] = False
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        self.pointer_records(result)[3]["x"] = CONFIRM_X - 1
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

    def test_tooltip_requires_the_native_blink_title_move_trace(self) -> None:
        result, versions = passing_result()
        pointer_trace = self.page_probe(result)["pointerTrace"]
        assert isinstance(pointer_trace, list)
        clear_trace = pointer_trace[1]
        assert isinstance(clear_trace, dict)
        clear_trace["targetId"] = "tooltip-target"
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        mouse_trace = self.page_probe(result)["mouseTrace"]
        assert isinstance(mouse_trace, list)
        hover_trace = mouse_trace[0]
        assert isinstance(hover_trace, dict)
        hover_trace["trusted"] = False
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

    def test_tooltip_visual_requires_the_exact_native_overlay_protocol(self) -> None:
        result, versions = passing_result()
        shown = result["tooltipShowProof"]
        assert isinstance(shown, dict)
        overlay = shown["overlay"]
        assert isinstance(overlay, dict)
        overlay["inkPixels"] = 423
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        shown = result["tooltipShowProof"]
        assert isinstance(shown, dict)
        overlay = shown["overlay"]
        assert isinstance(overlay, dict)
        overlay["anchorX"] = TOOLTIP_X - 1
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

    def test_tooltip_show_and_clear_require_later_compositor_frames(self) -> None:
        result, versions = passing_result()
        rapid = result["tooltipRapidClearProof"]
        assert isinstance(rapid, dict)
        rapid["backgroundPixels"] = 1
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        rapid = result["tooltipRapidClearProof"]
        assert isinstance(rapid, dict)
        rapid["quietForMs"] = (
            m3_content_server.M4_TOOLTIP_CLEAR_QUIESCENCE_MS - 1
        )
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        rapid = result["tooltipRapidClearProof"]
        assert isinstance(rapid, dict)
        rapid["moveGapMs"] = (
            m3_content_server.M4_TOOLTIP_RAPID_MOVE_MAX_GAP_MS + 1
        )
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        rapid = result["tooltipRapidClearProof"]
        assert isinstance(rapid, dict)
        rapid["frameId"] = 10
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        pointer_trace = self.page_probe(result)["pointerTrace"]
        assert isinstance(pointer_trace, list)
        second_move = pointer_trace[1]
        assert isinstance(second_move, dict)
        second_move["observedAtMs"] = (
            m3_content_server.M4_TOOLTIP_RAPID_MOVE_MAX_GAP_MS + 102
        )
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        shown = result["tooltipShowProof"]
        assert isinstance(shown, dict)
        shown["frameId"] = 10
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        shown = result["tooltipShowProof"]
        assert isinstance(shown, dict)
        shown["duplicateMoveGapMs"] = (
            m3_content_server.M4_TOOLTIP_RAPID_MOVE_MAX_GAP_MS + 1
        )
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        cleared = result["tooltipClearProof"]
        assert isinstance(cleared, dict)
        cleared["overlayAbsent"] = False
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        cleared = result["tooltipClearProof"]
        assert isinstance(cleared, dict)
        cleared["backgroundPixels"] = 1
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        cleared = result["tooltipClearProof"]
        assert isinstance(cleared, dict)
        cleared["quietForMs"] = (
            m3_content_server.M4_TOOLTIP_CLEAR_QUIESCENCE_MS - 1
        )
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)


if __name__ == "__main__":
    unittest.main()
