#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused harness tests for the M4 process-local Ctrl copy/paste smoke."""

from __future__ import annotations

import copy
import io
import inspect
from pathlib import Path
import sys
from unittest import mock
import unittest
from urllib.parse import parse_qs, urlsplit


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import m3_content_server
import m4_cdp
import run_m4_ozone_smoke


VERSIONS = {
    "chromium": "chromium-revision",
    "v8": "v8-revision",
    "emscripten": "emscripten-revision",
    "port": "port-revision",
}

COORDINATES = {
    "copySourceTargetX": 220,
    "copySourceTargetY": 144,
    "copyDragStartX": 180,
    "copyDragStartY": 228,
    "copyDragMiddleX": 246,
    "copyDragMiddleY": 228,
    "copyDragEndX": 312,
    "copyDragEndY": 228,
    "decoyTargetX": 220,
    "decoyTargetY": 328,
    "decoyDragStartX": 180,
    "decoyDragStartY": 412,
    "decoyDragMiddleX": 246,
    "decoyDragMiddleY": 412,
    "decoyDragEndX": 312,
    "decoyDragEndY": 412,
    "primaryVerifyTargetX": 220,
    "primaryVerifyTargetY": 468,
    "pasteTargetX": 220,
    "pasteTargetY": 512,
}


def click_trace(prefix: str) -> tuple[tuple[str, int, int, int, int], ...]:
    return (
        ("move", COORDINATES[prefix + "X"], COORDINATES[prefix + "Y"], -1, 0),
        ("down", COORDINATES[prefix + "X"], COORDINATES[prefix + "Y"], 0, 1),
        ("up", COORDINATES[prefix + "X"], COORDINATES[prefix + "Y"], 0, 0),
    )


def middle_click_trace(
    prefix: str,
) -> tuple[tuple[str, int, int, int, int], ...]:
    return (
        ("move", COORDINATES[prefix + "X"], COORDINATES[prefix + "Y"], -1, 0),
        ("down", COORDINATES[prefix + "X"], COORDINATES[prefix + "Y"], 1, 4),
        ("up", COORDINATES[prefix + "X"], COORDINATES[prefix + "Y"], 1, 0),
    )


def drag_trace(prefix: str) -> tuple[tuple[str, int, int, int, int], ...]:
    return (
        (
            "move",
            COORDINATES[prefix + "StartX"],
            COORDINATES[prefix + "StartY"],
            -1,
            0,
        ),
        (
            "down",
            COORDINATES[prefix + "StartX"],
            COORDINATES[prefix + "StartY"],
            0,
            1,
        ),
        (
            "move",
            COORDINATES[prefix + "MiddleX"],
            COORDINATES[prefix + "MiddleY"],
            -1,
            1,
        ),
        (
            "move",
            COORDINATES[prefix + "EndX"],
            COORDINATES[prefix + "EndY"],
            -1,
            1,
        ),
        (
            "up",
            COORDINATES[prefix + "EndX"],
            COORDINATES[prefix + "EndY"],
            0,
            0,
        ),
    )


def pointer_trace() -> tuple[tuple[str, int, int, int, int], ...]:
    return (
        *click_trace("copySourceTarget"),
        *drag_trace("copyDrag"),
        *click_trace("decoyTarget"),
        *drag_trace("decoyDrag"),
        *click_trace("pasteTarget"),
        *middle_click_trace("primaryVerifyTarget"),
    )


def pointer_record(
    record: tuple[str, int, int, int, int], sequence: int
) -> dict[str, object]:
    event_type, x, y, button, buttons = record
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


def key_record(
    event_type: str,
    code: str,
    key: str,
    control: bool,
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
            "control": control,
            "meta": False,
            "shift": False,
        },
        "sequence": sequence,
        "frameIdBefore": frame_id,
        "canvasFocused": True,
        "pointerActivated": True,
        "defaultPrevented": True,
    }


def rejected_key_record(
    event_type: str, reason: str, sequence: int
) -> dict[str, object]:
    return {
        "type": event_type,
        "code": "KeyC",
        "key": "c",
        "trusted": True,
        "queued": False,
        "reason": reason,
        "repeat": False,
        "isComposing": False,
        "modifiers": {
            "alt": False,
            "control": False,
            "meta": False,
            "shift": False,
        },
        "sequence": sequence,
        "frameIdBefore": 12,
        "canvasFocused": True,
        "pointerActivated": True,
    }


