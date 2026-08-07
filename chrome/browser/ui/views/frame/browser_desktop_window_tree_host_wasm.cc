// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/ui/views/frame/browser_desktop_window_tree_host_wasm.h"

#include "build/build_config.h"
#include "ui/views/widget/desktop_aura/desktop_native_widget_aura.h"

#if !BUILDFLAG(IS_WASM)
#error "browser_desktop_window_tree_host_wasm.cc must only be built for Wasm"
#endif

BrowserDesktopWindowTreeHostWasm::BrowserDesktopWindowTreeHostWasm(
    views::internal::NativeWidgetDelegate* native_widget_delegate,
    views::DesktopNativeWidgetAura* desktop_native_widget_aura)
    : DesktopWindowTreeHostPlatform(native_widget_delegate,
                                    desktop_native_widget_aura) {}

BrowserDesktopWindowTreeHostWasm::~BrowserDesktopWindowTreeHostWasm() =
    default;

views::DesktopWindowTreeHost*
BrowserDesktopWindowTreeHostWasm::AsDesktopWindowTreeHost() {
  return this;
}

bool BrowserDesktopWindowTreeHostWasm::UsesNativeSystemMenu() const {
  // There is no host-OS menu. BrowserWidget owns any menu presentation that
  // the Wasm Ozone surface supports.
  return false;
}

BrowserDesktopWindowTreeHost*
BrowserDesktopWindowTreeHost::CreateBrowserDesktopWindowTreeHost(
    views::internal::NativeWidgetDelegate* native_widget_delegate,
    views::DesktopNativeWidgetAura* desktop_native_widget_aura,
    BrowserView*,
    BrowserWidget*) {
  return new BrowserDesktopWindowTreeHostWasm(native_widget_delegate,
                                              desktop_native_widget_aura);
}
