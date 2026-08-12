// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_host_navigation_churn_smoke.h"

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
#error "wasm_browser_host_navigation_churn_smoke.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr int kNavigationChurnCycleCount = 3;
constexpr int kNavigationChurnNavigationsPerCycle = 2;
constexpr int kNavigationChurnLastStage =
    kNavigationChurnCycleCount * kNavigationChurnNavigationsPerCycle;

// The host invokes the export from the JavaScript main thread. Preserve one
// deferred report at a time and recheck the generation when it reaches the
// Chromium UI sequence. This is an observation channel only: no host input
// can start, redirect, reload, or otherwise influence a navigation.
class WasmBrowserHostNavigationChurnSmokeState {
 public:
  WasmBrowserHostNavigationChurnSmokeState() = default;
  WasmBrowserHostNavigationChurnSmokeState(
      const WasmBrowserHostNavigationChurnSmokeState&) = delete;
  WasmBrowserHostNavigationChurnSmokeState& operator=(
      const WasmBrowserHostNavigationChurnSmokeState&) = delete;
  ~WasmBrowserHostNavigationChurnSmokeState() = default;

  void SetCallbackOnUiThread(
      base::RepeatingCallback<bool(int)> backing_store_copy_callback) {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
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
    expected_stage_ = 1;
    task_runner_ = std::move(task_runner);
    backing_store_copy_callback_ = std::move(backing_store_copy_callback);
  }

  void ClearCallbackOnUiThread() {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    base::AutoLock lock(lock_);
    DisableLocked();
  }

  bool PostBackingStoreCopy(int stage) {
    base::AutoLock lock(lock_);
    if (!accepting_ || !task_runner_ || dispatch_pending_ ||
        stage != expected_stage_ || stage < 1 ||
        stage > kNavigationChurnLastStage) {
      return false;
    }

    const uint64_t generation = generation_;
    if (!task_runner_->PostTask(
            FROM_HERE,
            base::BindOnce(
                &WasmBrowserHostNavigationChurnSmokeState::DispatchOnUiThread,
                base::Unretained(this), stage, generation))) {
      return false;
    }
    dispatch_pending_ = true;
    return true;
  }

 private:
  void DisableLocked() EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    ++generation_;
    accepting_ = false;
    dispatch_pending_ = false;
    expected_stage_ = 0;
    task_runner_ = nullptr;
    backing_store_copy_callback_.Reset();
  }

  void DispatchOnUiThread(int stage, uint64_t generation) {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    base::RepeatingCallback<bool(int)> callback;
    {
      base::AutoLock lock(lock_);
      if (!accepting_ || generation != generation_ || !dispatch_pending_ ||
          stage != expected_stage_) {
        return;
      }
      callback = backing_store_copy_callback_;
    }

    if (!callback || !callback.Run(stage)) {
      // Reject stale, malformed, or early host reports at the capability
      // boundary. Do not turn this test-only signal into a Browser command or
      // a fatal Browser CHECK.
      base::AutoLock lock(lock_);
      if (generation == generation_) {
        DisableLocked();
      }
      return;
    }

    base::AutoLock lock(lock_);
    if (!accepting_ || generation != generation_ || !dispatch_pending_ ||
        stage != expected_stage_) {
      return;
    }
    dispatch_pending_ = false;
    if (expected_stage_ == kNavigationChurnLastStage) {
      DisableLocked();
      return;
    }
    ++expected_stage_;
  }

  base::Lock lock_;
  scoped_refptr<base::SingleThreadTaskRunner> task_runner_ GUARDED_BY(lock_);
  uint64_t generation_ GUARDED_BY(lock_) = 0;
  bool accepting_ GUARDED_BY(lock_) = false;
  bool dispatch_pending_ GUARDED_BY(lock_) = false;
  int expected_stage_ GUARDED_BY(lock_) = 0;
  base::RepeatingCallback<bool(int)> backing_store_copy_callback_
      GUARDED_BY(lock_);
};

WasmBrowserHostNavigationChurnSmokeState&
GetWasmBrowserHostNavigationChurnSmokeState() {
  static base::NoDestructor<WasmBrowserHostNavigationChurnSmokeState> state;
  return *state;
}

}  // namespace

void SetWasmBrowserHostNavigationChurnSmokeVerificationForTesting(
    base::RepeatingCallback<bool(int)> backing_store_copy_callback) {
  GetWasmBrowserHostNavigationChurnSmokeState().SetCallbackOnUiThread(
      std::move(backing_store_copy_callback));
}

void ClearWasmBrowserHostNavigationChurnSmokeVerificationForTesting() {
  GetWasmBrowserHostNavigationChurnSmokeState().ClearCallbackOnUiThread();
}

extern "C" {

EMSCRIPTEN_KEEPALIVE int
chromium_wasm_browser_host_navigation_churn_presented(int stage) {
  return GetWasmBrowserHostNavigationChurnSmokeState().PostBackingStoreCopy(
             stage)
             ? 1
             : 0;
}

}  // extern "C"

}  // namespace chrome
