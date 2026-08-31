#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the isolated M7 Chromium SQLite lock receipt."""

from __future__ import annotations

import argparse
import hashlib
import importlib
from pathlib import Path
import sys
import unittest

from tools.wasm.tests.m3_source_contract_test_support import ROOT_DIR, source


RUNNER_DIR = ROOT_DIR / "tools/wasm"
RUNNER_MODULE = "run_m7_chrome_profile_database_sqlite_lock_dom_smoke"


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


class M7ProfileDatabaseSqliteLockContractTest(unittest.TestCase):
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
        cls.host = source(
            "tools/wasm/host/chrome_wasm_profile_database_sqlite_lock_smoke.js"
        )
        cls.html = source(
            "tools/wasm/host/chrome_wasm_profile_database_sqlite_lock_smoke.html"
        )
        cls.runner_source = source(
            "tools/wasm/run_m7_chrome_profile_database_sqlite_lock_dom_smoke.py"
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

    def test_gn_selects_only_the_distinct_sqlite_lock_artifact(self) -> None:
        flag = "enable_chromium_wasm_m7_profile_database_sqlite_lock_test"
        self.assertIn(f"{flag} = false", self.gni)
        self.assertIn(
            "M7 SQLite lock probe requires the M7 database smoke configuration",
            self.gni,
        )
        self.assertIn(
            "M7 database diagnostics require separate fresh output configurations",
            self.gni,
        )
        self.assertIn('"wasm-chrome-m7-profile-database-sqlite-lock"', self.gni)
        self.assertIn(
            '"out/wasm-chrome-m7-profile-database-sqlite-lock"', self.gni
        )
        self.assertIn(
            'output_name = "chrome_wasm_m7_profile_database_sqlite_lock_test"',
            self.chrome_build,
        )
        self.assertIn(
            '"CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_LOCK_TEST=1"',
            self.wasm_build,
        )
        self.assertIn(
            "uses two real sql::Database connections", self.wasm_build
        )

    def test_source_requires_sqlite_busy_then_release_reopen(self) -> None:
        source_text = self.database_source
        self.assertIn("kSQLiteLockContentionMode", source_text)
        self.assertIn(
            "CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_LOCK_TEST", source_text
        )
        lock = _body_after_signature(
            source_text,
            "bool WriteSqliteTokensWithContenderAndReopen(",
        )
        for requirement in (
            "WriteSqliteTokenAndVerifyAfterClose(database_path, token_a)",
            "holder.Open(database_path) && contender.Open(database_path)",
            "HasSqliteLockContentionSettings(&holder)",
            "HasSqliteLockContentionSettings(&contender)",
            'holder.Execute("BEGIN IMMEDIATE")',
            "WriteSqliteTokenOnOpenDatabase(&holder, token_a)",
            "WriteSqliteTokenOnOpenDatabase(&contender, token_b)",
            "contender_errors.size() == 1",
            "sql::ToPrimaryErrorCode",
            "sql::SqliteErrorCode::kBusy",
            "contender.Close();",
            'holder.Execute("COMMIT")',
            'holder.Execute("ROLLBACK")',
            "ReadSqliteTokenAndVerifyAfterClose(database_path, token_a)",
            "WriteSqliteTokenAndVerifyAfterClose(database_path, token_b)",
        ):
            self.assertIn(requirement, lock)
        self.assertNotIn("SqliteErrorCode::kLocked", lock)
        self.assertLess(
            lock.index("holder.Open(database_path) && contender.Open(database_path)"),
            lock.index('holder.Execute("BEGIN IMMEDIATE")'),
        )
        self.assertLess(lock.index("contender.Close();"), lock.index('holder.Execute("COMMIT")'))
        self.assertLess(lock.index('holder.Execute("COMMIT")'), lock.index("holder.Close();"))

        settings = _body_after_signature(
            source_text, "bool HasSqliteLockContentionSettings("
        )
        for requirement in (
            'database->Execute("PRAGMA busy_timeout=0")',
            '"PRAGMA locking_mode", "normal"',
            '"PRAGMA journal_mode", "truncate"',
            '"PRAGMA mmap_size", 0',
        ):
            self.assertIn(requirement, settings)

        task = _body_after_signature(
            source_text, "DatabaseTaskResult RunDatabaseTask(DatabaseTaskInput input)"
        )
        self.assertIn("case SmokeMode::kSQLiteLockContention:", task)
        lock_case = task[
            task.index("case SmokeMode::kSQLiteLockContention:") : task.index(
                "case SmokeMode::kWriteA:"
            )
        ]
        self.assertIn("WriteSqliteTokensWithContenderAndReopen", lock_case)
        self.assertNotIn("EmitDatabaseTaskPhase", lock_case)

        start = _body_after_signature(source_text, "bool EnableFromCommandLine()")
        self.assertIn("if (mode != kSQLiteLockContentionMode)", start)
        self.assertIn("if (!has_token_a || !has_token_b)", start)
        self.assertIn("mode_ = SmokeMode::kSQLiteLockContention", start)
        self.assertIn("expected_digest_ = token_b_digest_", start)

    def test_marker_grammar_and_scope_do_not_overclaim(self) -> None:
        header = self.database_header
        normalized_header = header.replace("\n// ", " ")
        self.assertIn("sqlite-lock-contention", header)
        ordered_markers = (
            "READY",
            "SQLITE_LOCK_HOLDER_WRITE_A_ACCEPTED",
            "SQLITE_LOCK_CONTENDER_BUSY",
            "SQLITE_LOCK_RELEASE_REOPEN_A_INTEGRITY_OK",
            "SQLITE_LOCK_POST_RELEASE_WRITE_READ_B_INTEGRITY_OK",
            "DATABASES_CLOSED",
            "FENCE_OK",
            "LEASE_RELEASED",
        )
        lock_scope = header[
            header.index("// The SQLite lock artifact") : header.index(
                "// The write-interruption artifact"
            )
        ]
        positions = [lock_scope.index(marker) for marker in ordered_markers]
        self.assertEqual(positions, sorted(positions))
        for limitation in (
            "direct V4",
            "fcntl range-lock contention",
            "separate V4 mounts/profiles/documents/processes",
            "WAL or mmap",
            "external OPFS writer",
            "directory durability",
            "power-loss recovery",
            "normal-profile persistence",
            "M7 completion",
        ):
            self.assertIn(limitation, normalized_header)

    def test_runner_accepts_only_a_sqlite_lock_output_configuration(self) -> None:
        runner = self.runner
        valid = b"\n".join(
            (
                b"enable_chromium_wasm_m7_profile_database_test=true",
                b"enable_chromium_wasm_m7_profile_database_sqlite_lock_test=true",
                b"enable_chromium_wasm_m7_profile_database_lock_test=false",
                b"enable_chromium_wasm_m7_profile_database_abort_pc_diagnostic=false",
                b"enable_chromium_wasm_m7_profile_database_write_interruption_diagnostic=false",
                b"enable_chromium_wasm_m7_profile_database_recovery_test=false",
                b"enable_chromium_wasm_m7_profile_database_outstanding_io_refusal_test=false",
            )
        )
        runner.validate_m7_output_configuration(valid)
        for old, new in (
            (
                b"enable_chromium_wasm_m7_profile_database_sqlite_lock_test=true",
                b"enable_chromium_wasm_m7_profile_database_sqlite_lock_test=false",
            ),
            (
                b"enable_chromium_wasm_m7_profile_database_lock_test=false",
                b"enable_chromium_wasm_m7_profile_database_lock_test=true",
            ),
            (
                b"enable_chromium_wasm_m7_profile_database_recovery_test=false",
                b"enable_chromium_wasm_m7_profile_database_recovery_test=true",
            ),
            (
                b"enable_chromium_wasm_m7_profile_database_outstanding_io_refusal_test=false",
                b"enable_chromium_wasm_m7_profile_database_outstanding_io_refusal_test=true",
            ),
        ):
            with self.subTest(replacement=new):
                with self.assertRaises(runner.M0Error):
                    runner.validate_m7_output_configuration(valid.replace(old, new))
        # Every selector must be a single literal assignment. In particular,
        # a later expression must not bypass the matching literal check.
        for old, new in (
            (
                b"enable_chromium_wasm_m7_profile_database_sqlite_lock_test=true",
                b"enable_chromium_wasm_m7_profile_database_sqlite_lock_test=!true",
            ),
            (
                b"enable_chromium_wasm_m7_profile_database_lock_test=false",
                b"enable_chromium_wasm_m7_profile_database_lock_test=!false",
            ),
            (
                b"enable_chromium_wasm_m7_profile_database_test=true",
                b"enable_chromium_wasm_m7_profile_database_test=true || false",
            ),
        ):
            with self.subTest(nonliteral=new):
                with self.assertRaises(runner.M0Error):
                    runner.validate_m7_output_configuration(valid.replace(old, new))
        with self.assertRaises(runner.M0Error):
            runner.validate_m7_output_configuration(
                valid
                + b"\n"
                + b"enable_chromium_wasm_m7_profile_database_test=true"
            )

        token_a = "a" * 64
        token_b = "b" * 64
        escrow = runner.TokenEscrow(
            token_a=token_a,
            token_a_digest=hashlib.sha256(token_a.encode("ascii")).hexdigest(),
            token_b=token_b,
            token_b_digest=hashlib.sha256(token_b.encode("ascii")).hexdigest(),
        )
        self.assertEqual(
            [
                f"{runner.M7_DATABASE_MARKER_PREFIX}READY",
                f"{runner.M7_DATABASE_MARKER_PREFIX}"
                f"SQLITE_LOCK_HOLDER_WRITE_A_ACCEPTED sha256={escrow.token_a_digest}",
                f"{runner.M7_DATABASE_MARKER_PREFIX}SQLITE_LOCK_CONTENDER_BUSY",
                f"{runner.M7_DATABASE_MARKER_PREFIX}"
                f"SQLITE_LOCK_RELEASE_REOPEN_A_INTEGRITY_OK sha256={escrow.token_a_digest}",
                f"{runner.M7_DATABASE_MARKER_PREFIX}"
                f"SQLITE_LOCK_POST_RELEASE_WRITE_READ_B_INTEGRITY_OK "
                f"sha256={escrow.token_b_digest}",
                f"{runner.M7_DATABASE_MARKER_PREFIX}"
                f"DATABASES_CLOSED sha256={escrow.token_b_digest}",
                f"{runner.M7_DATABASE_MARKER_PREFIX}"
                f"FENCE_OK sha256={escrow.token_b_digest}",
                f"{runner.M7_DATABASE_MARKER_PREFIX}LEASE_RELEASED",
            ],
            runner.expected_markers(escrow),
        )
        summary = runner.sqlite_lock_summary()
        for field in (
            "sameProcessSqliteLockContentionReleaseProven",
            "sqliteHolderContenderReleaseReopenProven",
            "sqliteNonWalRollbackJournalProven",
            "sqliteMmapDisabledProven",
        ):
            self.assertTrue(summary[field], field)
        self.assertFalse(summary["m7GateComplete"])
        for field in (
            "sameProcessLevelDbLockContentionReleaseProven",
            "concurrentProfileContenderProven",
            "externalOpfsWriterProven",
            "directV4FcntlContentionProven",
            "crossProcessLockingProven",
            "crossProfileMountLockingProven",
            "walOrSharedMmapProven",
            "normalProfilePersistenceProven",
            "profilePersistenceProven",
            "directoryDurabilityProven",
            "physicalCrashBehaviorProven",
            "fullChromiumProfileProven",
        ):
            self.assertFalse(summary[field], field)

    def test_bootstrap_is_one_use_and_result_follows_bootstrap(self) -> None:
        runner = self.runner
        token_a = "a" * 64
        token_b = "b" * 64
        escrow = runner.TokenEscrow(
            token_a=token_a,
            token_a_digest=hashlib.sha256(token_a.encode("ascii")).hexdigest(),
            token_b=token_b,
            token_b_digest=hashlib.sha256(token_b.encode("ascii")).hexdigest(),
        )
        result_token = "r" * 24
        session = "s" * 24
        lock_session = runner.LockSession(result_token, session, escrow)
        payload = lock_session.bootstrap_payload(session)
        self.assertEqual(payload["tokenA"], token_a)
        self.assertEqual(payload["tokenADigest"], escrow.token_a_digest)
        self.assertEqual(payload["tokenB"], token_b)
        self.assertEqual(payload["tokenBDigest"], escrow.token_b_digest)
        with self.assertRaises(runner.ProtocolStateError):
            lock_session.bootstrap_payload(session)
        self.assertTrue(lock_session.accept_result(result_token))
        with self.assertRaises(runner.ProtocolStateError):
            lock_session.accept_result(result_token)

    def test_host_and_runner_keep_raw_tokens_off_the_launch_url_and_result(self) -> None:
        self.assertIn(
            'const PRODUCT_MODULE_NAME = "chrome_wasm_m7_profile_database_sqlite_lock_test";',
            self.host,
        )
        self.assertIn("./bootstrap/${this.#context.session}", self.host)
        self.assertIn("SQLITE_LOCK_CONTENDER_BUSY", self.host)
        self.assertIn("SQLITE_LOCK_RELEASE_REOPEN_A_INTEGRITY_OK", self.host)
        self.assertIn("SQLITE_LOCK_POST_RELEASE_WRITE_READ_B_INTEGRITY_OK", self.host)
        self.assertIn("tokenB", self.host)
        self.assertIn("const M7_PHASE_PREFIX", self.host)
        self.assertIn("rawTokensExcluded: true", self.host)
        self.assertIn("m7GateComplete: false", self.host)
        self.assertIn("hostOpfsAccessAttempted: false", self.host)
        self.assertIn("#runtimeModule = null;", self.host)
        self.assertIn("#factoryModule = null;", self.host)
        self.assertIn(
            "this.#factoryModule !== null && this.#factoryModule !== module",
            self.host,
        )
        self.assertIn(
            "this.#runtimeModule !== null && this.#runtimeModule !== module",
            self.host,
        )
        self.assertIn("this.#runtimeModule === this.#factoryModule", self.host)
        # Bootstrap, immutable artifacts, and the capability-bearing result
        # upload must fail before following a redirect.
        self.assertEqual(self.host.count('redirect: "error"'), 3)
        self.assertNotIn("navigator.storage", self.host)
        self.assertNotIn("navigator.locks", self.host)
        self.assertNotIn("WebAssembly.Memory", self.host)
        self.assertIn("lock-test opt-in", self.runner_source)
        self.assertIn("tokens exclusively in in-memory escrow", self.runner_source)
        self.assertIn("_contains_prohibited_strings", self.runner_source)
        self.assertIn(
            "CHROMIUM_WASM_M7_CHROME_PROFILE_DATABASE_SQLITE_LOCK_DOM",
            self.runner_source,
        )
        url_start = self.runner_source.index("def smoke_url(")
        url_end = self.runner_source.index("\ndef _require_exact_fields", url_start)
        url = self.runner_source[url_start:url_end]
        self.assertNotIn("token_a", url)
        self.assertNotIn("token_b", url)
        self.assertIn("resultToken", url)
        self.assertIn("session", url)
        self.assertIn("chrome_wasm_profile_database_sqlite_lock_smoke.js", self.html)

    def test_cli_has_the_cold_module_timeout_cap(self) -> None:
        self.assertEqual(
            self.runner.DEFAULT_GN_ARGUMENTS,
            'import("//out/wasm-chrome-m6/args.gn") '
            "enable_chromium_wasm_m7_profile_database_test=true "
            "enable_chromium_wasm_m7_profile_database_sqlite_lock_test=true",
        )
        self.assertEqual(self.runner.MAX_TIMEOUT_MS, 300_000)
        self.assertEqual(self.runner.parse_lock_timeout("300"), 300.0)
        for value in ("0", "nan", "inf", "300.001"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    argparse.ArgumentTypeError, "timeout must be finite"
                ):
                    self.runner.parse_lock_timeout(value)


if __name__ == "__main__":
    unittest.main()
