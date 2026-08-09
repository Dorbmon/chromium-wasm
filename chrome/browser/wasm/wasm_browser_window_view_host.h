// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_WINDOW_VIEW_HOST_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_WINDOW_VIEW_HOST_H_

#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "base/scoped_observation.h"
#include "ui/views/widget/widget.h"
#include "ui/views/widget/widget_observer.h"

class BrowserView;
class BrowserWidget;
class WasmBrowserWindowCore;

namespace content {
class WebContents;
}  // namespace content

namespace chrome {

// Owns the bounded Views side of a WasmBrowserWindowCore binding. The Core
// continues to own BrowserWindowInterface, BrowserWindowFeatures, and its
// TabStripModel; this host owns neither a Profile nor tabs/WebContents. Once
// BrowserWidget initializes, its RootView owns the BrowserView. The host
// maintains that Views ownership cycle and breaks it only after the Core has
// detached the selected WebContents and torn down BrowserWindowFeatures.
class WasmBrowserWindowViewHost final : public views::WidgetObserver {
 public:
  explicit WasmBrowserWindowViewHost(WasmBrowserWindowCore* core);
  WasmBrowserWindowViewHost(const WasmBrowserWindowViewHost&) = delete;
  WasmBrowserWindowViewHost& operator=(const WasmBrowserWindowViewHost&) =
      delete;
  ~WasmBrowserWindowViewHost() override;

  // Initializes one content-only BrowserView and its BrowserWidget, then
  // binds the view to |core_|. This remains a bounded no-unload lifecycle;
  // callers must keep the host alive until the Core's deferred close runs.
  void Initialize();

  // Starts the bounded Core close protocol if it has not already started. The
  // request is asynchronous and deliberately makes no completion or success
  // claim; the Core owns tab closing and posts final Views teardown.
  void RequestClose();

  BrowserView* browser_view() const;

  // These counters expose only the bounded lifecycle evidence needed by the
  // switch-gated smoke. They do not make tab or Core ownership part of this
  // host's public surface.
  int active_tab_change_count_for_testing() const {
    return active_tab_change_count_;
  }
  bool detached_active_contents_for_testing() const {
    return detached_active_contents_;
  }
  int close_request_count_for_testing() const {
    return close_request_count_;
  }

 private:
  void OnActiveContentsChanged(content::WebContents* old_contents,
                               content::WebContents* new_contents,
                               int active_index,
                               int reason);
  void OnContentsDetached(content::WebContents* contents, bool was_active);
  views::CloseRequestResult OnCloseRequested();
  void Destroy();

  // views::WidgetObserver:
  void OnWidgetActivationChanged(views::Widget* widget, bool active) override;
  void OnWidgetDestroying(views::Widget* widget) override;
  void OnWidgetDestroyed(views::Widget* widget) override;

  base::WeakPtr<WasmBrowserWindowCore> core_;
  raw_ptr<BrowserView> browser_view_ = nullptr;
  raw_ptr<BrowserWidget> widget_ = nullptr;
  base::ScopedObservation<views::Widget, views::WidgetObserver>
      widget_observation_{this};
  int active_tab_change_count_ = 0;
  bool detached_active_contents_ = false;
  bool close_requested_ = false;
  int close_request_count_ = 0;
};

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_WINDOW_VIEW_HOST_H_
