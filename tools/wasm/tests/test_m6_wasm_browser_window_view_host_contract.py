#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the bounded Wasm BrowserWindow Views-side host."""

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


class M6WasmBrowserWindowViewHostContractTest(unittest.TestCase):
    def test_host_owns_only_the_views_side_of_the_bounded_binding(self) -> None:
        header = source("chrome/browser/wasm/wasm_browser_window_view_host.h")
        implementation = source(
            "chrome/browser/wasm/wasm_browser_window_view_host.cc"
        )

        self.assertIn(
            "class WasmBrowserWindowViewHost final "
            ": public views::WidgetObserver",
            header,
        )
        for expected in (
            "explicit WasmBrowserWindowViewHost(WasmBrowserWindowCore* core);",
            "void Initialize();",
            "void RequestClose();",
            "BrowserView* browser_view() const;",
            "active_tab_change_count_for_testing",
            "detached_active_contents_for_testing",
            "close_request_count_for_testing",
            "base::WeakPtr<WasmBrowserWindowCore> core_;",
            "raw_ptr<BrowserView> browser_view_ = nullptr;",
            "raw_ptr<BrowserWidget> widget_ = nullptr;",
            "base::ScopedObservation<views::Widget, views::WidgetObserver>",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, header)

        for expected in (
            "new BrowserView(/*browser=*/nullptr)",
            "std::make_unique<BrowserWidget>(browser_view)",
            "widget->InitBrowserWidget();",
            "widget_observation_.Observe(widget);",
            "SetWasmCloseRequestCallbackForSmoke",
            "BindWindowForWasmBrowserWindowViewSmoke",
            "InitPostBrowserViewConstructionForWasmBrowserWindowViewSmoke",
            "OnWindowActivationChangedForWasmBrowserWindowViewSmoke",
            "RequestCloseForWasmBrowserWindowViewSmoke",
            "UnbindWindowForWasmBrowserWindowViewSmoke",
            "BrowserView::DestroyForWasmBrowserViewSmoke(browser_view_);",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, implementation)

        close_request = implementation.index(
            "void WasmBrowserWindowViewHost::RequestClose()"
        )
        close_request_order = (
            "CHECK(core_);",
            "CHECK(browser_view_);",
            "CHECK(widget_);",
            "if (close_requested_) {",
            "close_requested_ = true;",
            "core_->RequestCloseForWasmBrowserWindowViewSmoke();",
        )
        positions = [
            implementation.index(item, close_request) for item in close_request_order
        ]
        self.assertEqual(positions, sorted(positions))

        close_callback = implementation.index(
            "views::CloseRequestResult WasmBrowserWindowViewHost::OnCloseRequested()"
        )
        self.assertLess(
            implementation.index("++close_request_count_;", close_callback),
            implementation.index("RequestClose();", close_callback),
        )
        self.assertIn(
            "return views::CloseRequestResult::kCannotClose;",
            implementation[close_callback:],
        )

        destroy = implementation.index("void WasmBrowserWindowViewHost::Destroy()")
        destroy_order = (
            "browser_view_->Deactivate();",
            "CHECK(!core_->IsActive());",
            "core_->UnbindWindowForWasmBrowserWindowViewSmoke(browser_view_);",
            "widget_observation_.Reset();",
            "BrowserView::DestroyForWasmBrowserViewSmoke(browser_view_);",
            "browser_view_ = nullptr;",
            "widget_ = nullptr;",
        )
        positions = [implementation.index(item, destroy) for item in destroy_order]
        self.assertEqual(positions, sorted(positions))

        for expected in (
            "void WasmBrowserWindowViewHost::OnWidgetDestroying",
            "void WasmBrowserWindowViewHost::OnWidgetDestroyed",
            "CHECK(false)",
            "no-unload close lifecycle",
            "native teardown escaped",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, implementation)

        for forbidden in (
            '#include "chrome/browser/wasm/wasm_profile.h"',
            '#include "chrome/browser/ui/browser_manager_service.h"',
            '#include "chrome/browser/ui/tabs/tab_strip_model.h"',
            "WebContents::Create",
            "Browser::Create",
            "GetTabStripModel()",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, implementation)

    def test_core_bridge_is_private_to_the_view_host(self) -> None:
        header = source("chrome/browser/wasm/wasm_browser_window_core.h")
        friend = header.index("friend class chrome::WasmBrowserWindowViewHost;")
        private_bridge = header.index(
            "// The View host is the only allowed caller for this bounded bridge."
        )
        self.assertLess(friend, private_bridge)

        public_surface = header[:friend]
        for bridge in (
            "BindWindowForWasmBrowserWindowViewSmoke",
            "InitPostBrowserViewConstructionForWasmBrowserWindowViewSmoke",
            "OnWindowActivationChangedForWasmBrowserWindowViewSmoke",
            "RequestCloseForWasmBrowserWindowViewSmoke",
            "UnbindWindowForWasmBrowserWindowViewSmoke",
            "GetWeakPtrForWasmBrowserWindowViewSmoke",
        ):
            with self.subTest(bridge=bridge):
                self.assertNotIn(bridge, public_surface)
                self.assertIn(bridge, header[friend:])

        self.assertIn("void NotifyActiveTabDidChangeForWasmSmoke();", header[friend:])

    def test_host_target_is_private_to_the_explicit_view_smoke(self) -> None:
        build_file = source("chrome/browser/wasm/BUILD.gn")
        host_target = _source_set_body(
            build_file, "wasm_browser_window_view_host"
        )
        smoke_target = _source_set_body(
            build_file, "wasm_browser_window_view_smoke"
        )
        smoke = source("chrome/browser/wasm/wasm_browser_window_view_smoke.cc")

        for expected in (
            '"wasm_browser_window_view_host.h"',
            '"wasm_browser_window_view_host.cc"',
            'visibility = [ ":wasm_browser_window_view_smoke" ]',
            '":wasm_browser_view",',
            '":wasm_browser_widget",',
            '":wasm_browser_window_core",',
            '"//base",',
            '"//ui/views",',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, host_target)

        self.assertIn('":wasm_browser_window_view_host",', smoke_target)
        self.assertNotIn('":wasm_browser_widget",', smoke_target)
        self.assertIn(
            '#include "chrome/browser/wasm/wasm_browser_window_view_host.h"',
            smoke,
        )
        self.assertIn("WasmBrowserWindowViewHost view_host(raw_core);", smoke)
        self.assertNotIn("WasmBrowserWindowViewSmokeAdapter", smoke)
        self.assertIn("close_request_count_for_testing()", smoke)
        self.assertIn("detached_active_contents_for_testing()", smoke)


if __name__ == "__main__":
    unittest.main()
