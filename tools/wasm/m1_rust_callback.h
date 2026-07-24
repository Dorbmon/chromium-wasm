// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef TOOLS_WASM_M1_RUST_CALLBACK_H_
#define TOOLS_WASM_M1_RUST_CALLBACK_H_

#include <stdint.h>

namespace chromium_wasm::rust_smoke {

uint64_t RustSmokeCppCallback(uint64_t value, uint32_t worker_value);

}  // namespace chromium_wasm::rust_smoke

#endif  // TOOLS_WASM_M1_RUST_CALLBACK_H_
