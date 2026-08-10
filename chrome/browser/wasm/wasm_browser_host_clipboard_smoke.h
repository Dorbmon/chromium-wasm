// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_HOST_CLIPBOARD_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_HOST_CLIPBOARD_SMOKE_H_

#include "base/functional/callback.h"

namespace chrome {

// Installs the switch-gated observer-only verifier for the trusted-DOM host
// clipboard smoke. The exported ordinal can inspect only lifecycle-owned
// effects of ordinary Ozone input; it cannot set text, invoke a Browser
// command, choose clipboard data, or navigate.
void SetWasmBrowserHostClipboardSmokeVerificationForTesting(
    base::RepeatingCallback<bool(int)> check_callback);

// Invalidates queued exported checks before Browser or Ozone teardown.
void ClearWasmBrowserHostClipboardSmokeVerificationForTesting();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_HOST_CLIPBOARD_SMOKE_H_
