// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "services/resource_coordinator/public/cpp/memory_instrumentation/os_metrics.h"

#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "This file must only be compiled for Wasm."
#endif

namespace memory_instrumentation {

// static
bool OSMetrics::FillOSMemoryDump(base::ProcessHandle,
                                 const MemDumpFlagSet&,
                                 mojom::RawOSMemDump*) {
  // The web platform does not expose native process memory measurements.
  return false;
}

// static
std::vector<mojom::VmRegionPtr> OSMetrics::GetProcessMemoryMaps(
    base::ProcessHandle) {
  // The web platform does not expose native process memory maps.
  return {};
}

}  // namespace memory_instrumentation
