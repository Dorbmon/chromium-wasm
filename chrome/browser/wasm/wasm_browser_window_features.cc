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
#include "chrome/browser/ui/fullscreen/browser_window_fullscreen_controller.h"
#include "chrome/browser/ui/views/animations/side_panel_animations.h"
#include "chrome/browser/ui/views/animations/tab_strip_animations.h"
#include "chrome/browser/ui/views/frame/immersive_mode_controller.h"
#include "chrome/browser/ui/views/interaction/browser_elements_views.h"
#include "chrome/browser/ui/views/interaction/browser_elements_views_impl.h"
#include "chrome/browser/ui/window_feature_controller/window_feature_controller.h"
#include "ui/views/view.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_window_features.cc must only be built for WebAssembly"
#endif

class BrowserWindowFeatures::Impl {
 public:
  Impl(std::unique_ptr<BrowserWindowFullscreenController> fullscreen_controller,
       std::unique_ptr<WindowFeatureController> window_feature_controller,
       std::unique_ptr<ImmersiveModeController> immersive_mode_controller,
       std::unique_ptr<BrowserAnimationController> browser_animation_controller,
       std::unique_ptr<BrowserElements> browser_elements)
      : fullscreen_controller_(std::move(fullscreen_controller)),
        window_feature_controller_(std::move(window_feature_controller)),
        immersive_mode_controller_(std::move(immersive_mode_controller)),
        browser_animation_controller_(std::move(browser_animation_controller)),
        browser_elements_(std::move(browser_elements)) {
    CHECK(fullscreen_controller_);
    CHECK(window_feature_controller_);
    CHECK(immersive_mode_controller_);
    CHECK(browser_animation_controller_);
    CHECK(browser_elements_);
  }

  ImmersiveModeController* immersive_mode_controller() const {
    CHECK(immersive_mode_controller_);
    return immersive_mode_controller_.get();
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
    // Undo the UDD registration in the reverse order it was established,
    // before BrowserElements or animation can observe the destroyed browser.
    immersive_mode_controller_.reset();
    window_feature_controller_.reset();
    fullscreen_controller_.reset();

    if (browser_elements_) {
      auto* const provider = browser_elements_->AsA<BrowserElementsViews>();
      CHECK(provider);
      provider->TearDown();
      browser_elements_.reset();
    }
    browser_animation_controller_.reset();
  }

 private:
  std::unique_ptr<BrowserWindowFullscreenController> fullscreen_controller_;
  std::unique_ptr<WindowFeatureController> window_feature_controller_;
  std::unique_ptr<ImmersiveModeController> immersive_mode_controller_;
  std::unique_ptr<BrowserAnimationController> browser_animation_controller_;
  std::unique_ptr<BrowserElements> browser_elements_;
  bool browser_view_initialized_ = false;
};

BrowserWindowFeatures::BrowserWindowFeatures() = default;
BrowserWindowFeatures::~BrowserWindowFeatures() = default;

void BrowserWindowFeatures::Init(BrowserWindowInterface* browser) {
  CHECK(browser);
  CHECK(!impl_);

  // BrowserWindowFeatures is initialized before the browser window exists. P3
  // deliberately admits only the initial normal Browser window; app,
  // popup, DevTools, and Picture-in-Picture windows need their own policies.
  CHECK_EQ(browser->GetType(), BrowserWindowInterface::TYPE_NORMAL);

  // Keep each UDD creation in a separate statement. The registration order is
  // part of the lifecycle contract and must not depend on argument evaluation.
  auto fullscreen_controller =
      std::make_unique<BrowserWindowFullscreenController>(*browser);
  auto window_feature_controller =
      GetUserDataFactory().CreateInstance<WindowFeatureController>(
          *browser, fullscreen_controller.get(), /*app_controller=*/nullptr,
          browser->GetType(),
          // This value is not read by the normal-window-only policy.
          /*is_trusted_source=*/false, browser->GetUnownedUserDataHost());
  auto immersive_mode_controller =
      GetUserDataFactory()
          .CreateInstanceWithFactoryMethod<ImmersiveModeController,
                                           WindowFeatureController*,
                                           ui::UnownedUserDataHost&>(
              *browser, &chrome::CreateImmersiveModeController,
              window_feature_controller.get(),
              browser->GetUnownedUserDataHost());
  auto browser_animation_controller =
      GetUserDataFactory().CreateInstance<BrowserAnimationController>(*browser,
                                                                      *browser);
  auto browser_elements =
      GetUserDataFactory().CreateInstance<BrowserElementsViewsImpl>(*browser,
                                                                     *browser);

  impl_ = std::make_unique<Impl>(
      std::move(fullscreen_controller), std::move(window_feature_controller),
      std::move(immersive_mode_controller),
      std::move(browser_animation_controller), std::move(browser_elements));
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

ImmersiveModeController* BrowserWindowFeatures::immersive_mode_controller() {
  CHECK(impl_);
  return impl_->immersive_mode_controller();
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
