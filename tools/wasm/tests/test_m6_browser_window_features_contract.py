#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the first real Wasm BrowserWindowFeatures lifecycle slice."""

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


class M6BrowserWindowFeaturesContractTest(unittest.TestCase):
    def test_pimpl_hides_desktop_storage_and_keeps_unsupported_accessors_unlinked(
        self,
    ) -> None:
        header = source(
            "chrome/browser/ui/browser_window/public/browser_window_features.h"
        )

        self.assertIn('#include "build/build_config.h"', header)
        self.assertIn(
            "void InitPostBrowserViewConstruction(views::View* browser_view);",
            header,
        )
        self.assertIn(
            "void InitPostBrowserViewConstruction(BrowserView* browser_view);",
            header,
        )

        accessors_match = re.search(
            r"#if BUILDFLAG\(IS_WASM\)\n"
            r"  // The Wasm implementation deliberately exposes.*?\n"
            r"(?P<accessors>.*?)\n#else\n"
            r"  BrowserActions\* browser_actions\(\)",
            header,
            re.DOTALL,
        )
        self.assertIsNotNone(accessors_match)
        wasm_accessors = accessors_match.group("accessors")

        # These are precisely the direct-field inline accessors in the desktop
        # declaration.  In a normal Wasm build, the native-only profile
        # accessor is preprocessor-excluded, but it remains declared here so
        # the public source surface stays mechanically complete.
        accessor_counts = {
            "browser_actions": 1,
            "browser_command_controller": 1,
            "mv2_disabled_dialog_controller_for_testing": 1,
            "immersive_mode_controller": 1,
            "cast_browser_controller": 1,
            "extension_installed_watcher": 1,
            "glic_iph_controller": 1,
            "pinned_toolbar_actions": 1,
            "lens_region_search_controller": 1,
            "glic_nudge_controller": 1,
            "tab_strip_model": 1,
            "toast_service": 1,
            "extension_side_panel_manager": 1,
            "extension_keybinding_registry": 1,
            "most_recent_shared_tab_update_store": 1,
            "memory_saver_bubble_controller": 1,
            "shared_tab_group_feedback_controller": 1,
            "synced_window_delegate": 1,
            "tab_menu_model_delegate": 1,
            "tab_group_deletion_dialog_controller": 1,
            "signin_view_controller": 1,
            "tab_strip_service_feature": 1,
            "tab_drag_service_feature": 1,
            "tab_strip_ui_controller": 1,
            "location_bar_model": 2,
            "swap_location_bar_models": 1,
            "tabs_from_other_devices_side_panel_coordinator": 1,
            "new_tab_footer_controller": 1,
            "devtools_ui_controller": 1,
            "split_tab_highlight_controller": 1,
            "contents_border_controller": 1,
            "profile_menu_coordinator": 1,
            "incognito_clear_browsing_data_dialog_coordinator": 1,
            "overscroll_pref_manager": 1,
            "browser_select_file_dialog_controller": 1,
            "profile_customization_bubble_sync_controller": 1,
            "webui_browser_exclusive_access_context": 1,
            "exclusive_access_manager": 1,
            "fullscreen_control_host": 1,
            "history_clusters_side_panel_coordinator": 1,
            "content_setting_bubble_model_delegate": 1,
            "live_tab_context": 1,
            "accelerator_provider": 1,
            "find_bar_owner": 1,
            "searchbox_context_data": 1,
            "omnibox_popup_closer": 1,
            "contextual_cueing_controller": 1,
            "cookie_controls_controller": 1,
        }
        self.assertEqual(49, sum(accessor_counts.values()))
        for accessor, expected_count in accessor_counts.items():
            with self.subTest(accessor=accessor):
                self.assertEqual(
                    expected_count,
                    len(re.findall(rf"\b{accessor}\s*\(", wasm_accessors)),
                )

        # The PImpl branch must be declarations only: returning null here
        # would hide the missing controller and make a broken UI look viable.
        self.assertNotRegex(wasm_accessors, r"\breturn\b")
        self.assertNotIn(".get()", wasm_accessors)

        pimpl_match = re.search(
            r"#if BUILDFLAG\(IS_WASM\)\n"
            r"  class Impl;\n"
            r"  std::unique_ptr<Impl> impl_;\n"
            r"#else",
            header,
        )
        self.assertIsNotNone(pimpl_match)
        self.assertNotIn("desktop_browser_window_capabilities_", pimpl_match.group())

    def test_animation_and_browser_elements_lifecycles_are_real_and_ordered(
        self,
    ) -> None:
        implementation = source(
            "chrome/browser/wasm/wasm_browser_window_features.cc"
        )

        self.assertIn("class BrowserWindowFeatures::Impl", implementation)
        self.assertIn(
            "std::unique_ptr<BrowserAnimationController> "
            "browser_animation_controller_;",
            implementation,
        )
        self.assertRegex(
            implementation,
            r"GetUserDataFactory\(\)\.CreateInstance<"
            r"BrowserAnimationController>\(\*browser,\s*\*browser\)",
        )
        self.assertRegex(
            implementation,
            r"GetUserDataFactory\(\)\.CreateInstance<"
            r"BrowserElementsViewsImpl>\(\*browser,\s*\*browser\)",
        )
        self.assertRegex(
            implementation,
            r"BrowserWindowFeatures::InitPostBrowserViewConstruction\(\s*"
            r"views::View\* browser_view",
        )
        self.assertIn(
            "std::unique_ptr<BrowserElements> browser_elements_;",
            implementation,
        )
        elements_init = implementation.index(
            "browser_elements_->AsA<BrowserElementsViewsImpl>()"
        )
        animation_view_set = implementation.index(
            "browser_animation_controller_->set_browser_view"
        )
        self.assertLess(elements_init, animation_view_set)
        self.assertRegex(
            implementation,
            r"browser_elements_->AsA<BrowserElementsViewsImpl>\(\)[\s\S]*?"
            r"CHECK\(provider\);[\s\S]*?provider->Init\(browser_view\);",
        )
        self.assertIn("provider->Init(browser_view);", implementation)
        self.assertIn(
            "Active-contents WebView retrieval is deliberately not admitted here",
            implementation,
        )
        self.assertNotIn("AddRetrievalCallback", implementation)
        self.assertNotIn("kActiveContentsWebViewRetrievalId", implementation)
        self.assertNotIn("BrowserView::", implementation)
        self.assertIn("browser_animation_controller_->set_browser_view", implementation)

        side_panel = implementation.index("std::make_unique<SidePanelAnimations>()")
        tab_strip = implementation.index("std::make_unique<TabStripAnimations>()")
        initialized = implementation.index("browser_view_initialized_ = true")
        self.assertLess(side_panel, tab_strip)
        self.assertLess(tab_strip, initialized)
        elements_teardown = implementation.index(
            "browser_elements_->AsA<BrowserElementsViews>()"
        )
        elements_reset = implementation.index("browser_elements_.reset();")
        animation_reset = implementation.index(
            "browser_animation_controller_.reset();"
        )
        self.assertLess(elements_teardown, elements_reset)
        self.assertLess(elements_reset, animation_reset)
        self.assertRegex(
            implementation,
            r"browser_elements_->AsA<BrowserElementsViews>\(\)[\s\S]*?"
            r"CHECK\(provider\);[\s\S]*?provider->TearDown\(\);",
        )
        self.assertIn("provider->TearDown();", implementation)
        self.assertIn("browser_animation_controller_.reset();", implementation)
        self.assertIn("CHECK(!impl_);", implementation)
        self.assertIn("CHECK(!browser_view_initialized_);", implementation)
        self.assertIn("base::NoDestructor", implementation)

        # P1 implements only the lifecycle needed to own the real animation
        # UDD and its testing factory.  Everything else remains link-blocked.
        definitions = set(
            re.findall(
                r"BrowserWindowFeatures::([A-Za-z_][A-Za-z0-9_]*)\s*\(",
                implementation,
            )
        )
        self.assertEqual(
            {
                "BrowserWindowFeatures",
                "Init",
                "InitPostBrowserViewConstruction",
                "TearDownPreBrowserWindowDestruction",
                "GetUserDataFactoryForTesting",
                "GetUserDataFactory",
            },
            definitions,
        )
        self.assertIn("BrowserWindowFeatures::~BrowserWindowFeatures()", implementation)
        for forbidden in (
            "InitPostWindowConstruction",
            "Browser::Create",
            "BrowserActions",
            "BrowserCommandController",
            "ThemeService",
            "return nullptr",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, implementation)

    def test_source_selection_is_narrow_and_remains_unwired(self) -> None:
        wasm_build = source("chrome/browser/wasm/BUILD.gn")
        interaction_build = source(
            "chrome/browser/ui/views/interaction/BUILD.gn"
        )
        interaction_header = source(
            "chrome/browser/ui/views/interaction/browser_elements_views.h"
        )
        target = _source_set_body(wasm_build, "wasm_browser_window_features")
        interaction_target = _source_set_body(interaction_build, "interaction")
        features_target = _source_set_body(
            wasm_build, "wasm_browser_animation_features"
        )
        features_source = source(
            "chrome/browser/wasm/wasm_browser_animation_features.cc"
        )

        self.assertIn('"wasm_browser_animation_features.cc"', features_target)
        self.assertIn('"../ui/ui_features.h"', features_target)
        for dependency in (
            '"//base",',
            '"//chrome/common:buildflags",',
            '"//extensions/buildflags",',
        ):
            with self.subTest(features_dependency=dependency):
                self.assertIn(dependency, features_target)
        self.assertIn(
            "BASE_FEATURE(kSidePanelFlyoverAnimation, "
            "base::FEATURE_ENABLED_BY_DEFAULT);",
            features_source,
        )
        self.assertIn(
            "return base::FeatureList::IsEnabled(kSidePanelFlyoverAnimation);",
            features_source,
        )
        self.assertIn("kSidePanelFlyoverDurationMs", features_source)
        self.assertIn('"flyover_animation_duration_ms"', features_source)
        self.assertIn("350", features_source)
        self.assertNotIn("ui_features.cc", features_target)
        self.assertNotIn("//chrome/browser/ui:ui_features", features_target)
        self.assertRegex(
            interaction_build,
            r"if \(!is_wasm\) \{\s*source_set\(\"browser_tests\"\)",
        )
        self.assertIn(
            "namespace views {\nclass WebView;\n}", interaction_header
        )
        self.assertNotIn(
            '#include "ui/views/controls/webview/webview.h"',
            interaction_header,
        )
        self.assertIn(
            "DECLARE_TYPED_IDENTIFIER_VALUE(ui::ElementIdentifier,\n"
            "                               views::WebView,\n"
            "                               kActiveContentsWebViewRetrievalId);",
            interaction_header,
        )
        self.assertNotIn('"//ui/views/controls/webview",', interaction_target)

        for filename in (
            "wasm_browser_window_features.cc",
            "../ui/views/animations/side_panel_animations.cc",
            "../ui/views/animations/side_panel_animations.h",
            "../ui/views/animations/tab_strip_animations.cc",
            "../ui/views/animations/tab_strip_animations.h",
        ):
            with self.subTest(filename=filename):
                self.assertIn(f'"{filename}"', target)

        for dependency in (
            '":wasm_browser_animation",',
            '":wasm_browser_animation_features",',
            '"//base",',
            '"//chrome/browser/ui/browser_window",',
            '"//chrome/browser/ui/views/interaction:impl",',
            '"//ui/base/identifier",',
            '"//ui/base/interaction",',
            '"//ui/base/unowned_user_data",',
            '"//ui/gfx/animation",',
            '"//ui/views",',
        ):
            with self.subTest(dependency=dependency):
                self.assertIn(dependency, target)

        for forbidden in (
            '"//chrome/browser/ui:ui",',
            "//chrome/browser/ui:ui_features",
            "//chrome/browser/ui/animation:animation",
            "//chrome/browser/ui/views/animations:animations",
            '"//chrome/browser/ui/interaction",',
            '"//chrome/browser/ui/views/interaction",',
            '"//chrome/browser/ui:browser_element_identifiers",',
            '"//ui/views/controls/webview",',
            "//chrome/browser/ui/browser_window/internal",
            "//chrome/browser/history",
            "//chrome/common:constants",
            "//chrome/browser/ui/views/toolbar",
            "//chrome/browser/ui/views/location_bar",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, target)

        chrome_build = source("chrome/BUILD.gn")
        main_parts = _source_set_body(wasm_build, "wasm_browser_main_parts")
        self.assertNotIn(":wasm_browser_window_features", chrome_build)
        self.assertNotIn(":wasm_browser_window_features", main_parts)


if __name__ == "__main__":
    unittest.main()
