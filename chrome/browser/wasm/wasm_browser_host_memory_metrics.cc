// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <cstddef>
#include <limits>

#include "build/build_config.h"
#include "emscripten/emscripten.h"
#include "emscripten/heap.h"
#include "partition_alloc/page_allocator.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_host_memory_metrics.cc must only be built for WebAssembly"
#endif

namespace {

// The C ABI returns JavaScript Numbers. Keep this Wasm32-only observation
// exact instead of silently rounding a future wider address-space value.
static_assert(std::numeric_limits<size_t>::digits <=
              std::numeric_limits<double>::digits);

double ExactByteMetric(size_t value) {
  return static_cast<double>(value);
}

}  // namespace

extern "C" {

// This is the current capacity of the Emscripten Wasm linear memory. It is
// not an allocation, committed-memory, or residency measurement.
EMSCRIPTEN_KEEPALIVE double
chromium_wasm_browser_host_memory_linear_capacity_bytes() {
  return ExactByteMetric(emscripten_get_heap_size());
}

// This is Emscripten's configured maximum Wasm linear-memory capacity. The
// host derives capacity headroom from this exact value and the current capacity.
EMSCRIPTEN_KEEPALIVE double
chromium_wasm_browser_host_memory_linear_maximum_bytes() {
  return ExactByteMetric(emscripten_get_heap_max());
}

// This is PageAllocator's aggregate logical mapping counter across its
// clients. The mappings may be uncommitted; this is not RSS, allocation, or
// leak evidence.
EMSCRIPTEN_KEEPALIVE double
chromium_wasm_browser_host_memory_page_allocator_total_mapped_bytes() {
  return ExactByteMetric(partition_alloc::GetTotalMappedSize());
}

}  // extern "C"
