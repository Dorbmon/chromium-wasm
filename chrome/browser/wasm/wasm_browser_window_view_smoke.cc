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
#include "base/scoped_observation.h"
#include "base/task/single_thread_task_runner.h"
#include "base/timer/timer.h"
#include "build/build_config.h"
#include "chrome/browser/ui/browser_manager_service.h"
#include "chrome/browser/ui/browser_manager_service_factory.h"
#include "chrome/browser/ui/browser_window/public/browser_window_features.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/browser_window/public/global_browser_collection.h"
#include "chrome/browser/ui/tabs/tab_strip_model.h"
#include "chrome/browser/ui/views/frame/browser_view.h"
#include "chrome/browser/ui/views/frame/browser_widget.h"
#include "chrome/browser/wasm/wasm_browser_window_core.h"
#include "chrome/browser/wasm/wasm_profile.h"
#include "components/tabs/public/tab_interface.h"
#include "components/web_modal/web_contents_modal_dialog_manager.h"
#include "content/public/browser/browser_thread.h"
#include "content/public/browser/web_contents.h"
#include "ui/display/screen.h"
#include "ui/gfx/geometry/rect.h"
#include "ui/views/layout/layout_provider.h"
#include "ui/views/views_delegate.h"
#include "ui/views/widget/widget.h"
#include "ui/views/widget/widget_observer.h"
#include "ui/views/widget/root_view.h"

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

struct DeferredDeletionState {
  raw_ptr<BrowserManagerService> browser_manager = nullptr;
  bool delete_requested = false;
};

void RequestDeferredBrowserDeletion(DeferredDeletionState* state,
                                    BrowserWindowInterface* browser) {
  CHECK(state);
  CHECK(state->browser_manager);
  CHECK(browser);
  CHECK(browser->IsDeleteScheduled());

  // This runs during BrowserWindowInterface did-close dispatch. The Wasm
  // manager must remove logical ownership now but defer physical destruction
  // until all subscribers, including this one, have returned.
  state->browser_manager->DeleteBrowser(browser);
  state->delete_requested = true;
}

// The core owns the tab-model observer and BrowserWindowInterface relay. This
// adapter owns only the structural Views objects and converts those relay
// callbacks into BrowserView attachment, detachment, activation, and the
// client-owned Widget destruction protocol.
class WasmBrowserWindowViewSmokeAdapter final : public views::WidgetObserver {
 public:
  explicit WasmBrowserWindowViewSmokeAdapter(WasmBrowserWindowCore* core)
      : core_(core ? core->GetWeakPtrForWasmBrowserWindowViewSmoke()
                   : base::WeakPtr<WasmBrowserWindowCore>()) {
    CHECK(core_);
  }

  WasmBrowserWindowViewSmokeAdapter(
      const WasmBrowserWindowViewSmokeAdapter&) = delete;
  WasmBrowserWindowViewSmokeAdapter& operator=(
      const WasmBrowserWindowViewSmokeAdapter&) = delete;

  ~WasmBrowserWindowViewSmokeAdapter() override {
    widget_observation_.Reset();
    CHECK(!browser_view_);
    CHECK(!core_ || !core_->GetWindow());
  }

  void Initialize() {
    CHECK(core_);
    CHECK(!browser_view_);

    // BrowserView is owned by BrowserWidget's RootView after Init(). Do not put
    // it in a unique_ptr: Destroy() below breaks that ownership cycle.
    BrowserView* const browser_view = new BrowserView(/*browser=*/nullptr);
    auto browser_widget = std::make_unique<BrowserWidget>(browser_view);
    BrowserWidget* const widget = browser_widget.get();
    browser_view->set_browser_widget(std::move(browser_widget));
    widget->InitBrowserWidget();
    CHECK_EQ(browser_view->GetWidget(), widget);
    CHECK(widget->browser_native_widget());

    browser_view_ = browser_view;
    widget_ = widget;
    widget_observation_.Observe(widget);

    browser_view->SetWasmCloseRequestCallbackForSmoke(base::BindRepeating(
        &WasmBrowserWindowViewSmokeAdapter::OnCloseRequested,
        base::Unretained(this)));

    core_->BindWindowForWasmBrowserWindowViewSmoke(
        browser_view_,
        base::BindRepeating(
            &WasmBrowserWindowViewSmokeAdapter::OnActiveContentsChanged,
            base::Unretained(this)),
        base::BindRepeating(
            &WasmBrowserWindowViewSmokeAdapter::OnContentsDetached,
            base::Unretained(this)),
        base::BindOnce(&WasmBrowserWindowViewSmokeAdapter::Destroy,
                       base::Unretained(this)));
    core_->InitPostBrowserViewConstructionForWasmBrowserWindowViewSmoke(
        browser_view_);
  }

  BrowserView* browser_view() const {
    CHECK(browser_view_);
    return browser_view_;
  }

  int active_tab_change_count() const { return active_tab_change_count_; }
  bool detached_active_contents() const { return detached_active_contents_; }

 private:
  void OnActiveContentsChanged(content::WebContents* old_contents,
                               content::WebContents* new_contents,
                               int active_index,
                               int reason) {
    CHECK(browser_view_);
    if (new_contents) {
      CHECK(!old_contents);
      browser_view_->OnActiveTabChanged(old_contents, new_contents,
                                        active_index, reason);
      CHECK_EQ(browser_view_->GetActiveWebContents(), new_contents);
    } else {
      CHECK(old_contents);
      // The core calls OnContentsDetached() during OnTabWillBeRemoved(), while
      // the model still owns the tab. A null active event must never leave the
      // non-owning WebView attached to the removed contents.
      CHECK(detached_active_contents_);
      CHECK(!browser_view_->GetActiveWebContents());
    }
    ++active_tab_change_count_;
  }

