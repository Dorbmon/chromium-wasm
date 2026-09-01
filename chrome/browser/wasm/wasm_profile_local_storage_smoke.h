// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_LOCAL_STORAGE_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_LOCAL_STORAGE_SMOKE_H_

#include <memory>
#include <optional>
#include <string>

#include "base/files/file_path.h"
#include "base/functional/callback_forward.h"
#include "base/memory/weak_ptr.h"
#include "chrome/browser/wasm/wasm_profile_ordered_drain_lifecycle.h"

namespace content {
class BrowserContext;
class StoragePartition;
}

namespace chrome {

struct WasmProfileLocalStorageSmokeInput {
  enum class Mode {
    kNone,
    kWrite,
    kVerify,
    kRendererWrite,
    kRendererVerify,
  };

  Mode mode = Mode::kNone;
  std::string token;
  std::string token_digest;

  // The standalone LocalStorage artifacts expose their fixed stderr grammar.
  // An embedded source-selected owner receipt can suppress that grammar and
  // emit only its own bounded result marker after the participant completes.
  bool emit_protocol_markers = true;
};

// Owns every profile-bound object used by the LocalStorage acceptance. The
// transferred admission remains live until the exact LocalStorage owner and
// its database sequence have crossed WaitForCloseFence. A failure without
// that receipt is quarantined process-wide instead of retiring the admission.
class WasmProfileLocalStorageLifetimeParticipant {
 public:
  WasmProfileLocalStorageLifetimeParticipant(
      content::BrowserContext* browser_context,
      base::FilePath profile_path,
      WasmProfileLocalStorageSmokeInput input,
      WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold);

  // Uses an already-created persistent default StoragePartition instead of
  // calling BrowserContext::GetDefaultStoragePartition(). This is limited to
  // the source-selected shutdown probe, whose policy witness permits exactly
  // one default-partition construction query. The caller keeps both pointers
  // valid until the result-bearing completion runs.
  WasmProfileLocalStorageLifetimeParticipant(
      content::BrowserContext* browser_context,
      content::StoragePartition* storage_partition,
      base::FilePath profile_path,
      WasmProfileLocalStorageSmokeInput input,
      WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold);
  WasmProfileLocalStorageLifetimeParticipant(
      const WasmProfileLocalStorageLifetimeParticipant&) = delete;
  WasmProfileLocalStorageLifetimeParticipant& operator=(
      const WasmProfileLocalStorageLifetimeParticipant&) = delete;
  ~WasmProfileLocalStorageLifetimeParticipant();

  bool Start(base::OnceCallback<void(bool success)> completion);
  void Cancel();
  bool QuarantineForFailureShutdown();
  bool IsActive() const;
  bool DidSucceed() const;

 private:
  class State;
  void OnOperationRequiresQuarantine();
  static void RetainQuarantinedState(std::unique_ptr<State> state);
  std::unique_ptr<State> state_;
  base::WeakPtrFactory<WasmProfileLocalStorageLifetimeParticipant>
      weak_ptr_factory_{this};
};

// Fixed, test-only protocol for the two-fresh-module default-partition Local
// Storage acceptance. The isolated artifact
// chrome_wasm_m7_default_partition_local_storage_test recognizes:
//
//   --wasm-profile-local-storage-smoke=write
//   --wasm-profile-local-storage-token=<64 lowercase hex>
//
//   --wasm-profile-local-storage-smoke=verify
//   --wasm-profile-local-storage-token=<64 lowercase hex>
//
//   --wasm-profile-local-storage-smoke=renderer-write
//   --wasm-profile-local-storage-token=<64 lowercase hex>
//
//   --wasm-profile-local-storage-smoke=renderer-verify
//   --wasm-profile-local-storage-token=<64 lowercase hex>
//
// The first module writes the token through Chromium's privileged
// LocalStorageControl/StorageArea API. It then requires an on-disk LevelDB
// UpdateMaps snapshot, a result-bearing no-live-StorageArea arm receipt, and
// then a result-bearing LocalStorage close receipt. The second fresh module
// follows the same sequence after its bounded close-fence mutation.
// Each module only reports a SHA-256 digest of the opaque token.
//
// The browser-side modes prove an ordered commit -> LocalStorage destruction
// -> V4 backend drain -> fresh-module replay boundary. The renderer modes use
// one transient chrome://m7-local-storage/ WebContents and its external script
// to perform the equivalent operation through window.localStorage. They prove
// only that one test Chrome origin reopens through that renderer path; neither
// mode makes normal Wasm profiles persistent or proves SessionStorage,
// IndexedDB, Cache Storage, Service Workers, physical-crash recovery, or
// directory durability.
//
// The host may consume only this fixed stderr grammar, where |digest| is 64
// lowercase hexadecimal characters and |stage| is one of arguments,
// capability, storage, profile, read, commit, close, fence, lifecycle,
// content, or drain:
//
//   CHROMIUM_WASM_M7_LOCAL_STORAGE:READY
//   CHROMIUM_WASM_M7_LOCAL_STORAGE:WRITE_ACCEPTED sha256=<digest>
//   CHROMIUM_WASM_M7_LOCAL_STORAGE:REOPEN_READ_OK sha256=<digest>
//   CHROMIUM_WASM_M7_LOCAL_STORAGE:RENDERER_WRITE_OK sha256=<digest>
//   CHROMIUM_WASM_M7_LOCAL_STORAGE:RENDERER_REOPEN_READ_OK sha256=<digest>
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

// Returns the validated phase without transferring or exposing the opaque
// token. A combined artifact uses this before mounting the profile backend to
// reject mismatched Preferences/LocalStorage documents.
WasmProfileLocalStorageSmokeInput::Mode GetWasmProfileLocalStorageSmokeMode();

// True only for the renderer-owned modes. These modes create one transient
// WebContents, derive their StorageKey from its committed RenderFrameHost, and
// destroy that owner before arming the existing close fence.
bool IsWasmProfileRendererLocalStorageSmokeEnabled();

// Moves the validated one-shot request out of the process-global protocol
// latch. The returned input is then owned exclusively by WasmProfile's
// lifetime participant.
std::optional<WasmProfileLocalStorageSmokeInput>
TakeWasmProfileLocalStorageSmokeInput();

// True only after the selected LocalStorage mode reached its on-disk map-update
// and same-runner FIFO database-close receipt. BrowserMainParts uses this to
// withhold profile storage lifecycle acknowledgement on a failed close.
bool DidWasmProfileLocalStorageSmokeSucceed();
void NotifyWasmProfileLocalStorageSmokeOperationResult(bool success);

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
