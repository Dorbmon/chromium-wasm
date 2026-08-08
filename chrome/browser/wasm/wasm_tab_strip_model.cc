// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/ui/tabs/tab_strip_model.h"

#include <algorithm>
#include <memory>
#include <optional>
#include <utility>
#include <vector>

#include "base/check.h"
#include "base/check_op.h"
#include "base/observer_list.h"
#include "base/types/pass_key.h"
#include "build/build_config.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/ui/tabs/tab_group_model.h"
#include "chrome/browser/ui/tabs/tab_model.h"
#include "chrome/browser/ui/tabs/tab_enums.h"
#include "chrome/browser/ui/tabs/tab_strip_model_delegate.h"
#include "chrome/browser/ui/tabs/tab_strip_model_observer.h"
#include "components/tabs/public/tab_collection.h"
#include "components/tabs/public/tab_strip_collection.h"
#include "components/web_modal/web_contents_modal_dialog_manager.h"
#include "content/public/browser/browser_thread.h"
#include "content/public/browser/web_contents.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_tab_strip_model.cc must only be built for WebAssembly"
#endif

using content::WebContents;

namespace {

class ReentrancyCheck {
 public:
  explicit ReentrancyCheck(bool* guard_flag) : guard_flag_(guard_flag) {
    ValidateNotReentrant(guard_flag_);
    *guard_flag_ = true;
  }

  ~ReentrancyCheck() { *guard_flag_ = false; }

  static void ValidateNotReentrant(bool* guard_flag) {
    CHECK_CURRENTLY_ON(content::BrowserThread::UI);
    CHECK(!*guard_flag);
  }

 private:
  const raw_ptr<bool> guard_flag_;
};

}  // namespace

constexpr int TabStripModel::kNoTab;

TabStripModel::TabStripModel(TabStripModelDelegate* delegate,
                             Profile* profile,
                             TabGroupModelFactory* group_model_factory)
    : delegate_(delegate), profile_(profile), selection_model_(this) {
  CHECK(delegate_);
  CHECK(profile_);

  // A group model would make tab-group mutation paths reachable. Those paths
  // are deliberately outside this core until their backing UI and persistence
  // lifecycles are source-selected.
  CHECK(!group_model_factory)
      << "Wasm tab core does not support tab-group model construction";
  contents_data_ = std::make_unique<tabs::TabStripCollection>(false);
}

TabStripModel::~TabStripModel() {
  for (auto& observer : observers_) {
    observer.ModelDestroyed(TabStripModelObserver::ModelPasskey(), this);
  }
}

void TabStripModel::SetTabStripUI(TabStripModelObserver* observer) {
  CHECK(!tab_strip_ui_was_set_);
  CHECK(observer);

  std::vector<TabStripModelObserver*> new_observers{observer};
  for (auto& old_observer : observers_) {
    new_observers.push_back(&old_observer);
  }
  observers_.Clear();

  for (TabStripModelObserver* new_observer : new_observers) {
    observers_.AddObserver(new_observer);
  }
  observer->StartedObserving(TabStripModelObserver::ModelPasskey(), this);
  tab_strip_ui_was_set_ = true;
}

void TabStripModel::AddObserver(TabStripModelObserver* observer) {
  CHECK(observer);
  observers_.AddObserver(observer);
  observer->StartedObserving(TabStripModelObserver::ModelPasskey(), this);
}

void TabStripModel::RemoveObserver(TabStripModelObserver* observer) {
  CHECK(observer);
  observer->StoppedObserving(TabStripModelObserver::ModelPasskey(), this);
  if (tab_strip_ui_was_set_ && !observers_.empty() &&
      &*observers_.begin() == observer) {
    tab_strip_ui_was_set_ = false;
  }
  observers_.RemoveObserver(observer);
}

int TabStripModel::count() const {
  return contents_data_->TabCountRecursive();
}

bool TabStripModel::empty() const {
  return count() == 0;
}

bool TabStripModel::ContainsIndex(int index) const {
  return index >= 0 && index < count();
}

void TabStripModel::AppendWebContents(std::unique_ptr<WebContents> contents,
                                      bool foreground) {
  InsertWebContentsAt(
      count(), std::move(contents),
      foreground ? (ADD_INHERIT_OPENER | ADD_ACTIVE) : ADD_NONE);
}

void TabStripModel::AppendTab(std::unique_ptr<tabs::TabModel> tab,
                              bool foreground) {
  InsertDetachedTabAt(
      count(), std::move(tab),
      foreground ? (ADD_INHERIT_OPENER | ADD_ACTIVE) : ADD_NONE);
}

int TabStripModel::InsertWebContentsAt(
    int index,
    std::unique_ptr<WebContents> contents,
    int add_types,
    std::optional<tab_groups::TabGroupId> group) {
  CHECK(contents);
  return InsertDetachedTabAt(
      index, std::make_unique<tabs::TabModel>(std::move(contents), this),
      add_types, group);
}

