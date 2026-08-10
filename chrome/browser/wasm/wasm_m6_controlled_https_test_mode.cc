// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_m6_controlled_https_test_mode.h"

#include <atomic>

#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_m6_controlled_https_test_mode.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

std::atomic_bool& ControlledHttpsTestModeEnabled() {
  static std::atomic_bool enabled(false);
  return enabled;
}

}  // namespace

void EnableWasmM6ControlledHttpsTestMode() {
  ControlledHttpsTestModeEnabled().store(true, std::memory_order_release);
}

bool IsWasmM6ControlledHttpsTestModeEnabled() {
  return ControlledHttpsTestModeEnabled().load(std::memory_order_acquire);
}

}  // namespace chrome
