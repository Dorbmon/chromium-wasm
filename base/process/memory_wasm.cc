// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/process/memory.h"

#include <errno.h>
#include <malloc.h>
#include <stdlib.h>

#include <atomic>
#include <limits>
#include <new>

#include <emscripten/heap.h>

#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "memory_wasm.cc must only be built for WebAssembly"
#endif

namespace {

std::atomic_bool g_terminate_on_out_of_memory{false};

[[noreturn]] void TerminateOnOutOfMemory(size_t size) {
  base::TerminateBecauseOutOfMemory(size);
  __builtin_unreachable();
}

void* EnforceAllocationPolicy(void* result, size_t size) {
  if (!result && size != 0 &&
      g_terminate_on_out_of_memory.load(std::memory_order_relaxed)) {
    TerminateOnOutOfMemory(size);
  }
  return result;
}

size_t SaturatingMultiply(size_t left, size_t right) {
  if (left != 0 && right > std::numeric_limits<size_t>::max() / left) {
    return std::numeric_limits<size_t>::max();
  }
  return left * right;
}

bool IsValidPosixAlignment(size_t alignment) {
  return alignment >= sizeof(void*) &&
         (alignment & (alignment - 1)) == 0;
}

}  // namespace

// Emscripten deliberately provides weak allocator symbols and direct
// `emscripten_builtin_*` entry points so applications can install a policy
// wrapper. Keep ABORTING_MALLOC disabled: these strong symbols enforce
// Chromium's normal allocation policy, while base::Unchecked* bypasses it.
extern "C" {

void* malloc(size_t size) {
  return EnforceAllocationPolicy(emscripten_builtin_malloc(size), size);
}

void* calloc(size_t num_items, size_t size) {
  return EnforceAllocationPolicy(emscripten_builtin_calloc(num_items, size),
                                 SaturatingMultiply(num_items, size));
}

void* realloc(void* ptr, size_t size) {
  return EnforceAllocationPolicy(emscripten_builtin_realloc(ptr, size), size);
}

void free(void* ptr) {
  emscripten_builtin_free(ptr);
}

void* memalign(size_t alignment, size_t size) {
  if (!IsValidPosixAlignment(alignment)) {
    errno = EINVAL;
    return nullptr;
  }
  return EnforceAllocationPolicy(
      emscripten_builtin_memalign(alignment, size), size);
}

void* aligned_alloc(size_t alignment, size_t size) {
  if (!IsValidPosixAlignment(alignment) || size % alignment != 0) {
    errno = EINVAL;
    return nullptr;
  }
  return memalign(alignment, size);
}

int posix_memalign(void** result, size_t alignment, size_t size) {
  if (!result || !IsValidPosixAlignment(alignment)) {
    return EINVAL;
  }
  void* allocation =
      EnforceAllocationPolicy(emscripten_builtin_memalign(alignment, size),
                              size);
  if (!allocation) {
    return ENOMEM;
  }
  *result = allocation;
  return 0;
}

}  // extern "C"

namespace base {

void EnableTerminationOnOutOfMemory() {
  std::set_new_handler([] { TerminateOnOutOfMemory(0); });
  g_terminate_on_out_of_memory.store(true, std::memory_order_relaxed);
}

void EnableTerminationOnHeapCorruption() {
  // The web platform exposes no host allocator-corruption policy to enable.
}

bool UncheckedMalloc(size_t size, void** result) {
  *result = emscripten_builtin_malloc(size);
  return *result != nullptr;
}

bool UncheckedCalloc(size_t num_items, size_t size, void** result) {
  *result = emscripten_builtin_calloc(num_items, size);
  return *result != nullptr;
}

void UncheckedFree(void* ptr) {
  emscripten_builtin_free(ptr);
}

}  // namespace base
