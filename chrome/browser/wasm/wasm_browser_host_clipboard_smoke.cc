// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_host_clipboard_smoke.h"

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
#error "wasm_browser_host_clipboard_smoke.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

enum class HostClipboardSmokeExpectedCheck {
  kFocus,
  kPastedText,
  kNavigation,
  kFinished,
};

class WasmBrowserHostClipboardSmokeState {
 public:
  WasmBrowserHostClipboardSmokeState() = default;
  WasmBrowserHostClipboardSmokeState(
      const WasmBrowserHostClipboardSmokeState&) = delete;
  WasmBrowserHostClipboardSmokeState& operator=(
      const WasmBrowserHostClipboardSmokeState&) = delete;
  ~WasmBrowserHostClipboardSmokeState() = default;

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
    expected_check_ = HostClipboardSmokeExpectedCheck::kFocus;
  }

  void ClearCallbackOnUiThread() {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    base::AutoLock lock(lock_);
    ++generation_;
    accepting_ = false;
    task_runner_ = nullptr;
    callback_.Reset();
    expected_check_ = HostClipboardSmokeExpectedCheck::kFinished;
  }

  bool PostCheck(int stage) {
    base::AutoLock lock(lock_);
    if (!accepting_ || !task_runner_ || !IsExpectedCheckLocked(stage)) {
      return false;
    }
    const uint64_t generation = generation_;
    if (!task_runner_->PostTask(
            FROM_HERE,
            base::BindOnce(
                &WasmBrowserHostClipboardSmokeState::RunCheckOnUiThread,
                base::Unretained(this), stage, generation))) {
      return false;
    }
    AdvanceExpectedCheckLocked();
    return true;
  }

 private:
  bool IsExpectedCheckLocked(int stage) const EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    switch (expected_check_) {
      case HostClipboardSmokeExpectedCheck::kFocus:
        return stage == 1;
      case HostClipboardSmokeExpectedCheck::kPastedText:
        return stage == 2;
      case HostClipboardSmokeExpectedCheck::kNavigation:
        return stage == 3;
      case HostClipboardSmokeExpectedCheck::kFinished:
        return false;
    }
    NOTREACHED();
  }

  void AdvanceExpectedCheckLocked() EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    switch (expected_check_) {
      case HostClipboardSmokeExpectedCheck::kFocus:
        expected_check_ = HostClipboardSmokeExpectedCheck::kPastedText;
        return;
      case HostClipboardSmokeExpectedCheck::kPastedText:
        expected_check_ = HostClipboardSmokeExpectedCheck::kNavigation;
        return;
      case HostClipboardSmokeExpectedCheck::kNavigation:
        expected_check_ = HostClipboardSmokeExpectedCheck::kFinished;
        return;
      case HostClipboardSmokeExpectedCheck::kFinished:
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
    expected_check_ = HostClipboardSmokeExpectedCheck::kFinished;
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
      // A premature host ordinal becomes inert rather than turning a test
      // misuse into a Browser CHECK or a false host-integration success.
      DisableAfterFailedCheck(generation);
    }
  }

  base::Lock lock_;
  scoped_refptr<base::SingleThreadTaskRunner> task_runner_ GUARDED_BY(lock_);
  uint64_t generation_ GUARDED_BY(lock_) = 0;
  bool accepting_ GUARDED_BY(lock_) = false;
  HostClipboardSmokeExpectedCheck expected_check_ GUARDED_BY(lock_) =
      HostClipboardSmokeExpectedCheck::kFinished;
  base::RepeatingCallback<bool(int)> callback_ GUARDED_BY(lock_);
};

WasmBrowserHostClipboardSmokeState& GetWasmBrowserHostClipboardSmokeState() {
  static base::NoDestructor<WasmBrowserHostClipboardSmokeState> state;
  return *state;
}

}  // namespace

void SetWasmBrowserHostClipboardSmokeVerificationForTesting(
    base::RepeatingCallback<bool(int)> check_callback) {
  GetWasmBrowserHostClipboardSmokeState().SetCallbackOnUiThread(
      std::move(check_callback));
}

void ClearWasmBrowserHostClipboardSmokeVerificationForTesting() {
  GetWasmBrowserHostClipboardSmokeState().ClearCallbackOnUiThread();
}

extern "C" {

EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_clipboard_smoke_check(
    int stage) {
  return GetWasmBrowserHostClipboardSmokeState().PostCheck(stage) ? 1 : 0;
}

}  // extern "C"

}  // namespace chrome
