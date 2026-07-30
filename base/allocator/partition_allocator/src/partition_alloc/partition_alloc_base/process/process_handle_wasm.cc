// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "partition_alloc/partition_alloc_base/process/process_handle.h"

#include "partition_alloc/build_config.h"

#if !PA_BUILDFLAG(IS_WASM)
#error "process_handle_wasm.cc must only be built for WebAssembly"
#endif

namespace partition_alloc::internal::base {

ProcessId GetCurrentProcId() {
  // Chromium services share one Wasm module and one process-local address
  // space. Use a stable non-null identifier rather than implying host process
  // management support.
  return 1;
}

}  // namespace partition_alloc::internal::base
