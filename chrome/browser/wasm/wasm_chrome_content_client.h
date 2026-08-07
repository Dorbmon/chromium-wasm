// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_CHROME_CONTENT_CLIENT_H_
#define CHROME_BROWSER_WASM_WASM_CHROME_CONTENT_CLIENT_H_

#include <string>
#include <string_view>

#include "content/public/common/content_client.h"

// The Chrome resource bridge used by the single-process Wasm embedding.
// Browser services such as plugins, CDMs, and origin trials are deliberately
// left at ContentClient's unsupported defaults until they have a web-backed
// implementation.
class WasmChromeContentClient final : public content::ContentClient {
 public:
  WasmChromeContentClient();
  WasmChromeContentClient(const WasmChromeContentClient&) = delete;
  WasmChromeContentClient& operator=(const WasmChromeContentClient&) = delete;
  ~WasmChromeContentClient() override;

  std::u16string GetLocalizedString(int message_id) override;
  std::u16string GetLocalizedString(int message_id,
                                    const std::u16string& replacement) override;
  bool HasDataResource(int resource_id) const override;
  std::string_view GetDataResource(
      int resource_id,
      ui::ResourceScaleFactor scale_factor) override;
  base::RefCountedMemory* GetDataResourceBytes(int resource_id) override;
  std::string GetDataResourceString(int resource_id) override;
  gfx::Image& GetNativeImageNamed(int resource_id) override;
};

#endif  // CHROME_BROWSER_WASM_WASM_CHROME_CONTENT_CLIENT_H_
