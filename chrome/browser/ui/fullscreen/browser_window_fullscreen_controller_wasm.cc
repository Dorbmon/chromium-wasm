// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/ui/fullscreen/browser_window_fullscreen_controller.h"

#include "base/types/to_address.h"
#include "build/build_config.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "ui/base/base_window.h"

#if !BUILDFLAG(IS_WASM)
#error "browser_window_fullscreen_controller_wasm.cc must only be built for WebAssembly"
#endif

DEFINE_USER_DATA(BrowserWindowFullscreenController);

BrowserWindowFullscreenController::BrowserWindowFullscreenController(
    BrowserWindowInterface& browser)
    : browser_(browser),
      scoped_data_holder_(browser.GetUnownedUserDataHost(), *this) {}

BrowserWindowFullscreenController::~BrowserWindowFullscreenController() =
    default;

// static
BrowserWindowFullscreenController* BrowserWindowFullscreenController::From(
    BrowserWindowInterface* browser) {
  return browser
             ? ui::ScopedUnownedUserData<BrowserWindowFullscreenController>::
                   Get(browser->GetUnownedUserDataHost())
             : nullptr;
}

// static
const BrowserWindowFullscreenController*
BrowserWindowFullscreenController::From(const BrowserWindowInterface* browser) {
  return browser
             ? ui::ScopedUnownedUserData<BrowserWindowFullscreenController>::
                   Get(browser->GetUnownedUserDataHost())
             : nullptr;
}

bool BrowserWindowFullscreenController::ShouldHideUIForFullscreen() const {
  if (should_hide_ui_for_fullscreen_for_testing_.has_value()) {
    return should_hide_ui_for_fullscreen_for_testing_.value();
  }

  // BrowserWindowFeatures are initialized before
  // BrowserWindow::CreateBrowserWindow(), so the BrowserWindowInterface has no
  // BaseWindow during early setup.
  const ui::BaseWindow* const window =
      base::to_address(browser_)->GetWindow();
  return window && window->IsFullscreen();
}

bool BrowserWindowFullscreenController::IsForceFullscreen() const {
  return force_fullscreen_;
}

void BrowserWindowFullscreenController::SetForceFullscreen(
    bool force_fullscreen) {
  force_fullscreen_ = force_fullscreen;
}
