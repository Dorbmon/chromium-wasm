// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_window_view_smoke.h"

#include <cstdio>
#include <memory>
#include <utility>

#include "base/check.h"
#include "base/check_op.h"
#include "base/functional/bind.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "base/run_loop.h"
#include "base/task/single_thread_task_runner.h"
#include "base/time/time.h"
#include "base/timer/timer.h"
#include "build/build_config.h"
#include "chrome/app/chrome_command_ids.h"
#include "chrome/browser/ui/browser_manager_service.h"
#include "chrome/browser/ui/browser_manager_service_factory.h"
#include "chrome/browser/ui/browser_command_controller.h"
#include "chrome/browser/ui/browser_window/public/browser_window_features.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/browser_window/public/global_browser_collection.h"
#include "chrome/browser/ui/tabs/tab_strip_model.h"
#include "chrome/browser/ui/tabs/tab_strip_model_observer.h"
#include "chrome/browser/ui/views/frame/browser_view.h"
#include "chrome/browser/wasm/wasm_browser_window_core.h"
#include "chrome/browser/wasm/wasm_browser_window_view_host.h"
#include "chrome/browser/wasm/wasm_profile.h"
#include "components/tabs/public/tab_interface.h"
#include "components/web_modal/web_contents_modal_dialog_manager.h"
#include "content/public/browser/browser_thread.h"
#include "content/public/browser/navigation_controller.h"
#include "content/public/browser/navigation_handle.h"
#include "content/public/browser/web_contents.h"
#include "content/public/browser/web_contents_observer.h"
#include "ui/display/screen.h"
#include "ui/gfx/geometry/rect.h"
#include "ui/views/layout/layout_provider.h"
#include "ui/views/views_delegate.h"
#include "ui/views/widget/widget.h"
#include "ui/views/widget/root_view.h"
#include "url/gurl.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_window_view_smoke.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kBrowserWindowViewSmokeMarker[] =
    "CHROMIUM_WASM_M6_BROWSER_WINDOW_VIEW";
constexpr gfx::Rect kBrowserWindowViewSmokeBounds(0, 0, 640, 480);
constexpr base::TimeDelta kBrowserWindowViewSmokeVisibleDuration =
    base::Milliseconds(250);
constexpr base::TimeDelta kBrowserWindowViewSmokeNavigationTimeout =
    base::Seconds(5);

// These documents have no scripts, dialog APIs, or unload handlers. They
// exercise real top-level history independently of network/WISP availability,
// then leave the existing bounded no-modal/no-unload close path intact.
constexpr char kFirstNavigationUrl[] =
    "data:text/html;base64,"
    "PCFkb2N0eXBlIGh0bWw+PHRpdGxlPndhc20tbmF2LWE8L3RpdGxlPjxib2R5Pndhc20t"
    "bmF2LWE8L2JvZHk+";
constexpr char kSecondNavigationUrl[] =
    "data:text/html;base64,"
    "PCFkb2N0eXBlIGh0bWw+PHRpdGxlPndhc20tbmF2LWI8L3RpdGxlPjxib2R5Pndhc20t"
    "bmF2LWI8L2JvZHk+";

