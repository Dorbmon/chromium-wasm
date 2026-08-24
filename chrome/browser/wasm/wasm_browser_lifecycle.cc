// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_lifecycle.h"

#include <cstdio>
#include <memory>
#include <utility>
#include <vector>

#include "base/check.h"
#include "base/command_line.h"
#include "base/functional/bind.h"
#include "base/task/single_thread_task_runner.h"
#include "base/time/time.h"
#include "build/build_config.h"
#include "chrome/browser/ui/browser_manager_service.h"
#include "chrome/browser/ui/browser_manager_service_factory.h"
#include "chrome/browser/ui/browser_window/public/global_browser_collection.h"
#include "chrome/browser/ui/tabs/tab_strip_model.h"
#include "chrome/browser/ui/views/frame/browser_view.h"
#include "chrome/browser/wasm/wasm_browser.h"
#include "chrome/browser/wasm/wasm_browser_accessibility_snapshot_smoke.h"
#include "chrome/browser/wasm/wasm_browser_continuous_flow.h"
#include "chrome/browser/wasm/wasm_browser_devtools_protocol_smoke.h"
#include "chrome/browser/wasm/wasm_browser_host_clipboard.h"
#include "chrome/browser/wasm/wasm_browser_host_clipboard_smoke.h"
#include "chrome/browser/wasm/wasm_browser_host_continuous_flow_smoke.h"
#include "chrome/browser/wasm/wasm_browser_host_history_downloads_smoke.h"
#include "chrome/browser/wasm/wasm_browser_host_input.h"
#include "chrome/browser/wasm/wasm_browser_host_navigation_churn_smoke.h"
#include "chrome/browser/wasm/wasm_browser_host_pointer_menu_smoke.h"
#include "chrome/browser/wasm/wasm_browser_host_pointer_tab_smoke.h"
#include "chrome/browser/wasm/wasm_browser_host_security_warning_smoke.h"
#include "chrome/browser/wasm/wasm_browser_host_storage_estimate.h"
#include "chrome/browser/wasm/wasm_browser_host_storage_estimate_smoke.h"
#include "chrome/browser/wasm/wasm_browser_host_tab_churn_smoke.h"
#include "chrome/browser/wasm/wasm_browser_host_text.h"
#include "chrome/browser/wasm/wasm_browser_host_text_smoke.h"
#include "chrome/browser/wasm/wasm_browser_security_warning_dialog.h"
#include "chrome/browser/wasm/wasm_browser_navigation_churn_smoke.h"
#include "chrome/browser/wasm/wasm_browser_tab_churn_smoke.h"
#include "chrome/browser/wasm/wasm_profile.h"
#include "chrome/browser/wasm/wasm_downloads_ui.h"
#include "chrome/browser/wasm/wasm_browser_menu.h"
#include "chrome/browser/wasm/wasm_history_ui.h"
#include "chrome/browser/wasm/wasm_session_navigation_journal.h"
#include "chrome/browser/wasm/wasm_settings_ui.h"
#include "chrome/browser/wasm/wasm_tab_strip_view.h"
#include "chrome/browser/wasm/wasm_top_controls_view.h"
#include "components/web_modal/web_contents_modal_dialog_manager.h"
#include "content/public/browser/browser_thread.h"
#include "content/public/browser/navigation_controller.h"
#include "content/public/browser/navigation_handle.h"
#include "content/public/browser/render_frame_host.h"
#include "content/public/browser/web_contents.h"
#include "content/public/browser/web_contents_observer.h"
#include "content/public/browser/web_ui.h"
#include "content/public/browser/web_ui_controller.h"
#include "content/public/browser/webui_config.h"
#include "content/public/common/url_constants.h"
#include "ui/aura/window.h"
#include "ui/aura/window_tree_host.h"
#include "ui/base/page_transition_types.h"
#include "ui/gfx/geometry/point.h"
#include "ui/gfx/geometry/rect.h"
#include "ui/views/controls/button/label_button.h"
#include "ui/views/controls/textfield/textfield.h"
#include "ui/views/controls/webview/webview.h"
#include "ui/views/metrics.h"
#include "ui/views/view.h"
#include "ui/views/widget/widget.h"
#include "url/gurl.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_lifecycle.cc must only be built for WebAssembly"
#endif

