// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/ui/views/frame/browser_view.h"

#include <memory>
#include <utility>

#include "base/check.h"
#include "base/check_op.h"
#include "base/functional/bind.h"
#include "build/build_config.h"
#include "chrome/browser/ui/views/frame/browser_widget.h"
#include "content/public/browser/keyboard_event_processing_result.h"
#include "content/public/browser/web_contents.h"
#include "ui/base/metadata/metadata_impl_macros.h"
#include "ui/base/mojom/window_show_state.mojom.h"
#include "ui/gfx/geometry/point.h"
#include "ui/gfx/geometry/rect.h"
#include "ui/gfx/geometry/size.h"
#include "ui/views/controls/webview/webview.h"
#include "ui/views/layout/fill_layout.h"
#include "ui/views/widget/widget.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_view.cc must only be built for WebAssembly"
#endif

BrowserView::BrowserView(Browser* browser)
    : views::ClientView(/*widget=*/nullptr, /*contents_view=*/nullptr),
      browser_(browser) {
  auto contents_web_view = std::make_unique<views::WebView>();
  contents_web_view_ = AddChildView(std::move(contents_web_view));
  set_contents_view(contents_web_view_);
  SetLayoutManager(std::make_unique<views::FillLayout>());

  // Do not give WebView a BrowserContext. This class must never create or own
  // a WebContents; the future joined TabModel lifecycle remains its owner.
  tab_modal_dialog_host_ =
      std::make_unique<WasmTabModalDialogHost>(contents_web_view_);
  web_contents_detached_subscription_ =
      contents_web_view_->AddWebContentsDetachedCallback(base::BindRepeating(
          &BrowserView::OnWebContentsDetached, base::Unretained(this)));
}

BrowserView::~BrowserView() {
  widget_observation_.Reset();
  tab_modal_dialog_host_.reset();
  if (contents_web_view_) {
    contents_web_view_->SetWebContents(nullptr);
  }
  active_web_contents_ = nullptr;
}

void BrowserView::set_browser_widget(std::unique_ptr<BrowserWidget> widget) {
  CHECK(widget);
  CHECK(!browser_widget_);
  browser_widget_ = std::move(widget);
}

BrowserWidget* BrowserView::browser_widget() const {
  return browser_widget_.get();
}

void BrowserView::SetWasmCloseRequestCallbackForSmoke(
    base::RepeatingCallback<views::CloseRequestResult()> callback) {
  CHECK(callback);
  CHECK(!wasm_close_request_callback_);
  wasm_close_request_callback_ = std::move(callback);
}

// static
void BrowserView::DestroyForWasmBrowserViewSmoke(BrowserView* browser_view) {
  CHECK(browser_view);
  CHECK(!browser_view->browser_)
      << "Wasm BrowserView Browser destruction lifecycle is not selected";
  CHECK(browser_view->browser_widget_);
  CHECK(!browser_view->active_web_contents_)
      << "Detach the externally owned WebContents before Widget teardown";

  // BrowserWidget's RootView owns |browser_view| as its ClientView. Resetting
  // this unique_ptr is the canonical cycle break: it destroys the Widget and
  // then this BrowserView through the Views tree. Do not touch
  // |browser_view| after this statement.
  browser_view->browser_widget_.reset();
}

bool BrowserView::GetAccelerator(int command_id,
                                 ui::Accelerator* accelerator) const {
  static_cast<void>(command_id);
  static_cast<void>(accelerator);
  // No Chrome command/menu surface is selected for this content-only host.
  return false;
}

// static
BrowserView* BrowserView::GetBrowserViewForNativeWindow(
    gfx::NativeWindow window) {
  views::Widget* const widget = views::Widget::GetWidgetForNativeWindow(window);
  return widget ? reinterpret_cast<BrowserView*>(
                      widget->GetNativeWindowProperty(kBrowserViewKey))
                : nullptr;
}

// static
BrowserWindow* BrowserWindow::FindBrowserWindowWithWebContents(
    content::WebContents* web_contents) {
  if (!web_contents) {
    return nullptr;
  }

  views::Widget* const widget = views::Widget::GetTopLevelWidgetForNativeView(
      web_contents->GetNativeView());
  return widget ? BrowserView::GetBrowserViewForNativeWindow(
                      widget->GetNativeWindow())
                : nullptr;
}

