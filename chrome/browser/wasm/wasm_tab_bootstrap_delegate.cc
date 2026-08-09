// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_tab_bootstrap_delegate.h"

#include "base/check.h"
#include "base/functional/callback.h"
#include "build/build_config.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_tab_bootstrap_delegate.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

[[noreturn]] void UnsupportedTabBootstrapOperation(const char* operation) {
  CHECK(false) << "Wasm tab bootstrap does not support " << operation;
}

}  // namespace

WasmTabBootstrapDelegate::WasmTabBootstrapDelegate(
    BrowserWindowInterface* browser_window_interface)
    : browser_window_interface_(browser_window_interface) {
  CHECK(browser_window_interface_);
  CHECK_EQ(browser_window_interface_->GetType(),
           BrowserWindowInterface::TYPE_NORMAL);
}

WasmTabBootstrapDelegate::~WasmTabBootstrapDelegate() = default;

void WasmTabBootstrapDelegate::AddTabAt(
    const GURL& /*url*/,
    int /*index*/,
    bool /*foreground*/,
    std::optional<tab_groups::TabGroupId> /*group*/,
    bool /*pinned*/) {
  UnsupportedTabBootstrapOperation("tab creation");
}

Browser* WasmTabBootstrapDelegate::CreateNewStripWithTabs(
    std::vector<NewStripContents> /*tabs*/,
    const gfx::Rect& /*window_bounds*/,
    bool /*maximize*/) {
  UnsupportedTabBootstrapOperation("window creation");
}

void WasmTabBootstrapDelegate::WillAddWebContents(
    content::WebContents* contents) {
  CHECK(contents);

  // This delegate is reached after TabModel construction. It cannot establish
  // the SessionTabHelper precondition that TabModel needs, and it must not
  // prematurely choose between generic and Chrome security-state helpers. A
  // future Wasm TabModel owns that explicit pre-construction helper policy.
}

int WasmTabBootstrapDelegate::GetDragActions() const {
  return 0;  // Explicitly no move or tear-off actions.
}

bool WasmTabBootstrapDelegate::CanDuplicateContentsAt(int /*index*/) {
  return false;  // Explicitly unsupported.
}

bool WasmTabBootstrapDelegate::IsTabStripEditable() {
  return false;  // Editing/reordering is not in this bootstrap slice.
}

content::WebContents* WasmTabBootstrapDelegate::DuplicateContentsAt(
    int /*index*/) {
  return nullptr;  // Explicit unsupported result.
}

void WasmTabBootstrapDelegate::DuplicateSplit(
    split_tabs::SplitTabId /*split*/) {
  UnsupportedTabBootstrapOperation("split duplication");
}

void WasmTabBootstrapDelegate::MoveToExistingWindow(
    const std::vector<int>& /*indices*/,
    int /*browser_index*/) {
  UnsupportedTabBootstrapOperation("moving tabs between windows");
}

bool WasmTabBootstrapDelegate::CanMoveTabsToWindow(
    const std::vector<int>& /*indices*/) {
  return false;  // Explicitly unsupported.
}

void WasmTabBootstrapDelegate::MoveTabsToNewWindow(
    const std::vector<int>& /*indices*/) {
  UnsupportedTabBootstrapOperation("moving tabs to a new window");
}

void WasmTabBootstrapDelegate::MoveGroupToNewWindow(
    const tab_groups::TabGroupId& /*group*/) {
  UnsupportedTabBootstrapOperation("moving a tab group to a new window");
}

std::optional<SessionID> WasmTabBootstrapDelegate::CreateHistoricalTab(
    content::WebContents* /*contents*/) {
  return std::nullopt;  // Explicitly no tab-restore persistence.
}

void WasmTabBootstrapDelegate::CreateHistoricalGroup(
    const tab_groups::TabGroupId& /*group*/) {
  UnsupportedTabBootstrapOperation("historical tab groups");
}

void WasmTabBootstrapDelegate::CreateHistoricalSplit(
    const split_tabs::SplitTabId& /*split_id*/) {
  UnsupportedTabBootstrapOperation("historical split tabs");
}

void WasmTabBootstrapDelegate::GroupAdded(
    const tab_groups::TabGroupId& /*group*/) {
  UnsupportedTabBootstrapOperation("tab groups");
}

void WasmTabBootstrapDelegate::WillCloseGroup(
    const tab_groups::TabGroupId& /*group*/) {
  UnsupportedTabBootstrapOperation("closing tab groups");
}

void WasmTabBootstrapDelegate::WillCloseSplit(
    const split_tabs::SplitTabId& /*split_id*/) {
  UnsupportedTabBootstrapOperation("closing split tabs");
}

