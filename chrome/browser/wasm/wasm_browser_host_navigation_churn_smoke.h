// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_HOST_NAVIGATION_CHURN_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_HOST_NAVIGATION_CHURN_SMOKE_H_

#include "base/functional/callback.h"

namespace chrome {

// Installs the fixed-ordinal presentation verifier for the M9 same-instance
// navigation-churn smoke. JavaScript can only report a later Canvas2D
// backing-store copy after C++ has independently committed, title-checked,
// history-checked, RFH-checked, and FVP-checked a fixed native `data:`
// navigation. It cannot select URLs, start navigations, or issue Browser
// commands through this ABI.
void SetWasmBrowserHostNavigationChurnSmokeVerificationForTesting(
    base::RepeatingCallback<bool(int)> backing_store_copy_callback);

// Invalidates pending host reports before Browser or Ozone teardown. Safe
// before installation, after completion, and after a malformed report.
void ClearWasmBrowserHostNavigationChurnSmokeVerificationForTesting();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_HOST_NAVIGATION_CHURN_SMOKE_H_
