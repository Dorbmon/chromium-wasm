// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_storage_drain_result.h"

#include "build/build_config.h"
#include "testing/gtest/include/gtest/gtest.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_profile_storage_drain_result_unittests must only be built for WebAssembly"
#endif

namespace chrome {
namespace {

WasmProfileStorageDrainResult CompleteDrainResult() {
  WasmProfileStorageDrainResult result;
  result.backend_sealed = true;
  result.lease_released = true;
  result.backend_retired = true;
  return result;
}

TEST(WasmProfileStorageDrainResultTest, DefaultResultFailsClosed) {
  EXPECT_FALSE(WasmProfileStorageDrainResult().Succeeded());
}

TEST(WasmProfileStorageDrainResultTest,
     InformationalDescriptorAccountingDoesNotFailADrain) {
  WasmProfileStorageDrainResult result = CompleteDrainResult();
  result.detached_descriptors = 3;
  result.data_file_states = 2;

  EXPECT_TRUE(result.Succeeded());
}

TEST(WasmProfileStorageDrainResultTest, ErrorFailsADrain) {
  WasmProfileStorageDrainResult result = CompleteDrainResult();
  result.error = -1;

  EXPECT_FALSE(result.Succeeded());
}

TEST(WasmProfileStorageDrainResultTest, PositiveErrorFailsADrain) {
  WasmProfileStorageDrainResult result = CompleteDrainResult();
  result.error = 1;

  EXPECT_FALSE(result.Succeeded());
}

TEST(WasmProfileStorageDrainResultTest, OutstandingProfileIORefusalFailsADrain) {
  WasmProfileStorageDrainResult result = CompleteDrainResult();
  result.refused_for_outstanding_profile_io = true;

  EXPECT_FALSE(result.Succeeded());
}

TEST(WasmProfileStorageDrainResultTest, LibcFlushFailureFailsADrain) {
  WasmProfileStorageDrainResult result = CompleteDrainResult();
  result.libc_flush_failed = 1;

  EXPECT_FALSE(result.Succeeded());
}

TEST(WasmProfileStorageDrainResultTest, DataFlushFailureFailsADrain) {
  WasmProfileStorageDrainResult result = CompleteDrainResult();
  result.data_flush_failures = 1;

  EXPECT_FALSE(result.Succeeded());
}

TEST(WasmProfileStorageDrainResultTest, DataCloseFailureFailsADrain) {
  WasmProfileStorageDrainResult result = CompleteDrainResult();
  result.data_close_failures = 1;

  EXPECT_FALSE(result.Succeeded());
}

TEST(WasmProfileStorageDrainResultTest, PriorCloseFailureFailsADrain) {
  WasmProfileStorageDrainResult result = CompleteDrainResult();
  result.prior_close_failures = 1;

  EXPECT_FALSE(result.Succeeded());
}

TEST(WasmProfileStorageDrainResultTest, LeaseReleaseFailureFailsADrain) {
  WasmProfileStorageDrainResult result = CompleteDrainResult();
  result.lease_release_failures = 1;

  EXPECT_FALSE(result.Succeeded());
}

TEST(WasmProfileStorageDrainResultTest, BackendRetirementFailureFailsADrain) {
  WasmProfileStorageDrainResult result = CompleteDrainResult();
  result.backend_retire_failures = 1;

  EXPECT_FALSE(result.Succeeded());
}

TEST(WasmProfileStorageDrainResultTest, UnsealedBackendFailsADrain) {
  WasmProfileStorageDrainResult result = CompleteDrainResult();
  result.backend_sealed = false;

  EXPECT_FALSE(result.Succeeded());
}

TEST(WasmProfileStorageDrainResultTest, UnreleasedLeaseFailsADrain) {
  WasmProfileStorageDrainResult result = CompleteDrainResult();
  result.lease_released = false;

  EXPECT_FALSE(result.Succeeded());
}

TEST(WasmProfileStorageDrainResultTest, UnretiredBackendFailsADrain) {
  WasmProfileStorageDrainResult result = CompleteDrainResult();
  result.backend_retired = false;

  EXPECT_FALSE(result.Succeeded());
}

}  // namespace
}  // namespace chrome
