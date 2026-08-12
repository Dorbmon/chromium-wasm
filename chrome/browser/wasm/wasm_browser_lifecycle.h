// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_LIFECYCLE_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_LIFECYCLE_H_

#include <stdint.h>

#include <memory>

#include "base/callback_list.h"
#include "base/functional/callback.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "base/timer/timer.h"

class Browser;
class BrowserManagerService;
class BrowserWindowInterface;
class WasmProfile;

namespace content {
class WebContents;
}  // namespace content

namespace chrome {

class WasmBrowserHostTextNavigationObserver;
class WasmBrowserHostPointerMenuNavigationObserver;
class WasmBrowserHostHistoryDownloadsNavigationObserver;
class WasmBrowserHostStorageEstimateNavigationObserver;
class WasmBrowserContinuousFlow;
class WasmBrowserTabChurnSmoke;
class WasmBrowserNavigationChurnSmoke;
class WasmBrowserDevToolsProtocolSmoke;
class WasmBrowserDevToolsProtocolNavigationObserver;
class WasmBrowserAccessibilitySnapshotSmoke;
class WasmBrowserAccessibilitySnapshotNavigationObserver;

// Owns the process-lifetime side of one bounded slim Browser. The
// BrowserManagerService retains the Browser itself; this coordinator attaches
// its sole initial tab, observes every close route, and waits for the
// manager's physical-destruction turn before browser-main tears down the
// profile.
//
// It deliberately remains narrower than ordinary Chrome startup: one normal
// Browser, one no-unload tab, no general navigation or page-modal delegate,
// one explicit Browser-owned security-warning child dialog, and no desktop
// close controller.
class WasmBrowserLifecycle final {
 public:
  // |shutdown_complete| runs only after BrowserManagerService has physically
  // destroyed the Browser. It may delete this lifecycle through main-parts.
  WasmBrowserLifecycle(WasmProfile* profile,
                       base::OnceClosure shutdown_complete);
  WasmBrowserLifecycle(const WasmBrowserLifecycle&) = delete;
  WasmBrowserLifecycle& operator=(const WasmBrowserLifecycle&) = delete;
  ~WasmBrowserLifecycle();

  // Creates the manager-owned Browser, attaches its sole model-owned blank
  // WebContents, and shows its real Aura/Ozone BrowserView at fixed bounds
  // after all close-observation state is installed.
  void Initialize();

  // Begins the selected Browser's no-unload close path. A direct host close
  // also converges on the same did-close/destruction barrier.
  void BeginShutdown();

  // Arms the explicit host-to-Ozone accelerator proof after this lifecycle's
  // BrowserView is visible. The exported host ABI can only complete this
  // switch-gated check by delivering a selected physical shortcut through the
  // UI event path; it cannot directly invoke browser commands.
  void StartHostAcceleratorSmoke();

  // Arms the separate trusted-DOM committed-text smoke. Its only exported
  // test action is an ordered observation request; text itself still enters
  // through the Chrome-owned Ozone TextInputClient bridge.
  void StartHostTextSmoke();

  // Arms the separate real-browser smoke that accepts only trusted DOM mouse
  // records through Chrome's Ozone pointer bridge. Its exported test ABI can
  // ask this owner to inspect the model after a pointer action and acknowledge
  // a host-presented frame; it has no create/close/select command surface.
  void StartHostPointerTabSmoke();

  // Arms the separate real-browser smoke that opens the actual in-canvas
  // BrowserView menu and selects its Settings child through trusted DOM mouse
  // records. The exported verifier can only inspect the ensuing state and
  // acknowledge presentation; it cannot invoke menu commands or navigation.
  void StartHostPointerMenuSmoke();

  // Arms the separate trusted-DOM child-dialog smoke. The host may only
  // deliver physical pointer records and fixed ordinals; C++ verifies the
  // real Browser-owned WCMDM delegate, tab blocked state, Views widget, and
  // post-dismiss presentation before beginning ordinary Browser shutdown.
  void StartHostSecurityWarningSmoke();

  // Arms the test-only real-host route that journals two committed HTTPS tab
  // visits, then reaches the bounded History and Downloads WebUIs through the
  // normal text and pointer/Ozone paths. Its exported verifier only observes
  // ordinal stages and a post-presentation acknowledgement.
  void StartHostHistoryDownloadsSmoke();

  // Arms the formal Target-6 acceptance flow in one Browser lifetime. The
  // host receives only native-armed Views targets and fixed ordinal/frame
  // verifier exports; navigation, tabs, menu commands, and shutdown remain
  // owned by the existing Chrome/Ozone paths.
  void StartHostContinuousFlowSmoke();

  // Arms the M9 preparation smoke that retains one Browser through exactly
  // three trusted-DOM tab create/select/select/close cycles. It deliberately
  // does not navigate, persist data, use WISP, or measure worker behavior.
  void StartHostTabChurnSmoke();