namespace chrome {

class WasmBrowserHostTextNavigationObserver final
    : public content::WebContentsObserver {
 public:
  WasmBrowserHostTextNavigationObserver(
      content::WebContents* web_contents,
      GURL expected_url,
      base::RepeatingClosure navigation_observed)
      : content::WebContentsObserver(web_contents),
        expected_url_(std::move(expected_url)),
        navigation_observed_(std::move(navigation_observed)) {
    CHECK(web_contents);
    CHECK(expected_url_.is_valid());
    CHECK(navigation_observed_);
  }

  WasmBrowserHostTextNavigationObserver(
      const WasmBrowserHostTextNavigationObserver&) = delete;
  WasmBrowserHostTextNavigationObserver& operator=(
      const WasmBrowserHostTextNavigationObserver&) = delete;
  ~WasmBrowserHostTextNavigationObserver() override = default;

  void DidFinishNavigation(
      content::NavigationHandle* navigation_handle) override {
    if (observed_ || !navigation_handle ||
        !navigation_handle->IsInPrimaryMainFrame() ||
        navigation_handle->IsSameDocument() ||
        !navigation_handle->HasCommitted() ||
        navigation_handle->GetURL() != expected_url_) {
      return;
    }
    observed_ = true;
    navigation_observed_.Run();
  }

 private:
  const GURL expected_url_;
  const base::RepeatingClosure navigation_observed_;
  bool observed_ = false;
};

// Observes the Settings navigation independently of the ordinal verifier.
// The local WebUI can commit before the host's second verifier task runs, so
// completion is joined later with the Ozone-delivered Settings click rather
// than making the observer depend on that scheduling detail.
class WasmBrowserHostPointerMenuNavigationObserver final
    : public content::WebContentsObserver {
 public:
  WasmBrowserHostPointerMenuNavigationObserver(
      content::WebContents* web_contents,
      GURL expected_url,
      base::RepeatingClosure navigation_observed)
      : content::WebContentsObserver(web_contents),
        expected_url_(std::move(expected_url)),
        navigation_observed_(std::move(navigation_observed)) {
    CHECK(web_contents);
    CHECK(expected_url_.is_valid());
    CHECK(navigation_observed_);
  }

  WasmBrowserHostPointerMenuNavigationObserver(
      const WasmBrowserHostPointerMenuNavigationObserver&) = delete;
  WasmBrowserHostPointerMenuNavigationObserver& operator=(
      const WasmBrowserHostPointerMenuNavigationObserver&) = delete;
  ~WasmBrowserHostPointerMenuNavigationObserver() override = default;

  // content::WebContentsObserver:
  void DidFinishNavigation(
      content::NavigationHandle* navigation_handle) override {
    if (observed_ || committed_ || !navigation_handle ||
        !navigation_handle->IsInPrimaryMainFrame() ||
        navigation_handle->IsSameDocument() ||
        !navigation_handle->HasCommitted() || navigation_handle->IsErrorPage() ||
        navigation_handle->GetURL() != expected_url_ ||
        !ui::PageTransitionCoreTypeIs(navigation_handle->GetPageTransition(),
                                      ui::PAGE_TRANSITION_GENERATED) ||
        !navigation_handle->HasUserGesture() || !web_contents() ||
        web_contents()->GetLastCommittedURL() != expected_url_) {
      return;
    }

    committed_ = true;
    if (web_contents()->CompletedFirstVisuallyNonEmptyPaint()) {
      first_visually_nonempty_paint_after_commit_ = true;
    }
    if (!web_contents()->IsLoading()) {
      stopped_loading_after_commit_ = true;
    }
    MaybeNotify();
  }

  void DidStopLoading() override {
    if (!committed_ || observed_) {
      return;
    }
    stopped_loading_after_commit_ = true;
    MaybeNotify();
  }

  void DidFirstVisuallyNonEmptyPaint() override {
    if (!committed_ || observed_ || !web_contents() ||
        web_contents()->GetLastCommittedURL() != expected_url_) {
      return;
    }
    CHECK(web_contents()->CompletedFirstVisuallyNonEmptyPaint());
    first_visually_nonempty_paint_after_commit_ = true;
    MaybeNotify();
  }

 private:
  void MaybeNotify() {
    if (observed_ || !committed_ || !stopped_loading_after_commit_ ||
        !first_visually_nonempty_paint_after_commit_) {
      return;
    }
    observed_ = true;
    navigation_observed_.Run();
  }

  const GURL expected_url_;
  const base::RepeatingClosure navigation_observed_;
  bool committed_ = false;
  bool stopped_loading_after_commit_ = false;
  bool first_visually_nonempty_paint_after_commit_ = false;
  bool observed_ = false;
};

// Observes the fixed native Settings navigation used by the storage-estimate
// smoke. Unlike the pointer-menu flow, this switch-gated diagnostic test does
// not claim a host gesture: JavaScript can only acknowledge the already
// accepted outer-origin estimate and a later presentation frame.
class WasmBrowserHostStorageEstimateNavigationObserver final
    : public content::WebContentsObserver {
 public:
  WasmBrowserHostStorageEstimateNavigationObserver(
      content::WebContents* web_contents,
      GURL expected_url,
      base::RepeatingClosure navigation_observed)
      : content::WebContentsObserver(web_contents),
        expected_url_(std::move(expected_url)),
        navigation_observed_(std::move(navigation_observed)) {
    CHECK(web_contents);
    CHECK(expected_url_.is_valid());
    CHECK(navigation_observed_);
  }

  WasmBrowserHostStorageEstimateNavigationObserver(
      const WasmBrowserHostStorageEstimateNavigationObserver&) = delete;
  WasmBrowserHostStorageEstimateNavigationObserver& operator=(
      const WasmBrowserHostStorageEstimateNavigationObserver&) = delete;
  ~WasmBrowserHostStorageEstimateNavigationObserver() override = default;

  void DidFinishNavigation(
      content::NavigationHandle* navigation_handle) override {
    if (observed_ || committed_ || !navigation_handle ||
        !navigation_handle->IsInPrimaryMainFrame() ||
        navigation_handle->IsSameDocument() ||
        !navigation_handle->HasCommitted() || navigation_handle->IsErrorPage() ||
        navigation_handle->GetURL() != expected_url_ || !web_contents() ||
        web_contents()->GetLastCommittedURL() != expected_url_) {
      return;
    }
    committed_ = true;
    if (web_contents()->CompletedFirstVisuallyNonEmptyPaint()) {
      first_visually_nonempty_paint_after_commit_ = true;
    }
    if (!web_contents()->IsLoading()) {
      stopped_loading_after_commit_ = true;
    }
    MaybeNotify();
  }

  void DidStopLoading() override {
    if (!committed_ || observed_) {
      return;
    }
    stopped_loading_after_commit_ = true;
    MaybeNotify();
  }

  void DidFirstVisuallyNonEmptyPaint() override {
    if (!committed_ || observed_ || !web_contents() ||
        web_contents()->GetLastCommittedURL() != expected_url_) {
      return;
    }
    CHECK(web_contents()->CompletedFirstVisuallyNonEmptyPaint());
    first_visually_nonempty_paint_after_commit_ = true;
    MaybeNotify();
  }

 private:
  void MaybeNotify() {
    if (observed_ || !committed_ || !stopped_loading_after_commit_ ||
        !first_visually_nonempty_paint_after_commit_) {
      return;
    }
    observed_ = true;
    navigation_observed_.Run();
  }

  const GURL expected_url_;
  const base::RepeatingClosure navigation_observed_;
  bool committed_ = false;
  bool stopped_loading_after_commit_ = false;
  bool first_visually_nonempty_paint_after_commit_ = false;
  bool observed_ = false;
};

// Waits for the fixed, browser-initiated data URL used by the DevTools
// protocol smoke. The direct protocol client must never attach to the initial
// uncommitted blank WebContents: it needs the real, live primary renderer
// frame that this observer verifies after commit.
class WasmBrowserDevToolsProtocolNavigationObserver final
    : public content::WebContentsObserver {
 public:
  WasmBrowserDevToolsProtocolNavigationObserver(
      content::WebContents* web_contents,
      GURL expected_url,
      base::RepeatingClosure navigation_observed)
      : content::WebContentsObserver(web_contents),
        expected_url_(std::move(expected_url)),
        navigation_observed_(std::move(navigation_observed)) {
    CHECK(web_contents);
    CHECK(expected_url_.is_valid());
    CHECK(navigation_observed_);
  }

  WasmBrowserDevToolsProtocolNavigationObserver(
      const WasmBrowserDevToolsProtocolNavigationObserver&) = delete;
  WasmBrowserDevToolsProtocolNavigationObserver& operator=(
      const WasmBrowserDevToolsProtocolNavigationObserver&) = delete;
  ~WasmBrowserDevToolsProtocolNavigationObserver() override = default;

  void DidFinishNavigation(
      content::NavigationHandle* navigation_handle) override {
    if (observed_ || !navigation_handle ||
        !navigation_handle->IsInPrimaryMainFrame() ||
        navigation_handle->IsSameDocument() ||
        !navigation_handle->HasCommitted() || navigation_handle->IsErrorPage() ||
        navigation_handle->GetURL() != expected_url_ || !web_contents() ||
        web_contents()->GetLastCommittedURL() != expected_url_) {
      return;
    }

    content::RenderFrameHost* const primary_main_frame =
        web_contents()->GetPrimaryMainFrame();
    if (!primary_main_frame || !primary_main_frame->IsRenderFrameLive()) {
      return;
    }

    observed_ = true;
    navigation_observed_.Run();
  }

 private:
  const GURL expected_url_;
  const base::RepeatingClosure navigation_observed_;
  bool observed_ = false;
};

// Waits for the one fixed data URL used by the AX snapshot smoke to commit,
// finish loading, and paint before the one-shot renderer snapshot begins.
// The observer owns no semantic data and cannot select a URL or page.
class WasmBrowserAccessibilitySnapshotNavigationObserver final
    : public content::WebContentsObserver {
 public:
  WasmBrowserAccessibilitySnapshotNavigationObserver(
      content::WebContents* web_contents,
      GURL expected_url,
      base::RepeatingClosure navigation_observed)
      : content::WebContentsObserver(web_contents),
        expected_url_(std::move(expected_url)),
        navigation_observed_(std::move(navigation_observed)) {
    CHECK(web_contents);
    CHECK(expected_url_.is_valid());
    CHECK(navigation_observed_);
  }

  WasmBrowserAccessibilitySnapshotNavigationObserver(
      const WasmBrowserAccessibilitySnapshotNavigationObserver&) = delete;
  WasmBrowserAccessibilitySnapshotNavigationObserver& operator=(
      const WasmBrowserAccessibilitySnapshotNavigationObserver&) = delete;
  ~WasmBrowserAccessibilitySnapshotNavigationObserver() override = default;

  void DidFinishNavigation(
      content::NavigationHandle* navigation_handle) override {
    if (observed_ || committed_ || !navigation_handle ||
        !navigation_handle->IsInPrimaryMainFrame() ||
        navigation_handle->IsSameDocument() ||
        !navigation_handle->HasCommitted() || navigation_handle->IsErrorPage() ||
        navigation_handle->GetURL() != expected_url_ || !web_contents() ||
        web_contents()->GetLastCommittedURL() != expected_url_) {
      return;
    }

    content::RenderFrameHost* const primary_main_frame =
        web_contents()->GetPrimaryMainFrame();
    if (!primary_main_frame || !primary_main_frame->IsRenderFrameLive()) {
      return;
    }

    committed_ = true;
    if (web_contents()->CompletedFirstVisuallyNonEmptyPaint()) {
      first_visually_nonempty_paint_after_commit_ = true;
    }
    if (!web_contents()->IsLoading()) {
      stopped_loading_after_commit_ = true;
    }
    MaybeNotify();
  }

  void DidStopLoading() override {
    if (!committed_ || observed_) {
      return;
    }
    stopped_loading_after_commit_ = true;
    MaybeNotify();
  }

  void DidFirstVisuallyNonEmptyPaint() override {
    if (!committed_ || observed_ || !web_contents() ||
        web_contents()->GetLastCommittedURL() != expected_url_) {
      return;
    }
    CHECK(web_contents()->CompletedFirstVisuallyNonEmptyPaint());
    first_visually_nonempty_paint_after_commit_ = true;
    MaybeNotify();
  }

 private:
  void MaybeNotify() {
    if (observed_ || !committed_ || !stopped_loading_after_commit_ ||
        !first_visually_nonempty_paint_after_commit_) {
      return;
    }
    observed_ = true;
    navigation_observed_.Run();
  }

  const GURL expected_url_;
  const base::RepeatingClosure navigation_observed_;
  bool committed_ = false;
  bool stopped_loading_after_commit_ = false;
  bool first_visually_nonempty_paint_after_commit_ = false;
  bool observed_ = false;
};

// A compact observer for the trusted host WebUI flow. Navigation initiation is
// never supplied by this observer: the lifecycle arms it before each host
// phase, then it requires the real primary commit, user gesture, completion,
// and target first-visually-non-empty paint before notifying the owner.
class WasmBrowserHostHistoryDownloadsNavigationObserver final
    : public content::WebContentsObserver {
 public:
  enum class ExpectedNavigation {
    kTypedUser,
    kGeneratedUser,
  };

  WasmBrowserHostHistoryDownloadsNavigationObserver(
      content::WebContents* web_contents,
      GURL expected_url,
      ExpectedNavigation expected_navigation,
      base::RepeatingClosure navigation_observed)
      : content::WebContentsObserver(web_contents),
        expected_url_(std::move(expected_url)),
        expected_navigation_(expected_navigation),
        navigation_observed_(std::move(navigation_observed)) {
    CHECK(web_contents);
    CHECK(expected_url_.is_valid());
    CHECK(navigation_observed_);
  }

  WasmBrowserHostHistoryDownloadsNavigationObserver(
      const WasmBrowserHostHistoryDownloadsNavigationObserver&) = delete;
  WasmBrowserHostHistoryDownloadsNavigationObserver& operator=(
      const WasmBrowserHostHistoryDownloadsNavigationObserver&) = delete;
  ~WasmBrowserHostHistoryDownloadsNavigationObserver() override = default;

  // content::WebContentsObserver:
  void DidFinishNavigation(
      content::NavigationHandle* navigation_handle) override {
    if (observed_ || committed_ || !navigation_handle ||
        !navigation_handle->IsInPrimaryMainFrame() ||
        navigation_handle->IsSameDocument() ||
        !navigation_handle->HasCommitted() || navigation_handle->IsErrorPage() ||
        navigation_handle->GetURL() != expected_url_ ||
        !navigation_handle->HasUserGesture() || !web_contents() ||
        web_contents()->GetLastCommittedURL() != expected_url_) {
      return;
    }

    const ui::PageTransition expected_transition =
        expected_navigation_ == ExpectedNavigation::kTypedUser
            ? ui::PAGE_TRANSITION_TYPED
            : ui::PAGE_TRANSITION_GENERATED;
    if (!ui::PageTransitionCoreTypeIs(navigation_handle->GetPageTransition(),
                                      expected_transition)) {
      return;
    }

    committed_ = true;
    if (web_contents()->CompletedFirstVisuallyNonEmptyPaint()) {
      first_visually_nonempty_paint_after_commit_ = true;
    }
    if (!web_contents()->IsLoading()) {
      stopped_loading_after_commit_ = true;
    }
    MaybeNotify();
  }

  void DidStopLoading() override {
    if (!committed_ || observed_) {
      return;
    }
    stopped_loading_after_commit_ = true;
    MaybeNotify();
  }

  void DidFirstVisuallyNonEmptyPaint() override {
    if (!committed_ || observed_ || !web_contents() ||
        web_contents()->GetLastCommittedURL() != expected_url_) {
      return;
    }
    CHECK(web_contents()->CompletedFirstVisuallyNonEmptyPaint());
    first_visually_nonempty_paint_after_commit_ = true;
    MaybeNotify();
  }

 private:
  void MaybeNotify() {
    if (observed_ || !committed_ || !stopped_loading_after_commit_ ||
        !first_visually_nonempty_paint_after_commit_) {
      return;
    }
    observed_ = true;
    navigation_observed_.Run();
  }

  const GURL expected_url_;
  const ExpectedNavigation expected_navigation_;
  const base::RepeatingClosure navigation_observed_;
  bool committed_ = false;
  bool stopped_loading_after_commit_ = false;
  bool first_visually_nonempty_paint_after_commit_ = false;
  bool observed_ = false;
};

namespace {

constexpr char kHostAcceleratorsSmokeMarker[] =
    "CHROMIUM_WASM_M6_HOST_ACCELERATORS:PASS";
constexpr char kHostTextSmokeReadyMarker[] =
    "CHROMIUM_WASM_M6_HOST_TEXT:READY";
constexpr char kHostTextSmokeBurstArmedMarker[] =
    "CHROMIUM_WASM_M6_HOST_TEXT:BURST_ARMED";
constexpr char kHostTextSmokeFocusedMarker[] =
    "CHROMIUM_WASM_M6_HOST_TEXT:FOCUSED";
constexpr char kHostTextSmokeInsertedMarker[] =
    "CHROMIUM_WASM_M6_HOST_TEXT:TEXT_INSERTED";
constexpr char kHostTextSmokeNavigatedMarker[] =
    "CHROMIUM_WASM_M6_HOST_TEXT:NAVIGATED";
constexpr char kHostTextSmokePassMarker[] =
    "CHROMIUM_WASM_M6_HOST_TEXT:PASS";
constexpr char kHostClipboardSmokeReadyMarker[] =
    "CHROMIUM_WASM_M7_HOST_CLIPBOARD:READY";
constexpr char kHostClipboardSmokeFocusedMarker[] =
    "CHROMIUM_WASM_M7_HOST_CLIPBOARD:FOCUSED";
constexpr char kHostClipboardSmokePastedMarker[] =
    "CHROMIUM_WASM_M7_HOST_CLIPBOARD:PASTED";
constexpr char kHostClipboardSmokeNavigatedMarker[] =
    "CHROMIUM_WASM_M7_HOST_CLIPBOARD:NAVIGATED";
constexpr char kHostClipboardSmokePassMarker[] =
    "CHROMIUM_WASM_M7_HOST_CLIPBOARD:PASS";
constexpr char kHostStorageEstimateSmokeReadyMarker[] =
    "CHROMIUM_WASM_M7_HOST_STORAGE_ESTIMATE:READY";
constexpr char kHostStorageEstimateSmokeNavigatedMarker[] =
    "CHROMIUM_WASM_M7_HOST_STORAGE_ESTIMATE:SETTINGS_NAVIGATED";
constexpr char kHostStorageEstimateSmokePassMarker[] =
    "CHROMIUM_WASM_M7_HOST_STORAGE_ESTIMATE:PASS";
constexpr char kHostTextSmokeUrl[] = "chrome://version/";
constexpr char kHostStorageEstimateSettingsUrl[] = "chrome://settings/";
constexpr char kAccessibilitySnapshotSmokeReadyMarker[] =
    "CHROMIUM_WASM_M8_ACCESSIBILITY_SNAPSHOT:READY";
constexpr char kAccessibilitySnapshotSmokeNavigatedMarker[] =
    "CHROMIUM_WASM_M8_ACCESSIBILITY_SNAPSHOT:NAVIGATED";
constexpr char kAccessibilitySnapshotSmokePassMarker[] =
    "CHROMIUM_WASM_M8_ACCESSIBILITY_SNAPSHOT:PASS";
constexpr char16_t kHostStorageEstimateSettingsTitle[] =
    u"Settings \u2014 Chromium Wasm";
constexpr char kHostPointerTabsReadyMarker[] =
    "CHROMIUM_WASM_M6_HOST_POINTER_TABS:READY";
constexpr char kHostPointerTabsInsertedMarker[] =
    "CHROMIUM_WASM_M6_HOST_POINTER_TABS:INSERTED";
constexpr char kHostPointerTabsFirstSelectedMarker[] =
    "CHROMIUM_WASM_M6_HOST_POINTER_TABS:FIRST_SELECTED";
constexpr char kHostPointerTabsSecondSelectedMarker[] =
    "CHROMIUM_WASM_M6_HOST_POINTER_TABS:SECOND_SELECTED";
constexpr char kHostPointerTabsClosedMarker[] =
    "CHROMIUM_WASM_M6_HOST_POINTER_TABS:CLOSED";
constexpr char kHostPointerTabsPassMarker[] =
    "CHROMIUM_WASM_M6_HOST_POINTER_TABS:PASS";
constexpr char kHostPointerMenuReadyMarker[] =
    "CHROMIUM_WASM_M6_HOST_POINTER_MENU:READY";
constexpr char kHostPointerMenuOpenedMarker[] =
    "CHROMIUM_WASM_M6_HOST_POINTER_MENU:MENU_OPEN";
constexpr char kHostPointerMenuPresentedMarker[] =
    "CHROMIUM_WASM_M6_HOST_POINTER_MENU:MENU_PRESENTED";
constexpr char kHostPointerMenuClosedMarker[] =
    "CHROMIUM_WASM_M6_HOST_POINTER_MENU:MENU_CLOSED";
constexpr char kHostPointerMenuSettingsNavigatedMarker[] =
    "CHROMIUM_WASM_M6_HOST_POINTER_MENU:SETTINGS_NAVIGATED";
constexpr char kHostPointerMenuPassMarker[] =
    "CHROMIUM_WASM_M6_HOST_POINTER_MENU:PASS";
constexpr char kHostSecurityWarningReadyMarker[] =
    "CHROMIUM_WASM_M6_HOST_SECURITY_WARNING:READY";
constexpr char kHostSecurityWarningMenuOpenedMarker[] =
    "CHROMIUM_WASM_M6_HOST_SECURITY_WARNING:MENU_OPEN";
constexpr char kHostSecurityWarningMenuPresentedMarker[] =
    "CHROMIUM_WASM_M6_HOST_SECURITY_WARNING:MENU_PRESENTED";
constexpr char kHostSecurityWarningDialogOpenedMarker[] =
    "CHROMIUM_WASM_M6_HOST_SECURITY_WARNING:DIALOG_OPEN";
constexpr char kHostSecurityWarningDialogInteractionReadyMarker[] =
    "CHROMIUM_WASM_M6_HOST_SECURITY_WARNING:DIALOG_INTERACTION_READY";
constexpr char kHostSecurityWarningDialogDismissedMarker[] =
    "CHROMIUM_WASM_M6_HOST_SECURITY_WARNING:DIALOG_DISMISSED";
constexpr char kHostSecurityWarningPassMarker[] =
    "CHROMIUM_WASM_M6_HOST_SECURITY_WARNING:PASS";
constexpr char kHostPointerMenuSettingsUrl[] = "chrome://settings/";
constexpr char16_t kHostPointerMenuSettingsTitle[] =
    u"Settings \u2014 Chromium Wasm";
constexpr char kHostHistoryDownloadsReadyMarker[] =
    "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:READY";
constexpr char kHostHistoryDownloadsFirstNavigatedMarker[] =
    "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:FIRST_NAVIGATED";
constexpr char kHostHistoryDownloadsSecondTabReadyMarker[] =
    "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:SECOND_TAB_READY";
constexpr char kHostHistoryDownloadsSecondNavigatedMarker[] =
    "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:SECOND_NAVIGATED";
constexpr char kHostHistoryDownloadsHistoryNavigatedMarker[] =
    "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:HISTORY_NAVIGATED";
constexpr char kHostHistoryDownloadsMenuOpenedMarker[] =
    "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:MENU_OPEN_HISTORY";
constexpr char kHostHistoryDownloadsHistoryMenuClosedMarker[] =
    "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:MENU_CLOSED_HISTORY";
constexpr char kHostHistoryDownloadsDownloadsMenuOpenedMarker[] =
    "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:MENU_OPEN_DOWNLOADS";
constexpr char kHostHistoryDownloadsDownloadsMenuClosedMarker[] =
    "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:MENU_CLOSED_DOWNLOADS";
constexpr char kHostHistoryDownloadsDownloadsNavigatedMarker[] =
    "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:DOWNLOADS_NAVIGATED";
constexpr char kHostHistoryDownloadsPassMarker[] =
    "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:PASS";
constexpr char kHostHistoryDownloadsUrlSwitch[] =
    "wasm-browser-controlled-https-url";
constexpr char kHostHistoryDownloadsFirstJournalUrl[] =
    "https://a.test/m5/m6-ui#wasm_journal=1";
constexpr char kHostHistoryDownloadsSecondJournalUrl[] =
    "https://a.test/m5/m6-ui";
constexpr char kHostHistoryDownloadsRedactedJournalUrl[] =
    "https://a.test/m5/m6-ui";
constexpr char kHostHistoryDownloadsHistoryUrl[] = "chrome://history/";
constexpr char kHostHistoryDownloadsDownloadsUrl[] = "chrome://downloads/";
constexpr char16_t kHostHistoryDownloadsHistoryTitle[] =
    u"History \u2014 Chromium Wasm";
constexpr char16_t kHostHistoryDownloadsDownloadsTitle[] =
    u"Downloads \u2014 Chromium Wasm";
constexpr gfx::Rect kBrowserLifecycleSmokeBounds(0, 0, 640, 480);
constexpr int kMaximumHostPointerCoordinate = 16383;
constexpr base::TimeDelta kHostSecurityWarningInputProtectionMargin =
    base::Milliseconds(1);

bool IsWasmBrowserHostClipboardSmoke() {
  return base::CommandLine::ForCurrentProcess()->HasSwitch(
      "wasm-browser-host-clipboard-smoke");
}

gfx::Point GetHostPointerTarget(BrowserView& browser_view, views::View* view) {
  CHECK(view);
  CHECK(view->GetVisible());
  CHECK(view->GetEnabled());
  browser_view.DeprecatedLayoutImmediately();

  views::Widget* const widget = browser_view.GetWidget();
  CHECK(widget);
  CHECK(widget->IsVisible());
  const gfx::Rect target_bounds = view->GetBoundsInScreen();
  CHECK(!target_bounds.IsEmpty());
  const gfx::Point target = target_bounds.CenterPoint();
  CHECK(widget->GetWindowBoundsInScreen().Contains(target));
  CHECK_GE(target.x(), 0);
  CHECK_LE(target.x(), kMaximumHostPointerCoordinate);
  CHECK_GE(target.y(), 0);
  CHECK_LE(target.y(), kMaximumHostPointerCoordinate);
  return target;
}

bool IsAuraDescendantOf(aura::Window* window, aura::Window* ancestor) {
  CHECK(window);
  CHECK(ancestor);
  for (aura::Window* current = window; current; current = current->parent()) {
    if (current == ancestor) {
      return true;
    }
  }
  return false;
}

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
  // A queued host ABI check stores a callback bound to this coordinator. The
  // close barrier always runs on UI before destruction, so clear it before the
  // coordinator's raw callbacks and Browser weak pointer disappear.
  ClearWasmBrowserHostAcceleratorVerificationForTesting();
  ClearWasmBrowserHostTextSmokeVerificationForTesting();
  ClearWasmBrowserHostClipboardSmokeVerificationForTesting();
  ClearWasmBrowserHostPointerTabSmokeVerificationForTesting();
  ClearWasmBrowserHostPointerMenuSmokeVerificationForTesting();
  ClearWasmBrowserHostSecurityWarningSmokeVerificationForTesting();
  host_security_warning_dialog_interaction_ready_timer_.Stop();
  ClearWasmBrowserHostHistoryDownloadsSmokeVerificationForTesting();
  ClearWasmBrowserHostContinuousFlowSmokeVerificationForTesting();
  host_continuous_flow_.reset();
  ClearWasmBrowserHostTabChurnSmokeVerificationForTesting();
  host_tab_churn_smoke_.reset();
  ClearWasmBrowserHostNavigationChurnSmokeVerificationForTesting();
  host_navigation_churn_smoke_.reset();
  devtools_protocol_smoke_navigation_observer_.reset();
  devtools_protocol_smoke_contents_ = nullptr;
  devtools_protocol_smoke_.reset();
  accessibility_snapshot_smoke_.reset();
  accessibility_snapshot_smoke_navigation_observer_.reset();
  accessibility_snapshot_smoke_contents_ = nullptr;
  ClearWasmBrowserHostStorageEstimateSmokeVerificationForTesting();
  host_storage_estimate_navigation_observer_.reset();
  host_storage_estimate_contents_ = nullptr;
  ClearWasmBrowserHostClipboardTarget();
  ClearWasmBrowserHostTextTarget();
  host_text_navigation_observer_.reset();
  host_text_contents_ = nullptr;
  host_pointer_menu_navigation_observer_.reset();
  host_pointer_menu_contents_ = nullptr;
  host_security_warning_contents_ = nullptr;
  host_history_downloads_first_navigation_observer_.reset();
  host_history_downloads_second_navigation_observer_.reset();
  host_history_downloads_history_navigation_observer_.reset();
  host_history_downloads_downloads_navigation_observer_.reset();
  host_history_downloads_first_contents_ = nullptr;
  host_history_downloads_second_contents_ = nullptr;
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

