// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_tab_core_smoke.h"

#include <cstdio>
#include <memory>
#include <optional>
#include <utility>
#include <vector>

#include "base/check.h"
#include "base/check_op.h"
#include "base/functional/callback.h"
#include "base/memory/raw_ptr.h"
#include "build/build_config.h"
#include "chrome/browser/ssl/chrome_security_state_tab_helper.h"
#include "chrome/browser/ui/tabs/tab_enums.h"
#include "chrome/browser/ui/tabs/tab_strip_model.h"
#include "chrome/browser/ui/tabs/tab_strip_model_delegate.h"
#include "chrome/browser/ui/tabs/tab_strip_model_observer.h"
#include "chrome/browser/wasm/wasm_profile.h"
#include "chrome/browser/wasm/wasm_session_tab_helper.h"
#include "components/security_state/content/security_state_tab_helper.h"
#include "components/web_modal/web_contents_modal_dialog_manager.h"
#include "content/public/browser/browser_thread.h"
#include "content/public/browser/web_contents.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_tab_core_smoke.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kTabCoreSmokeMarker[] = "CHROMIUM_WASM_M6_TAB_CORE";

[[noreturn]] void UnsupportedTabCoreSmokeDelegateOperation(
    const char* operation) {
  CHECK(false) << "Wasm tab-core smoke does not support " << operation;
}

// This is intentionally not a BrowserWindowInterface substitute. The one
// insertion exercised below needs only WillAddWebContents(); every operation
// that would require a Browser or a BrowserWindowInterface terminates instead
// of returning a made-up success value.
class TabCoreSmokeDelegate final : public TabStripModelDelegate {
 public:
  explicit TabCoreSmokeDelegate(Profile* profile) : profile_(profile) {
    CHECK(profile_);
  }

  TabCoreSmokeDelegate(const TabCoreSmokeDelegate&) = delete;
  TabCoreSmokeDelegate& operator=(const TabCoreSmokeDelegate&) = delete;
  ~TabCoreSmokeDelegate() override = default;

 private:
  void AddTabAt(const GURL& /*url*/,
                int /*index*/,
                bool /*foreground*/,
                std::optional<tab_groups::TabGroupId> /*group*/,
                bool /*pinned*/) override {
    UnsupportedTabCoreSmokeDelegateOperation("delegate tab creation");
  }

  Browser* CreateNewStripWithTabs(std::vector<NewStripContents> /*tabs*/,
                                  const gfx::Rect& /*window_bounds*/,
                                  bool /*maximize*/) override {
    UnsupportedTabCoreSmokeDelegateOperation("delegate window creation");
  }

  void WillAddWebContents(content::WebContents* contents) override {
    CHECK(contents);
    CHECK_EQ(contents->GetBrowserContext(), profile_);
  }

  int GetDragActions() const override {
    UnsupportedTabCoreSmokeDelegateOperation("tab dragging");
  }

  bool CanDuplicateContentsAt(int /*index*/) override {
    UnsupportedTabCoreSmokeDelegateOperation("tab duplication query");
  }

  bool IsTabStripEditable() override {
    UnsupportedTabCoreSmokeDelegateOperation("tab-strip editing query");
  }

  content::WebContents* DuplicateContentsAt(int /*index*/) override {
    UnsupportedTabCoreSmokeDelegateOperation("tab duplication");
  }

  void DuplicateSplit(split_tabs::SplitTabId /*split*/) override {
    UnsupportedTabCoreSmokeDelegateOperation("split duplication");
  }

  void MoveToExistingWindow(const std::vector<int>& /*indices*/,
                            int /*browser_index*/) override {
    UnsupportedTabCoreSmokeDelegateOperation("moving tabs between windows");
  }

  bool CanMoveTabsToWindow(const std::vector<int>& /*indices*/) override {
    UnsupportedTabCoreSmokeDelegateOperation("tab move query");
  }

  void MoveTabsToNewWindow(const std::vector<int>& /*indices*/) override {
    UnsupportedTabCoreSmokeDelegateOperation("moving tabs to a new window");
  }

