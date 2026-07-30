// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>

#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <limits>

#include <emscripten/heap.h>

#include "partition_alloc/build_config.h"
#include "partition_alloc/buildflags.h"
#include "partition_alloc/page_allocator.h"
#include "partition_alloc/page_allocator_constants.h"
#include "partition_alloc/partition_alloc_base/posix/safe_strerror.h"
#include "partition_alloc/partition_alloc_base/rand_util.h"
#include "partition_alloc/partition_alloc_base/threading/platform_thread.h"
#include "partition_alloc/partition_alloc_base/time/time.h"
#include "partition_alloc/partition_alloc_constants.h"

namespace {

constexpr char kPrefix[] = "CHROMIUM_WASM_M3_PA_PAGE";
constexpr size_t kSystemPageBytes = 64 * 1024;
constexpr size_t kSuperPageBytes = 2 * 1024 * 1024;
constexpr size_t kAlignmentOffsetBytes = kSystemPageBytes;
constexpr size_t kReuseAllocationBytes = 4 * kSystemPageBytes;
constexpr size_t kContentionAllocationBytes = 2 * kSystemPageBytes;
constexpr int kReuseCycles = 128;
constexpr int kThreadCount = 4;
constexpr int kIterationsPerThread = 64;

using partition_alloc::PageAccessibilityConfiguration;
using partition_alloc::PageAccessibilityDisposition;
using partition_alloc::PageTag;

static_assert(PA_BUILDFLAG(IS_WASM));
static_assert(!PA_BUILDFLAG(IS_POSIX));
static_assert(!PA_BUILDFLAG(USE_PARTITION_ALLOC));
static_assert(!PA_BUILDFLAG(USE_ALLOCATOR_SHIM));
static_assert(!PA_BUILDFLAG(USE_PARTITION_ALLOC_AS_MALLOC));
static_assert(sizeof(size_t) == 4);
static_assert(partition_alloc::internal::PageAllocationGranularity() ==
              kSystemPageBytes);
static_assert(partition_alloc::internal::SystemPageSize() == kSystemPageBytes);
static_assert(partition_alloc::internal::kSuperPageSize == kSuperPageBytes);

PageAccessibilityConfiguration WritablePages() {
  return PageAccessibilityConfiguration(
      PageAccessibilityConfiguration::kReadWrite);
}

bool IsFilled(uintptr_t address, size_t length, unsigned char value) {
  const auto* bytes = reinterpret_cast<const unsigned char*>(address);
  for (size_t index = 0; index < length; ++index) {
    if (bytes[index] != value) {
      return false;
    }
  }
  return true;
}

bool RangesOverlap(uintptr_t first,
                   size_t first_size,
                   uintptr_t second,
                   size_t second_size) {
  return first < second + second_size && second < first + first_size;
}

void PrintPhase(const char* name) {
  printf("%s:PHASE name=%s status=ok\n", kPrefix, name);
}

int Fail(const char* reason) {
  fprintf(stderr, "%s:FAIL reason=%s\n", kPrefix, reason);
  return 1;
}

const char* TestConstants() {
  if (partition_alloc::internal::PageAllocationGranularity() !=
          kSystemPageBytes ||
      partition_alloc::internal::SystemPageSize() != kSystemPageBytes ||
      partition_alloc::internal::kSuperPageSize != kSuperPageBytes ||
      partition_alloc::PageAccessPermissionsAreEnforced() ||
      !partition_alloc::DecommittedMemoryIsAlwaysZeroed()) {
    return "constant_contract_mismatch";
  }

  std::array<unsigned char, 1> random_1{};
  std::array<unsigned char, 255> random_255{};
  std::array<unsigned char, 256> random_256{};
  std::array<unsigned char, 257> random_257_a{};
  std::array<unsigned char, 257> random_257_b{};
  partition_alloc::internal::base::RandBytes(random_1.data(), random_1.size());
  partition_alloc::internal::base::RandBytes(random_255.data(),
                                             random_255.size());
  partition_alloc::internal::base::RandBytes(random_256.data(),
                                             random_256.size());
  partition_alloc::internal::base::RandBytes(random_257_a.data(),
                                             random_257_a.size());
  partition_alloc::internal::base::RandBytes(random_257_b.data(),
                                             random_257_b.size());
  if (random_257_a == random_257_b) {
    return "secure_entropy_repeated";
  }

  using partition_alloc::internal::base::Milliseconds;
  using partition_alloc::internal::base::PlatformThread;
  using partition_alloc::internal::base::ThreadTicks;
  using partition_alloc::internal::base::TimeTicks;
  const TimeTicks before = TimeTicks::Now();
  PlatformThread::Sleep(Milliseconds(1));
  if (TimeTicks::Now() <= before || ThreadTicks::IsSupported() ||
      PlatformThread::CurrentId() == 0 ||
      PlatformThread::CurrentRef().is_null()) {
    return "allocator_base_runtime_contract";
  }

  char error_buffer[64];
  partition_alloc::internal::base::safe_strerror_r(
      ENOMEM, error_buffer, sizeof(error_buffer));
  if (!error_buffer[0]) {
    return "errno_logging_contract";
  }
  return nullptr;
}

const char* TestAlignedSuperPages() {
  const size_t baseline = partition_alloc::GetTotalMappedSize();
  const uintptr_t first =
      partition_alloc::AllocPages(kSuperPageBytes, kSuperPageBytes,
                                  WritablePages(), PageTag::kPartitionAlloc);
  if (!first) {
    return "first_superpage_allocation";
  }
  if ((first & (kSuperPageBytes - 1)) != 0 ||
      partition_alloc::GetTotalMappedSize() != baseline + kSuperPageBytes ||
      !IsFilled(first, kSuperPageBytes, 0)) {
    partition_alloc::FreePages(first, kSuperPageBytes);
    return "first_superpage_contract";
  }

  const uintptr_t second =
      partition_alloc::AllocPages(kSuperPageBytes, kSuperPageBytes,
                                  WritablePages(), PageTag::kPartitionAlloc);
  if (!second) {
    partition_alloc::FreePages(first, kSuperPageBytes);
    return "second_superpage_allocation";
  }
  const bool valid =
      (second & (kSuperPageBytes - 1)) == 0 &&
      !RangesOverlap(first, kSuperPageBytes, second, kSuperPageBytes) &&
      IsFilled(second, kSuperPageBytes, 0) &&
      partition_alloc::GetTotalMappedSize() ==
          baseline + 2 * kSuperPageBytes;
  if (valid) {
    memset(reinterpret_cast<void*>(first), 0x31, kSuperPageBytes);
    memset(reinterpret_cast<void*>(second), 0x72, kSuperPageBytes);
  }
  const bool patterns_valid =
      valid && IsFilled(first, kSuperPageBytes, 0x31) &&
      IsFilled(second, kSuperPageBytes, 0x72);
  partition_alloc::FreePages(second, kSuperPageBytes);
  partition_alloc::FreePages(first, kSuperPageBytes);
  if (!patterns_valid ||
      partition_alloc::GetTotalMappedSize() != baseline) {
    return "aligned_superpage_contract";
  }
  return nullptr;
}

const char* TestAlignmentOffset() {
  const size_t length = 2 * kSystemPageBytes;
  const size_t baseline = partition_alloc::GetTotalMappedSize();
  const uintptr_t address = partition_alloc::AllocPagesWithAlignOffset(
      0, length, kSuperPageBytes, kAlignmentOffsetBytes, WritablePages(),
      PageTag::kPartitionAlloc);
  if (!address) {
    return "offset_allocation";
  }
  const bool valid =
      address % kSuperPageBytes == kAlignmentOffsetBytes &&
      IsFilled(address, length, 0) &&
      partition_alloc::GetTotalMappedSize() == baseline + length;
  if (valid) {
    memset(reinterpret_cast<void*>(address), 0xa6, length);
  }
  const bool pattern_valid = valid && IsFilled(address, length, 0xa6);
  partition_alloc::FreePages(address, length);
  if (!pattern_valid ||
      partition_alloc::GetTotalMappedSize() != baseline) {
    return "offset_alignment_contract";
  }
  return nullptr;
}

const char* TestBoundedReuse() {
  const size_t baseline = partition_alloc::GetTotalMappedSize();
  uintptr_t warmup = partition_alloc::AllocPagesWithAlignOffset(
      0, kReuseAllocationBytes, kSuperPageBytes, kAlignmentOffsetBytes,
      WritablePages(), PageTag::kPartitionAlloc);
  if (!warmup || warmup % kSuperPageBytes != kAlignmentOffsetBytes ||
      !IsFilled(warmup, kReuseAllocationBytes, 0)) {
    return "reuse_warmup_allocation";
  }
  memset(reinterpret_cast<void*>(warmup), 0xcc, kReuseAllocationBytes);
  partition_alloc::FreePages(warmup, kReuseAllocationBytes);
  const size_t plateau_heap = emscripten_get_heap_size();

  for (int cycle = 0; cycle < kReuseCycles; ++cycle) {
    const uintptr_t address = partition_alloc::AllocPagesWithAlignOffset(
        0, kReuseAllocationBytes, kSuperPageBytes, kAlignmentOffsetBytes,
        WritablePages(), PageTag::kPartitionAlloc);
    if (!address || address % kSuperPageBytes != kAlignmentOffsetBytes ||
        !IsFilled(address, kReuseAllocationBytes, 0)) {
      return "reuse_zero_contract";
    }
    memset(reinterpret_cast<void*>(address), cycle + 1,
           kReuseAllocationBytes);
    partition_alloc::FreePages(address, kReuseAllocationBytes);
    if (partition_alloc::GetTotalMappedSize() != baseline ||
        emscripten_get_heap_size() != plateau_heap) {
      return "reuse_not_bounded";
    }
  }
  return nullptr;
}

struct LiveRange {
  uintptr_t address = 0;
  bool active = false;
};

struct ContentionState {
  pthread_mutex_t start_lock;
  pthread_cond_t start_condition;
  int start_state = 0;
  pthread_mutex_t range_lock;
  pthread_barrier_t live_barrier;
  pthread_barrier_t write_barrier;
  pthread_barrier_t free_barrier;
  std::atomic<int> error{0};
  std::atomic<int> allocations{0};
  size_t mapped_baseline = 0;
  LiveRange live_ranges[kThreadCount];
  uintptr_t thread_ids[kThreadCount] = {};
  int64_t tick_samples[kThreadCount] = {};
};

struct ContentionThread {
  ContentionState* state;
  int index;
};

void RecordContentionError(ContentionState* state, int error) {
  int expected = 0;
  state->error.compare_exchange_strong(expected, error,
                                       std::memory_order_relaxed);
}

void WaitAtBarrier(ContentionState* state, pthread_barrier_t* barrier) {
  const int result = pthread_barrier_wait(barrier);
  if (result != 0 && result != PTHREAD_BARRIER_SERIAL_THREAD) {
    RecordContentionError(state, 90);
  }
}

void* RunContentionThread(void* opaque) {
  auto* thread = static_cast<ContentionThread*>(opaque);
  ContentionState* state = thread->state;

  pthread_mutex_lock(&state->start_lock);
  while (state->start_state == 0) {
    pthread_cond_wait(&state->start_condition, &state->start_lock);
  }
  const bool cancelled = state->start_state < 0;
  pthread_mutex_unlock(&state->start_lock);
  if (cancelled) {
    return nullptr;
  }

  state->thread_ids[thread->index] = static_cast<uintptr_t>(
      partition_alloc::internal::base::PlatformThread::CurrentId());
  state->tick_samples[thread->index] =
      partition_alloc::internal::base::TimeTicks::Now().ToInternalValue();

  for (int iteration = 0; iteration < kIterationsPerThread; ++iteration) {
    const uintptr_t address =
        partition_alloc::AllocPages(kContentionAllocationBytes,
                                    kSystemPageBytes, WritablePages(),
                                    PageTag::kPartitionAlloc);
    if (!address) {
      RecordContentionError(state, 1);
    }

    pthread_mutex_lock(&state->range_lock);
    if (address) {
      for (int other = 0; other < kThreadCount; ++other) {
        if (state->live_ranges[other].active &&
            RangesOverlap(address, kContentionAllocationBytes,
                          state->live_ranges[other].address,
                          kContentionAllocationBytes)) {
          RecordContentionError(state, 2);
        }
      }
      state->live_ranges[thread->index] = {address, true};
    }
    pthread_mutex_unlock(&state->range_lock);

    WaitAtBarrier(state, &state->live_barrier);
    if (thread->index == 0 && address &&
        partition_alloc::GetTotalMappedSize() !=
            state->mapped_baseline +
                kThreadCount * kContentionAllocationBytes) {
      RecordContentionError(state, 3);
    }

    if (address) {
      const unsigned char pattern =
          static_cast<unsigned char>(1 + thread->index * 64 + iteration);
      memset(reinterpret_cast<void*>(address), pattern,
             kContentionAllocationBytes);
      if (!IsFilled(address, kContentionAllocationBytes, pattern)) {
        RecordContentionError(state, 4);
      }
    }
    WaitAtBarrier(state, &state->write_barrier);

    pthread_mutex_lock(&state->range_lock);
    state->live_ranges[thread->index] = {};
    pthread_mutex_unlock(&state->range_lock);
    if (address) {
      partition_alloc::FreePages(address, kContentionAllocationBytes);
      state->allocations.fetch_add(1, std::memory_order_relaxed);
    }

    WaitAtBarrier(state, &state->free_barrier);
    if (thread->index == 0 &&
        partition_alloc::GetTotalMappedSize() != state->mapped_baseline) {
      RecordContentionError(state, 5);
    }
    // Do not let the next iteration allocate until the baseline observation
    // above has completed.
    WaitAtBarrier(state, &state->live_barrier);
  }
  return nullptr;
}

const char* TestPthreadContention() {
  ContentionState state;
  state.mapped_baseline = partition_alloc::GetTotalMappedSize();
  if (pthread_mutex_init(&state.start_lock, nullptr) != 0 ||
      pthread_cond_init(&state.start_condition, nullptr) != 0 ||
      pthread_mutex_init(&state.range_lock, nullptr) != 0 ||
      pthread_barrier_init(&state.live_barrier, nullptr, kThreadCount) != 0 ||
      pthread_barrier_init(&state.write_barrier, nullptr, kThreadCount) != 0 ||
      pthread_barrier_init(&state.free_barrier, nullptr, kThreadCount) != 0) {
    return "pthread_primitives_init";
  }

  std::array<pthread_t, kThreadCount> handles{};
  std::array<ContentionThread, kThreadCount> threads{};
  int created = 0;
  for (; created < kThreadCount; ++created) {
    threads[created] = {&state, created};
    if (pthread_create(&handles[created], nullptr, RunContentionThread,
                       &threads[created]) != 0) {
      break;
    }
  }

  pthread_mutex_lock(&state.start_lock);
  state.start_state = created == kThreadCount ? 1 : -1;
  pthread_cond_broadcast(&state.start_condition);
  pthread_mutex_unlock(&state.start_lock);
  for (int index = 0; index < created; ++index) {
    pthread_join(handles[index], nullptr);
  }

  pthread_barrier_destroy(&state.free_barrier);
  pthread_barrier_destroy(&state.write_barrier);
  pthread_barrier_destroy(&state.live_barrier);
  pthread_mutex_destroy(&state.range_lock);
  pthread_cond_destroy(&state.start_condition);
  pthread_mutex_destroy(&state.start_lock);

  if (created != kThreadCount) {
    return "pthread_creation";
  }
  const int contention_error = state.error.load(std::memory_order_relaxed);
  const int allocation_count =
      state.allocations.load(std::memory_order_relaxed);
  const size_t final_mapped = partition_alloc::GetTotalMappedSize();
  if (contention_error != 0 ||
      allocation_count != kThreadCount * kIterationsPerThread ||
      final_mapped != state.mapped_baseline) {
    fprintf(stderr,
            "%s:DIAGNOSTIC contention_error=%d allocations=%d "
            "mapped_baseline=%zu final_mapped=%zu\n",
            kPrefix, contention_error, allocation_count,
            state.mapped_baseline, final_mapped);
    return "pthread_contention_contract";
  }
  for (int first = 0; first < kThreadCount; ++first) {
    if (state.thread_ids[first] == 0 || state.tick_samples[first] <= 0) {
      return "pthread_identity_clock";
    }
    for (int second = first + 1; second < kThreadCount; ++second) {
      if (state.thread_ids[first] == state.thread_ids[second]) {
        return "pthread_ids_not_unique";
      }
    }
  }
  return nullptr;
}

struct FailureIsolationState {
  pthread_barrier_t barrier;
  uintptr_t addresses[2] = {};
  uint32_t errors[2] = {};
};

struct FailureIsolationThread {
  FailureIsolationState* state;
  int index;
};

void* RunFailureIsolationThread(void* opaque) {
  auto* thread = static_cast<FailureIsolationThread*>(opaque);
  FailureIsolationState* state = thread->state;
  if (thread->index == 0) {
    state->addresses[0] = partition_alloc::AllocPages(
        kSystemPageBytes, kSystemPageBytes,
        PageAccessibilityConfiguration(
            PageAccessibilityConfiguration::kInaccessible),
        PageTag::kPartitionAlloc);
  } else {
    state->addresses[1] = partition_alloc::AllocPages(
        emscripten_get_heap_max(), kSystemPageBytes, WritablePages(),
        PageTag::kPartitionAlloc);
  }

  // Both distinct failures must be recorded before either thread observes its
  // own error. A process-global last-error value would make this racy.
  const int barrier_result = pthread_barrier_wait(&state->barrier);
  if (barrier_result != 0 &&
      barrier_result != PTHREAD_BARRIER_SERIAL_THREAD) {
    state->errors[thread->index] = std::numeric_limits<uint32_t>::max();
    return nullptr;
  }
  state->errors[thread->index] = partition_alloc::GetAllocPageErrorCode();
  return nullptr;
}

const char* TestPthreadFailureIsolation() {
  FailureIsolationState state;
  if (pthread_barrier_init(&state.barrier, nullptr, 2) != 0) {
    return "failure_barrier_init";
  }

  std::array<pthread_t, 2> handles{};
  std::array<FailureIsolationThread, 2> threads{{
      {&state, 0},
      {&state, 1},
  }};
  int created = 0;
  for (; created < 2; ++created) {
    if (pthread_create(&handles[created], nullptr, RunFailureIsolationThread,
                       &threads[created]) != 0) {
      break;
    }
  }
  if (created != 2) {
    fprintf(stderr,
            "%s:DIAGNOSTIC failure_isolation_threads_created=%d\n",
            kPrefix, created);
    abort();
  }
  for (pthread_t handle : handles) {
    pthread_join(handle, nullptr);
  }
  pthread_barrier_destroy(&state.barrier);
  if (state.addresses[0] || state.addresses[1] ||
      state.errors[0] != ENOTSUP || state.errors[1] != ENOMEM) {
    fprintf(stderr,
            "%s:DIAGNOSTIC failure_isolation_errors=%u,%u "
            "addresses=%zu,%zu\n",
            kPrefix, state.errors[0], state.errors[1],
            static_cast<size_t>(state.addresses[0]),
            static_cast<size_t>(state.addresses[1]));
    return "pthread_failure_isolation";
  }
  return nullptr;
}

const char* TestAllocationFailures() {
  const size_t baseline_mapped = partition_alloc::GetTotalMappedSize();
  const size_t baseline_heap = emscripten_get_heap_size();
  const size_t maximum_heap = emscripten_get_heap_max();
  const uintptr_t at_limit =
      partition_alloc::AllocPages(maximum_heap, kSystemPageBytes,
                                  WritablePages(), PageTag::kPartitionAlloc);
  if (at_limit || partition_alloc::GetAllocPageErrorCode() != ENOMEM ||
      partition_alloc::GetTotalMappedSize() != baseline_mapped ||
      emscripten_get_heap_size() != baseline_heap) {
    return "linear_limit_failure_contract";
  }

  constexpr size_t kOverflowRequest =
      std::numeric_limits<size_t>::max() & ~(kSystemPageBytes - 1);
  const uintptr_t overflow =
      partition_alloc::AllocPages(kOverflowRequest, kSystemPageBytes,
                                  WritablePages(), PageTag::kPartitionAlloc);
  if (overflow || partition_alloc::GetAllocPageErrorCode() != ENOMEM ||
      partition_alloc::GetTotalMappedSize() != baseline_mapped ||
      emscripten_get_heap_size() != baseline_heap) {
    return "overflow_failure_contract";
  }
  const char* failure_isolation = TestPthreadFailureIsolation();
  if (failure_isolation ||
      partition_alloc::GetTotalMappedSize() != baseline_mapped ||
      emscripten_get_heap_size() != baseline_heap) {
    return failure_isolation ? failure_isolation
                             : "failure_isolation_accounting";
  }
  return nullptr;
}

const char* TestPageLifecycle() {
  const size_t baseline = partition_alloc::GetTotalMappedSize();
  const uintptr_t inaccessible = partition_alloc::AllocPages(
      kSystemPageBytes, kSystemPageBytes,
      PageAccessibilityConfiguration(
          PageAccessibilityConfiguration::kInaccessible),
      PageTag::kPartitionAlloc);
  if (inaccessible || partition_alloc::GetAllocPageErrorCode() != ENOTSUP) {
    return "initial_inaccessible_not_rejected";
  }

  constexpr size_t kLength = 4 * kSystemPageBytes;
  const uintptr_t address =
      partition_alloc::AllocPages(kLength, kSystemPageBytes, WritablePages(),
                                  PageTag::kPartitionAlloc);
  if (!address || !IsFilled(address, kLength, 0)) {
    return "lifecycle_allocation";
  }

  partition_alloc::DiscardSystemPages(address, kSystemPageBytes);
  memset(reinterpret_cast<void*>(address), 0x1d, kSystemPageBytes);
  if (!IsFilled(address, kSystemPageBytes, 0x1d) ||
      partition_alloc::TrySetSystemPagesAccess(
          address, kSystemPageBytes,
          PageAccessibilityConfiguration(
              PageAccessibilityConfiguration::kInaccessible))) {
    partition_alloc::FreePages(address, kLength);
    return "discard_or_access_contract";
  }

  const uintptr_t allow_keep_page = address + kSystemPageBytes;
  memset(reinterpret_cast<void*>(allow_keep_page), 0x42, kSystemPageBytes);
  partition_alloc::DecommitSystemPages(
      allow_keep_page, kSystemPageBytes,
      PageAccessibilityDisposition::kAllowKeepForPerf);
  if (!IsFilled(allow_keep_page, kSystemPageBytes, 0) ||
      !partition_alloc::TryRecommitSystemPages(
          allow_keep_page, kSystemPageBytes, WritablePages(),
          PageAccessibilityDisposition::kAllowKeepForPerf) ||
      !IsFilled(allow_keep_page, kSystemPageBytes, 0)) {
    partition_alloc::FreePages(address, kLength);
    return "allow_keep_recommit_contract";
  }

  const uintptr_t require_update_page = address + 2 * kSystemPageBytes;
  memset(reinterpret_cast<void*>(require_update_page), 0x63,
         kSystemPageBytes);
  if (partition_alloc::TryRecommitSystemPages(
          require_update_page, kSystemPageBytes, WritablePages(),
          PageAccessibilityDisposition::kRequireUpdate) ||
      !IsFilled(require_update_page, kSystemPageBytes, 0x63)) {
    partition_alloc::FreePages(address, kLength);
    return "require_update_not_rejected";
  }

  const uintptr_t decommit_and_zero_page = address + 3 * kSystemPageBytes;
  memset(reinterpret_cast<void*>(decommit_and_zero_page), 0x84,
         kSystemPageBytes);
  if (partition_alloc::DecommitAndZeroSystemPages(
          decommit_and_zero_page, kSystemPageBytes,
          PageTag::kPartitionAlloc) ||
      !IsFilled(decommit_and_zero_page, kSystemPageBytes, 0x84) ||
      partition_alloc::SealSystemPages(address, kLength)) {
    partition_alloc::FreePages(address, kLength);
    return "decommit_and_zero_or_seal_contract";
  }

  partition_alloc::FreePages(address, kLength);
  if (partition_alloc::GetTotalMappedSize() != baseline) {
    return "lifecycle_mapped_accounting";
  }
  return nullptr;
}

struct GrowthMetrics {
  size_t pre_growth_heap_bytes = 0;
  size_t grown_heap_bytes = 0;
  size_t final_heap_bytes = 0;
  size_t growth_request_bytes = 0;
  size_t mapped_during_growth_bytes = 0;
};

const char* TestMemoryGrowth(GrowthMetrics* metrics) {
  const size_t baseline = partition_alloc::GetTotalMappedSize();
  metrics->pre_growth_heap_bytes = emscripten_get_heap_size();
  metrics->growth_request_bytes =
      (metrics->pre_growth_heap_bytes + 2 * kSystemPageBytes - 1) &
      ~(kSystemPageBytes - 1);
  if (metrics->growth_request_bytes <= metrics->pre_growth_heap_bytes ||
      metrics->growth_request_bytes >= emscripten_get_heap_max()) {
    return "growth_request_contract";
  }

  const uintptr_t first = partition_alloc::AllocPages(
      metrics->growth_request_bytes, kSystemPageBytes, WritablePages(),
      PageTag::kPartitionAlloc);
  if (!first) {
    return "growth_allocation";
  }
  metrics->grown_heap_bytes = emscripten_get_heap_size();
  metrics->mapped_during_growth_bytes =
      partition_alloc::GetTotalMappedSize();
  const bool first_valid =
      metrics->grown_heap_bytes > metrics->pre_growth_heap_bytes &&
      metrics->mapped_during_growth_bytes ==
          baseline + metrics->growth_request_bytes &&
      IsFilled(first, metrics->growth_request_bytes, 0);
  if (first_valid) {
    memset(reinterpret_cast<void*>(first), 0xb7,
           metrics->growth_request_bytes);
  }
  const bool first_pattern =
      first_valid && IsFilled(first, metrics->growth_request_bytes, 0xb7);
  partition_alloc::FreePages(first, metrics->growth_request_bytes);
  if (!first_pattern || partition_alloc::GetTotalMappedSize() != baseline) {
    return "growth_first_contract";
  }

  const uintptr_t second = partition_alloc::AllocPages(
      metrics->growth_request_bytes, kSystemPageBytes, WritablePages(),
      PageTag::kPartitionAlloc);
  if (!second ||
      emscripten_get_heap_size() != metrics->grown_heap_bytes ||
      !IsFilled(second, metrics->growth_request_bytes, 0)) {
    return "growth_reuse_contract";
  }
  partition_alloc::FreePages(second, metrics->growth_request_bytes);
  metrics->final_heap_bytes = emscripten_get_heap_size();
  if (metrics->final_heap_bytes != metrics->grown_heap_bytes ||
      partition_alloc::GetTotalMappedSize() != baseline) {
    return "growth_final_contract";
  }
  return nullptr;
}

}  // namespace

