#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the source-selected, Browser-owned Wasm window slice."""

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


def _wasm_branch(header: str) -> str:
    match = re.search(
        r"#if BUILDFLAG\(IS_WASM\)\n(?P<body>.*?)#else  // "
        r"BUILDFLAG\(IS_WASM\)",
        header,
        re.DOTALL,
    )
    if not match:
        raise AssertionError("could not find Wasm conditional header branch")
    return match.group("body")


class M6WasmBrowserContractTest(unittest.TestCase):
    def test_public_browser_header_selects_a_slim_wasm_owner(self) -> None:
        public_header = source("chrome/browser/ui/browser.h")
        wasm_header = source("chrome/browser/wasm/wasm_browser.h")
        wasm_branch = _wasm_branch(public_header)

        self.assertIn('#include "chrome/browser/wasm/wasm_browser.h"', wasm_branch)
        self.assertIn("class Browser final : public BrowserWindowInterface", wasm_header)
        for expected in (
            "struct CreateParams",
            "static Browser* Create(const CreateParams& params);",
            "static CreationStatus GetCreationStatusForProfile(Profile* profile);",
            "BrowserWindow* window() const",
            "TabStripModel* tab_strip_model() const",
            "BrowserView& GetBrowserView();",
            "void OnWindowClosing();",
            "Browser* GetBrowserForMigrationOnly() override;",
            "const Browser* GetBrowserForMigrationOnly() const override;",
            "std::unique_ptr<BrowserWindow, BrowserWindowDeleter> window_;",
            "std::unique_ptr<TabStripModelObserver> tab_strip_model_observer_;",
            "std::unique_ptr<WindowObserver> window_observer_;",
            "base::WeakPtrFactory<Browser> weak_ptr_factory_{this};",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, wasm_header)

        for forbidden in (
            "TabStripModelObserver,",
            "WebContentsCollection::Observer",
            "content::WebContentsDelegate",
            "BookmarkTabHelperObserver",
            "UnloadController",
            "BrowserTabStripModelDelegate",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, wasm_header)

    def test_browser_owns_factory_view_and_ordered_close(self) -> None:
        implementation = source("chrome/browser/wasm/wasm_browser.cc")

        initialization = (
            "std::make_unique<chrome::WasmTabBootstrapDelegate>(this)",
            "std::make_unique<TabStripModel>(",
            "tab_strip_model_->AddObserver(tab_strip_model_observer_.get());",
            "features_ = std::make_unique<BrowserWindowFeatures>();",
            "features_->Init(this);",
            "BrowserWindow::CreateBrowserWindow(this, params.user_gesture,",
            "browser_view.SetWasmCloseRequestCallback",
            "window_observer_->Observe(browser_view.GetWidget());",
            "features_->InitPostBrowserViewConstruction(&browser_view);",
        )
        positions = [implementation.index(item) for item in initialization]
        self.assertEqual(positions, sorted(positions))

        for expected in (
            "class Browser::TabStripModelObserver final",
            "class Browser::WindowObserver final",
            "const bool was_active = tab == tab_strip_model_->GetActiveTab();",
            "window_->OnTabDetached(tab->GetContents(), was_active);",
            "CHECK_LE(tab_strip_model_->count(), 2)",
            "Wasm Browser only closes its bounded two-tab model",
            "window_->OnActiveTabChanged(selection.old_contents, selection.new_contents,",
            "CHECK_EQ(selection.new_contents, tab_strip_model_->GetActiveWebContents());",
            "CHECK_NE(selection.old_contents, selection.new_contents);",
            "active_tab_changed_callbacks_.Notify(this);",
            "PostNonNestableTask(",
            "&Browser::FinishClose",
            "GetFeatures().TearDownPreBrowserWindowDestruction();",
            "window_observer_->Reset();",
            "window_.reset();",
            "NotifyBrowserDidClose();",
            "ScheduleManagerDeletion();",
            "&Browser::DeleteFromManager",
            "browser_manager->DeleteBrowser(this);",
            "if (!g_browser_process || g_browser_process->IsShuttingDown())",
            "return CreationStatus::kErrorShuttingDown;",
            "CHECK(params.initial_bounds.IsEmpty())",
            "CHECK_EQ(params.initial_show_state, ui::mojom::WindowShowState::kDefault)",
            "if (tab_strip_model_->empty()) {",
            "PostFinishClose();",
            "void Browser::PostFinishClose()",
            "CHECK(is_delete_scheduled_)",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, implementation)

        finish = implementation.index("void Browser::FinishClose()")
        finish_body = implementation[finish:implementation.index(
            "void Browser::NotifyBrowserDidClose()", finish
        )]
        ordered_finish = (
            "GetFeatures().TearDownPreBrowserWindowDestruction();",
            "features_torn_down_ = true;",
            "window_observer_->Reset();",
            "window_.reset();",
            "NotifyBrowserDidClose();",
            "ScheduleManagerDeletion();",
        )
        positions = [finish_body.index(item) for item in ordered_finish]
        self.assertEqual(positions, sorted(positions))

        for expected in (
            "return this;",
            "window_->GetWebContentsModalDialogHost();",
            "window_->GetWebContentsModalDialogHostFor(",
            'UnsupportedWasmBrowserOperation("BrowserWindowInterface OpenURL")',
            'UnsupportedWasmBrowserOperation("BrowserWindowInterface OpenGURL")',
            'UnsupportedWasmBrowserOperation("desktop browser capabilities")',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, implementation)

        for forbidden in (
            '#include "chrome/browser/ui/browser.cc"',
            "BrowserTabStripModelDelegate",
            "UnloadController",
            "CreateBrowserWindowNonAndroid",
            "features_->InitPostWindowConstruction(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, implementation)

    def test_smoke_and_build_closure_remain_explicit(self) -> None:
        build = source("chrome/browser/wasm/BUILD.gn")
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        smoke = source("chrome/browser/wasm/wasm_browser_smoke.cc")
        browser_target = _source_set_body(build, "wasm_browser")
        smoke_target = _source_set_body(build, "wasm_browser_smoke")

        for expected in (
            '"wasm_browser.h",',
            '"wasm_browser.cc"',
            '":wasm_browser_manager",',
            '":wasm_browser_process",',
            '":wasm_browser_window_factory",',
            '":wasm_browser_window_features",',
            '":wasm_tab_bootstrap_delegate",',
            '":wasm_tab_core",',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, browser_target)

        for forbidden in (
            "//chrome/browser/ui:ui",
            "../ui/browser.cc",
            "browser_tabstrip.cc",
            "unload_controller.cc",
            "create_browser_window_non_android.cc",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, browser_target)

        self.assertIn('":wasm_browser",', smoke_target)
        self.assertIn('":wasm_browser_smoke",', _source_set_body(
            build, "wasm_browser_main_parts"
        ))
        self.assertIn('"wasm-browser-smoke"', main_parts)
        self.assertIn("RunWasmBrowserSmoke(profile_.get())", main_parts)

        request = main_parts.index("void WasmBrowserMainParts::RequestShutdown")
        maybe_start = main_parts.index("void WasmBrowserMainParts::MaybeStartShutdown")
        request_body = main_parts[request:maybe_start]
        self.assertLess(
            request_body.index("shutdown_requested_ = true;"),
            request_body.index("browser_process_->EndSession();"),
        )
        shutdown = main_parts.index("void WasmBrowserMainParts::ShutdownFoundation")
        profile_shutdown = main_parts.index("profile_->Shutdown();", shutdown)
        process_end_session = main_parts.index(
            "browser_process_->EndSession();", shutdown
        )
        self.assertLess(process_end_session, profile_shutdown)

        for expected in (
            "Browser::Create(params)",
            "CloseEmptyBrowserForSmoke(profile, browser_manager, global_collection);",
            "void CloseEmptyBrowserForSmoke(",
            "tab_strip_model->AppendWebContents(std::move(first_contents)",
            "tab_strip_model->AppendWebContents(std::move(second_contents)",
            "tab_strip_model->ActivateTabAt(1);",
            "tab_strip_model->GetTabAtIndex(0)->Close();",
            "tab_strip_model->GetTabAtIndex(1)->Close();",
            "state.expected_active_contents.push_back(raw_second_contents);",
            "browser_view.Show();",
            "visible_run_loop.Run();",
            '"CHROMIUM_WASM_M6_BROWSER:READY"',
            "raw_browser->GetWindow()->Close();",
            "base::RunLoop().RunUntilIdle();",
            "CHECK(!weak_browser);",
            '"CHROMIUM_WASM_M6_BROWSER:PASS"',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, smoke)

        for forbidden in (
            "BrowserWindowModalDialogDelegate",
            "OpenURL(",
            "OpenGURL(",
            "Browser::CreateParams::CreateForApp",
            "chrome://settings",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, smoke)


if __name__ == "__main__":
    unittest.main()
