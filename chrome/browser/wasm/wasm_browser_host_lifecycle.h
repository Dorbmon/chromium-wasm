// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_HOST_LIFECYCLE_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_HOST_LIFECYCLE_H_

#include "base/functional/callback.h"

namespace chrome {

// Installs the Chrome-owned, one-shot host shutdown bridge for the ordinary
// Wasm Browser lifecycle. The exported host ABI only asks browser-main to
// begin its already-owned shutdown sequence; it never exposes Browser,
// WebContents, or a window pointer to JavaScript.
//
// This is deliberately separate from wasm_browser_host_input: physical input
// admission and browser lifecycle control have independent authority and
// teardown boundaries.
bool InitializeWasmBrowserHostLifecycle(
    base::RepeatingClosure request_shutdown);

// Invalidates queued shutdown requests before browser-main releases Ozone,
// the profile, and the callback target. Safe after failed initialization.
void ShutdownWasmBrowserHostLifecycle();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_HOST_LIFECYCLE_H_
