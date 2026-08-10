// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_host_history_downloads_smoke.h"

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
#error "wasm_browser_host_history_downloads_smoke.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

enum class HostHistoryDownloadsSmokeCallback {
  kCheck,
  kPresentation,
};

enum class HostHistoryDownloadsSmokeExpectedCallback {
  kSecondTabCheck,
  kHistoryMenuOpenCheck,
  kHistoryMenuClosedCheck,
  kDownloadsMenuOpenCheck,
  kDownloadsMenuClosedCheck,
  kFinalPresentation,
  kFinished,
};

class WasmBrowserHostHistoryDownloadsSmokeState {
 public:
  WasmBrowserHostHistoryDownloadsSmokeState() = default;
  WasmBrowserHostHistoryDownloadsSmokeState(
      const WasmBrowserHostHistoryDownloadsSmokeState&) = delete;
  WasmBrowserHostHistoryDownloadsSmokeState& operator=(
      const WasmBrowserHostHistoryDownloadsSmokeState&) = delete;
  ~WasmBrowserHostHistoryDownloadsSmokeState() = default;

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
    expected_callback_ =
        HostHistoryDownloadsSmokeExpectedCallback::kSecondTabCheck;
  }

  void ClearCallbacksOnUiThread() {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    base::AutoLock lock(lock_);
    ++generation_;
    accepting_ = false;
    task_runner_ = nullptr;
    check_callback_.Reset();
    presentation_callback_.Reset();
    expected_callback_ = HostHistoryDownloadsSmokeExpectedCallback::kFinished;
  }

  bool PostCallback(HostHistoryDownloadsSmokeCallback callback, int stage) {
    base::AutoLock lock(lock_);
    if (!accepting_ || !task_runner_ ||
        !IsExpectedCallbackLocked(callback, stage)) {
      return false;
    }
    const uint64_t generation = generation_;
    if (!task_runner_->PostTask(
            FROM_HERE,
            base::BindOnce(
                &WasmBrowserHostHistoryDownloadsSmokeState::DispatchOnUiThread,
                base::Unretained(this), callback, stage, generation))) {
      return false;
    }
    AdvanceExpectedCallbackLocked();
    return true;
  }

 private:
  bool IsExpectedCallbackLocked(HostHistoryDownloadsSmokeCallback callback,
                                int stage) const
      EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    switch (expected_callback_) {
      case HostHistoryDownloadsSmokeExpectedCallback::kSecondTabCheck:
        return callback == HostHistoryDownloadsSmokeCallback::kCheck &&
               stage == 1;
      case HostHistoryDownloadsSmokeExpectedCallback::kHistoryMenuOpenCheck:
        return callback == HostHistoryDownloadsSmokeCallback::kCheck &&
               stage == 2;
      case HostHistoryDownloadsSmokeExpectedCallback::kHistoryMenuClosedCheck:
        return callback == HostHistoryDownloadsSmokeCallback::kCheck &&
               stage == 3;
      case HostHistoryDownloadsSmokeExpectedCallback::kDownloadsMenuOpenCheck:
        return callback == HostHistoryDownloadsSmokeCallback::kCheck &&
               stage == 4;
      case HostHistoryDownloadsSmokeExpectedCallback::kDownloadsMenuClosedCheck:
        return callback == HostHistoryDownloadsSmokeCallback::kCheck &&
               stage == 5;
      case HostHistoryDownloadsSmokeExpectedCallback::kFinalPresentation:
        return callback == HostHistoryDownloadsSmokeCallback::kPresentation &&
               stage == 6;
      case HostHistoryDownloadsSmokeExpectedCallback::kFinished:
        return false;
    }
    NOTREACHED();
  }

  void AdvanceExpectedCallbackLocked() EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    switch (expected_callback_) {
      case HostHistoryDownloadsSmokeExpectedCallback::kSecondTabCheck:
        expected_callback_ =
            HostHistoryDownloadsSmokeExpectedCallback::kHistoryMenuOpenCheck;
        return;
      case HostHistoryDownloadsSmokeExpectedCallback::kHistoryMenuOpenCheck:
        expected_callback_ =
            HostHistoryDownloadsSmokeExpectedCallback::kHistoryMenuClosedCheck;
        return;
      case HostHistoryDownloadsSmokeExpectedCallback::kHistoryMenuClosedCheck:
        expected_callback_ =
            HostHistoryDownloadsSmokeExpectedCallback::kDownloadsMenuOpenCheck;
        return;
      case HostHistoryDownloadsSmokeExpectedCallback::kDownloadsMenuOpenCheck:
        expected_callback_ = HostHistoryDownloadsSmokeExpectedCallback::
            kDownloadsMenuClosedCheck;
        return;
      case HostHistoryDownloadsSmokeExpectedCallback::kDownloadsMenuClosedCheck:
        expected_callback_ =
            HostHistoryDownloadsSmokeExpectedCallback::kFinalPresentation;
        return;
      case HostHistoryDownloadsSmokeExpectedCallback::kFinalPresentation:
        expected_callback_ = HostHistoryDownloadsSmokeExpectedCallback::kFinished;
        return;
      case HostHistoryDownloadsSmokeExpectedCallback::kFinished:
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
    expected_callback_ = HostHistoryDownloadsSmokeExpectedCallback::kFinished;
  }

  void DispatchOnUiThread(HostHistoryDownloadsSmokeCallback callback,
                          int stage,
                          uint64_t generation) {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    base::RepeatingCallback<bool(int)> callback_to_run;
    {
      base::AutoLock lock(lock_);
      if (!accepting_ || generation != generation_) {
        return;
      }
      callback_to_run = callback == HostHistoryDownloadsSmokeCallback::kCheck
                            ? check_callback_
                            : presentation_callback_;
    }
    if (!callback_to_run || !callback_to_run.Run(stage)) {
      // Reject malformed/misordered host observations without turning the
      // verifier into an application command surface or a Browser CHECK.
      DisableAfterFailedCallback(generation);
    }
  }

  base::Lock lock_;
  scoped_refptr<base::SingleThreadTaskRunner> task_runner_ GUARDED_BY(lock_);
  uint64_t generation_ GUARDED_BY(lock_) = 0;
  bool accepting_ GUARDED_BY(lock_) = false;
  HostHistoryDownloadsSmokeExpectedCallback expected_callback_
      GUARDED_BY(lock_) = HostHistoryDownloadsSmokeExpectedCallback::kFinished;
  base::RepeatingCallback<bool(int)> check_callback_ GUARDED_BY(lock_);
  base::RepeatingCallback<bool(int)> presentation_callback_ GUARDED_BY(lock_);
};