void BrowserView::Show() {
  RequireBrowserWidget().Show();
}

void BrowserView::Hide() {
  RequireBrowserWidget().Hide();
}

bool BrowserView::IsVisible() const {
  return RequireBrowserWidget().IsVisible();
}

void BrowserView::ShowInactive() {
  RequireBrowserWidget().ShowInactive();
}

void BrowserView::Close() {
  // Both direct BaseWindow closes and host close requests route through the
  // same coordinator. It retains client ownership while the bounded tab close
  // posts its final Widget teardown; without it this remains unsupported.
  CHECK(wasm_close_request_callback_)
      << "Wasm BrowserView close lifecycle is not selected";
  CHECK_EQ(wasm_close_request_callback_.Run(),
           views::CloseRequestResult::kCannotClose);
}

void BrowserView::Activate() {
  RequireBrowserWidget().Activate();
}

void BrowserView::Deactivate() {
  RequireBrowserWidget().Deactivate();
}

bool BrowserView::IsActive() const {
  return RequireBrowserWidget().IsActive();
}

bool BrowserView::IsMaximized() const {
  return RequireBrowserWidget().IsMaximized();
}

bool BrowserView::IsMinimized() const {
  return RequireBrowserWidget().IsMinimized();
}

bool BrowserView::IsFullscreen() const {
  return RequireBrowserWidget().IsFullscreen();
}

gfx::NativeWindow BrowserView::GetNativeWindow() const {
  const views::Widget* const widget = GetWidget();
  return widget ? widget->GetNativeWindow() : gfx::NativeWindow();
}

gfx::Rect BrowserView::GetRestoredBounds() const {
  gfx::Rect bounds;
  ui::mojom::WindowShowState show_state =
      ui::mojom::WindowShowState::kDefault;
  RequireBrowserWidget().GetWindowPlacement(&bounds, &show_state);
  return bounds;
}

ui::mojom::WindowShowState BrowserView::GetRestoredState() const {
  gfx::Rect bounds;
  ui::mojom::WindowShowState show_state =
      ui::mojom::WindowShowState::kDefault;
  RequireBrowserWidget().GetWindowPlacement(&bounds, &show_state);
  return show_state;
}

gfx::Rect BrowserView::GetBounds() const {
  return RequireBrowserWidget().GetWindowBoundsInScreen();
}

void BrowserView::Maximize() {
  RequireBrowserWidget().Maximize();
}

void BrowserView::Minimize() {
  RequireBrowserWidget().Minimize();
}

void BrowserView::Restore() {
  RequireBrowserWidget().Restore();
}

void BrowserView::SetBounds(const gfx::Rect& bounds) {
  // There is no BrowserFrameView in this object-only slice. Route directly to
  // the real Views Widget rather than pretending a desktop frame exists.
  RequireBrowserWidget().SetBounds(bounds);
}

void BrowserView::FlashFrame(bool flash) {
  RequireBrowserWidget().FlashFrame(flash);
}

ui::ZOrderLevel BrowserView::GetZOrderLevel() const {
  return RequireBrowserWidget().GetZOrderLevel();
}

void BrowserView::SetZOrderLevel(ui::ZOrderLevel order) {
  RequireBrowserWidget().SetZOrderLevel(order);
}

ui::NativeTheme* BrowserView::GetNativeTheme() {
  return const_cast<ui::NativeTheme*>(views::ClientView::GetNativeTheme());
}

const ui::ThemeProvider* BrowserView::GetThemeProvider() const {
  return views::ClientView::GetThemeProvider();
}

const ui::ColorProvider* BrowserView::GetColorProvider() const {
  return views::ClientView::GetColorProvider();
}

void BrowserView::OnActiveTabChanged(content::WebContents* old_contents,
                                     content::WebContents* new_contents,
                                     int index,
                                     int reason) {
  static_cast<void>(old_contents);
  static_cast<void>(index);
  static_cast<void>(reason);
  CHECK(contents_web_view_);

  // WebView is deliberately non-owning here. The future TabModel/Browser
  // lifecycle must explicitly detach before it destroys a WebContents.
  contents_web_view_->SetWebContents(new_contents);
  active_web_contents_ = new_contents;
}

