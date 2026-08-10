// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_continuous_flow.h"

#include <cstdio>
#include <optional>
#include <utility>

#include "base/check.h"
#include "base/command_line.h"
#include "base/functional/bind.h"
#include "base/time/time.h"
#include "base/timer/timer.h"
#include "build/build_config.h"
#include "chrome/browser/ui/tabs/tab_strip_model.h"
#include "chrome/browser/ui/views/frame/browser_view.h"
#include "chrome/browser/ui/webui/version/version_ui.h"
#include "chrome/browser/wasm/wasm_browser.h"
#include "chrome/browser/wasm/wasm_browser_host_continuous_flow_smoke.h"
#include "chrome/browser/wasm/wasm_browser_menu.h"
#include "chrome/browser/wasm/wasm_m6_controlled_https_test_mode.h"
#include "chrome/browser/wasm/wasm_settings_ui.h"
#include "chrome/browser/wasm/wasm_tab_strip_view.h"
#include "chrome/browser/wasm/wasm_top_controls_view.h"
#include "content/public/browser/browser_thread.h"
#include "content/public/browser/navigation_handle.h"
#include "content/public/browser/reload_type.h"
#include "content/public/browser/web_contents.h"
#include "content/public/browser/web_contents_observer.h"
#include "content/public/browser/web_ui.h"
#include "content/public/browser/web_ui_controller.h"
#include "content/public/browser/webui_config.h"
#include "content/public/common/url_constants.h"
#include "net/socket/wisp_transport_wasm.h"
#include "ui/aura/window.h"
#include "ui/aura/window_tree_host.h"
#include "ui/base/page_transition_types.h"
#include "ui/gfx/geometry/point.h"
#include "ui/gfx/geometry/rect.h"
#include "ui/views/controls/button/label_button.h"
#include "ui/views/controls/webview/webview.h"
#include "ui/views/view.h"
#include "ui/views/widget/widget.h"
#include "url/gurl.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_continuous_flow.cc must only be built for WebAssembly"
#endif

// This import is provided by ozone_wasm's versioned host bridge. The target
// first-visually-non-empty-paint observer has already completed before this
// call, but the host must still observe a strictly later canvas frame.
extern "C" int chromium_wasm_report_controlled_https_target_fvp(int phase);

