// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CONTENT_SHELL_APP_WASM_M5_TEST_TRUST_H_
#define CONTENT_SHELL_APP_WASM_M5_TEST_TRUST_H_

namespace content {

// Adds the public certificate from Chromium's local test root to the test
// verifier for the lifetime of content_shell_wasm_m5_test. This is never used
// by the production Wasm Content Shell target.
void InstallWasmM5TestTrustRoot();

}  // namespace content

#endif  // CONTENT_SHELL_APP_WASM_M5_TEST_TRUST_H_
