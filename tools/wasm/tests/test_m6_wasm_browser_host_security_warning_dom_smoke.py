#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the trusted DOM security-warning child-dialog smoke."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m6_wasm_browser_host_security_warning_dom_smoke as smoke
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
    warning_target = {"x": 524, "y": 110, "clientX": 541.5, "clientY": 127.5}
    dismiss_target = {"x": 410, "y": 344, "clientX": 427.5, "clientY": 361.5}
    records = [
        pointer_record("down", 618, 48, button=0, buttons=1),
        pointer_record("up", 618, 48, button=0, buttons=0),
        pointer_record("down", 524, 110, button=0, buttons=1),
        pointer_record("up", 524, 110, button=0, buttons=0),
        pointer_record("down", 410, 344, button=0, buttons=1),
        pointer_record("up", 410, 344, button=0, buttons=0),
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
            f"{smoke.MENU_OPEN_MARKER} x=524 y=110",
            smoke.MENU_PRESENTED_MARKER,
            f"{smoke.DIALOG_OPEN_MARKER} x=410 y=344",
            f"{smoke.DIALOG_INTERACTION_READY_MARKER} x=410 y=344",
            smoke.DIALOG_DISMISSED_MARKER,
            smoke.PASS_MARKER,
        ],
        "frameReports": [
            {"id": 1, "width": 640, "height": 480, "timestampMs": 1.0},
            {"id": 2, "width": 640, "height": 480, "timestampMs": 2.0},
            {"id": 3, "width": 640, "height": 480, "timestampMs": 3.0},
            {"id": 4, "width": 640, "height": 480, "timestampMs": 4.0},
            {"id": 5, "width": 640, "height": 480, "timestampMs": 5.0},
            {"id": 6, "width": 640, "height": 480, "timestampMs": 6.0},
            {"id": 7, "width": 640, "height": 480, "timestampMs": 7.0},
            {"id": 8, "width": 640, "height": 480, "timestampMs": 8.0},
            {"id": 9, "width": 640, "height": 480, "timestampMs": 9.0},
            {"id": 10, "width": 640, "height": 480, "timestampMs": 10.0},
            {"id": 11, "width": 640, "height": 480, "timestampMs": 11.0},
            {"id": 12, "width": 640, "height": 480, "timestampMs": 12.0},
        ],
        "readiness": {
            "shellReady": True,
            "surfaceReady": True,
            # Generic Chrome FVP is intentionally not this dialog proof.
            "firstVisuallyNonEmptyPaint": False,
        },
        "readinessReports": [
            {
                "shellReady": True,
                "surfaceReady": True,
                "firstVisuallyNonEmptyPaint": False,
            }
        ],
        "ozoneFocusReports": [{"keyboardTargetPresent": True, "active": True}],
        "hostInput": {
            "attached": True,
            "readyObserved": True,
            "menuOpenedObserved": True,
            "menuPresentedObserved": True,
            "dialogOpenedObserved": True,
            "dialogInteractionReadyObserved": True,
            "dialogDismissedObserved": True,
            "passObserved": True,
            "menuTarget": menu_target,
            "warningTarget": warning_target,
            "dismissTarget": dismiss_target,
            "frameIdAtMenuOpenedMarker": 1,
            "frameIdAfterMenuOpen": 2,
            "frameIdAtWarningAction": 3,
            "frameIdAfterWarningAction": 4,
            "frameIdAtDialogOpenedMarker": 5,
            "frameIdAfterDialogOpen": 6,
            "frameIdAtDialogInteractionReadyMarker": 7,
            "frameIdAfterDialogInteractionReady": 8,
            "frameIdAtDismissAction": 9,
            "frameIdAfterDismissAction": 10,
            "frameIdAtDialogDismissedMarker": 11,
            "frameIdAfterDialogDismiss": 12,
            "menuCheckQueued": True,
            "menuPresentationQueued": True,
            "dialogCheckQueued": True,
            "dismissCheckQueued": True,
            "presentationQueued": True,
            "pointerRecords": records,
        },
    }