class ActiveTabNavigationObserver final
    : public content::WebContentsObserver {
 public:
  explicit ActiveTabNavigationObserver(content::WebContents* web_contents)
      : content::WebContentsObserver(web_contents) {
    CHECK(web_contents);
  }

  ActiveTabNavigationObserver(const ActiveTabNavigationObserver&) = delete;
  ActiveTabNavigationObserver& operator=(
      const ActiveTabNavigationObserver&) = delete;
  ~ActiveTabNavigationObserver() override = default;

  void WaitForNavigation(const GURL& expected_url,
                         base::OnceClosure start_navigation) {
    CHECK(expected_url.is_valid());
    CHECK(start_navigation);
    CHECK(!waiting_for_navigation_);
    CHECK(!wait_quit_closure_);
    CHECK(web_contents());

    expected_url_ = expected_url;
    waiting_for_navigation_ = true;
    committed_primary_main_frame_ = false;
    stopped_loading_after_commit_ = false;
    timed_out_ = false;

    base::RunLoop navigation_run_loop;
    wait_quit_closure_ = navigation_run_loop.QuitClosure();
    navigation_timeout_.Start(
        FROM_HERE, kBrowserWindowViewSmokeNavigationTimeout,
        base::BindOnce(&ActiveTabNavigationObserver::OnNavigationTimeout,
                       base::Unretained(this)));
    std::move(start_navigation).Run();
    navigation_run_loop.Run();
    navigation_timeout_.Stop();

    CHECK(!timed_out_);
    CHECK(committed_primary_main_frame_);
    CHECK(stopped_loading_after_commit_);
    CHECK(web_contents());
    CHECK_EQ(web_contents()->GetLastCommittedURL(), expected_url_);

    waiting_for_navigation_ = false;
    expected_url_ = GURL();
    ++completed_navigation_count_;
  }

  int completed_navigation_count() const {
    return completed_navigation_count_;
  }

 private:
  // content::WebContentsObserver:
  void DidFinishNavigation(
      content::NavigationHandle* navigation_handle) override {
    CHECK(navigation_handle);
    if (!waiting_for_navigation_ ||
        !navigation_handle->IsInPrimaryMainFrame() ||
        !navigation_handle->HasCommitted() || navigation_handle->IsErrorPage() ||
        navigation_handle->GetURL() != expected_url_) {
      return;
    }

    CHECK(!committed_primary_main_frame_);
    CHECK(web_contents());
    CHECK_EQ(web_contents()->GetLastCommittedURL(), expected_url_);
    committed_primary_main_frame_ = true;

    // A synchronous completion may not produce a later DidStopLoading()
    // callback after this observer begins waiting. In that case, the observed
    // real WebContents state still proves the document is no longer loading.
    if (!web_contents()->IsLoading()) {
      stopped_loading_after_commit_ = true;
      FinishNavigationWait();
    }
  }

  void DidStopLoading() override {
    if (!waiting_for_navigation_ || !committed_primary_main_frame_) {
      return;
    }

    stopped_loading_after_commit_ = true;
    FinishNavigationWait();
  }

  void OnNavigationTimeout() {
    timed_out_ = true;
    FinishNavigationWait();
  }

  void FinishNavigationWait() {
    if (!wait_quit_closure_) {
      return;
    }
    std::move(wait_quit_closure_).Run();
  }

  base::OneShotTimer navigation_timeout_;
  base::OnceClosure wait_quit_closure_;
  GURL expected_url_;
  bool waiting_for_navigation_ = false;
  bool committed_primary_main_frame_ = false;
  bool stopped_loading_after_commit_ = false;
  bool timed_out_ = false;
  int completed_navigation_count_ = 0;
};

void LoadCurrentTabAndWait(ActiveTabNavigationObserver* navigation_observer,
                           content::NavigationController* navigation_controller,
                           const GURL& expected_url) {
  CHECK(navigation_observer);
  CHECK(navigation_controller);
  navigation_observer->WaitForNavigation(
      expected_url,
      base::BindOnce(
          [](content::NavigationController* navigation_controller,
             GURL target_url) {
            content::NavigationController::LoadURLParams params(target_url);
            base::WeakPtr<content::NavigationHandle> navigation_handle =
                navigation_controller->LoadURLWithParams(params);
            CHECK(navigation_handle);
          },
          base::Unretained(navigation_controller), expected_url));
}

void ExecuteCurrentTabNavigationCommandAndWait(
    ActiveTabNavigationObserver* navigation_observer,
    BrowserCommandController* command_controller,
    int command_id,
    const GURL& expected_url) {
  CHECK(navigation_observer);
  CHECK(command_controller);
  navigation_observer->WaitForNavigation(
      expected_url,
      base::BindOnce(
          [](BrowserCommandController* command_controller, int command_id) {
            CHECK(command_controller->ExecuteCommand(command_id,
                                                     base::TimeTicks::Now()));
          },
          base::Unretained(command_controller), command_id));
}

struct ActiveTabRelayState {
  raw_ptr<BrowserView> browser_view = nullptr;
  int notification_count = 0;
  raw_ptr<content::WebContents> last_contents = nullptr;
};

void RecordActiveTabChange(ActiveTabRelayState* state,
                           BrowserWindowInterface* browser) {
  CHECK(state);
  CHECK(browser);
  CHECK(state->browser_view);
  ++state->notification_count;
  tabs::TabInterface* const active_tab = browser->GetActiveTabInterface();
  state->last_contents = active_tab ? active_tab->GetContents() : nullptr;
  CHECK_EQ(state->browser_view->GetActiveWebContents(),
           state->last_contents);
}

