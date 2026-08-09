#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the bounded persistent slim Browser lifecycle."""

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


class M6WasmBrowserLifecycleContractTest(unittest.TestCase):
    def test_lifecycle_retains_browser_until_manager_physical_destruction(
        self,
    ) -> None:
        header = source("chrome/browser/wasm/wasm_browser_lifecycle.h")
        implementation = source("chrome/browser/wasm/wasm_browser_lifecycle.cc")

        for expected in (
            "class WasmBrowserLifecycle final",
            "void Initialize();",
            "void BeginShutdown();",
            "void OnBrowserDidClose(BrowserWindowInterface* browser);",
            "void ArmBrowserDestructionBarrier();",
            "void OnBrowserDestructionsComplete();",
            "base::WeakPtr<Browser> browser_;",
            "base::CallbackListSubscription browser_did_close_subscription_;",
            "base::OnceClosure shutdown_complete_callback_;",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, header)

        ordered_initialization = (
            "Browser* const raw_browser = Browser::Create(create_params);",
            "browser_ = raw_browser->AsWeakPtr();",
            "raw_browser->RegisterBrowserDidClose(",
            "content::WebContents::Create(contents_params);",
            "tab_strip_model->AppendWebContents(std::move(contents), /*foreground=*/true);",
            "browser_view.SetBounds(kBrowserLifecycleSmokeBounds);",
            "browser_view.Show();",
            "initialized_ = true;",
        )
        positions = [implementation.index(item) for item in ordered_initialization]
        self.assertEqual(positions, sorted(positions))

        for expected in (
            "browser_->GetWindow()->Close();",
            "shutdown_started_ = true;",
            "browser_manager_->RunWhenBrowserDestructionsCompleteForWasm(",
            "CHECK(!browser_);",
            "CHECK(browser_manager_->IsEmpty());",
            "CHECK(global_collection->IsEmpty());",
            "std::move(shutdown_complete_callback_).Run();",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, implementation)

        did_close = implementation.index("void WasmBrowserLifecycle::OnBrowserDidClose")
        barrier = implementation.index(
            "void WasmBrowserLifecycle::ArmBrowserDestructionBarrier"
        )
        completion = implementation.index(
            "void WasmBrowserLifecycle::OnBrowserDestructionsComplete"
        )
        self.assertLess(did_close, barrier)
        self.assertLess(barrier, completion)

        for forbidden in (
            "BrowserWindowModalDialogDelegate",
            "OpenURL(",
            "OpenGURL(",
            "CreateBrowserWindowNonAndroid",
            "BrowserTabStripModelDelegate",
            "UnloadController",
            "WasmBrowserWindowViewHost",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, implementation)

    def test_main_parts_owns_both_smoke_and_normal_lifecycle_modes(self) -> None:
        header = source("chrome/browser/wasm/wasm_browser_main_parts.h")
        implementation = source("chrome/browser/wasm/wasm_browser_main_parts.cc")

        for expected in (
            "class WasmBrowserLifecycle;",
            "StartBrowserLifecycleSmokeShutdownTimer();",
            "OnBrowserLifecycleSmokeShutdownTimer();",
            "OnBrowserLifecycleShutdownComplete();",
            "std::unique_ptr<chrome::WasmBrowserLifecycle> browser_lifecycle_;",
            "base::OneShotTimer browser_lifecycle_smoke_shutdown_timer_;",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, header)

        switch = '"wasm-browser-lifecycle-smoke"'
        self.assertIn(switch, implementation)
        switch_index = implementation.index(switch)
        initialize_index = implementation.index("browser_lifecycle_->Initialize();")
        self.assertLess(switch_index, initialize_index)

        normal_ready = '"CHROMIUM_WASM_M6_NORMAL_BROWSER:READY"'
        normal_pass = '"CHROMIUM_WASM_M6_NORMAL_BROWSER:PASS"'
        smoke_pass = '"CHROMIUM_WASM_M6_BROWSER_LIFECYCLE:PASS"'
        for expected in (normal_ready, normal_pass, smoke_pass):
            with self.subTest(expected=expected):
                self.assertIn(expected, implementation)

        normal_path = implementation[
            implementation.index("InitializeWasmBrowserHostLifecycle("):
            implementation.index("void WasmBrowserMainParts::WillRunMainMessageLoop")
        ]
        self.assertIn("browser_lifecycle_ = std::make_unique", normal_path)
        self.assertIn("browser_lifecycle_->Initialize();", normal_path)
        self.assertIn("kWasmNormalBrowserReadyMarker", normal_path)
        self.assertNotIn("browser_lifecycle_smoke_requested_ = true", normal_path)

        will_run = implementation.index("void WasmBrowserMainParts::WillRunMainMessageLoop")
        post_run = implementation.index(
            "void WasmBrowserMainParts::PostMainMessageLoopRun", will_run
        )
        will_run_body = implementation[will_run:post_run]
        self.assertLess(
            will_run_body.index("main_message_loop_quit_closure_ ="),
            will_run_body.index("StartBrowserLifecycleSmokeShutdownTimer();"),
        )
        self.assertLess(
            will_run_body.index("StartBrowserLifecycleSmokeShutdownTimer();"),
            will_run_body.index("MaybeStartShutdown();"),
        )

        maybe_start = implementation.index("void WasmBrowserMainParts::MaybeStartShutdown")
        timer = implementation.index(
            "void WasmBrowserMainParts::StartBrowserLifecycleSmokeShutdownTimer"
        )
        maybe_body = implementation[maybe_start:timer]
        self.assertIn("if (browser_lifecycle_)", maybe_body)
        self.assertIn("browser_lifecycle_->BeginShutdown();", maybe_body)

        complete = implementation.index(
            "void WasmBrowserMainParts::OnBrowserLifecycleShutdownComplete"
        )
        complete_body = implementation[
            complete:implementation.index(
                "void WasmBrowserMainParts::StartBrowserWindowLifecycleSmokeShutdownTimer",
                complete,
            )
        ]
        self.assertIn("browser_lifecycle_smoke_shutdown_timer_.Stop();", complete_body)
        self.assertIn("kWasmBrowserLifecycleSmokePassMarker", complete_body)
        self.assertIn("kWasmNormalBrowserPassMarker", complete_body)
        self.assertIn("browser_lifecycle_.reset();", complete_body)
        self.assertIn("FinishShutdown();", complete_body)

        shutdown = implementation.index("void WasmBrowserMainParts::ShutdownFoundation")
        profile_shutdown = implementation.index("profile_->Shutdown();", shutdown)
        lifecycle_check = implementation.index("CHECK(!browser_lifecycle_);", shutdown)
        self.assertLess(lifecycle_check, profile_shutdown)

    def test_target_stays_browser_main_owned_and_narrow(self) -> None:
        build = source("chrome/browser/wasm/BUILD.gn")
        target = _source_set_body(build, "wasm_browser_lifecycle")
        main_parts_target = _source_set_body(build, "wasm_browser_main_parts")

        self.assertIn('visibility = [ ":wasm_browser_main_parts" ]', target)
        for expected in (
            '":wasm_browser",',
            '":wasm_browser_manager",',
            '":wasm_browser_view",',
            '":wasm_profile",',
            '":wasm_tab_core",',
            '"//content/public/browser",',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, target)
        self.assertIn('":wasm_browser_lifecycle",', main_parts_target)

        for forbidden in (
            "//chrome/browser/ui:ui",
            "../ui/browser.cc",
            "browser_tabstrip.cc",
            "unload_controller.cc",
            "create_browser_window_non_android.cc",
            ":wasm_constrained_window",
            "//components/constrained_window",
            "//components/javascript_dialogs",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, target)


if __name__ == "__main__":
    unittest.main()
