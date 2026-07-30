#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M3GfxFontSourceContractTest(unittest.TestCase):
    def test_wasm_selects_the_platform_neutral_skia_font_sources(self) -> None:
        build = source("ui/gfx/BUILD.gn")
        blink_sources = build.split("  if (use_blink) {", 1)[1].split(
            "  if (use_aura || toolkit_views)", 1
        )[0]

        self.assertIn(
            "if (is_android || is_fuchsia || is_ios || is_wasm) {\n"
            "      sources += [\n"
            '        "font_fallback_skia.cc",\n'
            '        "font_render_params_skia.cc",',
            blink_sources,
        )
        self.assertIn(
            "if (is_android || is_fuchsia || is_win || is_apple || "
            "is_wasm) {\n"
            "      sources += [\n"
            '        "font_fallback_skia_impl.cc",\n'
            '        "font_fallback_skia_impl.h",',
            blink_sources,
        )
        self.assertNotIn("font_fallback_linux.cc", blink_sources)
        self.assertNotIn("font_render_params_linux.cc", blink_sources)

    def test_skia_defaults_do_not_claim_host_font_configuration(self) -> None:
        render_params = source("ui/gfx/font_render_params_skia.cc")

        self.assertIn(
            "if (family_out)\n    NOTIMPLEMENTED();",
            render_params,
        )
        self.assertIn(
            "static const gfx::FontRenderParams params(LoadDefaults());",
            render_params,
        )
        self.assertIn(
            "float GetFontRenderParamsDeviceScaleFactor() {\n"
            "  return device_scale_factor_;\n"
            "}",
            render_params,
        )
        self.assertNotIn("fontconfig", render_params.lower())

    def test_skia_fallback_reports_missing_typefaces_as_failure(self) -> None:
        fallback = source("ui/gfx/font_fallback_skia.cc")
        fallback_impl = source("ui/gfx/font_fallback_skia_impl.cc")

        self.assertIn(
            "std::vector<Font> GetFallbackFonts(const Font& font) {\n"
            "  return std::vector<Font>();\n"
            "}",
            fallback,
        )
        self.assertIn(
            "if (text.empty())\n    return false;",
            fallback,
        )
        self.assertIn(
            "if (!fallback_typeface)\n    return false;",
            fallback,
        )
        self.assertIn("skia::DefaultFontMgr()", fallback_impl)
        self.assertIn(
            "if (!typeface || "
            "!tested_typeface.insert(typeface->uniqueID()).second)\n"
            "      continue;",
            fallback_impl,
        )
        self.assertNotIn("fontconfig", fallback_impl.lower())


if __name__ == "__main__":
    unittest.main()
