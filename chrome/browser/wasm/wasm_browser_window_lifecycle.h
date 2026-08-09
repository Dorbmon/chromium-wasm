// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_WINDOW_LIFECYCLE_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_WINDOW_LIFECYCLE_H_

#include <memory>

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
  explicit WasmBrowserWindowLifecycle(WasmProfile* profile);
  WasmBrowserWindowLifecycle(const WasmBrowserWindowLifecycle&) = delete;
  WasmBrowserWindowLifecycle& operator=(
      const WasmBrowserWindowLifecycle&) = delete;
  ~WasmBrowserWindowLifecycle();

  // Creates one manager-owned Core, binds its Views host, then appends the
  // sole model-owned about:blank tab after the host has bound its WebView.
  void Initialize();

  // Begins the existing bounded no-unload close sequence. |completion| runs
  // only after the Core has been physically destroyed by BrowserManagerService
  // and the retained Views host can be released safely.
  void BeginShutdown(base::OnceClosure completion);

  bool IsShutdownComplete() const { return shutdown_complete_; }

 private:
  void OnBrowserDestructionsComplete();

  const raw_ptr<WasmProfile> profile_;
  const raw_ptr<BrowserManagerService> browser_manager_;
  std::unique_ptr<WasmBrowserWindowViewHost> view_host_;
  base::WeakPtr<BrowserWindowInterface> core_;
  base::OnceClosure shutdown_complete_callback_;
  bool initialized_ = false;
  bool shutdown_started_ = false;
  bool shutdown_complete_ = false;
};

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_WINDOW_LIFECYCLE_H_
