// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "components/constrained_window/constrained_window_views.h"

#include <memory>

#include "base/check.h"
#include "base/check_op.h"
#include "base/functional/bind.h"
#include "base/memory/ptr_util.h"
#include "base/memory/raw_ptr.h"
#include "base/scoped_observation.h"
#include "build/build_config.h"
#include "components/web_modal/modal_dialog_host.h"
#include "components/web_modal/web_contents_modal_dialog_host.h"
#include "components/web_modal/web_contents_modal_dialog_manager.h"
#include "components/web_modal/web_contents_modal_dialog_manager_delegate.h"
#include "content/public/browser/web_contents.h"
#include "ui/base/class_property.h"
#include "ui/base/mojom/ui_base_types.mojom-shared.h"
#include "ui/gfx/geometry/rect.h"
#include "ui/gfx/geometry/size.h"
#include "ui/gfx/native_ui_types.h"
#include "ui/views/widget/native_widget.h"
#include "ui/views/widget/root_view.h"
#include "ui/views/widget/widget.h"
#include "ui/views/window/dialog_delegate.h"
#include "ui/views/window/non_client_view.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_constrained_window_views.cc must only be built for WebAssembly"
#endif

using web_modal::ModalDialogHost;
using web_modal::ModalDialogHostObserver;

DEFINE_UI_CLASS_PROPERTY_TYPE(ModalDialogHostObserver*)
DEFINE_OWNED_UI_CLASS_PROPERTY_KEY(ModalDialogHostObserver,
                                   kModalDialogHostObserverKey)

namespace constrained_window {

const void* kConstrainedWindowWidgetIdentifier = "ConstrainedWindowWidget";

namespace {

gfx::Rect GetModalDialogBounds(views::Widget* widget,
                               ModalDialogHost* dialog_host,
                               const gfx::Size& size) {
  // A Wasm kChild dialog is parented to the existing BrowserWidget Aura tree,
  // so its host position is already in the correct local coordinate space.
  if (!views::Widget::GetWidgetForNativeView(dialog_host->GetHostView())) {
    return gfx::Rect();
  }

  gfx::Point position = dialog_host->GetDialogPosition(size);
  // Align the first pixel inside the dialog's frame border with the host
  // position, matching the canonical constrained-window child layout.
  position.set_y(position.y() -
                 widget->non_client_view()->frame_view()->GetInsets().top());
  return gfx::Rect(position, size);
}

void UpdateModalDialogPosition(views::Widget* widget,
                               ModalDialogHost* dialog_host,
                               const gfx::Size& size) {
  // Do not forcibly update a dialog while the user is dragging it.
  if (widget->HasCapture()) {
    return;
  }

  if (!views::Widget::GetWidgetForNativeView(dialog_host->GetHostView())) {
    widget->SetSize(size);
    return;
  }

  widget->SetBounds(GetModalDialogBounds(widget, dialog_host, size));
}

void ConfigureDesiredBoundsDelegate(views::WidgetDelegate* dialog_delegate,
                                    ModalDialogHost* dialog_host) {
  views::Widget* const widget = dialog_delegate->GetWidget();
  CHECK(widget)
      << "SetDesiredBoundsDelegate() must be called after creating the widget.";
  dialog_delegate->set_desired_bounds_delegate(base::BindRepeating(
      [](views::Widget* widget, ModalDialogHost* dialog_host) -> gfx::Rect {
        return GetModalDialogBounds(
            widget, dialog_host, widget->GetRootView()->GetPreferredSize({}));
      },
      widget, dialog_host));
}

// Closes the child Widget if its host is destroyed before WCMDM closes it.
// Position changes after the manager is attached are owned by the canonical
// NativeWebContentsModalDialogManagerViews observer selected alongside this
// Wasm-only source.
class ModalDialogHostObserverViews : public ModalDialogHostObserver {
 public:
  ModalDialogHostObserverViews(ModalDialogHost* host,
                               views::Widget* dialog_widget)
      : host_(host), dialog_widget_(dialog_widget) {
    CHECK(host_);
    CHECK(dialog_widget_);
    modal_dialog_host_observation_.Observe(host);
  }

