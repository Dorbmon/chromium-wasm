// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <new>
#include <utility>

#include "partition_alloc/build_config.h"
#include "partition_alloc/buildflags.h"
#include "partition_alloc/memory_reclaimer.h"
#include "partition_alloc/partition_alloc.h"
#include "partition_alloc/partition_alloc_config.h"
#include "partition_alloc/partition_alloc_constants.h"
#include "partition_alloc/partition_stats.h"
#include "partition_alloc/thread_cache.h"

namespace {

constexpr char kPrefix[] = "CHROMIUM_WASM_M3_PA_ROOT";
constexpr char kTypeName[] = "m3_partition_alloc_root_smoke";
constexpr size_t kSystemPageBytes = 64 * 1024;
constexpr size_t kMinimumBucketRequestBytes =
    partition_alloc::BucketIndexLookup::kMinBucketSize;
constexpr size_t kBucketRequestBytes = 4097;
constexpr size_t kReallocRequestBytes = 8193;
constexpr size_t kDirectInitialBytes =
    partition_alloc::BucketIndexLookup::kMaxBucketSize +
    5 * kSystemPageBytes;
constexpr size_t kDirectShrinkBytes =
    partition_alloc::BucketIndexLookup::kMaxBucketSize +
    4 * kSystemPageBytes;
constexpr size_t kLargeAlignmentBytes = 512 * 1024;
constexpr size_t kAlignedRequestBytes = 96 * 1024;
constexpr int kThreadCount = 4;
constexpr int kThreadIterations = 128;
constexpr int kReclaimAllocationCount = 256;
constexpr size_t kFastRootThreadCacheIndex = 0;
#if PA_BUILDFLAG(USE_PARTITION_ALLOC)
constexpr char kProductionPartitionAlloc[] = "on";
#else
constexpr char kProductionPartitionAlloc[] = "off";
#endif

using partition_alloc::AllocFlags;
using partition_alloc::PartitionAllocator;
using partition_alloc::PartitionOptions;
using partition_alloc::PartitionRoot;

constexpr AllocFlags kTryAlloc = AllocFlags::kReturnNull;
constexpr AllocFlags kTryZeroAlloc =
    AllocFlags::kReturnNull | AllocFlags::kZeroFill;

static_assert(PA_BUILDFLAG(IS_WASM));
static_assert(!PA_BUILDFLAG(IS_POSIX));
static_assert(!PA_BUILDFLAG(USE_ALLOCATOR_SHIM));
static_assert(!PA_BUILDFLAG(USE_PARTITION_ALLOC_AS_MALLOC));
static_assert(sizeof(size_t) == 4);
static_assert(partition_alloc::internal::SystemPageSize() ==
              kSystemPageBytes);
static_assert(kMinimumBucketRequestBytes == 8);
static_assert(kDirectInitialBytes >
              partition_alloc::BucketIndexLookup::kMaxBucketSize);
static_assert(kDirectShrinkBytes >
              partition_alloc::BucketIndexLookup::kMaxBucketSize);
static_assert(kLargeAlignmentBytes <=
              partition_alloc::internal::kMaxSupportedAlignment);

template <typename T>
class NeverDestroyed {
 public:
  template <typename... Args>
  T* Construct(Args&&... args) {
    return ::new (storage_.data()) T(std::forward<Args>(args)...);
  }