def selection_activity(value: str) -> dict[str, object]:
    return {
        "count": 2,
        "trusted": True,
        "nonCollapsed": True,
        "trustedNonCollapsed": True,
        "selectCount": 1,
        "selectTrusted": True,
        "selectionChangeCount": 1,
        "selectionChangeTrusted": True,
        "lastNonCollapsed": {
            "trusted": True,
            "start": 0,
            "end": len(value),
            "text": value,
            "direction": "forward",
            "kind": "select",
        },
    }


def passing_result() -> tuple[dict[str, object], dict[str, str]]:
    pointer_records = [
        pointer_record(record, sequence)
        for sequence, record in enumerate(pointer_trace(), start=1)
    ]
    expected_keys = (
        ("down", "ControlLeft", "Control", True),
        ("down", "KeyC", "c", True),
        ("up", "KeyC", "c", True),
        ("up", "ControlLeft", "Control", False),
        ("down", "ControlLeft", "Control", True),
        ("down", "KeyV", "v", True),
        ("up", "KeyV", "v", True),
        ("up", "ControlLeft", "Control", False),
    )
    key_records = [
        key_record(*record, sequence, 15)
        for sequence, record in enumerate(expected_keys, start=3)
    ]
    rejected_key_records = [
        rejected_key_record("down", "UNSUPPORTED_SHORTCUT_STATE", 1),
        rejected_key_record("up", "UNMATCHED_UP", 2),
    ]
    pointer_input = {
        "enabled": True,
        "receivedCount": len(pointer_records),
        "trustedCount": len(pointer_records),
        "queuedCount": len(pointer_records),
        "queuedRecords": pointer_records,
        "lastQueued": copy.deepcopy(pointer_records[-1]),
    }
    keyboard_input = {
        "enabled": True,
        "activated": True,
        "receivedCount": len(key_records) + len(rejected_key_records),
        "trustedCount": len(key_records) + len(rejected_key_records),
        "queuedCount": len(key_records),
        "queuedRecords": key_records,
        "rejectedRecords": rejected_key_records,
        "pressedCodes": [],
        "lastQueuedDown": copy.deepcopy(key_records[5]),
        "lastQueuedUp": copy.deepcopy(key_records[-1]),
    }
    key_targets = (
        "copy-source",
        "copy-source",
        "copy-source",
        "copy-source",
        "paste-target",
        "paste-target",
        "paste-target",
        "paste-target",
    )
    inner_keys = [
        {
            "type": "keydown" if event_type == "down" else "keyup",
            "code": code,
            "key": key,
            "trusted": True,
            "ctrlKey": code in ("KeyC", "KeyV"),
            "repeat": False,
            "isComposing": False,
            "targetId": key_targets[index],
            "defaultPrevented": False,
        }
        for index, (event_type, code, key, _) in enumerate(expected_keys)
    ]
    empty_text_events = {
        "beforeinputCount": 0,
        "inputCount": 0,
        "compositionstartCount": 0,
        "compositionupdateCount": 0,
        "compositionendCount": 0,
    }
    page_probe: dict[str, object] = {
        "fontReady": True,
        "protocol": 1,
        "fixture": "chromium-wasm-m4-ozone-copy-paste-v1",
        "ready": True,
        "timerTicks": 3,
        "activeElementId": "primary-verify-target",
        "copySourceValue": "COPY",
        "decoyValue": "DECOY",
        "primaryVerifyValue": "DECOY",
        "primaryVerifySelectionStart": 5,
        "primaryVerifySelectionEnd": 5,
        "pasteValue": "COPY",
        "pasteSelectionStart": 4,
        "pasteSelectionEnd": 4,
        "copySourceActivationCount": 1,
        "copySourceFocusCount": 1,
        "selectionDecoyActivationCount": 1,
        "selectionDecoyFocusCount": 1,
        "primaryVerifyAuxClickCount": 1,
        "primaryVerifyAuxClickTrusted": True,
        "primaryVerifyFocusCount": 1,
        "primaryVerifyFocusTrusted": True,
        "pasteTargetActivationCount": 1,
        "pasteTargetFocusCount": 1,
        "resultText": "CTRL COPY/PASTE DELIVERED",
        **COORDINATES,
        "copySelectionActivity": selection_activity("COPY"),
        "decoySelectionActivity": selection_activity("DECOY"),
        "sourceTextInputEvents": copy.deepcopy(empty_text_events),
        "decoyTextInputEvents": copy.deepcopy(empty_text_events),
        "copyEventTrace": [
            {
                "type": "copy",
                "trusted": True,
                "targetId": "copy-source",
                "defaultPrevented": False,
                "selection": {
                    "start": 0,
                    "end": 4,
                    "text": "COPY",
                    "direction": "forward",
                },
            }
        ],
        "primaryVerifyPasteEventTrace": [
            {
                "type": "paste",
                "trusted": True,
                "targetId": "primary-verify-target",
                "defaultPrevented": False,
                "text": "DECOY",
            }
        ],
        "primaryVerifyPasteTextInputTrace": [
            {
                "type": event_type,
                "trusted": True,
                "inputType": "insertFromPaste",
                "data": "DECOY",
                "isComposing": False,
                "targetId": "primary-verify-target",
            }
            for event_type in ("beforeinput", "input")
        ],
        "pasteEventTrace": [
            {
                "type": "paste",
                "trusted": True,
                "targetId": "paste-target",
                "defaultPrevented": False,
                "text": "COPY",
            }
        ],
        "pasteTextInputTrace": [
            {
                "type": event_type,
                "trusted": True,
                "inputType": "insertFromPaste",
                "data": "COPY",
                "isComposing": False,
                "targetId": "paste-target",
            }
            for event_type in ("beforeinput", "input")
        ],
        "keyEventTrace": inner_keys,
    }
    result: dict[str, object] = {
        "protocol": 1,
        "case": "ozone_copy_paste_m4",
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
                "id": 16,
                "timestampMs": 1180,
                "width": 800,
                "height": 600,
            },
            "pageProbe": page_probe,
            "pointerInput": copy.deepcopy(pointer_input),
            "keyboardInput": copy.deepcopy(keyboard_input),
        },
        "pointerInput": pointer_input,
        "keyboardInput": keyboard_input,
        "activationProof": {
            "outerTraceExact": True,
            "sourceActivated": True,
            "frameAfterActivation": True,
        },
        "bareShortcutProof": {
            "hostRejected": True,
            "noBlinkDelivery": True,
        },
        "sourceSelectionProof": {
            "outerTraceExact": True,
            "nativeSelection": True,
            "frameAfterDrag": True,
        },
        "copyProof": {
            "outerTraceExact": True,
            "nativeCopy": True,
            "bareShortcutRejected": True,
            "innerKeys": True,
            "shortcutReleased": True,
        },
        "decoySelectionProof": {
            "outerTraceExact": True,
            "primarySelectionOverwritten": True,
            "releaseQueued": True,
        },
        "primarySelectionPasteProof": {
            "outerTraceExact": True,
            "primaryBufferContainsDecoy": True,
            "frameAfterPrimaryPaste": True,
        },
        "pasteProof": {
            "outerPointerTraceExact": True,
            "outerKeyTraceExact": True,
            "innerKeys": True,
            "nativePaste": True,
            "copyPasteBufferWins": True,
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
                "m4:keyboard:listeners-attached",
                "m4:keyboard:down:unsupported-shortcut-state",
                "m4:keyboard:up:unmatched",
                *["m4:keyboard:down:queued"] * 4,
                *["m4:keyboard:up:queued"] * 4,
                "shutdown:complete",
            ],
            "stdout": [],
            "stderr": [],
        },
        "failedChecks": [],
        "error": None,
    }
    return result, copy.deepcopy(VERSIONS)


