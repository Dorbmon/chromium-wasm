// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_LOCAL_STORAGE_CLOSE_RECEIPT_LIFETIME_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_LOCAL_STORAGE_CLOSE_RECEIPT_LIFETIME_H_

#include <optional>

#include "base/functional/callback.h"
#include "base/memory/weak_ptr.h"
#include "chrome/browser/wasm/wasm_profile_ordered_drain_lifecycle.h"

namespace chrome {

// Owns one profile-I/O admission across the LocalStorage close receipt and
// the following owner-sequence delivery turn. The caller supplies cleanup as
// a synchronous closure so no profile-bound object survives into either
// terminal callback.
//
// A failure before the exact close receipt never completes or destroys the
// admission. Instead it requests process-lifetime quarantine after cleanup;
// the owner must retain the object containing this controller.
class WasmProfileLocalStorageCloseReceiptLifetime {
 public:
  WasmProfileLocalStorageCloseReceiptLifetime(
      WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold,
      base::OnceClosure quarantine_callback);
  WasmProfileLocalStorageCloseReceiptLifetime(
      const WasmProfileLocalStorageCloseReceiptLifetime&) = delete;
  WasmProfileLocalStorageCloseReceiptLifetime& operator=(
      const WasmProfileLocalStorageCloseReceiptLifetime&) = delete;
  ~WasmProfileLocalStorageCloseReceiptLifetime();

  bool Start(base::OnceCallback<void(bool success)> completion);
  bool RejectBeforeStart();
  void Cancel();

  // `cleanup` runs synchronously before the completion is posted. This method
  // represents only WaitForCloseFence(kSuccess); every other result is a
  // pre-receipt failure.
  void CompleteAfterExactCloseReceipt(base::OnceClosure cleanup);

  // `cleanup` runs synchronously before quarantine is posted. The admission
  // deliberately remains outstanding, so neither clean drain nor failure
  // retirement can race an unobserved backend close.
  void FailBeforeExactCloseReceipt(base::OnceClosure cleanup);

  bool IsActive() const;
  bool HasCompleted() const;
  bool DidSucceed() const;
  bool HasExactCloseReceipt() const;
  bool HasOutstandingAdmission() const;

 private:
  void DeliverCloseReceipt();
  void DeliverQuarantineRequest();

  bool started_ = false;
  bool exact_close_receipt_received_ = false;
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
  base::WeakPtrFactory<WasmProfileLocalStorageCloseReceiptLifetime>
      weak_ptr_factory_{this};
};

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_PROFILE_LOCAL_STORAGE_CLOSE_RECEIPT_LIFETIME_H_
