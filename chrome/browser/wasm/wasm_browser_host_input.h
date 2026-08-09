// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_HOST_INPUT_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_HOST_INPUT_H_

#include "base/functional/callback.h"

namespace chrome {

// Installs the Chrome-owned, physical-key-only SystemInputInjector bridge.
// This is deliberately independent of Content Shell's host test ABI: it
// admits only the accelerator chord keys selected by the first Wasm Browser
// View and never synthesizes text, pointer, or generic DOM input.
bool InitializeWasmBrowserHostInput();

// Invalidates queued host work and releases the Ozone injector while Ozone is
// still alive. It is safe to call if initialization did not complete.
void ShutdownWasmBrowserHostInput();

// Switch-gated runtime verification hook. The host-side C ABI may ask the UI
// sequence to evaluate |verifier| after its posted physical key records. If
// it succeeds, |verified_callback| runs once on the UI sequence. Production
// code must not use this as a command or navigation API.
void SetWasmBrowserHostAcceleratorVerificationForTesting(
    base::RepeatingCallback<bool()> verifier,
    base::OnceClosure verified_callback);
void ClearWasmBrowserHostAcceleratorVerificationForTesting();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_HOST_INPUT_H_
