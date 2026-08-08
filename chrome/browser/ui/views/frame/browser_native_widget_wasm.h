// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_UI_VIEWS_FRAME_BROWSER_NATIVE_WIDGET_WASM_H_
#define CHROME_BROWSER_UI_VIEWS_FRAME_BROWSER_NATIVE_WIDGET_WASM_H_

#include <memory>

#include "base/memory/raw_ptr.h"
#include "chrome/browser/ui/views/frame/browser_native_widget.h"
#include "ui/views/widget/desktop_aura/desktop_native_widget_aura.h"

class BrowserWidget;

namespace wm {
class VisibilityController;
}

// BrowserNativeWidgetWasm is the browser-specific NativeWidget implementation
// for the Ozone Wasm platform. It owns the BrowserNativeWidget policy boundary
// instead of adapting a generic Widget shell: BrowserWidget still creates it
// through BrowserNativeWidgetFactory and delegates native-widget lifecycle to
// it, while the Aura host is supplied by BrowserDesktopWindowTreeHostWasm.
//
// A browser-hosted canvas does not have an OS window placement, workspace, or
// system menu. Those capabilities are explicitly disabled here rather than
// mapped to host-page state. BrowserView is intentionally not retained or
// observed by this platform layer; browser-specific view work stays above the
// Ozone boundary.
class BrowserNativeWidgetWasm : public views::DesktopNativeWidgetAura,
                                public BrowserNativeWidget {
 public:
  explicit BrowserNativeWidgetWasm(BrowserWidget* browser_widget);

  BrowserNativeWidgetWasm(const BrowserNativeWidgetWasm&) = delete;
  BrowserNativeWidgetWasm& operator=(const BrowserNativeWidgetWasm&) = delete;

 protected:
  ~BrowserNativeWidgetWasm() override;

  // views::DesktopNativeWidgetAura:
  void OnHostClosed() override;
  void InitNativeWidget(views::Widget::InitParams params) override;
  void ClientDestroyedWidget() override;

  // BrowserNativeWidget:
  views::Widget::InitParams GetWidgetParams(
      views::Widget::InitParams::Ownership ownership) override;
  bool UseCustomFrame() const override;
  bool UsesNativeSystemMenu() const override;
  bool ShouldSaveWindowPlacement() const override;
  void GetWindowPlacement(
      gfx::Rect* bounds,
      ui::mojom::WindowShowState* show_state) const override;
  content::KeyboardEventProcessingResult PreHandleKeyboardEvent(
      const input::NativeWebKeyboardEvent& event) override;
  bool HandleKeyboardEvent(const input::NativeWebKeyboardEvent& event) override;
  bool ShouldRestorePreviousBrowserWidgetState() const override;
  bool ShouldUseInitialVisibleOnAllWorkspaces() const override;

 private:
  // BrowserWidget outlives this NativeWidget during the normal client-owned
  // Widget teardown. Clear the pointer on both host- and client-driven
  // shutdown paths before delegating to DesktopNativeWidgetAura.
  raw_ptr<BrowserWidget> browser_widget_;

  // Installed on the root Aura window after its Wasm desktop host has been
  // initialized. It supplies the standard Views child-visibility animation
  // contract without relying on an OS window manager.
  std::unique_ptr<wm::VisibilityController> visibility_controller_;
};

#endif  // CHROME_BROWSER_UI_VIEWS_FRAME_BROWSER_NATIVE_WIDGET_WASM_H_
