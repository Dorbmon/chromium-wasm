// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_window_core.h"

#include <utility>

#include "base/check.h"
#include "build/build_config.h"
#include "chrome/browser/ui/browser_window/public/browser_window_features.h"
#include "chrome/browser/ui/tabs/tab_strip_model.h"
#include "chrome/browser/wasm/wasm_tab_bootstrap_delegate.h"
#include "components/tabs/public/tab_interface.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_window_core.cc must only be built for WebAssembly"
#endif

namespace {

[[noreturn]] void UnsupportedWasmBrowserWindowCoreOperation(
    const char* operation) {
  CHECK(false) << "Wasm browser-window core does not support " << operation;
}

}  // namespace

WasmBrowserWindowCore::WasmBrowserWindowCore(Profile* profile)
    : profile_(profile), session_id_(SessionID::NewUnique()) {
  CHECK(profile_);

  // The delegate and model precede BrowserWindowFeatures because the selected
  // command controller subscribes to active-tab changes during feature init.
  tab_delegate_ = std::make_unique<chrome::WasmTabBootstrapDelegate>(this);
  tab_strip_model_ = std::make_unique<TabStripModel>(
      tab_delegate_.get(), profile_.get(), /*group_model_factory=*/nullptr);
  features_ = std::make_unique<BrowserWindowFeatures>();
  features_->Init(this);
}

WasmBrowserWindowCore::~WasmBrowserWindowCore() {
  CHECK(tab_strip_model_);
  CHECK(tab_strip_model_->empty())
      << "Wasm browser-window core requires the joined tab close lifecycle";

  if (!is_delete_scheduled_) {
    // BrowserManagerService shutdown can destroy an unclosed empty core. Keep
    // the global/profile collections coherent without pretending a tab close
    // completed.
    NotifyBrowserDidClose();
  }

  weak_ptr_factory_.InvalidateWeakPtrs();

  // BrowserWindowFeatures owns UDDs whose host is this object. Tear them down
  // while the callback lists, model, delegate, and host are all still alive.
  features_->TearDownPreBrowserWindowDestruction();
  features_.reset();
  tab_strip_model_.reset();
  tab_delegate_.reset();
}

void WasmBrowserWindowCore::CloseForWasmBrowserWindowCoreSmoke() {
  CHECK(tab_strip_model_);
  CHECK(tab_strip_model_->empty());
  NotifyBrowserDidClose();
}

void WasmBrowserWindowCore::NotifyActiveTabDidChangeForWasmSmoke() {
  CHECK(tab_strip_model_);
  CHECK(!is_delete_scheduled_);

  // This smoke-only relay must reflect a real TabStripModel selection change,
  // rather than manufacture duplicate or stale BrowserWindowInterface events.
  tabs::TabInterface* const active_tab = GetActiveTabInterface();
  CHECK_NE(active_tab, last_notified_active_tab_.get());
  last_notified_active_tab_ = active_tab;
  active_tab_changed_callbacks_.Notify(this);
}

ui::UnownedUserDataHost& WasmBrowserWindowCore::GetUnownedUserDataHost() {
  return unowned_user_data_host_;
}

const ui::UnownedUserDataHost&
WasmBrowserWindowCore::GetUnownedUserDataHost() const {
  return unowned_user_data_host_;
}

ui::BaseWindow* WasmBrowserWindowCore::GetWindow() {
  // A null BaseWindow is the honest pre-BrowserView state. The Wasm fullscreen
  // controller explicitly supports this state during feature initialization.
  return nullptr;
}

const ui::BaseWindow* WasmBrowserWindowCore::GetWindow() const {
  return nullptr;
}

Profile* WasmBrowserWindowCore::GetProfile() {
  return profile_.get();
}

const Profile* WasmBrowserWindowCore::GetProfile() const {
  return profile_.get();
}

const SessionID& WasmBrowserWindowCore::GetSessionID() const {
  return session_id_;
}

bool WasmBrowserWindowCore::IsDeleteScheduled() const {
  return is_delete_scheduled_;
}

base::CallbackListSubscription
WasmBrowserWindowCore::RegisterBrowserDidClose(
    BrowserDidCloseCallback callback) {
  return browser_did_close_callbacks_.Add(std::move(callback));
}

BrowserWindowInterface::Type WasmBrowserWindowCore::GetType() const {
  return TYPE_NORMAL;
}

base::WeakPtr<BrowserWindowInterface> WasmBrowserWindowCore::GetWeakPtr() {
  return weak_ptr_factory_.GetWeakPtr();
}

