// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_SESSION_NAVIGATION_OBSERVER_H_
#define CHROME_BROWSER_WASM_WASM_SESSION_NAVIGATION_OBSERVER_H_

#include "base/memory/weak_ptr.h"
#include "content/public/browser/web_contents_observer.h"
#include "content/public/browser/web_contents_user_data.h"

class WasmSessionNavigationJournal;

namespace content {
class NavigationHandle;
class WebContents;
}  // namespace content

// The per-WebContents half of WasmSessionNavigationJournal. It carries only a
// weak journal reference, so a late navigation callback is inert after the
// owning profile starts shutdown.
class WasmSessionNavigationObserver final
    : public content::WebContentsObserver,
      public content::WebContentsUserData<WasmSessionNavigationObserver> {
 public:
  WasmSessionNavigationObserver(const WasmSessionNavigationObserver&) = delete;
  WasmSessionNavigationObserver& operator=(
      const WasmSessionNavigationObserver&) = delete;
  ~WasmSessionNavigationObserver() override;

 private:
  friend class content::WebContentsUserData<WasmSessionNavigationObserver>;
  WasmSessionNavigationObserver(
      content::WebContents* web_contents,
      base::WeakPtr<WasmSessionNavigationJournal> journal);

  // content::WebContentsObserver:
  void DidFinishNavigation(content::NavigationHandle* navigation_handle) override;
  void WebContentsDestroyed() override;

  base::WeakPtr<WasmSessionNavigationJournal> journal_;

  WEB_CONTENTS_USER_DATA_KEY_DECL();
};

#endif  // CHROME_BROWSER_WASM_WASM_SESSION_NAVIGATION_OBSERVER_H_
