// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_shutdown_failure_latch.h"

#include "build/build_config.h"
#include "testing/gtest/include/gtest/gtest.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_profile_shutdown_failure_latch_unittests must only be built for WebAssembly"
#endif

namespace chrome {
namespace {

class WasmProfileShutdownFailureLatchTest : public testing::Test {
 protected:
  void SetUp() override { ResetWasmProfileShutdownFailureLatch(); }

  void TearDown() override { ResetWasmProfileShutdownFailureLatch(); }
};

TEST_F(WasmProfileShutdownFailureLatchTest, ResetStartsClear) {
  EXPECT_FALSE(WasmProfileShutdownFailureWasRecorded());
}

TEST_F(WasmProfileShutdownFailureLatchTest, FailureRemainsStickyUntilReset) {
  RecordWasmProfileShutdownFailure();
  RecordWasmProfileShutdownFailure();

  EXPECT_TRUE(WasmProfileShutdownFailureWasRecorded());
}

TEST_F(WasmProfileShutdownFailureLatchTest, ResetClearsRecordedFailure) {
  RecordWasmProfileShutdownFailure();
  ASSERT_TRUE(WasmProfileShutdownFailureWasRecorded());

  ResetWasmProfileShutdownFailureLatch();

  EXPECT_FALSE(WasmProfileShutdownFailureWasRecorded());
}

}  // namespace
}  // namespace chrome
