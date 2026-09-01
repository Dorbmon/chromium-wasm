// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_database_smoke.h"

#include <atomic>
#include <cstdlib>
#include <cstdio>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "base/check.h"
#include "base/command_line.h"
#include "base/files/file_util.h"
#include "base/functional/bind.h"
#include "base/functional/callback.h"
#include "base/functional/callback_helpers.h"
#include "base/logging_wasm.h"
#include "base/no_destructor.h"
#include "base/strings/string_number_conversions.h"
#include "base/task/sequenced_task_runner.h"
#include "base/task/task_traits.h"
#include "base/task/thread_pool.h"
#include "base/threading/platform_thread.h"
#include "build/build_config.h"
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
#include "chrome/browser/wasm/wasm_profile_database_sqlite_recovery_vfs.h"
#endif
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_OUTSTANDING_IO_REFUSAL_TEST)
#include "chrome/browser/wasm/wasm_profile_storage.h"
#endif
#include "crypto/hash.h"
#include "leveldb/db.h"
#include "leveldb/env.h"
#include "leveldb/options.h"
#include "sql/database.h"
#include "sql/sqlite_result_code_values.h"
#include "sql/statement.h"
#include "sql/transaction.h"
#include "third_party/leveldatabase/env_chromium.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_profile_database_smoke.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kSmokeSwitch[] = "wasm-profile-database-smoke";
constexpr char kTokenASwitch[] = "wasm-profile-database-token-a";
constexpr char kTokenBSwitch[] = "wasm-profile-database-token-b";
constexpr char kWriteAMode[] = "write-a";
constexpr char kVerifyAWriteBMode[] = "verify-a-write-b";
constexpr char kVerifyBMode[] = "verify-b";
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_LOCK_TEST)
constexpr char kLockContentionMode[] = "lock-contention";
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_LOCK_TEST)
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_LOCK_TEST)
constexpr char kSQLiteLockContentionMode[] = "sqlite-lock-contention";
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_LOCK_TEST)
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)
constexpr char kInterruptLevelDBWriteBMode[] = "interrupt-leveldb-write-b";
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC) || defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
constexpr char kObserveLevelDBWriteBMode[] = "observe-leveldb-write-b";
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)
constexpr char kRecoverLevelDBWriteBMode[] = "recover-leveldb-write-b";
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
constexpr char kInterruptSqliteWriteBMode[] = "interrupt-sqlite-write-b";
constexpr char kRecoverSqliteWriteBMode[] = "recover-sqlite-write-b";
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
constexpr size_t kOpaqueTokenLength = 64;

constexpr char kSQLiteFilename[] = "m7_profile_database_smoke.sqlite";
constexpr char kLevelDBDirectory[] = "m7_profile_database_smoke_leveldb";
constexpr char kDatabaseKey[] = "m7_profile_database_smoke_token";

constexpr char kMarkerPrefix[] = "CHROMIUM_WASM_M7_DATABASE:";
constexpr char kPhasePrefix[] = "CHROMIUM_WASM_M7_DATABASE_PHASE:";
#if defined(\
    CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
// The five-store aggregate has a closed acceptance receipt. Standalone
// database artifacts retain this diagnostic phase stream, but emitting it in
// the aggregate would make otherwise valid runs fail the host grammar.
constexpr bool kEmitDatabaseTaskPhases = false;
#else
constexpr bool kEmitDatabaseTaskPhases = true;
#endif  // defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)

enum class SmokeMode {
  kNone,
  kWriteA,
  kVerifyAWriteB,
  kVerifyB,
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_LOCK_TEST)
  kLockContention,
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_LOCK_TEST)
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_LOCK_TEST)
  kSQLiteLockContention,
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_LOCK_TEST)
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)
  kInterruptLevelDBWriteB,
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC) || defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
  kObserveLevelDBWriteB,
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)
  kRecoverLevelDBWriteB,
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
  kInterruptSqliteWriteB,
  kRecoverSqliteWriteB,
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
};

enum class DatabaseTaskResult {
  kSuccess,
  kRecoveryA,
  kRecoveryB,
  kFailure,
};

// These are fixed diagnostic-only phases. They are deliberately separate from
// the acceptance-marker protocol and never carry input, paths, status, or
// digests.
enum class DatabaseTaskPhase {
  kTaskPost,
  kTaskStarted,
  kSQLiteWrite,
  kSQLiteRead,
  kLevelDBWrite,
  kLevelDBRead,
  kLevelDBWriteTracker,
  kLevelDBWriteOpen,
  kLevelDBWritePreDBImplConstruction,
  kLevelDBWriteEnvFileExistsFirstPre,
  kLevelDBWriteEnvFileExistsFirstPost,
  kLevelDBWriteEnvFileExistsSecondPre,
  kLevelDBWriteEnvFileExistsSecondPost,
  kLevelDBWriteEnvFileExistsLaterPre,
  kLevelDBWriteEnvFileExistsLaterPost,
  kLevelDBWriteEnvCreateDir,
  kLevelDBWriteEnvRenameFile,
  kLevelDBWriteEnvNewLogger,
  kLevelDBWriteLoggerLogvFirstPre,
  kLevelDBWriteLoggerLogvFirstPost,
  kLevelDBWriteLoggerFatalSourceWasmTime,
  kLevelDBWriteLoggerFatalSourceTimeFormatting,
  kLevelDBWriteLoggerFatalSourceLevelDB,
  kLevelDBWriteLoggerFatalSourceBaseFile,
  kLevelDBWriteEnvLockFile,
  kLevelDBWriteEnvNewWritableFile,
  kLevelDBWritePut,
  kLevelDBWriteCompact,
  kLevelDBWriteClose,
  kLevelDBReadOpen,
  kLevelDBReadGet,
  kLevelDBReadClose,
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)
  kLevelDBWriteLogSyncReturned,
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC) || defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
  kSQLiteWriteMainDbSyncReturned,
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
  kTaskComplete,
};

const char* DatabaseTaskPhaseName(DatabaseTaskPhase phase) {
  switch (phase) {
    case DatabaseTaskPhase::kTaskPost:
      return "task-post";
    case DatabaseTaskPhase::kTaskStarted:
      return "task-started";
    case DatabaseTaskPhase::kSQLiteWrite:
      return "sqlite-write";
    case DatabaseTaskPhase::kSQLiteRead:
      return "sqlite-read";
    case DatabaseTaskPhase::kLevelDBWrite:
      return "leveldb-write";
    case DatabaseTaskPhase::kLevelDBRead:
      return "leveldb-read";
    case DatabaseTaskPhase::kLevelDBWriteTracker:
      return "leveldb-write-tracker";
    case DatabaseTaskPhase::kLevelDBWriteOpen:
      return "leveldb-write-open";
    case DatabaseTaskPhase::kLevelDBWritePreDBImplConstruction:
      return "leveldb-write-pre-dbimpl-construction";
    case DatabaseTaskPhase::kLevelDBWriteEnvFileExistsFirstPre:
      return "leveldb-write-env-file-exists-first-pre";
    case DatabaseTaskPhase::kLevelDBWriteEnvFileExistsFirstPost:
      return "leveldb-write-env-file-exists-first-post";
    case DatabaseTaskPhase::kLevelDBWriteEnvFileExistsSecondPre:
      return "leveldb-write-env-file-exists-second-pre";
    case DatabaseTaskPhase::kLevelDBWriteEnvFileExistsSecondPost:
      return "leveldb-write-env-file-exists-second-post";
    case DatabaseTaskPhase::kLevelDBWriteEnvFileExistsLaterPre:
      return "leveldb-write-env-file-exists-later-pre";
    case DatabaseTaskPhase::kLevelDBWriteEnvFileExistsLaterPost:
      return "leveldb-write-env-file-exists-later-post";
    case DatabaseTaskPhase::kLevelDBWriteEnvCreateDir:
      return "leveldb-write-env-create-dir";
    case DatabaseTaskPhase::kLevelDBWriteEnvRenameFile:
      return "leveldb-write-env-rename-file";
    case DatabaseTaskPhase::kLevelDBWriteEnvNewLogger:
      return "leveldb-write-env-new-logger";
    case DatabaseTaskPhase::kLevelDBWriteLoggerLogvFirstPre:
      return "leveldb-write-logger-logv-first-pre";
    case DatabaseTaskPhase::kLevelDBWriteLoggerLogvFirstPost:
      return "leveldb-write-logger-logv-first-post";
    case DatabaseTaskPhase::kLevelDBWriteLoggerFatalSourceWasmTime:
      return "leveldb-write-logger-fatal-source-wasm-time";
    case DatabaseTaskPhase::kLevelDBWriteLoggerFatalSourceTimeFormatting:
      return "leveldb-write-logger-fatal-source-time-formatting";
    case DatabaseTaskPhase::kLevelDBWriteLoggerFatalSourceLevelDB:
      return "leveldb-write-logger-fatal-source-leveldb";
    case DatabaseTaskPhase::kLevelDBWriteLoggerFatalSourceBaseFile:
      return "leveldb-write-logger-fatal-source-base-file";
    case DatabaseTaskPhase::kLevelDBWriteEnvLockFile:
      return "leveldb-write-env-lock-file";
    case DatabaseTaskPhase::kLevelDBWriteEnvNewWritableFile:
      return "leveldb-write-env-new-writable-file";
    case DatabaseTaskPhase::kLevelDBWritePut:
      return "leveldb-write-put";
    case DatabaseTaskPhase::kLevelDBWriteCompact:
      return "leveldb-write-compact";
    case DatabaseTaskPhase::kLevelDBWriteClose:
      return "leveldb-write-close";
    case DatabaseTaskPhase::kLevelDBReadOpen:
      return "leveldb-read-open";
    case DatabaseTaskPhase::kLevelDBReadGet:
      return "leveldb-read-get";
    case DatabaseTaskPhase::kLevelDBReadClose:
      return "leveldb-read-close";
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)
    case DatabaseTaskPhase::kLevelDBWriteLogSyncReturned:
      return "leveldb-write-log-sync-returned";
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC) || defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
    case DatabaseTaskPhase::kSQLiteWriteMainDbSyncReturned:
      return "sqlite-write-main-db-sync-returned";
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
    case DatabaseTaskPhase::kTaskComplete:
      return "task-complete";
  }
  return "task-complete";
}

void EmitDatabaseTaskPhase(DatabaseTaskPhase phase) {
  if (!kEmitDatabaseTaskPhases) {
    return;
  }
  std::fprintf(stderr, "%s%s\n", kPhasePrefix, DatabaseTaskPhaseName(phase));
  std::fflush(stderr);
}

void EmitLevelDBWritePreDBImplConstructionPhase() {
  EmitDatabaseTaskPhase(
      DatabaseTaskPhase::kLevelDBWritePreDBImplConstruction);
}

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_ABORT_PC_DIAGNOSTIC)
std::optional<DatabaseTaskPhase> FatalLogSourcePhase(const char* file,
                                                      int line) {
  const std::string_view source(file ? file : "");
  // Wasm CHECK/DCHECK locations can arrive as source-root-relative paths.
  // Keep the original build-relative spellings as explicit aliases for direct
  // diagnostic callers; both paths map to the same fixed, redacted phase.
  if ((source == "base/time/time_wasm.cc" ||
       source == "../../base/time/time_wasm.cc") &&
      (line == 44 || line == 50)) {
    return DatabaseTaskPhase::kLevelDBWriteLoggerFatalSourceWasmTime;
  }
  if ((source == "base/i18n/time_formatting.cc" ||
       source == "../../base/i18n/time_formatting.cc") &&
      (line == 74 || line == 76 || line == 81)) {
    return DatabaseTaskPhase::kLevelDBWriteLoggerFatalSourceTimeFormatting;
  }
  if ((source == "third_party/leveldatabase/env_chromium.cc" ||
       source == "../../third_party/leveldatabase/env_chromium.cc") &&
      (line == 355 || line == 1340)) {
    return DatabaseTaskPhase::kLevelDBWriteLoggerFatalSourceLevelDB;
  }
  if (((source == "base/files/file.cc" ||
        source == "../../base/files/file.cc") &&
       (line == 46 || line == 53)) ||
      ((source == "base/files/file_posix.cc" ||
        source == "../../base/files/file_posix.cc") &&
       line == 439)) {
    return DatabaseTaskPhase::kLevelDBWriteLoggerFatalSourceBaseFile;
  }
  return std::nullopt;
}
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_ABORT_PC_DIAGNOSTIC)

// The Env and any Logger it hands to LevelDB share this small state. The
// Logger can remain owned by DBImpl until DB destruction, so retaining the
// state independently prevents a logger callback from referring to the Env
// object after that object has gone away.
class DatabaseOpenDiagnosticPhaseState final {
 public:
  explicit DatabaseOpenDiagnosticPhaseState(
      base::PlatformThreadId owner_thread_id)
      : owner_thread_id_(owner_thread_id) {}