namespace chrome {

namespace {

constexpr char kContinuousFlowUrlSwitch[] = "wasm-browser-controlled-https-url";
constexpr char kControlledHttpsUrl[] = "https://a.test/m5/m6-ui";
constexpr char kVersionUrl[] = "chrome://version/";
constexpr char kSettingsUrl[] = "chrome://settings/";
constexpr char16_t kControlledHttpsTitle[] = u"Chromium Wasm M6 UI fixture";
constexpr char16_t kVersionTitle[] = u"About Version";
constexpr char16_t kSettingsTitle[] = u"Settings \u2014 Chromium Wasm";
constexpr char kReadyMarker[] = "CHROMIUM_WASM_M6_CONTINUOUS:READY";
constexpr char kHttpsNavigatedMarker[] =
    "CHROMIUM_WASM_M6_CONTINUOUS:HTTPS_NAVIGATED";
constexpr char kVersionReadyMarker[] =
    "CHROMIUM_WASM_M6_CONTINUOUS:VERSION_READY";
constexpr char kVersionNavigatedMarker[] =
    "CHROMIUM_WASM_M6_CONTINUOUS:VERSION_NAVIGATED";
constexpr char kFirstTabSelectedMarker[] =
    "CHROMIUM_WASM_M6_CONTINUOUS:FIRST_TAB_SELECTED";
constexpr char kMenuReadyMarker[] = "CHROMIUM_WASM_M6_CONTINUOUS:MENU_READY";
constexpr char kMenuOpenedMarker[] =
    "CHROMIUM_WASM_M6_CONTINUOUS:MENU_OPENED";
constexpr char kSettingsNavigatedMarker[] =
    "CHROMIUM_WASM_M6_CONTINUOUS:SETTINGS_NAVIGATED";
constexpr char kFirstTabReturnedMarker[] =
    "CHROMIUM_WASM_M6_CONTINUOUS:FIRST_TAB_RETURNED";
constexpr char kSecondTabClosedMarker[] =
    "CHROMIUM_WASM_M6_CONTINUOUS:SECOND_TAB_CLOSED";
constexpr char kReloadReadyMarker[] =
    "CHROMIUM_WASM_M6_CONTINUOUS:RELOAD_READY";
constexpr char kReloadedMarker[] = "CHROMIUM_WASM_M6_CONTINUOUS:RELOADED";
constexpr char kPassMarker[] = "CHROMIUM_WASM_M6_CONTINUOUS:PASS";
constexpr char kRestartReadyMarker[] =
    "CHROMIUM_WASM_M6_CONTINUOUS:RESTART_READY";
constexpr char kRestartClosingMarker[] =
    "CHROMIUM_WASM_M6_CONTINUOUS:RESTART_CLOSING";
constexpr int kMaximumHostPointerCoordinate = 16383;
constexpr base::TimeDelta kContinuousFlowStepTimeout = base::Seconds(45);

gfx::Point GetHostPointerTarget(BrowserView& browser_view, views::View* view) {
  CHECK(view);
  CHECK(view->GetVisible());
  CHECK(view->GetEnabled());
  browser_view.DeprecatedLayoutImmediately();

  views::Widget* const widget = browser_view.GetWidget();
  CHECK(widget);
  CHECK(widget->IsVisible());
  const gfx::Rect bounds = view->GetBoundsInScreen();
  CHECK(!bounds.IsEmpty());
  const gfx::Point target = bounds.CenterPoint();
  CHECK(widget->GetWindowBoundsInScreen().Contains(target));
  CHECK_GE(target.x(), 0);
  CHECK_GE(target.y(), 0);
  CHECK_LE(target.x(), kMaximumHostPointerCoordinate);
  CHECK_LE(target.y(), kMaximumHostPointerCoordinate);
  return target;
}

void PrintTargetMarker(const char* marker, const gfx::Point& target) {
  CHECK(marker);
  std::fprintf(stderr, "%s x=%d y=%d\n", marker, target.x(), target.y());
  std::fflush(stderr);
}

bool IsExactSettingsWebUI(content::WebContents* contents) {
  if (!contents || contents->GetLastCommittedURL() != GURL(kSettingsUrl) ||
      contents->GetTitle() != kSettingsTitle) {
    return false;
  }
  content::WebUI* const web_ui = contents->GetWebUI();
  content::WebUIConfig* const config =
      web_ui ? web_ui->GetWebUIConfig() : nullptr;
  content::WebUIController* const controller =
      web_ui ? web_ui->GetController() : nullptr;
  WasmSettingsUI* const settings =
      controller ? controller->GetAs<WasmSettingsUI>() : nullptr;
  return config && controller && settings &&
         config->scheme() == content::kChromeUIScheme &&
         config->host() == "settings" && settings->web_ui() == web_ui;
}

bool IsExactVersionWebUI(content::WebContents* contents) {
  if (!contents || contents->GetLastCommittedURL() != GURL(kVersionUrl) ||
      contents->GetTitle() != kVersionTitle) {
    return false;
  }
  content::WebUI* const web_ui = contents->GetWebUI();
  content::WebUIConfig* const config =
      web_ui ? web_ui->GetWebUIConfig() : nullptr;
  content::WebUIController* const controller =
      web_ui ? web_ui->GetController() : nullptr;
  if (!config || !controller || config->scheme() != content::kChromeUIScheme ||
      config->host() != "version") {
    return false;
  }
  // VersionUI predates WebUIController's optional type token. Its exact
  // source-selected scheme/host config has been checked before this concrete
  // upstream controller assertion.
  VersionUI* const version_ui = controller ? static_cast<VersionUI*>(controller)
                                            : nullptr;
  return version_ui && version_ui->web_ui() == web_ui;
}

}  // namespace

// Observes an exact, host-initiated navigation after its coordinator has
// armed a URL/transition/FVP expectation. It neither starts a navigation nor
// invokes a Browser command. A local WebUI may paint before its subsequent
// host ordinal reaches the UI queue, so the completed fact is retained by the
// coordinator rather than inferred from callback order.
class WasmBrowserContinuousNavigationObserver final
    : public content::WebContentsObserver {
 public:
  enum class Expectation {
    kTyped,
    kGenerated,
    kReload,
  };

  WasmBrowserContinuousNavigationObserver(content::WebContents* web_contents,
                                          GURL expected_url,
                                          Expectation expectation,
                                          base::RepeatingClosure observed)
      : content::WebContentsObserver(web_contents),
        expected_url_(std::move(expected_url)),
        expectation_(expectation),
        observed_(std::move(observed)) {
    CHECK(web_contents);
    CHECK(expected_url_.is_valid());
    CHECK(observed_);
  }

  WasmBrowserContinuousNavigationObserver(
      const WasmBrowserContinuousNavigationObserver&) = delete;
  WasmBrowserContinuousNavigationObserver& operator=(
      const WasmBrowserContinuousNavigationObserver&) = delete;
  ~WasmBrowserContinuousNavigationObserver() override = default;

  // content::WebContentsObserver:
  void DidFinishNavigation(
      content::NavigationHandle* navigation_handle) override {
    if (notified_ || committed_ || !navigation_handle ||
        !navigation_handle->IsInPrimaryMainFrame() ||
        navigation_handle->IsSameDocument() || !navigation_handle->HasCommitted() ||
        navigation_handle->IsErrorPage() ||
        navigation_handle->GetURL() != expected_url_ || !web_contents() ||
        web_contents()->GetLastCommittedURL() != expected_url_) {
      return;
    }

    switch (expectation_) {
      case Expectation::kTyped:
        if (!ui::PageTransitionCoreTypeIs(navigation_handle->GetPageTransition(),
                                          ui::PAGE_TRANSITION_TYPED) ||
            !navigation_handle->HasUserGesture()) {
          return;
        }
        break;
      case Expectation::kGenerated:
        if (!ui::PageTransitionCoreTypeIs(navigation_handle->GetPageTransition(),
                                          ui::PAGE_TRANSITION_GENERATED) ||
            !navigation_handle->HasUserGesture()) {
          return;
        }
        break;
      case Expectation::kReload:
        if (!ui::PageTransitionCoreTypeIs(navigation_handle->GetPageTransition(),
                                          ui::PAGE_TRANSITION_RELOAD) ||
            navigation_handle->GetReloadType() != content::ReloadType::NORMAL) {
          return;
        }
        break;
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
    if (!committed_ || notified_) {
      return;
    }
    stopped_loading_after_commit_ = true;
    MaybeNotify();
  }

  void DidFirstVisuallyNonEmptyPaint() override {
    if (!committed_ || notified_ || !web_contents() ||
        web_contents()->GetLastCommittedURL() != expected_url_) {
      return;
    }
    CHECK(web_contents()->CompletedFirstVisuallyNonEmptyPaint());
    first_visually_nonempty_paint_after_commit_ = true;
    MaybeNotify();
  }

 private:
  void MaybeNotify() {
    if (notified_ || !committed_ || !stopped_loading_after_commit_ ||
        !first_visually_nonempty_paint_after_commit_) {
      return;
    }
    notified_ = true;
    observed_.Run();
  }

  const GURL expected_url_;
  const Expectation expectation_;
  const base::RepeatingClosure observed_;
  bool committed_ = false;
  bool stopped_loading_after_commit_ = false;
  bool first_visually_nonempty_paint_after_commit_ = false;
  bool notified_ = false;
};

WasmBrowserContinuousFlow::WasmBrowserContinuousFlow(
    Browser* browser,
    bool restart_only,
    base::RepeatingClosure request_shutdown)
    : browser_(browser),
      restart_only_(restart_only),
      request_shutdown_(std::move(request_shutdown)) {
  CHECK(browser_);
  CHECK(request_shutdown_);
}

WasmBrowserContinuousFlow::~WasmBrowserContinuousFlow() {
  ClearWasmBrowserHostContinuousFlowSmokeVerificationForTesting();
  first_https_navigation_observer_.reset();
  version_navigation_observer_.reset();
  settings_navigation_observer_.reset();
  reload_navigation_observer_.reset();
  first_contents_ = nullptr;
  second_contents_ = nullptr;
}

void WasmBrowserContinuousFlow::Start() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(!started_);
  CHECK(!shutdown_requested_);
  CHECK(browser_);
  CHECK(browser_->GetBrowserView().IsVisible());
  CHECK(chrome::IsWasmM6ControlledHttpsTestModeEnabled());

  BrowserView& browser_view = browser_->GetBrowserView();
  TabStripModel* const tab_strip_model = browser_->tab_strip_model();
  CHECK(tab_strip_model);
  CHECK_EQ(tab_strip_model->count(), 1);
  first_contents_ = tab_strip_model->GetActiveWebContents();
  CHECK(first_contents_);
  CHECK_EQ(browser_view.GetActiveWebContents(), first_contents_);

  started_ = true;
  SetWasmBrowserHostContinuousFlowSmokeVerificationForTesting(
      restart_only_,
      base::BindRepeating(&WasmBrowserContinuousFlow::VerifyCheck,
                          base::Unretained(this)),
      base::BindRepeating(&WasmBrowserContinuousFlow::VerifyPresentation,
                          base::Unretained(this)));

  if (restart_only_) {
    // The outer-page second instance intentionally has no network action. It
    // still proves a fresh Browser/View has reached presentation before the
    // normal owned close path begins.
    std::fprintf(stderr, "%s\n", kRestartReadyMarker);
    std::fflush(stderr);
    browser_view.SchedulePaint();
    ArmStepTimeout();
    return;
  }

  const base::CommandLine* const command_line =
      base::CommandLine::ForCurrentProcess();
  CHECK(command_line);
  CHECK_EQ(command_line->GetSwitchValueASCII(kContinuousFlowUrlSwitch),
           kControlledHttpsUrl);
  CHECK(net::IsWasmWispTransportConfigured());
  CHECK(net::BeginWasmWispTransportDiagnostics("a.test", 443));

  first_https_navigation_observer_ =
      std::make_unique<WasmBrowserContinuousNavigationObserver>(
          first_contents_, GURL(kControlledHttpsUrl),
          WasmBrowserContinuousNavigationObserver::Expectation::kTyped,
          base::BindRepeating(
              &WasmBrowserContinuousFlow::OnFirstHttpsNavigationObserved,
              base::Unretained(this)));
  std::fprintf(stderr, "%s\n", kReadyMarker);
  std::fflush(stderr);
  ArmStepTimeout();
}

bool WasmBrowserContinuousFlow::VerifyCheck(int stage) {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!started_ || restart_only_ || shutdown_requested_ || !browser_ ||
      !first_contents_) {
    return false;
  }

