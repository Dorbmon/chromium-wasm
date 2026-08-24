// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_UI_VIEWS_FRAME_BROWSER_DESKTOP_WINDOW_TREE_HOST_WASM_H_
#define CHROME_BROWSER_UI_VIEWS_FRAME_BROWSER_DESKTOP_WINDOW_TREE_HOST_WASM_H_

#include "chrome/browser/ui/views/frame/browser_desktop_window_tree_host.h"
#include "ui/views/widget/desktop_aura/desktop_window_tree_host_platform.h"

namespace views {
class DesktopNativeWidgetAura;
namespace internal {
class NativeWidgetDelegate;
}
}  // namespace views

// The browser frame on Wasm is an Aura desktop widget backed by the Ozone Wasm
// PlatformWindow.  DesktopWindowTreeHostPlatform already supplies the generic
// Aura/PlatformWindow lifecycle; unlike Linux it does not require window
// manager, D-Bus, X11, or Wayland integration.
class BrowserDesktopWindowTreeHostWasm
    : public BrowserDesktopWindowTreeHost,
      public views::DesktopWindowTreeHostPlatform {
 public:
  BrowserDesktopWindowTreeHostWasm(
      views::internal::NativeWidgetDelegate* native_widget_delegate,
      views::DesktopNativeWidgetAura* desktop_native_widget_aura);
  BrowserDesktopWindowTreeHostWasm(const BrowserDesktopWindowTreeHostWasm&) =
      delete;
  BrowserDesktopWindowTreeHostWasm& operator=(
      const BrowserDesktopWindowTreeHostWasm&) = delete;
  ~BrowserDesktopWindowTreeHostWasm() override;

 private:
  // BrowserDesktopWindowTreeHost:
  views::DesktopWindowTreeHost* AsDesktopWindowTreeHost() override;
  bool UsesNativeSystemMenu() const override;

  // DesktopWindowTreeHost:
  void InitModalType(ui::mojom::ModalType modal_type) override;
};

#endif  // CHROME_BROWSER_UI_VIEWS_FRAME_BROWSER_DESKTOP_WINDOW_TREE_HOST_WASM_H_
