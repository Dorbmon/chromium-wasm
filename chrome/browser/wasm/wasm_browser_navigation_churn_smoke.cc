// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_navigation_churn_smoke.h"

#include <array>
#include <cstdio>
#include <string>
#include <utility>

#include "base/check.h"
#include "base/functional/bind.h"
#include "base/location.h"
#include "base/task/single_thread_task_runner.h"
#include "base/time/time.h"
#include "build/build_config.h"
#include "chrome/browser/ui/tabs/tab_strip_model.h"
#include "chrome/browser/ui/views/frame/browser_view.h"
#include "chrome/browser/wasm/wasm_browser.h"
#include "chrome/browser/wasm/wasm_browser_host_navigation_churn_smoke.h"
#include "content/public/browser/browser_thread.h"
#include "content/public/browser/navigation_controller.h"
#include "content/public/browser/navigation_entry.h"
#include "content/public/browser/navigation_handle.h"
#include "content/public/browser/render_frame_host.h"
#include "content/public/browser/web_contents.h"
#include "content/public/browser/web_contents_observer.h"
#include "ui/base/page_transition_types.h"
#include "url/gurl.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_navigation_churn_smoke.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kReadyMarker[] = "CHROMIUM_WASM_M9_NAVIGATION_CHURN:READY";
constexpr char kNavigatedMarker[] =
    "CHROMIUM_WASM_M9_NAVIGATION_CHURN:NAVIGATED";
constexpr char kPresentedMarker[] =
    "CHROMIUM_WASM_M9_NAVIGATION_CHURN:PRESENTED";
constexpr char kPassMarker[] = "CHROMIUM_WASM_M9_NAVIGATION_CHURN:PASS";
constexpr char kFailMarker[] = "CHROMIUM_WASM_M9_NAVIGATION_CHURN:FAIL";
constexpr char kTimeoutMarker[] =
    "CHROMIUM_WASM_M9_NAVIGATION_CHURN:TIMEOUT";
constexpr int kCycleCount = 3;
constexpr int kNavigationsPerCycle = 2;
constexpr int kLastStage = kCycleCount * kNavigationsPerCycle;
constexpr base::TimeDelta kStepTimeout = base::Seconds(20);

struct StageDescription {
  const char* navigation_name;
  const char* data_url;
  const char16_t* title;
};

// Each document is static markup with a visible title/body only. These fixed
// URLs deliberately contain no script, resource, worker, storage, network,
// or page-WebAssembly operation. The native coordinator owns their selection;
// outer JavaScript receives no URL, navigation, history, or reload capability.
constexpr std::array<StageDescription, kLastStage> kStages = {{
    {"first",
     "data:text/html;charset=utf-8,%3Ctitle%3EChromium%20Wasm%20M9%20"
     "navigation%20C1%20N1%3C%2Ftitle%3E%3Cmain%3ECycle%201%20navigation%20"
     "1%3C%2Fmain%3E",
     u"Chromium Wasm M9 navigation C1 N1"},
    {"second",
     "data:text/html;charset=utf-8,%3Ctitle%3EChromium%20Wasm%20M9%20"
     "navigation%20C1%20N2%3C%2Ftitle%3E%3Cmain%3ECycle%201%20navigation%20"
     "2%3C%2Fmain%3E",
     u"Chromium Wasm M9 navigation C1 N2"},
    {"first",
     "data:text/html;charset=utf-8,%3Ctitle%3EChromium%20Wasm%20M9%20"
     "navigation%20C2%20N1%3C%2Ftitle%3E%3Cmain%3ECycle%202%20navigation%20"
     "1%3C%2Fmain%3E",
     u"Chromium Wasm M9 navigation C2 N1"},
    {"second",
     "data:text/html;charset=utf-8,%3Ctitle%3EChromium%20Wasm%20M9%20"
     "navigation%20C2%20N2%3C%2Ftitle%3E%3Cmain%3ECycle%202%20navigation%20"
     "2%3C%2Fmain%3E",
     u"Chromium Wasm M9 navigation C2 N2"},
    {"first",
     "data:text/html;charset=utf-8,%3Ctitle%3EChromium%20Wasm%20M9%20"
     "navigation%20C3%20N1%3C%2Ftitle%3E%3Cmain%3ECycle%203%20navigation%20"
     "1%3C%2Fmain%3E",
     u"Chromium Wasm M9 navigation C3 N1"},
    {"second",
     "data:text/html;charset=utf-8,%3Ctitle%3EChromium%20Wasm%20M9%20"
     "navigation%20C3%20N2%3C%2Ftitle%3E%3Cmain%3ECycle%203%20navigation%20"
     "2%3C%2Fmain%3E",
     u"Chromium Wasm M9 navigation C3 N2"},
}};

