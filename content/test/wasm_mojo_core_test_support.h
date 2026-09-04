// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CONTENT_TEST_WASM_MOJO_CORE_TEST_SUPPORT_H_
#define CONTENT_TEST_WASM_MOJO_CORE_TEST_SUPPORT_H_

namespace content::test {

// Initializes the Wasm Mojo embedder once for a test binary. The Wasm
// embedder rejects repeated Init() calls, so every fixture in a combined test
// binary must use this shared helper rather than a translation-unit local
// initializer.
void InitializeMojoCoreForWasmTests();

}  // namespace content::test

#endif  // CONTENT_TEST_WASM_MOJO_CORE_TEST_SUPPORT_H_
