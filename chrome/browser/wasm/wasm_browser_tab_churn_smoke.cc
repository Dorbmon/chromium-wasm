// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_tab_churn_smoke.h"

#include <cstdio>
#include <utility>

#include "base/check.h"
#include "base/functional/bind.h"
#include "base/time/time.h"
#include "build/build_config.h"
#include "chrome/browser/ui/tabs/tab_strip_model.h"
#include "chrome/browser/ui/views/frame/browser_view.h"
#include "chrome/browser/wasm/wasm_browser.h"
#include "chrome/browser/wasm/wasm_browser_host_tab_churn_smoke.h"
#include "chrome/browser/wasm/wasm_tab_strip_view.h"
#include "content/public/browser/browser_thread.h"
#include "content/public/browser/web_contents.h"
#include "ui/gfx/geometry/point.h"
#include "ui/gfx/geometry/rect.h"
#include "ui/views/controls/button/label_button.h"
#include "ui/views/view.h"
#include "ui/views/widget/widget.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_tab_churn_smoke.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kReadyMarker[] = "CHROMIUM_WASM_M9_TAB_CHURN:READY";
constexpr char kVerifiedMarker[] = "CHROMIUM_WASM_M9_TAB_CHURN:VERIFIED";
constexpr char kPassMarker[] = "CHROMIUM_WASM_M9_TAB_CHURN:PASS";
constexpr char kTimeoutMarker[] = "CHROMIUM_WASM_M9_TAB_CHURN:TIMEOUT";
constexpr int kCycleCount = 3;
constexpr int kActionsPerCycle = 4;
constexpr int kLastStage = kCycleCount * kActionsPerCycle;
constexpr int kMaximumHostPointerCoordinate = 16383;
constexpr base::TimeDelta kStepTimeout = base::Seconds(20);

enum class ChurnAction {
  kNewTab = 0,
  kSelectFirstTab = 1,
  kSelectSecondTab = 2,
  kCloseSecondTab = 3,
};

int CycleForStage(int stage) {
  CHECK_GE(stage, 1);
  CHECK_LE(stage, kLastStage);
  return ((stage - 1) / kActionsPerCycle) + 1;
}

ChurnAction ActionForStage(int stage) {
  CHECK_GE(stage, 1);
  CHECK_LE(stage, kLastStage);
  return static_cast<ChurnAction>((stage - 1) % kActionsPerCycle);
}

const char* ActionName(ChurnAction action) {
  switch (action) {
    case ChurnAction::kNewTab:
      return "new-tab";
    case ChurnAction::kSelectFirstTab:
      return "select-first";
    case ChurnAction::kSelectSecondTab:
      return "select-second";
    case ChurnAction::kCloseSecondTab:
      return "close-second";
  }
  NOTREACHED();
}

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

void PrintTargetMarker(int stage, const gfx::Point& target) {
  std::fprintf(stderr, "%s cycle=%d stage=%d action=%s x=%d y=%d\n",
               kReadyMarker, CycleForStage(stage), stage,
               ActionName(ActionForStage(stage)), target.x(), target.y());
  std::fflush(stderr);
}

void PrintVerifiedMarker(int stage) {
  std::fprintf(stderr, "%s cycle=%d stage=%d action=%s\n", kVerifiedMarker,
               CycleForStage(stage), stage, ActionName(ActionForStage(stage)));
  std::fflush(stderr);
}

}  // namespace

WasmBrowserTabChurnSmoke::WasmBrowserTabChurnSmoke(
    Browser* browser,
    base::RepeatingClosure request_shutdown)
    : browser_(browser), request_shutdown_(std::move(request_shutdown)) {
  CHECK(browser_);
  CHECK(request_shutdown_);
}

WasmBrowserTabChurnSmoke::~WasmBrowserTabChurnSmoke() {
  ClearWasmBrowserHostTabChurnSmokeVerificationForTesting();
  step_timeout_.Stop();
  second_contents_.reset();
  initial_contents_.reset();
}

void WasmBrowserTabChurnSmoke::Start() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(!started_);
  CHECK(!shutdown_requested_);
  CHECK(browser_);
  CHECK(browser_->GetBrowserView().IsVisible());

  BrowserView& browser_view = browser_->GetBrowserView();
  TabStripModel* const tab_strip_model = browser_->tab_strip_model();
  CHECK(tab_strip_model);
  CHECK_EQ(tab_strip_model->count(), 1);
  content::WebContents* const initial_contents =
      tab_strip_model->GetActiveWebContents();
  CHECK(initial_contents);
  initial_contents_ = initial_contents->GetWeakPtr();
  CHECK(initial_contents_);
  CHECK_EQ(browser_view.GetActiveWebContents(), initial_contents_.get());
  CHECK(!second_contents_);

  started_ = true;
  SetWasmBrowserHostTabChurnSmokeVerificationForTesting(
      base::BindRepeating(&WasmBrowserTabChurnSmoke::VerifyCheck,
                          base::Unretained(this)),
      base::BindRepeating(&WasmBrowserTabChurnSmoke::VerifyBackingStoreCopy,
                          base::Unretained(this)));
  PublishTargetForCurrentStage();
  ArmStepTimeout();
}

