#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused unit tests for the M4 trusted host-focus-loss harness."""

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


def key_down() -> dict[str, object]:
    return {
        "type": "down",
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
        "sequence": 1,
        "frameIdBefore": 7,
        "canvasFocused": True,
        "pointerActivated": True,
        "defaultPrevented": True,
    }


def generated_key_up() -> dict[str, object]:
    return {
        "type": "up",
        "code": "ArrowDown",
        "key": "ArrowDown",
        "trusted": False,
        "queued": True,
        "generated": True,
        "trigger": "canvas-blur",
        "triggerTrusted": True,
        "relatedTargetId": "m4-focus-sink",
        "repeat": False,
        "isComposing": False,
        "modifiers": {
            "alt": False,
            "control": False,
            "meta": False,
            "shift": False,
        },
        "sequence": 2,
        "frameIdBefore": 12,
        "canvasFocused": False,
        "pointerActivated": False,
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
        "receivedCount": 4,
        "trustedCount": 4,
        "queuedCount": 3,
        "lastQueued": {
            "type": "up",
            "trusted": True,
            "queued": True,
            "canvasFocused": True,
            "sequence": 3,
            "x": 388,
            "y": 211,
            "frameIdBefore": 6,
        },
    }
    keyboard_input = {
        "enabled": True,
        "activated": False,
        "receivedCount": 2,
        "trustedCount": 1,
        "queuedCount": 2,
        "pressedCodes": [],
        "lastQueuedDown": key_down(),
        "lastQueuedUp": generated_key_up(),
    }
    focus_input = {
        "enabled": True,
        "hostWindowActive": False,
        "receivedCount": 2,
        "trustedCount": 2,
        "queuedCount": 2,
        "lastQueuedFocusLoss": {
            "sequence": 2,
            "type": "canvas-blur",
            "trusted": True,
            "queued": True,
            "frameIdBefore": 12,
            "canvasFocused": False,
            "relatedTargetId": "m4-focus-sink",
            "ozoneFocusReportSequenceBefore": 1,
        },
    }
    ozone_focus_state = {
        "sequence": 2,
        "keyboardTargetPresent": False,
        "active": False,
    }
    result: dict[str, object] = {
        "protocol": 1,
        "case": "ozone_focus_m4",
        "status": "pass",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": False,
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
                "id": 13,
                "timestampMs": 1180,
                "width": 800,
                "height": 600,
            },
            "pageProbe": {
                "fontReady": True,
                "protocol": 1,
                "fixture": "chromium-wasm-m4-ozone-focus-v1",
                "ready": True,
                "targetCenterX": 388,
                "targetCenterY": 211,
                "timerTicks": 3,
                "activeElementId": "focus-target",
                "activationCount": 1,
                "clickTrusted": True,
                "focusCount": 1,
                "focusTrusted": True,
                "windowBlurCount": 1,
                "windowBlurTrusted": True,
                "documentHasFocus": False,
                "scrollTop": 26,
                "resultText": "WINDOW BLURRED",
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
                    "keydownTargetId": "focus-target",
                    "keyupTargetId": "focus-target",
                },
            },
            "pointerInput": pointer_input,
            "keyboardInput": keyboard_input,
            "focusInput": focus_input,
            "ozoneFocusState": ozone_focus_state,
        },
        "pointerInput": pointer_input,
        "keyboardInput": keyboard_input,
        "focusInput": focus_input,
        "ozoneFocusState": ozone_focus_state,
        "focusSinkClick": {
            "trusted": True,
            "defaultPrevented": False,
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
                "m4:focus:listeners-attached",
                "m4:pointer:down:queued",
                "m4:keyboard:pointer-activation",
                "m4:focus:pointer-activation",
                "m4:pointer:up:queued",
                "m4:keyboard:down:queued",
                "m4:pointer:exit:no-unpressed-hover",
                "m4:keyboard:canvas-blur:release-queued",
                "m4:focus:canvas-blur:deactivate-queued",
                "ozone:focus:keyboard-target-absent:inactive",
                "shutdown:complete",
            ],
            "stdout": [],
            "stderr": [],
        },
        "failedChecks": [],
        "error": None,
    }
    return result, versions


