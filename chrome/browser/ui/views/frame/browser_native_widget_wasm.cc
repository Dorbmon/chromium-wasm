// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/ui/views/frame/browser_native_widget_wasm.h"

#include <utility>

#include "base/check.h"
#include "build/build_config.h"
#include "chrome/browser/ui/views/frame/browser_desktop_window_tree_host.h"
#include "chrome/browser/ui/views/frame/browser_native_widget_factory.h"
#include "chrome/browser/ui/views/frame/browser_widget.h"
#include "ui/aura/client/aura_constants.h"
#include "ui/aura/window.h"
#include "ui/base/mojom/window_show_state.mojom.h"
#include "ui/gfx/geometry/rect.h"
#include "ui/views/widget/widget.h"
#include "ui/wm/core/visibility_controller.h"

#if !BUILDFLAG(IS_WASM)
#error "browser_native_widget_wasm.cc must only be built for Wasm"
#endif

BrowserNativeWidgetWasm::BrowserNativeWidgetWasm(
    BrowserWidget* browser_widget)
    : views::DesktopNativeWidgetAura(browser_widget),
      browser_widget_(browser_widget) {
  CHECK(browser_widget_);
  GetNativeWindow()->SetName("BrowserNativeWidgetWasm");
}

BrowserNativeWidgetWasm::~BrowserNativeWidgetWasm() = default;

void BrowserNativeWidgetWasm::OnHostClosed() {
  aura::client::SetVisibilityClient(GetNativeView()->GetRootWindow(), nullptr);
  visibility_controller_.reset();
  browser_widget_ = nullptr;
  views::DesktopNativeWidgetAura::OnHostClosed();
}

void BrowserNativeWidgetWasm::InitNativeWidget(
    views::Widget::InitParams params) {
  CHECK(browser_widget_);

  // BrowserDesktopWindowTreeHostWasm owns the desktop Aura/Ozone connection.
  // Its factory keeps the common BrowserWidget contract, but the Wasm host
  // does not inspect BrowserView; pass no view rather than retaining a view
  // that can be destroyed independently of the platform window.
  auto* browser_desktop_window_tree_host =
      BrowserDesktopWindowTreeHost::CreateBrowserDesktopWindowTreeHost(
          browser_widget_, this, nullptr, browser_widget_);
  params.desktop_window_tree_host =
      browser_desktop_window_tree_host->AsDesktopWindowTreeHost();
  views::DesktopNativeWidgetAura::InitNativeWidget(std::move(params));

  visibility_controller_ = std::make_unique<wm::VisibilityController>();
  aura::client::SetVisibilityClient(GetNativeView()->GetRootWindow(),
                                    visibility_controller_.get());
  wm::SetChildWindowVisibilityChangesAnimated(GetNativeView()->GetRootWindow());
}

void BrowserNativeWidgetWasm::ClientDestroyedWidget() {
  browser_widget_ = nullptr;
  views::DesktopNativeWidgetAura::ClientDestroyedWidget();
}

views::Widget::InitParams BrowserNativeWidgetWasm::GetWidgetParams(
    views::Widget::InitParams::Ownership ownership) {
  views::Widget::InitParams params(ownership);
  params.native_widget = this;

  // WasmWindow requires a concrete initial logical surface when Aura creates
  // its PlatformWindow. BrowserWidget normally receives its persisted bounds
  // from the desktop placement path, which is intentionally unsupported here.
  // This non-persistent fallback is superseded by a later host resize.
  if (params.bounds.IsEmpty()) {
    params.bounds = gfx::Rect(0, 0, 1024, 768);
  }

  // The frame is rendered by Chrome Views into the Ozone Wasm canvas. There
  // is no host-native titlebar to retain beneath it.
  params.remove_standard_frame = true;
  return params;
}

bool BrowserNativeWidgetWasm::UseCustomFrame() const {
  return true;
}

bool BrowserNativeWidgetWasm::UsesNativeSystemMenu() const {
  // BrowserWidget presents its system menu through Views. The host page never
  // receives a synthetic OS menu request.
  return false;
}

bool BrowserNativeWidgetWasm::ShouldSaveWindowPlacement() const {
  // A canvas surface has no durable OS placement. Do not claim that Chrome's
  // placement data was persisted in host-page state.
  return false;
}

void BrowserNativeWidgetWasm::GetWindowPlacement(
    gfx::Rect* bounds,
    ui::mojom::WindowShowState* show_state) const {
  // This is reachable only through callers that already honor
  // ShouldSaveWindowPlacement(). Keep the fallback explicit and non-persistent
  // for defensive callers.
  *bounds = gfx::Rect();
  *show_state = ui::mojom::WindowShowState::kNormal;
}

content::KeyboardEventProcessingResult
BrowserNativeWidgetWasm::PreHandleKeyboardEvent(
    const input::NativeWebKeyboardEvent& event) {
  // The host bridge has already forwarded DOM input into Aura. There is no
  // native menu bar or OS accelerator path that can consume this event first.
  return content::KeyboardEventProcessingResult::NOT_HANDLED;
}

bool BrowserNativeWidgetWasm::HandleKeyboardEvent(
    const input::NativeWebKeyboardEvent& event) {
  return false;
}

bool BrowserNativeWidgetWasm::ShouldRestorePreviousBrowserWidgetState() const {
  // BrowserWidget must not read desktop saved bounds/workspace state for a
  // browser-hosted canvas.
  return false;
}

bool BrowserNativeWidgetWasm::ShouldUseInitialVisibleOnAllWorkspaces() const {
  // The host page has one canvas surface and no workspace model.
  return false;
}

BrowserNativeWidget* BrowserNativeWidgetFactory::Create(
    BrowserWidget* browser_widget,
    BrowserView*) {
  return new BrowserNativeWidgetWasm(browser_widget);
}