  // The host never controls this widget identifier. Browser lifecycle owns
  // the single Ozone target and invalidates it before the Browser can be
  // destroyed, so copied text records cannot outlive Aura's TextInputClient.
  views::Widget* const widget = browser_view.GetWidget();
  CHECK(widget);
  aura::Window* const native_window = widget->GetNativeWindow();
  CHECK(native_window);
  aura::WindowTreeHost* const host = native_window->GetHost();
  CHECK(host);
  CHECK(SetWasmBrowserHostTextTarget(host->GetAcceleratedWidget()));
  CHECK(SetWasmBrowserHostClipboardTarget(host->GetAcceleratedWidget()));

  initialized_ = true;
}

void WasmBrowserLifecycle::BeginShutdown() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(browser_);
  CHECK_EQ(browser_manager_->GetSize(), 1u);

  host_security_warning_dialog_interaction_ready_timer_.Stop();
  shutdown_started_ = true;
  ClearWasmBrowserHostClipboardTarget();
  ClearWasmBrowserHostTextTarget();
  browser_->GetWindow()->Close();
}

void WasmBrowserLifecycle::StartHostAcceleratorSmoke() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(!host_accelerator_smoke_started_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(browser_);
  CHECK(IsVisible());

  host_accelerator_smoke_started_ = true;
  SetWasmBrowserHostAcceleratorVerificationForTesting(
      base::BindRepeating(&WasmBrowserLifecycle::VerifyHostAcceleratorDelivery,
                          base::Unretained(this)),
      base::BindOnce(
          &WasmBrowserLifecycle::OnHostAcceleratorDeliveryVerified,
          base::Unretained(this)));
}

void WasmBrowserLifecycle::StartHostTextSmoke() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(!host_text_smoke_started_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(browser_);
  CHECK(IsVisible());

  BrowserView& browser_view = browser_->GetBrowserView();
  WasmTopControlsView* const top_controls = browser_view.wasm_top_controls();
  CHECK(top_controls);
  CHECK(top_controls->address_field_for_testing());
  CHECK(!host_text_contents_);
  host_text_contents_ = browser_view.GetActiveWebContents();
  CHECK(host_text_contents_);
  CHECK(!host_text_navigation_observer_);
  host_text_navigation_observer_ =
      std::make_unique<WasmBrowserHostTextNavigationObserver>(
          host_text_contents_, GURL(kHostTextSmokeUrl),
          base::BindRepeating(
              &WasmBrowserLifecycle::OnHostTextNavigationObserved,
              base::Unretained(this)));

  // Install the observer and verifier before READY. The host may synchronously
  // submit its first trusted DOM Ctrl+L as soon as it sees that marker. The
  // M7 clipboard lane deliberately shares only lifecycle-owned observations;
  // it does not reuse M6's direct TextInputClient insertion protocol.
  host_text_smoke_started_ = true;
  if (IsWasmBrowserHostClipboardSmoke()) {
    SetWasmBrowserHostClipboardSmokeVerificationForTesting(base::BindRepeating(
        &WasmBrowserLifecycle::VerifyHostTextSmokeCheck,
        base::Unretained(this)));
    std::fprintf(stderr, "%s\n", kHostClipboardSmokeReadyMarker);
  } else {
    // The focused M6 proof must establish that two trusted DOM insertText
    // events were each admitted and focus-token-bound before either
    // acknowledgement. This test-only native gate is armed before READY,
    // never by page script.
    CHECK(ArmWasmBrowserHostTextSmokeTwoRecordBarrier());
    SetWasmBrowserHostTextSmokeVerificationForTesting(base::BindRepeating(
        &WasmBrowserLifecycle::VerifyHostTextSmokeCheck,
        base::Unretained(this)));
    std::fprintf(stderr, "%s\n%s\n", kHostTextSmokeBurstArmedMarker,
                 kHostTextSmokeReadyMarker);
  }
  std::fflush(stderr);
}

void WasmBrowserLifecycle::StartHostPointerTabSmoke() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(!host_pointer_tab_smoke_started_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(browser_);
  CHECK(IsVisible());

  BrowserView& browser_view = browser_->GetBrowserView();
  WasmTabStripView* const tab_strip = browser_view.wasm_tab_strip();
  CHECK(tab_strip);
  TabStripModel* const tab_strip_model = browser_->tab_strip_model();
  CHECK(tab_strip_model);
  CHECK_EQ(tab_strip_model->count(), 1);
  CHECK(!host_pointer_tab_second_contents_);
  host_pointer_tab_initial_contents_ = tab_strip_model->GetWebContentsAt(0);
  CHECK(host_pointer_tab_initial_contents_);

  // Install the UI verifier before reporting READY: the real host observes
  // this marker then dispatches trusted DOM pointer events immediately.
  host_pointer_tab_smoke_started_ = true;
  SetWasmBrowserHostPointerTabSmokeVerificationForTesting(
      base::BindRepeating(
          &WasmBrowserLifecycle::VerifyHostPointerTabSmokeCheck,
          base::Unretained(this)),
      base::BindRepeating(
          &WasmBrowserLifecycle::OnHostPointerTabSmokePresented,
          base::Unretained(this)));

  const gfx::Point target = GetHostPointerTarget(
      browser_view, tab_strip->new_tab_button_for_testing());
  std::fprintf(stderr, "%s x=%d y=%d\n", kHostPointerTabsReadyMarker,
               target.x(), target.y());
  std::fflush(stderr);
}

void WasmBrowserLifecycle::StartHostPointerMenuSmoke() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(!host_pointer_menu_smoke_started_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(browser_);
  CHECK(IsVisible());

  BrowserView& browser_view = browser_->GetBrowserView();
  WasmTopControlsView* const top_controls = browser_view.wasm_top_controls();
  WasmBrowserMenuView* const browser_menu =
      browser_view.wasm_browser_menu();
  CHECK(top_controls);
  CHECK(browser_menu);
  CHECK(!browser_menu->IsOpen());
  views::LabelButton* const menu_button =
      top_controls->menu_button_for_testing();
  views::WebView* const contents_web_view = browser_view.contents_web_view();
  CHECK(menu_button);
  CHECK(contents_web_view);

  TabStripModel* const tab_strip_model = browser_->tab_strip_model();
  CHECK(tab_strip_model);
  CHECK_EQ(tab_strip_model->count(), 1);
  CHECK(!host_pointer_menu_contents_);
  CHECK(!host_pointer_menu_navigation_observer_);
  host_pointer_menu_contents_ = tab_strip_model->GetActiveWebContents();
  CHECK(host_pointer_menu_contents_);
  CHECK_EQ(browser_view.GetActiveWebContents(), host_pointer_menu_contents_);

  browser_view.DeprecatedLayoutImmediately();
  host_pointer_menu_closed_contents_y_ = contents_web_view->bounds().y();
  CHECK_GE(host_pointer_menu_closed_contents_y_, 0);

  // The observer is deliberately installed before READY and independent of
  // check stage 2. A fast local WebUI can commit while the host's ordinal
  // callback is still queued; final presentation joins both proofs below.
  host_pointer_menu_navigation_observer_ =
      std::make_unique<WasmBrowserHostPointerMenuNavigationObserver>(
          host_pointer_menu_contents_, GURL(kHostPointerMenuSettingsUrl),
          base::BindRepeating(
              &WasmBrowserLifecycle::OnHostPointerMenuSettingsNavigationObserved,
              base::Unretained(this)));

  host_pointer_menu_smoke_started_ = true;
  SetWasmBrowserHostPointerMenuSmokeVerificationForTesting(
      base::BindRepeating(&WasmBrowserLifecycle::VerifyHostPointerMenuSmokeCheck,
                          base::Unretained(this)),
      base::BindRepeating(
          &WasmBrowserLifecycle::OnHostPointerMenuSmokePresented,
          base::Unretained(this)));

  const gfx::Point target = GetHostPointerTarget(browser_view, menu_button);
  std::fprintf(stderr, "%s x=%d y=%d\n", kHostPointerMenuReadyMarker,
               target.x(), target.y());
  std::fflush(stderr);
}

void WasmBrowserLifecycle::StartHostSecurityWarningSmoke() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(!host_security_warning_smoke_started_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(browser_);
  CHECK(IsVisible());

  BrowserView& browser_view = browser_->GetBrowserView();
  WasmTopControlsView* const top_controls = browser_view.wasm_top_controls();
  WasmBrowserMenuView* const browser_menu =
      browser_view.wasm_browser_menu();
  views::WebView* const contents_web_view = browser_view.contents_web_view();
  CHECK(top_controls);
  CHECK(browser_menu);
  CHECK(contents_web_view);
  CHECK(!browser_menu->IsOpen());
  views::LabelButton* const menu_button =
      top_controls->menu_button_for_testing();
  CHECK(menu_button);

  TabStripModel* const tab_strip_model = browser_->tab_strip_model();
  CHECK(tab_strip_model);
  CHECK_EQ(tab_strip_model->count(), 1);
  CHECK(!host_security_warning_contents_);
  host_security_warning_contents_ = tab_strip_model->GetActiveWebContents();
  CHECK(host_security_warning_contents_);
  CHECK_EQ(browser_view.GetActiveWebContents(),
           host_security_warning_contents_);
  CHECK(!tab_strip_model->IsTabBlocked(0));
  tabs::TabInterface* const active_tab = tab_strip_model->GetActiveTab();
  CHECK(active_tab);
  CHECK_EQ(active_tab->GetContents(), host_security_warning_contents_);
  CHECK(!active_tab->IsBlocked());

  WasmBrowserSecurityWarningDialog* const warning_dialog =
      browser_->wasm_security_warning_dialog_for_testing();
  CHECK(warning_dialog);
  CHECK(!warning_dialog->dialog_widget_for_testing());
  CHECK(!warning_dialog->dialog_web_contents_for_testing());
  web_modal::WebContentsModalDialogManager* const modal_manager =
      web_modal::WebContentsModalDialogManager::FromWebContents(
          host_security_warning_contents_);
  CHECK(modal_manager);
  CHECK_EQ(modal_manager->delegate(), warning_dialog);
  CHECK(!modal_manager->IsDialogActive());
  CHECK(!host_security_warning_menu_presentation_verified_);
  CHECK(!host_security_warning_dialog_interaction_ready_);
  CHECK(!host_security_warning_dialog_interaction_ready_timer_.IsRunning());
  host_security_warning_blocked_state_change_count_ =
      warning_dialog->blocked_state_change_count_for_testing();

  host_security_warning_smoke_started_ = true;
  SetWasmBrowserHostSecurityWarningSmokeVerificationForTesting(
      base::BindRepeating(
          &WasmBrowserLifecycle::VerifyHostSecurityWarningSmokeCheck,
          base::Unretained(this)),
      base::BindRepeating(
          &WasmBrowserLifecycle::OnHostSecurityWarningSmokePresented,
          base::Unretained(this)));

  const gfx::Point target = GetHostPointerTarget(browser_view, menu_button);
  std::fprintf(stderr, "%s x=%d y=%d\n", kHostSecurityWarningReadyMarker,
               target.x(), target.y());
  std::fflush(stderr);
}

void WasmBrowserLifecycle::StartHostHistoryDownloadsSmoke() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(!host_history_downloads_smoke_started_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(browser_);
  CHECK(IsVisible());

  // This route is activated only by chrome_wasm_m6_https_test. Production
  // chrome_wasm rejects its switch before this lifecycle exists and never
  // installs the local trust root. Keep the controlled root contract explicit
  // here as a second boundary: host DOM input can choose neither a journal
  // destination nor an arbitrary WebUI URL through this ordinal verifier.
  const base::CommandLine* const command_line =
      base::CommandLine::ForCurrentProcess();
  CHECK(command_line);
  CHECK_EQ(command_line->GetSwitchValueASCII(kHostHistoryDownloadsUrlSwitch),
           kHostHistoryDownloadsSecondJournalUrl);

  BrowserView& browser_view = browser_->GetBrowserView();
  WasmTabStripView* const tab_strip = browser_view.wasm_tab_strip();
  WasmTopControlsView* const top_controls = browser_view.wasm_top_controls();
  WasmBrowserMenuView* const browser_menu =
      browser_view.wasm_browser_menu();
  views::WebView* const contents_web_view = browser_view.contents_web_view();
  CHECK(tab_strip);
  CHECK(top_controls);
  CHECK(top_controls->address_field_for_testing());
  CHECK(browser_menu);
  CHECK(!browser_menu->IsOpen());
  CHECK(contents_web_view);

  TabStripModel* const tab_strip_model = browser_->tab_strip_model();
  CHECK(tab_strip_model);
  CHECK_EQ(tab_strip_model->count(), 1);
  CHECK(!host_history_downloads_first_contents_);
  CHECK(!host_history_downloads_second_contents_);
  CHECK(!host_history_downloads_first_navigation_observer_);
  CHECK(!host_history_downloads_second_navigation_observer_);
  CHECK(!host_history_downloads_history_navigation_observer_);
  CHECK(!host_history_downloads_downloads_navigation_observer_);

  host_history_downloads_first_contents_ =
      tab_strip_model->GetActiveWebContents();
  CHECK(host_history_downloads_first_contents_);
  CHECK_EQ(browser_view.GetActiveWebContents(),
           host_history_downloads_first_contents_);

  browser_view.DeprecatedLayoutImmediately();
  host_history_downloads_closed_contents_y_ = contents_web_view->bounds().y();
  CHECK_GE(host_history_downloads_closed_contents_y_, 0);

  // Arm the first typed-navigation observer before READY. The host's first
  // trusted Ctrl+L / insertText / Enter transaction may begin as soon as it
  // consumes this marker.
  host_history_downloads_first_navigation_observer_ =
      std::make_unique<WasmBrowserHostHistoryDownloadsNavigationObserver>(
          host_history_downloads_first_contents_,
          GURL(kHostHistoryDownloadsFirstJournalUrl),
          WasmBrowserHostHistoryDownloadsNavigationObserver::
              ExpectedNavigation::kTypedUser,
          base::BindRepeating(
              &WasmBrowserLifecycle::OnHostHistoryDownloadsFirstNavigationObserved,
              base::Unretained(this)));

  host_history_downloads_smoke_started_ = true;
  SetWasmBrowserHostHistoryDownloadsSmokeVerificationForTesting(
      base::BindRepeating(
          &WasmBrowserLifecycle::VerifyHostHistoryDownloadsSmokeCheck,
          base::Unretained(this)),
      base::BindRepeating(
          &WasmBrowserLifecycle::OnHostHistoryDownloadsSmokePresented,
          base::Unretained(this)));
  std::fprintf(stderr, "%s\n", kHostHistoryDownloadsReadyMarker);
  std::fflush(stderr);
}

