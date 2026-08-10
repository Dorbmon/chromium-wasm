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
#include "chrome/browser/wasm/wasm_browser_host_text.h"
#include "chrome/browser/wasm/wasm_browser_host_text_smoke.h"
#include "chrome/browser/wasm/wasm_profile.h"
#include "chrome/browser/wasm/wasm_tab_strip_view.h"
#include "chrome/browser/wasm/wasm_top_controls_view.h"
#include "content/public/browser/browser_thread.h"
#include "content/public/browser/navigation_handle.h"
#include "content/public/browser/web_contents.h"
#include "content/public/browser/web_contents_observer.h"
#include "ui/aura/window.h"
#include "ui/aura/window_tree_host.h"
#include "ui/gfx/geometry/point.h"
#include "ui/gfx/geometry/rect.h"
#include "ui/views/controls/button/label_button.h"
#include "ui/views/controls/textfield/textfield.h"
#include "ui/views/view.h"
#include "ui/views/widget/widget.h"
#include "url/gurl.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_lifecycle.cc must only be built for WebAssembly"
#endif

namespace chrome {

class WasmBrowserHostTextNavigationObserver final
    : public content::WebContentsObserver {
 public:
  WasmBrowserHostTextNavigationObserver(
      content::WebContents* web_contents,
      GURL expected_url,
      base::RepeatingClosure navigation_observed)
      : content::WebContentsObserver(web_contents),
        expected_url_(std::move(expected_url)),
        navigation_observed_(std::move(navigation_observed)) {
    CHECK(web_contents);
    CHECK(expected_url_.is_valid());
    CHECK(navigation_observed_);
  }

  WasmBrowserHostTextNavigationObserver(
      const WasmBrowserHostTextNavigationObserver&) = delete;
  WasmBrowserHostTextNavigationObserver& operator=(
      const WasmBrowserHostTextNavigationObserver&) = delete;
  ~WasmBrowserHostTextNavigationObserver() override = default;

  void DidFinishNavigation(
      content::NavigationHandle* navigation_handle) override {
    if (observed_ || !navigation_handle ||
        !navigation_handle->IsInPrimaryMainFrame() ||
        navigation_handle->IsSameDocument() ||
        !navigation_handle->HasCommitted() ||
        navigation_handle->GetURL() != expected_url_) {
      return;
    }
    observed_ = true;
    navigation_observed_.Run();
  }

 private:
  const GURL expected_url_;
  const base::RepeatingClosure navigation_observed_;
  bool observed_ = false;
};

namespace {

constexpr char kHostAcceleratorsSmokeMarker[] =
    "CHROMIUM_WASM_M6_HOST_ACCELERATORS:PASS";
constexpr char kHostTextSmokeReadyMarker[] =
    "CHROMIUM_WASM_M6_HOST_TEXT:READY";
constexpr char kHostTextSmokeBurstArmedMarker[] =
    "CHROMIUM_WASM_M6_HOST_TEXT:BURST_ARMED";
constexpr char kHostTextSmokeFocusedMarker[] =
    "CHROMIUM_WASM_M6_HOST_TEXT:FOCUSED";
constexpr char kHostTextSmokeInsertedMarker[] =
    "CHROMIUM_WASM_M6_HOST_TEXT:TEXT_INSERTED";
constexpr char kHostTextSmokeNavigatedMarker[] =
    "CHROMIUM_WASM_M6_HOST_TEXT:NAVIGATED";
constexpr char kHostTextSmokePassMarker[] =
    "CHROMIUM_WASM_M6_HOST_TEXT:PASS";
constexpr char kHostTextSmokeUrl[] = "chrome://version/";
constexpr char kHostPointerTabsReadyMarker[] =
    "CHROMIUM_WASM_M6_HOST_POINTER_TABS:READY";
constexpr char kHostPointerTabsInsertedMarker[] =
    "CHROMIUM_WASM_M6_HOST_POINTER_TABS:INSERTED";
constexpr char kHostPointerTabsFirstSelectedMarker[] =
    "CHROMIUM_WASM_M6_HOST_POINTER_TABS:FIRST_SELECTED";
constexpr char kHostPointerTabsSecondSelectedMarker[] =
    "CHROMIUM_WASM_M6_HOST_POINTER_TABS:SECOND_SELECTED";
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
  ClearWasmBrowserHostTextSmokeVerificationForTesting();
  ClearWasmBrowserHostPointerTabSmokeVerificationForTesting();
  ClearWasmBrowserHostTextTarget();
  host_text_navigation_observer_.reset();
  host_text_contents_ = nullptr;
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

