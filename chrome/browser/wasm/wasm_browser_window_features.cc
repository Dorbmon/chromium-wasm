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
#include "chrome/browser/ui/views/interaction/browser_elements_views.h"
#include "chrome/browser/ui/views/interaction/browser_elements_views_impl.h"
#include "ui/views/view.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_window_features.cc must only be built for WebAssembly"
#endif

class BrowserWindowFeatures::Impl {
 public:
  Impl(std::unique_ptr<BrowserAnimationController> browser_animation_controller,
       std::unique_ptr<BrowserElements> browser_elements)
      : browser_animation_controller_(std::move(browser_animation_controller)),
        browser_elements_(std::move(browser_elements)) {
    CHECK(browser_animation_controller_);
    CHECK(browser_elements_);
  }

  void InitPostBrowserViewConstruction(views::View* browser_view) {
    CHECK(browser_view);
    CHECK(!browser_view_initialized_);
    CHECK(browser_animation_controller_);

    auto* const provider =
        browser_elements_->AsA<BrowserElementsViewsImpl>();
    CHECK(provider);
    provider->Init(browser_view);

    // Active-contents WebView retrieval is deliberately not admitted here: it
    // requires BrowserView-specific wiring, which is outside this P2
    // lifecycle.
    browser_animation_controller_->set_browser_view(browser_view);
    browser_animation_controller_->AddAnimationProvider(
        std::make_unique<SidePanelAnimations>());
    browser_animation_controller_->AddAnimationProvider(
        std::make_unique<TabStripAnimations>());
    browser_view_initialized_ = true;
  }

  void TearDownPreBrowserWindowDestruction() {
    if (browser_elements_) {
      auto* const provider = browser_elements_->AsA<BrowserElementsViews>();
      CHECK(provider);
      provider->TearDown();
      browser_elements_.reset();
    }
    browser_animation_controller_.reset();
  }

 private:
  std::unique_ptr<BrowserAnimationController> browser_animation_controller_;
  std::unique_ptr<BrowserElements> browser_elements_;
  bool browser_view_initialized_ = false;
};

BrowserWindowFeatures::BrowserWindowFeatures() = default;
BrowserWindowFeatures::~BrowserWindowFeatures() = default;

void BrowserWindowFeatures::Init(BrowserWindowInterface* browser) {
  CHECK(browser);
  CHECK(!impl_);

  impl_ = std::make_unique<Impl>(
      GetUserDataFactory().CreateInstance<BrowserAnimationController>(*browser,
                                                                      *browser),
      GetUserDataFactory().CreateInstance<BrowserElementsViewsImpl>(*browser,
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
