// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_local_storage_close_receipt_lifetime.h"

#include <utility>

#include "base/check.h"
#include "base/functional/bind.h"
#include "base/task/sequenced_task_runner.h"

namespace chrome {

WasmProfileLocalStorageCloseReceiptLifetime::
    WasmProfileLocalStorageCloseReceiptLifetime(
        WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold,
        base::OnceClosure quarantine_callback)
    : profile_io_hold_(std::move(profile_io_hold)),
      quarantine_callback_(std::move(quarantine_callback)) {}

WasmProfileLocalStorageCloseReceiptLifetime::
    ~WasmProfileLocalStorageCloseReceiptLifetime() = default;

bool WasmProfileLocalStorageCloseReceiptLifetime::Start(
    base::OnceCallback<void(bool)> completion) {
  if (started_ || !profile_io_hold_ || !quarantine_callback_ || !completion) {
    return false;
  }
  started_ = true;
  completion_ = std::move(completion);
  return true;
}

bool WasmProfileLocalStorageCloseReceiptLifetime::RejectBeforeStart() {
  if (started_ || completed_ || !profile_io_hold_) {
    return false;
  }
  const bool hold_completed = profile_io_hold_->Complete(
      WasmProfileOrderedDrainLifecycle::ProfileIOCompletion::kFailed);
  profile_io_hold_.reset();
  completed_ = true;
  succeeded_ = false;
  return hold_completed;
}

void WasmProfileLocalStorageCloseReceiptLifetime::Cancel() {
  if (IsActive()) {
    cancel_requested_ = true;
  }
}

void WasmProfileLocalStorageCloseReceiptLifetime::
    CompleteAfterExactCloseReceipt(base::OnceClosure cleanup) {
  if (!IsActive() || exact_close_receipt_received_ ||
      quarantine_delivery_pending_ || quarantine_delivered_) {
    return;
  }

  CHECK(cleanup);
  exact_close_receipt_received_ = true;
  std::move(cleanup).Run();
  completion_delivery_pending_ = true;
  CHECK(base::SequencedTaskRunner::GetCurrentDefault()->PostTask(
      FROM_HERE,
      base::BindOnce(
          &WasmProfileLocalStorageCloseReceiptLifetime::DeliverCloseReceipt,
          weak_ptr_factory_.GetWeakPtr())));
}

void WasmProfileLocalStorageCloseReceiptLifetime::
    FailBeforeExactCloseReceipt(base::OnceClosure cleanup) {
  if (!IsActive() || quarantine_delivery_pending_ || quarantine_delivered_) {
    return;
  }
  if (exact_close_receipt_received_) {
    // A receipt already makes this operation terminal. Preserve its posted
    // delivery, but force the terminal result to the failure path.
    cancel_requested_ = true;
    return;
  }

  CHECK(cleanup);
  quarantine_delivery_pending_ = true;
  cancel_requested_ = true;
  std::move(cleanup).Run();
  CHECK(base::SequencedTaskRunner::GetCurrentDefault()->PostTask(
      FROM_HERE,
      base::BindOnce(&WasmProfileLocalStorageCloseReceiptLifetime::
                         DeliverQuarantineRequest,
                     weak_ptr_factory_.GetWeakPtr())));
}

bool WasmProfileLocalStorageCloseReceiptLifetime::IsActive() const {
  return started_ && !completed_;
}

bool WasmProfileLocalStorageCloseReceiptLifetime::HasCompleted() const {
  return completed_;
}

bool WasmProfileLocalStorageCloseReceiptLifetime::DidSucceed() const {
  return completed_ && succeeded_;
}

bool WasmProfileLocalStorageCloseReceiptLifetime::HasExactCloseReceipt()
    const {
  return exact_close_receipt_received_;
}

bool WasmProfileLocalStorageCloseReceiptLifetime::HasOutstandingAdmission()
    const {
  return profile_io_hold_.has_value();
}

void WasmProfileLocalStorageCloseReceiptLifetime::DeliverCloseReceipt() {
  if (!completion_delivery_pending_ || completed_ || !profile_io_hold_) {
    return;
  }

  const bool operation_succeeded = !cancel_requested_;
  const bool hold_completed = profile_io_hold_->Complete(
      operation_succeeded
          ? WasmProfileOrderedDrainLifecycle::ProfileIOCompletion::kSucceeded
          : WasmProfileOrderedDrainLifecycle::ProfileIOCompletion::kFailed);
  profile_io_hold_.reset();
  completion_delivery_pending_ = false;
  completed_ = true;
  succeeded_ = operation_succeeded && hold_completed;

  base::OnceCallback<void(bool)> completion = std::move(completion_);
  const bool succeeded = succeeded_;
  // The callback may synchronously destroy the containing State. Do not touch
  // members after returning control to its owner.
  CHECK(completion);
  std::move(completion).Run(succeeded);
}

void WasmProfileLocalStorageCloseReceiptLifetime::
    DeliverQuarantineRequest() {
  if (!quarantine_delivery_pending_ || completed_ || quarantine_delivered_) {
    return;
  }

  quarantine_delivery_pending_ = false;
  quarantine_delivered_ = true;
  base::OnceClosure quarantine_callback = std::move(quarantine_callback_);
  base::OnceCallback<void(bool)> completion = std::move(completion_);

  // Quarantine moves the containing State and can destroy its profile-owned
  // wrapper. Copy every needed callback first and never access `this` after
  // invoking it.
  CHECK(quarantine_callback);
  CHECK(completion);
  std::move(quarantine_callback).Run();
  std::move(completion).Run(false);
}

}  // namespace chrome
