#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the explicitly limited Wasm chrome://settings bootstrap."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def _source_set_body(build_file: str, target: str) -> str:
    match = re.search(rf'\bsource_set\("{re.escape(target)}"\)', build_file)
    if not match:
        raise AssertionError(f"missing source set {target!r}")
    opening_brace = build_file.find("{", match.end())
    if opening_brace < 0:
        raise AssertionError(f"missing opening brace for {target!r}")
    depth = 0
    for index in range(opening_brace, len(build_file)):
        if build_file[index] == "{":
            depth += 1
        elif build_file[index] == "}":
            depth -= 1
            if depth == 0:
                return build_file[opening_brace + 1 : index]
    raise AssertionError(f"missing closing brace for {target!r}")


class M6WasmSettingsUIContractTest(unittest.TestCase):
    def test_target_excludes_desktop_settings_graph(self) -> None:
        build = source("chrome/browser/wasm/BUILD.gn")
        target = _source_set_body(build, "wasm_settings_ui")

        for required in (
            '":wasm_browser_main_parts",',
            '":wasm_browser_smoke",',
            '"wasm_settings_ui.h"',
            '"wasm_settings_ui.cc"',
            '"//content/public/browser"',
            '"//content/public/common"',
        ):
            with self.subTest(required=required):
                self.assertIn(required, target)

        for forbidden in (
            "//chrome/browser/ui:ui",
            "//chrome/browser/ui/webui/settings",
            "//chrome/browser/themes",
            "//components/prefs",
            "//components/webui/settings",
            "//components/omnibox",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, target)

    def test_config_and_data_source_claim_only_the_read_only_root(self) -> None:
        header = source("chrome/browser/wasm/wasm_settings_ui.h")
        implementation = source("chrome/browser/wasm/wasm_settings_ui.cc")

        for required in (
            "class WasmSettingsUI final : public content::WebUIController",
            "WEB_UI_CONTROLLER_TYPE_DECL();",
            "class WasmSettingsUIConfig final",
            "content::DefaultWebUIConfig<WasmSettingsUI>",
            "bool ShouldHandleURL(const GURL& url) override;",
            "EnsureWasmSettingsWebUIConfigRegistered",
        ):
            with self.subTest(required=required):
                self.assertIn(required, header)

        for required in (
            "bool IsWasmSettingsRootURL",
            'url.host() == kWasmSettingsHost',
            "url.path() == \"/\" || url.path().empty()",
            "class WasmSettingsDataSource final : public content::URLDataSource",
            "std::move(callback).Run(nullptr);",
            "bool AllowCaching() override { return false; }",
            "content::URLDataSource::Add(",
            "std::make_unique<WasmSettingsUIConfig>()",
            "static bool registered = false;",
            "Limited M6 bootstrap",
            "read-only and volatile",
            "OPFS-backed profile",
        ):
            with self.subTest(required=required):
                self.assertIn(required, implementation)

        for forbidden in (
            "settings::SettingsUI",
            "WebUIDataSource",
            "AddString",
            "AddMessageHandler",
            "javascript",
            "ThemeService",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, implementation)

    def test_registration_and_navigation_are_explicit_and_concrete(self) -> None:
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        client = source("chrome/browser/wasm/wasm_content_browser_client.cc")
        controls = source("chrome/browser/wasm/wasm_top_controls_view.cc")
        smoke = source("chrome/browser/wasm/wasm_browser_smoke.cc")

        registration = "chrome::EnsureWasmSettingsWebUIConfigRegistered();"
        profile_creation = "profile_ = std::make_unique<WasmProfile>(profile_path);"
        self.assertIn(registration, main_parts)
        self.assertLess(main_parts.index(registration), main_parts.index(profile_creation))
        self.assertIn('constexpr char kWasmSettingsHost[] = "settings";', client)
        self.assertIn('constexpr char kWasmSettingsURL[] = "chrome://settings/";', controls)

        for required in (
            'constexpr char kSettingsWebUIUrl[] = "chrome://settings/";',
            'CHECK_EQ(settings_web_ui_config->host(), "settings");',
            "GetAs<WasmSettingsUI>()",
            'CHECK_EQ(raw_first_contents->GetTitle(), u"Settings \\u2014 Chromium Wasm");',
            '"CHROMIUM_WASM_M6_SETTINGS_BOOTSTRAP:PASS"',
        ):
            with self.subTest(required=required):
                self.assertIn(required, smoke)


if __name__ == "__main__":
    unittest.main()
