#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the opt-in structural Wasm BrowserView smoke.

The smoke is deliberately a runtime composition proof, not Browser startup:
one external WebContents is attached to a null-Browser BrowserView and the
client-owned Views ownership cycle is broken without selecting close/unload or
BrowserWindowFeatures policy.
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


class M6WasmBrowserViewSmokeContractTest(unittest.TestCase):
    def test_smoke_composes_real_view_widget_and_external_contents(self) -> None:
        header = source("chrome/browser/wasm/wasm_browser_view_smoke.h")
        implementation = source("chrome/browser/wasm/wasm_browser_view_smoke.cc")

        self.assertIn("bool RunWasmBrowserViewSmoke(WasmProfile* profile);", header)
        for expected in (
            "CHECK_CURRENTLY_ON(content::BrowserThread::UI);",
            "CHECK(views::ViewsDelegate::GetInstance());",
            "CHECK(views::LayoutProvider::Get());",
            "CHECK(display::Screen::HasScreen());",
            "ReportBrowserViewSmokeStep(\"construct-view\");",
            "ReportBrowserViewSmokeStep(\"widget-initialized\");",
            "ReportBrowserViewSmokeStep(\"web-contents-created\");",
            "ReportBrowserViewSmokeStep(\"web-contents-attached\");",
            "ReportBrowserViewSmokeStep(\"contents-sized\");",
            "ReportBrowserViewSmokeStep(\"widget-shown\");",
            "ReportBrowserViewSmokeStep(\"web-contents-detached\");",
            "ReportBrowserViewSmokeStep(\"widget-reset\");",
            "ReportBrowserViewSmokeStep(\"native-teardown-drained\");",
            "new BrowserView(/*browser=*/nullptr)",
            "std::make_unique<BrowserWidget>(browser_view)",
            "browser_view->set_browser_widget(std::move(browser_widget));",
            "widget->InitBrowserWidget();",
            "CHECK(widget->browser_native_widget());",
            "BrowserView::GetBrowserViewForNativeWindow(",
            "content::WebContents::CreateParams create_params(profile);",
            "content::WebContents::Create(create_params)",
            "browser_view->OnActiveTabChanged(/*old_contents=*/nullptr, raw_contents,",
            "browser_view->contents_web_view()->GetWebContents(), raw_contents",
            "browser_view->SetBounds(kBrowserViewSmokeBounds);",
            "widget->GetRootView()->DeprecatedLayoutImmediately();",
            "browser_view->GetContentsSize(), kBrowserViewSmokeBounds.size()",
            "browser_view->Show();",
            "CHECK(browser_view->IsVisible());",
            "base::OneShotTimer visible_timer;",
            "visible_timer.Start(FROM_HERE, kBrowserViewSmokeVisibleDuration,",
            "visible_run_loop.Run();",
            "ReportBrowserViewSmokeStep(\"visible-turn-complete\");",
            "browser_view->OnTabDetached(raw_contents, /*was_active=*/true);",
            "contents.reset();",
            "BrowserView::DestroyForWasmBrowserViewSmoke(browser_view);",
            "base::RunLoop().RunUntilIdle();",
            '"CHROMIUM_WASM_M6_BROWSER_VIEW"',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, implementation)

        # This is a structural proof only. It must not pretend that it owns a
        # Browser lifecycle, BrowserWindowFeatures, or an interactive close.
        for forbidden in (
            "Browser::Create",
            "BrowserWindowFeatures",
            "BrowserManager",
            "BrowserViewSmokeViewsDelegate",
            "DesktopScreenOzone ozone_screen",
            "MakeCloseSynchronous",
            "CloseNow(",
            "browser_view->Close(",
            "widget->Close(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, implementation)

        # The bounded timer only yields a real UI turn for the shown Ozone
        # Widget. It intentionally does not turn a Node callback into a canvas
        # presentation assertion.
        self.assertIn("This is not a frame assertion", implementation)
        self.assertNotIn("CHECK(!reports.frame.empty())", implementation)

    def test_teardown_helper_enforces_the_null_browser_boundary(self) -> None:
        header = source("chrome/browser/ui/views/frame/browser_view.h")
        implementation = source("chrome/browser/wasm/wasm_browser_view.cc")

        self.assertIn(
            "static void DestroyForWasmBrowserViewSmoke(BrowserView* browser_view);",
            header,
        )
        helper = re.search(
            r"void BrowserView::DestroyForWasmBrowserViewSmoke\("
            r"BrowserView\* browser_view\) \{(?P<body>.*?)\n\}",
            implementation,
            re.DOTALL,
        )
        self.assertIsNotNone(helper)
        body = helper.group("body")
        self.assertIn("CHECK(!browser_view->browser_)", body)
        self.assertIn("CHECK(browser_view->browser_widget_);", body)
        self.assertIn("CHECK(!browser_view->active_web_contents_)", body)
        self.assertIn("browser_view->browser_widget_.reset();", body)
        self.assertTrue(body.rstrip().endswith("browser_view->browser_widget_.reset();"))

    def test_switch_is_opt_in_and_normal_lifecycle_follows(self) -> None:
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")

        switch = (
            'constexpr char kWasmBrowserViewSmokeSwitch[] = '
            '"wasm-browser-view-smoke";'
        )
        self.assertIn(switch, main_parts)
        switch_index = main_parts.index(switch)
        run_index = main_parts.index("chrome::RunWasmBrowserViewSmoke(profile_.get())")
        shutdown_index = main_parts.index("RequestShutdown();", run_index)
        success_index = main_parts.index(
            "return content::RESULT_CODE_NORMAL_EXIT;", shutdown_index
        )
        normal_lifecycle_index = main_parts.index(
            "InitializeWasmBrowserHostLifecycle("
        )
        normal_ready_index = main_parts.index(
            "std::fprintf(stderr, \"%s\\n\", kWasmNormalBrowserReadyMarker);",
            normal_lifecycle_index,
        )
        self.assertLess(switch_index, run_index)
        self.assertLess(run_index, shutdown_index)
        self.assertLess(shutdown_index, success_index)
        self.assertLess(success_index, normal_lifecycle_index)
        self.assertLess(normal_lifecycle_index, normal_ready_index)

    def test_build_target_is_test_only_and_source_selected_by_main_parts(self) -> None:
        wasm_build = source("chrome/browser/wasm/BUILD.gn")
        chrome_build = source("chrome/BUILD.gn")
        smoke = _source_set_body(wasm_build, "wasm_browser_view_smoke")
        main_parts = _source_set_body(wasm_build, "wasm_browser_main_parts")

        for expected in (
            '"wasm_browser_view_smoke.cc"',
            '":wasm_browser_view",',
            '":wasm_browser_widget",',
            '":wasm_profile",',
            '"//content/public/browser",',
            '"//ui/views/controls/webview:webview",',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, smoke)

        for forbidden in (
            "//chrome/browser/ui:ui",
            "browser_window_factory.cc",
            ":wasm_browser_window_features",
            ":wasm_browser_main_parts",
            ":wasm_tab_core",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, smoke)

        self.assertIn('":wasm_browser_view_smoke",', main_parts)
        self.assertNotIn(":wasm_browser_view_smoke", chrome_build)

    def test_wasm_compositor_selects_the_platform_begin_frame_adapter(self) -> None:
        compositor_build = source("ui/compositor/BUILD.gn")

        self.assertIn(
            "(is_wasm && enable_chromium_wasm_chrome)", compositor_build
        )
        self.assertIn('"external_begin_frame_adapter.cc",', compositor_build)
        self.assertIn('"//ui/platform_window"', compositor_build)

    def test_wasm_views_supplies_only_generic_menu_metrics(self) -> None:
        views_build = source("ui/views/BUILD.gn")
        menu_config = source("ui/views/controls/menu/menu_config_wasm.cc")

        self.assertIn("is_wasm && enable_chromium_wasm_chrome", views_build)
        self.assertIn('"controls/menu/menu_config_wasm.cc"', views_build)
        self.assertIn("void MenuConfig::InitPlatform() {", menu_config)
        self.assertIn("InitCommon's generic Views defaults", menu_config)
        self.assertNotIn("OzonePlatform", menu_config)


if __name__ == "__main__":
    unittest.main()
