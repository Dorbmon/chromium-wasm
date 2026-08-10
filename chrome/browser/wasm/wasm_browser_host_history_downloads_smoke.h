// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_HOST_HISTORY_DOWNLOADS_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_HOST_HISTORY_DOWNLOADS_SMOKE_H_

#include "base/functional/callback.h"

namespace chrome {

// Installs the switch-gated History/Downloads smoke verifier. Exported calls
// carry only a fixed ordinal and a presentation acknowledgement. The lifecycle
// retains all Browser, WebContents, journal, Views, and WebUI state, so host
// JavaScript cannot turn this test helper into a command or navigation API.
void SetWasmBrowserHostHistoryDownloadsSmokeVerificationForTesting(
    base::RepeatingCallback<bool(int)> check_callback,
    base::RepeatingCallback<bool(int)> presentation_callback);

// Invalidates queued exported work before Browser lifecycle or Ozone teardown.
// Safe before installation and after a failed smoke.
void ClearWasmBrowserHostHistoryDownloadsSmokeVerificationForTesting();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_HOST_HISTORY_DOWNLOADS_SMOKE_H_
