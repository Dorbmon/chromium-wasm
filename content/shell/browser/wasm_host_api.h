// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CONTENT_SHELL_BROWSER_WASM_HOST_API_H_
#define CONTENT_SHELL_BROWSER_WASM_HOST_API_H_

namespace content {

// Registers the M3 host command queue and WebContents readiness observer on
// Chromium's UI sequence.
void InitializeWasmHostApi();
void ShutdownWasmHostApi();

// Enables the tightly scoped M5 network-test lane before ContentMain creates
// the Network Service. Only content_shell_wasm_m5_test invokes this; the
// regular Content Shell keeps its data:-only navigation boundary.
void EnableWasmM5NetworkTestModeForTesting();

// Enables the separate external/public HTTPS smoke lane before ContentMain
// creates the Network Service. Only content_shell_wasm_m5_public_test invokes
// this test-only mode; it never installs a local test root or broadens the
// regular Content Shell's data:-only navigation boundary.
void EnableWasmM5PublicNetworkTestModeForTesting();

}  // namespace content

#endif  // CONTENT_SHELL_BROWSER_WASM_HOST_API_H_
