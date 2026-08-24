#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Static contracts for the opt-in M7 LevelDB write-interruption diagnostic."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def _body_after_signature(text: str, signature: str) -> str:
    start = text.index(signature)
    opening = text.index("{", start)
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[opening + 1 : index]
    raise AssertionError(f"missing closing brace for {signature}")


class M7ProfileDatabaseWriteInterruptionDiagnosticContractTest(
    unittest.TestCase
):
    def setUp(self) -> None:
        self.header = source("chrome/browser/wasm/wasm_profile_database_smoke.h")
        self.smoke = source("chrome/browser/wasm/wasm_profile_database_smoke.cc")
        self.gni = source("chrome/browser/wasm/wasm_profile_database_smoke.gni")
        self.chrome_build = source("chrome/BUILD.gn")
        self.wasm_build = source("chrome/browser/wasm/BUILD.gn")

    def test_new_mode_has_a_distinct_and_explicitly_nonacceptance_contract(
        self,
    ) -> None:
        for token in (
            "--wasm-profile-database-smoke=interrupt-leveldb-write-b",
            "--wasm-profile-database-smoke=observe-leveldb-write-b",
            "LEVELDB_POST_SYNC_OBSERVATION outcome=a",
            "LEVELDB_POST_SYNC_OBSERVATION outcome=b",
            "LEVELDB_POST_SYNC_OBSERVATION outcome=missing",
            "LEVELDB_POST_SYNC_OBSERVATION outcome=other",
            "LEVELDB_POST_SYNC_OBSERVATION outcome=open-failed",
            "SQLITE_POST_SYNC_REOPEN_INTEGRITY_OK",
            "DIAGNOSTIC_DATABASES_CLOSED",
            "DIAGNOSTIC_FENCE_OK",
            "DIAGNOSTIC_LEASE_RELEASED",
            "does not establish crash recovery",
            "persistence",
            "directory durability",
            "outer-page reload behavior",
            "M7\n// completion",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.header)

        self.assertIn(
            "CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC",
            self.smoke,
        )
        self.assertNotIn("emscripten_exit_with_live_runtime", self.smoke)

    def test_gn_selects_only_a_third_fresh_artifact(self) -> None:
        flag = "enable_chromium_wasm_m7_profile_database_write_interruption_diagnostic"
        for token in (
            f"{flag} = false",
            f"!{flag} ||",
            "enable_chromium_wasm_m7_profile_database_test",
            "wasm-chrome-m7-profile-database-write-interruption",
            "M7 write-interruption diagnostic requires the M7 database smoke configuration",
            "M7 database diagnostics require separate fresh output configurations",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.gni)

        self.assertRegex(
            self.gni,
            re.escape(
                "enable_chromium_wasm_m7_profile_database_abort_pc_diagnostic"
            )
            + r"\s*&&\s*"
            + re.escape(
                "enable_chromium_wasm_m7_profile_database_write_interruption_diagnostic"
            ),
        )
        self.assertIn(
            "chrome_wasm_m7_profile_database_write_interruption_diagnostic",
            self.chrome_build,
        )
        self.assertEqual(self.chrome_build.count(flag), 1)
        self.assertEqual(self.wasm_build.count(flag), 1)

        target = _body_after_signature(self.chrome_build, 'executable("chrome_wasm")')
        branch = _body_after_signature(target, f"else if ({flag})")
        self.assertIn(
            'output_name =\n'
            '            "chrome_wasm_m7_profile_database_write_interruption_diagnostic"',
            branch,
        )
        self.assertNotIn("configs +=", branch)
        self.assertNotIn("inputs +=", branch)
        self.assertEqual(self.chrome_build.count("--emit-symbol-map"), 1)

        smoke_target = _body_after_signature(
            self.wasm_build, 'source_set("wasm_profile_database_smoke")'
        )
        macro_branch_start = smoke_target.index(f"if ({flag})")
        macro_branch = smoke_target[macro_branch_start : macro_branch_start + 600]
        self.assertIn(
            '"CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC=1"',
            macro_branch,
        )
        self.assertIn(
            "enable_chromium_wasm_m7_profile_database_abort_pc_diagnostic",
            smoke_target,
        )

    def test_wrapper_forwards_real_file_operations_then_aborts_once(self) -> None:
        wrapper = _body_after_signature(
            self.smoke, "class DatabaseWriteInterruptionWritableFile final"
        )
        for token in (
            "target_file_->Append(data)",
            "target_file_->Close()",
            "target_file_->Flush()",
            "target_file_->Sync()",
            "status.ok()",
            "TryClaimFirstSuccessfulLogSync(is_log_file_)",
            "DatabaseTaskPhase::kLevelDBWriteLogSyncReturned",
            "std::abort()",
        ):
            with self.subTest(token=token):
                self.assertIn(token, wrapper)
        self.assertLess(wrapper.index("target_file_->Sync()"), wrapper.index("status.ok()"))
        self.assertLess(
            wrapper.index("status.ok()"),
            wrapper.index("DatabaseTaskPhase::kLevelDBWriteLogSyncReturned"),
        )
        self.assertLess(
            wrapper.index("DatabaseTaskPhase::kLevelDBWriteLogSyncReturned"),
            wrapper.index("std::abort()"),
        )
        self.assertNotIn("DisableOwnerPhaseEmission", wrapper)

        env = _body_after_signature(
            self.smoke, "class DatabaseWriteInterruptionEnv final"
        )
        for token in (
            "NewWritableFile",
            "leveldb::EnvWrapper::NewWritableFile(filename, result)",
            "NewAppendableFile",
            "leveldb::EnvWrapper::NewAppendableFile(filename, result)",
            "ForwardAndWrapWritableFile",
        ):
            with self.subTest(token=token):
                self.assertIn(token, env)

        interrupt = _body_after_signature(
            self.smoke, "bool InterruptLevelDBWriteAfterLogSync("
        )
        for token in (
            "DatabaseWriteInterruptionEnv interruption_env",
            "interruption_options.create_if_missing = false",
            "write_options.sync = true",
            "interruption_env.ArmForSyncPut()",
            "database->Put(write_options, kDatabaseKey, token_slice)",
            "interruption_env.DisarmAfterSyncPut()",
            "return false",
        ):
            with self.subTest(token=token):
                self.assertIn(token, interrupt)
        self.assertLess(
            interrupt.index("interruption_env.ArmForSyncPut()"),
            interrupt.index("database->Put(write_options, kDatabaseKey, token_slice)"),
        )
        self.assertIn(
            "interruption_env.ArmForSyncPut();\n"
            "  database->Put(write_options, kDatabaseKey, token_slice);",
            interrupt,
        )
        self.assertLess(
            interrupt.index("database->Put(write_options, kDatabaseKey, token_slice)"),
            interrupt.index("interruption_env.DisarmAfterSyncPut()"),
        )
        self.assertLess(
            interrupt.index("DatabaseWriteInterruptionEnv interruption_env"),
            interrupt.index("std::unique_ptr<leveldb::DB> database"),
        )
        self.assertNotIn("DisableOwnerPhaseEmission", interrupt)
        self.assertNotIn("CompactRange", interrupt)
        self.assertNotIn("database.reset", interrupt)

    def test_interrupt_reports_fresh_a_before_its_only_postread_phase(self) -> None:
        run_task = _body_after_signature(
            self.smoke, "DatabaseTaskResult RunDatabaseTask(DatabaseTaskInput input)"
        )
        start = run_task.index("case SmokeMode::kInterruptLevelDBWriteB:")
        end = run_task.index("case SmokeMode::kObserveLevelDBWriteB:", start)
        branch = run_task[start:end]
        for token in (
            "ReadSqliteToken(sqlite_path, input.token_a)",
            'EmitDatabaseDigestMarker("SQLITE_READ_A_OK"',
            "ReadExistingLevelDBTokenWithoutPhases(",
            'EmitDatabaseDigestMarker("LEVELDB_READ_A_OK"',
            "InterruptLevelDBWriteAfterLogSync(",
        ):
            with self.subTest(token=token):
                self.assertIn(token, branch)
        self.assertLess(
            branch.index("ReadSqliteToken(sqlite_path, input.token_a)"),
            branch.index('EmitDatabaseDigestMarker("SQLITE_READ_A_OK"'),
        )
        self.assertLess(
            branch.index('EmitDatabaseDigestMarker("SQLITE_READ_A_OK"'),
            branch.index("ReadExistingLevelDBTokenWithoutPhases("),
        )
        self.assertLess(
            branch.index("ReadExistingLevelDBTokenWithoutPhases("),
            branch.index('EmitDatabaseDigestMarker("LEVELDB_READ_A_OK"'),
        )
        self.assertLess(
            branch.index('EmitDatabaseDigestMarker("LEVELDB_READ_A_OK"'),
            branch.index("InterruptLevelDBWriteAfterLogSync("),
        )
        self.assertNotIn("EmitDatabaseTaskPhase", branch)

        observation = _body_after_signature(
            self.smoke, "void EmitPostSyncObservation(PostSyncObservation observation)"
        )
        self.assertIn("LEVELDB_POST_SYNC_OBSERVATION outcome=%s", observation)
        self.assertNotIn("ToString", observation)
        self.assertNotIn("AsUTF8Unsafe", observation)
        self.assertNotIn("database_path", observation)

        sqlite_reopen = _body_after_signature(
            self.smoke, "void EmitPostSyncSqliteReopenIntegrity()"
        )
        self.assertIn("SQLITE_POST_SYNC_REOPEN_INTEGRITY_OK", sqlite_reopen)
        self.assertNotIn("AsUTF8Unsafe", sqlite_reopen)
        self.assertNotIn("sqlite_path", sqlite_reopen)

        observe_start = run_task.index("case SmokeMode::kObserveLevelDBWriteB:")
        observe_end = run_task.index("case SmokeMode::kNone:", observe_start)
        observe = run_task[observe_start:observe_end]
        self.assertIn("ObservePostSyncLevelDBWrite(", observe)
        self.assertIn("ReadSqliteTokenAndVerifyAfterClose(", observe)
        self.assertIn("EmitPostSyncSqliteReopenIntegrity();", observe)
        self.assertLess(
            observe.index("ObservePostSyncLevelDBWrite("),
            observe.index("ReadSqliteTokenAndVerifyAfterClose("),
        )
        self.assertLess(
            observe.index("ReadSqliteTokenAndVerifyAfterClose("),
            observe.index("EmitPostSyncSqliteReopenIntegrity();"),
        )

    def test_clean_diagnostic_terminals_replace_ordinary_acceptance_markers(
        self,
    ) -> None:
        fence = _body_after_signature(self.smoke, "void NotifyFenceResult(bool success)")
        self.assertLess(
            fence.index('EmitMarker("DIAGNOSTIC_FENCE_OK")'),
            fence.index('EmitDigestMarker("FENCE_OK", expected_digest_)'),
        )

        drain = _body_after_signature(self.smoke, "void NotifyBackendDrain(bool success)")
        self.assertLess(
            drain.index('EmitMarker("DIAGNOSTIC_LEASE_RELEASED")'),
            drain.index('EmitMarker("LEASE_RELEASED")'),
        )

        complete = _body_after_signature(
            self.smoke, "void OnDatabaseTaskComplete(DatabaseTaskResult result)"
        )
        self.assertLess(
            complete.index('EmitMarker("DIAGNOSTIC_DATABASES_CLOSED")'),
            complete.index('EmitDigestMarker("DATABASES_CLOSED", expected_digest_)'),
        )


if __name__ == "__main__":
    unittest.main()
