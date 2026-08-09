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
#include "base/functional/bind.h"
#include "base/functional/callback_helpers.h"
#include "base/memory/ptr_util.h"
#include "base/memory/weak_ptr.h"
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
#include "ui/base/models/list_selection_model.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_tab_strip_model.cc must only be built for WebAssembly"
#endif

using content::WebContents;

namespace {

// This selected model deliberately admits only the smallest multi-tab shape
// needed to prove selected-content attachment and Browser-owned close ordering.
// General tab-strip UI, reordering, groups, pinned tabs, and tab drag remain
// outside this source closure.
constexpr int kWasmMaximumTabCount = 2;

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
  CHECK(!closing_all_)
      << "Wasm tab core does not insert tabs after CloseAllTabs";
  CHECK_LT(count(), kWasmMaximumTabCount)
      << "Wasm tab core only supports two append-only tabs";
  CHECK_EQ(index, count())
      << "Wasm tab core does not support inserting or reordering tabs";
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

void TabStripModel::ActivateTabAt(
    int index,
    TabStripUserGestureDetails user_gesture) {
  ReentrancyCheck reentrancy_check(&reentrancy_guard_);
  CHECK(ContainsIndex(index));

  tabs::TabInterface* const requested_tab = GetTabAtIndex(index);
  CHECK(!requested_tab->IsSplit())
      << "Wasm tab core does not support split-tab activation";
  if (requested_tab == GetActiveTab()) {
    return;
  }

  // The Wasm selected-content host exposes one active WebContents-modal host.
  // Switching while either endpoint has an active modal would silently lose
  // its ownership/blocked-state semantics, so make that unsupported boundary
  // explicit until the joined modal lifecycle is selected.
  for (content::WebContents* const contents :
       {GetActiveWebContents(), requested_tab->GetContents()}) {
    CHECK(contents);
    const web_modal::WebContentsModalDialogManager* const modal_manager =
        web_modal::WebContentsModalDialogManager::FromWebContents(contents);
    CHECK(modal_manager);
    CHECK(!modal_manager->IsDialogActive())
        << "Wasm tab core does not switch tabs while modal UI is active";
  }

  tabs::TabStripModelSelectionState new_selection = selection_model_;
  SetSelectedTab(new_selection, requested_tab);
  SetSelection(
      new_selection,
      user_gesture.type != TabStripUserGestureDetails::GestureType::kNone
          ? TabStripModelObserver::CHANGE_REASON_USER_GESTURE
          : TabStripModelObserver::CHANGE_REASON_NONE,
      /*triggered_by_other_operation=*/false);
}

void TabStripModel::CloseWebContentsAt(int index, uint32_t close_types) {
  ReentrancyCheck::ValidateNotReentrant(&reentrancy_guard_);
  base::WeakPtr<TabStripModel> model_ref = weak_factory_.GetWeakPtr();
  reentrancy_guard_ = true;
  base::ScopedClosureRunner reset_reentrancy_guard(base::BindOnce(
      [](base::WeakPtr<TabStripModel> model) {
        if (model) {
          model->reentrancy_guard_ = false;
        }
      },
      model_ref));

  // This source-selected core deliberately owns only immediate closes in its
  // bounded two-tab model. A general close path needs the async beforeunload
  // loop, tab-restore persistence, and a Browser/window lifecycle; none may
  // be faked by returning successfully here.
  CHECK_EQ(close_types, static_cast<uint32_t>(TabCloseTypes::CLOSE_NONE));
  CHECK(ContainsIndex(index));
  CHECK_LE(count(), kWasmMaximumTabCount);

  tabs::TabModel* const tab = GetTabModelAtIndex(index);
  CHECK(!tab->IsPinned());
  CHECK(!tab->GetGroup().has_value());
  CHECK(!tab->IsSplit());
  CHECK(!tab->IsBlocked())
      << "Wasm tab core does not close a tab while modal UI is active";

  content::WebContents* const contents = tab->GetContents();
  CHECK(contents);
  const bool should_run_unload =
      ShouldRunUnloadListenerBeforeClosing(contents);
  if (!model_ref) {
    return;
  }
  CHECK(!should_run_unload)
      << "Wasm tab core does not support asynchronous beforeunload, unload, "
         "or delegate-requested close handling";
  const web_modal::WebContentsModalDialogManager* const modal_manager =
      web_modal::WebContentsModalDialogManager::FromWebContents(contents);
  CHECK(modal_manager);
  CHECK(!modal_manager->IsDialogActive())
      << "Wasm tab core does not close an active modal dialog";

  // A direct final-tab close has the same observer contract as an all-tab
  // close. CloseAllTabs() sends this once around its reverse-order loop.
  const bool notify_close_all = !closing_all_ && count() == 1;
  if (notify_close_all) {
    for (auto& observer : observers_) {
      observer.WillCloseAllTabs(this);
    }
    if (!model_ref) {
      return;
    }
  }

  tabs::TabInterface* const old_active_tab = GetActiveTab();
  content::WebContents* const old_contents = GetActiveWebContents();
  const ui::ListSelectionModel old_selection =
      selection_model().GetListSelectionModel();

  // CloseAllTabs() suppresses foreground transitions, matching upstream's
  // whole-window close behavior. A direct final-tab close retains them.
  if (!closing_all_ && tab == old_active_tab) {
    tab->WillDeactivate(base::PassKey<TabStripModel>());
  }
  if (!closing_all_ && tab->IsVisible()) {
    tab->WillBecomeHidden(base::PassKey<TabStripModel>());
  }
  tab->WillDetach(base::PassKey<TabStripModel>(),
                  tabs::TabInterface::DetachReason::kDelete);
  for (auto& observer : observers_) {
    observer.OnTabWillBeRemoved(tab, index);
  }
  if (!model_ref) {
    return;
  }

  // TabFeatures observes the WebContents and must be destroyed before the
  // collection releases the TabModel. Keep the returned TabModel alive through
  // the change callback, whose payload intentionally contains raw pointers.
  tab->DestroyTabFeatures();
  std::unique_ptr<tabs::TabModel> detached_tab = base::WrapUnique(
      static_cast<tabs::TabModel*>(
          contents_data_->RemoveTabAtIndexRecursive(index).release()));
  selection_model_.RemoveTabFromSelection(tab);
  selection_model_.InvalidateListSelectionModel(base::PassKey<TabStripModel>());
  if (empty()) {
    selection_model_.Clear();
  } else if (tab == old_active_tab) {
    // The bounded model has a single selected tab. When its active tab is
    // removed, select the adjacent surviving tab before observers receive the
    // removal event so the view-side host can reattach its non-owning WebView.
    SetSelectedTab(selection_model_,
                   GetTabAtIndex(std::min(index, count() - 1)));
  }
  detached_tab->OnRemovedFromModel();

  {
    TabStripModelChange::Remove remove;
    remove.contents.emplace_back(detached_tab.get(), index,
                                 TabRemovedReason::kDeleted,
                                 tabs::TabInterface::DetachReason::kDelete,
                                 std::nullopt);
    TabStripSelectionChange selection(old_active_tab, old_selection);
    selection.new_tab = GetActiveTab();
    selection.old_contents = old_contents;
    selection.new_contents = GetActiveWebContents();
    selection.new_model = selection_model().GetListSelectionModel();
    selection.selected_tabs_were_removed = old_selection.IsSelected(index);
    OnChange(TabStripModelChange(std::move(remove)), selection);
  }
  if (!model_ref) {
    return;
  }

  detached_tab.reset();
  if (empty()) {
    for (auto& observer : observers_) {
      observer.TabStripEmpty();
    }
    if (!model_ref) {
      return;
    }
  }
  if (notify_close_all) {
    for (auto& observer : observers_) {
      observer.CloseAllTabsStopped(
          this, TabStripModelObserver::kCloseAllCompleted);
    }
  }
}

void TabStripModel::CloseAllTabs() {
  ReentrancyCheck::ValidateNotReentrant(&reentrancy_guard_);

  // This is intentionally a bounded two-tab, no-history closing path. It
  // establishes the same whole-window notification distinction as desktop
  // Chromium while leaving async unload, persistence, and general multi-tab
  // behavior unadmitted.
  closing_all_ = true;
  if (empty()) {
    return;
  }
  CHECK_LE(count(), kWasmMaximumTabCount);

  base::WeakPtr<TabStripModel> model_ref = weak_factory_.GetWeakPtr();
  // Validate every tab before the first removal. In particular, do not close
  // a background tab and then discover that the active tab needs an unload
  // loop or has modal UI: this bounded path has no recovery sequence for a
  // partially completed whole-window close.
  for (int index = 0; index < count(); ++index) {
    tabs::TabModel* const tab = GetTabModelAtIndex(index);
    CHECK(!tab->IsPinned());
    CHECK(!tab->GetGroup().has_value());
    CHECK(!tab->IsSplit());
    CHECK(!tab->IsBlocked())
        << "Wasm tab core does not close a tab while modal UI is active";

    content::WebContents* const contents = tab->GetContents();
    CHECK(contents);
    CHECK(!ShouldRunUnloadListenerBeforeClosing(contents))
        << "Wasm tab core does not support asynchronous beforeunload, unload, "
           "or delegate-requested close handling";
    if (!model_ref) {
      return;
    }
    const web_modal::WebContentsModalDialogManager* const modal_manager =
        web_modal::WebContentsModalDialogManager::FromWebContents(contents);
    CHECK(modal_manager);
    CHECK(!modal_manager->IsDialogActive())
        << "Wasm tab core does not close an active modal dialog";
  }

  for (auto& observer : observers_) {
    observer.WillCloseAllTabs(this);
  }
  if (!model_ref) {
    return;
  }

  // Preserve the active tab until the final removal. That avoids attaching an
  // intermediate background WebContents to the view-side host during whole-window
  // teardown. The bounded model cannot have more than one background tab.
  while (!empty()) {
    const int index_to_close =
        count() == 1 ? 0 : (active_index() == 0 ? 1 : 0);
    CloseWebContentsAt(index_to_close, TabCloseTypes::CLOSE_NONE);
    if (!model_ref) {
      return;
    }
  }

  for (auto& observer : observers_) {
    observer.CloseAllTabsStopped(this,
                                 TabStripModelObserver::kCloseAllCompleted);
  }
}

bool TabStripModel::ShouldRunUnloadListenerBeforeClosing(
    content::WebContents* contents) {
  CHECK(contents);
  return contents->NeedToFireBeforeUnloadOrUnloadEvents() ||
         delegate_->ShouldRunUnloadListenerBeforeClosing(contents);
}