content::WebContents* WasmBrowserWindowCore::OpenURL(
    const content::OpenURLParams& /*params*/,
    base::OnceCallback<void(content::NavigationHandle&)>
        /*navigation_handle_callback*/) {
  UnsupportedWasmBrowserWindowCoreOperation("OpenURL navigation");
}

void WasmBrowserWindowCore::OpenGURL(
    const GURL& /*gurl*/,
    WindowOpenDisposition /*disposition*/) {
  UnsupportedWasmBrowserWindowCoreOperation("OpenGURL navigation");
}

TabStripModel* WasmBrowserWindowCore::GetTabStripModel() {
  return tab_strip_model_.get();
}

const TabStripModel* WasmBrowserWindowCore::GetTabStripModel() const {
  return tab_strip_model_.get();
}

bool WasmBrowserWindowCore::IsTabStripVisible() {
  // The object-only core has no BrowserView tab-strip presentation yet.
  return false;
}

base::CallbackListSubscription
WasmBrowserWindowCore::RegisterBrowserCloseCancelled(
    BrowserCloseCancelledCallback callback) {
  return browser_close_cancelled_callbacks_.Add(std::move(callback));
}

base::CallbackListSubscription
WasmBrowserWindowCore::RegisterActiveTabDidChange(
    ActiveTabChangeCallback callback) {
  return active_tab_changed_callbacks_.Add(std::move(callback));
}

tabs::TabInterface* WasmBrowserWindowCore::GetActiveTabInterface() {
  return tab_strip_model_->GetActiveTab();
}

BrowserWindowFeatures& WasmBrowserWindowCore::GetFeatures() {
  CHECK(features_);
  return *features_;
}

const BrowserWindowFeatures& WasmBrowserWindowCore::GetFeatures() const {
  CHECK(features_);
  return *features_;
}

web_modal::WebContentsModalDialogHost*
WasmBrowserWindowCore::GetWebContentsModalDialogHostForWindow() {
  UnsupportedWasmBrowserWindowCoreOperation("a modal-dialog host");
}

web_modal::WebContentsModalDialogHost*
WasmBrowserWindowCore::GetWebContentsModalDialogHostForTab(
    tabs::TabInterface* /*tab_interface*/) {
  UnsupportedWasmBrowserWindowCoreOperation("a tab modal-dialog host");
}

bool WasmBrowserWindowCore::IsActive() const {
  return is_active_;
}

base::CallbackListSubscription WasmBrowserWindowCore::RegisterDidBecomeActive(
    DidBecomeActiveCallback callback) {
  return did_become_active_callbacks_.Add(std::move(callback));
}

base::CallbackListSubscription
WasmBrowserWindowCore::RegisterDidBecomeInactive(
    DidBecomeInactiveCallback callback) {
  return did_become_inactive_callbacks_.Add(std::move(callback));
}

BrowserActions* WasmBrowserWindowCore::GetActions() {
  return GetFeatures().browser_actions();
}

std::vector<tabs::TabInterface*> WasmBrowserWindowCore::GetAllTabInterfaces() {
  std::vector<tabs::TabInterface*> tabs;
  tabs.reserve(tab_strip_model_->count());
  for (int index = 0; index < tab_strip_model_->count(); ++index) {
    tabs.push_back(tab_strip_model_->GetTabAtIndex(index));
  }
  return tabs;
}

Browser* WasmBrowserWindowCore::GetBrowserForMigrationOnly() {
  UnsupportedWasmBrowserWindowCoreOperation("Browser migration access");
}

const Browser* WasmBrowserWindowCore::GetBrowserForMigrationOnly() const {
  UnsupportedWasmBrowserWindowCoreOperation("Browser migration access");
}

bool WasmBrowserWindowCore::IsTabModalPopupDeprecated() const {
  return false;
}

bool WasmBrowserWindowCore::CreatedBySessionRestore() const {
  return false;
}

DesktopBrowserWindowCapabilities* WasmBrowserWindowCore::capabilities() {
  UnsupportedWasmBrowserWindowCoreOperation("desktop browser capabilities");
}

const DesktopBrowserWindowCapabilities* WasmBrowserWindowCore::capabilities()
    const {
  UnsupportedWasmBrowserWindowCoreOperation("desktop browser capabilities");
}

void WasmBrowserWindowCore::NotifyBrowserDidClose() {
  CHECK(!is_delete_scheduled_);
  is_delete_scheduled_ = true;
  browser_did_close_callbacks_.Notify(this);
}
