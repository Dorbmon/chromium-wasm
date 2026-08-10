// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_HOST_TEXT_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_HOST_TEXT_SMOKE_H_

#include "base/functional/callback.h"

namespace chrome {

// Installs the switch-gated observer-only verifier for the trusted DOM text
// smoke. The exported ordinal cannot set field text, invoke a command, or
// navigate: the Browser lifecycle inspects state produced by Ozone input.
void SetWasmBrowserHostTextSmokeVerificationForTesting(
    base::RepeatingCallback<bool(int)> check_callback);

// Invalidates queued exported checks before Browser or Ozone teardown.
void ClearWasmBrowserHostTextSmokeVerificationForTesting();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_HOST_TEXT_SMOKE_H_
