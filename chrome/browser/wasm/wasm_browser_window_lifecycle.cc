// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_window_lifecycle.h"

#include <cstdio>
#include <memory>
#include <utility>

#include "base/check.h"
#include "base/functional/bind.h"
#include "build/build_config.h"
#include "chrome/browser/ui/browser_manager_service.h"
#include "chrome/browser/ui/browser_manager_service_factory.h"
#include "chrome/browser/ui/browser_window/public/global_browser_collection.h"
#include "chrome/browser/ui/tabs/tab_strip_model.h"
#include "chrome/browser/ui/views/frame/browser_view.h"
#include "chrome/browser/wasm/wasm_browser_window_core.h"
#include "chrome/browser/wasm/wasm_browser_window_view_host.h"
#include "chrome/browser/wasm/wasm_profile.h"
#include "content/public/browser/browser_thread.h"
#include "content/public/browser/web_contents.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_window_lifecycle.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kBrowserWindowLifecycleSmokeMarker[] =
    "CHROMIUM_WASM_M6_BROWSER_WINDOW_LIFECYCLE:PASS";

}  // namespace

WasmBrowserWindowLifecycle::WasmBrowserWindowLifecycle(WasmProfile* profile)
    : profile_(profile),
      browser_manager_(BrowserManagerServiceFactory::GetForProfile(profile)) {
  CHECK(profile_);
  CHECK(browser_manager_);
}

WasmBrowserWindowLifecycle::~WasmBrowserWindowLifecycle() {
  // BrowserManagerService owns the Core. The retained Views host may only be
  // destroyed after the Core's manager deletion turn has invalidated |core_|.
  CHECK(!view_host_);
  CHECK(!core_);
  CHECK(!shutdown_complete_callback_);
}

void WasmBrowserWindowLifecycle::Initialize() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(!initialized_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(!view_host_);
  CHECK(!core_);
  CHECK(browser_manager_->IsEmpty());

  auto core = std::make_unique<WasmBrowserWindowCore>(profile_);
  WasmBrowserWindowCore* const raw_core = core.get();
  core_ = raw_core->GetWeakPtr();
  CHECK(core_);
  browser_manager_->AddBrowser(std::move(core));
  CHECK_EQ(browser_manager_->GetSize(), 1u);

  view_host_ = std::make_unique<WasmBrowserWindowViewHost>(raw_core);
  view_host_->Initialize();
  BrowserView* const browser_view = view_host_->browser_view();
  CHECK_EQ(raw_core->GetWindow(), browser_view);

  // The Core's close boundary deliberately requires exactly one model tab.
  // Attach it after the host binds its non-owning WebView so neither side can
  // observe a live WebContents without the other.
  content::WebContents::CreateParams create_params(profile_);
  std::unique_ptr<content::WebContents> contents =
      content::WebContents::Create(create_params);
  CHECK(contents);
  content::WebContents* const raw_contents = contents.get();
  TabStripModel* const tab_strip_model = raw_core->GetTabStripModel();
  CHECK(tab_strip_model);
  CHECK(tab_strip_model->empty());
  tab_strip_model->AppendWebContents(std::move(contents), /*foreground=*/true);
  CHECK_EQ(tab_strip_model->count(), 1);
  CHECK_EQ(tab_strip_model->GetActiveWebContents(), raw_contents);
  CHECK_EQ(browser_view->GetActiveWebContents(), raw_contents);

  initialized_ = true;
}

void WasmBrowserWindowLifecycle::BeginShutdown(base::OnceClosure completion) {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(completion);
  CHECK(view_host_);
  CHECK(core_);
  CHECK_EQ(browser_manager_->GetSize(), 1u);

  shutdown_started_ = true;
  shutdown_complete_callback_ = std::move(completion);

  // Register before asking the host to close. Core posts its manager deletion
  // only after the did-close callback list returns, and BrowserManagerService
  // then posts its own non-nestable physical destruction turn. This callback
  // is the only shutdown completion signal that spans both turns.
  browser_manager_->RunWhenBrowserDestructionsCompleteForWasm(
      base::BindOnce(
          &WasmBrowserWindowLifecycle::OnBrowserDestructionsComplete,
          base::Unretained(this)));
  view_host_->RequestClose();
}

void WasmBrowserWindowLifecycle::OnBrowserDestructionsComplete() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(!core_);
  CHECK(browser_manager_->IsEmpty());

  GlobalBrowserCollection* const global_collection =
      GlobalBrowserCollection::GetInstance();
  CHECK(global_collection);
  CHECK(global_collection->IsEmpty());

  // FinishClose has already invoked the host's ordered deactivate/unbind/View
  // destruction callback before it emits did-close. Releasing the host here
  // proves its weak Core has been invalidated rather than allowing profile
  // teardown to destroy a Core that is still bound to a Views window.
  CHECK(view_host_);
  CHECK_EQ(view_host_->active_tab_change_count_for_testing(), 2);
  CHECK(view_host_->detached_active_contents_for_testing());
  view_host_.reset();
  shutdown_complete_ = true;

  std::fprintf(stderr, "%s\n", kBrowserWindowLifecycleSmokeMarker);
  std::fflush(stderr);

  // |completion| may reset and destroy this lifecycle through main-parts. Do
  // not access members after running it.
  std::move(shutdown_complete_callback_).Run();
}

}  // namespace chrome
