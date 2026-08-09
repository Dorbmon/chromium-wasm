// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_WINDOW_VIEW_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_WINDOW_VIEW_SMOKE_H_

class WasmProfile;

namespace chrome {

// Runs the opt-in one-tab bridge between the source-selected
// BrowserWindowInterface model and the structural Wasm BrowserView. It commits
// two fixed data: documents in the selected tab, exercises the selected
// BrowserCommandController's back, forward, and reload operations, and
// temporarily drives one state-only WebContentsModalDialogManager through the
// existing BrowserView modal geometry. This is not Browser::Create(): it does
// not broaden the BrowserWindowInterface OpenURL/OpenGURL boundary,
// Browser-backed window ownership, a production modal delegate, or general
// host-close lifecycle, and it ends through one bounded no-unload close.
bool RunWasmBrowserWindowViewSmoke(WasmProfile* profile);

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_WINDOW_VIEW_SMOKE_H_
