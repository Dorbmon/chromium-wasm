#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the switch-gated real-ownership Wasm tab-core slice."""

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


class M6WasmTabCoreContractTest(unittest.TestCase):
    def test_tab_model_attaches_real_wasm_helpers_before_features(self) -> None:
        model = source("chrome/browser/ui/tabs/tab_model.cc")

        helper = re.search(
            r"void PrepareWasmTabWebContents\(content::WebContents\* contents\) "
            r"\{(?P<body>.*?)\n\}",
            model,
            re.DOTALL,
        )
        self.assertIsNotNone(helper)
        body = helper.group("body")
        ordered = (
            "chrome::EnsureWasmSessionTabHelper(contents);",
            "ChromeSecurityStateTabHelper::CreateForWebContents(contents);",
            "web_modal::WebContentsModalDialogManager::CreateForWebContents(contents);",
        )
        positions = [body.index(item) for item in ordered]
        self.assertEqual(positions, sorted(positions))

        prepare = model.index("PrepareWasmTabWebContents(contents_);")
        lookup = model.index(
            "tabs::TabLookupFromWebContents::CreateForWebContents(contents_, this);"
        )
        features = model.index("tab_features_ = std::make_unique<TabFeatures>();")
        self.assertLess(prepare, lookup)
        self.assertLess(lookup, features)

        discard_prepare = model.index("PrepareWasmTabWebContents(contents.get());")
        discard_notify = model.index(
            "will_discard_contents_callback_list_.Notify(this, contents_, contents.get());"
        )
        self.assertLess(discard_prepare, discard_notify)
        self.assertNotRegex(
            model,
            r"(?<!Chrome)SecurityStateTabHelper::CreateForWebContents",
        )

    def test_wasm_model_disables_groups_and_limits_close_to_one_tab_with_an_explicit_unload_boundary(
        self,
    ) -> None:
        header = source("chrome/browser/ui/tabs/tab_strip_model.h")
        implementation = source("chrome/browser/wasm/wasm_tab_strip_model.cc")
        group_model = source("chrome/browser/wasm/wasm_tab_group_model.cc")

        self.assertIn("#if BUILDFLAG(IS_WASM)", header)
        self.assertIn("TabGroupModelFactory* group_model_factory = nullptr", header)
        self.assertIn("CHECK(!group_model_factory)", implementation)
        self.assertIn("does not support tab-group model construction", implementation)
        self.assertIn("CHECK(!group.has_value())", implementation)
        self.assertIn("does not support tab-group insertion", implementation)
        self.assertIn("CHECK(!closing_all_)", implementation)
        self.assertIn("does not insert tabs after CloseAllTabs", implementation)
        self.assertIn("CHECK_EQ(count(), 0)", implementation)
        self.assertIn("only supports its first tab insertion", implementation)
        self.assertIn("does not support pinned-tab insertion", implementation)
        self.assertIn("void TabStripModel::CloseWebContentsAt", implementation)
        self.assertIn("void TabStripModel::CloseAllTabs()", implementation)
        self.assertIn("Wasm tab core only supports closing its sole initial tab", implementation)
        self.assertIn(
            "does not support asynchronous beforeunload, unload", implementation
        )
        self.assertIn("ShouldRunUnloadListenerBeforeClosing(contents)", implementation)
        self.assertIn(
            "delegate_->ShouldRunUnloadListenerBeforeClosing(contents)",
            implementation,
        )
        self.assertIn("does not close an active modal dialog", implementation)
        self.assertIn("TabGroupModel::TabGroupModel() = default;", group_model)
        self.assertIn("TabGroupModel::~TabGroupModel() = default;", group_model)

    def test_insertion_preserves_real_collection_selection_and_modal_state(
        self,
    ) -> None:
        implementation = source("chrome/browser/wasm/wasm_tab_strip_model.cc")

        for expected in (
            "std::make_unique<tabs::TabStripCollection>(false)",
            "tab->OnAddedToModel(this);",
            "delegate()->WillAddWebContents(tab->GetContents());",
            "web_modal::WebContentsModalDialogManager::FromWebContents(",
            "CHECK(manager);",
            "tab->SetBlocked(manager->IsDialogActive());",
            "contents_data_->AddTabRecursive",
            "tab->DidInsert(base::PassKey<TabStripModel>());",
            "TabStripModelChange::Insert insert;",
            "OnChange(TabStripModelChange(std::move(insert)), selection);",
            "contents_data_->ValidateData();",
            "contents_data_->DispatchPendingNotifications();",
            "selection_state.SetSelectedTabs({tab}, tab, tab);",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, implementation)

        for forbidden in (
            "BrowserView",
            "BrowserWidget",
            "TabHelpers::AttachTabHelpers",
            "TabGroupModelFactory::GetInstance",
            "TabDialogManager",
            "constrained_window",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, implementation)

    def test_target_is_narrow_and_reached_only_by_the_smoke_owner(self) -> None:
        wasm_build = source("chrome/browser/wasm/BUILD.gn")
        target = _source_set_body(wasm_build, "wasm_tab_core")

        for expected in (
            '"../ui/tabs/tab_model.cc",',
            '"../ui/tabs/tab_strip_model_delegate.cc",',
            '"../ui/tabs/tab_strip_model_observer.cc",',
            '"../ui/tabs/tab_strip_model_selection_state.cc",',
            '"wasm_tab_group_model.cc",',
            '"wasm_tab_strip_model.cc",',
            '":wasm_chrome_security_state_tab_helper",',
            '":wasm_session_tab_helper",',
            '":wasm_tab_features",',
            '"//components/tabs",',
            '"//components/web_modal",',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, target)

        for forbidden in (
            '"//chrome/browser/ui:ui",',
            '"//chrome/browser/ui/tabs:impl",',
            '"//chrome/browser/ui/tabs:tab_strip",',
            '"//chrome/browser/ui/javascript_dialogs",',
            '"//chrome/browser/ui/web_modal",',
            '"//components/constrained_window",',
            '"//chrome/browser/sessions",',
            ":wasm_browser_window_features",
            ":wasm_browser_main_parts",
            ":wasm_browser_command_controller",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, target)

        self.assertEqual(1, wasm_build.count('":wasm_tab_core",'))
        self.assertIn(
            '":wasm_tab_core",',
            _source_set_body(wasm_build, "wasm_tab_core_smoke"),
        )
        self.assertNotIn(":wasm_tab_core", source("chrome/BUILD.gn"))


if __name__ == "__main__":
    unittest.main()
