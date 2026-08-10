// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_host_continuous_flow_smoke.h"

#include <cstdint>
#include <utility>

#include "base/check.h"
#include "base/functional/bind.h"
#include "base/location.h"
#include "base/no_destructor.h"
#include "base/synchronization/lock.h"
#include "base/task/single_thread_task_runner.h"
#include "build/build_config.h"
#include "content/public/browser/browser_thread.h"
#include "emscripten/emscripten.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_host_continuous_flow_smoke.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

enum class HostContinuousFlowCallback {
  kCheck,
  kPresentation,
};

enum class HostContinuousFlowExpectedCallback {
  kNewTabCheck,
  kFirstTabCheck,
  kSecondTabCheck,
  kMenuOpenCheck,
  kFirstTabReturnCheck,
  kSecondTabCloseCheck,
  kFinalPresentation,
  kRestartPresentation,
  kFinished,
};

class WasmBrowserHostContinuousFlowSmokeState {
 public:
  WasmBrowserHostContinuousFlowSmokeState() = default;
  WasmBrowserHostContinuousFlowSmokeState(
      const WasmBrowserHostContinuousFlowSmokeState&) = delete;
  WasmBrowserHostContinuousFlowSmokeState& operator=(
      const WasmBrowserHostContinuousFlowSmokeState&) = delete;
  ~WasmBrowserHostContinuousFlowSmokeState() = default;

  void SetCallbacksOnUiThread(
      bool restart_only,
      base::RepeatingCallback<bool(int)> check_callback,
      base::RepeatingCallback<bool(int)> presentation_callback) {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    CHECK(check_callback);
    CHECK(presentation_callback);

    scoped_refptr<base::SingleThreadTaskRunner> task_runner =
        base::SingleThreadTaskRunner::GetCurrentDefault();
    CHECK(task_runner);

    base::AutoLock lock(lock_);
    CHECK(!accepting_);
    CHECK(!task_runner_);
    ++generation_;
    accepting_ = true;
    dispatch_pending_ = false;
    task_runner_ = std::move(task_runner);
    check_callback_ = std::move(check_callback);
    presentation_callback_ = std::move(presentation_callback);
    expected_callback_ = restart_only
                             ? HostContinuousFlowExpectedCallback::
                                   kRestartPresentation
                             : HostContinuousFlowExpectedCallback::kNewTabCheck;
  }

  void ClearCallbacksOnUiThread() {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    base::AutoLock lock(lock_);
    ++generation_;
    accepting_ = false;
    dispatch_pending_ = false;
    task_runner_ = nullptr;
    check_callback_.Reset();
    presentation_callback_.Reset();
    expected_callback_ = HostContinuousFlowExpectedCallback::kFinished;
  }

  bool PostCallback(HostContinuousFlowCallback callback, int stage) {
    base::AutoLock lock(lock_);
    if (!accepting_ || !task_runner_ ||
        dispatch_pending_ || !IsExpectedCallbackLocked(callback, stage)) {
      return false;
    }

    const uint64_t generation = generation_;
    if (!task_runner_->PostTask(
            FROM_HERE,
            base::BindOnce(
                &WasmBrowserHostContinuousFlowSmokeState::DispatchOnUiThread,
                base::Unretained(this), callback, stage, generation))) {
      return false;
    }
    // Do not advance while a JS import callback is merely queued.  The UI
    // callback rechecks this same ordinal/generation and advances only after
    // the native coordinator accepted the already-observed DOM evidence.
    // This prevents a second deferred JS callback from overtaking the first
    // before the coordinator has installed the next observer/Views target.
    dispatch_pending_ = true;
    return true;
  }

