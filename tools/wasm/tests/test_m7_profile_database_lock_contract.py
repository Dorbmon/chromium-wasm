#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the isolated M7 Chromium LevelDB lock receipt."""

from __future__ import annotations

import argparse
import hashlib
import importlib
from pathlib import Path
import sys
import unittest

from tools.wasm.tests.m3_source_contract_test_support import ROOT_DIR, source


RUNNER_DIR = ROOT_DIR / "tools/wasm"
RUNNER_MODULE = "run_m7_chrome_profile_database_lock_dom_smoke"


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


class M7ProfileDatabaseLockContractTest(unittest.TestCase):
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
            "tools/wasm/host/chrome_wasm_profile_database_lock_smoke.js"
        )
        cls.html = source(
            "tools/wasm/host/chrome_wasm_profile_database_lock_smoke.html"
        )
        cls.runner_source = source(
            "tools/wasm/run_m7_chrome_profile_database_lock_dom_smoke.py"
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

    def test_gn_selects_only_the_distinct_lock_artifact(self) -> None:
        flag = "enable_chromium_wasm_m7_profile_database_lock_test"
        self.assertIn(f"{flag} = false", self.gni)
        self.assertIn(
            "M7 database lock probe requires the M7 database smoke configuration",
            self.gni,
        )
        self.assertIn(
            "M7 database diagnostics require separate fresh output configurations",
            self.gni,
        )
        self.assertIn('"wasm-chrome-m7-profile-database-lock"', self.gni)
        self.assertIn(
            '"out/wasm-chrome-m7-profile-database-lock"', self.gni
        )
        self.assertIn(
            'output_name = "chrome_wasm_m7_profile_database_lock_test"',
            self.chrome_build,
        )
        self.assertIn(
            '"CHROME_WASM_M7_PROFILE_DATABASE_LOCK_TEST=1"', self.wasm_build
        )
        self.assertIn(
            "must not accept the ordinary database modes", self.wasm_build
        )

    def test_source_requires_holder_rejection_then_release_reopen(self) -> None:
        source_text = self.database_source
        self.assertIn("kLockContentionMode", source_text)
        self.assertIn("CHROME_WASM_M7_PROFILE_DATABASE_LOCK_TEST", source_text)
        lock = _body_after_signature(
            source_text,
            "bool WriteLevelDBTokenWithContenderAndReopen(",
        )
        self.assertIn("write_options.sync = true;", lock)
        self.assertIn("existing_options.create_if_missing = false;", lock)
        self.assertIn("existing_options.paranoid_checks = true;", lock)
        self.assertIn("leveldb_env::MethodID contender_method;", lock)
        self.assertIn(
            "base::File::Error contender_error = base::File::FILE_ERROR_MAX;",
            lock,
        )
        self.assertIn("!contender_status.ok() && !contender", lock)
        self.assertIn("leveldb_env::ParseMethodAndError", lock)
        self.assertIn("leveldb_env::METHOD_AND_BFE", lock)
        self.assertIn("contender_method == leveldb_env::kLockFile", lock)
        self.assertIn(
            "contender_error == base::File::FILE_ERROR_IN_USE", lock
        )
        self.assertLess(lock.index("contender_rejected"), lock.rindex("holder.reset();"))
        self.assertIn("read_options.verify_checksums = true;", lock)
        self.assertIn("std::string_view(value) == token", lock)

        task = _body_after_signature(
            source_text, "DatabaseTaskResult RunDatabaseTask(DatabaseTaskInput input)"
        )
        self.assertIn("case SmokeMode::kLockContention:", task)
        lock_case = task[
            task.index("case SmokeMode::kLockContention:") : task.index(
                "case SmokeMode::kWriteA:"
            )
        ]
        self.assertIn("WriteSqliteTokenAndVerifyAfterClose", lock_case)
        self.assertIn("WriteLevelDBTokenWithContenderAndReopen", lock_case)
        self.assertNotIn("EmitDatabaseTaskPhase", lock_case)
        self.assertIn(
            'EmitMarker("LEVELDB_LOCK_CONTENDER_REJECTED")', source_text
        )
        self.assertIn(
            'EmitDigestMarker("LEVELDB_LOCK_RELEASE_REOPEN_OK", token_a_digest_)',
            source_text,
        )

        start = _body_after_signature(
            source_text,
            "bool EnableFromCommandLine()",
        )
        self.assertIn("if (mode != kLockContentionMode)", start)
        self.assertIn("if (!has_token_a || has_token_b)", start)
        self.assertIn("mode_ = SmokeMode::kLockContention", start)

    def test_marker_grammar_and_scope_do_not_overclaim(self) -> None:
        header = self.database_header
        self.assertIn("lock-contention", header)
        ordered_markers = (
            "READY",
            "SQLITE_WRITE_ACCEPTED",
            "LEVELDB_LOCK_CONTENDER_REJECTED",
            "LEVELDB_LOCK_RELEASE_REOPEN_OK",
            "DATABASES_CLOSED",
            "FENCE_OK",
            "LEASE_RELEASED",
        )
        lock_scope = header[
            header.index("// The lock artifact writes") : header.index(
                "// The write-interruption artifact"
            )
        ]
        positions = [lock_scope.index(marker) for marker in ordered_markers]
        self.assertEqual(positions, sorted(positions))
        for limitation in (
            "direct V4",
            "fcntl range-lock behavior",
            "SQLite locking",
            "concurrent full Chrome profile",
            "external OPFS writer",
            "directory durability",
            "normal-profile persistence",
            "M7 completion",
        ):
            self.assertIn(limitation, header)

    def test_runner_accepts_only_a_lock_specific_output_configuration(self) -> None:
        runner = self.runner
        valid = b"\n".join(
            (
                b"enable_chromium_wasm_m7_profile_database_test=true",
                b"enable_chromium_wasm_m7_profile_database_lock_test=true",
                b"enable_chromium_wasm_m7_profile_database_abort_pc_diagnostic=false",
                b"enable_chromium_wasm_m7_profile_database_write_interruption_diagnostic=false",
                b"enable_chromium_wasm_m7_profile_database_recovery_test=false",
                b"enable_chromium_wasm_m7_profile_database_sqlite_recovery_test=false",
            )
        )
        runner.validate_m7_output_configuration(valid)
        for replacement in (
            b"enable_chromium_wasm_m7_profile_database_lock_test=false",
            b"enable_chromium_wasm_m7_profile_database_recovery_test=true",
            b"enable_chromium_wasm_m7_profile_database_abort_pc_diagnostic=true",
        ):
            with self.subTest(replacement=replacement):
                changed = valid.replace(
                    b"enable_chromium_wasm_m7_profile_database_lock_test=true"
                    if b"lock_test=false" in replacement
                    else (
                        b"enable_chromium_wasm_m7_profile_database_recovery_test=false"
                        if b"recovery_test=true" in replacement
                        else b"enable_chromium_wasm_m7_profile_database_abort_pc_diagnostic=false"
                    ),
                    replacement,
                )
                with self.assertRaises(runner.M0Error):
                    runner.validate_m7_output_configuration(changed)

        with self.assertRaises(runner.M0Error):
            runner.validate_m7_output_configuration(
                valid.replace(
                    b"enable_chromium_wasm_m7_profile_database_sqlite_recovery_test=false",
                    b"enable_chromium_wasm_m7_profile_database_sqlite_recovery_test=true",
                )
            )

        token = "a" * 64
        escrow = runner.TokenEscrow(
            token_a=token,
            token_a_digest=hashlib.sha256(token.encode("ascii")).hexdigest(),
        )
        self.assertEqual(
            [
                f"{runner.M7_DATABASE_MARKER_PREFIX}READY",
                f"{runner.M7_DATABASE_MARKER_PREFIX}SQLITE_WRITE_ACCEPTED sha256={escrow.token_a_digest}",
                f"{runner.M7_DATABASE_MARKER_PREFIX}LEVELDB_LOCK_CONTENDER_REJECTED",
                f"{runner.M7_DATABASE_MARKER_PREFIX}LEVELDB_LOCK_RELEASE_REOPEN_OK sha256={escrow.token_a_digest}",
                f"{runner.M7_DATABASE_MARKER_PREFIX}DATABASES_CLOSED sha256={escrow.token_a_digest}",
                f"{runner.M7_DATABASE_MARKER_PREFIX}FENCE_OK sha256={escrow.token_a_digest}",
                f"{runner.M7_DATABASE_MARKER_PREFIX}LEASE_RELEASED",
            ],
            runner.expected_markers(escrow),
        )
        summary = runner.lock_summary()
        self.assertTrue(summary["sameProcessLevelDbLockContentionReleaseProven"])
        self.assertFalse(summary["m7GateComplete"])
        for field in (
            "sqliteLockingProven",
            "concurrentProfileContenderProven",
            "externalOpfsWriterProven",
            "normalProfilePersistenceProven",
            "profilePersistenceProven",
            "directoryDurabilityProven",
            "physicalCrashBehaviorProven",
            "fullChromiumProfileProven",
        ):
            self.assertFalse(summary[field], field)

    def test_bootstrap_is_one_use_and_result_follows_bootstrap(self) -> None:
        runner = self.runner
        token = "b" * 64
        escrow = runner.TokenEscrow(
            token_a=token,
            token_a_digest=hashlib.sha256(token.encode("ascii")).hexdigest(),
        )
        result_token = "r" * 24
        session = "s" * 24
        lock_session = runner.LockSession(result_token, session, escrow)
        payload = lock_session.bootstrap_payload(session)
        self.assertEqual(payload["tokenA"], token)
        self.assertEqual(payload["tokenADigest"], escrow.token_a_digest)
        with self.assertRaises(runner.ProtocolStateError):
            lock_session.bootstrap_payload(session)
        self.assertTrue(lock_session.accept_result(result_token))
        with self.assertRaises(runner.ProtocolStateError):
            lock_session.accept_result(result_token)

    def test_host_and_runner_keep_raw_tokens_off_the_launch_url_and_result(self) -> None:
        self.assertIn('const PRODUCT_MODULE_NAME = "chrome_wasm_m7_profile_database_lock_test";', self.host)
        self.assertIn("./bootstrap/${this.#context.session}", self.host)
        self.assertIn("LEVELDB_LOCK_CONTENDER_REJECTED", self.host)
        self.assertIn("LEVELDB_LOCK_RELEASE_REOPEN_OK", self.host)
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
        self.assertIn("token exclusively in in-memory escrow", self.runner_source)
        self.assertIn("_contains_prohibited_strings", self.runner_source)
        self.assertIn("CHROMIUM_WASM_M7_CHROME_PROFILE_DATABASE_LOCK_DOM", self.runner_source)
        url_start = self.runner_source.index("def smoke_url(")
        url_end = self.runner_source.index("\ndef _require_exact_fields", url_start)
        url = self.runner_source[url_start:url_end]
        self.assertNotIn("token_a", url)
        self.assertIn("resultToken", url)
        self.assertIn("session", url)
        self.assertIn("chrome_wasm_profile_database_lock_smoke.js", self.html)

    def test_cli_has_the_cold_module_timeout_cap(self) -> None:
        self.assertEqual(
            self.runner.DEFAULT_GN_ARGUMENTS,
            'import("//out/wasm-chrome-m6/args.gn") '
            "enable_chromium_wasm_m7_profile_database_test=true "
            "enable_chromium_wasm_m7_profile_database_lock_test=true",
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
