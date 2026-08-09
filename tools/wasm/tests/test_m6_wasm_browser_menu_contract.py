#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the bounded one-surface Wasm Browser menu."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def _source_set_body(build_file: str, target: str) -> str:
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


class M6WasmBrowserMenuContractTest(unittest.TestCase):
    def test_target_is_a_narrow_views_child_not_desktop_menu_ui(self) -> None:
        build = source("chrome/browser/wasm/BUILD.gn")
        target = _source_set_body(build, "wasm_browser_menu")

        for required in (
            'visibility = [',
            '":wasm_browser_view",',
            '":wasm_browser_smoke",',
            '"wasm_browser_menu.h"',
            '"wasm_browser_menu.cc"',
            '":wasm_browser_command_controller",',
            '"//chrome/browser/ui/browser_window",',
            '"//content/public/browser",',
            '"//ui/views",',
        ):
            with self.subTest(required=required):
                self.assertIn(required, target)

        for forbidden in (
            "//chrome/browser/ui:ui",
            "//chrome/browser/ui/toolbar",
            "//chrome/browser/ui/views/toolbar",
            "//chrome/browser/ui/views/tabs",
            "//ui/menus",
            "//components/omnibox",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, target)

    def test_menu_uses_selected_tab_and_real_command_paths(self) -> None:
        header = source("chrome/browser/wasm/wasm_browser_menu.h")
        implementation = source("chrome/browser/wasm/wasm_browser_menu.cc")

        for required in (
            "class WasmBrowserMenuView final : public views::View,",
            "public CommandObserver",
            "void Toggle();",
            "void Close();",
            "void ActiveTabChanged",
            "EnabledStateChangedForCommand",
            "base::CallbackListSubscription active_tab_changed_subscription_",
        ):
            with self.subTest(required=required):
                self.assertIn(required, header)

        for required in (
            "RegisterActiveTabDidChange",
            "AddCommandObserver(IDC_RELOAD, this)",
            "RemoveCommandObserver(this)",
            "browser_command_controller_->IsCommandEnabled(IDC_RELOAD)",
            "browser_command_controller_->ExecuteCommand(IDC_RELOAD",
            "void WasmBrowserMenuView::ActiveTabChanged",
            "Close();",
            "void WasmBrowserMenuView::EnabledStateChangedForCommand",
            "content::NavigationController::LoadURLParams params{GURL(url)};",
            "params.transition_type = ui::PAGE_TRANSITION_GENERATED;",
            "params.has_user_gesture = true;",
            "LoadURLWithParams(params)",
            'constexpr char kWasmVersionURL[] = "chrome://version/";',
            'constexpr char kWasmSettingsURL[] = "chrome://settings/";',
        ):
            with self.subTest(required=required):
                self.assertIn(required, implementation)

        for forbidden in (
            "MenuRunner",
            "SimpleMenuModel",
            "OpenURL(",
            "OpenGURL(",
            "AppMenu",
            "ToolbarView",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, implementation)

    def test_browser_view_closes_the_panel_before_tab_or_widget_teardown(self) -> None:
        view_header = source("chrome/browser/ui/views/frame/browser_view.h")
        view = source("chrome/browser/wasm/wasm_browser_view.cc")
        smoke = source("chrome/browser/wasm/wasm_browser_smoke.cc")

        self.assertIn("WasmBrowserMenuView* wasm_browser_menu() const", view_header)
        self.assertIn("std::make_unique<WasmBrowserMenuView>", view)
        self.assertIn("&WasmBrowserMenuView::Toggle", view)
        self.assertIn("wasm_browser_menu_->Close();", view)
        self.assertIn("wasm_browser_menu_->GetPreferredSize().height()", view)

        for required in (
            "ClickButton(menu_button);",
            "CHECK(browser_menu->IsOpen());",
            "CHECK(!browser_menu->IsOpen());",
            "ClickNavigationButtonAndWait(&navigation_observer, menu_reload_button,",
            '"CHROMIUM_WASM_M6_BROWSER_MENU:PASS"',
        ):
            with self.subTest(required=required):
                self.assertIn(required, smoke)


if __name__ == "__main__":
    unittest.main()
