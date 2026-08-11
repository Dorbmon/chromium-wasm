// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_host_storage_estimate.h"

#include <cmath>
#include <limits>
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
#error "wasm_browser_host_storage_estimate.cc must only be built for WebAssembly"
#endif

extern "C" int chromium_wasm_request_outer_origin_storage_estimate(
    int generation);

namespace chrome {

namespace {

// JavaScript Numbers represent every integer in this range exactly. Keep the
// C ABI inside it, rather than allowing a rounded host value to masquerade as
// a precise capacity measurement.
constexpr uint64_t kMaximumExactHostStorageBytes = (UINT64_C(1) << 53) - 1;
constexpr int kHostStorageEstimateAvailable = 1;
constexpr int kHostStorageEstimateUnavailable = 2;
constexpr int kHostStorageEstimateError = 3;

bool IsExactNonnegativeHostStorageBytes(double value, uint64_t* bytes) {
  CHECK(bytes);
  if (!std::isfinite(value) || value < 0 || std::floor(value) != value ||
      value > static_cast<double>(kMaximumExactHostStorageBytes)) {
    return false;
  }
  *bytes = static_cast<uint64_t>(value);
  return true;
}

bool ValidateHostStorageEstimateCompletion(int generation,
                                           int outcome,
                                           double usage_bytes,
                                           double quota_bytes,
                                           uint64_t* usage,
                                           uint64_t* quota) {
  CHECK(usage);
  CHECK(quota);
  if (generation <= 0) {
    return false;
  }

  switch (outcome) {
    case kHostStorageEstimateAvailable:
      if (!IsExactNonnegativeHostStorageBytes(usage_bytes, usage) ||
          !IsExactNonnegativeHostStorageBytes(quota_bytes, quota)) {
        return false;
      }
      // A lower quota would make a fabricated remaining-capacity calculation
      // look meaningful. Reject the malformed result instead of presenting a
      // guessed low-space state.
      return *usage <= *quota;
    case kHostStorageEstimateUnavailable:
    case kHostStorageEstimateError:
      // Unavailable/error results deliberately carry no host error detail or
      // stale numeric value across the JS/C++ boundary.
      if (usage_bytes != 0 || quota_bytes != 0) {
        return false;
      }
      *usage = 0;
      *quota = 0;
      return true;
  }
  return false;
}

class WasmBrowserHostStorageEstimateState {
 public:
  WasmBrowserHostStorageEstimateState()
      : snapshot_(base::MakeRefCounted<WasmBrowserHostStorageEstimateSnapshot>(
            /*generation=*/0,
            WasmBrowserHostStorageEstimateSnapshot::State::kUnavailable,
            /*usage_bytes=*/0, /*quota_bytes=*/0)) {}
  WasmBrowserHostStorageEstimateState(
      const WasmBrowserHostStorageEstimateState&) = delete;
  WasmBrowserHostStorageEstimateState& operator=(
      const WasmBrowserHostStorageEstimateState&) = delete;
  ~WasmBrowserHostStorageEstimateState() = default;

  bool InitializeOnUiThread() {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    scoped_refptr<base::SingleThreadTaskRunner> task_runner =
        base::SingleThreadTaskRunner::GetCurrentDefault();
    if (!task_runner) {
      return false;
    }

    int generation = 0;
    {
      base::AutoLock lock(lock_);
      if (accepting_completions_ || ever_initialized_ ||
          permanently_shutdown_) {
        return false;
      }
      // This process owns one diagnostic request. Keep the C ABI generation
      // positive and signed so JavaScript can validate it exactly as an int.
      if (generation_ == std::numeric_limits<int>::max()) {
        return false;
      }
      generation_++;
      generation = generation_;
      ever_initialized_ = true;
      accepting_completions_ = true;
      task_runner_ = std::move(task_runner);
      completion_posted_ = false;
      completion_terminal_ = false;
      SetSnapshotLocked(generation,
                        WasmBrowserHostStorageEstimateSnapshot::State::kPending,
                        /*usage_bytes=*/0, /*quota_bytes=*/0);
    }

    // This host import only schedules navigator.storage.estimate(). Its
    // synchronous return reports whether a compatible host bridge accepted
    // the request, not whether a storage estimate exists. Missing support is
    // an explicit unavailable diagnostic, not a startup failure or a fake
    // profile quota.
    if (chromium_wasm_request_outer_origin_storage_estimate(generation) != 1) {
      SetUnavailableOnUiThread(generation);
    }
    return true;
  }

  void ShutdownOnUiThread() {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    base::AutoLock lock(lock_);
    if (!ever_initialized_ || permanently_shutdown_) {
      return;
    }
    if (generation_ != std::numeric_limits<int>::max()) {
      ++generation_;
    }
    accepting_completions_ = false;
    completion_posted_ = false;
    completion_terminal_ = true;
    task_runner_ = nullptr;
    permanently_shutdown_ = true;
  }

  scoped_refptr<const WasmBrowserHostStorageEstimateSnapshot> Snapshot() const {
    base::AutoLock lock(lock_);
    return snapshot_;
  }

