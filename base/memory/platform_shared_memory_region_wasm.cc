// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/memory/platform_shared_memory_region.h"

#include <optional>
#include <utility>

#include "base/check.h"
#include "base/check_op.h"
#include "base/memory/process_local_shared_memory_wasm.h"
#include "base/types/expected.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "platform_shared_memory_region_wasm.cc must only build for WebAssembly"
#endif

namespace base::subtle {
namespace {

using Rights = PlatformSharedMemoryHandleRights;

Rights RightsForMode(PlatformSharedMemoryRegion::Mode mode) {
  switch (mode) {
    case PlatformSharedMemoryRegion::Mode::kReadOnly:
      return Rights::kReadOnly;
    case PlatformSharedMemoryRegion::Mode::kWritable:
      return Rights::kWritable;
    case PlatformSharedMemoryRegion::Mode::kUnsafe:
      return Rights::kUnsafe;
  }
}

PlatformSharedMemoryRegion::TakeError ErrorForMode(
    PlatformSharedMemoryRegion::Mode expected_mode) {
  return expected_mode == PlatformSharedMemoryRegion::Mode::kReadOnly
             ? PlatformSharedMemoryRegion::TakeError::kExpectedReadOnlyButNot
             : PlatformSharedMemoryRegion::TakeError::kExpectedWritableButNot;
}

bool GUIDsMatch(const UnguessableToken& left,
                const UnguessableToken& right) {
  if (left.is_empty() || right.is_empty()) {
    return false;
  }
  return left.GetHighForSerialization() == right.GetHighForSerialization() &&
         left.GetLowForSerialization() == right.GetLowForSerialization();
}

bool MetadataMatches(const wasm::RegionMetadata& metadata,
                     PlatformSharedMemoryHandle handle,
                     PlatformSharedMemoryRegion::Mode mode,
                     size_t size,
                     const UnguessableToken& guid) {
  return handle.rights == metadata.rights &&
         RightsForMode(mode) == metadata.rights && size == metadata.size &&
         GUIDsMatch(guid, metadata.guid);
}

}  // namespace

expected<PlatformSharedMemoryRegion, PlatformSharedMemoryRegion::TakeError>
PlatformSharedMemoryRegion::TakeOrFail(
    ScopedPlatformSharedMemoryHandle handle,
    Mode mode,
    size_t size,
    const UnguessableToken& guid) {
  if (!handle.is_valid()) {
    return PlatformSharedMemoryRegion();
  }

  const PlatformSharedMemoryHandle raw_handle = handle.get();
  std::optional<wasm::RegionMetadata> metadata =
      wasm::GetRegionMetadata(raw_handle);
  if (!metadata.has_value()) {
    return PlatformSharedMemoryRegion();
  }

  if (raw_handle.rights != metadata->rights ||
      RightsForMode(mode) != metadata->rights) {
    return unexpected(ErrorForMode(mode));
  }

  if (size == 0 ||
      !MetadataMatches(*metadata, raw_handle, mode, size, guid)) {
    return PlatformSharedMemoryRegion();
  }

  return PlatformSharedMemoryRegion(std::move(handle), mode, size, guid);
}

PlatformSharedMemoryHandle PlatformSharedMemoryRegion::GetPlatformHandle()
    const {
  return handle_.get();
}

bool PlatformSharedMemoryRegion::IsValid() const {
  if (!handle_.is_valid()) {
    return false;
  }
  std::optional<wasm::RegionMetadata> metadata =
      wasm::GetRegionMetadata(handle_.get());
  return metadata.has_value() &&
         MetadataMatches(*metadata, handle_.get(), mode_, size_, guid_);
}

PlatformSharedMemoryRegion PlatformSharedMemoryRegion::Duplicate() const {
  if (!IsValid()) {
    return {};
  }

  CHECK_NE(mode_, Mode::kWritable)
      << "Duplicating a writable shared memory region is prohibited";
  ScopedPlatformSharedMemoryHandle duplicate =
      wasm::DuplicateHandle(handle_.get());
  if (!duplicate.is_valid()) {
    return {};
  }
  return PlatformSharedMemoryRegion(std::move(duplicate), mode_, size_, guid_);
}

bool PlatformSharedMemoryRegion::ConvertToReadOnly() {
  if (!IsValid()) {
    return false;
  }

  CHECK_EQ(mode_, Mode::kWritable)
      << "Only writable shared memory region can be converted to read-only";
  if (!wasm::ConvertHandleRights(handle_.get(), Rights::kReadOnly)) {
    handle_.reset();
    size_ = 0;
    guid_ = {};
    return false;
  }
  handle_.SetRightsForConversion(Rights::kReadOnly);
  mode_ = Mode::kReadOnly;
  return true;
}

bool PlatformSharedMemoryRegion::ConvertToUnsafe() {
  if (!IsValid()) {
    return false;
  }

  CHECK_EQ(mode_, Mode::kWritable)
      << "Only writable shared memory region can be converted to unsafe";
  if (!wasm::ConvertHandleRights(handle_.get(), Rights::kUnsafe)) {
    handle_.reset();
    size_ = 0;
    guid_ = {};
    return false;
  }
  handle_.SetRightsForConversion(Rights::kUnsafe);
  mode_ = Mode::kUnsafe;
  return true;
}

PlatformSharedMemoryRegion PlatformSharedMemoryRegion::Create(Mode mode,
                                                              size_t size) {
  CHECK_NE(mode, Mode::kReadOnly) << "Creating a region in read-only mode will "
                                    "lead to this region being non-modifiable";

  ScopedPlatformSharedMemoryHandle handle =
      wasm::CreateRegion(size, RightsForMode(mode));
  if (!handle.is_valid()) {
    return {};
  }
  std::optional<wasm::RegionMetadata> metadata =
      wasm::GetRegionMetadata(handle.get());
  if (!metadata.has_value()) {
    return {};
  }
  return PlatformSharedMemoryRegion(std::move(handle), mode, metadata->size,
                                    metadata->guid);
}

expected<void, PlatformSharedMemoryRegion::TakeError>
PlatformSharedMemoryRegion::CheckPlatformHandlePermissionsCorrespondToMode(
    PlatformSharedMemoryHandle handle,
    Mode mode,
    size_t size) {
  std::optional<wasm::RegionMetadata> metadata =
      wasm::GetRegionMetadata(handle);
  if (!metadata.has_value() || handle.rights != metadata->rights ||
      RightsForMode(mode) != metadata->rights || size != metadata->size) {
    return unexpected(ErrorForMode(mode));
  }
  return ok();
}

PlatformSharedMemoryRegion::PlatformSharedMemoryRegion(
    ScopedPlatformSharedMemoryHandle handle,
    Mode mode,
    size_t size,
    const UnguessableToken& guid)
    : handle_(std::move(handle)), mode_(mode), size_(size), guid_(guid) {}

}  // namespace base::subtle
