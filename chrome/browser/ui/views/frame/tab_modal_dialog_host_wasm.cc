// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/ui/views/frame/tab_modal_dialog_host_wasm.h"

#include "base/check.h"
#include "build/build_config.h"
#include "ui/gfx/geometry/point.h"
#include "ui/gfx/geometry/size.h"
#include "ui/views/controls/webview/webview.h"
#include "ui/views/view.h"
#include "ui/views/widget/widget.h"

#if !BUILDFLAG(IS_WASM)
#error "tab_modal_dialog_host_wasm.cc must only be built for WebAssembly"
#endif

WasmTabModalDialogHost::WasmTabModalDialogHost(
    views::WebView* contents_web_view)
    : contents_web_view_(contents_web_view) {
  CHECK(contents_web_view_);
  contents_web_view_observation_.Observe(contents_web_view_);
  ObserveWidget();
}

WasmTabModalDialogHost::~WasmTabModalDialogHost() {
  contents_web_view_observation_.Reset();
  widget_observation_.Reset();
  NotifyHostDestroying();
}

gfx::NativeView WasmTabModalDialogHost::GetHostView() const {
  if (host_destroying_ || !contents_web_view_) {
    return gfx::NativeView();
  }

  views::Widget* const host_widget = contents_web_view_->GetWidget();
  return host_widget ? host_widget->GetNativeView() : gfx::NativeView();
}

gfx::Point WasmTabModalDialogHost::GetDialogPosition(
    const gfx::Size& dialog_size) {
  const gfx::Rect contents_bounds = GetContentsBoundsInWidget();
  return gfx::Point(contents_bounds.x() +
                        (contents_bounds.width() - dialog_size.width()) / 2,
                    contents_bounds.y());
}

bool WasmTabModalDialogHost::ShouldActivateDialog() const {
  if (host_destroying_ || !contents_web_view_) {
    return false;
  }

  views::Widget* const host_widget = contents_web_view_->GetWidget();
  return host_widget && host_widget->ShouldPaintAsActive();
}

bool WasmTabModalDialogHost::ShouldConstrainDialogBoundsByHost() {
  // The host-page canvas has one parent Aura widget. A tab-modal dialog must
  // remain inside its selected WebView rather than escaping into a desktop
  // widget that the Wasm platform does not provide.
  return true;
}

void WasmTabModalDialogHost::AddObserver(
    web_modal::ModalDialogHostObserver* observer) {
  CHECK(!host_destroying_);
  observer_list_.AddObserver(observer);
}

void WasmTabModalDialogHost::RemoveObserver(
    web_modal::ModalDialogHostObserver* observer) {
  observer_list_.RemoveObserver(observer);
}

gfx::Size WasmTabModalDialogHost::GetMaximumDialogSize() {
  return GetContentsBoundsInWidget().size();
}

void WasmTabModalDialogHost::OnViewAddedToWidget(
    views::View* observed_view) {
  CHECK_EQ(observed_view, contents_web_view_);
  CHECK(!host_destroying_);
  ObserveWidget();
  NotifyPositionRequiresUpdate();
}

void WasmTabModalDialogHost::OnViewRemovedFromWidget(
    views::View* observed_view) {
  CHECK_EQ(observed_view, contents_web_view_);
  widget_observation_.Reset();
}

void WasmTabModalDialogHost::OnViewBoundsChanged(
    views::View* observed_view) {
  CHECK_EQ(observed_view, contents_web_view_);
  NotifyPositionRequiresUpdate();
}

void WasmTabModalDialogHost::OnViewVisibilityChanged(
    views::View* observed_view,
    views::View* /*starting_view*/,
    bool /*visible*/) {
  CHECK_EQ(observed_view, contents_web_view_);
  NotifyPositionRequiresUpdate();
}

void WasmTabModalDialogHost::OnViewIsDeleting(
    views::View* observed_view) {
  CHECK_EQ(observed_view, contents_web_view_);
  contents_web_view_observation_.Reset();
  widget_observation_.Reset();
  NotifyHostDestroying();
  contents_web_view_ = nullptr;
}

void WasmTabModalDialogHost::OnWidgetBoundsChanged(
    views::Widget* widget,
    const gfx::Rect& /*new_bounds*/) {
  CHECK(widget_observation_.IsObservingSource(widget));
  NotifyPositionRequiresUpdate();
}

void WasmTabModalDialogHost::OnWidgetDestroying(views::Widget* widget) {
  CHECK(widget_observation_.IsObservingSource(widget));
  widget_observation_.Reset();
  NotifyHostDestroying();
}

gfx::Rect WasmTabModalDialogHost::GetContentsBoundsInWidget() const {
  if (host_destroying_ || !contents_web_view_ ||
      !contents_web_view_->GetWidget()) {
    return gfx::Rect();
  }

  return contents_web_view_->ConvertRectToWidget(
      contents_web_view_->GetLocalBounds());
}

void WasmTabModalDialogHost::ObserveWidget() {
  if (host_destroying_ || !contents_web_view_) {
    return;
  }

  views::Widget* const widget = contents_web_view_->GetWidget();
  if (widget && widget_observation_.IsObservingSource(widget)) {
    return;
  }

  widget_observation_.Reset();
  if (widget) {
    widget_observation_.Observe(widget);
  }
}

void WasmTabModalDialogHost::NotifyPositionRequiresUpdate() {
  if (!host_destroying_) {
    observer_list_.Notify(
        &web_modal::ModalDialogHostObserver::OnPositionRequiresUpdate);
  }
}

void WasmTabModalDialogHost::NotifyHostDestroying() {
  if (host_destroying_) {
    return;
  }

  host_destroying_ = true;
  observer_list_.Notify(&web_modal::ModalDialogHostObserver::OnHostDestroying);
}
