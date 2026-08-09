#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the object-only, content-only Wasm BrowserView.

The slice deliberately hosts one externally-owned WebContents in Views without
admitting Browser construction, BrowserWindowFeatures, or the desktop Chrome
UI aggregate.
"""

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


class M6WasmBrowserViewContractTest(unittest.TestCase):
    def test_browser_window_is_slim_with_only_the_strict_visual_seam(self) -> None:
        wasm_window = _wasm_branch(source("chrome/browser/ui/browser_window.h"))

        for expected in (
            "class BrowserWindow : public ui::BaseWindow",
            "#include \"chrome/browser/ui/browser_window_deleter.h\"",
            "std::unique_ptr<BrowserWindow, BrowserWindowDeleter>",
            "CreateBrowserWindow(Browser* browser,",
            "virtual void DeleteBrowserWindow() = 0",
            "FindBrowserWindowWithWebContents",
            "GetNativeTheme() = 0",
            "GetThemeProvider() const = 0",
            "GetColorProvider() const = 0",
            "OnActiveTabChanged",
            "OnTabDetached",
            "GetContentsSize() const = 0",
            "SetContentsSize(const gfx::Size& size) = 0",
            "GetWebContentsModalDialogHost() = 0",
            "GetWebContentsModalDialogHostFor",
            "GetCanResize() = 0",
            "GetWindowShowState() const = 0",
            "AsBrowserView() = 0",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, wasm_window)

        for forbidden in (
            '#include "chrome/browser/ui/browser.h"',
            "Browser::DownloadCloseType",
            "ConfirmBrowserCloseWithPendingDownloads",
            "GetLocationBar",
            "UpdateToolbar",
            "GetExclusiveAccessContext",
            "ShowIntentPickerBubble",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, wasm_window)

    def test_browser_view_owns_one_real_non_owning_webview_and_host(self) -> None:
        header = source("chrome/browser/ui/views/frame/browser_view.h")
        implementation = source("chrome/browser/wasm/wasm_browser_view.cc")
        wasm_view = _wasm_branch(header)

        for expected in (
            "class BrowserView final : public BrowserWindow",
            "public views::WidgetDelegate",
            "public views::WidgetObserver",
            "public views::ClientView",
            "views::WebView* contents_web_view() const",
            "WasmTabModalDialogHost* tab_modal_dialog_host() const",
            "raw_ptr<views::WebView> contents_web_view_ = nullptr;",
            "raw_ptr<content::WebContents> active_web_contents_ = nullptr;",
            "std::unique_ptr<WasmTabModalDialogHost> tab_modal_dialog_host_;",
            "SetWasmCloseRequestCallback",
            "base::RepeatingCallback<views::CloseRequestResult()>",
            "wasm_close_request_callback_",
            "OnActiveTabChanged",
            "OnTabDetached",
            "GetWebContentsModalDialogHostFor",
            "OnWindowCloseRequested() override",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, wasm_view)

        self.assertIn("std::make_unique<views::WebView>()", implementation)
        self.assertIn("std::make_unique<WasmTabModalDialogHost>", implementation)
        self.assertIn("AddWebContentsDetachedCallback", implementation)
        self.assertIn("contents_web_view_->SetWebContents(new_contents);", implementation)
        self.assertIn("contents_web_view_->SetWebContents(nullptr);", implementation)
        self.assertIn("SetWasmCloseRequestCallback", implementation)
        self.assertIn("CHECK(wasm_close_request_callback_)", implementation)
        self.assertGreaterEqual(
            implementation.count("wasm_close_request_callback_.Run()"), 2
        )
        self.assertNotIn("MakeCloseSynchronous", implementation)

        # The standalone structural BrowserView smoke must not silently opt
        # into the joined Core close lifecycle.
        structural_smoke = source("chrome/browser/wasm/wasm_browser_view_smoke.cc")
        self.assertNotIn(
            "SetWasmCloseRequestCallback", structural_smoke
        )

        # A browser-created WebContents or Browser lifecycle call would violate
        # this object's explicit ownership boundary.
        for forbidden in (
            "GetWebContents(",
            "SetBrowserContext",
            "SetOwnedWebContents",
            "browser_->",
            "BrowserWindow::CreateBrowserWindow",
            "InitPostBrowserViewConstruction",
            "BrowserWindowFeatures",
            "TabStripModelObserver",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, implementation)

    def test_target_is_narrow_unwired_and_source_owns_both_headers(self) -> None:
        wasm_build = source("chrome/browser/wasm/BUILD.gn")
        target = _source_set_body(wasm_build, "wasm_browser_view")

        for expected in (
            '"../ui/browser_window.h",',
            '"../ui/views/frame/browser_view.h",',
            '"wasm_browser_view.cc"',
            '":wasm_tab_modal_dialog_host",',
            '":wasm_browser_ui",',
            '"//content/public/browser",',
            '"//ui/base/metadata:metadata",',
            '"//ui/views/controls/webview:webview",',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, target)

        for forbidden in (
            "//chrome/browser/ui:ui",
            "browser_window_factory.cc",
            '"../ui/views/frame/browser_view.cc"',
            ":wasm_browser_main_parts",
            ":wasm_browser_window_features",
            ":wasm_tab_core",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, target)

        self.assertNotIn(
            '"//chrome/browser/wasm:wasm_browser_view",',
            source("chrome/BUILD.gn"),
        )
        self.assertNotIn(
            '":wasm_browser_view",',
            _source_set_body(wasm_build, "wasm_browser_main_parts"),
        )


if __name__ == "__main__":
    unittest.main()
