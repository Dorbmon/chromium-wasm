// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_BOOKMARK_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_BOOKMARK_SMOKE_H_

#include "base/files/file_path.h"
#include "base/functional/callback_forward.h"
#include "chrome/browser/wasm/wasm_profile_preferences_smoke.h"

namespace chrome {

// Starts the source-selected BookmarkModel persistence witness selected by the
// optional Preferences acceptance argument. The completion runs on the
// initiating UI sequence only after the model's result-bearing local write and
// its direct destruction. It reports only the bounded digest-derived
// read/write/close result and never exposes a profile path, bookmark URL,
// title, or raw token.
bool StartWasmProfileBookmarkSmoke(
    base::FilePath profile_path,
    WasmProfilePreferencesBookmarkSmokeInput input,
    base::OnceCallback<void(bool success)> completion);

// True only after the enabled test-only BookmarkModel witness completed its
// local validation, result-bearing clear-text write, and direct model
// destruction successfully.
bool DidWasmProfileBookmarkSmokeSucceed();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_PROFILE_BOOKMARK_SMOKE_H_