void WasmBrowserLifecycle::StartHostContinuousFlowSmoke() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(browser_);
  CHECK(IsVisible());
  CHECK(!host_continuous_flow_);

  const base::CommandLine* const command_line =
      base::CommandLine::ForCurrentProcess();
  CHECK(command_line);
  const bool restart_only = command_line->HasSwitch(
      "wasm-browser-host-continuous-flow-restart-smoke");
  host_continuous_flow_ = std::make_unique<WasmBrowserContinuousFlow>(
      browser_.get(), restart_only,
      base::BindRepeating(&WasmBrowserLifecycle::BeginShutdown,
                          base::Unretained(this)));
  host_continuous_flow_->Start();
}

void WasmBrowserLifecycle::StartHostTabChurnSmoke() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(browser_);
  CHECK(IsVisible());
  CHECK(!host_tab_churn_smoke_);

  host_tab_churn_smoke_ = std::make_unique<WasmBrowserTabChurnSmoke>(
      browser_.get(),
      base::BindRepeating(&WasmBrowserLifecycle::BeginShutdown,
                          base::Unretained(this)));
  host_tab_churn_smoke_->Start();
}

void WasmBrowserLifecycle::StartHostNavigationChurnSmoke() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(browser_);
  CHECK(IsVisible());
  CHECK(!host_navigation_churn_smoke_);

  host_navigation_churn_smoke_ =
      std::make_unique<WasmBrowserNavigationChurnSmoke>(
          browser_.get(),
          base::BindOnce(&WasmBrowserLifecycle::BeginNavigationChurnShutdown,
                         weak_ptr_factory_.GetWeakPtr()));
  host_navigation_churn_smoke_->Start();
}

void WasmBrowserLifecycle::StartHostStorageEstimateSmoke() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(browser_);
  CHECK(IsVisible());
  CHECK(!host_storage_estimate_smoke_started_);
  CHECK(!host_storage_estimate_navigation_observer_);

  // Install before READY. The host may already have an accepted deferred
  // estimate result when it sees this marker, but can submit only fixed stage
  // one; this lifecycle owns the exact Settings URL and navigation call.
  host_storage_estimate_smoke_started_ = true;
  SetWasmBrowserHostStorageEstimateSmokeVerificationForTesting(
      base::BindRepeating(
          &WasmBrowserLifecycle::VerifyHostStorageEstimateSmokeCheck,
          base::Unretained(this)),
      base::BindRepeating(
          &WasmBrowserLifecycle::OnHostStorageEstimateSmokePresented,
          base::Unretained(this)));
  std::fprintf(stderr, "%s\n", kHostStorageEstimateSmokeReadyMarker);
  std::fflush(stderr);
}

void WasmBrowserLifecycle::StartDevToolsProtocolSmoke() {
  StartDevToolsProtocolSmokeInternal(
      WasmBrowserDevToolsProtocolSmokeMode::kPageWebAssemblyUnavailable);
}

void WasmBrowserLifecycle::StartPageWebAssemblyDevToolsProtocolSmoke() {
  StartDevToolsProtocolSmokeInternal(
      WasmBrowserDevToolsProtocolSmokeMode::kValidateModuleInstanceAdd42);
}

void WasmBrowserLifecycle::StartPageWebAssemblyMemoryDevToolsProtocolSmoke() {
  StartDevToolsProtocolSmokeInternal(
      WasmBrowserDevToolsProtocolSmokeMode::kMemoryImportReadWrite);
}

void WasmBrowserLifecycle::StartDevToolsProtocolSmokeInternal(
    WasmBrowserDevToolsProtocolSmokeMode mode) {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(browser_);
  CHECK(IsVisible());
  CHECK(!devtools_protocol_smoke_started_);
  CHECK(!devtools_protocol_smoke_succeeded_);
  CHECK(!devtools_protocol_smoke_contents_);
  CHECK(!devtools_protocol_smoke_navigation_observer_);
  CHECK(!devtools_protocol_smoke_);

  // The lifecycle owns exactly one active top-level tab. Pin the direct
  // client to that primary WebContents rather than discovering targets or
  // accepting an ID from the host page.
  TabStripModel* const tab_strip_model = browser_->tab_strip_model();
  CHECK(tab_strip_model);
  CHECK_EQ(tab_strip_model->count(), 1);
  content::WebContents* const contents =
      tab_strip_model->GetActiveWebContents();
  CHECK(contents);
  CHECK_EQ(contents, contents->GetOutermostWebContents());
  CHECK(contents->GetPrimaryMainFrame());
  CHECK_EQ(browser_->GetBrowserView().GetActiveWebContents(), contents);

  const GURL smoke_url = GetWasmBrowserDevToolsProtocolSmokeUrl(mode);
  CHECK(smoke_url.is_valid());
  devtools_protocol_smoke_started_ = true;
  devtools_protocol_smoke_mode_ = mode;
  devtools_protocol_smoke_contents_ = contents;
  devtools_protocol_smoke_navigation_observer_ =
      std::make_unique<WasmBrowserDevToolsProtocolNavigationObserver>(
          contents, smoke_url,
          base::BindRepeating(
              &WasmBrowserLifecycle::OnDevToolsProtocolSmokeNavigationObserved,
              base::Unretained(this)));

  content::NavigationController::LoadURLParams params(smoke_url);
  params.transition_type = ui::PAGE_TRANSITION_GENERATED;
  const base::WeakPtr<content::NavigationHandle> navigation_handle =
      contents->GetController().LoadURLWithParams(params);
  CHECK(navigation_handle);
}

void WasmBrowserLifecycle::OnDevToolsProtocolSmokeNavigationObserved() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(devtools_protocol_smoke_started_);
  CHECK(!devtools_protocol_smoke_succeeded_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(browser_);
  CHECK(devtools_protocol_smoke_contents_);
  CHECK(devtools_protocol_smoke_navigation_observer_);
  CHECK(!devtools_protocol_smoke_);

  content::WebContents* const contents = devtools_protocol_smoke_contents_;
  CHECK_EQ(browser_->GetBrowserView().GetActiveWebContents(), contents);
  CHECK_EQ(contents->GetOutermostWebContents(), contents);
  content::RenderFrameHost* const primary_main_frame =
      contents->GetPrimaryMainFrame();
  CHECK(primary_main_frame);
  CHECK(primary_main_frame->IsRenderFrameLive());
  const GURL expected_url =
      GetWasmBrowserDevToolsProtocolSmokeUrl(devtools_protocol_smoke_mode_);
  CHECK_EQ(contents->GetLastCommittedURL(), expected_url);

  devtools_protocol_smoke_navigation_observer_.reset();
  devtools_protocol_smoke_ = std::make_unique<WasmBrowserDevToolsProtocolSmoke>(
      devtools_protocol_smoke_mode_,
      base::BindOnce(&WasmBrowserLifecycle::OnDevToolsProtocolSmokeSucceeded,
                     weak_ptr_factory_.GetWeakPtr()));
  devtools_protocol_smoke_->Start(contents);
}

void WasmBrowserLifecycle::OnDevToolsProtocolSmokeSucceeded() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(devtools_protocol_smoke_started_);
  CHECK(!devtools_protocol_smoke_succeeded_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(browser_);
  CHECK(devtools_protocol_smoke_);
  // The direct client emits its success marker first and its detached marker
  // only after DetachClient succeeds. Do not permit Browser close until that
  // barrier is observable and the client has no agent-host reference.
  CHECK(devtools_protocol_smoke_->IsDetached());

  devtools_protocol_smoke_succeeded_ = true;
  // Network.enable can complete synchronously during Start(). Defer Browser
  // close to the next UI turn so its did-close observer cannot destroy the
  // still-returning direct protocol client.
  CHECK(base::SingleThreadTaskRunner::GetCurrentDefault()->PostTask(
      FROM_HERE,
      base::BindOnce(&WasmBrowserLifecycle::BeginDevToolsProtocolSmokeShutdown,
                     weak_ptr_factory_.GetWeakPtr())));
}

void WasmBrowserLifecycle::BeginDevToolsProtocolSmokeShutdown() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  // A direct Browser close can win the posted turn. The did-close path has
  // already armed the normal physical-destruction barrier in that case, so
  // this deferred test-only shutdown must be inert rather than re-entering
  // BeginShutdown's one-shot state machine.
  if (shutdown_started_ || shutdown_complete_ || !browser_) {
    return;
  }
  BeginShutdown();
}

void WasmBrowserLifecycle::StartAccessibilitySnapshotSmoke() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(browser_);
  CHECK(IsVisible());
  CHECK(!accessibility_snapshot_smoke_started_);
  CHECK(!accessibility_snapshot_smoke_completion_received_);
  CHECK(!accessibility_snapshot_smoke_succeeded_);
  CHECK(!accessibility_snapshot_smoke_contents_);
  CHECK(!accessibility_snapshot_smoke_navigation_observer_);
  CHECK(!accessibility_snapshot_smoke_);

  // The lifecycle owns exactly one active top-level tab. The snapshot is
  // pinned to it and to the fixed document below; no host input selects a
  // renderer, frame, URL, semantic text, or AX action.
  TabStripModel* const tab_strip_model = browser_->tab_strip_model();
  CHECK(tab_strip_model);
  CHECK_EQ(tab_strip_model->count(), 1);
  content::WebContents* const contents =
      tab_strip_model->GetActiveWebContents();
  CHECK(contents);
  CHECK_EQ(contents, contents->GetOutermostWebContents());
  CHECK(contents->GetPrimaryMainFrame());
  CHECK_EQ(browser_->GetBrowserView().GetActiveWebContents(), contents);

  const GURL smoke_url(GetWasmBrowserAccessibilitySnapshotSmokeUrl());
  CHECK(smoke_url.is_valid());
  accessibility_snapshot_smoke_started_ = true;
  accessibility_snapshot_smoke_contents_ = contents;
  accessibility_snapshot_smoke_navigation_observer_ =
      std::make_unique<WasmBrowserAccessibilitySnapshotNavigationObserver>(
          contents, smoke_url,
          base::BindRepeating(
              &WasmBrowserLifecycle::OnAccessibilitySnapshotSmokeNavigationObserved,
              weak_ptr_factory_.GetWeakPtr()));

  std::fprintf(stderr, "%s\n", kAccessibilitySnapshotSmokeReadyMarker);
  std::fflush(stderr);

  content::NavigationController::LoadURLParams params(smoke_url);
  params.transition_type = ui::PAGE_TRANSITION_GENERATED;
  const base::WeakPtr<content::NavigationHandle> navigation_handle =
      contents->GetController().LoadURLWithParams(params);
  CHECK(navigation_handle);
}

void WasmBrowserLifecycle::OnAccessibilitySnapshotSmokeNavigationObserved() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(accessibility_snapshot_smoke_started_);
  CHECK(!accessibility_snapshot_smoke_completion_received_);
  CHECK(!accessibility_snapshot_smoke_succeeded_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(browser_);
  CHECK(accessibility_snapshot_smoke_contents_);
  CHECK(accessibility_snapshot_smoke_navigation_observer_);
  CHECK(!accessibility_snapshot_smoke_);

  content::WebContents* const contents = accessibility_snapshot_smoke_contents_;
  CHECK_EQ(browser_->GetBrowserView().GetActiveWebContents(), contents);
  CHECK_EQ(contents->GetOutermostWebContents(), contents);
  content::RenderFrameHost* const primary_main_frame =
      contents->GetPrimaryMainFrame();
  CHECK(primary_main_frame);
  CHECK(primary_main_frame->IsRenderFrameLive());
  CHECK_EQ(contents->GetLastCommittedURL(),
           GetWasmBrowserAccessibilitySnapshotSmokeUrl());
  CHECK(contents->CompletedFirstVisuallyNonEmptyPaint());
  CHECK(!contents->IsLoading());

  std::fprintf(stderr, "%s\n", kAccessibilitySnapshotSmokeNavigatedMarker);
  std::fflush(stderr);
  accessibility_snapshot_smoke_navigation_observer_.reset();
  accessibility_snapshot_smoke_ =
      std::make_unique<WasmBrowserAccessibilitySnapshotSmoke>(
          base::BindOnce(&WasmBrowserLifecycle::OnAccessibilitySnapshotSmokeCompleted,
                         weak_ptr_factory_.GetWeakPtr()));
  accessibility_snapshot_smoke_->Start(contents);
}

void WasmBrowserLifecycle::OnAccessibilitySnapshotSmokeCompleted(bool success) {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (accessibility_snapshot_smoke_completion_received_) {
    return;
  }
  accessibility_snapshot_smoke_completion_received_ = true;

  if (success) {
    if (shutdown_started_ || shutdown_complete_ || !browser_ ||
        !accessibility_snapshot_smoke_ ||
        !accessibility_snapshot_smoke_contents_ ||
        browser_->GetBrowserView().GetActiveWebContents() !=
            accessibility_snapshot_smoke_contents_) {
      return;
    }
    accessibility_snapshot_smoke_succeeded_ = true;
    std::fprintf(stderr, "%s\n", kAccessibilitySnapshotSmokePassMarker);
    std::fflush(stderr);
  }

  // RequestAXTreeSnapshot can complete during callback dispatch. Defer close
  // so the smoke's completion stack can return before teardown resets the
  // owner that invalidates any late renderer reply.
  CHECK(base::SingleThreadTaskRunner::GetCurrentDefault()->PostTask(
      FROM_HERE,
      base::BindOnce(
          &WasmBrowserLifecycle::BeginAccessibilitySnapshotSmokeShutdown,
          weak_ptr_factory_.GetWeakPtr())));
}

void WasmBrowserLifecycle::BeginAccessibilitySnapshotSmokeShutdown() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  // A direct Browser close can win the posted turn. Its did-close route has
  // already reset the one-shot snapshot owner and armed the normal physical
  // destruction barrier, so do not re-enter the lifecycle state machine.
  if (shutdown_started_ || shutdown_complete_ || !browser_) {
    return;
  }
  BeginShutdown();
}

