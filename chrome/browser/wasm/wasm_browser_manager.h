// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_MANAGER_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_MANAGER_H_

// Registers the source-selected browser keyed-service factories before a
// WasmProfile is constructed. Profile's base constructor marks its browser
// context live, after which adding a BrowserContextKeyedServiceFactory is not
// safe.
void EnsureWasmBrowserKeyedServiceFactoriesBuilt();

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_MANAGER_H_
