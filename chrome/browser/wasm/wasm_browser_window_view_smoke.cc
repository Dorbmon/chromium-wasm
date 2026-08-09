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
#include "base/timer/timer.h"
#include "build/build_config.h"
#include "chrome/browser/ui/browser_manager_service.h"
#include "chrome/browser/ui/browser_manager_service_factory.h"
#include "chrome/browser/ui/browser_window/public/browser_window_features.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/browser_window/public/global_browser_collection.h"
#include "chrome/browser/ui/tabs/tab_strip_model.h"
#include "chrome/browser/ui/tabs/tab_strip_model_observer.h"
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

// This smoke-local bridge keeps the model and Views ownership independent.
// BrowserWindowInterface remains windowless, while the bridge carries the one
// selected model-owned WebContents into and out of the actual Views WebView.
class WasmBrowserWindowViewSmokeBridge final : public TabStripModelObserver {
 public:
  WasmBrowserWindowViewSmokeBridge(WasmBrowserWindowCore* core,
                                   BrowserView* browser_view)
      : core_(core), browser_view_(browser_view) {
    CHECK(core_);
    CHECK(browser_view_);
  }

  WasmBrowserWindowViewSmokeBridge(
      const WasmBrowserWindowViewSmokeBridge&) = delete;
  WasmBrowserWindowViewSmokeBridge& operator=(
      const WasmBrowserWindowViewSmokeBridge&) = delete;

  ~WasmBrowserWindowViewSmokeBridge() override { StopObserving(); }

  void StartObserving(TabStripModel* tab_strip_model) {
    CHECK(tab_strip_model);
    CHECK(!tab_strip_model_);
    tab_strip_model_ = tab_strip_model;
    tab_strip_model_->AddObserver(this);
  }

  void StopObserving() {
    if (tab_strip_model_) {
      tab_strip_model_->RemoveObserver(this);
      tab_strip_model_ = nullptr;
    }
  }

  int active_tab_change_count() const { return active_tab_change_count_; }
  bool detached_active_contents() const { return detached_active_contents_; }

 private:
  // TabStripModelObserver:
  void OnTabWillBeRemoved(tabs::TabInterface* tab, int index) override {
    CHECK(tab_strip_model_);
    CHECK(tab);
    CHECK_EQ(index, 0);
    CHECK_EQ(tab, tab_strip_model_->GetActiveTab());

    content::WebContents* const contents = tab->GetContents();
    CHECK(contents);
    CHECK_EQ(browser_view_->GetActiveWebContents(), contents);
    // The model still owns |contents|. Detach its non-owning WebView before
    // TabFeatures and then the TabModel/WebContents are destroyed.
    browser_view_->OnTabDetached(contents, /*was_active=*/true);
    CHECK(!browser_view_->GetActiveWebContents());
    detached_active_contents_ = true;
  }

  void OnTabStripModelChanged(
      TabStripModel* tab_strip_model,
      const TabStripModelChange& /*change*/,
      const TabStripSelectionChange& selection) override {
    CHECK_EQ(tab_strip_model, tab_strip_model_);
    if (!selection.active_tab_changed()) {
      return;
    }

    if (selection.new_contents) {
      CHECK(!selection.old_contents);
      CHECK_EQ(selection.new_contents,
               tab_strip_model_->GetActiveWebContents());
      // Attach the real model-owned contents before BrowserWindowInterface
      // subscribers observe the selected active tab.
      browser_view_->OnActiveTabChanged(selection.old_contents,
                                        selection.new_contents,
                                        tab_strip_model_->active_index(),
                                        selection.reason);
      CHECK_EQ(browser_view_->GetActiveWebContents(), selection.new_contents);
    } else {
      CHECK(selection.old_contents);
      CHECK(detached_active_contents_);
      CHECK(!tab_strip_model_->GetActiveWebContents());
      CHECK(!browser_view_->GetActiveWebContents());
    }

    core_->NotifyActiveTabDidChangeForWasmSmoke();
    ++active_tab_change_count_;
  }

