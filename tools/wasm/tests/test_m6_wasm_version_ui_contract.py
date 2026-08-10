#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the first source-selected Wasm Chrome WebUI."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def source_set_body(build_file: str, target: str) -> str:
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


class M6WasmVersionUIContractTest(unittest.TestCase):
    def test_source_selection_is_one_real_version_page_not_desktop_webui(self) -> None:
        build = source("chrome/browser/wasm/BUILD.gn")
        target = source_set_body(build, "wasm_version_ui")

        for required in (
            '"../ui/webui/version/version_handler.cc"',
            '"../ui/webui/version/version_ui.cc"',
            '"wasm_version_theme_source.cc"',
            '"wasm_version_ui.cc"',
            '":wasm_browser_main_parts",',
            '":wasm_browser_smoke",',
            '"//chrome/app/theme:theme_resources",',
            '"//components/resources:components_scaled_resources",',
            '"//components/webui/version/resources",',
            '"//content/public/browser",',
            '"//content/public/common",',
        ):
            with self.subTest(required=required):
                self.assertIn(required, target)

        for forbidden in (
            "//chrome/browser/ui:ui",
            "../ui/webui/theme_source.cc",
            "//chrome/browser/themes",
            "//chrome/browser/ui/webui/settings",
            "//components/javascript_dialogs",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, target)

    def test_registration_precedes_profile_and_any_browser_contents(self) -> None:
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        registration = "chrome::EnsureWasmVersionWebUIConfigRegistered();"
        profile_creation = "profile_ = std::make_unique<WasmProfile>(profile_path);"
        self.assertIn(registration, main_parts)
        self.assertIn(profile_creation, main_parts)
        self.assertLess(main_parts.index(registration), main_parts.index(profile_creation))

        registration_source = source("chrome/browser/wasm/wasm_version_ui.cc")
        for required in (
            "DCHECK_CURRENTLY_ON(content::BrowserThread::UI);",
            "static bool registered = false;",
            "std::make_unique<VersionUIConfig>()",
            "content::WebUIConfigMap::GetInstance().AddWebUIConfig",
        ):
            with self.subTest(required=required):
                self.assertIn(required, registration_source)

    def test_version_controller_uses_explicit_wasm_theme_and_variations_boundary(self) -> None:
        version_header = source("chrome/browser/ui/webui/version/version_ui.h")
        version_ui = source("chrome/browser/ui/webui/version/version_ui.cc")

        self.assertIn('DefaultWebUIConfig(content::kChromeUIScheme, "version")', version_header)
        self.assertIn("std::make_unique<chrome::WasmVersionThemeSource>()", version_ui)
        self.assertIn("base::Time::Now().UTCExplode(&now);", version_ui)
        self.assertIn("u\"Copyright \"", version_ui)
        self.assertIn("html_source->AddString(version_ui::kVariationsSource, std::string());", version_ui)
        self.assertIn("html_source->AddString(version_ui::kVariationsSeed, std::string());", version_ui)
        self.assertIn("#elif !BUILDFLAG(IS_WASM)", version_ui)

    def test_wasm_version_modifier_explicitly_discloses_security_boundary(self) -> None:
        version_ui = source("chrome/browser/ui/webui/version/version_ui.cc")
        version_template = source("components/webui/version/resources/about_version.html")

        self.assertIn("#if BUILDFLAG(IS_WASM)", version_ui)
        self.assertIn(
            'return "wasm-single-process (lacks Site Isolation and the Chromium sandbox; "',
            version_ui,
        )
        self.assertIn('"not security-equivalent to desktop Chrome)";', version_ui)
        # The real VersionUI template renders this backend value in the visible
        # product-version row rather than retaining it as an internal label.
        self.assertIn("$i18n{version_modifier}", version_template)

    def test_theme_source_serves_only_version_logo_resources(self) -> None:
        theme_source = source("chrome/browser/wasm/wasm_version_theme_source.cc")
        for required in (
            'constexpr char kWasmThemeHost[] = "theme";',
            'path == "current-channel-logo"',
            "IDR_PRODUCT_LOGO_32",
            'path == "IDR_PRODUCT_LOGO"',
            "IDR_PRODUCT_LOGO;",
            'path == "IDR_PRODUCT_LOGO_WHITE"',
            "IDR_PRODUCT_LOGO_WHITE;",
            "webui::ParsePathAndImageSpec",
            "std::move(callback).Run(nullptr);",
        ):
            with self.subTest(required=required):
                self.assertIn(required, theme_source)

        for forbidden in (
            "ThemeService",
            "NTPResourceCache",
            "BrowserThemePack",
            "CurrentChannelLogoResourceId",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, theme_source)

    def test_version_route_stays_narrow_alongside_settings_bootstrap(self) -> None:
        browser_client = source("chrome/browser/wasm/wasm_content_browser_client.cc")
        controls = source("chrome/browser/wasm/wasm_top_controls_view.cc")

        for required in (
            'constexpr char kWasmVersionHost[] = "version";',
            'constexpr char kWasmSettingsHost[] = "settings";',
            'constexpr char kWasmThemeHost[] = "theme";',
            'constexpr char kWasmResourcesHost[] = "resources";',
            "url.SchemeIs(content::kChromeUIScheme)",
        ):
            with self.subTest(required=required):
                self.assertIn(required, browser_client)

        self.assertIn('constexpr char kWasmVersionURL[] = "chrome://version/";', controls)
        for forbidden in (
            "SchemeIs(content::kChromeUIScheme)",
            "ThemeService",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, controls)

    def test_smoke_types_version_url_and_observes_real_webui_controller(self) -> None:
        smoke = source("chrome/browser/wasm/wasm_browser_smoke.cc")
        for required in (
            'constexpr char kVersionWebUIUrl[] = "chrome://version/";',
            "SubmitAddressAndWait(&navigation_observer, browser_widget, address_field,",
            "content::WebUI* const web_ui = raw_first_contents->GetWebUI();",
            "content::WebUIConfig* const web_ui_config = web_ui->GetWebUIConfig();",
            "CHECK_EQ(web_ui_config->scheme(), content::kChromeUIScheme);",
            'CHECK_EQ(web_ui_config->host(), "version");',
            "static_cast<VersionUI*>(web_ui->GetController());",
            "CHECK_EQ(version_ui->web_ui(), web_ui);",
            '"CHROMIUM_WASM_M6_VERSION_WEBUI:PASS"',
        ):
            with self.subTest(required=required):
                self.assertIn(required, smoke)


if __name__ == "__main__":
    unittest.main()
