// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/memory/process_local_shared_memory_wasm.h"

#include <stdint.h>

#include <bit>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <map>
#include <memory>
#include <utility>

#include "base/bits.h"
#include "base/check.h"
#include "base/check_op.h"
#include "base/compiler_specific.h"
#include "base/synchronization/lock.h"
#include "base/system/sys_info.h"

namespace base::subtle::wasm {
namespace {

struct AlignedFreeDeleter {
  void operator()(uint8_t* memory) const { std::free(memory); }
};

using AlignedStorage = std::unique_ptr<uint8_t, AlignedFreeDeleter>;

struct RegionRecord {
  uint64_t generation;
  PlatformSharedMemoryHandleRights rights;
  size_t size;
  UnguessableToken guid;
  AlignedStorage storage;
  size_t handle_references = 1;
  size_t mapping_references = 0;
};

struct MappingKey {
  uintptr_t address;
  size_t size;

  friend auto operator<=>(const MappingKey&, const MappingKey&) = default;
};

struct MappingRecord {
  uint64_t region_id;
  uint64_t generation;
  size_t count;
};

class ProcessLocalSharedMemoryRegistry {
 public:
  ScopedPlatformSharedMemoryHandle Create(
      size_t size,
      PlatformSharedMemoryHandleRights rights) {
    if (size == 0 ||
        size > static_cast<size_t>(std::numeric_limits<int>::max()) ||
        (rights != PlatformSharedMemoryHandleRights::kWritable &&
         rights != PlatformSharedMemoryHandleRights::kUnsafe)) {
      return {};
    }

    const size_t alignment = SysInfo::VMAllocationGranularity();
    CHECK(std::has_single_bit(alignment));
    if (size > std::numeric_limits<size_t>::max() - (alignment - 1)) {
      return {};
    }
    const size_t allocation_size = bits::AlignUp(size, alignment);

    void* allocation = nullptr;
    if (posix_memalign(&allocation, alignment, allocation_size) != 0) {
      return {};
    }
    std::memset(allocation, 0, allocation_size);
    AlignedStorage storage(static_cast<uint8_t*>(allocation));

    const UnguessableToken guid = UnguessableToken::Create();
    CHECK(!guid.is_empty());

    AutoLock hold(lock_);
    if (next_region_id_ == 0 || next_generation_ == 0) {
      return {};
    }

    const PlatformSharedMemoryHandle handle{
        .region_id = next_region_id_++,
        .generation = next_generation_++,
        .rights = rights,
    };
    auto record = std::make_unique<RegionRecord>(
        RegionRecord{.generation = handle.generation,
                     .rights = rights,
                     .size = size,
                     .guid = guid,
                     .storage = std::move(storage)});
    const bool inserted =
        regions_.emplace(handle.region_id, std::move(record)).second;
    CHECK(inserted);
    return ScopedPlatformSharedMemoryHandle(handle);
  }

  std::optional<RegionMetadata> GetMetadata(
      PlatformSharedMemoryHandle handle) {
    AutoLock hold(lock_);
    RegionRecord* record = FindByIdentity(handle);
    if (!record || record->handle_references == 0) {
      return std::nullopt;
    }
    return RegionMetadata{
        .size = record->size,
        .rights = record->rights,
        .guid = record->guid,
    };
  }

  bool IsValid(PlatformSharedMemoryHandle handle) {
    AutoLock hold(lock_);
    RegionRecord* record = FindByIdentity(handle);
    return record && record->handle_references != 0 &&
           record->rights == handle.rights;
  }

  ScopedPlatformSharedMemoryHandle Duplicate(
      PlatformSharedMemoryHandle handle) {
    AutoLock hold(lock_);
    RegionRecord* record = FindValid(handle);
    if (!record ||
        (record->rights != PlatformSharedMemoryHandleRights::kReadOnly &&
         record->rights != PlatformSharedMemoryHandleRights::kUnsafe) ||
        record->handle_references == std::numeric_limits<size_t>::max()) {
      return {};
    }
    ++record->handle_references;
    return ScopedPlatformSharedMemoryHandle(handle);
  }

