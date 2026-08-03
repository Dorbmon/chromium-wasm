#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused validation tests for the M4 native HTML select-popup smoke."""

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


VERSIONS = {
    "chromium": "chromium-revision",
    "v8": "v8-revision",
    "emscripten": "emscripten-revision",
    "port": "port-revision",
}

OPENER_X = 304
OPENER_Y = 175
OPTION_X = 303
OPTION_Y = 255


def pointer_record(
    event_type: str,
    x: int,
    y: int,
    button: int,
    buttons: int,
    sequence: int,
    frame_id: int,
) -> dict[str, object]:
    return {
        "type": event_type,
        "pointerId": 1,
        "trusted": True,
        "queued": True,
        "button": button,
        "buttons": buttons,
        "sequence": sequence,
        "x": x,
        "y": y,
        "frameIdBefore": frame_id,
        "canvasFocused": True,
    }


def opener_event(
    sequence: int, event_type: str, button: int, buttons: int
) -> dict[str, object]:
    return {
        "sequence": sequence,
        "type": event_type,
        "trusted": True,
        "targetId": "select-target",
        "clientX": OPENER_X,
        "clientY": OPENER_Y,
        "button": button,
        "buttons": buttons,
        "value": "one",
        "selectedIndex": 0,
    }


def select_event(sequence: int, event_type: str) -> dict[str, object]:
    return {
        "sequence": sequence,
        "type": event_type,
        "trusted": True,
        "targetId": "select-target",
        "value": "two",
        "selectedIndex": 1,
    }


def passing_result() -> tuple[dict[str, object], dict[str, str]]:
    records = [
        pointer_record("move", OPENER_X, OPENER_Y, -1, 0, 1, 10),
        pointer_record("down", OPENER_X, OPENER_Y, 0, 1, 2, 10),
        pointer_record("up", OPENER_X, OPENER_Y, 0, 0, 3, 10),
        pointer_record("move", OPTION_X, OPTION_Y, -1, 0, 4, 12),
        pointer_record("down", OPTION_X, OPTION_Y, 0, 1, 5, 12),
        pointer_record("up", OPTION_X, OPTION_Y, 0, 0, 6, 12),
    ]
    pointer_input: dict[str, object] = {
        "enabled": True,
        "receivedCount": len(records),
        "trustedCount": len(records),
        "queuedCount": len(records),
        "queuedRecords": records,
        "lastQueued": copy.deepcopy(records[-1]),
    }
    popup_open_pointer = copy.deepcopy(records[2])
    option_pointer = copy.deepcopy(records[-1])
    popup_option_scan = {
        "rgba": [250, 0, 250, 255],
        "pixelCount": 16848,
        "minX": 125,
        "maxX": 482,
        "minY": 228,
        "maxY": 283,
        "targetX": OPTION_X,
        "targetY": OPTION_Y,
    }
    page_probe: dict[str, object] = {
        "fontReady": True,
        "protocol": 1,
        "fixture": "chromium-wasm-m4-ozone-select-v1",
        "ready": True,
        "timerTicks": 3,
        "activeElementId": "select-target",
        "targetCenterX": OPENER_X,
        "targetCenterY": OPENER_Y,
        "targetBounds": {
            "left": 124,
            "top": 151,
            "right": 484,
            "bottom": 199,
        },
        "selectValue": "two",
        "selectedIndex": 1,
        "openerEventTrace": [
            opener_event(1, "pointerdown", 0, 1),
            opener_event(2, "mousedown", 0, 1),
            opener_event(3, "pointerup", 0, 0),
            opener_event(4, "mouseup", 0, 0),
            opener_event(5, "click", 0, 0),
        ],
        "inputEventTrace": [select_event(6, "input")],
        "changeEventTrace": [select_event(7, "change")],
        "resultText": "SELECTED:two",
    }
    result: dict[str, object] = {
        "protocol": 1,
        "case": "ozone_select_m4",
        "status": "pass",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "versions": VERSIONS,
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
                "id": 14,
                "timestampMs": 1180,
                "width": 800,
                "height": 600,
            },
            "pageProbe": page_probe,
            "pointerInput": copy.deepcopy(pointer_input),
        },
        "pointerInput": pointer_input,
        "popupOpenPointer": popup_open_pointer,
        "optionPointer": option_pointer,
        "popupOptionScan": popup_option_scan,
        "popupClosed": True,
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
                "m4:pointer:move:queued",
                "m4:pointer:down:queued",
                "m4:pointer:up:queued",
                "shutdown:complete",
            ],
            "stdout": [],
            "stderr": [],
        },
        "failedChecks": [],
        "error": None,
    }
    return result, VERSIONS


