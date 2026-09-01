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

}  // namespace chrome
