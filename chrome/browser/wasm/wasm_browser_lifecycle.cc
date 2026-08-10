// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_lifecycle.h"

#include <cstdio>
#include <memory>
#include <utility>

#include "base/check.h"
#include "base/functional/bind.h"
#include "build/build_config.h"
#include "chrome/browser/ui/browser_manager_service.h"
#include "chrome/browser/ui/browser_manager_service_factory.h"
#include "chrome/browser/ui/browser_window/public/global_browser_collection.h"
#include "chrome/browser/ui/tabs/tab_strip_model.h"
#include "chrome/browser/ui/views/frame/browser_view.h"
#include "chrome/browser/wasm/wasm_browser.h"
#include "chrome/browser/wasm/wasm_browser_host_input.h"
#include "chrome/browser/wasm/wasm_browser_host_pointer_tab_smoke.h"
#include "chrome/browser/wasm/wasm_profile.h"
#include "chrome/browser/wasm/wasm_tab_strip_view.h"
#include "chrome/browser/wasm/wasm_top_controls_view.h"
#include "content/public/browser/browser_thread.h"
#include "content/public/browser/web_contents.h"
#include "ui/gfx/geometry/point.h"
#include "ui/gfx/geometry/rect.h"
#include "ui/views/controls/button/label_button.h"
#include "ui/views/controls/textfield/textfield.h"
#include "ui/views/view.h"
#include "ui/views/widget/widget.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_lifecycle.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kHostAcceleratorsSmokeMarker[] =
    "CHROMIUM_WASM_M6_HOST_ACCELERATORS:PASS";
constexpr char kHostPointerTabsReadyMarker[] =
    "CHROMIUM_WASM_M6_HOST_POINTER_TABS:READY";
constexpr char kHostPointerTabsInsertedMarker[] =
    "CHROMIUM_WASM_M6_HOST_POINTER_TABS:INSERTED";
constexpr char kHostPointerTabsClosedMarker[] =
    "CHROMIUM_WASM_M6_HOST_POINTER_TABS:CLOSED";
constexpr char kHostPointerTabsPassMarker[] =
    "CHROMIUM_WASM_M6_HOST_POINTER_TABS:PASS";
constexpr gfx::Rect kBrowserLifecycleSmokeBounds(0, 0, 640, 480);
constexpr int kMaximumHostPointerCoordinate = 16383;

gfx::Point GetHostPointerTarget(BrowserView& browser_view, views::View* view) {
  CHECK(view);
  CHECK(view->GetVisible());
  CHECK(view->GetEnabled());
  browser_view.DeprecatedLayoutImmediately();

  views::Widget* const widget = browser_view.GetWidget();
  CHECK(widget);
  CHECK(widget->IsVisible());
  const gfx::Rect target_bounds = view->GetBoundsInScreen();
  CHECK(!target_bounds.IsEmpty());
  const gfx::Point target = target_bounds.CenterPoint();
  CHECK(widget->GetWindowBoundsInScreen().Contains(target));
  CHECK_GE(target.x(), 0);
  CHECK_LE(target.x(), kMaximumHostPointerCoordinate);
  CHECK_GE(target.y(), 0);
  CHECK_LE(target.y(), kMaximumHostPointerCoordinate);
  return target;
}

}  // namespace

WasmBrowserLifecycle::WasmBrowserLifecycle(
    WasmProfile* profile,
    base::OnceClosure shutdown_complete)
    : profile_(profile),
      browser_manager_(BrowserManagerServiceFactory::GetForProfile(profile)),
      shutdown_complete_callback_(std::move(shutdown_complete)) {
  CHECK(profile_);
  CHECK(browser_manager_);
  CHECK(shutdown_complete_callback_);
}

WasmBrowserLifecycle::~WasmBrowserLifecycle() {
  // A queued host ABI check stores a callback bound to this coordinator. The
  // close barrier always runs on UI before destruction, so clear it before the
  // coordinator's raw callbacks and Browser weak pointer disappear.
  ClearWasmBrowserHostAcceleratorVerificationForTesting();
  ClearWasmBrowserHostPointerTabSmokeVerificationForTesting();
  // BrowserManagerService owns the Browser. This lifecycle can disappear only
  // after the manager's physical destruction callback invalidates |browser_|.
  CHECK(!browser_);
  CHECK(!browser_did_close_subscription_);
  CHECK(!shutdown_complete_callback_);
}