class M4FocusResultValidationTest(unittest.TestCase):
    def assert_valid(
        self, result: dict[str, object], versions: dict[str, str]
    ) -> None:
        self.assertIsNone(
            m3_content_server.validate_m4_focus_result(
                result, expected_versions=versions
            )
        )

    def test_complete_focus_loss_contract_is_accepted(self) -> None:
        result, versions = passing_result()

        self.assert_valid(result, versions)

    def test_canvas_still_focused_is_rejected(self) -> None:
        result, versions = passing_result()
        result["canvasFocused"] = True

        with self.assertRaisesRegex(M0Error, "canvasFocused mismatch"):
            self.assert_valid(result, versions)

    def test_stale_host_window_state_is_rejected(self) -> None:
        result, versions = passing_result()
        focus = result["focusInput"]
        assert isinstance(focus, dict)
        focus["hostWindowActive"] = True

        with self.assertRaisesRegex(M0Error, "remained active"):
            self.assert_valid(result, versions)

    def test_actual_ozone_keyboard_target_is_rejected(self) -> None:
        result, versions = passing_result()
        ozone = result["ozoneFocusState"]
        assert isinstance(ozone, dict)
        ozone["keyboardTargetPresent"] = True

        with self.assertRaisesRegex(M0Error, "keyboard target"):
            self.assert_valid(result, versions)

    def test_stale_ozone_focus_report_is_rejected(self) -> None:
        result, versions = passing_result()
        ozone = result["ozoneFocusState"]
        assert isinstance(ozone, dict)
        ozone["sequence"] = 1

        with self.assertRaisesRegex(M0Error, "after deactivation"):
            self.assert_valid(result, versions)

    def test_untrusted_focus_sink_click_is_rejected(self) -> None:
        result, versions = passing_result()
        sink = result["focusSinkClick"]
        assert isinstance(sink, dict)
        sink["trusted"] = False

        with self.assertRaisesRegex(M0Error, "sink click was not trusted"):
            self.assert_valid(result, versions)

    def test_missing_generated_key_release_is_rejected(self) -> None:
        result, versions = passing_result()
        keyboard = result["keyboardInput"]
        assert isinstance(keyboard, dict)
        key_up = keyboard["lastQueuedUp"]
        assert isinstance(key_up, dict)
        key_up["generated"] = False

        with self.assertRaisesRegex(M0Error, "generated key up generated mismatch"):
            self.assert_valid(result, versions)

    def test_missing_inner_window_blur_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        page_probe["windowBlurCount"] = 0

        with self.assertRaisesRegex(M0Error, "window blur count"):
            self.assert_valid(result, versions)

    def test_inner_page_focus_retention_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        page_probe["documentHasFocus"] = True

        with self.assertRaisesRegex(M0Error, "documentHasFocus mismatch"):
            self.assert_valid(result, versions)

    def test_no_later_compositor_frame_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        frame = readiness["frame"]
        assert isinstance(frame, dict)
        frame["id"] = 12

        with self.assertRaisesRegex(M0Error, "no compositor frame after focus loss"):
            self.assert_valid(result, versions)

    def test_mismatched_readiness_focus_evidence_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        readiness["focusInput"] = copy.deepcopy(result["focusInput"])
        focus = readiness["focusInput"]
        assert isinstance(focus, dict)
        focus["queuedCount"] = 1

        with self.assertRaisesRegex(M0Error, "focus evidence differs"):
            self.assert_valid(result, versions)


class RecordingDevToolsClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    def call(
        self, method: str, params: dict[str, object] | None = None
    ) -> dict[str, object]:
        self.calls.append((method, params))
        return {}


class M4FocusDevToolsClientTest(unittest.TestCase):
    def test_held_arrow_down_uses_only_raw_key_down_without_text(self) -> None:
        recording = RecordingDevToolsClient()
        client = object.__new__(m4_cdp.DevToolsClient)
        client.call = recording.call  # type: ignore[method-assign]

        client.dispatch_arrow_down_down()

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
            ],
        )


class ValueDevToolsClient:
    def __init__(self, value: object) -> None:
        self.value = value

    def evaluate(self, expression: str) -> object:
        self.expression = expression
        return self.value


class M4FocusSinkGeometryTest(unittest.TestCase):
    def test_visible_focus_sink_center_is_used_for_real_cdp_click(self) -> None:
        client = ValueDevToolsClient(
            {
                "left": 700,
                "top": 12,
                "width": 88,
                "height": 32,
                "viewportWidth": 800,
                "viewportHeight": 600,
            }
        )

        self.assertEqual(
            run_m4_ozone_smoke.read_focus_sink_position(client),
            (744.0, 28.0),
        )
        self.assertIn("getBoundingClientRect", client.expression)

    def test_hidden_or_offscreen_focus_sink_is_rejected(self) -> None:
        cases = (
            ("missing", None, "geometry is unavailable"),
            (
                "offscreen",
                {
                    "left": 800,
                    "top": 12,
                    "width": 88,
                    "height": 32,
                    "viewportWidth": 800,
                    "viewportHeight": 600,
                },
                "center is outside the viewport",
            ),
            (
                "empty",
                {
                    "left": 700,
                    "top": 12,
                    "width": 0,
                    "height": 32,
                    "viewportWidth": 800,
                    "viewportHeight": 600,
                },
                "has nonpositive dimensions",
            ),
        )
        for name, value, error in cases:
            with self.subTest(name=name):
                with self.assertRaisesRegex(M0Error, error):
                    run_m4_ozone_smoke.read_focus_sink_position(
                        ValueDevToolsClient(value)
                    )


if __name__ == "__main__":
    unittest.main()
