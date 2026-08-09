// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_LIFECYCLE_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_LIFECYCLE_H_

#include "base/callback_list.h"
#include "base/functional/callback.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"

class Browser;
class BrowserManagerService;
class BrowserWindowInterface;
class WasmProfile;

namespace chrome {

// Owns the process-lifetime side of one switch-gated slim Browser. The
// BrowserManagerService retains the Browser itself; this coordinator attaches
// its sole initial tab, observes every close route, and waits for the
// manager's physical-destruction turn before browser-main tears down the
// profile.
//
// It deliberately remains narrower than ordinary Chrome startup: one normal
// Browser, one no-unload tab, no general navigation or modal delegate, and no
// desktop close controller.
class WasmBrowserLifecycle final {
 public:
  // |shutdown_complete| runs only after BrowserManagerService has physically
  // destroyed the Browser. It may delete this lifecycle through main-parts.
  WasmBrowserLifecycle(WasmProfile* profile,
                       base::OnceClosure shutdown_complete);
  WasmBrowserLifecycle(const WasmBrowserLifecycle&) = delete;
  WasmBrowserLifecycle& operator=(const WasmBrowserLifecycle&) = delete;
  ~WasmBrowserLifecycle();

  // Creates the manager-owned Browser, attaches its sole model-owned blank
  // WebContents, and shows its real Aura/Ozone BrowserView at fixed smoke
  // bounds after all close-observation state is installed.
  void Initialize();

  // Begins the selected Browser's no-unload close path. A direct host close
  // also converges on the same did-close/destruction barrier.
  void BeginShutdown();

  bool IsVisible() const;
  bool IsShutdownStarted() const { return shutdown_started_; }
  bool IsShutdownComplete() const { return shutdown_complete_; }

 private:
  void OnBrowserDidClose(BrowserWindowInterface* browser);
  void ArmBrowserDestructionBarrier();
  void OnBrowserDestructionsComplete();

  const raw_ptr<WasmProfile> profile_;
  const raw_ptr<BrowserManagerService> browser_manager_;
  base::WeakPtr<Browser> browser_;
  base::CallbackListSubscription browser_did_close_subscription_;
  base::OnceClosure shutdown_complete_callback_;
  bool initialized_ = false;
  bool shutdown_started_ = false;
  bool browser_destruction_barrier_armed_ = false;
  bool shutdown_complete_ = false;
};

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_LIFECYCLE_H_
