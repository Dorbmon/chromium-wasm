// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "content/test/wasm_mojo_core_test_support.h"

#include "mojo/core/embedder/embedder.h"

namespace content::test {

void InitializeMojoCoreForWasmTests() {
  static const bool initialized = [] {
    mojo::core::Init();
    return true;
  }();
  static_cast<void>(initialized);
}

}  // namespace content::test
