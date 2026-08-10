// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser.h"

#include <utility>

#include "base/check.h"
#include "base/check_op.h"
#include "base/functional/bind.h"
#include "base/scoped_observation.h"
#include "base/task/single_thread_task_runner.h"
#include "build/build_config.h"
#include "chrome/browser/browser_process.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/ui/browser_manager_service.h"
#include "chrome/browser/ui/browser_manager_service_factory.h"
#include "chrome/browser/ui/browser_window.h"
#include "chrome/browser/ui/browser_window/public/browser_window_features.h"
#include "chrome/browser/ui/tabs/tab_strip_model.h"
#include "chrome/browser/ui/tabs/tab_strip_model_observer.h"
#include "chrome/browser/ui/views/frame/browser_view.h"
#include "chrome/browser/wasm/wasm_browser_security_warning_dialog.h"
#include "chrome/browser/wasm/wasm_tab_bootstrap_delegate.h"
#include "components/web_modal/web_contents_modal_dialog_manager.h"
#include "components/tabs/public/tab_interface.h"
#include "content/public/browser/web_contents.h"
#include "ui/views/widget/widget.h"
#include "ui/views/widget/widget_observer.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser.cc must only be built for WebAssembly"
#endif

namespace {

[[noreturn]] void UnsupportedWasmBrowserOperation(const char* operation) {
  CHECK(false) << "Wasm Browser does not support " << operation;
}

}  // namespace

class Browser::TabStripModelObserver final : public ::TabStripModelObserver {
 public:
  explicit TabStripModelObserver(Browser* browser) : browser_(browser) {
    CHECK(browser_);
  }

  TabStripModelObserver(const TabStripModelObserver&) = delete;
  TabStripModelObserver& operator=(const TabStripModelObserver&) = delete;
  ~TabStripModelObserver() override = default;

 private:
  // TabStripModelObserver:
  void OnTabWillBeRemoved(tabs::TabInterface* tab, int index) override {
    browser_->OnTabWillBeRemoved(tab, index);
  }

  void OnTabStripModelChanged(
      TabStripModel* tab_strip_model,
      const TabStripModelChange& change,
      const TabStripSelectionChange& selection) override {
    browser_->OnTabStripModelChanged(tab_strip_model, change, selection);
  }

  void TabStripEmpty() override { browser_->OnTabStripEmpty(); }

  const raw_ptr<Browser> browser_;
};

class Browser::WindowObserver final : public views::WidgetObserver {
 public:
  explicit WindowObserver(Browser* browser) : browser_(browser) {
    CHECK(browser_);
  }

  WindowObserver(const WindowObserver&) = delete;
  WindowObserver& operator=(const WindowObserver&) = delete;
  ~WindowObserver() override { observation_.Reset(); }

  void Observe(views::Widget* widget) {
    CHECK(widget);
    CHECK(!observation_.IsObserving());
    observation_.Observe(widget);
  }

  void Reset() { observation_.Reset(); }

 private:
  // views::WidgetObserver:
  void OnWidgetActivationChanged(views::Widget* /*widget*/,
                                 bool active) override {
    browser_->OnWindowActivationChanged(active);
  }

  void OnWidgetDestroying(views::Widget* /*widget*/) override {
    // FinishClose removes this observation before BrowserWindowDeleter breaks
    // the BrowserWidget/View cycle. Seeing native destruction here therefore
    // means an uncontrolled platform close escaped the Browser owner.
    CHECK(false) << "Wasm Browser requires its controlled close lifecycle";
  }

  const raw_ptr<Browser> browser_;
  base::ScopedObservation<views::Widget, views::WidgetObserver> observation_{
      this};
};

Browser::CreateParams::CreateParams(Profile* profile, bool user_gesture)
    : profile(profile), user_gesture(user_gesture) {}

Browser::CreateParams::CreateParams(const CreateParams&) = default;
Browser::CreateParams& Browser::CreateParams::operator=(const CreateParams&) =
    default;
Browser::CreateParams::~CreateParams() = default;

