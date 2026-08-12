// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_HOST_TAB_CHURN_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_HOST_TAB_CHURN_SMOKE_H_

#include "base/functional/callback.h"

namespace chrome {

// Installs the fixed-ordinal verifier for the M9 same-instance tab-churn
// smoke. JavaScript can only report that a previously delivered trusted
// pointer action and its later Canvas2D backing-store copy were observed. It
// does not prove raster, compositor, display, or vsync presentation, and it
// cannot create, select, close, or navigate tabs through this ABI.
void SetWasmBrowserHostTabChurnSmokeVerificationForTesting(
    base::RepeatingCallback<bool(int)> check_callback,
    base::RepeatingCallback<bool(int)> backing_store_copy_callback);

// Invalidates pending host reports before Browser or Ozone teardown. Safe
// before installation, after completion, and after a malformed report.
void ClearWasmBrowserHostTabChurnSmokeVerificationForTesting();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_HOST_TAB_CHURN_SMOKE_H_