  DatabaseOpenDiagnosticPhaseState(const DatabaseOpenDiagnosticPhaseState&) =
      delete;
  DatabaseOpenDiagnosticPhaseState& operator=(
      const DatabaseOpenDiagnosticPhaseState&) = delete;

  void DisableOwnerPhaseEmission() {
    DCHECK_EQ(owner_thread_id_, base::PlatformThread::CurrentId());
    owner_phase_emission_enabled_.store(false, std::memory_order_relaxed);
  }

  bool IsOwnerPhaseEmissionEnabled() const {
    return base::PlatformThread::CurrentId() == owner_thread_id_ &&
           owner_phase_emission_enabled_.load(std::memory_order_relaxed);
  }

  bool TryClaimFirstOwnerLoggerLogvPhase() {
    // Check the owner and active interval before consuming the one-shot
    // diagnostic. A background Logger::Logv() must neither emit nor consume
    // the owner-thread checkpoint.
    if (!IsOwnerPhaseEmissionEnabled()) {
      return false;
    }
    bool expected = false;
    return owner_logger_logv_phase_claimed_.compare_exchange_strong(
        expected, true, std::memory_order_relaxed);
  }

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_ABORT_PC_DIAGNOSTIC)
  void ObserveOwnerFatalLogSource(const char* file, int line) {
    if (!IsOwnerPhaseEmissionEnabled()) {
      return;
    }
    const std::optional<DatabaseTaskPhase> phase =
        FatalLogSourcePhase(file, line);
    if (!phase) {
      return;
    }
    bool expected = false;
    if (owner_fatal_log_source_phase_claimed_.compare_exchange_strong(
            expected, true, std::memory_order_relaxed)) {
      EmitDatabaseTaskPhase(*phase);
    }
  }
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_ABORT_PC_DIAGNOSTIC)

 private:
  const base::PlatformThreadId owner_thread_id_;
  std::atomic<bool> owner_phase_emission_enabled_{true};
  std::atomic<bool> owner_logger_logv_phase_claimed_{false};
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_ABORT_PC_DIAGNOSTIC)
  std::atomic<bool> owner_fatal_log_source_phase_claimed_{false};
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_ABORT_PC_DIAGNOSTIC)
};

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_ABORT_PC_DIAGNOSTIC)
// This context is thread-local because the logging API observes every Chrome
// thread while the M7 diagnostic must attribute only its owner-thread Logv.
// It is set solely around the unchanged underlying Logger::Logv call.
thread_local DatabaseOpenDiagnosticPhaseState*
    g_database_open_diagnostic_logv_phase_state = nullptr;

bool ObserveDatabaseOpenDiagnosticFatalLog(int severity,
                                           const char* file,
                                           int line,
                                           size_t /*message_start*/,
                                           const std::string& /*message*/) {
  DatabaseOpenDiagnosticPhaseState* const phase_state =
      g_database_open_diagnostic_logv_phase_state;
  if (phase_state && severity == logging::LOGGING_FATAL) {
    // The source path and message are never retained or formatted. The state
    // compares only fixed file/line pairs and can emit only a fixed enum.
    phase_state->ObserveOwnerFatalLogSource(file, line);
  }
  // Preserve Chromium's normal stderr destinations and fatal crash behavior.
  return false;
}

class ScopedDatabaseOpenDiagnosticFatalLogObserver final {
 public:
  explicit ScopedDatabaseOpenDiagnosticFatalLogObserver(
      DatabaseOpenDiagnosticPhaseState* phase_state)
      : previous_phase_state_(g_database_open_diagnostic_logv_phase_state) {
    DCHECK(phase_state);
    g_database_open_diagnostic_logv_phase_state = phase_state;

    // Do not replace an existing observer. This diagnostic is optional; an
    // occupied logging hook is represented by the existing ambiguous result
    // rather than changing another component's logging semantics.
    installed_handler_ = logging::TrySetLogMessageHandlerIfNone(
        &ObserveDatabaseOpenDiagnosticFatalLog);
  }

  ScopedDatabaseOpenDiagnosticFatalLogObserver(
      const ScopedDatabaseOpenDiagnosticFatalLogObserver&) = delete;
  ScopedDatabaseOpenDiagnosticFatalLogObserver& operator=(
      const ScopedDatabaseOpenDiagnosticFatalLogObserver&) = delete;

  ~ScopedDatabaseOpenDiagnosticFatalLogObserver() {
    if (installed_handler_) {
      logging::ClearLogMessageHandlerIfEqual(
          &ObserveDatabaseOpenDiagnosticFatalLog);
    }
    g_database_open_diagnostic_logv_phase_state = previous_phase_state_;
  }

 private:
  DatabaseOpenDiagnosticPhaseState* const previous_phase_state_;
  bool installed_handler_ = false;
};
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_ABORT_PC_DIAGNOSTIC)

// This transparent Logger owns the Logger returned by the wrapped Env. It
// observes only the first active owner-thread Logv() call and forwards the
// format and va_list untouched.
class DatabaseOpenDiagnosticLogger final : public leveldb::Logger {
 public:
  DatabaseOpenDiagnosticLogger(
      std::unique_ptr<leveldb::Logger> target_logger,
      std::shared_ptr<DatabaseOpenDiagnosticPhaseState> phase_state)
      : target_logger_(std::move(target_logger)),
        phase_state_(std::move(phase_state)) {
    DCHECK(target_logger_);
    DCHECK(phase_state_);
  }

  DatabaseOpenDiagnosticLogger(const DatabaseOpenDiagnosticLogger&) = delete;
  DatabaseOpenDiagnosticLogger& operator=(
      const DatabaseOpenDiagnosticLogger&) = delete;
  ~DatabaseOpenDiagnosticLogger() override = default;

  void Logv(const char* format, va_list arguments) override {
    const bool emit_owner_phase =
        phase_state_->TryClaimFirstOwnerLoggerLogvPhase();
    if (emit_owner_phase) {
      EmitDatabaseTaskPhase(
          DatabaseTaskPhase::kLevelDBWriteLoggerLogvFirstPre);
    }
    const auto forward_logv = [&] {
      target_logger_->Logv(format, arguments);
    };
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_ABORT_PC_DIAGNOSTIC)
    if (emit_owner_phase) {
      ScopedDatabaseOpenDiagnosticFatalLogObserver fatal_log_observer(
          phase_state_.get());
      forward_logv();
    } else {
      forward_logv();
    }
#else
    forward_logv();
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_ABORT_PC_DIAGNOSTIC)
    if (emit_owner_phase) {
      EmitDatabaseTaskPhase(
          DatabaseTaskPhase::kLevelDBWriteLoggerLogvFirstPost);
    }
  }

 private:
  const std::unique_ptr<leveldb::Logger> target_logger_;
  const std::shared_ptr<DatabaseOpenDiagnosticPhaseState> phase_state_;
};

// This target-only wrapper emits fixed diagnostic phases for the actual Env
// calls made by one WriteLevelDBToken() OpenDB. It does not pre-call an
// operation, change its result, or constitute a database-success signal.
class DatabaseOpenDiagnosticEnv final : public leveldb::EnvWrapper {
 public:
  DatabaseOpenDiagnosticEnv(leveldb::Env* target,
                            base::PlatformThreadId owner_thread_id)
      : EnvWrapper(target),
        phase_state_(std::make_shared<DatabaseOpenDiagnosticPhaseState>(
            owner_thread_id)) {}

  DatabaseOpenDiagnosticEnv(const DatabaseOpenDiagnosticEnv&) = delete;
  DatabaseOpenDiagnosticEnv& operator=(const DatabaseOpenDiagnosticEnv&) =
      delete;

  void DisableOwnerPhaseEmission() {
    phase_state_->DisableOwnerPhaseEmission();
  }

  bool FileExists(const std::string& filename) override {
    // The pinned write-open flow uses its first two owner-thread calls for
    // distinct OpenDB checkpoints. Keep the protocol ordinal-only so it never
    // carries the consulted filename, a result, or an inferred filesystem
    // state. All subsequent owner-thread calls use one bounded fallback pair.
    FileExistsPhasePair phases = {
        DatabaseTaskPhase::kLevelDBWriteEnvFileExistsLaterPre,
        DatabaseTaskPhase::kLevelDBWriteEnvFileExistsLaterPost,
    };
    const bool emit_owner_phase = IsOwnerPhaseEmissionEnabled();
    if (emit_owner_phase) {
      phases = NextOwnerFileExistsPhases();
      EmitDatabaseTaskPhase(phases.pre);
    }
    const bool exists = leveldb::EnvWrapper::FileExists(filename);
    if (emit_owner_phase) {
      EmitDatabaseTaskPhase(phases.post);
    }
    return exists;
  }

  leveldb::Status CreateDir(const std::string& directory) override {
    EmitOwnerPhase(DatabaseTaskPhase::kLevelDBWriteEnvCreateDir);
    return leveldb::EnvWrapper::CreateDir(directory);
  }

  leveldb::Status RenameFile(const std::string& source,
                             const std::string& target) override {
    EmitOwnerPhase(DatabaseTaskPhase::kLevelDBWriteEnvRenameFile);
    return leveldb::EnvWrapper::RenameFile(source, target);
  }

  leveldb::Status NewLogger(const std::string& filename,
                            leveldb::Logger** result) override {
    EmitOwnerPhase(DatabaseTaskPhase::kLevelDBWriteEnvNewLogger);
    leveldb::Status status = leveldb::EnvWrapper::NewLogger(filename, result);
    if (status.ok() && result && *result) {
      *result = new DatabaseOpenDiagnosticLogger(
          std::unique_ptr<leveldb::Logger>(*result), phase_state_);
    }
    return status;
  }

  leveldb::Status LockFile(const std::string& filename,
                           leveldb::FileLock** lock) override {
    EmitOwnerPhase(DatabaseTaskPhase::kLevelDBWriteEnvLockFile);
    return leveldb::EnvWrapper::LockFile(filename, lock);
  }

  leveldb::Status NewWritableFile(const std::string& filename,
                                  leveldb::WritableFile** result) override {
    EmitOwnerPhase(DatabaseTaskPhase::kLevelDBWriteEnvNewWritableFile);
    return leveldb::EnvWrapper::NewWritableFile(filename, result);
  }

 private:
  struct FileExistsPhasePair {
    DatabaseTaskPhase pre;
    DatabaseTaskPhase post;
  };

  bool IsOwnerPhaseEmissionEnabled() const {
    return phase_state_->IsOwnerPhaseEmissionEnabled();
  }

  FileExistsPhasePair NextOwnerFileExistsPhases() {
    DCHECK(IsOwnerPhaseEmissionEnabled());
    // Only the owner thread reaches this helper. Saturate after the two
    // diagnostic ordinals so later calls cannot grow the fixed phase set.
    switch (owner_file_exists_ordinal_) {
      case 0:
        owner_file_exists_ordinal_ = 1;
        return {
            DatabaseTaskPhase::kLevelDBWriteEnvFileExistsFirstPre,
            DatabaseTaskPhase::kLevelDBWriteEnvFileExistsFirstPost,
        };
      case 1:
        owner_file_exists_ordinal_ = 2;
        return {
            DatabaseTaskPhase::kLevelDBWriteEnvFileExistsSecondPre,
            DatabaseTaskPhase::kLevelDBWriteEnvFileExistsSecondPost,
        };
      default:
        return {
            DatabaseTaskPhase::kLevelDBWriteEnvFileExistsLaterPre,
            DatabaseTaskPhase::kLevelDBWriteEnvFileExistsLaterPost,
        };
    }
  }

  void EmitOwnerPhase(DatabaseTaskPhase phase) {
    // Background compaction can call this Env concurrently. Those calls are
    // outside this active diagnostic interval and must not emit host phases.
    if (!IsOwnerPhaseEmissionEnabled()) {
      return;
    }
    EmitDatabaseTaskPhase(phase);
  }

  const std::shared_ptr<DatabaseOpenDiagnosticPhaseState> phase_state_;
  // Accessed only after IsOwnerPhaseEmissionEnabled() verifies the owner.
  size_t owner_file_exists_ordinal_ = 0;
};

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)
// This state belongs to exactly one diagnostic OpenDB and every WritableFile
// that it created. It deliberately admits only the synchronous Put owner's
// active .log file: a background maintenance Sync cannot move the requested
// interruption point past Put's return boundary.
class DatabaseWriteInterruptionState final {
 public:
  explicit DatabaseWriteInterruptionState(base::PlatformThreadId owner_thread)
      : owner_thread_(owner_thread) {}

  DatabaseWriteInterruptionState(const DatabaseWriteInterruptionState&) =
      delete;
  DatabaseWriteInterruptionState& operator=(
      const DatabaseWriteInterruptionState&) = delete;

