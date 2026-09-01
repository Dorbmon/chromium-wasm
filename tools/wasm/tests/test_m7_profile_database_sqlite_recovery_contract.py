#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for bounded M7 SQLite main-database-sync recovery."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import sys
import unittest

from tools.wasm.tests.m3_source_contract_test_support import ROOT_DIR, source


RUNNER_DIR = ROOT_DIR / "tools/wasm"
RUNNER_MODULE = "run_m7_chrome_profile_database_sqlite_recovery_dom_smoke"


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


class M7ProfileDatabaseSqliteRecoveryContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gni = source("chrome/browser/wasm/wasm_profile_database_smoke.gni")
        cls.chrome_build = source("chrome/BUILD.gn")
        cls.wasm_build = source("chrome/browser/wasm/BUILD.gn")
        cls.database_header = source(
            "chrome/browser/wasm/wasm_profile_database_smoke.h"
        )
        cls.database_source = source(
            "chrome/browser/wasm/wasm_profile_database_smoke.cc"
        )
        cls.vfs_header = source(
            "chrome/browser/wasm/wasm_profile_database_sqlite_recovery_vfs.h"
        )
        cls.vfs_source = source(
            "chrome/browser/wasm/wasm_profile_database_sqlite_recovery_vfs.cc"
        )
        cls.host = source(
            "tools/wasm/host/chrome_wasm_profile_database_sqlite_recovery_smoke.js"
        )
        cls.html = source(
            "tools/wasm/host/chrome_wasm_profile_database_sqlite_recovery_smoke.html"
        )
        cls.runner_source = source(
            "tools/wasm/run_m7_chrome_profile_database_sqlite_recovery_dom_smoke.py"
        )
        sys.path.insert(0, str(RUNNER_DIR))
        cls.runner = importlib.import_module(RUNNER_MODULE)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            sys.path.remove(str(RUNNER_DIR))
        except ValueError:
            pass
        sys.modules.pop(RUNNER_MODULE, None)

    def test_gn_selects_a_distinct_private_vfs_artifact(self) -> None:
        flag = "enable_chromium_wasm_m7_profile_database_sqlite_recovery_test"
        self.assertIn(f"{flag} = false", self.gni)
        self.assertIn(
            "M7 SQLite recovery probe requires the M7 database smoke configuration",
            self.gni,
        )
        self.assertIn(
            "M7 database diagnostics require separate fresh output configurations",
            self.gni,
        )
        self.assertIn(
            "!(enable_chromium_wasm_m7_profile_database_recovery_test &&\n"
            "          enable_chromium_wasm_m7_profile_database_sqlite_recovery_test)",
            self.gni,
        )
        self.assertIn(
            '"out/wasm-chrome-m7-profile-database-sqlite-recovery"', self.gni
        )
        self.assertIn(
            'output_name = "chrome_wasm_m7_profile_database_sqlite_recovery_test"',
            self.chrome_build,
        )
        self.assertIn("deliberately adds no Emscripten fault hook", self.chrome_build)
        self.assertIn(
            '"CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST=1"',
            self.wasm_build,
        )
        self.assertIn(
            'sources += [ "wasm_profile_database_sqlite_recovery_vfs.cc" ]',
            self.wasm_build,
        )
        self.assertIn("deps += [ \"//third_party/sqlite\" ]", self.wasm_build)
        sqlite_vfs_section = self.wasm_build[
            self.wasm_build.index(
                "if (enable_chromium_wasm_m7_profile_database_sqlite_recovery_test)"
            ) :
        ]
        self.assertIn(
            "It never enters normal\n"
            "      # Chrome, the normal M7 database probe, or the LevelDB recovery probe.",
            sqlite_vfs_section,
        )

    def test_private_vfs_forwards_the_real_main_database_sync_before_abort(self) -> None:
        self.assertIn("private, non-default forwarding VFS", self.vfs_header)
        self.assertIn(
            '"WasmProfileDatabaseSqliteCommitInterruptionVfs"', self.vfs_header
        )
        self.assertIn("MainDatabaseSyncCallback", self.vfs_header)
        self.assertIn("ArmForCommit", self.vfs_header)
        self.assertIn("DisarmAfterCommit", self.vfs_header)

        source_text = self.vfs_source
        for requirement in (
            "CHECK_EQ(sqlite3_vfs_find(kName), nullptr);",
            "sqlite3_vfs* default_vfs = sqlite3_vfs_find(nullptr);",
            "CHECK_GT(default_vfs->mxPathname, 0);",
            "vfs_.mxPathname = default_vfs->mxPathname;",
            "sqlite3_vfs_register(&vfs_, /*makeDflt=*/false)",
            "sqlite3_vfs_unregister(&vfs_)",
            "target_vfs_ = sqlite3_vfs_find(nullptr);",
            "(desired_flags & SQLITE_OPEN_MAIN_DB) != 0",
            "TryClaimFirstSuccessfulMainDatabaseSync",
        ):
            self.assertIn(requirement, source_text)

        sync = _body_after_signature(
            source_text,
            "int ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::Sync(",
        )
        forwarded_sync = "wrapped.target_file->pMethods->xSync(wrapped.target_file"
        self.assertIn(forwarded_sync, sync)
        self.assertIn("result == SQLITE_OK", sync)
        self.assertIn("main_database_sync_callback_();", sync)
        self.assertIn("std::abort();", sync)
        self.assertLess(sync.index(forwarded_sync), sync.index("result == SQLITE_OK"))
        self.assertLess(
            sync.index("result == SQLITE_OK"),
            sync.index("main_database_sync_callback_();"),
        )
        self.assertLess(
            sync.index("main_database_sync_callback_();"), sync.index("std::abort();")
        )
        self.assertNotIn("makeDflt=*/true", source_text)

    def test_sqlite_recovery_source_uses_the_selected_vfs_and_double_reopen(self) -> None:
        source_text = self.database_source
        self.assertIn(
            "CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST", source_text
        )
        self.assertIn("kInterruptSqliteWriteBMode", source_text)
        self.assertIn("kRecoverSqliteWriteBMode", source_text)
        self.assertIn("sqlite-write-main-db-sync-returned", source_text)

        settings = _body_after_signature(
            source_text, "bool HasSqliteRollbackJournalRecoverySettings("
        )
        for requirement in (
            'database->Execute("PRAGMA busy_timeout=0")',
            '"PRAGMA locking_mode",\n                                      "normal"',
            '"PRAGMA journal_mode",\n                                      "truncate"',
            '"PRAGMA mmap_size", 0',
        ):
            self.assertIn(requirement, settings)

        interrupt = _body_after_signature(
            source_text, "bool InterruptSqliteWriteAfterMainDbSync("
        )
        for requirement in (
            "ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs interruption_vfs",
            "base::PlatformThread::CurrentId()",
            "options.set_vfs_name_discouraged(interruption_vfs.name());",
            "HasSqliteRollbackJournalRecoverySettings(&database)",
            "statement.Run()",
            'EmitDatabaseDigestMarker("SQLITE_ROLLBACK_JOURNAL_COMMIT_B_ARMED"',
            "interruption_vfs.ArmForCommit();",
            "transaction.Commit();",
            "interruption_vfs.DisarmAfterCommit();",
        ):
            self.assertIn(requirement, interrupt)
        self.assertLess(interrupt.index("statement.Run()"), interrupt.index("ArmForCommit"))
        self.assertLess(
            interrupt.index("ArmForCommit"), interrupt.index("transaction.Commit()")
        )
        self.assertLess(
            interrupt.index("transaction.Commit()"), interrupt.index("DisarmAfterCommit")
        )

        once = _body_after_signature(
            source_text,
            "std::optional<RecoveredSqliteValue> ReadRecoveredSqliteValueOnce(",
        )
        for requirement in (
            "if (!base::PathExists(database_path))",
            "HasHealthySQLiteIntegrity(&database)",
            "database.Close();",
        ):
            self.assertIn(requirement, once)
        twice = _body_after_signature(
            source_text,
            "std::optional<RecoveredSqliteValue> ReadRecoveredSqliteValueTwice(",
        )
        self.assertEqual(2, twice.count("ReadRecoveredSqliteValueOnce("))
        self.assertIn("!second || *second != *first", twice)

        task = _body_after_signature(
            source_text, "DatabaseTaskResult RunDatabaseTask(DatabaseTaskInput input)"
        )
        self.assertIn("case SmokeMode::kInterruptSqliteWriteB:", task)
        self.assertIn("case SmokeMode::kRecoverSqliteWriteB:", task)
        self.assertIn("ReadRecoveredSqliteValueTwice(", task)
        self.assertIn("return DatabaseTaskResult::kRecoveryA;", task)
        self.assertIn("return DatabaseTaskResult::kRecoveryB;", task)

    def test_protocol_documents_only_the_bounded_main_db_sync_claim(self) -> None:
        header = self.database_header
        scope = header[
            header.index("// The separate SQLite recovery artifact") : header.index(
                "// True when any switch"
            )
        ]
        for marker in (
            "RECOVERY_LEASE_REACQUIRED",
            "SQLITE_RECOVERY_SEED_A_FULL_INTEGRITY_OK",
            "SQLITE_RECOVERY_READ_A_OK",
            "SQLITE_ROLLBACK_JOURNAL_COMMIT_B_ARMED",
            "sqlite-write-main-db-sync-returned",
            "SQLITE_RECOVERY_A_FULL_INTEGRITY_OK",
            "SQLITE_RECOVERY_B_FULL_INTEGRITY_OK",
            "RECOVERY_DATABASES_CLOSED",
            "RECOVERY_FENCE_OK",
            "RECOVERY_LEASE_RELEASED",
        ):
            self.assertIn(marker, scope)
        for limitation in (
            "physical crash or power-loss behavior",
            "directory durability",
            "cross-store atomicity",
            "general SQLite interruption recovery",
            "normal-profile persistence",
            "M7 completion",
        ):
            self.assertIn(limitation, scope)
        self.assertIn("private, non-default forwarding VFS", scope)
        self.assertIn("xSync()", scope)
        self.assertIn("before Commit() returns", scope)

    def test_runner_accepts_only_the_sqlite_recovery_artifact(self) -> None:
        runner = self.runner
        valid = b"\n".join(
            (
                b"enable_chromium_wasm_m7_profile_database_test=true",
                b"enable_chromium_wasm_m7_profile_database_sqlite_recovery_test=true",
                b"enable_chromium_wasm_m7_profile_database_abort_pc_diagnostic=false",
                b"enable_chromium_wasm_m7_profile_database_write_interruption_diagnostic=false",
                b"enable_chromium_wasm_m7_profile_database_recovery_test=false",
                b"enable_chromium_wasm_m7_profile_database_lock_test=false",
                b"enable_chromium_wasm_m7_profile_database_sqlite_lock_test=false",
                b"enable_chromium_wasm_m7_profile_database_outstanding_io_refusal_test=false",
            )
        )
        runner.validate_m7_output_configuration(valid)
        for old, new in (
            (
                b"enable_chromium_wasm_m7_profile_database_sqlite_recovery_test=true",
                b"enable_chromium_wasm_m7_profile_database_sqlite_recovery_test=false",
            ),
            (
                b"enable_chromium_wasm_m7_profile_database_recovery_test=false",
                b"enable_chromium_wasm_m7_profile_database_recovery_test=true",
            ),
            (
                b"enable_chromium_wasm_m7_profile_database_sqlite_lock_test=false",
                b"enable_chromium_wasm_m7_profile_database_sqlite_lock_test=true",
            ),
        ):
            with self.subTest(replacement=new):
                with self.assertRaises(runner.M0Error):
                    runner.validate_m7_output_configuration(valid.replace(old, new))

        escrow = runner.TokenEscrow(
            token_a="a" * 64,
            token_b="b" * 64,
            token_a_digest=hashlib.sha256(b"a" * 64).hexdigest(),
            token_b_digest=hashlib.sha256(b"b" * 64).hexdigest(),
        )
        self.assertEqual(
            [
                f"{runner.M7_DATABASE_MARKER_PREFIX}READY",
                runner.RECOVERY_LEASE_REACQUIRED_MARKER,
                f"{runner.M7_DATABASE_MARKER_PREFIX}"
                f"SQLITE_RECOVERY_SEED_A_FULL_INTEGRITY_OK "
                f"sha256={escrow.token_a_digest}",
                *runner.RECOVERY_CLEAN_MARKERS,
            ],
            runner.expected_markers(1, escrow),
        )
        self.assertEqual(
            [
                f"{runner.M7_DATABASE_MARKER_PREFIX}READY",
                runner.RECOVERY_LEASE_REACQUIRED_MARKER,
                f"{runner.M7_DATABASE_MARKER_PREFIX}SQLITE_RECOVERY_READ_A_OK "
                f"sha256={escrow.token_a_digest}",
                f"{runner.M7_DATABASE_MARKER_PREFIX}"
                f"SQLITE_ROLLBACK_JOURNAL_COMMIT_B_ARMED "
                f"sha256={escrow.token_b_digest}",
            ],
            runner.expected_markers(2, escrow),
        )
        self.assertEqual(
            f"{runner.M7_DATABASE_MARKER_PREFIX}SQLITE_RECOVERY_A_"
            f"FULL_INTEGRITY_OK sha256={escrow.token_a_digest}",
            runner.expected_markers(3, escrow, "a")[2],
        )
        self.assertEqual(
            f"{runner.M7_DATABASE_MARKER_PREFIX}SQLITE_RECOVERY_B_"
            f"FULL_INTEGRITY_OK sha256={escrow.token_b_digest}",
            runner.expected_markers(3, escrow, "b")[2],
        )

        summary = runner._recovery_summary("a")
        for field in (
            "boundedSqliteRollbackJournalInterruptionRecoveryProven",
            "sqliteMainDbSyncForwardedBeforeControlledAbortProven",
            "sqliteDoubleReopenFullIntegrityProven",
            "freshOuterDocumentReloadProven",
            "freshModuleLeaseReacquisitionObserved",
        ):
            self.assertTrue(summary[field], field)
        self.assertEqual(summary["stableSqlitePreOrPostValue"], "a")
        self.assertFalse(summary["m7GateComplete"])
        for field in (
            "normalProfilePersistenceProven",
            "profilePersistenceProven",
            "directoryDurabilityProven",
            "physicalCrashBehaviorProven",
            "sqliteInterruptionRecoveryProven",
            "crossStoreAtomicityProven",
            "fullChromiumProfileProven",
        ):
            self.assertFalse(summary[field], field)

    def test_host_and_runner_share_the_strict_three_document_protocol(self) -> None:
        for text in (self.host, self.runner_source):
            self.assertIn("chrome_profile_database_sqlite_recovery_m7", text)
            self.assertIn("bounded-sqlite-rollback-journal-main-db-sync-recovery", text)
            self.assertIn("sqlite-write-main-db-sync-returned", text)
            self.assertIn("m7GateComplete", text)
        for marker in (
            "SQLITE_RECOVERY_SEED_A_FULL_INTEGRITY_OK",
            "SQLITE_RECOVERY_READ_A_OK",
            "SQLITE_ROLLBACK_JOURNAL_COMMIT_B_ARMED",
        ):
            self.assertIn(marker, self.host)
        self.assertIn("function fixedRecoveredSqliteValue(text)", self.host)
        self.assertIn('const suffix = "_FULL_INTEGRITY_OK sha256=";', self.host)
        self.assertIn("RECOVERED_SQLITE_VALUES.includes(value)", self.host)
        self.assertIn("recoveredSqliteValue", self.host)
        self.assertIn("m7GateComplete: false", self.host)
        self.assertIn("rawTokensExcluded: true", self.host)
        self.assertNotIn("navigator.storage", self.host)
        self.assertNotIn("navigator.locks", self.host)
        self.assertNotIn("WebAssembly.Memory", self.host)
        self.assertEqual(self.host.count('redirect: "error"'), 3)
        self.assertIn(
            "chrome_wasm_profile_database_sqlite_recovery_smoke.js", self.html
        )

    def test_cli_has_the_cold_module_timeout_cap(self) -> None:
        self.assertEqual(
            self.runner.DEFAULT_GN_ARGUMENTS,
            'import("//out/wasm-chrome-m6/args.gn") '
            "enable_chromium_wasm_m7_profile_database_test=true "
            "enable_chromium_wasm_m7_profile_database_sqlite_recovery_test=true",
        )
        self.assertEqual(self.runner.MAX_TIMEOUT_MS, 300_000)
        self.assertEqual(self.runner.MAX_DATABASE_MARKER_CHARS, 160)
        self.assertEqual(self.runner.parse_recovery_timeout("300"), 300.0)
        for value in ("0", "nan", "inf", "300.001"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    argparse.ArgumentTypeError, "timeout must be finite"
                ):
                    self.runner.parse_recovery_timeout(value)


if __name__ == "__main__":
    unittest.main()