  // Arms the M9 preparation smoke that retains one Browser and its original
  // tab through three fixed local data: navigation cycles. The host can only
  // acknowledge later backing-store copies; it cannot select or initiate a
  // navigation, and the documents contain no page script or WebAssembly.
  void StartHostNavigationChurnSmoke();

  // Arms the switch-gated outer-origin storage estimate proof. JavaScript can
  // only acknowledge an already accepted estimate and a later canvas frame;
  // native lifecycle code owns the fixed Settings navigation and validates the
  // immutable snapshot retained by its real WebUI controller.
  void StartHostStorageEstimateSmoke();

  // Starts the test-only fixed in-process DevTools protocol proof on this
  // lifecycle's active primary WebContents. It never exposes a frontend,
  // transport, or caller-selected protocol command.
  void StartDevToolsProtocolSmoke();

  // Starts the test-only fixed WebContents AX snapshot proof. It takes one
  // snapshot and permits only its fixed static semantic text into the passive
  // host mirror; it is not an interactive accessibility bridge.
  void StartAccessibilitySnapshotSmoke();

  bool IsVisible() const;
  bool IsShutdownStarted() const { return shutdown_started_; }
  bool IsShutdownComplete() const { return shutdown_complete_; }

 private:
  void OnBrowserDidClose(BrowserWindowInterface* browser);
  void ArmBrowserDestructionBarrier();
  void OnBrowserDestructionsComplete();
  void BeginNavigationChurnShutdown();
  bool VerifyHostAcceleratorDelivery();
  void OnHostAcceleratorDeliveryVerified();
  bool VerifyHostTextSmokeCheck(int stage);
  void OnHostTextNavigationObserved();
  bool VerifyHostPointerTabSmokeCheck(int stage);
  bool OnHostPointerTabSmokePresented(int stage);
  bool VerifyHostPointerMenuSmokeCheck(int stage);
  bool OnHostPointerMenuSmokePresented(int stage);
  void OnHostPointerMenuSettingsNavigationObserved();
  bool VerifyHostSecurityWarningSmokeCheck(int stage);
  bool OnHostSecurityWarningSmokePresented(int stage);
  void OnHostSecurityWarningDialogInteractionReady();
  bool VerifyHostHistoryDownloadsSmokeCheck(int stage);
  bool OnHostHistoryDownloadsSmokePresented(int stage);
  void OnHostHistoryDownloadsFirstNavigationObserved();
  void OnHostHistoryDownloadsSecondNavigationObserved();
  void OnHostHistoryDownloadsHistoryNavigationObserved();
  void OnHostHistoryDownloadsDownloadsNavigationObserved();
  void MaybeCompleteHostHistoryDownloadsHistoryNavigation();
  void MaybeCompleteHostHistoryDownloadsDownloadsNavigation();
  bool VerifyHostStorageEstimateSmokeCheck(int stage);
  bool OnHostStorageEstimateSmokePresented(int stage);
  void OnHostStorageEstimateSettingsNavigationObserved();
  void OnDevToolsProtocolSmokeNavigationObserved();
  void OnDevToolsProtocolSmokeSucceeded();
  void BeginDevToolsProtocolSmokeShutdown();
  void OnAccessibilitySnapshotSmokeNavigationObserved();
  void OnAccessibilitySnapshotSmokeCompleted(bool success);
  void BeginAccessibilitySnapshotSmokeShutdown();

