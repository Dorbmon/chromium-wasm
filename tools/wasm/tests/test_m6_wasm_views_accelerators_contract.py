#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the bounded in-process Wasm Views accelerator routing."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def source_set_body(build_file: str, target: str) -> str:
    match = re.search(rf'\bsource_set\("{re.escape(target)}"\)', build_file)
    if not match:
        raise AssertionError(f"missing source set {target!r}")
    opening_brace = build_file.find("{", match.end())
    if opening_brace < 0:
        raise AssertionError(f"missing opening brace for {target!r}")
    depth = 0
    for index in range(opening_brace, len(build_file)):
        if build_file[index] == "{":
            depth += 1
        elif build_file[index] == "}":
            depth -= 1
            if depth == 0:
                return build_file[opening_brace + 1 : index]
    raise AssertionError(f"missing closing brace for {target!r}")


class M6WasmViewsAcceleratorsContractTest(unittest.TestCase):
    def test_view_routes_only_the_selected_visible_controls(self) -> None:
        header = source("chrome/browser/ui/views/frame/browser_view.h")
        view = source("chrome/browser/wasm/wasm_browser_view.cc")

        self.assertIn(
            "bool AcceleratorPressed(const ui::Accelerator& accelerator) override;",
            header,
        )
        self.assertIn("AddAccelerator(ui::Accelerator(ui::VKEY_L", view)
        self.assertIn("AddAccelerator(ui::Accelerator(ui::VKEY_R", view)
        self.assertIn("ui::VKEY_LEFT, ui::EF_ALT_DOWN", view)
        self.assertIn("ui::VKEY_RIGHT, ui::EF_ALT_DOWN", view)
        self.assertIn("ui::VKEY_TAB, ui::EF_CONTROL_DOWN", view)
        self.assertIn("bool BrowserView::AcceleratorPressed", view)

        for command in (
            "IDC_FOCUS_LOCATION",
            "IDC_RELOAD",
            "IDC_RELOAD_BYPASSING_CACHE",
            "IDC_BACK",
            "IDC_FORWARD",
            "IDC_SELECT_NEXT_TAB",
            "IDC_SELECT_PREVIOUS_TAB",
        ):
            with self.subTest(command=command):
                self.assertIn(command, view)

        for forbidden in (
            "BrowserCommandController::ExecuteCommand(",
            "BrowserTabStripController",
            "ToolbarView",
            "LocationBarView",
            "chrome://settings",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, view)

    def test_visible_controls_own_navigation_and_keyboard_tab_actions(self) -> None:
        controls = source("chrome/browser/wasm/wasm_top_controls_view.cc")
        tab_strip = source("chrome/browser/wasm/wasm_tab_strip_view.cc")

        for expected in (
            "FocusAddressFieldForAccelerator",
            "address_field_->RequestFocus();",
            "address_field_->SelectAll",
            "ExecuteNavigationCommandForAccelerator",
            "browser_command_controller_->ExecuteCommand(command_id, time_stamp)",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, controls)

        for expected in (
            "ActivateRelativeTabForAccelerator",
            "TabStripUserGestureDetails::GestureType::kKeyboard",
            "tab_strip_model_->ActivateTabAt(",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, tab_strip)

    def test_smoke_labels_widget_delivery_as_views_only(self) -> None:
        smoke = source("chrome/browser/wasm/wasm_browser_smoke.cc")
        runner = source("tools/wasm/run_m6_wasm_browser_smoke.py")

        self.assertIn("CHROMIUM_WASM_M6_VIEWS_ACCELERATORS:PASS", smoke)
        self.assertIn("Host DOM/Ozone delivery is a separate platform gate.", smoke)
        self.assertIn("widget->OnKeyEvent(&press);", smoke)
        self.assertIn(
            'VIEWS_ACCELERATORS_MARKER = "CHROMIUM_WASM_M6_VIEWS_ACCELERATORS:PASS"',
            runner,
        )

    def test_source_selection_stays_below_desktop_chrome_ui(self) -> None:
        build = source("chrome/browser/wasm/BUILD.gn")
        target = source_set_body(build, "wasm_browser_view")

        for required in (
            '"//chrome/app:command_ids",',
            '"//ui/events",',
            '":wasm_tab_strip",',
            '":wasm_top_controls",',
        ):
            with self.subTest(required=required):
                self.assertIn(required, target)

        for forbidden in (
            "//chrome/browser/ui:ui",
            "//chrome/browser/ui/views/toolbar",
            "//chrome/browser/ui/views/tabs",
            "//chrome/browser/ui/views/location_bar",
            "//components/omnibox",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, target)


if __name__ == "__main__":
    unittest.main()
