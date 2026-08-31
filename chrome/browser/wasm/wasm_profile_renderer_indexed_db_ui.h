// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_RENDERER_INDEXED_DB_UI_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_RENDERER_INDEXED_DB_UI_H_

#include "content/public/browser/web_ui_controller.h"
#include "content/public/browser/webui_config.h"

class GURL;

namespace chrome {

// The test-only chrome://m7-indexed-db document is intentionally limited to
// the source-selected M7 IndexedDB artifact. Its external script performs one
// real IndexedDB write or reopen/read/write operation in the renderer's normal
// WebUI world; the browser-side smoke observes only the fixed title completion
// and the RenderFrameHost's actual StorageKey.
class WasmProfileRendererIndexedDBUI final : public content::WebUIController {
 public:
  explicit WasmProfileRendererIndexedDBUI(content::WebUI* web_ui);
  WasmProfileRendererIndexedDBUI(const WasmProfileRendererIndexedDBUI&) =
      delete;
  WasmProfileRendererIndexedDBUI& operator=(
      const WasmProfileRendererIndexedDBUI&) = delete;
  ~WasmProfileRendererIndexedDBUI() override;

  WEB_UI_CONTROLLER_TYPE_DECL();
};

class WasmProfileRendererIndexedDBUIConfig final
    : public content::DefaultWebUIConfig<WasmProfileRendererIndexedDBUI> {
 public:
  WasmProfileRendererIndexedDBUIConfig();
  WasmProfileRendererIndexedDBUIConfig(
      const WasmProfileRendererIndexedDBUIConfig&) = delete;
  WasmProfileRendererIndexedDBUIConfig& operator=(
      const WasmProfileRendererIndexedDBUIConfig&) = delete;
  ~WasmProfileRendererIndexedDBUIConfig() override;

  bool ShouldHandleURL(const GURL& url) override;
};

// Registers the source-selected WebUI before the test creates its transient
// WebContents. The registry is process-global, so registration is idempotent.
void EnsureWasmProfileRendererIndexedDBWebUIConfigRegistered();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_PROFILE_RENDERER_INDEXED_DB_UI_H_