  void MoveGroupToNewWindow(const tab_groups::TabGroupId& /*group*/) override {
    UnsupportedTabCoreSmokeDelegateOperation("moving tab groups");
  }

  std::optional<SessionID> CreateHistoricalTab(
      content::WebContents* /*contents*/) override {
    UnsupportedTabCoreSmokeDelegateOperation("historical tab persistence");
  }

  void CreateHistoricalGroup(
      const tab_groups::TabGroupId& /*group*/) override {
    UnsupportedTabCoreSmokeDelegateOperation(
        "historical tab-group persistence");
  }

  void CreateHistoricalSplit(
      const split_tabs::SplitTabId& /*split_id*/) override {
    UnsupportedTabCoreSmokeDelegateOperation("historical split persistence");
  }

  void GroupAdded(const tab_groups::TabGroupId& /*group*/) override {
    UnsupportedTabCoreSmokeDelegateOperation("tab groups");
  }

  void WillCloseGroup(const tab_groups::TabGroupId& /*group*/) override {
    UnsupportedTabCoreSmokeDelegateOperation("closing tab groups");
  }

  void WillCloseSplit(const split_tabs::SplitTabId& /*split_id*/) override {
    UnsupportedTabCoreSmokeDelegateOperation("closing split tabs");
  }

  void GroupCloseStopped(const tab_groups::TabGroupId& /*group*/) override {
    UnsupportedTabCoreSmokeDelegateOperation("tab-group close cancellation");
  }

  void SplitClosed(const split_tabs::SplitTabId& /*split_id*/) override {
    UnsupportedTabCoreSmokeDelegateOperation("split close completion");
  }

  void SplitCloseStopped(const split_tabs::SplitTabId& /*split_id*/) override {
    UnsupportedTabCoreSmokeDelegateOperation("split close cancellation");
  }

  bool RunUnloadListenerBeforeClosing(
      content::WebContents* /*contents*/) override {
    UnsupportedTabCoreSmokeDelegateOperation("tab close unload handling");
  }

  bool ShouldRunUnloadListenerBeforeClosing(
      content::WebContents* contents) override {
    // The smoke intentionally exercises only the selected immediate-close
    // policy. A pending unload is a hard boundary, not an implicit approval
    // to destroy the WebContents.
    CHECK(contents);
    CHECK(!contents->NeedToFireBeforeUnloadOrUnloadEvents());
    return false;
  }

  bool CanReload() const override {
    UnsupportedTabCoreSmokeDelegateOperation("tab reload query");
  }

  void AddToReadLater(
      std::vector<content::WebContents*> /*web_contentses*/) override {
    UnsupportedTabCoreSmokeDelegateOperation("Read Later");
  }

  bool SupportsReadLater() override {
    UnsupportedTabCoreSmokeDelegateOperation("Read Later query");
  }

  bool IsForWebApp() override {
    UnsupportedTabCoreSmokeDelegateOperation("web-app query");
  }

  void CopyURL(content::WebContents* /*web_contents*/) override {
    UnsupportedTabCoreSmokeDelegateOperation("copying tab URLs");
  }

  void GoBack(content::WebContents* /*web_contents*/) override {
    UnsupportedTabCoreSmokeDelegateOperation("tab navigation");
  }

  bool CanGoBack(content::WebContents* /*web_contents*/) override {
    UnsupportedTabCoreSmokeDelegateOperation("tab navigation query");
  }

  bool IsNormalWindow() override {
    UnsupportedTabCoreSmokeDelegateOperation("browser-window type query");
  }

  BrowserWindowInterface* GetBrowserWindowInterface() override {
    UnsupportedTabCoreSmokeDelegateOperation("BrowserWindowInterface access");
  }

  void NewSplitTab(std::vector<int> /*indices*/,
                   split_tabs::SplitTabLayout /*layout*/,
                   split_tabs::SplitTabCreatedSource /*source*/) override {
    UnsupportedTabCoreSmokeDelegateOperation("split tabs");
  }

  void OnGroupsDestruction(
      const std::vector<tab_groups::TabGroupId>& /*group_ids*/,
      base::OnceCallback<void()> /*close_callback*/,
      bool /*delete_groups*/) override {
    UnsupportedTabCoreSmokeDelegateOperation("tab-group destruction");
  }

