// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_HOST_CLIPBOARD_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_HOST_CLIPBOARD_H_

#include "ui/gfx/native_ui_types.h"

namespace chrome {

// Initializes Chrome's narrow, one-way host clipboard import bridge while the
// UI sequence and ozone_wasm are live. It accepts only copied text/plain
// records from a trusted DOM paste event; it does not implement a platform
// clipboard, system-copy export, Browser command, or navigation API.
bool InitializeWasmBrowserHostClipboard();

// Invalidates queued paste imports and releases the Ozone injector while
// Ozone is still alive. Safe before a completed initialization and after a
// failed Browser lifecycle.
void ShutdownWasmBrowserHostClipboard();

// Browser lifecycle owns the one current BrowserView Ozone widget. The host
// never supplies a widget identifier, and target clear rejects any queued
// import before Aura or its TextInputClient can be destroyed.
bool SetWasmBrowserHostClipboardTarget(gfx::AcceleratedWidget widget);
void ClearWasmBrowserHostClipboardTarget();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_HOST_CLIPBOARD_H_
