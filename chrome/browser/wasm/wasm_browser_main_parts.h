// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_MAIN_PARTS_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_MAIN_PARTS_H_

#include "base/functional/callback.h"
#include "base/memory/weak_ptr.h"
#include "base/timer/timer.h"
#include <memory>

#include "content/public/browser/browser_main_parts.h"

class WasmBrowserProcess;
class WasmProfile;

namespace chrome {
class WasmBrowserLifecycle;
class WasmBrowserWindowLifecycle;
}

namespace display {
class Screen;
}

namespace views {
class LayoutProvider;
class ViewsDelegate;
}

namespace wm {
class WMState;
}

// Source-selected browser-main lifecycle for the initial Wasm Chrome process.
// It owns the resource bundle and the real, deliberately volatile process and
// profile objects. A normal startup result is withheld until the Chrome Views
// browser owner can construct and shut down a real Browser safely.
class WasmBrowserMainParts final : public content::BrowserMainParts {
 public:
  explicit WasmBrowserMainParts(bool is_integration_test);
  WasmBrowserMainParts(const WasmBrowserMainParts&) = delete;
  WasmBrowserMainParts& operator=(const WasmBrowserMainParts&) = delete;
  ~WasmBrowserMainParts() override;

  // content::BrowserMainParts:
  int PreEarlyInitialization() override;
  void ToolkitInitialized() override;
  void PostCreateMainMessageLoop() override;
  int PreCreateThreads() override;
  int PreMainMessageLoopRun() override;
  void WillRunMainMessageLoop(
      std::unique_ptr<base::RunLoop>& run_loop) override;
  void PostMainMessageLoopRun() override;

 private:
  bool PreflightResources();
  void RequestShutdown();
  void MaybeStartShutdown();
  void StartBrowserLifecycleSmokeShutdownTimer();
  void OnBrowserLifecycleSmokeShutdownTimer();
  void StartM9RepeatingTimerSmoke();
  void OnM9RepeatingTimerSmokeTick();
  void OnM9RepeatingTimerSmokeTimeout();
  void StopM9RepeatingTimerSmoke();
  void OnBrowserLifecycleShutdownComplete();
  void StartBrowserWindowLifecycleSmokeShutdownTimer();
  void OnBrowserWindowLifecycleSmokeShutdownTimer();
  void OnBrowserWindowLifecycleShutdownComplete();
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  void StartWasmProfileBookmarkSmokeOrCookieOrHistoryOrShutdown();
  void OnWasmProfileBookmarkSmokeComplete(bool success);
#endif
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  void StartWasmProfileCookieSmokeOrHistoryOrShutdown();
  void OnWasmProfileCookieSmokeComplete(bool success);
#endif
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  void StartWasmProfileHistorySmokeOrShutdown();
  void OnWasmProfileHistorySmokeComplete(bool success);
#endif
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
#if defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  void StartWasmProfileDatabaseSmokeOrShutdown();
#endif
  void OnWasmProfileDatabaseSmokeComplete(bool success);
#endif
#if defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  void StartWasmProfileRendererLocalStorageSmokeOrShutdown();
  void OnWasmProfileRendererLocalStorageSmokeComplete(bool success);
#endif
  void FinishShutdown();
  void ShutdownFoundation();

  bool resource_bundle_initialized_ = false;
  bool ozone_main_loop_initialized_ = false;
  bool shutdown_requested_ = false;
  bool browser_shutdown_started_ = false;
  bool browser_lifecycle_smoke_requested_ = false;
  bool m9_repeating_timer_smoke_requested_ = false;
  bool m9_repeating_timer_smoke_started_ = false;
  int m9_repeating_timer_smoke_observed_ticks_ = 0;
  int m9_repeating_timer_smoke_expected_ticks_ = 3;
  bool browser_window_shutdown_started_ = false;
  bool browser_window_lifecycle_smoke_requested_ = false;
  bool foundation_shutdown_ = false;
  base::RepeatingClosure main_message_loop_quit_closure_;

  // These generic Views/Aura singletons must outlive profile teardown and
  // Ozone's post-main-loop hook. Declaration order preserves the upstream
  // destruction order: WM state, screen, layout provider, then delegate.
  std::unique_ptr<views::ViewsDelegate> views_delegate_;
  std::unique_ptr<views::LayoutProvider> layout_provider_;
  std::unique_ptr<display::Screen> screen_;
  std::unique_ptr<wm::WMState> wm_state_;

  // Declaration order is intentional: profile shutdown must finish before
  // g_browser_process is cleared.
  std::unique_ptr<WasmBrowserProcess> browser_process_;
  std::unique_ptr<WasmProfile> profile_;

  // These are declared after |profile_| so their destructors run first. They
  // retain the bounded Browser/Core lifecycles until BrowserManagerService has
  // physically destroyed their manager-owned object before profile shutdown.
  std::unique_ptr<chrome::WasmBrowserLifecycle> browser_lifecycle_;
  std::unique_ptr<chrome::WasmBrowserWindowLifecycle>
      browser_window_lifecycle_;

  // These test-only timers start only after Content has installed the main
  // RunLoop. They prove retained visible windows survive an ordinary UI turn
  // before requesting their bounded shutdown sequence.
  base::OneShotTimer browser_lifecycle_smoke_shutdown_timer_;
  base::OneShotTimer browser_window_lifecycle_smoke_shutdown_timer_;
  base::RepeatingTimer m9_repeating_timer_smoke_timer_;
  base::OneShotTimer m9_repeating_timer_smoke_timeout_timer_;

  // Ozone retains the shutdown callback it receives at main-loop creation.
  // Keep this last so callbacks become inert before other state is destroyed.
  base::WeakPtrFactory<WasmBrowserMainParts> weak_ptr_factory_{this};
};

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_MAIN_PARTS_H_