  void OnRemovingAllTabsFromGroups(
      const std::vector<tab_groups::TabGroupId>& /*group_ids*/,
      base::OnceCallback<void()> /*callback*/) override {
    UnsupportedTabCoreSmokeDelegateOperation(
        "removing all tabs from tab groups");
  }

  bool IsTabGlicPinned(tabs::TabHandle /*tab_handle*/) override {
    UnsupportedTabCoreSmokeDelegateOperation("Glic tab-pin query");
  }

  bool GlicPinTabs(base::span<const tabs::TabHandle> /*tab_handles*/) override {
    UnsupportedTabCoreSmokeDelegateOperation("Glic tab pinning");
  }

  bool GlicUnpinTabs(
      base::span<const tabs::TabHandle> /*tab_handles*/) override {
    UnsupportedTabCoreSmokeDelegateOperation("Glic tab unpinning");
  }

  void OpenGlicWindowFromSharedTab() override {
    UnsupportedTabCoreSmokeDelegateOperation("opening Glic windows");
  }

  void GlicUnpinTabsFromAllConversations(
      base::span<const tabs::TabHandle> /*tab_handles*/) override {
    UnsupportedTabCoreSmokeDelegateOperation(
        "Glic conversation unpinning");
  }

  raw_ptr<Profile> profile_;
};

// Verifies that the selected close primitive keeps the removed TabModel alive
// during its model-change callback and only reports an empty strip after it has
// released the WebContents. This is intentionally not a Browser substitute.
class TabCoreSmokeCloseObserver final : public TabStripModelObserver {
 public:
  explicit TabCoreSmokeCloseObserver(content::WebContents* contents)
      : contents_(contents) {
    CHECK(contents_);
  }

  TabCoreSmokeCloseObserver(const TabCoreSmokeCloseObserver&) = delete;
  TabCoreSmokeCloseObserver& operator=(const TabCoreSmokeCloseObserver&) =
      delete;
  ~TabCoreSmokeCloseObserver() override = default;

  void ExpectComplete() const {
    CHECK_EQ(stage_, Stage::kCloseAllStopped);
  }

 private:
  enum class Stage {
    kInitial,
    kWillCloseAll,
    kWillRemove,
    kRemoved,
    kEmpty,
    kCloseAllStopped,
  };

  void WillCloseAllTabs(TabStripModel* tab_strip_model) override {
    CHECK_EQ(stage_, Stage::kInitial);
    CHECK_EQ(tab_strip_model->count(), 1);
    stage_ = Stage::kWillCloseAll;
  }

  void OnTabWillBeRemoved(tabs::TabInterface* tab, int index) override {
    CHECK_EQ(stage_, Stage::kWillCloseAll);
    CHECK_EQ(index, 0);
    CHECK_EQ(tab->GetContents(), contents_);
    stage_ = Stage::kWillRemove;
  }

  void OnTabStripModelChanged(
      TabStripModel* tab_strip_model,
      const TabStripModelChange& change,
      const TabStripSelectionChange& selection) override {
    CHECK_EQ(stage_, Stage::kWillRemove);
    CHECK_EQ(change.type(), TabStripModelChange::kRemoved);
    const TabStripModelChange::Remove* const remove = change.GetRemove();
    CHECK_EQ(remove->contents.size(), 1u);
    CHECK_EQ(remove->contents.front().contents, contents_);
    CHECK_EQ(tab_strip_model->count(), 0);
    CHECK_EQ(selection.old_contents, contents_);
    CHECK(!selection.new_contents);
    CHECK(selection.selected_tabs_were_removed);
    stage_ = Stage::kRemoved;
  }

  void TabStripEmpty() override {
    CHECK_EQ(stage_, Stage::kRemoved);
    stage_ = Stage::kEmpty;
  }

  void CloseAllTabsStopped(
      TabStripModel* tab_strip_model,
      TabStripModelObserver::CloseAllStoppedReason reason) override {
    CHECK_EQ(stage_, Stage::kEmpty);
    CHECK(tab_strip_model->empty());
    CHECK_EQ(reason, TabStripModelObserver::kCloseAllCompleted);
    stage_ = Stage::kCloseAllStopped;
  }

