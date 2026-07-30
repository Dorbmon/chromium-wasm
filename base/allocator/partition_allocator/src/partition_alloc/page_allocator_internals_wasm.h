// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef PARTITION_ALLOC_PAGE_ALLOCATOR_INTERNALS_WASM_H_
#define PARTITION_ALLOC_PAGE_ALLOCATOR_INTERNALS_WASM_H_

#include <emscripten/heap.h>

#include <cerrno>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>

#include "partition_alloc/page_allocator.h"
#include "partition_alloc/page_allocator_constants.h"
#include "partition_alloc/partition_alloc_check.h"
#include "partition_alloc/partition_lock.h"

namespace partition_alloc::internal {

static_assert(WASM_PAGE_SIZE == 64 * 1024);
static_assert(PageAllocationGranularity() == WASM_PAGE_SIZE);
static_assert(SystemPageSize() == WASM_PAGE_SIZE);

// Emscripten treats mmap address arguments as unsupported rather than binding
// mappings at that address.
constexpr bool kHintIsAdvisory = true;
// The retry path consumes this value immediately after its own allocation
// attempt. Keep it per pthread so a concurrent success or different failure
// cannot change whether this thread releases the emergency reservation.
thread_local int32_t s_allocPageErrorCode = 0;

namespace {

struct WasmPageMapping {
  uintptr_t allocation_address;
  size_t allocation_size;
  uintptr_t live_address;
  size_t live_size;
  size_t page_count;
  WasmPageMapping* next;

