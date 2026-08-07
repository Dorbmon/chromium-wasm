// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/ui/browser_window/public/browser_window_features.h"

#include <memory>
#include <utility>

#include "base/check.h"
#include "base/no_destructor.h"
#include "build/build_config.h"
#include "chrome/browser/ui/animation/browser_animation_controller.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/views/animations/side_panel_animations.h"
#include "chrome/browser/ui/views/animations/tab_strip_animations.h"
#include "ui/views/view.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_window_features.cc must only be built for WebAssembly"
#endif

class BrowserWindowFeatures::Impl {
 public:
  explicit Impl(
      std::unique_ptr<BrowserAnimationController> browser_animation_controller)
      : browser_animation_controller_(std::move(browser_animation_controller)) {
    CHECK(browser_animation_controller_);
  }

  void InitPostBrowserViewConstruction(views::View* browser_view) {
    CHECK(browser_view);
    CHECK(!browser_view_initialized_);
    CHECK(browser_animation_controller_);

    browser_animation_controller_->set_browser_view(browser_view);
    browser_animation_controller_->AddAnimationProvider(
        std::make_unique<SidePanelAnimations>());
    browser_animation_controller_->AddAnimationProvider(
        std::make_unique<TabStripAnimations>());
    browser_view_initialized_ = true;
  }

  void TearDownPreBrowserWindowDestruction() {
    browser_animation_controller_.reset();
  }

 private:
  std::unique_ptr<BrowserAnimationController> browser_animation_controller_;
  bool browser_view_initialized_ = false;
};

BrowserWindowFeatures::BrowserWindowFeatures() = default;
BrowserWindowFeatures::~BrowserWindowFeatures() = default;

void BrowserWindowFeatures::Init(BrowserWindowInterface* browser) {
  CHECK(browser);
  CHECK(!impl_);

  impl_ = std::make_unique<Impl>(
      GetUserDataFactory().CreateInstance<BrowserAnimationController>(*browser,
                                                                      *browser));
}

void BrowserWindowFeatures::InitPostBrowserViewConstruction(
    views::View* browser_view) {
  CHECK(impl_);
  impl_->InitPostBrowserViewConstruction(browser_view);
}

void BrowserWindowFeatures::TearDownPreBrowserWindowDestruction() {
  if (impl_) {
    impl_->TearDownPreBrowserWindowDestruction();
  }
}

// static
ui::UserDataFactoryWithOwner<BrowserWindowInterface>&
BrowserWindowFeatures::GetUserDataFactoryForTesting() {
  return GetUserDataFactory();
}

// static
ui::UserDataFactoryWithOwner<BrowserWindowInterface>&
BrowserWindowFeatures::GetUserDataFactory() {
  static base::NoDestructor<
      ui::UserDataFactoryWithOwner<BrowserWindowInterface>>
      factory;
  return *factory;
}
