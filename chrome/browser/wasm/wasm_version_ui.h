// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_VERSION_UI_H_
#define CHROME_BROWSER_WASM_WASM_VERSION_UI_H_

namespace chrome {

// Adds the one source-selected VersionUI configuration before any Wasm
// Browser/WebContents is created. It is deliberately idempotent because the
// WebUIConfigMap is process-global for the lifetime of the browser process.
void EnsureWasmVersionWebUIConfigRegistered();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_VERSION_UI_H_