void WasmBrowserLifecycle::Initialize() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(!initialized_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(!browser_);
  CHECK(!browser_did_close_subscription_);
  CHECK(shutdown_complete_callback_);
  CHECK(browser_manager_->IsEmpty());

  Browser::CreateParams create_params(profile_, /*user_gesture=*/true);
  Browser* const raw_browser = Browser::Create(create_params);
  CHECK(raw_browser);
  browser_ = raw_browser->AsWeakPtr();
  CHECK(browser_);
  CHECK_EQ(browser_manager_->GetSize(), 1u);

  // Install this before the BrowserView can become visible and expose its
  // close route. The manager callback is armed only after did-close: doing it
  // here would synchronously observe empty queues and finish before a close.
  browser_did_close_subscription_ = raw_browser->RegisterBrowserDidClose(
      base::BindRepeating(&WasmBrowserLifecycle::OnBrowserDidClose,
                          base::Unretained(this)));
  CHECK(browser_did_close_subscription_);

  content::WebContents::CreateParams contents_params(profile_);
  std::unique_ptr<content::WebContents> contents =
      content::WebContents::Create(contents_params);
  CHECK(contents);
  content::WebContents* const raw_contents = contents.get();
  TabStripModel* const tab_strip_model = raw_browser->tab_strip_model();
  CHECK(tab_strip_model);
  CHECK(tab_strip_model->empty());
  tab_strip_model->AppendWebContents(std::move(contents), /*foreground=*/true);
  CHECK_EQ(tab_strip_model->count(), 1);
  CHECK_EQ(tab_strip_model->GetActiveWebContents(), raw_contents);

  BrowserView& browser_view = raw_browser->GetBrowserView();
  CHECK_EQ(browser_view.browser(), raw_browser);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_contents);
  browser_view.SetBounds(kBrowserLifecycleSmokeBounds);
  CHECK_EQ(browser_view.GetBounds(), kBrowserLifecycleSmokeBounds);
  browser_view.Show();
  CHECK(browser_view.IsVisible());

  initialized_ = true;
}

void WasmBrowserLifecycle::BeginShutdown() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(browser_);
  CHECK_EQ(browser_manager_->GetSize(), 1u);

  shutdown_started_ = true;
  browser_->GetWindow()->Close();
}

void WasmBrowserLifecycle::StartHostAcceleratorSmoke() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(!host_accelerator_smoke_started_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(browser_);
  CHECK(IsVisible());

  host_accelerator_smoke_started_ = true;
  SetWasmBrowserHostAcceleratorVerificationForTesting(
      base::BindRepeating(&WasmBrowserLifecycle::VerifyHostAcceleratorDelivery,
                          base::Unretained(this)),
      base::BindOnce(
          &WasmBrowserLifecycle::OnHostAcceleratorDeliveryVerified,
          base::Unretained(this)));
}

void WasmBrowserLifecycle::StartHostPointerTabSmoke() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(!host_pointer_tab_smoke_started_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(browser_);
  CHECK(IsVisible());

  BrowserView& browser_view = browser_->GetBrowserView();
  WasmTabStripView* const tab_strip = browser_view.wasm_tab_strip();
  CHECK(tab_strip);
  TabStripModel* const tab_strip_model = browser_->tab_strip_model();
  CHECK(tab_strip_model);
  CHECK_EQ(tab_strip_model->count(), 1);
  host_pointer_tab_initial_contents_ = tab_strip_model->GetWebContentsAt(0);
  CHECK(host_pointer_tab_initial_contents_);

  // Install the UI verifier before reporting READY: the real host observes
  // this marker then dispatches trusted DOM pointer events immediately.
  host_pointer_tab_smoke_started_ = true;
  SetWasmBrowserHostPointerTabSmokeVerificationForTesting(
      base::BindRepeating(
          &WasmBrowserLifecycle::VerifyHostPointerTabSmokeCheck,
          base::Unretained(this)),
      base::BindRepeating(
          &WasmBrowserLifecycle::OnHostPointerTabSmokePresented,
          base::Unretained(this)));

  const gfx::Point target = GetHostPointerTarget(
      browser_view, tab_strip->new_tab_button_for_testing());
  std::fprintf(stderr, "%s x=%d y=%d\n", kHostPointerTabsReadyMarker,
               target.x(), target.y());
  std::fflush(stderr);
}

bool WasmBrowserLifecycle::IsVisible() const {
  CHECK(initialized_);
  CHECK(!shutdown_complete_);
  CHECK(browser_);
  return browser_->GetBrowserView().IsVisible();
}

void WasmBrowserLifecycle::OnBrowserDidClose(
    BrowserWindowInterface* browser) {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(!shutdown_complete_);
  CHECK_EQ(browser, browser_.get());

  // A direct BrowserView/host close can enter Browser::OnWindowClosing()
  // without BeginShutdown(). Both paths converge while did-close dispatch is
  // active, before Browser posts manager deletion.
  ClearWasmBrowserHostAcceleratorVerificationForTesting();
  ClearWasmBrowserHostPointerTabSmokeVerificationForTesting();
  shutdown_started_ = true;
  ArmBrowserDestructionBarrier();
}

void WasmBrowserLifecycle::ArmBrowserDestructionBarrier() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(browser_);
  if (browser_destruction_barrier_armed_) {
    return;
  }
  browser_destruction_barrier_armed_ = true;

  // Browser posts DeleteBrowser after every did-close subscriber returns, and
  // BrowserManagerService performs physical destruction on its second
  // non-nestable turn. Register inside did-close so neither route can let
  // profile shutdown race a bound BrowserWidget.
  browser_manager_->RunWhenBrowserDestructionsCompleteForWasm(
      base::BindOnce(&WasmBrowserLifecycle::OnBrowserDestructionsComplete,
                     base::Unretained(this)));
}

