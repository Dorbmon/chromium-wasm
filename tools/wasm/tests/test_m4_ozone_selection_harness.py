#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused validation tests for the bounded M4 pointer-selection smoke."""

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
import run_m4_ozone_smoke


COORDINATES = {
    "targetX": 220,
    "targetY": 144,
    "dragStartX": 180,
    "dragStartY": 228,
    "dragMiddleX": 246,
    "dragMiddleY": 228,
    "dragEndX": 312,
    "dragEndY": 228,
}


def outer_trace() -> tuple[tuple[str, int, int], ...]:
    return (
        ("move", COORDINATES["targetX"], COORDINATES["targetY"]),
        ("down", COORDINATES["targetX"], COORDINATES["targetY"]),
        ("up", COORDINATES["targetX"], COORDINATES["targetY"]),
        (
            "move",
            COORDINATES["dragStartX"],
            COORDINATES["dragStartY"],
        ),
        (
            "down",
            COORDINATES["dragStartX"],
            COORDINATES["dragStartY"],
        ),
        (
            "move",
            COORDINATES["dragMiddleX"],
            COORDINATES["dragMiddleY"],
        ),
        ("move", COORDINATES["dragEndX"], COORDINATES["dragEndY"]),
        ("up", COORDINATES["dragEndX"], COORDINATES["dragEndY"]),
    )


def outer_record(
    event_type: str, x: int, y: int, sequence: int
) -> dict[str, object]:
    return {
        "type": event_type,
        "trusted": True,
        "queued": True,
        "canvasFocused": True,
        "sequence": sequence,
        "x": x,
        "y": y,
        "frameIdBefore": 10,
    }


def inner_trace(prefix: str) -> list[dict[str, object]]:
    expected = (
        ("move", COORDINATES["targetX"], COORDINATES["targetY"], -1, 0),
        ("move", COORDINATES["targetX"], COORDINATES["targetY"], -1, 0),
        ("down", COORDINATES["targetX"], COORDINATES["targetY"], 0, 1),
        ("move", COORDINATES["targetX"], COORDINATES["targetY"], -1, 1),
        ("up", COORDINATES["targetX"], COORDINATES["targetY"], 0, 0),
        (
            "move",
            COORDINATES["dragStartX"],
            COORDINATES["dragStartY"],
            -1,
            0,
        ),
        (
            "down",
            COORDINATES["dragStartX"],
            COORDINATES["dragStartY"],
            0,
            1,
        ),
        (
            "move",
            COORDINATES["dragMiddleX"],
            COORDINATES["dragMiddleY"],
            -1,
            1,
        ),
        ("move", COORDINATES["dragEndX"], COORDINATES["dragEndY"], -1, 1),
        ("up", COORDINATES["dragEndX"], COORDINATES["dragEndY"], 0, 0),
    )
    return [
        {
            "type": prefix + event_type,
            "trusted": True,
            "button": 0
            if prefix == "mouse" and event_type == "move"
            else pointer_button,
            "buttons": buttons,
            "clientX": x,
            "clientY": y,
            "targetId": "editable-target",
            "defaultPrevented": False,
        }
        for event_type, x, y, pointer_button, buttons in expected
    ]


def passing_result() -> tuple[dict[str, object], dict[str, str]]:
    versions = {
        "chromium": "chromium-revision",
        "v8": "v8-revision",
        "emscripten": "emscripten-revision",
        "port": "port-revision",
    }
    records = [
        outer_record(event_type, x, y, index + 1)
        for index, (event_type, x, y) in enumerate(outer_trace())
    ]
    pointer_input = {
        "enabled": True,
        "receivedCount": 8,
        "trustedCount": 8,
        "queuedCount": 8,
        "queuedRecords": records,
        "lastQueued": copy.deepcopy(records[-1]),
    }
    activation_proof = {
        "outerTraceExact": True,
        "activationEvidence": True,
        "selectionCollapsed": True,
        "selectionStart": 2,
        "selectionEnd": 2,
        "selectionDirectionNeutral": True,
        "selectionDirection": "none",
        "selectedTextEmpty": True,
        "selectedText": "",
        "frameAfterActivation": True,
    }
    page_probe: dict[str, object] = {
        "fontReady": True,
        "protocol": 1,
        "fixture": "chromium-wasm-m4-ozone-selection-v1",
        "ready": True,
        "activeElementId": "editable-target",
        "activationCount": 1,
        "clickTrusted": True,
        "focusCount": 1,
        "focusTrusted": True,
        "value": "WASM",
        "selectionStart": 0,
        "selectionEnd": 4,
        "selectionDirection": "none",
        "selectedText": "WASM",
        "resultText": "TEXT SELECTED",
        "timerTicks": 3,
        **COORDINATES,
        "selectionActivity": {
            "count": 2,
            "trusted": True,
            "nonCollapsed": True,
            "trustedNonCollapsed": True,
            "selectCount": 1,
            "selectTrusted": True,
            "selectionChangeCount": 1,
            "selectionChangeTrusted": True,
        },
        "textInputEvents": {
            "beforeinputCount": 0,
            "inputCount": 0,
            "compositionstartCount": 0,
            "compositionupdateCount": 0,
            "compositionendCount": 0,
        },
        "mouseEventTrace": inner_trace("mouse"),
        "pointerEventTrace": inner_trace("pointer"),
    }
    result: dict[str, object] = {
        "protocol": 1,
        "case": "ozone_selection_m4",
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
            "pointerInput": copy.deepcopy(pointer_input),
        },
        "pointerInput": pointer_input,
        "activationProof": activation_proof,
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
                "m4:pointer:move:queued",
                "m4:pointer:move:queued",
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