int CycleForStage(int stage) {
  CHECK_GE(stage, 1);
  CHECK_LE(stage, kLastStage);
  return ((stage - 1) / kNavigationsPerCycle) + 1;
}

const StageDescription& DescriptionForStage(int stage) {
  CHECK_GE(stage, 1);
  CHECK_LE(stage, kLastStage);
  return kStages[stage - 1];
}

void PrintNavigatedMarker(int stage,
                          int history_entries,
                          int history_index,
                          int history_baseline_entries,
                          int history_baseline_index,
                          bool history_append_verified,
                          bool back_history) {
  const StageDescription& description = DescriptionForStage(stage);
  std::fprintf(stderr,
               "%s cycle=%d stage=%d navigation=%s historyEntries=%d "
               "historyIndex=%d historyBaselineEntries=%d "
               "historyBaselineIndex=%d historyAppendVerified=%d "
               "forwardHistory=0 backHistory=%d historyExact=1 titleExact=1 rfhLive=1 "
               "fvp=1\n",
               kNavigatedMarker, CycleForStage(stage), stage,
               description.navigation_name, history_entries, history_index,
               history_baseline_entries, history_baseline_index,
               history_append_verified ? 1 : 0, back_history ? 1 : 0);
  std::fflush(stderr);
}

void PrintPresentedMarker(int stage) {
  const StageDescription& description = DescriptionForStage(stage);
  std::fprintf(stderr, "%s cycle=%d stage=%d navigation=%s\n",
               kPresentedMarker, CycleForStage(stage), stage,
               description.navigation_name);
  std::fflush(stderr);
}

}  // namespace

// Waits only for the exact native stage that its C++ owner armed. A local
// `data:` document can commit, title, stop loading, and reach FVP on separate
// turns, so retain each fact until all of them describe the same primary page.
class WasmBrowserNavigationChurnObserver final
    : public content::WebContentsObserver {
 public:
  WasmBrowserNavigationChurnObserver(content::WebContents* web_contents,
                                     int stage,
                                     base::RepeatingCallback<void(int)> observed)
      : content::WebContentsObserver(web_contents),
        stage_(stage),
        expected_url_(DescriptionForStage(stage).data_url),
        expected_title_(DescriptionForStage(stage).title),
        observed_(std::move(observed)) {
    CHECK(web_contents);
    CHECK(expected_url_.is_valid());
    CHECK(observed_);
  }

  WasmBrowserNavigationChurnObserver(
      const WasmBrowserNavigationChurnObserver&) = delete;
  WasmBrowserNavigationChurnObserver& operator=(
      const WasmBrowserNavigationChurnObserver&) = delete;
  ~WasmBrowserNavigationChurnObserver() override = default;

  // content::WebContentsObserver:
  void DidFinishNavigation(
      content::NavigationHandle* navigation_handle) override {
    if (notified_ || committed_ || !navigation_handle ||
        !navigation_handle->IsInPrimaryMainFrame() ||
        navigation_handle->IsSameDocument() ||
        !navigation_handle->HasCommitted() || navigation_handle->IsErrorPage() ||
        navigation_handle->GetURL() != expected_url_ ||
        navigation_handle->HasUserGesture() || !web_contents() ||
        web_contents()->GetLastCommittedURL() != expected_url_ ||
        !ui::PageTransitionCoreTypeIs(navigation_handle->GetPageTransition(),
                                      ui::PAGE_TRANSITION_GENERATED)) {
      return;
    }

    content::RenderFrameHost* const primary_main_frame =
        web_contents()->GetPrimaryMainFrame();
    if (!primary_main_frame || !primary_main_frame->IsRenderFrameLive() ||
        navigation_handle->GetRenderFrameHost() != primary_main_frame) {
      return;
    }

    committed_ = true;
    primary_main_frame_live_after_commit_ = true;
    UpdateTitleAfterCommit();
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
    UpdateTitleAfterCommit();
    MaybeNotify();
  }

  void DidFirstVisuallyNonEmptyPaint() override {
    if (!committed_ || notified_ || !web_contents() ||
        web_contents()->GetLastCommittedURL() != expected_url_) {
      return;
    }
    CHECK(web_contents()->CompletedFirstVisuallyNonEmptyPaint());
    first_visually_nonempty_paint_after_commit_ = true;
    UpdateTitleAfterCommit();
    MaybeNotify();
  }

  void TitleWasSet(content::NavigationEntry* entry) override {
    if (!committed_ || notified_ || !entry || !web_contents() ||
        entry->GetURL() != expected_url_) {
      return;
    }
    UpdateTitleAfterCommit();
    MaybeNotify();
  }

 private:
  void UpdateTitleAfterCommit() {
    if (!committed_ || !web_contents() ||
        web_contents()->GetLastCommittedURL() != expected_url_) {
      return;
    }
    title_after_commit_ = web_contents()->GetTitle() == expected_title_;
  }

  void MaybeNotify() {
    if (notified_ || !committed_ || !primary_main_frame_live_after_commit_ ||
        !title_after_commit_ || !stopped_loading_after_commit_ ||
        !first_visually_nonempty_paint_after_commit_) {
      return;
    }
    notified_ = true;
    observed_.Run(stage_);
  }

  const int stage_;
  const GURL expected_url_;
  const std::u16string expected_title_;
  const base::RepeatingCallback<void(int)> observed_;
  bool committed_ = false;
  bool primary_main_frame_live_after_commit_ = false;
  bool title_after_commit_ = false;
  bool stopped_loading_after_commit_ = false;
  bool first_visually_nonempty_paint_after_commit_ = false;
  bool notified_ = false;
};

