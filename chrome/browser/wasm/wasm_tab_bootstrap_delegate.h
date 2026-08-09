// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_TAB_BOOTSTRAP_DELEGATE_H_
#define CHROME_BROWSER_WASM_WASM_TAB_BOOTSTRAP_DELEGATE_H_

#include <optional>
#include <vector>

#include "base/containers/span.h"
#include "base/memory/raw_ptr.h"
#include "chrome/browser/ui/tabs/tab_strip_model_delegate.h"

class BrowserWindowInterface;

namespace chrome {

// The narrow delegate for the first source-selected Wasm tab bootstrap.
//
// This object supplies the real BrowserWindowInterface identity and the
// bounded no-unload policy used by explicit Wasm smokes. It deliberately does
// not create windows, attach general WebContents helpers, persist sessions, or
// service tab menus. Those operations must remain outside the source closure
// until their complete Browser/TabStripModel lifecycles are selected.
//
// The BrowserWindowInterface must outlive this delegate. It is currently wired
// only by explicit Wasm BrowserWindowInterface smoke targets, including an
// empty core and the bounded one-tab close smoke; a future TYPE_NORMAL Browser
// owns both objects and supplies the interface at construction.
class WasmTabBootstrapDelegate : public TabStripModelDelegate {
 public:
  explicit WasmTabBootstrapDelegate(
      BrowserWindowInterface* browser_window_interface);

  WasmTabBootstrapDelegate(const WasmTabBootstrapDelegate&) = delete;
  WasmTabBootstrapDelegate& operator=(const WasmTabBootstrapDelegate&) =
      delete;

  ~WasmTabBootstrapDelegate() override;

 private:
  // TabStripModelDelegate:
  void AddTabAt(const GURL& url,
                int index,
                bool foreground,
                std::optional<tab_groups::TabGroupId> group,
                bool pinned) override;
  Browser* CreateNewStripWithTabs(std::vector<NewStripContents> tabs,
                                  const gfx::Rect& window_bounds,
                                  bool maximize) override;
  void WillAddWebContents(content::WebContents* contents) override;
  int GetDragActions() const override;
  bool CanDuplicateContentsAt(int index) override;
  bool IsTabStripEditable() override;
  content::WebContents* DuplicateContentsAt(int index) override;
  void DuplicateSplit(split_tabs::SplitTabId split) override;
  void MoveToExistingWindow(const std::vector<int>& indices,
                            int browser_index) override;
  bool CanMoveTabsToWindow(const std::vector<int>& indices) override;
  void MoveTabsToNewWindow(const std::vector<int>& indices) override;
  void MoveGroupToNewWindow(const tab_groups::TabGroupId& group) override;
  std::optional<SessionID> CreateHistoricalTab(
      content::WebContents* contents) override;
  void CreateHistoricalGroup(const tab_groups::TabGroupId& group) override;
  void CreateHistoricalSplit(const split_tabs::SplitTabId& split_id) override;
  void GroupAdded(const tab_groups::TabGroupId& group) override;
  void WillCloseGroup(const tab_groups::TabGroupId& group) override;
  void WillCloseSplit(const split_tabs::SplitTabId& split_id) override;
  void GroupCloseStopped(const tab_groups::TabGroupId& group) override;
  void SplitClosed(const split_tabs::SplitTabId& split_id) override;
  void SplitCloseStopped(const split_tabs::SplitTabId& split_id) override;
  bool RunUnloadListenerBeforeClosing(content::WebContents* contents) override;
  bool ShouldRunUnloadListenerBeforeClosing(
      content::WebContents* contents) override;
  bool CanReload() const override;
  void AddToReadLater(
      std::vector<content::WebContents*> web_contentses) override;
  bool SupportsReadLater() override;
  bool IsForWebApp() override;
  void CopyURL(content::WebContents* web_contents) override;
  void GoBack(content::WebContents* web_contents) override;
  bool CanGoBack(content::WebContents* web_contents) override;
  bool IsNormalWindow() override;
  BrowserWindowInterface* GetBrowserWindowInterface() override;
  void NewSplitTab(std::vector<int> indices,
                   split_tabs::SplitTabLayout layout,
                   split_tabs::SplitTabCreatedSource source) override;
  void OnGroupsDestruction(const std::vector<tab_groups::TabGroupId>& group_ids,
                           base::OnceCallback<void()> close_callback,
                           bool delete_groups) override;
  void OnRemovingAllTabsFromGroups(
      const std::vector<tab_groups::TabGroupId>& group_ids,
      base::OnceCallback<void()> callback) override;
  bool IsTabGlicPinned(tabs::TabHandle tab_handle) override;
  bool GlicPinTabs(base::span<const tabs::TabHandle> tab_handles) override;
  bool GlicUnpinTabs(base::span<const tabs::TabHandle> tab_handles) override;
  void OpenGlicWindowFromSharedTab() override;
  void GlicUnpinTabsFromAllConversations(
      base::span<const tabs::TabHandle> tab_handles) override;

  const raw_ptr<BrowserWindowInterface> browser_window_interface_;
};

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_TAB_BOOTSTRAP_DELEGATE_H_
