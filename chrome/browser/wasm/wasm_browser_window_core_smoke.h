// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_WINDOW_CORE_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_WINDOW_CORE_SMOKE_H_

class WasmProfile;

namespace chrome {

// Runs an opt-in ownership proof for an empty BrowserWindowInterface owner.
// It does not create a Browser, BrowserView, WebContents, or BaseWindow.
bool RunWasmBrowserWindowCoreSmoke(WasmProfile* profile);

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_WINDOW_CORE_SMOKE_H_
