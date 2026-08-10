// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_HOST_POINTER_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_HOST_POINTER_H_

namespace chrome {

// Installs the Chrome-owned, trusted-host pointer bridge. The host-facing ABI
// admits only bounded physical-canvas mouse records plus a stateful native
// hover exit, dispatching through Ozone without exposing a Browser, View,
// WebContents, or generic UI command to JavaScript.
bool InitializeWasmBrowserHostPointer();

// Invalidates queued pointer records and releases the Ozone injector while
// Ozone is still alive. Safe after failed initialization.
void ShutdownWasmBrowserHostPointer();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_HOST_POINTER_H_
