#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Source contracts for the isolated M7 OPFS normal-shutdown binary."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M7WasmfsOpfsShutdownSmokeContractTest(unittest.TestCase):
    def test_target_keeps_wasmfs_out_of_chrome_and_other_m7_targets(self) -> None:
        root_build = source("BUILD.gn")
        wasm_tools_build = source("tools/wasm/BUILD.gn")
        chrome_build = source("chrome/BUILD.gn")

        self.assertIn('config("m7_wasmfs_opfs_shutdown_smoke_link")', wasm_tools_build)
        self.assertIn('ldflags = [ "-sWASMFS=1" ]', wasm_tools_build)
        self.assertIn(
            'executable("m7_wasmfs_opfs_shutdown_smoke")', wasm_tools_build
        )
        self.assertIn(
            'sources = [ "m7_wasmfs_opfs_shutdown_smoke.cc" ]', wasm_tools_build
        )
        self.assertIn(
            '"//tools/wasm:m7_wasmfs_opfs_shutdown_smoke($default_toolchain)",',
            root_build,
        )
        self.assertNotIn("m7_wasmfs_opfs_shutdown_smoke", chrome_build)

    def test_source_mounts_a_fresh_namespace_and_returns_normally(self) -> None:
        smoke = source("tools/wasm/m7_wasmfs_opfs_shutdown_smoke.cc")

        for token in (
            '#if !BUILDFLAG(IS_WASM)',
            '#if BUILDFLAG(IS_POSIX)',
            'constexpr char kRunPrefix[] = "--m7-opfs-run=";',
            "bool IsValidRunId(std::string_view run_id)",
            'paths.root = "/opfs/" + run_id;',
            'paths.file = paths.root + "/shutdown.bin";',
            "wasmfs_create_opfs_backend()",
            'wasmfs_create_directory("/opfs", 0700, backend)',
            "emscripten_is_main_browser_thread()",
            "emscripten_has_threading_support()",
            "std::atexit(RecordAtexitAfterNativeCompletion)",
            "RunNormalShutdownWork(MakePaths(run_id));",
            "return 0;",
        ):
            with self.subTest(token=token):
                self.assertIn(token, smoke)

        self.assertNotIn("emscripten_exit_with_live_runtime", smoke)
        self.assertNotIn("emscripten_force_exit", smoke)
        self.assertNotIn("_Exit(", smoke)
        self.assertNotIn("quick_exit", smoke)

    def test_native_work_closes_and_removes_before_the_completion_marker(self) -> None:
        smoke = source("tools/wasm/m7_wasmfs_opfs_shutdown_smoke.cc")
        work = re.search(
            r"void RunNormalShutdownWork\(const Paths& paths\) \{(?P<body>.*?)\n\}",
            smoke,
            re.DOTALL,
        )
        self.assertIsNotNone(work)
        body = work.group("body")
        for token in (
            "mkdir(paths.root.c_str(), 0700)",
            "O_CREAT | O_EXCL | O_RDWR",
            "RequireExactWrite",
            "fdatasync(descriptor)",
            "RequireExactRead",
            "close(descriptor)",
            "unlink(paths.file.c_str())",
            "rmdir(paths.root.c_str())",
        ):
            with self.subTest(token=token):
                self.assertIn(token, body)
        self.assertLess(body.index("fdatasync(descriptor)"), body.index("close(descriptor)"))
        self.assertLess(body.index("close(descriptor)"), body.index("unlink(paths.file"))
        self.assertLess(body.index("unlink(paths.file"), body.index("rmdir(paths.root"))

        marker = smoke.rindex('std::fprintf(stdout, "%s\\n", kCompletionMarker);')
        cleanup = smoke.index("RunNormalShutdownWork(MakePaths(run_id));")
        normal_return = smoke.rindex("return 0;")
        self.assertLess(cleanup, marker)
        self.assertLess(marker, normal_return)

    def test_atexit_marker_is_guarded_by_the_flushed_native_completion_marker(
        self,
    ) -> None:
        smoke = source("tools/wasm/m7_wasmfs_opfs_shutdown_smoke.cc")

        for token in (
            'constexpr char kAtexitMarker[] =',
            '"CHROMIUM_WASM_M7_OPFS_ATEXIT:after-native-complete"',
            "bool g_native_completion_flushed = false;",
            "void RecordAtexitAfterNativeCompletion()",
            "if (!g_native_completion_flushed)",
            '"%s:FAIL reason=atexit_before_native_complete\\n"',
            'std::fprintf(stdout, "%s\\n", kAtexitMarker);',
            "std::fflush(stdout)",
            "std::atexit(RecordAtexitAfterNativeCompletion)",
            'Require(completion_written > 0, "completion_marker_write");',
            'Require(std::fflush(stdout) == 0, "completion_marker_flush");',
            "g_native_completion_flushed = true;",
        ):
            with self.subTest(token=token):
                self.assertIn(token, smoke)

        callback = re.search(
            r"void RecordAtexitAfterNativeCompletion\(\) \{(?P<body>.*?)\n\}\n\n"
            r"bool HasPrefix",
            smoke,
            re.DOTALL,
        )
        self.assertIsNotNone(callback)
        callback_body = callback.group("body")
        guard = callback_body.index("if (!g_native_completion_flushed)")
        atexit_marker = callback_body.index(
            'std::fprintf(stdout, "%s\\n", kAtexitMarker);'
        )
        callback_flush = callback_body.index("std::fflush(stdout)")
        self.assertLess(guard, atexit_marker)
        self.assertLess(atexit_marker, callback_flush)

        register = smoke.index("std::atexit(RecordAtexitAfterNativeCompletion)")
        cleanup = smoke.index("RunNormalShutdownWork(MakePaths(run_id));")
        completion = smoke.rindex(
            'std::fprintf(stdout, "%s\\n", kCompletionMarker);'
        )
        completion_flush = smoke.rindex(
            'Require(std::fflush(stdout) == 0, "completion_marker_flush");'
        )
        flushed = smoke.rindex("g_native_completion_flushed = true;")
        normal_return = smoke.rindex("return 0;")
        self.assertLess(register, cleanup)
        self.assertLess(cleanup, completion)
        self.assertLess(completion, completion_flush)
        self.assertLess(completion_flush, flushed)
        self.assertLess(flushed, normal_return)


if __name__ == "__main__":
    unittest.main()
