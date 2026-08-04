#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused validation tests for M4 printable Ozone key input."""

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


def key_record(
    event_type: str,
    code: str,
    key: str,
    sequence: int,
    frame_id: int,
) -> dict[str, object]:
    return {
        "type": event_type,
        "code": code,
        "key": key,
        "trusted": True,
        "queued": True,
        "repeat": False,
        "isComposing": False,
        "modifiers": {
            "alt": False,
            "control": False,
            "meta": False,
            "shift": False,
        },
        "sequence": sequence,
        "frameIdBefore": frame_id,
        "canvasFocused": True,
        "pointerActivated": True,
        "defaultPrevented": True,
    }


def inner_key_record(
    event_type: str, code: str, key: str
) -> dict[str, object]:
    return {
        "type": event_type,
        "trusted": True,
        "code": code,
        "key": key,
        "repeat": False,
        "isComposing": False,
        "defaultPrevented": False,
        "targetId": "editable-target",
    }


def text_input_record(event_type: str, data: str) -> dict[str, object]:
    return {
        "type": event_type,
        "trusted": True,
        "inputType": "insertText",
        "data": data,
        "isComposing": False,
        "targetId": "editable-target",
    }


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
            "x": 388,
            "y": 215,
            "frameIdBefore": 6,
        },
    }
    queued_records = [
        key_record("down", "KeyA", "a", 1, 7),
        key_record("up", "KeyA", "a", 2, 7),
        key_record("down", "KeyB", "b", 3, 8),
        key_record("up", "KeyB", "b", 4, 8),
    ]
    keyboard_input = {
        "enabled": True,
        "activated": True,
        "receivedCount": 4,
        "trustedCount": 4,
        "queuedCount": 4,
        "queuedRecords": queued_records,
        "pressedCodes": [],
        "lastQueuedDown": copy.deepcopy(queued_records[2]),
        "lastQueuedUp": copy.deepcopy(queued_records[3]),
    }
    page_probe = {
        "fontReady": True,
        "protocol": 1,
        "fixture": "chromium-wasm-m4-ozone-printable-key-v2",
        "ready": True,
        "targetCenterX": 388,
        "targetCenterY": 215,
        "timerTicks": 3,
        "activeElementId": "editable-target",
        "activationCount": 1,
        "clickTrusted": True,
        "focusCount": 1,
        "focusTrusted": True,
        "value": "ab",
        "selectionStart": 2,
        "selectionEnd": 2,
        "resultText": "TEXT INPUT RECEIVED",
        "keyEvents": {
            "keydownCount": 2,
            "keyupCount": 2,
        },
        "keyEventTrace": [
            inner_key_record("keydown", "KeyA", "a"),
            inner_key_record("keyup", "KeyA", "a"),
            inner_key_record("keydown", "KeyB", "b"),
            inner_key_record("keyup", "KeyB", "b"),
        ],
        "textInputTrace": [
            text_input_record("beforeinput", "a"),
            text_input_record("input", "a"),
            text_input_record("beforeinput", "b"),
            text_input_record("input", "b"),
        ],
        "textInputEvents": {
            "beforeinputCount": 2,
            "inputCount": 2,
            "compositionstartCount": 0,
            "compositionupdateCount": 0,
            "compositionendCount": 0,
        },
    }
    result: dict[str, object] = {
        "protocol": 1,
        "case": "ozone_printable_key_m4",
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
                "id": 9,
                "timestampMs": 1180,
                "width": 800,
                "height": 600,
            },
            "pageProbe": page_probe,
            "pointerInput": pointer_input,
            "keyboardInput": keyboard_input,
        },
        "pointerInput": pointer_input,
        "keyboardInput": keyboard_input,
        "keyAProof": {
            "outerTraceExact": True,
            "innerTraceExact": True,
            "textTraceExact": True,
            "noComposition": True,
            "value": "a",
            "selectionStart": 1,
            "selectionEnd": 1,
            "frameAfterKeyADown": True,
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
                "m4:keyboard:listeners-attached",
                "m4:pointer:down:queued",
                "m4:keyboard:pointer-activation",
                "m4:pointer:up:queued",
                "m4:keyboard:down:queued",
                "m4:keyboard:up:queued",
                "m4:keyboard:down:queued",
                "m4:keyboard:up:queued",
                "shutdown:complete",
            ],
            "stdout": [],
            "stderr": [],
        },
        "failedChecks": [],
        "error": None,
    }
    return result, versions


