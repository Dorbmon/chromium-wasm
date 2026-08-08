// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_VIEW_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_VIEW_SMOKE_H_

class WasmProfile;

namespace chrome {

// Runs the explicitly opt-in structural BrowserView/BrowserWidget proof. It
// creates no Browser or BrowserWindowFeatures and owns the one WebContents
// outside BrowserView, then tears the Widget down through the client-owned
// Views ownership path before returning.
bool RunWasmBrowserViewSmoke(WasmProfile* profile);

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_VIEW_SMOKE_H_