  BrowserView& browser_view = browser_->GetBrowserView();
  TabStripModel* const tab_strip_model = browser_->tab_strip_model();
  WasmTabStripView* const tab_strip = browser_view.wasm_tab_strip();
  WasmTopControlsView* const top_controls = browser_view.wasm_top_controls();
  WasmBrowserMenuView* const menu = browser_view.wasm_browser_menu();
  if (!tab_strip_model || !tab_strip || !top_controls || !menu) {
    return false;
  }

  if (stage == 1) {
    if (!first_https_navigation_observed_ || second_tab_created_ ||
        tab_strip_model->count() != 2 ||
        tab_strip_model->GetWebContentsAt(0) != first_contents_) {
      return false;
    }
    content::WebContents* const second = tab_strip_model->GetWebContentsAt(1);
    if (!second || second == first_contents_ ||
        tab_strip_model->GetActiveWebContents() != second ||
        browser_view.GetActiveWebContents() != second || second_contents_) {
      return false;
    }
    version_navigation_observer_ =
        std::make_unique<WasmBrowserContinuousNavigationObserver>(
            second, GURL(kVersionUrl),
            WasmBrowserContinuousNavigationObserver::Expectation::kTyped,
            base::BindRepeating(
                &WasmBrowserContinuousFlow::OnVersionNavigationObserved,
                base::Unretained(this)));
    second_contents_ = second;
    second_tab_created_ = true;
    std::fprintf(stderr, "%s\n", kVersionReadyMarker);
    std::fflush(stderr);
    browser_view.SchedulePaint();
    ArmStepTimeout();
    return true;
  }