// static
Browser* Browser::Create(const CreateParams& params) {
  CHECK_EQ(CreationStatus::kOk, GetCreationStatusForProfile(params.profile));
  CHECK_EQ(params.type, TYPE_NORMAL)
      << "Wasm Browser only supports TYPE_NORMAL";
  CHECK(!params.in_tab_dragging)
      << "Wasm Browser does not support tab-drag creation";
  CHECK(params.initial_bounds.IsEmpty())
      << "Wasm Browser does not support CreateParams initial bounds";
  CHECK_EQ(params.initial_show_state, ui::mojom::WindowShowState::kDefault)
      << "Wasm Browser does not support CreateParams initial show state";

  auto browser = std::unique_ptr<Browser>(new Browser(params));
  Browser* const browser_ptr = browser.get();
  BrowserManagerService* const browser_manager =
      BrowserManagerServiceFactory::GetForProfile(params.profile);
  CHECK(browser_manager);
  browser_manager->AddBrowser(std::move(browser));
  return browser_ptr;
}

// static
BrowserWindowInterface::CreationStatus Browser::GetCreationStatusForProfile(
    Profile* profile) {
  if (!g_browser_process || g_browser_process->IsShuttingDown()) {
    return CreationStatus::kErrorShuttingDown;
  }
  if (!profile || !profile->AllowsBrowserWindows()) {
    return CreationStatus::kErrorProfileUnsuitable;
  }
  return CreationStatus::kOk;
}

Browser::Browser(const CreateParams& params)
    : create_params_(params),
      type_(params.type),
      profile_(params.profile),
      session_id_(SessionID::NewUnique()) {
  CHECK(profile_);
  CHECK_EQ(type_, TYPE_NORMAL);
  CHECK(!params.in_tab_dragging);

  // The selected command controller subscribes to active-tab changes during
  // BrowserWindowFeatures::Init(), so establish the model first.
  tab_delegate_ = std::make_unique<chrome::WasmTabBootstrapDelegate>(this);
  tab_strip_model_ = std::make_unique<TabStripModel>(
      tab_delegate_.get(), profile_.get(), /*group_model_factory=*/nullptr);
  tab_strip_model_observer_ = std::make_unique<TabStripModelObserver>(this);
  tab_strip_model_->AddObserver(tab_strip_model_observer_.get());

  features_ = std::make_unique<BrowserWindowFeatures>();
  features_->Init(this);

  window_ = BrowserWindow::CreateBrowserWindow(this, params.user_gesture,
                                                params.in_tab_dragging);
  CHECK(window_);
  BrowserView& browser_view = GetBrowserView();
  browser_view.SetWasmCloseRequestCallback(base::BindRepeating(
      &Browser::OnWindowCloseRequested, base::Unretained(this)));

  window_observer_ = std::make_unique<WindowObserver>(this);
  window_observer_->Observe(browser_view.GetWidget());

  // This Browser owns the shared modal-manager delegate for every current
  // and future bounded-model WebContents.  It is constructed only after the
  // real BrowserView exists, so a user-triggered child dialog can retrieve
  // the active tab's in-canvas modal host through normal Browser ownership.
  security_warning_dialog_ =
      std::make_unique<chrome::WasmBrowserSecurityWarningDialog>(this);

  // The Wasm feature implementation intentionally omits the desktop
  // post-window Browser graph. It uses the real selected BrowserView instead.
  features_->InitPostBrowserViewConstruction(&browser_view);
  browser_view.InitializeWasmTopControls(
      this, features_->browser_command_controller(),
      base::BindRepeating(
          [](base::WeakPtr<Browser> browser) {
            return browser && browser->CreateWasmUserTab();
          },
          weak_ptr_factory_.GetWeakPtr()),
      base::BindRepeating(
          [](base::WeakPtr<Browser> browser) {
            return browser && browser->CanCreateWasmUserTab();
          },
          weak_ptr_factory_.GetWeakPtr()),
      base::BindRepeating(
          [](base::WeakPtr<Browser> browser, int index) {
            return browser && browser->CanActivateWasmUserTabAt(index);
          },
          weak_ptr_factory_.GetWeakPtr()),
      base::BindRepeating(
          [](base::WeakPtr<Browser> browser, int index) {
            return browser && browser->CloseWasmUserTabAt(index);
          },
          weak_ptr_factory_.GetWeakPtr()),
      base::BindRepeating(
          [](base::WeakPtr<Browser> browser, int index) {
            return browser && browser->CanCloseWasmUserTabAt(index);
          },
          weak_ptr_factory_.GetWeakPtr()),
      base::BindRepeating(
          [](base::WeakPtr<Browser> browser) {
            return browser && browser->ShowWasmSecurityWarningDialog();
          },
          weak_ptr_factory_.GetWeakPtr()));
}

