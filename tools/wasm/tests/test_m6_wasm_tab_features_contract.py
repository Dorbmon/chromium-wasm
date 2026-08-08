#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the bounded, object-only Wasm TabFeatures slice."""

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


class M6WasmTabFeaturesContractTest(unittest.TestCase):
    def test_wasm_tab_features_header_is_reduced_and_desktop_is_preserved(
        self,
    ) -> None:
        header = source("chrome/browser/ui/tabs/public/tab_features.h")
        wasm_match = re.search(
            r"#if BUILDFLAG\(IS_WASM\)\n"
            r"(?P<body>.*?)"
            r"#else\nclass ContextHighlightTabFeature;",
            header,
            re.DOTALL,
        )
        self.assertIsNotNone(wasm_match)
        wasm_header = wasm_match.group("body")

        for expected in (
            "class TabInterface;",
            "class TabFeatures {",
            "void Init(TabInterface& tab, Profile* profile);",
            "bool initialized_ = false;",
            "std::unique_ptr<TabUIHelper> tab_ui_helper_;",
            "compile-time failure instead of a null or",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, wasm_header)

        for unsupported in (
            "data_protection_controller",
            "permission_indicators_tab_data",
            "tab_dialog_manager",
            "page_action_controller",
            "saved_tab_group_web_contents_listener",
            "SetTabUIHelperForTesting",
            "GetUserDataFactoryForTesting",
            "base::WeakPtrFactory",
        ):
            with self.subTest(unsupported=unsupported):
                self.assertNotIn(unsupported, wasm_header)

        # The original desktop catalog remains in the non-Wasm branch.
        desktop_header = header[wasm_match.end() :]
        self.assertIn("data_protection_controller()", desktop_header)
        self.assertIn("GetUserDataFactoryForTesting()", desktop_header)
        self.assertIn("base::WeakPtrFactory<TabFeatures>", desktop_header)

    def test_live_helper_uses_real_tab_and_webcontents_observers(self) -> None:
        features = source("chrome/browser/wasm/wasm_tab_features.cc")
        helper = source("chrome/browser/wasm/wasm_tab_ui_helper.cc")
        observing_header = source(
            "chrome/browser/ui/tabs/contents_observing_tab_feature.h"
        )
        helper_header = source("chrome/browser/ui/tab_ui_helper.h")

        self.assertNotIn(
            '#include "chrome/browser/ui/tabs/public/tab_features.h"',
            observing_header,
        )
        self.assertIn('#include "build/build_config.h"', helper_header)

        self.assertIn('#include "chrome/browser/ui/tab_ui_helper.h"', features)
        self.assertIn("#if !BUILDFLAG(IS_WASM)", features)
        self.assertIn("CHECK(!initialized_);", features)
        self.assertIn("tab_ui_helper_ = std::make_unique<TabUIHelper>(tab);", features)
        self.assertIn("static_cast<void>(profile);", features)
        self.assertNotIn("g_disable_tab_feature_initialization", features)

        for expected in (
            "ContentsObservingTabFeature(tab_interface)",
            "scoped_unowned_user_data_(tab_interface.GetUnownedUserDataHost(), *this)",
            "RegisterPinnedStateChanged",
            "web_contents()->GetTitle()",
            "GetLastCommittedEntry()",
            "entry->GetFavicon().image",
            "contents->GetVisibleURL()",
            "tabs::TabNetworkStateForWebContents(web_contents())",
            "tab_ui_change_callbacks_.Notify();",
            "CHECK_EQ(&tab(), tab_interface);",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, helper)

        for forbidden in (
            "BrowserWindowInterface",
            "TabStripModel",
            "SavedTabGroup",
            "WebApp",
            "SecurityInterstitial",
            "memory_saver",
            '"chrome/browser/sessions/session_restore.h"',
            "g_disable_tab_feature_initialization",
            "return nullptr",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, helper)

        # Unsupported desktop-only helpers deliberately lack definitions. A
        # future consumer therefore hits a link boundary rather than receiving
        # an inert controller or a fake-success result.
        for method in (
            "ShouldThemifyFavicon",
            "ShouldDisplayFavicon",
            "IsMonochromeFavicon",
            "ShouldDisplayURL",
            "ShouldShowDiscardStatus",
            "GetDiscardedMemorySavings",
        ):
            with self.subTest(method=method):
                self.assertNotRegex(
                    helper,
                    rf"TabUIHelper::{method}\s*\(",
                )
                self.assertIn(f"- {method}()", helper)

    def test_target_is_narrow_and_unwired(self) -> None:
        wasm_build = source("chrome/browser/wasm/BUILD.gn")
        target = _source_set_body(wasm_build, "wasm_tab_features")

        for entry in (
            '"wasm_tab_features.cc",',
            '"wasm_tab_ui_helper.cc",',
            '"../ui/tabs/contents_observing_tab_feature.cc",',
            '":wasm_tabs_features",',
            '"//components/tabs:public",',
            '"//content/public/browser",',
            '"//ui/base/unowned_user_data",',
        ):
            with self.subTest(entry=entry):
                self.assertIn(entry, target)

        for forbidden in (
            '"//chrome/browser/ui:ui",',
            '"//chrome/browser/ui/tabs:impl",',
            '"//chrome/browser/ui/tabs:tab_strip",',
            '"//chrome/browser/ui/browser_window",',
            '"//chrome/browser/sessions",',
            '"//components/security_interstitials/content",',
            ":wasm_browser_window_features",
            ":wasm_browser_main_parts",
            ":wasm_browser_command_controller",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, target)

        # The joined tab core is the sole direct owner of this feature
        # lifetime. Browser main parts reaches it only through the opt-in
        # process-local smoke, not through a browser-window lifecycle.
        self.assertEqual(1, wasm_build.count('":wasm_tab_features",'))
        self.assertIn(
            '":wasm_tab_features",',
            _source_set_body(wasm_build, "wasm_tab_core"),
        )
        self.assertNotIn(":wasm_tab_features", source("chrome/BUILD.gn"))


if __name__ == "__main__":
    unittest.main()
