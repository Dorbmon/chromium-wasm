// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_session_tab_helper.h"

#include "base/check.h"
#include "build/build_config.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/wasm/wasm_profile.h"
#include "chrome/browser/wasm/wasm_session_navigation_observer.h"
#include "components/sessions/content/session_tab_helper.h"
#include "content/public/browser/web_contents.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_session_tab_helper.cc must only be built for WebAssembly"
#endif

namespace chrome {

void EnsureWasmSessionTabHelper(content::WebContents* web_contents) {
  CHECK(web_contents);

  // TabModel calls this from PrepareWasmTabWebContents both when a tab is
  // constructed and when DiscardContents replaces its WebContents. Attach the
  // profile-owned observer here rather than TabFeatures::Init, which runs only
  // for the original TabModel and would miss a replacement contents.
  WasmProfile* const profile = static_cast<WasmProfile*>(
      Profile::FromBrowserContext(web_contents->GetBrowserContext()));
  CHECK(profile);
  WasmSessionNavigationObserver::CreateForWebContents(
      web_contents, profile->GetSessionNavigationJournalWeakPtr());

  if (sessions::SessionTabHelper::FromWebContents(web_contents)) {
    return;
  }

  // SessionTabHelper allocates its real per-session ID. An empty lookup means
  // navigation callbacks have no persistence delegate until a future,
  // complete Wasm session-service lifecycle is explicitly selected.
  sessions::SessionTabHelper::CreateForWebContents(
      web_contents, sessions::SessionTabHelper::DelegateLookup());
  CHECK(sessions::SessionTabHelper::FromWebContents(web_contents));
}

SessionID GetWasmSessionTabId(content::WebContents* web_contents) {
  CHECK(web_contents);
  sessions::SessionTabHelper* helper =
      sessions::SessionTabHelper::FromWebContents(web_contents);
  CHECK(helper) << "EnsureWasmSessionTabHelper must run before querying the tab ID";
  const SessionID id = sessions::SessionTabHelper::IdForTab(web_contents);
  CHECK(id.is_valid());
  return id;
}

}  // namespace chrome
