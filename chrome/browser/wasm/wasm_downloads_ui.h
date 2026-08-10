// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_DOWNLOADS_UI_H_
#define CHROME_BROWSER_WASM_WASM_DOWNLOADS_UI_H_

#include "content/public/browser/web_ui_controller.h"
#include "content/public/browser/webui_config.h"

class GURL;

namespace chrome {

// A root-only unavailable-status WebUI. It deliberately exposes neither a
// DownloadManager, a synthetic download row, nor an action surface until M7
// supplies an OPFS/export DownloadManagerDelegate.
class WasmDownloadsUI final : public content::WebUIController {
 public:
  explicit WasmDownloadsUI(content::WebUI* web_ui);
  WasmDownloadsUI(const WasmDownloadsUI&) = delete;
  WasmDownloadsUI& operator=(const WasmDownloadsUI&) = delete;
  ~WasmDownloadsUI() override;

  WEB_UI_CONTROLLER_TYPE_DECL();
};

class WasmDownloadsUIConfig final
    : public content::DefaultWebUIConfig<WasmDownloadsUI> {
 public:
  WasmDownloadsUIConfig();
  WasmDownloadsUIConfig(const WasmDownloadsUIConfig&) = delete;
  WasmDownloadsUIConfig& operator=(const WasmDownloadsUIConfig&) = delete;
  ~WasmDownloadsUIConfig() override;

  bool ShouldHandleURL(const GURL& url) override;
};

void EnsureWasmDownloadsWebUIConfigRegistered();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_DOWNLOADS_UI_H_
