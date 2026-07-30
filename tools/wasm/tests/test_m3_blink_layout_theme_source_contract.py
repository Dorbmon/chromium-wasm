#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M3BlinkLayoutThemeSourceContractTest(unittest.TestCase):
    def test_wasm_selects_a_dedicated_layout_theme(self) -> None:
        build = source("third_party/blink/renderer/core/layout/build.gni")
        wasm_sources = build.split("if (is_wasm) {", 1)[1].split(
            "}", 1
        )[0]

        self.assertIn(
            'blink_core_sources_layout += [ "layout_theme_wasm.cc" ]',
            wasm_sources,
        )
        self.assertNotIn("layout_theme_linux.cc", wasm_sources)
        self.assertNotIn("layout_theme_fuchsia.cc", wasm_sources)

    def test_wasm_theme_is_a_guarded_default_theme(self) -> None:
        implementation = source(
            "third_party/blink/renderer/core/layout/layout_theme_wasm.cc"
        )

        self.assertIn('#include "build/build_config.h"', implementation)
        self.assertIn(
            "#if !BUILDFLAG(IS_WASM)\n"
            '#error "layout_theme_wasm.cc must only be built for '
            'WebAssembly"\n'
            "#endif",
            implementation,
        )
        self.assertIn(
            "class LayoutThemeWasm : public LayoutThemeDefault",
            implementation,
        )
        self.assertIn(
            "return base::AdoptRef(new LayoutThemeWasm());",
            implementation,
        )
        self.assertNotIn("ui::NativeTheme", implementation)
        self.assertNotIn("fontconfig", implementation.lower())
        self.assertNotIn("Platform::Current", implementation)

    def test_native_theme_is_process_static(self) -> None:
        implementation = source(
            "third_party/blink/renderer/core/layout/layout_theme_wasm.cc"
        )

        self.assertIn(
            "LayoutTheme& LayoutTheme::NativeTheme() {\n"
            "  DEFINE_STATIC_REF(LayoutTheme, layout_theme, "
            "(LayoutThemeWasm::Create()));\n"
            "  return *layout_theme;\n"
            "}",
            implementation,
        )

    def test_production_theme_lookup_calls_native_theme(self) -> None:
        implementation = source(
            "third_party/blink/renderer/core/layout/layout_theme.cc"
        )

        self.assertIn(
            "LayoutTheme& LayoutTheme::GetTheme()",
            implementation,
        )
        self.assertIn("return NativeTheme();", implementation)


if __name__ == "__main__":
    unittest.main()