struct ActivationState {
  int did_become_active = 0;
  int did_become_inactive = 0;
};

void RecordDidBecomeActive(ActivationState* state,
                           BrowserWindowInterface* browser) {
  CHECK(state);
  CHECK(browser);
  CHECK(browser->IsActive());
  ++state->did_become_active;
}

void RecordDidBecomeInactive(ActivationState* state,
                             BrowserWindowInterface* browser) {
  CHECK(state);
  CHECK(browser);
  CHECK(!browser->IsActive());
  ++state->did_become_inactive;
}

struct NestedTabStripEmptyState {
  raw_ptr<WasmBrowserWindowCore> core;
  raw_ptr<BrowserView> browser_view;
  bool nested_run_loop_completed = false;
};

// Proves that the Core's TabStripEmpty teardown task is non-nestable. This
// observer runs after the Core's own observer has posted FinishClose().
class NestedTabStripEmptyObserver final : public TabStripModelObserver {
 public:
  explicit NestedTabStripEmptyObserver(NestedTabStripEmptyState* state)
      : state_(state) {
    CHECK(state_);
  }

  NestedTabStripEmptyObserver(const NestedTabStripEmptyObserver&) = delete;
  NestedTabStripEmptyObserver& operator=(
      const NestedTabStripEmptyObserver&) = delete;
  ~NestedTabStripEmptyObserver() override = default;

 private:
  // TabStripModelObserver:
  void TabStripEmpty() override {
    CHECK(state_->core);
    CHECK(state_->browser_view);
    base::RunLoop nested_run_loop(
        base::RunLoop::Type::kNestableTasksAllowed);
    nested_run_loop.RunUntilIdle();

    // FinishClose must remain queued until the outer tab-model close task
    // returns. Destroying this Widget during observer dispatch would invalidate
    // the View/model ownership boundary that is still on the stack.
    CHECK_EQ(state_->core->GetWindow(), state_->browser_view);
    CHECK(state_->browser_view->GetWidget());
    CHECK(!state_->core->IsDeleteScheduled());
    state_->nested_run_loop_completed = true;
  }

  const raw_ptr<NestedTabStripEmptyState> state_;
};

void CheckSelectedTabRemainsBound(
    WasmBrowserWindowCore* core,
    BrowserView* browser_view,
    const WasmBrowserWindowViewHost* view_host,
    const ActiveTabRelayState* relay_state,
    const web_modal::WebContentsModalDialogManager* modal_manager,
    content::WebContents* expected_contents) {
  CHECK(core);
  CHECK(browser_view);
  CHECK(view_host);
  CHECK(relay_state);
  CHECK(modal_manager);
  CHECK(expected_contents);

  TabStripModel* const tab_strip_model = core->GetTabStripModel();
  CHECK(tab_strip_model);
  CHECK_EQ(tab_strip_model->count(), 1);
  CHECK_EQ(tab_strip_model->GetActiveWebContents(), expected_contents);
  tabs::TabInterface* const active_tab = core->GetActiveTabInterface();
  CHECK(active_tab);
  CHECK_EQ(active_tab->GetContents(), expected_contents);
  CHECK_EQ(core->GetWindow(), browser_view);
  CHECK(browser_view->GetWidget());
  CHECK_EQ(browser_view->GetActiveWebContents(), expected_contents);
  CHECK_EQ(view_host->active_tab_change_count_for_testing(), 1);
  CHECK_EQ(relay_state->notification_count, 1);
  CHECK_EQ(relay_state->last_contents, expected_contents);
  CHECK(!modal_manager->IsDialogActive());
  CHECK(!tab_strip_model->IsTabBlocked(0));
}

struct BoundCoreCloseTaskState {
  raw_ptr<WasmBrowserWindowCore> core;
  raw_ptr<BrowserView> browser_view;
  raw_ptr<WasmBrowserWindowViewHost> view_host;
  raw_ptr<TabStripModel> tab_strip_model;
  raw_ptr<ActiveTabRelayState> relay_state;
  raw_ptr<NestedTabStripEmptyState> nested_tab_strip_empty_state;
  raw_ptr<NestedTabStripEmptyObserver> nested_tab_strip_empty_observer;
  raw_ptr<BrowserManagerService> browser_manager;
  raw_ptr<GlobalBrowserCollection> global_collection;
  raw_ptr<base::RunLoop> outer_run_loop;
  bool close_task_completed = false;
};