  bool PostCompletion(int generation,
                      int outcome,
                      uint64_t usage_bytes,
                      uint64_t quota_bytes) {
    base::AutoLock lock(lock_);
    if (!accepting_completions_ || !task_runner_ || completion_posted_ ||
        completion_terminal_ ||
        snapshot_->state() !=
            WasmBrowserHostStorageEstimateSnapshot::State::kPending ||
        generation <= 0 || generation != generation_) {
      return false;
    }
    completion_posted_ = true;
    if (task_runner_->PostTask(
        FROM_HERE,
        base::BindOnce(
            &WasmBrowserHostStorageEstimateState::DispatchCompletionOnUiThread,
            base::Unretained(this), generation, outcome, usage_bytes,
            quota_bytes))) {
      return true;
    }
    completion_posted_ = false;
    return false;
  }

 private:
  void SetSnapshotLocked(
      int generation,
      WasmBrowserHostStorageEstimateSnapshot::State state,
      uint64_t usage_bytes,
      uint64_t quota_bytes) EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    snapshot_ = base::MakeRefCounted<WasmBrowserHostStorageEstimateSnapshot>(
        static_cast<uint32_t>(generation), state, usage_bytes, quota_bytes);
  }

  void SetUnavailableOnUiThread(int generation) {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    base::AutoLock lock(lock_);
    if (!accepting_completions_ || completion_posted_ || completion_terminal_ ||
        snapshot_->state() !=
            WasmBrowserHostStorageEstimateSnapshot::State::kPending ||
        generation != generation_) {
      return;
    }
    completion_terminal_ = true;
    SetSnapshotLocked(generation,
                      WasmBrowserHostStorageEstimateSnapshot::State::kUnavailable,
                      /*usage_bytes=*/0, /*quota_bytes=*/0);
  }

  void DispatchCompletionOnUiThread(int generation,
                                    int outcome,
                                    uint64_t usage_bytes,
                                    uint64_t quota_bytes) {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    base::AutoLock lock(lock_);
    if (!accepting_completions_ || !completion_posted_ ||
        completion_terminal_ ||
        snapshot_->state() !=
            WasmBrowserHostStorageEstimateSnapshot::State::kPending ||
        generation != generation_) {
      return;
    }
    completion_posted_ = false;
    completion_terminal_ = true;
    SetSnapshotLocked(
        generation,
        outcome == kHostStorageEstimateAvailable
            ? WasmBrowserHostStorageEstimateSnapshot::State::kAvailable
            : outcome == kHostStorageEstimateUnavailable
                  ? WasmBrowserHostStorageEstimateSnapshot::State::kUnavailable
                  : WasmBrowserHostStorageEstimateSnapshot::State::kError,
        usage_bytes, quota_bytes);
  }

  mutable base::Lock lock_;
  scoped_refptr<base::SingleThreadTaskRunner> task_runner_ GUARDED_BY(lock_);
  scoped_refptr<const WasmBrowserHostStorageEstimateSnapshot> snapshot_
      GUARDED_BY(lock_);
  int generation_ GUARDED_BY(lock_) = 0;
  bool accepting_completions_ GUARDED_BY(lock_) = false;
  bool completion_posted_ GUARDED_BY(lock_) = false;
  bool completion_terminal_ GUARDED_BY(lock_) = false;
  bool ever_initialized_ GUARDED_BY(lock_) = false;
  bool permanently_shutdown_ GUARDED_BY(lock_) = false;
};

WasmBrowserHostStorageEstimateState& GetWasmBrowserHostStorageEstimateState() {
  static base::NoDestructor<WasmBrowserHostStorageEstimateState> state;
  return *state;
}

}  // namespace

WasmBrowserHostStorageEstimateSnapshot::WasmBrowserHostStorageEstimateSnapshot(
    uint32_t generation,
    State state,
    uint64_t usage_bytes,
    uint64_t quota_bytes)
    : generation_(generation),
      state_(state),
      usage_bytes_(usage_bytes),
      quota_bytes_(quota_bytes) {}

WasmBrowserHostStorageEstimateSnapshot::~WasmBrowserHostStorageEstimateSnapshot() =
    default;

bool InitializeWasmBrowserHostStorageEstimate() {
  return GetWasmBrowserHostStorageEstimateState().InitializeOnUiThread();
}

void ShutdownWasmBrowserHostStorageEstimate() {
  GetWasmBrowserHostStorageEstimateState().ShutdownOnUiThread();
}

scoped_refptr<const WasmBrowserHostStorageEstimateSnapshot>
GetWasmBrowserHostStorageEstimateSnapshot() {
  return GetWasmBrowserHostStorageEstimateState().Snapshot();
}

extern "C" {

EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_storage_estimate_complete(
    int generation,
    int outcome,
    double usage_bytes,
    double quota_bytes) {
  uint64_t usage = 0;
  uint64_t quota = 0;
  if (!ValidateHostStorageEstimateCompletion(generation, outcome, usage_bytes,
                                             quota_bytes, &usage, &quota)) {
    return 0;
  }
  return GetWasmBrowserHostStorageEstimateState().PostCompletion(
             generation, outcome, usage, quota)
             ? 1
             : 0;
}

}  // extern "C"

}  // namespace chrome
