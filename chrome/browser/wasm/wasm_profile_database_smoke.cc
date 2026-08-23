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
#include "crypto/hash.h"
#include "leveldb/db.h"
#include "leveldb/env.h"
#include "leveldb/options.h"
#include "sql/database.h"
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
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
constexpr char kInterruptLevelDBWriteBMode[] = "interrupt-leveldb-write-b";
constexpr char kObserveLevelDBWriteBMode[] = "observe-leveldb-write-b";
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
constexpr size_t kOpaqueTokenLength = 64;

constexpr char kSQLiteFilename[] = "m7_profile_database_smoke.sqlite";
constexpr char kLevelDBDirectory[] = "m7_profile_database_smoke_leveldb";
constexpr char kDatabaseKey[] = "m7_profile_database_smoke_token";

constexpr char kMarkerPrefix[] = "CHROMIUM_WASM_M7_DATABASE:";
constexpr char kPhasePrefix[] = "CHROMIUM_WASM_M7_DATABASE_PHASE:";

enum class SmokeMode {
  kNone,
  kWriteA,
  kVerifyAWriteB,
  kVerifyB,
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
  kInterruptLevelDBWriteB,
  kObserveLevelDBWriteB,
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
};

enum class DatabaseTaskResult {
  kSuccess,
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
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
  kLevelDBWriteLogSyncReturned,
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
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
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
    case DatabaseTaskPhase::kLevelDBWriteLogSyncReturned:
      return "leveldb-write-log-sync-returned";
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
    case DatabaseTaskPhase::kTaskComplete:
      return "task-complete";
  }
  return "task-complete";
}

void EmitDatabaseTaskPhase(DatabaseTaskPhase phase) {
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

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
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
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)

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

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
void EmitDatabaseDigestMarker(const char* marker, std::string_view digest) {
  std::fprintf(stderr, "%s%s sha256=%.*s\n", kMarkerPrefix, marker,
               static_cast<int>(digest.size()), digest.data());
  std::fflush(stderr);
}
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)

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
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)

