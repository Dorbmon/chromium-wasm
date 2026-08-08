// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/ui/views/frame/browser_widget.h"

#include <memory>
#include <utility>

#include "base/check.h"
#include "base/no_destructor.h"
#include "build/build_config.h"
#include "chrome/browser/ui/views/frame/browser_native_widget.h"
#include "chrome/browser/ui/views/frame/browser_native_widget_factory.h"
#include "chrome/browser/ui/views/frame/browser_view.h"
#include "chrome/browser/wasm/wasm_default_theme_provider.h"
#include "ui/base/hit_test.h"
#include "ui/base/mojom/window_show_state.mojom.h"
#include "ui/gfx/geometry/point.h"
#include "ui/native_theme/native_theme.h"
#include "ui/views/widget/root_view.h"
#include "ui/views/window/frame_view.h"
#include "ui/views/window/non_client_view.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_widget.cc must only be built for WebAssembly"
#endif

namespace {

const ui::ThemeProvider& GetWasmDefaultThemeProvider() {
  // The provider is immutable and shared by every Wasm browser widget. It
  // deliberately has no profile-backed customization or destruction-order
  // dependency on the ResourceBundle it queries on demand.
  static const base::NoDestructor<WasmDefaultThemeProvider> provider;
  return *provider;
}

// FrameView's generic base implementation reserves no client area because it
// is normally completed by a platform-specific frame. Wasm deliberately has
// neither a host-native frame nor a BrowserFrameView, so keep the generic
// Views frame and define its one required content-only geometry policy here.
class WasmContentFrameView final : public views::FrameView {
 public:
  WasmContentFrameView() = default;
  WasmContentFrameView(const WasmContentFrameView&) = delete;
  WasmContentFrameView& operator=(const WasmContentFrameView&) = delete;
  ~WasmContentFrameView() override = default;

  gfx::Rect GetBoundsForClientView() const override {
    return GetLocalBounds();
  }

  gfx::Rect GetWindowBoundsForClientBounds(
      const gfx::Rect& client_bounds) const override {
    return client_bounds;
  }

  int NonClientHitTest(const gfx::Point& point) override {
    return GetLocalBounds().Contains(point) ? HTCLIENT : HTNOWHERE;
  }
};

}  // namespace

BrowserWidget::BrowserWidget(BrowserView* browser_view)
    : browser_native_widget_(nullptr), browser_view_(browser_view) {
  CHECK(browser_view_);

  // Selecting a tab will focus its WebContents after a joined Browser/tab
  // lifecycle is added. The structural content host must not claim focus first.
  set_focus_on_creation(false);
}

BrowserWidget::~BrowserWidget() {
  // Do not tear down a Browser or its feature owner here. Those objects are
  // outside this object-only source closure, and the close/unload/modal owner
  // must be selected before they can be destroyed safely.
  set_widget_closed();
}

void BrowserWidget::InitBrowserWidget() {
  CHECK(!browser_native_widget_);

  browser_native_widget_ =
      BrowserNativeWidgetFactory::CreateBrowserNativeWidget(this, browser_view_);
  CHECK(browser_native_widget_);

  views::Widget::InitParams params = browser_native_widget_->GetWidgetParams(
      views::Widget::InitParams::CLIENT_OWNS_WIDGET);
  params.name = "BrowserWidgetWasm";
  params.delegate = browser_view_;
  Init(std::move(params));

  // Ozone Wasm supplies the real Aura native widget. The browser-frame theme
  // remains a fixed ResourceBundle-backed provider rather than a profile or
  // host-page theme.
  SetNativeTheme(ui::NativeTheme::GetInstanceForNativeUi());

  // The platform accurately reports that no OS system menu exists. Install the
  // controller so an attempted non-client context-menu route fails explicitly
  // below instead of silently suggesting that a host-page menu was shown.
  CHECK(non_client_view());
  non_client_view()->set_context_menu_controller(this);
}

BrowserFrameView* BrowserWidget::GetFrameView() const {
  // This content-only slice deliberately creates a generic Views FrameView,
  // not a BrowserFrameView with tab-strip or toolbar behavior.
  return nullptr;
}

bool BrowserWidget::ShouldSaveWindowPlacement() const {
  return browser_native_widget_ &&
         browser_native_widget_->ShouldSaveWindowPlacement();
}

void BrowserWidget::GetWindowPlacement(
    gfx::Rect* bounds,
    ui::mojom::WindowShowState* show_state) const {
  CHECK(bounds);
  CHECK(show_state);
  CHECK(browser_native_widget_)
      << "Wasm BrowserWidget placement requested before initialization";
  browser_native_widget_->GetWindowPlacement(bounds, show_state);
}

content::KeyboardEventProcessingResult BrowserWidget::PreHandleKeyboardEvent(
    const input::NativeWebKeyboardEvent& event) {
  return browser_native_widget_
             ? browser_native_widget_->PreHandleKeyboardEvent(event)
             : content::KeyboardEventProcessingResult::NOT_HANDLED;
}