  if (stage == 2) {
    if (!version_navigation_observed_ || first_tab_selected_ ||
        tab_strip_model->count() != 2 || !second_contents_ ||
        tab_strip_model->GetWebContentsAt(0) != first_contents_ ||
        tab_strip_model->GetWebContentsAt(1) != second_contents_ ||
        tab_strip_model->GetActiveWebContents() != first_contents_ ||
        browser_view.GetActiveWebContents() != first_contents_ || menu->IsOpen()) {
      return false;
    }
    const gfx::Point target =
        GetHostPointerTarget(browser_view, tab_strip->tab_button_for_testing(1));
    first_tab_selected_ = true;
    PrintTargetMarker(kFirstTabSelectedMarker, target);
    browser_view.SchedulePaint();
    ArmStepTimeout();
    return true;
  }

  if (stage == 3) {
    if (!first_tab_selected_ || second_tab_selected_ ||
        tab_strip_model->count() != 2 || !second_contents_ ||
        tab_strip_model->GetActiveWebContents() != second_contents_ ||
        browser_view.GetActiveWebContents() != second_contents_ || menu->IsOpen() ||
        second_contents_->GetLastCommittedURL() != GURL(kVersionUrl)) {
      return false;
    }
    settings_navigation_observer_ =
        std::make_unique<WasmBrowserContinuousNavigationObserver>(
            second_contents_, GURL(kSettingsUrl),
            WasmBrowserContinuousNavigationObserver::Expectation::kGenerated,
            base::BindRepeating(
                &WasmBrowserContinuousFlow::OnSettingsNavigationObserved,
                base::Unretained(this)));
    const gfx::Point target = GetHostPointerTarget(
        browser_view, top_controls->menu_button_for_testing());
    second_tab_selected_ = true;
    PrintTargetMarker(kMenuReadyMarker, target);
    browser_view.SchedulePaint();
    ArmStepTimeout();
    return true;
  }

