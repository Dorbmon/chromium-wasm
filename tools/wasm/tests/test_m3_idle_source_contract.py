#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M3IdleSourceContractTest(unittest.TestCase):
    def test_wasm_selects_conservative_idle_platform(self) -> None:
        build = source("ui/base/idle/BUILD.gn")
        implementation = source("ui/base/idle/idle_wasm.cc")
        unit_test = source("ui/base/idle/idle_wasm_unittest.cc")

        self.assertIn(
            'if (is_wasm) {\n    sources += [ "idle_wasm.cc" ]\n  }',
            build,
        )
        self.assertIn(
            'if (is_wasm) {\n'
            '    sources += [ "idle_wasm_unittest.cc" ]\n'
            "  }",
            build,
        )
        self.assertEqual(
            implementation.count("NOTIMPLEMENTED_LOG_ONCE();"), 3
        )
        self.assertIn("return 0;", implementation)
        self.assertIn("return false;", implementation)
        self.assertIn("return {};", implementation)
        self.assertIn("EXPECT_FALSE(subscription);", unit_test)
        self.assertIn(
            "EXPECT_EQ(IDLE_STATE_ACTIVE, "
            "CalculateIdleState(/*idle_threshold=*/1));",
            unit_test,
        )


if __name__ == "__main__":
    unittest.main()
