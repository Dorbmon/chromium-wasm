#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the opt-in Wasm BrowserWindowInterface/View smoke."""

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
        host_header = source(
            "chrome/browser/wasm/wasm_browser_window_view_host.h"
        )
        host_implementation = source(
            "chrome/browser/wasm/wasm_browser_window_view_host.cc"
        )

        self.assertIn(
            "bool RunWasmBrowserWindowViewSmoke(WasmProfile* profile);",
            header,
        )
        self.assertIn(
            "class WasmBrowserWindowViewHost final "
            ": public views::WidgetObserver",
            host_header,
        )
        self.assertIn("SetWasmCloseRequestCallbackForSmoke", host_implementation)
        self.assertIn("OnCloseRequested", host_implementation)
        self.assertIn(
            "return views::CloseRequestResult::kCannotClose;",
            host_implementation,
        )
        self.assertIn("if (close_requested_)", host_implementation)
        self.assertNotIn("MakeCloseSynchronous", host_implementation)
        self.assertIn("void OnContentsDetached(", host_header)
        self.assertIn("void OnActiveContentsChanged(", host_header)
        self.assertIn(
            "browser_view_->OnTabDetached(contents, was_active);",
            host_implementation,
        )
        self.assertIn("raw_ptr<BrowserView> browser_view = nullptr;", implementation)
        self.assertIn(
            "CHECK_EQ(state->browser_view->GetActiveWebContents(),",
            implementation,
        )

        core = source("chrome/browser/wasm/wasm_browser_window_core.cc")
        attach = host_implementation.index("browser_view_->OnActiveTabChanged(")
        detach = host_implementation.index(
            "browser_view_->OnTabDetached(contents, was_active);"
        )
        relay = core.index("NotifyActiveTabDidChangeForWasmSmoke();")
        core_attach = core.index("active_contents_changed_callback_.Run(")
        core_detach = core.index("contents_detached_callback_.Run(tab->GetContents()")
        self.assertLess(
            attach, host_implementation.index("++active_tab_change_count_")
        )
        self.assertLess(
            detach,
            host_implementation.index("detached_active_contents_ = true"),
        )
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
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, implementation)
        self.assertIn(
            "BrowserView::DestroyForWasmBrowserViewSmoke(browser_view_);",
            host_implementation,
        )
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
        host_implementation = source(
            "chrome/browser/wasm/wasm_browser_window_view_host.cc"
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
        destroy = host_implementation.index(
            "void WasmBrowserWindowViewHost::Destroy()"
        )
        host_order = (
            "core_->UnbindWindowForWasmBrowserWindowViewSmoke(browser_view_);",
            "widget_observation_.Reset();",
            "BrowserView::DestroyForWasmBrowserViewSmoke(browser_view_);",
        )
        positions = [
            host_implementation.index(item, destroy) for item in host_order
        ]
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
            "CHECK_EQ(state->view_host->close_request_count_for_testing(), 3);",
            "CHECK(state->tab_strip_model->empty());",
            "CHECK(state->view_host->detached_active_contents_for_testing());",
            "CHECK_EQ(state->view_host->active_tab_change_count_for_testing(), 2);",
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

    def test_selected_active_tab_navigation_is_bounded_and_real(self) -> None:
        header = source(
            "chrome/browser/wasm/wasm_browser_window_view_smoke.h"
        )
        implementation = source(
            "chrome/browser/wasm/wasm_browser_window_view_smoke.cc"
        )

        self.assertIn("two fixed data: documents", header)
        self.assertIn("OpenURL/OpenGURL boundary", header)
        self.assertIn("class ActiveTabNavigationObserver final", implementation)
        self.assertIn("kFirstNavigationUrl", implementation)
        self.assertIn("kSecondNavigationUrl", implementation)
        self.assertIn("data:text/html;base64,", implementation)
        self.assertIn("kBrowserWindowViewSmokeNavigationTimeout", implementation)
        self.assertIn("base::Seconds(5)", implementation)
        for expected in (
            "NavigationController::LoadURLParams",
            "LoadURLWithParams(params)",
            "DidFinishNavigation(",
            "IsInPrimaryMainFrame()",
            "HasCommitted()",
            "IsErrorPage()",
            "GetLastCommittedURL()",
            "DidStopLoading()",
            "if (!wait_quit_closure_) {",
            "std::move(wait_quit_closure_).Run();",
            "raw_core->GetFeatures().browser_command_controller()",
            "CheckSelectedTabRemainsBound(",
            "CHECK_EQ(navigation_observer.completed_navigation_count(), 5);",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, implementation)

        # The observer must tolerate the finish/stop/timeout ordering without
        # attempting to run its OnceClosure twice.
        finish_wait = implementation.index("void FinishNavigationWait() {")
        self.assertLess(
            implementation.index("if (!wait_quit_closure_) {", finish_wait),
            implementation.index(
                "std::move(wait_quit_closure_).Run();", finish_wait
            ),
        )

        for expected in (
            "IDC_BACK",
            "IDC_FORWARD",
            "IDC_RELOAD",
            "IDC_RELOAD_BYPASSING_CACHE",
            "IDC_STOP",
            "navigation_controller.CanGoBack()",
            "navigation_controller.CanGoForward()",
            "command_controller->IsCommandEnabled(IDC_BACK)",
            "command_controller->IsCommandEnabled(IDC_FORWARD)",
            "command_controller->IsCommandEnabled(IDC_RELOAD)",
            "command_controller->IsCommandEnabled(IDC_STOP)",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, implementation)

        navigation_start = implementation.index(
            "const GURL first_navigation_url(kFirstNavigationUrl);"
        )
        first_load = implementation.index(
            "LoadCurrentTabAndWait(", navigation_start
        )
        second_load = implementation.index(
            "LoadCurrentTabAndWait(", first_load + 1
        )
        back = implementation.index(
            "ExecuteCurrentTabNavigationCommandAndWait(", second_load
        )
        forward = implementation.index(
            "ExecuteCurrentTabNavigationCommandAndWait(", back + 1
        )
        reload = implementation.index(
            "ExecuteCurrentTabNavigationCommandAndWait(", forward + 1
        )
        self.assertEqual(
            [first_load, second_load, back, forward, reload],
            sorted([first_load, second_load, back, forward, reload]),
        )
        for position, expected in (
            (first_load, "first_navigation_url"),
            (second_load, "second_navigation_url"),
            (back, "IDC_BACK"),
            (forward, "IDC_FORWARD"),
            (reload, "IDC_RELOAD"),
        ):
            with self.subTest(position=position, expected=expected):
                self.assertIn(expected, implementation[position : position + 220])

        bound_state = implementation.index("void CheckSelectedTabRemainsBound(")
        for expected in (
            "CHECK_EQ(tab_strip_model->count(), 1);",
            "CHECK_EQ(active_tab->GetContents(), expected_contents);",
            "CHECK_EQ(browser_view->GetActiveWebContents(), expected_contents);",
            "CHECK_EQ(view_host->active_tab_change_count_for_testing(), 1);",
            "CHECK_EQ(relay_state->notification_count, 1);",
            "CHECK(!modal_manager->IsDialogActive());",
            "CHECK(!tab_strip_model->IsTabBlocked(0));",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, implementation[bound_state:])

    def test_switch_local_modal_manager_clears_blocking_before_tab_close(
        self,
    ) -> None:
        header = source(
            "chrome/browser/wasm/wasm_browser_window_view_smoke.h"
        )
        implementation = source(
            "chrome/browser/wasm/wasm_browser_window_view_smoke.cc"
        )

        self.assertIn(
            "temporarily drives one state-only WebContentsModalDialogManager",
            header,
        )
        for expected in (
            "class LocalWcmdmDelegate final",
            "class ControlledSingleWebContentsDialogManager final",
            "browser_view_->GetWebContentsModalDialogHostFor(web_contents)",
            "tab_strip_model_->SetTabBlocked(index, blocked);",
            "const gfx::NativeWindow dialog = browser_view->GetNativeWindow();",
            "modal_manager->ShowDialogWithManager(",
            "raw_dialog_manager->Close();",
            "modal_manager->SetDelegate(nullptr);",
            "CHECK(!modal_manager->IsDialogActive());",
            "CHECK(!tab_strip_model->IsTabBlocked(0));",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, implementation)

        modal_proof = implementation.index(
            "void ExerciseWasmModalManagerState("
        )
        close = implementation.index(
            "raw_dialog_manager->Close();", modal_proof
        )
        clear_delegate = implementation.index(
            "modal_manager->SetDelegate(nullptr);", close
        )
        close_setup = implementation.index(
            "NestedTabStripEmptyState", clear_delegate
        )
        self.assertLess(modal_proof, close)
        self.assertLess(close, clear_delegate)
        self.assertLess(clear_delegate, close_setup)

        # The controlled manager drives real WCMDM state only. This focused
        # smoke must not grow a production modal pipeline or create child UI.
        for forbidden in (
            "Browser::Create",
            "BrowserWindowModalDialogDelegate",
            "constrained_window",
            "views::Widget::InitParams",
            "new views::Widget",
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
            '":wasm_browser_command_controller",',
            '":wasm_browser_window_features",',
            '":wasm_browser_window_view_host",',
            '":wasm_tab_core",',
            '"//chrome/app:command_ids",',
            '"//components/web_modal",',
            '"//content/public/browser",',
            '"//url",',
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
