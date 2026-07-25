// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/profiler/stack_sampler.h"

#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "stack_sampler_wasm.cc must only be built for WebAssembly"
#endif

namespace base {

// static
std::unique_ptr<StackSampler> StackSampler::Create(
    SamplingProfilerThreadToken thread_token,
    scoped_refptr<StackUnwindData> stack_unwind_data,
    UnwindersFactory core_unwinders_factory,
    RepeatingClosure record_sample_callback,
    StackSamplerTestDelegate* test_delegate) {
  // Browser workers cannot suspend one another or expose their native stacks.
  return nullptr;
}

// static
size_t StackSampler::GetStackBufferSize() {
  return 0;
}

}  // namespace base
