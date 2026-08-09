#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the bounded, process-local Wasm tab-core smoke."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def _source_set_body(build_file: str, target: str) -> str:
    match = re.search(
        rf'\bsource_set\s*\(\s*"{re.escape(target)}"\s*\)', build_file
    )
    if not match:
        raise AssertionError(f"could not find source set {target!r}")

    opening_brace = build_file.find("{", match.end())
    if opening_brace == -1:
        raise AssertionError(f"source set {target!r} has no opening brace")

    depth = 0
    for index in range(opening_brace, len(build_file)):
        if build_file[index] == "{":
            depth += 1
        elif build_file[index] == "}":
            depth -= 1
            if depth == 0:
                return build_file[opening_brace + 1 : index]
    raise AssertionError(f"source set {target!r} has no closing brace")


class M6WasmTabCoreSmokeContractTest(unittest.TestCase):
    def test_smoke_constructs_one_real_tab_with_the_required_helpers(self) -> None:
        header = source("chrome/browser/wasm/wasm_tab_core_smoke.h")
        implementation = source("chrome/browser/wasm/wasm_tab_core_smoke.cc")

        self.assertIn("bool RunWasmTabCoreSmoke(WasmProfile* profile);", header)
        for expected in (
            "CHECK_CURRENTLY_ON(content::BrowserThread::UI);",
            "content::WebContents::CreateParams create_params(profile);",
            "content::WebContents::Create(create_params)",
            "TabStripModel tab_strip_model(&delegate, profile,",
            "/*group_model_factory=*/nullptr",
            "tab_strip_model.AppendWebContents(std::move(contents), /*foreground=*/true);",
            "CHECK_EQ(tab_strip_model.count(), 1);",
            "CHECK_EQ(tab_strip_model.active_index(), 0);",
            "CHECK_EQ(tab_strip_model.GetActiveWebContents(), raw_contents);",
            "CHECK(tab_strip_model.IsTabSelected(0));",
            "CHECK(tab_strip_model.IsTabInForeground(0));",
            "GetWasmSessionTabId(raw_contents)",
            "CHECK(session_tab_id.is_valid());",
            "static_cast<ChromeSecurityStateTabHelper*>(",
            "CHECK(chrome_security_state_helper->uses_embedder_information().value());",
            "WebContentsModalDialogManager::FromWebContents(raw_contents)",
            "CHECK(!modal_manager->IsDialogActive());",
            '"CHROMIUM_WASM_M6_TAB_CORE"',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, implementation)

    def test_delegate_has_no_fake_browser_window_or_unsupported_success(self) -> None:
        implementation = source("chrome/browser/wasm/wasm_tab_core_smoke.cc")

        self.assertIn("class TabCoreSmokeDelegate final : public TabStripModelDelegate", implementation)
        self.assertIn("void WillAddWebContents(content::WebContents* contents) override", implementation)
        self.assertIn("CHECK_EQ(contents->GetBrowserContext(), profile_);", implementation)
        self.assertIn("UnsupportedTabCoreSmokeDelegateOperation", implementation)
        self.assertIn("BrowserWindowInterface access", implementation)
        self.assertIn("browser-window type query", implementation)
        self.assertNotIn('#include "chrome/browser/ui/browser.h"', implementation)
        self.assertNotIn('#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"', implementation)
        self.assertNotIn("Browser::Create", implementation)
        self.assertNotIn("BrowserView", implementation)
        self.assertNotIn("BrowserWidget", implementation)

    def test_switch_is_opt_in_and_normal_lifecycle_follows(self) -> None:
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")

        switch = 'constexpr char kWasmTabCoreSmokeSwitch[] = "wasm-tab-core-smoke";'
        self.assertIn(switch, main_parts)
        switch_index = main_parts.index(switch)
        run_index = main_parts.index("chrome::RunWasmTabCoreSmoke(profile_.get())")
        shutdown_index = main_parts.index("RequestShutdown();", run_index)
        normal_lifecycle_index = main_parts.index(
            "InitializeWasmBrowserHostLifecycle("
        )
        normal_ready_index = main_parts.index(
            "std::fprintf(stderr, \"%s\\n\", kWasmNormalBrowserReadyMarker);",
            normal_lifecycle_index,
        )
        self.assertLess(switch_index, run_index)
        self.assertLess(run_index, shutdown_index)
        self.assertLess(shutdown_index, normal_lifecycle_index)
        self.assertLess(normal_lifecycle_index, normal_ready_index)

    def test_build_owner_is_narrow_and_not_a_browser_ui_target(self) -> None:
        wasm_build = source("chrome/browser/wasm/BUILD.gn")
        chrome_build = source("chrome/BUILD.gn")
        smoke = _source_set_body(wasm_build, "wasm_tab_core_smoke")
        main_parts = _source_set_body(wasm_build, "wasm_browser_main_parts")

        for expected in (
            '"wasm_tab_core_smoke.cc"',
            '":wasm_tab_core",',
            '":wasm_profile",',
            '":wasm_session_tab_helper",',
            '":wasm_chrome_security_state_tab_helper",',
            '"//components/web_modal",',
            '"//content/public/browser",',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, smoke)

        for forbidden in (
            '"//chrome/browser/ui:ui",',
            '"//chrome/browser/ui/tabs:tab_strip",',
            '"//ui/views",',
            ":wasm_browser_ui",
            ":wasm_browser_window_features",
            ":wasm_browser_command_controller",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, smoke)

        self.assertIn('":wasm_tab_core_smoke",', main_parts)
        self.assertNotIn('":wasm_tab_core",', main_parts)
        self.assertNotIn(":wasm_tab_core", chrome_build)


if __name__ == "__main__":
    unittest.main()
