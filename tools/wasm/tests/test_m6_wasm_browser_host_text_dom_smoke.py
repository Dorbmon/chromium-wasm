#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the trusted-DOM committed-text browser smoke lane."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m6_wasm_browser_host_text_dom_smoke as smoke
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
    beforeinput = [
        {
            "inputType": "insertText",
            "dataOmitted": True,
            "dataUtf16Units": len(chunk),
            "dataUtf8Bytes": len(chunk),
            "trusted": True,
            "cancelable": True,
            "isComposing": False,
            "proxyFocused": True,
            "queued": True,
            "defaultPrevented": True,
            "sequence": index + 1,
            "nativeDispatched": True,
            "nativeAccepted": True,
        }
        for index, chunk in enumerate(smoke.ADDRESS_TEXT_CHUNKS)
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
        "m6GateComplete": False,
        "runtimeExitCode": 0,
        "processExitCode": 0,
        "runtimeInitialized": True,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocusedAtStart": True,
        "proxyFocused": True,
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
            }
        ],
        "hostInput": {
            "attached": True,
            "editable": True,
            "shortcutComplete": True,
            "proxyFocused": True,
            "readyObserved": True,
            "burstArmedObserved": True,
            "nativeBurstAdmissionsObserved": True,
            "nativeTextAdmissionCount": 2,
            "nativeTextDeliveryCountAtAdmission": [0, 0],
            "nativeTextDeliveryCount": 2,
            "nativeTextDeliverySequences": [1, 2],
            "focusObserved": True,
            "focusPresentationObserved": True,
            "insertedObserved": True,
            "insertedPresentationObserved": True,
            "navigatedObserved": True,
            "navigationPresentationObserved": True,
            "passObserved": True,
            "focusCheckQueued": True,
            "textCheckQueued": True,
            "navigationCheckQueued": True,
            "focusMarkerFrameId": 1,
            "frameIdAfterFocus": 2,
            "insertedMarkerFrameId": 2,
            "frameIdAfterInsert": 3,
            "navigationMarkerFrameId": 3,
            "frameIdAfterNavigation": 4,
            "textQueued": True,
            "deliveryAccepted": True,
            "deliveryRejected": False,
            "proxySessionCleared": False,
            "focusGeneration": 1,
            "acceptedDeliveryFocusGeneration": 1,
            "pendingDeliveryCount": 0,
            "pendingTextUtf8Bytes": 0,
            "tombstonedDeliveryCount": 0,
            "textareaValue": "",
            "ctrlLRecords": ctrl_l,
            "beforeInputRecords": beforeinput,
            "browserTextDeliveryReports": [
                {"action": 4, "sessionId": 0, "sequence": 1, "accepted": True},
                {"action": 4, "sessionId": 0, "sequence": 2, "accepted": True},
            ],
            "enterRecords": enter,
            "rejectedRecords": [],
            "cleanupRecords": [],
        },
        "stdout": [],
        "stderr": [
            smoke.BURST_ARMED_MARKER,
            smoke.READY_MARKER,
            smoke.FOCUSED_MARKER,
            smoke.INSERTED_MARKER,
            smoke.NAVIGATED_MARKER,
            smoke.PASS_MARKER,
        ],
        "failedChecks": [],
        "error": None,
    }