int main() {
  const size_t startup_heap_bytes = emscripten_get_heap_size();
  const size_t maximum_heap_bytes = emscripten_get_heap_max();
  const size_t initial_mapped_bytes = partition_alloc::GetTotalMappedSize();
  printf("%s:RUNTIME_START\n", kPrefix);

  const char* error = TestConstants();
  if (error) {
    return Fail(error);
  }
  PrintPhase("constants");

  error = TestAlignedSuperPages();
  if (error) {
    return Fail(error);
  }
  PrintPhase("aligned_superpages");

  error = TestAlignmentOffset();
  if (error) {
    return Fail(error);
  }
  PrintPhase("alignment_offset");

  error = TestBoundedReuse();
  if (error) {
    return Fail(error);
  }
  PrintPhase("bounded_reuse");

  error = TestPthreadContention();
  if (error) {
    return Fail(error);
  }
  PrintPhase("pthread_contention");

  error = TestAllocationFailures();
  if (error) {
    return Fail(error);
  }
  PrintPhase("allocation_failures");

  error = TestPageLifecycle();
  if (error) {
    return Fail(error);
  }
  PrintPhase("page_lifecycle");

  GrowthMetrics growth;
  error = TestMemoryGrowth(&growth);
  if (error) {
    return Fail(error);
  }
  PrintPhase("memory_growth");

  const size_t final_mapped_bytes = partition_alloc::GetTotalMappedSize();
  printf("%s:RUNTIME_END\n", kPrefix);
  printf(
      "%s:METRICS startup_heap_bytes=%zu pre_growth_heap_bytes=%zu "
      "grown_heap_bytes=%zu final_heap_bytes=%zu max_heap_bytes=%zu "
      "initial_mapped_bytes=%zu growth_request_bytes=%zu "
      "mapped_during_growth_bytes=%zu final_mapped_bytes=%zu\n",
      kPrefix, startup_heap_bytes, growth.pre_growth_heap_bytes,
      growth.grown_heap_bytes, growth.final_heap_bytes, maximum_heap_bytes,
      initial_mapped_bytes, growth.growth_request_bytes,
      growth.mapped_during_growth_bytes, final_mapped_bytes);
  printf(
      "%s:RESULT host=wasm32 production_pa=off allocator_shim=off "
      "pa_as_malloc=off granularity_64k=ok system_page_64k=ok "
      "superpage_alignment=ok superpage_nonoverlap=ok "
      "superpage_fresh_zero=ok offset_alignment=ok bounded_reuse=ok "
      "reused_zero=ok free_accounting=ok pthread_contention=ok "
      "overflow_rejected=ok linear_limit_rejected=ok failure_isolation=ok "
      "discard_contract=ok "
      "decommit_recommit_zero=ok require_update=unsupported "
      "decommit_and_zero=unsupported permissions=logical_only "
      "unsupported_permissions=reported memory_growth=ok growth_reuse=ok "
      "mapped_accounting=ok threads=4 iterations_per_thread=64 "
      "contention_allocations=256 reuse_cycles=128 "
      "allocation_granularity_bytes=65536 system_page_bytes=65536 "
      "superpage_bytes=2097152 alignment_offset_bytes=65536\n",
      kPrefix);
  printf("%s:PASS\n", kPrefix);
  return 0;
}
