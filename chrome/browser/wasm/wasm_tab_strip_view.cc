// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_tab_strip_view.h"

#include <memory>
#include <string>
#include <utility>

#include "base/check.h"
#include "base/check_op.h"
#include "base/functional/bind.h"
#include "build/build_config.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/tab_ui_helper.h"
#include "chrome/browser/ui/tabs/tab_strip_model.h"
#include "chrome/browser/ui/tabs/tab_strip_user_gesture_details.h"
#include "components/tabs/public/tab_interface.h"
#include "third_party/skia/include/core/SkColor.h"
#include "ui/base/metadata/metadata_impl_macros.h"
#include "ui/events/event.h"
#include "ui/gfx/geometry/insets.h"
#include "ui/gfx/geometry/size.h"
#include "ui/views/background.h"
#include "ui/views/controls/button/label_button.h"
#include "ui/views/layout/box_layout.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_tab_strip_view.cc must only be built for WebAssembly"
#endif

namespace {

constexpr int kWasmMaximumTabCount = 2;
constexpr int kWasmTabStripHeight = 32;
constexpr int kWasmTabButtonMinimumWidth = 120;
constexpr char16_t kWasmUntitledTab[] = u"New tab";

}  // namespace

WasmTabStripView::WasmTabStripView(
    BrowserWindowInterface* browser_window_interface)
    : browser_window_interface_(browser_window_interface) {
  CHECK(browser_window_interface_);
  tab_strip_model_ = browser_window_interface_->GetTabStripModel();
  CHECK(tab_strip_model_);

  SetPreferredSize(gfx::Size(0, kWasmTabStripHeight));
  auto layout = std::make_unique<views::BoxLayout>(
      views::BoxLayout::Orientation::kHorizontal, gfx::Insets::VH(4, 8), 4);
  views::BoxLayout* const layout_ptr = layout.get();
  SetLayoutManager(std::move(layout));

  for (int index = 0; index < kWasmMaximumTabCount; ++index) {
    tab_buttons_[index] = AddChildView(std::make_unique<views::LabelButton>(
        base::BindRepeating(&WasmTabStripView::ActivateTab,
                            base::Unretained(this), index),
        kWasmUntitledTab));
    tab_buttons_[index]->SetMinSize(
        gfx::Size(kWasmTabButtonMinimumWidth, 0));
    layout_ptr->SetFlexForView(tab_buttons_[index], 1,
                               /*use_min_size=*/true);
    ClearButton(index);
  }

  tab_strip_model_->AddObserver(this);
  SyncFromModel();
}

WasmTabStripView::~WasmTabStripView() {
  for (base::CallbackListSubscription& subscription :
       tab_ui_change_subscriptions_) {
    subscription = base::CallbackListSubscription();
  }
  if (tab_strip_model_) {
    tab_strip_model_->RemoveObserver(this);
  }
}

views::LabelButton* WasmTabStripView::tab_button_for_testing(int index) const {
  CHECK_GE(index, 0);
  CHECK_LT(index, kWasmMaximumTabCount);
  return tab_buttons_[index];
}

bool WasmTabStripView::ActivateRelativeTabForAccelerator(
    bool previous,
    base::TimeTicks time_stamp) {
  CHECK(tab_strip_model_);
  const int tab_count = tab_strip_model_->count();
  if (tab_count < 2) {
    return false;
  }

  const int active_index = tab_strip_model_->active_index();
  CHECK_GE(active_index, 0);
  CHECK_LT(active_index, tab_count);
  const int target_index =
      previous ? (active_index + tab_count - 1) % tab_count
               : (active_index + 1) % tab_count;
  CHECK_NE(target_index, active_index);
  tab_strip_model_->ActivateTabAt(
      target_index,
      TabStripUserGestureDetails(
          TabStripUserGestureDetails::GestureType::kKeyboard, time_stamp));
  return true;
}