Browser::~Browser() {
  CHECK(tab_strip_model_);
  CHECK(tab_strip_model_->empty())
      << "Wasm Browser requires its bounded tab close lifecycle";
  CHECK(!window_)
      << "Wasm Browser requires BrowserWindow teardown before destruction";
  CHECK(is_delete_scheduled_)
      << "Wasm Browser must finish its bounded close lifecycle before "
         "BrowserManagerService shutdown";

  weak_ptr_factory_.InvalidateWeakPtrs();
  window_observer_.reset();
  security_warning_dialog_.reset();
  if (!features_torn_down_) {
    features_->TearDownPreBrowserWindowDestruction();
  }
  features_.reset();
  tab_strip_model_observer_.reset();
  tab_strip_model_.reset();
  tab_delegate_.reset();
}

BrowserView& Browser::GetBrowserView() {
  CHECK(window_);
  BrowserView* const browser_view = window_->AsBrowserView();
  CHECK(browser_view);
  return *browser_view;
}

base::WeakPtr<Browser> Browser::AsWeakPtr() {
  return weak_ptr_factory_.GetWeakPtr();
}

base::WeakPtr<const Browser> Browser::AsWeakPtr() const {
  return weak_ptr_factory_.GetWeakPtr();
}

void Browser::OnWindowClosing() {
  if (is_delete_scheduled_ || close_requested_) {
    return;
  }

  CHECK(window_);
  CHECK(tab_strip_model_);
  close_requested_ = true;
  CHECK(security_warning_dialog_);
  // TabStripModel's bounded close contract requires no active constrained
  // dialog or blocked tab.  Drain the Browser-owned WCMDM delegates while the
  // model and BrowserWidget are both still live; do not rely on WebContents
  // destruction to close a child Widget after model removal has begun.
  security_warning_dialog_->CloseAllDialogsForBrowserClose();
  if (tab_strip_model_->empty()) {
    // The strict factory may expose an empty Browser before its first initial
    // WebContents is appended. It still owns a real Widget/BWF graph, so
    // close through the same deferred teardown rather than stranding it.
    PostFinishClose();
    return;
  }

  CHECK_LE(tab_strip_model_->count(), 2)
      << "Wasm Browser only closes its bounded two-tab model";
  // TabStripModel enforces no beforeunload, no active modal, no history, and
  // no groups/splits. Do not make this Browser close path an acknowledgement
  // of a wider lifecycle than the model actually implements.
  tab_strip_model_->CloseAllTabs();
  CHECK(tab_strip_model_->empty());
}

ui::UnownedUserDataHost& Browser::GetUnownedUserDataHost() {
  return unowned_user_data_host_;
}

const ui::UnownedUserDataHost& Browser::GetUnownedUserDataHost() const {
  return unowned_user_data_host_;
}

ui::BaseWindow* Browser::GetWindow() {
  return window_.get();
}

const ui::BaseWindow* Browser::GetWindow() const {
  return window_.get();
}

Profile* Browser::GetProfile() {
  return profile_.get();
}

const Profile* Browser::GetProfile() const {
  return profile_.get();
}

const SessionID& Browser::GetSessionID() const {
  return session_id_;
}

bool Browser::IsDeleteScheduled() const {
  return is_delete_scheduled_;
}

base::CallbackListSubscription Browser::RegisterBrowserDidClose(
    BrowserDidCloseCallback callback) {
  return browser_did_close_callbacks_.Add(std::move(callback));
}

BrowserWindowInterface::Type Browser::GetType() const {
  return type_;
}

base::WeakPtr<BrowserWindowInterface> Browser::GetWeakPtr() {
  return weak_ptr_factory_.GetWeakPtr();
}

content::WebContents* Browser::OpenURL(
    const content::OpenURLParams& /*params*/,
    base::OnceCallback<void(content::NavigationHandle&)>
        /*navigation_handle_callback*/) {
  UnsupportedWasmBrowserOperation("BrowserWindowInterface OpenURL");
}

