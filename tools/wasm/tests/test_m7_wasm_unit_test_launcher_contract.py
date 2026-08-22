#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from pathlib import Path
import unittest


ROOT_DIR = Path(__file__).resolve().parents[3]


def source(path: str) -> str:
    return (ROOT_DIR / path).read_text(encoding="utf-8")


class WasmUnitTestLauncherContractTest(unittest.TestCase):
    def test_wasm_source_selects_the_in_process_launcher(self) -> None:
        build = source("base/test/BUILD.gn")
        blink_sources = build.split("  if (use_blink) {", 1)[1].split(
            "  sources += [\n    \"../trace_event", 1
        )[0]

        self.assertIn("if (is_wasm) {", blink_sources)
        self.assertIn(
            'sources += [ "launcher/unit_test_launcher_wasm.cc" ]',
            blink_sources,
        )
        self.assertIn("} else {", blink_sources)
        self.assertIn('"launcher/test_launcher.cc",', blink_sources)
        self.assertIn('"launcher/unit_test_launcher.cc",', blink_sources)

    def test_wasm_launcher_executes_the_supplied_suite_once(self) -> None:
        launcher = source("base/test/launcher/unit_test_launcher_wasm.cc")

        self.assertIn("RunUnitTestsInWasmProcess", launcher)
        self.assertIn("#if !BUILDFLAG(IS_WASM)", launcher)
        self.assertIn("test::AllowCheckIsTestForTesting();", launcher)
        self.assertIn("CommandLine::InitializedForCurrentProcess()", launcher)
        self.assertEqual(launcher.count("std::move(run_test_suite).Run()"), 1)
        self.assertNotIn("TestLauncher", launcher)
        self.assertNotIn("LaunchProcess", launcher)

    def test_wasm_omits_child_process_launcher_interfaces(self) -> None:
        launcher_header = source("base/test/launcher/unit_test_launcher.h")
        test_launcher_header = source("base/test/launcher/test_launcher.h")
        base_build = source("base/BUILD.gn")

        self.assertIn(
            "#if BUILDFLAG(USE_BLINK) && !BUILDFLAG(IS_WASM)",
            launcher_header,
        )
        self.assertIn(
            "#elif BUILDFLAG(IS_POSIX) || BUILDFLAG(IS_FUCHSIA)",
            test_launcher_header,
        )
        self.assertEqual(
            base_build.count(
                'sources -= [ "test/launcher/test_launcher_unittest.cc" ]'
            ),
            1,
        )

    def test_wasm_omits_the_unsupported_trace_processor_test_api(self) -> None:
        build = source("base/test/BUILD.gn")
        base_build = source("base/BUILD.gn")
        trace_processor = source("base/test/tracing/test_trace_processor.h")

        wasm_guard = build.split("if (!is_cronet_build) {", 1)[1].split(
            "  if (is_win) {", 1
        )[0]
        self.assertIn("if (!is_wasm) {", wasm_guard)
        self.assertIn('public_deps += [ ":test_trace_processor" ]', wasm_guard)
        self.assertIn(
            'sources += [ "test/tracing/test_trace_processor_example_unittest.cc" ]',
            base_build,
        )
        self.assertIn("if (!is_wasm) {", base_build)
        self.assertIn(
            "#if !BUILDFLAG(IS_WIN) && !BUILDFLAG(IS_WASM)",
            trace_processor,
        )

    def test_wasm_test_suite_keeps_stack_dumping_at_the_host_boundary(self) -> None:
        test_suite = source("base/test/test_suite.cc")
        stack_trace = source("base/debug/stack_trace_wasm.cc")

        self.assertIn(
            "#if !BUILDFLAG(IS_WASM)\n"
            "  CHECK(debug::EnableInProcessStackDumping());\n"
            "#else\n"
            "  // Wasm traps are reported by the host harness;",
            test_suite,
        )
        self.assertIn("return false;", stack_trace)


if __name__ == "__main__":
    unittest.main()