bool WasmBrowserLifecycle::VerifyHostStorageEstimateSmokeCheck(int stage) {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (stage != 1 || !host_storage_estimate_smoke_started_ ||
      host_storage_estimate_check_verified_ || shutdown_started_ ||
      shutdown_complete_ || !browser_ ||
      host_storage_estimate_navigation_observer_) {
    return false;
  }

  const scoped_refptr<const WasmBrowserHostStorageEstimateSnapshot> snapshot =
      GetWasmBrowserHostStorageEstimateSnapshot();
  if (!snapshot || snapshot->state() !=
                       WasmBrowserHostStorageEstimateSnapshot::State::kAvailable ||
      snapshot->generation() == 0 ||
      snapshot->usage_bytes() > snapshot->quota_bytes()) {
    return false;
  }

  BrowserView& browser_view = browser_->GetBrowserView();
  content::WebContents* const contents = browser_view.GetActiveWebContents();
  if (!contents || contents->IsBeingDestroyed()) {
    return false;
  }

  const GURL settings_url(kHostStorageEstimateSettingsUrl);
  CHECK(settings_url.is_valid());
  host_storage_estimate_generation_ = snapshot->generation();
  host_storage_estimate_usage_bytes_ = snapshot->usage_bytes();
  host_storage_estimate_quota_bytes_ = snapshot->quota_bytes();
  host_storage_estimate_contents_ = contents;
  host_storage_estimate_navigation_observer_ =
      std::make_unique<WasmBrowserHostStorageEstimateNavigationObserver>(
          contents, settings_url,
          base::BindRepeating(
              &WasmBrowserLifecycle::OnHostStorageEstimateSettingsNavigationObserved,
              base::Unretained(this)));

  content::NavigationController::LoadURLParams params(settings_url);
  // This is a fixed, switch-gated test navigation, not a reported host
  // gesture. Do not synthesize a user gesture or let the host choose a URL.
  params.transition_type = ui::PAGE_TRANSITION_GENERATED;
  // A local chrome:// WebUI can synchronously commit during LoadURLWithParams.
  // Mark the prerequisite before initiation so the one-shot observer can join
  // that commit to the immutable snapshot check; roll it back on rejection.
  host_storage_estimate_check_verified_ = true;
  const base::WeakPtr<content::NavigationHandle> navigation_handle =
      contents->GetController().LoadURLWithParams(params);
  if (!navigation_handle) {
    host_storage_estimate_check_verified_ = false;
    host_storage_estimate_navigation_observer_.reset();
    host_storage_estimate_contents_ = nullptr;
    return false;
  }
  return true;
}

void WasmBrowserLifecycle::OnHostStorageEstimateSettingsNavigationObserved() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!host_storage_estimate_smoke_started_ ||
      !host_storage_estimate_check_verified_ ||
      host_storage_estimate_navigation_verified_ || shutdown_started_ ||
      shutdown_complete_ || !browser_ || !host_storage_estimate_contents_) {
    return;
  }

  BrowserView& browser_view = browser_->GetBrowserView();
  if (browser_view.GetActiveWebContents() != host_storage_estimate_contents_ ||
      host_storage_estimate_contents_->GetLastCommittedURL() !=
          GURL(kHostStorageEstimateSettingsUrl) ||
      host_storage_estimate_contents_->GetTitle() !=
          kHostStorageEstimateSettingsTitle) {
    return;
  }

  content::WebUI* const settings_web_ui =
      host_storage_estimate_contents_->GetWebUI();
  content::WebUIConfig* const settings_web_ui_config =
      settings_web_ui ? settings_web_ui->GetWebUIConfig() : nullptr;
  content::WebUIController* const settings_web_ui_controller =
      settings_web_ui ? settings_web_ui->GetController() : nullptr;
  WasmSettingsUI* const settings_ui = settings_web_ui_controller
                                          ? settings_web_ui_controller
                                                ->GetAs<WasmSettingsUI>()
                                          : nullptr;
  const scoped_refptr<const WasmBrowserHostStorageEstimateSnapshot>
      controller_snapshot = settings_ui
                                ? settings_ui->GetStorageEstimateSnapshotForTesting()
                                : nullptr;
  if (!settings_web_ui_config || !settings_web_ui_controller || !settings_ui ||
      !controller_snapshot ||
      settings_web_ui_config->scheme() != content::kChromeUIScheme ||
      settings_web_ui_config->host() != "settings" ||
      settings_ui->web_ui() != settings_web_ui ||
      controller_snapshot->state() !=
          WasmBrowserHostStorageEstimateSnapshot::State::kAvailable ||
      controller_snapshot->generation() != host_storage_estimate_generation_ ||
      controller_snapshot->usage_bytes() != host_storage_estimate_usage_bytes_ ||
      controller_snapshot->quota_bytes() != host_storage_estimate_quota_bytes_) {
    return;
  }

  host_storage_estimate_navigation_verified_ = true;
  std::fprintf(stderr, "%s\n", kHostStorageEstimateSmokeNavigatedMarker);
  std::fflush(stderr);
  // A host callback can finish only after it observes a strictly later canvas
  // frame. That makes the result proof include native Settings presentation,
  // not just controller construction or a committed URL.
  browser_view.SchedulePaint();
}

bool WasmBrowserLifecycle::OnHostStorageEstimateSmokePresented(int stage) {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (stage != 2 || !host_storage_estimate_smoke_started_ ||
      !host_storage_estimate_check_verified_ ||
      !host_storage_estimate_navigation_verified_ || shutdown_started_ ||
      shutdown_complete_ || !browser_ || !host_storage_estimate_contents_ ||
      browser_->GetBrowserView().GetActiveWebContents() !=
          host_storage_estimate_contents_) {
    return false;
  }

  std::fprintf(stderr, "%s\n", kHostStorageEstimateSmokePassMarker);
  std::fflush(stderr);
  BeginShutdown();
  return true;
}

bool WasmBrowserLifecycle::IsVisible() const {
  CHECK(initialized_);
  CHECK(!shutdown_complete_);
  CHECK(browser_);
  return browser_->GetBrowserView().IsVisible();
}

void WasmBrowserLifecycle::BeginNavigationChurnShutdown() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  // The coordinator posts this weak callback after its own verification stack
  // returns. A direct Browser close can win that turn and reset/destroy the
  // coordinator, so leave the lifecycle's one-shot close state untouched.
  if (shutdown_started_ || shutdown_complete_ || !browser_) {
    return;
  }
  BeginShutdown();
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
  ClearWasmBrowserHostAcceleratorVerificationForTesting();
  ClearWasmBrowserHostTextSmokeVerificationForTesting();
  ClearWasmBrowserHostClipboardSmokeVerificationForTesting();
  ClearWasmBrowserHostPointerTabSmokeVerificationForTesting();
  ClearWasmBrowserHostPointerMenuSmokeVerificationForTesting();
  ClearWasmBrowserHostSecurityWarningSmokeVerificationForTesting();
  host_security_warning_dialog_interaction_ready_timer_.Stop();
  ClearWasmBrowserHostHistoryDownloadsSmokeVerificationForTesting();
  ClearWasmBrowserHostContinuousFlowSmokeVerificationForTesting();
  host_continuous_flow_.reset();
  ClearWasmBrowserHostTabChurnSmokeVerificationForTesting();
  host_tab_churn_smoke_.reset();
  ClearWasmBrowserHostNavigationChurnSmokeVerificationForTesting();
  host_navigation_churn_smoke_.reset();
  devtools_protocol_smoke_navigation_observer_.reset();
  devtools_protocol_smoke_contents_ = nullptr;
  devtools_protocol_smoke_.reset();
  accessibility_snapshot_smoke_.reset();
  accessibility_snapshot_smoke_navigation_observer_.reset();
  accessibility_snapshot_smoke_contents_ = nullptr;
  ClearWasmBrowserHostStorageEstimateSmokeVerificationForTesting();
  host_storage_estimate_navigation_observer_.reset();
  host_storage_estimate_contents_ = nullptr;
  ClearWasmBrowserHostClipboardTarget();
  ClearWasmBrowserHostTextTarget();
  host_text_navigation_observer_.reset();
  host_text_contents_ = nullptr;
  host_pointer_menu_navigation_observer_.reset();
  host_pointer_menu_contents_ = nullptr;
  host_security_warning_contents_ = nullptr;
  host_history_downloads_first_navigation_observer_.reset();
  host_history_downloads_second_navigation_observer_.reset();
  host_history_downloads_history_navigation_observer_.reset();
  host_history_downloads_downloads_navigation_observer_.reset();
  host_history_downloads_first_contents_ = nullptr;
  host_history_downloads_second_contents_ = nullptr;
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

  ClearWasmBrowserHostAcceleratorVerificationForTesting();
  ClearWasmBrowserHostTextSmokeVerificationForTesting();
  ClearWasmBrowserHostClipboardSmokeVerificationForTesting();
  ClearWasmBrowserHostPointerTabSmokeVerificationForTesting();
  ClearWasmBrowserHostPointerMenuSmokeVerificationForTesting();
  ClearWasmBrowserHostSecurityWarningSmokeVerificationForTesting();
  host_security_warning_dialog_interaction_ready_timer_.Stop();
  ClearWasmBrowserHostHistoryDownloadsSmokeVerificationForTesting();
  ClearWasmBrowserHostContinuousFlowSmokeVerificationForTesting();
  host_continuous_flow_.reset();
  ClearWasmBrowserHostTabChurnSmokeVerificationForTesting();
  host_tab_churn_smoke_.reset();
  ClearWasmBrowserHostNavigationChurnSmokeVerificationForTesting();
  host_navigation_churn_smoke_.reset();
  devtools_protocol_smoke_navigation_observer_.reset();
  devtools_protocol_smoke_contents_ = nullptr;
  devtools_protocol_smoke_.reset();
  accessibility_snapshot_smoke_.reset();
  accessibility_snapshot_smoke_navigation_observer_.reset();
  accessibility_snapshot_smoke_contents_ = nullptr;
  ClearWasmBrowserHostStorageEstimateSmokeVerificationForTesting();
  host_storage_estimate_navigation_observer_.reset();
  host_storage_estimate_contents_ = nullptr;
  ClearWasmBrowserHostClipboardTarget();
  ClearWasmBrowserHostTextTarget();
  host_text_navigation_observer_.reset();
  host_text_contents_ = nullptr;
  host_pointer_menu_navigation_observer_.reset();
  host_pointer_menu_contents_ = nullptr;
  host_security_warning_contents_ = nullptr;
  host_history_downloads_first_navigation_observer_.reset();
  host_history_downloads_second_navigation_observer_.reset();
  host_history_downloads_history_navigation_observer_.reset();
  host_history_downloads_downloads_navigation_observer_.reset();
  host_history_downloads_first_contents_ = nullptr;
  host_history_downloads_second_contents_ = nullptr;

  // This callback may reset and destroy this lifecycle in main-parts.
  std::move(shutdown_complete_callback_).Run();
}

bool WasmBrowserLifecycle::VerifyHostAcceleratorDelivery() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(host_accelerator_smoke_started_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(browser_);

  BrowserView& browser_view = browser_->GetBrowserView();
  WasmTopControlsView* const top_controls =
      browser_view.wasm_top_controls();
  CHECK(top_controls);
  views::Textfield* const address_field =
      top_controls->address_field_for_testing();
  CHECK(address_field);

  // Ctrl+L is intentionally the first host proof: it has an unambiguous
  // visible focus and selection result, while navigation and tab commands
  // remain covered by the richer Views routing smoke.
  return address_field->HasFocus() && !address_field->GetText().empty() &&
         address_field->GetSelectedText() == address_field->GetText();
}

void WasmBrowserLifecycle::OnHostAcceleratorDeliveryVerified() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(initialized_);
  CHECK(host_accelerator_smoke_started_);
  CHECK(!shutdown_started_);
  CHECK(!shutdown_complete_);
  CHECK(VerifyHostAcceleratorDelivery());

  std::fprintf(stderr, "%s\n", kHostAcceleratorsSmokeMarker);
  std::fflush(stderr);
  BeginShutdown();
}

bool WasmBrowserLifecycle::VerifyHostTextSmokeCheck(int stage) {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!host_text_smoke_started_ || shutdown_started_ || shutdown_complete_ ||
      !browser_ || !host_text_contents_) {
    return false;
  }

  BrowserView& browser_view = browser_->GetBrowserView();
  if (browser_view.GetActiveWebContents() != host_text_contents_) {
    return false;
  }
  WasmTopControlsView* const top_controls = browser_view.wasm_top_controls();
  views::Textfield* const address_field =
      top_controls ? top_controls->address_field_for_testing() : nullptr;
  if (!address_field) {
    return false;
  }

  if (stage == 1) {
    if (host_text_focus_verified_ || !address_field->HasFocus() ||
        address_field->GetText().empty() ||
        address_field->GetSelectedText() != address_field->GetText()) {
      return false;
    }
    host_text_focus_verified_ = true;
    std::fprintf(stderr, "%s\n",
                 IsWasmBrowserHostClipboardSmoke()
                     ? kHostClipboardSmokeFocusedMarker
                     : kHostTextSmokeFocusedMarker);
    std::fflush(stderr);
    browser_view.SchedulePaint();
    return true;
  }

  if (stage == 2) {
    if (!host_text_focus_verified_ || host_text_inserted_verified_ ||
        !address_field->HasFocus() ||
        address_field->GetText() != u"chrome://version/") {
      return false;
    }
    host_text_inserted_verified_ = true;
    std::fprintf(stderr, "%s\n",
                 IsWasmBrowserHostClipboardSmoke()
                     ? kHostClipboardSmokePastedMarker
                     : kHostTextSmokeInsertedMarker);
    std::fflush(stderr);
    browser_view.SchedulePaint();
    return true;
  }

  if (stage == 3) {
    if (!host_text_inserted_verified_ || !host_text_navigation_observed_ ||
        address_field->HasFocus() ||
        host_text_contents_->GetLastCommittedURL() !=
            GURL(kHostTextSmokeUrl) ||
        address_field->GetText() != u"chrome://version/") {
      return false;
    }
    std::fprintf(stderr, "%s\n",
                 IsWasmBrowserHostClipboardSmoke()
                     ? kHostClipboardSmokePassMarker
                     : kHostTextSmokePassMarker);
    std::fflush(stderr);
    BeginShutdown();
    return true;
  }

  return false;
}

void WasmBrowserLifecycle::OnHostTextNavigationObserved() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!host_text_smoke_started_ || shutdown_started_ || shutdown_complete_ ||
      !browser_ || !host_text_contents_ || host_text_navigation_observed_) {
    return;
  }
  BrowserView& browser_view = browser_->GetBrowserView();
  if (browser_view.GetActiveWebContents() != host_text_contents_ ||
      host_text_contents_->GetLastCommittedURL() != GURL(kHostTextSmokeUrl)) {
    return;
  }
  host_text_navigation_observed_ = true;
  std::fprintf(stderr, "%s\n",
               IsWasmBrowserHostClipboardSmoke()
                   ? kHostClipboardSmokeNavigatedMarker
                   : kHostTextSmokeNavigatedMarker);
  std::fflush(stderr);
  browser_view.SchedulePaint();
}