  if (stage == 4) {
    if (!second_tab_selected_ || menu_open_observed_ || !menu->IsOpen() ||
        !second_contents_ || browser_view.GetActiveWebContents() != second_contents_) {
      return false;
    }
    views::LabelButton* const settings_button =
        menu->settings_button_for_testing();
    if (!settings_button || !settings_button->GetVisible() ||
        !settings_button->GetEnabled()) {
      return false;
    }
    const gfx::Point target = GetHostPointerTarget(browser_view, settings_button);
    menu_open_observed_ = true;
    PrintTargetMarker(kMenuOpenedMarker, target);
    browser_view.SchedulePaint();
    ArmStepTimeout();
    return true;
  }

  if (stage == 5) {
    if (!settings_navigation_observed_ || first_tab_returned_ ||
        !second_contents_ || tab_strip_model->count() != 2 || menu->IsOpen() ||
        tab_strip_model->GetActiveWebContents() != first_contents_ ||
        browser_view.GetActiveWebContents() != first_contents_ ||
        second_contents_->GetLastCommittedURL() != GURL(kSettingsUrl)) {
      return false;
    }
    views::LabelButton* const close_button =
        tab_strip->close_tab_button_for_testing(1);
    if (!close_button || !close_button->GetVisible() || !close_button->GetEnabled()) {
      return false;
    }
    const gfx::Point target = GetHostPointerTarget(browser_view, close_button);
    first_tab_returned_ = true;
    PrintTargetMarker(kFirstTabReturnedMarker, target);
    browser_view.SchedulePaint();
    ArmStepTimeout();
    return true;
  }

