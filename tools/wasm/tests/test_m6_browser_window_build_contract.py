#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Source contract for the M6 browser-window public GN admission."""

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def _braced_block(text: str, marker: str) -> str:
    start = text.find(marker)
    if start == -1:
        raise AssertionError(f"missing block marker: {marker}")
    opening_brace = text.find("{", start + len(marker))
    if opening_brace == -1:
        raise AssertionError(f"missing opening brace after: {marker}")

    depth = 0
    for index in range(opening_brace, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[opening_brace + 1 : index]
    raise AssertionError(f"missing closing brace after: {marker}")


class M6BrowserWindowBuildContractTest(unittest.TestCase):
    def test_test_only_targets_do_not_enter_the_wasm_parse_graph(self) -> None:
        build = source("chrome/browser/ui/browser_window/BUILD.gn")
        non_wasm_targets = _braced_block(build, "if (!is_wasm)")
        outside_non_wasm_targets = build.replace(
            "if (!is_wasm) {" + non_wasm_targets + "}", "", 1
        )

        # Preserve the existing platform selection for every non-Wasm build.
        self.assertIn("if (!is_android) {", non_wasm_targets)
        self.assertIn(
            "if (!is_android || is_desktop_android) {", non_wasm_targets
        )

        for target in (
            'source_set("interactive_ui_tests")',
            'source_set("browser_tests")',
            '"//chrome/test:test_support",',
        ):
            with self.subTest(target=target):
                self.assertIn(target, non_wasm_targets)
                self.assertNotIn(target, outside_non_wasm_targets)


if __name__ == "__main__":
    unittest.main()
