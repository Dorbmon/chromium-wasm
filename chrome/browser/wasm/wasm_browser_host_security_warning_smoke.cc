// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_host_security_warning_smoke.h"

#include <cstdio>
#include <cstdint>
#include <utility>

#include "base/check.h"
#include "base/functional/bind.h"
#include "base/location.h"
#include "base/no_destructor.h"
#include "base/synchronization/lock.h"
#include "base/task/single_thread_task_runner.h"
#include "base/time/time.h"
#include "build/build_config.h"
#include "content/public/browser/browser_thread.h"
#include "emscripten/emscripten.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_host_security_warning_smoke.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kPostInputObservationFailedMarker[] =
    "CHROMIUM_WASM_M6_HOST_SECURITY_WARNING:OBSERVATION_FAILED";

// A pointer ABI call posts move/down/up independently to the Browser UI
// sequence.  The host has already withheld the first dialog observation until
// a strictly later canvas frame, but an in-flight Ozone release can still
// arrive after that first observation task.  Keep the test-only observer
// bounded and state-based: it never injects another event or calls a Browser
// command, and it reports a terminal marker rather than silently disabling
// itself if no post-input state becomes observable.
constexpr int kMaxPostInputObservationFailures = 8;
constexpr base::TimeDelta kPostInputObservationRetryInterval =
    base::Milliseconds(16);

enum class HostSecurityWarningSmokeCallback {
  kCheck,
  kPresentation,
};

enum class HostSecurityWarningSmokeExpectedCallback {
  kMenuCheck,
  kMenuPresentation,
  kDialogCheck,
  kDismissCheck,
  kDismissPresentation,
  kFinished,
};

enum class PostInputObservationRetryResult {
  kQueued,
  kExhausted,
  kInvalidated,
};

