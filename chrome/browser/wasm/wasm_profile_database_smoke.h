// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_DATABASE_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_DATABASE_SMOKE_H_

#include <memory>

#include "base/files/file_path.h"
#include "base/functional/callback_forward.h"
#include "base/sequence_checker.h"
#include "chrome/browser/wasm/wasm_profile_ordered_drain_lifecycle.h"

namespace chrome {

// Redacted phase identity used only to pair this protocol with other aggregate
// owners before mounting the profile backend. It exposes no token, digest,
// database status, or filesystem path.
enum class WasmProfileDatabaseSmokeMode {
  kNone,
  kWriteA,
  kVerifyAWriteB,
  kVerifyB,
};

// Fixed, test-only protocol for source-selected SQLite and LevelDB acceptances.
// The standalone database artifact and five-store aggregate enable the same
// three-phase graceful close/reopen capability. Their hosts supply exactly one
// of these complete argument sets:
//
//   --wasm-profile-database-smoke=write-a
//   --wasm-profile-database-token-a=<64 lowercase hex>
//
//   --wasm-profile-database-smoke=verify-a-write-b
//   --wasm-profile-database-token-a=<64 lowercase hex>
//   --wasm-profile-database-token-b=<64 lowercase hex>
//
//   --wasm-profile-database-smoke=verify-b
//   --wasm-profile-database-token-b=<64 lowercase hex>
//
// chrome_wasm_m7_profile_database_sqlite_lock_test is a separate
// source-selected artifact. It accepts only this complete argument set:
//
//   --wasm-profile-database-smoke=sqlite-lock-contention
//   --wasm-profile-database-token-a=<64 lowercase hex>
//   --wasm-profile-database-token-b=<64 lowercase hex>
//
// chrome_wasm_m7_profile_database_lock_test is a separate source-selected
// artifact. It accepts only this complete argument set:
//
//   --wasm-profile-database-smoke=lock-contention
//   --wasm-profile-database-token-a=<64 lowercase hex>
//
// The distinct write-interruption diagnostic and bounded recovery artifacts
// additionally accept their own private modes. They are rejected by the
// normal and abort-PC artifacts, even though those artifacts share this source
// file:
//
//   --wasm-profile-database-smoke=interrupt-leveldb-write-b
//   --wasm-profile-database-token-a=<64 lowercase hex>
//   --wasm-profile-database-token-b=<64 lowercase hex>
//
//   --wasm-profile-database-smoke=observe-leveldb-write-b
//   --wasm-profile-database-token-a=<64 lowercase hex>
//   --wasm-profile-database-token-b=<64 lowercase hex>
//
// The bounded recovery artifact accepts this final mode instead of the
// diagnostic observation mode:
//
//   --wasm-profile-database-smoke=recover-leveldb-write-b
//   --wasm-profile-database-token-a=<64 lowercase hex>
//   --wasm-profile-database-token-b=<64 lowercase hex>
//
// chrome_wasm_m7_profile_database_sqlite_recovery_test is another distinct,
// source-selected artifact. It accepts only the ordinary SQLite A seed and
// these two controlled-boundary modes:
//
//   --wasm-profile-database-smoke=interrupt-sqlite-write-b
//   --wasm-profile-database-token-a=<64 lowercase hex>
//   --wasm-profile-database-token-b=<64 lowercase hex>
//
//   --wasm-profile-database-smoke=recover-sqlite-write-b
//   --wasm-profile-database-token-a=<64 lowercase hex>
//   --wasm-profile-database-token-b=<64 lowercase hex>
//
// In verify-a-write-b mode token B must differ from token A. The raw tokens
// remain inside database files below the profile's Default directory and never
// leave this process in a marker, diagnostic, database status string, or path.
// The host may consume only this stderr grammar, where |digest| is exactly 64
// lowercase hexadecimal characters and |stage| is one of arguments,
// capability, storage, profile, database, fence, lifecycle, content, or drain:
//
//   CHROMIUM_WASM_M7_DATABASE:READY
//   CHROMIUM_WASM_M7_DATABASE:SQLITE_READ_A_OK sha256=<digest>
//   CHROMIUM_WASM_M7_DATABASE:LEVELDB_READ_A_OK sha256=<digest>
//   CHROMIUM_WASM_M7_DATABASE:SQLITE_READ_B_OK sha256=<digest>
//   CHROMIUM_WASM_M7_DATABASE:LEVELDB_READ_B_OK sha256=<digest>
//   CHROMIUM_WASM_M7_DATABASE:SQLITE_WRITE_ACCEPTED sha256=<digest>
//   CHROMIUM_WASM_M7_DATABASE:LEVELDB_WRITE_ACCEPTED sha256=<digest>
//   CHROMIUM_WASM_M7_DATABASE:LEVELDB_LOCK_CONTENDER_REJECTED
//   CHROMIUM_WASM_M7_DATABASE:LEVELDB_LOCK_RELEASE_REOPEN_OK sha256=<digest>
//   CHROMIUM_WASM_M7_DATABASE:SQLITE_LOCK_HOLDER_WRITE_A_ACCEPTED sha256=<digest>
//   CHROMIUM_WASM_M7_DATABASE:SQLITE_LOCK_CONTENDER_BUSY
//   CHROMIUM_WASM_M7_DATABASE:SQLITE_LOCK_RELEASE_REOPEN_A_INTEGRITY_OK sha256=<digest>
//   CHROMIUM_WASM_M7_DATABASE:SQLITE_LOCK_POST_RELEASE_WRITE_READ_B_INTEGRITY_OK sha256=<digest>
//   CHROMIUM_WASM_M7_DATABASE:DATABASES_CLOSED sha256=<digest>
//   CHROMIUM_WASM_M7_DATABASE:FENCE_OK sha256=<digest>
//   CHROMIUM_WASM_M7_DATABASE:LEASE_RELEASED
//   CHROMIUM_WASM_M7_DATABASE:FAIL stage=<fixed lowercase stage>
//
// write-a emits READY, SQLITE_WRITE_ACCEPTED(A), LEVELDB_WRITE_ACCEPTED(A),
// DATABASES_CLOSED(A), FENCE_OK(A), and LEASE_RELEASED. verify-a-write-b
// emits READY, both READ_A_OK(A) markers, both WRITE_ACCEPTED(B) markers,
// DATABASES_CLOSED(B), FENCE_OK(B), and LEASE_RELEASED. verify-b emits READY,
// both READ_B_OK(B) markers, DATABASES_CLOSED(B), FENCE_OK(B), and
// LEASE_RELEASED. A failure emits at most one fixed FAIL line and no raw token,
// database status, or profile path.

// The lock artifact writes and independently closes/reopens SQLite A as a
// control. It then uses Chromium's real leveldb_env::OpenDB path to write A
// synchronously while holding the LevelDB database lock, requires a second
// same-process OpenDB to fail with no returned database and Chromium's
// LockFile/FILE_ERROR_IN_USE status, destroys that holder, and requires a
// create-if-missing=false paranoid checksum reopen to read A.
// Its clean marker sequence is READY, SQLITE_WRITE_ACCEPTED(A),
// LEVELDB_LOCK_CONTENDER_REJECTED, LEVELDB_LOCK_RELEASE_REOPEN_OK(A),
// DATABASES_CLOSED(A), FENCE_OK(A), and LEASE_RELEASED. This proves only the
// Chromium single-process LevelDB lock-table path; it does not prove direct V4
// fcntl range-lock behavior, SQLite locking, a concurrent full Chrome profile,
// an external OPFS writer, directory durability, normal-profile persistence,
// or M7 completion.
//
// The SQLite lock artifact is a separate source-selected receipt. It seeds one
// SQLite file in the V4-mounted /profile/Default test-profile directory, opens
// two real Chromium sql::Database connections before either writes, and keeps
// the holder's rollback-journal transaction live after a real A write. The
// contender's B write must fail with primary SQLite BUSY; it is explicitly
// closed before the holder commits. Fresh handles then reopen and
// FullIntegrityCheck A, write B, and independently reopen and verify B.
// Its clean marker sequence is READY, SQLITE_LOCK_HOLDER_WRITE_A_ACCEPTED(A),
// SQLITE_LOCK_CONTENDER_BUSY,
// SQLITE_LOCK_RELEASE_REOPEN_A_INTEGRITY_OK(A),
// SQLITE_LOCK_POST_RELEASE_WRITE_READ_B_INTEGRITY_OK(B),
// DATABASES_CLOSED(B), FENCE_OK(B), and LEASE_RELEASED.
//
// This proves only real same-Wasm-process SQLite connection contention,
// release, close/reopen, and integrity on one file in that V4-mounted
// test-profile directory. It does not prove direct V4 fcntl range-lock
// contention, contention between separate V4 mounts/profiles/documents/processes,
// WAL or mmap semantics, an external OPFS writer, directory durability, crash
// or power-loss recovery, normal-profile persistence, or M7 completion.
//
// The write-interruption artifact is a controlled write-interruption
// diagnostic, not an M7 acceptance. It does not establish crash recovery,
// persistence, directory durability, outer-page reload behavior, or M7
// completion. In that artifact, clean write-a setup emits its existing write
// accepted digest markers, followed only by these diagnostic terminal markers:
//
//   CHROMIUM_WASM_M7_DATABASE:DIAGNOSTIC_DATABASES_CLOSED
//   CHROMIUM_WASM_M7_DATABASE:DIAGNOSTIC_FENCE_OK
//   CHROMIUM_WASM_M7_DATABASE:DIAGNOSTIC_LEASE_RELEASED
//
// interrupt-leveldb-write-b first emits READY and both existing READ_A_OK
// digest markers after independently reopening SQLite and LevelDB. It then
// opens a separate LevelDB handle, arms a target-local writable-file wrapper
// immediately before its sync Put(B), and, only after the first owner-thread
// .log Sync forwards successfully, emits exactly this fixed phase before a
// native abort prevents Put from returning:
//
//   CHROMIUM_WASM_M7_DATABASE_PHASE:leveldb-write-log-sync-returned
//
// It emits no FAIL, DATABASES_CLOSED, FENCE_OK, LEASE_RELEASED, or diagnostic
// terminal marker on that intended abort path. observe-leveldb-write-b opens a
// fresh LevelDB handle and emits exactly one of these fixed observations:
//
//   CHROMIUM_WASM_M7_DATABASE:LEVELDB_POST_SYNC_OBSERVATION outcome=a
//   CHROMIUM_WASM_M7_DATABASE:LEVELDB_POST_SYNC_OBSERVATION outcome=b
//   CHROMIUM_WASM_M7_DATABASE:LEVELDB_POST_SYNC_OBSERVATION outcome=missing
//   CHROMIUM_WASM_M7_DATABASE:LEVELDB_POST_SYNC_OBSERVATION outcome=other
//   CHROMIUM_WASM_M7_DATABASE:LEVELDB_POST_SYNC_OBSERVATION outcome=open-failed
//
// After that separate LevelDB handle has closed, it also independently closes
// and reopens SQLite's pre-existing A value and requires its normal full
// integrity result before emitting this fixed, redacted diagnostic marker:
//
//   CHROMIUM_WASM_M7_DATABASE:SQLITE_POST_SYNC_REOPEN_INTEGRITY_OK
//
// Every LevelDB observation remains a diagnostic result, not evidence that B
// was durable. The SQLite marker is only an in-module close/reopen observation;
// it does not establish interruption recovery. It then cleanly emits only the
// three diagnostic terminal markers above. The diagnostic artifact never emits
// ordinary DATABASES_CLOSED, FENCE_OK, or LEASE_RELEASED for any clean mode.

// The separate recovery artifact has a deliberately narrower grammar. Its
// first fresh module writes A; its second fresh module verifies A and aborts
// only after the owner-thread active LevelDB .log Sync returns from a sync
// Put(B); and its third fresh module reacquires the test profile lease before
// reopening LevelDB twice with `paranoid_checks` and checksum reads. The third
// module accepts only a matching A or B value from both independently closed
// LevelDB handles and separately reopens SQLite's pre-existing A value twice
// with FullIntegrityCheck. Its fixed markers are proof for that bounded
// controlled boundary only, never a claim about physical crash behavior,
// SQLite interruption recovery, directory durability, cross-store atomicity,
// full Chromium profile persistence, or M7 completion:
//
//   CHROMIUM_WASM_M7_DATABASE:RECOVERY_LEASE_REACQUIRED
//   CHROMIUM_WASM_M7_DATABASE:LEVELDB_RECOVERY_A_OK sha256=<digest-a>
//   CHROMIUM_WASM_M7_DATABASE:LEVELDB_RECOVERY_B_OK sha256=<digest-b>
//   CHROMIUM_WASM_M7_DATABASE:SQLITE_RECOVERY_A_INTEGRITY_OK sha256=<digest-a>
//   CHROMIUM_WASM_M7_DATABASE:RECOVERY_DATABASES_CLOSED
//   CHROMIUM_WASM_M7_DATABASE:RECOVERY_FENCE_OK
//   CHROMIUM_WASM_M7_DATABASE:RECOVERY_LEASE_RELEASED

// The separate SQLite recovery artifact has an equally narrow but different
// receipt. Its first fresh module writes and independently closes/reopens
// SQLite A using Chrome's normal VFS. Its second fresh module first reads that
// committed A value normally, then opens only its target SQLite connection via
// a private, non-default forwarding VFS. The connection uses normal advisory
// locking, a TRUNCATE rollback journal, mmap disabled, and SQLite's FULL
// synchronous setting. After its B statement succeeds, that VFS is armed
// immediately before the real Transaction::Commit(). It forwards the selected
// main-database xSync() to Chromium's default VFS first and aborts only after
// that call returns SQLITE_OK. Its third fresh module requires the existing
// file, then independently opens, FullIntegrityChecks, closes, and repeats
// that recovery read; both outcomes must stably be the exact A or B token.
// Its fixed markers are:
//
//   CHROMIUM_WASM_M7_DATABASE:RECOVERY_LEASE_REACQUIRED
//   CHROMIUM_WASM_M7_DATABASE:SQLITE_RECOVERY_SEED_A_FULL_INTEGRITY_OK sha256=<digest-a>
//   CHROMIUM_WASM_M7_DATABASE:SQLITE_RECOVERY_READ_A_OK sha256=<digest-a>
//   CHROMIUM_WASM_M7_DATABASE:SQLITE_ROLLBACK_JOURNAL_COMMIT_B_ARMED sha256=<digest-b>
//   CHROMIUM_WASM_M7_DATABASE_PHASE:sqlite-write-main-db-sync-returned
//   CHROMIUM_WASM_M7_DATABASE:SQLITE_RECOVERY_A_FULL_INTEGRITY_OK sha256=<digest-a>
//   CHROMIUM_WASM_M7_DATABASE:SQLITE_RECOVERY_B_FULL_INTEGRITY_OK sha256=<digest-b>
//   CHROMIUM_WASM_M7_DATABASE:RECOVERY_DATABASES_CLOSED
//   CHROMIUM_WASM_M7_DATABASE:RECOVERY_FENCE_OK
//   CHROMIUM_WASM_M7_DATABASE:RECOVERY_LEASE_RELEASED
//
// This proves only a source-selected, controlled interruption after a
// successful SQLite main-database xSync and before Commit() returns. It does
// not prove physical crash or power-loss behavior, directory durability,
// cross-store atomicity, general SQLite interruption recovery, a concurrent
// normal Chromium profile, normal-profile persistence, or M7 completion.

// True when any switch in the dedicated database protocol is present. This
// includes orphaned token switches so ChromeMain fails them before ordinary
// startup rather than silently falling through to browser setup.
bool HasWasmProfileDatabaseSmokeArguments();

// Validates the private command-line protocol and enables this process-local
// test capability. ChromeMain calls this only in the dedicated executable.
// Invalid input emits a fixed arguments failure marker.
bool EnableWasmProfileDatabaseSmokeTestMode();

// Whether the dedicated executable enabled a valid database smoke request.
bool IsWasmProfileDatabaseSmokeEnabled();

// Returns the enabled normal acceptance phase. Diagnostic-only modes map to
// kNone so an aggregate cannot accidentally admit a diagnostic protocol.
WasmProfileDatabaseSmokeMode GetWasmProfileDatabaseSmokeMode();

// Owns the source-selected SQLite and LevelDB witness for one WasmProfile.
// The caller transfers an admitted profile-I/O hold at construction. Start()
// keeps that admission, its shutdown-blocking runner, and the result callback
// together until RunDatabaseTask has returned after destroying every database
// handle. Cancellation latches failure but cannot interrupt or falsely close
// active database work. If its UI reply can no longer run, owner destruction
// quarantines the active state for process lifetime so the outer V4 drain
// refuses while the admission remains unresolved.
class WasmProfileDatabaseLifetimeParticipant {
 public:
  WasmProfileDatabaseLifetimeParticipant(
      base::FilePath profile_path,
      WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold);
  WasmProfileDatabaseLifetimeParticipant(
      const WasmProfileDatabaseLifetimeParticipant&) = delete;
  WasmProfileDatabaseLifetimeParticipant& operator=(
      const WasmProfileDatabaseLifetimeParticipant&) = delete;
  ~WasmProfileDatabaseLifetimeParticipant();

