// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_window_core.h"

#include <utility>

#include "base/check.h"
#include "base/functional/bind.h"
#include "base/task/single_thread_task_runner.h"
#include "build/build_config.h"
#include "chrome/browser/ui/browser_window/public/browser_window_features.h"
#include "chrome/browser/ui/tabs/tab_strip_model.h"
#include "chrome/browser/ui/tabs/tab_strip_model_observer.h"
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

class WasmBrowserWindowCore::TabStripModelObserver final
    : public ::TabStripModelObserver {
 public:
  explicit TabStripModelObserver(WasmBrowserWindowCore* core) : core_(core) {
    CHECK(core_);
  }

  TabStripModelObserver(const TabStripModelObserver&) = delete;
  TabStripModelObserver& operator=(const TabStripModelObserver&) = delete;
  ~TabStripModelObserver() override = default;

 private:
  // TabStripModelObserver:
  void OnTabWillBeRemoved(tabs::TabInterface* tab, int index) override {
    core_->OnTabWillBeRemovedForWasmBrowserWindowViewSmoke(tab, index);
  }

  void OnTabStripModelChanged(
      TabStripModel* tab_strip_model,
      const TabStripModelChange& change,
      const TabStripSelectionChange& selection) override {
    core_->OnTabStripModelChangedForWasmBrowserWindowViewSmoke(
        tab_strip_model, change, selection);
  }

  void TabStripEmpty() override {
    core_->OnTabStripEmptyForWasmBrowserWindowViewSmoke();
  }

  const raw_ptr<WasmBrowserWindowCore> core_;
};

WasmBrowserWindowCore::WasmBrowserWindowCore(Profile* profile)
    : profile_(profile), session_id_(SessionID::NewUnique()) {
  CHECK(profile_);

  // The delegate and model precede BrowserWindowFeatures because the selected
  // command controller subscribes to active-tab changes during feature init.
  tab_delegate_ = std::make_unique<chrome::WasmTabBootstrapDelegate>(this);
  tab_strip_model_ = std::make_unique<TabStripModel>(
      tab_delegate_.get(), profile_.get(), /*group_model_factory=*/nullptr);
  tab_strip_model_observer_ = std::make_unique<TabStripModelObserver>(this);
  tab_strip_model_->AddObserver(tab_strip_model_observer_.get());
  features_ = std::make_unique<BrowserWindowFeatures>();
  features_->Init(this);
}

WasmBrowserWindowCore::~WasmBrowserWindowCore() {
  CHECK(tab_strip_model_);
  CHECK(tab_strip_model_->empty())
      << "Wasm browser-window core requires the joined tab close lifecycle";
  CHECK(!window_)
      << "Wasm browser-window core requires the Views window to unbind first";

  if (!is_delete_scheduled_) {
    // BrowserManagerService shutdown can destroy an unclosed empty core. Keep
    // the global/profile collections coherent without pretending a tab close
    // completed.
    NotifyBrowserDidClose();
  }

  weak_ptr_factory_.InvalidateWeakPtrs();

  // BrowserWindowFeatures owns UDDs whose host is this object. Tear them down
  // while the callback lists, model, delegate, and host are all still alive.
  if (!features_torn_down_) {
    features_->TearDownPreBrowserWindowDestruction();
  }
  features_.reset();
  tab_strip_model_observer_.reset();
  tab_strip_model_.reset();
  tab_delegate_.reset();
}

void WasmBrowserWindowCore::CloseForWasmBrowserWindowCoreSmoke() {
  CHECK(tab_strip_model_);
  CHECK(tab_strip_model_->empty());
  CHECK(!window_);
  CHECK(!browser_view_initialized_);
  NotifyBrowserDidClose();
}