void RequestBoundCoreClose(BoundCoreCloseTaskState* state) {
  CHECK(state);
  CHECK(state->core);
  CHECK(state->browser_view);
  CHECK(state->view_host);
  CHECK(state->tab_strip_model);
  CHECK(state->relay_state);
  CHECK(state->nested_tab_strip_empty_state);
  CHECK(state->nested_tab_strip_empty_observer);
  CHECK(state->browser_manager);
  CHECK(state->global_collection);
  CHECK(state->outer_run_loop);

  // Exercise direct BaseWindow close, the Widget's host-close route, and a
  // repeated direct request while the one-tab teardown is pending. Every entry
  // point must reject native destruction until FinishClose runs in the outer
  // UI turn.
  state->core->GetWindow()->Close();
  state->browser_view->GetWidget()->Close();
  state->core->GetWindow()->Close();
  CHECK_EQ(state->core->GetWindow(), state->browser_view);
  CHECK(state->browser_view->GetWidget());
  CHECK(!state->core->IsDeleteScheduled());
  CHECK_EQ(state->view_host->close_request_count_for_testing(), 3);
  CHECK(state->tab_strip_model->empty());
  CHECK(state->view_host->detached_active_contents_for_testing());
  CHECK_EQ(state->view_host->active_tab_change_count_for_testing(), 2);
  CHECK_EQ(state->relay_state->notification_count, 2);
  CHECK(!state->relay_state->last_contents);
  CHECK(!state->browser_view->GetActiveWebContents());
  CHECK(state->nested_tab_strip_empty_state->nested_run_loop_completed);

  // FinishClose is intentionally posted non-nestably. Until that outer close
  // dispatch completes, the registered Core remains visible rather than
  // reporting a premature manager/global removal.
  CHECK_EQ(state->browser_manager->GetSize(), 1u);
  CHECK_EQ(state->global_collection->GetSize(), 1u);

  // The observer has already verified the nested-loop boundary. Remove it
  // while the model is still alive; the outer task will subsequently destroy
  // the Core and its TabStripModel.
  state->tab_strip_model->RemoveObserver(
      state->nested_tab_strip_empty_observer);
  state->close_task_completed = true;
  state->outer_run_loop->QuitWhenIdle();
}

}  // namespace

