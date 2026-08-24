// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_READINESS_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_READINESS_H_

namespace chrome {

// Reports that a Browser-owned, source-selected Wasm BrowserView has been
// shown with its Chrome controls and selected WebContents attached. This does
// not report Ozone canvas presentation or document paint readiness; those are
// independently owned by the Ozone bridge and WebContents paint observer.
bool ReportWasmBrowserShellReady();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_READINESS_H_
