// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_HISTORY_UI_H_
#define CHROME_BROWSER_WASM_WASM_HISTORY_UI_H_

#include <cstddef>

#include "content/public/browser/web_ui_controller.h"
#include "content/public/browser/webui_config.h"

class GURL;

namespace chrome {

// A root-only, read-only view of WasmProfile's bounded in-memory navigation
// journal. This is deliberately not desktop HistoryUI or HistoryService: it
// has no search, deletion, sync, persistence, or browser-side mutation API.
class WasmHistoryUI final : public content::WebUIController {
 public:
  explicit WasmHistoryUI(content::WebUI* web_ui);
  WasmHistoryUI(const WasmHistoryUI&) = delete;
  WasmHistoryUI& operator=(const WasmHistoryUI&) = delete;
  ~WasmHistoryUI() override;

  // The browser smoke verifies that this controller was constructed from the
  // immutable profile-journal snapshot rather than a desktop HistoryService.
  size_t entry_count_for_testing() const { return entry_count_; }

  WEB_UI_CONTROLLER_TYPE_DECL();

 private:
  size_t entry_count_ = 0;
};

class WasmHistoryUIConfig final
    : public content::DefaultWebUIConfig<WasmHistoryUI> {
 public:
  WasmHistoryUIConfig();
  WasmHistoryUIConfig(const WasmHistoryUIConfig&) = delete;
  WasmHistoryUIConfig& operator=(const WasmHistoryUIConfig&) = delete;
  ~WasmHistoryUIConfig() override;

  bool ShouldHandleURL(const GURL& url) override;
};

// Registers only chrome://history/ in the Wasm-owned config map. Browser
// startup deliberately never registers the generic desktop WebUI configs,
// whose history host would conflict with this bounded bootstrap.
void EnsureWasmHistoryWebUIConfigRegistered();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_HISTORY_UI_H_
