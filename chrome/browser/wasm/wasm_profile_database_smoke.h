// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_DATABASE_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_DATABASE_SMOKE_H_

#include "base/files/file_path.h"
#include "base/functional/callback.h"

namespace chrome {

// Fixed, test-only protocol for the three-fresh-module SQLite and LevelDB
// graceful close/reopen acceptance. Only
// chrome_wasm_m7_profile_database_test enables this capability. Its host
// supplies exactly one of these complete argument sets:
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
// The distinct write-interruption diagnostic artifact additionally accepts
// these diagnostic-only modes. They are rejected by the normal and abort-PC
// artifacts, even though those artifacts share this source file:
//
//   --wasm-profile-database-smoke=interrupt-leveldb-write-b
//   --wasm-profile-database-token-a=<64 lowercase hex>
//   --wasm-profile-database-token-b=<64 lowercase hex>
//
//   --wasm-profile-database-smoke=observe-leveldb-write-b
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
// Every observation is a valid diagnostic result, not evidence that B was
// durable. It then cleanly emits only the three diagnostic terminal markers
// above. The diagnostic artifact never emits ordinary DATABASES_CLOSED,
// FENCE_OK, or LEASE_RELEASED for any clean mode.

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

// Starts the database work only after Chrome admitted the profile storage
// lifecycle. The one completion callback runs on the initiating application
// sequence after all SQLite and LevelDB handles have been closed/destroyed on
// the smoke's one shutdown-blocking sequenced runner. It runs for both success
// and failure so the caller can request ordinary asynchronous shutdown.
bool StartWasmProfileDatabaseSmoke(base::FilePath profile_path,
                                   base::OnceClosure completion);

// True only after the database task completed successfully and emitted its
// DATABASES_CLOSED marker. BrowserMainParts uses this to withhold the profile
// storage lifecycle acknowledgement on database failure, which keeps the
// scoped backend drain fail-closed and prevents a lease-success marker.
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