class M4CopyPasteResultValidationTest(unittest.TestCase):
    def assert_valid(
        self, result: dict[str, object], versions: dict[str, str]
    ) -> None:
        self.assertIsNone(
            m3_content_server.validate_m4_copy_paste_result(
                result, expected_versions=versions
            )
        )

    def test_complete_standard_copy_paste_result_is_accepted(self) -> None:
        result, versions = passing_result()

        self.assert_valid(result, versions)

    def test_copy_paste_validation_rejects_decoy_as_the_paste_result(
        self,
    ) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        probe = readiness["pageProbe"]
        assert isinstance(probe, dict)
        probe["pasteValue"] = "DECOY"

        with self.assertRaisesRegex(M0Error, "pasteValue mismatch"):
            self.assert_valid(result, versions)

    def test_validation_requires_decoy_in_the_primary_buffer(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        probe = readiness["pageProbe"]
        assert isinstance(probe, dict)
        probe["primaryVerifyValue"] = "COPY"

        with self.assertRaisesRegex(M0Error, "primaryVerifyValue mismatch"):
            self.assert_valid(result, versions)

    def test_validation_requires_ctrl_v_before_primary_selection_paste(
        self,
    ) -> None:
        result, versions = passing_result()
        pointer = result["pointerInput"]
        assert isinstance(pointer, dict)
        records = pointer["queuedRecords"]
        assert isinstance(records, list)
        # The final six records are the regular paste click followed by the
        # final middle-click primary-selection verification.  Reversing the
        # two gestures models the old ordering, which loses focus before the
        # ordinary Ctrl+V delivery can be proven.
        records[-6:] = [*records[-3:], *records[-6:-3]]
        for sequence, record in enumerate(records, start=1):
            assert isinstance(record, dict)
            record["sequence"] = sequence
        pointer["lastQueued"] = copy.deepcopy(records[-1])
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        readiness["pointerInput"] = copy.deepcopy(pointer)

        with self.assertRaisesRegex(M0Error, "pointer trace"):
            self.assert_valid(result, versions)

    def test_control_modifier_is_required_for_the_copy_key(self) -> None:
        result, versions = passing_result()
        keyboard = result["keyboardInput"]
        assert isinstance(keyboard, dict)
        records = keyboard["queuedRecords"]
        assert isinstance(records, list)
        copy_down = records[1]
        assert isinstance(copy_down, dict)
        modifiers = copy_down["modifiers"]
        assert isinstance(modifiers, dict)
        modifiers["control"] = False
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        readiness["keyboardInput"] = copy.deepcopy(keyboard)

        with self.assertRaisesRegex(M0Error, "modifier mismatch"):
            self.assert_valid(result, versions)


class M4CopyPasteFixtureRouteTest(unittest.TestCase):
    def test_copy_paste_url_and_fixture_route_are_dedicated(self) -> None:
        class Server:
            server_address = ("127.0.0.1", 31415)

        url = m3_content_server.m4_copy_paste_smoke_url(
            Server(),
            "copy-paste-token",
            VERSIONS,
            module_name="copy_paste_shell",
            timeout_seconds=12.5,
        )

        parsed = urlsplit(url)
        self.assertEqual(parsed.scheme, "http")
        self.assertEqual(parsed.netloc, "127.0.0.1:31415")
        self.assertEqual(parsed.path, "/__m3__/")
        self.assertEqual(
            parse_qs(parsed.query),
            {
                "case": ["ozone_copy_paste_m4"],
                "chromium": ["chromium-revision"],
                "emscripten": ["emscripten-revision"],
                "fixture": ["/__m3__/m4-copy-paste-fixture.html"],
                "font": ["/__m3__/Ahem.woff2"],
                "module": ["/__m3__/artifacts/copy_paste_shell.js"],
                "port": ["port-revision"],
                "token": ["copy-paste-token"],
                "timeout_ms": ["12500"],
                "v8": ["v8-revision"],
            },
        )

        fixture = m3_content_server.M4_COPY_PASTE_FIXTURE
        self.assertEqual(fixture.name, "m4_ozone_copy_paste_page.html")
        fixture_text = fixture.read_text(encoding="utf-8")
        for marker in (
            'id="copy-source"',
            'id="selection-decoy"',
            'id="primary-verify-target"',
            'id="paste-target"',
            "chromium-wasm-m4-ozone-copy-paste-v1",
            "copyEventTrace",
            "pasteEventTrace",
            "CTRL COPY/PASTE DELIVERED",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, fixture_text)

        get_handler = inspect.getsource(m3_content_server.M3RequestHandler.do_GET)
        self.assertIn(
            '"/__m3__/m4-copy-paste-fixture.html": M4_COPY_PASTE_FIXTURE',
            get_handler,
        )


class RecordingDevToolsClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    def call(
        self, method: str, params: dict[str, object] | None = None
    ) -> dict[str, object]:
        self.calls.append((method, params))
        return {}


class M4CopyPasteDevToolsClientTest(unittest.TestCase):
    def test_ctrl_c_and_ctrl_v_emit_only_raw_physical_key_sequences(self) -> None:
        recording = RecordingDevToolsClient()
        client = object.__new__(m4_cdp.DevToolsClient)
        client.call = recording.call  # type: ignore[method-assign]

        client.dispatch_ctrl_c()
        client.dispatch_ctrl_v()

        self.assertEqual(
            recording.calls,
            [
                (
                    "Input.dispatchKeyEvent",
                    {
                        "type": "rawKeyDown",
                        "code": "ControlLeft",
                        "key": "Control",
                        "windowsVirtualKeyCode": 17,
                        "modifiers": 2,
                    },
                ),
                (
                    "Input.dispatchKeyEvent",
                    {
                        "type": "rawKeyDown",
                        "code": "KeyC",
                        "key": "c",
                        "windowsVirtualKeyCode": 67,
                        "modifiers": 2,
                    },
                ),
                (
                    "Input.dispatchKeyEvent",
                    {
                        "type": "keyUp",
                        "code": "KeyC",
                        "key": "c",
                        "windowsVirtualKeyCode": 67,
                        "modifiers": 2,
                    },
                ),
                (
                    "Input.dispatchKeyEvent",
                    {
                        "type": "keyUp",
                        "code": "ControlLeft",
                        "key": "Control",
                        "windowsVirtualKeyCode": 17,
                        "modifiers": 0,
                    },
                ),
                (
                    "Input.dispatchKeyEvent",
                    {
                        "type": "rawKeyDown",
                        "code": "ControlLeft",
                        "key": "Control",
                        "windowsVirtualKeyCode": 17,
                        "modifiers": 2,
                    },
                ),
                (
                    "Input.dispatchKeyEvent",
                    {
                        "type": "rawKeyDown",
                        "code": "KeyV",
                        "key": "v",
                        "windowsVirtualKeyCode": 86,
                        "modifiers": 2,
                    },
                ),
                (
                    "Input.dispatchKeyEvent",
                    {
                        "type": "keyUp",
                        "code": "KeyV",
                        "key": "v",
                        "windowsVirtualKeyCode": 86,
                        "modifiers": 2,
                    },
                ),
                (
                    "Input.dispatchKeyEvent",
                    {
                        "type": "keyUp",
                        "code": "ControlLeft",
                        "key": "Control",
                        "windowsVirtualKeyCode": 17,
                        "modifiers": 0,
                    },
                ),
            ],
        )
        self.assertTrue(
            all(
                method == "Input.dispatchKeyEvent"
                and "text" not in (params or {})
                for method, params in recording.calls
            )
        )


class M4CopyPasteRunnerTest(unittest.TestCase):
    def test_copy_paste_input_selects_its_dedicated_runner_case(self) -> None:
        failure = M0Error("stop before browser startup")
        context = {"test": "copy-paste"}
        stderr = io.StringIO()

        with (
            mock.patch.object(
                sys,
                "argv",
                ["run_m4_ozone_smoke.py", "--input=copy-paste"],
            ),
            mock.patch.object(
                run_m4_ozone_smoke,
                "load_manifest",
                return_value={},
            ),
            mock.patch.object(
                run_m4_ozone_smoke,
                "checked_output",
                return_value="port-revision",
            ),
            mock.patch.object(
                run_m4_ozone_smoke,
                "manifest_versions",
                return_value=VERSIONS,
            ),
            mock.patch.object(
                run_m4_ozone_smoke,
                "print_context",
                return_value=context,
            ) as print_context,
            mock.patch.object(
                run_m4_ozone_smoke,
                "find_browser",
                side_effect=failure,
            ),
            mock.patch.object(
                run_m4_ozone_smoke,
                "write_failure_diagnostics",
                return_value=Path("diagnostics.json"),
            ) as diagnostics,
            mock.patch.object(sys, "stderr", stderr),
        ):
            self.assertEqual(run_m4_ozone_smoke.main(), 1)

        self.assertEqual(
            print_context.call_args.kwargs["case"],
            m3_content_server.M4_COPY_PASTE_CASE,
        )
        self.assertIn(
            "ControlLeft+KeyC",
            print_context.call_args.kwargs["input_driver"],
        )
        self.assertIn(
            "ControlLeft+KeyV",
            print_context.call_args.kwargs["input_driver"],
        )
        self.assertEqual(
            diagnostics.call_args.kwargs["case"],
            m3_content_server.M4_COPY_PASTE_CASE,
        )


if __name__ == "__main__":
    unittest.main()