void Browser::OpenGURL(const GURL& /*gurl*/,
                       WindowOpenDisposition /*disposition*/) {
  UnsupportedWasmBrowserOperation("BrowserWindowInterface OpenGURL");
}

TabStripModel* Browser::GetTabStripModel() {
  return tab_strip_model_.get();
}

const TabStripModel* Browser::GetTabStripModel() const {
  return tab_strip_model_.get();
}

bool Browser::IsTabStripVisible() {
  return window_ && GetBrowserView().wasm_tab_strip() != nullptr;
}

base::CallbackListSubscription Browser::RegisterBrowserCloseCancelled(
    BrowserCloseCancelledCallback callback) {
  return browser_close_cancelled_callbacks_.Add(std::move(callback));
}

base::CallbackListSubscription Browser::RegisterActiveTabDidChange(
    ActiveTabChangeCallback callback) {
  return active_tab_changed_callbacks_.Add(std::move(callback));
}

tabs::TabInterface* Browser::GetActiveTabInterface() {
  return tab_strip_model_->GetActiveTab();
}

BrowserWindowFeatures& Browser::GetFeatures() {
  CHECK(features_);
  return *features_;
}

const BrowserWindowFeatures& Browser::GetFeatures() const {
  CHECK(features_);
  return *features_;
}

web_modal::WebContentsModalDialogHost*
Browser::GetWebContentsModalDialogHostForWindow() {
  CHECK(window_);
  return window_->GetWebContentsModalDialogHost();
}

web_modal::WebContentsModalDialogHost*
Browser::GetWebContentsModalDialogHostForTab(
    tabs::TabInterface* tab_interface) {
  CHECK(window_);
  CHECK(tab_interface);
  CHECK_EQ(tab_interface, GetActiveTabInterface())
      << "Wasm Browser has no background-tab modal host";
  return window_->GetWebContentsModalDialogHostFor(
      tab_interface->GetContents());
}

bool Browser::IsActive() const {
  return is_active_;
}

base::CallbackListSubscription Browser::RegisterDidBecomeActive(
    DidBecomeActiveCallback callback) {
  return did_become_active_callbacks_.Add(std::move(callback));
}

base::CallbackListSubscription Browser::RegisterDidBecomeInactive(
    DidBecomeInactiveCallback callback) {
  return did_become_inactive_callbacks_.Add(std::move(callback));
}

BrowserActions* Browser::GetActions() {
  return GetFeatures().browser_actions();
}

std::vector<tabs::TabInterface*> Browser::GetAllTabInterfaces() {
  std::vector<tabs::TabInterface*> tabs;
  tabs.reserve(tab_strip_model_->count());
  for (int index = 0; index < tab_strip_model_->count(); ++index) {
    tabs.push_back(tab_strip_model_->GetTabAtIndex(index));
  }
  return tabs;
}

Browser* Browser::GetBrowserForMigrationOnly() {
  return this;
}

const Browser* Browser::GetBrowserForMigrationOnly() const {
  return this;
}

bool Browser::IsTabModalPopupDeprecated() const {
  return false;
}

bool Browser::CreatedBySessionRestore() const {
  return false;
}

DesktopBrowserWindowCapabilities* Browser::capabilities() {
  UnsupportedWasmBrowserOperation("desktop browser capabilities");
}

const DesktopBrowserWindowCapabilities* Browser::capabilities() const {
  UnsupportedWasmBrowserOperation("desktop browser capabilities");
}

void Browser::OnWindowActivationChanged(bool active) {
  if (is_delete_scheduled_ || is_active_ == active) {
    return;
  }

  is_active_ = active;
  if (is_active_) {
    did_become_active_callbacks_.Notify(this);
  } else {
    did_become_inactive_callbacks_.Notify(this);
  }
}

views::CloseRequestResult Browser::OnWindowCloseRequested() {
  OnWindowClosing();
  // Keep BrowserWidget client ownership alive until TabStripModel observer
  // dispatch has returned and FinishClose reaches BrowserWindowDeleter.
  return views::CloseRequestResult::kCannotClose;
}

