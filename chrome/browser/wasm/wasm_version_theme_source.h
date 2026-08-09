// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_VERSION_THEME_SOURCE_H_
#define CHROME_BROWSER_WASM_WASM_VERSION_THEME_SOURCE_H_

#include <string>

#include "content/public/browser/url_data_source.h"

namespace chrome {

// The first Wasm WebUI has no ThemeService, custom theme pack, or new-tab
// resource cache. VersionUI needs only its three static product-logo URLs, so
// serve those real bundled resources and reject every other chrome://theme
// request explicitly. A general ThemeSource remains a later Chrome UI slice.
class WasmVersionThemeSource final : public content::URLDataSource {
 public:
  WasmVersionThemeSource();
  WasmVersionThemeSource(const WasmVersionThemeSource&) = delete;
  WasmVersionThemeSource& operator=(const WasmVersionThemeSource&) = delete;
  ~WasmVersionThemeSource() override;

  // content::URLDataSource:
  std::string GetSource() override;
  void StartDataRequest(const GURL& url,
                        const content::WebContents::Getter& wc_getter,
                        GotDataCallback callback) override;
  std::string GetMimeType(const GURL& url) override;
};

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_VERSION_THEME_SOURCE_H_
