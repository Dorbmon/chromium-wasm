// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_lifecycle.h"

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
#include "chrome/browser/wasm/wasm_browser.h"
#include "chrome/browser/wasm/wasm_profile.h"
#include "content/public/browser/browser_thread.h"
#include "content/public/browser/web_contents.h"
#include "ui/gfx/geometry/rect.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_lifecycle.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kBrowserLifecycleSmokeMarker[] =
    "CHROMIUM_WASM_M6_BROWSER_LIFECYCLE:PASS";
constexpr gfx::Rect kBrowserLifecycleSmokeBounds(0, 0, 640, 480);

}  // namespace

WasmBrowserLifecycle::WasmBrowserLifecycle(
    WasmProfile* profile,
    base::OnceClosure shutdown_complete)
    : profile_(profile),
      browser_manager_(BrowserManagerServiceFactory::GetForProfile(profile)),
      shutdown_complete_callback_(std::move(shutdown_complete)) {
  CHECK(profile_);
  CHECK(browser_manager_);
  CHECK(shutdown_complete_callback_);
}

WasmBrowserLifecycle::~WasmBrowserLifecycle() {
  // BrowserManagerService owns the Browser. This lifecycle can disappear only
  // after the manager's physical destruction callback invalidates |browser_|.
  CHECK(!browser_);
  CHECK(!browser_did_close_subscription_);
  CHECK(!shutdown_complete_callback_);
}

void WasmBrowserLifecycle::Initialize() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(!initialized_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(!browser_);
  CHECK(!browser_did_close_subscription_);
  CHECK(shutdown_complete_callback_);
  CHECK(browser_manager_->IsEmpty());

  Browser::CreateParams create_params(profile_, /*user_gesture=*/true);
  Browser* const raw_browser = Browser::Create(create_params);
  CHECK(raw_browser);
  browser_ = raw_browser->AsWeakPtr();
  CHECK(browser_);
  CHECK_EQ(browser_manager_->GetSize(), 1u);

  // Install this before the BrowserView can become visible and expose its
  // close route. The manager callback is armed only after did-close: doing it
  // here would synchronously observe empty queues and finish before a close.
  browser_did_close_subscription_ = raw_browser->RegisterBrowserDidClose(
      base::BindRepeating(&WasmBrowserLifecycle::OnBrowserDidClose,
                          base::Unretained(this)));
  CHECK(browser_did_close_subscription_);

  content::WebContents::CreateParams contents_params(profile_);
  std::unique_ptr<content::WebContents> contents =
      content::WebContents::Create(contents_params);
  CHECK(contents);
  content::WebContents* const raw_contents = contents.get();
  TabStripModel* const tab_strip_model = raw_browser->tab_strip_model();
  CHECK(tab_strip_model);
  CHECK(tab_strip_model->empty());
  tab_strip_model->AppendWebContents(std::move(contents), /*foreground=*/true);
  CHECK_EQ(tab_strip_model->count(), 1);
  CHECK_EQ(tab_strip_model->GetActiveWebContents(), raw_contents);

  BrowserView& browser_view = raw_browser->GetBrowserView();
  CHECK_EQ(browser_view.browser(), raw_browser);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_contents);
  browser_view.SetBounds(kBrowserLifecycleSmokeBounds);
  CHECK_EQ(browser_view.GetBounds(), kBrowserLifecycleSmokeBounds);
  browser_view.Show();
  CHECK(browser_view.IsVisible());

  initialized_ = true;
}

void WasmBrowserLifecycle::BeginShutdown() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(browser_);
  CHECK_EQ(browser_manager_->GetSize(), 1u);

  shutdown_started_ = true;
  browser_->GetWindow()->Close();
}

bool WasmBrowserLifecycle::IsVisible() const {
  CHECK(initialized_);
  CHECK(!shutdown_complete_);
  CHECK(browser_);
  return browser_->GetBrowserView().IsVisible();
}

void WasmBrowserLifecycle::OnBrowserDidClose(
    BrowserWindowInterface* browser) {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(!shutdown_complete_);
  CHECK_EQ(browser, browser_.get());

  // A direct BrowserView/host close can enter Browser::OnWindowClosing()
  // without BeginShutdown(). Both paths converge while did-close dispatch is
  // active, before Browser posts manager deletion.
  shutdown_started_ = true;
  ArmBrowserDestructionBarrier();
}

void WasmBrowserLifecycle::ArmBrowserDestructionBarrier() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(browser_);
  if (browser_destruction_barrier_armed_) {
    return;
  }
  browser_destruction_barrier_armed_ = true;

  // Browser posts DeleteBrowser after every did-close subscriber returns, and
  // BrowserManagerService performs physical destruction on its second
  // non-nestable turn. Register inside did-close so neither route can let
  // profile shutdown race a bound BrowserWidget.
  browser_manager_->RunWhenBrowserDestructionsCompleteForWasm(
      base::BindOnce(&WasmBrowserLifecycle::OnBrowserDestructionsComplete,
                     base::Unretained(this)));
}

void WasmBrowserLifecycle::OnBrowserDestructionsComplete() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(shutdown_started_);
  CHECK(browser_destruction_barrier_armed_);
  CHECK(!shutdown_complete_);
  CHECK(!browser_);
  CHECK(browser_manager_->IsEmpty());

  GlobalBrowserCollection* const global_collection =
      GlobalBrowserCollection::GetInstance();
  CHECK(global_collection);
  CHECK(global_collection->IsEmpty());

  browser_did_close_subscription_ = base::CallbackListSubscription();
  shutdown_complete_ = true;

  std::fprintf(stderr, "%s\n", kBrowserLifecycleSmokeMarker);
  std::fflush(stderr);

  // This callback may reset and destroy this lifecycle in main-parts.
  std::move(shutdown_complete_callback_).Run();
}

}  // namespace chrome
