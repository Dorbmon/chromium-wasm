// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_HOST_SECURITY_WARNING_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_HOST_SECURITY_WARNING_SMOKE_H_

#include "base/functional/callback.h"

namespace chrome {

// Installs the switch-gated security-warning verifier for the trusted-DOM
// host smoke. Its exports carry only fixed ordinals: Browser, menu, dialog,
// tab-model, and shutdown ownership remain entirely in C++.
void SetWasmBrowserHostSecurityWarningSmokeVerificationForTesting(
    base::RepeatingCallback<bool(int)> check_callback,
    base::RepeatingCallback<bool(int)> presentation_callback);

// Invalidates queued ordinal callbacks before Browser lifecycle or Ozone
// teardown. Safe before installation and after an incomplete host smoke.
void ClearWasmBrowserHostSecurityWarningSmokeVerificationForTesting();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_HOST_SECURITY_WARNING_SMOKE_H_