  void ArmForSyncPut() {
    DCHECK_EQ(owner_thread_, base::PlatformThread::CurrentId());
    DCHECK(!abort_claimed_.load(std::memory_order_relaxed));
    armed_.store(true, std::memory_order_release);
  }

  void DisarmAfterSyncPut() {
    DCHECK_EQ(owner_thread_, base::PlatformThread::CurrentId());
    armed_.store(false, std::memory_order_release);
  }

  bool TryClaimFirstSuccessfulLogSync(bool is_log_file) {
    if (!is_log_file ||
        base::PlatformThread::CurrentId() != owner_thread_ ||
        !armed_.load(std::memory_order_acquire)) {
      return false;
    }
    bool expected = false;
    return abort_claimed_.compare_exchange_strong(
        expected, true, std::memory_order_acq_rel);
  }

 private:
  const base::PlatformThreadId owner_thread_;
  std::atomic<bool> armed_{false};
  std::atomic<bool> abort_claimed_{false};
};

bool IsLevelDBLogFile(const std::string& filename) {
  // The filename remains entirely inside this process. The only external
  // consequence is the fixed phase below after a real, successful Sync.
  return base::FilePath::FromUTF8Unsafe(filename).Extension() ==
         FILE_PATH_LITERAL(".log");
}

class DatabaseWriteInterruptionWritableFile final
    : public leveldb::WritableFile {
 public:
  DatabaseWriteInterruptionWritableFile(
      std::unique_ptr<leveldb::WritableFile> target_file,
      std::shared_ptr<DatabaseWriteInterruptionState> state,
      bool is_log_file)
      : target_file_(std::move(target_file)),
        state_(std::move(state)),
        is_log_file_(is_log_file) {
    DCHECK(target_file_);
    DCHECK(state_);
  }

  DatabaseWriteInterruptionWritableFile(
      const DatabaseWriteInterruptionWritableFile&) = delete;
  DatabaseWriteInterruptionWritableFile& operator=(
      const DatabaseWriteInterruptionWritableFile&) = delete;
  ~DatabaseWriteInterruptionWritableFile() override = default;

  leveldb::Status Append(const leveldb::Slice& data) override {
    return target_file_->Append(data);
  }

  leveldb::Status Close() override { return target_file_->Close(); }

  leveldb::Status Flush() override { return target_file_->Flush(); }

  leveldb::Status Sync() override {
    // Forward first. This diagnostic never fabricates a successful Sync and
    // never uses a pre-call as a stand-in for LevelDB's real durability path.
    leveldb::Status status = target_file_->Sync();
    if (status.ok() && state_->TryClaimFirstSuccessfulLogSync(is_log_file_)) {
      EmitDatabaseTaskPhase(
          DatabaseTaskPhase::kLevelDBWriteLogSyncReturned);
      // Intentionally terminate in native code before the synchronous Put can
      // return. The dedicated build has no Emscripten live-runtime exit path.
      std::abort();
    }
    return status;
  }

 private:
  const std::unique_ptr<leveldb::WritableFile> target_file_;
  const std::shared_ptr<DatabaseWriteInterruptionState> state_;
  const bool is_log_file_;
};

// This Env exists only for the distinct write-interruption artifact. It
// forwards both creation variants because a reused active log can be opened
// appendably while a replacement active log is created writable. Every
// non-log file is still transparently forwarded by the same wrapper.
class DatabaseWriteInterruptionEnv final : public leveldb::EnvWrapper {
 public:
  DatabaseWriteInterruptionEnv(leveldb::Env* target,
                               base::PlatformThreadId owner_thread)
      : EnvWrapper(target),
        state_(std::make_shared<DatabaseWriteInterruptionState>(owner_thread)) {}

  DatabaseWriteInterruptionEnv(const DatabaseWriteInterruptionEnv&) = delete;
  DatabaseWriteInterruptionEnv& operator=(
      const DatabaseWriteInterruptionEnv&) = delete;

  void ArmForSyncPut() { state_->ArmForSyncPut(); }

  void DisarmAfterSyncPut() { state_->DisarmAfterSyncPut(); }

  leveldb::Status NewWritableFile(const std::string& filename,
                                  leveldb::WritableFile** result) override {
    return ForwardAndWrapWritableFile(
        filename, result, [&] {
          return leveldb::EnvWrapper::NewWritableFile(filename, result);
        });
  }

  leveldb::Status NewAppendableFile(const std::string& filename,
                                    leveldb::WritableFile** result) override {
    return ForwardAndWrapWritableFile(
        filename, result, [&] {
          return leveldb::EnvWrapper::NewAppendableFile(filename, result);
        });
  }

 private:
  template <typename OpenTargetFile>
  leveldb::Status ForwardAndWrapWritableFile(const std::string& filename,
                                             leveldb::WritableFile** result,
                                             OpenTargetFile open_target_file) {
    leveldb::Status status = open_target_file();
    if (!status.ok() || !result || !*result) {
      return status;
    }
    std::unique_ptr<leveldb::WritableFile> target_file(*result);
    *result = new DatabaseWriteInterruptionWritableFile(
        std::move(target_file), state_, IsLevelDBLogFile(filename));
    return status;
  }

  const std::shared_ptr<DatabaseWriteInterruptionState> state_;
};
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC) || defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)

struct DatabaseTaskInput {
  DatabaseTaskInput(base::FilePath profile_path,
                    SmokeMode mode,
                    std::string token_a,
                    std::string token_b,
                    leveldb_env::Options leveldb_options)
      : profile_path(std::move(profile_path)),
        mode(mode),
        token_a(std::move(token_a)),
        token_b(std::move(token_b)),
        leveldb_options(std::move(leveldb_options)) {}
  DatabaseTaskInput(const DatabaseTaskInput&) = delete;
  DatabaseTaskInput& operator=(const DatabaseTaskInput&) = delete;
  DatabaseTaskInput(DatabaseTaskInput&&) = default;
  DatabaseTaskInput& operator=(DatabaseTaskInput&&) = default;
  ~DatabaseTaskInput() { ClearRawTokens(); }

  void ClearRawTokens() {
    token_a.clear();
    token_b.clear();
  }

  base::FilePath profile_path;
  SmokeMode mode;
  std::string token_a;
  std::string token_b;
  // Constructed on the UI/main sequence before this task input moves to its
  // background runner. The worker only reuses this immutable configuration.
  leveldb_env::Options leveldb_options;
};

bool IsOpaqueToken(std::string_view value) {
  if (value.size() != kOpaqueTokenLength) {
    return false;
  }
  for (const char character : value) {
    if (!((character >= '0' && character <= '9') ||
          (character >= 'a' && character <= 'f'))) {
      return false;
    }
  }
  return true;
}

std::string DigestToken(std::string_view token) {
  return base::HexEncodeLower(crypto::hash::Sha256(token));
}

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
void EmitDatabaseDigestMarker(const char* marker, std::string_view digest) {
  std::fprintf(stderr, "%s%s sha256=%.*s\n", kMarkerPrefix, marker,
               static_cast<int>(digest.size()), digest.data());
  std::fflush(stderr);
}
#endif  // source-selected recovery or write-interruption artifact.

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
enum class PostSyncObservation {
  kA,
  kB,
  kMissing,
  kOther,
  kOpenFailed,
};

const char* PostSyncObservationName(PostSyncObservation observation) {
  switch (observation) {
    case PostSyncObservation::kA:
      return "a";
    case PostSyncObservation::kB:
      return "b";
    case PostSyncObservation::kMissing:
      return "missing";
    case PostSyncObservation::kOther:
      return "other";
    case PostSyncObservation::kOpenFailed:
      return "open-failed";
  }
  return "other";
}

void EmitPostSyncObservation(PostSyncObservation observation) {
  // This intentionally reports only one fixed category. It never formats a
  // LevelDB status, pathname, stored token, or derived database metadata.
  std::fprintf(stderr, "%sLEVELDB_POST_SYNC_OBSERVATION outcome=%s\n",
               kMarkerPrefix, PostSyncObservationName(observation));
  std::fflush(stderr);
}

void EmitPostSyncSqliteReopenIntegrity() {
  // Keep this separate from the LevelDB value classification. It witnesses
  // only a fresh SQLite close/reopen plus FullIntegrityCheck for the existing
  // A value, never a path, token, SQLite error, or interruption-recovery
  // result.
  std::fprintf(stderr, "%sSQLITE_POST_SYNC_REOPEN_INTEGRITY_OK\n",
               kMarkerPrefix);
  std::fflush(stderr);
}
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)

sql::DatabaseOptions DatabaseOptionsForSmoke() {
  sql::DatabaseOptions options;
  // This deliberately exercises SQLite's normal advisory locking path. The
  // test does not use exclusive locking or WAL as a way to bypass it. Keep
  // mmap disabled and SQLite's normal sync behavior enabled. Individual
  // source-selected artifacts may add a controlled interruption boundary, but
  // these options themselves never claim a physical crash-recovery model.
  options.set_exclusive_locking(false)
      .set_wal_mode(false)
      .set_mmap_enabled(false)
      .set_no_sync(false);
  return options;
}

bool HasHealthySQLiteIntegrity(sql::Database* database) {
  if (!database->CheckpointDatabase(true)) {
    return false;
  }
  std::vector<std::string> messages;
  return database->FullIntegrityCheck(&messages) && messages.size() == 1 &&
         messages[0] == "ok";
}

bool WriteSqliteToken(const base::FilePath& database_path,
                      std::string_view token) {
  sql::Database database(DatabaseOptionsForSmoke(),
                         sql::Database::Tag("Test"));
  // Database error text can include filesystem details. The outer protocol
  // reports only its fixed database stage, so consume SQL's callback locally.
  database.set_error_callback(base::DoNothing());
  bool success = false;
  if (database.Open(database_path) &&
      database.Execute(
          "CREATE TABLE IF NOT EXISTS m7_profile_database_smoke "
          "(key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL)")) {
    {
      sql::Transaction transaction(&database);
      if (transaction.Begin()) {
        {
          sql::Statement statement(database.GetUniqueStatement(
              "INSERT OR REPLACE INTO m7_profile_database_smoke (key, value) "
              "VALUES (?, ?)"));
          if (statement.is_valid()) {
            statement.BindString(0, kDatabaseKey);
            statement.BindString(1, token);
            success = statement.Run() && transaction.Commit();
          }
        }
      }
    }
    // All statement and transaction objects must be gone before either the
    // integrity pass or Close(): sql::Database DCHECKs that no statements
    // remain registered when it closes.
    if (success) {
      success = HasHealthySQLiteIntegrity(&database);
    }
  }
  database.Close();
  return success;
}

bool ReadSqliteToken(const base::FilePath& database_path,
                     std::string_view expected_token) {
  sql::Database database(DatabaseOptionsForSmoke(),
                         sql::Database::Tag("Test"));
  database.set_error_callback(base::DoNothing());
  bool success = false;
  if (database.Open(database_path)) {
    {
      sql::Statement statement(database.GetUniqueStatement(
          "SELECT value FROM m7_profile_database_smoke WHERE key = ?"));
      if (statement.is_valid()) {
        statement.BindString(0, kDatabaseKey);
        const bool read_expected_value =
            statement.Step() &&
            std::string_view(statement.ColumnString(0)) == expected_token;
        const bool exactly_one_value =
            !statement.Step() && statement.Succeeded();
        success = read_expected_value && exactly_one_value;
      }
    }
    // Destroy the query statement before the integrity query and Close().
    if (success) {
      success = HasHealthySQLiteIntegrity(&database);
    }
  }
  database.Close();
  return success;
}

bool WriteSqliteTokenAndVerifyAfterClose(const base::FilePath& database_path,
                                         std::string_view token) {
  // WriteSqliteToken() closes and destroys its Database before this independent
  // reopen verifies both the stored value and SQLite's full integrity result.
  return WriteSqliteToken(database_path, token) &&
         ReadSqliteToken(database_path, token);
}

bool ReadSqliteTokenAndVerifyAfterClose(const base::FilePath& database_path,
                                        std::string_view token) {
  // The first read proves cross-module reopening; the second is a separate
  // close/reopen witness within this module.
  return ReadSqliteToken(database_path, token) &&
         ReadSqliteToken(database_path, token);
}

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
bool ReadSqliteRecoveryTextPragma(sql::Database* database,
                                  base::cstring_view pragma,
                                  std::string_view expected_value) {
  sql::Statement statement(database->GetUniqueStatement(pragma));
  return statement.is_valid() && statement.Step() &&
         std::string_view(statement.ColumnString(0)) == expected_value &&
         !statement.Step() && statement.Succeeded();
}

bool ReadSqliteRecoveryIntegerPragma(sql::Database* database,
                                     base::cstring_view pragma,
                                     int64_t expected_value) {
  sql::Statement statement(database->GetUniqueStatement(pragma));
  return statement.is_valid() && statement.Step() &&
         statement.ColumnInt64(0) == expected_value && !statement.Step() &&
         statement.Succeeded();
}