  unsigned char* decommitted_pages() {
    return reinterpret_cast<unsigned char*>(this + 1);
  }
};

Lock g_wasm_page_mapping_lock;
WasmPageMapping* g_wasm_page_mappings
    PA_GUARDED_BY(g_wasm_page_mapping_lock) = nullptr;

bool IsSupportedInitialAccessibility(
    PageAccessibilityConfiguration accessibility) {
  switch (accessibility.permissions) {
    case PageAccessibilityConfiguration::kReadWrite:
    case PageAccessibilityConfiguration::kReadWriteTagged:
      return true;
    case PageAccessibilityConfiguration::kInaccessible:
    case PageAccessibilityConfiguration::kInaccessibleWillJitLater:
    case PageAccessibilityConfiguration::kRead:
    case PageAccessibilityConfiguration::kReadExecuteProtected:
    case PageAccessibilityConfiguration::kReadExecute:
    case PageAccessibilityConfiguration::kReadWriteExecuteProtected:
    case PageAccessibilityConfiguration::kReadWriteExecute:
      return false;
  }
  return false;
}

uintptr_t AllocationFailure(int error) {
  s_allocPageErrorCode = error;
  return 0;
}

bool IsWritableAccessibility(
    PageAccessibilityConfiguration accessibility) {
  return accessibility.permissions ==
             PageAccessibilityConfiguration::kReadWrite ||
         accessibility.permissions ==
             PageAccessibilityConfiguration::kReadWriteTagged;
}

bool RangeEnd(uintptr_t address, size_t length, uintptr_t* end) {
  if (length > std::numeric_limits<uintptr_t>::max() - address) {
    return false;
  }
  *end = address + length;
  return true;
}

bool IsSystemPageRange(uintptr_t address, size_t length) {
  uintptr_t end;
  return length && !(address & SystemPageOffsetMask()) &&
         !(length & SystemPageOffsetMask()) &&
         RangeEnd(address, length, &end);
}

WasmPageMapping* FindContainingMappingLocked(uintptr_t address, size_t length)
    PA_EXCLUSIVE_LOCKS_REQUIRED(g_wasm_page_mapping_lock) {
  uintptr_t end;
  if (!IsSystemPageRange(address, length) ||
      !RangeEnd(address, length, &end)) {
    return nullptr;
  }
  for (WasmPageMapping* mapping = g_wasm_page_mappings; mapping;
       mapping = mapping->next) {
    uintptr_t allocation_end;
    uintptr_t live_end;
    PA_CHECK(IsSystemPageRange(mapping->allocation_address,
                               mapping->allocation_size));
    PA_CHECK(IsSystemPageRange(mapping->live_address, mapping->live_size));
    PA_CHECK(mapping->page_count ==
             (mapping->allocation_size >> SystemPageShift()));
    PA_CHECK(RangeEnd(mapping->allocation_address, mapping->allocation_size,
                      &allocation_end));
    PA_CHECK(RangeEnd(mapping->live_address, mapping->live_size, &live_end));
    PA_CHECK(mapping->live_address >= mapping->allocation_address);
    PA_CHECK(live_end <= allocation_end);
    if (address >= mapping->live_address && end <= live_end) {
      return mapping;
    }
  }
  return nullptr;
}

void SetDecommittedStateLocked(WasmPageMapping* mapping,
                               uintptr_t address,
                               size_t length,
                               bool decommitted)
    PA_EXCLUSIVE_LOCKS_REQUIRED(g_wasm_page_mapping_lock) {
  PA_CHECK(!(address & SystemPageOffsetMask()));
  PA_CHECK(!(length & SystemPageOffsetMask()));
  PA_CHECK(address >= mapping->allocation_address);

  const size_t first_page =
      (address - mapping->allocation_address) >> SystemPageShift();
  const size_t page_count = length >> SystemPageShift();
  PA_CHECK(first_page <= mapping->page_count);
  PA_CHECK(page_count <= mapping->page_count - first_page);

  unsigned char* states = mapping->decommitted_pages();
  for (size_t page = first_page; page < first_page + page_count; ++page) {
    const unsigned char mask = static_cast<unsigned char>(1u << (page & 7));
    unsigned char& state = states[page >> 3];
    if (decommitted) {
      state = static_cast<unsigned char>(state | mask);
    } else {
      state = static_cast<unsigned char>(state & ~mask);
    }
  }
}

void ZeroDecommittedPagesLocked(WasmPageMapping* mapping,
                                uintptr_t address,
                                size_t length)
    PA_EXCLUSIVE_LOCKS_REQUIRED(g_wasm_page_mapping_lock) {
  const size_t first_page =
      (address - mapping->allocation_address) >> SystemPageShift();
  const size_t page_count = length >> SystemPageShift();
  unsigned char* states = mapping->decommitted_pages();
  for (size_t page = first_page; page < first_page + page_count; ++page) {
    const unsigned char mask = static_cast<unsigned char>(1u << (page & 7));
    if (states[page >> 3] & mask) {
      const uintptr_t page_address =
          mapping->allocation_address + (page << SystemPageShift());
      std::memset(reinterpret_cast<void*>(page_address), 0, SystemPageSize());
      states[page >> 3] =
          static_cast<unsigned char>(states[page >> 3] & ~mask);
    }
  }
}

bool MarkDecommittedAndZero(uintptr_t address, size_t length) {
  ScopedGuard guard(g_wasm_page_mapping_lock);
  WasmPageMapping* mapping = FindContainingMappingLocked(address, length);
  if (!mapping) {
    return false;
  }
  std::memset(reinterpret_cast<void*>(address), 0, length);
  SetDecommittedStateLocked(mapping, address, length, true);
  return true;
}

bool RecommitAndZeroIfNeeded(uintptr_t address, size_t length) {
  ScopedGuard guard(g_wasm_page_mapping_lock);
  WasmPageMapping* mapping = FindContainingMappingLocked(address, length);
  if (!mapping) {
    return false;
  }
  ZeroDecommittedPagesLocked(mapping, address, length);
  return true;
}

}  // namespace

uintptr_t SystemAllocPagesInternal(
    uintptr_t hint,
    size_t length,
    PageAccessibilityConfiguration accessibility,
    PageTag page_tag,
    int file_descriptor_for_shared_alloc) {
  static_cast<void>(page_tag);

  if (!length || (hint & PageAllocationGranularityOffsetMask()) ||
      (length & PageAllocationGranularityOffsetMask())) {
    return AllocationFailure(EINVAL);
  }
  if (file_descriptor_for_shared_alloc != -1 ||
      !IsSupportedInitialAccessibility(accessibility)) {
    return AllocationFailure(ENOTSUP);
  }

  // A request as large as the entire linear memory can never fit alongside
  // static data, stacks, the system allocator, and this mapping's metadata.
  if (length >= emscripten_get_heap_max()) {
    return AllocationFailure(ENOMEM);
  }

  const size_t page_count = length >> SystemPageShift();
  if (page_count > std::numeric_limits<size_t>::max() - 7) {
    return AllocationFailure(ENOMEM);
  }
  const size_t state_bytes = (page_count + 7) / 8;
  if (state_bytes >
      std::numeric_limits<size_t>::max() - sizeof(WasmPageMapping)) {
    return AllocationFailure(ENOMEM);
  }

  void* allocation =
      emscripten_builtin_memalign(PageAllocationGranularity(), length);
  if (!allocation) {
    return AllocationFailure(ENOMEM);
  }
  std::memset(allocation, 0, length);

  auto* mapping = static_cast<WasmPageMapping*>(
      emscripten_builtin_calloc(1, sizeof(WasmPageMapping) + state_bytes));
  if (!mapping) {
    emscripten_builtin_free(allocation);
    return AllocationFailure(ENOMEM);
  }

  mapping->allocation_address = reinterpret_cast<uintptr_t>(allocation);
  mapping->allocation_size = length;
  mapping->live_address = mapping->allocation_address;
  mapping->live_size = length;
  mapping->page_count = page_count;
  PA_CHECK(!(mapping->allocation_address &
             PageAllocationGranularityOffsetMask()));

  {
    ScopedGuard guard(g_wasm_page_mapping_lock);
    mapping->next = g_wasm_page_mappings;
    g_wasm_page_mappings = mapping;
  }
  s_allocPageErrorCode = 0;
  return mapping->live_address;
}

bool TrySetSystemPagesAccessInternal(
    uintptr_t address,
    size_t length,
    PageAccessibilityConfiguration accessibility) {
  if (!IsWritableAccessibility(accessibility)) {
    return false;
  }
  return RecommitAndZeroIfNeeded(address, length);
}

void SetSystemPagesAccessInternal(
    uintptr_t address,
    size_t length,
    PageAccessibilityConfiguration accessibility) {
  PA_CHECK(
      TrySetSystemPagesAccessInternal(address, length, accessibility));
}

void FreePagesInternal(uintptr_t address, size_t length) {
  WasmPageMapping* released_mapping = nullptr;
  {
    ScopedGuard guard(g_wasm_page_mapping_lock);
    uintptr_t free_end = 0;
    PA_CHECK(IsSystemPageRange(address, length));
    PA_CHECK(RangeEnd(address, length, &free_end));

    bool found = false;
    WasmPageMapping** link = &g_wasm_page_mappings;
    while (*link) {
      WasmPageMapping* mapping = *link;
      uintptr_t live_end;
      PA_CHECK(RangeEnd(mapping->live_address, mapping->live_size, &live_end));
      const bool trims_prefix =
          address == mapping->live_address && free_end <= live_end;
      const bool trims_suffix =
          free_end == live_end && address >= mapping->live_address;
      if (!trims_prefix && !trims_suffix) {
        link = &mapping->next;
        continue;
      }

      if (address == mapping->live_address && length == mapping->live_size) {
        *link = mapping->next;
        released_mapping = mapping;
      } else if (trims_prefix) {
        mapping->live_address += length;
        mapping->live_size -= length;
      } else {
        mapping->live_size -= length;
      }
      found = true;
      break;
    }
    PA_CHECK(found);
  }

  if (released_mapping) {
    emscripten_builtin_free(
        reinterpret_cast<void*>(released_mapping->allocation_address));
    emscripten_builtin_free(released_mapping);
  }
}

uintptr_t TrimMappingInternal(
    uintptr_t base_address,
    size_t base_length,
    size_t trim_length,
    PageAccessibilityConfiguration accessibility,
    size_t pre_slack,
    size_t post_slack) {
  static_cast<void>(accessibility);
  PA_CHECK(pre_slack <= base_length);
  PA_CHECK(trim_length <= base_length - pre_slack);
  PA_CHECK(post_slack == base_length - pre_slack - trim_length);
  uintptr_t result = base_address;
  if (pre_slack) {
    FreePages(base_address, pre_slack);
    result += pre_slack;
  }
  if (post_slack) {
    FreePages(result + trim_length, post_slack);
  }
  return result;
}

void DecommitSystemPagesInternal(
    uintptr_t address,
    size_t length,
    PageAccessibilityDisposition accessibility_disposition) {
  // WebAssembly linear memory cannot make a subrange inaccessible. A required
  // protection update therefore cannot be reported as successful.
  PA_CHECK(accessibility_disposition ==
           PageAccessibilityDisposition::kAllowKeepForPerf);
  PA_CHECK(MarkDecommittedAndZero(address, length));
}

bool DecommitAndZeroSystemPagesInternal(uintptr_t address,
                                        size_t length,
                                        PageTag page_tag) {
  static_cast<void>(address);
  static_cast<void>(length);
  static_cast<void>(page_tag);
  // This API promises both zeroing and an inaccessible range. Returning false
  // must leave the caller's live contents untouched, so do not perform the
  // logical-only decommit used by DecommitSystemPages(kAllowKeepForPerf).
  return false;
}

void RecommitSystemPagesInternal(
    uintptr_t address,
    size_t length,
    PageAccessibilityConfiguration accessibility,
    PageAccessibilityDisposition accessibility_disposition) {
  PA_CHECK(IsWritableAccessibility(accessibility));
  // kRequireUpdate promises a permission transition that Wasm cannot perform.
  PA_CHECK(accessibility_disposition ==
           PageAccessibilityDisposition::kAllowKeepForPerf);
  PA_CHECK(RecommitAndZeroIfNeeded(address, length));
}

bool TryRecommitSystemPagesInternal(
    uintptr_t address,
    size_t length,
    PageAccessibilityConfiguration accessibility,
    PageAccessibilityDisposition accessibility_disposition) {
  if (!IsWritableAccessibility(accessibility) ||
      accessibility_disposition !=
          PageAccessibilityDisposition::kAllowKeepForPerf) {
    return false;
  }
  return RecommitAndZeroIfNeeded(address, length);
}

void DiscardSystemPagesInternal(uintptr_t address, size_t length) {
  // DiscardSystemPages() explicitly permits a no-op. Validate ownership so a
  // caller bug is not hidden, but retain the bytes because linear memory has
  // no physical-page discard primitive.
  ScopedGuard guard(g_wasm_page_mapping_lock);
  PA_CHECK(FindContainingMappingLocked(address, length));
}

bool SealSystemPagesInternal(uintptr_t address, size_t length) {
  static_cast<void>(address);
  static_cast<void>(length);
  return false;
}

}  // namespace partition_alloc::internal

#endif  // PARTITION_ALLOC_PAGE_ALLOCATOR_INTERNALS_WASM_H_
