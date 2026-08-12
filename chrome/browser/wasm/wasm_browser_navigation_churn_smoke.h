// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_NAVIGATION_CHURN_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_NAVIGATION_CHURN_SMOKE_H_

#include <memory>

#include "base/functional/callback.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "base/timer/timer.h"

class Browser;

namespace content {
class WebContents;
}  // namespace content

namespace chrome {

class WasmBrowserNavigationChurnObserver;

// UI-thread owner for a bounded M9 preparation smoke. It retains exactly one
// Browser and one WebContents while C++ initiates six fixed, script-free
// `data:` document navigations in three cycles. It intentionally does not
// exercise page JavaScript or WebAssembly, networking/WISP, persistence,
// memory pressure, or worker saturation.
class WasmBrowserNavigationChurnSmoke final {
 public:
  WasmBrowserNavigationChurnSmoke(Browser* browser,
                                  base::OnceClosure request_shutdown);
  WasmBrowserNavigationChurnSmoke(const WasmBrowserNavigationChurnSmoke&) =
      delete;
  WasmBrowserNavigationChurnSmoke& operator=(
      const WasmBrowserNavigationChurnSmoke&) = delete;
  ~WasmBrowserNavigationChurnSmoke();

  // Installs the host observation bridge only after the initial Browser and
  // active WebContents are live on the UI thread. The first native data:
  // navigation establishes the history baseline because Content may retain or
  // replace its startup about:blank entry.
  void Start();

 private:
  void BeginCurrentStageNavigation();
  void OnNavigationObserved(int stage);
  bool VerifyBackingStoreCopy(int stage);
  void ArmStepTimeout();
  void OnStepTimeout();
  void FailAndRequestOrderlyShutdown();
  void RequestOrderlyShutdown();
  void PostOrderlyShutdown();

  const raw_ptr<Browser> browser_;
  base::OnceClosure request_shutdown_;
  bool started_ = false;
  bool shutdown_requested_ = false;
  bool navigation_verified_ = false;
  bool history_baseline_captured_ = false;
  int current_stage_ = 1;
  // These record the exact post-navigation controller state only after a
  // completed stage has also received its later host copy acknowledgement.
  // They intentionally have no assumed startup value.
  int history_baseline_entry_count_ = 0;
  int history_baseline_entry_index_ = -1;
  int current_stage_history_entry_count_ = 0;
  int current_stage_history_entry_index_ = -1;
  base::OneShotTimer step_timeout_;
  // The normal Browser close path can destroy its last WebContents after a
  // direct close. Keep the coordinator's observation state weak so a late
  // host acknowledgement fails closed instead of dereferencing an old tab.
  base::WeakPtr<content::WebContents> contents_;
  std::unique_ptr<WasmBrowserNavigationChurnObserver> navigation_observer_;
  // Must remain last so every callback into this coordinator becomes inert
  // before the other member state is destroyed.
  base::WeakPtrFactory<WasmBrowserNavigationChurnSmoke> weak_ptr_factory_{this};
};

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_NAVIGATION_CHURN_SMOKE_H_
