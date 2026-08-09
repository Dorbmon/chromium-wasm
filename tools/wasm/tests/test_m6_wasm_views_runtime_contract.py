#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for Wasm's process-lifetime generic Views/Aura runtime."""

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


def _method_body(implementation: str, method: str) -> str:
    match = re.search(
        rf"(?:void|int) WasmBrowserMainParts::{re.escape(method)}\(\) \{{"
        rf"(?P<body>.*?)\n\}}",
        implementation,
        re.DOTALL,
    )
    if not match:
        raise AssertionError(f"could not find WasmBrowserMainParts::{method}()")
    return match.group("body")


class M6WasmViewsRuntimeContractTest(unittest.TestCase):
    def test_main_parts_owns_generic_views_runtime_in_safe_order(self) -> None:
        header = source("chrome/browser/wasm/wasm_browser_main_parts.h")
        implementation = source("chrome/browser/wasm/wasm_browser_main_parts.cc")

        fields = (
            "std::unique_ptr<views::ViewsDelegate> views_delegate_;",
            "std::unique_ptr<views::LayoutProvider> layout_provider_;",
            "std::unique_ptr<display::Screen> screen_;",
            "std::unique_ptr<wm::WMState> wm_state_;",
            "std::unique_ptr<WasmBrowserProcess> browser_process_;",
            "std::unique_ptr<WasmProfile> profile_;",
        )
        positions = []
        for field in fields:
            with self.subTest(field=field):
                self.assertIn(field, header)
            positions.append(header.index(field))
        self.assertEqual(positions, sorted(positions))

        self.assertIn(
            "class WasmViewsDelegate final : public views::ViewsDelegate",
            implementation,
        )
        for forbidden in (
            '#include "chrome/browser/ui/views/chrome_views_delegate.h"',
            '#include "chrome/browser/ui/views/chrome_layout_provider.h"',
            "std::make_unique<ChromeViewsDelegate>",
            "ChromeBrowserMainExtraPartsViews()",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, implementation)

    def test_startup_creates_generic_globals_before_profiles_and_widgets(self) -> None:
        implementation = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        toolkit = _method_body(implementation, "ToolkitInitialized")
        pre_create_threads = _method_body(implementation, "PreCreateThreads")

        expected_toolkit = (
            "views_delegate_ = std::make_unique<WasmViewsDelegate>();",
            "layout_provider_ = std::make_unique<views::LayoutProvider>();",
            "wm_state_ = std::make_unique<wm::WMState>();",
            "base::BindRepeating(color::AddComponentsColorMixers)",
        )
        positions = []
        for expected in expected_toolkit:
            with self.subTest(expected=expected):
                self.assertIn(expected, toolkit)
            positions.append(toolkit.index(expected))
        self.assertEqual(positions, sorted(positions))

        self.assertIn("screen_ = views::CreateDesktopScreen();", pre_create_threads)
        self.assertIn("CHECK(display::Screen::Get());", pre_create_threads)
        self.assertLess(
            pre_create_threads.index("screen_ = views::CreateDesktopScreen();"),
            pre_create_threads.index("browser_process_ = std::make_unique<WasmBrowserProcess>();"),
        )

    def test_runtime_stays_alive_through_smoke_teardown_and_ozone_post_main(self) -> None:
        implementation = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        smoke = source("chrome/browser/wasm/wasm_browser_view_smoke.cc")
        post_main = _method_body(implementation, "PostMainMessageLoopRun")

        for expected in (
            "CHECK(views::ViewsDelegate::GetInstance());",
            "CHECK(views::LayoutProvider::Get());",
            "CHECK(display::Screen::HasScreen());",
        ):
            with self.subTest(expected=expected):
                self.assertGreaterEqual(smoke.count(expected), 2)

        self.assertNotIn("views_delegate_.reset()", post_main)
        self.assertNotIn("layout_provider_.reset()", post_main)
        self.assertNotIn("screen_.reset()", post_main)
        self.assertNotIn("wm_state_.reset()", post_main)
        self.assertLess(
            post_main.index("PostMainMessageLoopRun()"),
            post_main.index("ShutdownFoundation();"),
        )

    def test_main_parts_selects_only_generic_views_runtime_targets(self) -> None:
        build_file = source("chrome/browser/wasm/BUILD.gn")
        main_parts = _source_set_body(build_file, "wasm_browser_main_parts")

        for required in (
            '"//components/color",',
            '"//ui/display",',
            '"//ui/views",',
            '"//ui/wm",',
        ):
            with self.subTest(required=required):
                self.assertIn(required, main_parts)

        for forbidden in (
            "//chrome/browser/ui:ui",
            "ChromeViewsDelegate",
            "ChromeBrowserMainExtraPartsViews",
            "//chrome/browser/ui/views",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, main_parts)


if __name__ == "__main__":
    unittest.main()
