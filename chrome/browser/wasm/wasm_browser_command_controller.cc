// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/ui/browser_command_controller.h"

#include <memory>

#include "base/check.h"
#include "base/functional/bind.h"
#include "build/build_config.h"
#include "chrome/app/chrome_command_ids.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "components/tabs/public/tab_interface.h"
#include "content/public/browser/navigation_controller.h"
#include "content/public/browser/reload_type.h"
#include "content/public/browser/web_contents.h"
#include "content/public/browser/web_contents_observer.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_command_controller.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

// Keep this list deliberately small. Each command below maps directly to a
// Chromium NavigationController or WebContents operation and does not need a
// desktop Browser, an action catalog, a profile service, or an unimplemented
// window-management capability.
bool IsWasmNavigationCommand(int command_id) {
  switch (command_id) {
    case IDC_BACK:
    case IDC_FORWARD:
    case IDC_RELOAD:
    case IDC_RELOAD_BYPASSING_CACHE:
    case IDC_STOP:
      return true;
    default:
      return false;
  }
}

}  // namespace

class BrowserCommandController::ActiveContentsObserver
    : public content::WebContentsObserver {
 public:
  ActiveContentsObserver(BrowserCommandController* controller,
                         content::WebContents* web_contents)
      : content::WebContentsObserver(web_contents), controller_(controller) {
    CHECK(controller_);
    CHECK(web_contents);
  }

  ActiveContentsObserver(const ActiveContentsObserver&) = delete;
  ActiveContentsObserver& operator=(const ActiveContentsObserver&) = delete;

  ~ActiveContentsObserver() override = default;

  content::WebContents* observed_contents() const { return web_contents(); }

  void DidFinishNavigation(
      content::NavigationHandle* /*navigation_handle*/) override {
    controller_->UpdateNavigationCommands();
  }

  void DidStartLoading() override { controller_->UpdateNavigationCommands(); }

  void DidStopLoading() override { controller_->UpdateNavigationCommands(); }

  void NavigationEntriesDeleted() override {
    controller_->UpdateNavigationCommands();
  }

  void WebContentsDestroyed() override {
    // BrowserWindowInterface's active-tab callback owns selecting a replacement
    // WebContents. Do not recreate this observer while it is handling its own
    // teardown notification, and do not query NavigationController while the
    // observed WebContents is being destroyed.
    controller_->ActiveContentsDestroyed();
  }

 private:
  const raw_ptr<BrowserCommandController> controller_;
};

BrowserCommandController::BrowserCommandController(BrowserWindowInterface* bwi)
    : browser_window_interface_(bwi) {
  CHECK(browser_window_interface_);

  active_tab_changed_subscription_ =
      browser_window_interface_->RegisterActiveTabDidChange(
          base::BindRepeating(&BrowserCommandController::ActiveTabChanged,
                              base::Unretained(this)));

  // Create each allowlisted entry before Views can attach observers. Unknown
  // command ids are rejected by every public CommandUpdater entry point.
  command_updater_.UpdateCommandEnabled(IDC_BACK, false);
  command_updater_.UpdateCommandEnabled(IDC_FORWARD, false);
  command_updater_.UpdateCommandEnabled(IDC_RELOAD, false);
  command_updater_.UpdateCommandEnabled(IDC_RELOAD_BYPASSING_CACHE, false);
  command_updater_.UpdateCommandEnabled(IDC_STOP, false);
  ObserveActiveContents();
}

BrowserCommandController::~BrowserCommandController() = default;

bool BrowserCommandController::IsReservedCommandOrKey(
    int command_id,
    const input::NativeWebKeyboardEvent& event) {
  // A supported navigation shortcut is a browser accelerator. Every other
  // desktop command remains unreserved until its full implementation is
  // source-selected, so it cannot look like a functioning Wasm command.
  static_cast<void>(event);
  return IsWasmNavigationCommand(command_id);
}

void BrowserCommandController::TabStateChanged() {
  ObserveActiveContents();
}

void BrowserCommandController::ZoomStateChanged() {
  UpdateNavigationCommands();
}

void BrowserCommandController::ContentRestrictionsChanged() {
  UpdateNavigationCommands();
}

void BrowserCommandController::FullscreenStateChanged() {
  UpdateNavigationCommands();
}

void BrowserCommandController::PrintingStateChanged() {
  UpdateNavigationCommands();
}

void BrowserCommandController::GlicActiveInstanceChanged(
    glic::GlicInstance* /*instance*/) {
  UpdateNavigationCommands();
}

void BrowserCommandController::GlicFreStateChanged(
    glic::mojom::FreWebUiState /*new_state*/) {
  UpdateNavigationCommands();
}

void BrowserCommandController::LoadingStateChanged(bool is_loading,
                                                   bool force) {
  // Query the real WebContents rather than trusting the notification payload:
  // the active tab can change between a queued loading notification and this
  // controller update.
  static_cast<void>(is_loading);
  static_cast<void>(force);
  UpdateNavigationCommands();
}

void BrowserCommandController::FindBarVisibilityChanged() {
  UpdateNavigationCommands();
}

void BrowserCommandController::ExtensionStateChanged() {
  UpdateNavigationCommands();
}

void BrowserCommandController::TabKeyboardFocusChangedTo(
    std::optional<int> index) {
  static_cast<void>(index);
  UpdateNavigationCommands();
}

void BrowserCommandController::WebContentsFocusChanged() {
  UpdateNavigationCommands();
}

bool BrowserCommandController::SupportsCommand(int id) const {
  return IsWasmNavigationCommand(id);
}

