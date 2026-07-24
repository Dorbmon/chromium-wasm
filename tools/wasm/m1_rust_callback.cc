// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "tools/wasm/m1_rust_callback.h"

#include <atomic>
#include <cstdint>

namespace chromium_wasm::rust_smoke {
namespace {

constexpr uint64_t kCallbackMask = UINT64_C(0xa5a55a5adeadbeef);
std::atomic<uint32_t> g_callback_count{0};

uint64_t RotateLeft13(uint64_t value) {
  return (value << 13) | (value >> (64 - 13));
}

}  // namespace

uint64_t RustSmokeCppCallback(uint64_t value, uint32_t worker_value) {
  const uint32_t callback_count =
      g_callback_count.fetch_add(1, std::memory_order_relaxed) + 1;
  return RotateLeft13(value) ^
         (static_cast<uint64_t>(worker_value) << 32) ^ kCallbackMask ^
         callback_count;
}

}  // namespace chromium_wasm::rust_smoke