 private:
  bool IsExpectedCallbackLocked(HostContinuousFlowCallback callback,
                                int stage) const
      EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    switch (expected_callback_) {
      case HostContinuousFlowExpectedCallback::kNewTabCheck:
        return callback == HostContinuousFlowCallback::kCheck && stage == 1;
      case HostContinuousFlowExpectedCallback::kFirstTabCheck:
        return callback == HostContinuousFlowCallback::kCheck && stage == 2;
      case HostContinuousFlowExpectedCallback::kSecondTabCheck:
        return callback == HostContinuousFlowCallback::kCheck && stage == 3;
      case HostContinuousFlowExpectedCallback::kMenuOpenCheck:
        return callback == HostContinuousFlowCallback::kCheck && stage == 4;
      case HostContinuousFlowExpectedCallback::kFirstTabReturnCheck:
        return callback == HostContinuousFlowCallback::kCheck && stage == 5;
      case HostContinuousFlowExpectedCallback::kSecondTabCloseCheck:
        return callback == HostContinuousFlowCallback::kCheck && stage == 6;
      case HostContinuousFlowExpectedCallback::kFinalPresentation:
        return callback == HostContinuousFlowCallback::kPresentation &&
               stage == 7;
      case HostContinuousFlowExpectedCallback::kRestartPresentation:
        return callback == HostContinuousFlowCallback::kPresentation &&
               stage == 1;
      case HostContinuousFlowExpectedCallback::kFinished:
        return false;
    }
    NOTREACHED();
  }

  void AdvanceExpectedCallbackLocked() EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    switch (expected_callback_) {
      case HostContinuousFlowExpectedCallback::kNewTabCheck:
        expected_callback_ = HostContinuousFlowExpectedCallback::kFirstTabCheck;
        return;
      case HostContinuousFlowExpectedCallback::kFirstTabCheck:
        expected_callback_ = HostContinuousFlowExpectedCallback::kSecondTabCheck;
        return;
      case HostContinuousFlowExpectedCallback::kSecondTabCheck:
        expected_callback_ = HostContinuousFlowExpectedCallback::kMenuOpenCheck;
        return;
      case HostContinuousFlowExpectedCallback::kMenuOpenCheck:
        expected_callback_ =
            HostContinuousFlowExpectedCallback::kFirstTabReturnCheck;
        return;
      case HostContinuousFlowExpectedCallback::kFirstTabReturnCheck:
        expected_callback_ =
            HostContinuousFlowExpectedCallback::kSecondTabCloseCheck;
        return;
      case HostContinuousFlowExpectedCallback::kSecondTabCloseCheck:
        expected_callback_ =
            HostContinuousFlowExpectedCallback::kFinalPresentation;
        return;
      case HostContinuousFlowExpectedCallback::kFinalPresentation:
      case HostContinuousFlowExpectedCallback::kRestartPresentation:
        expected_callback_ = HostContinuousFlowExpectedCallback::kFinished;
        return;
      case HostContinuousFlowExpectedCallback::kFinished:
        NOTREACHED();
    }
  }

  void DisableAfterFailedCallback(uint64_t generation) {
    base::AutoLock lock(lock_);
    if (generation != generation_) {
      return;
    }
    ++generation_;
    accepting_ = false;
    dispatch_pending_ = false;
    task_runner_ = nullptr;
    check_callback_.Reset();
    presentation_callback_.Reset();
    expected_callback_ = HostContinuousFlowExpectedCallback::kFinished;
  }

  void DispatchOnUiThread(HostContinuousFlowCallback callback,
                          int stage,
                          uint64_t generation) {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    base::RepeatingCallback<bool(int)> callback_to_run;
    {
      base::AutoLock lock(lock_);
      if (!accepting_ || generation != generation_ || !dispatch_pending_ ||
          !IsExpectedCallbackLocked(callback, stage)) {
        return;
      }
      callback_to_run = callback == HostContinuousFlowCallback::kCheck
                            ? check_callback_
                            : presentation_callback_;
    }
    if (!callback_to_run || !callback_to_run.Run(stage)) {
      // A host report is only evidence about previously delivered trusted DOM
      // input. Make malformed or prematurely queued reports inert rather than
      // turning this verifier into an application command surface.
      DisableAfterFailedCallback(generation);
      return;
    }

    {
      base::AutoLock lock(lock_);
      if (!accepting_ || generation != generation_ || !dispatch_pending_ ||
          !IsExpectedCallbackLocked(callback, stage)) {
        return;
      }
      dispatch_pending_ = false;
      AdvanceExpectedCallbackLocked();
    }
  }

  base::Lock lock_;
  scoped_refptr<base::SingleThreadTaskRunner> task_runner_ GUARDED_BY(lock_);
  uint64_t generation_ GUARDED_BY(lock_) = 0;
  bool accepting_ GUARDED_BY(lock_) = false;
  bool dispatch_pending_ GUARDED_BY(lock_) = false;
  HostContinuousFlowExpectedCallback expected_callback_ GUARDED_BY(lock_) =
      HostContinuousFlowExpectedCallback::kFinished;
  base::RepeatingCallback<bool(int)> check_callback_ GUARDED_BY(lock_);
  base::RepeatingCallback<bool(int)> presentation_callback_ GUARDED_BY(lock_);
};

WasmBrowserHostContinuousFlowSmokeState&
GetWasmBrowserHostContinuousFlowSmokeState() {
  static base::NoDestructor<WasmBrowserHostContinuousFlowSmokeState> state;
  return *state;
}

}  // namespace

void SetWasmBrowserHostContinuousFlowSmokeVerificationForTesting(
    bool restart_only,
    base::RepeatingCallback<bool(int)> check_callback,
    base::RepeatingCallback<bool(int)> presentation_callback) {
  GetWasmBrowserHostContinuousFlowSmokeState().SetCallbacksOnUiThread(
      restart_only, std::move(check_callback), std::move(presentation_callback));
}

void ClearWasmBrowserHostContinuousFlowSmokeVerificationForTesting() {
  GetWasmBrowserHostContinuousFlowSmokeState().ClearCallbacksOnUiThread();
}

extern "C" {

EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_continuous_flow_check(
    int stage) {
  return GetWasmBrowserHostContinuousFlowSmokeState().PostCallback(
             HostContinuousFlowCallback::kCheck, stage)
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_continuous_flow_presented(
    int stage) {
  return GetWasmBrowserHostContinuousFlowSmokeState().PostCallback(
             HostContinuousFlowCallback::kPresentation, stage)
             ? 1
             : 0;
}

}  // extern "C"

}  // namespace chrome