bool BrowserCommandController::IsCommandEnabled(int id) const {
  return SupportsCommand(id) && command_updater_.IsCommandEnabled(id);
}

bool BrowserCommandController::ExecuteCommand(int id,
                                              base::TimeTicks time_stamp) {
  return ExecuteCommandWithDisposition(id, WindowOpenDisposition::CURRENT_TAB,
                                       time_stamp);
}

bool BrowserCommandController::ExecuteCommandWithDisposition(
    int id,
    WindowOpenDisposition disposition,
    base::TimeTicks time_stamp) {
  // The first browser window has no tab duplication/reparenting lifecycle.
  // Reject non-current dispositions explicitly instead of silently navigating
  // a different tab or pretending the requested operation succeeded.
  if (disposition != WindowOpenDisposition::CURRENT_TAB) {
    return false;
  }

  static_cast<void>(time_stamp);
  UpdateNavigationCommands();
  if (!IsCommandEnabled(id)) {
    return false;
  }

  content::WebContents* const web_contents = GetActiveContents();
  if (!web_contents || web_contents->IsBeingDestroyed()) {
    return false;
  }

  content::NavigationController& navigation_controller =
      web_contents->GetController();
  switch (id) {
    case IDC_BACK:
      // Back-to-opener navigation is intentionally outside this source
      // closure. The enabled state above requires real session history.
      navigation_controller.GoBack();
      return true;
    case IDC_FORWARD:
      navigation_controller.GoForward();
      return true;
    case IDC_RELOAD:
      navigation_controller.Reload(content::ReloadType::NORMAL,
                                   /*check_for_repost=*/true);
      return true;
    case IDC_RELOAD_BYPASSING_CACHE:
      navigation_controller.Reload(content::ReloadType::BYPASSING_CACHE,
                                   /*check_for_repost=*/true);
      return true;
    case IDC_STOP:
      web_contents->Stop();
      return true;
    default:
      return false;
  }
}

void BrowserCommandController::AddCommandObserver(int id,
                                                  CommandObserver* observer) {
  if (SupportsCommand(id)) {
    command_updater_.AddCommandObserver(id, observer);
  }
}

void BrowserCommandController::RemoveCommandObserver(
    int id,
    CommandObserver* observer) {
  if (SupportsCommand(id)) {
    command_updater_.RemoveCommandObserver(id, observer);
  }
}

void BrowserCommandController::RemoveCommandObserver(
    CommandObserver* observer) {
  command_updater_.RemoveCommandObserver(observer);
}

bool BrowserCommandController::UpdateCommandEnabled(int id, bool state) {
  if (!SupportsCommand(id)) {
    return false;
  }
  return command_updater_.UpdateCommandEnabled(id, state);
}

void BrowserCommandController::ObserveActiveContents() {
  if (active_contents_destroyed_) {
    ClearNavigationCommands();
    return;
  }

  content::WebContents* const active_contents = GetActiveContents();
  if (!active_contents_observer_ ||
      active_contents_observer_->observed_contents() != active_contents) {
    active_contents_observer_.reset();
    if (active_contents) {
      active_contents_observer_ =
          std::make_unique<ActiveContentsObserver>(this, active_contents);
    }
  }
  UpdateNavigationCommands();
}

void BrowserCommandController::ActiveTabChanged(
    BrowserWindowInterface* browser_window_interface) {
  CHECK_EQ(browser_window_interface, browser_window_interface_);
  active_contents_destroyed_ = false;
  ObserveActiveContents();
}

void BrowserCommandController::ActiveContentsDestroyed() {
  active_contents_destroyed_ = true;
  ClearNavigationCommands();
}

void BrowserCommandController::ClearNavigationCommands() {
  command_updater_.UpdateCommandEnabled(IDC_BACK, false);
  command_updater_.UpdateCommandEnabled(IDC_FORWARD, false);
  command_updater_.UpdateCommandEnabled(IDC_RELOAD, false);
  command_updater_.UpdateCommandEnabled(IDC_RELOAD_BYPASSING_CACHE, false);
  command_updater_.UpdateCommandEnabled(IDC_STOP, false);
}

void BrowserCommandController::UpdateNavigationCommands() {
  content::WebContents* const web_contents = GetActiveContents();
  if (!web_contents || web_contents->IsBeingDestroyed()) {
    // NavigationController may no longer be safe to query during WebContents
    // teardown. The observer's WebContentsDestroyed() callback will retain
    // this disabled state until BrowserWindowInterface selects a replacement.
    ClearNavigationCommands();
    return;
  }

  command_updater_.UpdateCommandEnabled(
      IDC_BACK, web_contents->GetController().CanGoBack());
  command_updater_.UpdateCommandEnabled(
      IDC_FORWARD, web_contents->GetController().CanGoForward());
  command_updater_.UpdateCommandEnabled(IDC_RELOAD, true);
  command_updater_.UpdateCommandEnabled(IDC_RELOAD_BYPASSING_CACHE,
                                        true);
  command_updater_.UpdateCommandEnabled(
      IDC_STOP, web_contents->IsLoading());
}

content::WebContents* BrowserCommandController::GetActiveContents() const {
  if (active_contents_destroyed_) {
    return nullptr;
  }

  tabs::TabInterface* const active_tab =
      browser_window_interface_->GetActiveTabInterface();
  return active_tab ? active_tab->GetContents() : nullptr;
}

// ShowCustomizeChromeSidePanel() and
// UpdateSharedCommandsForIncognitoAvailability() intentionally have no Wasm
// definitions. Linking either API is an explicit feature-boundary failure
// until the corresponding side-panel or profile-command lifecycle is real.

}  // namespace chrome
