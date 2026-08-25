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

    def test_source_has_a_strict_multi_phase_opfs_contract(self) -> None:
        smoke = source("tools/wasm/m7_wasmfs_opfs_smoke.cc")

        for token in (
            'constexpr char kWritePhase[] = "write";',
            'constexpr char kVerifyPhase[] = "verify";',
            'constexpr char kRecoveryPrecommitPhase[] = "recovery-precommit";',
            '"recovery-precommit-verify";',
            'constexpr char kRecoveryPostcommitPhase[] = "recovery-postcommit";',
            '"recovery-postcommit-verify";',
            'constexpr char kPhasePrefix[] = "--m7-opfs-phase=";',
            'constexpr char kRunPrefix[] = "--m7-opfs-run=";',
            "bool IsValidRunId(std::string_view run_id)",
            "bool IsKnownPhase(std::string_view phase)",
            "bool IsRecoveryInterruptionPhase(std::string_view phase)",
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

    def test_direct_backend_contract_keeps_supported_and_unsupported_paths_explicit(
        self,
    ) -> None:
        smoke = source("tools/wasm/m7_wasmfs_opfs_smoke.cc")
        contract = re.search(
            r"void TestDirectOpfsBackendContract\(const FixturePaths& paths\) "
            r"\{(?P<body>.*?)\n\}",
            smoke,
            re.DOTALL,
        )
        self.assertIsNotNone(contract)
        body = contract.group("body")

        for token in (
            'PrintPhase("direct_opfs_backend_contract")',
            "RequireDirectoryCreate(contract_root",
            "RequireDirectoryCreate(contract_nested",
            "RequireDirectoryCreate(contract_empty",
            "WriteDurableNewFile(contract_temporary, kCommitGenerationBData",
            "contract_temp_fdatasync",
            "rename(contract_temporary.c_str(), contract_final.c_str()) == 0",
            "RequireDirectoryNames(contract_root, {\"empty\", \"nested\"}",
            "RequireDirectoryNames(contract_nested, {\"record.bin\"}",
            "RequireDirectoryNames(contract_empty, {}",
            "rmdir(contract_empty.c_str()) == 0",
            "O_RDONLY | O_DIRECTORY",
            "fsync(directory) == -1 && errno == ENOTSUP",
            "fdatasync(directory) == -1 && errno == ENOTSUP",
            "rename(contract_empty.c_str(), contract_renamed_empty.c_str()) == -1 &&",
            "errno == EBUSY",
            "chmod(contract_final.c_str(), 0600) == -1 && errno == ENOTSUP",
            "utimensat(AT_FDCWD, contract_final.c_str(), changed_times, 0) == -1 &&",
            "errno == ENOTSUP",
            "DIRECT_BACKEND_CONTRACT",
            "directory_durability=not_claimed",
            "normal_chrome_profile=not_claimed",
            "m7_gate_complete=false",
        ):
            with self.subTest(token=token):
                self.assertIn(token, body)

        self.assertLess(
            body.index("WriteDurableNewFile(contract_temporary"),
            body.index("rename(contract_temporary.c_str(), contract_final.c_str())"),
        )
        self.assertLess(
            body.index("rename(contract_temporary.c_str(), contract_final.c_str())"),
            body.index("fsync(directory) == -1 && errno == ENOTSUP"),
        )
        self.assertLess(
            body.index("fdatasync(directory) == -1 && errno == ENOTSUP"),
            body.index("rmdir(contract_empty.c_str()) == 0"),
        )
        self.assertLess(
            smoke.index("TestDirectOpfsBackendContract(paths);"),
            smoke.index("RequireDirectoryCreate(paths.tree"),
        )

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
        self.assertIn("OPFS/database crash-recovery durability", smoke)
        main = re.search(r"int main\(int argc, char\* argv\[\]\) \{(?P<body>.*)", smoke, re.DOTALL)
        self.assertIsNotNone(main)
        body = main.group("body")
        interruption_exit = body.index("if (IsRecoveryInterruptionPhase")
        pass_marker = body.index(":PASS phase=%s")
        final_exit = body.rindex("emscripten_exit_with_live_runtime();")
        self.assertLess(interruption_exit, pass_marker)
        self.assertLess(pass_marker, final_exit)

    def test_recovery_boundaries_are_outer_document_only(self) -> None:
        smoke = source("tools/wasm/m7_wasmfs_opfs_smoke.cc")
        precommit = re.search(
            r"void RunRecoveryPrecommitPhase\(const FixturePaths& paths\) "
            r"\{(?P<body>.*?)\n\}",
            smoke,
            re.DOTALL,
        )
        precommit_verify = re.search(
            r"void RunRecoveryPrecommitVerifyPhase\(const FixturePaths& paths\) "
            r"\{(?P<body>.*?)\n\}",
            smoke,
            re.DOTALL,
        )
        postcommit = re.search(
            r"void RunRecoveryPostcommitPhase\(const FixturePaths& paths\) "
            r"\{(?P<body>.*?)\n\}",
            smoke,
            re.DOTALL,
        )
        postcommit_verify = re.search(
            r"void RunRecoveryPostcommitVerifyPhase\(const FixturePaths& paths\) "
            r"\{(?P<body>.*?)\n\}",
            smoke,
            re.DOTALL,
        )
        self.assertIsNotNone(precommit)
        self.assertIsNotNone(precommit_verify)
        self.assertIsNotNone(postcommit)
        self.assertIsNotNone(postcommit_verify)

        precommit_body = precommit.group("body")
        precommit_verify_body = precommit_verify.group("body")
        postcommit_body = postcommit.group("body")
        postcommit_verify_body = postcommit_verify.group("body")
        self.assertLess(
            precommit_body.index("CreateRecoveryFixture(paths)"),
            precommit_body.index("PrintRecoveryInterruptionReady"),
        )
        self.assertNotIn(
            "rename(paths.temporary_commit.c_str(), paths.commit.c_str())",
            precommit_body,
        )
        self.assertLess(
            postcommit_body.index(
                "rename(paths.temporary_commit.c_str(), paths.commit.c_str())"
            ),
            postcommit_body.index("PrintRecoveryInterruptionReady"),
        )
        self.assertLess(
            precommit_verify_body.index(
                "VerifyExactFile(paths.commit, kCommitGenerationAData"
            ),
            precommit_verify_body.index("RemoveFile(paths.temporary_commit"),
        )
        self.assertLess(
            precommit_verify_body.index("RemoveFile(paths.temporary_commit"),
            precommit_verify_body.index(
                "VerifyExactFile(paths.commit, kCommitGenerationAData",
                precommit_verify_body.index("RemoveFile(paths.temporary_commit"),
            ),
        )
        self.assertIn("Require(IsMissing(paths.temporary_commit)", postcommit_verify_body)
        self.assertIn(
            "VerifyExactFile(paths.commit, kCommitGenerationBData",
            postcommit_verify_body,
        )
        for token in (
            "not a hook inside OPFS move()",
            "not a SQLite or LevelDB journal",
            "atomic_recovery=not_claimed",
            "database_recovery=not_claimed",
            "cleanup=ok",
            "RECOVERY_INTERRUPTION_READY",
            "RECOVERY_READY",
        ):
            with self.subTest(token=token):
                self.assertIn(token, smoke)

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