  uint64_t ExportForTransport(ScopedPlatformSharedMemoryHandle handle) {
    if (!handle.is_valid()) {
      return 0;
    }

    AutoLock hold(lock_);
    if (!FindValid(handle.get()) || next_transport_token_ == 0) {
      return 0;
    }

    const uint64_t token = next_transport_token_++;
    const bool inserted =
        transport_handles_.emplace(token, handle.get()).second;
    CHECK(inserted);
    (void)handle.release();
    return token;
  }

  ScopedPlatformSharedMemoryHandle ImportForTransport(uint64_t token) {
    if (token == 0) {
      return {};
    }

    AutoLock hold(lock_);
    auto it = transport_handles_.find(token);
    if (it == transport_handles_.end()) {
      return {};
    }
    PlatformSharedMemoryHandle handle = it->second;
    transport_handles_.erase(it);
    return ScopedPlatformSharedMemoryHandle(handle);
  }

  bool Convert(PlatformSharedMemoryHandle handle,
               PlatformSharedMemoryHandleRights new_rights) {
    AutoLock hold(lock_);
    RegionRecord* record = FindValid(handle);
    if (!record ||
        record->rights != PlatformSharedMemoryHandleRights::kWritable ||
        (new_rights != PlatformSharedMemoryHandleRights::kReadOnly &&
         new_rights != PlatformSharedMemoryHandleRights::kUnsafe) ||
        record->handle_references != 1) {
      return false;
    }
    record->rights = new_rights;
    return true;
  }

  void Release(PlatformSharedMemoryHandle handle) {
    if (handle.region_id == 0 || handle.generation == 0) {
      return;
    }

    AutoLock hold(lock_);
    RegionRecord* record = FindByIdentity(handle);
    if (!record || record->handle_references == 0) {
      return;
    }
    auto it = regions_.find(handle.region_id);
    CHECK(it != regions_.end());
    --record->handle_references;
    MaybeEraseRegion(it);
  }

  std::optional<span<uint8_t>> Map(PlatformSharedMemoryHandle handle,
                                   bool write_allowed,
                                   uint64_t offset,
                                   size_t size) {
    if (size == 0) {
      return std::nullopt;
    }

    AutoLock hold(lock_);
    RegionRecord* record = FindValid(handle);
    if (!record ||
        (write_allowed &&
         record->rights == PlatformSharedMemoryHandleRights::kReadOnly) ||
        offset > record->size || size > record->size - offset ||
        record->mapping_references == std::numeric_limits<size_t>::max()) {
      return std::nullopt;
    }

    uint8_t* address =
        UNSAFE_BUFFERS(record->storage.get() + static_cast<size_t>(offset));
    const MappingKey key{
        .address = reinterpret_cast<uintptr_t>(address),
        .size = size,
    };
    auto [mapping_it, inserted] =
        mappings_.try_emplace(key, MappingRecord{handle.region_id,
                                                handle.generation, 0});
    if (!inserted &&
        (mapping_it->second.region_id != handle.region_id ||
         mapping_it->second.generation != handle.generation)) {
      return std::nullopt;
    }
    if (mapping_it->second.count == std::numeric_limits<size_t>::max()) {
      return std::nullopt;
    }

    ++mapping_it->second.count;
    ++record->mapping_references;
    return UNSAFE_BUFFERS(span(address, size));
  }

  void Unmap(span<uint8_t> mapping) {
    if (mapping.empty()) {
      return;
    }

    AutoLock hold(lock_);
    const MappingKey key{
        .address = reinterpret_cast<uintptr_t>(mapping.data()),
        .size = mapping.size(),
    };
    auto mapping_it = mappings_.find(key);
    CHECK(mapping_it != mappings_.end());
    CHECK_GT(mapping_it->second.count, 0U);

    const uint64_t region_id = mapping_it->second.region_id;
    const uint64_t generation = mapping_it->second.generation;
    if (--mapping_it->second.count == 0) {
      mappings_.erase(mapping_it);
    }

    auto region_it = regions_.find(region_id);
    CHECK(region_it != regions_.end());
    CHECK_EQ(region_it->second->generation, generation);
    CHECK_GT(region_it->second->mapping_references, 0U);
    --region_it->second->mapping_references;
    MaybeEraseRegion(region_it);
  }

