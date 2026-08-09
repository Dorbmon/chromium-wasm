#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the deterministic, data-backed Wasm platform font path."""

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M4WasmFontManagerContractTest(unittest.TestCase):
    def test_wasm_installs_a_real_font_before_skia_default_lookup(self) -> None:
        font_util = source("ui/gfx/font_util.cc")
        wasm_font_util = source("ui/gfx/font_util_wasm.cc")
        gfx_build = source("ui/gfx/BUILD.gn")

        self.assertIn('"font_util_wasm.cc"', gfx_build)
        self.assertIn('"font_util_wasm.h"', gfx_build)
        self.assertIn("if (is_wasm)", gfx_build)
        self.assertIn("InitializeFontsWasm();", font_util)
        self.assertLess(
            font_util.index("InitializeFontsWasm();"),
            font_util.index("skia::InitializeFontRendering();"),
        )

        for expected in (
            'constexpr char kWasmDefaultFontPath[] = "/assets/Roboto-Regular.ttf";',
            "SkData::MakeFromFileName(kWasmDefaultFontPath)",
            "SkFontMgr_New_Custom_Data(font_data)",
            "legacyMakeTypeface(nullptr, SkFontStyle())",
            "typeface.unicharToGlyph('x')",
            "font.measureText(kFontMetricsProbe",
            "skia::OverrideDefaultSkFontMgr(std::move(font_manager));",
            'skia::MakeTypefaceFromName("sans", SkFontStyle())',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, wasm_font_util)

        for forbidden in (
            "SkTypeface::MakeEmpty",
            "SetAverageWidth",
            "FontConfig",
            "default_width_in_chars_",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, wasm_font_util)

    def test_skia_selects_the_data_manager_only_for_wasm_freetype(self) -> None:
        skia_build = source("skia/BUILD.gn")
        wasm_font_block = skia_build.split(
            "# The platform FontConfig path is intentionally unavailable on Wasm.",
            1,
        )[1].split("    }\n    sources += skia_ports_typeface_proxy_sources", 1)[0]

        self.assertIn("if (is_wasm)", wasm_font_block)
        self.assertIn("skia_ports_fontmgr_embedded_sources", wasm_font_block)
        self.assertIn("skia_ports_fontmgr_embedded_public", wasm_font_block)
        self.assertNotIn("skia_ports_fontmgr_fontconfig", wasm_font_block)

    def test_all_current_wasm_browser_executables_embed_the_font_asset(self) -> None:
        chrome_build = source("chrome/BUILD.gn")
        shell_build = source("content/shell/BUILD.gn")

        for build in (chrome_build, shell_build):
            self.assertIn(
                '"//third_party/skia/resources/fonts/Roboto-Regular.ttf"', build
            )
            self.assertIn("@/assets/Roboto-Regular.ttf", build)

        for target in (
            'executable("content_shell_wasm")',
            'executable("content_shell_wasm_m5_test")',
            'executable("content_shell_wasm_m5_controlled_preflight_test")',
            'executable("content_shell_wasm_m5_public_test")',
        ):
            with self.subTest(target=target):
                target_body = shell_build.split(target, 1)[1].split("\n  }", 1)[0]
                self.assertIn("wasm_default_font_asset", target_body)


if __name__ == "__main__":
    unittest.main()