class M4SelectionResultValidationTest(unittest.TestCase):
    def assert_valid(
        self, result: dict[str, object], versions: dict[str, str]
    ) -> None:
        self.assertIsNone(
            m3_content_server.validate_m4_selection_result(
                result, expected_versions=versions
            )
        )

    def page_probe(self, result: dict[str, object]) -> dict[str, object]:
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        return page_probe

    def pointer_input(self, result: dict[str, object]) -> dict[str, object]:
        pointer_input = result["pointerInput"]
        assert isinstance(pointer_input, dict)
        return pointer_input

    def activation_proof(self, result: dict[str, object]) -> dict[str, object]:
        proof = result["activationProof"]
        assert isinstance(proof, dict)
        return proof

    def test_complete_native_selection_contract_is_accepted(self) -> None:
        result, versions = passing_result()

        self.assert_valid(result, versions)

    def test_mutated_fixed_markup_value_is_rejected(self) -> None:
        result, versions = passing_result()
        self.page_probe(result)["value"] = "WAS"

        with self.assertRaisesRegex(M0Error, "value mismatch"):
            self.assert_valid(result, versions)

    def test_backward_or_invalid_final_selection_direction_is_rejected(
        self,
    ) -> None:
        result, versions = passing_result()
        for selection_direction in ("backward", "invalid"):
            with self.subTest(selection_direction=selection_direction):
                self.page_probe(result)["selectionDirection"] = (
                    selection_direction
                )

                with self.assertRaisesRegex(
                    M0Error, "selection direction is invalid"
                ):
                    self.assert_valid(result, versions)

    def test_final_selection_requires_an_activation(self) -> None:
        result, versions = passing_result()
        self.page_probe(result)["activationCount"] = 0

        with self.assertRaisesRegex(M0Error, "activation count"):
            self.assert_valid(result, versions)

    def test_collapsed_or_untrusted_selection_is_rejected(self) -> None:
        result, versions = passing_result()
        activity = self.page_probe(result)["selectionActivity"]
        assert isinstance(activity, dict)
        activity["trustedNonCollapsed"] = False

        with self.assertRaisesRegex(
            M0Error, "activity trustedNonCollapsed is not true"
        ):
            self.assert_valid(result, versions)

    def test_activation_proof_requires_a_collapsed_native_selection(self) -> None:
        result, versions = passing_result()
        self.activation_proof(result)["selectionEnd"] = 3

        with self.assertRaisesRegex(M0Error, "selection is not collapsed"):
            self.assert_valid(result, versions)

    def test_activation_proof_requires_valid_direction_and_empty_text(self) -> None:
        result, versions = passing_result()
        proof = self.activation_proof(result)
        proof["selectionDirection"] = "forward"
        self.assert_valid(result, versions)

        result, versions = passing_result()
        proof = self.activation_proof(result)
        proof["selectionDirection"] = "backward"
        with self.assertRaisesRegex(M0Error, "selection direction is invalid"):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        proof = self.activation_proof(result)
        proof["selectedText"] = "A"

        with self.assertRaisesRegex(M0Error, "selected text is not empty"):
            self.assert_valid(result, versions)

    def test_text_or_composition_input_is_rejected(self) -> None:
        result, versions = passing_result()
        text_events = self.page_probe(result)["textInputEvents"]
        assert isinstance(text_events, dict)
        text_events["beforeinputCount"] = 1

        with self.assertRaisesRegex(M0Error, "unexpectedly received text"):
            self.assert_valid(result, versions)

    def test_outer_pointer_trace_requires_exact_coordinates(self) -> None:
        result, versions = passing_result()
        records = self.pointer_input(result)["queuedRecords"]
        assert isinstance(records, list)
        record = records[5]
        assert isinstance(record, dict)
        record["x"] = COORDINATES["dragMiddleX"] - 1
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        readiness["pointerInput"] = copy.deepcopy(self.pointer_input(result))

        with self.assertRaisesRegex(M0Error, "does not match the fixture"):
            self.assert_valid(result, versions)

    def test_drag_geometry_must_be_strictly_forward(self) -> None:
        result, versions = passing_result()
        page_probe = self.page_probe(result)
        page_probe["dragMiddleX"] = page_probe["dragStartX"]

        with self.assertRaisesRegex(
            M0Error, "drag geometry is not strictly forward"
        ):
            self.assert_valid(result, versions)

    def test_outer_pointer_sequence_must_be_exact(self) -> None:
        result, versions = passing_result()
        records = self.pointer_input(result)["queuedRecords"]
        assert isinstance(records, list)
        record = records[3]
        assert isinstance(record, dict)
        record["sequence"] = 7
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        readiness["pointerInput"] = copy.deepcopy(self.pointer_input(result))

        with self.assertRaisesRegex(M0Error, "sequence is not exact"):
            self.assert_valid(result, versions)

    def test_mouse_and_pointer_move_button_semantics_are_distinct(self) -> None:
        result, versions = passing_result()
        mouse_trace = self.page_probe(result)["mouseEventTrace"]
        assert isinstance(mouse_trace, list)
        mouse_move = mouse_trace[0]
        assert isinstance(mouse_move, dict)
        mouse_move["button"] = -1

        with self.assertRaisesRegex(M0Error, "mouse trace 0 button mismatch"):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        pointer_trace = self.page_probe(result)["pointerEventTrace"]
        assert isinstance(pointer_trace, list)
        pointer_move = pointer_trace[0]
        assert isinstance(pointer_move, dict)
        pointer_move["button"] = 0

        with self.assertRaisesRegex(
            M0Error, "pointer trace 0 button mismatch"
        ):
            self.assert_valid(result, versions)

    def test_post_drag_compositor_frame_is_required(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        frame = readiness["frame"]
        assert isinstance(frame, dict)
        frame["id"] = 10

        with self.assertRaisesRegex(M0Error, "no compositor frame after drag"):
            self.assert_valid(result, versions)

    def test_readiness_pointer_snapshot_must_match_result(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        readiness_pointer = readiness["pointerInput"]
        assert isinstance(readiness_pointer, dict)
        readiness_pointer["queuedCount"] = 7

        with self.assertRaisesRegex(
            M0Error, "pointer evidence differs from readiness evidence"
        ):
            self.assert_valid(result, versions)


class M4SelectionCanvasPointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = {"dragStartX": 100, "dragStartY": 50}
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

    def test_drag_point_accounts_for_border_and_backing_scale(self) -> None:
        self.assertEqual(
            run_m4_ozone_smoke.canvas_point_position(
                self.state,
                self.geometry,
                x_field="dragStartX",
                y_field="dragStartY",
                description="drag start",
            ),
            (62.25, 48.25),
        )

    def test_missing_or_invalid_drag_point_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            M0Error, "did not publish fixture drag start coordinates"
        ):
            run_m4_ozone_smoke.canvas_point_position(
                {},
                self.geometry,
                x_field="dragStartX",
                y_field="dragStartY",
                description="drag start",
            )
        with self.assertRaisesRegex(
            M0Error, "invalid fixture drag start coordinates"
        ):
            run_m4_ozone_smoke.canvas_point_position(
                {"dragStartX": True, "dragStartY": 50},
                self.geometry,
                x_field="dragStartX",
                y_field="dragStartY",
                description="drag start",
            )


class M4SelectionActivationStageTest(unittest.TestCase):
    def passing_state(self) -> dict[str, object]:
        return {
            "state": "awaiting-dom-selection-drag",
            "activationProof": {
                "outerTraceExact": True,
                "activationEvidence": True,
                "selectionCollapsed": True,
                "selectionStart": 2,
                "selectionEnd": 2,
                "selectionDirectionNeutral": True,
                "selectionDirection": "none",
                "selectedTextEmpty": True,
                "selectedText": "",
                "frameAfterActivation": True,
            },
        }

    def test_drag_requires_the_frozen_collapsed_selection_proof(self) -> None:
        run_m4_ozone_smoke.validate_selection_activation_stage(
            self.passing_state()
        )

    def test_drag_rejects_missing_or_incomplete_activation_proof(self) -> None:
        with self.assertRaisesRegex(M0Error, "did not publish a proof"):
            run_m4_ozone_smoke.validate_selection_activation_stage({})

        state = self.passing_state()
        proof = state["activationProof"]
        assert isinstance(proof, dict)
        proof["selectionCollapsed"] = False
        with self.assertRaisesRegex(M0Error, "selectionCollapsed"):
            run_m4_ozone_smoke.validate_selection_activation_stage(state)

    def test_drag_requires_empty_valid_collapsed_native_selection(self) -> None:
        state = self.passing_state()
        proof = state["activationProof"]
        assert isinstance(proof, dict)
        proof["selectionEnd"] = 3
        with self.assertRaisesRegex(M0Error, "collapsed native selection"):
            run_m4_ozone_smoke.validate_selection_activation_stage(state)

        state = self.passing_state()
        proof = state["activationProof"]
        assert isinstance(proof, dict)
        proof["selectionDirection"] = "forward"
        run_m4_ozone_smoke.validate_selection_activation_stage(state)

        state = self.passing_state()
        proof = state["activationProof"]
        assert isinstance(proof, dict)
        proof["selectionDirection"] = "backward"
        with self.assertRaisesRegex(M0Error, "selection direction is invalid"):
            run_m4_ozone_smoke.validate_selection_activation_stage(state)

        state = self.passing_state()
        proof = state["activationProof"]
        assert isinstance(proof, dict)
        proof["selectedText"] = "A"
        with self.assertRaisesRegex(M0Error, "selected text is not empty"):
            run_m4_ozone_smoke.validate_selection_activation_stage(state)


class M4SelectionUrlTest(unittest.TestCase):
    def test_selection_url_uses_the_dedicated_case_and_fixture(self) -> None:
        class Server:
            server_address = ("127.0.0.1", 31415)

        url = m3_content_server.m4_selection_smoke_url(
            Server(),
            "selection-token",
            {
                "chromium": "chromium-revision",
                "v8": "v8-revision",
                "emscripten": "emscripten-revision",
                "port": "port-revision",
            },
            module_name="selection_shell",
            timeout_seconds=12.5,
        )

        parsed = urlsplit(url)
        self.assertEqual(parsed.scheme, "http")
        self.assertEqual(parsed.netloc, "127.0.0.1:31415")
        self.assertEqual(parsed.path, "/__m3__/")
        self.assertEqual(
            parse_qs(parsed.query),
            {
                "case": ["ozone_selection_m4"],
                "chromium": ["chromium-revision"],
                "emscripten": ["emscripten-revision"],
                "fixture": ["/__m3__/m4-selection-fixture.html"],
                "font": ["/__m3__/Ahem.woff2"],
                "module": ["/__m3__/artifacts/selection_shell.js"],
                "port": ["port-revision"],
                "token": ["selection-token"],
                "timeout_ms": ["12500"],
                "v8": ["v8-revision"],
            },
        )


class RecordingDevToolsClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    def call(
        self, method: str, params: dict[str, object] | None = None
    ) -> dict[str, object]:
        self.calls.append((method, params))
        return {}


class M4SelectionDevToolsClientTest(unittest.TestCase):
    def test_primary_drag_uses_only_trusted_mouse_events(self) -> None:
        recording = RecordingDevToolsClient()
        client = object.__new__(m4_cdp.DevToolsClient)
        client.call = recording.call  # type: ignore[method-assign]

        client.dispatch_primary_drag(10.5, 20.5, 30.5, 40.5, 50.5, 60.5)

        self.assertEqual(
            recording.calls,
            [
                (
                    "Input.dispatchMouseEvent",
                    {
                        "type": "mouseMoved",
                        "x": 10.5,
                        "y": 20.5,
                        "pointerType": "mouse",
                    },
                ),
                (
                    "Input.dispatchMouseEvent",
                    {
                        "type": "mousePressed",
                        "x": 10.5,
                        "y": 20.5,
                        "button": "left",
                        "clickCount": 1,
                        "pointerType": "mouse",
                    },
                ),
                (
                    "Input.dispatchMouseEvent",
                    {
                        "type": "mouseMoved",
                        "x": 30.5,
                        "y": 40.5,
                        "button": "left",
                        "buttons": 1,
                        "pointerType": "mouse",
                    },
                ),
                (
                    "Input.dispatchMouseEvent",
                    {
                        "type": "mouseMoved",
                        "x": 50.5,
                        "y": 60.5,
                        "button": "left",
                        "buttons": 1,
                        "pointerType": "mouse",
                    },
                ),
                (
                    "Input.dispatchMouseEvent",
                    {
                        "type": "mouseReleased",
                        "x": 50.5,
                        "y": 60.5,
                        "button": "left",
                        "clickCount": 1,
                        "pointerType": "mouse",
                    },
                ),
            ],
        )
        self.assertTrue(
            all(
                "text" not in params
                for _, params in recording.calls
                if isinstance(params, dict)
            )
        )


if __name__ == "__main__":
    unittest.main()
