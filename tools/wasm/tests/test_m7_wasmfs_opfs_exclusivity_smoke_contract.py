#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Source contracts for the isolated M7 OPFS writer-exclusivity binary."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M7WasmfsOpfsExclusivitySmokeContractTest(unittest.TestCase):
    def test_target_keeps_wasmfs_out_of_chrome_and_other_m7_target(self) -> None:
        root_build = source("BUILD.gn")
        wasm_tools_build = source("tools/wasm/BUILD.gn")
        chrome_build = source("chrome/BUILD.gn")

        self.assertIn(
            'config("m7_wasmfs_opfs_exclusivity_smoke_link")', wasm_tools_build
        )
        self.assertIn('ldflags = [ "-sWASMFS=1" ]', wasm_tools_build)
        self.assertIn(
            'executable("m7_wasmfs_opfs_exclusivity_smoke")', wasm_tools_build
        )
        self.assertIn(
            'sources = [ "m7_wasmfs_opfs_exclusivity_smoke.cc" ]', wasm_tools_build
        )
        self.assertIn(
            '"//tools/wasm:m7_wasmfs_opfs_exclusivity_smoke($default_toolchain)",',
            root_build,
        )
        self.assertNotIn("m7_wasmfs_opfs_exclusivity_smoke", chrome_build)

    def test_source_has_strict_role_and_thread_contract(self) -> None:
        smoke = source("tools/wasm/m7_wasmfs_opfs_exclusivity_smoke.cc")

        for token in (
            'constexpr char kHolderRole[] = "holder";',
            'constexpr char kContenderRole[] = "contender";',
            'constexpr char kReopenRole[] = "reopen";',
            'constexpr char kRolePrefix[] = "--m7-opfs-role=";',
            'constexpr char kRunPrefix[] = "--m7-opfs-run=";',
            "bool IsValidRunId(std::string_view run_id)",
            "wasmfs_create_opfs_backend()",
            'wasmfs_create_directory("/opfs", 0700, backend)',
            "emscripten_is_main_browser_thread()",
            "emscripten_has_threading_support()",
        ):
            with self.subTest(token=token):
                self.assertIn(token, smoke)

        self.assertIn("#if !BUILDFLAG(IS_WASM)", smoke)
        self.assertIn("#if BUILDFLAG(IS_POSIX)", smoke)
        self.assertIn("application_main_on_browser_thread", smoke)
        self.assertIn("pthread_support_unavailable", smoke)

    def test_holder_retains_writable_fd_and_uses_live_runtime(self) -> None:
        smoke = source("tools/wasm/m7_wasmfs_opfs_exclusivity_smoke.cc")
        holder = re.search(
            r"\[\[noreturn\]\] void RunHolder\(const Paths& paths\) "
            r"\{(?P<body>.*?)\n\}",
            smoke,
            re.DOTALL,
        )
        self.assertIsNotNone(holder)
        body = holder.group("body")
        self.assertIn("O_CREAT | O_EXCL | O_RDWR", body)
        self.assertIn("fdatasync(descriptor)", body)
        self.assertIn("g_holder_fd = descriptor;", body)
        self.assertIn(":HOLDER_READY access_fd_held=1 fdatasync=ok", body)
        self.assertIn("RetainLiveRuntime();", body)
        self.assertNotIn("close(g_holder_fd)", smoke)
        self.assertLess(body.index("fdatasync(descriptor)"), body.index(":HOLDER_READY"))
        self.assertLess(body.index(":HOLDER_READY"), body.index("RetainLiveRuntime();"))
        self.assertIn("emscripten_exit_with_live_runtime();", smoke)
        self.assertIn("outer document is the\n// only teardown boundary", smoke)

    def test_contender_proves_only_writable_open_eacces(self) -> None:
        smoke = source("tools/wasm/m7_wasmfs_opfs_exclusivity_smoke.cc")
        contender = re.search(
            r"\[\[noreturn\]\] void RunContender\(const Paths& paths\) "
            r"\{(?P<body>.*?)\n\}",
            smoke,
            re.DOTALL,
        )
        self.assertIsNotNone(contender)
        body = contender.group("body")
        self.assertIn("kContenderOpenBeginMarker", body)
        self.assertIn("open(paths.writer.c_str(), O_RDWR)", body)
        self.assertIn("descriptor == -1 && open_errno == EACCES", body)
        self.assertIn(":CONTENDER_EACCES errno=eacces", body)
        self.assertIn("RetainLiveRuntime();", body)
        self.assertNotIn("stat(", body)
        self.assertNotIn("pread(", body)
        self.assertLess(
            body.index("kContenderOpenBeginMarker"),
            body.index("open(paths.writer.c_str(), O_RDWR)"),
        )
        self.assertNotIn("errno=13", smoke)
        self.assertNotIn("F_SETLK", smoke)
        self.assertNotIn("F_SETLKW", smoke)

    def test_reopen_is_post_outer_teardown_cleanup_not_recovery_claim(self) -> None:
        smoke = source("tools/wasm/m7_wasmfs_opfs_exclusivity_smoke.cc")
        reopen = re.search(
            r"\[\[noreturn\]\] void RunReopen\(const Paths& paths\) "
            r"\{(?P<body>.*?)\n\}",
            smoke,
            re.DOTALL,
        )
        self.assertIsNotNone(reopen)
        body = reopen.group("body")
        for token in (
            "open(paths.writer.c_str(), O_RDWR)",
            "RequireExactRead",
            "close(descriptor)",
            "unlink(paths.writer.c_str())",
            "rmdir(paths.root.c_str())",
            ":REOPEN_OK cleanup=ok",
            "RetainLiveRuntime();",
        ):
            with self.subTest(token=token):
                self.assertIn(token, body)


if __name__ == "__main__":
    unittest.main()