bool HasSqliteRollbackJournalRecoverySettings(sql::Database* database) {
  // Query the live connection selected for the controlled commit. This locks
  // in normal advisory locking, a truncate rollback journal, and no mmap;
  // the DatabaseOptions also retain SQLite's default FULL sync setting.
  return database->Execute("PRAGMA busy_timeout=0") &&
         ReadSqliteRecoveryTextPragma(database, "PRAGMA locking_mode",
                                      "normal") &&
         ReadSqliteRecoveryTextPragma(database, "PRAGMA journal_mode",
                                      "truncate") &&
         ReadSqliteRecoveryIntegerPragma(database, "PRAGMA mmap_size", 0) &&
         ReadSqliteRecoveryIntegerPragma(database, "PRAGMA synchronous", 2);
}

enum class RecoveredSqliteValue {
  kA,
  kB,
};

std::optional<RecoveredSqliteValue> ReadRecoveredSqliteValueOnce(
    const base::FilePath& database_path,
    std::string_view token_a,
    std::string_view token_b) {
  // A recovery verifier must never create a replacement file. The prior
  // interrupted document is required to leave the actual V4-backed SQLite
  // database available to this fresh module.
  if (!base::PathExists(database_path)) {
    return std::nullopt;
  }

  sql::Database database(DatabaseOptionsForSmoke(),
                         sql::Database::Tag("Test"));
  database.set_error_callback(base::DoNothing());
  std::optional<RecoveredSqliteValue> result;
  if (database.Open(database_path)) {
    {
      sql::Statement statement(database.GetUniqueStatement(
          "SELECT value FROM m7_profile_database_smoke WHERE key = ?"));
      if (statement.is_valid()) {
        statement.BindString(0, kDatabaseKey);
        if (statement.Step()) {
          const std::string value = statement.ColumnString(0);
          if (value == token_a) {
            result = RecoveredSqliteValue::kA;
          } else if (value == token_b) {
            result = RecoveredSqliteValue::kB;
          }
          if (result && (statement.Step() || !statement.Succeeded())) {
            result.reset();
          }
        }
      }
    }
    // The statement is destroyed before FullIntegrityCheck() and Close().
    if (result && !HasHealthySQLiteIntegrity(&database)) {
      result.reset();
    }
  }
  // Explicit close gives the next verifier a separate SQLite connection and
  // lets its recovery protocol own any rollback-journal cleanup.
  database.Close();
  return result;
}

std::optional<RecoveredSqliteValue> ReadRecoveredSqliteValueTwice(
    const base::FilePath& database_path,
    std::string_view token_a,
    std::string_view token_b) {
  const std::optional<RecoveredSqliteValue> first =
      ReadRecoveredSqliteValueOnce(database_path, token_a, token_b);
  if (!first) {
    return std::nullopt;
  }
  const std::optional<RecoveredSqliteValue> second =
      ReadRecoveredSqliteValueOnce(database_path, token_a, token_b);
  if (!second || *second != *first) {
    return std::nullopt;
  }
  return first;
}

void EmitSqliteWriteMainDbSyncReturned() {
  EmitDatabaseTaskPhase(DatabaseTaskPhase::kSQLiteWriteMainDbSyncReturned);
}

bool InterruptSqliteWriteAfterMainDbSync(const base::FilePath& database_path,
                                         std::string_view token_b) {
  // This private VFS is registered only on the database task's one MayBlock
  // runner and selected only for this one existing SQLite connection. It is
  // not SQLite's default VFS, so neither normal Chrome nor the recovery
  // verifier can consume its controlled abort.
  ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs interruption_vfs(
      base::PlatformThread::CurrentId(), &EmitSqliteWriteMainDbSyncReturned);
  sql::DatabaseOptions options = DatabaseOptionsForSmoke();
  options.set_vfs_name_discouraged(interruption_vfs.name());
  sql::Database database(options, sql::Database::Tag("Test"));
  database.set_error_callback(base::DoNothing());
  if (!database.Open(database_path) ||
      !HasSqliteRollbackJournalRecoverySettings(&database)) {
    database.Close();
    return false;
  }

  {
    sql::Transaction transaction(&database);
    if (transaction.Begin()) {
      sql::Statement statement(database.GetUniqueStatement(
          "INSERT OR REPLACE INTO m7_profile_database_smoke (key, value) "
          "VALUES (?, ?)"));
      if (statement.is_valid()) {
        statement.BindString(0, kDatabaseKey);
        statement.BindString(1, token_b);
        if (statement.Run()) {
          // Keep the VFS unarmed through Open(), journal setup, and the B
          // statement. The next call is the real sql::Transaction commit
          // boundary whose main-database xSync must forward before aborting.
          interruption_vfs.ArmForCommit();
          // This is emitted only after the VFS is armed. Emitting a fixed
          // stderr marker does not make a SQLite call, so no Sync can occur
          // between arming and Transaction::Commit().
          EmitDatabaseDigestMarker("SQLITE_ROLLBACK_JOURNAL_COMMIT_B_ARMED",
                                   DigestToken(token_b));
          const bool commit_returned = transaction.Commit();
          interruption_vfs.DisarmAfterCommit();
          // The intended VFS callback aborts before Commit() can return,
          // whether or not SQLite would otherwise report success. Never turn
          // an unexpected return into a clean B write or recovery result.
          if (commit_returned) {
            return false;
          }
        }
      }
    }
  }
  database.Close();
  return false;
}

bool IsSqliteRecoveryMode(SmokeMode mode) {
  return mode == SmokeMode::kInterruptSqliteWriteB ||
         mode == SmokeMode::kRecoverSqliteWriteB;
}
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_LOCK_TEST)
bool ReadSqliteTextPragma(sql::Database* database,
                           base::cstring_view pragma,
                           std::string_view expected_value) {
  sql::Statement statement(database->GetUniqueStatement(pragma));
  return statement.is_valid() && statement.Step() &&
         std::string_view(statement.ColumnString(0)) == expected_value &&
         !statement.Step() && statement.Succeeded();
}

bool ReadSqliteIntegerPragma(sql::Database* database,
                              base::cstring_view pragma,
                              int64_t expected_value) {
  sql::Statement statement(database->GetUniqueStatement(pragma));
  return statement.is_valid() && statement.Step() &&
         statement.ColumnInt64(0) == expected_value && !statement.Step() &&
         statement.Succeeded();
}

bool HasSqliteLockContentionSettings(sql::Database* database) {
  // The sql::Database open options configure normal rollback-journal
  // locking. Query the live connection before it enters the holder
  // transaction, and explicitly clear SQLite's busy handler so the contender
  // must report an immediate lock result instead of waiting.
  return database->Execute("PRAGMA busy_timeout=0") &&
         ReadSqliteTextPragma(database, "PRAGMA locking_mode", "normal") &&
         ReadSqliteTextPragma(database, "PRAGMA journal_mode", "truncate") &&
         ReadSqliteIntegerPragma(database, "PRAGMA mmap_size", 0);
}

bool WriteSqliteTokenOnOpenDatabase(sql::Database* database,
                                    std::string_view token) {
  sql::Statement statement(database->GetUniqueStatement(
      "INSERT OR REPLACE INTO m7_profile_database_smoke (key, value) "
      "VALUES (?, ?)"));
  if (!statement.is_valid()) {
    return false;
  }
  statement.BindString(0, kDatabaseKey);
  statement.BindString(1, token);
  return statement.Run();
}

void RecordSqliteError(std::vector<int>* errors,
                       int error,
                       sql::Statement*) {
  errors->push_back(error);
}

bool WriteSqliteTokensWithContenderAndReopen(
    const base::FilePath& database_path,
    std::string_view token_a,
    std::string_view token_b) {
  // First create and independently close/reopen the ordinary SQLite database.
  // The two contender connections below are both opened against this exact
  // existing V4-backed file before the holder takes its rollback-journal
  // write lock; no path is recreated while either connection exists.
  if (!WriteSqliteTokenAndVerifyAfterClose(database_path, token_a)) {
    return false;
  }

  sql::Database holder(DatabaseOptionsForSmoke(), sql::Database::Tag("Test"));
  sql::Database contender(DatabaseOptionsForSmoke(),
                           sql::Database::Tag("Test"));
  holder.set_error_callback(base::DoNothing());
  std::vector<int> contender_errors;
  contender.set_error_callback(base::BindRepeating(
      &RecordSqliteError, base::Unretained(&contender_errors)));

  bool contender_rejected = false;
  bool holder_committed = false;
  if (holder.Open(database_path) && contender.Open(database_path) &&
      HasSqliteLockContentionSettings(&holder) &&
      HasSqliteLockContentionSettings(&contender)) {
    {
      // Use BEGIN IMMEDIATE rather than Transaction::Begin(), which is
      // deferred. The holder must synchronously own SQLite's normal
      // rollback-journal RESERVED lock before the contender's real B write
      // attempts to acquire it.
      const bool holder_transaction_started = holder.Execute("BEGIN IMMEDIATE");
      if (holder_transaction_started) {
        const bool holder_wrote =
            WriteSqliteTokenOnOpenDatabase(&holder, token_a);
        if (holder_wrote) {
          // Ignore setup diagnostics and require exactly one callback for the
          // deliberate contending B write. This is a real SQLite BUSY result,
          // not acceptance of an arbitrary failed SQL statement.
          contender_errors.clear();
          const bool contender_wrote =
              WriteSqliteTokenOnOpenDatabase(&contender, token_b);
          contender_rejected =
              !contender_wrote && contender_errors.size() == 1 &&
              sql::ToPrimaryErrorCode(static_cast<sql::SqliteErrorCode>(
                  contender_errors.front())) == sql::SqliteErrorCode::kBusy;
          // SQLite's VFS can defer this close while the holder owns a lock.
          // Close the unsuccessful contender before committing the holder to
          // cover that normal connection-lifetime behavior.
          contender.Close();
          if (contender_rejected) {
            holder_committed = holder.Execute("COMMIT");
          }
        }
        if (!holder_committed) {
          std::ignore = holder.Execute("ROLLBACK");
        }
      }
    }
  }
  // The transaction and every statement have been destroyed before either
  // close. This keeps SQLite's own deferred-close handling in charge of the
  // V4-backed file-descriptor lifetime.
  contender.Close();
  holder.Close();

  if (!contender_rejected || !holder_committed) {
    return false;
  }

  // Fresh handles first verify the committed holder value with full integrity,
  // then write and independently reopen B after lock release.
  return ReadSqliteTokenAndVerifyAfterClose(database_path, token_a) &&
         WriteSqliteTokenAndVerifyAfterClose(database_path, token_b);
}
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_LOCK_TEST)

leveldb_env::Options LevelDBOptionsForSmoke() {
  leveldb_env::Options options;
  options.env = leveldb::Env::Default();
  options.create_if_missing = true;
  options.error_if_exists = false;
  options.paranoid_checks = true;
  options.reuse_logs = true;
  return options;
}

bool ReadLevelDBToken(const base::FilePath& database_path,
                      std::string_view expected_token,
                      const leveldb_env::Options& options) {
  std::unique_ptr<leveldb::DB> database;
  EmitDatabaseTaskPhase(DatabaseTaskPhase::kLevelDBReadOpen);
  if (!leveldb_env::OpenDB(options, database_path.AsUTF8Unsafe(), &database)
           .ok() ||
      !database) {
    return false;
  }

  leveldb::ReadOptions read_options;
  read_options.verify_checksums = true;
  std::string value;
  EmitDatabaseTaskPhase(DatabaseTaskPhase::kLevelDBReadGet);
  const bool success =
      database->Get(read_options, kDatabaseKey, &value).ok() &&
      std::string_view(value) == expected_token;
  EmitDatabaseTaskPhase(DatabaseTaskPhase::kLevelDBReadClose);
  database.reset();
  return success;
}

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)
bool ReadExistingLevelDBTokenWithoutPhases(
    const base::FilePath& database_path,
    std::string_view expected_token,
    const leveldb_env::Options& options) {
  // A verifier must not create a replacement database while attempting to
  // establish its fresh-document A witness.
  leveldb_env::Options existing_options = options;
  existing_options.create_if_missing = false;
  existing_options.paranoid_checks = true;
  std::unique_ptr<leveldb::DB> database;
  if (!leveldb_env::OpenDB(existing_options, database_path.AsUTF8Unsafe(),
                           &database)
           .ok() ||
      !database) {
    return false;
  }

  leveldb::ReadOptions read_options;
  read_options.verify_checksums = true;
  std::string value;
  const bool success =
      database->Get(read_options, kDatabaseKey, &value).ok() &&
      std::string_view(value) == expected_token;
  database.reset();
  return success;
}