  ModalDialogHostObserverViews(const ModalDialogHostObserverViews&) = delete;
  ModalDialogHostObserverViews& operator=(
      const ModalDialogHostObserverViews&) = delete;
  ~ModalDialogHostObserverViews() override = default;

  // web_modal::ModalDialogHostObserver:
  void OnPositionRequiresUpdate() override {}

  void OnHostDestroying() override {
    modal_dialog_host_observation_.Reset();
    host_ = nullptr;
    dialog_widget_->CloseNow();
  }

 private:
  raw_ptr<ModalDialogHost> host_;
  raw_ptr<views::Widget> dialog_widget_;
  base::ScopedObservation<ModalDialogHost, ModalDialogHostObserver>
      modal_dialog_host_observation_{this};
};

}  // namespace

void UpdateWebContentsModalDialogPosition(
    views::Widget* widget,
    web_modal::WebContentsModalDialogHost* dialog_host) {
  CHECK(widget);
  CHECK(dialog_host);

  gfx::Size size = widget->GetRootView()->GetPreferredSize({});
  gfx::Size max_size = dialog_host->GetMaximumDialogSize();
  // The frame is shifted upward below, so account for its top border before
  // constraining the preferred child-dialog size to the host WebView.
  max_size.Enlarge(0,
                   widget->non_client_view()->frame_view()->GetInsets().top());
  size.SetToMin(max_size);
  UpdateModalDialogPosition(widget, dialog_host, size);
}

views::Widget* ShowWebModalDialogViews(
    views::WidgetDelegate* dialog,
    content::WebContents* initiator_web_contents) {
  // The initial Wasm smoke owns exactly one direct top-level WebContents. Do
  // not enter guest-view resolution here: guest WebContents are outside this
  // narrow source-selected slice.
  CHECK(initiator_web_contents);
  views::Widget* const widget =
      CreateWebModalDialogViews(dialog, initiator_web_contents);
  ShowModalDialog(widget->GetNativeWindow(), initiator_web_contents);
  return widget;
}

std::unique_ptr<views::Widget> ShowWebModalDialogViewsOwned(
    views::WidgetDelegate* dialog,
    content::WebContents* initiator_web_contents,
    views::Widget::InitParams::Ownership expected_ownership) {
  views::Widget* const widget =
      ShowWebModalDialogViews(dialog, initiator_web_contents);
  CHECK_EQ(widget->ownership(), expected_ownership);
  return base::WrapUnique(widget);
}

views::Widget* CreateWebModalDialogViews(views::WidgetDelegate* dialog,
                                         content::WebContents* web_contents) {
  CHECK(dialog);
  CHECK(web_contents);
  DCHECK_EQ(ui::mojom::ModalType::kChild, dialog->GetModalType());

  web_modal::WebContentsModalDialogManager* const manager =
      web_modal::WebContentsModalDialogManager::FromWebContents(web_contents);
  CHECK(manager);
  CHECK(manager->delegate());
  web_modal::WebContentsModalDialogHost* const dialog_host =
      manager->delegate()->GetWebContentsModalDialogHost(web_contents);
  CHECK(dialog_host);
  CHECK(dialog_host->ShouldConstrainDialogBoundsByHost());

  // Ozone Wasm has no desktop child-window implementation. Keep the dialog in
  // the one BrowserWidget Aura tree supplied by WasmTabModalDialogHost.
  dialog->set_use_desktop_widget_override(false);

  views::Widget* const widget = views::DialogDelegate::CreateDialogWidget(
      dialog, gfx::NativeWindow(), dialog_host->GetHostView());
  std::unique_ptr<ModalDialogHostObserver> observer =
      std::make_unique<ModalDialogHostObserverViews>(dialog_host, widget);
  widget->SetProperty(kModalDialogHostObserverKey, std::move(observer));
  ConfigureDesiredBoundsDelegate(dialog, dialog_host);
  widget->SetNativeWindowProperty(
      views::kWidgetIdentifierKey,
      const_cast<void*>(kConstrainedWindowWidgetIdentifier));

  return widget;
}

}  // namespace constrained_window