int TabStripModel::InsertDetachedTabAt(
    int index,
    std::unique_ptr<tabs::TabModel> tab,
    int add_types,
    std::optional<tab_groups::TabGroupId> group) {
  ReentrancyCheck reentrancy_check(&reentrancy_guard_);
  CHECK(tab);
  CHECK(!group.has_value())
      << "Wasm tab core does not support tab-group insertion";
  tab->OnAddedToModel(this);
  return InsertTabAtImpl(index, std::move(tab), add_types, group);
}

content::WebContents* TabStripModel::GetActiveWebContents() const {
  tabs::TabInterface* active_tab = selection_model_.active_tab();
  return active_tab ? active_tab->GetContents() : nullptr;
}

tabs::TabInterface* TabStripModel::GetActiveTab() const {
  return selection_model_.active_tab();
}

std::vector<tabs::TabInterface*> TabStripModel::GetForegroundTabs() const {
  tabs::TabInterface* active_tab = GetActiveTab();
  return active_tab ? std::vector<tabs::TabInterface*>{active_tab}
                    : std::vector<tabs::TabInterface*>();
}

WebContents* TabStripModel::GetWebContentsAt(int index) const {
  return ContainsIndex(index) ? GetTabAtIndex(index)->GetContents() : nullptr;
}

int TabStripModel::GetIndexOfWebContents(const WebContents* contents) const {
  int index = 0;
  for (const tabs::TabInterface* tab : *this) {
    if (tab->GetContents() == contents) {
      return index;
    }
    ++index;
  }
  return kNoTab;
}

void TabStripModel::SetTabBlocked(int index, bool blocked) {
  CHECK(ContainsIndex(index));
  tabs::TabModel* tab = GetTabModelAtIndex(index);
  if (tab->IsBlocked() == blocked) {
    return;
  }
  tab->SetBlocked(blocked);
  NotifyTabChanged(tab, TabChangeType::kBlockedOnly);
}

bool TabStripModel::IsTabBlocked(int index) const {
  CHECK(ContainsIndex(index));
  return GetTabAtIndex(index)->IsBlocked();
}

bool TabStripModel::IsTabInForeground(int index) const {
  return ContainsIndex(index) && active_index() == index;
}

bool TabStripModel::IsTabSelected(int index) const {
  CHECK(ContainsIndex(index));
  return selection_model_.IsSelected(GetTabAtIndex(index));
}

void TabStripModel::NotifyTabChanged(tabs::TabInterface* tab,
                                     TabChangeType change_type) {
  const int index = GetIndexOfTab(tab);
  CHECK_NE(index, kNoTab);
  for (auto& observer : observers_) {
    observer.OnTabChangedAt(tab, index, change_type);
  }
}

void TabStripModel::UpdateWebContentsStateAt(int index,
                                             TabChangeType change_type) {
  CHECK(ContainsIndex(index));
  NotifyTabChanged(GetTabAtIndex(index), change_type);
}

TabStripModel::TabIterator TabStripModel::begin() const {
  return contents_data_->begin();
}

TabStripModel::TabIterator TabStripModel::end() const {
  return contents_data_->end();
}

const tabs::TabCollection* TabStripModel::Root() const {
  return contents_data_.get();
}

const tabs::TabCollection* TabStripModel::GetRootForTesting() const {
  return contents_data_.get();
}

tabs::TabModel* TabStripModel::GetTabModelAtIndex(int index) const {
  return static_cast<tabs::TabModel*>(GetTabAtIndex(index));
}

tabs::TabModel* TabStripModel::GetActiveTabModel() const {
  return static_cast<tabs::TabModel*>(GetActiveTab());
}

int TabStripModel::ConstrainInsertionIndex(int index, bool pinned_tab) const {
  return pinned_tab ? std::clamp(index, 0, IndexOfFirstNonPinnedTab())
                    : std::clamp(index, IndexOfFirstNonPinnedTab(), count());
}

int TabStripModel::IndexOfFirstNonPinnedTab() const {
  return contents_data_->IndexOfFirstNonPinnedTab();
}

int TabStripModel::GetIndexOfTab(const tabs::TabInterface* tab) const {
  if (!tab) {
    return kNoTab;
  }
  std::optional<size_t> index = contents_data_->GetIndexOfTabRecursive(tab);
  return index.value_or(kNoTab);
}

tabs::TabInterface* TabStripModel::GetTabAtIndex(int index) const {
  CHECK(ContainsIndex(index));
  return contents_data_->GetTabAtIndexRecursive(index);
}

tabs::TabInterface* TabStripModel::GetTabForWebContents(
    const content::WebContents* contents) const {
  const int index = GetIndexOfWebContents(contents);
  return index == kNoTab ? nullptr : GetTabAtIndex(index);
}

void TabStripModel::OnChange(const TabStripModelChange& change,
                             const TabStripSelectionChange& selection) {
  CompleteModelUpdateTransaction();
  OnActiveTabChanged(selection);
  for (auto& observer : observers_) {
    observer.OnTabStripModelChanged(this, change, selection);
  }
}

