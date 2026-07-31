#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M3BlinkFontCacheSourceContractTest(unittest.TestCase):
    def test_wasm_selects_a_dedicated_blink_font_cache(self) -> None:
        build = source("third_party/blink/renderer/platform/BUILD.gn")
        wasm_sources = build.split("  if (is_wasm) {", 1)[1].split(
            "  # Add in the generated files.", 1
        )[0]

        self.assertIn('"fonts/wasm/font_cache_wasm.cc",', wasm_sources)
        self.assertNotIn("fonts/linux/font_cache_linux.cc", wasm_sources)
        self.assertNotIn("fonts/fuchsia/font_cache_fuchsia.cc", wasm_sources)

    def test_empty_system_family_is_an_explicitly_supported_state(self) -> None:
        font_cache = source(
            "third_party/blink/renderer/platform/fonts/font_cache.cc"
        )

        self.assertIn(
            "BUILDFLAG(IS_FUCHSIA) || BUILDFLAG(IS_IOS) || "
            "BUILDFLAG(IS_WASM)",
            font_cache,
        )
        self.assertIn(
            "if (family.empty() || family == font_family_names::kSystemUi)\n"
            "    return nullptr;",
            font_cache,
        )

    def test_system_family_starts_empty_and_only_stores_real_names(
        self,
    ) -> None:
        implementation = source(
            "third_party/blink/renderer/platform/fonts/wasm/"
            "font_cache_wasm.cc"
        )

        self.assertIn(
            "DEFINE_THREAD_SAFE_STATIC_LOCAL(AtomicString, "
            "system_font_family, ());",
            implementation,
        )
        self.assertIn('#include "build/build_config.h"', implementation)
        self.assertIn(
            "#if !BUILDFLAG(IS_WASM)\n"
            '#error "font_cache_wasm.cc must only be built for WebAssembly"\n'
            "#endif",
            implementation,
        )
        self.assertIn(
            "if (family_name.empty()) {\n"
            "    return;\n"
            "  }\n"
            "  MutableSystemFontFamily() = family_name;",
            implementation,
        )

    def test_character_fallback_uses_the_bundled_skia_font_manager(
        self,
    ) -> None:
        implementation = source(
            "third_party/blink/renderer/platform/fonts/wasm/"
            "font_cache_wasm.cc"
        )

        self.assertIn("skia::DefaultFontMgr()", implementation)
        self.assertIn("GetBcp47LocaleForRequest", implementation)
        self.assertIn("matchFamilyStyleCharacter", implementation)
        self.assertIn(
            "if (!typeface) {\n"
            "    return nullptr;\n"
            "  }",
            implementation,
        )
        self.assertIn(
            "MakeGarbageCollected<FontPlatformData>",
            implementation,
        )
        self.assertIn(
            "return FontDataFromFontPlatformData(font_data);",
            implementation,
        )
        self.assertNotIn("fontconfig", implementation.lower())
        self.assertNotIn("WebSandboxSupport", implementation)

    def test_wasm_does_not_enter_fontconfig_typeface_factory(self) -> None:
        implementation = source(
            "third_party/blink/renderer/platform/fonts/skia/"
            "sktypeface_factory.cc"
        )
        fontconfig_factory = implementation.split(
            "SkTypeface_Factory::FromFontConfigInterfaceIdAndTtcIndex(", 1
        )[1].split(
            "SkTypeface_Factory::FromFilenameAndTtcIndex(", 1
        )[0]
        filename_factory = implementation.split(
            "SkTypeface_Factory::FromFilenameAndTtcIndex(", 1
        )[1]

        self.assertIn(
            "!BUILDFLAG(IS_FUCHSIA) && !BUILDFLAG(IS_WASM)",
            fontconfig_factory,
        )
        self.assertIn("SkFontConfigInterface::RefGlobal()", fontconfig_factory)
        self.assertIn("#else\n  NOTREACHED();", fontconfig_factory)
        self.assertIn(
            "#if !BUILDFLAG(IS_WASM)\n"
            '#include "third_party/skia/include/ports/'
            'SkFontConfigInterface.h"\n'
            "#endif",
            implementation,
        )
        self.assertIn(
            "SkFontMgr_New_Fontations_Empty()->makeFromFile",
            filename_factory,
        )
        self.assertNotIn("IS_WASM", filename_factory)


if __name__ == "__main__":
    unittest.main()
