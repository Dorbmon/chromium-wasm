// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_session_navigation_observer.h"

#include <utility>

#include "base/check.h"
#include "build/build_config.h"
#include "chrome/browser/wasm/wasm_session_navigation_journal.h"
#include "content/public/browser/browser_thread.h"
#include "content/public/browser/navigation_handle.h"
#include "content/public/browser/web_contents.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_session_navigation_observer.cc must only be built for WebAssembly"
#endif

WasmSessionNavigationObserver::WasmSessionNavigationObserver(
    content::WebContents* web_contents,
    base::WeakPtr<WasmSessionNavigationJournal> journal)
    : content::WebContentsObserver(web_contents),
      content::WebContentsUserData<WasmSessionNavigationObserver>(*web_contents),
      journal_(std::move(journal)) {
  CHECK(web_contents);
}

WasmSessionNavigationObserver::~WasmSessionNavigationObserver() = default;

void WasmSessionNavigationObserver::DidFinishNavigation(
    content::NavigationHandle* navigation_handle) {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!journal_ || !navigation_handle ||
      !navigation_handle->IsInPrimaryMainFrame() ||
      !navigation_handle->HasCommitted() || navigation_handle->IsSameDocument() ||
      navigation_handle->IsErrorPage() || navigation_handle->IsDownload()) {
    return;
  }

  journal_->RecordCommittedPrimaryMainFrameNavigation(
      navigation_handle->GetURL());
}

void WasmSessionNavigationObserver::WebContentsDestroyed() {
  // WebContentsUserData owns this observer and destroys it with the contents.
  // Do not delete the helper or touch the profile here: dropping the weak
  // reference makes any late, already-queued callback inert.
  journal_.reset();
  Observe(nullptr);
}

WEB_CONTENTS_USER_DATA_KEY_IMPL(WasmSessionNavigationObserver);