void WasmTabBootstrapDelegate::GroupCloseStopped(
    const tab_groups::TabGroupId& /*group*/) {
  UnsupportedTabBootstrapOperation("tab-group close cancellation");
}

void WasmTabBootstrapDelegate::SplitClosed(
    const split_tabs::SplitTabId& /*split_id*/) {
  UnsupportedTabBootstrapOperation("split-tab closure");
}

void WasmTabBootstrapDelegate::SplitCloseStopped(
    const split_tabs::SplitTabId& /*split_id*/) {
  UnsupportedTabBootstrapOperation("split-tab close cancellation");
}

bool WasmTabBootstrapDelegate::RunUnloadListenerBeforeClosing(
    content::WebContents* /*contents*/) {
  UnsupportedTabBootstrapOperation("tab close unload handling");
}

bool WasmTabBootstrapDelegate::ShouldRunUnloadListenerBeforeClosing(
    content::WebContents* contents) {
  CHECK(contents);
  CHECK(!contents->NeedToFireBeforeUnloadOrUnloadEvents())
      << "Wasm tab bootstrap does not support asynchronous beforeunload or "
         "unload handling";

  // The bounded TabStripModel close path has already established that the
  // one initial tab has no pending beforeunload or unload work. Do not ask for
  // a delegate-owned asynchronous close sequence that this source-selected
  // bootstrap deliberately does not implement.
  return false;
}

bool WasmTabBootstrapDelegate::CanReload() const {
  return false;  // Explicitly unsupported until the browser command lifecycle.
}

void WasmTabBootstrapDelegate::AddToReadLater(
    std::vector<content::WebContents*> /*web_contentses*/) {
  UnsupportedTabBootstrapOperation("Read Later");
}

bool WasmTabBootstrapDelegate::SupportsReadLater() {
  return false;  // Explicitly unsupported.
}

bool WasmTabBootstrapDelegate::IsForWebApp() {
  return false;  // This delegate only admits TYPE_NORMAL Browser windows.
}

void WasmTabBootstrapDelegate::CopyURL(
    content::WebContents* /*web_contents*/) {
  UnsupportedTabBootstrapOperation("copying tab URLs");
}

void WasmTabBootstrapDelegate::GoBack(
    content::WebContents* /*web_contents*/) {
  UnsupportedTabBootstrapOperation("web-app tab navigation");
}

bool WasmTabBootstrapDelegate::CanGoBack(
    content::WebContents* /*web_contents*/) {
  return false;  // Explicitly unsupported.
}

bool WasmTabBootstrapDelegate::IsNormalWindow() {
  return browser_window_interface_->GetType() ==
         BrowserWindowInterface::TYPE_NORMAL;
}

BrowserWindowInterface*
WasmTabBootstrapDelegate::GetBrowserWindowInterface() {
  return browser_window_interface_;
}

void WasmTabBootstrapDelegate::NewSplitTab(
    std::vector<int> /*indices*/,
    split_tabs::SplitTabLayout /*layout*/,
    split_tabs::SplitTabCreatedSource /*source*/) {
  UnsupportedTabBootstrapOperation("split tabs");
}

void WasmTabBootstrapDelegate::OnGroupsDestruction(
    const std::vector<tab_groups::TabGroupId>& /*group_ids*/,
    base::OnceCallback<void()> /*close_callback*/,
    bool /*delete_groups*/) {
  UnsupportedTabBootstrapOperation("tab-group destruction");
}

void WasmTabBootstrapDelegate::OnRemovingAllTabsFromGroups(
    const std::vector<tab_groups::TabGroupId>& /*group_ids*/,
    base::OnceCallback<void()> /*callback*/) {
  UnsupportedTabBootstrapOperation("removing tabs from groups");
}

bool WasmTabBootstrapDelegate::IsTabGlicPinned(
    tabs::TabHandle /*tab_handle*/) {
  return false;  // Explicitly unsupported.
}

bool WasmTabBootstrapDelegate::GlicPinTabs(
    base::span<const tabs::TabHandle> /*tab_handles*/) {
  return false;  // Explicitly unsupported.
}

bool WasmTabBootstrapDelegate::GlicUnpinTabs(
    base::span<const tabs::TabHandle> /*tab_handles*/) {
  return false;  // Explicitly unsupported.
}

void WasmTabBootstrapDelegate::OpenGlicWindowFromSharedTab() {
  UnsupportedTabBootstrapOperation("Glic");
}

void WasmTabBootstrapDelegate::GlicUnpinTabsFromAllConversations(
    base::span<const tabs::TabHandle> /*tab_handles*/) {
  UnsupportedTabBootstrapOperation("Glic");
}

}  // namespace chrome
