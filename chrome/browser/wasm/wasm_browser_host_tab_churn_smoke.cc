// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_host_tab_churn_smoke.h"

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
#error "wasm_browser_host_tab_churn_smoke.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr int kTabChurnCycleCount = 3;
constexpr int kTabChurnActionsPerCycle = 4;
constexpr int kTabChurnLastStage =
    kTabChurnCycleCount * kTabChurnActionsPerCycle;

enum class HostTabChurnCallback {
  kCheck,
  kBackingStoreCopy,
};

enum class HostTabChurnExpectedCallback {
  kCheck,
  kBackingStoreCopy,
  kFinished,
};

// The host invokes each exported function from the JavaScript main thread.
// Post the fixed ordinal to the Chromium UI sequence, retain exactly one task
// in flight, and recheck the generation before the lifecycle-owned callback
// can observe it. This is deliberately an observation channel, never a
// Browser command channel.
class WasmBrowserHostTabChurnSmokeState {
 public:
  WasmBrowserHostTabChurnSmokeState() = default;
  WasmBrowserHostTabChurnSmokeState(const WasmBrowserHostTabChurnSmokeState&) =
      delete;
  WasmBrowserHostTabChurnSmokeState& operator=(
      const WasmBrowserHostTabChurnSmokeState&) = delete;
  ~WasmBrowserHostTabChurnSmokeState() = default;

  void SetCallbacksOnUiThread(
      base::RepeatingCallback<bool(int)> check_callback,
      base::RepeatingCallback<bool(int)> backing_store_copy_callback) {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    CHECK(check_callback);
    CHECK(backing_store_copy_callback);

    scoped_refptr<base::SingleThreadTaskRunner> task_runner =
        base::SingleThreadTaskRunner::GetCurrentDefault();
    CHECK(task_runner);

    base::AutoLock lock(lock_);
    CHECK(!accepting_);
    CHECK(!task_runner_);
    ++generation_;
    accepting_ = true;
    dispatch_pending_ = false;
    expected_callback_ = HostTabChurnExpectedCallback::kCheck;
    expected_stage_ = 1;
    task_runner_ = std::move(task_runner);
    check_callback_ = std::move(check_callback);
    backing_store_copy_callback_ = std::move(backing_store_copy_callback);
  }

  void ClearCallbacksOnUiThread() {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    base::AutoLock lock(lock_);
    ++generation_;
    accepting_ = false;
    dispatch_pending_ = false;
    expected_callback_ = HostTabChurnExpectedCallback::kFinished;
    expected_stage_ = 0;
    task_runner_ = nullptr;
    check_callback_.Reset();
    backing_store_copy_callback_.Reset();
  }

  bool PostCallback(HostTabChurnCallback callback, int stage) {
    base::AutoLock lock(lock_);
    if (!accepting_ || !task_runner_ || dispatch_pending_ ||
        !IsExpectedCallbackLocked(callback, stage)) {
      return false;
    }

    const uint64_t generation = generation_;
    if (!task_runner_->PostTask(
            FROM_HERE,
            base::BindOnce(
                &WasmBrowserHostTabChurnSmokeState::DispatchOnUiThread,
                base::Unretained(this), callback, stage, generation))) {
      return false;
    }
    // The expected ordinal advances only after the UI owner accepted the
    // already-observed pointer or frame event. A second deferred JavaScript
    // report cannot overtake the observer/target installation for this stage.
    dispatch_pending_ = true;
    return true;
  }

