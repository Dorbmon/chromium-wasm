// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_TAB_STRIP_VIEW_H_
#define CHROME_BROWSER_WASM_WASM_TAB_STRIP_VIEW_H_

#include <array>

#include "base/callback_list.h"
#include "base/functional/callback.h"
#include "base/memory/raw_ptr.h"
#include "base/time/time.h"
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
// source-selected TabStripModel. It exposes two ordinary tab-selection
// buttons plus explicit create/close affordances supplied by its Browser
// owner. Reordering, drag, groups, tab menus, and the desktop TabStrip
// controller remain outside this source closure.
class WasmTabStripView final : public views::View,
                               public TabStripModelObserver {
  METADATA_HEADER(WasmTabStripView, views::View)

 public:
  WasmTabStripView(
      BrowserWindowInterface* browser_window_interface,
      base::RepeatingCallback<bool()> create_tab_callback,
      base::RepeatingCallback<bool()> can_create_tab_callback,
      base::RepeatingCallback<bool(int)> can_activate_tab_callback,
      base::RepeatingCallback<bool(int)> close_tab_callback,
      base::RepeatingCallback<bool(int)> can_close_tab_callback);
  WasmTabStripView(const WasmTabStripView&) = delete;
  WasmTabStripView& operator=(const WasmTabStripView&) = delete;
  ~WasmTabStripView() override;

  // These accessors expose the real Views input entry points used by the
  // switch-gated Browser smoke. The callbacks remain Browser-owned; this View
  // never creates, closes, or owns WebContents itself.
  views::LabelButton* tab_button_for_testing(int index) const;
  views::LabelButton* new_tab_button_for_testing() const;
  views::LabelButton* close_tab_button_for_testing(int index) const;

  // BrowserView invokes this only from registered keyboard accelerators. It
  // retains the model's real keyboard user-gesture semantics and never adds
  // tabs, changes their order, or reaches the desktop tab-strip controller.
  bool ActivateRelativeTabForAccelerator(bool previous,
                                         base::TimeTicks time_stamp);

 private:
  void SyncFromModel();
  void UpdateButtonForTab(int index);
  void UpdateActionButtons();
  void ClearButton(int index);
  void OnTabUIChanged(tabs::TabInterface* tab);
  void ActivateTab(int index, const ui::Event& event);
  void CreateTab(const ui::Event& event);
  void CloseTab(int index, const ui::Event& event);

  // TabStripModelObserver:
  void OnTabStripModelChanged(
      TabStripModel* tab_strip_model,
      const TabStripModelChange& change,
      const TabStripSelectionChange& selection) override;
  void OnTabChangedAt(tabs::TabInterface* tab,
                      int index,
                      TabChangeType change_type) override;
  void OnTabWillBeRemoved(tabs::TabInterface* tab, int index) override;
  void OnTabStripModelDestroyed(TabStripModel* tab_strip_model) override;

  const raw_ptr<BrowserWindowInterface> browser_window_interface_;
  raw_ptr<TabStripModel> tab_strip_model_ = nullptr;
  std::array<raw_ptr<views::LabelButton>, 2> tab_buttons_ = {};
  std::array<raw_ptr<views::LabelButton>, 2> close_tab_buttons_ = {};
  raw_ptr<views::LabelButton> new_tab_button_ = nullptr;
  std::array<base::CallbackListSubscription, 2> tab_ui_change_subscriptions_;
  base::RepeatingCallback<bool()> create_tab_callback_;
  base::RepeatingCallback<bool()> can_create_tab_callback_;
  base::RepeatingCallback<bool(int)> can_activate_tab_callback_;
  base::RepeatingCallback<bool(int)> close_tab_callback_;
  base::RepeatingCallback<bool(int)> can_close_tab_callback_;
};

#endif  // CHROME_BROWSER_WASM_WASM_TAB_STRIP_VIEW_H_
