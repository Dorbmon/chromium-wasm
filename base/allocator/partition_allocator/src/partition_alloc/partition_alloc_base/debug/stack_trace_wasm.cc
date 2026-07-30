// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "partition_alloc/partition_alloc_base/debug/stack_trace.h"

#include <cstddef>

#include "partition_alloc/build_config.h"
#include "partition_alloc/partition_alloc_base/compiler_specific.h"
#include "partition_alloc/partition_alloc_base/logging.h"
#include "partition_alloc/partition_alloc_base/strings/safe_sprintf.h"

#if !PA_BUILDFLAG(IS_WASM)
#error "stack_trace_wasm.cc must only be built for WebAssembly"
#endif

namespace partition_alloc::internal::base::debug {

size_t CollectStackTrace(const void** trace, size_t count) {
  static_cast<void>(trace);
  static_cast<void>(count);
  // Emscripten implements return-address collection by creating and parsing a
  // JavaScript Error stack. That can allocate and is therefore unsafe inside
  // PartitionAlloc diagnostics. Report native stack collection as unsupported.
  return 0;
}

void PrintStackTrace(const void** trace, size_t count) {
  for (size_t index = 0; index < count; ++index) {
    char buffer[64];
    strings::SafeSPrintf(buffer, "#%02d %p\n", index,
                         PA_UNSAFE_TODO(trace[index]));
    PA_RAW_LOG(INFO, buffer);
  }
}

}  // namespace partition_alloc::internal::base::debug