void WasmTabStripView::SyncFromModel() {
  CHECK(tab_strip_model_);
  CHECK_LE(tab_strip_model_->count(), kWasmMaximumTabCount)
      << "Wasm tab strip only supports two model tabs";

  for (base::CallbackListSubscription& subscription :
       tab_ui_change_subscriptions_) {
    subscription = base::CallbackListSubscription();
  }

  for (int index = 0; index < kWasmMaximumTabCount; ++index) {
    if (!tab_strip_model_->ContainsIndex(index)) {
      ClearButton(index);
      continue;
    }

    tabs::TabInterface* const tab = tab_strip_model_->GetTabAtIndex(index);
    CHECK(tab);
    TabUIHelper* const tab_ui_helper = TabUIHelper::From(tab);
    CHECK(tab_ui_helper);
    tab_ui_change_subscriptions_[index] =
        tab_ui_helper->AddTabUIChangeCallback(base::BindRepeating(
            &WasmTabStripView::OnTabUIChanged, base::Unretained(this), tab));
    UpdateButtonForTab(index);
  }
}

void WasmTabStripView::UpdateButtonForTab(int index) {
  CHECK(tab_strip_model_);
  CHECK(tab_strip_model_->ContainsIndex(index));
  views::LabelButton* const button = tab_buttons_[index];
  CHECK(button);

  tabs::TabInterface* const tab = tab_strip_model_->GetTabAtIndex(index);
  CHECK(tab);
  TabUIHelper* const tab_ui_helper = TabUIHelper::From(tab);
  CHECK(tab_ui_helper);
  std::u16string title = tab_ui_helper->GetTitle();
  if (title.empty()) {
    title = kWasmUntitledTab;
  }

  button->SetText(title);
  button->SetTooltipText(title);
  button->SetAccessibleName(title);
  button->SetEnabled(true);
  button->SetVisible(true);
  if (tab_strip_model_->active_index() == index) {
    button->SetBackground(
        views::CreateRoundedRectBackground(SK_ColorLTGRAY, 6));
  } else {
    button->SetBackground(nullptr);
  }
}

void WasmTabStripView::ClearButton(int index) {
  CHECK_GE(index, 0);
  CHECK_LT(index, kWasmMaximumTabCount);
  views::LabelButton* const button = tab_buttons_[index];
  CHECK(button);
  button->SetBackground(nullptr);
  button->SetVisible(false);
  button->SetEnabled(false);
}

void WasmTabStripView::OnTabUIChanged(tabs::TabInterface* tab) {
  if (!tab_strip_model_) {
    return;
  }

  const int index = tab_strip_model_->GetIndexOfTab(tab);
  if (index == TabStripModel::kNoTab) {
    return;
  }
  UpdateButtonForTab(index);
}

void WasmTabStripView::ActivateTab(int index, const ui::Event& event) {
  CHECK(tab_strip_model_);
  CHECK(tab_strip_model_->ContainsIndex(index));
  tab_strip_model_->ActivateTabAt(
      index, TabStripUserGestureDetails(
                 TabStripUserGestureDetails::GestureType::kMouse,
                 event.time_stamp()));
}

void WasmTabStripView::OnTabStripModelChanged(
    TabStripModel* tab_strip_model,
    const TabStripModelChange& /*change*/,
    const TabStripSelectionChange& /*selection*/) {
  CHECK_EQ(tab_strip_model, tab_strip_model_);
  SyncFromModel();
}

void WasmTabStripView::OnTabWillBeRemoved(tabs::TabInterface* tab,
                                           int index) {
  CHECK(tab_strip_model_);
  CHECK(tab);
  CHECK(tab_strip_model_->ContainsIndex(index));
  CHECK_EQ(tab, tab_strip_model_->GetTabAtIndex(index));

  // TabStripModel destroys TabFeatures after this notification. Drop the
  // TabUIHelper callback while that feature still owns the subscription.
  tab_ui_change_subscriptions_[index] = base::CallbackListSubscription();
}

void WasmTabStripView::OnTabStripModelDestroyed(
    TabStripModel* tab_strip_model) {
  CHECK_EQ(tab_strip_model, tab_strip_model_);
  for (base::CallbackListSubscription& subscription :
       tab_ui_change_subscriptions_) {
    subscription = base::CallbackListSubscription();
  }
  tab_strip_model_ = nullptr;
  for (int index = 0; index < kWasmMaximumTabCount; ++index) {
    ClearButton(index);
  }
}

BEGIN_METADATA(WasmTabStripView)
END_METADATA