 private:
  alignas(T) std::array<std::byte, sizeof(T)> storage_{};
};

NeverDestroyed<PartitionAllocator> g_buffer_allocator;
NeverDestroyed<PartitionAllocator> g_fast_allocator;
NeverDestroyed<PartitionAllocator> g_array_buffer_allocator;

PartitionRoot* g_buffer_root = nullptr;
PartitionRoot* g_fast_root = nullptr;
PartitionRoot* g_array_buffer_root = nullptr;
std::atomic<size_t> g_unexpected_oom_size{0};

[[noreturn]] void HandleOutOfMemory(size_t size) {
  g_unexpected_oom_size.store(size, std::memory_order_relaxed);
  fprintf(stderr, "%s:FAIL phase=allocator reason=unexpected_oom size=%zu\n",
          kPrefix, size);
  abort();
}

void PrintPhase(const char* name) {
  printf("%s:PHASE name=%s status=ok\n", kPrefix, name);
}

int Fail(const char* phase, const char* reason) {
  fprintf(stderr, "%s:FAIL phase=%s reason=%s\n", kPrefix, phase, reason);
  return 1;
}

bool IsFilled(const void* memory, size_t size, unsigned char value) {
  const auto* bytes = static_cast<const unsigned char*>(memory);
  for (size_t index = 0; index < size; ++index) {
    if (bytes[index] != value) {
      return false;
    }
  }
  return true;
}

struct CapturingStatsDumper final
    : public partition_alloc::PartitionStatsDumper {
  void PartitionDumpTotals(
      const char*,
      const partition_alloc::PartitionMemoryStats* memory_stats) override {
    totals = *memory_stats;
    saw_totals = true;
  }

  void PartitionsDumpBucketStats(
      const char*,
      const partition_alloc::PartitionBucketMemoryStats* bucket_stats)
      override {
    if (bucket_stats->is_valid && bucket_stats->is_direct_map) {
      saw_direct_map = true;
      direct_map_active_count += bucket_stats->active_count;
      direct_map_active_bytes += bucket_stats->active_bytes;
    }
  }

  partition_alloc::PartitionMemoryStats totals{};
  bool saw_totals = false;
  bool saw_direct_map = false;
  size_t direct_map_active_count = 0;
  size_t direct_map_active_bytes = 0;
};

const char* InitializeBlinkLikeRoots() {
  partition_alloc::PartitionAllocGlobalInit(&HandleOutOfMemory);

  PartitionOptions buffer_options;
  g_buffer_root = g_buffer_allocator.Construct(buffer_options)->root();

  PartitionOptions fast_options;
  fast_options.thread_cache = PartitionOptions::kEnabled;
  fast_options.thread_cache_index = kFastRootThreadCacheIndex;
  g_fast_root = g_fast_allocator.Construct(fast_options)->root();

  PartitionOptions array_buffer_options;
  array_buffer_options.backup_ref_ptr = PartitionOptions::kDisabled;
  array_buffer_options.use_configurable_pool = PartitionOptions::kAllowed;
  array_buffer_options.memory_tagging = {
      .enabled = PartitionOptions::kDisabled};
  g_array_buffer_root =
      g_array_buffer_allocator.Construct(array_buffer_options)->root();

  if (!g_buffer_root || !g_fast_root || !g_array_buffer_root ||
      g_buffer_root == g_fast_root || g_buffer_root == g_array_buffer_root ||
      g_fast_root == g_array_buffer_root) {
    return "root_construction";
  }
  if (!PA_CONFIG(THREAD_CACHE_SUPPORTED) ||
      !g_fast_root->settings_.with_thread_cache) {
    return "wasm_thread_cache_not_enabled";
  }
  if (g_buffer_root->settings_.with_thread_cache ||
      g_array_buffer_root->settings_.with_thread_cache) {
    return "unexpected_thread_cache_root";
  }
  return nullptr;
}

const char* TestRootIsolation() {
  void* buffer_object =
      g_buffer_root->Alloc<kTryAlloc>(64, kTypeName);
  void* fast_object = g_fast_root->Alloc<kTryAlloc>(64, kTypeName);
  void* array_buffer_object =
      g_array_buffer_root->Alloc<kTryAlloc>(64, kTypeName);
  if (!buffer_object || !fast_object || !array_buffer_object) {
    if (buffer_object) {
      g_buffer_root->Free(buffer_object);
    }
    if (fast_object) {
      g_fast_root->Free(fast_object);
    }
    if (array_buffer_object) {
      g_array_buffer_root->Free(array_buffer_object);
    }
    return "root_isolation_allocation";
  }

  const bool roots_match =
      PartitionRoot::GetRootFromAddress(buffer_object) == g_buffer_root &&
      PartitionRoot::GetRootFromAddress(fast_object) == g_fast_root &&
      PartitionRoot::GetRootFromAddress(array_buffer_object) ==
          g_array_buffer_root;
  const bool addresses_differ =
      buffer_object != fast_object && buffer_object != array_buffer_object &&
      fast_object != array_buffer_object;
  memset(buffer_object, 0x19, 64);
  memset(fast_object, 0x38, 64);
  memset(array_buffer_object, 0x57, 64);
  const bool patterns_match =
      IsFilled(buffer_object, 64, 0x19) &&
      IsFilled(fast_object, 64, 0x38) &&
      IsFilled(array_buffer_object, 64, 0x57);

  g_array_buffer_root->Free(array_buffer_object);
  g_fast_root->Free(fast_object);
  g_buffer_root->Free(buffer_object);
  if (!roots_match || !addresses_differ || !patterns_match) {
    return "root_isolation_contract";
  }
  return nullptr;
}

const char* TestBucketZeroCapacityAndRealloc() {
  void* minimum_bucket_object = g_buffer_root->Alloc<kTryZeroAlloc>(
      kMinimumBucketRequestBytes, kTypeName);
  if (!minimum_bucket_object ||
      !IsFilled(minimum_bucket_object, kMinimumBucketRequestBytes, 0)) {
    if (minimum_bucket_object) {
      g_buffer_root->Free(minimum_bucket_object);
    }
    return "minimum_bucket_geometry";
  }
  g_buffer_root->Free(minimum_bucket_object);
  g_buffer_root->PurgeMemory(
      partition_alloc::PurgeFlags::kDecommitEmptySlotSpans);

  void* object =
      g_buffer_root->Alloc<kTryZeroAlloc>(kBucketRequestBytes, kTypeName);
  if (!object) {
    return "bucket_allocation";
  }
  const size_t first_capacity = PartitionRoot::GetUsableSize(object);
  if (first_capacity < kBucketRequestBytes ||
      first_capacity !=
          g_buffer_root->AllocationCapacityFromRequestedSize(
              kBucketRequestBytes) ||
      !IsFilled(object, kBucketRequestBytes, 0)) {
    g_buffer_root->Free(object);
    return "bucket_zero_capacity";
  }

  memset(object, 0xa6, kBucketRequestBytes);
  void* grown =
      g_buffer_root->Realloc<kTryAlloc>(object, kReallocRequestBytes,
                                       kTypeName);
  if (!grown) {
    g_buffer_root->Free(object);
    return "bucket_realloc";
  }
  const size_t grown_capacity = PartitionRoot::GetUsableSize(grown);
  if (PartitionRoot::GetRootFromAddress(grown) != g_buffer_root ||
      grown_capacity < kReallocRequestBytes ||
      grown_capacity !=
          g_buffer_root->AllocationCapacityFromRequestedSize(
              kReallocRequestBytes) ||
      !IsFilled(grown, kBucketRequestBytes, 0xa6)) {
    g_buffer_root->Free(grown);
    return "bucket_realloc_contract";
  }
  memset(grown, 0x5b, kReallocRequestBytes);
  g_buffer_root->Free(grown);

  void* zeroed =
      g_buffer_root->Alloc<kTryZeroAlloc>(kReallocRequestBytes, kTypeName);
  if (!zeroed || !IsFilled(zeroed, kReallocRequestBytes, 0)) {
    if (zeroed) {
      g_buffer_root->Free(zeroed);
    }
    return "bucket_reuse_zero";
  }
  g_buffer_root->Free(zeroed);
  return nullptr;
}

const char* TestDirectMapAndRealloc() {
  void* object =
      g_buffer_root->Alloc<kTryZeroAlloc>(kDirectInitialBytes, kTypeName);
  if (!object) {
    return "direct_map_allocation";
  }
  if (PartitionRoot::GetRootFromAddress(object) != g_buffer_root ||
      PartitionRoot::GetUsableSize(object) < kDirectInitialBytes ||
      !IsFilled(object, kSystemPageBytes, 0)) {
    g_buffer_root->Free(object);
    return "direct_map_initial_contract";
  }

  CapturingStatsDumper active_stats;
  g_buffer_root->DumpStats("buffer", false, true, &active_stats);
  if (!active_stats.saw_totals || !active_stats.saw_direct_map ||
      active_stats.direct_map_active_count != 1 ||
      active_stats.direct_map_active_bytes < kDirectInitialBytes ||
      active_stats.totals.total_active_count == 0 ||
      active_stats.totals.total_active_bytes < kDirectInitialBytes) {
    g_buffer_root->Free(object);
    return "direct_map_stats";
  }

  memset(object, 0xc3, kSystemPageBytes);
  static_cast<unsigned char*>(object)[kDirectShrinkBytes - 1] = 0x7d;
  void* shrunk = g_buffer_root->Realloc<kTryAlloc>(
      object, kDirectShrinkBytes, kTypeName);
  if (!shrunk) {
    g_buffer_root->Free(object);
    return "direct_map_shrink";
  }
  if (PartitionRoot::GetUsableSize(shrunk) < kDirectShrinkBytes ||
      !IsFilled(shrunk, kSystemPageBytes, 0xc3) ||
      static_cast<unsigned char*>(shrunk)[kDirectShrinkBytes - 1] != 0x7d) {
    g_buffer_root->Free(shrunk);
    return "direct_map_shrink_preservation";
  }

  void* regrown = g_buffer_root->Realloc<kTryAlloc>(
      shrunk, kDirectInitialBytes, kTypeName);
  if (!regrown) {
    g_buffer_root->Free(shrunk);
    return "direct_map_regrow";
  }
  if (PartitionRoot::GetRootFromAddress(regrown) != g_buffer_root ||
      PartitionRoot::GetUsableSize(regrown) < kDirectInitialBytes ||
      !IsFilled(regrown, kSystemPageBytes, 0xc3) ||
      static_cast<unsigned char*>(regrown)[kDirectShrinkBytes - 1] != 0x7d) {
    g_buffer_root->Free(regrown);
    return "direct_map_regrow_preservation";
  }
  g_buffer_root->Free(regrown);
  return nullptr;
}

const char* TestAlignedArrayBufferAllocation() {
  void* natural = g_array_buffer_root->AlignedAlloc<kTryZeroAlloc>(
      16, kBucketRequestBytes);
  if (!natural ||
      (reinterpret_cast<uintptr_t>(natural) & (size_t{16} - 1)) != 0 ||
      !IsFilled(natural, kBucketRequestBytes, 0)) {
    if (natural) {
      g_array_buffer_root->AlignedFree(natural);
    }
    return "array_buffer_natural_alignment";
  }
  g_array_buffer_root->AlignedFree(natural);

  void* highly_aligned = g_array_buffer_root->AlignedAlloc<kTryZeroAlloc>(
      kLargeAlignmentBytes, kAlignedRequestBytes);
  if (!highly_aligned ||
      (reinterpret_cast<uintptr_t>(highly_aligned) &
       (kLargeAlignmentBytes - 1)) != 0 ||
      PartitionRoot::GetRootFromAddress(highly_aligned) !=
          g_array_buffer_root ||
      PartitionRoot::GetUsableSize(highly_aligned) < kAlignedRequestBytes ||
      !IsFilled(highly_aligned, kAlignedRequestBytes, 0)) {
    if (highly_aligned) {
      g_array_buffer_root->AlignedFree(highly_aligned);
    }
    return "array_buffer_large_alignment";
  }
  memset(highly_aligned, 0xe4, kAlignedRequestBytes);
  if (!IsFilled(highly_aligned, kAlignedRequestBytes, 0xe4)) {
    g_array_buffer_root->AlignedFree(highly_aligned);
    return "array_buffer_aligned_write";
  }
  g_array_buffer_root->AlignedFree(highly_aligned);
  return nullptr;
}

struct ThreadState {
  PartitionRoot* root = nullptr;
  pthread_barrier_t barrier;
  std::atomic<int> error{0};
  std::atomic<int> live_allocations{0};
  std::atomic<int> maximum_live_allocations{0};
  std::atomic<int> completed_allocations{0};
  std::atomic<int> thread_caches_seen{0};
};

struct ThreadArgument {
  ThreadState* state = nullptr;
  int thread_index = 0;
};

void SetThreadError(ThreadState* state, int code) {
  int expected = 0;
  state->error.compare_exchange_strong(expected, code,
                                       std::memory_order_relaxed);
}

void RaiseMaximum(std::atomic<int>* maximum, int value) {
  int observed = maximum->load(std::memory_order_relaxed);
  while (observed < value &&
         !maximum->compare_exchange_weak(observed, value,
                                         std::memory_order_relaxed)) {
  }
}

void* PartitionAllocThread(void* opaque) {
  auto* argument = static_cast<ThreadArgument*>(opaque);
  ThreadState* state = argument->state;
  bool saw_thread_cache = false;

  for (int iteration = 0; iteration < kThreadIterations; ++iteration) {
    const size_t size =
        48 + static_cast<size_t>((iteration + argument->thread_index) % 32) *
                 16;
    void* object = state->root->Alloc<kTryZeroAlloc>(size, kTypeName);
    bool live = object != nullptr;
    if (!object) {
      SetThreadError(state, 1);
    } else {
      if (!IsFilled(object, size, 0) ||
          PartitionRoot::GetUsableSize(object) < size ||
          PartitionRoot::GetRootFromAddress(object) != state->root) {
        SetThreadError(state, 2);
      }
      if (!saw_thread_cache && state->root->thread_cache_for_testing()) {
        saw_thread_cache = true;
        state->thread_caches_seen.fetch_add(1, std::memory_order_relaxed);
      }
      memset(object, 0x40 + argument->thread_index, size);
      const int live_count =
          state->live_allocations.fetch_add(1, std::memory_order_relaxed) + 1;
      RaiseMaximum(&state->maximum_live_allocations, live_count);
    }

    pthread_barrier_wait(&state->barrier);
    if (object &&
        !IsFilled(object, size, 0x40 + argument->thread_index)) {
      SetThreadError(state, 3);
    }
    pthread_barrier_wait(&state->barrier);

    if (live) {
      state->live_allocations.fetch_sub(1, std::memory_order_relaxed);
      state->root->Free(object);
      state->completed_allocations.fetch_add(1, std::memory_order_relaxed);
    }
    pthread_barrier_wait(&state->barrier);
  }

  if (!saw_thread_cache) {
    SetThreadError(state, 4);
  }
  return nullptr;
}

const char* TestPthreadContention() {
  ThreadState state;
  state.root = g_fast_root;
  if (pthread_barrier_init(&state.barrier, nullptr, kThreadCount) != 0) {
    return "pthread_barrier_init";
  }

  std::array<pthread_t, kThreadCount> handles{};
  std::array<ThreadArgument, kThreadCount> arguments{};
  int created = 0;
  for (; created < kThreadCount; ++created) {
    arguments[created] = {
        .state = &state,
        .thread_index = created,
    };
    if (pthread_create(&handles[created], nullptr, &PartitionAllocThread,
                       &arguments[created]) != 0) {
      break;
    }
  }

  if (created != kThreadCount) {
    // Threads already waiting on the barrier cannot be safely joined after a
    // partial creation. This is a hard harness failure, so terminate without
    // pretending the allocator was tested.
    fprintf(stderr,
            "%s:FAIL phase=pthread_contention reason=pthread_creation "
            "created=%d\n",
            kPrefix, created);
    abort();
  }
  for (int index = 0; index < kThreadCount; ++index) {
    pthread_join(handles[index], nullptr);
  }
  pthread_barrier_destroy(&state.barrier);

  if (state.error.load(std::memory_order_relaxed) != 0 ||
      state.live_allocations.load(std::memory_order_relaxed) != 0 ||
      state.maximum_live_allocations.load(std::memory_order_relaxed) !=
          kThreadCount ||
      state.completed_allocations.load(std::memory_order_relaxed) !=
          kThreadCount * kThreadIterations ||
      state.thread_caches_seen.load(std::memory_order_relaxed) !=
          kThreadCount) {
    fprintf(stderr,
            "%s:DIAGNOSTIC thread_error=%d live=%d max_live=%d "
            "completed=%d caches=%d\n",
            kPrefix, state.error.load(std::memory_order_relaxed),
            state.live_allocations.load(std::memory_order_relaxed),
            state.maximum_live_allocations.load(std::memory_order_relaxed),
            state.completed_allocations.load(std::memory_order_relaxed),
            state.thread_caches_seen.load(std::memory_order_relaxed));
    return "pthread_allocator_contract";
  }
  return nullptr;
}

const char* TestPurgeStatsAndReclaimer(size_t* committed_before,
                                       size_t* committed_after) {
  CapturingStatsDumper baseline_stats;
  g_fast_root->DumpStats("fast_malloc", true, false, &baseline_stats);
  if (!baseline_stats.saw_totals ||
      !baseline_stats.totals.has_thread_cache) {
    return "baseline_reclaimer_stats";
  }
  const size_t baseline_active_count =
      baseline_stats.totals.total_active_count;
  const size_t baseline_allocated_bytes =
      baseline_stats.totals.total_allocated_bytes;

  std::array<void*, kReclaimAllocationCount> objects{};
  int allocated = 0;
  for (; allocated < kReclaimAllocationCount; ++allocated) {
    objects[allocated] =
        g_fast_root->Alloc<kTryAlloc>(4096, kTypeName);
    if (!objects[allocated]) {
      break;
    }
    memset(objects[allocated], 0x91, 4096);
  }
  for (int index = 0; index < allocated; ++index) {
    if (!IsFilled(objects[index], 4096, 0x91)) {
      return "reclaimer_pre_free_pattern";
    }
  }
  for (int index = 0; index < allocated; ++index) {
    g_fast_root->Free(objects[index]);
  }
  if (allocated != kReclaimAllocationCount) {
    return "reclaimer_allocation";
  }

  CapturingStatsDumper before_stats;
  g_fast_root->DumpStats("fast_malloc", true, false, &before_stats);
  if (!before_stats.saw_totals || !before_stats.totals.has_thread_cache ||
      before_stats.totals.total_active_count != baseline_active_count ||
      before_stats.totals.total_allocated_bytes !=
          baseline_allocated_bytes ||
      before_stats.totals.total_committed_bytes == 0) {
    fprintf(stderr,
            "%s:DIAGNOSTIC pre_reclaim saw=%d cache=%d active_count=%zu "
            "allocated=%zu committed=%zu decommittable=%zu\n",
            kPrefix, before_stats.saw_totals,
            before_stats.totals.has_thread_cache,
            before_stats.totals.total_active_count,
            before_stats.totals.total_allocated_bytes,
            before_stats.totals.total_committed_bytes,
            before_stats.totals.total_decommittable_bytes);
    return "pre_reclaimer_stats";
  }
  *committed_before = before_stats.totals.total_committed_bytes;

  partition_alloc::ThreadCache::PurgeCurrentThread();
  partition_alloc::MemoryReclaimer::Instance()->ReclaimAll();

  CapturingStatsDumper after_stats;
  g_fast_root->DumpStats("fast_malloc", true, false, &after_stats);
  *committed_after = after_stats.totals.total_committed_bytes;
  if (!after_stats.saw_totals || !after_stats.totals.has_thread_cache ||
      after_stats.totals.total_active_count > baseline_active_count ||
      after_stats.totals.total_allocated_bytes > baseline_allocated_bytes ||
      *committed_after >= *committed_before) {
    fprintf(stderr,
            "%s:DIAGNOSTIC post_reclaim saw=%d cache=%d active_count=%zu "
            "allocated=%zu committed=%zu before=%zu decommittable=%zu\n",
            kPrefix, after_stats.saw_totals,
            after_stats.totals.has_thread_cache,
            after_stats.totals.total_active_count,
            after_stats.totals.total_allocated_bytes,
            after_stats.totals.total_committed_bytes, *committed_before,
            after_stats.totals.total_decommittable_bytes);
    return "post_reclaimer_stats";
  }

  const int purge_flags =
      partition_alloc::PurgeFlags::kDecommitEmptySlotSpans |
      partition_alloc::PurgeFlags::kDiscardUnusedSystemPages;
  g_buffer_root->PurgeMemory(purge_flags);
  g_array_buffer_root->PurgeMemory(purge_flags);
  CapturingStatsDumper buffer_final_stats;
  CapturingStatsDumper fast_final_stats;
  CapturingStatsDumper array_buffer_final_stats;
  g_buffer_root->DumpStats("buffer", true, false, &buffer_final_stats);
  g_fast_root->DumpStats("fast_malloc", true, false, &fast_final_stats);
  g_array_buffer_root->DumpStats("array_buffer", true, false,
                                 &array_buffer_final_stats);
  if (!buffer_final_stats.saw_totals || !fast_final_stats.saw_totals ||
      !array_buffer_final_stats.saw_totals ||
      buffer_final_stats.totals.total_active_count != 0 ||
      fast_final_stats.totals.total_active_count > baseline_active_count ||
      array_buffer_final_stats.totals.total_active_count != 0 ||
      buffer_final_stats.totals.total_allocated_bytes != 0 ||
      fast_final_stats.totals.total_allocated_bytes >
          baseline_allocated_bytes ||
      array_buffer_final_stats.totals.total_allocated_bytes != 0) {
    return "post_purge_allocated_bytes";
  }
  return nullptr;
}

}  // namespace

