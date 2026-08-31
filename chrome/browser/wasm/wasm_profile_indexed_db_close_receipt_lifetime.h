// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_INDEXED_DB_CLOSE_RECEIPT_LIFETIME_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_INDEXED_DB_CLOSE_RECEIPT_LIFETIME_H_

#include <optional>

#include "base/functional/callback.h"
#include "base/memory/weak_ptr.h"
#include "chrome/browser/wasm/wasm_profile_ordered_drain_lifecycle.h"

namespace chrome {

// Owns one profile-I/O admission through the selected IndexedDB bucket's
// result-bearing ForceClose callback and the following UI-sequence delivery
// turn. The caller supplies synchronous cleanup, so the transient renderer
// page and its raw test tokens cannot survive either terminal callback.
//
// A failure before that callback deliberately leaves the admission unresolved
// and requests process-lifetime quarantine after cleanup. This is fail-closed:
// it prevents the V4 profile backend from claiming a clean drain after an
// unobserved IndexedDB backing-store close.
class WasmProfileIndexedDBCloseReceiptLifetime {
 public:
  WasmProfileIndexedDBCloseReceiptLifetime(
      WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold,
      base::OnceClosure quarantine_callback);
  WasmProfileIndexedDBCloseReceiptLifetime(
      const WasmProfileIndexedDBCloseReceiptLifetime&) = delete;
  WasmProfileIndexedDBCloseReceiptLifetime& operator=(
      const WasmProfileIndexedDBCloseReceiptLifetime&) = delete;
  ~WasmProfileIndexedDBCloseReceiptLifetime();

  bool Start(base::OnceCallback<void(bool success)> completion);
  bool RejectBeforeStart();
  void Cancel();

  // Represents only the selected, already-observed persistent bucket's
  // IndexedDBControl::ForceClose callback. It is a backing-store close receipt,
  // not a claim that every StoragePartition owner has completed shutdown.
  void CompleteAfterSelectedBucketCloseReceipt(base::OnceClosure cleanup);

  // The admission remains outstanding when the exact selected-bucket close
  // callback was not observed. The owner retains its State process-wide.
  void FailBeforeSelectedBucketCloseReceipt(base::OnceClosure cleanup);

  bool IsActive() const;
  bool HasCompleted() const;
  bool DidSucceed() const;
  bool HasSelectedBucketCloseReceipt() const;
  bool HasOutstandingAdmission() const;

 private:
  void DeliverCloseReceipt();
  void DeliverQuarantineRequest();

  bool started_ = false;
  bool selected_bucket_close_receipt_received_ = false;
  bool cancel_requested_ = false;
  bool completion_delivery_pending_ = false;
  bool quarantine_delivery_pending_ = false;
  bool quarantine_delivered_ = false;
  bool completed_ = false;
  bool succeeded_ = false;
  std::optional<WasmProfileOrderedDrainLifecycle::ProfileIOHold>
      profile_io_hold_;
  base::OnceClosure quarantine_callback_;
  base::OnceCallback<void(bool)> completion_;
  base::WeakPtrFactory<WasmProfileIndexedDBCloseReceiptLifetime>
      weak_ptr_factory_{this};
};

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_PROFILE_INDEXED_DB_CLOSE_RECEIPT_LIFETIME_H_
