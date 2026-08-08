#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for Wasm's pre-BrowserView Chrome toolkit initialization."""

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


def _method_body(implementation: str, method: str) -> str:
    match = re.search(
        rf"void WasmBrowserMainParts::{re.escape(method)}\(\) \{{"
        rf"(?P<body>.*?)\n\}}",
        implementation,
        re.DOTALL,
    )
    if not match:
        raise AssertionError(f"could not find WasmBrowserMainParts::{method}()")
    return match.group("body")


class M6ToolkitInitializationContractTest(unittest.TestCase):
    def test_toolkit_initialized_registers_canonical_startup_state_in_order(
        self,
    ) -> None:
        header = source("chrome/browser/wasm/wasm_browser_main_parts.h")
        implementation = source("chrome/browser/wasm/wasm_browser_main_parts.cc")

        self.assertIn("void ToolkitInitialized() override;", header)
        body = _method_body(implementation, "ToolkitInitialized")

        component_initializer = (
            "base::BindRepeating(color::AddComponentsColorMixers)"
        )
        chrome_initializer = "base::BindRepeating(AddChromeColorMixers)"
        action_mapping = "InitializeActionIdStringMapping();"
        for required in (component_initializer, chrome_initializer, action_mapping):
            with self.subTest(required=required):
                self.assertIn(required, body)

        self.assertLess(
            body.index(component_initializer), body.index(chrome_initializer)
        )
        self.assertLess(body.index(chrome_initializer), body.index(action_mapping))

        # Mapping strings is safe before a browser exists; creating an action
        # root or a Browser would cross the intentionally unselected M6 seam.
        self.assertNotIn("InitializeChromeActions", body)
        self.assertNotIn("Browser::Create(", body)

    def test_wasm_feature_definitions_match_the_canonical_color_dependencies(
        self,
    ) -> None:
        features = source("chrome/browser/wasm/wasm_browser_toolkit_features.cc")

        self.assertIn("#if !BUILDFLAG(IS_WASM)", features)
        self.assertIn(
            '#error "wasm_browser_toolkit_features.cc must only be built for WebAssembly"',
            features,
        )
        for feature, predicate in (
            (
                "kTabGroupColorRefresh",
                "IsTabGroupColorRefreshEnabled",
            ),
            (
                "kWebuiRefresh2026",
                "IsWebuiRefresh2026Enabled",
            ),
        ):
            with self.subTest(feature=feature):
                self.assertIn(
                    f"BASE_FEATURE({feature}, base::FEATURE_DISABLED_BY_DEFAULT);",
                    features,
                )
                self.assertIn(f"bool {predicate}()", features)
                self.assertIn(
                    f"base::FeatureList::IsEnabled({feature})", features
                )

        self.assertEqual(
            2, features.count("base::FeatureList::IsEnabled(kDesktopGlowUp)")
        )

    def test_source_selection_is_canonical_and_excludes_desktop_runtime_graphs(
        self,
    ) -> None:
        wasm_build = source("chrome/browser/wasm/BUILD.gn")
        feature_target = _source_set_body(
            wasm_build, "wasm_browser_toolkit_features"
        )
        toolkit_target = _source_set_body(wasm_build, "wasm_browser_toolkit")

        self.assertIn('"wasm_browser_toolkit_features.cc"', feature_target)
        self.assertIn('"../ui/ui_features.h"', feature_target)
        self.assertIn('"//ui/base:features"', feature_target)
        # ui_features.h needs an extension buildflag declaration, but no
        # extension runtime target is selected for this toolkit slice.
        self.assertIn('"//extensions/buildflags"', feature_target)
        for forbidden in (
            "//extensions/browser",
            "//extensions/common",
            "//chrome/browser/ui:ui",
            "//chrome/browser/themes",
            "//chrome/browser/history",
            "//chrome/common:constants",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, feature_target)

        canonical_sources = (
            "../ui/actions/chrome_actions.cc",
            "../ui/color/chrome_color_mixer.cc",
            "../ui/color/chrome_color_mixers.cc",
            "../ui/color/chrome_color_provider_utils.cc",
            "../ui/color/material_chrome_color_mixer.cc",
            "../ui/color/material_new_tab_page_color_mixer.cc",
            "../ui/color/material_omnibox_color_mixer.cc",
            "../ui/color/material_side_panel_color_mixer.cc",
            "../ui/color/material_tab_strip_color_mixer.cc",
            "../ui/color/native_chrome_color_mixer.cc",
            "../ui/color/new_tab_page_color_mixer.cc",
            "../ui/color/omnibox_color_mixer.cc",
            "../ui/color/product_specifications_color_mixer.cc",
            "../ui/color/projects_panel_color_mixer.cc",
            "../ui/color/tab_strip_color_mixer.cc",
        )
        for source_file in canonical_sources:
            with self.subTest(source_file=source_file):
                self.assertIn(f'"{source_file}"', toolkit_target)

        self.assertIn(
            'configs += [ "//build/config/compiler:wexit_time_destructors" ]',
            toolkit_target,
        )

        for required in (
            '"../ui/color/chrome_color_id.h",',
            '":wasm_browser_toolkit_features",',
            '"//components/color:color_headers",',
            '"//ui/color:color_headers",',
            '"//chrome/browser/themes:theme_properties",',
            '"//chrome/browser/ui/actions:actions_headers",',
            '"//components/color",',
            '"//ui/actions",',
            '"//ui/color",',
            '"//ui/color:mixers",',
        ):
            with self.subTest(required=required):
                self.assertIn(required, toolkit_target)

        # ThemeProperties is a static color-token helper. The profile-backed
        # themes aggregate and all desktop Browser UI/runtime graphs stay out.
        for forbidden in (
            '"//chrome/browser/ui:ui",',
            '"//chrome/browser/ui/color:color_headers",',
            '"//chrome/browser/themes",',
            '"//chrome/common:constants",',
            '"//chrome/browser/history",',
            '"//extensions/browser",',
            '"//extensions/common",',
            '"//chrome/browser/ui/browser_window",',
            '"//chrome/browser/ui/views",',
            ":wasm_browser_ui",
            "Browser::Create",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, toolkit_target)

        main_parts_target = _source_set_body(
            wasm_build, "wasm_browser_main_parts"
        )
        self.assertIn('":wasm_browser_toolkit",', main_parts_target)
        self.assertEqual(1, wasm_build.count('":wasm_browser_toolkit",'))


if __name__ == "__main__":
    unittest.main()
