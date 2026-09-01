// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_persistent_default_partition_shutdown_probe.h"

#include "testing/gtest/include/gtest/gtest.h"

namespace chrome {

TEST(WasmPersistentDefaultPartitionShutdownProbeTest,
     AcceptsOnlyOneRealPersistentDefaultPartition) {
  EXPECT_TRUE(IsWasmPersistentDefaultPartitionStructuralWitness(
      /*is_default=*/true, /*in_memory=*/false,
      /*partition_present=*/true, /*partition_path_matches_profile=*/true,
      /*loaded_partition_count=*/1));
  EXPECT_FALSE(IsWasmPersistentDefaultPartitionStructuralWitness(
      /*is_default=*/true, /*in_memory=*/true,
      /*partition_present=*/true, /*partition_path_matches_profile=*/true,
      /*loaded_partition_count=*/1));
  EXPECT_FALSE(IsWasmPersistentDefaultPartitionStructuralWitness(
      /*is_default=*/false, /*in_memory=*/false,
      /*partition_present=*/true, /*partition_path_matches_profile=*/true,
      /*loaded_partition_count=*/1));
  EXPECT_FALSE(IsWasmPersistentDefaultPartitionStructuralWitness(
      /*is_default=*/true, /*in_memory=*/false,
      /*partition_present=*/false, /*partition_path_matches_profile=*/true,
      /*loaded_partition_count=*/1));
  EXPECT_FALSE(IsWasmPersistentDefaultPartitionStructuralWitness(
      /*is_default=*/true, /*in_memory=*/false,
      /*partition_present=*/true, /*partition_path_matches_profile=*/false,
      /*loaded_partition_count=*/1));
  EXPECT_FALSE(IsWasmPersistentDefaultPartitionStructuralWitness(
      /*is_default=*/true, /*in_memory=*/false,
      /*partition_present=*/true, /*partition_path_matches_profile=*/true,
      /*loaded_partition_count=*/2));
}

TEST(WasmPersistentDefaultPartitionShutdownProbeTest,
     AcceptsOnlyAnAbsentPartitionMapAfterShutdown) {
  EXPECT_TRUE(IsWasmPersistentDefaultPartitionMapDropped(
      /*has_partition_map=*/false,
      /*loaded_partition_count=*/0));
  EXPECT_FALSE(IsWasmPersistentDefaultPartitionMapDropped(
      /*has_partition_map=*/true,
      /*loaded_partition_count=*/0));
  EXPECT_FALSE(IsWasmPersistentDefaultPartitionMapDropped(
      /*has_partition_map=*/false,
      /*loaded_partition_count=*/1));
}

TEST(WasmPersistentDefaultPartitionShutdownProbeTest,
     RequiresTheExactNotificationBeforeMapDrop) {
  EXPECT_TRUE(IsWasmPersistentDefaultPartitionShutdownNotificationWitness(
      /*notification_armed=*/true,
      /*notification_dispatched=*/true,
      /*content_notification_returned=*/true));
  EXPECT_FALSE(IsWasmPersistentDefaultPartitionShutdownNotificationWitness(
      /*notification_armed=*/false,
      /*notification_dispatched=*/true,
      /*content_notification_returned=*/true));
  EXPECT_FALSE(IsWasmPersistentDefaultPartitionShutdownNotificationWitness(
      /*notification_armed=*/true,
      /*notification_dispatched=*/false,
      /*content_notification_returned=*/true));
  EXPECT_FALSE(IsWasmPersistentDefaultPartitionShutdownNotificationWitness(
      /*notification_armed=*/true,
      /*notification_dispatched=*/true,
      /*content_notification_returned=*/false));
}

TEST(WasmPersistentDefaultPartitionShutdownProbeTest,
     RequiresCookieWriteFlushSQLiteRowReadbackAndCloseReceipts) {
  EXPECT_TRUE(IsWasmPersistentDefaultPartitionCookieStoreReceiptWitness(
      /*cookie_write_accepted=*/true,
      /*cookie_store_flush_acknowledged=*/true,
      /*cookie_sqlite_row_readback_succeeded=*/true,
      /*cookie_store_close_acknowledged=*/true));
  EXPECT_FALSE(IsWasmPersistentDefaultPartitionCookieStoreReceiptWitness(
      /*cookie_write_accepted=*/false,
      /*cookie_store_flush_acknowledged=*/true,
      /*cookie_sqlite_row_readback_succeeded=*/true,
      /*cookie_store_close_acknowledged=*/true));
  EXPECT_FALSE(IsWasmPersistentDefaultPartitionCookieStoreReceiptWitness(
      /*cookie_write_accepted=*/true,
      /*cookie_store_flush_acknowledged=*/false,
      /*cookie_sqlite_row_readback_succeeded=*/true,
      /*cookie_store_close_acknowledged=*/true));
  EXPECT_FALSE(IsWasmPersistentDefaultPartitionCookieStoreReceiptWitness(
      /*cookie_write_accepted=*/true,
      /*cookie_store_flush_acknowledged=*/true,
      /*cookie_sqlite_row_readback_succeeded=*/false,
      /*cookie_store_close_acknowledged=*/true));
  EXPECT_FALSE(IsWasmPersistentDefaultPartitionCookieStoreReceiptWitness(
      /*cookie_write_accepted=*/true,
      /*cookie_store_flush_acknowledged=*/true,
      /*cookie_sqlite_row_readback_succeeded=*/true,
      /*cookie_store_close_acknowledged=*/false));
}

TEST(WasmPersistentDefaultPartitionShutdownProbeTest,
     RequiresBothSelectedOwnerReceipts) {
  EXPECT_TRUE(IsWasmPersistentDefaultPartitionSelectedOwnerReceiptWitness(
      /*local_storage_receipt_started=*/true,
      /*local_storage_on_disk_commit_and_close_acknowledged=*/true,
      /*cookie_write_accepted=*/true,
      /*cookie_store_flush_acknowledged=*/true,
      /*cookie_sqlite_row_readback_succeeded=*/true,
      /*cookie_store_close_acknowledged=*/true));
  EXPECT_FALSE(IsWasmPersistentDefaultPartitionSelectedOwnerReceiptWitness(
      /*local_storage_receipt_started=*/false,
      /*local_storage_on_disk_commit_and_close_acknowledged=*/true,
      /*cookie_write_accepted=*/true,
      /*cookie_store_flush_acknowledged=*/true,
      /*cookie_sqlite_row_readback_succeeded=*/true,
      /*cookie_store_close_acknowledged=*/true));
  EXPECT_FALSE(IsWasmPersistentDefaultPartitionSelectedOwnerReceiptWitness(
      /*local_storage_receipt_started=*/true,
      /*local_storage_on_disk_commit_and_close_acknowledged=*/false,
      /*cookie_write_accepted=*/true,
      /*cookie_store_flush_acknowledged=*/true,
      /*cookie_sqlite_row_readback_succeeded=*/true,
      /*cookie_store_close_acknowledged=*/true));
  EXPECT_FALSE(IsWasmPersistentDefaultPartitionSelectedOwnerReceiptWitness(
      /*local_storage_receipt_started=*/true,
      /*local_storage_on_disk_commit_and_close_acknowledged=*/true,
      /*cookie_write_accepted=*/false,
      /*cookie_store_flush_acknowledged=*/true,
      /*cookie_sqlite_row_readback_succeeded=*/true,
      /*cookie_store_close_acknowledged=*/true));
}

}  // namespace chrome
