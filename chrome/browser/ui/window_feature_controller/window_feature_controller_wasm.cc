// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/ui/window_feature_controller/window_feature_controller.h"

#include "base/check.h"
#include "base/check_deref.h"
#include "build/build_config.h"
#include "chrome/browser/ui/fullscreen/browser_window_fullscreen_controller.h"

#if !BUILDFLAG(IS_WASM)
#error "window_feature_controller_wasm.cc must only be built for WebAssembly"
#endif

DEFINE_USER_DATA(WindowFeatureController);

WindowFeatureController::WindowFeatureController(
    BrowserWindowFullscreenController* fullscreen_controller,
    web_app::AppBrowserController* app_controller,
    BrowserWindowInterface::Type browser_type,
    bool is_trusted_source,
    ui::UnownedUserDataHost& host)
    : fullscreen_controller_(CHECK_DEREF(fullscreen_controller)),
      app_controller_(app_controller),
      browser_type_(browser_type),
      is_trusted_source_(is_trusted_source),
      scoped_unowned_user_data_(host, *this) {
  // P3 only admits the initial normal Chrome window. App, popup, DevTools,
  // and Picture-in-Picture windows require their own explicit policy slices.
  CHECK_EQ(browser_type_, BrowserWindowInterface::TYPE_NORMAL);
  CHECK(!app_controller_);
}

WindowFeatureController::~WindowFeatureController() = default;

// static
WindowFeatureController* WindowFeatureController::From(
    BrowserWindowInterface* browser) {
  return ui::ScopedUnownedUserData<WindowFeatureController>::Get(
      browser->GetUnownedUserDataHost());
}

// static
const WindowFeatureController* WindowFeatureController::From(
    const BrowserWindowInterface* browser) {
  return ui::ScopedUnownedUserData<WindowFeatureController>::Get(
      browser->GetUnownedUserDataHost());
}

bool WindowFeatureController::SupportsWindowFeature(
    WindowFeature feature) const {
  const bool supports =
      SupportsWindowFeatureImpl(feature, /*check_can_support=*/false);
  DCHECK(!supports || CanSupportWindowFeature(feature));
  return supports;
}

bool WindowFeatureController::CanSupportWindowFeature(
    WindowFeature feature) const {
  return SupportsWindowFeatureImpl(feature, /*check_can_support=*/true);
}

bool WindowFeatureController::NormalBrowserSupportsWindowFeature(
    WindowFeature feature,
    bool check_can_support) const {
  switch (feature) {
    case WindowFeature::kFeatureBookmarkBar:
      return true;
    case WindowFeature::kFeatureTabStrip:
    case WindowFeature::kFeatureToolbar:
    case WindowFeature::kFeatureLocationBar:
      return check_can_support || !IsFullscreen();
    case WindowFeature::kFeatureTitleBar:
    case WindowFeature::kFeatureNone:
      return false;
  }
}

bool WindowFeatureController::SupportsWindowFeatureImpl(
    WindowFeature feature,
    bool check_can_support) const {
  // The constructor makes the non-normal cases an explicit unsupported
  // boundary. Do not silently inherit desktop app or popup behavior here.
  CHECK_EQ(browser_type_, BrowserWindowInterface::TYPE_NORMAL);
  return NormalBrowserSupportsWindowFeature(feature, check_can_support);
}

bool WindowFeatureController::IsFullscreen() const {
  return fullscreen_controller_->ShouldHideUIForFullscreen();
}