  // This address is examined only through the removal callback, while the
  // detached TabModel still owns the WebContents. It is intentionally a plain
  // non-owning value because TabStripEmpty() follows destruction.
  content::WebContents* contents_;
  Stage stage_ = Stage::kInitial;
};

}  // namespace

bool RunWasmTabCoreSmoke(WasmProfile* profile) {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(profile);

  TabCoreSmokeDelegate delegate(profile);
  TabStripModel tab_strip_model(&delegate, profile,
                                /*group_model_factory=*/nullptr);

  content::WebContents::CreateParams create_params(profile);
  std::unique_ptr<content::WebContents> contents =
      content::WebContents::Create(create_params);
  CHECK(contents);
  content::WebContents* const raw_contents = contents.get();

  tab_strip_model.AppendWebContents(std::move(contents), /*foreground=*/true);

  CHECK_EQ(tab_strip_model.count(), 1);
  CHECK_EQ(tab_strip_model.active_index(), 0);
  CHECK_EQ(tab_strip_model.GetActiveWebContents(), raw_contents);
  CHECK_EQ(tab_strip_model.GetTabAtIndex(0), tab_strip_model.GetActiveTab());
  CHECK(tab_strip_model.IsTabSelected(0));
  CHECK(tab_strip_model.IsTabInForeground(0));
  CHECK(!tab_strip_model.IsTabBlocked(0));

  const std::vector<tabs::TabInterface*> foreground_tabs =
      tab_strip_model.GetForegroundTabs();
  CHECK_EQ(foreground_tabs.size(), 1u);
  CHECK_EQ(foreground_tabs.front(), tab_strip_model.GetActiveTab());

  // This is the real transient SessionTabHelper ID established before
  // TabModel construction, not a made-up tab or window identifier.
  const SessionID session_tab_id = GetWasmSessionTabId(raw_contents);
  CHECK(session_tab_id.is_valid());

  // ChromeSecurityStateTabHelper shares SecurityStateTabHelper's UserData
  // key. The elevated bit proves that the Chrome-owned derived helper, rather
  // than the generic content helper, owns the identity for this tab.
  auto* chrome_security_state_helper =
      static_cast<ChromeSecurityStateTabHelper*>(
          SecurityStateTabHelper::FromWebContents(raw_contents));
  CHECK(chrome_security_state_helper);
  CHECK(chrome_security_state_helper->uses_embedder_information().value());

  web_modal::WebContentsModalDialogManager* const modal_manager =
      web_modal::WebContentsModalDialogManager::FromWebContents(raw_contents);
  CHECK(modal_manager);
  CHECK(!modal_manager->IsDialogActive());

  TabCoreSmokeCloseObserver close_observer(raw_contents);
  tab_strip_model.AddObserver(&close_observer);
  tab_strip_model.GetTabAtIndex(0)->Close();
  close_observer.ExpectComplete();
  tab_strip_model.RemoveObserver(&close_observer);
  CHECK(tab_strip_model.empty());
  CHECK_EQ(tab_strip_model.GetActiveWebContents(), nullptr);

  std::unique_ptr<content::WebContents> second_contents =
      content::WebContents::Create(create_params);
  CHECK(second_contents);
  content::WebContents* const second_raw_contents = second_contents.get();
  tab_strip_model.AppendWebContents(std::move(second_contents),
                                    /*foreground=*/true);
  TabCoreSmokeCloseObserver close_all_observer(second_raw_contents);
  tab_strip_model.AddObserver(&close_all_observer);
  tab_strip_model.CloseAllTabs();
  close_all_observer.ExpectComplete();
  tab_strip_model.RemoveObserver(&close_all_observer);
  CHECK(tab_strip_model.empty());
  CHECK_EQ(tab_strip_model.GetActiveWebContents(), nullptr);

  std::fprintf(stderr, "%s:PASS\n", kTabCoreSmokeMarker);
  return true;
}

}  // namespace chrome