WasmBrowserNavigationChurnSmoke::WasmBrowserNavigationChurnSmoke(
    Browser* browser,
    base::OnceClosure request_shutdown)
    : browser_(browser), request_shutdown_(std::move(request_shutdown)) {
  CHECK(browser_);
  CHECK(request_shutdown_);
}

WasmBrowserNavigationChurnSmoke::~WasmBrowserNavigationChurnSmoke() {
  weak_ptr_factory_.InvalidateWeakPtrs();
  ClearWasmBrowserHostNavigationChurnSmokeVerificationForTesting();
  step_timeout_.Stop();
  navigation_observer_.reset();
  contents_.reset();
}

void WasmBrowserNavigationChurnSmoke::Start() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(!started_);
  CHECK(!shutdown_requested_);
  CHECK(browser_);
  CHECK(browser_->GetBrowserView().IsVisible());

  BrowserView& browser_view = browser_->GetBrowserView();
  TabStripModel* const tab_strip_model = browser_->tab_strip_model();
  CHECK(tab_strip_model);
  CHECK_EQ(tab_strip_model->count(), 1);
  content::WebContents* const contents = tab_strip_model->GetActiveWebContents();
  CHECK(contents);
  CHECK_EQ(browser_view.GetActiveWebContents(), contents);
  contents_ = contents->GetWeakPtr();
  CHECK(contents_);

  started_ = true;
  SetWasmBrowserHostNavigationChurnSmokeVerificationForTesting(
      base::BindRepeating(
          [](base::WeakPtr<WasmBrowserNavigationChurnSmoke> owner, int stage) {
            return owner ? owner->VerifyBackingStoreCopy(stage) : false;
          },
          weak_ptr_factory_.GetWeakPtr()));
  std::fprintf(stderr, "%s cycles=%d navigations=%d\n", kReadyMarker,
               kCycleCount, kLastStage);
  std::fflush(stderr);
  BeginCurrentStageNavigation();
}

void WasmBrowserNavigationChurnSmoke::BeginCurrentStageNavigation() {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!started_ || shutdown_requested_ || !browser_ || !contents_ ||
      navigation_observer_) {
    FailAndRequestOrderlyShutdown();
    return;
  }
  CHECK_GE(current_stage_, 1);
  CHECK_LE(current_stage_, kLastStage);

  content::WebContents* const contents = contents_.get();
  BrowserView& browser_view = browser_->GetBrowserView();
  TabStripModel* const tab_strip_model = browser_->tab_strip_model();
  if (!tab_strip_model || tab_strip_model->count() != 1 ||
      tab_strip_model->GetActiveWebContents() != contents ||
      browser_view.GetActiveWebContents() != contents) {
    FailAndRequestOrderlyShutdown();
    return;
  }

  content::NavigationController& controller = contents->GetController();
  // Do not make an assumption about Content's initial about:blank history.
  // The first data: navigation establishes a post-stage-one baseline: it may
  // replace that startup entry or append to it. Before every later native
  // route, require the exact verified baseline with no forward history; after
  // it commits, require exactly one appended entry/current-index advance and
  // a usable back-history entry.
  if ((current_stage_ == 1 && history_baseline_captured_) ||
      (current_stage_ > 1 &&
       (!history_baseline_captured_ ||
        controller.GetEntryCount() != history_baseline_entry_count_ ||
        controller.GetCurrentEntryIndex() != history_baseline_entry_index_ ||
        controller.CanGoForward()))) {
    FailAndRequestOrderlyShutdown();
    return;
  }

  navigation_verified_ = false;
  const StageDescription& description = DescriptionForStage(current_stage_);
  const GURL url(description.data_url);
  CHECK(url.is_valid());
  navigation_observer_ = std::make_unique<WasmBrowserNavigationChurnObserver>(
      contents, current_stage_,
      base::BindRepeating(
          &WasmBrowserNavigationChurnSmoke::OnNavigationObserved,
          base::Unretained(this)));
  ArmStepTimeout();

  content::NavigationController::LoadURLParams params(url);
  // This is the native, fixed, browser-initiated test route. It is not a
  // user gesture, host event, or reissued existing entry. Stages two through
  // six must append a new history item from the captured stage-one baseline.
  params.transition_type = ui::PAGE_TRANSITION_GENERATED;
  params.should_replace_current_entry = false;
  const base::WeakPtr<content::NavigationHandle> navigation_handle =
      controller.LoadURLWithParams(params);
  if (!navigation_handle) {
    navigation_observer_.reset();
    FailAndRequestOrderlyShutdown();
  }
}

