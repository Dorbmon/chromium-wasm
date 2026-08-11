// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_HOST_STORAGE_ESTIMATE_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_HOST_STORAGE_ESTIMATE_SMOKE_H_

#include "base/functional/callback.h"

namespace chrome {

// Installs the fixed-ordinal verifier for the host-origin storage-estimate
// smoke. JavaScript can acknowledge only an already-delivered scalar result
// and a later compositor frame; the lifecycle keeps the fixed Settings URL,
// navigation, WebUI, snapshot, and shutdown authority.
void SetWasmBrowserHostStorageEstimateSmokeVerificationForTesting(
    base::RepeatingCallback<bool(int)> check_callback,
    base::RepeatingCallback<bool(int)> presentation_callback);

// Invalidates queued checks before Browser lifecycle or Ozone teardown. Safe
// before installation and after a failed smoke.
void ClearWasmBrowserHostStorageEstimateSmokeVerificationForTesting();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_HOST_STORAGE_ESTIMATE_SMOKE_H_
