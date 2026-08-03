#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused validation tests for the bounded M4 physical Backspace smoke."""

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
import run_m4_ozone_smoke


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
        key_record("down", "Backspace", "Backspace", 3, 8),
        key_record("up", "Backspace", "Backspace", 4, 8),
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
    key_event_trace = [
        {
            "type": "keydown",
            "trusted": True,
            "code": "KeyA",
            "key": "a",
            "repeat": False,
            "isComposing": False,
            "defaultPrevented": False,
            "targetId": "editable-target",
        },
        {
            "type": "keyup",
            "trusted": True,
            "code": "KeyA",
            "key": "a",
            "repeat": False,
            "isComposing": False,
            "defaultPrevented": False,
            "targetId": "editable-target",
        },
        {
            "type": "keydown",
            "trusted": True,
            "code": "Backspace",
            "key": "Backspace",
            "repeat": False,
            "isComposing": False,
            "defaultPrevented": False,
            "targetId": "editable-target",
        },
        {
            "type": "keyup",
            "trusted": True,
            "code": "Backspace",
            "key": "Backspace",
            "repeat": False,
            "isComposing": False,
            "defaultPrevented": False,
            "targetId": "editable-target",
        },
    ]
    text_input_trace = [
        {
            "type": "beforeinput",
            "trusted": True,
            "inputType": "insertText",
            "data": "a",
            "isComposing": False,
            "targetId": "editable-target",
        },
        {
            "type": "input",
            "trusted": True,
            "inputType": "insertText",
            "data": "a",
            "isComposing": False,
            "targetId": "editable-target",
        },
        {
            "type": "beforeinput",
            "trusted": True,
            "inputType": "deleteContentBackward",
            "data": None,
            "isComposing": False,
            "targetId": "editable-target",
        },
        {
            "type": "input",
            "trusted": True,
            "inputType": "deleteContentBackward",
            "data": None,
            "isComposing": False,
            "targetId": "editable-target",
        },
    ]
    page_probe = {
        "fontReady": True,
        "protocol": 1,
        "fixture": "chromium-wasm-m4-ozone-backspace-v1",
        "ready": True,
        "targetCenterX": 388,
        "targetCenterY": 215,
        "timerTicks": 3,
        "activeElementId": "editable-target",
        "activationCount": 1,
        "clickTrusted": True,
        "focusCount": 1,
        "focusTrusted": True,
        "value": "",
        "selectionStart": 0,
        "selectionEnd": 0,
        "resultText": "TEXT INSERTED THEN DELETED",
        "keyEventTrace": key_event_trace,
        "textInputTrace": text_input_trace,
        "compositionEventCounts": {
            "compositionstart": 0,
            "compositionupdate": 0,
            "compositionend": 0,
        },
    }
    result: dict[str, object] = {
        "protocol": 1,
        "case": "ozone_backspace_m4",
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
                "shutdown:complete",
            ],
            "stdout": [],
            "stderr": [],
        },
        "failedChecks": [],
        "error": None,
    }
    return result, versions