bool BrowserWidget::HandleKeyboardEvent(
    const input::NativeWebKeyboardEvent& event) {
  return browser_native_widget_ &&
         browser_native_widget_->HandleKeyboardEvent(event);
}

void BrowserWidget::UserChangedTheme(
    BrowserThemeChangeType theme_change_type) {
  static_cast<void>(theme_change_type);

  // The fixed Wasm provider has no profile/custom-theme state to regenerate.
  // Views still needs a real repaint after a native-theme notification.
  ThemeChanged();
}

views::internal::RootView* BrowserWidget::CreateRootView() {
  // The desktop-specific root owns tab-drag and frame behavior. The generic
  // root preserves actual Views input/focus routing without importing it.
  return new views::internal::RootView(this);
}

std::unique_ptr<views::FrameView> BrowserWidget::CreateFrameView() {
  // BrowserNativeWidgetWasm removes the host-native frame. This generic Views
  // FrameView subclass is the full client boundary, not a replacement Chrome
  // BrowserFrameView with tab-strip or toolbar behavior.
  return std::make_unique<WasmContentFrameView>();
}

bool BrowserWidget::GetAccelerator(int command_id,
                                   ui::Accelerator* accelerator) const {
  CHECK(browser_view_);
  return browser_view_->GetAccelerator(command_id, accelerator);
}

const ui::ThemeProvider* BrowserWidget::GetThemeProvider() const {
  return &GetWasmDefaultThemeProvider();
}

ui::ColorProviderKey::ThemeInitializerSupplier*
BrowserWidget::GetCustomTheme() const {
  // Profile-backed custom themes are intentionally outside the Wasm window
  // source closure.
  return nullptr;
}

void BrowserWidget::OnNativeWidgetWorkspaceChanged() {
  // The Wasm platform reports no workspace persistence. Preserve Views'
  // observer notification without claiming that Chrome state was saved.
  views::Widget::OnNativeWidgetWorkspaceChanged();
}

void BrowserWidget::OnNativeWidgetDestroyed() {
  browser_native_widget_ = nullptr;

  // A Browser-backed window needs ordered unload, modal cancellation, tab
  // detachment, and feature teardown. This structural target is useful only
  // with a null Browser identity, where normal Views teardown is truthful and
  // allows a future focused widget smoke to clean up.
  CHECK(!browser_view_ || !browser_view_->browser())
      << "Wasm BrowserWidget Browser destruction lifecycle is not selected";
  views::Widget::OnNativeWidgetDestroyed();
}

void BrowserWidget::ShowContextMenuForViewImpl(
    views::View* source,
    const gfx::Point& p,
    ui::mojom::MenuSourceType source_type) {
  static_cast<void>(source);
  static_cast<void>(p);
  static_cast<void>(source_type);
  CHECK(false) << "Wasm BrowserWidget system-menu presentation is not selected";
}

bool BrowserWidget::IsMenuRunnerRunningForTesting() const {
  // No system-menu source is selected for the content-only browser widget.
  return false;
}

ui::MenuModel* BrowserWidget::GetSystemMenuModel() {
  CHECK(false) << "Wasm BrowserWidget system-menu model is not selected";
}

void BrowserWidget::SetTabDragKind(TabDragKind tab_drag_kind) {
  CHECK(tab_drag_kind == TabDragKind::kNone)
      << "Wasm BrowserWidget tab dragging is not selected";
  tab_drag_kind_ = tab_drag_kind;
}

void BrowserWidget::OnNativeThemeUpdated(ui::NativeTheme* observed_theme) {
  views::Widget::OnNativeThemeUpdated(observed_theme);
}

ui::ColorProviderKey BrowserWidget::GetColorProviderKey() const {
  auto key = views::Widget::GetColorProviderKey();
  key.frame_type = ui::ColorProviderKey::FrameType::kChromium;
  return key;
}

void BrowserWidget::OnTouchUiChanged() {
  if (client_view()) {
    client_view()->InvalidateLayout();
  }
  if (non_client_view()) {
    non_client_view()->InvalidateLayout();
  }
  if (GetRootView()) {
    GetRootView()->InvalidateLayout();
  }
}

void BrowserWidget::OnMenuClosed() {
  CHECK(false) << "Wasm BrowserWidget system-menu presentation is not selected";
}

void BrowserWidget::SelectNativeTheme() {
  SetNativeTheme(ui::NativeTheme::GetInstanceForNativeUi());
}

bool BrowserWidget::RegenerateFrameOnThemeChange(
    BrowserThemeChangeType theme_change_type) {
  static_cast<void>(theme_change_type);
  // A generic FrameView has no Chrome frame policy to regenerate.
  return false;
}

bool BrowserWidget::IsIncognitoBrowser() const {
  CHECK(false) << "Wasm BrowserWidget profile lifecycle is not selected";
}