class WasmBrowserHostSecurityWarningSmokeState {
 public:
  WasmBrowserHostSecurityWarningSmokeState() = default;
  WasmBrowserHostSecurityWarningSmokeState(
      const WasmBrowserHostSecurityWarningSmokeState&) = delete;
  WasmBrowserHostSecurityWarningSmokeState& operator=(
      const WasmBrowserHostSecurityWarningSmokeState&) = delete;
  ~WasmBrowserHostSecurityWarningSmokeState() = default;

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
    post_input_observation_failures_ = 0;
    task_runner_ = std::move(task_runner);
    check_callback_ = std::move(check_callback);
    presentation_callback_ = std::move(presentation_callback);
    expected_callback_ = HostSecurityWarningSmokeExpectedCallback::kMenuCheck;
  }

  void ClearCallbacksOnUiThread() {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    base::AutoLock lock(lock_);
    ++generation_;
    accepting_ = false;
    dispatch_pending_ = false;
    post_input_observation_failures_ = 0;
    task_runner_ = nullptr;
    check_callback_.Reset();
    presentation_callback_.Reset();
    expected_callback_ = HostSecurityWarningSmokeExpectedCallback::kFinished;
  }

  bool PostCallback(HostSecurityWarningSmokeCallback callback, int stage) {
    base::AutoLock lock(lock_);
    if (!accepting_ || !task_runner_ || dispatch_pending_ ||
        !IsExpectedCallbackLocked(callback, stage)) {
      return false;
    }

    const uint64_t generation = generation_;
    if (!task_runner_->PostTask(
            FROM_HERE,
            base::BindOnce(
                &WasmBrowserHostSecurityWarningSmokeState::DispatchOnUiThread,
                base::Unretained(this), callback, stage, generation))) {
      return false;
    }
    // The UI callback advances only after the native coordinator has accepted
    // the preceding trusted pointer evidence.  In particular, stages 2 and 3
    // retain their expected ordinal for the bounded post-input observations
    // below rather than letting a premature check permanently disable proof.
    dispatch_pending_ = true;
    return true;
  }

 private:
  bool IsExpectedCallbackLocked(HostSecurityWarningSmokeCallback callback,
                                int stage) const
      EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    switch (expected_callback_) {
      case HostSecurityWarningSmokeExpectedCallback::kMenuCheck:
        return callback == HostSecurityWarningSmokeCallback::kCheck &&
               stage == 1;
      case HostSecurityWarningSmokeExpectedCallback::kMenuPresentation:
        return callback == HostSecurityWarningSmokeCallback::kPresentation &&
               stage == 1;
      case HostSecurityWarningSmokeExpectedCallback::kDialogCheck:
        return callback == HostSecurityWarningSmokeCallback::kCheck &&
               stage == 2;
      case HostSecurityWarningSmokeExpectedCallback::kDismissCheck:
        return callback == HostSecurityWarningSmokeCallback::kCheck &&
               stage == 3;
      case HostSecurityWarningSmokeExpectedCallback::kDismissPresentation:
        return callback == HostSecurityWarningSmokeCallback::kPresentation &&
               stage == 2;
      case HostSecurityWarningSmokeExpectedCallback::kFinished:
        return false;
    }
    NOTREACHED();
  }

  void AdvanceExpectedCallbackLocked() EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    switch (expected_callback_) {
      case HostSecurityWarningSmokeExpectedCallback::kMenuCheck:
        expected_callback_ =
            HostSecurityWarningSmokeExpectedCallback::kMenuPresentation;
        return;
      case HostSecurityWarningSmokeExpectedCallback::kMenuPresentation:
        expected_callback_ =
            HostSecurityWarningSmokeExpectedCallback::kDialogCheck;
        return;
      case HostSecurityWarningSmokeExpectedCallback::kDialogCheck:
        expected_callback_ =
            HostSecurityWarningSmokeExpectedCallback::kDismissCheck;
        return;
      case HostSecurityWarningSmokeExpectedCallback::kDismissCheck:
        expected_callback_ =
            HostSecurityWarningSmokeExpectedCallback::kDismissPresentation;
        return;
      case HostSecurityWarningSmokeExpectedCallback::kDismissPresentation:
        expected_callback_ =
            HostSecurityWarningSmokeExpectedCallback::kFinished;
        return;
      case HostSecurityWarningSmokeExpectedCallback::kFinished:
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
    post_input_observation_failures_ = 0;
    task_runner_ = nullptr;
    check_callback_.Reset();
    presentation_callback_.Reset();
    expected_callback_ = HostSecurityWarningSmokeExpectedCallback::kFinished;
  }

  bool IsPostInputObservationRetryable(
      HostSecurityWarningSmokeCallback callback,
      int stage) const {
    return callback == HostSecurityWarningSmokeCallback::kCheck &&
           (stage == 2 || stage == 3);
  }

  PostInputObservationRetryResult QueuePostInputObservation(
      HostSecurityWarningSmokeCallback callback,
      int stage,
      uint64_t generation) {
    scoped_refptr<base::SingleThreadTaskRunner> task_runner;
    int failures = 0;
    {
      base::AutoLock lock(lock_);
      if (!accepting_ || generation != generation_ || !dispatch_pending_ ||
          !task_runner_ || !IsExpectedCallbackLocked(callback, stage)) {
        return PostInputObservationRetryResult::kInvalidated;
      }
      failures = ++post_input_observation_failures_;
      if (failures >= kMaxPostInputObservationFailures) {
        return PostInputObservationRetryResult::kExhausted;
      }
      task_runner = task_runner_;
    }

    if (!task_runner->PostDelayedTask(
            FROM_HERE,
            base::BindOnce(
                &WasmBrowserHostSecurityWarningSmokeState::DispatchOnUiThread,
                base::Unretained(this), callback, stage, generation),
            kPostInputObservationRetryInterval)) {
      return PostInputObservationRetryResult::kExhausted;
    }
    return PostInputObservationRetryResult::kQueued;
  }

  void ReportPostInputObservationFailure(int stage, int attempts) {
    std::fprintf(stderr, "%s stage=%d attempts=%d\n",
                 kPostInputObservationFailedMarker, stage, attempts);
    std::fflush(stderr);
  }

  void DispatchOnUiThread(HostSecurityWarningSmokeCallback callback,
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
      callback_to_run = callback == HostSecurityWarningSmokeCallback::kCheck
                            ? check_callback_
                            : presentation_callback_;
    }
    if (!callback_to_run || !callback_to_run.Run(stage)) {
      if (IsPostInputObservationRetryable(callback, stage)) {
        const PostInputObservationRetryResult retry_result =
            QueuePostInputObservation(callback, stage, generation);
        if (retry_result == PostInputObservationRetryResult::kQueued ||
            retry_result == PostInputObservationRetryResult::kInvalidated) {
          return;
        }
        ReportPostInputObservationFailure(
            stage, kMaxPostInputObservationFailures);
      }
      // A copied/malformed host ordinal never becomes a Browser command. Make
      // the narrow test ABI inert if it loses its trusted-pointer ordering.
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
      post_input_observation_failures_ = 0;
      AdvanceExpectedCallbackLocked();
    }
  }

  base::Lock lock_;
  scoped_refptr<base::SingleThreadTaskRunner> task_runner_ GUARDED_BY(lock_);
  uint64_t generation_ GUARDED_BY(lock_) = 0;
  bool accepting_ GUARDED_BY(lock_) = false;
  bool dispatch_pending_ GUARDED_BY(lock_) = false;
  int post_input_observation_failures_ GUARDED_BY(lock_) = 0;
  HostSecurityWarningSmokeExpectedCallback expected_callback_
      GUARDED_BY(lock_) = HostSecurityWarningSmokeExpectedCallback::kFinished;
  base::RepeatingCallback<bool(int)> check_callback_ GUARDED_BY(lock_);
  base::RepeatingCallback<bool(int)> presentation_callback_ GUARDED_BY(lock_);
};

WasmBrowserHostSecurityWarningSmokeState&
GetWasmBrowserHostSecurityWarningSmokeState() {
  static base::NoDestructor<WasmBrowserHostSecurityWarningSmokeState> state;
  return *state;
}

}  // namespace

void SetWasmBrowserHostSecurityWarningSmokeVerificationForTesting(
    base::RepeatingCallback<bool(int)> check_callback,
    base::RepeatingCallback<bool(int)> presentation_callback) {
  GetWasmBrowserHostSecurityWarningSmokeState().SetCallbacksOnUiThread(
      std::move(check_callback), std::move(presentation_callback));
}

void ClearWasmBrowserHostSecurityWarningSmokeVerificationForTesting() {
  GetWasmBrowserHostSecurityWarningSmokeState().ClearCallbacksOnUiThread();
}

extern "C" {

EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_security_warning_check(
    int stage) {
  return GetWasmBrowserHostSecurityWarningSmokeState().PostCallback(
             HostSecurityWarningSmokeCallback::kCheck, stage)
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int
chromium_wasm_browser_host_security_warning_presented(int stage) {
  return GetWasmBrowserHostSecurityWarningSmokeState().PostCallback(
             HostSecurityWarningSmokeCallback::kPresentation, stage)
             ? 1
             : 0;
}

}  // extern "C"

}  // namespace chrome
