// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_DEFAULT_THEME_PROVIDER_H_
#define CHROME_BROWSER_WASM_WASM_DEFAULT_THEME_PROVIDER_H_

#include <memory>

#include "ui/base/theme_provider.h"

// A fixed default Chrome theme for the Wasm embedding.  It intentionally has
// no profile, custom-theme supplier, system-theme integration, or change
// observation.  Callers must create it only after ResourceBundle has been
// initialized with the curated Wasm resources.
class WasmDefaultThemeProvider final : public ui::ThemeProvider {
 public:
  WasmDefaultThemeProvider();
  WasmDefaultThemeProvider(const WasmDefaultThemeProvider&) = delete;
  WasmDefaultThemeProvider& operator=(const WasmDefaultThemeProvider&) =
      delete;
  ~WasmDefaultThemeProvider() override;

  // ui::ThemeProvider:
  gfx::ImageSkia* GetImageSkiaNamed(int id) const override;
  color_utils::HSL GetTint(int id) const override;
  int GetDisplayProperty(int id) const override;
  bool ShouldUseNativeFrame() const override;
  bool HasCustomImage(int id) const override;
  base::RefCountedMemory* GetRawData(
      int id,
      ui::ResourceScaleFactor scale_factor) const override;
};

// Creates the fixed default provider used by a future source-selected Wasm
// BrowserWidget.  It is deliberately not wired into the browser lifecycle by
// this target.
std::unique_ptr<ui::ThemeProvider> CreateWasmDefaultThemeProvider();

#endif  // CHROME_BROWSER_WASM_WASM_DEFAULT_THEME_PROVIDER_H_