  if (stage == 6) {
    if (!first_tab_returned_ || second_tab_closed_ || tab_strip_model->count() != 1 ||
        tab_strip_model->GetWebContentsAt(0) != first_contents_ ||
        tab_strip_model->GetActiveWebContents() != first_contents_ ||
        browser_view.GetActiveWebContents() != first_contents_ || menu->IsOpen() ||
        first_contents_->GetLastCommittedURL() != GURL(kControlledHttpsUrl) ||
        first_contents_->GetTitle() != kControlledHttpsTitle) {
      return false;
    }
    const std::optional<net::WasmWispTransportDiagnostics> diagnostics =
        net::GetWasmWispTransportDiagnostics();
    if (!diagnostics || diagnostics->completion_flags !=
                            net::kWasmWispDiagnosticAllRequired) {
      return false;
    }
    reload_navigation_observer_ =
        std::make_unique<WasmBrowserContinuousNavigationObserver>(
            first_contents_, GURL(kControlledHttpsUrl),
            WasmBrowserContinuousNavigationObserver::Expectation::kReload,
            base::BindRepeating(
                &WasmBrowserContinuousFlow::OnReloadNavigationObserved,
                base::Unretained(this)));
    // Do not retain a raw pointer to model-destroyed B after this check.
    second_contents_ = nullptr;
    second_tab_closed_ = true;
    std::fprintf(stderr, "%s\n%s\n", kSecondTabClosedMarker,
                 kReloadReadyMarker);
    std::fflush(stderr);
    browser_view.SchedulePaint();
    ArmStepTimeout();
    return true;
  }

  return false;
}

bool WasmBrowserContinuousFlow::VerifyPresentation(int stage) {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!started_ || shutdown_requested_ || !browser_) {
    return false;
  }
  BrowserView& browser_view = browser_->GetBrowserView();
  if (!browser_view.IsVisible()) {
    return false;
  }

  if (restart_only_) {
    if (stage != 1 || first_https_navigation_observed_ ||
        final_presentation_observed_) {
      return false;
    }
    final_presentation_observed_ = true;
    std::fprintf(stderr, "%s\n", kRestartClosingMarker);
    std::fflush(stderr);
    step_timeout_.Stop();
    RequestOrderlyShutdown();
    return true;
  }

  if (stage != 7 || !reload_navigation_observed_ ||
      final_presentation_observed_ ||
      browser_view.GetActiveWebContents() != first_contents_ ||
      first_contents_->GetLastCommittedURL() != GURL(kControlledHttpsUrl) ||
      first_contents_->GetTitle() != kControlledHttpsTitle) {
    return false;
  }
  final_presentation_observed_ = true;
  std::fprintf(stderr, "%s\n", kPassMarker);
  std::fflush(stderr);
  step_timeout_.Stop();
  RequestOrderlyShutdown();
  return true;
}

void WasmBrowserContinuousFlow::OnFirstHttpsNavigationObserved() {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!started_ || restart_only_ || shutdown_requested_ || !browser_ ||
      !first_contents_ || first_https_navigation_observed_ ||
      first_contents_->GetLastCommittedURL() != GURL(kControlledHttpsUrl) ||
      first_contents_->GetTitle() != kControlledHttpsTitle) {
    return;
  }
  BrowserView& browser_view = browser_->GetBrowserView();
  WasmTabStripView* const tab_strip = browser_view.wasm_tab_strip();
  if (!tab_strip || browser_view.GetActiveWebContents() != first_contents_) {
    return;
  }
  const gfx::Point target = GetHostPointerTarget(
      browser_view, tab_strip->new_tab_button_for_testing());
  first_https_navigation_observed_ = true;
  PrintTargetMarker(kHttpsNavigatedMarker, target);
  CHECK_EQ(chromium_wasm_report_controlled_https_target_fvp(1), 1);
  browser_view.SchedulePaint();
  ArmStepTimeout();
}

