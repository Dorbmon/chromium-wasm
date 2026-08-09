// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_MENU_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_MENU_H_

#include "base/callback_list.h"
#include "base/memory/raw_ptr.h"
#include "chrome/browser/command_observer.h"
#include "ui/base/metadata/metadata_header_macros.h"
#include "ui/views/view.h"

class BrowserWindowInterface;

namespace chrome {
class BrowserCommandController;
}  // namespace chrome

namespace ui {
class Event;
}  // namespace ui

namespace views {
class LabelButton;
}  // namespace views

// A deliberately small in-canvas app menu for the one-surface Wasm embedding.
// Desktop MenuRunner creates a second native menu Widget, while ozone_wasm
// truthfully owns one compositor surface. Keeping this panel in BrowserView's
// existing Views tree preserves real Aura/Views input and presentation without
// claiming desktop multi-window menu support.
class WasmBrowserMenuView final : public views::View,
                                  public CommandObserver {
  METADATA_HEADER(WasmBrowserMenuView, views::View)

 public:
  WasmBrowserMenuView(
      BrowserWindowInterface* browser_window_interface,
      chrome::BrowserCommandController* browser_command_controller);
  WasmBrowserMenuView(const WasmBrowserMenuView&) = delete;
  WasmBrowserMenuView& operator=(const WasmBrowserMenuView&) = delete;
  ~WasmBrowserMenuView() override;

  void Toggle();
  void Close();
  bool IsOpen() const { return GetVisible(); }

  // Narrow smoke-only accessors. They expose the actual child controls rather
  // than a second menu command route.
  views::LabelButton* reload_button_for_testing() const {
    return reload_button_;
  }
  views::LabelButton* about_button_for_testing() const {
    return about_button_;
  }
  views::LabelButton* settings_button_for_testing() const {
    return settings_button_;
  }

 private:
  void ActiveTabChanged(BrowserWindowInterface* browser_window_interface);
  void UpdateEnabledState();
  void Reload(const ui::Event& event);
  void ShowVersion(const ui::Event& event);
  void ShowSettings(const ui::Event& event);
  bool NavigateTo(const char* url, const ui::Event& event);

  // CommandObserver:
  void EnabledStateChangedForCommand(int command_id, bool enabled) override;

  const raw_ptr<BrowserWindowInterface> browser_window_interface_;
  const raw_ptr<chrome::BrowserCommandController>
      browser_command_controller_;
  raw_ptr<views::LabelButton> reload_button_ = nullptr;
  raw_ptr<views::LabelButton> about_button_ = nullptr;
  raw_ptr<views::LabelButton> settings_button_ = nullptr;
  base::CallbackListSubscription active_tab_changed_subscription_;
};

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_MENU_H_
