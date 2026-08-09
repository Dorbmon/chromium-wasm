// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_version_theme_source.h"

#include <string>
#include <utility>

#include "base/check.h"
#include "base/memory/ref_counted_memory.h"
#include "build/build_config.h"
#include "chrome/grit/theme_resources.h"
#include "components/grit/components_scaled_resources.h"
#include "content/public/browser/url_data_source.h"
#include "content/public/common/url_constants.h"
#include "ui/base/resource/resource_bundle.h"
#include "ui/base/resource/resource_scale_factor.h"
#include "ui/base/webui/web_ui_util.h"
#include "url/gurl.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_version_theme_source.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kWasmThemeHost[] = "theme";

int ResourceForVersionThemePath(const std::string& path) {
  if (path == "current-channel-logo") {
    // The selected Wasm resource packs carry the product's base logo. Channel
    // variants require the broader channel/theme stack and are intentionally
    // not implied by this first static source.
    return IDR_PRODUCT_LOGO_32;
  }
  if (path == "IDR_PRODUCT_LOGO") {
    return IDR_PRODUCT_LOGO;
  }
  if (path == "IDR_PRODUCT_LOGO_WHITE") {
    return IDR_PRODUCT_LOGO_WHITE;
  }
  return -1;
}

}  // namespace

WasmVersionThemeSource::WasmVersionThemeSource() = default;

WasmVersionThemeSource::~WasmVersionThemeSource() = default;

std::string WasmVersionThemeSource::GetSource() {
  return kWasmThemeHost;
}

void WasmVersionThemeSource::StartDataRequest(
    const GURL& url,
    const content::WebContents::Getter& /*wc_getter*/,
    GotDataCallback callback) {
  CHECK(url.SchemeIs(content::kChromeUIScheme));
  CHECK_EQ(url.host(), kWasmThemeHost);

  std::string path;
  float scale = 1.0f;
  int frame = -1;
  webui::ParsePathAndImageSpec(url, &path, &scale, &frame);
  const int resource_id = ResourceForVersionThemePath(path);
  if (resource_id == -1 || frame > 0) {
    std::move(callback).Run(nullptr);
    return;
  }

  std::move(callback).Run(
      ui::ResourceBundle::GetSharedInstance().LoadDataResourceBytesForScale(
          resource_id, ui::GetSupportedResourceScaleFactor(scale)));
}

std::string WasmVersionThemeSource::GetMimeType(const GURL& /*url*/) {
  return "image/png";
}

}  // namespace chrome
