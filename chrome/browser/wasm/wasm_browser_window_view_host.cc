// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_window_view_host.h"

#include <memory>
#include <utility>

#include "base/check.h"
#include "base/functional/bind.h"
#include "build/build_config.h"
#include "chrome/browser/ui/views/frame/browser_view.h"
#include "chrome/browser/ui/views/frame/browser_widget.h"
#include "chrome/browser/wasm/wasm_browser_window_core.h"
#include "ui/views/widget/widget.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_window_view_host.cc must only be built for WebAssembly"
#endif

namespace chrome {

WasmBrowserWindowViewHost::WasmBrowserWindowViewHost(
    WasmBrowserWindowCore* core)
    : core_(core ? core->GetWeakPtrForWasmBrowserWindowViewSmoke()
                 : base::WeakPtr<WasmBrowserWindowCore>()) {
  CHECK(core_);
}

WasmBrowserWindowViewHost::~WasmBrowserWindowViewHost() {
  widget_observation_.Reset();
  CHECK(!browser_view_);
  CHECK(!core_ || !core_->GetWindow());
}

void WasmBrowserWindowViewHost::Initialize() {
  CHECK(core_);
  CHECK(!browser_view_);

  // BrowserView is owned by BrowserWidget's RootView after Init(). Do not put
  // it in a unique_ptr: Destroy() below breaks that ownership cycle.
  BrowserView* const browser_view = new BrowserView(/*browser=*/nullptr);
  auto browser_widget = std::make_unique<BrowserWidget>(browser_view);
  BrowserWidget* const widget = browser_widget.get();
  browser_view->set_browser_widget(std::move(browser_widget));
  widget->InitBrowserWidget();
  CHECK_EQ(browser_view->GetWidget(), widget);
  CHECK(widget->browser_native_widget());

  browser_view_ = browser_view;
  widget_ = widget;
  widget_observation_.Observe(widget);

  browser_view->SetWasmCloseRequestCallback(base::BindRepeating(
      &WasmBrowserWindowViewHost::OnCloseRequested, base::Unretained(this)));

  core_->BindWindowForWasmBrowserWindowViewSmoke(
      browser_view_,
      base::BindRepeating(&WasmBrowserWindowViewHost::OnActiveContentsChanged,
                          base::Unretained(this)),
      base::BindRepeating(&WasmBrowserWindowViewHost::OnContentsDetached,
                          base::Unretained(this)),
      base::BindOnce(&WasmBrowserWindowViewHost::Destroy,
                     base::Unretained(this)));
  core_->InitPostBrowserViewConstructionForWasmBrowserWindowViewSmoke(
      browser_view_);
}

void WasmBrowserWindowViewHost::RequestClose() {
  CHECK(core_);
  CHECK(browser_view_);
  CHECK(widget_);
  if (close_requested_) {
    return;
  }

  close_requested_ = true;
  core_->RequestCloseForWasmBrowserWindowViewSmoke();
}

BrowserView* WasmBrowserWindowViewHost::browser_view() const {
  CHECK(browser_view_);
  return browser_view_;
}

void WasmBrowserWindowViewHost::OnActiveContentsChanged(
    content::WebContents* old_contents,
    content::WebContents* new_contents,
    int active_index,
    int reason) {
  CHECK(browser_view_);
  if (new_contents) {
    CHECK(!old_contents);
    browser_view_->OnActiveTabChanged(old_contents, new_contents, active_index,
                                      reason);
    CHECK_EQ(browser_view_->GetActiveWebContents(), new_contents);
  } else {
    CHECK(old_contents);
    // The Core calls OnContentsDetached() during OnTabWillBeRemoved(), while
    // the model still owns the tab. A null active event must never leave the
    // non-owning WebView attached to the removed contents.
    CHECK(detached_active_contents_);
    CHECK(!browser_view_->GetActiveWebContents());
  }
  ++active_tab_change_count_;
}

void WasmBrowserWindowViewHost::OnContentsDetached(
    content::WebContents* contents,
    bool was_active) {
  CHECK(browser_view_);
  CHECK(contents);
  CHECK(was_active);
  CHECK_EQ(browser_view_->GetActiveWebContents(), contents);
  browser_view_->OnTabDetached(contents, was_active);
  CHECK(!browser_view_->GetActiveWebContents());
  detached_active_contents_ = true;
}

views::CloseRequestResult WasmBrowserWindowViewHost::OnCloseRequested() {
  ++close_request_count_;
  RequestClose();
  // Keep the client-owned Widget alive while the Core posts its ordered
  // BrowserWindowFeatures/View teardown. Repeated close requests during that
  // turn are intentionally rejected rather than re-entering the model.
  return views::CloseRequestResult::kCannotClose;
}

void WasmBrowserWindowViewHost::Destroy() {
  CHECK(core_);
  CHECK(browser_view_);
  CHECK(widget_);
  CHECK(close_requested_);
  CHECK(!browser_view_->GetActiveWebContents());

  // Keep BrowserWindowFeatures teardown in the Core before this callback.
  // Deactivate the real Ozone/Views window before publishing the inactive
  // BrowserWindowInterface state, so global active-window queries cannot
  // observe contradictory BaseWindow and BWI activation states.
  if (browser_view_->IsActive()) {
    browser_view_->Deactivate();
  }
  CHECK(!core_->IsActive());

  // Clear the BaseWindow relation before resetting the client-owned Widget;
  // global collection queries then see the honest no-window state.
  core_->UnbindWindowForWasmBrowserWindowViewSmoke(browser_view_);
  widget_observation_.Reset();
  BrowserView::DestroyForWasmBrowserViewSmoke(browser_view_);
  browser_view_ = nullptr;
  widget_ = nullptr;
}

void WasmBrowserWindowViewHost::OnWidgetActivationChanged(
    views::Widget* widget,
    bool active) {
  CHECK_EQ(widget, widget_);
  CHECK(core_);
  core_->OnWindowActivationChangedForWasmBrowserWindowViewSmoke(browser_view_,
                                                                  active);
}

void WasmBrowserWindowViewHost::OnWidgetDestroying(views::Widget* widget) {
  CHECK_EQ(widget, widget_);
  // BrowserView observes this event first and clears its WebView. A native
  // teardown with a live model would therefore be unable to perform the
  // required detach/BWF ordering. It remains an explicit unsupported path.
  CHECK(false) << "Wasm BrowserWindow view host requires its controlled "
                  "no-unload close lifecycle";
}

void WasmBrowserWindowViewHost::OnWidgetDestroyed(views::Widget* widget) {
  CHECK_EQ(widget, widget_);
  CHECK(false) << "Wasm BrowserWindow view host native teardown escaped its "
                  "controlled lifecycle";
}

}  // namespace chrome