class M6WasmBrowserHostTextDomSmokeTest(unittest.TestCase):
    def test_shared_adapter_is_used_by_normal_and_smoke_hosts(self) -> None:
        adapter = source("tools/wasm/host/chrome_wasm_text_input.js")
        normal_host = source("tools/wasm/host/chrome_wasm_host.js")
        smoke_host = source(
            "tools/wasm/host/chrome_wasm_browser_host_text_smoke_host.js"
        )
        for host in (normal_host, smoke_host):
            self.assertIn(
                'import {ChromiumWasmTrustedTextInput} from "./chrome_wasm_text_input.js";',
                host,
            )
            self.assertIn("new ChromiumWasmTrustedTextInput", host)
            self.assertIn("handleOzoneBrowserTextInputDelivery", host)
        for expected in (
            'this.#proxy.addEventListener("beforeinput"',
            'this.#proxy.addEventListener("keydown"',
            'this.#canvas.addEventListener("keydown"',
            'this.#proxy.addEventListener("blur"',
            'document.addEventListener("visibilitychange"',
            'this.#releaseHeldEnter("document-hidden")',
            "event.isTrusted !== true",
            "event.cancelable !== true",
            'event.inputType !== "insertText"',
            "event.isComposing",
            "event.preventDefault()",
            "handleOzoneBrowserTextInputDelivery(report)",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, adapter)

    def test_shared_adapter_validates_text_before_explicit_wasm_copy(self) -> None:
        adapter = source("tools/wasm/host/chrome_wasm_text_input.js")
        for expected in (
            "function isWellFormedUtf16(text)",
            "MAX_UTF8_BYTES = 192 * 1024",
            "MAX_UTF16_UNITS = 64 * 1024",
            "MAX_NATIVE_PENDING_DELIVERIES = 16",
            "MAX_NATIVE_PENDING_UTF8_BYTES = 192 * 1024",
            "this.#pendingDeliveries.size >= MAX_NATIVE_PENDING_DELIVERIES",
            "event.data.length > MAX_UTF16_UNITS",
            "event.data.length * 3 > MAX_UTF8_BYTES",
            "!isWellFormedUtf16(event.data)",
            "bytes.byteLength > MAX_UTF8_BYTES",
            "this.#pendingTextUtf8Bytes + bytes.byteLength >",
            "module._malloc(bytes.byteLength)",
            "module.HEAPU8.set(bytes, pointer)",
            '"chromium_wasm_browser_host_text", "number", ["number", "number"]',
            "module._free(pointer)",
            "this.#pendingDeliveries.size === 0",
            "this.#acceptedDeliveryFocusGeneration === this.#focusGeneration",
            "this.#callHostTextBytes(bytes)",
            "this.#tombstonePendingDeliveries()",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, adapter)
        host_text_section = adapter.split('"chromium_wasm_browser_host_text"', 1)[1]
        self.assertNotIn('["string", "number"]', host_text_section.split("#resetShortcut", 1)[0])
        self.assertNotIn("#queuedTextRequests", adapter)

    def test_smoke_defers_wasm_reentry_from_native_delivery_and_frame_reports(self) -> None:
        host = source("tools/wasm/host/chrome_wasm_browser_host_text_smoke_host.js")
        for expected in (
            "onBeforeInputQueued: (record) => this.#recordNativeTextAdmission(record)",
            "onNativeDelivery: (report) => this.#recordNativeTextDelivery(report)",
            "nativeTextDeliveryCountAtAdmission",
            "ADDRESS_TEXT_CHUNKS",
            "setTimeout(() => {",
            "synchronous UI->JS bridge import",
            "this.#callSmokeCheck(2)",
            "this.#callSmokeCheck(3)",
            "frameIdAfterFocus",
            "frameIdAfterInsert",
            "frameIdAfterNavigation",
            "this.#textInput?.activateProxy()",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, host)
        for forbidden in ("SetText", "NavigationController", "location.assign(", "location.href ="):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, host)

    def test_runner_uses_only_cdp_ctrl_l_insert_text_and_raw_enter(self) -> None:
        runner = source("tools/wasm/run_m6_wasm_browser_host_text_dom_smoke.py")
        for expected in (
            "wait_for_page_client",
            'client.dispatch_control_shortcut("KeyL", "l", 76)',
            "for text_chunk in ADDRESS_TEXT_CHUNKS:",
            'client.call("Input.insertText", {"text": text_chunk})',
            '"Input.dispatchKeyEvent"',
            '"rawKeyDown"',
            '"keyUp"',
            '"code": "Enter"',
            '"modifiers": 0',
            "chrome_wasm_text_input.js",
            "awaiting-trusted-dom-insert-text",
            "awaiting-trusted-dom-enter",
            "verify_explicit_text_heap_exports",
            'Module["_malloc"]',
            'Module["_free"]',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, runner)
        for forbidden in (
            "chromium_wasm_browser_host_text\",",
            "ccall(",
            "Page.navigate",
            "location.assign",
            "location.href",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, runner)

    def test_runner_omits_text_fields_from_cdp_enter_key_up(self) -> None:
        class Client:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict[str, object]]] = []

            def call(self, method: str, params: dict[str, object]) -> None:
                self.calls.append((method, params))

        client = Client()
        smoke.dispatch_unmodified_enter(client)
        self.assertEqual(len(client.calls), 2)
        down_method, down = client.calls[0]
        up_method, up = client.calls[1]
        self.assertEqual(down_method, "Input.dispatchKeyEvent")
        self.assertEqual(up_method, "Input.dispatchKeyEvent")
        self.assertEqual(down["type"], "rawKeyDown")
        self.assertEqual(down["text"], "")
        self.assertEqual(down["unmodifiedText"], "")
        self.assertEqual(up["type"], "keyUp")
        self.assertNotIn("text", up)
        self.assertNotIn("unmodifiedText", up)

    def test_html_keeps_the_textarea_focusable_without_direct_field_control(self) -> None:
        html = source("tools/wasm/host/chrome_wasm_browser_host_text_smoke.html")
        proxy = html.split('<textarea\n      id="browser-text-proxy"', 1)[1].split(
            "></textarea>", 1
        )[0]
        for forbidden in ("hidden", "disabled", "readonly", "inert"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, proxy)
        self.assertNotIn("SetText", html)

    def test_accepts_complete_trusted_input_delivery_navigation_and_paint_evidence(self) -> None:
        result = successful_result()
        versions = result["versions"]
        assert isinstance(versions, dict)
        smoke.validate_result(result, expected_versions=versions)

    def test_rejects_missing_delivery_or_presentation_evidence(self) -> None:
        for mutate, expression in (
            (
                lambda result: result["hostInput"].__setitem__(
                    "deliveryAccepted", False
                ),
                "deliveryAccepted",
            ),
            (
                lambda result: result["hostInput"].__setitem__(
                    "frameIdAfterNavigation", 3
                ),
                "fresh presentation",
            ),
            (
                lambda result: result["hostInput"]["beforeInputRecords"][0].__setitem__(
                    "trusted", False
                ),
                "beforeinput trusted",
            ),
            (
                lambda result: result["hostInput"]["browserTextDeliveryReports"].__setitem__(
                    1, {"action": 4, "sessionId": 0, "sequence": 2, "accepted": False}
                ),
                "native delivery",
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
                b'{"protocol":1,"protocol":1,"case":"browser_host_text_m6"}'
            )
        )


if __name__ == "__main__":
    unittest.main()
