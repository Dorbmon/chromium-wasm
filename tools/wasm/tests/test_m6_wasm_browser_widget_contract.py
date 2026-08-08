#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the object-only Wasm BrowserWidget source slice.

The slice may construct a real generic Views Widget over the Ozone Wasm native
widget, but it must not imply that the desktop Browser frame, close lifecycle,
or system-menu implementation has been ported. The opt-in BrowserView smoke
may select it transitively, but normal Chrome startup must not.
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


class M6WasmBrowserWidgetContractTest(unittest.TestCase):
    def test_wasm_implementation_uses_generic_views_and_real_native_widget(
        self,
    ) -> None:
        implementation = source("chrome/browser/wasm/wasm_browser_widget.cc")

        for expected in (
            '#include "chrome/browser/ui/views/frame/browser_native_widget_factory.h"',
            '#include "chrome/browser/wasm/wasm_default_theme_provider.h"',
            "BrowserNativeWidgetFactory::CreateBrowserNativeWidget(",
            "browser_native_widget_->GetWidgetParams(",
            "views::Widget::InitParams::CLIENT_OWNS_WIDGET",
            'params.name = "BrowserWidgetWasm";',
            "params.delegate = browser_view_;",
            "SetNativeTheme(ui::NativeTheme::GetInstanceForNativeUi());",
            "new views::internal::RootView(this)",
            "class WasmContentFrameView final : public views::FrameView",
            "std::make_unique<WasmContentFrameView>()",
            "gfx::Rect GetBoundsForClientView() const override",
            "return GetLocalBounds();",
            "return GetLocalBounds().Contains(point) ? HTCLIENT : HTNOWHERE;",
            "static const base::NoDestructor<WasmDefaultThemeProvider> provider;",
            "return &GetWasmDefaultThemeProvider();",
            "ui::ColorProviderKey::FrameType::kChromium",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, implementation)

        # This is a content-only frame. It must not admit the desktop Chrome
        # root/frame classes or profile theme machinery just to compile.
        for forbidden in (
            "BrowserRootView",
            "BrowserFrameViewChromeOS",
            "chrome::CreateBrowserFrameView",
            "ThemeService",
            "ThemeServiceFactory",
            "SystemMenuModelBuilder",
            "BrowserWindowFeatures",
            "SynchronouslyDestroyBrowser",
            "OnWindowClosing",
            "TearDownPreBrowserWindowDestruction",
            "BrowserWindow::CreateBrowserWindow",
            "browser_->",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, implementation)

    def test_unimplemented_desktop_routes_fail_explicitly(self) -> None:
        implementation = source("chrome/browser/wasm/wasm_browser_widget.cc")

        self.assertIn(
            "CHECK(!browser_view_ || !browser_view_->browser())", implementation
        )
        self.assertIn(
            "Wasm BrowserWidget Browser destruction lifecycle is not selected",
            implementation,
        )
        self.assertIn(
            "Wasm BrowserWidget system-menu presentation is not selected",
            implementation,
        )
        self.assertIn(
            "Wasm BrowserWidget system-menu model is not selected", implementation
        )
        self.assertIn("Wasm BrowserWidget tab dragging is not selected", implementation)
        self.assertIn("return false;", implementation)

        # Generic Views notifications are preserved without inventing a host
        # workspace or changing a profile-backed browser theme.
        self.assertIn(
            "views::Widget::OnNativeWidgetWorkspaceChanged();", implementation
        )
        self.assertIn("ThemeChanged();", implementation)
        self.assertIn("client_view()->InvalidateLayout();", implementation)

    def test_header_drops_desktop_owned_menu_state_only_for_wasm(self) -> None:
        header = source("chrome/browser/ui/views/frame/browser_widget.h")

        self.assertRegex(
            header,
            re.compile(
                r"#if !BUILDFLAG\(IS_WASM\).*?"
                r"std::unique_ptr<SystemMenuModelBuilder> menu_model_builder_;.*?"
                r"std::unique_ptr<views::MenuRunner> menu_runner_;.*?"
                r"#endif  // !BUILDFLAG\(IS_WASM\)",
                re.DOTALL,
            ),
        )
        self.assertIn("ui::MenuModel* GetSystemMenuModel();", header)
        self.assertIn("bool IsMenuRunnerRunningForTesting() const;", header)
        self.assertIn("void OnTouchUiChanged();", header)

    def test_target_is_narrow_and_unwired(self) -> None:
        wasm_build = source("chrome/browser/wasm/BUILD.gn")
        target = _source_set_body(wasm_build, "wasm_browser_widget")

        self.assertIn("assert(use_aura && use_ozone && toolkit_views)", target)
        for expected in (
            '"../ui/views/frame/browser_widget.h"',
            '"wasm_browser_widget.cc"',
            '":wasm_browser_ui",',
            '":wasm_browser_view",',
            '":wasm_default_theme_provider",',
            '"//ui/native_theme",',
            '"//ui/views",',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, target)

        for forbidden in (
            "//chrome/browser/ui:ui",
            '"../ui/views/frame/browser_widget.cc"',
            "browser_window_factory.cc",
            ":wasm_browser_main_parts",
            ":wasm_browser_window_features",
            ":wasm_tab_core",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, target)

        self.assertNotIn(
            '":wasm_browser_widget",', source("chrome/BUILD.gn")
        )
        self.assertNotIn(
            ":wasm_browser_widget",
            _source_set_body(wasm_build, "wasm_browser_main_parts"),
        )


if __name__ == "__main__":
    unittest.main()
