// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_host_storage_estimate_smoke.h"

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
#error "wasm_browser_host_storage_estimate_smoke.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

enum class HostStorageEstimateSmokeCallback {
  kCheck,
  kPresentation,
};

enum class HostStorageEstimateSmokeExpectedCallback {
  kStorageEstimateCheck,
  kSettingsPresentation,
  kFinished,
};

class WasmBrowserHostStorageEstimateSmokeState {
 public:
  WasmBrowserHostStorageEstimateSmokeState() = default;
  WasmBrowserHostStorageEstimateSmokeState(
      const WasmBrowserHostStorageEstimateSmokeState&) = delete;
  WasmBrowserHostStorageEstimateSmokeState& operator=(
      const WasmBrowserHostStorageEstimateSmokeState&) = delete;
  ~WasmBrowserHostStorageEstimateSmokeState() = default;

  void SetCallbacksOnUiThread(
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
    expected_callback_ =
        HostStorageEstimateSmokeExpectedCallback::kStorageEstimateCheck;
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
    expected_callback_ = HostStorageEstimateSmokeExpectedCallback::kFinished;
  }

  bool PostCallback(HostStorageEstimateSmokeCallback callback, int stage) {
    base::AutoLock lock(lock_);
    if (!accepting_ || !task_runner_ || dispatch_pending_ ||
        !IsExpectedCallbackLocked(callback, stage)) {
      return false;
    }

    const uint64_t generation = generation_;
    if (!task_runner_->PostTask(
            FROM_HERE,
            base::BindOnce(
                &WasmBrowserHostStorageEstimateSmokeState::DispatchOnUiThread,
                base::Unretained(this), callback, stage, generation))) {
      return false;
    }
    dispatch_pending_ = true;
    return true;
  }

 private:
  bool IsExpectedCallbackLocked(HostStorageEstimateSmokeCallback callback,
                                int stage) const
      EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    switch (expected_callback_) {
      case HostStorageEstimateSmokeExpectedCallback::kStorageEstimateCheck:
        return callback == HostStorageEstimateSmokeCallback::kCheck &&
               stage == 1;
      case HostStorageEstimateSmokeExpectedCallback::kSettingsPresentation:
        return callback == HostStorageEstimateSmokeCallback::kPresentation &&
               stage == 2;
      case HostStorageEstimateSmokeExpectedCallback::kFinished:
        return false;
    }
    NOTREACHED();
  }

  void AdvanceExpectedCallbackLocked() EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    switch (expected_callback_) {
      case HostStorageEstimateSmokeExpectedCallback::kStorageEstimateCheck:
        expected_callback_ =
            HostStorageEstimateSmokeExpectedCallback::kSettingsPresentation;
        return;
      case HostStorageEstimateSmokeExpectedCallback::kSettingsPresentation:
        expected_callback_ = HostStorageEstimateSmokeExpectedCallback::kFinished;
        return;
      case HostStorageEstimateSmokeExpectedCallback::kFinished:
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
    expected_callback_ = HostStorageEstimateSmokeExpectedCallback::kFinished;
  }

  void DispatchOnUiThread(HostStorageEstimateSmokeCallback callback,
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
      callback_to_run = callback == HostStorageEstimateSmokeCallback::kCheck
                            ? check_callback_
                            : presentation_callback_;
    }
    if (!callback_to_run || !callback_to_run.Run(stage)) {
      // A malformed or premature host observation must become inert rather
      // than turning this switch-gated verifier into a navigation command.
      DisableAfterFailedCallback(generation);
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
  HostStorageEstimateSmokeExpectedCallback expected_callback_
      GUARDED_BY(lock_) = HostStorageEstimateSmokeExpectedCallback::kFinished;
  base::RepeatingCallback<bool(int)> check_callback_ GUARDED_BY(lock_);
  base::RepeatingCallback<bool(int)> presentation_callback_ GUARDED_BY(lock_);
};

WasmBrowserHostStorageEstimateSmokeState&
GetWasmBrowserHostStorageEstimateSmokeState() {
  static base::NoDestructor<WasmBrowserHostStorageEstimateSmokeState> state;
  return *state;
}

}  // namespace

void SetWasmBrowserHostStorageEstimateSmokeVerificationForTesting(
    base::RepeatingCallback<bool(int)> check_callback,
    base::RepeatingCallback<bool(int)> presentation_callback) {
  GetWasmBrowserHostStorageEstimateSmokeState().SetCallbacksOnUiThread(
      std::move(check_callback), std::move(presentation_callback));
}

void ClearWasmBrowserHostStorageEstimateSmokeVerificationForTesting() {
  GetWasmBrowserHostStorageEstimateSmokeState().ClearCallbacksOnUiThread();
}

extern "C" {

EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_storage_estimate_check(
    int stage) {
  return GetWasmBrowserHostStorageEstimateSmokeState().PostCallback(
             HostStorageEstimateSmokeCallback::kCheck, stage)
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_storage_estimate_presented(
    int stage) {
  return GetWasmBrowserHostStorageEstimateSmokeState().PostCallback(
             HostStorageEstimateSmokeCallback::kPresentation, stage)
             ? 1
             : 0;
}

}  // extern "C"

}  // namespace chrome
