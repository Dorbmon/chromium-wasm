// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_WINDOW_LIFECYCLE_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_WINDOW_LIFECYCLE_H_

#include <memory>

#include "base/callback_list.h"
#include "base/functional/callback.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"

class BrowserManagerService;
class BrowserWindowInterface;
class WasmProfile;

namespace chrome {

class WasmBrowserWindowViewHost;

// Owns the bounded process-lifetime side of one switch-gated Wasm browser
// window. BrowserManagerService continues to own the BrowserWindowInterface;
// this object retains the Views host and waits for the manager's physical
// destruction turn before allowing browser-main profile shutdown.
//
// This is deliberately not a general Browser lifecycle. It admits one
// about:blank WebContents with the existing no-unload TabStripModel policy and
// never creates Browser, Browser::Create(), or a desktop close controller.
class WasmBrowserWindowLifecycle final {
 public:
  // |shutdown_complete| runs after this lifecycle has observed every Core
  // close path, waited for BrowserManagerService to physically destroy the
  // Core, and released its retained Views host. It may delete this object.
  WasmBrowserWindowLifecycle(WasmProfile* profile,
                             base::OnceClosure shutdown_complete);
  WasmBrowserWindowLifecycle(const WasmBrowserWindowLifecycle&) = delete;
  WasmBrowserWindowLifecycle& operator=(
      const WasmBrowserWindowLifecycle&) = delete;
  ~WasmBrowserWindowLifecycle();

  // Creates one manager-owned Core, binds its Views host, then appends the
  // sole model-owned about:blank tab after the host has bound its WebView.
  // The bounded content-only BrowserView is shown at a deterministic size so
  // the lifecycle smoke retains a real canvas-backed primary surface through
  // the main message loop.
  void Initialize();

  // Begins the existing bounded no-unload close sequence. Completion is owned
  // by this object so the same physical-destruction barrier also handles a
  // direct BrowserView/host close that reaches the Core without this call.
  void BeginShutdown();

  bool IsVisible() const;
  bool IsShutdownStarted() const { return shutdown_started_; }
  bool IsShutdownComplete() const { return shutdown_complete_; }

 private:
  void OnCoreDidClose(BrowserWindowInterface* browser);
  void ArmBrowserDestructionBarrier();
  void OnBrowserDestructionsComplete();

  const raw_ptr<WasmProfile> profile_;
  const raw_ptr<BrowserManagerService> browser_manager_;
  std::unique_ptr<WasmBrowserWindowViewHost> view_host_;
  base::WeakPtr<BrowserWindowInterface> core_;
  base::CallbackListSubscription core_did_close_subscription_;
  base::OnceClosure shutdown_complete_callback_;
  bool initialized_ = false;
  bool shutdown_started_ = false;
  bool browser_destruction_barrier_armed_ = false;
  bool shutdown_complete_ = false;
};

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_WINDOW_LIFECYCLE_H_
