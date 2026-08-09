#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the switch-gated Wasm browser-window shutdown barrier."""

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


class M6WasmBrowserWindowLifecycleContractTest(unittest.TestCase):
    def test_manager_completion_waits_for_physical_not_logical_destruction(self) -> None:
        header = source("chrome/browser/ui/browser_manager_service.h")
        implementation = source(
            "chrome/browser/wasm/wasm_browser_manager_service.cc"
        )

        for expected in (
            "RunWhenBrowserDestructionsCompleteForWasm",
            "pending_browser_destructions_",
            "browser_destruction_callbacks_",
            "MaybeRunBrowserDestructionCallbacksForWasm",
            "stronger than IsEmpty()",
            "neither closes nor prevents creation of later browsers",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, header)

        registration = implementation.index(
            "void BrowserManagerService::RunWhenBrowserDestructionsCompleteForWasm"
        )
        destroy = implementation.index(
            "void BrowserManagerService::DestroyPendingBrowserDestructions"
        )
        helper = implementation.index(
            "void BrowserManagerService::MaybeRunBrowserDestructionCallbacksForWasm"
        )
        self.assertLess(registration, destroy)
        self.assertLess(destroy, helper)
        destroy_body = implementation[destroy:helper]
        self.assertLess(
            destroy_body.index("pending_browser_destructions_.clear();"),
            destroy_body.index("MaybeRunBrowserDestructionCallbacksForWasm();"),
        )
        helper_body = implementation[helper:]
        self.assertIn("!browsers_and_subscriptions_.empty()", helper_body)
        self.assertIn("!pending_browser_destructions_.empty()", helper_body)
        self.assertIn("std::move(callback).Run();", helper_body)

    def test_lifecycle_closes_one_attached_no_unload_tab_before_completion(self) -> None:
        header = source("chrome/browser/wasm/wasm_browser_window_lifecycle.h")
        implementation = source(
            "chrome/browser/wasm/wasm_browser_window_lifecycle.cc"
        )

        for expected in (
            "class WasmBrowserWindowLifecycle final",
            "void Initialize();",
            "void BeginShutdown(base::OnceClosure completion);",
            "bool IsShutdownComplete() const",
            "std::unique_ptr<WasmBrowserWindowViewHost> view_host_;",
            "base::WeakPtr<BrowserWindowInterface> core_;",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, header)

        for expected in (
            "std::make_unique<WasmBrowserWindowCore>(profile_)",
            "browser_manager_->AddBrowser(std::move(core));",
            "std::make_unique<WasmBrowserWindowViewHost>(raw_core)",
            "view_host_->Initialize();",
            "content::WebContents::Create(create_params)",
            "tab_strip_model->AppendWebContents(std::move(contents)",
            "CHECK_EQ(tab_strip_model->count(), 1);",
            "CHECK_EQ(browser_view->GetActiveWebContents(), raw_contents);",
            "RunWhenBrowserDestructionsCompleteForWasm",
            "view_host_->RequestClose();",
            "CHECK(!core_);",
            "CHECK(browser_manager_->IsEmpty());",
            "CHECK(global_collection->IsEmpty());",
            "CHECK_EQ(view_host_->active_tab_change_count_for_testing(), 2);",
            "CHECK(view_host_->detached_active_contents_for_testing());",
            "view_host_.reset();",
            '"CHROMIUM_WASM_M6_BROWSER_WINDOW_LIFECYCLE:PASS"',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, implementation)

        initialize = implementation.index("void WasmBrowserWindowLifecycle::Initialize")
        host_initialize = implementation.index("view_host_->Initialize();", initialize)
        append = implementation.index("tab_strip_model->AppendWebContents", initialize)
        self.assertLess(host_initialize, append)

        begin = implementation.index("void WasmBrowserWindowLifecycle::BeginShutdown")
        register = implementation.index(
            "RunWhenBrowserDestructionsCompleteForWasm", begin
        )
        close = implementation.index("view_host_->RequestClose();", begin)
        self.assertLess(register, close)

        complete = implementation.index(
            "void WasmBrowserWindowLifecycle::OnBrowserDestructionsComplete"
        )
        reset = implementation.index("view_host_.reset();", complete)
        callback = implementation.index(
            "std::move(shutdown_complete_callback_).Run();", complete
        )
        self.assertLess(reset, callback)

        for forbidden in (
            "Browser::Create",
            "OpenURL(",
            "OpenGURL(",
            "BrowserWindowModalDialogDelegate",
            "RunUntilIdle",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, implementation)

    def test_main_parts_waits_for_lifecycle_before_profile_shutdown(self) -> None:
        header = source("chrome/browser/wasm/wasm_browser_main_parts.h")
        implementation = source(
            "chrome/browser/wasm/wasm_browser_main_parts.cc"
        )
        build_file = source("chrome/browser/wasm/BUILD.gn")
        target = _source_set_body(build_file, "wasm_browser_window_lifecycle")
        main_parts_target = _source_set_body(
            build_file, "wasm_browser_main_parts"
        )

        self.assertIn(
            "std::unique_ptr<chrome::WasmBrowserWindowLifecycle>", header
        )
        self.assertIn("browser_window_shutdown_started_", header)
        for expected in (
            "void MaybeStartShutdown();",
            "void OnBrowserWindowLifecycleShutdownComplete();",
            "void FinishShutdown();",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, header)

        for expected in (
            '"wasm-browser-window-lifecycle-smoke"',
            "std::make_unique<chrome::WasmBrowserWindowLifecycle>(profile_.get())",
            "browser_window_lifecycle_->Initialize();",
            "RequestShutdown();",
            "MaybeStartShutdown();",
            "browser_window_lifecycle_->BeginShutdown",
            "OnBrowserWindowLifecycleShutdownComplete",
            "browser_window_lifecycle_.reset();",
            "FinishShutdown();",
            "CHECK(!browser_window_lifecycle_);",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, implementation)

        will_run = implementation.index("void WasmBrowserMainParts::WillRunMainMessageLoop")
        self.assertIn("MaybeStartShutdown();", implementation[will_run:])
        request = implementation.index("void WasmBrowserMainParts::RequestShutdown")
        maybe = implementation.index("void WasmBrowserMainParts::MaybeStartShutdown")
        self.assertLess(request, maybe)
        maybe_body = implementation[maybe:]
        self.assertIn("!main_message_loop_quit_closure_", maybe_body)
        self.assertIn("browser_window_shutdown_started_", maybe_body)

        shutdown = implementation.index("void WasmBrowserMainParts::ShutdownFoundation")
        lifecycle_check = implementation.index(
            "CHECK(!browser_window_lifecycle_);", shutdown
        )
        profile_shutdown = implementation.index("profile_->Shutdown();", shutdown)
        self.assertLess(lifecycle_check, profile_shutdown)

        for expected in (
            'visibility = [ ":wasm_browser_main_parts" ]',
            '":wasm_browser_manager",',
            '":wasm_browser_window_core",',
            '":wasm_browser_window_view_host",',
            '":wasm_tab_core",',
            '"//content/public/browser",',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, target)
        self.assertIn('":wasm_browser_window_lifecycle",', main_parts_target)

        # `:wasm_tab_core` is the explicit Wasm tab-model implementation
        # required to create the one no-unload model tab. It must not pull a
        # desktop UI/tab-strip aggregate, the constrained-window composition
        # path, or JavaScript-dialog ownership into this lifecycle target.
        for forbidden in (
            '"//chrome/browser/ui",',
            '"//chrome/browser/ui:ui",',
            '"//chrome/browser/ui/tabs",',
            '"//chrome/browser/ui/tabs:tabs",',
            '":wasm_constrained_window",',
            '"//components/constrained_window",',
            '"//components/javascript_dialogs",',
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, target)

        # Browser::Create is mentioned in pre-existing explanatory comments
        # for other bounded Wasm paths. The lifecycle target itself owns the
        # no-general-browser contract above; the main-parts gate must only
        # avoid navigation and modal entry points.
        for forbidden in (
            "OpenURL(",
            "OpenGURL(",
            "BrowserWindowModalDialogDelegate",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, implementation)


if __name__ == "__main__":
    unittest.main()
