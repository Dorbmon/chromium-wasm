// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_smoke.h"

#include <cstdio>
#include <memory>
#include <vector>

#include "base/check.h"
#include "base/functional/bind.h"
#include "base/run_loop.h"
#include "base/time/time.h"
#include "base/timer/timer.h"
#include "build/build_config.h"
#include "chrome/browser/wasm/wasm_browser.h"
#include "chrome/browser/ui/browser_manager_service.h"
#include "chrome/browser/ui/browser_manager_service_factory.h"
#include "chrome/browser/ui/browser_window/public/global_browser_collection.h"
#include "chrome/browser/ui/tabs/tab_strip_model.h"
#include "chrome/browser/ui/views/frame/browser_view.h"
#include "chrome/browser/wasm/wasm_profile.h"
#include "components/tabs/public/tab_interface.h"
#include "content/public/browser/web_contents.h"
#include "ui/gfx/geometry/rect.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_smoke.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kBrowserSmokeMarker[] = "CHROMIUM_WASM_M6_BROWSER:PASS";
constexpr char kBrowserSmokeReadyMarker[] = "CHROMIUM_WASM_M6_BROWSER:READY";
constexpr gfx::Rect kBrowserSmokeBounds(0, 0, 640, 480);
constexpr base::TimeDelta kBrowserSmokeVisibleDuration = base::Milliseconds(250);

struct BrowserSmokeState {
  BrowserWindowInterface* expected_browser = nullptr;
  std::vector<content::WebContents*> expected_active_contents;
  size_t active_tab_change_count = 0;
  bool did_close = false;
};

void OnActiveTabChanged(BrowserSmokeState* state,
                        BrowserWindowInterface* browser) {
  CHECK(state);
  CHECK(browser);
  CHECK_EQ(browser, state->expected_browser);
  CHECK_LT(state->active_tab_change_count,
           state->expected_active_contents.size());

  tabs::TabInterface* const active_tab = browser->GetActiveTabInterface();
  content::WebContents* const active_contents =
      active_tab ? active_tab->GetContents() : nullptr;
  CHECK_EQ(active_contents,
           state->expected_active_contents[state->active_tab_change_count]);
  ++state->active_tab_change_count;
}

void OnBrowserDidClose(BrowserSmokeState* state,
                       BrowserWindowInterface* browser) {
  CHECK(state);
  CHECK(browser);
  CHECK(!state->did_close);
  CHECK_EQ(browser, state->expected_browser);
  CHECK(browser->IsDeleteScheduled());
  state->did_close = true;
}

void CloseEmptyBrowserForSmoke(Profile* profile,
                               BrowserManagerService* browser_manager,
                               GlobalBrowserCollection* global_collection) {
  CHECK(profile);
  CHECK(browser_manager);
  CHECK(global_collection);
  CHECK(browser_manager->IsEmpty());
  CHECK(global_collection->IsEmpty());

  // Browser::Create deliberately exposes an empty model before a caller
  // supplies its first initial WebContents. Exercise that close edge first so
  // it cannot strand an initialized BrowserWidget/BWF graph.
  Browser::CreateParams params(profile, /*user_gesture=*/false);
  Browser* const raw_browser = Browser::Create(params);
  CHECK(raw_browser);
  base::WeakPtr<Browser> weak_browser = raw_browser->AsWeakPtr();
  raw_browser->GetWindow()->Close();
  base::RunLoop().RunUntilIdle();

  CHECK(!weak_browser);
  CHECK(browser_manager->IsEmpty());
  CHECK(global_collection->IsEmpty());
}

}  // namespace

