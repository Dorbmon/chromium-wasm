#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the bounded Wasm Views navigation controls."""

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


class M6WasmTopControlsContractTest(unittest.TestCase):
    def test_source_selection_stays_narrow(self) -> None:
        build = source("chrome/browser/wasm/BUILD.gn")
        target = source_set_body(build, "wasm_top_controls")

        for required in (
            'visibility = [',
            '":wasm_browser_smoke",',
            '":wasm_browser_view",',
            '"wasm_top_controls_view.h"',
            '"wasm_top_controls_view.cc"',
            '":wasm_browser_command_controller",',
            '":wasm_tab_features",',
            '"//content/public/browser",',
            '"//ui/views",',
            '"//url",',
        ):
            with self.subTest(required=required):
                self.assertIn(required, target)

        for forbidden in (
            "//chrome/browser/ui:ui",
            "//chrome/browser/ui/views/toolbar",
            "//chrome/browser/ui/views/tabs",
            "//chrome/browser/ui/views/location_bar",
            "//components/omnibox",
            "//chrome/browser/history",
            "//components/webui",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, target)

    def test_controls_use_real_selected_navigation_and_reject_wider_routes(self) -> None:
        header = source("chrome/browser/wasm/wasm_top_controls_view.h")
        implementation = source("chrome/browser/wasm/wasm_top_controls_view.cc")

        for expected in (
            "class WasmTopControlsView final",
            "public views::TextfieldController",
            "public CommandObserver",
            "OnActiveWebContentsDetached",
            "address_field_for_testing",
            "back_button_for_testing",
            "forward_button_for_testing",
            "reload_button_for_testing",
            "stop_button_for_testing",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, header)

        for expected in (
            "RegisterActiveTabDidChange",
            "TabUIHelper::From(active_tab_)",
            "AddTabUIChangeCallback",
            "browser_command_controller_->AddCommandObserver(IDC_BACK, this)",
            "browser_command_controller_->AddCommandObserver(IDC_FORWARD, this)",
            "browser_command_controller_->AddCommandObserver(IDC_RELOAD, this)",
            "browser_command_controller_->AddCommandObserver(IDC_STOP, this)",
            "LoadURLWithParams(params)",
            "params.transition_type = ui::PAGE_TRANSITION_TYPED;",
            "params.has_user_gesture = true;",
            "address_field_->SetInvalid(true);",
            "url::kDataScheme",
            "url::kAboutBlankURL",
            "ClearActiveTab();",
            "address_field_->GetFocusManager()->ClearFocus();",
            "browser_command_controller_->RemoveCommandObserver(this);",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, implementation)

        for forbidden in (
            "ToolbarView",
            "LocationBarView",
            "Omnibox",
            "OpenURL(",
            "OpenGURL(",
            "chrome://",
            "javascript:",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, implementation)

    def test_browser_view_installs_and_detaches_controls_in_lifetime_order(self) -> None:
        browser = source("chrome/browser/wasm/wasm_browser.cc")
        view_header = source("chrome/browser/ui/views/frame/browser_view.h")
        view = source("chrome/browser/wasm/wasm_browser_view.cc")

        self.assertIn("InitializeWasmTopControls(", view_header)
        self.assertIn("WasmTopControlsView* wasm_top_controls() const", view_header)
        self.assertIn("std::make_unique<views::BoxLayout>(", view)
        self.assertIn("views::BoxLayout::Orientation::kVertical", view)
        self.assertIn("layout->SetFlexForView(contents_web_view_, 1", view)
        self.assertIn(
            "wasm_top_controls_->OnActiveWebContentsDetached(contents);", view
        )
        self.assertIn(
            "wasm_top_controls_->OnActiveWebContentsDetached(active_web_contents_);",
            view,
        )
        self.assertIn("wasm_top_controls_->GetPreferredSize().height()", view)

        feature_init = browser.index("features_->InitPostBrowserViewConstruction")
        top_controls_init = browser.index("browser_view.InitializeWasmTopControls")
        self.assertLess(feature_init, top_controls_init)


if __name__ == "__main__":
    unittest.main()
