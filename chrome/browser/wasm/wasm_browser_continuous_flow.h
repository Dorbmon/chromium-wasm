// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_CONTINUOUS_FLOW_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_CONTINUOUS_FLOW_H_

#include <memory>

#include "base/functional/callback.h"
#include "base/memory/raw_ptr.h"
#include "base/timer/timer.h"

class Browser;

namespace content {
class WebContents;
}  // namespace content

namespace chrome {

class WasmBrowserContinuousNavigationObserver;

// UI-thread owner for the one-Browser M6 acceptance-flow smoke. It binds
// fixed native observers before publishing each dynamic Views target to the
// host, while the host supplies only trusted DOM key/text/pointer records via
// the existing Ozone bridges. It deliberately has no API that starts a
// navigation, creates a tab, selects a tab, or invokes a Browser command.
class WasmBrowserContinuousFlow final {
 public:
  WasmBrowserContinuousFlow(Browser* browser,
                           bool restart_only,
                           base::RepeatingClosure request_shutdown);
  WasmBrowserContinuousFlow(const WasmBrowserContinuousFlow&) = delete;
  WasmBrowserContinuousFlow& operator=(const WasmBrowserContinuousFlow&) =
      delete;
  ~WasmBrowserContinuousFlow();

  // Arms the verifier and publishes the first marker only after all initial
  // Browser/View/observer state is live on the UI thread.
  void Start();

 private:
  bool VerifyCheck(int stage);
  bool VerifyPresentation(int stage);
  void OnFirstHttpsNavigationObserved();
  void OnVersionNavigationObserved();
  void OnSettingsNavigationObserved();
  void OnReloadNavigationObserved();
  void ArmStepTimeout();
  void OnStepTimeout();
  void FailAndRequestOrderlyShutdown();
  void RequestOrderlyShutdown();

  const raw_ptr<Browser> browser_;
  const bool restart_only_;
  base::RepeatingClosure request_shutdown_;
  bool started_ = false;
  bool shutdown_requested_ = false;
  bool first_https_navigation_observed_ = false;
  bool second_tab_created_ = false;
  bool version_navigation_observed_ = false;
  bool first_tab_selected_ = false;
  bool second_tab_selected_ = false;
  bool menu_open_observed_ = false;
  bool settings_navigation_observed_ = false;
  bool first_tab_returned_ = false;
  bool second_tab_closed_ = false;
  bool reload_navigation_observed_ = false;
  bool final_presentation_observed_ = false;
  base::OneShotTimer step_timeout_;
  raw_ptr<content::WebContents> first_contents_ = nullptr;
  raw_ptr<content::WebContents> second_contents_ = nullptr;
  std::unique_ptr<WasmBrowserContinuousNavigationObserver>
      first_https_navigation_observer_;
  std::unique_ptr<WasmBrowserContinuousNavigationObserver>
      version_navigation_observer_;
  std::unique_ptr<WasmBrowserContinuousNavigationObserver>
      settings_navigation_observer_;
  std::unique_ptr<WasmBrowserContinuousNavigationObserver>
      reload_navigation_observer_;
};

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_CONTINUOUS_FLOW_H_
