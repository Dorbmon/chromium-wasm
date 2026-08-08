#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the structural Wasm tab-modal Views host.

This is intentionally a geometry and lifetime seam only. It must not wire a
WebContentsModalDialogManager delegate or admit a desktop Browser lifecycle.
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


class M6WasmTabModalDialogHostContractTest(unittest.TestCase):
    def test_host_is_a_real_views_modal_host_with_explicit_lifetime(self) -> None:
        header = source(
            "chrome/browser/ui/views/frame/tab_modal_dialog_host_wasm.h"
        )
        implementation = source(
            "chrome/browser/ui/views/frame/tab_modal_dialog_host_wasm.cc"
        )

        self.assertIn("class WasmTabModalDialogHost final", header)
        self.assertIn("public web_modal::WebContentsModalDialogHost", header)
        self.assertIn("public views::ViewObserver", header)
        self.assertIn("public views::WidgetObserver", header)
        self.assertIn("explicit WasmTabModalDialogHost(views::WebView*", header)
        self.assertIn("gfx::NativeView GetHostView() const override;", header)
        self.assertIn(
            "gfx::Point GetDialogPosition(const gfx::Size& dialog_size) override;",
            header,
        )
        self.assertIn("gfx::Size GetMaximumDialogSize() override;", header)
        self.assertIn("bool ShouldActivateDialog() const override;", header)
        self.assertIn(
            "bool ShouldConstrainDialogBoundsByHost() override;", header
        )
        self.assertIn("void AddObserver(web_modal::ModalDialogHostObserver*", header)
        self.assertIn("void RemoveObserver(web_modal::ModalDialogHostObserver*", header)
        self.assertIn("raw_ptr<views::WebView> contents_web_view_;", header)
        self.assertIn("contents_web_view_observation_", header)
        self.assertIn("widget_observation_", header)
        self.assertIn("base::ObserverList<web_modal::ModalDialogHostObserver>", header)
        self.assertIn("bool host_destroying_ = false;", header)

        self.assertIn("#if !BUILDFLAG(IS_WASM)", implementation)
        self.assertIn("contents_web_view_observation_.Observe(contents_web_view_);", implementation)
        self.assertIn("ObserveWidget();", implementation)
        self.assertIn("contents_web_view_observation_.Reset();", implementation)
        self.assertIn("widget_observation_.Reset();", implementation)
        self.assertIn("NotifyHostDestroying();", implementation)
        self.assertIn("contents_web_view_ = nullptr;", implementation)

    def test_geometry_uses_the_outer_widget_and_active_webview_bounds(self) -> None:
        implementation = source(
            "chrome/browser/ui/views/frame/tab_modal_dialog_host_wasm.cc"
        )

        self.assertIn(
            "host_widget ? host_widget->GetNativeView() : gfx::NativeView();",
            implementation,
        )
        self.assertIn("contents_web_view_->ConvertRectToWidget(", implementation)
        self.assertIn("contents_web_view_->GetLocalBounds()", implementation)
        self.assertIn("(contents_bounds.width() - dialog_size.width()) / 2", implementation)
        self.assertIn("contents_bounds.y()", implementation)
        self.assertIn("return GetContentsBoundsInWidget().size();", implementation)
        self.assertIn("host_widget && host_widget->ShouldPaintAsActive();", implementation)
        self.assertRegex(
            implementation,
            r"(?s)bool WasmTabModalDialogHost::ShouldConstrainDialogBoundsByHost\(\)"
            r"\s*\{.*?return true;",
        )

        # Host destruction is observable, and geometry updates are sent from
        # both the active content view and the outer Widget.
        self.assertIn(
            "&web_modal::ModalDialogHostObserver::OnPositionRequiresUpdate",
            implementation,
        )
        self.assertIn(
            "&web_modal::ModalDialogHostObserver::OnHostDestroying",
            implementation,
        )
        self.assertIn("void WasmTabModalDialogHost::OnViewBoundsChanged", implementation)
        self.assertIn("void WasmTabModalDialogHost::OnWidgetBoundsChanged", implementation)
        self.assertIn("void WasmTabModalDialogHost::OnWidgetDestroying", implementation)

    def test_target_stays_outside_modal_manager_and_browser_lifecycles(self) -> None:
        wasm_build = source("chrome/browser/wasm/BUILD.gn")
        target = _source_set_body(wasm_build, "wasm_tab_modal_dialog_host")
        header = source(
            "chrome/browser/ui/views/frame/tab_modal_dialog_host_wasm.h"
        )
        implementation = source(
            "chrome/browser/ui/views/frame/tab_modal_dialog_host_wasm.cc"
        )

        for expected in (
            '"../ui/views/frame/tab_modal_dialog_host_wasm.h"',
            '"../ui/views/frame/tab_modal_dialog_host_wasm.cc"',
            '"//base",',
            '"//components/web_modal",',
            '"//ui/gfx",',
            '"//ui/gfx/geometry"',
            '"//ui/views",',
            '"//ui/views/controls/webview:webview",',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, target)

        forbidden_target = (
            "//chrome/browser/ui:ui",
            "//chrome/browser/ui/web_modal",
            "//components/constrained_window",
            ":wasm_browser_main_parts",
            ":wasm_browser_window_features",
        )
        for forbidden_text in forbidden_target:
            with self.subTest(forbidden=forbidden_text):
                self.assertNotIn(forbidden_text, target)

        forbidden_source = (
            "WebContentsModalDialogManager",
            "WebContentsModalDialogManagerDelegate",
            "BrowserWindowModalDialogDelegate",
            "BrowserWindowFeatures",
            "TabStripModel",
            "TabDialogManager",
            "constrained_window",
        )
        for text in (header, implementation):
            for forbidden_text in forbidden_source:
                with self.subTest(source=text[:40], forbidden=forbidden_text):
                    self.assertNotIn(forbidden_text, text)

        self.assertNotIn(":wasm_tab_modal_dialog_host", source("chrome/BUILD.gn"))
        self.assertNotIn(
            ":wasm_tab_modal_dialog_host",
            _source_set_body(wasm_build, "wasm_browser_main_parts"),
        )


if __name__ == "__main__":
    unittest.main()