void WasmBrowserWindowCore::NotifyActiveTabDidChangeForWasmSmoke() {
  CHECK(tab_strip_model_);
  CHECK(!is_delete_scheduled_);
  CHECK(window_);

  // This smoke-only relay must reflect a real TabStripModel selection change,
  // rather than manufacture duplicate or stale BrowserWindowInterface events.
  tabs::TabInterface* const active_tab = GetActiveTabInterface();
  CHECK_NE(active_tab, last_notified_active_tab_.get());
  last_notified_active_tab_ = active_tab;
  active_tab_changed_callbacks_.Notify(this);
}

void WasmBrowserWindowCore::BindWindowForWasmBrowserWindowViewSmoke(
    ui::BaseWindow* window,
    ActiveContentsChangedCallback active_contents_changed_callback,
    ContentsDetachedCallback contents_detached_callback,
    base::OnceClosure destroy_window_callback) {
  CHECK(window);
  CHECK(!window_);
  CHECK(active_contents_changed_callback);
  CHECK(contents_detached_callback);
  CHECK(destroy_window_callback);
  CHECK(!is_delete_scheduled_);
  CHECK(!browser_view_initialized_);
  CHECK(tab_strip_model_);
  CHECK(tab_strip_model_->empty());

  window_ = window;
  active_contents_changed_callback_ =
      std::move(active_contents_changed_callback);
  contents_detached_callback_ = std::move(contents_detached_callback);
  destroy_window_callback_ = std::move(destroy_window_callback);
}

void WasmBrowserWindowCore::
    InitPostBrowserViewConstructionForWasmBrowserWindowViewSmoke(
        views::View* browser_view) {
  CHECK(window_);
  CHECK(browser_view);
  CHECK(!browser_view_initialized_);
  GetFeatures().InitPostBrowserViewConstruction(browser_view);
  browser_view_initialized_ = true;
}

void WasmBrowserWindowCore::
    OnWindowActivationChangedForWasmBrowserWindowViewSmoke(
        ui::BaseWindow* window,
        bool active) {
  CHECK_EQ(window, window_);
  CHECK(!is_delete_scheduled_);
  if (is_active_ == active) {
    return;
  }

  is_active_ = active;
  if (is_active_) {
    did_become_active_callbacks_.Notify(this);
  } else {
    did_become_inactive_callbacks_.Notify(this);
  }
}

void WasmBrowserWindowCore::RequestCloseForWasmBrowserWindowViewSmoke() {
  CHECK(window_);
  CHECK(!is_delete_scheduled_);
  CHECK(!close_requested_);
  CHECK(tab_strip_model_);
  CHECK_EQ(tab_strip_model_->count(), 1);

  close_requested_ = true;
  // TabStripModel rejects beforeunload, modal, grouped, split, and multi-tab
  // close paths at their boundaries. Do not turn this callback into an
  // acknowledgement of any of those unsupported lifecycles.
  tab_strip_model_->CloseAllTabs();
  CHECK(tab_strip_model_->empty());
}

void WasmBrowserWindowCore::UnbindWindowForWasmBrowserWindowViewSmoke(
    ui::BaseWindow* window) {
  CHECK_EQ(window, window_);
  CHECK(close_requested_);
  CHECK(features_torn_down_);
  CHECK(tab_strip_model_);
  CHECK(tab_strip_model_->empty())
      << "Wasm browser-window core cannot lose a live Views window";
  CHECK(!is_active_)
      << "Deactivate the real BaseWindow before unbinding its lifecycle";
  window_ = nullptr;
  active_contents_changed_callback_.Reset();
  contents_detached_callback_.Reset();
}

base::WeakPtr<WasmBrowserWindowCore>
WasmBrowserWindowCore::GetWeakPtrForWasmBrowserWindowViewSmoke() {
  return weak_ptr_factory_.GetWeakPtr();
}

ui::UnownedUserDataHost& WasmBrowserWindowCore::GetUnownedUserDataHost() {
  return unowned_user_data_host_;
}

const ui::UnownedUserDataHost&
WasmBrowserWindowCore::GetUnownedUserDataHost() const {
  return unowned_user_data_host_;
}

