#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the trusted-DOM browser accelerator smoke lane."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m6_wasm_browser_host_accelerator_dom_smoke as smoke
from tools.wasm.tests.m3_source_contract_test_support import source


def successful_result() -> dict[str, object]:
    records = [
        {
            "type": "keydown",
            "code": "ControlLeft",
            "trusted": True,
            "accepted": True,
            "defaultPrevented": True,
            "canvasFocused": True,
        },
        {
            "type": "keydown",
            "code": "KeyL",
            "trusted": True,
            "accepted": True,
            "defaultPrevented": True,
            "canvasFocused": True,
        },
        {
            "type": "keyup",
            "code": "KeyL",
            "trusted": True,
            "accepted": True,
            "defaultPrevented": True,
            "canvasFocused": True,
        },
        {
            "type": "keyup",
            "code": "ControlLeft",
            "trusted": True,
            "accepted": True,
            "defaultPrevented": True,
            "canvasFocused": True,
        },
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
        "canvasFocused": True,
        "abort": None,
        "fatalErrors": [],
        "windowErrors": [],
        "unhandledRejections": [],
        "failedChecks": [],
        "error": None,
        "versions": {"chromium": "c", "v8": "v", "emscripten": "e", "port": "p"},
        "stdout": [],
        "stderr": [smoke.READY_MARKER, smoke.PASS_MARKER],
        "frameReports": [{"id": 1, "width": 640, "height": 480, "timestampMs": 1.0}],
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
        "hostInput": {
            "attached": True,
            "readyObserved": True,
            "passObserved": True,
            "verificationQueued": True,
            "reservedShortcutLimitation": "reserved outer-browser shortcuts may not reach DOM",
            "receivedRecords": records,
            "acceptedRecords": records,
            "rejectedRecords": [],
            "heldCodes": [],
            "cleanupRecords": [],
        },
    }


class M6WasmBrowserHostAcceleratorDomSmokeTest(unittest.TestCase):
    def test_host_listener_is_canvas_scoped_and_releases_on_loss_of_focus(self) -> None:
        host = source(
            "tools/wasm/host/chrome_wasm_browser_host_accelerator_smoke_host.js"
        )
        for expected in (
            "chromium_wasm_browser_host_key",
            "canvas.addEventListener(\"keydown\"",
            "canvas.addEventListener(\"keyup\"",
            "canvas.addEventListener(\"blur\"",
            "window.addEventListener(\"blur\"",
            "document.addEventListener(\"visibilitychange\"",
            "event.preventDefault()",
            "event.isTrusted",
            "chromium_wasm_browser_host_accelerator_check",
            "releaseHeldKeys",
            "awaiting-trusted-dom-ctrl-l",
            smoke.READY_MARKER,
            smoke.PASS_MARKER,
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, host)

    def test_host_validates_dom_events_before_calling_the_chrome_abi(self) -> None:
        host = source(
            "tools/wasm/host/chrome_wasm_browser_host_accelerator_smoke_host.js"
        )
        for expected in (
            "HOST_ACCELERATOR_CODES",
            "C++ accelerator verifier is not ready",
            "event.isTrusted !== true",
            "event.cancelable !== true",
            "document.activeElement !== this.#canvas",
            "event.isComposing",
            "event.repeat",
            "event.metaKey",
            'event.getModifierState("AltGraph")',
            "#hasExactAcceptedModifierState",
            "DOM keyboard modifier state does not match accepted left modifiers",
            "const rejectionReason = this.#rejectionReason(event, down)",
            "rejectionReason === null &&",
            "this.#callHostKey(event.code, down)",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, host)

    def test_host_applies_reported_ozone_cursor_before_acknowledging_it(self) -> None:
        host = source(
            "tools/wasm/host/chrome_wasm_browser_host_accelerator_smoke_host.js"
        )
        for expected in (
            "function ozoneCursorDescriptor(cursorType)",
            "#reportOzoneCursor(value)",
            "this.#canvas.style.cursor = descriptor.cssCursor",
            "host canvas rejected the Ozone cursor style",
            "reportOzoneCursor(report) {",
            "return host.#reportOzoneCursor(report);",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, host)
        self.assertNotIn("reportOzoneCursor() {\n        return true;", host)

    def test_runner_waits_for_dom_listener_then_uses_trusted_cdp_input(self) -> None:
        runner = source(
            "tools/wasm/run_m6_wasm_browser_host_accelerator_dom_smoke.py"
        )
        for expected in (
            "wait_for_page_client",
            "wait_for_input_ready",
            "client.dispatch_control_shortcut(\"KeyL\", \"l\", 76)",
            "--wasm-browser-host-accelerator-smoke",
            "remote-debugging-port",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, runner)
        self.assertNotIn("ccall(", runner)

    def test_accepts_complete_trusted_dom_and_presentation_evidence(self) -> None:
        expected_versions = successful_result()["versions"]
        assert isinstance(expected_versions, dict)
        smoke.validate_result(successful_result(), expected_versions=expected_versions)

    def test_rejects_missing_or_unaccepted_dom_key_evidence(self) -> None:
        for mutate, expression in (
            (
                lambda result: result["hostInput"].__setitem__("attached", False),
                "attached",
            ),
            (
                lambda result: result["hostInput"]["receivedRecords"].pop(),
                "record count",
            ),
            (
                lambda result: result["hostInput"]["receivedRecords"][1].__setitem__(
                    "trusted", False
                ),
                "trusted",
            ),
            (
                lambda result: result["hostInput"].__setitem__("heldCodes", ["KeyL"]),
                "pressed DOM key",
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
                b'{"protocol":1,"protocol":1,"case":"browser_host_accelerators_m6"}'
            )
        )


if __name__ == "__main__":
    unittest.main()
