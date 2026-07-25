#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from pathlib import Path
import unittest


ROOT_DIR = Path(__file__).resolve().parents[3]


class M3PolicySourceContractTest(unittest.TestCase):
    def test_wasm_generates_the_desktop_linux_policy_schema(self) -> None:
        source = (
            ROOT_DIR / "components/policy/tools/generate_policy_source.gni"
        ).read_text(encoding="utf-8")

        self.assertIn("policy_target_platform = target_os", source)
        self.assertIn(
            'if (target_os == "emscripten") {\n'
            '    # The Wasm port runs Chromium\'s desktop policy implementation',
            source,
        )
        self.assertIn('policy_target_platform = "linux"', source)
        self.assertIn(
            '"--target-platform=" + policy_target_platform',
            source,
        )
        self.assertNotIn('"--target-platform=" + target_os', source)


if __name__ == "__main__":
    unittest.main()
