#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the strict, unwired Wasm BrowserWindow visual factory."""

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


class M6WasmBrowserWindowFactoryContractTest(unittest.TestCase):
    def test_factory_and_custom_deleter_remain_a_strict_unwired_seam(self) -> None:
        window_header = _wasm_branch(source("chrome/browser/ui/browser_window.h"))
        view_header = _wasm_branch(
            source("chrome/browser/ui/views/frame/browser_view.h")
        )
        view = source("chrome/browser/wasm/wasm_browser_view.cc")
        widget = source("chrome/browser/wasm/wasm_browser_widget.cc")
        factory = source("chrome/browser/wasm/wasm_browser_window_factory.cc")
        build = source("chrome/browser/wasm/BUILD.gn")
        target = _source_set_body(build, "wasm_browser_window_factory")

        for expected in (
            "#include <memory>",
            '#include "chrome/browser/ui/browser_window_deleter.h"',
            "class Browser;",
            "std::unique_ptr<BrowserWindow, BrowserWindowDeleter>",
            "CreateBrowserWindow(Browser* browser,",
            "friend struct BrowserWindowDeleter;",
            "virtual void DeleteBrowserWindow() = 0;",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, window_header)

        self.assertIn("void DeleteBrowserWindow() final;", view_header)
        self.assertIn(
            "IsWasmBrowserWindowDeletionInProgress() const", view_header
        )
        for expected in (
            "void BrowserView::DeleteBrowserWindow()",
            "CHECK(browser_)",
            "CHECK(!active_web_contents_)",
            "CHECK(!browser_window_deletion_in_progress_);",
            "browser_window_deletion_in_progress_ = true;",
            "browser_widget_.reset();",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, view)

        for expected in (
            "IsWasmBrowserWindowDeletionInProgress()",
            "Detach WebContents before Wasm BrowserWidget destruction",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, widget)

        factory_order = (
            "CHECK(browser);",
            "CHECK(!in_tab_dragging)",
            "new BrowserView(browser)",
            "std::make_unique<BrowserWidget>(view)",
            "view->set_browser_widget(std::move(browser_widget));",
            "view->browser_widget()->InitBrowserWidget();",
            "kCreatedByUserGesture",
            "return std::unique_ptr<BrowserWindow, BrowserWindowDeleter>(view);",
        )
        positions = [factory.index(item) for item in factory_order]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("#if !BUILDFLAG(IS_WASM)", factory)

        for expected in (
            'visibility = [ ":*" ]',
            '"../ui/browser_window_deleter.cc",',
            '"wasm_browser_window_factory.cc",',
            '":wasm_browser_view"',
            '":wasm_browser_widget",',
            '"//ui/aura",',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, target)

        for forbidden in (
            '../ui/views/frame/browser_window_factory.cc',
            "Browser::Create",
            "BrowserWindowModalDialogDelegate",
            "//chrome/browser/ui:ui",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, factory)


if __name__ == "__main__":
    unittest.main()
