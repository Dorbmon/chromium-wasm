// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CONTENT_BROWSER_WASM_STORAGE_PARTITION_SHUTDOWN_TEST_SUPPORT_H_
#define CONTENT_BROWSER_WASM_STORAGE_PARTITION_SHUTDOWN_TEST_SUPPORT_H_

namespace content {

class StoragePartition;

namespace internal {

// Called inline only after the real
// StoragePartitionImpl::OnBrowserContextWillBeDestroyed() returns.
void NotifyWasmStoragePartitionShutdownNotificationReturnedForTest(
    StoragePartition* partition);

}  // namespace internal

}  // namespace content

#endif  // CONTENT_BROWSER_WASM_STORAGE_PARTITION_SHUTDOWN_TEST_SUPPORT_H_
