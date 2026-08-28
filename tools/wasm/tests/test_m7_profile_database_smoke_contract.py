#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Source contracts for the isolated M7 SQLite/LevelDB close smoke."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def _body_after_signature(text: str, signature: str) -> str:
    """Returns one balanced C++ body without depending on source layout."""

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


class M7ProfileDatabaseSmokeContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.header = source("chrome/browser/wasm/wasm_profile_database_smoke.h")
        self.smoke = source("chrome/browser/wasm/wasm_profile_database_smoke.cc")
        self.logging = source("base/logging.cc")
        self.logging_wasm_header = source("base/logging_wasm.h")
        self.icu_build = source("third_party/icu/BUILD.gn")
        self.leveldb_header = source("third_party/leveldatabase/env_chromium.h")
        self.leveldb_source = source("third_party/leveldatabase/env_chromium.cc")

    def test_chromium_wasm_uses_complete_icu_data(self) -> None:
        chromium_wasm_data = """} else if (is_wasm && enable_chromium_wasm_port) {
  # Chromium's Wasm port uses ICU date and locale formatting in its normal
  # browser services. Flutter's filtered bundle omits those resources, so use
  # the complete Chromium data package for this explicitly enabled port.
  data_dir = \"common\"
} else if (current_cpu == \"wasm\") {
  data_dir = \"flutter\"
}"""
        self.assertIn(chromium_wasm_data, self.icu_build)
        chromium_wasm_branch = self.icu_build.index(
            "} else if (is_wasm && enable_chromium_wasm_port)"
        )
        flutter_wasm_branch = self.icu_build.index(
            '} else if (current_cpu == "wasm")', chromium_wasm_branch
        )
        self.assertLess(chromium_wasm_branch, flutter_wasm_branch)

    def test_strict_private_three_module_argument_protocol(self) -> None:
        for token in (
            'constexpr char kSmokeSwitch[] = "wasm-profile-database-smoke";',
            'constexpr char kTokenASwitch[] = "wasm-profile-database-token-a";',
            'constexpr char kTokenBSwitch[] = "wasm-profile-database-token-b";',
            'constexpr char kWriteAMode[] = "write-a";',
            'constexpr char kVerifyAWriteBMode[] = "verify-a-write-b";',
            'constexpr char kVerifyBMode[] = "verify-b";',
            "constexpr size_t kOpaqueTokenLength = 64;",
            "value.size() != kOpaqueTokenLength",
            "character >= '0' && character <= '9'",
            "character >= 'a' && character <= 'f'",
            "token_a_ == token_b_",
            '#include "crypto/hash.h"',
            "crypto::hash::Sha256(token)",
            "base::HexEncodeLower",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.smoke)

        for token in (
            "--wasm-profile-database-smoke=write-a",
            "--wasm-profile-database-smoke=verify-a-write-b",
            "--wasm-profile-database-smoke=verify-b",
            "In verify-a-write-b mode token B must differ from token A.",
            "database status string, or path",
            "capability, storage, profile, database, fence, lifecycle, content, or drain:",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.header)

        enable = _body_after_signature(self.smoke, "bool EnableFromCommandLine()")
        write_a = enable.index("if (mode == kWriteAMode)")
        verify_a_write_b = enable.index("else if (mode == kVerifyAWriteBMode)")
        verify_b = enable.index("else if (mode == kVerifyBMode)")
        self.assertLess(write_a, verify_a_write_b)
        self.assertLess(verify_a_write_b, verify_b)
        self.assertIn("if (!has_token_a || has_token_b)", enable)
        self.assertIn("if (!has_token_a || !has_token_b)", enable)
        self.assertIn("if (has_token_a || !has_token_b)", enable)

    def test_fixed_digest_only_stderr_protocol_and_raw_token_clearing(self) -> None:
        for token in (
            'constexpr char kMarkerPrefix[] = "CHROMIUM_WASM_M7_DATABASE:";',
            'EmitMarker("READY")',
            'EmitDigestMarker("SQLITE_READ_A_OK", token_a_digest_)',
            'EmitDigestMarker("LEVELDB_READ_A_OK", token_a_digest_)',
            'EmitDigestMarker("SQLITE_READ_B_OK", token_b_digest_)',
            'EmitDigestMarker("LEVELDB_READ_B_OK", token_b_digest_)',
            'EmitDigestMarker("SQLITE_WRITE_ACCEPTED", token_a_digest_)',
            'EmitDigestMarker("LEVELDB_WRITE_ACCEPTED", token_a_digest_)',
            'EmitDigestMarker("SQLITE_WRITE_ACCEPTED", token_b_digest_)',
            'EmitDigestMarker("LEVELDB_WRITE_ACCEPTED", token_b_digest_)',
            'EmitDigestMarker("DATABASES_CLOSED", expected_digest_)',
            'EmitDigestMarker("FENCE_OK", expected_digest_)',
            'EmitMarker("LEASE_RELEASED")',
            'std::fprintf(stderr, "%sFAIL stage=%s\\n", kMarkerPrefix,',
            'std::fprintf(stderr, "%s%s sha256=%s\\n", kMarkerPrefix, marker,',
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.smoke)

        self.assertNotIn("std::cout", self.smoke)
        self.assertNotIn("LOG(", self.smoke)
        self.assertNotIn("SHA256HashString", self.smoke)
        self.assertNotIn('#include "crypto/sha2.h"', self.smoke)

        failure = _body_after_signature(
            self.smoke,
            "void ReportFailure(WasmProfileDatabaseSmokeFailureStage stage)",
        )
        self.assertLess(failure.index("ClearRawTokens();"), failure.index("std::fprintf"))
        self.assertIn("token_a.clear();", self.smoke)
        self.assertIn("token_b.clear();", self.smoke)
        self.assertIn("input.ClearRawTokens();", self.smoke)
        self.assertIn("~DatabaseTaskInput() { ClearRawTokens(); }", self.smoke)

        for signature in (
            "void EmitMarker(const char* marker)",
            "void EmitDigestMarker(const char* marker, const std::string& digest)",
            "void ReportFailure(WasmProfileDatabaseSmokeFailureStage stage)",
        ):
            body = _body_after_signature(self.smoke, signature)
            for sensitive in ("token_a", "token_b", "database_path", "value"):
                with self.subTest(signature=signature, sensitive=sensitive):
                    self.assertNotIn(sensitive, body)

    def test_fixed_abort_phase_diagnostics_are_redacted_and_not_success_markers(self) -> None:
        self.assertIn(
            'constexpr char kPhasePrefix[] = "CHROMIUM_WASM_M7_DATABASE_PHASE:";',
            self.smoke,
        )
        phase_names = _body_after_signature(
            self.smoke,
            "const char* DatabaseTaskPhaseName(DatabaseTaskPhase phase)",
        )
        for suffix in (
            "task-post",
            "task-started",
            "sqlite-write",
            "sqlite-read",
            "leveldb-write",
            "leveldb-read",
            "leveldb-write-tracker",
            "leveldb-write-open",
            "leveldb-write-pre-dbimpl-construction",
            "leveldb-write-env-file-exists-first-pre",
            "leveldb-write-env-file-exists-first-post",
            "leveldb-write-env-file-exists-second-pre",
            "leveldb-write-env-file-exists-second-post",
            "leveldb-write-env-file-exists-later-pre",
            "leveldb-write-env-file-exists-later-post",
            "leveldb-write-env-create-dir",
            "leveldb-write-env-rename-file",
            "leveldb-write-env-new-logger",
            "leveldb-write-logger-logv-first-pre",
            "leveldb-write-logger-logv-first-post",
            "leveldb-write-logger-fatal-source-wasm-time",
            "leveldb-write-logger-fatal-source-time-formatting",
            "leveldb-write-logger-fatal-source-leveldb",
            "leveldb-write-logger-fatal-source-base-file",
            "leveldb-write-env-lock-file",
            "leveldb-write-env-new-writable-file",
            "leveldb-write-put",
            "leveldb-write-compact",
            "leveldb-write-close",
            "leveldb-read-open",
            "leveldb-read-get",
            "leveldb-read-close",
            "leveldb-write-log-sync-returned",
            "task-complete",
        ):
            with self.subTest(suffix=suffix):
                self.assertIn(f'return "{suffix}";', phase_names)
        self.assertEqual(
            {
                "task-post",
                "task-started",
                "sqlite-write",
                "sqlite-read",
                "leveldb-write",
                "leveldb-read",
                "leveldb-write-tracker",
                "leveldb-write-open",
                "leveldb-write-pre-dbimpl-construction",
                "leveldb-write-env-file-exists-first-pre",
                "leveldb-write-env-file-exists-first-post",
                "leveldb-write-env-file-exists-second-pre",
                "leveldb-write-env-file-exists-second-post",
                "leveldb-write-env-file-exists-later-pre",
                "leveldb-write-env-file-exists-later-post",
                "leveldb-write-env-create-dir",
                "leveldb-write-env-rename-file",
                "leveldb-write-env-new-logger",
                "leveldb-write-logger-logv-first-pre",
                "leveldb-write-logger-logv-first-post",
                "leveldb-write-logger-fatal-source-wasm-time",
                "leveldb-write-logger-fatal-source-time-formatting",
                "leveldb-write-logger-fatal-source-leveldb",
                "leveldb-write-logger-fatal-source-base-file",
                "leveldb-write-env-lock-file",
                "leveldb-write-env-new-writable-file",
                "leveldb-write-put",
                "leveldb-write-compact",
                "leveldb-write-close",
                "leveldb-read-open",
                "leveldb-read-get",
                "leveldb-read-close",
                "leveldb-write-log-sync-returned",
                "task-complete",
            },
            set(re.findall(r'return "([a-z-]+)";', phase_names)),
        )

        emit_phase = _body_after_signature(
            self.smoke,
            "void EmitDatabaseTaskPhase(DatabaseTaskPhase phase)",
        )
        self.assertIn(
            'std::fprintf(stderr, "%s%s\\n", kPhasePrefix, '
            "DatabaseTaskPhaseName(phase));",
            emit_phase,
        )
        self.assertIn("std::fflush(stderr);", emit_phase)
        self.assertNotIn("EmitMarker", emit_phase)
        self.assertNotIn("EmitDigestMarker", emit_phase)
        for sensitive in ("token", "profile", "path", "status", "digest"):
            with self.subTest(sensitive=sensitive):
                self.assertNotIn(sensitive, emit_phase.lower())

        start = _body_after_signature(
            self.smoke,
            "bool Start(base::FilePath profile_path, base::OnceClosure completion)",
        )
        task_post = "EmitDatabaseTaskPhase(DatabaseTaskPhase::kTaskPost);"
        self.assertLess(
            start.index("base::ThreadPool::CreateSequencedTaskRunner("),
            start.index(task_post),
        )
        self.assertLess(start.index(task_post), start.index("PostTaskAndReplyWithResult("))

        task = _body_after_signature(
            self.smoke, "DatabaseTaskResult RunDatabaseTask(DatabaseTaskInput input)"
        )
        self.assertLess(
            task.index("EmitDatabaseTaskPhase(DatabaseTaskPhase::kTaskStarted);"),
            task.index("const base::FilePath sqlite_path"),
        )
        self.assertLess(
            task.index("input.ClearRawTokens();"),
            task.index("EmitDatabaseTaskPhase(DatabaseTaskPhase::kTaskComplete);"),
        )
        self.assertLess(
            task.index("EmitDatabaseTaskPhase(DatabaseTaskPhase::kTaskComplete);"),
            task.index("return success ? DatabaseTaskResult::kSuccess"),
        )
        self.assertEqual(
            2,
            task.count("EmitDatabaseTaskPhase(DatabaseTaskPhase::kTaskComplete);"),
        )

        # The source-selected lock receipt has no phase telemetry, and the
        # separate write-interruption diagnostic has an intentionally
        # different, redacted read-marker grammar. Retain this legacy
        # normal-mode assertion over only the three ordinary switch cases.
        normal_cases = task[
            task.index("case SmokeMode::kWriteA:") : task.index(
                "case SmokeMode::kInterruptLevelDBWriteB:"
            )
        ]

        def assert_phase_immediately_precedes(phase: str, call: str) -> None:
            matches = re.findall(
                re.escape(f"EmitDatabaseTaskPhase(DatabaseTaskPhase::{phase});")
                + r"\s+(?:if\s*\(\s*|success\s*=\s*)"
                + re.escape(call),
                normal_cases,
            )
            self.assertEqual(len(matches), normal_cases.count(call))

        assert_phase_immediately_precedes(
            "kSQLiteWrite", "WriteSqliteTokenAndVerifyAfterClose("
        )
        assert_phase_immediately_precedes(
            "kLevelDBWrite", "WriteLevelDBTokenAndVerifyAfterClose("
        )
        assert_phase_immediately_precedes(
            "kSQLiteRead", "ReadSqliteToken("
        )
        assert_phase_immediately_precedes(
            "kSQLiteRead", "ReadSqliteTokenAndVerifyAfterClose("
        )
        assert_phase_immediately_precedes(
            "kLevelDBRead", "ReadLevelDBToken("
        )
        assert_phase_immediately_precedes(
            "kLevelDBRead", "ReadLevelDBTokenAndVerifyAfterClose("
        )

        def assert_phase_immediately_precedes_leveldb_call(
            body: str, phase: str, call: str
        ) -> None:
            self.assertRegex(
                body,
                re.escape(f"EmitDatabaseTaskPhase(DatabaseTaskPhase::{phase});")
                + r"\s+"
                + re.escape(call),
            )

        leveldb_read = _body_after_signature(
            self.smoke,
            "bool ReadLevelDBToken(const base::FilePath& database_path,",
        )
        assert_phase_immediately_precedes_leveldb_call(
            leveldb_read, "kLevelDBReadOpen", "if (!leveldb_env::OpenDB("
        )
        assert_phase_immediately_precedes_leveldb_call(
            leveldb_read,
            "kLevelDBReadGet",
            "const bool success =\n      database->Get(",
        )
        assert_phase_immediately_precedes_leveldb_call(
            leveldb_read, "kLevelDBReadClose", "database.reset();"
        )

        leveldb_write = _body_after_signature(
            self.smoke,
            "bool WriteLevelDBToken(const base::FilePath& database_path,",
        )
        self.assertIn("MayBlock-worker pre-call is diagnostic-only", leveldb_write)
        self.assertIn("not a behavior-equivalent repair", leveldb_write)
        assert_phase_immediately_precedes_leveldb_call(
            leveldb_write,
            "kLevelDBWriteTracker",
            "leveldb_env::DBTracker::GetInstance();",
        )
        assert_phase_immediately_precedes_leveldb_call(
            leveldb_write,
            "kLevelDBWriteOpen",
            "const leveldb::Status open_status = leveldb_env::OpenDB(",
        )
        self.assertIn(
            "&EmitLevelDBWritePreDBImplConstructionPhase",
            leveldb_write,
        )
        self.assertLess(
            leveldb_write.index("leveldb_env::DBTracker::GetInstance();"),
            leveldb_write.index(
                "EmitDatabaseTaskPhase(DatabaseTaskPhase::kLevelDBWriteOpen);"
            ),
        )
        assert_phase_immediately_precedes_leveldb_call(
            leveldb_write,
            "kLevelDBWritePut",
            "const bool success =\n      database->Put(",
        )
        assert_phase_immediately_precedes_leveldb_call(
            leveldb_write,
            "kLevelDBWriteCompact",
            "database->CompactRange(nullptr, nullptr);",
        )
        assert_phase_immediately_precedes_leveldb_call(
            leveldb_write, "kLevelDBWriteClose", "database.reset();"
        )

    def test_leveldb_open_env_diagnostic_is_scoped_owner_only_and_forwarding(self) -> None:
        self.assertIn("#include <atomic>", self.smoke)
        self.assertIn('#include "base/threading/platform_thread.h"', self.smoke)
        wrapper = _body_after_signature(
            self.smoke, "class DatabaseOpenDiagnosticEnv final"
        )
        for wording in (
            "target-only wrapper emits fixed diagnostic phases",
            "does not pre-call an\n// operation",
            "database-success signal",
            "outside this active diagnostic interval",
        ):
            with self.subTest(wording=wording):
                self.assertIn(wording, self.smoke)

        for forbidden in (
            "std::fprintf",
            "std::fflush",
            "database_path",
            "token",
            "digest",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, wrapper)

        phase_state = _body_after_signature(
            self.smoke, "class DatabaseOpenDiagnosticPhaseState final"
        )
        self.assertIn(
            "const std::shared_ptr<DatabaseOpenDiagnosticPhaseState> phase_state_;",
            wrapper,
        )
        self.assertIn(
            "std::make_shared<DatabaseOpenDiagnosticPhaseState>", wrapper
        )
        self.assertIn("bool IsOwnerPhaseEmissionEnabled() const", phase_state)
        self.assertIn(
            "base::PlatformThread::CurrentId() == owner_thread_id_", phase_state
        )
        self.assertIn(
            "std::atomic<bool> owner_phase_emission_enabled_{true};", phase_state
        )
        self.assertIn(
            "owner_phase_emission_enabled_.load(std::memory_order_relaxed)",
            phase_state,
        )
        self.assertIn(
            "owner_phase_emission_enabled_.store(false, std::memory_order_relaxed);",
            phase_state,
        )
        self.assertIn(
            "phase_state_->DisableOwnerPhaseEmission();", wrapper
        )
        owner_emission = _body_after_signature(
            phase_state, "bool IsOwnerPhaseEmissionEnabled() const"
        )
        self.assertLess(
            owner_emission.index("base::PlatformThread::CurrentId() == owner_thread_id_"),
            owner_emission.index("owner_phase_emission_enabled_.load("),
        )

        first_logger_logv = _body_after_signature(
            phase_state, "bool TryClaimFirstOwnerLoggerLogvPhase()"
        )
        self.assertIn("if (!IsOwnerPhaseEmissionEnabled())", first_logger_logv)
        self.assertIn(
            "std::atomic<bool> owner_logger_logv_phase_claimed_{false};",
            phase_state,
        )
        self.assertIn(
            "owner_logger_logv_phase_claimed_.compare_exchange_strong(",
            first_logger_logv,
        )
        self.assertLess(
            first_logger_logv.index("if (!IsOwnerPhaseEmissionEnabled())"),
            first_logger_logv.index("owner_logger_logv_phase_claimed_"),
        )

        forwarding = (
            (
                "leveldb::Status CreateDir(const std::string& directory) override",
                "kLevelDBWriteEnvCreateDir",
                "return leveldb::EnvWrapper::CreateDir(directory);",
            ),
            (
                "leveldb::Status RenameFile(const std::string& source,",
                "kLevelDBWriteEnvRenameFile",
                "return leveldb::EnvWrapper::RenameFile(source, target);",
            ),
            (
                "leveldb::Status LockFile(const std::string& filename,",
                "kLevelDBWriteEnvLockFile",
                "return leveldb::EnvWrapper::LockFile(filename, lock);",
            ),
            (
                "leveldb::Status NewWritableFile(const std::string& filename,",
                "kLevelDBWriteEnvNewWritableFile",
                "return leveldb::EnvWrapper::NewWritableFile(filename, result);",
            ),
        )
        for signature, phase, forwarded_call in forwarding:
            body = _body_after_signature(wrapper, signature)
            emission = f"EmitOwnerPhase(DatabaseTaskPhase::{phase});"
            with self.subTest(signature=signature):
                self.assertIn(emission, body)
                self.assertIn(forwarded_call, body)
                self.assertLess(body.index(emission), body.index(forwarded_call))

        new_logger = _body_after_signature(
            wrapper, "leveldb::Status NewLogger(const std::string& filename,"
        )
        self.assertIn(
            "EmitOwnerPhase(DatabaseTaskPhase::kLevelDBWriteEnvNewLogger);",
            new_logger,
        )
        self.assertEqual(
            1,
            new_logger.count("leveldb::EnvWrapper::NewLogger(filename, result)"),
        )
        self.assertIn("status.ok() && result && *result", new_logger)
        self.assertIn("*result = new DatabaseOpenDiagnosticLogger(", new_logger)
        self.assertIn("std::unique_ptr<leveldb::Logger>(*result)", new_logger)
        self.assertIn("phase_state_", new_logger)
        self.assertLess(
            new_logger.index(
                "EmitOwnerPhase(DatabaseTaskPhase::kLevelDBWriteEnvNewLogger);"
            ),
            new_logger.index("leveldb::EnvWrapper::NewLogger(filename, result)"),
        )
        self.assertLess(
            new_logger.index("leveldb::EnvWrapper::NewLogger(filename, result)"),
            new_logger.index("*result = new DatabaseOpenDiagnosticLogger("),
        )

        logger = _body_after_signature(
            self.smoke, "class DatabaseOpenDiagnosticLogger final"
        )
        self.assertIn("const std::unique_ptr<leveldb::Logger> target_logger_;", logger)
        self.assertIn(
            "const std::shared_ptr<DatabaseOpenDiagnosticPhaseState> phase_state_;",
            logger,
        )
        logger_logv = _body_after_signature(
            logger, "void Logv(const char* format, va_list arguments) override"
        )
        logger_logv_without_forwarding = logger_logv.replace(
            "target_logger_->Logv(format, arguments);", ""
        )
        for forbidden in ("va_copy", "va_end", "StringPrint", "format", "arguments"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, logger_logv_without_forwarding)
        self.assertEqual(
            1, logger_logv.count("target_logger_->Logv(format, arguments);")
        )
        self.assertIn(
            "phase_state_->TryClaimFirstOwnerLoggerLogvPhase();", logger_logv
        )
        self.assertIn(
            "DatabaseTaskPhase::kLevelDBWriteLoggerLogvFirstPre", logger_logv
        )
        self.assertIn(
            "DatabaseTaskPhase::kLevelDBWriteLoggerLogvFirstPost", logger_logv
        )
        self.assertLess(
            logger_logv.index("TryClaimFirstOwnerLoggerLogvPhase();"),
            logger_logv.index("kLevelDBWriteLoggerLogvFirstPre"),
        )
        self.assertLess(
            logger_logv.index("kLevelDBWriteLoggerLogvFirstPre"),
            logger_logv.index("target_logger_->Logv(format, arguments);"),
        )
        self.assertLess(
            logger_logv.index("target_logger_->Logv(format, arguments);"),
            logger_logv.index("kLevelDBWriteLoggerLogvFirstPost"),
        )

        file_exists = _body_after_signature(
            wrapper, "bool FileExists(const std::string& filename) override"
        )
        self.assertEqual(1, file_exists.count("leveldb::EnvWrapper::FileExists(filename)"))
        self.assertIn(
            "const bool emit_owner_phase = IsOwnerPhaseEmissionEnabled();",
            file_exists,
        )
        self.assertIn("phases = NextOwnerFileExistsPhases();", file_exists)
        self.assertIn("EmitDatabaseTaskPhase(phases.pre);", file_exists)
        self.assertIn("EmitDatabaseTaskPhase(phases.post);", file_exists)
        self.assertLess(
            file_exists.index("EmitDatabaseTaskPhase(phases.pre);"),
            file_exists.index("leveldb::EnvWrapper::FileExists(filename)"),
        )
        self.assertLess(
            file_exists.index("leveldb::EnvWrapper::FileExists(filename)"),
            file_exists.index("EmitDatabaseTaskPhase(phases.post);"),
        )
        self.assertLess(
            file_exists.index("EmitDatabaseTaskPhase(phases.post);"),
            file_exists.index("return exists;"),
        )
        self.assertNotIn(
            "EmitOwnerPhase(DatabaseTaskPhase::kLevelDBWriteEnvFileExists",
            file_exists,
        )
        self.assertNotIn("kLevelDBWriteEnvFileExistsReturned", wrapper)
        self.assertIn("never\n    // carries the consulted filename", file_exists)
        self.assertIn("bounded fallback pair", file_exists)

        file_exists_phases = _body_after_signature(
            wrapper, "FileExistsPhasePair NextOwnerFileExistsPhases()"
        )
        expected_file_exists_phases = (
            "kLevelDBWriteEnvFileExistsFirstPre",
            "kLevelDBWriteEnvFileExistsFirstPost",
            "kLevelDBWriteEnvFileExistsSecondPre",
            "kLevelDBWriteEnvFileExistsSecondPost",
            "kLevelDBWriteEnvFileExistsLaterPre",
            "kLevelDBWriteEnvFileExistsLaterPost",
        )
        for phase in expected_file_exists_phases:
            with self.subTest(phase=phase):
                self.assertIn(f"DatabaseTaskPhase::{phase}", file_exists_phases)
                self.assertEqual(
                    1, file_exists_phases.count(f"DatabaseTaskPhase::{phase}")
                )
        self.assertLess(
            file_exists_phases.index("kLevelDBWriteEnvFileExistsFirstPre"),
            file_exists_phases.index("kLevelDBWriteEnvFileExistsFirstPost"),
        )
        self.assertLess(
            file_exists_phases.index("kLevelDBWriteEnvFileExistsFirstPost"),
            file_exists_phases.index("kLevelDBWriteEnvFileExistsSecondPre"),
        )
        self.assertLess(
            file_exists_phases.index("kLevelDBWriteEnvFileExistsSecondPre"),
            file_exists_phases.index("kLevelDBWriteEnvFileExistsSecondPost"),
        )
        self.assertLess(
            file_exists_phases.index("kLevelDBWriteEnvFileExistsSecondPost"),
            file_exists_phases.index("kLevelDBWriteEnvFileExistsLaterPre"),
        )
        self.assertLess(
            file_exists_phases.index("kLevelDBWriteEnvFileExistsLaterPre"),
            file_exists_phases.index("kLevelDBWriteEnvFileExistsLaterPost"),
        )
        self.assertIn("switch (owner_file_exists_ordinal_)", file_exists_phases)
        self.assertIn("owner_file_exists_ordinal_ = 1;", file_exists_phases)
        self.assertIn("owner_file_exists_ordinal_ = 2;", file_exists_phases)
        self.assertIn("Saturate after the two", file_exists_phases)

        write = _body_after_signature(
            self.smoke,
            "bool WriteLevelDBToken(const base::FilePath& database_path,",
        )
        for token in (
            "DBImpl retains the Env pointer through its background work and destruction",
            "Its fixed phases observe only the\n  // real OpenDB forwarding calls",
            "stop as soon as OpenDB returns.",
            "DatabaseOpenDiagnosticEnv diagnostic_env(",
            "leveldb_env::Options diagnostic_options = options;",
            "diagnostic_options.env = &diagnostic_env;",
            "std::unique_ptr<leveldb::DB> database;",
            "diagnostic_env.DisableOwnerPhaseEmission();",
            "database.reset();",
        ):
            with self.subTest(token=token):
                self.assertIn(token, write)
        self.assertEqual(1, write.count("leveldb_env::OpenDB("))
        self.assertNotIn("leveldb_env::OpenDB(options,", write)
        self.assertRegex(
            write,
            r"const leveldb::Status open_status = leveldb_env::OpenDB\(\s*"
            r"diagnostic_options, database_path\.AsUTF8Unsafe\(\), &database,\s*"
            r"&EmitLevelDBWritePreDBImplConstructionPhase\);\s*"
            r"diagnostic_env\.DisableOwnerPhaseEmission\(\);",
        )
        ordered = (
            "DatabaseOpenDiagnosticEnv diagnostic_env(",
            "leveldb_env::Options diagnostic_options = options;",
            "diagnostic_options.env = &diagnostic_env;",
            "std::unique_ptr<leveldb::DB> database;",
            "const leveldb::Status open_status = leveldb_env::OpenDB(",
            "diagnostic_env.DisableOwnerPhaseEmission();",
            "database.reset();",
        )
        positions = [write.index(token) for token in ordered]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(1, self.smoke.count("DatabaseOpenDiagnosticEnv diagnostic_env"))

    def test_abort_pc_fatal_source_observer_is_scoped_and_redacted(self) -> None:
        self.assertIn("#include <optional>", self.smoke)
        self.assertIn('#include "base/logging_wasm.h"', self.smoke)
        self.assertIn(
            "#if defined(CHROME_WASM_M7_PROFILE_DATABASE_ABORT_PC_DIAGNOSTIC)",
            self.smoke,
        )

        source_phase = _body_after_signature(
            self.smoke,
            "std::optional<DatabaseTaskPhase> FatalLogSourcePhase(const char* file,",
        )
        expected_branches = (
            """if ((source == \"base/time/time_wasm.cc\" ||
       source == \"../../base/time/time_wasm.cc\") &&
      (line == 44 || line == 50)) {
    return DatabaseTaskPhase::kLevelDBWriteLoggerFatalSourceWasmTime;
  }""",
            """if ((source == \"base/i18n/time_formatting.cc\" ||
       source == \"../../base/i18n/time_formatting.cc\") &&
      (line == 74 || line == 76 || line == 81)) {
    return DatabaseTaskPhase::kLevelDBWriteLoggerFatalSourceTimeFormatting;
  }""",
            """if ((source == \"third_party/leveldatabase/env_chromium.cc\" ||
       source == \"../../third_party/leveldatabase/env_chromium.cc\") &&
      (line == 355 || line == 1340)) {
    return DatabaseTaskPhase::kLevelDBWriteLoggerFatalSourceLevelDB;
  }""",
            """if (((source == \"base/files/file.cc\" ||
        source == \"../../base/files/file.cc\") &&
       (line == 46 || line == 53)) ||
      ((source == \"base/files/file_posix.cc\" ||
        source == \"../../base/files/file_posix.cc\") &&
       line == 439)) {
    return DatabaseTaskPhase::kLevelDBWriteLoggerFatalSourceBaseFile;
  }""",
        )
        for branch in expected_branches:
            with self.subTest(branch=branch):
                self.assertIn(branch, source_phase)
        self.assertEqual(
            [
                "base/time/time_wasm.cc",
                "../../base/time/time_wasm.cc",
                "base/i18n/time_formatting.cc",
                "../../base/i18n/time_formatting.cc",
                "third_party/leveldatabase/env_chromium.cc",
                "../../third_party/leveldatabase/env_chromium.cc",
                "base/files/file.cc",
                "../../base/files/file.cc",
                "base/files/file_posix.cc",
                "../../base/files/file_posix.cc",
            ],
            re.findall(r'source == "([^"]+)"', source_phase),
        )
        self.assertEqual(
            [44, 50, 74, 76, 81, 355, 1340, 46, 53, 439],
            [int(line) for line in re.findall(r"line == (\d+)", source_phase)],
        )
        self.assertEqual(
            [
                "kLevelDBWriteLoggerFatalSourceWasmTime",
                "kLevelDBWriteLoggerFatalSourceTimeFormatting",
                "kLevelDBWriteLoggerFatalSourceLevelDB",
                "kLevelDBWriteLoggerFatalSourceBaseFile",
            ],
            re.findall(r"return DatabaseTaskPhase::(k\w+);", source_phase),
        )
        self.assertEqual(1, source_phase.count("return std::nullopt;"))
        for widening_operation in (
            "starts_with",
            "ends_with",
            ".find(",
            ".substr(",
            "replace",
            "FilePath",
        ):
            with self.subTest(widening_operation=widening_operation):
                self.assertNotIn(widening_operation, source_phase)
        self.assertNotIn("EmitMarker", source_phase)
        self.assertNotIn("EmitDigestMarker", source_phase)
        self.assertNotIn("std::fprintf", source_phase)

        diagnostic_macro = (
            "#if defined(CHROME_WASM_M7_PROFILE_DATABASE_ABORT_PC_DIAGNOSTIC)"
        )
        diagnostic_endif = (
            "#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_ABORT_PC_DIAGNOSTIC)"
        )
        for symbol in (
            "FatalLogSourcePhase",
            "ObserveOwnerFatalLogSource",
            "g_database_open_diagnostic_logv_phase_state",
            "ObserveDatabaseOpenDiagnosticFatalLog",
            "ScopedDatabaseOpenDiagnosticFatalLogObserver",
        ):
            with self.subTest(symbol=symbol):
                symbol_index = self.smoke.index(symbol)
                self.assertNotEqual(
                    -1, self.smoke.rfind(diagnostic_macro, 0, symbol_index)
                )
                self.assertNotEqual(
                    -1, self.smoke.find(diagnostic_endif, symbol_index)
                )

        phase_state = _body_after_signature(
            self.smoke, "class DatabaseOpenDiagnosticPhaseState final"
        )
        fatal_source = _body_after_signature(
            phase_state, "void ObserveOwnerFatalLogSource(const char* file, int line)"
        )
        self.assertIn("if (!IsOwnerPhaseEmissionEnabled())", fatal_source)
        self.assertIn("FatalLogSourcePhase(file, line)", fatal_source)
        self.assertIn("owner_fatal_log_source_phase_claimed_.compare_exchange_strong(", fatal_source)
        self.assertIn("EmitDatabaseTaskPhase(*phase);", fatal_source)
        self.assertIn(
            "std::atomic<bool> owner_fatal_log_source_phase_claimed_{false};",
            phase_state,
        )

        callback = _body_after_signature(
            self.smoke, "bool ObserveDatabaseOpenDiagnosticFatalLog(int severity,"
        )
        self.assertIn("severity == logging::LOGGING_FATAL", callback)
        self.assertIn("phase_state->ObserveOwnerFatalLogSource(file, line);", callback)
        self.assertEqual("return false;", callback.strip().splitlines()[-1].strip())
        for forbidden in ("message_start", "message)", "std::fprintf", "EmitMarker"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, callback)

        scoped_observer = _body_after_signature(
            self.smoke,
            "class ScopedDatabaseOpenDiagnosticFatalLogObserver final",
        )
        self.assertIn("g_database_open_diagnostic_logv_phase_state = phase_state;", scoped_observer)
        self.assertRegex(
            self.smoke,
            r"thread_local DatabaseOpenDiagnosticPhaseState\*\s+"
            r"g_database_open_diagnostic_logv_phase_state = nullptr;",
        )
        self.assertIn(
            "installed_handler_ = logging::TrySetLogMessageHandlerIfNone(",
            scoped_observer,
        )
        self.assertIn(
            "&ObserveDatabaseOpenDiagnosticFatalLog);",
            scoped_observer,
        )
        self.assertIn("logging::ClearLogMessageHandlerIfEqual(", scoped_observer)
        self.assertLess(
            scoped_observer.index("logging::ClearLogMessageHandlerIfEqual("),
            scoped_observer.index(
                "g_database_open_diagnostic_logv_phase_state = previous_phase_state_;"
            ),
        )
        self.assertIn(
            "g_database_open_diagnostic_logv_phase_state = previous_phase_state_;",
            scoped_observer,
        )

        logger = _body_after_signature(
            self.smoke, "class DatabaseOpenDiagnosticLogger final"
        )
        logger_logv = _body_after_signature(
            logger, "void Logv(const char* format, va_list arguments) override"
        )
        self.assertIn(
            "const auto forward_logv = [&]",
            logger_logv,
        )
        self.assertIn(
            "ScopedDatabaseOpenDiagnosticFatalLogObserver fatal_log_observer(",
            logger_logv,
        )
        observer_start = logger_logv.index(
            "ScopedDatabaseOpenDiagnosticFatalLogObserver fatal_log_observer("
        )
        self.assertLess(
            observer_start,
            logger_logv.index("forward_logv();", observer_start),
        )

        self.assertIn(
            "std::atomic<LogMessageHandlerFunction> g_log_message_handler = nullptr;",
            self.logging,
        )
        setter = _body_after_signature(
            self.logging, "void SetLogMessageHandler(LogMessageHandlerFunction handler)"
        )
        getter = _body_after_signature(
            self.logging, "LogMessageHandlerFunction GetLogMessageHandler()"
        )
        self.assertIn("g_log_message_handler.store(handler, std::memory_order_release);", setter)
        self.assertIn("g_log_message_handler.load(std::memory_order_acquire);", getter)
        self.assertIn(
            "BASE_EXPORT bool TrySetLogMessageHandlerIfNone(",
            self.logging_wasm_header,
        )
        self.assertIn(
            "BASE_EXPORT bool ClearLogMessageHandlerIfEqual(",
            self.logging_wasm_header,
        )
        self.assertIn(
            '#error "logging_wasm.h must only be included by WebAssembly targets"',
            self.logging_wasm_header,
        )
        claim = _body_after_signature(
            self.logging,
            "bool TrySetLogMessageHandlerIfNone(LogMessageHandlerFunction handler)",
        )
        clear = _body_after_signature(
            self.logging,
            "bool ClearLogMessageHandlerIfEqual(LogMessageHandlerFunction handler)",
        )
        self.assertIn("g_log_message_handler.compare_exchange_strong(", claim)
        self.assertIn("LogMessageHandlerFunction expected = nullptr;", claim)
        self.assertIn("expected, handler", claim)
        self.assertIn("g_log_message_handler.compare_exchange_strong(", clear)
        self.assertIn("LogMessageHandlerFunction expected = handler;", clear)
        self.assertIn("expected, nullptr", clear)
        flush = _body_after_signature(self.logging, "void LogMessage::Flush()")
        self.assertIn(
            "const LogMessageHandlerFunction message_handler = GetLogMessageHandler();",
            flush,
        )
        self.assertIn("message_handler(severity_, file_, line_, message_start_, str_newline)", flush)

    def test_leveldb_pre_dbimpl_diagnostic_is_once_and_preserves_factory_override(self) -> None:
        self.assertIn('#include "base/functional/callback.h"', self.leveldb_header)
        self.assertIn(
            "void (*before_dbimpl_construction)()", self.leveldb_header
        )
        self.assertIn(
            "void (*before_dbimpl_construction)() = nullptr",
            self.leveldb_header,
        )
        self.assertNotIn(
            "base::OnceClosure before_dbimpl_construction", self.leveldb_header
        )
        self.assertIn("Testing-only overload", self.leveldb_header)
        self.assertIn(
            "before the first real leveldb::DB::Open", self.leveldb_header
        )
        self.assertIn(
            "not called when a DBFactory override handles the open",
            self.leveldb_header,
        )
        self.assertIn("callback is not called again", self.leveldb_header)
        self.assertIn(
            "does not allocate before it is emitted", self.leveldb_header
        )

        normal_open = _body_after_signature(
            self.leveldb_source,
            "leveldb::Status OpenDB(const leveldb_env::Options& options,\n"
            "                       const std::string& name,\n"
            "                       std::unique_ptr<leveldb::DB>* dbptr)",
        )
        self.assertEqual(
            "return OpenDB(options, name, dbptr, nullptr);",
            normal_open.strip(),
        )

        diagnostic_open = _body_after_signature(
            self.leveldb_source,
            "leveldb::Status OpenDB(const leveldb_env::Options& options,\n"
            "                       const std::string& name,\n"
            "                       std::unique_ptr<leveldb::DB>* dbptr,\n"
            "                       void (*before_dbimpl_construction)())",
        )
        factory = "if (!GetDBFactoryOverride().is_null())"
        first_tracker_open = "DBTracker::GetInstance()->OpenDatabase(\n        options, name, &tracked_db, before_dbimpl_construction);"
        retry_tracker_open = "DBTracker::GetInstance()->OpenDatabase(\n          options, name, &tracked_db, nullptr);"
        self.assertIn(factory, diagnostic_open)
        self.assertIn(first_tracker_open, diagnostic_open)
        self.assertIn(retry_tracker_open, diagnostic_open)
        self.assertLess(diagnostic_open.index(factory), diagnostic_open.index(first_tracker_open))
        self.assertLess(
            diagnostic_open.index(first_tracker_open),
            diagnostic_open.index(retry_tracker_open),
        )
        factory_body_start = diagnostic_open.index(factory)
        factory_body_end = diagnostic_open.index("\n  }", factory_body_start)
        factory_body = diagnostic_open[factory_body_start:factory_body_end]
        self.assertIn(
            "return GetDBFactoryOverride().Run(options, name, dbptr);",
            factory_body,
        )
        self.assertNotIn(
            "before_dbimpl_construction",
            factory_body,
        )
        self.assertNotIn("OpenDatabase(", factory_body)

        tracker_open = _body_after_signature(
            self.leveldb_source,
            "leveldb::Status DBTracker::OpenDatabase(\n"
            "    const leveldb_env::Options& options,\n"
            "    const std::string& name,\n"
            "    TrackedDB** dbptr,\n"
            "    void (*before_dbimpl_construction)())",
        )
        self.assertRegex(
            tracker_open,
            r"if \(before_dbimpl_construction\) \{\s*"
            r"before_dbimpl_construction\(\);\s*\}\s*"
            r"auto status = leveldb::DB::Open\(options, name, &db\);",
        )

        pre_dbimpl_phase = _body_after_signature(
            self.smoke,
            "void EmitLevelDBWritePreDBImplConstructionPhase()",
        )
        self.assertEqual(
            "EmitDatabaseTaskPhase(\n"
            "      DatabaseTaskPhase::kLevelDBWritePreDBImplConstruction);",
            pre_dbimpl_phase.strip(),
        )

        write = _body_after_signature(
            self.smoke,
            "bool WriteLevelDBToken(const base::FilePath& database_path,",
        )
        self.assertEqual(
            1, write.count("&EmitLevelDBWritePreDBImplConstructionPhase")
        )
        self.assertNotIn("base::BindOnce(&EmitDatabaseTaskPhase", write)
        self.assertLess(
            write.index("&EmitLevelDBWritePreDBImplConstructionPhase"),
            write.index("diagnostic_env.DisableOwnerPhaseEmission();"),
        )

    def test_one_shutdown_blocking_runner_performs_all_database_work(self) -> None:
        self.assertEqual(
            self.smoke.count("base::ThreadPool::CreateSequencedTaskRunner("), 1
        )
        self.assertEqual(self.smoke.count("PostTaskAndReplyWithResult("), 1)
        self.assertIn(
            "{base::MayBlock(), base::TaskShutdownBehavior::BLOCK_SHUTDOWN}",
            self.smoke,
        )
        start = _body_after_signature(
            self.smoke,
            "bool Start(base::FilePath profile_path, base::OnceClosure completion)",
        )
        self.assertLess(start.index('EmitMarker("READY")'), start.index("DatabaseTaskInput input"))
        self.assertLess(start.index("DatabaseTaskInput input"), start.index("ClearRawTokens();"))
        self.assertIn("base::BindOnce(&RunDatabaseTask, std::move(input))", start)
        self.assertIn("OnDatabaseTaskComplete(DatabaseTaskResult::kFailure);", start)

        task = _body_after_signature(
            self.smoke, "DatabaseTaskResult RunDatabaseTask(DatabaseTaskInput input)"
        )
        self.assertIn("input.profile_path.AppendASCII(kSQLiteFilename)", task)
        self.assertIn("input.profile_path.AppendASCII(kLevelDBDirectory)", task)
        middle = task[task.index("case SmokeMode::kVerifyAWriteB:") : task.index("case SmokeMode::kVerifyB:")]
        self.assertLess(middle.index("ReadSqliteToken"), middle.index("ReadLevelDBToken"))
        self.assertLess(middle.index("ReadLevelDBToken"), middle.index("WriteSqliteTokenAndVerifyAfterClose"))
        self.assertLess(middle.index("WriteSqliteTokenAndVerifyAfterClose"), middle.index("WriteLevelDBTokenAndVerifyAfterClose"))
        self.assertLess(task.index("input.ClearRawTokens();"), task.index("return success"))

    def test_leveldb_options_are_initialized_on_ui_before_worker_reuse(self) -> None:
        start = _body_after_signature(
            self.smoke,
            "bool Start(base::FilePath profile_path, base::OnceClosure completion)",
        )
        options = "leveldb_env::Options leveldb_options = LevelDBOptionsForSmoke();"
        input_construction = "DatabaseTaskInput input"
        runner = "base::ThreadPool::CreateSequencedTaskRunner("
        post = "PostTaskAndReplyWithResult("
        self.assertIn("this UI/main sequence", start)
        self.assertIn(options, start)
        self.assertIn("std::move(leveldb_options)", start)
        self.assertLess(start.index(options), start.index(input_construction))
        self.assertLess(start.index(input_construction), start.index(runner))
        self.assertLess(start.index(runner), start.index(post))

        input_constructor_start = self.smoke.index(
            "DatabaseTaskInput(base::FilePath profile_path,"
        )
        input_constructor = self.smoke[
            input_constructor_start : self.smoke.index("{", input_constructor_start)
        ]
        self.assertIn("leveldb_env::Options leveldb_options", input_constructor)
        self.assertIn("leveldb_options(std::move(leveldb_options))", input_constructor)
        self.assertIn("leveldb_env::Options leveldb_options;", self.smoke)

        task = _body_after_signature(
            self.smoke, "DatabaseTaskResult RunDatabaseTask(DatabaseTaskInput input)"
        )
        self.assertNotIn("LevelDBOptionsForSmoke", task)
        # The original four normal-mode uses retain the UI-created options;
        # the source-selected interruption diagnostic adds three more, the
        # bounded recovery probe adds its strict double-reopen consumer, and
        # the separate lock receipt adds its holder/contender/reopen consumer,
        # without constructing options on its worker.
        self.assertEqual(9, task.count("input.leveldb_options"))

        for signature in (
            "bool ReadLevelDBToken(const base::FilePath& database_path,",
            "bool WriteLevelDBToken(const base::FilePath& database_path,",
            "bool WriteLevelDBTokenAndVerifyAfterClose(",
            "bool ReadLevelDBTokenAndVerifyAfterClose(",
        ):
            start = self.smoke.index(signature)
            declaration = self.smoke[start : self.smoke.index("{", start)]
            body = _body_after_signature(self.smoke, signature)
            with self.subTest(signature=signature):
                self.assertIn("const leveldb_env::Options& options", declaration)
                self.assertNotIn("LevelDBOptionsForSmoke", body)

        self.assertIn("WriteLevelDBToken(database_path, token, options)", self.smoke)
        self.assertIn("ReadLevelDBToken(database_path, token, options)", self.smoke)

    def test_sqlite_uses_normal_locking_transaction_checkpoint_integrity_and_reopen(self) -> None:
        for token in (
            '#include "sql/database.h"',
            '#include "sql/statement.h"',
            '#include "sql/transaction.h"',
            "options.set_exclusive_locking(false)",
            ".set_wal_mode(false)",
            'sql::Database::Tag("Test")',
            "sql::Transaction transaction(&database);",
            "transaction.Begin()",
            "transaction.Commit()",
            "database->CheckpointDatabase(true)",
            "database->FullIntegrityCheck(&messages)",
            'messages[0] == "ok"',
            "database.Close();",
            ".set_mmap_enabled(false)",
            ".set_no_sync(false)",
            "WriteSqliteTokenAndVerifyAfterClose",
            "ReadSqliteTokenAndVerifyAfterClose",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.smoke)

        self.assertIn("database.set_error_callback(base::DoNothing());", self.smoke)
        write_reopen = _body_after_signature(
            self.smoke,
            "bool WriteSqliteTokenAndVerifyAfterClose(const base::FilePath& database_path,",
        )
        self.assertIn("WriteSqliteToken(database_path, token)", write_reopen)
        self.assertIn("ReadSqliteToken(database_path, token)", write_reopen)

    def test_leveldb_uses_chromium_env_sync_compact_close_and_reopen(self) -> None:
        for token in (
            '#include "third_party/leveldatabase/env_chromium.h"',
            "leveldb_env::Options options;",
            "options.env = leveldb::Env::Default();",
            "options.create_if_missing = true;",
            "options.error_if_exists = false;",
            "options.paranoid_checks = true;",
            "options.reuse_logs = true;",
            "leveldb_env::OpenDB(options, database_path.AsUTF8Unsafe(), &database)",
            "leveldb::WriteOptions write_options;",
            "write_options.sync = true;",
            "leveldb::ReadOptions read_options;",
            "read_options.verify_checksums = true;",
            "database->CompactRange(nullptr, nullptr);",
            "database.reset();",
            "WriteLevelDBTokenAndVerifyAfterClose",
            "ReadLevelDBTokenAndVerifyAfterClose",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.smoke)

        write = _body_after_signature(
            self.smoke,
            "bool WriteLevelDBToken(const base::FilePath& database_path,",
        )
        self.assertLess(write.index("write_options.sync = true;"), write.index("->Put("))
        self.assertLess(write.index("->Put("), write.index("database->CompactRange(nullptr, nullptr);"))
        self.assertLess(write.index("database->CompactRange(nullptr, nullptr);"), write.index("database.reset();"))

    def test_closed_marker_precedes_shutdown_completion_and_lease_requires_all_boundaries(self) -> None:
        complete = _body_after_signature(
            self.smoke,
            "void OnDatabaseTaskComplete(DatabaseTaskResult result)",
        )
        closed = complete.index('EmitDigestMarker("DATABASES_CLOSED", expected_digest_);')
        completion = complete.index("std::move(completion_).Run();")
        self.assertLess(closed, completion)
        self.assertIn("databases_closed_ = true;", complete)

        fence = _body_after_signature(self.smoke, "void NotifyFenceResult(bool success)")
        lifecycle = _body_after_signature(
            self.smoke, "void NotifyStorageLifecycle(bool success)"
        )
        drain = _body_after_signature(
            self.smoke, "void NotifyBackendDrain(bool success)"
        )
        self.assertIn("!DidSucceed()", fence)
        self.assertIn("!fence_succeeded_", lifecycle)
        self.assertIn("!storage_lifecycle_succeeded_", drain)
        self.assertLess(drain.index("lease_released_ = true;"), drain.index('EmitMarker("LEASE_RELEASED")'))

    def test_native_marker_grammar_matches_frozen_host_and_runner_protocol(self) -> None:
        host = source("tools/wasm/host/chrome_wasm_profile_database_smoke.js")
        runner = source("tools/wasm/run_m7_chrome_profile_database_dom_smoke.py")
        self.assertIn(
            'const M7_MARKER_PREFIX = "CHROMIUM_WASM_M7_DATABASE:";', host
        )
        self.assertIn(
            'M7_DATABASE_MARKER_PREFIX = "CHROMIUM_WASM_M7_DATABASE:"', runner
        )

        host_expected = _body_after_signature(
            host, "function expectedMarkers(ordinal, digests)"
        )
        run_one = host_expected[
            host_expected.index("if (ordinal === 1)") : host_expected.index(
                "if (ordinal === 2)"
            )
        ]
        run_two = host_expected[
            host_expected.index("if (ordinal === 2)") : host_expected.index(
                "if (ordinal === 3)"
            )
        ]
        run_three = host_expected[host_expected.index("if (ordinal === 3)") :]

        def assert_in_order(text: str, markers: tuple[str, ...]) -> None:
            positions = [text.index(marker) for marker in markers]
            self.assertEqual(positions, sorted(positions))

        assert_in_order(
            run_one,
            (
                "READY",
                "SQLITE_WRITE_ACCEPTED",
                "LEVELDB_WRITE_ACCEPTED",
                "DATABASES_CLOSED",
                "FENCE_OK",
                "LEASE_RELEASED",
            ),
        )
        assert_in_order(
            run_two,
            (
                "READY",
                "SQLITE_READ_A_OK",
                "LEVELDB_READ_A_OK",
                "SQLITE_WRITE_ACCEPTED",
                "LEVELDB_WRITE_ACCEPTED",
                "DATABASES_CLOSED",
                "FENCE_OK",
                "LEASE_RELEASED",
            ),
        )
        assert_in_order(
            run_three,
            (
                "READY",
                "SQLITE_READ_B_OK",
                "LEVELDB_READ_B_OK",
                "DATABASES_CLOSED",
                "FENCE_OK",
                "LEASE_RELEASED",
            ),
        )

        complete = _body_after_signature(
            self.smoke, "void OnDatabaseTaskComplete(DatabaseTaskResult result)"
        )
        write_a = complete[
            complete.index("case SmokeMode::kWriteA:") : complete.index(
                "case SmokeMode::kVerifyAWriteB:"
            )
        ]
        verify_a_write_b = complete[
            complete.index("case SmokeMode::kVerifyAWriteB:") : complete.index(
                "case SmokeMode::kVerifyB:"
            )
        ]
        verify_b = complete[
            complete.index("case SmokeMode::kVerifyB:") : complete.index(
                "case SmokeMode::kNone:"
            )
        ]
        assert_in_order(
            write_a, ("SQLITE_WRITE_ACCEPTED", "LEVELDB_WRITE_ACCEPTED")
        )
        assert_in_order(
            verify_a_write_b,
            (
                "SQLITE_READ_A_OK",
                "LEVELDB_READ_A_OK",
                "SQLITE_WRITE_ACCEPTED",
                "LEVELDB_WRITE_ACCEPTED",
            ),
        )
        assert_in_order(verify_b, ("SQLITE_READ_B_OK", "LEVELDB_READ_B_OK"))
        self.assertLess(
            complete.index('EmitDigestMarker("DATABASES_CLOSED", expected_digest_);'),
            complete.index("std::move(completion_).Run();"),
        )


if __name__ == "__main__":
    unittest.main()