class M4PrintableKeyResultValidationTest(unittest.TestCase):
    def assert_valid(
        self, result: dict[str, object], versions: dict[str, str]
    ) -> None:
        self.assertIsNone(
            m3_content_server.validate_m4_printable_key_result(
                result, expected_versions=versions
            )
        )

    def test_complete_printable_key_contract_is_accepted(self) -> None:
        result, versions = passing_result()

        self.assert_valid(result, versions)

    def test_untrusted_inner_key_event_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        key_trace = page_probe["keyEventTrace"]
        assert isinstance(key_trace, list)
        key_b_down = key_trace[2]
        assert isinstance(key_b_down, dict)
        key_b_down["trusted"] = False

        with self.assertRaisesRegex(M0Error, "inner keyEventTrace"):
            self.assert_valid(result, versions)

    def test_outer_key_trace_requires_key_a_then_key_b(self) -> None:
        result, versions = passing_result()
        keyboard = result["keyboardInput"]
        assert isinstance(keyboard, dict)
        records = keyboard["queuedRecords"]
        assert isinstance(records, list)
        key_b_down = records[2]
        assert isinstance(key_b_down, dict)
        key_b_down["code"] = "KeyA"
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        readiness["keyboardInput"] = copy.deepcopy(keyboard)

        with self.assertRaisesRegex(M0Error, "queued record 2 code mismatch"):
            self.assert_valid(result, versions)

    def test_inner_key_trace_requires_key_a_then_key_b(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        key_trace = page_probe["keyEventTrace"]
        assert isinstance(key_trace, list)
        key_b_up = key_trace[3]
        assert isinstance(key_b_up, dict)
        key_b_up["key"] = "a"

        with self.assertRaisesRegex(M0Error, "inner keyEventTrace"):
            self.assert_valid(result, versions)

    def test_two_trusted_insert_text_pairs_are_required(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        text_trace = page_probe["textInputTrace"]
        assert isinstance(text_trace, list)
        second_input = text_trace[3]
        assert isinstance(second_input, dict)
        second_input["data"] = "a"

        with self.assertRaisesRegex(M0Error, "inner textInputTrace"):
            self.assert_valid(result, versions)

    def test_untrusted_beforeinput_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        text_trace = page_probe["textInputTrace"]
        assert isinstance(text_trace, list)
        first_beforeinput = text_trace[0]
        assert isinstance(first_beforeinput, dict)
        first_beforeinput["trusted"] = False

        with self.assertRaisesRegex(M0Error, "inner textInputTrace"):
            self.assert_valid(result, versions)

    def test_text_input_trace_requires_explicit_non_composing_state(
        self,
    ) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        text_trace = page_probe["textInputTrace"]
        assert isinstance(text_trace, list)
        second_beforeinput = text_trace[2]
        assert isinstance(second_beforeinput, dict)
        second_beforeinput["isComposing"] = True

        with self.assertRaisesRegex(M0Error, "inner textInputTrace"):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        text_trace = page_probe["textInputTrace"]
        assert isinstance(text_trace, list)
        first_input = text_trace[1]
        assert isinstance(first_input, dict)
        first_input.pop("isComposing")

        with self.assertRaisesRegex(M0Error, "inner textInputTrace"):
            self.assert_valid(result, versions)

    def test_key_a_stage_proof_is_required_and_exact(self) -> None:
        result, versions = passing_result()
        result.pop("keyAProof")

        with self.assertRaisesRegex(M0Error, "KeyA-stage proof"):
            self.assert_valid(result, versions)

        for field, invalid_value in (
            ("outerTraceExact", False),
            ("innerTraceExact", False),
            ("textTraceExact", False),
            ("noComposition", False),
            ("value", "ab"),
            ("selectionStart", 2),
            ("selectionEnd", 2),
            ("frameAfterKeyADown", False),
        ):
            with self.subTest(field=field):
                result, versions = passing_result()
                key_a_proof = result["keyAProof"]
                assert isinstance(key_a_proof, dict)
                key_a_proof[field] = invalid_value

                with self.assertRaisesRegex(M0Error, "KeyA-stage proof"):
                    self.assert_valid(result, versions)

    def test_final_value_and_selection_require_both_characters(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        page_probe["value"] = "a"

        with self.assertRaisesRegex(M0Error, "value mismatch"):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        page_probe["selectionEnd"] = 1

        with self.assertRaisesRegex(M0Error, "selectionEnd mismatch"):
            self.assert_valid(result, versions)

    def test_composition_activity_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        composition = page_probe["textInputEvents"]
        assert isinstance(composition, dict)
        composition["compositionstartCount"] = 1

        with self.assertRaisesRegex(
            M0Error, "compositionstartCount mismatch"
        ):
            self.assert_valid(result, versions)

    def test_pointer_activation_and_key_release_are_required(self) -> None:
        result, versions = passing_result()
        keyboard = result["keyboardInput"]
        assert isinstance(keyboard, dict)
        keyboard["activated"] = False

        with self.assertRaisesRegex(M0Error, "not activated by pointer"):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        keyboard = result["keyboardInput"]
        assert isinstance(keyboard, dict)
        keyboard["pressedCodes"] = ["KeyB"]

        with self.assertRaisesRegex(M0Error, "key state was not released"):
            self.assert_valid(result, versions)

    def test_four_accepted_keyboard_records_are_required(self) -> None:
        result, versions = passing_result()
        keyboard = result["keyboardInput"]
        assert isinstance(keyboard, dict)
        keyboard["receivedCount"] = 3
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        readiness["keyboardInput"] = copy.deepcopy(keyboard)

        with self.assertRaisesRegex(
            M0Error, "keyboard receivedCount must be at least 4"
        ):
            self.assert_valid(result, versions)

    def test_no_later_compositor_frame_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        frame = readiness["frame"]
        assert isinstance(frame, dict)
        frame["id"] = 8

        with self.assertRaisesRegex(M0Error, "no compositor frame"):
            self.assert_valid(result, versions)

    def test_mismatched_readiness_keyboard_evidence_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        readiness["keyboardInput"] = copy.deepcopy(result["keyboardInput"])
        readiness_keyboard = readiness["keyboardInput"]
        assert isinstance(readiness_keyboard, dict)
        readiness_keyboard["queuedCount"] = 3

        with self.assertRaisesRegex(
            M0Error, "keyboard evidence differs from readiness evidence"
        ):
            self.assert_valid(result, versions)


class RecordingDevToolsClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    def call(
        self, method: str, params: dict[str, object] | None = None
    ) -> dict[str, object]:
        self.calls.append((method, params))
        return {}


class M4PrintableKeyDevToolsClientTest(unittest.TestCase):
    def test_raw_key_a_and_b_use_key_down_and_key_up_without_text(self) -> None:
        recording = RecordingDevToolsClient()
        client = object.__new__(m4_cdp.DevToolsClient)
        client.call = recording.call  # type: ignore[method-assign]

        client.dispatch_key_a()
        client.dispatch_key_b()

        self.assertEqual(
            recording.calls,
            [
                (
                    "Input.dispatchKeyEvent",
                    {
                        "type": "rawKeyDown",
                        "code": "KeyA",
                        "key": "a",
                        "windowsVirtualKeyCode": 65,
                        "modifiers": 0,
                    },
                ),
                (
                    "Input.dispatchKeyEvent",
                    {
                        "type": "keyUp",
                        "code": "KeyA",
                        "key": "a",
                        "windowsVirtualKeyCode": 65,
                        "modifiers": 0,
                    },
                ),
                (
                    "Input.dispatchKeyEvent",
                    {
                        "type": "rawKeyDown",
                        "code": "KeyB",
                        "key": "b",
                        "windowsVirtualKeyCode": 66,
                        "modifiers": 0,
                    },
                ),
                (
                    "Input.dispatchKeyEvent",
                    {
                        "type": "keyUp",
                        "code": "KeyB",
                        "key": "b",
                        "windowsVirtualKeyCode": 66,
                        "modifiers": 0,
                    },
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