int TabStripModel::InsertTabAtImpl(
    int index,
    std::unique_ptr<tabs::TabModel> tab,
    int add_types,
    std::optional<tab_groups::TabGroupId> group) {
  CHECK(!group.has_value());
  delegate()->WillAddWebContents(tab->GetContents());

  const bool active = (add_types & ADD_ACTIVE) != 0 || empty();
  const bool pinned = (add_types & ADD_PINNED) != 0;
  CHECK(!pinned) << "Wasm tab core does not support pinned-tab insertion";
  index = ConstrainInsertionIndex(index, pinned);

  tabs::TabModel* active_tab = GetActiveTabModel();
  if ((add_types & ADD_INHERIT_OPENER) && active_tab) {
    tab->set_opener(active_tab);
  }

  const web_modal::WebContentsModalDialogManager* manager =
      web_modal::WebContentsModalDialogManager::FromWebContents(
          tab->GetContents());
  CHECK(manager);
  tab->SetBlocked(manager->IsDialogActive());

  InsertTabAtIndexImpl(std::move(tab), index, group, pinned, active);
  return index;
}

void TabStripModel::InsertTabAtIndexImpl(
    std::unique_ptr<tabs::TabModel> tab_model,
    int index,
    std::optional<tab_groups::TabGroupId> group,
    bool pinned,
    bool active) {
  CHECK(!group.has_value());
  tabs::TabModel* tab = tab_model.get();
  tabs::TabInterface* old_active_tab = GetActiveTab();
  contents_data_->AddTabRecursive(std::move(tab_model), index, std::nullopt,
                                  pinned);
  selection_model_.InvalidateListSelectionModel(base::PassKey<TabStripModel>());

  TabStripSelectionChange selection(old_active_tab,
                                    selection_model().GetListSelectionModel());
  if (active) {
    tabs::TabStripModelSelectionState new_selection = selection_model_;
    SetSelectedTab(new_selection, GetTabAtIndex(index));
    SetSelection(new_selection, TabStripModelObserver::CHANGE_REASON_NONE,
                 /*triggered_by_other_operation=*/true);
  }

  tab->DidInsert(base::PassKey<TabStripModel>());
  selection.new_model = selection_model().GetListSelectionModel();
  selection.new_tab = GetActiveTab();
  selection.new_contents = GetActiveWebContents();
  TabStripModelChange::Insert insert;
  insert.contents.push_back({tab, tab->GetContents(), index});
  OnChange(TabStripModelChange(std::move(insert)), selection);
}

TabStripSelectionChange TabStripModel::SetSelection(
    const tabs::TabStripModelSelectionState& new_model,
    TabStripModelObserver::ChangeReason reason,
    bool triggered_by_other_operation) {
  TabStripSelectionChange selection;
  selection.old_model = selection_model().GetListSelectionModel();
  selection.old_tab = GetActiveTab();
  selection.old_contents = GetActiveWebContents();
  selection.new_model = new_model.GetListSelectionModel();
  selection.reason = reason;

  if (selection_model_.active_tab() && new_model.active_tab() &&
      selection_model_.active_tab() != new_model.active_tab()) {
    NotifyForegroundTabsWillEnterBackground();
  }

  selection_model_ = new_model;
  selection.new_tab = GetActiveTab();
  selection.new_contents = GetActiveWebContents();

  if (!triggered_by_other_operation &&
      (selection.active_tab_changed() || selection.selection_changed())) {
    OnChange(TabStripModelChange(), selection);
  }
  return selection;
}

void TabStripModel::SetSelectedTab(
    tabs::TabStripModelSelectionState& selection_state,
    tabs::TabInterface* tab) {
  CHECK(tab);
  CHECK(!tab->IsSplit()) << "Wasm tab core does not support split tabs";
  selection_state.SetSelectedTabs({tab}, tab, tab);
}

void TabStripModel::CompleteModelUpdateTransaction() {
  contents_data_->ValidateData();
  contents_data_->DispatchPendingNotifications();
  if (empty()) {
    return;
  }
  CHECK(selection_model_.active_tab());
  CHECK(selection_model_.IsSelected(selection_model_.active_tab()));
  selection_model_.InvalidateListSelectionModel(base::PassKey<TabStripModel>());
  static_cast<void>(selection_model_.GetListSelectionModel());
}

void TabStripModel::OnActiveTabChanged(
    const TabStripSelectionChange& selection) {
  if (!selection.active_tab_changed()) {
    return;
  }
  // Thumbnail capture, tab-group activity, opener reset, and media/user
  // education integrations are not part of this source-selected core. The
  // actual active-tab change still reaches all observers in OnChange().
}

void TabStripModel::NotifyForegroundTabsWillEnterBackground() {
  for (tabs::TabInterface* tab : GetForegroundTabs()) {
    tabs::TabModel* model = static_cast<tabs::TabModel*>(tab);
    if (model->IsActivated()) {
      model->WillDeactivate(base::PassKey<TabStripModel>());
    }
    model->WillBecomeHidden(base::PassKey<TabStripModel>());
  }
}

void TabStripModel::CloseWebContentsAt(int /*index*/, uint32_t /*close_types*/) {
  CHECK(false)
      << "Wasm tab core has no joined unload/modal/browser-close lifecycle";
}
