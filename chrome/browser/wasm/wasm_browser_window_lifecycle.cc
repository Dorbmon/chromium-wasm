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
#include "ui/gfx/geometry/rect.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_window_lifecycle.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kBrowserWindowLifecycleSmokeMarker[] =
    "CHROMIUM_WASM_M6_BROWSER_WINDOW_LIFECYCLE:PASS";
constexpr gfx::Rect kBrowserWindowLifecycleSmokeBounds(0, 0, 640, 480);

}  // namespace

WasmBrowserWindowLifecycle::WasmBrowserWindowLifecycle(
    WasmProfile* profile,
    base::OnceClosure shutdown_complete)
    : profile_(profile),
      browser_manager_(BrowserManagerServiceFactory::GetForProfile(profile)),
      shutdown_complete_callback_(std::move(shutdown_complete)) {
  CHECK(profile_);
  CHECK(browser_manager_);
  CHECK(shutdown_complete_callback_);
}

WasmBrowserWindowLifecycle::~WasmBrowserWindowLifecycle() {
  // BrowserManagerService owns the Core. The retained Views host may only be
  // destroyed after the Core's manager deletion turn has invalidated |core_|.
  CHECK(!view_host_);
  CHECK(!core_);
  CHECK(!core_did_close_subscription_);
  CHECK(!shutdown_complete_callback_);
}

void WasmBrowserWindowLifecycle::Initialize() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(!initialized_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(!view_host_);
  CHECK(!core_);
  CHECK(!core_did_close_subscription_);
  CHECK(shutdown_complete_callback_);
  CHECK(browser_manager_->IsEmpty());

  auto core = std::make_unique<WasmBrowserWindowCore>(profile_);
  WasmBrowserWindowCore* const raw_core = core.get();
  core_ = raw_core->GetWeakPtr();
  CHECK(core_);
  browser_manager_->AddBrowser(std::move(core));
  CHECK_EQ(browser_manager_->GetSize(), 1u);

  // Install this before the Views host can expose a close route. The manager
  // callback is intentionally armed only once the Core emits did-close: doing
  // so during initialization would observe an empty destruction queue and
  // complete immediately before any close had occurred.
  core_did_close_subscription_ = raw_core->RegisterBrowserDidClose(
      base::BindRepeating(&WasmBrowserWindowLifecycle::OnCoreDidClose,
                          base::Unretained(this)));
  CHECK(core_did_close_subscription_);

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

  // The selected Wasm BrowserView BaseWindow implementation forwards these
  // calls to its retained BrowserWidget. Keep the test geometry fixed until
  // the primary-window factory owns host-display resize policy.
  browser_view->SetBounds(kBrowserWindowLifecycleSmokeBounds);
  CHECK_EQ(browser_view->GetBounds(), kBrowserWindowLifecycleSmokeBounds);
  browser_view->Show();
  CHECK(browser_view->IsVisible());
}

void WasmBrowserWindowLifecycle::BeginShutdown() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(view_host_);
  CHECK(core_);
  CHECK_EQ(browser_manager_->GetSize(), 1u);

  shutdown_started_ = true;
  view_host_->RequestClose();
}

bool WasmBrowserWindowLifecycle::IsVisible() const {
  CHECK(initialized_);
  CHECK(!shutdown_complete_);
  CHECK(view_host_);
  const views::Widget* const widget = view_host_->browser_view()->GetWidget();
  CHECK(widget);
  return widget->IsVisible();
}

void WasmBrowserWindowLifecycle::OnCoreDidClose(
    BrowserWindowInterface* browser) {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(!shutdown_complete_);
  CHECK_EQ(browser, core_.get());

  // A BrowserView/host close may enter the Core directly rather than through
  // BeginShutdown(). Both paths converge here while did-close dispatch is
  // still active, before the Core posts manager deletion.
  shutdown_started_ = true;
  ArmBrowserDestructionBarrier();
}

void WasmBrowserWindowLifecycle::ArmBrowserDestructionBarrier() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(core_);
  if (browser_destruction_barrier_armed_) {
    return;
  }
  browser_destruction_barrier_armed_ = true;

  // Core posts manager deletion only after every did-close subscriber has
  // returned. BrowserManagerService then posts its own non-nestable physical
  // destruction turn. Register during did-close so this covers both the
  // owner-initiated and direct BrowserView/host close paths without claiming
  // a manager-empty callback during initialization.
  browser_manager_->RunWhenBrowserDestructionsCompleteForWasm(
      base::BindOnce(
          &WasmBrowserWindowLifecycle::OnBrowserDestructionsComplete,
          base::Unretained(this)));
}

void WasmBrowserWindowLifecycle::OnBrowserDestructionsComplete() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(shutdown_started_);
  CHECK(browser_destruction_barrier_armed_);
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
  core_did_close_subscription_ = base::CallbackListSubscription();
  shutdown_complete_ = true;

  std::fprintf(stderr, "%s\n", kBrowserWindowLifecycleSmokeMarker);
  std::fflush(stderr);

  // |completion| may reset and destroy this lifecycle through main-parts. Do
  // not access members after running it.
  std::move(shutdown_complete_callback_).Run();
}

}  // namespace chrome
