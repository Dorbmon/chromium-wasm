// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_SMOKE_H_

class WasmProfile;

namespace chrome {

// Exercises the first real manager-owned Wasm Browser: its BrowserWindow
// factory, selected BrowserWindowFeatures, bounded two-tab model/view
// transitions, real chrome://version navigation, and ordered
// BrowserWindowDeleter/manager close path. This remains a no-unload/no-modal
// smoke, not ordinary Chrome startup.
bool RunWasmBrowserSmoke(WasmProfile* profile);

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_SMOKE_H_
