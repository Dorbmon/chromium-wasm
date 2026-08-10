#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Source contracts for the isolated M7 WasmFS/OPFS feasibility binary."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M7WasmfsOpfsSmokeContractTest(unittest.TestCase):
    def test_target_keeps_wasmfs_out_of_chrome(self) -> None:
        root_build = source("BUILD.gn")
        wasm_tools_build = source("tools/wasm/BUILD.gn")
        chrome_build = source("chrome/BUILD.gn")

        self.assertIn('config("m7_wasmfs_opfs_smoke_link")', wasm_tools_build)
        self.assertIn('ldflags = [ "-sWASMFS=1" ]', wasm_tools_build)
        self.assertIn('executable("m7_wasmfs_opfs_smoke")', wasm_tools_build)
        self.assertIn(
            'sources = [ "m7_wasmfs_opfs_smoke.cc" ]', wasm_tools_build
        )
        self.assertIn(
            '"//tools/wasm:m7_wasmfs_opfs_smoke($default_toolchain)",',
            root_build,
        )
        self.assertNotIn("m7_wasmfs_opfs_smoke", chrome_build)

    def test_source_has_a_strict_two_phase_opfs_contract(self) -> None:
        smoke = source("tools/wasm/m7_wasmfs_opfs_smoke.cc")

        for token in (
            'constexpr char kWritePhase[] = "write";',
            'constexpr char kVerifyPhase[] = "verify";',
            'constexpr char kPhasePrefix[] = "--m7-opfs-phase=";',
            'constexpr char kRunPrefix[] = "--m7-opfs-run=";',
            "bool IsValidRunId(std::string_view run_id)",
            "return std::isalnum(value) || value == '-' || value == '_';",
            "wasmfs_create_opfs_backend()",
            "wasmfs_create_directory(mount_point, 0700, backend)",
            'MountOpfs("/opfs")',
        ):
            with self.subTest(token=token):
                self.assertIn(token, smoke)

        self.assertIn("#if !BUILDFLAG(IS_WASM)", smoke)
        self.assertIn("#if BUILDFLAG(IS_POSIX)", smoke)
        self.assertIn("application_main_on_browser_thread", smoke)
        self.assertIn("pthread_support_unavailable", smoke)

    def test_smoke_exercises_durable_file_and_tree_primitives(self) -> None:
        smoke = source("tools/wasm/m7_wasmfs_opfs_smoke.cc")

        for token in (
            "O_CREAT | O_EXCL | O_RDWR",
            "read(descriptor, actual.data(), actual.size())",
            "pwrite(descriptor, bytes, length, offset)",
            "pread(descriptor, actual.data(), actual.size(), offset)",
            "ftruncate(descriptor, 9)",
            "ftruncate(descriptor, 16)",
            "fdatasync(descriptor)",
            "rename(paths.temporary_commit.c_str(), paths.commit.c_str())",
            "unlink(paths.deleted.c_str())",
            "opendir(path.c_str())",
            "readdir(directory)",
            "VerifyExactFile(paths.data, expected_data",
            "RemoveDirectory(paths.root, \"cleanup_root\")",
        ):
            with self.subTest(token=token):
                self.assertIn(token, smoke)

    def test_rename_replace_persists_only_completed_overwrites(self) -> None:
        smoke = source("tools/wasm/m7_wasmfs_opfs_smoke.cc")
        write = re.search(
            r"void RunWritePhase\(const FixturePaths& paths\) "
            r"\{(?P<body>.*?)\n\}",
            smoke,
            re.DOTALL,
        )
        verify = re.search(
            r"void RunVerifyPhase\(const FixturePaths& paths\) "
            r"\{(?P<body>.*?)\n\}",
            smoke,
            re.DOTALL,
        )
        self.assertIsNotNone(write)
        self.assertIsNotNone(verify)
        write_body = write.group("body")
        verify_body = verify.group("body")

        generation_a = "WriteDurableNewFile(paths.commit, kCommitGenerationAData"
        generation_a_verify = "VerifyExactFile(paths.commit, kCommitGenerationAData"
        generation_b = (
            "WriteDurableNewFile(paths.temporary_commit, kCommitGenerationBData"
        )
        rename = "rename(paths.temporary_commit.c_str(), paths.commit.c_str())"
        generation_b_verify = "VerifyExactFile(paths.commit, kCommitGenerationBData"
        for token in (
            "kCommitGenerationAData",
            "kCommitGenerationBData",
            generation_a,
            generation_a_verify,
            generation_b,
            rename,
            generation_b_verify,
            "rename_replace=ok atomic_recovery=not_claimed",
        ):
            with self.subTest(token=token):
                self.assertIn(token, smoke)

        self.assertLess(write_body.index(generation_a), write_body.index(generation_a_verify))
        self.assertLess(
            write_body.index(generation_a_verify), write_body.index(generation_b)
        )
        self.assertLess(write_body.index(generation_b), write_body.index(rename))
        self.assertLess(write_body.index(rename), write_body.index(generation_b_verify))
        self.assertIn(generation_b_verify, verify_body)
        self.assertLess(
            verify_body.index(generation_b_verify),
            verify_body.index("Require(IsMissing(paths.temporary_commit)"),
        )
        self.assertEqual(
            smoke.count("rename_replace=ok atomic_recovery=not_claimed"), 2
        )
        self.assertIn("does not claim atomic\n  // crash recovery semantics", smoke)

    def test_same_instance_open_is_explicitly_not_a_lock_claim(self) -> None:
        smoke = source("tools/wasm/m7_wasmfs_opfs_smoke.cc")

        self.assertIn("TestSameInstanceWriteOpenCoalescing", smoke)
        self.assertIn("same_instance_write_open_not_coalesced", smoke)
        self.assertIn("same_instance_open=coalesced", smoke)
        self.assertIn("lock_proof=not_claimed", smoke)
        self.assertIn("not a\n  // lock-acquisition test", smoke)
        self.assertNotIn("F_SETLK", smoke)
        self.assertNotIn("F_SETLKW", smoke)

    def test_success_uses_live_runtime_not_browser_main_thread_teardown(self) -> None:
        smoke = source("tools/wasm/m7_wasmfs_opfs_smoke.cc")

        self.assertIn("#include <emscripten/emscripten.h>", smoke)
        self.assertIn("emscripten_exit_with_live_runtime();", smoke)
        self.assertIn("outer document replacement dispose the live runtime", smoke)
        self.assertIn("not orderly WasmFS\n  // shutdown or crash recovery", smoke)
        main = re.search(r"int main\(int argc, char\* argv\[\]\) \{(?P<body>.*)", smoke, re.DOTALL)
        self.assertIsNotNone(main)
        body = main.group("body")
        self.assertLess(body.index(":PASS phase=%s"), body.index("emscripten_exit_with_live_runtime();"))

    def test_verify_started_precedes_any_persistence_read(self) -> None:
        smoke = source("tools/wasm/m7_wasmfs_opfs_smoke.cc")
        verify = re.search(
            r"void RunVerifyPhase\(const FixturePaths& paths\) "
            r"\{(?P<body>.*?)\n\}",
            smoke,
            re.DOTALL,
        )
        self.assertIsNotNone(verify)
        body = verify.group("body")
        self.assertLess(
            body.index(":VERIFY_STARTED"),
            body.index("VerifyExactFile(paths.data"),
        )


if __name__ == "__main__":
    unittest.main()
