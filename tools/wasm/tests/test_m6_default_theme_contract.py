#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Source contracts for the M6 fixed Wasm default theme provider."""

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


class M6DefaultThemeContractTest(unittest.TestCase):
    def test_properties_are_split_from_the_desktop_theme_service_graph(
        self,
    ) -> None:
        themes_build = source("chrome/browser/themes/BUILD.gn")
        generic_properties = _source_set_body(themes_build, "theme_properties")
        desktop_themes = _source_set_body(themes_build, "themes")
        properties_header = source("chrome/browser/themes/theme_properties.h")
        properties_source = source("chrome/browser/themes/theme_properties.cc")
        helper_source = source("chrome/browser/themes/theme_helper.cc")

        self.assertIn("is_chromeos || is_wasm", themes_build)
        self.assertIn("if (!is_wasm)", themes_build)
        self.assertIn('"theme_properties.h"', generic_properties)
        self.assertIn('"theme_properties.cc"', generic_properties)
        self.assertIn('"//base"', generic_properties)
        self.assertIn('"//ui/gfx"', generic_properties)
        self.assertIn('"//ui/gfx:color_utils"', generic_properties)
        self.assertIn('":theme_properties"', desktop_themes)
        self.assertNotIn('"theme_properties.h"', desktop_themes)
        self.assertNotIn('"theme_properties.cc"', desktop_themes)

        self.assertIn("GetDefaultDisplayProperty(int id)", properties_header)
        for default_case in (
            "NTP_BACKGROUND_ALIGNMENT",
            "NTP_BACKGROUND_TILING",
            "NTP_LOGO_ALTERNATE",
            "SHOULD_FILL_BACKGROUND_TAB_COLOR",
        ):
            with self.subTest(default_case=default_case):
                self.assertIn(f"case {default_case}:", properties_source)
        self.assertIn("return TP::GetDefaultDisplayProperty(id);", helper_source)

    def test_provider_uses_resources_and_generic_defaults_without_services(
        self,
    ) -> None:
        provider_target = _source_set_body(
            source("chrome/browser/wasm/BUILD.gn"),
            "wasm_default_theme_provider",
        )
        header = source("chrome/browser/wasm/wasm_default_theme_provider.h")
        implementation = source(
            "chrome/browser/wasm/wasm_default_theme_provider.cc"
        )

        self.assertIn('"wasm_default_theme_provider.h"', provider_target)
        self.assertIn('"wasm_default_theme_provider.cc"', provider_target)
        self.assertIn(
            '"//chrome/browser/themes:theme_properties"', provider_target
        )
        self.assertIn('"//ui/base"', provider_target)
        self.assertIn("class WasmDefaultThemeProvider", header)
        self.assertIn("CreateWasmDefaultThemeProvider", header)
        self.assertIn(
            "ResourceBundle::GetSharedInstance().GetImageSkiaNamed",
            implementation,
        )
        self.assertIn("LoadDataResourceBytesForScale", implementation)
        self.assertIn("ThemeProperties::GetDefaultTint", implementation)
        self.assertIn("ThemeProperties::GetDefaultDisplayProperty", implementation)
        self.assertIn("return false;", implementation)
        self.assertIn("must only be built for WebAssembly", implementation)

        for forbidden in (
            "//chrome/browser/themes:themes",
            "//extensions",
            "//components/sync",
            "//chrome/browser/ui/webui/new_tab_page",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, provider_target)

        for forbidden in (
            "ThemeService",
            "theme_service",
            "ThemeServiceFactory",
            "extensions/",
            "sync/",
            "new_tab_page",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, implementation)

    def test_provider_stays_unwired_until_browser_widget_lifecycle_exists(
        self,
    ) -> None:
        chrome_build = source("chrome/BUILD.gn")
        main_parts = _source_set_body(
            source("chrome/browser/wasm/BUILD.gn"), "wasm_browser_main_parts"
        )

        self.assertNotIn(":wasm_default_theme_provider", chrome_build)
        self.assertNotIn(":wasm_default_theme_provider", main_parts)


if __name__ == "__main__":
    unittest.main()
