#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the source-selected Wasm tab feature definitions."""

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


class M6TabsFeaturesContractTest(unittest.TestCase):
    def test_tab_search_entry_point_defaults_off_only_on_wasm(self) -> None:
        implementation = source("chrome/browser/ui/tabs/features.cc")

        self.assertIn('#include "build/build_config.h"', implementation)
        self.assertNotIn(
            '#include "chrome/browser/ui/ui_features.h"', implementation
        )
        self.assertRegex(
            implementation,
            r"#if BUILDFLAG\(IS_WASM\)\n"
            r"(?:.*\n)*?"
            r"BASE_FEATURE\(kHorizontalTabStripComboButton,\n"
            r"\s+base::FEATURE_DISABLED_BY_DEFAULT\);\n"
            r"#else\n"
            r"BASE_FEATURE\(kHorizontalTabStripComboButton, "
            r"base::FEATURE_ENABLED_BY_DEFAULT\);\n"
            r"#endif",
        )

    def test_native_tab_features_no_longer_depend_on_ui_aggregate(self) -> None:
        target = _source_set_body(
            source("chrome/browser/ui/tabs/BUILD.gn"), "features"
        )

        self.assertIn('"features.cc"', target)
        self.assertIn('"features.h"', target)
        self.assertIn('"//base"', target)
        self.assertNotIn("//chrome/browser/ui:ui_features", target)

    def test_wasm_features_are_source_selected_and_unwired(self) -> None:
        wasm_build = source("chrome/browser/wasm/BUILD.gn")
        target = _source_set_body(wasm_build, "wasm_tabs_features")

        for source_file in (
            '"../ui/tabs/features.h"',
            '"../ui/tabs/features.cc"',
            '"//base"',
        ):
            with self.subTest(source_file=source_file):
                self.assertIn(source_file, target)

        for forbidden in (
            "//chrome/browser/ui/tabs:features",
            "//chrome/browser/ui:ui_features",
            "//chrome/browser/ui:ui",
            "//chrome/browser/ui/actions",
            "//chrome/browser/ui/webui/tab_search",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, target)

        self.assertNotIn("//chrome/browser/ui/tabs:features", wasm_build)
        self.assertNotIn(":wasm_tabs_features", source("chrome/BUILD.gn"))
        self.assertNotIn(
            ":wasm_tabs_features",
            _source_set_body(wasm_build, "wasm_browser_main_parts"),
        )


if __name__ == "__main__":
    unittest.main()