ui::BaseWindow* WasmBrowserWindowCore::GetWindow() {
  // A null BaseWindow is the honest pre-BrowserView state and again after the
  // bounded Views adapter has torn down. The fullscreen controller supports
  // that state during feature initialization.
  return window_.get();
}

const ui::BaseWindow* WasmBrowserWindowCore::GetWindow() const {
  return window_.get();
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

void WasmBrowserWindowCore::OnTabWillBeRemovedForWasmBrowserWindowViewSmoke(
    tabs::TabInterface* tab,
    int index) {
  CHECK(window_);
  CHECK(close_requested_);
  CHECK(tab);
  CHECK_EQ(index, 0);
  CHECK_EQ(tab, tab_strip_model_->GetActiveTab());
  CHECK(contents_detached_callback_);

  // The model owns |contents| until after the kRemoved observer event. Detach
  // the non-owning Views WebView first so it can never retain a dead tab.
  contents_detached_callback_.Run(tab->GetContents(), /*was_active=*/true);
}

void WasmBrowserWindowCore::OnTabStripModelChangedForWasmBrowserWindowViewSmoke(
    TabStripModel* tab_strip_model,
    const TabStripModelChange& /*change*/,
    const TabStripSelectionChange& selection) {
  CHECK_EQ(tab_strip_model, tab_strip_model_.get());
  if (!selection.active_tab_changed()) {
    return;
  }

  CHECK(window_);
  CHECK(active_contents_changed_callback_);
  if (selection.new_contents) {
    CHECK(!selection.old_contents);
    CHECK_EQ(selection.new_contents,
             tab_strip_model_->GetActiveWebContents());
  } else {
    CHECK(selection.old_contents);
    CHECK(!tab_strip_model_->GetActiveWebContents());
  }

  // View-side attachment/detachment precedes BrowserWindowInterface callbacks
  // so BrowserCommandController and future selected consumers see a coherent
  // active contents relationship.
  active_contents_changed_callback_.Run(
      selection.old_contents, selection.new_contents,
      tab_strip_model_->active_index(), selection.reason);
  NotifyActiveTabDidChangeForWasmSmoke();
}

void WasmBrowserWindowCore::OnTabStripEmptyForWasmBrowserWindowViewSmoke() {
  CHECK(close_requested_);
  CHECK(tab_strip_model_->empty());
  base::SingleThreadTaskRunner::GetCurrentDefault()->PostTask(
      FROM_HERE,
      base::BindOnce(
          &WasmBrowserWindowCore::FinishCloseForWasmBrowserWindowViewSmoke,
          weak_ptr_factory_.GetWeakPtr()));
}

void WasmBrowserWindowCore::FinishCloseForWasmBrowserWindowViewSmoke() {
  CHECK(close_requested_);
  CHECK(tab_strip_model_);
  CHECK(tab_strip_model_->empty());
  CHECK(window_);
  CHECK(browser_view_initialized_);
  CHECK(!features_torn_down_);
  CHECK(destroy_window_callback_);

  // BrowserElements and the animation controller retain the real Views
  // object. Their teardown must happen before the adapter resets its
  // BrowserWidget and destroys the BrowserView.
  GetFeatures().TearDownPreBrowserWindowDestruction();
  features_torn_down_ = true;

  base::WeakPtr<WasmBrowserWindowCore> weak_this =
      weak_ptr_factory_.GetWeakPtr();
  std::move(destroy_window_callback_).Run();
  if (!weak_this) {
    return;
  }

  CHECK(!window_);
  NotifyBrowserDidClose();
}

void WasmBrowserWindowCore::NotifyBrowserDidClose() {
  CHECK(!is_delete_scheduled_);
  CHECK(!window_);
  CHECK(!browser_view_initialized_ || features_torn_down_);
  is_delete_scheduled_ = true;
  browser_did_close_callbacks_.Notify(this);
}