bool Browser::CanCreateWasmUserTab() const {
  if (!window_ || !tab_strip_model_ || close_requested_ ||
      is_delete_scheduled_ || tab_strip_model_->count() >= 2) {
    return false;
  }

  tabs::TabInterface* const active_tab = tab_strip_model_->GetActiveTab();
  if (!active_tab || active_tab->IsBlocked()) {
    return false;
  }
  content::WebContents* const active_contents = active_tab->GetContents();
  if (!active_contents) {
    return false;
  }
  const web_modal::WebContentsModalDialogManager* const modal_manager =
      web_modal::WebContentsModalDialogManager::FromWebContents(
          active_contents);
  return modal_manager && !modal_manager->IsDialogActive();
}

bool Browser::CreateWasmUserTab() {
  if (!CanCreateWasmUserTab()) {
    return false;
  }

  content::WebContents::CreateParams create_params(profile_);
  std::unique_ptr<content::WebContents> contents =
      content::WebContents::Create(create_params);
  if (!contents) {
    return false;
  }

  // The bounded model owns the new blank WebContents before it notifies the
  // selected BrowserView. It is foregrounded so the visible '+' affordance
  // follows ordinary browser tab-creation expectations without widening the
  // unsupported generic TabStripModelDelegate::AddTabAt() path.
  tab_strip_model_->AppendWebContents(std::move(contents),
                                      /*foreground=*/true);
  return true;
}

bool Browser::ShowWasmSecurityWarningDialog() {
  return security_warning_dialog_ && security_warning_dialog_->Show();
}

bool Browser::CanActivateWasmUserTabAt(int index) const {
  if (!window_ || !tab_strip_model_ || close_requested_ ||
      is_delete_scheduled_ || !tab_strip_model_->ContainsIndex(index)) {
    return false;
  }

  tabs::TabInterface* const active_tab = tab_strip_model_->GetActiveTab();
  tabs::TabInterface* const requested_tab =
      tab_strip_model_->GetTabAtIndex(index);
  if (!active_tab || !requested_tab) {
    return false;
  }

  for (tabs::TabInterface* const tab : {active_tab, requested_tab}) {
    if (tab->IsBlocked()) {
      return false;
    }
    content::WebContents* const contents = tab->GetContents();
    if (!contents) {
      return false;
    }
    const web_modal::WebContentsModalDialogManager* const modal_manager =
        web_modal::WebContentsModalDialogManager::FromWebContents(contents);
    if (!modal_manager || modal_manager->IsDialogActive()) {
      return false;
    }
  }
  return true;
}

bool Browser::CanCloseWasmUserTabAt(int index) const {
  if (!window_ || !tab_strip_model_ || close_requested_ ||
      is_delete_scheduled_ || tab_strip_model_->count() <= 1 ||
      !tab_strip_model_->ContainsIndex(index)) {
    return false;
  }

  tabs::TabInterface* const tab = tab_strip_model_->GetTabAtIndex(index);
  if (!tab || tab->IsBlocked()) {
    return false;
  }

  content::WebContents* const contents = tab->GetContents();
  if (!contents || contents->NeedToFireBeforeUnloadOrUnloadEvents()) {
    return false;
  }
  const web_modal::WebContentsModalDialogManager* const modal_manager =
      web_modal::WebContentsModalDialogManager::FromWebContents(contents);
  return modal_manager && !modal_manager->IsDialogActive();
}

bool Browser::CloseWasmUserTabAt(int index) {
  if (!CanCloseWasmUserTabAt(index)) {
    return false;
  }

  const int tab_count_before_close = tab_strip_model_->count();
  base::WeakPtr<Browser> weak_browser = weak_ptr_factory_.GetWeakPtr();
  tab_strip_model_->GetTabAtIndex(index)->Close();
  return weak_browser && weak_browser->tab_strip_model_ &&
         weak_browser->tab_strip_model_->count() ==
             tab_count_before_close - 1;
}

void Browser::OnTabWillBeRemoved(tabs::TabInterface* tab, int index) {
  CHECK(window_);
  CHECK(tab_strip_model_);
  CHECK(tab);
  CHECK(tab_strip_model_->ContainsIndex(index));
  CHECK_EQ(tab, tab_strip_model_->GetTabAtIndex(index));

  const bool was_active = tab == tab_strip_model_->GetActiveTab();

  CHECK(security_warning_dialog_);
  // Close and clear this manager before the model releases the WebContents.
  // The controller owns one delegate across all tabs, so this also prevents a
  // replacement/removal path from retaining a stale raw per-tab delegate.
  security_warning_dialog_->OnTabWillBeRemoved(tab->GetContents());

  // The TabModel still owns the contents at this notification. Detach the
  // non-owning Views WebView before kRemoved observers and destruction can
  // release it. Background-tab removal deliberately leaves the currently
  // attached WebView alone.
  window_->OnTabDetached(tab->GetContents(), was_active);
}

