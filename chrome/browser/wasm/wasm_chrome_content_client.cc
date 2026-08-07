// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_chrome_content_client.h"

#include "build/build_config.h"
#include "ui/base/l10n/l10n_util.h"
#include "ui/base/resource/resource_bundle.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_chrome_content_client.cc must only be built for WebAssembly"
#endif

WasmChromeContentClient::WasmChromeContentClient() = default;

WasmChromeContentClient::~WasmChromeContentClient() = default;

std::u16string WasmChromeContentClient::GetLocalizedString(int message_id) {
  return l10n_util::GetStringUTF16(message_id);
}

std::u16string WasmChromeContentClient::GetLocalizedString(
    int message_id,
    const std::u16string& replacement) {
  return l10n_util::GetStringFUTF16(message_id, replacement);
}

bool WasmChromeContentClient::HasDataResource(int resource_id) const {
  return ui::ResourceBundle::GetSharedInstance().HasDataResource(resource_id);
}

std::string_view WasmChromeContentClient::GetDataResource(
    int resource_id,
    ui::ResourceScaleFactor scale_factor) {
  return ui::ResourceBundle::GetSharedInstance().GetRawDataResourceForScale(
      resource_id, scale_factor);
}

base::RefCountedMemory* WasmChromeContentClient::GetDataResourceBytes(
    int resource_id) {
  return ui::ResourceBundle::GetSharedInstance().LoadDataResourceBytes(
      resource_id);
}

std::string WasmChromeContentClient::GetDataResourceString(int resource_id) {
  return ui::ResourceBundle::GetSharedInstance().LoadDataResourceString(
      resource_id);
}

gfx::Image& WasmChromeContentClient::GetNativeImageNamed(int resource_id) {
  return ui::ResourceBundle::GetSharedInstance().GetNativeImageNamed(
      resource_id);
}