 private:
  using RegionMap =
      std::map<uint64_t, std::unique_ptr<RegionRecord>>;

  RegionMap::iterator FindIteratorByIdentity(
      PlatformSharedMemoryHandle handle) EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    auto it = regions_.find(handle.region_id);
    if (it == regions_.end() || it->second->generation != handle.generation) {
      return regions_.end();
    }
    return it;
  }

  RegionRecord* FindByIdentity(PlatformSharedMemoryHandle handle)
      EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    auto it = FindIteratorByIdentity(handle);
    return it == regions_.end() ? nullptr : it->second.get();
  }

  RegionRecord* FindValid(PlatformSharedMemoryHandle handle)
      EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    RegionRecord* record = FindByIdentity(handle);
    return record && record->handle_references != 0 &&
                   record->rights == handle.rights
               ? record
               : nullptr;
  }

  void MaybeEraseRegion(RegionMap::iterator it)
      EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    if (it->second->handle_references == 0 &&
        it->second->mapping_references == 0) {
      regions_.erase(it);
    }
  }

  Lock lock_;
  uint64_t next_region_id_ GUARDED_BY(lock_) = 1;
  uint64_t next_generation_ GUARDED_BY(lock_) = 1;
  uint64_t next_transport_token_ GUARDED_BY(lock_) = 1;
  RegionMap regions_ GUARDED_BY(lock_);
  std::map<MappingKey, MappingRecord> mappings_ GUARDED_BY(lock_);
  std::map<uint64_t, PlatformSharedMemoryHandle> transport_handles_
      GUARDED_BY(lock_);
};

ProcessLocalSharedMemoryRegistry& GetRegistry() {
  static auto* registry = new ProcessLocalSharedMemoryRegistry;
  return *registry;
}

}  // namespace

ScopedPlatformSharedMemoryHandle CreateRegion(
    size_t size,
    PlatformSharedMemoryHandleRights rights) {
  return GetRegistry().Create(size, rights);
}

std::optional<RegionMetadata> GetRegionMetadata(
    PlatformSharedMemoryHandle handle) {
  return GetRegistry().GetMetadata(handle);
}

bool IsHandleValid(PlatformSharedMemoryHandle handle) {
  return GetRegistry().IsValid(handle);
}

ScopedPlatformSharedMemoryHandle DuplicateHandle(
    PlatformSharedMemoryHandle handle) {
  return GetRegistry().Duplicate(handle);
}

uint64_t ExportHandleForTransport(ScopedPlatformSharedMemoryHandle handle) {
  return GetRegistry().ExportForTransport(std::move(handle));
}

ScopedPlatformSharedMemoryHandle ImportHandleForTransport(uint64_t token) {
  return GetRegistry().ImportForTransport(token);
}

void DiscardTransportHandle(uint64_t token) {
  ScopedPlatformSharedMemoryHandle handle =
      GetRegistry().ImportForTransport(token);
}

bool ConvertHandleRights(PlatformSharedMemoryHandle handle,
                         PlatformSharedMemoryHandleRights new_rights) {
  return GetRegistry().Convert(handle, new_rights);
}

void ReleaseHandleReference(PlatformSharedMemoryHandle handle) {
  GetRegistry().Release(handle);
}

std::optional<span<uint8_t>> Map(PlatformSharedMemoryHandle handle,
                                 bool write_allowed,
                                 uint64_t offset,
                                 size_t size) {
  return GetRegistry().Map(handle, write_allowed, offset, size);
}

void Unmap(span<uint8_t> mapping) {
  GetRegistry().Unmap(mapping);
}

}  // namespace base::subtle::wasm
