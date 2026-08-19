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

// Navigates the visible address field to the one local HTTPS/H2 M6 fixture
// through a host-configured WISP transport. This is test-only: the dedicated
// executable installs Chromium's local test root, while production
// chrome_wasm never links that root or expands its certificate policy.
bool RunWasmBrowserControlledHttpsSmoke(WasmProfile* profile);

// Drives one test-only Chrome Browser through the normal Ozone address-field
// route to the fixed M9 WISP recovery document. The document deliberately
// loses its carrier while a fetch is active, then completes a fresh HTTP/2
// recovery request in the same Browser and WebContents before normal close.
// The dedicated M6 test executable is the only binary allowed to select this
// route because it installs the local fixture root before ContentMain.
bool RunWasmBrowserM9WispRecoverySmoke(WasmProfile* profile);

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_SMOKE_H_
