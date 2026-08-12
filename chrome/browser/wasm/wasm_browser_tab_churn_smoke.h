// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_TAB_CHURN_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_TAB_CHURN_SMOKE_H_

#include "base/functional/callback.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "base/timer/timer.h"

class Browser;

namespace content {
class WebContents;
}  // namespace content

namespace chrome {

// UI-thread owner for the fixed M9 preparation smoke. It keeps one Browser
// alive through exactly three trusted-DOM tab create/select/select/close
// cycles. It intentionally performs no navigation, persistence, networking,
// worker, memory-growth, or page-WebAssembly operation.
class WasmBrowserTabChurnSmoke final {
 public:
  WasmBrowserTabChurnSmoke(Browser* browser,
                           base::RepeatingClosure request_shutdown);
  WasmBrowserTabChurnSmoke(const WasmBrowserTabChurnSmoke&) = delete;
  WasmBrowserTabChurnSmoke& operator=(const WasmBrowserTabChurnSmoke&) =
      delete;
  ~WasmBrowserTabChurnSmoke();

  // Arms the host observation bridge and publishes the first native Views
  // target only after the initial Browser and tab model are live on the UI
  // thread.
  void Start();

 private:
  bool VerifyCheck(int stage);
  bool VerifyBackingStoreCopy(int stage);
  void PublishTargetForCurrentStage();
  void ArmStepTimeout();
  void OnStepTimeout();
  void FailAndRequestOrderlyShutdown();
  void RequestOrderlyShutdown();

  const raw_ptr<Browser> browser_;
  base::RepeatingClosure request_shutdown_;
  bool started_ = false;
  bool shutdown_requested_ = false;
  bool action_verified_ = false;
  int current_stage_ = 1;
  base::OneShotTimer step_timeout_;
  // Trusted pointer delivery may synchronously remove either tab before this
  // UI-sequence verifier runs. Keep no cross-click raw WebContents pointer:
  // expired weak references turn an unexpected removal into a failed smoke
  // check rather than a dangling comparison or dereference.
  base::WeakPtr<content::WebContents> initial_contents_;
  base::WeakPtr<content::WebContents> second_contents_;
};

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_TAB_CHURN_SMOKE_H_