sql::DatabaseOptions DatabaseOptionsForSmoke() {
  sql::DatabaseOptions options;
  // This deliberately exercises SQLite's normal advisory locking path. The
  // test does not use exclusive locking or WAL as a way to bypass it. Keep
  // mmap disabled and SQLite's normal sync behavior enabled so this remains a
  // deterministic graceful-close/reopen check, not a crash-recovery claim.
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

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
bool ReadExistingLevelDBTokenWithoutPhases(
    const base::FilePath& database_path,
    std::string_view expected_token,
    const leveldb_env::Options& options) {
  // A diagnostic verifier must not create a replacement database while
  // attempting to establish its fresh-document A witness.
  leveldb_env::Options existing_options = options;
  existing_options.create_if_missing = false;
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
  return database->Get(read_options, kDatabaseKey, &value).ok() &&
         std::string_view(value) == expected_token;
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

DatabaseTaskResult RunDatabaseTask(DatabaseTaskInput input) {
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
  const bool emit_task_phases =
      !IsWriteInterruptionDiagnosticMode(input.mode);
  if (emit_task_phases) {
    EmitDatabaseTaskPhase(DatabaseTaskPhase::kTaskStarted);
  }
#else
  EmitDatabaseTaskPhase(DatabaseTaskPhase::kTaskStarted);
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
  const base::FilePath sqlite_path =
      input.profile_path.AppendASCII(kSQLiteFilename);
  const base::FilePath leveldb_path =
      input.profile_path.AppendASCII(kLevelDBDirectory);

  bool success = false;
  switch (input.mode) {
    case SmokeMode::kWriteA:
      EmitDatabaseTaskPhase(DatabaseTaskPhase::kSQLiteWrite);
      if (WriteSqliteTokenAndVerifyAfterClose(sqlite_path, input.token_a)) {
        EmitDatabaseTaskPhase(DatabaseTaskPhase::kLevelDBWrite);
        success = WriteLevelDBTokenAndVerifyAfterClose(
            leveldb_path, input.token_a, input.leveldb_options);
      }
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
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
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
    case SmokeMode::kObserveLevelDBWriteB:
      // Every fixed observation is useful controlled diagnostic output. It is
      // not a B durability claim, so open failure and every value class
      // complete this diagnostic cleanly through its distinct terminal-marker
      // grammar.
      EmitPostSyncObservation(ObservePostSyncLevelDBWrite(
          leveldb_path, input.token_a, input.token_b, input.leveldb_options));
      success = true;
      break;
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
    case SmokeMode::kNone:
      break;
  }

  input.ClearRawTokens();
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
  if (emit_task_phases) {
    EmitDatabaseTaskPhase(DatabaseTaskPhase::kTaskComplete);
  }
#else
  EmitDatabaseTaskPhase(DatabaseTaskPhase::kTaskComplete);
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
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
    if (mode == kWriteAMode) {
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
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
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
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
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

  bool Start(base::FilePath profile_path, base::OnceClosure completion) {
    if (!enabled_ || started_ || profile_path.empty() || !completion) {
      ReportFailure(WasmProfileDatabaseSmokeFailureStage::kProfile);
      return false;
    }
    started_ = true;
    completion_ = std::move(completion);
    EmitMarker("READY");

    // leveldb_env::Options initializes Chromium's shared browser block cache.
    // Do that on this UI/main sequence before this input is posted to the
    // MayBlock runner, where all database I/O remains serialized.
    leveldb_env::Options leveldb_options = LevelDBOptionsForSmoke();
    DatabaseTaskInput input(std::move(profile_path), mode_, std::move(token_a_),
                            std::move(token_b_), std::move(leveldb_options));
    ClearRawTokens();
    task_runner_ = base::ThreadPool::CreateSequencedTaskRunner(
        {base::MayBlock(), base::TaskShutdownBehavior::BLOCK_SHUTDOWN});
    if (!task_runner_) {
      OnDatabaseTaskComplete(DatabaseTaskResult::kFailure);
      return true;
    }
    // This is immediately before the reply-post API whose sequenced-context
    // contract is the current abort candidate.
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
    if (!IsWriteInterruptionDiagnosticMode(mode_)) {
      EmitDatabaseTaskPhase(DatabaseTaskPhase::kTaskPost);
    }
#else
    EmitDatabaseTaskPhase(DatabaseTaskPhase::kTaskPost);
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
    if (!task_runner_->PostTaskAndReplyWithResult(
        FROM_HERE, base::BindOnce(&RunDatabaseTask, std::move(input)),
        base::BindOnce(&WasmProfileDatabaseSmokeState::OnDatabaseTaskComplete,
                       base::Unretained(this)))) {
      // The completion still takes the normal BrowserMainParts shutdown path.
      // It withholds storage lifecycle acknowledgement after this fixed failure.
      OnDatabaseTaskComplete(DatabaseTaskResult::kFailure);
    }
    return true;
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

  void OnDatabaseTaskComplete(DatabaseTaskResult result) {
    if (task_completed_) {
      ReportFailure(WasmProfileDatabaseSmokeFailureStage::kDatabase);
      return;
    }
    task_completed_ = true;
    task_runner_.reset();

    if (result != DatabaseTaskResult::kSuccess || expected_digest_.empty()) {
      ReportFailure(WasmProfileDatabaseSmokeFailureStage::kDatabase);
    } else {
      database_succeeded_ = true;
      switch (mode_) {
        case SmokeMode::kWriteA:
          EmitDigestMarker("SQLITE_WRITE_ACCEPTED", token_a_digest_);
          EmitDigestMarker("LEVELDB_WRITE_ACCEPTED", token_a_digest_);
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
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
        case SmokeMode::kInterruptLevelDBWriteB:
          // The intended native abort prevents this branch. If Put returned
          // without the fixed phase, do not convert it into a clean result.
          ReportFailure(WasmProfileDatabaseSmokeFailureStage::kDatabase);
          break;
        case SmokeMode::kObserveLevelDBWriteB:
          // RunDatabaseTask() already emitted exactly one fixed observation
          // after its fresh LevelDB handle was destroyed.
          break;
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
        case SmokeMode::kNone:
          ReportFailure(WasmProfileDatabaseSmokeFailureStage::kDatabase);
          break;
      }
      if (!failure_reported_) {
        // RunDatabaseTask() has returned only after every SQLite and LevelDB
        // object was explicitly closed and then destroyed on its one runner.
        databases_closed_ = true;
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
        EmitMarker("DIAGNOSTIC_DATABASES_CLOSED");
#else
        EmitDigestMarker("DATABASES_CLOSED", expected_digest_);
#endif  // defined(CHROME_WASM_M7_PROFILE_DATABASE_WRITE_INTERRUPTION_DIAGNOSTIC)
      }
    }

    if (completion_) {
      std::move(completion_).Run();
    }
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
  scoped_refptr<base::SequencedTaskRunner> task_runner_;
  base::OnceClosure completion_;
};

WasmProfileDatabaseSmokeState& GetWasmProfileDatabaseSmokeState() {
  static base::NoDestructor<WasmProfileDatabaseSmokeState> state;
  return *state;
}

}  // namespace

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

bool StartWasmProfileDatabaseSmoke(base::FilePath profile_path,
                                   base::OnceClosure completion) {
  return GetWasmProfileDatabaseSmokeState().Start(std::move(profile_path),
                                                  std::move(completion));
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
