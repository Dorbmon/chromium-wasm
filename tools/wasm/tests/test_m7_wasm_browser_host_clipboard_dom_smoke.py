#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Static and result-validation contracts for the M7 clipboard DOM smoke."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m7_wasm_browser_host_clipboard_dom_smoke as smoke
from tools.wasm.tests.m3_source_contract_test_support import source


def successful_result() -> dict[str, object]:
    ctrl_l = [
        {
            "type": event_type,
            "code": code,
            "trusted": True,
            "cancelable": True,
            "canvasFocused": True,
            "accepted": True,
            "defaultPrevented": True,
        }
        for event_type, code in (
            ("keydown", "ControlLeft"),
            ("keydown", "KeyL"),
            ("keyup", "KeyL"),
            ("keyup", "ControlLeft"),
        )
    ]
    enter = [
        {
            "type": event_type,
            "code": "Enter",
            "key": "Enter",
            "trusted": True,
            "cancelable": True,
            "proxyFocused": True,
            "accepted": True,
            "defaultPrevented": True,
        }
        for event_type in ("keydown", "keyup")
    ]
    return {
        "protocol": 1,
        "case": smoke.CASE,
        "scope": smoke.SCOPE,
        "status": "pass",
        "m7GateComplete": False,
        "runtimeExitCode": 0,
        "processExitCode": 0,
        "runtimeInitialized": True,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocusedAtStart": True,
        "proxyFocused": True,
        "normalCloseObserved": True,
        "abort": None,
        "fatalErrors": [],
        "windowErrors": [],
        "unhandledRejections": [],
        "versions": {"chromium": "c", "v8": "v", "emscripten": "e", "port": "p"},
        "frameReports": [
            {"id": 1, "width": 640, "height": 480, "timestampMs": 1.0},
            {"id": 2, "width": 640, "height": 480, "timestampMs": 2.0},
            {"id": 3, "width": 640, "height": 480, "timestampMs": 3.0},
            {"id": 4, "width": 640, "height": 480, "timestampMs": 4.0},
            {"id": 5, "width": 640, "height": 480, "timestampMs": 5.0},
            {"id": 6, "width": 640, "height": 480, "timestampMs": 6.0},
        ],
        "readiness": {
            "shellReady": True,
            "surfaceReady": True,
            "firstVisuallyNonEmptyPaint": True,
        },
        "readinessReports": [
            {
                "shellReady": True,
                "surfaceReady": True,
                "firstVisuallyNonEmptyPaint": True,
            }
        ],
        "ozoneFocusReports": [{"keyboardTargetPresent": True, "active": True}],
        "ozoneTextInputStates": [
            {
                "focusedClientPresent": True,
                "editable": True,
                "canComposeInline": False,
            },
            {
                "focusedClientPresent": False,
                "editable": False,
                "canComposeInline": False,
            },
        ],
        "ozoneCursorReports": [],
        "hostInput": {
            "attached": True,
            # Native navigation can remove the editable TextInputClient before
            # this final snapshot. The earlier Ozone state remains the
            # admission evidence.
            "editable": False,
            "proxyFocused": True,
            "readyObserved": True,
            "focusCheckQueued": True,
            "focusObserved": True,
            "focusPresentationObserved": True,
            "seedButtonTrustedClicked": True,
            "seedButtonClickCancelable": True,
            "seedButtonDefaultPrevented": True,
            "seedWriteRequested": True,
            "seedWriteSucceeded": True,
            "seedWriteFailed": False,
            "proxyFocusedAfterSeed": True,
            "clipboardDeliveryObserved": True,
            "clipboardDeliveryAccepted": True,
            "clipboardDeliveryRequestId": 1,
            "pasteCheckQueued": True,
            "pastedObserved": True,
            "pastedPresentationObserved": True,
            "enterDispatchStarted": True,
            "enterHeld": False,
            "enterComplete": True,
            "navigatedObserved": True,
            "navigationPresentationObserved": True,
            "navigationCheckQueued": True,
            "passObserved": True,
            "ctrlLIndex": 4,
            "ctrlLComplete": True,
            "ctrlLRecords": ctrl_l,
            "seedRecords": [
                {
                    "trusted": True,
                    "cancelable": True,
                    "state": "awaiting-trusted-dom-clipboard-seed",
                    "defaultPrevented": True,
                    "writeRequested": True,
                    "writeSucceeded": True,
                    "reason": None,
                }
            ],
            "enterRecords": enter,
            "rejectedKeyRecords": [],
            "keyCleanupRecords": [],
            "ordinalChecks": [1, 2, 3],
            "focusMarkerFrameId": 1,
            "frameIdAfterFocus": 2,
            "pastedMarkerFrameId": 3,
            "frameIdAfterPaste": 4,
            "navigationMarkerFrameId": 5,
            "frameIdAfterNavigation": 6,
            "focusGeneration": 1,
            "pendingRequestId": None,
            "tombstonedRequestCount": 0,
            "proxyTextEmpty": True,
            "pasteRecords": [
                {
                    "trusted": True,
                    "cancelable": True,
                    "proxyFocused": True,
                    "containsPlainText": True,
                    "textUtf16Units": len(smoke.ADDRESS_TEXT),
                    "textUtf8Bytes": len(smoke.ADDRESS_TEXT.encode("utf-8")),
                    "requestId": 1,
                    "admitted": True,
                    "defaultPrevented": True,
                    "reason": None,
                }
            ],
            "deliveryReports": [
                {"requestId": 1, "nativeAccepted": True, "accepted": True}
            ],
            "rejectedRecords": [],
            "cleanupRecords": [],
        },
        "stdout": [],
        "stderr": [
            smoke.READY_MARKER,
            smoke.FOCUSED_MARKER,
            smoke.PASTED_MARKER,
            smoke.NAVIGATED_MARKER,
            smoke.PASS_MARKER,
        ],
        "failedChecks": [],
        "error": None,
    }