void WasmBrowserLifecycle::OnBrowserDestructionsComplete() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(shutdown_started_);
  CHECK(browser_destruction_barrier_armed_);
  CHECK(!shutdown_complete_);
  CHECK(!browser_);
  CHECK(browser_manager_->IsEmpty());

  GlobalBrowserCollection* const global_collection =
      GlobalBrowserCollection::GetInstance();
  CHECK(global_collection);
  CHECK(global_collection->IsEmpty());

  browser_did_close_subscription_ = base::CallbackListSubscription();
  shutdown_complete_ = true;

  ClearWasmBrowserHostAcceleratorVerificationForTesting();
  ClearWasmBrowserHostPointerTabSmokeVerificationForTesting();

  // This callback may reset and destroy this lifecycle in main-parts.
  std::move(shutdown_complete_callback_).Run();
}

bool WasmBrowserLifecycle::VerifyHostAcceleratorDelivery() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(host_accelerator_smoke_started_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(browser_);

  BrowserView& browser_view = browser_->GetBrowserView();
  WasmTopControlsView* const top_controls =
      browser_view.wasm_top_controls();
  CHECK(top_controls);
  views::Textfield* const address_field =
      top_controls->address_field_for_testing();
  CHECK(address_field);

  // Ctrl+L is intentionally the first host proof: it has an unambiguous
  // visible focus and selection result, while navigation and tab commands
  // remain covered by the richer Views routing smoke.
  return address_field->HasFocus() && !address_field->GetText().empty() &&
         address_field->GetSelectedText() == address_field->GetText();
}

void WasmBrowserLifecycle::OnHostAcceleratorDeliveryVerified() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(host_accelerator_smoke_started_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(VerifyHostAcceleratorDelivery());

  std::fprintf(stderr, "%s\n", kHostAcceleratorsSmokeMarker);
  std::fflush(stderr);
  BeginShutdown();
}

bool WasmBrowserLifecycle::VerifyHostPointerTabSmokeCheck(int stage) {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!host_pointer_tab_smoke_started_ || shutdown_started_ ||
      shutdown_complete_ || !browser_ || !host_pointer_tab_initial_contents_) {
    return false;
  }

  TabStripModel* const tab_strip_model = browser_->tab_strip_model();
  if (!tab_strip_model) {
    return false;
  }
  BrowserView& browser_view = browser_->GetBrowserView();
  WasmTabStripView* const tab_strip = browser_view.wasm_tab_strip();
  if (!tab_strip) {
    return false;
  }

  if (stage == 1) {
    if (host_pointer_tab_insert_verified_ || tab_strip_model->count() != 2 ||
        tab_strip_model->GetWebContentsAt(0) !=
            host_pointer_tab_initial_contents_ ||
        tab_strip_model->GetWebContentsAt(1) ==
            host_pointer_tab_initial_contents_) {
      return false;
    }

    const gfx::Point target = GetHostPointerTarget(
        browser_view, tab_strip->close_tab_button_for_testing(1));
    host_pointer_tab_insert_verified_ = true;
    std::fprintf(stderr, "%s x=%d y=%d\n", kHostPointerTabsInsertedMarker,
                 target.x(), target.y());
    std::fflush(stderr);
    // The host must observe a canvas frame after this model action before it
    // dispatches the second trusted DOM click.
    browser_view.SchedulePaint();
    return true;
  }

  if (stage == 2) {
    views::LabelButton* const new_tab_button =
        tab_strip->new_tab_button_for_testing();
    if (!host_pointer_tab_insert_verified_ ||
        host_pointer_tab_close_verified_ || tab_strip_model->count() != 1 ||
        tab_strip_model->GetWebContentsAt(0) !=
            host_pointer_tab_initial_contents_ ||
        !new_tab_button || !new_tab_button->GetVisible() ||
        !new_tab_button->GetEnabled()) {
      return false;
    }

    host_pointer_tab_close_verified_ = true;
    std::fprintf(stderr, "%s\n", kHostPointerTabsClosedMarker);
    std::fflush(stderr);
    // The host acknowledges this exact post-close presentation before this
    // lifecycle begins its normal ordered Browser shutdown.
    browser_view.SchedulePaint();
    return true;
  }

  return false;
}

bool WasmBrowserLifecycle::OnHostPointerTabSmokePresented(int stage) {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (stage != 2 || !host_pointer_tab_smoke_started_ ||
      !host_pointer_tab_insert_verified_ || !host_pointer_tab_close_verified_ ||
      host_pointer_tab_presentation_verified_ || shutdown_started_ ||
      shutdown_complete_ || !browser_) {
    return false;
  }

  host_pointer_tab_presentation_verified_ = true;
  std::fprintf(stderr, "%s\n", kHostPointerTabsPassMarker);
  std::fflush(stderr);
  BeginShutdown();
  return true;
}

}  // namespace chrome
