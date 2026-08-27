// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_HISTORY_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_HISTORY_SMOKE_H_

#include "base/files/file_path.h"
#include "base/functional/callback_forward.h"

namespace chrome {

// Starts the test-only core HistoryService probe selected by the optional
// Preferences acceptance argument. The completion runs on the initiating UI
// sequence only after HistoryBackend has closed both History and Favicons.
// Its boolean reports the probe's fixed write/read result; it carries no path,
// database status, or opaque preference token.
bool StartWasmProfileHistorySmoke(
    base::FilePath profile_path,
    base::OnceCallback<void(bool success)> completion);

// True only after the enabled test-only HistoryService probe completed its
// query sequence and the HistoryBackend destruction callback confirmed its
// database-close boundary. BrowserMainParts uses this to withhold the V4
// profile-storage handoff after any history failure.
bool DidWasmProfileHistorySmokeSucceed();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_PROFILE_HISTORY_SMOKE_H_