// Opens its own target-local Env after the fresh A checks have completed. The
// shared state is deliberately unarmed throughout OpenDB, then arms directly
// adjacent to the sync Put. A successful .log Sync never returns here because
// the forwarding WritableFile aborts immediately after it returns OK.
bool InterruptLevelDBWriteAfterLogSync(
    const base::FilePath& database_path,
    std::string_view token_b,
    const leveldb_env::Options& options) {
  DatabaseWriteInterruptionEnv interruption_env(
      options.env, base::PlatformThread::CurrentId());
  leveldb_env::Options interruption_options = options;
  interruption_options.env = &interruption_env;
  interruption_options.create_if_missing = false;
  std::unique_ptr<leveldb::DB> database;
  if (!leveldb_env::OpenDB(interruption_options,
                           database_path.AsUTF8Unsafe(), &database)
           .ok() ||
      !database) {
    return false;
  }

  leveldb::WriteOptions write_options;
  write_options.sync = true;
  const leveldb::Slice token_slice(token_b.data(), token_b.size());
  interruption_env.ArmForSyncPut();
  database->Put(write_options, kDatabaseKey, token_slice);
  interruption_env.DisarmAfterSyncPut();

  // If Put returned, the requested post-Sync interruption was not observed.
  // Do not turn that unexpected path into a database or durability success.
  return false;
}

#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC) || defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
PostSyncObservation ObservePostSyncLevelDBWrite(
    const base::FilePath& database_path,
    std::string_view token_a,
    std::string_view token_b,
    const leveldb_env::Options& options) {
  leveldb_env::Options existing_options = options;
  existing_options.create_if_missing = false;
  std::unique_ptr<leveldb::DB> database;
  if (!leveldb_env::OpenDB(existing_options, database_path.AsUTF8Unsafe(),
                           &database)
           .ok() ||
      !database) {
    return PostSyncObservation::kOpenFailed;
  }

  leveldb::ReadOptions read_options;
  read_options.verify_checksums = true;
  std::string value;
  const leveldb::Status status =
      database->Get(read_options, kDatabaseKey, &value);
  if (status.ok()) {
    if (std::string_view(value) == token_a) {
      return PostSyncObservation::kA;
    }
    if (std::string_view(value) == token_b) {
      return PostSyncObservation::kB;
    }
    return PostSyncObservation::kOther;
  }
  return status.IsNotFound() ? PostSyncObservation::kMissing
                             : PostSyncObservation::kOther;
}

bool IsWriteInterruptionDiagnosticMode(SmokeMode mode) {
  return mode == SmokeMode::kInterruptLevelDBWriteB ||
         mode == SmokeMode::kObserveLevelDBWriteB;
}
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)
enum class RecoveredLevelDBValue {
  kA,
  kB,
};

std::optional<RecoveredLevelDBValue> ReadRecoveredLevelDBValueOnce(
    const base::FilePath& database_path,
    std::string_view token_a,
    std::string_view token_b,
    const leveldb_env::Options& options) {
  // Do not let a verifier create a replacement database. The fresh recovery
  // document must reopen the post-interruption database exactly as it exists.
  leveldb_env::Options existing_options = options;
  existing_options.create_if_missing = false;
  existing_options.paranoid_checks = true;
  std::unique_ptr<leveldb::DB> database;
  if (!leveldb_env::OpenDB(existing_options, database_path.AsUTF8Unsafe(),
                           &database)
           .ok() ||
      !database) {
    return std::nullopt;
  }

  leveldb::ReadOptions read_options;
  read_options.verify_checksums = true;
  std::string value;
  const leveldb::Status status =
      database->Get(read_options, kDatabaseKey, &value);
  std::optional<RecoveredLevelDBValue> result;
  if (status.ok() && std::string_view(value) == token_a) {
    result = RecoveredLevelDBValue::kA;
  } else if (status.ok() && std::string_view(value) == token_b) {
    result = RecoveredLevelDBValue::kB;
  }
  // Explicitly destroy the first owner before a second independent OpenDB.
  database.reset();
  return result;
}

std::optional<RecoveredLevelDBValue> ReadRecoveredLevelDBValueTwice(
    const base::FilePath& database_path,
    std::string_view token_a,
    std::string_view token_b,
    const leveldb_env::Options& options) {
  const std::optional<RecoveredLevelDBValue> first =
      ReadRecoveredLevelDBValueOnce(database_path, token_a, token_b, options);
  if (!first) {
    return std::nullopt;
  }
  const std::optional<RecoveredLevelDBValue> second =
      ReadRecoveredLevelDBValueOnce(database_path, token_a, token_b, options);
  if (!second || *second != *first) {
    return std::nullopt;
  }
  return first;
}

bool IsDatabaseRecoveryMode(SmokeMode mode) {
  return mode == SmokeMode::kInterruptLevelDBWriteB ||
         mode == SmokeMode::kRecoverLevelDBWriteB;
}
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)

bool WriteLevelDBToken(const base::FilePath& database_path,
                       std::string_view token,
                       const leveldb_env::Options& options) {
  // This MayBlock-worker pre-call is diagnostic-only. It materializes
  // DBTracker's lazy memory-dump registration separately from OpenDB; it is
  // not a behavior-equivalent repair or a database-success signal.
  EmitDatabaseTaskPhase(DatabaseTaskPhase::kLevelDBWriteTracker);
  leveldb_env::DBTracker::GetInstance();

  // DBImpl retains the Env pointer through its background work and destruction,
  // so this wrapper must outlive |database|. Its fixed phases observe only the
  // real OpenDB forwarding calls and stop as soon as OpenDB returns.
  DatabaseOpenDiagnosticEnv diagnostic_env(
      options.env, base::PlatformThread::CurrentId());
  leveldb_env::Options diagnostic_options = options;
  diagnostic_options.env = &diagnostic_env;
  std::unique_ptr<leveldb::DB> database;
  EmitDatabaseTaskPhase(DatabaseTaskPhase::kLevelDBWriteOpen);
  const leveldb::Status open_status = leveldb_env::OpenDB(
      diagnostic_options, database_path.AsUTF8Unsafe(), &database,
      &EmitLevelDBWritePreDBImplConstructionPhase);
  diagnostic_env.DisableOwnerPhaseEmission();
  if (!open_status.ok() || !database) {
    return false;
  }

  leveldb::WriteOptions write_options;
  write_options.sync = true;
  const leveldb::Slice token_slice(token.data(), token.size());
  EmitDatabaseTaskPhase(DatabaseTaskPhase::kLevelDBWritePut);
  const bool success =
      database->Put(write_options, kDatabaseKey, token_slice).ok();
  if (success) {
    // Force the bounded normal LevelDB rewrite/rename path before destruction;
    // this is graceful-close/reopen coverage, not a power-loss recovery claim.
    EmitDatabaseTaskPhase(DatabaseTaskPhase::kLevelDBWriteCompact);
    database->CompactRange(nullptr, nullptr);
  }
  EmitDatabaseTaskPhase(DatabaseTaskPhase::kLevelDBWriteClose);
  database.reset();
  return success;
}

bool WriteLevelDBTokenAndVerifyAfterClose(const base::FilePath& database_path,
                                          std::string_view token,
                                          const leveldb_env::Options& options) {
  // WriteLevelDBToken() synchronizes, compacts, and destroys its DB before
  // this independent Chromium Env/OpenDB reopen verifies the raw value.
  return WriteLevelDBToken(database_path, token, options) &&
         ReadLevelDBToken(database_path, token, options);
}

bool ReadLevelDBTokenAndVerifyAfterClose(const base::FilePath& database_path,
                                         std::string_view token,
                                         const leveldb_env::Options& options) {
  return ReadLevelDBToken(database_path, token, options) &&
         ReadLevelDBToken(database_path, token, options);
}

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_LOCK_TEST)
bool WriteLevelDBTokenWithContenderAndReopen(
    const base::FilePath& database_path,
    std::string_view token,
    const leveldb_env::Options& options) {
  // This is Chromium's actual LevelDB lock path: leveldb_env::OpenDB() asks
  // ChromiumEnv to acquire LOCK through storage::FilesystemProxy. The holder
  // and final reopen traverse the V4-backed path; its same-process LockTable
  // rejects the overlapping contender before it reaches the V4 fcntl layer.
  std::unique_ptr<leveldb::DB> holder;
  if (!leveldb_env::OpenDB(options, database_path.AsUTF8Unsafe(), &holder)
           .ok() ||
      !holder) {
    return false;
  }

  leveldb::WriteOptions write_options;
  write_options.sync = true;
  const leveldb::Slice token_slice(token.data(), token.size());
  if (!holder->Put(write_options, kDatabaseKey, token_slice).ok()) {
    holder.reset();
    return false;
  }

  leveldb_env::Options existing_options = options;
  existing_options.create_if_missing = false;
  existing_options.paranoid_checks = true;
  std::unique_ptr<leveldb::DB> contender;
  const leveldb::Status contender_status = leveldb_env::OpenDB(
      existing_options, database_path.AsUTF8Unsafe(), &contender);
  leveldb_env::MethodID contender_method;
  base::File::Error contender_error = base::File::FILE_ERROR_MAX;
  // Do not treat an arbitrary OpenDB failure as lock evidence. ChromiumEnv
  // encodes its FilesystemProxy LockFile failure with this exact method/error
  // pair. The same-process contender is rejected by that lock table before
  // any V4 fcntl operation, so an unrelated OpenDB error cannot pass here.
  const bool contender_rejected =
      !contender_status.ok() && !contender &&
      leveldb_env::ParseMethodAndError(contender_status, &contender_method,
                                       &contender_error) ==
          leveldb_env::METHOD_AND_BFE &&
      contender_method == leveldb_env::kLockFile &&
      contender_error == base::File::FILE_ERROR_IN_USE;
  contender.reset();

  // Destroy the exact holder before the final open. A failed contender alone
  // could be a permanent or unrelated failure; this release/reopen pair is
  // the evidence that the same LevelDB path observed normal lock teardown.
  holder.reset();
  if (!contender_rejected) {
    return false;
  }

  std::unique_ptr<leveldb::DB> reopened;
  if (!leveldb_env::OpenDB(existing_options, database_path.AsUTF8Unsafe(),
                           &reopened)
           .ok() ||
      !reopened) {
    return false;
  }
  leveldb::ReadOptions read_options;
  read_options.verify_checksums = true;
  std::string value;
  const bool success =
      reopened->Get(read_options, kDatabaseKey, &value).ok() &&
      std::string_view(value) == token;
  reopened.reset();
  return success;
}
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_LOCK_TEST)

DatabaseTaskResult RunDatabaseTask(DatabaseTaskInput input) {
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
  const bool emit_task_phases =
      !IsWriteInterruptionDiagnosticMode(input.mode);
  if (emit_task_phases) {
    EmitDatabaseTaskPhase(DatabaseTaskPhase::kTaskStarted);
  }
#elif defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)
  const bool emit_task_phases = !IsDatabaseRecoveryMode(input.mode);
  if (emit_task_phases) {
    EmitDatabaseTaskPhase(DatabaseTaskPhase::kTaskStarted);
  }
#elif defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
  const bool emit_task_phases = !IsSqliteRecoveryMode(input.mode);
  if (emit_task_phases) {
    EmitDatabaseTaskPhase(DatabaseTaskPhase::kTaskStarted);
  }
#elif defined(CHROME_WASM_M7_PROFILE_DATABASE_LOCK_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_LOCK_TEST)
  // The lock artifacts have closed success receipts. Database-task phase
  // telemetry belongs only to the distinct diagnostic artifacts.
#else
  EmitDatabaseTaskPhase(DatabaseTaskPhase::kTaskStarted);
#endif  // M7 diagnostic or lock artifact.
  const base::FilePath sqlite_path =
      input.profile_path.AppendASCII(kSQLiteFilename);
  const base::FilePath leveldb_path =
      input.profile_path.AppendASCII(kLevelDBDirectory);

  bool success = false;
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)
  std::optional<RecoveredLevelDBValue> recovered_leveldb_value;
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
  std::optional<RecoveredSqliteValue> recovered_sqlite_value;
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
  switch (input.mode) {
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_LOCK_TEST)
    case SmokeMode::kLockContention:
      // SQLite remains an independently closed/reopened control for this
      // lock-specific LevelDB acceptance. It is not presented as SQLite lock
      // evidence; only the subsequent real LevelDB holder/contender/reopen is.
      if (WriteSqliteTokenAndVerifyAfterClose(sqlite_path, input.token_a)) {
        success = WriteLevelDBTokenWithContenderAndReopen(
            leveldb_path, input.token_a, input.leveldb_options);
      }
      break;
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_LOCK_TEST)
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_LOCK_TEST)
    case SmokeMode::kSQLiteLockContention:
      success = WriteSqliteTokensWithContenderAndReopen(
          sqlite_path, input.token_a, input.token_b);
      break;
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_LOCK_TEST)
    case SmokeMode::kWriteA:
      EmitDatabaseTaskPhase(DatabaseTaskPhase::kSQLiteWrite);
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
      // The SQLite recovery artifact deliberately seeds only the one SQLite
      // database whose subsequent rollback-journal commit it interrupts.
      success = WriteSqliteTokenAndVerifyAfterClose(sqlite_path, input.token_a);
