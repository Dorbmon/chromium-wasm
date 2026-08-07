// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_CHROME_MAIN_DELEGATE_H_
#define CHROME_BROWSER_WASM_WASM_CHROME_MAIN_DELEGATE_H_

#include <memory>
#include <optional>

#include "content/public/app/content_main_delegate.h"

// The top-level Content delegate for a single-process Wasm Chrome embedding.
// It deliberately bypasses ChromeMainDelegate, whose desktop startup graph
// owns process spawning, native profile startup, and host integrations that
// are not implemented on the web platform.
class WasmChromeMainDelegate final : public content::ContentMainDelegate {
 public:
  WasmChromeMainDelegate();
  WasmChromeMainDelegate(const WasmChromeMainDelegate&) = delete;
  WasmChromeMainDelegate& operator=(const WasmChromeMainDelegate&) = delete;
  ~WasmChromeMainDelegate() override;

 protected:
  // content::ContentMainDelegate:
  std::optional<int> BasicStartupComplete() override;
  void PreSandboxStartup() override;
  std::optional<int> PostEarlyInitialization(InvokedIn invoked_in) override;
  content::ContentClient* CreateContentClient() override;
  content::ContentBrowserClient* CreateContentBrowserClient() override;

  // Content's default GPU, renderer, and utility clients remain in use during
  // this software-rendered foundation. Source-select Chrome-specific clients
  // only with the Chrome Views/tab lifecycle that owns their browser services.

 private:
  class State;
  std::unique_ptr<State> state_;
};

#endif  // CHROME_BROWSER_WASM_WASM_CHROME_MAIN_DELEGATE_H_