void BrowserView::OnTabDetached(content::WebContents* contents,
                                bool was_active) {
  if (!was_active && contents != active_web_contents_) {
    return;
  }

  CHECK(contents_web_view_);
  contents_web_view_->SetWebContents(nullptr);
  active_web_contents_ = nullptr;
}

gfx::Size BrowserView::GetContentsSize() const {
  CHECK(contents_web_view_);
  return contents_web_view_->size();
}

void BrowserView::SetContentsSize(const gfx::Size& size) {
  if (GetContentsSize() == size) {
    return;
  }

  gfx::Rect bounds = GetBounds();
  bounds.set_size(size);
  SetBounds(bounds);
}

web_modal::WebContentsModalDialogHost*
BrowserView::GetWebContentsModalDialogHost() {
  CHECK(tab_modal_dialog_host_);
  return tab_modal_dialog_host_.get();
}

web_modal::WebContentsModalDialogHost*
BrowserView::GetWebContentsModalDialogHostFor(
    content::WebContents* web_contents) {
  CHECK(!web_contents || web_contents == active_web_contents_)
      << "Wasm BrowserView has no background-tab modal host";
  return GetWebContentsModalDialogHost();
}

bool BrowserView::GetCanResize() {
  return CanResize();
}

ui::mojom::WindowShowState BrowserView::GetWindowShowState() const {
  if (IsMaximized()) {
    return ui::mojom::WindowShowState::kMaximized;
  }
  if (IsMinimized()) {
    return ui::mojom::WindowShowState::kMinimized;
  }
  if (IsFullscreen()) {
    return ui::mojom::WindowShowState::kFullscreen;
  }
  return ui::mojom::WindowShowState::kDefault;
}

BrowserView* BrowserView::AsBrowserView() {
  return this;
}

bool BrowserView::CanResize() const {
  return true;
}

bool BrowserView::CanMaximize() const {
  return true;
}

bool BrowserView::CanMinimize() const {
  return true;
}

bool BrowserView::CanActivate() const {
  return true;
}

views::View* BrowserView::GetContentsView() {
  return contents_web_view_;
}

views::ClientView* BrowserView::CreateClientView(views::Widget* widget) {
  static_cast<void>(widget);
  return this;
}

views::Widget* BrowserView::GetWidget() {
  return views::View::GetWidget();
}

const views::Widget* BrowserView::GetWidget() const {
  return views::View::GetWidget();
}

void BrowserView::OnWidgetDestroying(views::Widget* widget) {
  CHECK(widget_observation_.IsObservingSource(widget));
  widget_observation_.Reset();
  tab_modal_dialog_host_.reset();
  if (contents_web_view_) {
    contents_web_view_->SetWebContents(nullptr);
  }
  active_web_contents_ = nullptr;
}

views::CloseRequestResult BrowserView::OnWindowCloseRequested() {
  CHECK(wasm_close_request_callback_)
      << "Wasm BrowserView close lifecycle is not selected";
  return wasm_close_request_callback_.Run();
}

int BrowserView::NonClientHitTest(const gfx::Point& point) {
  return views::ClientView::NonClientHitTest(point);
}

gfx::Size BrowserView::GetMinimumSize() const {
  return contents_web_view_ ? contents_web_view_->GetMinimumSize()
                            : gfx::Size();
}

void BrowserView::AddedToWidget() {
  views::ClientView::AddedToWidget();
  views::Widget* const widget = GetWidget();
  CHECK(widget);

  if (!widget_observation_.IsObserving()) {
    widget_observation_.Observe(widget);
  }
  widget->SetNativeWindowProperty(kBrowserViewKey, this);
}

void BrowserView::RemovedFromWidget() {
  widget_observation_.Reset();
  views::ClientView::RemovedFromWidget();
}

BrowserWidget& BrowserView::RequireBrowserWidget() const {
  CHECK(browser_widget_);
  return *browser_widget_;
}

void BrowserView::OnWebContentsDetached(views::WebView* web_view) {
  CHECK_EQ(web_view, contents_web_view_);
  active_web_contents_ = nullptr;
}

BEGIN_METADATA(BrowserView)
END_METADATA
