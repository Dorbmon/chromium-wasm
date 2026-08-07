// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/ui/browser_actions.h"

#include <memory>

#include "base/check.h"
#include "base/memory/raw_ptr.h"
#include "build/build_config.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "ui/actions/actions.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_actions.cc must only be built for WebAssembly"
#endif

// This owns only the ActionManager registration lifetime. Browser-window
// action callbacks and their supporting controllers are deliberately not part
// of this source-selected foundation.
class BrowserActions::Impl {
 public:
  explicit Impl(BrowserWindowInterface* browser) {
    // Retain the same construction preconditions as the desktop action owner
    // without admitting profile-backed action catalog dependencies.
    CHECK(browser);
    CHECK(browser->GetProfile());
  }

  ~Impl() {
    if (root_action_item_) {
      // Extract the unique ptr and destruct it after the raw_ptr to avoid a
      // dangling pointer scenario.
      std::unique_ptr<actions::ActionItem> owned_root_action_item =
          actions::ActionManager::Get().RemoveAction(root_action_item_);
      root_action_item_ = nullptr;
    }
  }

  void InitializeBrowserActions() {
    CHECK(!root_action_item_);
    actions::ActionManager::Get().AddAction(
        actions::ActionItem::Builder()
            .CopyAddressTo(&root_action_item_)
            .Build());
  }

  actions::ActionItem* root_action_item() const { return root_action_item_; }

 private:
  raw_ptr<actions::ActionItem> root_action_item_ = nullptr;
};

BrowserActions::BrowserActions(BrowserWindowInterface* browser)
    : impl_(std::make_unique<Impl>(browser)) {}

BrowserActions::~BrowserActions() = default;

actions::ActionItem* BrowserActions::root_action_item() const {
  CHECK(impl_);
  return impl_->root_action_item();
}

void BrowserActions::InitializeBrowserActions() {
  CHECK(impl_);
  impl_->InitializeBrowserActions();
}