  // Runs |completion| on the initiating sequence after the database task and
  // the transferred profile-I/O admission have both reached terminal results.
  bool Start(base::OnceCallback<void(bool success)> completion);
  void Cancel();
  bool QuarantineForFailureShutdown();

  bool IsActive() const;
  bool HasCompleted() const;
  bool DidSucceed() const;

 private:
  class State;

  SEQUENCE_CHECKER(sequence_checker_);
  std::unique_ptr<State> state_;
};

// Process-lifetime result latch used after the WasmProfile-owned participant
// has been destroyed. True only after the database task returned successfully
// following handle destruction and emitted its DATABASES_CLOSED marker. The
// latch owns no task runner or completion callback.
bool DidWasmProfileDatabaseSmokeSucceed();

// Result-bearing lifecycle notifications that complete the fixed marker
// sequence. Callers provide fixed booleans only, never a raw token, database
// status, or filesystem path.
void NotifyWasmProfileDatabaseSmokeFenceResult(bool success);
void NotifyWasmProfileDatabaseSmokeStorageLifecycle(bool success);
void NotifyWasmProfileDatabaseSmokeBackendDrain(bool success);

enum class WasmProfileDatabaseSmokeFailureStage {
  kArguments,
  kCapability,
  kStorage,
  kProfile,
  kDatabase,
  kFence,
  kLifecycle,
  kContent,
  kDrain,
};
void ReportWasmProfileDatabaseSmokeFailure(
    WasmProfileDatabaseSmokeFailureStage stage);

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_PROFILE_DATABASE_SMOKE_H_
