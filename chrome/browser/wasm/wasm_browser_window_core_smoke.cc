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

struct ReentrantBrowserWindowCoreDeletionState {
  raw_ptr<BrowserManagerService> browser_manager;
  raw_ptr<GlobalBrowserCollection> global_collection;
  base::WeakPtr<BrowserWindowInterface> weak_core;
  bool delete_requested = false;
  bool nested_run_loop_completed = false;
};

void RequestReentrantBrowserWindowCoreDeletion(
    ReentrantBrowserWindowCoreDeletionState* state,
    BrowserWindowInterface* browser) {
  CHECK(state);
  CHECK(state->browser_manager);
  CHECK(browser);
  CHECK(browser->IsDeleteScheduled());

  // This deliberately requests deletion during did-close dispatch. The
  // manager must keep the full BrowserAndSubscriptions entry alive until all
  // callback-list subscribers return, while Core's own deferred request below
  // becomes an idempotent no-op.
  state->browser_manager->DeleteBrowser(browser);
  state->delete_requested = true;

  // The manager's destruction task must not run while this callback has a
  // nested UI loop active. A non-nestable turn keeps the callback list and
  // the core alive until the outer did-close dispatch returns.
  base::RunLoop nested_run_loop(
      base::RunLoop::Type::kNestableTasksAllowed);
  nested_run_loop.RunUntilIdle();
  CHECK(state->weak_core);
  CHECK(state->browser_manager->IsEmpty());
  CHECK(state->global_collection->IsEmpty());
  state->nested_run_loop_completed = true;
}

void CloseReentrantBrowserWindowCore(
    WasmBrowserWindowCore* core,
    ReentrantBrowserWindowCoreDeletionState* state,
    base::RunLoop* outer_run_loop) {
  CHECK(core);
  CHECK(state);
  CHECK(outer_run_loop);
  core->CloseForWasmBrowserWindowCoreSmoke();
  CHECK(state->delete_requested);
  CHECK(state->nested_run_loop_completed);
  outer_run_loop->QuitWhenIdle();
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

  // Core itself schedules manager deletion only after all did-close
  // subscribers return. Retain a weak reference across that turn and prove
  // that physical destruction occurs only after the task queue drains.
  base::WeakPtr<BrowserWindowInterface> weak_core = raw_core->GetWeakPtr();
  raw_core->CloseForWasmBrowserWindowCoreSmoke();
  CHECK(close_state.did_close);
  CHECK(weak_core);
  CHECK(weak_core->IsDeleteScheduled());
  CHECK(browser_manager->IsEmpty());
  CHECK(global_collection->IsEmpty());
  base::RunLoop().RunUntilIdle();

  CHECK(!weak_core);
  CHECK(browser_manager->IsEmpty());
  CHECK(global_collection->IsEmpty());

  // Exercise an independent direct manager deletion request from a did-close
  // subscriber. It must not destroy the core or its callback list before this
  // notification returns; after the queue drains it shares the same terminal
  // ownership result as the normal Core-owned path.
  auto reentrant_core = std::make_unique<WasmBrowserWindowCore>(profile);
  WasmBrowserWindowCore* const raw_reentrant_core = reentrant_core.get();
  browser_manager->AddBrowser(std::move(reentrant_core));
  CHECK_EQ(browser_manager->GetSize(), 1u);
  CHECK_EQ(global_collection->GetSize(), 1u);
  ReentrantBrowserWindowCoreDeletionState reentrant_deletion_state{
      .browser_manager = browser_manager,
      .global_collection = global_collection,
  };
  base::CallbackListSubscription reentrant_deletion_subscription =
      raw_reentrant_core->RegisterBrowserDidClose(base::BindRepeating(
          &RequestReentrantBrowserWindowCoreDeletion,
          base::Unretained(&reentrant_deletion_state)));
  base::WeakPtr<BrowserWindowInterface> weak_reentrant_core =
      raw_reentrant_core->GetWeakPtr();
  reentrant_deletion_state.weak_core = weak_reentrant_core;
  // PreMainMessageLoopRun() itself is not inside the BrowserMainLoop RunLoop.
  // Start this close from a posted outer task so the subscriber's RunUntilIdle
  // below is genuinely nested and cannot execute non-nestable destruction.
  base::RunLoop reentrant_outer_run_loop;
  CHECK(base::SingleThreadTaskRunner::GetCurrentDefault()->PostTask(
      FROM_HERE,
      base::BindOnce(&CloseReentrantBrowserWindowCore, raw_reentrant_core,
                     &reentrant_deletion_state, &reentrant_outer_run_loop)));
  reentrant_outer_run_loop.Run();
  CHECK(reentrant_deletion_state.delete_requested);
  CHECK(reentrant_deletion_state.nested_run_loop_completed);
  CHECK(!weak_reentrant_core);
  CHECK(browser_manager->IsEmpty());
  CHECK(global_collection->IsEmpty());
  std::puts(kBrowserWindowCoreSmokeMarker);
  std::fflush(stdout);
  return true;
}

}  // namespace chrome
