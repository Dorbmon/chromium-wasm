// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef UI_GFX_FONT_UTIL_WASM_H_
#define UI_GFX_FONT_UTIL_WASM_H_

namespace gfx {

// Installs the deterministic bundled Wasm font manager. This must be called
// before any access to skia::DefaultFontMgr().
void InitializeFontsWasm();

}  // namespace gfx

#endif  // UI_GFX_FONT_UTIL_WASM_H_
