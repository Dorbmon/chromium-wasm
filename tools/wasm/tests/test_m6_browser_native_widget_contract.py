#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the source-selected Wasm BrowserNativeWidget seam.

The first real Chrome frame must retain BrowserWidget's platform-factory
contract, but it must not smuggle in the stock desktop Aura implementation or
pretend that host-page canvas placement is persistent OS window state.
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


class M6BrowserNativeWidgetContractTest(unittest.TestCase):
    def test_wasm_widget_is_a_browser_specific_aura_native_widget(self) -> None:
        header = source(
            "chrome/browser/ui/views/frame/browser_native_widget_wasm.h"
        )

        self.assertIn("class BrowserNativeWidgetWasm", header)
        self.assertIn("public views::DesktopNativeWidgetAura", header)
        self.assertIn("public BrowserNativeWidget", header)
        self.assertIn("explicit BrowserNativeWidgetWasm(BrowserWidget*", header)
        self.assertIn(
            "void InitNativeWidget(views::Widget::InitParams params)", header
        )
        self.assertIn("void ClientDestroyedWidget() override;", header)
        self.assertIn(
            "bool ShouldSaveWindowPlacement() const override;", header
        )
        self.assertIn(
            "bool ShouldRestorePreviousBrowserWidgetState() const override;",
            header,
        )
        self.assertIn(
            "bool ShouldUseInitialVisibleOnAllWorkspaces() const override;",
            header,
        )
        self.assertIn("raw_ptr<BrowserWidget> browser_widget_;", header)
        self.assertIn("class VisibilityController;", header)
        self.assertIn(
            "std::unique_ptr<wm::VisibilityController> visibility_controller_;",
            header,
        )

        # BrowserView remains above this platform boundary. In particular this
        # class must not retain it through shutdown or access its
        # implementation.
        for forbidden in (
            "class BrowserView;",
            "raw_ptr<BrowserView>",
            '#include "chrome/browser/ui/views/frame/browser_view.h"',
            "browser_view_",
            "browser_native_widget_aura.h",
            "BrowserNativeWidgetAura",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, header)

    def test_factory_and_host_lifecycle_remain_chrome_specific(self) -> None:
        implementation = source(
            "chrome/browser/ui/views/frame/browser_native_widget_wasm.cc"
        )

        self.assertIn("#if !BUILDFLAG(IS_WASM)", implementation)
        self.assertIn(
            'GetNativeWindow()->SetName("BrowserNativeWidgetWasm");',
            implementation,
        )
        self.assertIn(
            "BrowserDesktopWindowTreeHost::CreateBrowserDesktopWindowTreeHost(",
            implementation,
        )
        self.assertRegex(
            implementation,
            r"CreateBrowserDesktopWindowTreeHost\(\s*browser_widget_,\s*"
            r"this,\s*"
            r"nullptr,\s*browser_widget_\)",
        )
        self.assertIn(
            "params.desktop_window_tree_host =\n"
            "      browser_desktop_window_tree_host->"
            "AsDesktopWindowTreeHost();",
            implementation,
        )
        self.assertIn(
            "views::DesktopNativeWidgetAura::InitNativeWidget("
            "std::move(params));",
            implementation,
        )
        self.assertIn(
            "visibility_controller_ = "
            "std::make_unique<wm::VisibilityController>();",
            implementation,
        )
        self.assertIn("aura::client::SetVisibilityClient(", implementation)
        self.assertIn(
            "wm::SetChildWindowVisibilityChangesAnimated("
            "GetNativeView()->GetRootWindow());",
            implementation,
        )
        self.assertIn("params.native_widget = this;", implementation)
        self.assertIn("params.remove_standard_frame = true;", implementation)
        self.assertIn("BrowserNativeWidgetFactory::Create(", implementation)
        self.assertRegex(
            implementation,
            r"BrowserNativeWidget\* BrowserNativeWidgetFactory::Create\(\s*"
            r"BrowserWidget\* browser_widget,\s*BrowserView\*\)",
        )
        self.assertIn(
            "return new BrowserNativeWidgetWasm(browser_widget);",
            implementation,
        )

        # This is a concrete BrowserNativeWidget implementation, not a generic
        # widget wrapper or the desktop Chrome Aura subclass.
        for forbidden in (
            "browser_native_widget_aura.h",
            "BrowserNativeWidgetAura",
            "new views::DesktopNativeWidgetAura",
            "browser_view.h",
            "browser_view_",
            "browser_view->",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, implementation)

    def test_canvas_window_policy_never_claims_persistence(self) -> None:
        implementation = source(
            "chrome/browser/ui/views/frame/browser_native_widget_wasm.cc"
        )

        self.assertIn(
            "bool BrowserNativeWidgetWasm::UseCustomFrame() const {\n"
            "  return true;\n"
            "}",
            implementation,
        )
        self.assertIn(
            "bool BrowserNativeWidgetWasm::UsesNativeSystemMenu() const {",
            implementation,
        )
        self.assertIn("return false;", implementation)

        for method in (
            "ShouldSaveWindowPlacement",
            "ShouldRestorePreviousBrowserWidgetState",
            "ShouldUseInitialVisibleOnAllWorkspaces",
        ):
            match = re.search(
                rf"bool BrowserNativeWidgetWasm::{method}\(\) const \{{"
                rf"(?P<body>.*?)\n\}}",
                implementation,
                re.DOTALL,
            )
            self.assertIsNotNone(match, method)
            self.assertIn("return false;", match.group("body"))

        self.assertIn("*bounds = gfx::Rect();", implementation)
        self.assertIn(
            "*show_state = ui::mojom::WindowShowState::kNormal;",
            implementation,
        )
        self.assertIn(
            "content::KeyboardEventProcessingResult::NOT_HANDLED",
            implementation,
        )
        self.assertIn(
            "bool BrowserNativeWidgetWasm::HandleKeyboardEvent(\n"
            "    const input::NativeWebKeyboardEvent& event) {\n"
            "  return false;\n}",
            implementation,
        )

        # Aura creates WasmWindow before BrowserWidget can resize it. The
        # platform seam supplies a non-persistent logical fallback rather than
        # relying on desktop saved placement or accepting an invalid empty
        # PlatformWindow rectangle.
        self.assertIn("if (params.bounds.IsEmpty()) {", implementation)
        self.assertIn("params.bounds = gfx::Rect(0, 0, 1024, 768);", implementation)
        self.assertIn("This non-persistent fallback is superseded", implementation)

        # Both destruction orders invalidate the BrowserWidget pointer before
        # delegating into the generic Aura lifecycle.
        for method in ("OnHostClosed", "ClientDestroyedWidget"):
            match = re.search(
                rf"void BrowserNativeWidgetWasm::{method}\(\) \{{"
                rf"(?P<body>.*?)\n\}}",
                implementation,
                re.DOTALL,
            )
            self.assertIsNotNone(match, method)
            self.assertIn("browser_widget_ = nullptr;", match.group("body"))

        host_closed_match = re.search(
            r"void BrowserNativeWidgetWasm::OnHostClosed\(\) \{"
            r"(?P<body>.*?)\n\}",
            implementation,
            re.DOTALL,
        )
        self.assertIsNotNone(host_closed_match)
        host_closed_body = host_closed_match.group("body")
        detach_client = host_closed_body.index(
            "aura::client::SetVisibilityClient("
        )
        destroy_controller = host_closed_body.index(
            "visibility_controller_.reset();"
        )
        base_teardown = host_closed_body.index(
            "views::DesktopNativeWidgetAura::OnHostClosed();"
        )
        self.assertLess(detach_client, destroy_controller)
        self.assertLess(destroy_controller, base_teardown)

    def test_source_selection_keeps_the_browser_native_widget_narrow(self) -> None:
        wasm_build = source("chrome/browser/wasm/BUILD.gn")
        target = _source_set_body(wasm_build, "wasm_browser_ui")

        self.assertIn("assert(use_aura && use_ozone && toolkit_views)", target)
        for required in (
            '"../ui/views/frame/browser_native_widget.h"',
            '"../ui/views/frame/browser_native_widget_factory.h"',
            '"../ui/views/frame/browser_native_widget_wasm.h"',
            '"../ui/views/frame/browser_widget.h"',
            '"../ui/views/frame/browser_native_widget_factory.cc"',
            '"../ui/views/frame/browser_native_widget_wasm.cc"',
            '":wasm_browser_views_platform",',
            '"//base",',
            '"//content/public/browser",',
            '"//ui/views",',
            '"//ui/aura",',
            '"//ui/base/mojom:ui_base_types",',
            '"//ui/wm",',
        ):
            with self.subTest(required=required):
                self.assertIn(required, target)

        for forbidden in (
            "//chrome/browser/ui:ui",
            "browser_native_widget_aura.cc",
            "browser_native_widget_aura.h",
            "browser_native_widget_factory_aura.cc",
            "//chrome/browser/themes:themes",
            "//chrome/browser/ui/browser_window/internal",
            "//chrome/common:constants",
            "//chrome/browser/history",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, target)

        self.assertNotIn(":wasm_browser_ui", source("chrome/BUILD.gn"))
        self.assertNotIn(
            ":wasm_browser_ui", _source_set_body(wasm_build, "wasm_browser_main_parts")
        )


if __name__ == "__main__":
    unittest.main()
