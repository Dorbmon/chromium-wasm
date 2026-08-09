// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_window_core_smoke.h"

#include <cstdio>
#include <memory>

#include "base/check.h"
#include "base/functional/bind.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "base/run_loop.h"
#include "base/task/single_thread_task_runner.h"
#include "build/build_config.h"
#include "chrome/browser/ui/browser_manager_service.h"
#include "chrome/browser/ui/browser_manager_service_factory.h"
#include "chrome/browser/ui/browser_window/public/browser_window_features.h"
#include "chrome/browser/ui/browser_window/public/global_browser_collection.h"
#include "chrome/browser/ui/tabs/tab_strip_model.h"
#include "chrome/browser/wasm/wasm_browser_window_core.h"
#include "chrome/browser/wasm/wasm_profile.h"
#include "content/public/browser/browser_thread.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_window_core_smoke.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kBrowserWindowCoreSmokeMarker[] =
    "CHROMIUM_WASM_M6_BROWSER_WINDOW_CORE:PASS";

struct BrowserWindowCoreCloseState {
  raw_ptr<BrowserManagerService> browser_manager;
  raw_ptr<GlobalBrowserCollection> global_collection;
  bool did_close = false;
};

void OnBrowserWindowCoreClosed(BrowserWindowCoreCloseState* state,
                               BrowserWindowInterface* browser) {
  CHECK(state);
  CHECK(browser);
  CHECK(browser->IsDeleteScheduled());
  CHECK(state->browser_manager->IsEmpty());
  CHECK(state->global_collection->IsEmpty());
  state->did_close = true;
}

}  // namespace

bool RunWasmBrowserWindowCoreSmoke(WasmProfile* profile) {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(profile);

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
  CHECK(raw_core->GetSessionID().is_valid());
  CHECK(raw_core->GetTabStripModel());
  CHECK(raw_core->GetTabStripModel()->empty());
  CHECK(!raw_core->GetActiveTabInterface());
  CHECK(raw_core->GetActions());
  CHECK(raw_core->GetFeatures().browser_command_controller());

  browser_manager->AddBrowser(std::move(core));
  CHECK_EQ(browser_manager->GetSize(), 1u);
  CHECK_EQ(global_collection->GetSize(), 1u);
  // This verifies that a real pre-widget BrowserWindowInterface remains
  // invisible to the global active-window query instead of needing a fake
  // BaseWindow solely to satisfy collection bookkeeping.
  CHECK(!global_collection->GetActiveBrowser());

  BrowserWindowCoreCloseState close_state{
      .browser_manager = browser_manager,
      .global_collection = global_collection,
  };
  base::CallbackListSubscription close_subscription =
      raw_core->RegisterBrowserDidClose(base::BindRepeating(
          &OnBrowserWindowCoreClosed, base::Unretained(&close_state)));

  // A collection observer may elect to delete the core from its did-close
  // callback. Retain only a weak reference across that notification.
  base::WeakPtr<BrowserWindowInterface> weak_core = raw_core->GetWeakPtr();
  raw_core->CloseForWasmBrowserWindowCoreSmoke();
  CHECK(close_state.did_close);
  CHECK(!weak_core || weak_core->IsDeleteScheduled());
  CHECK(browser_manager->IsEmpty());
  CHECK(global_collection->IsEmpty());

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
  std::puts(kBrowserWindowCoreSmokeMarker);
  std::fflush(stdout);
  return true;
}

}  // namespace chrome