  // The host never controls this widget identifier. Browser lifecycle owns
  // the single Ozone target and invalidates it before the Browser can be
  // destroyed, so copied text records cannot outlive Aura's TextInputClient.
  views::Widget* const widget = browser_view.GetWidget();
  CHECK(widget);
  aura::Window* const native_window = widget->GetNativeWindow();
  CHECK(native_window);
  aura::WindowTreeHost* const host = native_window->GetHost();
  CHECK(host);
  CHECK(SetWasmBrowserHostTextTarget(host->GetAcceleratedWidget()));

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
  ClearWasmBrowserHostTextTarget();
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

void WasmBrowserLifecycle::StartHostTextSmoke() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(!host_text_smoke_started_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(browser_);
  CHECK(IsVisible());

  BrowserView& browser_view = browser_->GetBrowserView();
  WasmTopControlsView* const top_controls = browser_view.wasm_top_controls();
  CHECK(top_controls);
  CHECK(top_controls->address_field_for_testing());
  CHECK(!host_text_contents_);
  host_text_contents_ = browser_view.GetActiveWebContents();
  CHECK(host_text_contents_);
  CHECK(!host_text_navigation_observer_);
  host_text_navigation_observer_ =
      std::make_unique<WasmBrowserHostTextNavigationObserver>(
          host_text_contents_, GURL(kHostTextSmokeUrl),
          base::BindRepeating(
              &WasmBrowserLifecycle::OnHostTextNavigationObserved,
              base::Unretained(this)));

  // The focused proof must establish that two trusted DOM insertText events
  // were each admitted and focus-token-bound before either acknowledgement.
  // This test-only native gate is armed before READY, never by page script.
  CHECK(ArmWasmBrowserHostTextSmokeTwoRecordBarrier());

  // Install the observer and verifier before READY. The host may synchronously
  // submit its first trusted DOM Ctrl+L as soon as it sees that marker.
  host_text_smoke_started_ = true;
  SetWasmBrowserHostTextSmokeVerificationForTesting(base::BindRepeating(
      &WasmBrowserLifecycle::VerifyHostTextSmokeCheck,
      base::Unretained(this)));
  std::fprintf(stderr, "%s\n%s\n", kHostTextSmokeBurstArmedMarker,
               kHostTextSmokeReadyMarker);
  std::fflush(stderr);
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
  CHECK(!host_pointer_tab_second_contents_);
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
  ClearWasmBrowserHostTextSmokeVerificationForTesting();
  ClearWasmBrowserHostPointerTabSmokeVerificationForTesting();
  ClearWasmBrowserHostTextTarget();
  host_text_navigation_observer_.reset();
  host_text_contents_ = nullptr;
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
  ClearWasmBrowserHostTextSmokeVerificationForTesting();
  ClearWasmBrowserHostPointerTabSmokeVerificationForTesting();
  ClearWasmBrowserHostTextTarget();
  host_text_navigation_observer_.reset();
  host_text_contents_ = nullptr;

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

bool WasmBrowserLifecycle::VerifyHostTextSmokeCheck(int stage) {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!host_text_smoke_started_ || shutdown_started_ || shutdown_complete_ ||
      !browser_ || !host_text_contents_) {
    return false;
  }

  BrowserView& browser_view = browser_->GetBrowserView();
  if (browser_view.GetActiveWebContents() != host_text_contents_) {
    return false;
  }
  WasmTopControlsView* const top_controls = browser_view.wasm_top_controls();
  views::Textfield* const address_field =
      top_controls ? top_controls->address_field_for_testing() : nullptr;
  if (!address_field) {
    return false;
  }

  if (stage == 1) {
    if (host_text_focus_verified_ || !address_field->HasFocus() ||
        address_field->GetText().empty() ||
        address_field->GetSelectedText() != address_field->GetText()) {
      return false;
    }
    host_text_focus_verified_ = true;
    std::fprintf(stderr, "%s\n", kHostTextSmokeFocusedMarker);
    std::fflush(stderr);
    browser_view.SchedulePaint();
    return true;
  }

  if (stage == 2) {
    if (!host_text_focus_verified_ || host_text_inserted_verified_ ||
        !address_field->HasFocus() ||
        address_field->GetText() != u"chrome://version/") {
      return false;
    }
    host_text_inserted_verified_ = true;
    std::fprintf(stderr, "%s\n", kHostTextSmokeInsertedMarker);
    std::fflush(stderr);
    browser_view.SchedulePaint();
    return true;
  }

  if (stage == 3) {
    if (!host_text_inserted_verified_ || !host_text_navigation_observed_ ||
        address_field->HasFocus() ||
        host_text_contents_->GetLastCommittedURL() !=
            GURL(kHostTextSmokeUrl) ||
        address_field->GetText() != u"chrome://version/") {
      return false;
    }
    std::fprintf(stderr, "%s\n", kHostTextSmokePassMarker);
    std::fflush(stderr);
    BeginShutdown();
    return true;
  }

  return false;
}

void WasmBrowserLifecycle::OnHostTextNavigationObserved() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!host_text_smoke_started_ || shutdown_started_ || shutdown_complete_ ||
      !browser_ || !host_text_contents_ || host_text_navigation_observed_) {
    return;
  }
  BrowserView& browser_view = browser_->GetBrowserView();
  if (browser_view.GetActiveWebContents() != host_text_contents_ ||
      host_text_contents_->GetLastCommittedURL() != GURL(kHostTextSmokeUrl)) {
    return;
  }
  host_text_navigation_observed_ = true;
  std::fprintf(stderr, "%s\n", kHostTextSmokeNavigatedMarker);
  std::fflush(stderr);
  browser_view.SchedulePaint();
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
            host_pointer_tab_initial_contents_) {
      return false;
    }

    content::WebContents* const second_contents =
        tab_strip_model->GetWebContentsAt(1);
    if (!second_contents || second_contents == host_pointer_tab_initial_contents_ ||
        tab_strip_model->active_index() != 1 ||
        tab_strip_model->GetActiveWebContents() != second_contents ||
        browser_view.GetActiveWebContents() != second_contents) {
      return false;
    }

    const gfx::Point target = GetHostPointerTarget(
        browser_view, tab_strip->tab_button_for_testing(0));
    host_pointer_tab_second_contents_ = second_contents;
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
    if (!host_pointer_tab_insert_verified_ ||
        host_pointer_tab_first_selection_verified_ ||
        tab_strip_model->count() != 2 ||
        tab_strip_model->GetWebContentsAt(0) !=
            host_pointer_tab_initial_contents_ ||
        tab_strip_model->GetWebContentsAt(1) !=
            host_pointer_tab_second_contents_ ||
        tab_strip_model->active_index() != 0 ||
        tab_strip_model->GetActiveWebContents() !=
            host_pointer_tab_initial_contents_ ||
        browser_view.GetActiveWebContents() !=
            host_pointer_tab_initial_contents_) {
      return false;
    }

    const gfx::Point target = GetHostPointerTarget(
        browser_view, tab_strip->tab_button_for_testing(1));
    host_pointer_tab_first_selection_verified_ = true;
    std::fprintf(stderr, "%s x=%d y=%d\n",
                 kHostPointerTabsFirstSelectedMarker, target.x(), target.y());
    std::fflush(stderr);
    // The host waits for this presentation before it dispatches the second
    // trusted tab-selector click. This keeps both selection assertions tied
    // to a visibly updated Chromium BrowserView rather than only model state.
    browser_view.SchedulePaint();
    return true;
  }

  if (stage == 3) {
    if (!host_pointer_tab_first_selection_verified_ ||
        host_pointer_tab_second_selection_verified_ ||
        tab_strip_model->count() != 2 ||
        tab_strip_model->GetWebContentsAt(0) !=
            host_pointer_tab_initial_contents_ ||
        tab_strip_model->GetWebContentsAt(1) !=
            host_pointer_tab_second_contents_ ||
        tab_strip_model->active_index() != 1 ||
        tab_strip_model->GetActiveWebContents() !=
            host_pointer_tab_second_contents_ ||
        browser_view.GetActiveWebContents() !=
            host_pointer_tab_second_contents_) {
      return false;
    }

    const gfx::Point target = GetHostPointerTarget(
        browser_view, tab_strip->close_tab_button_for_testing(1));
    host_pointer_tab_second_selection_verified_ = true;
    std::fprintf(stderr, "%s x=%d y=%d\n",
                 kHostPointerTabsSecondSelectedMarker, target.x(), target.y());
    std::fflush(stderr);
    // The host waits for this presentation before it closes the active second
    // tab through the same trusted DOM pointer/Ozone path.
    browser_view.SchedulePaint();
    return true;
  }

  if (stage == 4) {
    views::LabelButton* const new_tab_button =
        tab_strip->new_tab_button_for_testing();
    if (!host_pointer_tab_second_selection_verified_ ||
        host_pointer_tab_close_verified_ || tab_strip_model->count() != 1 ||
        tab_strip_model->GetWebContentsAt(0) !=
            host_pointer_tab_initial_contents_ ||
        tab_strip_model->active_index() != 0 ||
        tab_strip_model->GetActiveWebContents() !=
            host_pointer_tab_initial_contents_ ||
        browser_view.GetActiveWebContents() !=
            host_pointer_tab_initial_contents_ || !new_tab_button ||
        !new_tab_button->GetVisible() || !new_tab_button->GetEnabled()) {
      return false;
    }

    // The closed WebContents is no longer model-owned; never carry its raw
    // pointer beyond this verification point.
    host_pointer_tab_second_contents_ = nullptr;
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
  if (stage != 4 || !host_pointer_tab_smoke_started_ ||
      !host_pointer_tab_insert_verified_ ||
      !host_pointer_tab_first_selection_verified_ ||
      !host_pointer_tab_second_selection_verified_ ||
      !host_pointer_tab_close_verified_ ||
      host_pointer_tab_presentation_verified_ || shutdown_started_ ||
      shutdown_complete_ || !browser_ || host_pointer_tab_second_contents_) {
    return false;
  }

  host_pointer_tab_presentation_verified_ = true;
  std::fprintf(stderr, "%s\n", kHostPointerTabsPassMarker);
  std::fflush(stderr);
  BeginShutdown();
  return true;
}

}  // namespace chrome
