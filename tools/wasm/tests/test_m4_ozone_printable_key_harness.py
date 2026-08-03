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


def key_record(event_type: str, frame_id: int) -> dict[str, object]:
    return {
        "type": event_type,
        "code": "KeyA",
        "key": "a",
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
        "sequence": 3 if event_type == "down" else 4,
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
    keyboard_input = {
        "enabled": True,
        "activated": True,
        "receivedCount": 2,
        "trustedCount": 2,
        "queuedCount": 2,
        "pressedCodes": [],
        "lastQueuedDown": key_record("down", 7),
        "lastQueuedUp": key_record("up", 7),
    }
    page_probe = {
        "fontReady": True,
        "protocol": 1,
        "fixture": "chromium-wasm-m4-ozone-printable-key-v1",
        "ready": True,
        "targetCenterX": 388,
        "targetCenterY": 215,
        "timerTicks": 3,
        "activeElementId": "editable-target",
        "activationCount": 1,
        "clickTrusted": True,
        "focusCount": 1,
        "focusTrusted": True,
        "value": "a",
        "selectionStart": 1,
        "selectionEnd": 1,
        "resultText": "TEXT INPUT RECEIVED",
        "keyEvents": {
            "keydownCount": 1,
            "keyupCount": 1,
            "keydownTrusted": True,
            "keyupTrusted": True,
            "keydownCode": "KeyA",
            "keyupCode": "KeyA",
            "keydownKey": "a",
            "keyupKey": "a",
            "keydownRepeat": False,
            "keyupRepeat": False,
            "keydownComposing": False,
            "keyupComposing": False,
            "keydownDefaultPrevented": False,
            "keyupDefaultPrevented": False,
            "keydownTargetId": "editable-target",
            "keyupTargetId": "editable-target",
        },
        "textInputEvents": {
            "beforeinputCount": 1,
            "inputCount": 1,
            "beforeinputTrusted": True,
            "inputTrusted": True,
            "beforeinputInputType": "insertText",
            "inputInputType": "insertText",
            "beforeinputData": "a",
            "inputData": "a",
            "beforeinputTargetId": "editable-target",
            "inputTargetId": "editable-target",
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
                "id": 8,
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
        key_events = page_probe["keyEvents"]
        assert isinstance(key_events, dict)
        key_events["keydownTrusted"] = False

        with self.assertRaisesRegex(M0Error, "keydownTrusted mismatch"):
            self.assert_valid(result, versions)

    def test_untrusted_outer_key_event_is_rejected(self) -> None:
        result, versions = passing_result()
        keyboard = result["keyboardInput"]
        assert isinstance(keyboard, dict)
        key_down = keyboard["lastQueuedDown"]
        assert isinstance(key_down, dict)
        key_down["trusted"] = False

        with self.assertRaisesRegex(M0Error, "trusted mismatch"):
            self.assert_valid(result, versions)

    def test_non_printable_code_is_rejected(self) -> None:
        result, versions = passing_result()
        keyboard = result["keyboardInput"]
        assert isinstance(keyboard, dict)
        key_down = keyboard["lastQueuedDown"]
        assert isinstance(key_down, dict)
        key_down["code"] = "ArrowDown"

        with self.assertRaisesRegex(M0Error, "code mismatch"):
            self.assert_valid(result, versions)

    def test_wrong_inner_text_data_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        text_events = page_probe["textInputEvents"]
        assert isinstance(text_events, dict)
        text_events["inputData"] = "b"

        with self.assertRaisesRegex(M0Error, "inputData mismatch"):
            self.assert_valid(result, versions)

    def test_untrusted_beforeinput_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        text_events = page_probe["textInputEvents"]
        assert isinstance(text_events, dict)
        text_events["beforeinputTrusted"] = False

        with self.assertRaisesRegex(M0Error, "beforeinputTrusted mismatch"):
            self.assert_valid(result, versions)

    def test_missing_input_event_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        text_events = page_probe["textInputEvents"]
        assert isinstance(text_events, dict)
        text_events["inputCount"] = 0

        with self.assertRaisesRegex(M0Error, "inputCount mismatch"):
            self.assert_valid(result, versions)

    def test_wrong_value_or_selection_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        page_probe["value"] = ""

        with self.assertRaisesRegex(M0Error, "value mismatch"):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        page_probe["selectionEnd"] = 0

        with self.assertRaisesRegex(M0Error, "selectionEnd mismatch"):
            self.assert_valid(result, versions)

    def test_composition_activity_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        text_events = page_probe["textInputEvents"]
        assert isinstance(text_events, dict)
        text_events["compositionstartCount"] = 1

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
        keyboard["pressedCodes"] = ["KeyA"]

        with self.assertRaisesRegex(M0Error, "key state was not released"):
            self.assert_valid(result, versions)

    def test_extra_accepted_keyboard_record_is_rejected(self) -> None:
        result, versions = passing_result()
        keyboard = result["keyboardInput"]
        assert isinstance(keyboard, dict)
        keyboard["receivedCount"] = 3
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        readiness["keyboardInput"] = copy.deepcopy(keyboard)

        with self.assertRaisesRegex(
            M0Error, "keyboard receivedCount is not exactly two"
        ):
            self.assert_valid(result, versions)

    def test_no_later_compositor_frame_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        frame = readiness["frame"]
        assert isinstance(frame, dict)
        frame["id"] = 7

        with self.assertRaisesRegex(M0Error, "no compositor frame"):
            self.assert_valid(result, versions)

    def test_mismatched_readiness_keyboard_evidence_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        readiness["keyboardInput"] = copy.deepcopy(result["keyboardInput"])
        readiness_keyboard = readiness["keyboardInput"]
        assert isinstance(readiness_keyboard, dict)
        readiness_keyboard["queuedCount"] = 1

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
    def test_raw_key_a_uses_key_down_and_key_up_without_text(self) -> None:
        recording = RecordingDevToolsClient()
        client = object.__new__(m4_cdp.DevToolsClient)
        client.call = recording.call  # type: ignore[method-assign]

        client.dispatch_key_a()

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
            ],
        )


if __name__ == "__main__":
    unittest.main()
