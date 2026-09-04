// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_INDEXED_DB_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_INDEXED_DB_SMOKE_H_

#include <memory>
#include <optional>
#include <string>

#include "base/files/file_path.h"
#include "base/functional/callback_forward.h"
#include "base/memory/scoped_refptr.h"
#include "base/memory/weak_ptr.h"
#include "chrome/browser/wasm/wasm_profile_ordered_drain_lifecycle.h"

namespace content {
class BrowserContext;
class SiteInstance;
class StoragePartition;
}

namespace chrome {

struct WasmProfileIndexedDBSmokeInput {
  enum class Mode {
    kNone,
    kRendererWrite,
    kRendererVerifyAWriteB,
    kRendererVerifyB,
  };

  Mode mode = Mode::kNone;
  std::string token_a;
  std::string token_b;
  std::string token_a_digest;
  std::string token_b_digest;

  // The standalone IndexedDB artifact exposes its fixed redacted protocol on
  // stderr. The persistent-default-partition shutdown probe instead publishes
  // only its own aggregate marker grammar after this participant's selected
  // bucket receipt returns, so it suppresses these per-operation diagnostics.
  bool emit_protocol_markers = true;

  // The selected persistent-default-partition shutdown probe additionally
  // asks this transient renderer to make one real Cache API write/readback.
  // The browser observes only the fixed renderer acknowledgement; this is not
  // a Cache Storage close, flush, durability, or aggregate-partition receipt.
  bool require_cache_api_write_readback = false;

  // The standalone renderer reload witness asks each fresh renderer module to
  // use one fixed Cache API entry: write A, reopen/read A and write B, then
  // reopen/read B. The participant also receives a selected live-cache
  // close/index-replacement receipt for each module. This remains narrower
  // than CacheStorage-wide quiescence, durable flush, or crash recovery.
  bool require_cache_api_persistence = false;
};

// Owns the one source-selected persistent IndexedDB renderer witness. The
// admitted profile-I/O hold remains live until the browser has observed the
// actual renderer bucket, verified it is disk-backed under the V4-mounted
// profile, and received IndexedDBControl::ForceClose for that selected bucket.
//
// This is intentionally narrower than a complete StoragePartition shutdown:
// it proves only the selected Chromium IndexedDB backing store closes before
// the V4 backend drain. When requested by its input, the same renderer also
// proves one selected-partition Cache API write/readback before that IndexedDB
// close. Neither observation makes normal profiles persistent or claims Cache
// Storage close/flush, quota, Service Worker, or all-partition ownership
// semantics.
class WasmProfileIndexedDBLifetimeParticipant {
 public:
  WasmProfileIndexedDBLifetimeParticipant(
      content::BrowserContext* browser_context,
      base::FilePath profile_path,
      WasmProfileIndexedDBSmokeInput input,
      WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold);
  // The persistent-default-partition shutdown probe supplies the one already
  // created persistent default partition plus its SiteInstance. It must not
  // call GetDefaultStoragePartition() again from the renderer participant:
  // the probe validates that supplied partition's identity with no-create map
  // lookups at the renderer handoff boundaries.
  WasmProfileIndexedDBLifetimeParticipant(
      content::BrowserContext* browser_context,
      base::FilePath profile_path,
      WasmProfileIndexedDBSmokeInput input,
      WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold,
      content::StoragePartition* expected_default_storage_partition,
      scoped_refptr<content::SiteInstance> renderer_site_instance);
  WasmProfileIndexedDBLifetimeParticipant(
      const WasmProfileIndexedDBLifetimeParticipant&) = delete;
  WasmProfileIndexedDBLifetimeParticipant& operator=(
      const WasmProfileIndexedDBLifetimeParticipant&) = delete;
  ~WasmProfileIndexedDBLifetimeParticipant();

  bool Start(base::OnceCallback<void(bool success)> completion);
  void Cancel();
  bool QuarantineForFailureShutdown();
  bool IsActive() const;
  bool DidSucceed() const;
  // True only when |require_cache_api_write_readback| selected the renderer's
  // synthetic HTTPS Cache API put/match operation and it completed before the
  // IndexedDB close receipt. This is deliberately not a Cache Storage close or
  // durable-flush acknowledgement.
  bool DidRendererCacheAPIWriteAndReadbackSucceed() const;
  // True only after the selected renderer Cache API object remained live
  // through the browser-side backend close and CacheStorage index replacement
  // callbacks. This is not an fsync, durable-flush, reload, recovery, or
  // CacheStorage-wide shutdown acknowledgement.
  bool DidRendererCacheAPIBackendCloseAndIndexReplacementSucceed() const;

 private:
  class State;
  void OnOperationRequiresQuarantine();
  static void RetainQuarantinedState(std::unique_ptr<State> state);

