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

    def test_window_feature_animation_and_browser_elements_lifecycles_are_real_and_ordered(
        self,
    ) -> None:
        implementation = source(
            "chrome/browser/wasm/wasm_browser_window_features.cc"
        )

        self.assertIn("class BrowserWindowFeatures::Impl", implementation)
        self.assertIn('#include "chrome/browser/ui/browser_actions.h"', implementation)
        self.assertIn(
            '#include "chrome/browser/ui/browser_command_controller.h"',
            implementation,
        )
        self.assertRegex(
            implementation,
            r"std::unique_ptr<BrowserActions>\s+browser_actions_;",
        )
        self.assertRegex(
            implementation,
            r"std::unique_ptr<chrome::BrowserCommandController>\s+"
            r"browser_command_controller_;",
        )
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
        self.assertIn(
            "std::make_unique<BrowserWindowFullscreenController>(*browser)",
            implementation,
        )
        self.assertRegex(
            implementation,
            r"GetUserDataFactory\(\)\.CreateInstance<"
            r"WindowFeatureController>\(",
        )
        self.assertIn(
            "CreateInstanceWithFactoryMethod<ImmersiveModeController,",
            implementation,
        )
        self.assertIn("&chrome::CreateImmersiveModeController", implementation)
        self.assertIn(
            "CHECK_EQ(browser->GetType(), BrowserWindowInterface::TYPE_NORMAL);",
            implementation,
        )

        fullscreen_init = implementation.index(
            "std::make_unique<BrowserWindowFullscreenController>(*browser)"
        )
        actions_init = implementation.index(
            "std::make_unique<BrowserActions>(browser)"
        )
        window_feature_init = implementation.index(
            "CreateInstance<WindowFeatureController>"
        )
        immersive_init = implementation.index(
            "CreateInstanceWithFactoryMethod<ImmersiveModeController,"
        )
        command_controller_init = implementation.index(
            "std::make_unique<chrome::BrowserCommandController>(browser)"
        )
        actions_initialized = implementation.index(
            "browser_actions->InitializeBrowserActions();"
        )
        animation_init = implementation.index(
            "CreateInstance<BrowserAnimationController>"
        )
        elements_init_call = implementation.index(
            "CreateInstance<BrowserElementsViewsImpl>"
        )
        self.assertLess(fullscreen_init, actions_init)
        self.assertLess(actions_init, window_feature_init)
        self.assertLess(window_feature_init, immersive_init)
        self.assertLess(immersive_init, command_controller_init)
        self.assertLess(command_controller_init, actions_initialized)
        self.assertLess(actions_initialized, animation_init)
        self.assertLess(immersive_init, animation_init)
        self.assertLess(animation_init, elements_init_call)
        self.assertEqual(
            1,
            implementation.count("browser_actions->InitializeBrowserActions();"),
        )
        self.assertIn("std::move(browser_actions)", implementation)
        self.assertIn("std::move(browser_command_controller)", implementation)
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
        immersive_teardown = implementation.index(
            "immersive_mode_controller_.reset();"
        )
        window_feature_teardown = implementation.index(
            "window_feature_controller_.reset();"
        )
        fullscreen_teardown = implementation.index("fullscreen_controller_.reset();")
        elements_teardown = implementation.index(
            "browser_elements_->AsA<BrowserElementsViews>()"
        )
        elements_reset = implementation.index("browser_elements_.reset();")
        animation_reset = implementation.index(
            "browser_animation_controller_.reset();"
        )
        self.assertLess(immersive_teardown, window_feature_teardown)
        self.assertLess(window_feature_teardown, fullscreen_teardown)
        self.assertLess(fullscreen_teardown, elements_teardown)
        self.assertLess(elements_teardown, elements_reset)
        self.assertLess(elements_reset, animation_reset)
        self.assertNotIn("browser_actions_.reset()", implementation)
        self.assertNotIn("browser_command_controller_.reset()", implementation)
        action_member = implementation.index(
            "std::unique_ptr<BrowserActions> browser_actions_;"
        )
        command_member = implementation.index("browser_command_controller_;")
        self.assertLess(action_member, command_member)
        self.assertIn("through BrowserWidget destruction", implementation)
        self.assertIn("in reverse declaration order.", implementation)
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

        # P3's UDD lifecycle is retained, and the selected action root and
        # navigation command controller now have checked, owning accessors.
        # Everything else remains link-blocked.
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
                "browser_actions",
                "browser_command_controller",
                "immersive_mode_controller",
                "GetUserDataFactoryForTesting",
                "GetUserDataFactory",
            },
            definitions,
        )
        self.assertRegex(
            implementation,
            r"BrowserActions\* BrowserWindowFeatures::browser_actions\(\) \{\s*"
            r"CHECK\(impl_\);\s*"
            r"return impl_->browser_actions\(\);",
        )
        self.assertRegex(
            implementation,
            r"chrome::BrowserCommandController\*\s*"
            r"BrowserWindowFeatures::browser_command_controller\(\) const \{\s*"
            r"CHECK\(impl_\);\s*"
            r"return impl_->browser_command_controller\(\);",
        )
        self.assertRegex(
            implementation,
            r"ImmersiveModeController\* "
            r"BrowserWindowFeatures::immersive_mode_controller\(\) \{\s*"
            r"CHECK\(impl_\);\s*"
            r"return impl_->immersive_mode_controller\(\);",
        )
        self.assertIn("BrowserWindowFeatures::~BrowserWindowFeatures()", implementation)
        for forbidden in (
            "InitPostWindowConstruction",
            "Browser::Create",
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
        controller_target = _source_set_body(
            wasm_build, "wasm_window_feature_controllers"
        )
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
            '":wasm_browser_actions",',
            '":wasm_browser_animation",',
            '":wasm_browser_animation_features",',
            '":wasm_browser_command_controller",',
            '":wasm_window_feature_controllers",',
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
            "//chrome/browser:command_updater_impl",
            "//chrome/browser/ui/tabs:tab_strip",
            "//chrome/browser/ui/browser_actions",
            "//chrome/browser/ui/browser_command_controller",
            "//chrome/browser/history",
            "//chrome/common:constants",
            "//chrome/browser/ui/views/toolbar",
            "//chrome/browser/ui/views/location_bar",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, target)

        for filename in (
            "../ui/fullscreen/browser_window_fullscreen_controller.h",
            "../ui/views/frame/immersive_mode_controller.h",
            "../ui/window_feature_controller/window_feature_controller.h",
            "../ui/fullscreen/browser_window_fullscreen_controller_wasm.cc",
            "../ui/views/frame/immersive_mode_controller.cc",
            "../ui/views/frame/immersive_mode_controller_wasm.cc",
            "../ui/window_feature_controller/window_feature_controller_wasm.cc",
        ):
            with self.subTest(controller_filename=filename):
                self.assertIn(f'"{filename}"', controller_target)

        for dependency in (
            '"//base",',
            '"//chrome/browser/ui/browser_window",',
            '"//ui/base/unowned_user_data",',
            '"//ui/base"',
        ):
            with self.subTest(controller_dependency=dependency):
                self.assertIn(dependency, controller_target)

        for forbidden in (
            "//chrome/browser/ui:ui",
            "//chrome/browser/ui/fullscreen",
            "//chrome/browser/ui/window_feature_controller",
            "//chrome/browser/ui/web_applications",
            "//chrome/browser/history",
            "//chrome/browser/themes",
            "//chrome/browser/ui/browser_actions",
            "//chrome/browser/ui/browser_command_controller",
            "//chrome/browser/ui/browser_window/internal",
            "//chrome/common:constants",
            "//ui/views/controls/webview",
        ):
            with self.subTest(controller_forbidden=forbidden):
                self.assertNotIn(forbidden, controller_target)

        fullscreen_source = source(
            "chrome/browser/ui/fullscreen/"
            "browser_window_fullscreen_controller_wasm.cc"
        )
        window_feature_source = source(
            "chrome/browser/ui/window_feature_controller/"
            "window_feature_controller_wasm.cc"
        )
        immersive_source = source(
            "chrome/browser/ui/views/frame/immersive_mode_controller_wasm.cc"
        )

        override_check = fullscreen_source.index(
            "should_hide_ui_for_fullscreen_for_testing_.has_value()"
        )
        window_check = fullscreen_source.index("window && window->IsFullscreen()")
        self.assertLess(override_check, window_check)
        self.assertIn("base::to_address(browser_)->GetWindow()", fullscreen_source)
        self.assertNotIn("ImmersiveModeController", fullscreen_source)

        self.assertIn(
            "CHECK_EQ(browser_type_, BrowserWindowInterface::TYPE_NORMAL);",
            window_feature_source,
        )
        self.assertIn("CHECK(!app_controller_);", window_feature_source)
        self.assertIn("case WindowFeature::kFeatureBookmarkBar:", window_feature_source)
        self.assertIn(
            "return check_can_support || !IsFullscreen();", window_feature_source
        )
        self.assertNotIn("app_browser_controller.h", window_feature_source)
        self.assertNotIn("web_applications", window_feature_source)

        self.assertIn("class WasmImmersiveModeController", immersive_source)
        self.assertIn("CHECK(!enabled);", immersive_source)
        self.assertIn("return std::make_unique<WasmImmersiveRevealedLock>();", immersive_source)
        self.assertIn("bool IsEnabled() const override { return false; }", immersive_source)
        self.assertIn("bool IsRevealed() const override { return false; }", immersive_source)
        self.assertNotIn("return nullptr", immersive_source)

        chrome_build = source("chrome/BUILD.gn")
        main_parts = _source_set_body(wasm_build, "wasm_browser_main_parts")
        self.assertEqual(1, wasm_build.count('\":wasm_browser_actions\",'))
        self.assertIn(
            ":wasm_browser_command_controller",
            _source_set_body(wasm_build, "wasm_browser_window_features"),
        )
        self.assertIn(
            ":wasm_browser_command_controller",
            _source_set_body(wasm_build, "wasm_browser_window_view_smoke"),
        )
        self.assertEqual(
            2, wasm_build.count('\":wasm_browser_command_controller\",')
        )
        self.assertNotIn(":wasm_window_feature_controllers", chrome_build)
        self.assertNotIn(":wasm_window_feature_controllers", main_parts)
        self.assertNotIn(":wasm_browser_actions", chrome_build)
        self.assertNotIn(":wasm_browser_actions", main_parts)
        self.assertNotIn(":wasm_browser_command_controller", chrome_build)
        self.assertNotIn(
            ":wasm_browser_command_controller", main_parts
        )
        self.assertNotIn(":wasm_browser_window_features", chrome_build)
        self.assertNotIn(":wasm_browser_window_features", main_parts)


if __name__ == "__main__":
    unittest.main()