WasmBrowserHostHistoryDownloadsSmokeState&
GetWasmBrowserHostHistoryDownloadsSmokeState() {
  static base::NoDestructor<WasmBrowserHostHistoryDownloadsSmokeState> state;
  return *state;
}

}  // namespace

void SetWasmBrowserHostHistoryDownloadsSmokeVerificationForTesting(
    base::RepeatingCallback<bool(int)> check_callback,
    base::RepeatingCallback<bool(int)> presentation_callback) {
  GetWasmBrowserHostHistoryDownloadsSmokeState().SetCallbacksOnUiThread(
      std::move(check_callback), std::move(presentation_callback));
}

void ClearWasmBrowserHostHistoryDownloadsSmokeVerificationForTesting() {
  GetWasmBrowserHostHistoryDownloadsSmokeState().ClearCallbacksOnUiThread();
}

extern "C" {

EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_history_downloads_check(
    int stage) {
  return GetWasmBrowserHostHistoryDownloadsSmokeState().PostCallback(
             HostHistoryDownloadsSmokeCallback::kCheck, stage)
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int
chromium_wasm_browser_host_history_downloads_presented(int stage) {
  return GetWasmBrowserHostHistoryDownloadsSmokeState().PostCallback(
             HostHistoryDownloadsSmokeCallback::kPresentation, stage)
             ? 1
             : 0;
}

}  // extern "C"

}  // namespace chrome