void WasmBrowserNavigationChurnSmoke::OnNavigationObserved(int stage) {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!started_ || shutdown_requested_ || !browser_ || !contents_ ||
      !navigation_observer_ || navigation_verified_ || stage != current_stage_) {
    FailAndRequestOrderlyShutdown();
    return;
  }

  content::WebContents* const contents = contents_.get();
  BrowserView& browser_view = browser_->GetBrowserView();
  TabStripModel* const tab_strip_model = browser_->tab_strip_model();
  content::NavigationController& controller = contents->GetController();
  const StageDescription& description = DescriptionForStage(stage);
  const GURL expected_url(description.data_url);
  const std::u16string expected_title(description.title);
  const int history_entries = controller.GetEntryCount();
  const int history_index = controller.GetCurrentEntryIndex();
  const bool history_append_verified = stage > 1;
  const bool back_history = controller.CanGoBack();
  const int history_baseline_entries =
      history_append_verified ? history_baseline_entry_count_ : history_entries;
  const int history_baseline_index =
      history_append_verified ? history_baseline_entry_index_ : history_index;
  content::RenderFrameHost* const primary_main_frame =
      contents->GetPrimaryMainFrame();
  if (!tab_strip_model || tab_strip_model->count() != 1 ||
      tab_strip_model->GetActiveWebContents() != contents ||
      browser_view.GetActiveWebContents() != contents ||
      contents->GetLastCommittedURL() != expected_url ||
      contents->GetTitle() != expected_title || contents->IsLoading() ||
      !contents->CompletedFirstVisuallyNonEmptyPaint() ||
      history_entries < 1 || history_index < 0 ||
      history_index >= history_entries || controller.CanGoForward() ||
      !primary_main_frame ||
      !primary_main_frame->IsRenderFrameLive() ||
      (history_append_verified &&
       (!history_baseline_captured_ ||
        history_entries != history_baseline_entries + 1 ||
        history_index != history_baseline_index + 1 || !back_history))) {
    FailAndRequestOrderlyShutdown();
    return;
  }
  content::NavigationEntry* const entry =
      controller.GetEntryAtIndex(history_index);
  if (!entry || entry->GetURL() != expected_url ||
      entry->GetTitle() != expected_title) {
    FailAndRequestOrderlyShutdown();
    return;
  }

  navigation_verified_ = true;
  current_stage_history_entry_count_ = history_entries;
  current_stage_history_entry_index_ = history_index;
  PrintNavigatedMarker(stage, history_entries, history_index,
                       history_baseline_entries, history_baseline_index,
                       history_append_verified, back_history);
  // This schedules the later host Canvas2D backing-store copy that the only
  // exported ABI can acknowledge. It does not prove raster, compositor,
  // display, or vsync presentation.
  browser_view.SchedulePaint();
  ArmStepTimeout();
}

