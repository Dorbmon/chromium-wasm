// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/profiler/core_unwinders.h"

#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "core_unwinders_wasm.cc must only be built for WebAssembly"
#endif

namespace base {

StackSamplingProfiler::UnwindersFactory CreateCoreUnwindersFactory() {
  // Browser workers cannot inspect or unwind one another's native stacks.
  return StackSamplingProfiler::UnwindersFactory();
}

}  // namespace base