class M4BackspaceResultValidationTest(unittest.TestCase):
    def assert_valid(
        self, result: dict[str, object], versions: dict[str, str]
    ) -> None:
        self.assertIsNone(
            m3_content_server.validate_m4_backspace_result(
                result, expected_versions=versions
            )
        )

    def test_complete_backspace_contract_is_accepted(self) -> None:
        result, versions = passing_result()

        self.assert_valid(result, versions)

    def test_untrusted_inner_insert_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        text_trace = page_probe["textInputTrace"]
        assert isinstance(text_trace, list)
        record = text_trace[0]
        assert isinstance(record, dict)
        record["trusted"] = False

        with self.assertRaisesRegex(M0Error, "text trace 0 trusted mismatch"):
            self.assert_valid(result, versions)

    def test_delete_must_follow_insert_with_null_data(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        text_trace = page_probe["textInputTrace"]
        assert isinstance(text_trace, list)
        record = text_trace[2]
        assert isinstance(record, dict)
        record["data"] = "a"

        with self.assertRaisesRegex(M0Error, "text trace 2 data mismatch"):
            self.assert_valid(result, versions)

    def test_outer_key_records_must_be_exact_and_ordered(self) -> None:
        result, versions = passing_result()
        keyboard = result["keyboardInput"]
        assert isinstance(keyboard, dict)
        records = keyboard["queuedRecords"]
        assert isinstance(records, list)
        record = records[2]
        assert isinstance(record, dict)
        record["code"] = "KeyA"
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        readiness["keyboardInput"] = copy.deepcopy(keyboard)

        with self.assertRaisesRegex(M0Error, "queued key trace 2 code mismatch"):
            self.assert_valid(result, versions)

    def test_outer_key_sequence_must_increase(self) -> None:
        result, versions = passing_result()
        keyboard = result["keyboardInput"]
        assert isinstance(keyboard, dict)
        records = keyboard["queuedRecords"]
        assert isinstance(records, list)
        record = records[3]
        assert isinstance(record, dict)
        record["sequence"] = 3
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        readiness["keyboardInput"] = copy.deepcopy(keyboard)

        with self.assertRaisesRegex(M0Error, "sequence"):
            self.assert_valid(result, versions)

    def test_final_empty_value_and_collapsed_selection_are_required(self) -> None:
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
        composition = page_probe["compositionEventCounts"]
        assert isinstance(composition, dict)
        composition["compositionstart"] = 1

        with self.assertRaisesRegex(M0Error, "compositionstart count is not zero"):
            self.assert_valid(result, versions)

    def test_frame_dimensions_require_exact_integer_types(self) -> None:
        for field, value in (("width", 800.0), ("height", 600.0)):
            with self.subTest(field=field):
                result, versions = passing_result()
                readiness = result["readiness"]
                assert isinstance(readiness, dict)
                frame = readiness["frame"]
                assert isinstance(frame, dict)
                frame[field] = value

                with self.assertRaisesRegex(
                    M0Error, "frame dimensions do not match the canvas"
                ):
                    self.assert_valid(result, versions)

    def test_last_pointer_boolean_fields_require_exact_types(self) -> None:
        for field in ("trusted", "queued", "canvasFocused"):
            with self.subTest(field=field):
                result, versions = passing_result()
                pointer_input = result["pointerInput"]
                assert isinstance(pointer_input, dict)
                last_pointer = pointer_input["lastQueued"]
                assert isinstance(last_pointer, dict)
                last_pointer[field] = 1

                with self.assertRaisesRegex(
                    M0Error, f"queued pointer {field} mismatch"
                ):
                    self.assert_valid(result, versions)

    def test_readiness_evidence_requires_exact_json_types(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        pointer_input = result["pointerInput"]
        assert isinstance(pointer_input, dict)
        readiness_pointer = copy.deepcopy(pointer_input)
        readiness["pointerInput"] = readiness_pointer
        last_pointer = readiness_pointer["lastQueued"]
        assert isinstance(last_pointer, dict)
        last_pointer["trusted"] = 1

        with self.assertRaisesRegex(
            M0Error, "pointer evidence differs from readiness evidence"
        ):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        keyboard_input = result["keyboardInput"]
        assert isinstance(keyboard_input, dict)
        readiness_keyboard = copy.deepcopy(keyboard_input)
        readiness["keyboardInput"] = readiness_keyboard
        records = readiness_keyboard["queuedRecords"]
        assert isinstance(records, list)
        record = records[0]
        assert isinstance(record, dict)
        record["queued"] = 1

        with self.assertRaisesRegex(
            M0Error, "keyboard evidence differs from readiness evidence"
        ):
            self.assert_valid(result, versions)

    def test_pointer_counts_must_be_coherent(self) -> None:
        result, versions = passing_result()
        pointer_input = result["pointerInput"]
        assert isinstance(pointer_input, dict)
        pointer_input["trustedCount"] = 4

        with self.assertRaisesRegex(
            M0Error, "trusted pointer count exceeds received pointer records"
        ):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        pointer_input = result["pointerInput"]
        assert isinstance(pointer_input, dict)
        pointer_input["receivedCount"] = 4
        pointer_input["queuedCount"] = 4

        with self.assertRaisesRegex(
            M0Error, "queued pointer count exceeds trusted pointer records"
        ):
            self.assert_valid(result, versions)

    def test_last_pointer_sequence_must_be_a_safe_positive_integer(self) -> None:
        for value in (None, 0, 3.0, 1 << 53):
            with self.subTest(value=value):
                result, versions = passing_result()
                pointer_input = result["pointerInput"]
                assert isinstance(pointer_input, dict)
                last_pointer = pointer_input["lastQueued"]
                assert isinstance(last_pointer, dict)
                if value is None:
                    del last_pointer["sequence"]
                else:
                    last_pointer["sequence"] = value

                with self.assertRaisesRegex(
                    M0Error, "queued pointer sequence"
                ):
                    self.assert_valid(result, versions)

    def test_modifier_map_requires_exact_false_booleans(self) -> None:
        for field in ("alt", "control", "meta", "shift"):
            with self.subTest(field=field):
                result, versions = passing_result()
                keyboard_input = result["keyboardInput"]
                assert isinstance(keyboard_input, dict)
                records = keyboard_input["queuedRecords"]
                assert isinstance(records, list)
                record = records[0]
                assert isinstance(record, dict)
                modifiers = record["modifiers"]
                assert isinstance(modifiers, dict)
                modifiers[field] = 0

                with self.assertRaisesRegex(
                    M0Error, "queued key trace 0 modifiers are not all false"
                ):
                    self.assert_valid(result, versions)

    def test_log_entries_must_be_exact_strings(self) -> None:
        for stream in ("host", "stdout", "stderr"):
            with self.subTest(stream=stream):
                result, versions = passing_result()
                logs = result["logs"]
                assert isinstance(logs, dict)
                entries = logs[stream]
                assert isinstance(entries, list)
                if stream == "host":
                    entries[0] = {
                        "message": "m4:pointer:listeners-attached"
                    }
                else:
                    entries.append({"message": "diagnostic"})

                with self.assertRaisesRegex(
                    M0Error, f"{stream} log entry 0 must be a string"
                ):
                    self.assert_valid(result, versions)

    def test_later_frame_after_backspace_is_required(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        frame = readiness["frame"]
        assert isinstance(frame, dict)
        frame["id"] = 8

        with self.assertRaisesRegex(M0Error, "no compositor frame after Backspace"):
            self.assert_valid(result, versions)


class RecordingDevToolsClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    def call(
        self, method: str, params: dict[str, object] | None = None
    ) -> dict[str, object]:
        self.calls.append((method, params))
        return {}


class M4BackspaceDevToolsClientTest(unittest.TestCase):
    def test_raw_key_a_then_backspace_use_no_text_payload(self) -> None:
        recording = RecordingDevToolsClient()
        client = object.__new__(m4_cdp.DevToolsClient)
        client.call = recording.call  # type: ignore[method-assign]

        client.dispatch_key_a()
        client.dispatch_backspace()

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
                        "code": "Backspace",
                        "key": "Backspace",
                        "windowsVirtualKeyCode": 8,
                        "modifiers": 0,
                    },
                ),
                (
                    "Input.dispatchKeyEvent",
                    {
                        "type": "keyUp",
                        "code": "Backspace",
                        "key": "Backspace",
                        "windowsVirtualKeyCode": 8,
                        "modifiers": 0,
                    },
                ),
            ],
        )
        self.assertNotIn(
            "text",
            {key for _, params in recording.calls for key in (params or {})},
        )