bool WasmBrowserNavigationChurnSmoke::VerifyBackingStoreCopy(int stage) {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!started_ || shutdown_requested_ || !browser_ || !contents_ ||
      !navigation_observer_ || !navigation_verified_ || stage != current_stage_) {
    return false;
  }

  content::WebContents* const contents = contents_.get();
  BrowserView& browser_view = browser_->GetBrowserView();
  TabStripModel* const tab_strip_model = browser_->tab_strip_model();
  content::NavigationController& controller = contents->GetController();
  const StageDescription& description = DescriptionForStage(stage);
  const GURL expected_url(description.data_url);
  const std::u16string expected_title(description.title);
  const int expected_history_entries = current_stage_history_entry_count_;
  const int expected_history_index = current_stage_history_entry_index_;
  content::RenderFrameHost* const primary_main_frame =
      contents->GetPrimaryMainFrame();
  if (!tab_strip_model || tab_strip_model->count() != 1 ||
      tab_strip_model->GetActiveWebContents() != contents ||
      browser_view.GetActiveWebContents() != contents ||
      contents->GetLastCommittedURL() != expected_url ||
      contents->GetTitle() != expected_title || contents->IsLoading() ||
      !contents->CompletedFirstVisuallyNonEmptyPaint() ||
      expected_history_entries < 1 || expected_history_index < 0 ||
      expected_history_index >= expected_history_entries ||
      controller.GetEntryCount() != expected_history_entries ||
      controller.GetCurrentEntryIndex() != expected_history_index ||
      controller.CanGoForward() || !primary_main_frame ||
      !primary_main_frame->IsRenderFrameLive() ||
      (stage > 1 && !controller.CanGoBack())) {
    return false;
  }
  content::NavigationEntry* const entry =
      controller.GetEntryAtIndex(expected_history_index);
  if (!entry || entry->GetURL() != expected_url ||
      entry->GetTitle() != expected_title) {
    return false;
  }

  step_timeout_.Stop();
  history_baseline_captured_ = true;
  history_baseline_entry_count_ = expected_history_entries;
  history_baseline_entry_index_ = expected_history_index;
  PrintPresentedMarker(stage);
  if (stage == kLastStage) {
    std::fprintf(stderr, "%s cycles=%d navigations=%d\n", kPassMarker,
                 kCycleCount, kLastStage);
    std::fflush(stderr);
    RequestOrderlyShutdown();
    return true;
  }

  // The observer has completed and no longer needs the previous document's
  // callbacks before the next fixed, appended navigation starts.
  navigation_observer_.reset();
  navigation_verified_ = false;
  ++current_stage_;
  BeginCurrentStageNavigation();
  return !shutdown_requested_;
}

void WasmBrowserNavigationChurnSmoke::ArmStepTimeout() {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!started_ || shutdown_requested_) {
    return;
  }
  step_timeout_.Start(
      FROM_HERE, kStepTimeout,
      base::BindOnce(&WasmBrowserNavigationChurnSmoke::OnStepTimeout,
                     base::Unretained(this)));
}

void WasmBrowserNavigationChurnSmoke::OnStepTimeout() {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!started_ || shutdown_requested_) {
    return;
  }
  std::fprintf(stderr, "%s stage=%d\n", kTimeoutMarker, current_stage_);
  std::fflush(stderr);
  FailAndRequestOrderlyShutdown();
}

void WasmBrowserNavigationChurnSmoke::FailAndRequestOrderlyShutdown() {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!started_ || shutdown_requested_) {
    return;
  }
  std::fprintf(stderr, "%s stage=%d\n", kFailMarker, current_stage_);
  std::fflush(stderr);
  shutdown_requested_ = true;
  step_timeout_.Stop();
  ClearWasmBrowserHostNavigationChurnSmokeVerificationForTesting();
  navigation_observer_.reset();
  PostOrderlyShutdown();
}

void WasmBrowserNavigationChurnSmoke::RequestOrderlyShutdown() {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(started_);
  CHECK(!shutdown_requested_);
  shutdown_requested_ = true;
  step_timeout_.Stop();
  // Do not allow a later host ordinal to re-enter a Browser that is beginning
  // its regular close path. Lifecycle clear paths repeat this before any
  // direct Browser destruction as well.
  ClearWasmBrowserHostNavigationChurnSmokeVerificationForTesting();
  navigation_observer_.reset();
  PostOrderlyShutdown();
}

void WasmBrowserNavigationChurnSmoke::PostOrderlyShutdown() {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(request_shutdown_);
  scoped_refptr<base::SingleThreadTaskRunner> task_runner =
      base::SingleThreadTaskRunner::GetCurrentDefault();
  CHECK(task_runner);
  // Browser did-close synchronously resets the lifecycle-owned coordinator.
  // Post the weak lifecycle callback after this member call returns so a
  // direct close cannot delete this coordinator while it is on the stack.
  CHECK(task_runner->PostTask(FROM_HERE, std::move(request_shutdown_)));
}

}  // namespace chrome
