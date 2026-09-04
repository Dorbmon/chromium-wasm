// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CONTENT_PUBLIC_BROWSER_WASM_STORAGE_PARTITION_SHUTDOWN_TEST_SUPPORT_H_
#define CONTENT_PUBLIC_BROWSER_WASM_STORAGE_PARTITION_SHUTDOWN_TEST_SUPPORT_H_

#include "base/functional/callback_forward.h"
#include "content/common/content_export.h"

namespace content {

class StoragePartition;

#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
// Arms one source-selected receipt for the exact StoragePartition whose real
// StoragePartitionImpl::OnBrowserContextWillBeDestroyed() call must return.
// The callback runs inline immediately after that real method returns. This is
// a structural shutdown observation only; it is not an asynchronous service
// close, durable-flush, or profile-persistence acknowledgement.
CONTENT_EXPORT bool ArmWasmStoragePartitionShutdownNotificationForTest(
    StoragePartition* expected_partition,
    base::OnceClosure on_notification_returned);

// Returns true only after the armed exact partition's destruction notification
// returned exactly once. This source-selected bridge has no normal-build
// declaration or behavior.
CONTENT_EXPORT bool
DidWasmStoragePartitionShutdownNotificationForTest();

// Disarms an armed witness after a probe failure. This leaves the structural
// receipt false and prevents a stale non-owning partition pointer from
// surviving an abnormal teardown path.
CONTENT_EXPORT void CancelWasmStoragePartitionShutdownNotificationForTest();

// Starts a result-bearing close of the exact partition's IndexedDB context.
// |on_closed| runs on the caller's sequence only after the helper has posted
// the IndexedDB-sequence completion back to it. The receipt covers all live
// buckets in that one context after their factory ingress is sealed and their
// destruction has completed; it does not cover LocalStorage, Cookies, or
// aggregate StoragePartition shutdown.
CONTENT_EXPORT bool ShutdownWasmStoragePartitionIndexedDBForTest(
    StoragePartition* partition,
    base::OnceClosure on_closed);
#endif

}  // namespace content

#endif  // CONTENT_PUBLIC_BROWSER_WASM_STORAGE_PARTITION_SHUTDOWN_TEST_SUPPORT_H_
