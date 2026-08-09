// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_TAB_STRIP_VIEW_H_
#define CHROME_BROWSER_WASM_WASM_TAB_STRIP_VIEW_H_

#include <array>

#include "base/callback_list.h"
#include "base/memory/raw_ptr.h"
#include "chrome/browser/ui/tabs/tab_strip_model_observer.h"
#include "ui/base/metadata/metadata_header_macros.h"
#include "ui/views/view.h"

class BrowserWindowInterface;
class TabStripModel;

namespace tabs {
class TabInterface;
}  // namespace tabs

namespace ui {
class Event;
}  // namespace ui

namespace views {
class LabelButton;
}  // namespace views

// The first Wasm tab strip is a deliberately bounded Views surface over the
// source-selected TabStripModel. It exposes only two ordinary tab-selection
// buttons; creation, closing, reordering, drag, groups, tab menus, and the
// desktop TabStrip controller remain outside this source closure.
class WasmTabStripView final : public views::View,
                               public TabStripModelObserver {
  METADATA_HEADER(WasmTabStripView, views::View)

 public:
  explicit WasmTabStripView(BrowserWindowInterface* browser_window_interface);
  WasmTabStripView(const WasmTabStripView&) = delete;
  WasmTabStripView& operator=(const WasmTabStripView&) = delete;
  ~WasmTabStripView() override;

  // This accessor exposes the real Views input entry point used by the
  // switch-gated Browser smoke. It does not create a second tab API.
  views::LabelButton* tab_button_for_testing(int index) const;

 private:
  void SyncFromModel();
  void UpdateButtonForTab(int index);
  void ClearButton(int index);
  void OnTabUIChanged(tabs::TabInterface* tab);
  void ActivateTab(int index, const ui::Event& event);

  // TabStripModelObserver:
  void OnTabStripModelChanged(
      TabStripModel* tab_strip_model,
      const TabStripModelChange& change,
      const TabStripSelectionChange& selection) override;
  void OnTabWillBeRemoved(tabs::TabInterface* tab, int index) override;
  void OnTabStripModelDestroyed(TabStripModel* tab_strip_model) override;

  const raw_ptr<BrowserWindowInterface> browser_window_interface_;
  raw_ptr<TabStripModel> tab_strip_model_ = nullptr;
  std::array<raw_ptr<views::LabelButton>, 2> tab_buttons_ = {};
  std::array<base::CallbackListSubscription, 2> tab_ui_change_subscriptions_;
};

#endif  // CHROME_BROWSER_WASM_WASM_TAB_STRIP_VIEW_H_
