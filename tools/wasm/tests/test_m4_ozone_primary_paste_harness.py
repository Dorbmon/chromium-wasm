#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused validation tests for the M4 native primary-selection paste smoke."""

from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import m3_content_server
import m4_cdp


COORDINATES = {
    "sourceTargetX": 220,
    "sourceTargetY": 144,
    "dragStartX": 180,
    "dragStartY": 228,
    "dragMiddleX": 246,
    "dragMiddleY": 228,
    "dragEndX": 312,
    "dragEndY": 228,
    "pasteTargetX": 220,
    "pasteTargetY": 328,
}


def outer_trace() -> tuple[tuple[str, int, int, int, int], ...]:
    return (
        ("move", 220, 144, -1, 0),
        ("down", 220, 144, 0, 1),
        ("up", 220, 144, 0, 0),
        ("move", 180, 228, -1, 0),
        ("down", 180, 228, 0, 1),
        ("move", 246, 228, -1, 1),
        ("move", 312, 228, -1, 1),
        ("up", 312, 228, 0, 0),
        ("move", 220, 328, -1, 0),
        ("down", 220, 328, 1, 4),
        ("up", 220, 328, 1, 0),
    )


def outer_record(
    event_type: str,
    x: int,
    y: int,
    button: int,
    buttons: int,
    sequence: int,
) -> dict[str, object]:
    return {
        "type": event_type,
        "trusted": True,
        "queued": True,
        "button": button,
        "buttons": buttons,
        "sequence": sequence,
        "x": x,
        "y": y,
        "frameIdBefore": 10,
        "canvasFocused": True,
    }


def inner_button_events(
    prefix: str, target_id: str, button: int, buttons: int
) -> list[dict[str, object]]:
    return [
        {
            "type": prefix + "down",
            "trusted": True,
            "button": button,
            "buttons": buttons,
            "targetId": target_id,
            "defaultPrevented": False,
        },
        {
            "type": prefix + "up",
            "trusted": True,
            "button": button,
            "buttons": 0,
            "targetId": target_id,
            "defaultPrevented": False,
        },
    ]


