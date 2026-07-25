// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef UI_OZONE_PLATFORM_WASM_OZONE_PLATFORM_WASM_H_
#define UI_OZONE_PLATFORM_WASM_OZONE_PLATFORM_WASM_H_

namespace gfx {
class ClientNativePixmapFactory;
}

namespace ui {

class OzonePlatform;

// Constructor hook used by Ozone's generated platform list.
OzonePlatform* CreateOzonePlatformWasm();
gfx::ClientNativePixmapFactory* CreateClientNativePixmapFactoryWasm();

}  // namespace ui

#endif  // UI_OZONE_PLATFORM_WASM_OZONE_PLATFORM_WASM_H_
