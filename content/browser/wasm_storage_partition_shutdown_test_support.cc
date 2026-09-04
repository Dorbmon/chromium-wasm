// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "content/browser/wasm_storage_partition_shutdown_test_support.h"

#include <utility>

#include "base/functional/callback.h"
#include "base/memory/raw_ptr.h"
#include "base/no_destructor.h"
#include "base/task/bind_post_task.h"
#include "base/task/sequenced_task_runner.h"
#include "content/browser/storage_partition_impl.h"
#include "content/public/browser/browser_thread.h"
#include "content/public/browser/wasm_storage_partition_shutdown_test_support.h"

namespace content {

namespace {

class WasmStoragePartitionShutdownNotificationState {
 public:
  bool Arm(StoragePartition* expected_partition,
           base::OnceClosure on_notification_returned) {
    DCHECK_CURRENTLY_ON(BrowserThread::UI);
    if (!expected_partition || !on_notification_returned || armed_) {
      return false;
    }

    expected_partition_ = expected_partition;
    on_notification_returned_ = std::move(on_notification_returned);
    armed_ = true;
    return true;
  }

  void NotifyReturned(StoragePartition* partition) {
    DCHECK_CURRENTLY_ON(BrowserThread::UI);
    if (!armed_ || rejected_ || notification_returned_ ||
        partition != expected_partition_) {
      rejected_ = true;
      expected_partition_ = nullptr;
      on_notification_returned_.Reset();
      return;
    }

    expected_partition_ = nullptr;
    notification_returned_ = true;
    std::move(on_notification_returned_).Run();
  }

  bool notification_returned() const {
    DCHECK_CURRENTLY_ON(BrowserThread::UI);
    return armed_ && !rejected_ && notification_returned_ &&
           !expected_partition_ && !on_notification_returned_;
  }

  void Cancel() {
    DCHECK_CURRENTLY_ON(BrowserThread::UI);
    if (!armed_ || notification_returned_) {
      return;
    }

    expected_partition_ = nullptr;
    on_notification_returned_.Reset();
    rejected_ = true;
  }

 private:
  raw_ptr<StoragePartition> expected_partition_ = nullptr;
  base::OnceClosure on_notification_returned_;
  bool armed_ = false;
  bool notification_returned_ = false;
  bool rejected_ = false;
};

WasmStoragePartitionShutdownNotificationState& GetNotificationState() {
  static base::NoDestructor<WasmStoragePartitionShutdownNotificationState>
      state;
  return *state;
}

}  // namespace

bool ArmWasmStoragePartitionShutdownNotificationForTest(
    StoragePartition* expected_partition,
    base::OnceClosure on_notification_returned) {
  return GetNotificationState().Arm(expected_partition,
                                    std::move(on_notification_returned));
}

bool DidWasmStoragePartitionShutdownNotificationForTest() {
  return GetNotificationState().notification_returned();
}

void CancelWasmStoragePartitionShutdownNotificationForTest() {
  GetNotificationState().Cancel();
}

bool ShutdownWasmStoragePartitionIndexedDBForTest(
    StoragePartition* partition,
    base::OnceClosure on_closed) {
  DCHECK_CURRENTLY_ON(BrowserThread::UI);
  if (!partition || !on_closed) {
    return false;
  }

  // IndexedDBContextImpl resolves its close callback on its own sequence.
  // Preserve the caller's UI-sequence ownership boundary before the probe can
  // touch the BrowserContext again.
  return static_cast<StoragePartitionImpl*>(partition)
      ->ShutdownIndexedDBForWasmTest(base::BindPostTask(
          base::SequencedTaskRunner::GetCurrentDefault(),
          std::move(on_closed)));
}

namespace internal {

void NotifyWasmStoragePartitionShutdownNotificationReturnedForTest(
    StoragePartition* partition) {
  GetNotificationState().NotifyReturned(partition);
}

}  // namespace internal

}  // namespace content
