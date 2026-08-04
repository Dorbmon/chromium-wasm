#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused validation tests for retained M4 Ozone/Blink focus."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import m3_content_server


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
        "sequence": sequence,
        "type": event_type,
        "trusted": True,
        "queued": True,
        "canvasFocused": True,
        "x": x,
        "y": y,
        "button": button,
        "buttons": buttons,
        "frameIdBefore": frame_id,
    }


def key_record(event_type: str, sequence: int, frame_id: int) -> dict[str, object]:
    return {
        "sequence": sequence,
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
        "frameIdBefore": frame_id,
        "canvasFocused": True,
        "pointerActivated": True,
        "defaultPrevented": True,
    }


def ozone_focus_report(sequence: int) -> dict[str, object]:
    return {
        "sequence": sequence,
        "keyboardTargetPresent": True,
        "active": True,
    }


def passing_result() -> tuple[dict[str, object], dict[str, str]]:
    versions = {
        "chromium": "chromium-revision",
        "v8": "v8-revision",
        "emscripten": "emscripten-revision",
        "port": "port-revision",
    }
    editable_x, editable_y = 390, 214
    retention_x, retention_y = 390, 326
    queued_pointer = [
        pointer_record("move", editable_x, editable_y, -1, 0, 1, 7),
        pointer_record("down", editable_x, editable_y, 0, 1, 2, 7),
        pointer_record("up", editable_x, editable_y, 0, 0, 3, 8),
        pointer_record("move", retention_x, retention_y, -1, 0, 4, 9),
    ]
    pointer_input = {
        "enabled": True,
        "receivedCount": 4,
        "trustedCount": 4,
        "queuedCount": 4,
        "queuedRecords": queued_pointer,
        "lastQueued": queued_pointer[-1],
    }
    queued_keys = [key_record("down", 1, 11), key_record("up", 2, 11)]
    keyboard_input = {
        "enabled": True,
        "activated": True,
        "receivedCount": 2,
        "trustedCount": 2,
        "queuedCount": 2,
        "queuedRecords": queued_keys,
        "pressedCodes": [],
        "lastQueuedDown": queued_keys[0],
        "lastQueuedUp": queued_keys[1],
    }
    focus_input = {
        "enabled": True,
        "hostWindowActive": True,
        "receivedCount": 1,
        "trustedCount": 1,
        "queuedCount": 1,
        "lastQueuedFocusLoss": None,
    }
    ozone_focus_reports = [
        ozone_focus_report(1),
        ozone_focus_report(2),
    ]
    ozone_focus_state = ozone_focus_reports[-1]
    retention_reports: list[dict[str, object]] = []
    retention = {
        "editableActivationCount": 1,
        "editableClickTrusted": True,
        "editableFocusCount": 1,
        "editableFocusTrusted": True,
        "editableBlurCount": 0,
        "windowBlurCount": 0,
        "windowBlurTrusted": False,
        "retentionPointerMoveCount": 1,
        "retentionPointerMoveTrusted": True,
        "keyEventTrace": [
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
        ],
        "textInputTrace": [
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
        ],
        "compositionEventCounts": {
            "compositionstart": 0,
            "compositionupdate": 0,
            "compositionend": 0,
        },
        "value": "a",
        "selectionStart": 1,
        "selectionEnd": 1,
        "resultText": "FOCUS RETAINED",
    }
    page_probe = {
        "fontReady": True,
        "protocol": 1,
        "fixture": "chromium-wasm-m4-ozone-focus-retention-v1",
        "ready": True,
        "timerTicks": 3,
        "editableTargetX": editable_x,
        "editableTargetY": editable_y,
        "retentionTargetX": retention_x,
        "retentionTargetY": retention_y,
        "activeElementId": "editable-target",
        "documentHasFocus": True,
        "focusRetention": retention,
    }
    readiness = {
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
            "id": 12,
            "timestampMs": 1180,
            "width": 800,
            "height": 600,
        },
        "pageProbe": page_probe,
        "pointerInput": pointer_input,
        "keyboardInput": keyboard_input,
        "focusInput": focus_input,
        "ozoneFocusState": ozone_focus_state,
        "ozoneFocusReports": ozone_focus_reports,
    }
    result: dict[str, object] = {
        "protocol": 1,
        "case": "ozone_focus_retention_m4",
        "status": "pass",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "versions": versions,
        "readiness": readiness,
        "editableTargetX": editable_x,
        "editableTargetY": editable_y,
        "retentionTargetX": retention_x,
        "retentionTargetY": retention_y,
        "retentionFocusSequenceBefore": 2,
        "retentionFocusSequenceAfter": 2,
        "retentionOzoneFocusReports": retention_reports,
        "pointerInput": pointer_input,
        "keyboardInput": keyboard_input,
        "focusInput": focus_input,
        "ozoneFocusState": ozone_focus_state,
        "focusRetentionProof": {
            "pointerTraceExact": True,
            "nativeFocusStateStable": True,
            "blinkFocusRetained": True,
            "keyOuterTraceExact": True,
            "keyInnerTraceExact": True,
            "textTraceExact": True,
            "noComposition": True,
            "frameAfterKeyDown": True,
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
                "m4:pointer:move:queued",
                "m4:keyboard:down:queued",
                "m4:keyboard:up:queued",
                "m4:focus:shutdown:deactivate-queued",
                "shutdown:complete",
            ],
            "stdout": [],
            "stderr": [],
        },
        "failedChecks": [],
        "error": None,
    }
    return result, versions


