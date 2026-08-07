// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_default_theme_provider.h"

#include <memory>

#include "build/build_config.h"
#include "chrome/browser/themes/theme_properties.h"
#include "ui/base/resource/resource_bundle.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_default_theme_provider.cc must only be built for WebAssembly"
#endif

WasmDefaultThemeProvider::WasmDefaultThemeProvider() = default;

WasmDefaultThemeProvider::~WasmDefaultThemeProvider() = default;

gfx::ImageSkia* WasmDefaultThemeProvider::GetImageSkiaNamed(int id) const {
  // ResourceBundle owns the returned image and diagnoses a missing required
  // Chrome resource rather than silently substituting an empty image.
  return ui::ResourceBundle::GetSharedInstance().GetImageSkiaNamed(id);
}

color_utils::HSL WasmDefaultThemeProvider::GetTint(int id) const {
  return ThemeProperties::GetDefaultTint(id, /*incognito=*/false,
                                         /*dark_mode=*/false);
}

int WasmDefaultThemeProvider::GetDisplayProperty(int id) const {
  return ThemeProperties::GetDefaultDisplayProperty(id);
}

bool WasmDefaultThemeProvider::ShouldUseNativeFrame() const {
  // The browser frame is rendered through Aura/Ozone into a host canvas.
  return false;
}

bool WasmDefaultThemeProvider::HasCustomImage(int id) const {
  // Profile-backed custom themes are intentionally outside this source slice.
  return false;
}

base::RefCountedMemory* WasmDefaultThemeProvider::GetRawData(
    int id,
    ui::ResourceScaleFactor scale_factor) const {
  // ResourceBundle preserves explicit absence with nullptr and resolves the
  // requested scale from the curated Wasm data packs.
  return ui::ResourceBundle::GetSharedInstance().LoadDataResourceBytesForScale(
      id, scale_factor);
}

std::unique_ptr<ui::ThemeProvider> CreateWasmDefaultThemeProvider() {
  return std::make_unique<WasmDefaultThemeProvider>();
}