bool WasmBrowserLifecycle::VerifyHostPointerTabSmokeCheck(int stage) {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!host_pointer_tab_smoke_started_ || shutdown_started_ ||
      shutdown_complete_ || !browser_ || !host_pointer_tab_initial_contents_) {
    return false;
  }

  TabStripModel* const tab_strip_model = browser_->tab_strip_model();
  if (!tab_strip_model) {
    return false;
  }
  BrowserView& browser_view = browser_->GetBrowserView();
  WasmTabStripView* const tab_strip = browser_view.wasm_tab_strip();
  if (!tab_strip) {
    return false;
  }

  if (stage == 1) {
    if (host_pointer_tab_insert_verified_ || tab_strip_model->count() != 2 ||
        tab_strip_model->GetWebContentsAt(0) !=
            host_pointer_tab_initial_contents_) {
      return false;
    }

    content::WebContents* const second_contents =
        tab_strip_model->GetWebContentsAt(1);
    if (!second_contents || second_contents == host_pointer_tab_initial_contents_ ||
        tab_strip_model->active_index() != 1 ||
        tab_strip_model->GetActiveWebContents() != second_contents ||
        browser_view.GetActiveWebContents() != second_contents) {
      return false;
    }

    const gfx::Point target = GetHostPointerTarget(
        browser_view, tab_strip->tab_button_for_testing(0));
    host_pointer_tab_second_contents_ = second_contents;
    host_pointer_tab_insert_verified_ = true;
    std::fprintf(stderr, "%s x=%d y=%d\n", kHostPointerTabsInsertedMarker,
                 target.x(), target.y());
    std::fflush(stderr);
    // The host must observe a canvas frame after this model action before it
    // dispatches the second trusted DOM click.
    browser_view.SchedulePaint();
    return true;
  }

  if (stage == 2) {
    if (!host_pointer_tab_insert_verified_ ||
        host_pointer_tab_first_selection_verified_ ||
        tab_strip_model->count() != 2 ||
        tab_strip_model->GetWebContentsAt(0) !=
            host_pointer_tab_initial_contents_ ||
        tab_strip_model->GetWebContentsAt(1) !=
            host_pointer_tab_second_contents_ ||
        tab_strip_model->active_index() != 0 ||
        tab_strip_model->GetActiveWebContents() !=
            host_pointer_tab_initial_contents_ ||
        browser_view.GetActiveWebContents() !=
            host_pointer_tab_initial_contents_) {
      return false;
    }

    const gfx::Point target = GetHostPointerTarget(
        browser_view, tab_strip->tab_button_for_testing(1));
    host_pointer_tab_first_selection_verified_ = true;
    std::fprintf(stderr, "%s x=%d y=%d\n",
                 kHostPointerTabsFirstSelectedMarker, target.x(), target.y());
    std::fflush(stderr);
    // The host waits for this presentation before it dispatches the second
    // trusted tab-selector click. This keeps both selection assertions tied
    // to a visibly updated Chromium BrowserView rather than only model state.
    browser_view.SchedulePaint();
    return true;
  }

  if (stage == 3) {
    if (!host_pointer_tab_first_selection_verified_ ||
        host_pointer_tab_second_selection_verified_ ||
        tab_strip_model->count() != 2 ||
        tab_strip_model->GetWebContentsAt(0) !=
            host_pointer_tab_initial_contents_ ||
        tab_strip_model->GetWebContentsAt(1) !=
            host_pointer_tab_second_contents_ ||
        tab_strip_model->active_index() != 1 ||
        tab_strip_model->GetActiveWebContents() !=
            host_pointer_tab_second_contents_ ||
        browser_view.GetActiveWebContents() !=
            host_pointer_tab_second_contents_) {
      return false;
    }

    const gfx::Point target = GetHostPointerTarget(
        browser_view, tab_strip->close_tab_button_for_testing(1));
    host_pointer_tab_second_selection_verified_ = true;
    std::fprintf(stderr, "%s x=%d y=%d\n",
                 kHostPointerTabsSecondSelectedMarker, target.x(), target.y());
    std::fflush(stderr);
    // The host waits for this presentation before it closes the active second
    // tab through the same trusted DOM pointer/Ozone path.
    browser_view.SchedulePaint();
    return true;
  }

  if (stage == 4) {
    views::LabelButton* const new_tab_button =
        tab_strip->new_tab_button_for_testing();
    if (!host_pointer_tab_second_selection_verified_ ||
        host_pointer_tab_close_verified_ || tab_strip_model->count() != 1 ||
        tab_strip_model->GetWebContentsAt(0) !=
            host_pointer_tab_initial_contents_ ||
        tab_strip_model->active_index() != 0 ||
        tab_strip_model->GetActiveWebContents() !=
            host_pointer_tab_initial_contents_ ||
        browser_view.GetActiveWebContents() !=
            host_pointer_tab_initial_contents_ || !new_tab_button ||
        !new_tab_button->GetVisible() || !new_tab_button->GetEnabled()) {
      return false;
    }

    // The closed WebContents is no longer model-owned; never carry its raw
    // pointer beyond this verification point.
    host_pointer_tab_second_contents_ = nullptr;
    host_pointer_tab_close_verified_ = true;
    std::fprintf(stderr, "%s\n", kHostPointerTabsClosedMarker);
    std::fflush(stderr);
    // The host acknowledges this exact post-close presentation before this
    // lifecycle begins its normal ordered Browser shutdown.
    browser_view.SchedulePaint();
    return true;
  }

  return false;
}

bool WasmBrowserLifecycle::OnHostPointerTabSmokePresented(int stage) {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (stage != 4 || !host_pointer_tab_smoke_started_ ||
      !host_pointer_tab_insert_verified_ ||
      !host_pointer_tab_first_selection_verified_ ||
      !host_pointer_tab_second_selection_verified_ ||
      !host_pointer_tab_close_verified_ ||
      host_pointer_tab_presentation_verified_ || shutdown_started_ ||
      shutdown_complete_ || !browser_ || host_pointer_tab_second_contents_) {
    return false;
  }

  host_pointer_tab_presentation_verified_ = true;
  std::fprintf(stderr, "%s\n", kHostPointerTabsPassMarker);
  std::fflush(stderr);
  BeginShutdown();
  return true;
}

bool WasmBrowserLifecycle::VerifyHostPointerMenuSmokeCheck(int stage) {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!host_pointer_menu_smoke_started_ || shutdown_started_ ||
      shutdown_complete_ || !browser_ || !host_pointer_menu_contents_ ||
      !host_pointer_menu_navigation_observer_) {
    return false;
  }

  BrowserView& browser_view = browser_->GetBrowserView();
  WasmTopControlsView* const top_controls = browser_view.wasm_top_controls();
  WasmBrowserMenuView* const browser_menu =
      browser_view.wasm_browser_menu();
  views::WebView* const contents_web_view = browser_view.contents_web_view();
  if (!top_controls || !browser_menu || !contents_web_view ||
      browser_view.GetActiveWebContents() != host_pointer_menu_contents_) {
    return false;
  }

  if (stage == 1) {
    if (host_pointer_menu_open_verified_ ||
        host_pointer_menu_open_presentation_verified_ ||
        host_pointer_menu_settings_click_verified_ ||
        host_pointer_menu_settings_navigation_verified_ ||
        host_pointer_menu_settings_presentation_verified_ ||
        !browser_menu->IsOpen()) {
      return false;
    }

    browser_view.DeprecatedLayoutImmediately();
    if (contents_web_view->bounds().y() <=
        host_pointer_menu_closed_contents_y_) {
      return false;
    }
    views::LabelButton* const settings_button =
        browser_menu->settings_button_for_testing();
    if (!settings_button || !settings_button->GetVisible() ||
        !settings_button->GetEnabled()) {
      return false;
    }

    // The Settings center is published only after the real BrowserView has
    // laid out the now-visible child panel. JS cannot supply this coordinate.
    const gfx::Point settings_target =
        GetHostPointerTarget(browser_view, settings_button);
    host_pointer_menu_open_verified_ = true;
    std::fprintf(stderr, "%s x=%d y=%d\n", kHostPointerMenuOpenedMarker,
                 settings_target.x(), settings_target.y());
    std::fflush(stderr);
    browser_view.SchedulePaint();
    return true;
  }

  if (stage == 2) {
    if (!host_pointer_menu_open_verified_ ||
        !host_pointer_menu_open_presentation_verified_ ||
        host_pointer_menu_settings_click_verified_ ||
        host_pointer_menu_settings_presentation_verified_ ||
        browser_menu->IsOpen()) {
      return false;
    }

    browser_view.DeprecatedLayoutImmediately();
    if (contents_web_view->bounds().y() !=
        host_pointer_menu_closed_contents_y_) {
      return false;
    }
    host_pointer_menu_settings_click_verified_ = true;
    std::fprintf(stderr, "%s\n", kHostPointerMenuClosedMarker);
    std::fflush(stderr);
    // A later observer marker additionally requires target FVP. Scheduling
    // here preserves an independent post-click canvas frame even when the
    // local WebUI commits on the next browser task.
    browser_view.SchedulePaint();
    return true;
  }

  return false;
}

bool WasmBrowserLifecycle::OnHostPointerMenuSmokePresented(int stage) {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!host_pointer_menu_smoke_started_ || shutdown_started_ ||
      shutdown_complete_ || !browser_ || !host_pointer_menu_contents_) {
    return false;
  }

  BrowserView& browser_view = browser_->GetBrowserView();
  WasmBrowserMenuView* const browser_menu =
      browser_view.wasm_browser_menu();
  views::WebView* const contents_web_view = browser_view.contents_web_view();
  if (!browser_menu || !contents_web_view ||
      browser_view.GetActiveWebContents() != host_pointer_menu_contents_) {
    return false;
  }

  if (stage == 1) {
    if (!host_pointer_menu_open_verified_ ||
        host_pointer_menu_open_presentation_verified_ ||
        host_pointer_menu_settings_click_verified_ ||
        host_pointer_menu_settings_navigation_verified_ ||
        host_pointer_menu_settings_presentation_verified_ ||
        !browser_menu->IsOpen()) {
      return false;
    }
    browser_view.DeprecatedLayoutImmediately();
    if (contents_web_view->bounds().y() <=
        host_pointer_menu_closed_contents_y_) {
      return false;
    }
    host_pointer_menu_open_presentation_verified_ = true;
    std::fprintf(stderr, "%s\n", kHostPointerMenuPresentedMarker);
    std::fflush(stderr);
    return true;
  }

  if (stage != 2 || !host_pointer_menu_open_verified_ ||
      !host_pointer_menu_open_presentation_verified_ ||
      !host_pointer_menu_settings_click_verified_ ||
      !host_pointer_menu_settings_navigation_verified_ ||
      host_pointer_menu_settings_presentation_verified_ ||
      browser_menu->IsOpen()) {
    return false;
  }
  browser_view.DeprecatedLayoutImmediately();
  if (contents_web_view->bounds().y() !=
      host_pointer_menu_closed_contents_y_) {
    return false;
  }

  host_pointer_menu_settings_presentation_verified_ = true;
  std::fprintf(stderr, "%s\n", kHostPointerMenuPassMarker);
  std::fflush(stderr);
  BeginShutdown();
  return true;
}

void WasmBrowserLifecycle::OnHostPointerMenuSettingsNavigationObserved() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!host_pointer_menu_smoke_started_ || shutdown_started_ ||
      shutdown_complete_ || !browser_ || !host_pointer_menu_contents_ ||
      host_pointer_menu_settings_navigation_verified_) {
    return;
  }

  BrowserView& browser_view = browser_->GetBrowserView();
  WasmBrowserMenuView* const browser_menu =
      browser_view.wasm_browser_menu();
  views::WebView* const contents_web_view = browser_view.contents_web_view();
  if (!browser_menu || !contents_web_view || browser_menu->IsOpen() ||
      browser_view.GetActiveWebContents() != host_pointer_menu_contents_ ||
      host_pointer_menu_contents_->GetLastCommittedURL() !=
          GURL(kHostPointerMenuSettingsUrl) ||
      host_pointer_menu_contents_->GetTitle() !=
          kHostPointerMenuSettingsTitle) {
    return;
  }

  browser_view.DeprecatedLayoutImmediately();
  if (contents_web_view->bounds().y() !=
      host_pointer_menu_closed_contents_y_) {
    return;
  }

  content::WebUI* const settings_web_ui =
      host_pointer_menu_contents_->GetWebUI();
  content::WebUIConfig* const settings_web_ui_config =
      settings_web_ui ? settings_web_ui->GetWebUIConfig() : nullptr;
  content::WebUIController* const settings_web_ui_controller =
      settings_web_ui ? settings_web_ui->GetController() : nullptr;
  WasmSettingsUI* const settings_ui = settings_web_ui_controller
                                          ? settings_web_ui_controller
                                                ->GetAs<WasmSettingsUI>()
                                          : nullptr;
  if (!settings_web_ui_config || !settings_web_ui_controller || !settings_ui ||
      settings_web_ui_config->scheme() != content::kChromeUIScheme ||
      settings_web_ui_config->host() != "settings" ||
      settings_ui->web_ui() != settings_web_ui) {
    return;
  }

  host_pointer_menu_settings_navigation_verified_ = true;
  std::fprintf(stderr, "%s\n", kHostPointerMenuSettingsNavigatedMarker);
  std::fflush(stderr);
  // The host records a compositor frame strictly after this marker, which is
  // itself emitted only after primary commit, loading completion, and target
  // first-visually-non-empty paint for the limited Settings bootstrap.
  browser_view.SchedulePaint();
}

bool WasmBrowserLifecycle::VerifyHostSecurityWarningSmokeCheck(int stage) {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!host_security_warning_smoke_started_ || shutdown_started_ ||
      shutdown_complete_ || !browser_ || !host_security_warning_contents_) {
    return false;
  }

  BrowserView& browser_view = browser_->GetBrowserView();
  TabStripModel* const tab_strip_model = browser_->tab_strip_model();
  WasmBrowserMenuView* const browser_menu =
      browser_view.wasm_browser_menu();
  views::WebView* const contents_web_view = browser_view.contents_web_view();
  WasmBrowserSecurityWarningDialog* const warning_dialog =
      browser_->wasm_security_warning_dialog_for_testing();
  if (!tab_strip_model || !browser_menu || !contents_web_view ||
      !warning_dialog || tab_strip_model->count() != 1 ||
      tab_strip_model->GetActiveWebContents() !=
          host_security_warning_contents_ ||
      browser_view.GetActiveWebContents() !=
          host_security_warning_contents_) {
    return false;
  }
  tabs::TabInterface* const active_tab = tab_strip_model->GetActiveTab();
  web_modal::WebContentsModalDialogManager* const modal_manager =
      web_modal::WebContentsModalDialogManager::FromWebContents(
          host_security_warning_contents_);
  if (!active_tab || active_tab->GetContents() != host_security_warning_contents_ ||
      !modal_manager || modal_manager->delegate() != warning_dialog) {
    return false;
  }

  if (stage == 1) {
    if (host_security_warning_menu_open_verified_ ||
        host_security_warning_menu_presentation_verified_ ||
        host_security_warning_dialog_open_verified_ ||
        host_security_warning_dialog_interaction_ready_ ||
        host_security_warning_dismissed_verified_ ||
        host_security_warning_presentation_verified_ ||
        !browser_menu->IsOpen() || modal_manager->IsDialogActive() ||
        tab_strip_model->IsTabBlocked(0) || active_tab->IsBlocked() ||
        warning_dialog->dialog_widget_for_testing() ||
        warning_dialog->dialog_web_contents_for_testing()) {
      return false;
    }

    browser_view.DeprecatedLayoutImmediately();
    views::LabelButton* const warning_button =
        browser_menu->security_warning_button_for_testing();
    if (!warning_button || !warning_button->GetVisible() ||
        !warning_button->GetEnabled()) {
      return false;
    }
    const gfx::Point target = GetHostPointerTarget(browser_view, warning_button);
    host_security_warning_menu_open_verified_ = true;
    std::fprintf(stderr, "%s x=%d y=%d\n",
                 kHostSecurityWarningMenuOpenedMarker, target.x(), target.y());
    std::fflush(stderr);
    // The outer host refuses to click the dynamic warning target until a
    // strictly later compositor frame has followed this layout-derived target.
    browser_view.SchedulePaint();
    return true;
  }

  if (stage == 2) {
    if (!host_security_warning_menu_open_verified_ ||
        !host_security_warning_menu_presentation_verified_ ||
        host_security_warning_dialog_open_verified_ ||
        host_security_warning_dialog_interaction_ready_ ||
        host_security_warning_dismissed_verified_ ||
        host_security_warning_presentation_verified_ || browser_menu->IsOpen() ||
        !modal_manager->IsDialogActive() || !tab_strip_model->IsTabBlocked(0) ||
        !active_tab->IsBlocked() ||
        warning_dialog->dialog_web_contents_for_testing() !=
            host_security_warning_contents_ ||
        warning_dialog->blocked_state_change_count_for_testing() !=
            host_security_warning_blocked_state_change_count_ + 1) {
      return false;
    }

    views::Widget* const dialog_widget =
        warning_dialog->dialog_widget_for_testing();
    if (!dialog_widget || !dialog_widget->IsVisible() ||
        dialog_widget->is_top_level()) {
      return false;
    }
    browser_view.DeprecatedLayoutImmediately();
    dialog_widget->LayoutRootViewIfNecessary();
    views::View* const dialog_client_contents =
        dialog_widget->GetClientContentsView();
    views::View* const dismiss_button =
        warning_dialog->dismiss_button_for_testing();
    const bool dismiss_button_in_dialog =
        dismiss_button && dismiss_button->GetWidget() == dialog_widget;
    views::Widget* const browser_widget = browser_view.GetWidget();
    aura::Window* const dialog_native = dialog_widget->GetNativeWindow();
    aura::Window* const browser_native =
        browser_widget ? browser_widget->GetNativeWindow() : nullptr;
    if (!dialog_client_contents || !dialog_client_contents->GetVisible() ||
        !dismiss_button_in_dialog ||
        !dismiss_button->GetVisible() || !dismiss_button->GetEnabled() ||
        !dialog_native || !browser_native ||
        !IsAuraDescendantOf(dialog_native, browser_native)) {
      return false;
    }
    const gfx::Rect dialog_bounds = dialog_widget->GetWindowBoundsInScreen();
    const gfx::Rect contents_bounds = contents_web_view->GetBoundsInScreen();
    if (dialog_bounds.IsEmpty() || contents_bounds.IsEmpty() ||
        !contents_bounds.Contains(dialog_bounds.CenterPoint())) {
      return false;
    }

    const gfx::Point target = GetHostPointerTarget(browser_view, dismiss_button);
    host_security_warning_dialog_open_verified_ = true;
    std::fprintf(stderr, "%s x=%d y=%d\n",
                 kHostSecurityWarningDialogOpenedMarker, target.x(), target.y());
    std::fflush(stderr);
    // DialogClientView deliberately ignores a pointer click during its
    // platform double-click interval after becoming visible. Keep that real
    // clickjacking protection enabled: the host is only told when it may make
    // its one physical Dismiss click, after this lifecycle-owned timer and a
    // subsequent compositor frame.
    host_security_warning_dialog_interaction_ready_timer_.Start(
        FROM_HERE,
        views::GetDoubleClickInterval() +
            kHostSecurityWarningInputProtectionMargin,
        base::BindOnce(
            &WasmBrowserLifecycle::OnHostSecurityWarningDialogInteractionReady,
            base::Unretained(this)));
    // The Dismiss click is likewise withheld until the actual child Widget has
    // been presented in a strictly subsequent host-canvas frame.
    browser_view.SchedulePaint();
    return true;
  }

  if (stage == 3) {
    if (!host_security_warning_menu_open_verified_ ||
        !host_security_warning_menu_presentation_verified_ ||
        !host_security_warning_dialog_open_verified_ ||
        !host_security_warning_dialog_interaction_ready_ ||
        host_security_warning_dismissed_verified_ ||
        host_security_warning_presentation_verified_ || browser_menu->IsOpen() ||
        modal_manager->IsDialogActive() || tab_strip_model->IsTabBlocked(0) ||
        active_tab->IsBlocked() || warning_dialog->dialog_widget_for_testing() ||
        warning_dialog->dialog_web_contents_for_testing() ||
        warning_dialog->blocked_state_change_count_for_testing() !=
            host_security_warning_blocked_state_change_count_ + 2) {
      return false;
    }

    host_security_warning_dismissed_verified_ = true;
    std::fprintf(stderr, "%s\n", kHostSecurityWarningDialogDismissedMarker);
    std::fflush(stderr);
    // The final ordinal is not admitted until the host observes a frame
    // strictly after C++ confirmed the tab's unblock and child-widget close.
    browser_view.SchedulePaint();
    return true;
  }

  return false;
}

