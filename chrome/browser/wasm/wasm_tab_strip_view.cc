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
constexpr int kWasmTabActionButtonWidth = 28;
constexpr char16_t kWasmUntitledTab[] = u"New tab";
constexpr char16_t kWasmNewTabButtonLabel[] = u"+";
constexpr char16_t kWasmCloseTabButtonLabel[] = u"\u00d7";

}  // namespace

WasmTabStripView::WasmTabStripView(
    BrowserWindowInterface* browser_window_interface,
    base::RepeatingCallback<bool()> create_tab_callback,
    base::RepeatingCallback<bool()> can_create_tab_callback,
    base::RepeatingCallback<bool(int)> can_activate_tab_callback,
    base::RepeatingCallback<bool(int)> close_tab_callback,
    base::RepeatingCallback<bool(int)> can_close_tab_callback)
    : browser_window_interface_(browser_window_interface),
      create_tab_callback_(std::move(create_tab_callback)),
      can_create_tab_callback_(std::move(can_create_tab_callback)),
      can_activate_tab_callback_(std::move(can_activate_tab_callback)),
      close_tab_callback_(std::move(close_tab_callback)),
      can_close_tab_callback_(std::move(can_close_tab_callback)) {
  CHECK(browser_window_interface_);
  CHECK(create_tab_callback_);
  CHECK(can_create_tab_callback_);
  CHECK(can_activate_tab_callback_);
  CHECK(close_tab_callback_);
  CHECK(can_close_tab_callback_);
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

    close_tab_buttons_[index] =
        AddChildView(std::make_unique<views::LabelButton>(
            base::BindRepeating(&WasmTabStripView::CloseTab,
                                base::Unretained(this), index),
            kWasmCloseTabButtonLabel));
    close_tab_buttons_[index]->SetMinSize(
        gfx::Size(kWasmTabActionButtonWidth, 0));
    ClearButton(index);
  }

  new_tab_button_ = AddChildView(std::make_unique<views::LabelButton>(
      base::BindRepeating(&WasmTabStripView::CreateTab,
                          base::Unretained(this)),
      kWasmNewTabButtonLabel));
  new_tab_button_->SetMinSize(gfx::Size(kWasmTabActionButtonWidth, 0));
  new_tab_button_->SetAccessibleName(u"New tab");

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

views::LabelButton* WasmTabStripView::new_tab_button_for_testing() const {
  return new_tab_button_;
}

views::LabelButton* WasmTabStripView::close_tab_button_for_testing(
    int index) const {
  CHECK_GE(index, 0);
  CHECK_LT(index, kWasmMaximumTabCount);
  return close_tab_buttons_[index];
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
  if (!can_activate_tab_callback_.Run(target_index)) {
    return false;
  }
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
  UpdateActionButtons();
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
  button->SetEnabled(can_activate_tab_callback_.Run(index));
  button->SetVisible(true);
  if (tab_strip_model_->active_index() == index) {
    button->SetBackground(
        views::CreateRoundedRectBackground(SK_ColorLTGRAY, 6));
  } else {
    button->SetBackground(nullptr);
  }

  views::LabelButton* const close_button = close_tab_buttons_[index];
  CHECK(close_button);
  const std::u16string close_tab_name = std::u16string(u"Close ") + title;
  close_button->SetAccessibleName(close_tab_name);
  close_button->SetTooltipText(close_tab_name);
  close_button->SetVisible(tab_strip_model_->count() > 1);
  close_button->SetEnabled(tab_strip_model_->count() > 1 &&
                           can_close_tab_callback_.Run(index));
}

void WasmTabStripView::UpdateActionButtons() {
  CHECK(new_tab_button_);
  if (!tab_strip_model_) {
    new_tab_button_->SetVisible(false);
    new_tab_button_->SetEnabled(false);
    return;
  }

  new_tab_button_->SetVisible(true);
  new_tab_button_->SetEnabled(tab_strip_model_->count() <
                                  kWasmMaximumTabCount &&
                              can_create_tab_callback_.Run());
}

void WasmTabStripView::ClearButton(int index) {
  CHECK_GE(index, 0);
  CHECK_LT(index, kWasmMaximumTabCount);
  views::LabelButton* const button = tab_buttons_[index];
  CHECK(button);
  button->SetBackground(nullptr);
  button->SetVisible(false);
  button->SetEnabled(false);

  views::LabelButton* const close_button = close_tab_buttons_[index];
  CHECK(close_button);
  close_button->SetVisible(false);
  close_button->SetEnabled(false);
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
  if (!tab_strip_model_ || !tab_strip_model_->ContainsIndex(index) ||
      !can_activate_tab_callback_.Run(index)) {
    return;
  }
  tab_strip_model_->ActivateTabAt(
      index, TabStripUserGestureDetails(
                 TabStripUserGestureDetails::GestureType::kMouse,
                 event.time_stamp()));
}

void WasmTabStripView::CreateTab(const ui::Event& /*event*/) {
  if (!tab_strip_model_ || tab_strip_model_->count() >= kWasmMaximumTabCount ||
      !create_tab_callback_ || !can_create_tab_callback_.Run()) {
    return;
  }

  // Browser owns WebContents and may synchronously notify this model while it
  // adds the foreground tab. Do not retain model/tab pointers across the
  // callback; OnTabStripModelChanged() refreshes the visible state.
  create_tab_callback_.Run();
}

void WasmTabStripView::CloseTab(int index, const ui::Event& /*event*/) {
  if (!tab_strip_model_ || tab_strip_model_->count() <= 1 ||
      !tab_strip_model_->ContainsIndex(index) || !close_tab_callback_ ||
      !can_close_tab_callback_.Run(index)) {
    return;
  }

  // The Browser callback rejects unsupported close state and may synchronously
  // remove the selected or background tab. Do not retain model/tab pointers
  // after this call; model observers drop TabUIHelper subscriptions first.
  close_tab_callback_.Run(index);
}

void WasmTabStripView::OnTabStripModelChanged(
    TabStripModel* tab_strip_model,
    const TabStripModelChange& /*change*/,
    const TabStripSelectionChange& /*selection*/) {
  CHECK_EQ(tab_strip_model, tab_strip_model_);
  SyncFromModel();
}

void WasmTabStripView::OnTabChangedAt(tabs::TabInterface* tab,
                                      int index,
                                      TabChangeType /*change_type*/) {
  if (!tab_strip_model_ || !tab_strip_model_->ContainsIndex(index) ||
      tab_strip_model_->GetTabAtIndex(index) != tab) {
    return;
  }

  // Blocking state is published separately from a model/selection change.
  // Refresh every control because a modal on the active tab can make a
  // different target's selection or creation action unsafe as well.
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
  create_tab_callback_.Reset();
  can_create_tab_callback_.Reset();
  can_activate_tab_callback_.Reset();
  close_tab_callback_.Reset();
  can_close_tab_callback_.Reset();
  for (int index = 0; index < kWasmMaximumTabCount; ++index) {
    ClearButton(index);
  }
  UpdateActionButtons();
}

BEGIN_METADATA(WasmTabStripView)
END_METADATA
