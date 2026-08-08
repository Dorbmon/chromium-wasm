// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_TAB_CORE_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_TAB_CORE_SMOKE_H_

class WasmProfile;

namespace chrome {

// Runs one bounded, process-local tab-core construction proof against the
// already-live Wasm browser profile. It deliberately creates neither a
// Browser nor a BrowserWindowInterface and returns before the normal M6
// foundation branch reports its explicit unsupported result.
bool RunWasmTabCoreSmoke(WasmProfile* profile);

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_TAB_CORE_SMOKE_H_
