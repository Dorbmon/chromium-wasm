#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the Wasm Browser's explicitly modeless top-level host."""

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M6BrowserModelessContractTest(unittest.TestCase):
    def test_browser_only_wasm_host_is_source_selected(self) -> None:
        build = source("chrome/browser/wasm/BUILD.gn")
        native_widget = source(
            "chrome/browser/ui/views/frame/browser_native_widget_wasm.cc"
        )
        header = source(
            "chrome/browser/ui/views/frame/browser_desktop_window_tree_host_wasm.h"
        )

        self.assertIn('source_set("wasm_browser_views_platform")', build)
        self.assertIn(
            '"../ui/views/frame/browser_desktop_window_tree_host_wasm.cc"', build
        )
        self.assertIn("BrowserDesktopWindowTreeHostWasm", header)
        self.assertIn(
            "BrowserDesktopWindowTreeHost::CreateBrowserDesktopWindowTreeHost(",
            native_widget,
        )
        self.assertIn(
            "params.desktop_window_tree_host =\n"
            "      browser_desktop_window_tree_host->AsDesktopWindowTreeHost();",
            native_widget,
        )

    def test_only_the_modeless_browser_contract_is_accepted(self) -> None:
        header = source(
            "chrome/browser/ui/views/frame/browser_desktop_window_tree_host_wasm.h"
        )
        implementation = source(
            "chrome/browser/ui/views/frame/browser_desktop_window_tree_host_wasm.cc"
        )
        generic_host = source(
            "ui/views/widget/desktop_aura/desktop_window_tree_host_platform.cc"
        )

        self.assertIn(
            "void InitModalType(ui::mojom::ModalType modal_type) override;", header
        )
        self.assertIn(
            "void BrowserDesktopWindowTreeHostWasm::InitModalType(\n"
            "    ui::mojom::ModalType modal_type)",
            implementation,
        )
        self.assertIn(
            "CHECK_EQ(modal_type, ui::mojom::ModalType::kNone);", implementation
        )
        self.assertIn("requires no PlatformWindow or host-page action", implementation)
        self.assertIn("Do not turn an\n  // unexpected modal request", implementation)
        self.assertNotIn("WasmWindow", implementation)
        self.assertNotIn("platform_window()", implementation)

        # Generic dialogs/non-Browser DesktopNativeWidgetAura users retain the
        # pre-existing explicit unsupported path. This Browser-only override
        # must not weaken that boundary.
        generic_modal = generic_host.split(
            "void DesktopWindowTreeHostPlatform::InitModalType(", 1
        )[1].split("void DesktopWindowTreeHostPlatform::FlashFrame", 1)[0]
        self.assertIn("NOTIMPLEMENTED_LOG_ONCE();", generic_modal)


if __name__ == "__main__":
    unittest.main()
