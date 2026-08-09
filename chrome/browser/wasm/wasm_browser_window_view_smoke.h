// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_WINDOW_VIEW_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_WINDOW_VIEW_SMOKE_H_

class WasmProfile;

namespace chrome {

// Runs the opt-in one-tab bridge between the source-selected
// BrowserWindowInterface model and the structural Wasm BrowserView. This is
// not Browser::Create(): it admits no Browser-backed window ownership, modal
// delegate, navigation, or host-close lifecycle.
bool RunWasmBrowserWindowViewSmoke(WasmProfile* profile);

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_WINDOW_VIEW_SMOKE_H_