#else
      if (WriteSqliteTokenAndVerifyAfterClose(sqlite_path, input.token_a)) {
        EmitDatabaseTaskPhase(DatabaseTaskPhase::kLevelDBWrite);
        success = WriteLevelDBTokenAndVerifyAfterClose(
            leveldb_path, input.token_a, input.leveldb_options);
      }
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
      break;
    case SmokeMode::kVerifyAWriteB:
      // Both previous-A checks occur before either B write. All four database
      // phases still execute serially on this one sequenced runner.
      EmitDatabaseTaskPhase(DatabaseTaskPhase::kSQLiteRead);
      if (ReadSqliteToken(sqlite_path, input.token_a)) {
        EmitDatabaseTaskPhase(DatabaseTaskPhase::kLevelDBRead);
        if (ReadLevelDBToken(leveldb_path, input.token_a,
                             input.leveldb_options)) {
          EmitDatabaseTaskPhase(DatabaseTaskPhase::kSQLiteWrite);
          if (WriteSqliteTokenAndVerifyAfterClose(sqlite_path,
                                                  input.token_b)) {
            EmitDatabaseTaskPhase(DatabaseTaskPhase::kLevelDBWrite);
            success = WriteLevelDBTokenAndVerifyAfterClose(
                leveldb_path, input.token_b, input.leveldb_options);
          }
        }
      }
      break;
    case SmokeMode::kVerifyB:
      EmitDatabaseTaskPhase(DatabaseTaskPhase::kSQLiteRead);
      if (ReadSqliteTokenAndVerifyAfterClose(sqlite_path, input.token_b)) {
        EmitDatabaseTaskPhase(DatabaseTaskPhase::kLevelDBRead);
        success = ReadLevelDBTokenAndVerifyAfterClose(
            leveldb_path, input.token_b, input.leveldb_options);
      }
      break;
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)
    case SmokeMode::kInterruptLevelDBWriteB:
      // These read markers must be emitted before the target-local writer is
      // armed: the subsequent native abort intentionally prevents the task
      // reply and ordinary database-completion marker path.
      if (ReadSqliteToken(sqlite_path, input.token_a)) {
        EmitDatabaseDigestMarker("SQLITE_READ_A_OK",
                                 DigestToken(input.token_a));
        if (ReadExistingLevelDBTokenWithoutPhases(
                leveldb_path, input.token_a, input.leveldb_options)) {
          EmitDatabaseDigestMarker("LEVELDB_READ_A_OK",
                                   DigestToken(input.token_a));
          success = InterruptLevelDBWriteAfterLogSync(
              leveldb_path, input.token_b, input.leveldb_options);
        }
      }
      break;
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC) || defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
    case SmokeMode::kInterruptSqliteWriteB:
      // This normal A reopen intentionally precedes private-VFS construction,
      // so sql::Database has installed Chromium's default VFSWrapper before
      // the forwarding VFS snapshots its required pathname capacity. The VFS
      // remains unarmed through open and statement setup, then aborts only
      // after its owner-thread main-database xSync returns SQLITE_OK.
      if (ReadSqliteToken(sqlite_path, input.token_a)) {
        EmitDatabaseDigestMarker("SQLITE_RECOVERY_READ_A_OK",
                                 DigestToken(input.token_a));
        success = InterruptSqliteWriteAfterMainDbSync(sqlite_path,
                                                      input.token_b);
      }
      break;
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
    case SmokeMode::kObserveLevelDBWriteB:
      // Every fixed observation is useful controlled diagnostic output. It is
      // not a B durability claim, so open failure and every value class
      // retain their distinct terminal-marker grammar. Before that grammar is
      // allowed to complete, separately close and reopen the pre-existing
      // SQLite A database and require its normal full-integrity result. This
      // is still an in-module diagnostic, not interruption recovery.
      EmitPostSyncObservation(ObservePostSyncLevelDBWrite(
          leveldb_path, input.token_a, input.token_b, input.leveldb_options));
      if (ReadSqliteTokenAndVerifyAfterClose(sqlite_path, input.token_a)) {
        EmitPostSyncSqliteReopenIntegrity();
        success = true;
      }
      break;
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)
    case SmokeMode::kRecoverLevelDBWriteB:
      // This strictly bounded recovery witness permits only a stable A or B
      // LevelDB value from two independently closed/reopened checksum and
      // paranoid-check handles. SQLite remains the committed A control and
      // must independently pass two full-integrity close/reopen checks.
      recovered_leveldb_value = ReadRecoveredLevelDBValueTwice(
          leveldb_path, input.token_a, input.token_b, input.leveldb_options);
      if (recovered_leveldb_value &&
          ReadSqliteTokenAndVerifyAfterClose(sqlite_path, input.token_a)) {
        success = true;
      }
      break;
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
    case SmokeMode::kRecoverSqliteWriteB:
      // A fresh module must reopen the exact pre-existing SQLite file twice,
      // require a stable A-or-B value, and pass FullIntegrityCheck on both
      // independently closed connections.
      recovered_sqlite_value = ReadRecoveredSqliteValueTwice(
          sqlite_path, input.token_a, input.token_b);
      success = recovered_sqlite_value.has_value();
      break;
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
    case SmokeMode::kNone:
      break;
  }

  input.ClearRawTokens();
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
  if (emit_task_phases) {
    EmitDatabaseTaskPhase(DatabaseTaskPhase::kTaskComplete);
  }
#elif defined(CHROME_WASM_M7_PROFILE_DATABASE_LOCK_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_LOCK_TEST)
  // The lock receipts expose no diagnostic task phases.
#else
  EmitDatabaseTaskPhase(DatabaseTaskPhase::kTaskComplete);
#endif  // M7 diagnostic or lock artifact.
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)
  if (success && recovered_leveldb_value == RecoveredLevelDBValue::kA) {
    return DatabaseTaskResult::kRecoveryA;
  }
  if (success && recovered_leveldb_value == RecoveredLevelDBValue::kB) {
    return DatabaseTaskResult::kRecoveryB;
  }
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
  if (success && recovered_sqlite_value == RecoveredSqliteValue::kA) {
    return DatabaseTaskResult::kRecoveryA;
  }
  if (success && recovered_sqlite_value == RecoveredSqliteValue::kB) {
    return DatabaseTaskResult::kRecoveryB;
  }
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
  return success ? DatabaseTaskResult::kSuccess : DatabaseTaskResult::kFailure;
}

class WasmProfileDatabaseSmokeState {
 public:
  WasmProfileDatabaseSmokeState() = default;
  WasmProfileDatabaseSmokeState(const WasmProfileDatabaseSmokeState&) = delete;
  WasmProfileDatabaseSmokeState& operator=(
      const WasmProfileDatabaseSmokeState&) = delete;
  ~WasmProfileDatabaseSmokeState() = default;

