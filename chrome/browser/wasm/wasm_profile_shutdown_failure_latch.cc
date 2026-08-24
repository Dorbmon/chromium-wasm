// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_shutdown_failure_latch.h"

#include "base/no_destructor.h"
#include "base/synchronization/lock.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_profile_shutdown_failure_latch.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

class WasmProfileShutdownFailureLatch {
 public:
  WasmProfileShutdownFailureLatch() = default;
  WasmProfileShutdownFailureLatch(const WasmProfileShutdownFailureLatch&) =
      delete;
  WasmProfileShutdownFailureLatch& operator=(
      const WasmProfileShutdownFailureLatch&) = delete;
  ~WasmProfileShutdownFailureLatch() = default;

  void Reset() {
    base::AutoLock lock(lock_);
    failure_recorded_ = false;
  }

  void RecordFailure() {
    base::AutoLock lock(lock_);
    failure_recorded_ = true;
  }

  bool failure_recorded() const {
    base::AutoLock lock(lock_);
    return failure_recorded_;
  }

 private:
  mutable base::Lock lock_;
  bool failure_recorded_ GUARDED_BY(lock_) = false;
};

WasmProfileShutdownFailureLatch& GetWasmProfileShutdownFailureLatch() {
  static base::NoDestructor<WasmProfileShutdownFailureLatch> latch;
  return *latch;
}

}  // namespace

void ResetWasmProfileShutdownFailureLatch() {
  GetWasmProfileShutdownFailureLatch().Reset();
}

void RecordWasmProfileShutdownFailure() {
  GetWasmProfileShutdownFailureLatch().RecordFailure();
}

bool WasmProfileShutdownFailureWasRecorded() {
  return GetWasmProfileShutdownFailureLatch().failure_recorded();
}

}  // namespace chrome
