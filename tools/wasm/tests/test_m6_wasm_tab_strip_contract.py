#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the bounded model-backed Wasm Views tab strip."""

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


class M6WasmTabStripContractTest(unittest.TestCase):
    def test_source_selection_is_a_small_views_observer_not_desktop_tabs(self) -> None:
        build = source("chrome/browser/wasm/BUILD.gn")
        target = source_set_body(build, "wasm_tab_strip")

        for required in (
            'visibility = [',
            '":wasm_browser_smoke",',
            '":wasm_browser_view",',
            '"wasm_tab_strip_view.h"',
            '"wasm_tab_strip_view.cc"',
            '":wasm_tab_core",',
            '":wasm_tab_features",',
            '"//chrome/browser/ui/browser_window",',
            '"//components/tabs:public",',
            '"//skia",',
            '"//ui/views",',
        ):
            with self.subTest(required=required):
                self.assertIn(required, target)

        for forbidden in (
            "//chrome/browser/ui:ui",
            "//chrome/browser/ui/views/tabs",
            "//chrome/browser/ui/views/toolbar",
            "//chrome/browser/ui/views/location_bar",
            "//components/omnibox",
            "//components/tab_groups",
            "//components/webui",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, target)

    def test_buttons_reflect_real_model_selection_and_title_lifetime(self) -> None:
        header = source("chrome/browser/wasm/wasm_tab_strip_view.h")
        implementation = source("chrome/browser/wasm/wasm_tab_strip_view.cc")

        for expected in (
            "class WasmTabStripView final",
            "public TabStripModelObserver",
            "tab_button_for_testing",
            "OnTabStripModelChanged",
            "OnTabWillBeRemoved",
            "OnTabStripModelDestroyed",
            "std::array<raw_ptr<views::LabelButton>, 2>",
            "std::array<base::CallbackListSubscription, 2>",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, header)

        for expected in (
            "constexpr int kWasmMaximumTabCount = 2;",
            "tab_strip_model_->AddObserver(this);",
            "tab_strip_model_->RemoveObserver(this);",
            "CHECK_LE(tab_strip_model_->count(), kWasmMaximumTabCount)",
            "TabUIHelper::From(tab)",
            "AddTabUIChangeCallback",
            "event.time_stamp()",
            "TabStripUserGestureDetails::GestureType::kMouse",
            "tab_strip_model_->ActivateTabAt(",
            "views::CreateRoundedRectBackground",
            "OnTabWillBeRemoved",
            "OnTabStripModelDestroyed",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, implementation)

        removal = implementation.index("void WasmTabStripView::OnTabWillBeRemoved")
        destruction = implementation.index(
            "void WasmTabStripView::OnTabStripModelDestroyed"
        )
        removal_body = implementation[removal:destruction]
        self.assertIn(
            "tab_ui_change_subscriptions_[index] = base::CallbackListSubscription();",
            removal_body,
        )
        self.assertIn("TabStripModel destroys TabFeatures", removal_body)

        for forbidden in (
            "CloseWebContentsAt(",
            "AppendWebContents(",
            "BrowserTabStripController",
            "TabDragController",
            "NewTabButton",
            "TabSearch",
            "ToolbarView",
            "LocationBarView",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, implementation)

    def test_browser_view_places_the_bounded_strip_above_content(self) -> None:
        header = source("chrome/browser/ui/views/frame/browser_view.h")
        view = source("chrome/browser/wasm/wasm_browser_view.cc")
        browser = source("chrome/browser/wasm/wasm_browser.cc")

        for expected in (
            "class WasmTabStripView;",
            "WasmTabStripView* wasm_tab_strip() const",
            "raw_ptr<WasmTabStripView> wasm_tab_strip_ = nullptr;",
            "int GetWasmTopChromeHeight() const;",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, header)

        for expected in (
            "std::make_unique<WasmTabStripView>(browser_window_interface)",
            "wasm_tab_strip_ = AddChildViewAt(std::move(tab_strip), 0);",
            "wasm_top_controls_ = AddChildViewAt(std::move(top_controls), 1);",
            "GetWasmTopChromeHeight()",
            "wasm_tab_strip_->GetPreferredSize().height()",
            "wasm_top_controls_->GetPreferredSize().height()",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, view)

        self.assertIn(
            "return window_ && GetBrowserView().wasm_tab_strip() != nullptr;",
            browser,
        )

    def test_smoke_uses_physical_button_events_and_records_the_marker(self) -> None:
        smoke = source("chrome/browser/wasm/wasm_browser_smoke.cc")
        runner = source("tools/wasm/run_m6_wasm_browser_smoke.py")

        for expected in (
            '"CHROMIUM_WASM_M6_TAB_STRIP:PASS"',
            "WasmTabStripView* const wasm_tab_strip",
            "browser_view.wasm_tab_strip()",
            "raw_browser->IsTabStripVisible()",
            "UserGestureTabSelectionObserver",
            "ClickButton(second_tab_button);",
            "ClickButton(first_tab_button);",
            "TabStripModelObserver::CHANGE_REASON_USER_GESTURE",
            'CHECK_EQ(first_tab_button->GetText(), u"wasm-top-controls-a");',
            'CHECK_EQ(first_tab_button->GetText(), u"wasm-top-controls-b");',
            "CHECK(second_tab_button->GetBackground());",
            "CHECK(!second_tab_button->GetVisible());",
            "std::puts(kTabStripSmokeMarker);",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, smoke)

        self.assertIn('TAB_STRIP_MARKER = "CHROMIUM_WASM_M6_TAB_STRIP:PASS"', runner)
        self.assertIn("missing its tab-strip marker", runner)


if __name__ == "__main__":
    unittest.main()
