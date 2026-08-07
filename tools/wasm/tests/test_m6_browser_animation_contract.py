#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Source contracts for the M6 Wasm BrowserAnimationController slice."""

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


class M6BrowserAnimationContractTest(unittest.TestCase):
    def test_controller_is_source_selected_without_desktop_ui_aggregate(
        self,
    ) -> None:
        target = _source_set_body(
            source("chrome/browser/wasm/BUILD.gn"), "wasm_browser_animation"
        )

        for filename in (
            "browser_animation_controller.cc",
            "browser_animation_provider.cc",
            "browser_animation_provider_internal.cc",
            "browser_animation_controller.h",
            "browser_animation_provider.h",
            "browser_animation_provider_internal.h",
            "browser_animation_types.h",
        ):
            with self.subTest(filename=filename):
                self.assertIn(f'"../ui/animation/{filename}"', target)

        for dependency in (
            '"//base",',
            '"//chrome/browser/ui/browser_window",',
            '"//ui/base/identifier",',
            '"//ui/base/unowned_user_data",',
            '"//ui/gfx/animation",',
            '"//ui/views",',
        ):
            with self.subTest(dependency=dependency):
                self.assertIn(dependency, target)

        for forbidden in (
            "//chrome/browser/ui:ui",
            "//chrome/browser/ui/animation:animation",
            "//chrome/browser/ui/browser.h",
            "//chrome/browser/history",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, target)

    def test_slice_remains_unwired_until_the_real_browser_lifecycle(self) -> None:
        chrome_build = source("chrome/BUILD.gn")
        main_parts_target = _source_set_body(
            source("chrome/browser/wasm/BUILD.gn"), "wasm_browser_main_parts"
        )

        self.assertNotIn(":wasm_browser_animation", chrome_build)
        self.assertNotIn(":wasm_browser_animation", main_parts_target)


if __name__ == "__main__":
    unittest.main()