bool WasmBrowserTabChurnSmoke::VerifyCheck(int stage) {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  content::WebContents* const initial_contents = initial_contents_.get();
  if (!started_ || shutdown_requested_ || !browser_ || !initial_contents ||
      action_verified_ || stage != current_stage_) {
    return false;
  }

  BrowserView& browser_view = browser_->GetBrowserView();
  TabStripModel* const tab_strip_model = browser_->tab_strip_model();
  WasmTabStripView* const tab_strip = browser_view.wasm_tab_strip();
  if (!tab_strip_model || !tab_strip) {
    return false;
  }

  switch (ActionForStage(stage)) {
    case ChurnAction::kNewTab: {
      if (second_contents_ || tab_strip_model->count() != 2 ||
          tab_strip_model->GetWebContentsAt(0) != initial_contents) {
        return false;
      }
      content::WebContents* const second = tab_strip_model->GetWebContentsAt(1);
      if (!second || second == initial_contents ||
          tab_strip_model->active_index() != 1 ||
          tab_strip_model->GetActiveWebContents() != second ||
          browser_view.GetActiveWebContents() != second) {
        return false;
      }
      second_contents_ = second->GetWeakPtr();
      break;
    }
    case ChurnAction::kSelectFirstTab: {
      content::WebContents* const second_contents = second_contents_.get();
      if (!second_contents || tab_strip_model->count() != 2 ||
          tab_strip_model->GetWebContentsAt(0) != initial_contents ||
          tab_strip_model->GetWebContentsAt(1) != second_contents ||
          tab_strip_model->active_index() != 0 ||
          tab_strip_model->GetActiveWebContents() != initial_contents ||
          browser_view.GetActiveWebContents() != initial_contents) {
        return false;
      }
      break;
    }
    case ChurnAction::kSelectSecondTab: {
      content::WebContents* const second_contents = second_contents_.get();
      if (!second_contents || tab_strip_model->count() != 2 ||
          tab_strip_model->GetWebContentsAt(0) != initial_contents ||
          tab_strip_model->GetWebContentsAt(1) != second_contents ||
          tab_strip_model->active_index() != 1 ||
          tab_strip_model->GetActiveWebContents() != second_contents ||
          browser_view.GetActiveWebContents() != second_contents) {
        return false;
      }
      break;
    }
    case ChurnAction::kCloseSecondTab:
      if (tab_strip_model->count() != 1 ||
          tab_strip_model->GetWebContentsAt(0) != initial_contents ||
          tab_strip_model->active_index() != 0 ||
          tab_strip_model->GetActiveWebContents() != initial_contents ||
          browser_view.GetActiveWebContents() != initial_contents) {
        return false;
      }
      // The trusted close can synchronously destroy the removed WebContents,
      // or destroy it later in the Browser close path. Discard the weak
      // reference without dereferencing it in either case.
      second_contents_.reset();
      break;
  }

  action_verified_ = true;
  PrintVerifiedMarker(stage);
  // The next host report is accepted only after it observes a strictly later
  // Canvas2D backing-store copy. This does not prove raster, compositor,
  // display, or vsync presentation; it only orders the host copy report after
  // the verified tab-model mutation.
  browser_view.SchedulePaint();
  ArmStepTimeout();
  return true;
}