  bool EnableFromCommandLine() {
    if (configured_) {
      return enabled_;
    }
    configured_ = true;

    const base::CommandLine* command_line =
        base::CommandLine::ForCurrentProcess();
    const bool has_mode = command_line->HasSwitch(kSmokeSwitch);
    const bool has_token_a = command_line->HasSwitch(kTokenASwitch);
    const bool has_token_b = command_line->HasSwitch(kTokenBSwitch);
    if (!has_mode) {
      ReportFailure(WasmProfileDatabaseSmokeFailureStage::kArguments);
      return false;
    }

    const std::string mode = command_line->GetSwitchValueASCII(kSmokeSwitch);
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_LOCK_TEST)
    // The separate lock artifact must never silently become a generic
    // graceful-close database executable. Its one mode owns the exact
    // holder/contender/release marker grammar below.
    if (mode != kLockContentionMode) {
      ReportFailure(WasmProfileDatabaseSmokeFailureStage::kArguments);
      return false;
    }
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_LOCK_TEST)
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_LOCK_TEST)
    // The separate SQLite lock artifact must never silently become a generic
    // graceful-close database executable. Its one mode owns the exact
    // two-connection holder/contender/release marker grammar below.
    if (mode != kSQLiteLockContentionMode) {
      ReportFailure(WasmProfileDatabaseSmokeFailureStage::kArguments);
      return false;
    }
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_LOCK_TEST)
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)
    // A recovery artifact cannot be used as a generic graceful-close test.
    // Its source-selected protocol has exactly one seed, one controlled
    // interruption, and one strict fresh-module recovery mode.
    if (mode != kWriteAMode && mode != kInterruptLevelDBWriteBMode &&
        mode != kRecoverLevelDBWriteBMode) {
      ReportFailure(WasmProfileDatabaseSmokeFailureStage::kArguments);
      return false;
    }
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
    // The private-VFS recovery artifact is likewise not a generic database
    // executable. It admits only its seed, native-interruption, and fresh
    // SQLite recovery modes.
    if (mode != kWriteAMode && mode != kInterruptSqliteWriteBMode &&
        mode != kRecoverSqliteWriteBMode) {
      ReportFailure(WasmProfileDatabaseSmokeFailureStage::kArguments);
      return false;
    }
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_LOCK_TEST)
    if (mode == kLockContentionMode) {
      if (!has_token_a || has_token_b) {
        ReportFailure(WasmProfileDatabaseSmokeFailureStage::kArguments);
        return false;
      }
      token_a_ = command_line->GetSwitchValueASCII(kTokenASwitch);
      if (!IsOpaqueToken(token_a_)) {
        ReportFailure(WasmProfileDatabaseSmokeFailureStage::kArguments);
        return false;
      }
      mode_ = SmokeMode::kLockContention;
      token_a_digest_ = DigestToken(token_a_);
      expected_digest_ = token_a_digest_;
    } else if (mode == kWriteAMode) {
#elif defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_LOCK_TEST)
    if (mode == kSQLiteLockContentionMode) {
      if (!has_token_a || !has_token_b) {
        ReportFailure(WasmProfileDatabaseSmokeFailureStage::kArguments);
        return false;
      }
      token_a_ = command_line->GetSwitchValueASCII(kTokenASwitch);
      token_b_ = command_line->GetSwitchValueASCII(kTokenBSwitch);
      if (!IsOpaqueToken(token_a_) || !IsOpaqueToken(token_b_) ||
          token_a_ == token_b_) {
        ReportFailure(WasmProfileDatabaseSmokeFailureStage::kArguments);
        return false;
      }
      mode_ = SmokeMode::kSQLiteLockContention;
      token_a_digest_ = DigestToken(token_a_);
      token_b_digest_ = DigestToken(token_b_);
      expected_digest_ = token_b_digest_;
    } else if (mode == kWriteAMode) {
#else
    if (mode == kWriteAMode) {
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_LOCK_TEST)
      if (!has_token_a || has_token_b) {
        ReportFailure(WasmProfileDatabaseSmokeFailureStage::kArguments);
        return false;
      }
      token_a_ = command_line->GetSwitchValueASCII(kTokenASwitch);
      if (!IsOpaqueToken(token_a_)) {
        ReportFailure(WasmProfileDatabaseSmokeFailureStage::kArguments);
        return false;
      }
      mode_ = SmokeMode::kWriteA;
      token_a_digest_ = DigestToken(token_a_);
      expected_digest_ = token_a_digest_;
    } else if (mode == kVerifyAWriteBMode) {
      if (!has_token_a || !has_token_b) {
        ReportFailure(WasmProfileDatabaseSmokeFailureStage::kArguments);
        return false;
      }
      token_a_ = command_line->GetSwitchValueASCII(kTokenASwitch);
      token_b_ = command_line->GetSwitchValueASCII(kTokenBSwitch);
      if (!IsOpaqueToken(token_a_) || !IsOpaqueToken(token_b_) ||
          token_a_ == token_b_) {
        ReportFailure(WasmProfileDatabaseSmokeFailureStage::kArguments);
        return false;
      }
      mode_ = SmokeMode::kVerifyAWriteB;
      token_a_digest_ = DigestToken(token_a_);
      token_b_digest_ = DigestToken(token_b_);
      expected_digest_ = token_b_digest_;
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)
    } else if (mode == kInterruptLevelDBWriteBMode ||
               mode == kRecoverLevelDBWriteBMode) {
      if (!has_token_a || !has_token_b) {
        ReportFailure(WasmProfileDatabaseSmokeFailureStage::kArguments);
        return false;
      }
      token_a_ = command_line->GetSwitchValueASCII(kTokenASwitch);
      token_b_ = command_line->GetSwitchValueASCII(kTokenBSwitch);
      if (!IsOpaqueToken(token_a_) || !IsOpaqueToken(token_b_) ||
          token_a_ == token_b_) {
        ReportFailure(WasmProfileDatabaseSmokeFailureStage::kArguments);
        return false;
      }
      mode_ = mode == kInterruptLevelDBWriteBMode
                  ? SmokeMode::kInterruptLevelDBWriteB
                  : SmokeMode::kRecoverLevelDBWriteB;
      token_a_digest_ = DigestToken(token_a_);
      token_b_digest_ = DigestToken(token_b_);
      // The clean terminal marker has no token digest. Keep a private,
      // nonempty expectation solely for the existing result-bearing lifecycle
      // validation; recovered A and B are distinguished before that handoff.
      expected_digest_ = token_b_digest_;
#elif defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
    } else if (mode == kInterruptSqliteWriteBMode ||
               mode == kRecoverSqliteWriteBMode) {
      if (!has_token_a || !has_token_b) {
        ReportFailure(WasmProfileDatabaseSmokeFailureStage::kArguments);
        return false;
      }
      token_a_ = command_line->GetSwitchValueASCII(kTokenASwitch);
      token_b_ = command_line->GetSwitchValueASCII(kTokenBSwitch);
      if (!IsOpaqueToken(token_a_) || !IsOpaqueToken(token_b_) ||
          token_a_ == token_b_) {
        ReportFailure(WasmProfileDatabaseSmokeFailureStage::kArguments);
        return false;
      }
      mode_ = mode == kInterruptSqliteWriteBMode
                  ? SmokeMode::kInterruptSqliteWriteB
                  : SmokeMode::kRecoverSqliteWriteB;
      token_a_digest_ = DigestToken(token_a_);
      token_b_digest_ = DigestToken(token_b_);
      // Recovery terminal markers carry no raw value or digest. This private
      // value only keeps the existing lifecycle result validation nonempty.
      expected_digest_ = token_b_digest_;
#elif defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
    } else if (mode == kInterruptLevelDBWriteBMode ||
               mode == kObserveLevelDBWriteBMode) {
      if (!has_token_a || !has_token_b) {
        ReportFailure(WasmProfileDatabaseSmokeFailureStage::kArguments);
        return false;
      }
      token_a_ = command_line->GetSwitchValueASCII(kTokenASwitch);
      token_b_ = command_line->GetSwitchValueASCII(kTokenBSwitch);
      if (!IsOpaqueToken(token_a_) || !IsOpaqueToken(token_b_) ||
          token_a_ == token_b_) {
        ReportFailure(WasmProfileDatabaseSmokeFailureStage::kArguments);
        return false;
      }
      mode_ = mode == kInterruptLevelDBWriteBMode
                  ? SmokeMode::kInterruptLevelDBWriteB
                  : SmokeMode::kObserveLevelDBWriteB;
      token_a_digest_ = DigestToken(token_a_);
      token_b_digest_ = DigestToken(token_b_);
      // Diagnostic terminal markers deliberately carry no digest, but the
      // unchanged result-bearing lifecycle still requires a nonempty private
      // expectation before it can release the real profile lease.
      expected_digest_ = token_b_digest_;
#endif  // source-selected recovery or diagnostic artifact.
    } else if (mode == kVerifyBMode) {
      if (has_token_a || !has_token_b) {
        ReportFailure(WasmProfileDatabaseSmokeFailureStage::kArguments);
        return false;
      }
      token_b_ = command_line->GetSwitchValueASCII(kTokenBSwitch);
      if (!IsOpaqueToken(token_b_)) {
        ReportFailure(WasmProfileDatabaseSmokeFailureStage::kArguments);
        return false;
      }
      mode_ = SmokeMode::kVerifyB;
      token_b_digest_ = DigestToken(token_b_);
      expected_digest_ = token_b_digest_;
    } else {
      ReportFailure(WasmProfileDatabaseSmokeFailureStage::kArguments);
      return false;
    }

    enabled_ = true;
    return true;
  }

  bool enabled() const { return enabled_; }

  SmokeMode mode() const { return mode_; }

  std::optional<DatabaseTaskInput> BeginDatabaseTask(
      base::FilePath profile_path) {
    if (!enabled_ || started_ || failure_reported_ || profile_path.empty()) {
      ReportFailure(WasmProfileDatabaseSmokeFailureStage::kProfile);
      return std::nullopt;
    }
    started_ = true;
    EmitMarker("READY");
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
    // Start is reached only after the dedicated Chrome entry point mounted the
    // exact leased OPFS backend and BrowserMainParts admitted the profile
    // lifecycle. Each outer document constructs a fresh module, so this is a
    // fixed receipt for the test backend's fresh lease acquisition, not a
    // claim about general Chromium profile locking.
    EmitMarker("RECOVERY_LEASE_REACQUIRED");
#endif  // source-selected recovery artifact.

    // leveldb_env::Options initializes Chromium's shared browser block cache.
    // Do that on this UI/main sequence before this input is posted to the
    // MayBlock runner, where all database I/O remains serialized.
    leveldb_env::Options leveldb_options = LevelDBOptionsForSmoke();
    std::optional<DatabaseTaskInput> input(
        std::in_place, std::move(profile_path), mode_, std::move(token_a_),
        std::move(token_b_), std::move(leveldb_options));
    ClearRawTokens();
    return input;
  }

  void NotifyDatabaseTaskPosted() {
    if (!enabled_ || !started_ || task_completed_ || failure_reported_) {
      return;
    }
    // This is immediately before the reply-post API whose sequenced-context
    // contract is the current abort candidate.
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
    if (!IsWriteInterruptionDiagnosticMode(mode_)) {
      EmitDatabaseTaskPhase(DatabaseTaskPhase::kTaskPost);
    }
#elif defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)
    if (!IsDatabaseRecoveryMode(mode_)) {
      EmitDatabaseTaskPhase(DatabaseTaskPhase::kTaskPost);
    }
#elif defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
    if (!IsSqliteRecoveryMode(mode_)) {
      EmitDatabaseTaskPhase(DatabaseTaskPhase::kTaskPost);
    }
#elif defined(CHROME_WASM_M7_PROFILE_DATABASE_LOCK_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_LOCK_TEST)
    // The lock artifacts' strict success receipts have no task-phase telemetry.
#else
    EmitDatabaseTaskPhase(DatabaseTaskPhase::kTaskPost);
#endif  // M7 diagnostic or lock artifact.
  }

  bool CompleteDatabaseTask(DatabaseTaskResult result,
                            bool operation_allowed) {
    if (task_completed_) {
      ReportFailure(WasmProfileDatabaseSmokeFailureStage::kDatabase);
      return false;
    }
    task_completed_ = true;

    if (!operation_allowed || failure_reported_ ||
        (result != DatabaseTaskResult::kSuccess &&
         result != DatabaseTaskResult::kRecoveryA &&
         result != DatabaseTaskResult::kRecoveryB) ||
        expected_digest_.empty()) {
      ReportFailure(WasmProfileDatabaseSmokeFailureStage::kDatabase);
      return false;
    }

    database_succeeded_ = true;
    switch (mode_) {
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_LOCK_TEST)
      case SmokeMode::kLockContention:
        EmitDigestMarker("SQLITE_WRITE_ACCEPTED", token_a_digest_);
        EmitMarker("LEVELDB_LOCK_CONTENDER_REJECTED");
        EmitDigestMarker("LEVELDB_LOCK_RELEASE_REOPEN_OK", token_a_digest_);
        break;
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_LOCK_TEST)
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_LOCK_TEST)
      case SmokeMode::kSQLiteLockContention:
        EmitDigestMarker("SQLITE_LOCK_HOLDER_WRITE_A_ACCEPTED",
                         token_a_digest_);
        EmitMarker("SQLITE_LOCK_CONTENDER_BUSY");
        EmitDigestMarker("SQLITE_LOCK_RELEASE_REOPEN_A_INTEGRITY_OK",
                         token_a_digest_);
        EmitDigestMarker("SQLITE_LOCK_POST_RELEASE_WRITE_READ_B_INTEGRITY_OK",
                         token_b_digest_);
        break;
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_LOCK_TEST)
      case SmokeMode::kWriteA:
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
        EmitDigestMarker("SQLITE_RECOVERY_SEED_A_FULL_INTEGRITY_OK",
                         token_a_digest_);
#else
        EmitDigestMarker("SQLITE_WRITE_ACCEPTED", token_a_digest_);
        EmitDigestMarker("LEVELDB_WRITE_ACCEPTED", token_a_digest_);
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
        break;
      case SmokeMode::kVerifyAWriteB:
        EmitDigestMarker("SQLITE_READ_A_OK", token_a_digest_);
        EmitDigestMarker("LEVELDB_READ_A_OK", token_a_digest_);
        EmitDigestMarker("SQLITE_WRITE_ACCEPTED", token_b_digest_);
        EmitDigestMarker("LEVELDB_WRITE_ACCEPTED", token_b_digest_);
        break;
      case SmokeMode::kVerifyB:
        EmitDigestMarker("SQLITE_READ_B_OK", token_b_digest_);
        EmitDigestMarker("LEVELDB_READ_B_OK", token_b_digest_);
        break;
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)
      case SmokeMode::kInterruptLevelDBWriteB:
        // The intended native abort prevents this branch. If Put returned
        // without the fixed phase, do not convert it into a clean result.
        ReportFailure(WasmProfileDatabaseSmokeFailureStage::kDatabase);
        break;
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC) || defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
      case SmokeMode::kInterruptSqliteWriteB:
        // The selected VFS must abort after its one post-sync phase. Any task
        // reply would mean Commit() returned unexpectedly, not recovery proof.
        ReportFailure(WasmProfileDatabaseSmokeFailureStage::kDatabase);
        break;
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
      case SmokeMode::kObserveLevelDBWriteB:
        // RunDatabaseTask() already emitted exactly one fixed observation
        // after its fresh LevelDB handle was destroyed.
        break;
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)
      case SmokeMode::kRecoverLevelDBWriteB:
        if (result == DatabaseTaskResult::kRecoveryA) {
          EmitDigestMarker("LEVELDB_RECOVERY_A_OK", token_a_digest_);
        } else if (result == DatabaseTaskResult::kRecoveryB) {
          EmitDigestMarker("LEVELDB_RECOVERY_B_OK", token_b_digest_);
        } else {
          ReportFailure(WasmProfileDatabaseSmokeFailureStage::kDatabase);
          break;
        }
        EmitDigestMarker("SQLITE_RECOVERY_A_INTEGRITY_OK", token_a_digest_);
        break;
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST)
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
      case SmokeMode::kRecoverSqliteWriteB:
        if (result == DatabaseTaskResult::kRecoveryA) {
          EmitDigestMarker("SQLITE_RECOVERY_A_FULL_INTEGRITY_OK",
                           token_a_digest_);
        } else if (result == DatabaseTaskResult::kRecoveryB) {
          EmitDigestMarker("SQLITE_RECOVERY_B_FULL_INTEGRITY_OK",
                           token_b_digest_);
        } else {
          ReportFailure(WasmProfileDatabaseSmokeFailureStage::kDatabase);
        }
        break;
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
      case SmokeMode::kNone:
        ReportFailure(WasmProfileDatabaseSmokeFailureStage::kDatabase);
        break;
    }
    if (failure_reported_) {
      return false;
    }

    // RunDatabaseTask() has returned only after every source-selected database
    // object was explicitly closed and destroyed on its one runner.
    databases_closed_ = true;
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
    EmitMarker("DIAGNOSTIC_DATABASES_CLOSED");
#elif defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
    EmitMarker("RECOVERY_DATABASES_CLOSED");
