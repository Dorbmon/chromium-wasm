// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_SETTINGS_UI_H_
#define CHROME_BROWSER_WASM_WASM_SETTINGS_UI_H_

#include "content/public/browser/web_ui_controller.h"
#include "content/public/browser/webui_config.h"

class GURL;

namespace chrome {

// A deliberately small, source-selected chrome://settings bootstrap. This is
// not Chrome's desktop SettingsUI: it installs no settings handlers, does not
// read or write preferences, and exposes no profile-mutating controls. Its
// static status document gives the M6 browser a real WebUI destination while
// the complete settings graph remains unavailable.
class WasmSettingsUI final : public content::WebUIController {
 public:
  explicit WasmSettingsUI(content::WebUI* web_ui);
  WasmSettingsUI(const WasmSettingsUI&) = delete;
  WasmSettingsUI& operator=(const WasmSettingsUI&) = delete;
  ~WasmSettingsUI() override;

  WEB_UI_CONTROLLER_TYPE_DECL();
};

// Keeps chrome://settings in the Wasm-owned WebUI registry instead of pulling
// Chrome's desktop settings config, handlers, resources, or platform services
// into the M6 source closure.
class WasmSettingsUIConfig final
    : public content::DefaultWebUIConfig<WasmSettingsUI> {
 public:
  WasmSettingsUIConfig();
  WasmSettingsUIConfig(const WasmSettingsUIConfig&) = delete;
  WasmSettingsUIConfig& operator=(const WasmSettingsUIConfig&) = delete;
  ~WasmSettingsUIConfig() override;

  // Only the static document root belongs to this bootstrap. Full Settings
  // subroutes must wait for the complete source-selected settings graph.
  bool ShouldHandleURL(const GURL& url) override;
};

// Adds the source-selected Wasm settings configuration before WebContents can
// navigate to chrome://settings. WebUIConfigMap is process-global, so this is
// intentionally idempotent for the browser-process lifetime.
void EnsureWasmSettingsWebUIConfigRegistered();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_SETTINGS_UI_H_
