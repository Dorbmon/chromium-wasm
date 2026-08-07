// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_GLOBAL_BROWSER_COLLECTION_H_
#define CHROME_BROWSER_WASM_WASM_GLOBAL_BROWSER_COLLECTION_H_

class GlobalBrowserCollection;

// The desktop browser process owns GlobalBrowserCollection through
// GlobalFeatures. The source-selected Wasm process owns the same real
// collection directly, so this narrowly scoped registration bridge preserves
// the public GlobalBrowserCollection::GetInstance() API without initializing
// desktop GlobalFeatures.
void RegisterWasmGlobalBrowserCollection(
    GlobalBrowserCollection* global_browser_collection);
void UnregisterWasmGlobalBrowserCollection(
    GlobalBrowserCollection* global_browser_collection);
GlobalBrowserCollection* GetWasmGlobalBrowserCollection();

#endif  // CHROME_BROWSER_WASM_WASM_GLOBAL_BROWSER_COLLECTION_H_
