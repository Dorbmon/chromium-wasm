#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the isolated Wasm BrowserActions root lifecycle."""

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


class M6BrowserActionsContractTest(unittest.TestCase):
    def test_wasm_header_hides_desktop_storage(self) -> None:
        header = source("chrome/browser/ui/browser_actions.h")

        self.assertIn('#include "build/build_config.h"', header)
        self.assertRegex(
            header,
            r"#if BUILDFLAG\(IS_WASM\)\n"
            r"(?:  //.*\n)+"
            r"  actions::ActionItem\* root_action_item\(\) const;\n"
            r"#else\n"
            r"  actions::ActionItem\* root_action_item\(\) const \{ "
            r"return root_action_item_; \}\n"
            r"#endif",
        )
        self.assertRegex(
            header,
            r"#if BUILDFLAG\(IS_WASM\)\n"
            r"  class Impl;\n"
            r"  std::unique_ptr<Impl> impl_;\n"
            r"#else\n"
            r"  raw_ptr<actions::ActionItem> root_action_item_ = nullptr;",
        )

    def test_root_registration_and_removal_are_real_and_bounded(self) -> None:
        implementation = source("chrome/browser/wasm/wasm_browser_actions.cc")

        self.assertIn("#if !BUILDFLAG(IS_WASM)", implementation)
        self.assertIn("class BrowserActions::Impl", implementation)
        self.assertIn("CHECK(browser->GetProfile());", implementation)
        self.assertIn("CHECK(!root_action_item_);", implementation)
        self.assertIn("actions::ActionManager::Get().AddAction(", implementation)
        self.assertRegex(
            implementation,
            r"actions::ActionItem::Builder\(\)\s*"
            r"\.CopyAddressTo\(&root_action_item_\)\s*"
            r"\.Build\(\)",
        )
        self.assertIn(
            "actions::ActionManager::Get().RemoveAction(root_action_item_)",
            implementation,
        )
        self.assertIn("root_action_item_ = nullptr;", implementation)

        definitions = set(
            re.findall(
                r"BrowserActions::(~?BrowserActions|[A-Za-z_][A-Za-z0-9_]*)\s*\(",
                implementation,
            )
        )
        self.assertEqual(
            {
                "BrowserActions",
                "~BrowserActions",
                "InitializeBrowserActions",
                "root_action_item",
            },
            definitions,
        )

        for forbidden in (
            "GetCleanTitleAndTooltipText",
            "InitializeSidePanelActions",
            "InitializePageActionIconActions",
            "InitializeChromeMenuActions",
            "InitializeToolbarAndMiscActions",
            "AddListeners",
            "kAction",
            "SetActionId",
            "AddChild",
            "SetInvokeActionCallback",
            "BindRepeating",
            "BrowserCommandController",
            "browser_commands",
            "BrowserActionPrefsListener",
            "ThemeService",
            "history",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, implementation)

    def test_source_selection_is_narrow_and_unwired(self) -> None:
        wasm_build = source("chrome/browser/wasm/BUILD.gn")
        target = _source_set_body(wasm_build, "wasm_browser_actions")
        window_features = _source_set_body(
            wasm_build, "wasm_browser_window_features"
        )

        self.assertIn('"wasm_browser_actions.cc"', target)
        self.assertIn('"../ui/browser_actions.h"', target)
        for dependency in (
            '"//base"',
            '"//chrome/browser/ui/browser_window",',
            '"//ui/actions",',
        ):
            with self.subTest(dependency=dependency):
                self.assertIn(dependency, target)

        for forbidden in (
            "//chrome/browser/ui:ui",
            "//chrome/browser/ui/browser_window/internal",
            "//chrome/browser:primitives",
            "//chrome/browser/history",
            "//chrome/browser/themes",
            "//extensions",
            "//chrome/browser/ui/actions",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, target)

        self.assertNotIn(":wasm_browser_actions", window_features)
        self.assertNotIn(
            "BrowserWindowFeatures::browser_actions(",
            source("chrome/browser/wasm/wasm_browser_window_features.cc"),
        )
        self.assertNotIn(":wasm_browser_actions", source("chrome/BUILD.gn"))
        self.assertNotIn(
            ":wasm_browser_actions",
            _source_set_body(wasm_build, "wasm_browser_main_parts"),
        )


if __name__ == "__main__":
    unittest.main()