class M4BackspaceKeyAStageTest(unittest.TestCase):
    def passing_state(self) -> dict[str, object]:
        return {
            "state": "awaiting-dom-backspace",
            "keyAProof": {
                "outerTraceExact": True,
                "innerTraceExact": True,
                "textTraceExact": True,
                "noComposition": True,
                "frameAfterKeyADown": True,
                "value": "a",
                "selectionStart": 1,
                "selectionEnd": 1,
            },
        }

    def test_key_a_stage_requires_the_frozen_blink_edit_proof(self) -> None:
        run_m4_ozone_smoke.validate_backspace_key_a_stage(
            self.passing_state()
        )

    def test_key_a_stage_rejects_missing_or_incomplete_proof(self) -> None:
        with self.assertRaisesRegex(M0Error, "did not publish a proof"):
            run_m4_ozone_smoke.validate_backspace_key_a_stage({})

        state = self.passing_state()
        proof = state["keyAProof"]
        assert isinstance(proof, dict)
        proof["textTraceExact"] = False
        with self.assertRaisesRegex(M0Error, "textTraceExact"):
            run_m4_ozone_smoke.validate_backspace_key_a_stage(state)

    def test_key_a_stage_requires_the_inserted_value_and_selection(self) -> None:
        state = self.passing_state()
        proof = state["keyAProof"]
        assert isinstance(proof, dict)
        proof["value"] = ""
        with self.assertRaisesRegex(M0Error, "value 'a'"):
            run_m4_ozone_smoke.validate_backspace_key_a_stage(state)

        state = self.passing_state()
        proof = state["keyAProof"]
        assert isinstance(proof, dict)
        proof["selectionEnd"] = True
        with self.assertRaisesRegex(M0Error, "selectionEnd"):
            run_m4_ozone_smoke.validate_backspace_key_a_stage(state)


if __name__ == "__main__":
    unittest.main()
