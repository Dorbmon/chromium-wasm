// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_indexed_db_close_receipt_lifetime.h"

#include <utility>

#include "base/check.h"
#include "base/functional/bind.h"
#include "base/task/sequenced_task_runner.h"

namespace chrome {

WasmProfileIndexedDBCloseReceiptLifetime::
    WasmProfileIndexedDBCloseReceiptLifetime(
        WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold,
        base::OnceClosure quarantine_callback)
    : profile_io_hold_(std::move(profile_io_hold)),
      quarantine_callback_(std::move(quarantine_callback)) {}

WasmProfileIndexedDBCloseReceiptLifetime::
    ~WasmProfileIndexedDBCloseReceiptLifetime() = default;

bool WasmProfileIndexedDBCloseReceiptLifetime::Start(
    base::OnceCallback<void(bool)> completion) {
  if (started_ || !profile_io_hold_ || !quarantine_callback_ || !completion) {
    return false;
  }
  started_ = true;
  completion_ = std::move(completion);
  return true;
}

bool WasmProfileIndexedDBCloseReceiptLifetime::RejectBeforeStart() {
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

void WasmProfileIndexedDBCloseReceiptLifetime::Cancel() {
  if (IsActive()) {
    cancel_requested_ = true;
  }
}

void WasmProfileIndexedDBCloseReceiptLifetime::
    CompleteAfterSelectedBucketCloseReceipt(base::OnceClosure cleanup) {
  if (!IsActive() || selected_bucket_close_receipt_received_ ||
      quarantine_delivery_pending_ || quarantine_delivered_) {
    return;
  }

  CHECK(cleanup);
  selected_bucket_close_receipt_received_ = true;
  std::move(cleanup).Run();
  completion_delivery_pending_ = true;
  CHECK(base::SequencedTaskRunner::GetCurrentDefault()->PostTask(
      FROM_HERE,
      base::BindOnce(
          &WasmProfileIndexedDBCloseReceiptLifetime::DeliverCloseReceipt,
          weak_ptr_factory_.GetWeakPtr())));
}

void WasmProfileIndexedDBCloseReceiptLifetime::
    FailBeforeSelectedBucketCloseReceipt(base::OnceClosure cleanup) {
  if (!IsActive() || quarantine_delivery_pending_ || quarantine_delivered_) {
    return;
  }
  if (selected_bucket_close_receipt_received_) {
    // Preserve the already-posted selected-bucket receipt but turn its
    // terminal profile-I/O result into failure if cancellation races it.
    cancel_requested_ = true;
    return;
  }

  CHECK(cleanup);
  quarantine_delivery_pending_ = true;
  cancel_requested_ = true;
  std::move(cleanup).Run();
  CHECK(base::SequencedTaskRunner::GetCurrentDefault()->PostTask(
      FROM_HERE,
      base::BindOnce(
          &WasmProfileIndexedDBCloseReceiptLifetime::DeliverQuarantineRequest,
          weak_ptr_factory_.GetWeakPtr())));
}

bool WasmProfileIndexedDBCloseReceiptLifetime::IsActive() const {
  return started_ && !completed_;
}

bool WasmProfileIndexedDBCloseReceiptLifetime::HasCompleted() const {
  return completed_;
}

bool WasmProfileIndexedDBCloseReceiptLifetime::DidSucceed() const {
  return completed_ && succeeded_;
}

bool WasmProfileIndexedDBCloseReceiptLifetime::
    HasSelectedBucketCloseReceipt() const {
  return selected_bucket_close_receipt_received_;
}

bool WasmProfileIndexedDBCloseReceiptLifetime::HasOutstandingAdmission()
    const {
  return profile_io_hold_.has_value();
}

void WasmProfileIndexedDBCloseReceiptLifetime::DeliverCloseReceipt() {
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
  // |completion| can synchronously destroy the containing State.
  CHECK(completion);
  std::move(completion).Run(succeeded);
}

void WasmProfileIndexedDBCloseReceiptLifetime::DeliverQuarantineRequest() {
  if (!quarantine_delivery_pending_ || completed_ || quarantine_delivered_) {
    return;
  }

  quarantine_delivery_pending_ = false;
  quarantine_delivered_ = true;
  base::OnceClosure quarantine_callback = std::move(quarantine_callback_);
  base::OnceCallback<void(bool)> completion = std::move(completion_);

  // Quarantine moves the containing State into process lifetime. Never touch
  // a member after it has run.
  CHECK(quarantine_callback);
  CHECK(completion);
  std::move(quarantine_callback).Run();
  std::move(completion).Run(false);
}

}  // namespace chrome
