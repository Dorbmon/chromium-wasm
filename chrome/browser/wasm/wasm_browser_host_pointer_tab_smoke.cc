// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_host_pointer_tab_smoke.h"

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
#error "wasm_browser_host_pointer_tab_smoke.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

enum class HostPointerTabSmokeCallback {
  kCheck,
  kPresentation,
};

enum class HostPointerTabSmokeExpectedCallback {
  kFirstCheck,
  kSecondCheck,
  kThirdCheck,
  kFourthCheck,
  kFourthPresentation,
  kFinished,
};

class WasmBrowserHostPointerTabSmokeState {
 public:
  WasmBrowserHostPointerTabSmokeState() = default;
  WasmBrowserHostPointerTabSmokeState(
      const WasmBrowserHostPointerTabSmokeState&) = delete;
  WasmBrowserHostPointerTabSmokeState& operator=(
      const WasmBrowserHostPointerTabSmokeState&) = delete;
  ~WasmBrowserHostPointerTabSmokeState() = default;

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
    task_runner_ = std::move(task_runner);
    check_callback_ = std::move(check_callback);
    presentation_callback_ = std::move(presentation_callback);
    expected_callback_ = HostPointerTabSmokeExpectedCallback::kFirstCheck;
  }

  void ClearCallbacksOnUiThread() {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    base::AutoLock lock(lock_);
    ++generation_;
    accepting_ = false;
    task_runner_ = nullptr;
    check_callback_.Reset();
    presentation_callback_.Reset();
    expected_callback_ = HostPointerTabSmokeExpectedCallback::kFinished;
  }

  bool PostCallback(HostPointerTabSmokeCallback callback, int stage) {
    base::AutoLock lock(lock_);
    if (!accepting_ || !task_runner_ ||
        !IsExpectedCallbackLocked(callback, stage)) {
      return false;
    }
    const uint64_t generation = generation_;
    if (!task_runner_->PostTask(
        FROM_HERE,
        base::BindOnce(
            &WasmBrowserHostPointerTabSmokeState::DispatchOnUiThread,
            base::Unretained(this), callback, stage, generation))) {
      return false;
    }
    AdvanceExpectedCallbackLocked();
    return true;
  }

 private:
  bool IsExpectedCallbackLocked(HostPointerTabSmokeCallback callback,
                                int stage) const
      EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    switch (expected_callback_) {
      case HostPointerTabSmokeExpectedCallback::kFirstCheck:
        return callback == HostPointerTabSmokeCallback::kCheck && stage == 1;
      case HostPointerTabSmokeExpectedCallback::kSecondCheck:
        return callback == HostPointerTabSmokeCallback::kCheck && stage == 2;
      case HostPointerTabSmokeExpectedCallback::kThirdCheck:
        return callback == HostPointerTabSmokeCallback::kCheck && stage == 3;
      case HostPointerTabSmokeExpectedCallback::kFourthCheck:
        return callback == HostPointerTabSmokeCallback::kCheck && stage == 4;
      case HostPointerTabSmokeExpectedCallback::kFourthPresentation:
        return callback == HostPointerTabSmokeCallback::kPresentation &&
               stage == 4;
      case HostPointerTabSmokeExpectedCallback::kFinished:
        return false;
    }
    NOTREACHED();
  }

  void AdvanceExpectedCallbackLocked() EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    switch (expected_callback_) {
      case HostPointerTabSmokeExpectedCallback::kFirstCheck:
        expected_callback_ = HostPointerTabSmokeExpectedCallback::kSecondCheck;
        return;
      case HostPointerTabSmokeExpectedCallback::kSecondCheck:
        expected_callback_ =
            HostPointerTabSmokeExpectedCallback::kThirdCheck;
        return;
      case HostPointerTabSmokeExpectedCallback::kThirdCheck:
        expected_callback_ =
            HostPointerTabSmokeExpectedCallback::kFourthCheck;
        return;
      case HostPointerTabSmokeExpectedCallback::kFourthCheck:
        expected_callback_ =
            HostPointerTabSmokeExpectedCallback::kFourthPresentation;
        return;
      case HostPointerTabSmokeExpectedCallback::kFourthPresentation:
        expected_callback_ = HostPointerTabSmokeExpectedCallback::kFinished;
        return;
      case HostPointerTabSmokeExpectedCallback::kFinished:
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
    task_runner_ = nullptr;
    check_callback_.Reset();
    presentation_callback_.Reset();
    expected_callback_ = HostPointerTabSmokeExpectedCallback::kFinished;
  }

  void DispatchOnUiThread(HostPointerTabSmokeCallback callback,
                          int stage,
                          uint64_t generation) {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    base::RepeatingCallback<bool(int)> callback_to_run;
    {
      base::AutoLock lock(lock_);
      if (!accepting_ || generation != generation_) {
        return;
      }
      callback_to_run = callback == HostPointerTabSmokeCallback::kCheck
                            ? check_callback_
                            : presentation_callback_;
    }
    if (!callback_to_run || !callback_to_run.Run(stage)) {
      // A semantically premature record can race the preceding trusted input
      // across task queues. Make this test ABI inert rather than turning a
      // malformed host request into a Browser CHECK/abort.
      DisableAfterFailedCallback(generation);
    }
  }

  base::Lock lock_;
  scoped_refptr<base::SingleThreadTaskRunner> task_runner_ GUARDED_BY(lock_);
  uint64_t generation_ GUARDED_BY(lock_) = 0;
  bool accepting_ GUARDED_BY(lock_) = false;
  HostPointerTabSmokeExpectedCallback expected_callback_ GUARDED_BY(lock_) =
      HostPointerTabSmokeExpectedCallback::kFinished;
  base::RepeatingCallback<bool(int)> check_callback_ GUARDED_BY(lock_);
  base::RepeatingCallback<bool(int)> presentation_callback_ GUARDED_BY(lock_);
};

WasmBrowserHostPointerTabSmokeState& GetWasmBrowserHostPointerTabSmokeState() {
  static base::NoDestructor<WasmBrowserHostPointerTabSmokeState> state;
  return *state;
}

}  // namespace

void SetWasmBrowserHostPointerTabSmokeVerificationForTesting(
    base::RepeatingCallback<bool(int)> check_callback,
    base::RepeatingCallback<bool(int)> presentation_callback) {
  GetWasmBrowserHostPointerTabSmokeState().SetCallbacksOnUiThread(
      std::move(check_callback), std::move(presentation_callback));
}

void ClearWasmBrowserHostPointerTabSmokeVerificationForTesting() {
  GetWasmBrowserHostPointerTabSmokeState().ClearCallbacksOnUiThread();
}

extern "C" {

EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_pointer_tab_check(
    int stage) {
  return GetWasmBrowserHostPointerTabSmokeState().PostCallback(
             HostPointerTabSmokeCallback::kCheck, stage)
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_pointer_tab_presented(
    int stage) {
  return GetWasmBrowserHostPointerTabSmokeState().PostCallback(
             HostPointerTabSmokeCallback::kPresentation, stage)
             ? 1
             : 0;
}

}  // extern "C"

}  // namespace chrome