class M7WasmBrowserHostClipboardDomSmokeTest(unittest.TestCase):
    def test_host_uses_production_adapter_and_only_test_button_may_write_clipboard(self) -> None:
        adapter = source("tools/wasm/host/chrome_wasm_clipboard_input.js")
        host = source(
            "tools/wasm/host/chrome_wasm_browser_host_clipboard_smoke_host.js"
        )
        html = source("tools/wasm/host/chrome_wasm_browser_host_clipboard_smoke.html")
        self.assertIn(
            'import {ChromiumWasmTrustedClipboardInput} from "./chrome_wasm_clipboard_input.js";',
            host,
        )
        self.assertIn("new ChromiumWasmTrustedClipboardInput", host)
        self.assertNotIn("navigator.clipboard.", adapter)
        self.assertIn('id="clipboard-seed"', html)
        self.assertIn("disabled", html.split('id="clipboard-seed"', 1)[1].split(">", 1)[0])

        seed_handler = host.split("  #handleSeedClick(event) {", 1)[1].split(
            "  #recordNativeClipboardDelivery", 1
        )[0]
        for expected in (
            "event.isTrusted === true",
            "event.cancelable === true",
            "navigator.clipboard.writeText(ADDRESS_TEXT)",
            "event.preventDefault();",
            'this.#setState("awaiting-trusted-dom-clipboard-paste")',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, seed_handler)
        self.assertLess(
            seed_handler.index("!record.trusted"),
            seed_handler.index("navigator.clipboard.writeText(ADDRESS_TEXT)"),
        )
        self.assertNotIn("navigator.clipboard.readText", host)
        self.assertNotIn("execCommand(", host)
        self.assertNotIn("ClipboardEvent(", host)
        self.assertNotIn("textareaValue", host)
        self.assertIn("proxyTextEmpty", host)

    def test_host_defers_observer_reentry_and_uses_only_fixed_ordinals(self) -> None:
        host = source(
            "tools/wasm/host/chrome_wasm_browser_host_clipboard_smoke_host.js"
        )
        for expected in (
            '"chromium_wasm_browser_host_clipboard_smoke_check"',
            "this.#callSmokeCheck(1)",
            "this.#callSmokeCheck(2)",
            "this.#callSmokeCheck(3)",
            "setTimeout(() => {",
            "frameIdAfterFocus",
            "frameIdAfterPaste",
            "frameIdAfterNavigation",
            "handleOzoneBrowserClipboardPasteDelivery",
            "enterDispatchStarted = true;",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, host)
        self.assertNotIn('"chromium_wasm_browser_host_clipboard_paste"', host)
        enter_handler = host.split("  #handleProxyEnter(event, down) {", 1)[1].split(
            "  #releaseHeldEnter", 1
        )[0]
        self.assertLess(
            enter_handler.index("this.#input.enterDispatchStarted = true;"),
            enter_handler.index('this.#callHostKey("Enter", down)'),
        )
        navigation_marker = host.split("if (text.includes(NAVIGATED_MARKER)) {", 1)[1].split(
            "if (text.includes(PASS_MARKER))", 1
        )[0]
        self.assertIn("!this.#input.enterDispatchStarted", navigation_marker)
        self.assertIn("!this.#input.pastedPresentationObserved", navigation_marker)
        for forbidden in (
            "NavigationController",
            "LoadURL",
            "OpenURL",
            "Page.navigate",
            "location.assign(",
            "location.href =",
            "SetText(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, host)

    def test_runner_drives_trusted_button_then_physical_ctrl_v_and_enter(self) -> None:
        runner = source("tools/wasm/run_m7_wasm_browser_host_clipboard_dom_smoke.py")
        for expected in (
            "wait_for_page_client",
            'client.dispatch_control_shortcut("KeyL", "l", 76)',
            "client.dispatch_primary_click(x, y)",
            "client.dispatch_ctrl_v()",
            '"Input.dispatchKeyEvent"',
            "awaiting-trusted-dom-clipboard-seed",
            "awaiting-trusted-dom-clipboard-paste",
            "awaiting-trusted-dom-enter",
            "wait_for_normal_close_result",
            "chrome_wasm_clipboard_input.js",
            "verify_explicit_clipboard_heap_exports",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, runner)
        for forbidden in (
            "Input.insertText",
            "Page.navigate",
            "location.assign",
            "location.href",
            "ccall(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, runner)

    def test_accepts_complete_trusted_paste_navigation_and_normal_close_evidence(self) -> None:
        result = successful_result()
        versions = result["versions"]
        assert isinstance(versions, dict)
        smoke.validate_result(result, expected_versions=versions)

    def test_rejects_missing_trusted_paste_later_frame_or_normal_close(self) -> None:
        for mutate, expression in (
            (
                lambda result: result["hostInput"]["pasteRecords"][0].__setitem__(
                    "trusted", False
                ),
                "paste trusted",
            ),
            (
                lambda result: result["hostInput"].__setitem__(
                    "frameIdAfterPaste", 3
                ),
                "later-frame evidence",
            ),
            (
                lambda result: result.__setitem__("normalCloseObserved", False),
                "normalCloseObserved",
            ),
            (
                lambda result: result["hostInput"].__setitem__(
                    "ordinalChecks", [1, 3]
                ),
                r"exactly \[1, 2, 3\]",
            ),
            (
                lambda result: result["hostInput"].__setitem__(
                    "enterDispatchStarted", False
                ),
                "enterDispatchStarted",
            ),
            (
                lambda result: result["hostInput"].__setitem__(
                    "editable", "false"
                ),
                "final editable state is invalid",
            ),
            (
                lambda result: result.__setitem__(
                    "ozoneTextInputStates",
                    [
                        {
                            "focusedClientPresent": False,
                            "editable": False,
                            "canComposeInline": False,
                        }
                    ],
                ),
                "no editable Ozone TextInputClient state",
            ),
        ):
            with self.subTest(expression=expression):
                result = successful_result()
                mutate(result)
                with self.assertRaisesRegex(M0Error, expression):
                    smoke.validate_result(result, expected_versions=result["versions"])

    def test_parser_rejects_duplicate_or_wrong_scope_results(self) -> None:
        result = json.dumps(successful_result(), separators=(",", ":")).encode()
        self.assertEqual(smoke.parse_result_payload(result), successful_result())
        self.assertIsNone(
            smoke.parse_result_payload(
                b'{"protocol":1,"protocol":1,"case":"browser_host_clipboard_m7"}'
            )
        )
        wrong_scope = successful_result()
        wrong_scope["scope"] = "wrong"
        self.assertIsNone(
            smoke.parse_result_payload(json.dumps(wrong_scope).encode("utf-8"))
        )

    def test_seed_button_center_rejects_nonfinite_or_negative_coordinates(self) -> None:
        for state in (
            {},
            {"seedButtonCenter": {"x": "1", "y": 2}},
            {"seedButtonCenter": {"x": float("nan"), "y": 2}},
            {"seedButtonCenter": {"x": -1, "y": 2}},
        ):
            with self.subTest(state=state):
                with self.assertRaises(M0Error):
                    smoke.seed_button_center(state)


if __name__ == "__main__":
    unittest.main()
