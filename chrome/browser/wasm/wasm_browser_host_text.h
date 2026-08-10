// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_HOST_TEXT_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_HOST_TEXT_H_

#include "ui/gfx/native_ui_types.h"

namespace chrome {

// Initializes the Chrome-owned committed-text bridge while the UI sequence
// and ozone_wasm are live. The exported ABI accepts one copied, bounded UTF-8
// record; it has no browser command, focus, selection, or navigation surface.
bool InitializeWasmBrowserHostText();

// Invalidates all queued text records before Ozone teardown. Safe before a
// completed initialization and after a failed Browser lifecycle.
void ShutdownWasmBrowserHostText();

// Binds the bridge to the one current BrowserView Ozone widget. The lifecycle
// owns this association and clears it before the Browser can be destroyed;
// host JavaScript never supplies an accelerated-widget identifier.
bool SetWasmBrowserHostTextTarget(gfx::AcceleratedWidget widget);
void ClearWasmBrowserHostTextTarget();

// Enables the focused host-text smoke's deterministic two-record burst gate.
// Production text delivery always starts dispatching after its first native
// reservation; the smoke arms this before it reports READY so two back-to-back
// trusted DOM insertText events are both admitted and token-bound before the
// first delivery acknowledgement can be observed.
bool ArmWasmBrowserHostTextSmokeTwoRecordBarrier();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_HOST_TEXT_H_