void Browser::OnTabStripModelChanged(
    TabStripModel* tab_strip_model,
    const TabStripModelChange& change,
    const TabStripSelectionChange& selection) {
  CHECK_EQ(tab_strip_model, tab_strip_model_.get());
  CHECK(security_warning_dialog_);
  security_warning_dialog_->OnTabStripModelChanged(change);
  if (!selection.active_tab_changed()) {
    return;
  }

  CHECK(window_);
  CHECK_EQ(selection.new_contents, tab_strip_model_->GetActiveWebContents());
  if (!selection.new_contents) {
    CHECK(selection.old_contents);
  } else if (selection.old_contents) {
    CHECK_NE(selection.old_contents, selection.new_contents);
  }

  // The BrowserView attachment is always updated before BrowserWindowInterface
  // active-tab subscribers observe the selection state.
  window_->OnActiveTabChanged(selection.old_contents, selection.new_contents,
                              tab_strip_model_->active_index(),
                              selection.reason);
  NotifyActiveTabDidChange();
}

void Browser::OnTabStripEmpty() {
  CHECK(close_requested_);
  CHECK(tab_strip_model_->empty());
  PostFinishClose();
}

void Browser::PostFinishClose() {
  CHECK(close_requested_);
  CHECK(tab_strip_model_);
  CHECK(tab_strip_model_->empty());
  if (finish_close_posted_) {
    return;
  }
  finish_close_posted_ = true;
  // A TabStripModel observer can run a nested loop. Do not tear down the
  // BrowserView/BrowserWidget cycle until the outer model dispatch returns.
  // Empty-model close uses the same non-nestable turn because a platform
  // close request can itself arrive from a nested Views callback.
  CHECK(base::SingleThreadTaskRunner::GetCurrentDefault()->PostNonNestableTask(
      FROM_HERE,
      base::BindOnce(&Browser::FinishClose, weak_ptr_factory_.GetWeakPtr())));
}

void Browser::NotifyActiveTabDidChange() {
  CHECK(!is_delete_scheduled_);
  tabs::TabInterface* const active_tab = GetActiveTabInterface();
  CHECK_NE(active_tab, last_notified_active_tab_.get());
  last_notified_active_tab_ = active_tab;
  active_tab_changed_callbacks_.Notify(this);
}

void Browser::FinishClose() {
  CHECK(close_requested_);
  CHECK(finish_close_posted_);
  CHECK(tab_strip_model_->empty());
  CHECK(window_);
  CHECK(!features_torn_down_);

  // BrowserElements and animation providers retain BrowserView. Tear them
  // down before BrowserWindowDeleter breaks the BrowserWidget/View cycle.
  GetFeatures().TearDownPreBrowserWindowDestruction();
  features_torn_down_ = true;

  if (window_->IsActive()) {
    window_->Deactivate();
  }
  CHECK(!is_active_);

  window_observer_->Reset();
  window_.reset();
  CHECK(!window_);

  NotifyBrowserDidClose();
  ScheduleManagerDeletion();
}

void Browser::NotifyBrowserDidClose() {
  CHECK(!is_delete_scheduled_);
  CHECK(!window_);
  CHECK(features_torn_down_ || !features_);
  is_delete_scheduled_ = true;
  browser_did_close_callbacks_.Notify(this);
}

void Browser::ScheduleManagerDeletion() {
  CHECK(is_delete_scheduled_);
  CHECK(!window_);
  CHECK(base::SingleThreadTaskRunner::GetCurrentDefault()->PostNonNestableTask(
      FROM_HERE,
      base::BindOnce(&Browser::DeleteFromManager,
                     weak_ptr_factory_.GetWeakPtr())));
}

void Browser::DeleteFromManager() {
  CHECK(is_delete_scheduled_);
  CHECK(!window_);
  BrowserManagerService* const browser_manager =
      BrowserManagerServiceFactory::GetForProfile(profile_.get());
  CHECK(browser_manager);
  browser_manager->DeleteBrowser(this);
}