  const raw_ptr<WasmProfile> profile_;
  const raw_ptr<BrowserManagerService> browser_manager_;
  base::WeakPtr<Browser> browser_;
  base::CallbackListSubscription browser_did_close_subscription_;
  base::OnceClosure shutdown_complete_callback_;
  bool initialized_ = false;
  bool host_accelerator_smoke_started_ = false;
  bool host_text_smoke_started_ = false;
  bool host_text_focus_verified_ = false;
  bool host_text_inserted_verified_ = false;
  bool host_text_navigation_observed_ = false;
  raw_ptr<content::WebContents> host_text_contents_ = nullptr;
  std::unique_ptr<WasmBrowserHostTextNavigationObserver>
      host_text_navigation_observer_;
  bool host_pointer_tab_smoke_started_ = false;
  bool host_pointer_tab_insert_verified_ = false;
  bool host_pointer_tab_first_selection_verified_ = false;
  bool host_pointer_tab_second_selection_verified_ = false;
  bool host_pointer_tab_close_verified_ = false;
  bool host_pointer_tab_presentation_verified_ = false;
  raw_ptr<content::WebContents> host_pointer_tab_initial_contents_ = nullptr;
  raw_ptr<content::WebContents> host_pointer_tab_second_contents_ = nullptr;
  bool host_pointer_menu_smoke_started_ = false;
  bool host_pointer_menu_open_verified_ = false;
  bool host_pointer_menu_open_presentation_verified_ = false;
  bool host_pointer_menu_settings_click_verified_ = false;
  bool host_pointer_menu_settings_navigation_verified_ = false;
  bool host_pointer_menu_settings_presentation_verified_ = false;
  int host_pointer_menu_closed_contents_y_ = 0;
  raw_ptr<content::WebContents> host_pointer_menu_contents_ = nullptr;
  std::unique_ptr<WasmBrowserHostPointerMenuNavigationObserver>
      host_pointer_menu_navigation_observer_;
  bool host_security_warning_smoke_started_ = false;
  bool host_security_warning_menu_open_verified_ = false;
  bool host_security_warning_menu_presentation_verified_ = false;
  bool host_security_warning_dialog_open_verified_ = false;
  bool host_security_warning_dialog_interaction_ready_ = false;
  bool host_security_warning_dismissed_verified_ = false;
  bool host_security_warning_presentation_verified_ = false;
  int host_security_warning_blocked_state_change_count_ = 0;
  raw_ptr<content::WebContents> host_security_warning_contents_ = nullptr;
  base::OneShotTimer host_security_warning_dialog_interaction_ready_timer_;
  bool host_history_downloads_smoke_started_ = false;
  bool host_history_downloads_first_navigation_verified_ = false;
  bool host_history_downloads_second_tab_verified_ = false;
  bool host_history_downloads_second_navigation_verified_ = false;
  bool host_history_downloads_history_target_fvp_observed_ = false;
  bool host_history_downloads_history_navigation_verified_ = false;
  bool host_history_downloads_history_menu_open_verified_ = false;
  bool host_history_downloads_history_menu_close_verified_ = false;
  bool host_history_downloads_downloads_menu_open_verified_ = false;
  bool host_history_downloads_downloads_menu_close_verified_ = false;
  bool host_history_downloads_downloads_target_fvp_observed_ = false;
  bool host_history_downloads_downloads_navigation_verified_ = false;
  bool host_history_downloads_presentation_verified_ = false;
  int host_history_downloads_closed_contents_y_ = 0;
  raw_ptr<content::WebContents> host_history_downloads_first_contents_ =
      nullptr;
  raw_ptr<content::WebContents> host_history_downloads_second_contents_ =
      nullptr;
  std::unique_ptr<WasmBrowserHostHistoryDownloadsNavigationObserver>
      host_history_downloads_first_navigation_observer_;
  std::unique_ptr<WasmBrowserHostHistoryDownloadsNavigationObserver>
      host_history_downloads_second_navigation_observer_;
  std::unique_ptr<WasmBrowserHostHistoryDownloadsNavigationObserver>
      host_history_downloads_history_navigation_observer_;
  std::unique_ptr<WasmBrowserHostHistoryDownloadsNavigationObserver>
      host_history_downloads_downloads_navigation_observer_;
  std::unique_ptr<WasmBrowserContinuousFlow> host_continuous_flow_;
  std::unique_ptr<WasmBrowserTabChurnSmoke> host_tab_churn_smoke_;
  std::unique_ptr<WasmBrowserNavigationChurnSmoke>
      host_navigation_churn_smoke_;
  bool devtools_protocol_smoke_started_ = false;
  bool devtools_protocol_smoke_succeeded_ = false;
  raw_ptr<content::WebContents> devtools_protocol_smoke_contents_ = nullptr;
  std::unique_ptr<WasmBrowserDevToolsProtocolNavigationObserver>
      devtools_protocol_smoke_navigation_observer_;
  std::unique_ptr<WasmBrowserDevToolsProtocolSmoke> devtools_protocol_smoke_;
  bool accessibility_snapshot_smoke_started_ = false;
  bool accessibility_snapshot_smoke_completion_received_ = false;
  bool accessibility_snapshot_smoke_succeeded_ = false;
  raw_ptr<content::WebContents> accessibility_snapshot_smoke_contents_ =
      nullptr;
  std::unique_ptr<WasmBrowserAccessibilitySnapshotNavigationObserver>
      accessibility_snapshot_smoke_navigation_observer_;
  std::unique_ptr<WasmBrowserAccessibilitySnapshotSmoke>
      accessibility_snapshot_smoke_;
  bool host_storage_estimate_smoke_started_ = false;
  bool host_storage_estimate_check_verified_ = false;
  bool host_storage_estimate_navigation_verified_ = false;
  uint32_t host_storage_estimate_generation_ = 0;
  uint64_t host_storage_estimate_usage_bytes_ = 0;
  uint64_t host_storage_estimate_quota_bytes_ = 0;
  raw_ptr<content::WebContents> host_storage_estimate_contents_ = nullptr;
  std::unique_ptr<WasmBrowserHostStorageEstimateNavigationObserver>
      host_storage_estimate_navigation_observer_;
  bool shutdown_started_ = false;
  bool browser_destruction_barrier_armed_ = false;
  bool shutdown_complete_ = false;
  base::WeakPtrFactory<WasmBrowserLifecycle> weak_ptr_factory_{this};
};

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_LIFECYCLE_H_