class M6WasmBrowserHostSecurityWarningDomSmokeTest(unittest.TestCase):
    def test_host_uses_only_shared_pointer_input_and_deferred_ordinals(self) -> None:
        normal_host = source("tools/wasm/host/chrome_wasm_host.js")
        dialog_host = source(
            "tools/wasm/host/chrome_wasm_browser_host_security_warning_smoke_host.js"
        )
        for host in (normal_host, dialog_host):
            self.assertIn(
                'import {ChromiumWasmTrustedPointerInput} from "./chrome_wasm_pointer_input.js";',
                host,
            )
            self.assertIn("new ChromiumWasmTrustedPointerInput", host)
        for expected in (
            "chromium_wasm_browser_host_security_warning_check",
            "chromium_wasm_browser_host_security_warning_presented",
            "setTimeout(() =>",
            "MENU_OPEN_MARKER",
            "MENU_PRESENTED_MARKER",
            "DIALOG_OPEN_MARKER",
            "DIALOG_INTERACTION_READY_MARKER",
            "DIALOG_DISMISSED_MARKER",
            "OBSERVATION_FAILED_MARKER",
            "frameIdAfterMenuOpen",
            "frameIdAfterDialogOpen",
            "frameIdAfterDialogInteractionReady",
            "frameIdAfterDialogDismiss",
            "awaiting-trusted-dom-security-warning",
            "awaiting-trusted-dom-dismiss",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, dialog_host)
        for forbidden in (
            '"chromium_wasm_browser_host_pointer",',
            "location.assign",
            "location.href",
            "window.open",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, dialog_host)

    def test_runner_uses_only_cdp_pointer_and_read_only_state(self) -> None:
        runner = source(
            "tools/wasm/run_m6_wasm_browser_host_security_warning_dom_smoke.py"
        )
        for expected in (
            "wait_for_page_client",
            "awaiting-trusted-dom-menu",
            "awaiting-trusted-dom-security-warning",
            "awaiting-trusted-dom-dismiss",
            "client.dispatch_primary_click",
            "--wasm-browser-host-security-warning-smoke",
            "chrome_wasm_pointer_input.js",
            "remote-debugging-port",
            "__chromiumWasmM6HostSecurityWarningState",
            "exactly three pointer clicks",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, runner)
        self.assertNotIn("ccall(", runner)
        self.assertNotIn("Runtime.evaluate", runner)

    def test_cxx_verifier_is_ordinal_only_and_lifecycle_owns_dialog_proof(self) -> None:
        verifier = source(
            "chrome/browser/wasm/wasm_browser_host_security_warning_smoke.cc"
        )
        lifecycle = source("chrome/browser/wasm/wasm_browser_lifecycle.cc")
        browser = source("chrome/browser/wasm/wasm_browser.cc")
        controller = source(
            "chrome/browser/wasm/wasm_browser_security_warning_dialog.cc"
        )
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        for expected in (
            "kMenuCheck",
            "kMenuPresentation",
            "kDialogCheck",
            "kDismissCheck",
            "kDismissPresentation",
            "generation_",
            "dispatch_pending_",
            "kMaxPostInputObservationFailures",
            "QueuePostInputObservation",
            "OBSERVATION_FAILED",
            "ClearCallbacksOnUiThread",
            "chromium_wasm_browser_host_security_warning_check",
            "chromium_wasm_browser_host_security_warning_presented",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, verifier)
        for forbidden in (
            "NavigationController",
            "BrowserView",
            "LoadURL",
            "WasmBrowserSecurityWarningDialog",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, verifier)
        for expected in (
            "StartHostSecurityWarningSmoke",
            "security_warning_button_for_testing",
            "dialog_widget_for_testing",
            "dismiss_button_for_testing",
            "IsAuraDescendantOf",
            "dialog_widget->GetClientContentsView()",
            "dismiss_button->GetWidget() == dialog_widget",
            "views::GetDoubleClickInterval()",
            "DIALOG_INTERACTION_READY",
            "OnHostSecurityWarningDialogInteractionReady",
            "modal_manager->IsDialogActive()",
            "tab_strip_model->IsTabBlocked(0)",
            "host_security_warning_blocked_state_change_count_ + 1",
            "host_security_warning_blocked_state_change_count_ + 2",
            "SchedulePaint",
            "ClearWasmBrowserHostSecurityWarningSmokeVerificationForTesting",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, lifecycle)
        self.assertIn("wasm-browser-host-security-warning-smoke", main_parts)
        self.assertIn("SetModalType(ui::mojom::ModalType::kChild)", controller)
        self.assertIn("ShowWebModalDialogViewsOwned", controller)
        self.assertIn("SetButtonLabel(ui::mojom::DialogButton::kOk, u\"Dismiss\")", controller)
        self.assertIn("Chromium Wasm runs browser and page code in one process", controller)
        self.assertIn("TabStripModelChange::kReplaced", controller)
        self.assertIn("GetIndexOfTab(blocked_tab_)", controller)
        self.assertNotIn("SK_ColorMAGENTA", controller)
        close_index = browser.index("CloseAllDialogsForBrowserClose();")
        tabs_index = browser.index("tab_strip_model_->CloseAllTabs();")
        self.assertLess(close_index, tabs_index)

    def test_html_has_one_status_node_and_uses_dedicated_host(self) -> None:
        html = source(
            "tools/wasm/host/chrome_wasm_browser_host_security_warning_smoke.html"
        )
        self.assertEqual(html.count('id="browser-host-security-warning-status"'), 1)
        self.assertIn(
            "chrome_wasm_browser_host_security_warning_smoke_host.js", html
        )
        self.assertIn('id="browser-canvas"', html)

    def test_accepts_complete_dialog_block_unblock_and_frame_evidence(self) -> None:
        result = successful_result()
        versions = result["versions"]
        assert isinstance(versions, dict)
        smoke.validate_result(result, expected_versions=versions)

    def test_accepts_action_recorded_in_the_prior_presented_frame(self) -> None:
        result = successful_result()
        host_input = result["hostInput"]
        assert isinstance(host_input, dict)
        # An input callback runs after the host consumed the prior frame, so
        # its snapshot may carry that frame's ID. Its own post-action frame is
        # still required to be strictly newer.
        host_input["frameIdAtWarningAction"] = 2
        host_input["frameIdAtDialogOpenedMarker"] = 4
        host_input["frameIdAtDismissAction"] = 8
        host_input["frameIdAtDialogDismissedMarker"] = 10
        versions = result["versions"]
        assert isinstance(versions, dict)
        smoke.validate_result(result, expected_versions=versions)

    def test_rejects_missing_or_invalid_dialog_evidence(self) -> None:
        mutations = (
            (
                lambda result: result["hostInput"].__setitem__(
                    "dialogOpenedObserved", False
                ),
                "dialogOpenedObserved",
            ),
            (
                lambda result: result["hostInput"].__setitem__(
                    "dialogInteractionReadyObserved", False
                ),
                "dialogInteractionReadyObserved",
            ),
            (
                lambda result: result["hostInput"].__setitem__(
                    "frameIdAfterDialogDismiss", 9
                ),
                "ordered presentation",
            ),
            (
                lambda result: result["hostInput"]["pointerRecords"][4].__setitem__(
                    "trusted", False
                ),
                "action 4 trusted",
            ),
            (
                lambda result: result["hostInput"].__setitem__(
                    "frameIdAtWarningAction", 1
                ),
                "did not wait for Menu presentation",
            ),
            (
                lambda result: result["hostInput"].__setitem__(
                    "frameIdAtDismissAction", 5
                ),
                "did not wait for dialog presentation",
            ),
            (
                lambda result: result["hostInput"].__setitem__(
                    "frameIdAtDismissAction", 7
                ),
                "did not wait for dialog interaction readiness",
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
                b'{"protocol":1,"protocol":1,"case":"browser_host_security_warning_m6"}'
            )
        )


if __name__ == "__main__":
    unittest.main()