  std::unique_ptr<State> state_;
  base::WeakPtrFactory<WasmProfileIndexedDBLifetimeParticipant>
      weak_ptr_factory_{this};
};

// The source-selected chrome_wasm_m7_profile_indexed_db_test recognizes only
// these three fresh-module phases:
//
//   --wasm-profile-indexed-db-smoke=renderer-write
//   --wasm-profile-indexed-db-token-a=<64 lowercase hex>
//
//   --wasm-profile-indexed-db-smoke=renderer-verify-a-write-b
//   --wasm-profile-indexed-db-token-a=<64 lowercase hex>
//   --wasm-profile-indexed-db-token-b=<64 lowercase hex, distinct from A>
//
//   --wasm-profile-indexed-db-smoke=renderer-verify-b
//   --wasm-profile-indexed-db-token-b=<64 lowercase hex>
//
// Append --wasm-profile-indexed-db-cache-api=persistence to any phase to add
// the selected Cache API persistence witness described below.
//
// The renderer-owned chrome://m7-indexed-db page uses globalThis.indexedDB to
// commit A, reopen/read A and commit B, then reopen/read B plus a fixed
// non-no-op close-fence record. The browser validates the committed frame's
// actual non-default persistent StoragePartition and its live bucket metadata,
// then waits for that bucket's ForceClose callback before releasing its
// profile-I/O admission. The host receives only the fixed grammar below; raw
// tokens, URLs, profile paths, and IndexedDB errors never leave Chromium:
//
//   CHROMIUM_WASM_M7_INDEXED_DB:READY
//   CHROMIUM_WASM_M7_INDEXED_DB:RENDERER_WRITE_OK sha256=<digest>
//   CHROMIUM_WASM_M7_INDEXED_DB:RENDERER_REOPEN_READ_A_OK sha256=<digest>
//   CHROMIUM_WASM_M7_INDEXED_DB:RENDERER_WRITE_B_OK sha256=<digest>
//   CHROMIUM_WASM_M7_INDEXED_DB:RENDERER_REOPEN_READ_B_OK sha256=<digest>
//
// With --wasm-profile-indexed-db-cache-api=persistence, the selected Cache
// API operation adds these phase-specific markers before BACKING_STORES_CLOSED:
//   CHROMIUM_WASM_M7_INDEXED_DB:CACHE_API_WRITE_READBACK_OK sha256=<digest>
//   CHROMIUM_WASM_M7_INDEXED_DB:CACHE_API_REOPEN_READ_A_OK sha256=<digest>
//   CHROMIUM_WASM_M7_INDEXED_DB:CACHE_API_WRITE_B_OK sha256=<digest>
//   CHROMIUM_WASM_M7_INDEXED_DB:CACHE_API_REOPEN_READ_B_OK sha256=<digest>
//   CHROMIUM_WASM_M7_INDEXED_DB:CACHE_API_BACKEND_CLOSED_AND_INDEX_REPLACED sha256=<digest>
//   CHROMIUM_WASM_M7_INDEXED_DB:BACKING_STORES_CLOSED sha256=<digest>
//   CHROMIUM_WASM_M7_INDEXED_DB:FENCE_OK sha256=<digest>
//   CHROMIUM_WASM_M7_INDEXED_DB:LEASE_RELEASED
//   CHROMIUM_WASM_M7_INDEXED_DB:FAIL stage=<fixed lowercase stage>
//
// The close receipt is forced selected-bucket backing-store destruction after
// the renderer called IDBDatabase.close(). It is not a general IndexedDB or
// StoragePartition graceful-shutdown/fdatasync claim; durability handoff is
// accepted only after the separately verified V4 backend drain.

bool HasWasmProfileIndexedDBSmokeArguments();
bool EnableWasmProfileIndexedDBSmokeTestMode();
bool IsWasmProfileIndexedDBSmokeEnabled();
WasmProfileIndexedDBSmokeInput::Mode GetWasmProfileIndexedDBSmokeMode();
std::optional<WasmProfileIndexedDBSmokeInput>
TakeWasmProfileIndexedDBSmokeInput();
bool DidWasmProfileIndexedDBSmokeSucceed();
void NotifyWasmProfileIndexedDBSmokeOperationResult(bool success);
void NotifyWasmProfileIndexedDBSmokeFenceResult(bool success);
void NotifyWasmProfileIndexedDBSmokeStorageLifecycle(bool success);
void NotifyWasmProfileIndexedDBSmokeBackendDrain(bool success);

enum class WasmProfileIndexedDBSmokeFailureStage {
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
void ReportWasmProfileIndexedDBSmokeFailure(
    WasmProfileIndexedDBSmokeFailureStage stage);

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_PROFILE_INDEXED_DB_SMOKE_H_