void WasmBrowserContinuousFlow::OnVersionNavigationObserved() {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!started_ || restart_only_ || shutdown_requested_ || !browser_ ||
      !second_contents_ || version_navigation_observed_ ||
      !IsExactVersionWebUI(second_contents_)) {
    return;
  }
  BrowserView& browser_view = browser_->GetBrowserView();
  WasmTabStripView* const tab_strip = browser_view.wasm_tab_strip();
  if (!tab_strip || browser_view.GetActiveWebContents() != second_contents_) {
    return;
  }
  const gfx::Point target = GetHostPointerTarget(
      browser_view, tab_strip->tab_button_for_testing(0));
  version_navigation_observed_ = true;
  PrintTargetMarker(kVersionNavigatedMarker, target);
  browser_view.SchedulePaint();
  ArmStepTimeout();
}

void WasmBrowserContinuousFlow::OnSettingsNavigationObserved() {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!started_ || restart_only_ || shutdown_requested_ || !browser_ ||
      !second_contents_ || settings_navigation_observed_ ||
      !IsExactSettingsWebUI(second_contents_)) {
    return;
  }
  BrowserView& browser_view = browser_->GetBrowserView();
  WasmBrowserMenuView* const menu = browser_view.wasm_browser_menu();
  WasmTabStripView* const tab_strip = browser_view.wasm_tab_strip();
  if (!menu || !tab_strip || menu->IsOpen() ||
      browser_view.GetActiveWebContents() != second_contents_) {
    return;
  }
  const gfx::Point target = GetHostPointerTarget(
      browser_view, tab_strip->tab_button_for_testing(0));
  settings_navigation_observed_ = true;
  PrintTargetMarker(kSettingsNavigatedMarker, target);
  browser_view.SchedulePaint();
  ArmStepTimeout();
}

void WasmBrowserContinuousFlow::OnReloadNavigationObserved() {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!started_ || restart_only_ || shutdown_requested_ || !browser_ ||
      !first_contents_ || reload_navigation_observed_ ||
      first_contents_->GetLastCommittedURL() != GURL(kControlledHttpsUrl) ||
      first_contents_->GetTitle() != kControlledHttpsTitle) {
    return;
  }
  BrowserView& browser_view = browser_->GetBrowserView();
  if (browser_view.GetActiveWebContents() != first_contents_) {
    return;
  }
  const std::optional<net::WasmWispTransportDiagnostics> diagnostics =
      net::GetWasmWispTransportDiagnostics();
  if (!diagnostics ||
      diagnostics->completion_flags != net::kWasmWispDiagnosticAllRequired) {
    return;
  }
  reload_navigation_observed_ = true;
  std::fprintf(stderr, "%s\n", kReloadedMarker);
  std::fflush(stderr);
  CHECK_EQ(chromium_wasm_report_controlled_https_target_fvp(2), 1);
  browser_view.SchedulePaint();
  ArmStepTimeout();
}

void WasmBrowserContinuousFlow::ArmStepTimeout() {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!started_ || shutdown_requested_) {
    return;
  }
  step_timeout_.Start(
      FROM_HERE, kContinuousFlowStepTimeout,
      base::BindOnce(&WasmBrowserContinuousFlow::OnStepTimeout,
                     base::Unretained(this)));
}

void WasmBrowserContinuousFlow::OnStepTimeout() {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!started_ || shutdown_requested_) {
    return;
  }
  std::fprintf(stderr, "CHROMIUM_WASM_M6_CONTINUOUS:TIMEOUT\n");
  std::fflush(stderr);
  FailAndRequestOrderlyShutdown();
}

void WasmBrowserContinuousFlow::FailAndRequestOrderlyShutdown() {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!started_ || shutdown_requested_) {
    return;
  }
  shutdown_requested_ = true;
  step_timeout_.Stop();
  ClearWasmBrowserHostContinuousFlowSmokeVerificationForTesting();
  request_shutdown_.Run();
}

void WasmBrowserContinuousFlow::RequestOrderlyShutdown() {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(started_);
  CHECK(!shutdown_requested_);
  shutdown_requested_ = true;
  step_timeout_.Stop();
  // A final presentation report has been accepted. Make all later reports
  // inert before Browser::Close can invalidate View and WebContents owners.
  ClearWasmBrowserHostContinuousFlowSmokeVerificationForTesting();
  request_shutdown_.Run();
}

}  // namespace chrome
