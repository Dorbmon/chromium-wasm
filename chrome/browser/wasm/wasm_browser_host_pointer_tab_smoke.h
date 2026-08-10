// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_HOST_POINTER_TAB_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_HOST_POINTER_TAB_SMOKE_H_

#include "base/functional/callback.h"

namespace chrome {

// Installs the switch-gated tab-flow verifier used only by the real-browser
// trusted-pointer smoke. The exported checks carry an ordinal only; they
// cannot create, select, or close tabs. The lifecycle owner verifies the real
// model/View state after Ozone has delivered the trusted DOM input.
void SetWasmBrowserHostPointerTabSmokeVerificationForTesting(
    base::RepeatingCallback<bool(int)> check_callback,
    base::RepeatingCallback<bool(int)> presentation_callback);

// Invalidates queued exported checks before the Browser lifecycle or Ozone
// platform is torn down. Safe before installation and after a failed smoke.
void ClearWasmBrowserHostPointerTabSmokeVerificationForTesting();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_HOST_POINTER_TAB_SMOKE_H_