#else
    EmitDigestMarker("DATABASES_CLOSED", expected_digest_);
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
    return DidSucceed();
  }

  bool DidSucceed() const {
    return enabled_ && database_succeeded_ && databases_closed_ &&
           !failure_reported_;
  }

  void NotifyFenceResult(bool success) {
    if (!enabled_ || failure_reported_) {
      return;
    }
    if (!success || !DidSucceed() || expected_digest_.empty() ||
        fence_succeeded_) {
      ReportFailure(WasmProfileDatabaseSmokeFailureStage::kFence);
      return;
    }
    fence_succeeded_ = true;
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
    // This artifact can cleanly release the real profile lease, but that
    // lifecycle fact is not an M7 persistence acceptance.
    EmitMarker("DIAGNOSTIC_FENCE_OK");
#elif defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
    EmitMarker("RECOVERY_FENCE_OK");
#else
    EmitDigestMarker("FENCE_OK", expected_digest_);
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
  }

  void NotifyStorageLifecycle(bool success) {
    if (!enabled_ || failure_reported_) {
      return;
    }
    if (!success || !DidSucceed() || !fence_succeeded_ ||
        storage_lifecycle_succeeded_) {
      ReportFailure(WasmProfileDatabaseSmokeFailureStage::kLifecycle);
      return;
    }
    storage_lifecycle_succeeded_ = true;
  }

  void NotifyBackendDrain(bool success) {
    if (!enabled_ || failure_reported_) {
      return;
    }
    if (!success || !DidSucceed() || !fence_succeeded_ ||
        !storage_lifecycle_succeeded_ || lease_released_) {
      ReportFailure(WasmProfileDatabaseSmokeFailureStage::kDrain);
      return;
    }
    lease_released_ = true;
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
    EmitMarker("DIAGNOSTIC_LEASE_RELEASED");
#elif defined(CHROME_WASM_M7_PROFILE_DATABASE_RECOVERY_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_SQLITE_RECOVERY_TEST)
    EmitMarker("RECOVERY_LEASE_RELEASED");
#else
    EmitMarker("LEASE_RELEASED");
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
  }

  void ReportFailure(WasmProfileDatabaseSmokeFailureStage stage) {
    if (failure_reported_) {
      return;
    }
    // Clear raw command-line data before any fixed failure marker. The task
    // owns a moved copy only while it is performing the opaque database work.
    ClearRawTokens();
    failure_reported_ = true;
    std::fprintf(stderr, "%sFAIL stage=%s\n", kMarkerPrefix,
                 FailureStageName(stage));
    std::fflush(stderr);
  }

 private:
  static const char* FailureStageName(
      WasmProfileDatabaseSmokeFailureStage stage) {
    switch (stage) {
      case WasmProfileDatabaseSmokeFailureStage::kArguments:
        return "arguments";
      case WasmProfileDatabaseSmokeFailureStage::kCapability:
        return "capability";
      case WasmProfileDatabaseSmokeFailureStage::kStorage:
        return "storage";
      case WasmProfileDatabaseSmokeFailureStage::kProfile:
        return "profile";
      case WasmProfileDatabaseSmokeFailureStage::kDatabase:
        return "database";
      case WasmProfileDatabaseSmokeFailureStage::kFence:
        return "fence";
      case WasmProfileDatabaseSmokeFailureStage::kLifecycle:
        return "lifecycle";
      case WasmProfileDatabaseSmokeFailureStage::kContent:
        return "content";
      case WasmProfileDatabaseSmokeFailureStage::kDrain:
        return "drain";
    }
    return "drain";
  }

  void EmitMarker(const char* marker) {
    std::fprintf(stderr, "%s%s\n", kMarkerPrefix, marker);
    std::fflush(stderr);
  }

  void EmitDigestMarker(const char* marker, const std::string& digest) {
    std::fprintf(stderr, "%s%s sha256=%s\n", kMarkerPrefix, marker,
                 digest.c_str());
    std::fflush(stderr);
  }

  void ClearRawTokens() {
    token_a_.clear();
    token_b_.clear();
  }

  bool configured_ = false;
  bool enabled_ = false;
  bool started_ = false;
  bool task_completed_ = false;
  bool database_succeeded_ = false;
  bool databases_closed_ = false;
  bool fence_succeeded_ = false;
  bool storage_lifecycle_succeeded_ = false;
  bool lease_released_ = false;
  bool failure_reported_ = false;
  SmokeMode mode_ = SmokeMode::kNone;
  std::string token_a_;
  std::string token_b_;
  std::string token_a_digest_;
  std::string token_b_digest_;
  std::string expected_digest_;
};

WasmProfileDatabaseSmokeState& GetWasmProfileDatabaseSmokeState() {
  static base::NoDestructor<WasmProfileDatabaseSmokeState> state;
  return *state;
}

}  // namespace

class WasmProfileDatabaseLifetimeParticipant::State {
 public:
  State(base::FilePath profile_path,
        WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold)
      : profile_path_(std::move(profile_path)),
        profile_io_hold_(std::move(profile_io_hold)) {}
  State(const State&) = delete;
  State& operator=(const State&) = delete;
  ~State() = default;

  bool Start(base::OnceCallback<void(bool success)> completion) {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    // A duplicate start must not replace the callback or the admission that
    // owns an already-posted database task.
    if (started_ || completed_) {
      return false;
    }
    if (!profile_io_hold_ || !completion) {
      GetWasmProfileDatabaseSmokeState().ReportFailure(
          WasmProfileDatabaseSmokeFailureStage::kProfile);
      CompleteProfileIO(/*operation_succeeded=*/false);
      return false;
    }

    started_ = true;
    completion_ = std::move(completion);
    std::optional<DatabaseTaskInput> input =
        GetWasmProfileDatabaseSmokeState().BeginDatabaseTask(
            std::move(profile_path_));
    if (!input) {
      CompleteProfileIO(/*operation_succeeded=*/false);
      return true;
    }

    task_runner_ = base::ThreadPool::CreateSequencedTaskRunner(
        {base::MayBlock(), base::TaskShutdownBehavior::BLOCK_SHUTDOWN});
    if (!task_runner_) {
      GetWasmProfileDatabaseSmokeState().CompleteDatabaseTask(
          DatabaseTaskResult::kFailure, /*operation_allowed=*/false);
      CompleteProfileIO(/*operation_succeeded=*/false);
      return true;
    }

    GetWasmProfileDatabaseSmokeState().NotifyDatabaseTaskPosted();
    task_posted_ = task_runner_->PostTaskAndReplyWithResult(
        FROM_HERE, base::BindOnce(&RunDatabaseTask, std::move(*input)),
        base::BindOnce(&State::OnDatabaseTaskComplete,
                       base::Unretained(this)));
    if (!task_posted_) {
      task_runner_.reset();
      GetWasmProfileDatabaseSmokeState().CompleteDatabaseTask(
          DatabaseTaskResult::kFailure, /*operation_allowed=*/false);
      CompleteProfileIO(/*operation_succeeded=*/false);
    }
    return true;
  }

  void Cancel() {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    if (completed_) {
      return;
    }
    cancelled_ = true;
    // RunDatabaseTask is deliberately uninterruptible. It owns real SQLite
    // and LevelDB handles on its BLOCK_SHUTDOWN sequence, so only its reply can
    // release this participant's ProfileIOHold. If that reply never runs, the
    // quarantine below keeps the admission unresolved and forces drain
    // refusal rather than inventing a close receipt.
  }

  bool IsActive() const {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    return started_ && !completed_;
  }

  bool HasCompleted() const {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    return completed_;
  }

  bool DidSucceed() const {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    return started_ && completed_ && succeeded_;
  }

 private:
  void OnDatabaseTaskComplete(DatabaseTaskResult result) {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    if (completed_ || !task_posted_) {
      GetWasmProfileDatabaseSmokeState().ReportFailure(
          WasmProfileDatabaseSmokeFailureStage::kDatabase);
      return;
    }

    // PostTaskAndReplyWithResult cannot run this reply until RunDatabaseTask
    // has returned. Every SQLite and LevelDB owner has therefore been closed
    // and destroyed before either the marker latch or ProfileIOHold advances.
    task_runner_.reset();
    const bool database_succeeded =
        GetWasmProfileDatabaseSmokeState().CompleteDatabaseTask(
            result, /*operation_allowed=*/!cancelled_);
    CompleteProfileIO(database_succeeded && !cancelled_);
  }

  void CompleteProfileIO(bool operation_succeeded) {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    if (completed_) {
      return;
    }

    bool admission_succeeded = false;
    if (profile_io_hold_) {
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_OUTSTANDING_IO_REFUSAL_TEST)
      // This one negative diagnostic intentionally retains the completed
      // task's admission whether its database result succeeded or failed. Its
      // verify-b mode uses a never-written value and therefore expects the
      // database operation to fail; completing that hold here would erase the
      // outstanding-I/O condition that the outer drain must refuse. The task
      // carries no live database handle at this point. ChromeMain explicitly
      // completes the retained hold as failed before fail-closed cleanup.
      admission_succeeded =
          RetainWasmProfileStorageOutstandingIOForRefusalTest(
              std::move(*profile_io_hold_));
#else
      admission_succeeded = profile_io_hold_->Complete(
          operation_succeeded
              ? WasmProfileOrderedDrainLifecycle::ProfileIOCompletion::
                    kSucceeded
              : WasmProfileOrderedDrainLifecycle::ProfileIOCompletion::
                    kFailed);
#endif
      profile_io_hold_.reset();
    }

    completed_ = true;
    succeeded_ = operation_succeeded && admission_succeeded;
    if (operation_succeeded && !admission_succeeded) {
      GetWasmProfileDatabaseSmokeState().ReportFailure(
          WasmProfileDatabaseSmokeFailureStage::kLifecycle);
    }
    if (completion_) {
      base::OnceCallback<void(bool success)> completion =
          std::move(completion_);
      const bool succeeded = succeeded_;
      // The callback may synchronously destroy either the profile-owned or a
      // quarantined State. Do not access members after returning ownership.
      std::move(completion).Run(succeeded);
    }
  }

  bool started_ = false;
  bool task_posted_ = false;
  bool cancelled_ = false;
  bool completed_ = false;
  bool succeeded_ = false;
  base::FilePath profile_path_;
  std::optional<WasmProfileOrderedDrainLifecycle::ProfileIOHold>
      profile_io_hold_;
  scoped_refptr<base::SequencedTaskRunner> task_runner_;
  base::OnceCallback<void(bool success)> completion_;
  SEQUENCE_CHECKER(sequence_checker_);
};

WasmProfileDatabaseLifetimeParticipant::
    WasmProfileDatabaseLifetimeParticipant(
        base::FilePath profile_path,
        WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold)
    : state_(std::make_unique<State>(std::move(profile_path),
                                     std::move(profile_io_hold))) {}

WasmProfileDatabaseLifetimeParticipant::
    ~WasmProfileDatabaseLifetimeParticipant() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  (void)QuarantineForFailureShutdown();
}

bool WasmProfileDatabaseLifetimeParticipant::Start(
    base::OnceCallback<void(bool success)> completion) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return state_ && state_->Start(std::move(completion));
}

void WasmProfileDatabaseLifetimeParticipant::Cancel() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (state_) {
    state_->Cancel();
  }
}

bool WasmProfileDatabaseLifetimeParticipant::
    QuarantineForFailureShutdown() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (!state_ || !state_->IsActive()) {
    return true;
  }

  state_->Cancel();
  if (!state_->IsActive()) {
    return true;
  }

  static base::NoDestructor<std::vector<std::unique_ptr<State>>>
      quarantined_states;
  quarantined_states->push_back(std::move(state_));
  return true;
}

bool WasmProfileDatabaseLifetimeParticipant::IsActive() const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return state_ && state_->IsActive();
}

bool WasmProfileDatabaseLifetimeParticipant::HasCompleted() const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return state_ && state_->HasCompleted();
}

bool WasmProfileDatabaseLifetimeParticipant::DidSucceed() const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return state_ && state_->DidSucceed();
}

bool HasWasmProfileDatabaseSmokeArguments() {
  const base::CommandLine* command_line =
      base::CommandLine::ForCurrentProcess();
  return command_line->HasSwitch(kSmokeSwitch) ||
         command_line->HasSwitch(kTokenASwitch) ||
         command_line->HasSwitch(kTokenBSwitch);
}

bool EnableWasmProfileDatabaseSmokeTestMode() {
  return GetWasmProfileDatabaseSmokeState().EnableFromCommandLine();
}

bool IsWasmProfileDatabaseSmokeEnabled() {
  return GetWasmProfileDatabaseSmokeState().enabled();
}

WasmProfileDatabaseSmokeMode GetWasmProfileDatabaseSmokeMode() {
  switch (GetWasmProfileDatabaseSmokeState().mode()) {
    case SmokeMode::kWriteA:
      return WasmProfileDatabaseSmokeMode::kWriteA;
    case SmokeMode::kVerifyAWriteB:
      return WasmProfileDatabaseSmokeMode::kVerifyAWriteB;
    case SmokeMode::kVerifyB:
      return WasmProfileDatabaseSmokeMode::kVerifyB;
    default:
      return WasmProfileDatabaseSmokeMode::kNone;
  }
}

bool DidWasmProfileDatabaseSmokeSucceed() {
  return GetWasmProfileDatabaseSmokeState().DidSucceed();
}

void NotifyWasmProfileDatabaseSmokeFenceResult(bool success) {
  GetWasmProfileDatabaseSmokeState().NotifyFenceResult(success);
}

void NotifyWasmProfileDatabaseSmokeStorageLifecycle(bool success) {
  GetWasmProfileDatabaseSmokeState().NotifyStorageLifecycle(success);
}

void NotifyWasmProfileDatabaseSmokeBackendDrain(bool success) {
  GetWasmProfileDatabaseSmokeState().NotifyBackendDrain(success);
}

void ReportWasmProfileDatabaseSmokeFailure(
    WasmProfileDatabaseSmokeFailureStage stage) {
  GetWasmProfileDatabaseSmokeState().ReportFailure(stage);
}

}  // namespace chrome
