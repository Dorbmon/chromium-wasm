// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_host_lifecycle.h"

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
#error "wasm_browser_host_lifecycle.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

class WasmBrowserHostLifecycleState {
 public:
  WasmBrowserHostLifecycleState() = default;
  WasmBrowserHostLifecycleState(const WasmBrowserHostLifecycleState&) = delete;
  WasmBrowserHostLifecycleState& operator=(
      const WasmBrowserHostLifecycleState&) = delete;
  ~WasmBrowserHostLifecycleState() = default;

  bool InitializeOnUiThread(base::RepeatingClosure request_shutdown) {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    if (!request_shutdown) {
      return false;
    }

    scoped_refptr<base::SingleThreadTaskRunner> task_runner =
        base::SingleThreadTaskRunner::GetCurrentDefault();
    if (!task_runner) {
      return false;
    }

    base::AutoLock lock(lock_);
    CHECK(!accepting_shutdown_requests_);
    CHECK(!task_runner_);
    CHECK(!request_shutdown_);
    ++generation_;
    accepting_shutdown_requests_ = true;
    shutdown_requested_ = false;
    task_runner_ = std::move(task_runner);
    request_shutdown_ = std::move(request_shutdown);
    return true;
  }

  void ShutdownOnUiThread() {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    base::AutoLock lock(lock_);
    ++generation_;
    accepting_shutdown_requests_ = false;
    shutdown_requested_ = false;
    task_runner_ = nullptr;
    request_shutdown_.Reset();
  }

  bool PostShutdownRequest() {
    base::AutoLock lock(lock_);
    if (!accepting_shutdown_requests_ || shutdown_requested_ ||
        !task_runner_ || !request_shutdown_) {
      return false;
    }

    const uint64_t generation = generation_;
    shutdown_requested_ = true;
    if (task_runner_->PostTask(
            FROM_HERE,
            base::BindOnce(
                &WasmBrowserHostLifecycleState::RunShutdownOnUiThread,
                base::Unretained(this), generation))) {
      return true;
    }

    if (generation == generation_) {
      shutdown_requested_ = false;
    }
    return false;
  }

 private:
  void RunShutdownOnUiThread(uint64_t generation) {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    base::RepeatingClosure request_shutdown;
    {
      base::AutoLock lock(lock_);
      if (!accepting_shutdown_requests_ || generation != generation_ ||
          !shutdown_requested_ || !request_shutdown_) {
        return;
      }
      request_shutdown = request_shutdown_;
    }
    request_shutdown.Run();
  }

  mutable base::Lock lock_;
  scoped_refptr<base::SingleThreadTaskRunner> task_runner_
      GUARDED_BY(lock_);
  base::RepeatingClosure request_shutdown_ GUARDED_BY(lock_);
  uint64_t generation_ GUARDED_BY(lock_) = 0;
  bool accepting_shutdown_requests_ GUARDED_BY(lock_) = false;
  bool shutdown_requested_ GUARDED_BY(lock_) = false;
};

WasmBrowserHostLifecycleState& GetWasmBrowserHostLifecycleState() {
  static base::NoDestructor<WasmBrowserHostLifecycleState> state;
  return *state;
}

}  // namespace

bool InitializeWasmBrowserHostLifecycle(
    base::RepeatingClosure request_shutdown) {
  return GetWasmBrowserHostLifecycleState().InitializeOnUiThread(
      std::move(request_shutdown));
}

void ShutdownWasmBrowserHostLifecycle() {
  GetWasmBrowserHostLifecycleState().ShutdownOnUiThread();
}

extern "C" {

EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_request_shutdown() {
  return GetWasmBrowserHostLifecycleState().PostShutdownRequest() ? 1 : 0;
}

}  // extern "C"

}  // namespace chrome