bool RunWasmBrowserSmoke(WasmProfile* profile) {
  CHECK(profile);
  BrowserManagerService* const browser_manager =
      BrowserManagerServiceFactory::GetForProfile(profile);
  CHECK(browser_manager);
  CHECK(browser_manager->IsEmpty());

  GlobalBrowserCollection* const global_collection =
      GlobalBrowserCollection::GetInstance();
  CHECK(global_collection);
  CHECK(global_collection->IsEmpty());

  CloseEmptyBrowserForSmoke(profile, browser_manager, global_collection);

  Browser::CreateParams params(profile, /*user_gesture=*/true);
  Browser* const raw_browser = Browser::Create(params);
  CHECK(raw_browser);
  CHECK_EQ(browser_manager->GetSize(), 1u);
  CHECK_EQ(raw_browser->GetBrowserForMigrationOnly(), raw_browser);
  CHECK(raw_browser->window());
  CHECK_EQ(raw_browser->GetWindow(), raw_browser->window());

  BrowserView& browser_view = raw_browser->GetBrowserView();
  CHECK_EQ(browser_view.browser(), raw_browser);
  browser_view.SetBounds(kBrowserSmokeBounds);
  CHECK_EQ(browser_view.GetBounds(), kBrowserSmokeBounds);

  content::WebContents::CreateParams create_params(profile);
  std::unique_ptr<content::WebContents> first_contents =
      content::WebContents::Create(create_params);
  CHECK(first_contents);
  content::WebContents* const raw_first_contents = first_contents.get();
  TabStripModel* const tab_strip_model = raw_browser->tab_strip_model();
  CHECK(tab_strip_model);
  CHECK(tab_strip_model->empty());
  tab_strip_model->AppendWebContents(std::move(first_contents),
                                     /*foreground=*/true);
  CHECK_EQ(tab_strip_model->count(), 1);
  CHECK_EQ(tab_strip_model->GetActiveWebContents(), raw_first_contents);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_first_contents);
  CHECK_EQ(raw_browser->GetActiveTabInterface(),
           tab_strip_model->GetActiveTab());

  std::unique_ptr<content::WebContents> second_contents =
      content::WebContents::Create(create_params);
  CHECK(second_contents);
  content::WebContents* const raw_second_contents = second_contents.get();
  tab_strip_model->AppendWebContents(std::move(second_contents),
                                     /*foreground=*/false);
  CHECK_EQ(tab_strip_model->count(), 2);
  CHECK_EQ(tab_strip_model->GetActiveWebContents(), raw_first_contents);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_first_contents);

  browser_view.Show();
  CHECK(browser_view.IsVisible());

  // Let the real Aura/Ozone widget traverse a compositor turn before closing
  // it. The Node smoke verifies the resulting canvas copy, frame, readiness,
  // and keyboard-focus reports; merely constructing a Widget is not enough
  // evidence that this Browser-owned window is presentable.
  base::RunLoop visible_run_loop;
  base::OneShotTimer visible_timer;
  visible_timer.Start(FROM_HERE, kBrowserSmokeVisibleDuration,
                      visible_run_loop.QuitClosure());
  visible_run_loop.Run();
  std::puts(kBrowserSmokeReadyMarker);

  BrowserSmokeState state;
  state.expected_browser = raw_browser;
  base::CallbackListSubscription active_tab_subscription =
      raw_browser->RegisterActiveTabDidChange(
          base::BindRepeating(&OnActiveTabChanged, &state));
  base::CallbackListSubscription close_subscription =
      raw_browser->RegisterBrowserDidClose(
          base::BindRepeating(&OnBrowserDidClose, &state));
  base::WeakPtr<Browser> weak_browser = raw_browser->AsWeakPtr();

  // The model owns both WebContents while BrowserView owns only the selected
  // native view. Verify an explicit switch, a background close, then an
  // active close that selects and reattaches the surviving tab.
  state.expected_active_contents.push_back(raw_second_contents);
  tab_strip_model->ActivateTabAt(1);
  CHECK_EQ(tab_strip_model->GetActiveWebContents(), raw_second_contents);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_second_contents);
  CHECK_EQ(state.active_tab_change_count, 1u);

  tab_strip_model->GetTabAtIndex(0)->Close();
  CHECK_EQ(tab_strip_model->count(), 1);
  CHECK_EQ(tab_strip_model->GetActiveWebContents(), raw_second_contents);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_second_contents);
  CHECK_EQ(state.active_tab_change_count, 1u);

  std::unique_ptr<content::WebContents> third_contents =
      content::WebContents::Create(create_params);
  CHECK(third_contents);
  content::WebContents* const raw_third_contents = third_contents.get();
  tab_strip_model->AppendWebContents(std::move(third_contents),
                                     /*foreground=*/false);
  CHECK_EQ(tab_strip_model->count(), 2);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_second_contents);

  state.expected_active_contents.push_back(raw_third_contents);
  tab_strip_model->ActivateTabAt(1);
  CHECK_EQ(tab_strip_model->GetActiveWebContents(), raw_third_contents);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_third_contents);
  CHECK_EQ(state.active_tab_change_count, 2u);

  state.expected_active_contents.push_back(raw_second_contents);
  tab_strip_model->GetTabAtIndex(1)->Close();
  CHECK_EQ(tab_strip_model->count(), 1);
  CHECK_EQ(tab_strip_model->GetActiveWebContents(), raw_second_contents);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_second_contents);
  CHECK_EQ(state.active_tab_change_count, 3u);

  std::unique_ptr<content::WebContents> fourth_contents =
      content::WebContents::Create(create_params);
  CHECK(fourth_contents);
  tab_strip_model->AppendWebContents(std::move(fourth_contents),
                                     /*foreground=*/false);
  CHECK_EQ(tab_strip_model->count(), 2);
  CHECK_EQ(tab_strip_model->GetActiveWebContents(), raw_second_contents);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_second_contents);

  // Exercise both BaseWindow close requests before the model's non-nestable
  // finish task runs. BrowserView must keep the Widget alive and absorb the
  // repeated request rather than letting client-owned native destruction race
  // tab removal.
  state.expected_active_contents.push_back(nullptr);
  raw_browser->GetWindow()->Close();
  raw_browser->GetWindow()->Close();
  CHECK(weak_browser);
  CHECK(tab_strip_model->empty());
  CHECK(!raw_browser->IsDeleteScheduled());
  CHECK(!browser_view.GetActiveWebContents());
  CHECK_EQ(state.active_tab_change_count,
           state.expected_active_contents.size());

  base::RunLoop().RunUntilIdle();

  CHECK(state.did_close);
  CHECK(!weak_browser);
  CHECK(browser_manager->IsEmpty());
  CHECK(global_collection->IsEmpty());

  std::puts(kBrowserSmokeMarker);
  return true;
}

}  // namespace chrome