class M4FocusRetentionResultValidationTest(unittest.TestCase):
    def assert_valid(
        self, result: dict[str, object], versions: dict[str, str]
    ) -> None:
        self.assertIsNone(
            m3_content_server.validate_m4_focus_retention_result(
                result, expected_versions=versions
            )
        )

    def test_complete_retention_contract_accepts_shutdown_deactivation(self) -> None:
        result, versions = passing_result()

        self.assert_valid(result, versions)

    def test_any_post_move_ozone_focus_report_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        reports = readiness["ozoneFocusReports"]
        assert isinstance(reports, list)
        reports.append(ozone_focus_report(3))

        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

    def test_changed_ozone_focus_sequence_is_rejected(self) -> None:
        result, versions = passing_result()
        result["retentionFocusSequenceAfter"] = 3

        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

    def test_missing_or_untrusted_retention_move_is_rejected(self) -> None:
        for field, value in (
            ("retentionPointerMoveCount", 0),
            ("retentionPointerMoveTrusted", False),
        ):
            with self.subTest(field=field):
                result, versions = passing_result()
                readiness = result["readiness"]
                assert isinstance(readiness, dict)
                page_probe = readiness["pageProbe"]
                assert isinstance(page_probe, dict)
                retention = page_probe["focusRetention"]
                assert isinstance(retention, dict)
                retention[field] = value

                with self.assertRaisesRegex(M0Error, f"{field} mismatch"):
                    self.assert_valid(result, versions)

    def test_blink_blur_or_focus_count_change_is_rejected(self) -> None:
        for field, value in (
            ("editableBlurCount", 1),
            ("windowBlurCount", 1),
            ("editableFocusCount", 2),
        ):
            with self.subTest(field=field):
                result, versions = passing_result()
                readiness = result["readiness"]
                assert isinstance(readiness, dict)
                page_probe = readiness["pageProbe"]
                assert isinstance(page_probe, dict)
                retention = page_probe["focusRetention"]
                assert isinstance(retention, dict)
                retention[field] = value

                with self.assertRaisesRegex(M0Error, f"{field} mismatch"):
                    self.assert_valid(result, versions)

    def test_keyboard_activation_must_survive_retention(self) -> None:
        result, versions = passing_result()
        keyboard = result["keyboardInput"]
        assert isinstance(keyboard, dict)
        keyboard["activated"] = False

        with self.assertRaisesRegex(M0Error, "was not pointer activated"):
            self.assert_valid(result, versions)

    def test_second_focus_activation_is_rejected(self) -> None:
        result, versions = passing_result()
        focus = result["focusInput"]
        assert isinstance(focus, dict)
        for field in ("receivedCount", "trustedCount", "queuedCount"):
            focus[field] = 2

        with self.assertRaisesRegex(M0Error, "focus receivedCount mismatch"):
            self.assert_valid(result, versions)

    def test_extra_pointer_record_is_rejected(self) -> None:
        result, versions = passing_result()
        pointer = result["pointerInput"]
        assert isinstance(pointer, dict)
        records = pointer["queuedRecords"]
        assert isinstance(records, list)
        records.append(pointer_record("move", 390, 326, -1, 0, 5, 10))
        for field in ("receivedCount", "trustedCount", "queuedCount"):
            pointer[field] = 5

        with self.assertRaisesRegex(M0Error, "pointer receivedCount is not exactly four"):
            self.assert_valid(result, versions)

    def test_runtime_focus_loss_is_rejected_but_shutdown_is_allowed(self) -> None:
        result, versions = passing_result()
        logs = result["logs"]
        assert isinstance(logs, dict)
        host_logs = logs["host"]
        assert isinstance(host_logs, list)
        host_logs.append("m4:focus:canvas-blur:deactivate-queued")

        with self.assertRaisesRegex(M0Error, "for canvas-blur"):
            self.assert_valid(result, versions)


if __name__ == "__main__":
    unittest.main()