 private:
  bool IsExpectedCallbackLocked(HostTabChurnCallback callback,
                                int stage) const
      EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    if (stage != expected_stage_ || stage < 1 || stage > kTabChurnLastStage) {
      return false;
    }
    switch (expected_callback_) {
      case HostTabChurnExpectedCallback::kCheck:
        return callback == HostTabChurnCallback::kCheck;
      case HostTabChurnExpectedCallback::kBackingStoreCopy:
        return callback == HostTabChurnCallback::kBackingStoreCopy;
      case HostTabChurnExpectedCallback::kFinished:
        return false;
    }
    NOTREACHED();
  }

  void DisableLocked() EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    ++generation_;
    accepting_ = false;
    dispatch_pending_ = false;
    expected_callback_ = HostTabChurnExpectedCallback::kFinished;
    expected_stage_ = 0;
    task_runner_ = nullptr;
    check_callback_.Reset();
    backing_store_copy_callback_.Reset();
  }

  void AdvanceExpectedCallbackLocked() EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    switch (expected_callback_) {
      case HostTabChurnExpectedCallback::kCheck:
        expected_callback_ = HostTabChurnExpectedCallback::kBackingStoreCopy;
        return;
      case HostTabChurnExpectedCallback::kBackingStoreCopy:
        if (expected_stage_ == kTabChurnLastStage) {
          expected_callback_ = HostTabChurnExpectedCallback::kFinished;
          expected_stage_ = 0;
        } else {
          ++expected_stage_;
          expected_callback_ = HostTabChurnExpectedCallback::kCheck;
        }
        return;
      case HostTabChurnExpectedCallback::kFinished:
        NOTREACHED();
    }
  }

  void DispatchOnUiThread(HostTabChurnCallback callback,
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
      callback_to_run = callback == HostTabChurnCallback::kCheck
                            ? check_callback_
                            : backing_store_copy_callback_;
    }

    if (!callback_to_run || !callback_to_run.Run(stage)) {
      // A stale or malformed report must disable this test-only observer, not
      // become a route into Browser commands or a fatal browser CHECK.
      base::AutoLock lock(lock_);
      if (generation == generation_) {
        DisableLocked();
      }
      return;
    }

    base::AutoLock lock(lock_);
    if (!accepting_ || generation != generation_ || !dispatch_pending_ ||
        !IsExpectedCallbackLocked(callback, stage)) {
      return;
    }
    dispatch_pending_ = false;
    AdvanceExpectedCallbackLocked();
  }

  base::Lock lock_;
  scoped_refptr<base::SingleThreadTaskRunner> task_runner_ GUARDED_BY(lock_);
  uint64_t generation_ GUARDED_BY(lock_) = 0;
  bool accepting_ GUARDED_BY(lock_) = false;
  bool dispatch_pending_ GUARDED_BY(lock_) = false;
  HostTabChurnExpectedCallback expected_callback_ GUARDED_BY(lock_) =
      HostTabChurnExpectedCallback::kFinished;
  int expected_stage_ GUARDED_BY(lock_) = 0;
  base::RepeatingCallback<bool(int)> check_callback_ GUARDED_BY(lock_);
  base::RepeatingCallback<bool(int)> backing_store_copy_callback_
      GUARDED_BY(lock_);
};

WasmBrowserHostTabChurnSmokeState& GetWasmBrowserHostTabChurnSmokeState() {
  static base::NoDestructor<WasmBrowserHostTabChurnSmokeState> state;
  return *state;
}

}  // namespace

void SetWasmBrowserHostTabChurnSmokeVerificationForTesting(
    base::RepeatingCallback<bool(int)> check_callback,
    base::RepeatingCallback<bool(int)> backing_store_copy_callback) {
  GetWasmBrowserHostTabChurnSmokeState().SetCallbacksOnUiThread(
      std::move(check_callback), std::move(backing_store_copy_callback));
}

void ClearWasmBrowserHostTabChurnSmokeVerificationForTesting() {
  GetWasmBrowserHostTabChurnSmokeState().ClearCallbacksOnUiThread();
}

extern "C" {

EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_tab_churn_check(int stage) {
  return GetWasmBrowserHostTabChurnSmokeState().PostCallback(
             HostTabChurnCallback::kCheck, stage)
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_tab_churn_presented(
    int stage) {
  return GetWasmBrowserHostTabChurnSmokeState().PostCallback(
             HostTabChurnCallback::kBackingStoreCopy, stage)
             ? 1
             : 0;
}

}  // extern "C"

}  // namespace chrome
