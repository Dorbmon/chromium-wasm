// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_host_pointer_menu_smoke.h"

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
#error "wasm_browser_host_pointer_menu_smoke.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

enum class HostPointerMenuSmokeCallback {
  kCheck,
  kPresentation,
};

enum class HostPointerMenuSmokeExpectedCallback {
  kMenuCheck,
  kMenuPresentation,
  kSettingsCheck,
  kSettingsPresentation,
  kFinished,
};

class WasmBrowserHostPointerMenuSmokeState {
 public:
  WasmBrowserHostPointerMenuSmokeState() = default;
  WasmBrowserHostPointerMenuSmokeState(
      const WasmBrowserHostPointerMenuSmokeState&) = delete;
  WasmBrowserHostPointerMenuSmokeState& operator=(
      const WasmBrowserHostPointerMenuSmokeState&) = delete;
  ~WasmBrowserHostPointerMenuSmokeState() = default;

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
    expected_callback_ = HostPointerMenuSmokeExpectedCallback::kMenuCheck;
  }

  void ClearCallbacksOnUiThread() {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    base::AutoLock lock(lock_);
    ++generation_;
    accepting_ = false;
    task_runner_ = nullptr;
    check_callback_.Reset();
    presentation_callback_.Reset();
    expected_callback_ = HostPointerMenuSmokeExpectedCallback::kFinished;
  }

  bool PostCallback(HostPointerMenuSmokeCallback callback, int stage) {
    base::AutoLock lock(lock_);
    if (!accepting_ || !task_runner_ ||
        !IsExpectedCallbackLocked(callback, stage)) {
      return false;
    }

    const uint64_t generation = generation_;
    if (!task_runner_->PostTask(
            FROM_HERE,
            base::BindOnce(
                &WasmBrowserHostPointerMenuSmokeState::DispatchOnUiThread,
                base::Unretained(this), callback, stage, generation))) {
      return false;
    }
    AdvanceExpectedCallbackLocked();
    return true;
  }

 private:
  bool IsExpectedCallbackLocked(HostPointerMenuSmokeCallback callback,
                                int stage) const
      EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    switch (expected_callback_) {
      case HostPointerMenuSmokeExpectedCallback::kMenuCheck:
        return callback == HostPointerMenuSmokeCallback::kCheck && stage == 1;
      case HostPointerMenuSmokeExpectedCallback::kMenuPresentation:
        return callback == HostPointerMenuSmokeCallback::kPresentation &&
               stage == 1;
      case HostPointerMenuSmokeExpectedCallback::kSettingsCheck:
        return callback == HostPointerMenuSmokeCallback::kCheck && stage == 2;
      case HostPointerMenuSmokeExpectedCallback::kSettingsPresentation:
        return callback == HostPointerMenuSmokeCallback::kPresentation &&
               stage == 2;
      case HostPointerMenuSmokeExpectedCallback::kFinished:
        return false;
    }
    NOTREACHED();
  }

  void AdvanceExpectedCallbackLocked() EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    switch (expected_callback_) {
      case HostPointerMenuSmokeExpectedCallback::kMenuCheck:
        expected_callback_ =
            HostPointerMenuSmokeExpectedCallback::kMenuPresentation;
        return;
      case HostPointerMenuSmokeExpectedCallback::kMenuPresentation:
        expected_callback_ =
            HostPointerMenuSmokeExpectedCallback::kSettingsCheck;
        return;
      case HostPointerMenuSmokeExpectedCallback::kSettingsCheck:
        expected_callback_ =
            HostPointerMenuSmokeExpectedCallback::kSettingsPresentation;
        return;
      case HostPointerMenuSmokeExpectedCallback::kSettingsPresentation:
        expected_callback_ = HostPointerMenuSmokeExpectedCallback::kFinished;
        return;
      case HostPointerMenuSmokeExpectedCallback::kFinished:
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
    expected_callback_ = HostPointerMenuSmokeExpectedCallback::kFinished;
  }

  void DispatchOnUiThread(HostPointerMenuSmokeCallback callback,
                          int stage,
                          uint64_t generation) {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    base::RepeatingCallback<bool(int)> callback_to_run;
    {
      base::AutoLock lock(lock_);
      if (!accepting_ || generation != generation_) {
        return;
      }
      callback_to_run = callback == HostPointerMenuSmokeCallback::kCheck
                            ? check_callback_
                            : presentation_callback_;
    }
    if (!callback_to_run || !callback_to_run.Run(stage)) {
      // A host ordinal can race a preceding trusted pointer event across task
      // queues. Make this test ABI inert rather than turning malformed host
      // input into a Browser command surface or an application CHECK.
      DisableAfterFailedCallback(generation);
    }
  }

  base::Lock lock_;
  scoped_refptr<base::SingleThreadTaskRunner> task_runner_ GUARDED_BY(lock_);
  uint64_t generation_ GUARDED_BY(lock_) = 0;
  bool accepting_ GUARDED_BY(lock_) = false;
  HostPointerMenuSmokeExpectedCallback expected_callback_ GUARDED_BY(lock_) =
      HostPointerMenuSmokeExpectedCallback::kFinished;
  base::RepeatingCallback<bool(int)> check_callback_ GUARDED_BY(lock_);
  base::RepeatingCallback<bool(int)> presentation_callback_ GUARDED_BY(lock_);
};

WasmBrowserHostPointerMenuSmokeState&
GetWasmBrowserHostPointerMenuSmokeState() {
  static base::NoDestructor<WasmBrowserHostPointerMenuSmokeState> state;
  return *state;
}

}  // namespace

void SetWasmBrowserHostPointerMenuSmokeVerificationForTesting(
    base::RepeatingCallback<bool(int)> check_callback,
    base::RepeatingCallback<bool(int)> presentation_callback) {
  GetWasmBrowserHostPointerMenuSmokeState().SetCallbacksOnUiThread(
      std::move(check_callback), std::move(presentation_callback));
}

void ClearWasmBrowserHostPointerMenuSmokeVerificationForTesting() {
  GetWasmBrowserHostPointerMenuSmokeState().ClearCallbacksOnUiThread();
}

extern "C" {

EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_pointer_menu_check(
    int stage) {
  return GetWasmBrowserHostPointerMenuSmokeState().PostCallback(
             HostPointerMenuSmokeCallback::kCheck, stage)
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_pointer_menu_presented(
    int stage) {
  return GetWasmBrowserHostPointerMenuSmokeState().PostCallback(
             HostPointerMenuSmokeCallback::kPresentation, stage)
             ? 1
             : 0;
}

}  // extern "C"

}  // namespace chrome
