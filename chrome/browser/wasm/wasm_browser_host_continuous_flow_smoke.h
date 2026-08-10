// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_HOST_CONTINUOUS_FLOW_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_HOST_CONTINUOUS_FLOW_SMOKE_H_

#include "base/functional/callback.h"

namespace chrome {

// Installs the fixed-ordinal verifier for the one-Browser M6 acceptance flow.
// JavaScript can report only that a preceding trusted DOM/Ozone action has
// completed or that a canvas frame was presented. The coordinator retains all
// Browser, WebContents, Views, and navigation state, so this test-only bridge
// is not a command or navigation API.
void SetWasmBrowserHostContinuousFlowSmokeVerificationForTesting(
    bool restart_only,
    base::RepeatingCallback<bool(int)> check_callback,
    base::RepeatingCallback<bool(int)> presentation_callback);

// Invalidates queued exported work before the Browser lifecycle or Ozone
// teardown. Safe before installation and after a failed smoke.
void ClearWasmBrowserHostContinuousFlowSmokeVerificationForTesting();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_HOST_CONTINUOUS_FLOW_SMOKE_H_
