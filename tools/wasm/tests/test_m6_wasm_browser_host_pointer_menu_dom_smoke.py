#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for trusted DOM Menu -> Settings input through Chrome Wasm."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m6_wasm_browser_host_pointer_menu_dom_smoke as smoke
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
    menu_target = {"x": 618, "y": 48, "clientX": 635.5, "clientY": 65.5}
    settings_target = {"x": 218, "y": 110, "clientX": 235.5, "clientY": 127.5}
    records = [
        pointer_record("move", 618, 48, button=-1, buttons=0),
        pointer_record("down", 618, 48, button=0, buttons=1),
        pointer_record("up", 618, 48, button=0, buttons=0),
        pointer_record("move", 218, 110, button=-1, buttons=0),
        pointer_record("down", 218, 110, button=0, buttons=1),
        pointer_record("up", 218, 110, button=0, buttons=0),
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
            f"{smoke.READY_MARKER} x=618 y=48",
            f"{smoke.MENU_OPEN_MARKER} x=218 y=110",
            smoke.MENU_PRESENTED_MARKER,
            smoke.MENU_CLOSED_MARKER,
            smoke.SETTINGS_NAVIGATED_MARKER,
            smoke.PASS_MARKER,
        ],
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
        "hostInput": {
            "attached": True,
            "readyObserved": True,
            "menuOpenedObserved": True,
            "menuPresentedObserved": True,
            "menuClosedObserved": True,
            "settingsNavigatedObserved": True,
            "passObserved": True,
            "menuTarget": menu_target,
            "settingsTarget": settings_target,
            "frameIdAtMenuOpenedMarker": 1,
            "frameIdAfterMenuOpen": 2,
            "frameIdAtMenuClosedMarker": 2,
            "frameIdAfterSettingsClick": 3,
            "frameIdAtSettingsNavigatedMarker": 3,
            "frameIdAfterSettingsNavigation": 4,
            "menuCheckQueued": True,
            "menuPresentationQueued": True,
            "settingsCheckQueued": True,
            "settingsPresentationQueued": True,
            "pointerRecords": records,
            "settingsBootstrap": smoke.LIMITED_SETTINGS_BOOTSTRAP,
        },
    }


class M6WasmBrowserHostPointerMenuDomSmokeTest(unittest.TestCase):
    def test_host_uses_only_the_shared_pointer_adapter_and_deferred_verifier(self) -> None:
        normal_host = source("tools/wasm/host/chrome_wasm_host.js")
        menu_host = source(
            "tools/wasm/host/chrome_wasm_browser_host_pointer_menu_smoke_host.js"
        )
        for host in (normal_host, menu_host):
            self.assertIn(
                'import {ChromiumWasmTrustedPointerInput} from "./chrome_wasm_pointer_input.js";',
                host,
            )
            self.assertIn("new ChromiumWasmTrustedPointerInput", host)
        for expected in (
            "chromium_wasm_browser_host_pointer_menu_check",
            "chromium_wasm_browser_host_pointer_menu_presented",
            "setTimeout(() =>",
            "MENU_PRESENTED_MARKER",
            "SETTINGS_NAVIGATED_MARKER",
            "frameIdAfterMenuOpen",
            "frameIdAfterSettingsClick",
            "frameIdAfterSettingsNavigation",
            "LIMITED_SETTINGS_BOOTSTRAP",
            "awaiting-trusted-dom-menu",
            "awaiting-trusted-dom-settings",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, menu_host)
        self.assertNotIn('"chromium_wasm_browser_host_pointer",', menu_host)
        self.assertNotIn("location.assign", menu_host)
        self.assertNotIn("location.href", menu_host)

    def test_runner_uses_only_cdp_pointer_and_read_only_state(self) -> None:
        runner = source("tools/wasm/run_m6_wasm_browser_host_pointer_menu_dom_smoke.py")
        for expected in (
            "wait_for_page_client",
            "awaiting-trusted-dom-menu",
            "awaiting-trusted-dom-settings",
            "client.dispatch_primary_click",
            "--wasm-browser-host-pointer-menu-smoke",
            "chrome_wasm_pointer_input.js",
            "remote-debugging-port",
            "__chromiumWasmM6HostPointerMenuState",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, runner)
        self.assertNotIn("ccall(", runner)
        self.assertNotIn("Runtime.evaluate", runner)

    def test_cxx_verifier_is_ordinal_only_and_lifecycle_owns_ui_proof(self) -> None:
        verifier = source(
            "chrome/browser/wasm/wasm_browser_host_pointer_menu_smoke.cc"
        )
        lifecycle = source("chrome/browser/wasm/wasm_browser_lifecycle.cc")
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        for expected in (
            "kMenuCheck",
            "kMenuPresentation",
            "kSettingsCheck",
            "kSettingsPresentation",
            "generation_",
            "ClearCallbacksOnUiThread",
            "chromium_wasm_browser_host_pointer_menu_check",
            "chromium_wasm_browser_host_pointer_menu_presented",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, verifier)
        for forbidden in (
            "NavigationController",
            "WasmBrowserMenuView",
            "LoadURL",
            "BrowserView",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, verifier)
        for expected in (
            "StartHostPointerMenuSmoke",
            "GetHostPointerTarget(browser_view, menu_button)",
            "GetHostPointerTarget(browser_view, settings_button)",
            "PAGE_TRANSITION_GENERATED",
            "HasUserGesture()",
            "DidFirstVisuallyNonEmptyPaint",
            "DidStopLoading",
            "kHostPointerMenuSettingsTitle",
            "content::kChromeUIScheme",
            "GetAs<WasmSettingsUI>()",
            "MENU_PRESENTED",
            "ClearWasmBrowserHostPointerMenuSmokeVerificationForTesting",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, lifecycle)
        self.assertIn("wasm-browser-host-pointer-menu-smoke", main_parts)

    def test_html_has_one_status_node_and_uses_the_dedicated_host(self) -> None:
        html = source(
            "tools/wasm/host/chrome_wasm_browser_host_pointer_menu_smoke.html"
        )
        self.assertEqual(html.count('id="browser-host-pointer-menu-status"'), 1)
        self.assertIn("chrome_wasm_browser_host_pointer_menu_smoke_host.js", html)
        self.assertIn('id="browser-canvas"', html)

    def test_accepts_complete_menu_settings_and_frame_evidence(self) -> None:
        result = successful_result()
        versions = result["versions"]
        assert isinstance(versions, dict)
        smoke.validate_result(result, expected_versions=versions)

    def test_rejects_missing_or_invalid_pointer_menu_evidence(self) -> None:
        mutations = (
            (
                lambda result: result["hostInput"].__setitem__(
                    "menuPresentedObserved", False
                ),
                "menuPresentedObserved",
            ),
            (
                lambda result: result["hostInput"].__setitem__(
                    "frameIdAfterMenuOpen", 1
                ),
                "ordered presentation",
            ),
            (
                lambda result: result["hostInput"].__setitem__(
                    "settingsBootstrap", "desktop-settings"
                ),
                "limited Settings",
            ),
            (
                lambda result: result["hostInput"]["pointerRecords"][4].__setitem__(
                    "trusted", False
                ),
                "action 2 trusted",
            ),
            (
                lambda result: result["hostInput"].__setitem__(
                    "frameIdAtMenuClosedMarker", 1
                ),
                "did not wait for Menu presentation",
            ),
        )
        for mutate, expression in mutations:
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
                b'{"protocol":1,"protocol":1,"case":"browser_host_pointer_menu_settings_m6"}'
            )
        )


if __name__ == "__main__":
    unittest.main()
