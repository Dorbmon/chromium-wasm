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

}  // namespace content

#endif  // CONTENT_SHELL_BROWSER_WASM_HOST_API_H_
