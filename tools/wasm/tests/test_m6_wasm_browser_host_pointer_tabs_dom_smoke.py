#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the real-browser trusted-DOM pointer tab-flow smoke."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m6_wasm_browser_host_pointer_tabs_dom_smoke as smoke
from tools.wasm.tests.m3_source_contract_test_support import source


def pointer_record(
    event_type: str,
    x: int,
    y: int,
    *,
    button: int,
    buttons: int,
) -> dict[str, object]:
    return {
        "type": event_type,
        "trusted": True,
        "cancelable": True,
        "pointerType": "mouse",
        "primary": True,
        "pointerId": 1,
        "button": button,
        "buttons": buttons,
        "accepted": True,
        "defaultPrevented": True,
        "x": x,
        "y": y,
        "reason": None,
    }


def successful_result() -> dict[str, object]:
    new_target = {"x": 618, "y": 16, "clientX": 635.5, "clientY": 33.5}
    first_target = {"x": 76, "y": 16, "clientX": 93.5, "clientY": 33.5}
    second_target = {"x": 226, "y": 16, "clientX": 243.5, "clientY": 33.5}
    close_target = {"x": 294, "y": 16, "clientX": 311.5, "clientY": 33.5}
    records = [
        pointer_record("move", 618, 16, button=-1, buttons=0),
        pointer_record("down", 618, 16, button=0, buttons=1),
        pointer_record("up", 618, 16, button=0, buttons=0),
        pointer_record("move", 76, 16, button=-1, buttons=0),
        pointer_record("down", 76, 16, button=0, buttons=1),
        pointer_record("up", 76, 16, button=0, buttons=0),
        pointer_record("move", 226, 16, button=-1, buttons=0),
        pointer_record("down", 226, 16, button=0, buttons=1),
        pointer_record("up", 226, 16, button=0, buttons=0),
        pointer_record("move", 294, 16, button=-1, buttons=0),
        pointer_record("down", 294, 16, button=0, buttons=1),
        pointer_record("up", 294, 16, button=0, buttons=0),
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
        "stderr": [
            f"{smoke.READY_MARKER} x=618 y=16",
            f"{smoke.INSERTED_MARKER} x=76 y=16",
            f"{smoke.FIRST_SELECTED_MARKER} x=226 y=16",
            f"{smoke.SECOND_SELECTED_MARKER} x=294 y=16",
            smoke.CLOSED_MARKER,
            smoke.PASS_MARKER,
        ],
        "frameReports": [
            {"id": 1, "width": 640, "height": 480, "timestampMs": 1.0},
            {"id": 2, "width": 640, "height": 480, "timestampMs": 2.0},
            {"id": 3, "width": 640, "height": 480, "timestampMs": 3.0},
            {"id": 4, "width": 640, "height": 480, "timestampMs": 4.0},
            {"id": 5, "width": 640, "height": 480, "timestampMs": 5.0},
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
        "hostInput": {
            "attached": True,
            "readyObserved": True,
            "insertedObserved": True,
            "firstSelectedObserved": True,
            "secondSelectedObserved": True,
            "closedObserved": True,
            "passObserved": True,
            "newTabTarget": new_target,
            "firstTabTarget": first_target,
            "secondTabTarget": second_target,
            "closeTabTarget": close_target,
            "frameIdAtInsertedMarker": 1,
            "frameIdAfterInsert": 2,
            "frameIdAtFirstSelectedMarker": 2,
            "frameIdAfterFirstSelection": 3,
            "frameIdAtSecondSelectedMarker": 3,
            "frameIdAfterSecondSelection": 4,
            "frameIdAtClosedMarker": 4,
            "frameIdAfterClose": 5,
            "insertCheckQueued": True,
            "firstSelectionCheckQueued": True,
            "secondSelectionCheckQueued": True,
            "closeCheckQueued": True,
            "presentationQueued": True,
            "pointerRecords": records,
        },
    }


class M6WasmBrowserHostPointerTabsDomSmokeTest(unittest.TestCase):
    def test_special_host_imports_the_exact_normal_pointer_adapter(self) -> None:
        normal_host = source("tools/wasm/host/chrome_wasm_host.js")
        pointer_host = source(
            "tools/wasm/host/chrome_wasm_browser_host_pointer_tabs_smoke_host.js"
        )
        adapter = source("tools/wasm/host/chrome_wasm_pointer_input.js")
        for host in (normal_host, pointer_host):
            self.assertIn(
                'import {ChromiumWasmTrustedPointerInput} from "./chrome_wasm_pointer_input.js";',
                host,
            )
            self.assertIn("new ChromiumWasmTrustedPointerInput", host)
        for expected in (
            "chromium_wasm_browser_host_pointer_tab_check",
            "chromium_wasm_browser_host_pointer_tab_presented",
            "frameIdAtInsertedMarker",
            "frameIdAtFirstSelectedMarker",
            "frameIdAtSecondSelectedMarker",
            "frameIdAtClosedMarker",
            "FIRST_SELECTED_MARKER",
            "SECOND_SELECTED_MARKER",
            "awaiting-trusted-dom-new-tab",
            "awaiting-trusted-dom-select-first-tab",
            "awaiting-trusted-dom-select-second-tab",
            "awaiting-trusted-dom-close-tab",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, pointer_host)
        self.assertNotIn('"chromium_wasm_browser_host_pointer",', pointer_host)
        self.assertIn("chromium_wasm_browser_host_pointer", adapter)

    def test_shared_adapter_accepts_only_trusted_primary_pointer_cleanup(self) -> None:
        adapter = source("tools/wasm/host/chrome_wasm_pointer_input.js")
        for expected in (
            "if (!record.trusted)",
            "if (!record.cancelable)",
            "#isTrustedActivePointerCleanupEvent(event)",
            "event?.isTrusted === true",
            'event.pointerType === "mouse"',
            "event.isPrimary === true",
            'this.releaseActivePointer("pointer-cancel")',
            'this.releaseActivePointer("lost-pointer-capture")',
            'this.releaseActivePointer("canvas-blur")',
            'this.releaseActivePointer("document-hidden")',
            "chromium_wasm_browser_host_pointer_exit",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, adapter)

    def test_runner_only_uses_trusted_cdp_clicks(self) -> None:
        runner = source("tools/wasm/run_m6_wasm_browser_host_pointer_tabs_dom_smoke.py")
        for expected in (
            "wait_for_page_client",
            "awaiting-trusted-dom-new-tab",
            "awaiting-trusted-dom-select-first-tab",
            "awaiting-trusted-dom-select-second-tab",
            "awaiting-trusted-dom-close-tab",
            "client.dispatch_primary_click",
            "--wasm-browser-host-pointer-tab-smoke",
            "remote-debugging-port",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, runner)
        self.assertNotIn("ccall(", runner)
        self.assertNotIn("Runtime.evaluate", runner)

    def test_accepts_complete_tab_model_and_post_action_presentation_evidence(self) -> None:
        result = successful_result()
        versions = result["versions"]
        assert isinstance(versions, dict)
        smoke.validate_result(result, expected_versions=versions)

    def test_rejects_missing_or_invalid_pointer_flow_evidence(self) -> None:
        for mutate, expression in (
            (
                lambda result: result["hostInput"].__setitem__("closedObserved", False),
                "closedObserved",
            ),
            (
                lambda result: result["hostInput"].__setitem__("frameIdAfterClose", 3),
                "ordered presentation",
            ),
            (
                lambda result: result["hostInput"].__setitem__(
                    "firstSelectedObserved", False
                ),
                "firstSelectedObserved",
            ),
            (
                lambda result: result["hostInput"].__setitem__(
                    "frameIdAfterSecondSelection", 3
                ),
                "ordered presentation",
            ),
            (
                lambda result: result["hostInput"]["pointerRecords"][1].__setitem__(
                    "trusted", False
                ),
                "trusted",
            ),
            (
                lambda result: result["hostInput"]["pointerRecords"].pop(),
                "exactly four pointer clicks",
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
                b'{"protocol":1,"protocol":1,"case":"browser_host_pointer_tabs_m6"}'
            )
        )


if __name__ == "__main__":
    unittest.main()
