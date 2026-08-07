#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the M6 Wasm Aura/Ozone browser-frame platform slice.

This is intentionally only the platform host.  Chrome does not create a
BrowserView yet, so the source-selected target must remain independent of the
monolithic desktop UI aggregate and its toolbar/frame implementation graph.
"""

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


class M6BrowserFrameContractTest(unittest.TestCase):
    def test_platform_host_uses_the_generic_wasm_ozone_host(self) -> None:
        views_build = source("ui/views/BUILD.gn")
        platform_target = _source_set_body(
            source("chrome/browser/wasm/BUILD.gn"),
            "wasm_browser_views_platform",
        )
        host_header = source(
            "chrome/browser/ui/views/frame/browser_desktop_window_tree_host_wasm.h"
        )
        host_source = source(
            "chrome/browser/ui/views/frame/browser_desktop_window_tree_host_wasm.cc"
        )

        self.assertIn(
            "is_linux || is_fuchsia ||\n"
            "          (is_wasm && enable_chromium_wasm_chrome)",
            views_build,
        )
        self.assertIn("desktop_window_tree_host_platform.cc", views_build)
        self.assertIn(
            '"../ui/views/frame/browser_desktop_window_tree_host_wasm.cc"',
            platform_target,
        )
        self.assertIn(
            '"../ui/views/frame/browser_desktop_window_tree_host_wasm.h"',
            platform_target,
        )
        self.assertIn('public_deps = [ "//ui/views" ]', platform_target)
        self.assertIn(
            '"//chrome/browser/wasm:wasm_browser_views_platform"',
            source("chrome/BUILD.gn"),
        )
        self.assertIn("BrowserDesktopWindowTreeHostWasm", host_header)
        self.assertIn("DesktopWindowTreeHostPlatform", host_header)
        self.assertIn("return this;", host_source)
        self.assertIn("return false;", host_source)

        for forbidden in (
            "//chrome/browser/ui:ui",
            "//chrome/browser/ui/browser_window/internal",
            "//chrome/browser/ui/views/toolbar",
            "//chrome/browser/ui/views/location_bar",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, platform_target)


if __name__ == "__main__":
    unittest.main()
