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
            "class WasmBrowserWindowViewSmokeBridge final "
            ": public TabStripModelObserver",
            implementation,
        )
        self.assertIn("void OnTabWillBeRemoved(", implementation)
        self.assertIn("void OnTabStripModelChanged(", implementation)
        self.assertIn(
            "browser_view_->OnTabDetached(contents, /*was_active=*/true);",
            implementation,
        )
        self.assertIn("raw_ptr<BrowserView> browser_view = nullptr;", implementation)
        self.assertIn(
            "CHECK_EQ(state->browser_view->GetActiveWebContents(),",
            implementation,
        )

        attach = implementation.index("browser_view_->OnActiveTabChanged(")
        relay = implementation.index(
            "core_->NotifyActiveTabDidChangeForWasmSmoke();"
        )
        detach = implementation.index(
            "browser_view_->OnTabDetached(contents, /*was_active=*/true);"
        )
        self.assertLess(attach, relay)
        self.assertLess(detach, relay)
        self.assertIn(
            "CHECK_NE(active_tab, last_notified_active_tab_.get());",
            source("chrome/browser/wasm/wasm_browser_window_core.cc"),
        )

        for expected in (
            "tab_strip_model->AppendWebContents(std::move(contents),",
            "web_modal::WebContentsModalDialogManager::FromWebContents(",
            "CHECK(!modal_manager->IsDialogActive());",
            "RecordActiveTabChange",
            "relay_state.notification_count, 2",
            "active_tab->Close();",
            "CHECK(tab_strip_model->empty());",
            "CHECK(!browser_view->GetActiveWebContents());",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, implementation)

    def test_teardown_keeps_view_dependent_features_alive_until_detach(self) -> None:
        implementation = source(
            "chrome/browser/wasm/wasm_browser_window_view_smoke.cc"
        )

        ordered = (
            "active_tab->Close();",
            "raw_core->GetFeatures().TearDownPreBrowserWindowDestruction();",
            "bridge.StopObserving();",
            "BrowserView::DestroyForWasmBrowserViewSmoke(browser_view);",
            "base::RunLoop().RunUntilIdle();",
            "raw_core->CloseForWasmBrowserWindowCoreSmoke();",
            "browser_manager->DeleteBrowser(core.get());",
            "CHECK(!weak_core);",
        )
        positions = [implementation.index(item) for item in ordered]
        self.assertEqual(positions, sorted(positions))
        weak_capture = implementation.index(
            "base::WeakPtr<BrowserWindowInterface> weak_core = "
            "raw_core->GetWeakPtr();"
        )
        close_call = implementation.index(
            "raw_core->CloseForWasmBrowserWindowCoreSmoke();"
        )
        self.assertLess(weak_capture, close_call)
        self.assertNotIn("raw_core->", implementation[close_call + 1 :])
        self.assertIn("if (core) {", implementation)
        self.assertIn(
            '"CHROMIUM_WASM_M6_BROWSER_WINDOW_VIEW"', implementation
        )
        self.assertIn('std::fprintf(stderr, "%s:PASS\\n",', implementation)

        # The smoke validates a real model/view bridge, not Browser startup or
        # a partial window lifecycle that claims unsupported routes worked.
        for forbidden in (
            "Browser::Create",
            "BrowserWindowModalDialogDelegate",
            "browser_view->Close(",
            "widget->Close(",
            "OpenURL(",
            "OpenGURL(",
            "GetWindow()",
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
