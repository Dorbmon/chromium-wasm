#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the bounded, immediate Wasm tab-close primitive."""

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M6WasmTabCloseContractTest(unittest.TestCase):
    def test_close_is_bounded_two_tab_immediate_and_preserves_notification_lifetime(
        self,
    ) -> None:
        implementation = source("chrome/browser/wasm/wasm_tab_strip_model.cc")

        for expected in (
            "void TabStripModel::CloseWebContentsAt(int index, uint32_t close_types)",
            "CHECK_EQ(close_types, static_cast<uint32_t>(TabCloseTypes::CLOSE_NONE));",
            "CHECK(ContainsIndex(index));",
            "CHECK_LE(count(), kWasmMaximumTabCount);",
            "bounded two-tab model",
            "NeedToFireBeforeUnloadOrUnloadEvents()",
            "delegate_->ShouldRunUnloadListenerBeforeClosing(contents)",
            "does not support asynchronous beforeunload, unload",
            "WebContentsModalDialogManager::FromWebContents(contents)",
            "does not close an active modal dialog",
            "reentrancy_guard_ = true;",
            "const bool notify_close_all = !closing_all_ && count() == 1;",
            "observer.WillCloseAllTabs(this);",
            "tab->WillDetach(base::PassKey<TabStripModel>(),",
            "observer.OnTabWillBeRemoved(tab, index);",
            "tab->DestroyTabFeatures();",
            "contents_data_->RemoveTabAtIndexRecursive(index)",
            "detached_tab->OnRemovedFromModel();",
            "else if (tab == old_active_tab)",
            "SetSelectedTab(selection_model_,",
            "TabStripModelChange::Remove remove;",
            "OnChange(TabStripModelChange(std::move(remove)), selection);",
            "detached_tab.reset();",
            "if (empty()) {",
            "observer.TabStripEmpty();",
            "observer.CloseAllTabsStopped(",
            "TabStripModelObserver::kCloseAllCompleted",
            "void TabStripModel::CloseAllTabs()",
            "closing_all_ = true;",
            "const int index_to_close =",
            "while (!empty())",
            "if (!closing_all_ && tab == old_active_tab)",
            "if (!closing_all_ && tab->IsVisible())",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, implementation)

        for forbidden in (
            "TabCloseTypesData",
            "FastShutdownIfPossible",
            "CreateHistoricalTab",
            "browser_tabstrip",
            "UnloadController",
            "BrowserView",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, implementation)

    def test_tab_model_close_routes_to_the_selected_model_primitive(self) -> None:
        model = source("chrome/browser/ui/tabs/tab_model.cc")
        wasm_close = model.split("void TabModel::Close()", 1)[1].split("#else", 1)[0]

        self.assertIn("CHECK(owning_model_)", wasm_close)
        self.assertIn("owning_model_->GetIndexOfTab(this)", wasm_close)
        self.assertIn("owning_model_->CloseWebContentsAt", wasm_close)
        self.assertIn("TabCloseTypes::CLOSE_NONE", wasm_close)

    def test_runtime_smoke_checks_remove_before_destroy_and_empty_afterward(self) -> None:
        smoke = source("chrome/browser/wasm/wasm_tab_core_smoke.cc")

        for expected in (
            "class TabCoreSmokeCloseObserver final : public TabStripModelObserver",
            "TabStripModelChange::kRemoved",
            "remove->contents.front().contents, contents_",
            "CHECK_EQ(tab_strip_model->count(), 0);",
            "CHECK_EQ(selection.old_contents, contents_);",
            "CHECK(!selection.new_contents);",
            "TabCoreSmokeCloseObserver close_observer(raw_contents);",
            "tab_strip_model.GetTabAtIndex(0)->Close();",
            "close_observer.ExpectComplete();",
            "tab_strip_model.CloseAllTabs();",
            "close_all_observer.ExpectComplete();",
            "CHECK(tab_strip_model.empty());",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, smoke)

        for forbidden in (
            "Browser::Create",
            "BrowserView",
            "BrowserWidget",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, smoke)


if __name__ == "__main__":
    unittest.main()
