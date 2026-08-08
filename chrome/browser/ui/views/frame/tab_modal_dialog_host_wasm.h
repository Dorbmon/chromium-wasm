// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_UI_VIEWS_FRAME_TAB_MODAL_DIALOG_HOST_WASM_H_
#define CHROME_BROWSER_UI_VIEWS_FRAME_TAB_MODAL_DIALOG_HOST_WASM_H_

#include "base/memory/raw_ptr.h"
#include "base/observer_list.h"
#include "base/scoped_observation.h"
#include "components/web_modal/web_contents_modal_dialog_host.h"
#include "ui/gfx/geometry/rect.h"
#include "ui/views/view_observer.h"
#include "ui/views/widget/widget_observer.h"

namespace views {
class WebView;
class Widget;
}  // namespace views

// Positions tab-modal Views dialogs within the one active WebView of the
// first Wasm BrowserView. The host deliberately owns no WebContents-modal
// manager delegate: wiring blocked-state, visibility, and close behavior needs
// the joined Browser/BrowserWidget lifecycle rather than a partial substitute.
class WasmTabModalDialogHost final : public web_modal::WebContentsModalDialogHost,
                                     public views::ViewObserver,
                                     public views::WidgetObserver {
 public:
  explicit WasmTabModalDialogHost(views::WebView* contents_web_view);

  WasmTabModalDialogHost(const WasmTabModalDialogHost&) = delete;
  WasmTabModalDialogHost& operator=(const WasmTabModalDialogHost&) = delete;

  ~WasmTabModalDialogHost() override;

  // web_modal::ModalDialogHost:
  gfx::NativeView GetHostView() const override;
  gfx::Point GetDialogPosition(const gfx::Size& dialog_size) override;
  bool ShouldActivateDialog() const override;
  bool ShouldConstrainDialogBoundsByHost() override;
  void AddObserver(web_modal::ModalDialogHostObserver* observer) override;
  void RemoveObserver(web_modal::ModalDialogHostObserver* observer) override;

  // web_modal::WebContentsModalDialogHost:
  gfx::Size GetMaximumDialogSize() override;

  // views::ViewObserver:
  void OnViewAddedToWidget(views::View* observed_view) override;
  void OnViewRemovedFromWidget(views::View* observed_view) override;
  void OnViewBoundsChanged(views::View* observed_view) override;
  void OnViewVisibilityChanged(views::View* observed_view,
                               views::View* starting_view,
                               bool visible) override;
  void OnViewIsDeleting(views::View* observed_view) override;

  // views::WidgetObserver:
  void OnWidgetBoundsChanged(views::Widget* widget,
                             const gfx::Rect& new_bounds) override;
  void OnWidgetDestroying(views::Widget* widget) override;

 private:
  gfx::Rect GetContentsBoundsInWidget() const;
  void ObserveWidget();
  void NotifyPositionRequiresUpdate();
  void NotifyHostDestroying();

  // This remains a raw pointer because the owner View owns the WebView. The
  // ViewObserver makes an unexpected earlier destruction explicit instead of
  // allowing the host to retain a dangling geometry source.
  raw_ptr<views::WebView> contents_web_view_;
  base::ScopedObservation<views::View, views::ViewObserver>
      contents_web_view_observation_{this};
  base::ScopedObservation<views::Widget, views::WidgetObserver>
      widget_observation_{this};
  base::ObserverList<web_modal::ModalDialogHostObserver> observer_list_;

  // The outer Widget is the native parent for hosted dialogs. Once it begins
  // destruction this host must not be reused with a new widget: a future
  // joined Browser close path owns any reparenting before that point.
  bool host_destroying_ = false;
};

#endif  // CHROME_BROWSER_UI_VIEWS_FRAME_TAB_MODAL_DIALOG_HOST_WASM_H_
