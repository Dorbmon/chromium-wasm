// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_LOCAL_STORAGE_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_LOCAL_STORAGE_SMOKE_H_

#include "base/files/file_path.h"
#include "base/functional/callback_forward.h"

namespace content {
class StoragePartition;
}

namespace chrome {

// Fixed, test-only protocol for the two-fresh-module default-partition Local
// Storage acceptance. Only chrome_wasm_m7_default_partition_local_storage_test
// recognizes these switches:
//
//   --wasm-profile-local-storage-smoke=write
//   --wasm-profile-local-storage-token=<64 lowercase hex>
//
//   --wasm-profile-local-storage-smoke=verify
//   --wasm-profile-local-storage-token=<64 lowercase hex>
//
// The first module writes the token through Chromium's privileged
// LocalStorageControl/StorageArea API. It then requires an on-disk LevelDB
// UpdateMaps snapshot, a result-bearing no-live-StorageArea arm receipt, and
// then a result-bearing LocalStorage close receipt. The second fresh module
// follows the same sequence after its bounded close-fence mutation.
// Each module only reports a SHA-256 digest of the opaque token.
//
// This proves an ordered commit -> LocalStorage destruction -> V4 backend
// drain -> fresh-module replay boundary. Local Storage's normal LevelDB write
// does not use sync writes, so this is not a power-loss, physical-crash, or
// directory-durability claim. It also does not prove renderer
// window.localStorage, SessionStorage, or other StoragePartition services.
//
// The host may consume only this fixed stderr grammar, where |digest| is 64
// lowercase hexadecimal characters and |stage| is one of arguments,
// capability, storage, profile, read, commit, close, fence, lifecycle,
// content, or drain:
//
//   CHROMIUM_WASM_M7_LOCAL_STORAGE:READY
//   CHROMIUM_WASM_M7_LOCAL_STORAGE:WRITE_ACCEPTED sha256=<digest>
//   CHROMIUM_WASM_M7_LOCAL_STORAGE:REOPEN_READ_OK sha256=<digest>
//   CHROMIUM_WASM_M7_LOCAL_STORAGE:ON_DISK_COMMIT_OK sha256=<digest>
//   CHROMIUM_WASM_M7_LOCAL_STORAGE:DB_CLOSE_OK sha256=<digest>
//   CHROMIUM_WASM_M7_LOCAL_STORAGE:FENCE_OK sha256=<digest>
//   CHROMIUM_WASM_M7_LOCAL_STORAGE:LEASE_RELEASED
//   CHROMIUM_WASM_M7_LOCAL_STORAGE:FAIL stage=<fixed lowercase stage>
//
// A failure emits at most one fixed FAIL line and never includes the opaque
// token, a profile path, a database status, or a Mojo error string.

// Returns true when any private LocalStorage smoke switch is present. This
// includes an orphaned token switch so ChromeMain can reject it before normal
// browser startup.
bool HasWasmProfileLocalStorageSmokeArguments();

// Validates the private command-line protocol and enables this process-local
// test capability. Invalid input emits the fixed arguments failure marker.
bool EnableWasmProfileLocalStorageSmokeTestMode();

// Whether the dedicated executable enabled a valid LocalStorage smoke request.
bool IsWasmProfileLocalStorageSmokeEnabled();

// Starts the real browser-side LocalStorage operation after the profile storage
// lifecycle admitted the profile. `completion` runs only after the test bridge
// received either a result-bearing database-close receipt or a terminal
// failure. It always runs asynchronously after a successful start so the
// caller can complete its profile-I/O hold before requesting normal shutdown.
bool StartWasmProfileLocalStorageSmoke(
    content::StoragePartition* storage_partition,
    const base::FilePath& profile_path,
    base::OnceClosure completion);

// True only after the selected LocalStorage mode reached its on-disk map-update
// and same-runner FIFO database-close receipt. BrowserMainParts uses this to
// withhold profile storage lifecycle acknowledgement on a failed close.
bool DidWasmProfileLocalStorageSmokeSucceed();

// Result-bearing profile lifecycle notifications. These use fixed booleans so
// no raw LocalStorage data or backing-store diagnostics escape the process.
void NotifyWasmProfileLocalStorageSmokeFenceResult(bool success);
void NotifyWasmProfileLocalStorageSmokeStorageLifecycle(bool success);
void NotifyWasmProfileLocalStorageSmokeBackendDrain(bool success);

enum class WasmProfileLocalStorageSmokeFailureStage {
  kArguments,
  kCapability,
  kStorage,
  kProfile,
  kRead,
  kCommit,
  kClose,
  kFence,
  kLifecycle,
  kContent,
  kDrain,
};
void ReportWasmProfileLocalStorageSmokeFailure(
    WasmProfileLocalStorageSmokeFailureStage stage);

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_PROFILE_LOCAL_STORAGE_SMOKE_H_
