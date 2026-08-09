#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the opt-in Wasm BrowserWindowInterface/View relay smoke."""

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


class M6WasmBrowserWindowViewSmokeContractTest(unittest.TestCase):
    def test_relay_attaches_before_active_callback_and_detaches_before_destroy(
        self,
    ) -> None:
        header = source(
            "chrome/browser/wasm/wasm_browser_window_view_smoke.h"
        )
        implementation = source(
            "chrome/browser/wasm/wasm_browser_window_view_smoke.cc"
        )

        self.assertIn(
            "bool RunWasmBrowserWindowViewSmoke(WasmProfile* profile);",
            header,
        )
        self.assertIn(
            "class WasmBrowserWindowViewSmokeAdapter final "
            ": public views::WidgetObserver",
            implementation,
        )
        self.assertIn("SetWasmCloseRequestCallbackForSmoke", implementation)
        self.assertIn("OnCloseRequested", implementation)
        self.assertIn("return views::CloseRequestResult::kCannotClose;", implementation)
        self.assertIn("if (!close_requested_)", implementation)
        self.assertNotIn("MakeCloseSynchronous", implementation)
        self.assertIn("void OnContentsDetached(", implementation)
        self.assertIn("void OnActiveContentsChanged(", implementation)
        self.assertIn(
            "browser_view_->OnTabDetached(contents, was_active);",
            implementation,
        )
        self.assertIn("raw_ptr<BrowserView> browser_view = nullptr;", implementation)
        self.assertIn(
            "CHECK_EQ(state->browser_view->GetActiveWebContents(),",
            implementation,
        )

        core = source("chrome/browser/wasm/wasm_browser_window_core.cc")
        attach = implementation.index("browser_view_->OnActiveTabChanged(")
        detach = implementation.index(
            "browser_view_->OnTabDetached(contents, was_active);"
        )
        relay = core.index("NotifyActiveTabDidChangeForWasmSmoke();")
        core_attach = core.index("active_contents_changed_callback_.Run(")
        core_detach = core.index("contents_detached_callback_.Run(tab->GetContents()")
        self.assertLess(attach, implementation.index("++active_tab_change_count_"))
        self.assertLess(detach, implementation.index("detached_active_contents_ = true"))
        self.assertLess(core_attach, relay)
        self.assertLess(core_detach, core_attach)
        self.assertIn(
            "CHECK_NE(active_tab, last_notified_active_tab_.get());",
            core,
        )

        for expected in (
            "tab_strip_model->AppendWebContents(std::move(contents),",
            "web_modal::WebContentsModalDialogManager::FromWebContents(",
            "CHECK(!modal_manager->IsDialogActive());",
            "RecordActiveTabChange",
            "state->core->GetWindow()->Close();",
            "state->browser_view->GetWidget()->Close();",
            "BrowserView::DestroyForWasmBrowserViewSmoke(browser_view_);",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, implementation)
        for expected in (
            "RequestCloseForWasmBrowserWindowViewSmoke",
            "CloseAllTabs();",
            "CHECK(!window_);",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, core)

    def test_close_hook_keeps_view_dependent_features_alive_until_detach(self) -> None:
        implementation = source(
            "chrome/browser/wasm/wasm_browser_window_view_smoke.cc"
        )
        core = source("chrome/browser/wasm/wasm_browser_window_core.cc")

        detach = core.index("contents_detached_callback_.Run(tab->GetContents()")
        active = core.index("active_contents_changed_callback_.Run(")
        self.assertLess(detach, active)
        finish = core.index(
            "void WasmBrowserWindowCore::FinishCloseForWasmBrowserWindowViewSmoke"
        )
        ordered_finish = (
            "GetFeatures().TearDownPreBrowserWindowDestruction();",
            "features_torn_down_ = true;",
            "std::move(destroy_window_callback_).Run();",
            "CHECK(!window_);",
            "NotifyBrowserDidClose();",
            "ScheduleManagerDeletionForWasmBrowserWindowSmoke();",
        )
        positions = [core.index(item, finish) for item in ordered_finish]
        self.assertEqual(positions, sorted(positions))
        destroy = implementation.index("void Destroy() {")
        adapter_order = (
            "core_->UnbindWindowForWasmBrowserWindowViewSmoke(browser_view_);",
            "widget_observation_.Reset();",
            "BrowserView::DestroyForWasmBrowserViewSmoke(browser_view_);",
        )
        positions = [implementation.index(item, destroy) for item in adapter_order]
        self.assertEqual(positions, sorted(positions))
        weak_capture = implementation.index(
            "base::WeakPtr<BrowserWindowInterface> weak_core = "
            "raw_core->GetWeakPtr();"
        )
        close_task = implementation.index("void RequestBoundCoreClose(")
        self.assertEqual(
            implementation.count("state->core->GetWindow()->Close();"), 2
        )
        close_dispatch = implementation.index("close_outer_run_loop.Run();")
        self.assertLess(weak_capture, close_dispatch)
        close_order = (
            "state->core->GetWindow()->Close();",
            "state->browser_view->GetWidget()->Close();",
            "state->core->GetWindow()->Close();",
            "CHECK_EQ(state->adapter->close_request_count(), 3);",
            "CHECK(state->tab_strip_model->empty());",
            "CHECK(state->adapter->detached_active_contents());",
            "CHECK_EQ(state->adapter->active_tab_change_count(), 2);",
            "CHECK_EQ(state->relay_state->notification_count, 2);",
            "CHECK(!state->relay_state->last_contents);",
            "CHECK(!state->browser_view->GetActiveWebContents());",
            "CHECK_EQ(state->browser_manager->GetSize(), 1u);",
            "CHECK_EQ(state->global_collection->GetSize(), 1u);",
            "state->tab_strip_model->RemoveObserver(",
            "state->outer_run_loop->QuitWhenIdle();",
        )
        positions = []
        cursor = close_task
        for item in close_order:
            position = implementation.index(item, cursor)
            positions.append(position)
            cursor = position + len(item)
        self.assertEqual(positions, sorted(positions))
        self.assertIn(
            "class NestedTabStripEmptyObserver final", implementation
        )
        self.assertIn(
            "base::RunLoop::Type::kNestableTasksAllowed", implementation
        )
        self.assertIn("nested_run_loop.RunUntilIdle();", implementation)
        self.assertIn(
            "CHECK_EQ(state_->core->GetWindow(), state_->browser_view);",
            implementation,
        )
        self.assertIn("base::RunLoop close_outer_run_loop;", implementation)
        self.assertIn("close_outer_run_loop.Run();", implementation)
        self.assertIn("CHECK(!weak_core);", implementation)
        self.assertNotIn("DeferredDeletionState", implementation)
        self.assertNotIn("RequestDeferredBrowserDeletion", implementation)
        self.assertIn(
            '"CHROMIUM_WASM_M6_BROWSER_WINDOW_VIEW"', implementation
        )
        self.assertIn('std::fprintf(stderr, "%s:PASS\\n",', implementation)

        # The smoke validates a real model/view bridge, not Browser startup or
        # a partial window lifecycle that claims unsupported routes worked.
        for forbidden in (
            "Browser::Create",
            "BrowserWindowModalDialogDelegate",
            "OpenURL(",
            "OpenGURL(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, implementation)

    def test_target_and_switch_are_smoke_only(self) -> None:
        wasm_build = source("chrome/browser/wasm/BUILD.gn")
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        chrome_build = source("chrome/BUILD.gn")
        target = _source_set_body(wasm_build, "wasm_browser_window_view_smoke")
        main_parts_target = _source_set_body(
            wasm_build, "wasm_browser_main_parts"
        )

        for expected in (
            '"wasm_browser_window_view_smoke.cc"',
            '":wasm_browser_window_core",',
            '":wasm_browser_view",',
            '":wasm_browser_widget",',
            '":wasm_browser_window_features",',
            '":wasm_tab_core",',
            '"//components/web_modal",',
            '"//content/public/browser",',
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
            ":wasm_browser_main_parts",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, target)

        self.assertIn('":wasm_browser_window_view_smoke",', main_parts_target)
        self.assertNotIn(":wasm_browser_window_view_smoke", chrome_build)
        self.assertIn(
            '"wasm-browser-window-view-smoke"', main_parts
        )
        self.assertIn(
            "RunWasmBrowserWindowViewSmoke(profile_.get())", main_parts
        )


if __name__ == "__main__":
    unittest.main()
