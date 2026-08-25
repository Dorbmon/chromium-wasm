#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the bounded M7 database recovery artifact."""

from __future__ import annotations

import importlib
from pathlib import Path
import sys
import unittest

from tools.wasm.tests.m3_source_contract_test_support import ROOT_DIR, source


RUNNER_DIR = ROOT_DIR / "tools/wasm"
RUNNER_MODULE = "run_m7_chrome_profile_database_recovery_dom_smoke"


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


class M7ProfileDatabaseRecoveryContractTest(unittest.TestCase):
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
            "tools/wasm/host/chrome_wasm_profile_database_recovery_smoke.js"
        )
        cls.runner_source = source(
            "tools/wasm/run_m7_chrome_profile_database_recovery_dom_smoke.py"
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

    def test_gn_requires_a_separate_recovery_output_and_database_capability(self) -> None:
        flag = "enable_chromium_wasm_m7_profile_database_recovery_test"
        self.assertIn(f"{flag} = false", self.gni)
        self.assertIn(
            "M7 database recovery probe requires the M7 database smoke configuration",
            self.gni,
        )
        self.assertIn(
            "M7 database diagnostics require separate fresh output configurations",
            self.gni,
        )
        self.assertIn('"wasm-chrome-m7-profile-database-recovery"', self.gni)
        self.assertIn(
            '"out/wasm-chrome-m7-profile-database-recovery"', self.gni
        )

        self.assertIn(
            'output_name = "chrome_wasm_m7_profile_database_recovery_test"',
            self.chrome_build,
        )
        self.assertIn(
            "enable_chromium_wasm_m7_profile_database_test", self.chrome_build
        )
        self.assertIn(
            '"CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST=1"',
            self.wasm_build,
        )
        self.assertIn(
            "must not share a binary with the observation-only interruption",
            self.wasm_build,
        )

    def test_recovery_protocol_documents_only_its_bounded_claim(self) -> None:
        self.assertIn("recover-leveldb-write-b", self.database_header)
        for limitation in (
            "physical crash behavior",
            "SQLite interruption recovery",
            "directory durability",
            "cross-store atomicity",
            "full Chromium profile persistence",
            "M7 completion",
        ):
            self.assertIn(limitation, self.database_header)
        for marker in (
            "RECOVERY_LEASE_REACQUIRED",
            "LEVELDB_RECOVERY_A_OK",
            "LEVELDB_RECOVERY_B_OK",
            "SQLITE_RECOVERY_A_INTEGRITY_OK",
            "RECOVERY_DATABASES_CLOSED",
            "RECOVERY_FENCE_OK",
            "RECOVERY_LEASE_RELEASED",
        ):
            self.assertIn(marker, self.database_header)

    def test_recovery_source_uses_real_post_sync_abort_and_strict_reopens(self) -> None:
        source_text = self.database_source
        self.assertIn("CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST", source_text)
        self.assertIn("kRecoverLevelDBWriteBMode", source_text)
        self.assertIn("InterruptLevelDBWriteAfterLogSync", source_text)
        sync = _body_after_signature(
            source_text, "leveldb::Status Sync() override"
        )
        self.assertIn("target_file_->Sync()", sync)
        self.assertLess(
            sync.index("target_file_->Sync()"),
            sync.index("kLevelDBWriteLogSyncReturned"),
        )
        self.assertIn("std::abort();", sync)

        once = _body_after_signature(
            source_text,
            "std::optional<RecoveredLevelDBValue> ReadRecoveredLevelDBValueOnce(",
        )
        self.assertIn("existing_options.create_if_missing = false;", once)
        self.assertIn("existing_options.paranoid_checks = true;", once)
        self.assertIn("read_options.verify_checksums = true;", once)
        self.assertIn("database.reset();", once)

        twice = _body_after_signature(
            source_text,
            "std::optional<RecoveredLevelDBValue> ReadRecoveredLevelDBValueTwice(",
        )
        self.assertEqual(2, twice.count("ReadRecoveredLevelDBValueOnce("))
        self.assertIn("!second || *second != *first", twice)

        task = _body_after_signature(
            source_text, "DatabaseTaskResult RunDatabaseTask(DatabaseTaskInput input)"
        )
        self.assertIn("ReadRecoveredLevelDBValueTwice(", task)
        self.assertIn(
            "ReadSqliteTokenAndVerifyAfterClose(sqlite_path, input.token_a)", task
        )
        self.assertIn("return DatabaseTaskResult::kRecoveryA;", task)
        self.assertIn("return DatabaseTaskResult::kRecoveryB;", task)

        start = _body_after_signature(
            source_text,
            "bool Start(base::FilePath profile_path, base::OnceClosure completion)",
        )
        self.assertIn('EmitMarker("RECOVERY_LEASE_REACQUIRED");', start)

    def test_host_requires_only_stable_a_or_b_and_never_sets_m7_complete(self) -> None:
        self.assertIn(
            'const RECOVERED_LEVELDB_VALUES = Object.freeze(["a", "b"]);',
            self.host,
        )
        self.assertNotIn("open-failed", self.host)
        self.assertNotIn("LEVELDB_POST_SYNC_OBSERVATION", self.host)
        self.assertIn("RECOVERY_LEASE_REACQUIRED_MARKER", self.host)
        self.assertIn("RECOVERY_SQLITE_A_INTEGRITY_MARKER", self.host)
        self.assertIn("recovered.digest !== expectedDigest", self.host)
        self.assertIn("run.markerIndex !== 2", self.host)
        self.assertIn("m7GateComplete: false", self.host)
        self.assertIn('if (this.#bootstrap.ordinal === 3) return "recovered";', self.host)

    def test_runner_accepts_only_the_separate_strict_artifact(self) -> None:
        runner = self.runner
        valid = b"\n".join(
            (
                b"enable_chromium_wasm_m7_profile_database_test=true",
                b"enable_chromium_wasm_m7_profile_database_recovery_test=true",
                b"enable_chromium_wasm_m7_profile_database_abort_pc_diagnostic=false",
                b"enable_chromium_wasm_m7_profile_database_write_interruption_diagnostic=false",
            )
        )
        runner.validate_m7_output_configuration(valid)
        with self.assertRaises(runner.M0Error):
            runner.validate_m7_output_configuration(
                valid.replace(
                    b"enable_chromium_wasm_m7_profile_database_write_interruption_diagnostic=false",
                    b"enable_chromium_wasm_m7_profile_database_write_interruption_diagnostic=true",
                )
            )

        escrow = runner.TokenEscrow(
            token_a="a" * 64,
            token_b="b" * 64,
            token_a_digest="1" * 64,
            token_b_digest="2" * 64,
        )
        self.assertEqual(
            [
                f"{runner.M7_DATABASE_MARKER_PREFIX}READY",
                runner.RECOVERY_LEASE_REACQUIRED_MARKER,
                f"{runner.M7_DATABASE_MARKER_PREFIX}LEVELDB_RECOVERY_A_OK sha256={escrow.token_a_digest}",
                f"{runner.RECOVERY_SQLITE_A_INTEGRITY_MARKER} sha256={escrow.token_a_digest}",
                *runner.RECOVERY_CLEAN_MARKERS,
            ],
            runner.expected_markers(3, escrow, "a"),
        )
        self.assertEqual(
            f"{runner.M7_DATABASE_MARKER_PREFIX}LEVELDB_RECOVERY_B_OK sha256={escrow.token_b_digest}",
            runner.expected_markers(3, escrow, "b")[2],
        )
        with self.assertRaises(runner.M0Error):
            runner.expected_markers(3, escrow, "missing")

        summary = runner._recovery_summary("a")
        self.assertTrue(summary["boundedDatabaseRecoveryAccepted"])
        self.assertFalse(summary["m7GateComplete"])
        for key in (
            "persistenceProven",
            "profilePersistenceProven",
            "durabilityProven",
            "directoryDurabilityProven",
            "physicalCrashBehaviorProven",
            "sqliteInterruptionRecoveryProven",
            "crossStoreAtomicityProven",
            "fullChromiumProfileProven",
        ):
            self.assertFalse(summary[key], key)

    def test_runner_and_host_have_the_same_recovery_scope(self) -> None:
        self.assertIn(
            "bounded-leveldb-post-sync-recovery", self.runner_source
        )
        self.assertIn("bounded-leveldb-post-sync-recovery", self.host)
        self.assertIn("m7GateComplete\": False", self.runner_source)
        self.assertIn("CHROMIUM_WASM_M7_CHROME_PROFILE_DATABASE_RECOVERY_DOM", self.runner_source)


if __name__ == "__main__":
    unittest.main()
