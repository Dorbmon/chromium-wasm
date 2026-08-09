// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_global_browser_collection.h"

#include <algorithm>

#include "base/check.h"
#include "build/build_config.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/ui/browser_window/public/browser_collection_observer.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/browser_window/public/global_browser_collection.h"
#include "ui/base/base_window.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_global_browser_collection.cc must only be built for WebAssembly"
#endif

namespace {

// This is process-global by design. Chromium's GlobalBrowserCollection is a
// singleton scoped to BrowserProcess; WebAssembly starts one browser process
// in the module and its owner explicitly registers and clears this pointer.
GlobalBrowserCollection* g_wasm_global_browser_collection = nullptr;

}  // namespace

void RegisterWasmGlobalBrowserCollection(
    GlobalBrowserCollection* global_browser_collection) {
  CHECK(global_browser_collection);
  CHECK(!g_wasm_global_browser_collection);
  g_wasm_global_browser_collection = global_browser_collection;
}

void UnregisterWasmGlobalBrowserCollection(
    GlobalBrowserCollection* global_browser_collection) {
  CHECK_EQ(g_wasm_global_browser_collection, global_browser_collection);
  g_wasm_global_browser_collection = nullptr;
}

GlobalBrowserCollection* GetWasmGlobalBrowserCollection() {
  CHECK(g_wasm_global_browser_collection);
  return g_wasm_global_browser_collection;
}

GlobalBrowserCollection::GlobalBrowserCollection()
    : platform_delegate_(GlobalBrowserCollectionPlatformDelegate(*this)) {}

GlobalBrowserCollection::~GlobalBrowserCollection() = default;

// static
GlobalBrowserCollection* GlobalBrowserCollection::GetInstance() {
  return GetWasmGlobalBrowserCollection();
}

bool GlobalBrowserCollection::IsEmpty() const {
  return browsers_creation_order_.empty();
}

size_t GlobalBrowserCollection::GetSize() const {
  return browsers_creation_order_.size();
}

BrowserCollection::BrowserVector GlobalBrowserCollection::GetBrowsers(
    Order order) {
  CHECK(order == Order::kCreation || order == Order::kActivation);
  return order == Order::kCreation ? browsers_creation_order_
                                   : browsers_activation_order_;
}

void GlobalBrowserCollection::OnBrowserCreated(
    BrowserWindowInterface* browser) {
  browsers_creation_order_.push_back(browser);

  // Push the browser to the back of the activation order list. It will be moved
  // to the front when the browser is eventually activated (which may or may
  // not happen immediately after creation).
  browsers_activation_order_.push_back(browser);

  for (BrowserCollectionObserver& observer : observers()) {
    observer.OnBrowserCreated(browser);
  }
}

void GlobalBrowserCollection::OnBrowserClosed(BrowserWindowInterface* browser) {
  std::erase(browsers_activation_order_, browser);
  std::erase(browsers_creation_order_, browser);
  for (BrowserCollectionObserver& observer : observers()) {
    observer.OnBrowserClosed(browser);
  }
}

void GlobalBrowserCollection::OnBrowserActivated(
    BrowserWindowInterface* browser) {
  // Move `browser` to the front of the activation list.
  auto it = std::ranges::find(browsers_activation_order_, browser);
  CHECK(it != browsers_activation_order_.end());
  std::rotate(browsers_activation_order_.begin(), it, it + 1);

  for (BrowserCollectionObserver& observer : observers()) {
    observer.OnBrowserActivated(browser);
  }
}

void GlobalBrowserCollection::OnBrowserDeactivated(
    BrowserWindowInterface* browser) {
  for (BrowserCollectionObserver& observer : observers()) {
    observer.OnBrowserDeactivated(browser);
  }
}

GlobalBrowserCollectionPlatformDelegate*
GlobalBrowserCollection::GetPlatformDelegate() {
  return &platform_delegate_;
}

BrowserWindowInterface* GlobalBrowserCollection::GetActiveBrowser() {
  BrowserWindowInterface* browser = GetLastActiveBrowser();
  // A BrowserWindowInterface becomes globally visible before its BrowserView
  // and BaseWindow are constructed. Treat that honest pre-widget state as not
  // active rather than manufacturing a placeholder BaseWindow.
  ui::BaseWindow* const window = browser ? browser->GetWindow() : nullptr;
  return (window && window->IsActive()) ? browser : nullptr;
}

size_t GlobalBrowserCollection::GetIncognitoBrowserCount() {
  size_t incognito_browser_count = 0;
  ForEach([&incognito_browser_count](BrowserWindowInterface* browser) {
    if (!browser->GetProfile()->IsIncognitoProfile()) {
      return true;
    }
    if (browser->GetType() == BrowserWindowInterface::Type::TYPE_DEVTOOLS) {
      return true;
    }
    incognito_browser_count++;
    return true;
  });
  return incognito_browser_count;
}

size_t GlobalBrowserCollection::GetGuestBrowserCount() {
  size_t guest_browser_count = 0;
  ForEach([&guest_browser_count](BrowserWindowInterface* browser) {
    if (browser->GetProfile()->IsGuestSession() &&
        browser->GetType() != BrowserWindowInterface::Type::TYPE_DEVTOOLS) {
      ++guest_browser_count;
    }
    return true;
  });
  return guest_browser_count;
}