bool RunWasmBrowserWindowViewSmoke(WasmProfile* profile) {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(profile);
  CHECK(views::ViewsDelegate::GetInstance());
  CHECK(views::LayoutProvider::Get());
  CHECK(display::Screen::HasScreen());

  BrowserManagerService* const browser_manager =
      BrowserManagerServiceFactory::GetForProfile(profile);
  CHECK(browser_manager);
  CHECK(browser_manager->IsEmpty());

  GlobalBrowserCollection* const global_collection =
      GlobalBrowserCollection::GetInstance();
  CHECK(global_collection);
  CHECK(global_collection->IsEmpty());

  auto core = std::make_unique<WasmBrowserWindowCore>(profile);
  WasmBrowserWindowCore* const raw_core = core.get();
  browser_manager->AddBrowser(std::move(core));
  CHECK_EQ(browser_manager->GetSize(), 1u);
  CHECK_EQ(global_collection->GetSize(), 1u);
  CHECK(!global_collection->GetActiveBrowser());
  // Keep this before the did-close event: a collection observer may
  // synchronously request manager deletion, which removes logical ownership
  // while the Core stays alive through the deferred destruction turn.
  base::WeakPtr<BrowserWindowInterface> weak_core = raw_core->GetWeakPtr();

  {
    WasmBrowserWindowViewHost view_host(raw_core);
    view_host.Initialize();
    BrowserView* const browser_view = view_host.browser_view();
    CHECK_EQ(raw_core->GetWindow(), browser_view);

    ActiveTabRelayState relay_state{
        .browser_view = browser_view,
    };
    base::CallbackListSubscription active_tab_subscription =
        raw_core->RegisterActiveTabDidChange(base::BindRepeating(
            &RecordActiveTabChange, base::Unretained(&relay_state)));
    ActivationState activation_state;
    base::CallbackListSubscription did_become_active_subscription =
        raw_core->RegisterDidBecomeActive(base::BindRepeating(
            &RecordDidBecomeActive, base::Unretained(&activation_state)));
    base::CallbackListSubscription did_become_inactive_subscription =
        raw_core->RegisterDidBecomeInactive(base::BindRepeating(
            &RecordDidBecomeInactive, base::Unretained(&activation_state)));
    TabStripModel* const tab_strip_model = raw_core->GetTabStripModel();
    CHECK(tab_strip_model);

    content::WebContents::CreateParams create_params(profile);
    std::unique_ptr<content::WebContents> contents =
        content::WebContents::Create(create_params);
    CHECK(contents);
    content::WebContents* const raw_contents = contents.get();
    tab_strip_model->AppendWebContents(std::move(contents),
                                       /*foreground=*/true);

    CHECK_EQ(tab_strip_model->count(), 1);
    CHECK_EQ(tab_strip_model->GetActiveWebContents(), raw_contents);
    CHECK_EQ(browser_view->GetActiveWebContents(), raw_contents);
    CHECK_EQ(relay_state.notification_count, 1);
    CHECK_EQ(relay_state.last_contents, raw_contents);
    CHECK_EQ(view_host.active_tab_change_count_for_testing(), 1);
    const web_modal::WebContentsModalDialogManager* const modal_manager =
        web_modal::WebContentsModalDialogManager::FromWebContents(
            raw_contents);
    CHECK(modal_manager);
    CHECK(!modal_manager->IsDialogActive());

    browser_view->SetBounds(kBrowserWindowViewSmokeBounds);
    browser_view->GetWidget()->GetRootView()->DeprecatedLayoutImmediately();
    CHECK_EQ(browser_view->GetContentsSize(),
             kBrowserWindowViewSmokeBounds.size());
    browser_view->Show();
    CHECK(browser_view->IsVisible());

    base::RunLoop visible_run_loop;
    base::OneShotTimer visible_timer;
    visible_timer.Start(FROM_HERE, kBrowserWindowViewSmokeVisibleDuration,
                        visible_run_loop.QuitClosure());
    visible_run_loop.Run();
    CHECK(raw_core->IsActive());
    CHECK_EQ(global_collection->GetActiveBrowser(), raw_core);
    CHECK_GE(activation_state.did_become_active, 1);

    // Exercise exactly one selected model tab through the real command
    // controller that BrowserWindowFeatures owns. This is intentionally a
    // direct active-contents smoke, not a general PageNavigator, popup, or
    // browser-window navigation implementation.
    const GURL first_navigation_url(kFirstNavigationUrl);
    const GURL second_navigation_url(kSecondNavigationUrl);
    CHECK(first_navigation_url.is_valid());
    CHECK(second_navigation_url.is_valid());
    content::NavigationController& navigation_controller =
        raw_contents->GetController();
    BrowserCommandController* const command_controller =
        raw_core->GetFeatures().browser_command_controller();
    CHECK(command_controller);
    CHECK(!command_controller->IsCommandEnabled(IDC_BACK));
    CHECK(!command_controller->IsCommandEnabled(IDC_FORWARD));
    CHECK(command_controller->IsCommandEnabled(IDC_RELOAD));
    CHECK(command_controller->IsCommandEnabled(IDC_RELOAD_BYPASSING_CACHE));
    CHECK(!command_controller->IsCommandEnabled(IDC_STOP));

    ActiveTabNavigationObserver navigation_observer(raw_contents);
    LoadCurrentTabAndWait(&navigation_observer, &navigation_controller,
                          first_navigation_url);
    CheckSelectedTabRemainsBound(raw_core, browser_view, &view_host,
                                 &relay_state, modal_manager, raw_contents);

    LoadCurrentTabAndWait(&navigation_observer, &navigation_controller,
                          second_navigation_url);
    CheckSelectedTabRemainsBound(raw_core, browser_view, &view_host,
                                 &relay_state, modal_manager, raw_contents);
    CHECK(navigation_controller.CanGoBack());
    CHECK(!navigation_controller.CanGoForward());
    CHECK(command_controller->IsCommandEnabled(IDC_BACK));
    CHECK(!command_controller->IsCommandEnabled(IDC_FORWARD));
    CHECK(command_controller->IsCommandEnabled(IDC_RELOAD));
    CHECK(command_controller->IsCommandEnabled(IDC_RELOAD_BYPASSING_CACHE));
    CHECK(!command_controller->IsCommandEnabled(IDC_STOP));

    ExecuteCurrentTabNavigationCommandAndWait(
        &navigation_observer, command_controller, IDC_BACK,
        first_navigation_url);
    CheckSelectedTabRemainsBound(raw_core, browser_view, &view_host,
                                 &relay_state, modal_manager, raw_contents);
    CHECK(navigation_controller.CanGoForward());
    CHECK(command_controller->IsCommandEnabled(IDC_FORWARD));
    CHECK(command_controller->IsCommandEnabled(IDC_RELOAD));
    CHECK(!command_controller->IsCommandEnabled(IDC_STOP));

    ExecuteCurrentTabNavigationCommandAndWait(
        &navigation_observer, command_controller, IDC_FORWARD,
        second_navigation_url);
    CheckSelectedTabRemainsBound(raw_core, browser_view, &view_host,
                                 &relay_state, modal_manager, raw_contents);
    CHECK(!navigation_controller.CanGoForward());
    CHECK(!command_controller->IsCommandEnabled(IDC_FORWARD));
    CHECK(command_controller->IsCommandEnabled(IDC_RELOAD));
    CHECK(!command_controller->IsCommandEnabled(IDC_STOP));

    const int history_entry_count = navigation_controller.GetEntryCount();
    const int history_entry_index = navigation_controller.GetCurrentEntryIndex();
    ExecuteCurrentTabNavigationCommandAndWait(
        &navigation_observer, command_controller, IDC_RELOAD,
        second_navigation_url);
    CheckSelectedTabRemainsBound(raw_core, browser_view, &view_host,
                                 &relay_state, modal_manager, raw_contents);
    CHECK_EQ(navigation_controller.GetEntryCount(), history_entry_count);
    CHECK_EQ(navigation_controller.GetCurrentEntryIndex(), history_entry_index);
    CHECK_EQ(navigation_observer.completed_navigation_count(), 5);
    CHECK(command_controller->IsCommandEnabled(IDC_RELOAD));
    CHECK(!command_controller->IsCommandEnabled(IDC_STOP));

    NestedTabStripEmptyState nested_tab_strip_empty_state{
        .core = raw_core,
        .browser_view = browser_view,
    };
    NestedTabStripEmptyObserver nested_tab_strip_empty_observer(
        &nested_tab_strip_empty_state);
    tab_strip_model->AddObserver(&nested_tab_strip_empty_observer);

    // PreMainMessageLoopRun() itself is not inside the BrowserMainLoop's
    // RunLoop. Start the close from a posted outer task so the observer's
    // nested run loop genuinely verifies the non-nestable FinishClose turn.
    base::RunLoop close_outer_run_loop;
    BoundCoreCloseTaskState close_task_state{
        .core = raw_core,
        .browser_view = browser_view,
        .view_host = &view_host,
        .tab_strip_model = tab_strip_model,
        .relay_state = &relay_state,
        .nested_tab_strip_empty_state = &nested_tab_strip_empty_state,
        .nested_tab_strip_empty_observer = &nested_tab_strip_empty_observer,
        .browser_manager = browser_manager,
        .global_collection = global_collection,
        .outer_run_loop = &close_outer_run_loop,
    };
    CHECK(base::SingleThreadTaskRunner::GetCurrentDefault()->PostTask(
        FROM_HERE,
        base::BindOnce(&RequestBoundCoreClose, &close_task_state)));
    close_outer_run_loop.Run();
    CHECK(close_task_state.close_task_completed);
    CHECK(nested_tab_strip_empty_state.nested_run_loop_completed);
    base::RunLoop().RunUntilIdle();
    CHECK_GE(activation_state.did_become_inactive, 1);
    CHECK(!weak_core);
    CHECK(browser_manager->IsEmpty());
    CHECK(global_collection->IsEmpty());
  }
  std::fprintf(stderr, "%s:PASS\n", kBrowserWindowViewSmokeMarker);
  return true;
}

}  // namespace chrome
