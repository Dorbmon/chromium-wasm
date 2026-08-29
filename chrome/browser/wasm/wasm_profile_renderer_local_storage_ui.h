// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_RENDERER_LOCAL_STORAGE_UI_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_RENDERER_LOCAL_STORAGE_UI_H_

#include "content/public/browser/web_ui_controller.h"
#include "content/public/browser/webui_config.h"

class GURL;

namespace chrome {

// The test-only chrome://m7-local-storage document is intentionally limited to
// the source-selected M7 LocalStorage artifact. Its external script performs
// one window.localStorage write or reopen-read in the renderer's normal WebUI
// world; the browser-side smoke observes only the fixed title completion and
// the RenderFrameHost's actual StorageKey.
class WasmProfileRendererLocalStorageUI final
    : public content::WebUIController {
 public:
  explicit WasmProfileRendererLocalStorageUI(content::WebUI* web_ui);
  WasmProfileRendererLocalStorageUI(
      const WasmProfileRendererLocalStorageUI&) = delete;
  WasmProfileRendererLocalStorageUI& operator=(
      const WasmProfileRendererLocalStorageUI&) = delete;
  ~WasmProfileRendererLocalStorageUI() override;

  WEB_UI_CONTROLLER_TYPE_DECL();
};

class WasmProfileRendererLocalStorageUIConfig final
    : public content::DefaultWebUIConfig<WasmProfileRendererLocalStorageUI> {
 public:
  WasmProfileRendererLocalStorageUIConfig();
  WasmProfileRendererLocalStorageUIConfig(
      const WasmProfileRendererLocalStorageUIConfig&) = delete;
  WasmProfileRendererLocalStorageUIConfig& operator=(
      const WasmProfileRendererLocalStorageUIConfig&) = delete;
  ~WasmProfileRendererLocalStorageUIConfig() override;

  bool ShouldHandleURL(const GURL& url) override;
};

// Registers the source-selected WebUI before the test creates its transient
// WebContents. The registry is process-global, so registration is idempotent.
void EnsureWasmProfileRendererLocalStorageWebUIConfigRegistered();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_PROFILE_RENDERER_LOCAL_STORAGE_UI_H_