  raw_ptr<WasmBrowserWindowCore> core_;
  raw_ptr<BrowserView> browser_view_;
  raw_ptr<TabStripModel> tab_strip_model_ = nullptr;
  int active_tab_change_count_ = 0;
  bool detached_active_contents_ = false;
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
    // BrowserView is owned by BrowserWidget's RootView after Init(). Do not put
    // it in a unique_ptr: the explicit helper below breaks that ownership cycle.
    BrowserView* browser_view = new BrowserView(/*browser=*/nullptr);
    auto browser_widget = std::make_unique<BrowserWidget>(browser_view);
    BrowserWidget* const widget = browser_widget.get();
    browser_view->set_browser_widget(std::move(browser_widget));
    widget->InitBrowserWidget();
    CHECK_EQ(browser_view->GetWidget(), widget);
    CHECK(widget->browser_native_widget());

    ActiveTabRelayState relay_state{
        .browser_view = browser_view,
    };
    base::CallbackListSubscription active_tab_subscription =
        raw_core->RegisterActiveTabDidChange(base::BindRepeating(
            &RecordActiveTabChange, base::Unretained(&relay_state)));

    {
      WasmBrowserWindowViewSmokeBridge bridge(raw_core, browser_view);
      TabStripModel* const tab_strip_model = raw_core->GetTabStripModel();
      CHECK(tab_strip_model);
      bridge.StartObserving(tab_strip_model);

      // BrowserElements and the animation controller retain this real View, so
      // their paired pre-window teardown below must precede Widget destruction.
      raw_core->GetFeatures().InitPostBrowserViewConstruction(browser_view);

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
      CHECK_EQ(bridge.active_tab_change_count(), 1);
      const web_modal::WebContentsModalDialogManager* const modal_manager =
          web_modal::WebContentsModalDialogManager::FromWebContents(
              raw_contents);
      CHECK(modal_manager);
      CHECK(!modal_manager->IsDialogActive());

      browser_view->SetBounds(kBrowserWindowViewSmokeBounds);
      widget->GetRootView()->DeprecatedLayoutImmediately();
      CHECK_EQ(browser_view->GetContentsSize(),
               kBrowserWindowViewSmokeBounds.size());
      browser_view->Show();
      CHECK(browser_view->IsVisible());

      base::RunLoop visible_run_loop;
      base::OneShotTimer visible_timer;
      visible_timer.Start(FROM_HERE, kBrowserWindowViewSmokeVisibleDuration,
                          visible_run_loop.QuitClosure());
      visible_run_loop.Run();

      tabs::TabInterface* const active_tab = raw_core->GetActiveTabInterface();
      CHECK(active_tab);
      active_tab->Close();
      CHECK(tab_strip_model->empty());
      CHECK(bridge.detached_active_contents());
      CHECK_EQ(bridge.active_tab_change_count(), 2);
      CHECK_EQ(relay_state.notification_count, 2);
      CHECK(!relay_state.last_contents);
      CHECK(!browser_view->GetActiveWebContents());

      // BrowserElementsViewsImpl and BrowserAnimationController retain the raw
      // BrowserView. Mirror BrowserWidget's intended ordering before the helper
      // destroys the view through its client-owned Widget tree.
      raw_core->GetFeatures().TearDownPreBrowserWindowDestruction();
      bridge.StopObserving();
    }

    BrowserView::DestroyForWasmBrowserViewSmoke(browser_view);
    base::RunLoop().RunUntilIdle();

    raw_core->CloseForWasmBrowserWindowCoreSmoke();
    CHECK(!weak_core || weak_core->IsDeleteScheduled());
    CHECK(browser_manager->IsEmpty());
    CHECK(global_collection->IsEmpty());
  }

  base::SingleThreadTaskRunner::GetCurrentDefault()->PostTask(
      FROM_HERE,
      base::BindOnce(
          [](BrowserManagerService* browser_manager,
             base::WeakPtr<BrowserWindowInterface> core) {
            CHECK(browser_manager);
            if (core) {
              browser_manager->DeleteBrowser(core.get());
            }
          },
          base::Unretained(browser_manager), weak_core));
  base::RunLoop().RunUntilIdle();

  CHECK(!weak_core);
  CHECK(browser_manager->IsEmpty());
  CHECK(global_collection->IsEmpty());
  std::fprintf(stderr, "%s:PASS\n", kBrowserWindowViewSmokeMarker);
  return true;
}

}  // namespace chrome
