#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M3BaseProfilerSourceContractTest(unittest.TestCase):
    def test_wasm_selects_an_empty_core_unwinders_factory(self) -> None:
        build = source("base/BUILD.gn")
        implementation = source(
            "base/profiler/core_unwinders_wasm.cc"
        )
        posix_implementation = source(
            "base/profiler/core_unwinders_posix.cc"
        )

        self.assertIn(
            '"profiler/core_unwinders_wasm.cc",\n'
            '      "profiler/module_cache_wasm.cc",\n'
            '      "profiler/stack_sampler_wasm.cc",',
            build,
        )
        self.assertIn(
            '#if !BUILDFLAG(IS_WASM)\n'
            '#error "core_unwinders_wasm.cc must only be built for '
            'WebAssembly"\n'
            "#endif",
            implementation,
        )
        self.assertIn(
            "StackSamplingProfiler::UnwindersFactory "
            "CreateCoreUnwindersFactory() {\n"
            "  // Browser workers cannot inspect or unwind one another's "
            "native stacks.\n"
            "  return StackSamplingProfiler::UnwindersFactory();\n"
            "}",
            implementation,
        )
        empty_factory = (
            "return StackSamplingProfiler::UnwindersFactory();"
        )
        self.assertIn(empty_factory, posix_implementation)
        self.assertEqual(implementation.count(empty_factory), 1)
        self.assertNotIn("BindOnce", implementation)
        self.assertNotIn("make_unique", implementation)

    def test_wasm_stack_sampling_remains_unsupported(self) -> None:
        profiler = source("base/profiler/stack_sampling_profiler.cc")
        sampler = source("base/profiler/stack_sampler_wasm.cc")
        support_gate = profiler.split(
            "bool StackSamplingProfiler::IsSupportedForCurrentPlatform() {",
            1,
        )[1].split(
            "StackSamplingProfiler::StackSamplingProfiler(",
            1,
        )[0]

        self.assertNotIn("BUILDFLAG(IS_WASM)", support_gate)
        self.assertIn("#else\n  return false;\n#endif", support_gate)
        self.assertIn(
            "// Browser workers cannot suspend one another or expose their "
            "native stacks.\n"
            "  return nullptr;",
            sampler,
        )
        self.assertIn(
            "size_t StackSampler::GetStackBufferSize() {\n"
            "  return 0;\n"
            "}",
            sampler,
        )


if __name__ == "__main__":
    unittest.main()
