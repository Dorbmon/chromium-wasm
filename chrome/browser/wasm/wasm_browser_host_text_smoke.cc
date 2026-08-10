// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_host_text_smoke.h"

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
#error "wasm_browser_host_text_smoke.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

enum class HostTextSmokeExpectedCheck {
  kFocus,
  kInsertedText,
  kNavigation,
  kFinished,
};

class WasmBrowserHostTextSmokeState {
 public:
  WasmBrowserHostTextSmokeState() = default;
  WasmBrowserHostTextSmokeState(const WasmBrowserHostTextSmokeState&) =
      delete;
  WasmBrowserHostTextSmokeState& operator=(
      const WasmBrowserHostTextSmokeState&) = delete;
  ~WasmBrowserHostTextSmokeState() = default;

  void SetCallbackOnUiThread(base::RepeatingCallback<bool(int)> callback) {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    CHECK(callback);
    scoped_refptr<base::SingleThreadTaskRunner> task_runner =
        base::SingleThreadTaskRunner::GetCurrentDefault();
    CHECK(task_runner);

    base::AutoLock lock(lock_);
    CHECK(!accepting_);
    CHECK(!task_runner_);
    ++generation_;
    accepting_ = true;
    task_runner_ = std::move(task_runner);
    callback_ = std::move(callback);
    expected_check_ = HostTextSmokeExpectedCheck::kFocus;
  }

  void ClearCallbackOnUiThread() {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    base::AutoLock lock(lock_);
    ++generation_;
    accepting_ = false;
    task_runner_ = nullptr;
    callback_.Reset();
    expected_check_ = HostTextSmokeExpectedCheck::kFinished;
  }

  bool PostCheck(int stage) {
    base::AutoLock lock(lock_);
    if (!accepting_ || !task_runner_ || !IsExpectedCheckLocked(stage)) {
      return false;
    }
    const uint64_t generation = generation_;
    if (!task_runner_->PostTask(
            FROM_HERE,
            base::BindOnce(&WasmBrowserHostTextSmokeState::RunCheckOnUiThread,
                           base::Unretained(this), stage, generation))) {
      return false;
    }
    AdvanceExpectedCheckLocked();
    return true;
  }

 private:
  bool IsExpectedCheckLocked(int stage) const EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    switch (expected_check_) {
      case HostTextSmokeExpectedCheck::kFocus:
        return stage == 1;
      case HostTextSmokeExpectedCheck::kInsertedText:
        return stage == 2;
      case HostTextSmokeExpectedCheck::kNavigation:
        return stage == 3;
      case HostTextSmokeExpectedCheck::kFinished:
        return false;
    }
    NOTREACHED();
  }

  void AdvanceExpectedCheckLocked() EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    switch (expected_check_) {
      case HostTextSmokeExpectedCheck::kFocus:
        expected_check_ = HostTextSmokeExpectedCheck::kInsertedText;
        return;
      case HostTextSmokeExpectedCheck::kInsertedText:
        expected_check_ = HostTextSmokeExpectedCheck::kNavigation;
        return;
      case HostTextSmokeExpectedCheck::kNavigation:
        expected_check_ = HostTextSmokeExpectedCheck::kFinished;
        return;
      case HostTextSmokeExpectedCheck::kFinished:
        NOTREACHED();
    }
  }

  void DisableAfterFailedCheck(uint64_t generation) {
    base::AutoLock lock(lock_);
    if (generation != generation_) {
      return;
    }
    ++generation_;
    accepting_ = false;
    task_runner_ = nullptr;
    callback_.Reset();
    expected_check_ = HostTextSmokeExpectedCheck::kFinished;
  }

  void RunCheckOnUiThread(int stage, uint64_t generation) {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    base::RepeatingCallback<bool(int)> callback;
    {
      base::AutoLock lock(lock_);
      if (!accepting_ || generation != generation_ || !callback_) {
        return;
      }
      callback = callback_;
    }
    if (!callback.Run(stage)) {
      // A semantically premature host record becomes inert instead of
      // converting a test-only ABI misuse into a Browser CHECK/abort.
      DisableAfterFailedCheck(generation);
    }
  }

  base::Lock lock_;
  scoped_refptr<base::SingleThreadTaskRunner> task_runner_ GUARDED_BY(lock_);
  uint64_t generation_ GUARDED_BY(lock_) = 0;
  bool accepting_ GUARDED_BY(lock_) = false;
  HostTextSmokeExpectedCheck expected_check_ GUARDED_BY(lock_) =
      HostTextSmokeExpectedCheck::kFinished;
  base::RepeatingCallback<bool(int)> callback_ GUARDED_BY(lock_);
};

WasmBrowserHostTextSmokeState& GetWasmBrowserHostTextSmokeState() {
  static base::NoDestructor<WasmBrowserHostTextSmokeState> state;
  return *state;
}

}  // namespace

void SetWasmBrowserHostTextSmokeVerificationForTesting(
    base::RepeatingCallback<bool(int)> check_callback) {
  GetWasmBrowserHostTextSmokeState().SetCallbackOnUiThread(
      std::move(check_callback));
}

void ClearWasmBrowserHostTextSmokeVerificationForTesting() {
  GetWasmBrowserHostTextSmokeState().ClearCallbackOnUiThread();
}

extern "C" {

EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_text_smoke_check(
    int stage) {
  return GetWasmBrowserHostTextSmokeState().PostCheck(stage) ? 1 : 0;
}

}  // extern "C"

}  // namespace chrome