bool WasmBrowserTabChurnSmoke::VerifyBackingStoreCopy(int stage) {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  content::WebContents* const initial_contents = initial_contents_.get();
  if (!started_ || shutdown_requested_ || !browser_ || !initial_contents ||
      !action_verified_ || stage != current_stage_) {
    return false;
  }

  BrowserView& browser_view = browser_->GetBrowserView();
  TabStripModel* const tab_strip_model = browser_->tab_strip_model();
  WasmTabStripView* const tab_strip = browser_view.wasm_tab_strip();
  if (!tab_strip_model || !tab_strip) {
    return false;
  }

  // Revalidate the complete model/View state after the host's later Canvas2D
  // backing-store-copy acknowledgement. This rejects a stale copy report or a
  // direct close that raced the fixed ordinal without dereferencing a closed
  // tab.
  switch (ActionForStage(stage)) {
    case ChurnAction::kNewTab: {
      content::WebContents* const second_contents = second_contents_.get();
      if (!second_contents || tab_strip_model->count() != 2 ||
          tab_strip_model->GetWebContentsAt(0) != initial_contents ||
          tab_strip_model->GetWebContentsAt(1) != second_contents ||
          tab_strip_model->GetActiveWebContents() != second_contents ||
          browser_view.GetActiveWebContents() != second_contents) {
        return false;
      }
      break;
    }
    case ChurnAction::kSelectFirstTab: {
      content::WebContents* const second_contents = second_contents_.get();
      if (!second_contents || tab_strip_model->count() != 2 ||
          tab_strip_model->GetWebContentsAt(0) != initial_contents ||
          tab_strip_model->GetWebContentsAt(1) != second_contents ||
          tab_strip_model->GetActiveWebContents() != initial_contents ||
          browser_view.GetActiveWebContents() != initial_contents) {
        return false;
      }
      break;
    }
    case ChurnAction::kSelectSecondTab: {
      content::WebContents* const second_contents = second_contents_.get();
      if (!second_contents || tab_strip_model->count() != 2 ||
          tab_strip_model->GetWebContentsAt(0) != initial_contents ||
          tab_strip_model->GetWebContentsAt(1) != second_contents ||
          tab_strip_model->GetActiveWebContents() != second_contents ||
          browser_view.GetActiveWebContents() != second_contents) {
        return false;
      }
      break;
    }
    case ChurnAction::kCloseSecondTab:
      if (second_contents_ || tab_strip_model->count() != 1 ||
          tab_strip_model->GetWebContentsAt(0) != initial_contents ||
          tab_strip_model->GetActiveWebContents() != initial_contents ||
          browser_view.GetActiveWebContents() != initial_contents) {
        return false;
      }
      break;
  }

  action_verified_ = false;
  if (stage == kLastStage) {
    std::fprintf(stderr, "%s cycles=%d\n", kPassMarker, kCycleCount);
    std::fflush(stderr);
    step_timeout_.Stop();
    RequestOrderlyShutdown();
    return true;
  }

  ++current_stage_;
  PublishTargetForCurrentStage();
  ArmStepTimeout();
  return true;
}

void WasmBrowserTabChurnSmoke::PublishTargetForCurrentStage() {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(started_);
  CHECK(!shutdown_requested_);
  CHECK(browser_);
  CHECK(initial_contents_);
  CHECK_GE(current_stage_, 1);
  CHECK_LE(current_stage_, kLastStage);

  BrowserView& browser_view = browser_->GetBrowserView();
  WasmTabStripView* const tab_strip = browser_view.wasm_tab_strip();
  CHECK(tab_strip);

  views::View* target = nullptr;
  switch (ActionForStage(current_stage_)) {
    case ChurnAction::kNewTab:
      target = tab_strip->new_tab_button_for_testing();
      break;
    case ChurnAction::kSelectFirstTab:
      target = tab_strip->tab_button_for_testing(0);
      break;
    case ChurnAction::kSelectSecondTab:
      target = tab_strip->tab_button_for_testing(1);
      break;
    case ChurnAction::kCloseSecondTab:
      target = tab_strip->close_tab_button_for_testing(1);
      break;
  }
  PrintTargetMarker(current_stage_, GetHostPointerTarget(browser_view, target));
}

void WasmBrowserTabChurnSmoke::ArmStepTimeout() {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!started_ || shutdown_requested_) {
    return;
  }
  step_timeout_.Start(
      FROM_HERE, kStepTimeout,
      base::BindOnce(&WasmBrowserTabChurnSmoke::OnStepTimeout,
                     base::Unretained(this)));
}

void WasmBrowserTabChurnSmoke::OnStepTimeout() {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!started_ || shutdown_requested_) {
    return;
  }
  std::fprintf(stderr, "%s stage=%d\n", kTimeoutMarker, current_stage_);
  std::fflush(stderr);
  FailAndRequestOrderlyShutdown();
}

void WasmBrowserTabChurnSmoke::FailAndRequestOrderlyShutdown() {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!started_ || shutdown_requested_) {
    return;
  }
  shutdown_requested_ = true;
  step_timeout_.Stop();
  ClearWasmBrowserHostTabChurnSmokeVerificationForTesting();
  request_shutdown_.Run();
}

void WasmBrowserTabChurnSmoke::RequestOrderlyShutdown() {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(started_);
  CHECK(!shutdown_requested_);
  shutdown_requested_ = true;
  step_timeout_.Stop();
  // No later host ordinal can re-enter a Browser that BeginShutdown is about
  // to close. The lifecycle also clears this bridge on every direct-close path.
  ClearWasmBrowserHostTabChurnSmokeVerificationForTesting();
  request_shutdown_.Run();
}

}  // namespace chrome
