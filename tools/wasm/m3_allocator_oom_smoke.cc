// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <limits>

#include <emscripten/heap.h>

#include "base/process/memory.h"

namespace {

constexpr char kPrefix[] = "CHROMIUM_WASM_M3_ALLOCATOR";
constexpr size_t kControlAllocationBytes = 64;

int Fail(const char* reason) {
  fprintf(stderr, "%s:FAIL reason=%s\n", kPrefix, reason);
  return 1;
}

bool ReportLimit(const char* mode,
                 size_t* initial_heap_bytes,
                 size_t* request_bytes) {
  const size_t current_heap_bytes = emscripten_get_heap_size();
  const size_t maximum_heap_bytes = emscripten_get_heap_max();
  if (current_heap_bytes == 0 || maximum_heap_bytes < current_heap_bytes ||
      maximum_heap_bytes == std::numeric_limits<size_t>::max()) {
    return false;
  }

  *initial_heap_bytes = current_heap_bytes;
  *request_bytes = maximum_heap_bytes + 1;
  printf(
      "%s:LIMIT mode=%s current_heap_bytes=%zu max_heap_bytes=%zu "
      "request_bytes=%zu\n",
      kPrefix, mode, current_heap_bytes, maximum_heap_bytes, *request_bytes);
  return true;
}

int RunUncheckedMode() {
  size_t initial_heap_bytes = 0;
  size_t request_bytes = 0;
  if (!ReportLimit("unchecked", &initial_heap_bytes, &request_bytes)) {
    return Fail("invalid_linear_memory_limit");
  }

  base::EnableTerminationOnOutOfMemory();
  printf("%s:POLICY mode=unchecked terminate_on_oom=enabled\n", kPrefix);

  void* control = nullptr;
  if (!base::UncheckedMalloc(kControlAllocationBytes, &control) || !control) {
    return Fail("unchecked_control_allocation_failed");
  }
  base::UncheckedFree(control);
  printf("%s:CONTROL mode=unchecked success=1\n", kPrefix);

  void* allocation = reinterpret_cast<void*>(1);
  const bool success = base::UncheckedMalloc(request_bytes, &allocation);
  const bool pointer_is_null = allocation == nullptr;
  const size_t final_heap_bytes = emscripten_get_heap_size();
  const bool heap_unchanged = final_heap_bytes == initial_heap_bytes;
  printf("%s:HEAP_AFTER mode=unchecked heap_bytes=%zu unchanged=%d\n", kPrefix,
         final_heap_bytes, heap_unchanged);
  printf("%s:RESULT mode=unchecked success=%d pointer_null=%d\n", kPrefix,
         success, pointer_is_null);
  if (!heap_unchanged) {
    if (allocation) {
      base::UncheckedFree(allocation);
    }
    return Fail("unchecked_failure_grew_linear_memory");
  }
  if (success || !pointer_is_null) {
    if (allocation) {
      base::UncheckedFree(allocation);
    }
    return Fail("unchecked_ceiling_allocation_did_not_fail");
  }

  printf("%s:PASS mode=unchecked\n", kPrefix);
  return 0;
}

int RunOrdinaryMode() {
  size_t initial_heap_bytes = 0;
  size_t request_bytes = 0;
  if (!ReportLimit("ordinary", &initial_heap_bytes, &request_bytes)) {
    return Fail("invalid_linear_memory_limit");
  }

  base::EnableTerminationOnOutOfMemory();
  printf("%s:POLICY mode=ordinary terminate_on_oom=enabled\n", kPrefix);

  void* (*volatile allocate)(size_t) = &malloc;
  void* control = allocate(kControlAllocationBytes);
  if (!control) {
    return Fail("ordinary_control_allocation_failed");
  }
  free(control);
  printf("%s:CONTROL mode=ordinary success=1\n", kPrefix);

  printf("%s:TRIGGER mode=ordinary allocator=malloc\n", kPrefix);
  fflush(stdout);

  [[maybe_unused]] void* volatile allocation = allocate(request_bytes);
  printf("%s:FALSE_SUCCESS mode=ordinary pointer_null=%d\n", kPrefix,
         allocation == nullptr);
  return Fail("ordinary_ceiling_allocation_returned");
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 2) {
    return Fail("expected_exactly_one_mode");
  }

  const char* mode = argv[1];
  printf("%s:RUNTIME_START mode=%s\n", kPrefix, mode);
  if (strcmp(mode, "unchecked") == 0) {
    return RunUncheckedMode();
  }
  if (strcmp(mode, "ordinary") == 0) {
    return RunOrdinaryMode();
  }
  return Fail("unsupported_mode");
}