def passing_result() -> tuple[dict[str, object], dict[str, str]]:
    versions = {
        "chromium": "chromium-revision",
        "v8": "v8-revision",
        "emscripten": "emscripten-revision",
        "port": "port-revision",
    }
    records = [
        outer_record(*record, index + 1)
        for index, record in enumerate(outer_trace())
    ]
    for record in records[-2:]:
        record["defaultPrevented"] = True
    pointer = {
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
        "fixture": "chromium-wasm-m4-ozone-primary-paste-v1",
        "ready": True,
        "timerTicks": 3,
        "activeElementId": "paste-target",
        "sourceActivationCount": 2,
        "sourceClickTrusted": True,
        "sourceFocusCount": 1,
        "sourceFocusTrusted": True,
        "sourceValue": "WASM",
        "sourceSelectionStart": 0,
        "sourceSelectionEnd": 4,
        "sourceSelectionDirection": "forward",
        "sourceSelectedText": "WASM",
        "pasteActivationCount": 0,
        "pasteClickTrusted": False,
        "pasteAuxClickCount": 1,
        "pasteAuxClickTrusted": True,
        "pasteFocusCount": 1,
        "pasteFocusTrusted": True,
        "pasteValue": "WASM",
        "pasteSelectionStart": 4,
        "pasteSelectionEnd": 4,
        "resultText": "PRIMARY SELECTION PASTED",
        **COORDINATES,
        "sourceSelectionActivity": {
            "count": 2,
            "trusted": True,
            "nonCollapsed": True,
            "trustedNonCollapsed": True,
            "selectCount": 1,
            "selectTrusted": True,
            "selectionChangeCount": 1,
            "selectionChangeTrusted": True,
        },
        "sourceTextInputEvents": {
            "beforeinputCount": 0,
            "inputCount": 0,
            "compositionstartCount": 0,
            "compositionupdateCount": 0,
            "compositionendCount": 0,
        },
        "sourceMouseEventTrace": inner_button_events(
            "mouse", "source-target", 0, 1
        ),
        "sourcePointerEventTrace": inner_button_events(
            "pointer", "source-target", 0, 1
        ),
        "pasteMouseEventTrace": inner_button_events(
            "mouse", "paste-target", 1, 4
        ),
        "pastePointerEventTrace": inner_button_events(
            "pointer", "paste-target", 1, 4
        ),
        "pasteEventTrace": [
            {
                "type": "paste",
                "trusted": True,
                "targetId": "paste-target",
                "defaultPrevented": False,
            }
        ],
        "pasteTextInputTrace": [
            {
                "type": "beforeinput",
                "trusted": True,
                "inputType": "insertFromPaste",
                "data": "WASM",
                "isComposing": False,
                "targetId": "paste-target",
            },
            {
                "type": "input",
                "trusted": True,
                "inputType": "insertFromPaste",
                "data": "WASM",
                "isComposing": False,
                "targetId": "paste-target",
            },
        ],
    }
    result: dict[str, object] = {
        "protocol": 1,
        "case": "ozone_primary_paste_m4",
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
                "id": 11,
                "timestampMs": 1180,
                "width": 800,
                "height": 600,
            },
            "pageProbe": page_probe,
            "pointerInput": copy.deepcopy(pointer),
        },
        "pointerInput": pointer,
        "activationProof": {
            "outerTraceExact": True,
            "sourceActivated": True,
            "selectionCollapsed": True,
            "frameAfterActivation": True,
        },
        "selectionProof": {
            "outerTraceExact": True,
            "nativeSelection": True,
            "innerSourceEvents": True,
            "frameAfterDrag": True,
        },
        "primaryPasteProof": {
            "sourceSelection": True,
            "outerTraceExact": True,
            "nativePaste": True,
            "frameAfterPaste": True,
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
    return result, versions


class M4PrimaryPasteResultValidationTest(unittest.TestCase):
    def assert_valid(
        self, result: dict[str, object], versions: dict[str, str]
    ) -> None:
        self.assertIsNone(
            m3_content_server.validate_m4_primary_paste_result(
                result, expected_versions=versions
            )
        )

    def page_probe(self, result: dict[str, object]) -> dict[str, object]:
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        return page_probe

    def pointer(self, result: dict[str, object]) -> dict[str, object]:
        pointer = result["pointerInput"]
        assert isinstance(pointer, dict)
        return pointer

    def sync_readiness_pointer(self, result: dict[str, object]) -> None:
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        readiness["pointerInput"] = copy.deepcopy(self.pointer(result))

    def test_complete_native_primary_paste_contract_is_accepted(self) -> None:
        result, versions = passing_result()

        self.assert_valid(result, versions)

    def test_primary_paste_requires_source_selection_proof(self) -> None:
        result, versions = passing_result()
        proof = result["primaryPasteProof"]
        assert isinstance(proof, dict)
        proof["sourceSelection"] = False

        with self.assertRaisesRegex(M0Error, "sourceSelection is not true"):
            self.assert_valid(result, versions)

    def test_middle_button_outer_record_is_required(self) -> None:
        result, versions = passing_result()
        records = self.pointer(result)["queuedRecords"]
        assert isinstance(records, list)
        middle_down = records[-2]
        assert isinstance(middle_down, dict)
        middle_down["button"] = 0
        self.sync_readiness_pointer(result)

        with self.assertRaisesRegex(M0Error, "button mismatch"):
            self.assert_valid(result, versions)

    def test_native_paste_input_data_is_required(self) -> None:
        result, versions = passing_result()
        trace = self.page_probe(result)["pasteTextInputTrace"]
        assert isinstance(trace, list)
        input_event = trace[1]
        assert isinstance(input_event, dict)
        input_event["data"] = "other"

        with self.assertRaisesRegex(M0Error, "data mismatch"):
            self.assert_valid(result, versions)

    def test_trusted_paste_event_is_required(self) -> None:
        result, versions = passing_result()
        trace = self.page_probe(result)["pasteEventTrace"]
        assert isinstance(trace, list)
        paste_event = trace[0]
        assert isinstance(paste_event, dict)
        paste_event["trusted"] = False

        with self.assertRaisesRegex(M0Error, "trusted mismatch"):
            self.assert_valid(result, versions)

    def test_source_text_mutation_is_rejected(self) -> None:
        result, versions = passing_result()
        source_text = self.page_probe(result)["sourceTextInputEvents"]
        assert isinstance(source_text, dict)
        source_text["inputCount"] = 1

        with self.assertRaisesRegex(M0Error, "unexpectedly received text"):
            self.assert_valid(result, versions)

    def test_source_selection_range_is_required(self) -> None:
        result, versions = passing_result()
        self.page_probe(result)["sourceSelectionEnd"] = 3

        with self.assertRaisesRegex(M0Error, "sourceSelectionEnd mismatch"):
            self.assert_valid(result, versions)

    def test_source_selected_text_is_required(self) -> None:
        result, versions = passing_result()
        self.page_probe(result)["sourceSelectedText"] = "WAS"

        with self.assertRaisesRegex(M0Error, "sourceSelectedText mismatch"):
            self.assert_valid(result, versions)

    def test_source_selection_direction_is_required(self) -> None:
        result, versions = passing_result()
        self.page_probe(result)["sourceSelectionDirection"] = "backward"

        with self.assertRaisesRegex(M0Error, "selection direction is invalid"):
            self.assert_valid(result, versions)

    def test_source_drag_click_is_required(self) -> None:
        result, versions = passing_result()
        self.page_probe(result)["sourceActivationCount"] = 1

        with self.assertRaisesRegex(M0Error, "sourceActivationCount mismatch"):
            self.assert_valid(result, versions)

    def test_canvas_is_focused_for_the_entire_pointer_trace(self) -> None:
        result, versions = passing_result()
        records = self.pointer(result)["queuedRecords"]
        assert isinstance(records, list)
        first_record = records[0]
        assert isinstance(first_record, dict)
        first_record["canvasFocused"] = False
        self.sync_readiness_pointer(result)

        with self.assertRaisesRegex(M0Error, "canvas focus mismatch"):
            self.assert_valid(result, versions)

    def test_middle_button_prevents_the_outer_page_default(self) -> None:
        result, versions = passing_result()
        records = self.pointer(result)["queuedRecords"]
        assert isinstance(records, list)
        middle_down = records[-2]
        assert isinstance(middle_down, dict)
        middle_down["defaultPrevented"] = False
        self.sync_readiness_pointer(result)

        with self.assertRaisesRegex(M0Error, "did not prevent"):
            self.assert_valid(result, versions)

    def test_post_paste_compositor_frame_is_required(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        frame = readiness["frame"]
        assert isinstance(frame, dict)
        frame["id"] = 10

        with self.assertRaisesRegex(M0Error, "no compositor frame after paste"):
            self.assert_valid(result, versions)


class RecordingDevToolsClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    def call(
        self, method: str, params: dict[str, object] | None = None
    ) -> dict[str, object]:
        self.calls.append((method, params))
        return {}


class M4PrimaryPasteDevToolsClientTest(unittest.TestCase):
    def test_middle_click_uses_an_unpressed_hover_then_middle_button(self) -> None:
        recording = RecordingDevToolsClient()
        client = object.__new__(m4_cdp.DevToolsClient)
        client.call = recording.call  # type: ignore[method-assign]

        client.dispatch_middle_click(12.5, 34.75)

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
                        "button": "middle",
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
                        "button": "middle",
                        "pointerType": "mouse",
                        "clickCount": 1,
                    },
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