void WasmBrowserLifecycle::OnHostSecurityWarningDialogInteractionReady() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!host_security_warning_smoke_started_ || shutdown_started_ ||
      shutdown_complete_ || !browser_ || !host_security_warning_contents_ ||
      !host_security_warning_dialog_open_verified_ ||
      host_security_warning_dialog_interaction_ready_ ||
      host_security_warning_dismissed_verified_ ||
      host_security_warning_presentation_verified_) {
    return;
  }

  BrowserView& browser_view = browser_->GetBrowserView();
  TabStripModel* const tab_strip_model = browser_->tab_strip_model();
  WasmBrowserMenuView* const browser_menu =
      browser_view.wasm_browser_menu();
  WasmBrowserSecurityWarningDialog* const warning_dialog =
      browser_->wasm_security_warning_dialog_for_testing();
  web_modal::WebContentsModalDialogManager* const modal_manager =
      web_modal::WebContentsModalDialogManager::FromWebContents(
          host_security_warning_contents_);
  tabs::TabInterface* const active_tab =
      tab_strip_model ? tab_strip_model->GetActiveTab() : nullptr;
  if (!tab_strip_model || !browser_menu || !warning_dialog || !modal_manager ||
      !active_tab || tab_strip_model->count() != 1 || browser_menu->IsOpen() ||
      tab_strip_model->GetActiveWebContents() !=
          host_security_warning_contents_ ||
      browser_view.GetActiveWebContents() != host_security_warning_contents_ ||
      active_tab->GetContents() != host_security_warning_contents_ ||
      !modal_manager->IsDialogActive() || !tab_strip_model->IsTabBlocked(0) ||
      !active_tab->IsBlocked() ||
      warning_dialog->dialog_web_contents_for_testing() !=
          host_security_warning_contents_ ||
      warning_dialog->blocked_state_change_count_for_testing() !=
          host_security_warning_blocked_state_change_count_ + 1) {
    return;
  }

  views::Widget* const dialog_widget =
      warning_dialog->dialog_widget_for_testing();
  if (!dialog_widget || !dialog_widget->IsVisible() ||
      dialog_widget->is_top_level()) {
    return;
  }
  browser_view.DeprecatedLayoutImmediately();
  dialog_widget->LayoutRootViewIfNecessary();
  views::View* const dialog_client_contents =
      dialog_widget->GetClientContentsView();
  views::View* const dismiss_button =
      warning_dialog->dismiss_button_for_testing();
  const bool dismiss_button_in_dialog =
      dismiss_button && dismiss_button->GetWidget() == dialog_widget;
  views::Widget* const browser_widget = browser_view.GetWidget();
  aura::Window* const dialog_native = dialog_widget->GetNativeWindow();
  aura::Window* const browser_native =
      browser_widget ? browser_widget->GetNativeWindow() : nullptr;
  if (!dialog_client_contents || !dialog_client_contents->GetVisible() ||
      !dismiss_button_in_dialog || !dismiss_button->GetVisible() ||
      !dismiss_button->GetEnabled() || !dialog_native || !browser_native ||
      !IsAuraDescendantOf(dialog_native, browser_native)) {
    return;
  }
  const gfx::Rect dialog_bounds = dialog_widget->GetWindowBoundsInScreen();
  views::WebView* const contents_web_view = browser_view.contents_web_view();
  if (!contents_web_view || dialog_bounds.IsEmpty() ||
      contents_web_view->GetBoundsInScreen().IsEmpty() ||
      !contents_web_view->GetBoundsInScreen().Contains(
          dialog_bounds.CenterPoint())) {
    return;
  }

  const gfx::Point target = GetHostPointerTarget(browser_view, dismiss_button);
  host_security_warning_dialog_interaction_ready_ = true;
  std::fprintf(stderr, "%s x=%d y=%d\n",
               kHostSecurityWarningDialogInteractionReadyMarker, target.x(),
               target.y());
  std::fflush(stderr);
  browser_view.SchedulePaint();
}

bool WasmBrowserLifecycle::OnHostSecurityWarningSmokePresented(int stage) {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!host_security_warning_smoke_started_ || shutdown_started_ ||
      shutdown_complete_ || !browser_ || !host_security_warning_contents_) {
    return false;
  }

  BrowserView& browser_view = browser_->GetBrowserView();
  TabStripModel* const tab_strip_model = browser_->tab_strip_model();
  WasmBrowserMenuView* const browser_menu =
      browser_view.wasm_browser_menu();
  WasmBrowserSecurityWarningDialog* const warning_dialog =
      browser_->wasm_security_warning_dialog_for_testing();
  web_modal::WebContentsModalDialogManager* const modal_manager =
      web_modal::WebContentsModalDialogManager::FromWebContents(
          host_security_warning_contents_);
  tabs::TabInterface* const active_tab =
      tab_strip_model ? tab_strip_model->GetActiveTab() : nullptr;
  if (!tab_strip_model || !browser_menu || !warning_dialog || !modal_manager ||
      !active_tab ||
      tab_strip_model->count() != 1 ||
      browser_view.GetActiveWebContents() != host_security_warning_contents_ ||
      tab_strip_model->GetActiveWebContents() !=
          host_security_warning_contents_ ||
      active_tab->GetContents() != host_security_warning_contents_ ||
      modal_manager->delegate() != warning_dialog) {
    return false;
  }

  if (stage == 1) {
    if (!host_security_warning_menu_open_verified_ ||
        host_security_warning_menu_presentation_verified_ ||
        host_security_warning_dialog_open_verified_ ||
        host_security_warning_dialog_interaction_ready_ ||
        host_security_warning_dismissed_verified_ ||
        host_security_warning_presentation_verified_ || !browser_menu->IsOpen() ||
        modal_manager->IsDialogActive() || tab_strip_model->IsTabBlocked(0) ||
        active_tab->IsBlocked() || warning_dialog->dialog_widget_for_testing() ||
        warning_dialog->dialog_web_contents_for_testing()) {
      return false;
    }
    browser_view.DeprecatedLayoutImmediately();
    views::LabelButton* const warning_button =
        browser_menu->security_warning_button_for_testing();
    if (!warning_button || !warning_button->GetVisible() ||
        !warning_button->GetEnabled()) {
      return false;
    }
    host_security_warning_menu_presentation_verified_ = true;
    std::fprintf(stderr, "%s\n", kHostSecurityWarningMenuPresentedMarker);
    std::fflush(stderr);
    return true;
  }

  if (stage != 2 || !host_security_warning_menu_open_verified_ ||
      !host_security_warning_menu_presentation_verified_ ||
      !host_security_warning_dialog_open_verified_ ||
      !host_security_warning_dialog_interaction_ready_ ||
      !host_security_warning_dismissed_verified_ ||
      host_security_warning_presentation_verified_ || browser_menu->IsOpen() ||
      modal_manager->IsDialogActive() || tab_strip_model->IsTabBlocked(0) ||
      active_tab->IsBlocked() || warning_dialog->dialog_widget_for_testing() ||
      warning_dialog->dialog_web_contents_for_testing() ||
      warning_dialog->blocked_state_change_count_for_testing() !=
          host_security_warning_blocked_state_change_count_ + 2) {
    return false;
  }

  host_security_warning_presentation_verified_ = true;
  std::fprintf(stderr, "%s\n", kHostSecurityWarningPassMarker);
  std::fflush(stderr);
  BeginShutdown();
  return true;
}

bool WasmBrowserLifecycle::VerifyHostHistoryDownloadsSmokeCheck(int stage) {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!host_history_downloads_smoke_started_ || shutdown_started_ ||
      shutdown_complete_ || !browser_ ||
      !host_history_downloads_first_contents_) {
    return false;
  }

  BrowserView& browser_view = browser_->GetBrowserView();
  TabStripModel* const tab_strip_model = browser_->tab_strip_model();
  WasmTabStripView* const tab_strip = browser_view.wasm_tab_strip();
  WasmTopControlsView* const top_controls = browser_view.wasm_top_controls();
  WasmBrowserMenuView* const browser_menu =
      browser_view.wasm_browser_menu();
  views::WebView* const contents_web_view = browser_view.contents_web_view();
  if (!tab_strip_model || !tab_strip || !top_controls || !browser_menu ||
      !contents_web_view) {
    return false;
  }

  if (stage == 1) {
    if (!host_history_downloads_first_navigation_verified_ ||
        host_history_downloads_second_tab_verified_ ||
        host_history_downloads_second_contents_ || tab_strip_model->count() != 2 ||
        tab_strip_model->GetWebContentsAt(0) !=
            host_history_downloads_first_contents_) {
      return false;
    }

    content::WebContents* const second_contents =
        tab_strip_model->GetWebContentsAt(1);
    if (!second_contents ||
        second_contents == host_history_downloads_first_contents_ ||
        tab_strip_model->active_index() != 1 ||
        tab_strip_model->GetActiveWebContents() != second_contents ||
        browser_view.GetActiveWebContents() != second_contents) {
      return false;
    }

    // Arm the exact second typed-navigation observer before publishing the
    // stage marker. The host cannot race a second Ctrl+L transaction ahead of
    // this lifecycle-owned WebContents observer.
    host_history_downloads_second_navigation_observer_ =
        std::make_unique<WasmBrowserHostHistoryDownloadsNavigationObserver>(
            second_contents, GURL(kHostHistoryDownloadsSecondJournalUrl),
            WasmBrowserHostHistoryDownloadsNavigationObserver::
                ExpectedNavigation::kTypedUser,
            base::BindRepeating(
                &WasmBrowserLifecycle::OnHostHistoryDownloadsSecondNavigationObserved,
                base::Unretained(this)));
    host_history_downloads_second_contents_ = second_contents;
    host_history_downloads_second_tab_verified_ = true;
    std::fprintf(stderr, "%s\n", kHostHistoryDownloadsSecondTabReadyMarker);
    std::fflush(stderr);
    browser_view.SchedulePaint();
    return true;
  }

  if (stage == 2) {
    if (!host_history_downloads_first_navigation_verified_ ||
        !host_history_downloads_second_tab_verified_ ||
        !host_history_downloads_second_navigation_verified_ ||
        !host_history_downloads_second_contents_ ||
        host_history_downloads_history_menu_open_verified_ ||
        host_history_downloads_history_menu_close_verified_ ||
        host_history_downloads_history_navigation_verified_ ||
        host_history_downloads_downloads_menu_open_verified_ ||
        host_history_downloads_downloads_menu_close_verified_ ||
        host_history_downloads_downloads_navigation_verified_ ||
        browser_view.GetActiveWebContents() !=
            host_history_downloads_second_contents_ ||
        !browser_menu->IsOpen()) {
      return false;
    }

    browser_view.DeprecatedLayoutImmediately();
    if (contents_web_view->bounds().y() <=
        host_history_downloads_closed_contents_y_) {
      return false;
    }
    views::LabelButton* const history_button =
        browser_menu->history_button_for_testing();
    if (!history_button || !history_button->GetVisible() ||
        !history_button->GetEnabled()) {
      return false;
    }

    const gfx::Point history_target =
        GetHostPointerTarget(browser_view, history_button);
    host_history_downloads_history_menu_open_verified_ = true;
    std::fprintf(stderr, "%s x=%d y=%d\n",
                 kHostHistoryDownloadsMenuOpenedMarker, history_target.x(),
                 history_target.y());
    std::fflush(stderr);
    browser_view.SchedulePaint();
    return true;
  }

  if (stage == 3) {
    if (!host_history_downloads_history_menu_open_verified_ ||
        host_history_downloads_history_menu_close_verified_ ||
        host_history_downloads_downloads_menu_open_verified_ ||
        host_history_downloads_downloads_menu_close_verified_ ||
        browser_view.GetActiveWebContents() !=
            host_history_downloads_second_contents_ ||
        browser_menu->IsOpen()) {
      return false;
    }
    browser_view.DeprecatedLayoutImmediately();
    if (contents_web_view->bounds().y() !=
        host_history_downloads_closed_contents_y_) {
      return false;
    }

    host_history_downloads_history_menu_close_verified_ = true;
    std::fprintf(stderr, "%s\n",
                 kHostHistoryDownloadsHistoryMenuClosedMarker);
    std::fflush(stderr);
    // The local History WebUI can reach target FVP before the deferred host
    // ordinal callback arrives. Join its latched target-FVP state with this
    // required close proof rather than allowing a pre-close marker.
    MaybeCompleteHostHistoryDownloadsHistoryNavigation();
    browser_view.SchedulePaint();
    return true;
  }

  if (stage == 4) {
    if (!host_history_downloads_history_menu_open_verified_ ||
        !host_history_downloads_history_menu_close_verified_ ||
        !host_history_downloads_history_navigation_verified_ ||
        host_history_downloads_downloads_menu_open_verified_ ||
        host_history_downloads_downloads_menu_close_verified_ ||
        host_history_downloads_downloads_navigation_verified_ ||
        browser_view.GetActiveWebContents() !=
            host_history_downloads_second_contents_ ||
        !browser_menu->IsOpen()) {
      return false;
    }

    browser_view.DeprecatedLayoutImmediately();
    if (contents_web_view->bounds().y() <=
        host_history_downloads_closed_contents_y_) {
      return false;
    }
    views::LabelButton* const downloads_button =
        browser_menu->downloads_button_for_testing();
    if (!downloads_button || !downloads_button->GetVisible() ||
        !downloads_button->GetEnabled()) {
      return false;
    }

    const gfx::Point downloads_target =
        GetHostPointerTarget(browser_view, downloads_button);
    host_history_downloads_downloads_menu_open_verified_ = true;
    std::fprintf(stderr, "%s x=%d y=%d\n",
                 kHostHistoryDownloadsDownloadsMenuOpenedMarker,
                 downloads_target.x(), downloads_target.y());
    std::fflush(stderr);
    browser_view.SchedulePaint();
    return true;
  }

  if (stage == 5) {
    if (!host_history_downloads_downloads_menu_open_verified_ ||
        host_history_downloads_downloads_menu_close_verified_ ||
        browser_view.GetActiveWebContents() !=
            host_history_downloads_second_contents_ ||
        browser_menu->IsOpen()) {
      return false;
    }
    browser_view.DeprecatedLayoutImmediately();
    if (contents_web_view->bounds().y() !=
        host_history_downloads_closed_contents_y_) {
      return false;
    }

    host_history_downloads_downloads_menu_close_verified_ = true;
    std::fprintf(stderr, "%s\n",
                 kHostHistoryDownloadsDownloadsMenuClosedMarker);
    std::fflush(stderr);
    // Mirror History: an already completed local Downloads WebUI observer is
    // joined only after this physical menu-close verification succeeds.
    MaybeCompleteHostHistoryDownloadsDownloadsNavigation();
    browser_view.SchedulePaint();
    return true;
  }

  return false;
}