  void OnContentsDetached(content::WebContents* contents, bool was_active) {
    CHECK(browser_view_);
    CHECK(contents);
    CHECK(was_active);
    CHECK_EQ(browser_view_->GetActiveWebContents(), contents);
    browser_view_->OnTabDetached(contents, was_active);
    CHECK(!browser_view_->GetActiveWebContents());
    detached_active_contents_ = true;
  }

  views::CloseRequestResult OnCloseRequested() {
    CHECK(core_);
    if (!close_requested_) {
      close_requested_ = true;
      core_->RequestCloseForWasmBrowserWindowViewSmoke();
    }
    // Keep the client-owned Widget alive while the Core posts its ordered
    // BrowserWindowFeatures/View teardown. Repeated close requests during
    // that turn are intentionally rejected rather than re-entering the model.
    return views::CloseRequestResult::kCannotClose;
  }

  void Destroy() {
    CHECK(core_);
    CHECK(browser_view_);
    CHECK(widget_);
    CHECK(close_requested_);
    CHECK(!browser_view_->GetActiveWebContents());

    // Keep BrowserWindowFeatures teardown in the core before this callback.
    // Deactivate the real Ozone/Views window before publishing the inactive
    // BrowserWindowInterface state, so global active-window queries cannot
    // observe contradictory BaseWindow and BWI activation states.
    if (browser_view_->IsActive()) {
      browser_view_->Deactivate();
    }
    CHECK(!core_->IsActive());

    // Clear the BaseWindow relation before resetting the client-owned Widget;
    // global collection queries then see the honest no-window state.
    core_->UnbindWindowForWasmBrowserWindowViewSmoke(browser_view_);
    widget_observation_.Reset();
    BrowserView::DestroyForWasmBrowserViewSmoke(browser_view_);
    browser_view_ = nullptr;
    widget_ = nullptr;
  }

  // views::WidgetObserver:
  void OnWidgetActivationChanged(views::Widget* widget, bool active) override {
    CHECK_EQ(widget, widget_);
    CHECK(core_);
    core_->OnWindowActivationChangedForWasmBrowserWindowViewSmoke(
        browser_view_, active);
  }

  void OnWidgetDestroying(views::Widget* widget) override {
    CHECK_EQ(widget, widget_);
    // BrowserView observes this event first and clears its WebView. A native
    // teardown with a live model would therefore be unable to perform the
    // required detach/BWF ordering. It remains an explicit unsupported path.
    CHECK(false) << "Wasm BrowserWindow view smoke requires its controlled "
                    "no-unload close lifecycle";
  }

  void OnWidgetDestroyed(views::Widget* widget) override {
    CHECK_EQ(widget, widget_);
    CHECK(false) << "Wasm BrowserWindow view smoke native teardown escaped "
                    "its controlled lifecycle";
  }

  base::WeakPtr<WasmBrowserWindowCore> core_;
  raw_ptr<BrowserView> browser_view_;
  raw_ptr<BrowserWidget> widget_ = nullptr;
  base::ScopedObservation<views::Widget, views::WidgetObserver>
      widget_observation_{this};
  int active_tab_change_count_ = 0;
  bool detached_active_contents_ = false;
  bool close_requested_ = false;
};

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
  // synchronously delete the core while it is notifying close subscribers.
  base::WeakPtr<BrowserWindowInterface> weak_core = raw_core->GetWeakPtr();

  {
    WasmBrowserWindowViewSmokeAdapter adapter(raw_core);
    adapter.Initialize();
    BrowserView* const browser_view = adapter.browser_view();
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
    DeferredDeletionState deferred_deletion_state{
        .browser_manager = browser_manager,
    };
    base::CallbackListSubscription close_deletion_subscription =
        raw_core->RegisterBrowserDidClose(base::BindRepeating(
            &RequestDeferredBrowserDeletion,
            base::Unretained(&deferred_deletion_state)));

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
    CHECK_EQ(adapter.active_tab_change_count(), 1);
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

    // The real BrowserWindowInterface now exposes the real BrowserView
    // BaseWindow. Both direct close requests are rejected while one bounded
    // no-unload model close posts its ordered teardown.
    raw_core->GetWindow()->Close();
    raw_core->GetWindow()->Close();
    CHECK_EQ(raw_core->GetWindow(), browser_view);
    CHECK(browser_view->GetWidget());
    CHECK(!raw_core->IsDeleteScheduled());
    CHECK(tab_strip_model->empty());
    CHECK(adapter.detached_active_contents());
    CHECK_EQ(adapter.active_tab_change_count(), 2);
    CHECK_EQ(relay_state.notification_count, 2);
    CHECK(!relay_state.last_contents);
    CHECK(!browser_view->GetActiveWebContents());
    base::RunLoop().RunUntilIdle();
    CHECK_GE(activation_state.did_become_inactive, 1);
    CHECK(deferred_deletion_state.delete_requested);
    CHECK(!weak_core);
    CHECK(browser_manager->IsEmpty());
    CHECK(global_collection->IsEmpty());
  }
  std::fprintf(stderr, "%s:PASS\n", kBrowserWindowViewSmokeMarker);
  return true;
}

}  // namespace chrome
