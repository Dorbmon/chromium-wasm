// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_M6_TEST_TRUST_H_
#define CHROME_BROWSER_WASM_WASM_M6_TEST_TRUST_H_

namespace chrome {

// Adds Chromium's local test root to the verifier for the lifetime of the
// dedicated controlled-M6 HTTPS test executable. Production Wasm Chrome never
// links or calls this test-only hook.
void InstallWasmM6TestTrustRoot();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_M6_TEST_TRUST_H_
