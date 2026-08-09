// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/ui/browser_window.h"

#include <memory>

#include "base/check.h"
#include "build/build_config.h"
#include "chrome/browser/ui/browser_window_deleter.h"
#include "chrome/browser/ui/views/frame/browser_view.h"
#include "chrome/browser/ui/views/frame/browser_widget.h"
#include "ui/aura/client/aura_constants.h"
#include "ui/aura/window.h"
#include "ui/views/widget/widget.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_window_factory.cc must only be built for WebAssembly"
#endif

// static
std::unique_ptr<BrowserWindow, BrowserWindowDeleter>
BrowserWindow::CreateBrowserWindow(Browser* browser,
                                   bool user_gesture,
                                   bool in_tab_dragging) {
  CHECK(browser);
  CHECK(!in_tab_dragging)
      << "Wasm BrowserWindow factory does not support tab-drag creation";

  // BrowserWidget's RootView owns |view| after InitBrowserWidget(). Do not put
  // the view in a unique_ptr here: BrowserWindowDeleter reaches
  // BrowserView::DeleteBrowserWindow(), which breaks that Views ownership
  // cycle only after the future Browser owner has completed tab/BWF teardown.
  BrowserView* const view = new BrowserView(browser);
  auto browser_widget = std::make_unique<BrowserWidget>(view);
  view->set_browser_widget(std::move(browser_widget));
  view->browser_widget()->InitBrowserWidget();

  aura::Window* const native_window = view->GetWidget()->GetNativeWindow();
  CHECK(native_window);
  native_window->SetProperty(aura::client::kCreatedByUserGesture,
                             user_gesture);

  return std::unique_ptr<BrowserWindow, BrowserWindowDeleter>(view);
}
