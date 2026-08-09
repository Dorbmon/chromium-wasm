#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the switch-gated Wasm BrowserWindowInterface lifecycle probe."""

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


class M6WasmBrowserWindowCoreContractTest(unittest.TestCase):
    def test_core_owns_real_selected_bwi_prerequisites_only(self) -> None:
        header = source("chrome/browser/wasm/wasm_browser_window_core.h")
        implementation = source(
            "chrome/browser/wasm/wasm_browser_window_core.cc"
        )

        self.assertIn(
            "class WasmBrowserWindowCore final : public BrowserWindowInterface",
            header,
        )
        for member in (
            "ui::UnownedUserDataHost unowned_user_data_host_;",
            "std::unique_ptr<chrome::WasmTabBootstrapDelegate> tab_delegate_;",
            "std::unique_ptr<TabStripModel> tab_strip_model_;",
            "std::unique_ptr<TabStripModelObserver> tab_strip_model_observer_;",
            "std::unique_ptr<BrowserWindowFeatures> features_;",
            "raw_ptr<ui::BaseWindow> window_ = nullptr;",
            "bool features_torn_down_ = false;",
            "base::WeakPtrFactory<WasmBrowserWindowCore> "
            "weak_ptr_factory_{this};",
        ):
            with self.subTest(member=member):
                self.assertIn(member, header)

        self.assertIn(
            "void NotifyActiveTabDidChangeForWasmSmoke();", header
        )
        self.assertIn(
            "active_tab_changed_callbacks_.Notify(this);", implementation
        )
        self.assertIn(
            "raw_ptr<tabs::TabInterface> last_notified_active_tab_ = nullptr;",
            header,
        )
        self.assertIn(
            "CHECK_NE(active_tab, last_notified_active_tab_.get());",
            implementation,
        )
        for expected in (
            "BindWindowForWasmBrowserWindowViewSmoke",
            "InitPostBrowserViewConstructionForWasmBrowserWindowViewSmoke",
            "RequestCloseForWasmBrowserWindowViewSmoke",
            "UnbindWindowForWasmBrowserWindowViewSmoke",
            "OnWindowActivationChangedForWasmBrowserWindowViewSmoke",
            "ScheduleManagerDeletionForWasmBrowserWindowSmoke",
            "DeleteFromManagerForWasmBrowserWindowSmoke",
            "class WasmBrowserWindowCore::TabStripModelObserver final",
            "tab_strip_model_->AddObserver(tab_strip_model_observer_.get());",
            "contents_detached_callback_.Run(tab->GetContents()",
            "active_contents_changed_callback_.Run(",
            "tab_strip_model_->CloseAllTabs();",
            "FinishCloseForWasmBrowserWindowViewSmoke",
            "CHECK(close_requested_);",
            "CHECK(features_torn_down_);",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, implementation)

        order = (
            "std::make_unique<chrome::WasmTabBootstrapDelegate>(this)",
            "std::make_unique<TabStripModel>(",
            "features_ = std::make_unique<BrowserWindowFeatures>();",
            "features_->Init(this);",
        )
        positions = [implementation.index(item) for item in order]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("return TYPE_NORMAL;", implementation)
        self.assertIn("return window_.get();", implementation)
        self.assertIn("return GetFeatures().browser_actions();", implementation)
        self.assertIn("return tab_strip_model_->GetActiveTab();", implementation)
        self.assertIn("return false;", implementation)
        self.assertIn("if (!features_torn_down_)", implementation)

        # This core binds only a BaseWindow plus view-side callbacks. It must
        # not acquire Browser/View ownership or start browser navigation.
        for forbidden in (
            '#include "chrome/browser/ui/browser.h"',
            '#include "chrome/browser/ui/views/frame/browser_view.h"',
            "WebContents::Create",
            "Browser::Create",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, implementation)

        for operation in (
            "OpenURL navigation",
            "OpenGURL navigation",
            "a modal-dialog host",
            "a tab modal-dialog host",
            "Browser migration access",
            "desktop browser capabilities",
        ):
            with self.subTest(operation=operation):
                self.assertIn(
                    f'UnsupportedWasmBrowserWindowCoreOperation("{operation}")',
                    implementation,
                )

    def test_close_notification_precedes_async_owner_destruction(self) -> None:
        implementation = source(
            "chrome/browser/wasm/wasm_browser_window_core.cc"
        )
        smoke = source(
            "chrome/browser/wasm/wasm_browser_window_core_smoke.cc"
        )
        collection = source(
            "chrome/browser/wasm/wasm_global_browser_collection.cc"
        )

        self.assertIn("CHECK(tab_strip_model_->empty())", implementation)
        notify = implementation.index(
            "void WasmBrowserWindowCore::NotifyBrowserDidClose"
        )
        scheduled = implementation.index("is_delete_scheduled_ = true;", notify)
        callbacks = implementation.index(
            "browser_did_close_callbacks_.Notify(this);", notify
        )
        feature_phase = implementation.index(
            "CHECK(!browser_view_initialized_ || features_torn_down_);", notify
        )
        self.assertLess(feature_phase, scheduled)
        self.assertLess(scheduled, callbacks)

        destructor = implementation.index(
            "WasmBrowserWindowCore::~WasmBrowserWindowCore"
        )
        ordered_teardown = (
            "weak_ptr_factory_.InvalidateWeakPtrs();",
            "features_->TearDownPreBrowserWindowDestruction();",
            "features_.reset();",
            "tab_strip_model_observer_.reset();",
            "tab_strip_model_.reset();",
            "tab_delegate_.reset();",
        )
        positions = [
            implementation.index(item, destructor) for item in ordered_teardown
        ]
        self.assertEqual(positions, sorted(positions))

        self.assertIn("ui::BaseWindow* const window", collection)
        self.assertIn(
            "return (window && window->IsActive()) ? browser : nullptr;",
            collection,
        )

        close_entry = implementation.index(
            "void WasmBrowserWindowCore::CloseForWasmBrowserWindowCoreSmoke"
        )
        close_order = (
            "NotifyBrowserDidClose();",
            "if (weak_this) {",
            "ScheduleManagerDeletionForWasmBrowserWindowSmoke();",
        )
        close_positions = [implementation.index(item, close_entry) for item in close_order]
        self.assertEqual(close_positions, sorted(close_positions))

        schedule_entry = implementation.index(
            "void WasmBrowserWindowCore::ScheduleManagerDeletionForWasmBrowserWindowSmoke"
        )
        schedule_body = implementation[schedule_entry:]
        for expected in (
            "PostNonNestableTask(",
            "CHECK(base::SingleThreadTaskRunner::GetCurrentDefault()",
            "&WasmBrowserWindowCore::DeleteFromManagerForWasmBrowserWindowSmoke",
            "weak_ptr_factory_.GetWeakPtr()",
            "BrowserManagerServiceFactory::GetForProfile(profile_.get())",
            "browser_manager->DeleteBrowser(this);",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, schedule_body)

        smoke_order = (
            "browser_manager->AddBrowser(std::move(core));",
            "raw_core->CloseForWasmBrowserWindowCoreSmoke();",
            "CHECK(weak_core);",
            "base::RunLoop().RunUntilIdle();",
            "CHECK(!weak_core);",
        )
        add_browser = smoke.index(smoke_order[0])
        smoke_positions = [smoke.index(item, add_browser) for item in smoke_order]
        self.assertEqual(smoke_positions, sorted(smoke_positions))
        weak_capture = smoke.index(
            "base::WeakPtr<BrowserWindowInterface> weak_core = "
            "raw_core->GetWeakPtr();"
        )
        close_call = smoke.index("raw_core->CloseForWasmBrowserWindowCoreSmoke();")
        self.assertLess(weak_capture, close_call)
        self.assertIn(
            "base::SingleThreadTaskRunner::GetCurrentDefault()->PostTask(",
            smoke,
        )
        self.assertIn(
            "RequestReentrantBrowserWindowCoreDeletion", smoke
        )
        self.assertIn(
            "state->browser_manager->DeleteBrowser(browser);", smoke
        )
        self.assertIn(
            "base::RunLoop::Type::kNestableTasksAllowed", smoke
        )
        self.assertIn("nested_run_loop.RunUntilIdle();", smoke)
        self.assertIn("CHECK(state->weak_core);", smoke)
        self.assertIn("CloseReentrantBrowserWindowCore", smoke)
        self.assertIn("base::RunLoop reentrant_outer_run_loop;", smoke)
        self.assertIn("reentrant_outer_run_loop.Run();", smoke)
        self.assertIn(
            "CHECK(reentrant_deletion_state.nested_run_loop_completed);",
            smoke,
        )
        self.assertIn("CHECK(reentrant_deletion_state.delete_requested);", smoke)
        self.assertIn("CHECK(!weak_reentrant_core);", smoke)
        self.assertIn("CHECK(browser_manager->IsEmpty());", smoke)
        self.assertIn("CHECK(global_collection->IsEmpty());", smoke)
        tab_empty = implementation.index(
            "void WasmBrowserWindowCore::OnTabStripEmptyForWasmBrowserWindowViewSmoke"
        )
        self.assertIn("PostNonNestableTask(", implementation[tab_empty:])
        self.assertIn(
            '"CHROMIUM_WASM_M6_BROWSER_WINDOW_CORE:PASS"', smoke
        )
        self.assertIn("std::puts(kBrowserWindowCoreSmokeMarker);", smoke)

    def test_targets_and_switch_are_explicitly_smoke_only(self) -> None:
        wasm_build = source("chrome/browser/wasm/BUILD.gn")
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        core_target = _source_set_body(wasm_build, "wasm_browser_window_core")
        smoke_target = _source_set_body(
            wasm_build, "wasm_browser_window_core_smoke"
        )
        main_parts_target = _source_set_body(
            wasm_build, "wasm_browser_main_parts"
        )

        for expected in (
            '"wasm_browser_window_core.cc"',
            '"wasm_browser_window_core.h"',
            '":wasm_browser_manager",',
            '":wasm_browser_window_features",',
            '":wasm_tab_bootstrap_delegate",',
            '":wasm_tab_core",',
            '"//chrome/browser/ui/browser_window",',
            '"//components/sessions:session_id",',
            '"//ui/base/unowned_user_data",',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, core_target)

        for forbidden in (
            '"//chrome/browser/ui:ui",',
            '"//chrome/browser/ui/tabs:tab_strip",',
            '"//chrome/browser/ui/tabs:impl",',
            '"//chrome/browser/ui/javascript_dialogs",',
            '"//components/sessions",',
            '"//components/web_modal",',
            ":wasm_browser_view",
            ":wasm_browser_widget",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, core_target)

        for expected in (
            '"wasm_browser_window_core_smoke.cc"',
            '"wasm_browser_window_core_smoke.h"',
            '":wasm_browser_manager",',
            '":wasm_browser_window_core",',
            '":wasm_profile",',
            '":wasm_tab_core",',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, smoke_target)

        self.assertIn(
            '":wasm_browser_window_core_smoke",', main_parts_target
        )
        self.assertNotIn(
            '":wasm_browser_window_core",', main_parts_target
        )
        self.assertIn(
            '"wasm-browser-window-core-smoke"', main_parts
        )
        self.assertIn(
            "RunWasmBrowserWindowCoreSmoke(profile_.get())", main_parts
        )
        self.assertNotIn(
            ":wasm_browser_window_core", source("chrome/BUILD.gn")
        )


if __name__ == "__main__":
    unittest.main()
