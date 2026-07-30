#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M3GpuInfoCollectorSourceContractTest(unittest.TestCase):
    def test_wasm_reports_unavailable_native_gpu_information(self) -> None:
        build = source("gpu/config/BUILD.gn")
        implementation = source("gpu/config/gpu_info_collector_wasm.cc")
        common = source("gpu/config/gpu_info_collector.cc")

        self.assertIn(
            'if (is_wasm) {\n'
            '    sources += [ "gpu_info_collector_wasm.cc" ]',
            build,
        )
        self.assertIn(
            'if (is_linux || is_chromeos) {\n'
            '    sources += [ "gpu_info_collector_linux.cc" ]',
            build,
        )
        self.assertIn(
            "bool CollectBasicGraphicsInfo(GPUInfo* gpu_info)",
            implementation,
        )
        self.assertIn(
            "bool CollectContextGraphicsInfo(GPUInfo* gpu_info)",
            implementation,
        )
        self.assertEqual(implementation.count("return false;"), 2)
        self.assertNotIn("gpu_info->", implementation)
        self.assertNotIn("FillGPUInfoFromSystemInfo", implementation)
        self.assertNotIn("CollectGraphicsInfoGL", implementation)
        self.assertIn(
            "if (implementation == gl::kGLImplementationDisabled) {",
            common,
        )
        self.assertIn('gpu_info->gl_vendor = "Disabled";', common)


if __name__ == "__main__":
    unittest.main()
