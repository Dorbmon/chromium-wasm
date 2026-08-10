// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_M6_CONTROLLED_HTTPS_TEST_MODE_H_
#define CHROME_BROWSER_WASM_WASM_M6_CONTROLLED_HTTPS_TEST_MODE_H_

namespace chrome {

// Marks this process as the dedicated controlled-M6 HTTPS test executable.
// The test-only entry point calls this only after it installs Chromium's local
// test root and before ContentMain. Production chrome_wasm retains this false,
// so it rejects the corresponding smoke switch before creating a Browser.
void EnableWasmM6ControlledHttpsTestMode();

// Returns whether the test-only entry point registered the process before
// browser-main startup. This is deliberately a process-level capability, not
// a command-line switch: the switch alone must never enable local test trust.
bool IsWasmM6ControlledHttpsTestModeEnabled();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_M6_CONTROLLED_HTTPS_TEST_MODE_H_