int main() {
  printf("%s:RUNTIME_START\n", kPrefix);

  const char* failure = InitializeBlinkLikeRoots();
  if (failure) {
    return Fail("root_initialization", failure);
  }
  PrintPhase("root_initialization");

  failure = TestRootIsolation();
  if (failure) {
    return Fail("root_isolation", failure);
  }
  PrintPhase("root_isolation");

  failure = TestBucketZeroCapacityAndRealloc();
  if (failure) {
    return Fail("bucket_zero_capacity_realloc", failure);
  }
  PrintPhase("bucket_zero_capacity_realloc");

  failure = TestDirectMapAndRealloc();
  if (failure) {
    return Fail("direct_map_realloc_stats", failure);
  }
  PrintPhase("direct_map_realloc_stats");

  failure = TestAlignedArrayBufferAllocation();
  if (failure) {
    return Fail("array_buffer_alignment", failure);
  }
  PrintPhase("array_buffer_alignment");

  failure = TestPthreadContention();
  if (failure) {
    return Fail("pthread_contention", failure);
  }
  PrintPhase("pthread_contention");

  size_t committed_before = 0;
  size_t committed_after = 0;
  failure = TestPurgeStatsAndReclaimer(&committed_before, &committed_after);
  if (failure) {
    return Fail("purge_stats_reclaimer", failure);
  }
  PrintPhase("purge_stats_reclaimer");

  printf("%s:RUNTIME_END\n", kPrefix);
  printf(
      "%s:METRICS committed_before_reclaim=%zu committed_after_reclaim=%zu "
      "threads=%d iterations_per_thread=%d contention_allocations=%d "
      "roots=3\n",
      kPrefix, committed_before, committed_after, kThreadCount,
      kThreadIterations, kThreadCount * kThreadIterations);
  printf(
      "%s:RESULT host=wasm32 production_pa=%s allocator_shim=off "
      "pa_as_malloc=off explicit_roots=ok root_isolation=ok "
      "bucket_allocation=ok zero_fill=ok capacity=ok realloc=ok "
      "direct_map=ok direct_map_stats=ok alignment=ok thread_cache=ok "
      "pthread_contention=ok purge=ok stats=ok reclaimer=ok\n",
      kPrefix, kProductionPartitionAlloc);
  printf("%s:PASS\n", kPrefix);
  return 0;
}