bool WasmBrowserLifecycle::OnHostHistoryDownloadsSmokePresented(int stage) {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (stage != 6 || !host_history_downloads_smoke_started_ ||
      !host_history_downloads_first_navigation_verified_ ||
      !host_history_downloads_second_tab_verified_ ||
      !host_history_downloads_second_navigation_verified_ ||
      !host_history_downloads_history_menu_open_verified_ ||
      !host_history_downloads_history_menu_close_verified_ ||
      !host_history_downloads_history_navigation_verified_ ||
      !host_history_downloads_downloads_menu_open_verified_ ||
      !host_history_downloads_downloads_menu_close_verified_ ||
      !host_history_downloads_downloads_navigation_verified_ ||
      host_history_downloads_presentation_verified_ || shutdown_started_ ||
      shutdown_complete_ || !browser_ ||
      !host_history_downloads_second_contents_) {
    return false;
  }

  BrowserView& browser_view = browser_->GetBrowserView();
  WasmBrowserMenuView* const browser_menu =
      browser_view.wasm_browser_menu();
  views::WebView* const contents_web_view = browser_view.contents_web_view();
  if (!browser_menu || !contents_web_view || browser_menu->IsOpen() ||
      browser_view.GetActiveWebContents() !=
          host_history_downloads_second_contents_) {
    return false;
  }
  browser_view.DeprecatedLayoutImmediately();
  if (contents_web_view->bounds().y() !=
      host_history_downloads_closed_contents_y_) {
    return false;
  }

  host_history_downloads_presentation_verified_ = true;
  std::fprintf(stderr, "%s\n", kHostHistoryDownloadsPassMarker);
  std::fflush(stderr);
  BeginShutdown();
  return true;
}

void WasmBrowserLifecycle::OnHostHistoryDownloadsFirstNavigationObserved() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!host_history_downloads_smoke_started_ || shutdown_started_ ||
      shutdown_complete_ || !browser_ ||
      !host_history_downloads_first_contents_ ||
      host_history_downloads_first_navigation_verified_) {
    return;
  }

  BrowserView& browser_view = browser_->GetBrowserView();
  TabStripModel* const tab_strip_model = browser_->tab_strip_model();
  WasmTabStripView* const tab_strip = browser_view.wasm_tab_strip();
  if (!tab_strip_model || !tab_strip || tab_strip_model->count() != 1 ||
      tab_strip_model->GetActiveWebContents() !=
          host_history_downloads_first_contents_ ||
      browser_view.GetActiveWebContents() !=
          host_history_downloads_first_contents_ ||
      host_history_downloads_first_contents_->GetLastCommittedURL() !=
          GURL(kHostHistoryDownloadsFirstJournalUrl)) {
    return;
  }

  const gfx::Point new_tab_target = GetHostPointerTarget(
      browser_view, tab_strip->new_tab_button_for_testing());
  host_history_downloads_first_navigation_verified_ = true;
  std::fprintf(stderr, "%s x=%d y=%d\n",
               kHostHistoryDownloadsFirstNavigatedMarker, new_tab_target.x(),
               new_tab_target.y());
  std::fflush(stderr);
  // A later host click must follow a canvas frame that is strictly after the
  // target's typed commit, load completion, and first non-empty paint.
  browser_view.SchedulePaint();
}

void WasmBrowserLifecycle::OnHostHistoryDownloadsSecondNavigationObserved() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!host_history_downloads_smoke_started_ || shutdown_started_ ||
      shutdown_complete_ || !browser_ ||
      !host_history_downloads_second_contents_ ||
      host_history_downloads_second_navigation_verified_) {
    return;
  }

  BrowserView& browser_view = browser_->GetBrowserView();
  WasmTopControlsView* const top_controls = browser_view.wasm_top_controls();
  WasmBrowserMenuView* const browser_menu =
      browser_view.wasm_browser_menu();
  if (!top_controls || !browser_menu || browser_menu->IsOpen() ||
      browser_view.GetActiveWebContents() !=
          host_history_downloads_second_contents_ ||
      host_history_downloads_second_contents_->GetLastCommittedURL() !=
          GURL(kHostHistoryDownloadsSecondJournalUrl) ||
      host_history_downloads_history_navigation_observer_) {
    return;
  }

  // The actual History menu action may commit immediately on local WebUI
  // tasks. Arm its generated-user observer before exposing the real menu
  // center to host JavaScript.
  host_history_downloads_history_navigation_observer_ =
      std::make_unique<WasmBrowserHostHistoryDownloadsNavigationObserver>(
          host_history_downloads_second_contents_,
          GURL(kHostHistoryDownloadsHistoryUrl),
          WasmBrowserHostHistoryDownloadsNavigationObserver::
              ExpectedNavigation::kGeneratedUser,
          base::BindRepeating(
              &WasmBrowserLifecycle::OnHostHistoryDownloadsHistoryNavigationObserved,
              base::Unretained(this)));

  const gfx::Point menu_target = GetHostPointerTarget(
      browser_view, top_controls->menu_button_for_testing());
  host_history_downloads_second_navigation_verified_ = true;
  std::fprintf(stderr, "%s x=%d y=%d\n",
               kHostHistoryDownloadsSecondNavigatedMarker, menu_target.x(),
               menu_target.y());
  std::fflush(stderr);
  browser_view.SchedulePaint();
}

void WasmBrowserLifecycle::OnHostHistoryDownloadsHistoryNavigationObserved() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!host_history_downloads_smoke_started_ || shutdown_started_ ||
      shutdown_complete_ || !browser_ ||
      !host_history_downloads_second_contents_ ||
      host_history_downloads_history_navigation_verified_) {
    return;
  }

  // The observer invokes this only after exact primary generated-user commit,
  // loading completion, and target FVP. Latch that fact independently: the
  // host's deferred menu-close ordinal can arrive on a later UI task.
  host_history_downloads_history_target_fvp_observed_ = true;
  MaybeCompleteHostHistoryDownloadsHistoryNavigation();
}

void WasmBrowserLifecycle::MaybeCompleteHostHistoryDownloadsHistoryNavigation() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!host_history_downloads_smoke_started_ || shutdown_started_ ||
      shutdown_complete_ || !browser_ ||
      !host_history_downloads_second_contents_ ||
      !host_history_downloads_history_target_fvp_observed_ ||
      !host_history_downloads_history_menu_close_verified_ ||
      host_history_downloads_history_navigation_verified_) {
    return;
  }

  BrowserView& browser_view = browser_->GetBrowserView();
  WasmTopControlsView* const top_controls = browser_view.wasm_top_controls();
  WasmBrowserMenuView* const browser_menu =
      browser_view.wasm_browser_menu();
  views::WebView* const contents_web_view = browser_view.contents_web_view();
  if (!top_controls || !browser_menu || !contents_web_view ||
      browser_menu->IsOpen() ||
      browser_view.GetActiveWebContents() !=
          host_history_downloads_second_contents_ ||
      host_history_downloads_second_contents_->GetLastCommittedURL() !=
          GURL(kHostHistoryDownloadsHistoryUrl) ||
      host_history_downloads_second_contents_->GetTitle() !=
          kHostHistoryDownloadsHistoryTitle ||
      host_history_downloads_downloads_navigation_observer_) {
    return;
  }

  browser_view.DeprecatedLayoutImmediately();
  if (contents_web_view->bounds().y() !=
      host_history_downloads_closed_contents_y_) {
    return;
  }

  content::WebUI* const history_web_ui =
      host_history_downloads_second_contents_->GetWebUI();
  content::WebUIConfig* const history_web_ui_config =
      history_web_ui ? history_web_ui->GetWebUIConfig() : nullptr;
  content::WebUIController* const history_web_ui_controller =
      history_web_ui ? history_web_ui->GetController() : nullptr;
  WasmHistoryUI* const history_ui =
      history_web_ui_controller
          ? history_web_ui_controller->GetAs<WasmHistoryUI>()
          : nullptr;
  if (!history_web_ui_config || !history_web_ui_controller || !history_ui ||
      history_web_ui_config->scheme() != content::kChromeUIScheme ||
      history_web_ui_config->host() != "history" ||
      history_ui->web_ui() != history_web_ui ||
      history_ui->entry_count_for_testing() != 2u) {
    return;
  }

  base::WeakPtr<WasmSessionNavigationJournal> journal =
      profile_->GetSessionNavigationJournalWeakPtr();
  if (!journal) {
    return;
  }
  const std::vector<WasmSessionNavigationJournal::Entry> entries =
      journal->GetSnapshot();
  if (entries.size() != 2u || entries[0].sequence != 1u ||
      entries[1].sequence != 2u ||
      entries[0].display_url != kHostHistoryDownloadsRedactedJournalUrl ||
      entries[1].display_url != kHostHistoryDownloadsRedactedJournalUrl) {
    return;
  }

  // Arm Downloads before publishing the second menu target. This preserves
  // observer ownership even if the static local WebUI commits before the
  // host's ordinal menu-close report runs.
  host_history_downloads_downloads_navigation_observer_ =
      std::make_unique<WasmBrowserHostHistoryDownloadsNavigationObserver>(
          host_history_downloads_second_contents_,
          GURL(kHostHistoryDownloadsDownloadsUrl),
          WasmBrowserHostHistoryDownloadsNavigationObserver::
              ExpectedNavigation::kGeneratedUser,
          base::BindRepeating(
              &WasmBrowserLifecycle::OnHostHistoryDownloadsDownloadsNavigationObserved,
              base::Unretained(this)));

  const gfx::Point menu_target = GetHostPointerTarget(
      browser_view, top_controls->menu_button_for_testing());
  host_history_downloads_history_navigation_verified_ = true;
  std::fprintf(stderr, "%s x=%d y=%d\n",
               kHostHistoryDownloadsHistoryNavigatedMarker, menu_target.x(),
               menu_target.y());
  std::fflush(stderr);
  browser_view.SchedulePaint();
}

void WasmBrowserLifecycle::OnHostHistoryDownloadsDownloadsNavigationObserved() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!host_history_downloads_smoke_started_ || shutdown_started_ ||
      shutdown_complete_ || !browser_ ||
      !host_history_downloads_second_contents_ ||
      host_history_downloads_downloads_navigation_verified_) {
    return;
  }

  // The observer's callback is target-FVP-complete, but must be joined with
  // the separately deferred physical Downloads menu-close ordinal below.
  host_history_downloads_downloads_target_fvp_observed_ = true;
  MaybeCompleteHostHistoryDownloadsDownloadsNavigation();
}

void WasmBrowserLifecycle::MaybeCompleteHostHistoryDownloadsDownloadsNavigation() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!host_history_downloads_smoke_started_ || shutdown_started_ ||
      shutdown_complete_ || !browser_ ||
      !host_history_downloads_second_contents_ ||
      !host_history_downloads_downloads_target_fvp_observed_ ||
      !host_history_downloads_downloads_menu_close_verified_ ||
      host_history_downloads_downloads_navigation_verified_) {
    return;
  }

  BrowserView& browser_view = browser_->GetBrowserView();
  WasmBrowserMenuView* const browser_menu =
      browser_view.wasm_browser_menu();
  views::WebView* const contents_web_view = browser_view.contents_web_view();
  if (!browser_menu || !contents_web_view || browser_menu->IsOpen() ||
      !host_history_downloads_downloads_menu_open_verified_ ||
      browser_view.GetActiveWebContents() !=
          host_history_downloads_second_contents_ ||
      host_history_downloads_second_contents_->GetLastCommittedURL() !=
          GURL(kHostHistoryDownloadsDownloadsUrl) ||
      host_history_downloads_second_contents_->GetTitle() !=
          kHostHistoryDownloadsDownloadsTitle) {
    return;
  }

  browser_view.DeprecatedLayoutImmediately();
  if (contents_web_view->bounds().y() !=
      host_history_downloads_closed_contents_y_) {
    return;
  }

  content::WebUI* const downloads_web_ui =
      host_history_downloads_second_contents_->GetWebUI();
  content::WebUIConfig* const downloads_web_ui_config =
      downloads_web_ui ? downloads_web_ui->GetWebUIConfig() : nullptr;
  content::WebUIController* const downloads_web_ui_controller =
      downloads_web_ui ? downloads_web_ui->GetController() : nullptr;
  WasmDownloadsUI* const downloads_ui =
      downloads_web_ui_controller
          ? downloads_web_ui_controller->GetAs<WasmDownloadsUI>()
          : nullptr;
  if (!downloads_web_ui_config || !downloads_web_ui_controller ||
      !downloads_ui ||
      downloads_web_ui_config->scheme() != content::kChromeUIScheme ||
      downloads_web_ui_config->host() != "downloads" ||
      downloads_ui->web_ui() != downloads_web_ui ||
      profile_->GetDownloadManagerDelegate() != nullptr) {
    return;
  }

  host_history_downloads_downloads_navigation_verified_ = true;
  std::fprintf(stderr, "%s\n", kHostHistoryDownloadsDownloadsNavigatedMarker);
  std::fflush(stderr);
  // The host must record a canvas frame strictly after this target-FVP marker
  // before it can acknowledge presentation and start ordinary shutdown.
  browser_view.SchedulePaint();
}

}  // namespace chrome
