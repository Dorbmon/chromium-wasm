// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/memory/shared_memory_mapping.h"

#include <cstdint>
#include <utility>

#include "base/bits.h"
#include "base/check_op.h"
#include "base/compiler_specific.h"
#include "base/memory/shared_memory_security_policy.h"
#include "base/system/sys_info.h"
#include "base/unguessable_token.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "shared_memory_mapping_wasm.cc must only build for WebAssembly"
#endif

namespace base {

SharedMemoryMapping::SharedMemoryMapping() = default;

SharedMemoryMapping::SharedMemoryMapping(SharedMemoryMapping&& mapping) noexcept
    : mapped_span_(std::exchange(mapping.mapped_span_, span<uint8_t>())),
      size_(mapping.size_),
      guid_(mapping.guid_),
      mapper_(mapping.mapper_) {}

SharedMemoryMapping& SharedMemoryMapping::operator=(
    SharedMemoryMapping&& mapping) noexcept {
  Unmap();
  mapped_span_ = std::exchange(mapping.mapped_span_, span<uint8_t>());
  size_ = mapping.size_;
  guid_ = mapping.guid_;
  mapper_ = mapping.mapper_;
  return *this;
}

SharedMemoryMapping::~SharedMemoryMapping() {
  Unmap();
}

SharedMemoryMapping::SharedMemoryMapping(span<uint8_t> mapped_span,
                                         size_t size,
                                         const UnguessableToken& guid,
                                         SharedMemoryMapper* mapper)
    : mapped_span_(mapped_span), size_(size), guid_(guid), mapper_(mapper) {
  CHECK_LE(size_, mapped_span_.size());
  // Native mappings have distinct virtual addresses, while process-local Wasm
  // mappings intentionally alias one allocation. Tracing is disabled in the
  // focused graph, so SharedMemoryTracker is explicitly not used here.
}

void SharedMemoryMapping::Unmap() {
  if (!IsValid()) {
    return;
  }

  SharedMemorySecurityPolicy::ReleaseReservationForMapping(size_);

  SharedMemoryMapper* mapper = mapper_;
  if (!mapper) {
    mapper = SharedMemoryMapper::GetDefaultInstance();
  }

  uint8_t* aligned_data =
      bits::AlignDown(mapped_span_.data(), SysInfo::VMAllocationGranularity());
  size_t adjusted_size =
      mapped_span_.size() +
      static_cast<size_t>(mapped_span_.data() - aligned_data);
  mapper->Unmap(UNSAFE_TODO(span(aligned_data, adjusted_size)));
  mapped_span_ = span<uint8_t>();
  size_ = 0;
  mapper_ = nullptr;
}

ReadOnlySharedMemoryMapping::ReadOnlySharedMemoryMapping() = default;
ReadOnlySharedMemoryMapping::ReadOnlySharedMemoryMapping(
    ReadOnlySharedMemoryMapping&&) noexcept = default;
ReadOnlySharedMemoryMapping& ReadOnlySharedMemoryMapping::operator=(
    ReadOnlySharedMemoryMapping&&) noexcept = default;
ReadOnlySharedMemoryMapping::ReadOnlySharedMemoryMapping(
    span<uint8_t> mapped_span,
    size_t size,
    const UnguessableToken& guid,
    SharedMemoryMapper* mapper)
    : SharedMemoryMapping(mapped_span, size, guid, mapper) {}

WritableSharedMemoryMapping::WritableSharedMemoryMapping() = default;
WritableSharedMemoryMapping::WritableSharedMemoryMapping(
    WritableSharedMemoryMapping&&) noexcept = default;
WritableSharedMemoryMapping& WritableSharedMemoryMapping::operator=(
    WritableSharedMemoryMapping&&) noexcept = default;
WritableSharedMemoryMapping::WritableSharedMemoryMapping(
    span<uint8_t> mapped_span,
    size_t size,
    const UnguessableToken& guid,
    SharedMemoryMapper* mapper)
    : SharedMemoryMapping(mapped_span, size, guid, mapper) {}

}  // namespace base
