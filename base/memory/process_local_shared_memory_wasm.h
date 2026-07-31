// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef BASE_MEMORY_PROCESS_LOCAL_SHARED_MEMORY_WASM_H_
#define BASE_MEMORY_PROCESS_LOCAL_SHARED_MEMORY_WASM_H_

#include <stddef.h>
#include <stdint.h>

#include <optional>

#include "base/containers/span.h"
#include "base/memory/platform_shared_memory_handle.h"
#include "base/unguessable_token.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "process_local_shared_memory_wasm.h is only for WebAssembly"
#endif

namespace base::subtle::wasm {

struct RegionMetadata {
  size_t size;
  PlatformSharedMemoryHandleRights rights;
  UnguessableToken guid;
};

ScopedPlatformSharedMemoryHandle CreateRegion(
    size_t size,
    PlatformSharedMemoryHandleRights rights);

std::optional<RegionMetadata> GetRegionMetadata(
    PlatformSharedMemoryHandle handle);

bool IsHandleValid(PlatformSharedMemoryHandle handle);

ScopedPlatformSharedMemoryHandle DuplicateHandle(
    PlatformSharedMemoryHandle handle);

// Moves one registry reference through an opaque, process-local transfer
// token. Tokens are one-shot capabilities: importing or discarding a token
// consumes it.
[[nodiscard]] uint64_t ExportHandleForTransport(
    ScopedPlatformSharedMemoryHandle handle);
ScopedPlatformSharedMemoryHandle ImportHandleForTransport(uint64_t token);
void DiscardTransportHandle(uint64_t token);

bool ConvertHandleRights(PlatformSharedMemoryHandle handle,
                         PlatformSharedMemoryHandleRights new_rights);

void ReleaseHandleReference(PlatformSharedMemoryHandle handle);

std::optional<span<uint8_t>> Map(PlatformSharedMemoryHandle handle,
                                 bool write_allowed,
                                 uint64_t offset,
                                 size_t size);

void Unmap(span<uint8_t> mapping);

}  // namespace base::subtle::wasm

#endif  // BASE_MEMORY_PROCESS_LOCAL_SHARED_MEMORY_WASM_H_
