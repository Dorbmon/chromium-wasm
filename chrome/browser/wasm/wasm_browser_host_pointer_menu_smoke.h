// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_HOST_POINTER_MENU_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_HOST_POINTER_MENU_SMOKE_H_

#include "base/functional/callback.h"

namespace chrome {

// Installs the switch-gated Menu -> Settings verifier used only by the real
// browser trusted-pointer smoke. The exported calls carry an ordinal only;
// they cannot open a menu, activate an item, or navigate a WebContents. The
// lifecycle owner independently verifies the Views, WebUI, and presentation
// state after the normal Ozone pointer path has run.
void SetWasmBrowserHostPointerMenuSmokeVerificationForTesting(
    base::RepeatingCallback<bool(int)> check_callback,
    base::RepeatingCallback<bool(int)> presentation_callback);

// Invalidates queued exported checks before Browser lifecycle or Ozone
// teardown. Safe before installation and after a failed smoke.
void ClearWasmBrowserHostPointerMenuSmokeVerificationForTesting();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_HOST_POINTER_MENU_SMOKE_H_
