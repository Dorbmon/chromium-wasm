#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused unit tests for the M4 trusted-keyboard host harness."""

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
        "code": "ArrowDown",
        "key": "ArrowDown",
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
        "receivedCount": 2,
        "trustedCount": 2,
        "queuedCount": 2,
        "lastQueued": {
            "type": "up",
            "trusted": True,
            "queued": True,
            "canvasFocused": True,
            "sequence": 2,
            "x": 285,
            "y": 229,
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
    result: dict[str, object] = {
        "protocol": 1,
        "case": "ozone_keyboard_m4",
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
            "pageProbe": {
                "fontReady": True,
                "protocol": 1,
                "fixture": "chromium-wasm-m4-ozone-keyboard-v1",
                "ready": True,
                "targetCenterX": 285,
                "targetCenterY": 229,
                "timerTicks": 3,
                "activeElementId": "keyboard-target",
                "activationCount": 1,
                "clickTrusted": True,
                "focusCount": 1,
                "focusTrusted": True,
                "scrollTop": 40,
                "resultText": "ARROW DOWN RECEIVED",
                "keyEvents": {
                    "keydownCount": 1,
                    "keyupCount": 1,
                    "keydownTrusted": True,
                    "keyupTrusted": True,
                    "keydownCode": "ArrowDown",
                    "keyupCode": "ArrowDown",
                    "keydownKey": "ArrowDown",
                    "keyupKey": "ArrowDown",
                    "keydownRepeat": False,
                    "keyupRepeat": False,
                    "keydownComposing": False,
                    "keyupComposing": False,
                    "keydownDefaultPrevented": False,
                    "keyupDefaultPrevented": False,
                    "keydownTargetId": "keyboard-target",
                    "keyupTargetId": "keyboard-target",
                },
                "textInputEvents": {
                    "beforeinputCount": 0,
                    "inputCount": 0,
                    "compositionstartCount": 0,
                    "compositionupdateCount": 0,
                    "compositionendCount": 0,
                },
            },
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


class M4KeyboardResultValidationTest(unittest.TestCase):
    def assert_valid(
        self, result: dict[str, object], versions: dict[str, str]
    ) -> None:
        self.assertIsNone(
            m3_content_server.validate_m4_keyboard_result(
                result, expected_versions=versions
            )
        )

    def test_complete_raw_navigation_key_contract_is_accepted(self) -> None:
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

        with self.assertRaisesRegex(
            M0Error, "last queued key down trusted mismatch"
        ):
            self.assert_valid(result, versions)

    def test_non_navigation_code_is_rejected(self) -> None:
        result, versions = passing_result()
        keyboard = result["keyboardInput"]
        assert isinstance(keyboard, dict)
        key_down = keyboard["lastQueuedDown"]
        assert isinstance(key_down, dict)
        key_down["code"] = "KeyA"

        with self.assertRaisesRegex(
            M0Error, "last queued key down code mismatch"
        ):
            self.assert_valid(result, versions)

    def test_pointer_activation_is_required(self) -> None:
        result, versions = passing_result()
        keyboard = result["keyboardInput"]
        assert isinstance(keyboard, dict)
        keyboard["activated"] = False

        with self.assertRaisesRegex(M0Error, "not activated by pointer input"):
            self.assert_valid(result, versions)

    def test_inner_focus_is_required(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        page_probe["activeElementId"] = None

        with self.assertRaisesRegex(M0Error, "activeElementId mismatch"):
            self.assert_valid(result, versions)

    def test_no_default_scroll_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        page_probe["scrollTop"] = 0

        with self.assertRaisesRegex(
            M0Error, "document scroll top must be at least 1"
        ):
            self.assert_valid(result, versions)

    def test_unexpected_text_or_composition_event_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        text_events = page_probe["textInputEvents"]
        assert isinstance(text_events, dict)
        text_events["compositionstartCount"] = 1

        with self.assertRaisesRegex(
            M0Error, "unexpected text or composition event"
        ):
            self.assert_valid(result, versions)

    def test_pressed_key_leak_is_rejected(self) -> None:
        result, versions = passing_result()
        keyboard = result["keyboardInput"]
        assert isinstance(keyboard, dict)
        keyboard["pressedCodes"] = ["ArrowDown"]

        with self.assertRaisesRegex(M0Error, "key state was not released"):
            self.assert_valid(result, versions)

    def test_no_later_compositor_frame_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        frame = readiness["frame"]
        assert isinstance(frame, dict)
        frame["id"] = 7

        with self.assertRaisesRegex(
            M0Error, "no compositor frame after raw key input"
        ):
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


class M4KeyboardDevToolsClientTest(unittest.TestCase):
    def test_raw_arrow_down_uses_key_down_and_key_up_without_text(self) -> None:
        recording = RecordingDevToolsClient()
        client = object.__new__(m4_cdp.DevToolsClient)
        client.call = recording.call  # type: ignore[method-assign]

        client.dispatch_arrow_down()

        self.assertEqual(
            recording.calls,
            [
                (
                    "Input.dispatchKeyEvent",
                    {
                        "type": "rawKeyDown",
                        "code": "ArrowDown",
                        "key": "ArrowDown",
                        "windowsVirtualKeyCode": 40,
                        "modifiers": 0,
                    },
                ),
                (
                    "Input.dispatchKeyEvent",
                    {
                        "type": "keyUp",
                        "code": "ArrowDown",
                        "key": "ArrowDown",
                        "windowsVirtualKeyCode": 40,
                        "modifiers": 0,
                    },
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
