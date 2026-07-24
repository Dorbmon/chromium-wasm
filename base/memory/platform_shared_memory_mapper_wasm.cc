// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/memory/platform_shared_memory_mapper.h"

#include "base/memory/process_local_shared_memory_wasm.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "platform_shared_memory_mapper_wasm.cc must only build for WebAssembly"
#endif

namespace base {

std::optional<span<uint8_t>> PlatformSharedMemoryMapper::Map(
    subtle::PlatformSharedMemoryHandle handle,
    bool write_allowed,
    uint64_t offset,
    size_t size) {
  return subtle::wasm::Map(handle, write_allowed, offset, size);
}

void PlatformSharedMemoryMapper::Unmap(span<uint8_t> mapping) {
  subtle::wasm::Unmap(mapping);
}

}  // namespace base