class M4SelectResultValidationTest(unittest.TestCase):
    def assert_valid(
        self, result: dict[str, object], versions: dict[str, str]
    ) -> None:
        self.assertIsNone(
            m3_content_server.validate_m4_select_result(
                result, expected_versions=versions
            )
        )

    def page_probe(self, result: dict[str, object]) -> dict[str, object]:
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        return page_probe

    def records(self, result: dict[str, object]) -> list[dict[str, object]]:
        pointer = result["pointerInput"]
        assert isinstance(pointer, dict)
        records = pointer["queuedRecords"]
        assert isinstance(records, list)
        return records  # type: ignore[return-value]

    def test_complete_native_select_popup_contract_is_accepted(self) -> None:
        result, versions = passing_result()

        self.assert_valid(result, versions)

    def test_selected_value_and_index_must_be_the_second_option(self) -> None:
        result, versions = passing_result()
        self.page_probe(result)["selectValue"] = "one"
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        self.page_probe(result)["selectedIndex"] = 0
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

    def test_input_and_change_events_must_be_trusted_native_delivery(self) -> None:
        result, versions = passing_result()
        trace = self.page_probe(result)["inputEventTrace"]
        assert isinstance(trace, list)
        event = trace[0]
        assert isinstance(event, dict)
        event["trusted"] = False
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        trace = self.page_probe(result)["changeEventTrace"]
        assert isinstance(trace, list)
        event = trace[0]
        assert isinstance(event, dict)
        event["selectedIndex"] = 0
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

    def test_open_and_option_clicks_must_be_complete_trusted_pointer_traces(
        self,
    ) -> None:
        result, versions = passing_result()
        record = self.records(result)[2]
        record["trusted"] = False
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        readiness["pointerInput"] = copy.deepcopy(result["pointerInput"])
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        record = self.records(result)[4]
        record["buttons"] = 0
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        readiness["pointerInput"] = copy.deepcopy(result["pointerInput"])
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

    def test_option_click_must_use_the_exact_scan_derived_target(self) -> None:
        result, versions = passing_result()
        option_pointer = result["optionPointer"]
        assert isinstance(option_pointer, dict)
        option_pointer["x"] = OPTION_X - 1
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        scan = result["popupOptionScan"]
        assert isinstance(scan, dict)
        scan["targetY"] = OPTION_Y - 1
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

    def test_popup_open_snapshot_must_be_the_first_click_release(self) -> None:
        result, versions = passing_result()
        popup_open_pointer = result["popupOpenPointer"]
        assert isinstance(popup_open_pointer, dict)
        popup_open_pointer["sequence"] = 2

        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

    def test_popup_scan_requires_the_exact_opaque_option_color(self) -> None:
        result, versions = passing_result()
        scan = result["popupOptionScan"]
        assert isinstance(scan, dict)
        scan["rgba"] = [250, 0, 250, 254]
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        scan = result["popupOptionScan"]
        assert isinstance(scan, dict)
        scan["pixelCount"] = 0
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

    def test_popup_must_close_and_the_option_click_must_present_a_later_frame(
        self,
    ) -> None:
        result, versions = passing_result()
        result["popupClosed"] = False
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        frame = readiness["frame"]
        assert isinstance(frame, dict)
        frame["id"] = 12
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

    def test_readiness_pointer_evidence_must_match_the_result(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        readiness_pointer = readiness["pointerInput"]
        assert isinstance(readiness_pointer, dict)
        readiness_pointer["queuedCount"] = 5

        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

    def test_clean_shutdown_is_required(self) -> None:
        result, versions = passing_result()
        shutdown = result["shutdown"]
        assert isinstance(shutdown, dict)
        shutdown["runtimeExitCode"] = 1

        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)


class M4SelectUrlTest(unittest.TestCase):
    def test_select_url_uses_the_dedicated_case_and_fixture(self) -> None:
        class Server:
            server_address = ("127.0.0.1", 31415)

        url = m3_content_server.m4_select_smoke_url(
            Server(),
            "select-token",
            VERSIONS,
            module_name="select_shell",
            timeout_seconds=12.5,
        )

        parsed = urlsplit(url)
        self.assertEqual(parsed.scheme, "http")
        self.assertEqual(parsed.netloc, "127.0.0.1:31415")
        self.assertEqual(parsed.path, "/__m3__/")
        self.assertEqual(
            parse_qs(parsed.query),
            {
                "case": ["ozone_select_m4"],
                "chromium": ["chromium-revision"],
                "emscripten": ["emscripten-revision"],
                "fixture": ["/__m3__/m4-select-fixture.html"],
                "font": ["/__m3__/Ahem.woff2"],
                "module": ["/__m3__/artifacts/select_shell.js"],
                "port": ["port-revision"],
                "token": ["select-token"],
                "timeout_ms": ["12500"],
                "v8": ["v8-revision"],
            },
        )


if __name__ == "__main__":
    unittest.main()
