// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <emscripten/heap.h>
#include <emscripten/threading.h>

#include <algorithm>
#include <atomic>
#include <cinttypes>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <limits>
#include <type_traits>
#include <utility>

#include "base/containers/span.h"
#include "base/memory/platform_shared_memory_handle.h"
#include "base/memory/platform_shared_memory_region.h"
#include "base/memory/process_local_shared_memory_wasm.h"
#include "base/memory/read_only_shared_memory_region.h"
#include "base/memory/shared_memory_mapper.h"
#include "base/memory/unsafe_shared_memory_region.h"
#include "base/memory/writable_shared_memory_region.h"
#include "base/synchronization/waitable_event.h"
#include "base/system/sys_info.h"
#include "base/threading/platform_thread.h"
#include "base/time/time.h"
#include "base/unguessable_token.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "m1_shared_memory_smoke must be built for WebAssembly"
#endif

#if BUILDFLAG(IS_POSIX)
#error "WebAssembly must not inherit POSIX platform semantics"
#endif

namespace {

using PlatformRegion = base::subtle::PlatformSharedMemoryRegion;
using PlatformHandle = base::subtle::PlatformSharedMemoryHandle;
using ScopedPlatformHandle =
    base::subtle::ScopedPlatformSharedMemoryHandle;
using HandleRights = base::subtle::PlatformSharedMemoryHandleRights;

constexpr char kPrefix[] = "CHROMIUM_WASM_M1_SHARED_MEMORY";
constexpr size_t kPublicMinimumAlignment =
    PlatformRegion::kMapMinimumAlignment;
constexpr size_t kWasmAllocationGranularity = 65536;
constexpr size_t kRegionSize = 2 * kWasmAllocationGranularity + 1024;
constexpr size_t kPatternSize = 257;
constexpr size_t kConcurrentSize = 4096;
constexpr uint64_t kExpectedMaximumMemory = UINT64_C(2147483648);
constexpr base::TimeDelta kPhaseTimeout = base::Seconds(3);
constexpr base::TimeDelta kConcurrentWindow = base::Milliseconds(275);

static_assert(kPublicMinimumAlignment == 32);
static_assert(!std::is_integral_v<PlatformHandle>);
static_assert(!std::is_pointer_v<PlatformHandle>);

int Fail(const char* reason) {
  std::fprintf(stderr, "%s:FAIL reason=%s\n", kPrefix, reason);
  std::fflush(stderr);
  return 1;
}

[[noreturn]] void FailImmediately(const char* reason) {
  Fail(reason);
  std::abort();
}

void Require(bool condition, const char* reason) {
  if (!condition) {
    FailImmediately(reason);
  }
}

void BeginPhase(const char* phase) {
  std::fprintf(stdout, "%s:PHASE name=%s\n", kPrefix, phase);
  std::fflush(stdout);
}

template <typename Predicate>
bool WaitUntil(Predicate predicate, base::TimeDelta timeout = kPhaseTimeout) {
  const base::TimeTicks deadline = base::TimeTicks::Now() + timeout;
  while (!predicate()) {
    if (base::TimeTicks::Now() >= deadline) {
      return predicate();
    }
    base::PlatformThread::YieldCurrentThread();
    base::PlatformThread::Sleep(base::Milliseconds(1));
  }
  return true;
}

bool SameGuid(const base::UnguessableToken& left,
              const base::UnguessableToken& right) {
  return left.GetHighForSerialization() == right.GetHighForSerialization() &&
         left.GetLowForSerialization() == right.GetLowForSerialization();
}

template <typename Mapping>
bool HasPattern(const Mapping& mapping,
                size_t offset,
                size_t size,
                uint8_t seed) {
  base::span<const uint8_t> bytes(mapping);
  if (offset > bytes.size() || size > bytes.size() - offset) {
    return false;
  }
  for (size_t index = 0; index < size; ++index) {
    const uint8_t expected =
        static_cast<uint8_t>(seed + (index * 29U) % 251U);
    if (bytes[offset + index] != expected) {
      return false;
    }
  }
  return true;
}

void WritePattern(base::span<uint8_t> bytes, uint8_t seed) {
  for (size_t index = 0; index < bytes.size(); ++index) {
    bytes[index] =
        static_cast<uint8_t>(seed + (index * 29U) % 251U);
  }
}

struct MemoryMetrics {
  uint64_t initial_heap_bytes = emscripten_get_heap_size();
  uint64_t peak_heap_bytes = initial_heap_bytes;
  uint64_t max_heap_bytes = emscripten_get_heap_max();

  void Sample() {
    peak_heap_bytes =
        std::max<uint64_t>(peak_heap_bytes, emscripten_get_heap_size());
  }
};

bool MetadataRejected(base::ReadOnlySharedMemoryRegion region,
                      size_t size,
                      const base::UnguessableToken& guid) {
  PlatformRegion platform =
      base::ReadOnlySharedMemoryRegion::TakeHandleForSerialization(
          std::move(region));
  ScopedPlatformHandle handle = platform.PassPlatformHandle();
  auto result = PlatformRegion::TakeOrFail(std::move(handle),
                                           PlatformRegion::Mode::kReadOnly,
                                           size, guid);
  return !result.has_value() || !result->IsValid();
}

bool CapabilityRejected(PlatformHandle handle) {
  return !base::subtle::wasm::IsHandleValid(handle) &&
         !base::subtle::wasm::GetRegionMetadata(handle).has_value() &&
         !base::subtle::wasm::DuplicateHandle(handle).is_valid() &&
         !base::subtle::wasm::Map(handle, true, 0, 1).has_value();
}

void TestWritableAndReadOnly(MemoryMetrics* metrics) {
  BeginPhase("writable_read_only");

  base::WritableSharedMemoryRegion region =
      base::WritableSharedMemoryRegion::Create(kRegionSize);
  Require(region.IsValid(), "writable_create");
  Require(region.GetSize() == kRegionSize, "writable_size");
  const base::UnguessableToken guid = region.GetGUID();
  Require(!guid.is_empty(), "writable_guid_empty");

  base::WritableSharedMemoryMapping mapping = region.Map();
  Require(mapping.IsValid() && mapping.size() == kRegionSize,
          "writable_map");
  Require(reinterpret_cast<uintptr_t>(mapping.data()) %
                  kPublicMinimumAlignment ==
              0,
          "minimum_alignment");
  Require(reinterpret_cast<uintptr_t>(mapping.data()) %
                  kWasmAllocationGranularity ==
              0,
          "vm_alignment");
  WritePattern(base::span(mapping).first(kPatternSize), 0x31);

  base::WritableSharedMemoryMapping second_mapping =
      region.MapAt(0, kPatternSize);
  Require(second_mapping.IsValid() &&
              HasPattern(second_mapping, 0, kPatternSize, 0x31),
          "writable_byte_round_trip");

  base::WritableSharedMemoryRegion moved_region = std::move(region);
  Require(!region.IsValid() && moved_region.IsValid(),  // NOLINT
          "writable_move");
  Require(SameGuid(moved_region.GetGUID(), guid), "writable_move_guid");

  PlatformRegion serialized =
      base::WritableSharedMemoryRegion::TakeHandleForSerialization(
          std::move(moved_region));
  Require(!moved_region.IsValid() && serialized.IsValid(),  // NOLINT
          "writable_serialize");
  Require(
      !base::subtle::wasm::DuplicateHandle(
           serialized.GetPlatformHandle())
           .is_valid(),
      "writable_duplicate_allowed");

  base::WritableSharedMemoryRegion restored =
      base::WritableSharedMemoryRegion::Deserialize(std::move(serialized));
  Require(restored.IsValid() && SameGuid(restored.GetGUID(), guid),
          "writable_deserialize");
  base::WritableSharedMemoryMapping restored_mapping = restored.Map();
  Require(restored_mapping.IsValid() &&
              HasPattern(restored_mapping, 0, kPatternSize, 0x31),
          "writable_serialization_round_trip");

  base::ReadOnlySharedMemoryRegion read_only =
      base::WritableSharedMemoryRegion::ConvertToReadOnly(
          std::move(restored));
  Require(read_only.IsValid() && SameGuid(read_only.GetGUID(), guid),
          "convert_to_read_only");
  base::ReadOnlySharedMemoryMapping read_only_mapping = read_only.Map();
  Require(read_only_mapping.IsValid() &&
              HasPattern(read_only_mapping, 0, kPatternSize, 0x31),
          "read_only_map");

  base::ReadOnlySharedMemoryRegion read_only_duplicate =
      read_only.Duplicate();
  Require(read_only_duplicate.IsValid() &&
              SameGuid(read_only_duplicate.GetGUID(), guid),
          "read_only_duplicate");
  base::ReadOnlySharedMemoryMapping duplicate_mapping =
      read_only_duplicate.Map();
  Require(duplicate_mapping.IsValid() &&
              HasPattern(duplicate_mapping, 0, kPatternSize, 0x31),
          "read_only_duplicate_map");

  Require(
      !base::subtle::wasm::Map(read_only.GetPlatformHandle(), true, 0,
                               kPatternSize)
           .has_value(),
      "read_only_writable_map_allowed");
  Require(!base::subtle::wasm::ConvertHandleRights(
              read_only.GetPlatformHandle(), HandleRights::kWritable),
          "read_only_promoted");

  PlatformRegion mismatched =
      base::ReadOnlySharedMemoryRegion::TakeHandleForSerialization(
          read_only.Duplicate());
  const size_t mismatched_size = mismatched.GetSize();
  const base::UnguessableToken mismatched_guid = mismatched.GetGUID();
  ScopedPlatformHandle mismatched_handle =
      mismatched.PassPlatformHandle();
  auto mismatched_result = PlatformRegion::TakeOrFail(
      std::move(mismatched_handle), PlatformRegion::Mode::kWritable,
      mismatched_size, mismatched_guid);
  Require(!mismatched_result.has_value() ||
              !mismatched_result->IsValid(),
          "mode_mismatch_accepted");

  Require(
      MetadataRejected(read_only.Duplicate(), read_only.GetSize() + 1, guid),
      "corrupt_size_accepted");
  const base::UnguessableToken wrong_guid =
      base::UnguessableToken::Create();
  Require(!SameGuid(wrong_guid, guid), "wrong_guid_collision");
  Require(MetadataRejected(read_only.Duplicate(), read_only.GetSize(),
                           wrong_guid),
          "corrupt_guid_accepted");

  base::MappedReadOnlyRegion initially_read_only =
      base::ReadOnlySharedMemoryRegion::Create(kPatternSize);
  Require(initially_read_only.IsValid(), "read_only_create");
  WritePattern(base::span(initially_read_only.mapping), 0x4A);
  base::ReadOnlySharedMemoryMapping initial_read_mapping =
      initially_read_only.region.Map();
  Require(initial_read_mapping.IsValid() &&
              HasPattern(initial_read_mapping, 0, kPatternSize, 0x4A),
          "read_only_create_round_trip");

  metrics->Sample();
}

void TestMappingAndRegionLifetime(MemoryMetrics* metrics) {
  BeginPhase("mapping_lifetime");

  base::WritableSharedMemoryMapping survivor;
  base::UnguessableToken guid;
  {
    base::WritableSharedMemoryRegion region =
        base::WritableSharedMemoryRegion::Create(kPatternSize);
    Require(region.IsValid(), "lifetime_region_create");
    guid = region.GetGUID();
    survivor = region.Map();
    Require(survivor.IsValid(), "lifetime_region_map");
    WritePattern(base::span(survivor), 0x62);
  }

  Require(survivor.IsValid() &&
              SameGuid(survivor.guid(), guid) &&
              HasPattern(survivor, 0, kPatternSize, 0x62),
          "mapping_did_not_outlive_handle");
  base::WritableSharedMemoryMapping moved_mapping = std::move(survivor);
  Require(!survivor.IsValid() && moved_mapping.IsValid(),  // NOLINT
          "mapping_move");
  Require(HasPattern(moved_mapping, 0, kPatternSize, 0x62),
          "moved_mapping_contents");

  base::UnsafeSharedMemoryRegion unsafe =
      base::UnsafeSharedMemoryRegion::Create(kPatternSize);
  Require(unsafe.IsValid(), "unsafe_create");
  base::WritableSharedMemoryMapping unsafe_mapping = unsafe.Map();
  Require(unsafe_mapping.IsValid(), "unsafe_map");
  WritePattern(base::span(unsafe_mapping), 0x73);
  base::UnsafeSharedMemoryRegion unsafe_duplicate = unsafe.Duplicate();
  Require(unsafe_duplicate.IsValid() &&
              SameGuid(unsafe_duplicate.GetGUID(), unsafe.GetGUID()),
          "unsafe_duplicate");
  unsafe = {};
  base::WritableSharedMemoryMapping unsafe_duplicate_mapping =
      unsafe_duplicate.Map();
  Require(unsafe_duplicate_mapping.IsValid() &&
              HasPattern(unsafe_duplicate_mapping, 0, kPatternSize, 0x73),
          "unsafe_duplicate_lifetime");

  metrics->Sample();
}

void TestRangesAndCapabilities(MemoryMetrics* metrics) {
  BeginPhase("ranges_capabilities");

  base::UnsafeSharedMemoryRegion region =
      base::UnsafeSharedMemoryRegion::Create(kRegionSize);
  Require(region.IsValid(), "range_region_create");
  base::WritableSharedMemoryMapping full_mapping = region.Map();
  Require(full_mapping.IsValid(), "range_full_map");
  Require(reinterpret_cast<uintptr_t>(full_mapping.data()) %
                  kWasmAllocationGranularity ==
              0,
          "range_vm_alignment");

  const size_t partial_offset = kWasmAllocationGranularity + 37;
  base::WritableSharedMemoryMapping partial =
      region.MapAt(partial_offset, kPatternSize);
  Require(partial.IsValid() && partial.size() == kPatternSize,
          "partial_map");
  WritePattern(base::span(partial), 0x85);
  Require(HasPattern(full_mapping, partial_offset, kPatternSize, 0x85),
          "partial_map_round_trip");

  Require(!region.MapAt(kRegionSize, 1).IsValid(),
          "range_offset_at_end");
  Require(!region.MapAt(kRegionSize - 1, 2).IsValid(),
          "range_past_end");
  Require(!region
               .MapAt(kWasmAllocationGranularity,
                      std::numeric_limits<size_t>::max())
               .IsValid(),
          "range_overflow");
  Require(!region.MapAt(0, 0).IsValid(), "zero_map");
  Require(!base::WritableSharedMemoryRegion::Create(0).IsValid(),
          "zero_writable_create");
  Require(!base::UnsafeSharedMemoryRegion::Create(0).IsValid(),
          "zero_unsafe_create");
  Require(!base::ReadOnlySharedMemoryRegion::Create(0).IsValid(),
          "zero_read_only_create");

  PlatformHandle invalid;
  Require(CapabilityRejected(invalid), "zero_capability_accepted");

  const PlatformHandle live = region.GetPlatformHandle();
  PlatformHandle forged_region_id = live;
  forged_region_id.region_id ^= UINT64_C(1) << 63;
  Require(forged_region_id.region_id != 0 &&
              forged_region_id.region_id != live.region_id,
          "forged_region_id_invalid");
  Require(CapabilityRejected(forged_region_id),
          "forged_region_id_accepted");

  PlatformHandle forged_generation = live;
  forged_generation.generation ^= UINT64_C(1) << 63;
  Require(forged_generation.generation != 0 &&
              forged_generation.generation != live.generation,
          "forged_generation_invalid");
  Require(CapabilityRejected(forged_generation),
          "forged_generation_accepted");
  Require(base::subtle::wasm::IsHandleValid(live) &&
              base::subtle::wasm::GetRegionMetadata(live).has_value() &&
              region.MapAt(0, 1).IsValid(),
          "live_capability_damaged");

  PlatformHandle corrupted_rights_stale;
  {
    base::UnsafeSharedMemoryRegion corrupted_rights_region =
        base::UnsafeSharedMemoryRegion::Create(kPatternSize);
    Require(corrupted_rights_region.IsValid(),
            "corrupt_rights_region_create");
    corrupted_rights_stale =
        corrupted_rights_region.GetPlatformHandle();
    ScopedPlatformHandle corrupted_rights_handle =
        base::subtle::wasm::DuplicateHandle(corrupted_rights_stale);
    Require(corrupted_rights_handle.is_valid(),
            "corrupt_rights_duplicate");
    PlatformHandle corrupted_rights =
        corrupted_rights_handle.release();
    corrupted_rights.rights = HandleRights::kReadOnly;
    auto corrupted_rights_result = PlatformRegion::TakeOrFail(
        ScopedPlatformHandle(corrupted_rights),
        PlatformRegion::Mode::kReadOnly, kPatternSize,
        corrupted_rights_region.GetGUID());
    Require(!corrupted_rights_result.has_value(),
            "corrupt_rights_accepted");

    ScopedPlatformHandle invalid_rights_handle =
        base::subtle::wasm::DuplicateHandle(corrupted_rights_stale);
    Require(invalid_rights_handle.is_valid(),
            "invalid_rights_duplicate");
    PlatformHandle invalid_rights = invalid_rights_handle.release();
    invalid_rights.rights = HandleRights::kInvalid;
    auto invalid_rights_result = PlatformRegion::TakeOrFail(
        ScopedPlatformHandle(invalid_rights),
        PlatformRegion::Mode::kUnsafe, kPatternSize,
        corrupted_rights_region.GetGUID());
    Require(!invalid_rights_result.has_value() ||
                !invalid_rights_result->IsValid(),
            "invalid_rights_accepted");
  }
  Require(CapabilityRejected(corrupted_rights_stale),
          "corrupt_rights_reference_leaked");

  PlatformHandle stale;
  base::UnguessableToken stale_guid;
  {
    base::UnsafeSharedMemoryRegion stale_region =
        base::UnsafeSharedMemoryRegion::Create(kPatternSize);
    Require(stale_region.IsValid(), "stale_region_create");
    stale = stale_region.GetPlatformHandle();
    stale_guid = stale_region.GetGUID();
    Require(base::subtle::wasm::IsHandleValid(stale),
            "fresh_capability_invalid");
  }
  Require(!base::subtle::wasm::IsHandleValid(stale),
          "stale_capability_valid");
  Require(!base::subtle::wasm::GetRegionMetadata(stale).has_value(),
          "stale_capability_metadata");
  Require(!base::subtle::wasm::DuplicateHandle(stale).is_valid(),
          "stale_capability_duplicate");
  Require(!base::subtle::wasm::Map(stale, true, 0, 1).has_value(),
          "stale_capability_map");
  auto stale_result = PlatformRegion::TakeOrFail(
      ScopedPlatformHandle(stale), PlatformRegion::Mode::kUnsafe,
      kPatternSize, stale_guid);
  Require(!stale_result.has_value() || !stale_result->IsValid(),
          "stale_capability_adopted");

  metrics->Sample();
}

void UpdateMaximum(std::atomic<int>* maximum, int candidate) {
  int current = maximum->load(std::memory_order_relaxed);
  while (current < candidate &&
         !maximum->compare_exchange_weak(
             current, candidate, std::memory_order_relaxed,
             std::memory_order_relaxed)) {
  }
}

class SharedMemoryWorker final : public base::PlatformThread::Delegate {
 public:
  SharedMemoryWorker(base::UnsafeSharedMemoryRegion region,
                     base::WaitableEvent* ready,
                     base::WaitableEvent* start,
                     std::atomic<int>* live_threads,
                     std::atomic<int>* max_live_threads)
      : region_(std::move(region)),
        ready_(ready),
        start_(start),
        live_threads_(live_threads),
        max_live_threads_(max_live_threads) {}

  void ThreadMain() override {
    const int live =
        live_threads_->fetch_add(1, std::memory_order_acq_rel) + 1;
    UpdateMaximum(max_live_threads_, live);

    base::WritableSharedMemoryMapping mapping = region_.Map();
    mapping_valid_ = mapping.IsValid();
    ready_->Signal();
    if (!mapping_valid_ || !start_->TimedWait(kPhaseTimeout)) {
      wait_succeeded_ = false;
      live_threads_->fetch_sub(1, std::memory_order_acq_rel);
      return;
    }

    wait_succeeded_ = true;
    active_.store(true, std::memory_order_release);
    const base::TimeTicks deadline =
        base::TimeTicks::Now() + kConcurrentWindow;
    base::span<uint8_t> worker_bytes =
        base::span(mapping).subspan(kConcurrentSize / 2);
    while (base::TimeTicks::Now() < deadline) {
      WritePattern(worker_bytes, 0xB4);
      ++iterations_;
      base::PlatformThread::YieldCurrentThread();
    }
    active_.store(false, std::memory_order_release);
    live_threads_->fetch_sub(1, std::memory_order_acq_rel);
  }

  bool active() const { return active_.load(std::memory_order_acquire); }
  bool mapping_valid() const { return mapping_valid_; }
  bool wait_succeeded() const { return wait_succeeded_; }
  int iterations() const { return iterations_; }

 private:
  base::UnsafeSharedMemoryRegion region_;
  base::WaitableEvent* const ready_;
  base::WaitableEvent* const start_;
  std::atomic<int>* const live_threads_;
  std::atomic<int>* const max_live_threads_;
  std::atomic<bool> active_{false};
  bool mapping_valid_ = false;
  bool wait_succeeded_ = false;
  int iterations_ = 0;
};

void TestConcurrentThreads(MemoryMetrics* metrics) {
  BeginPhase("concurrent_threads");

  base::UnsafeSharedMemoryRegion region =
      base::UnsafeSharedMemoryRegion::Create(kConcurrentSize);
  Require(region.IsValid(), "concurrent_region_create");
  base::WritableSharedMemoryMapping application_mapping = region.Map();
  Require(application_mapping.IsValid(), "concurrent_application_map");
  base::UnsafeSharedMemoryRegion worker_region = region.Duplicate();
  Require(worker_region.IsValid(), "concurrent_region_duplicate");

  base::WaitableEvent ready(base::WaitableEvent::ResetPolicy::MANUAL,
                            base::WaitableEvent::InitialState::NOT_SIGNALED);
  base::WaitableEvent start(base::WaitableEvent::ResetPolicy::MANUAL,
                            base::WaitableEvent::InitialState::NOT_SIGNALED);
  std::atomic<int> live_threads{1};
  std::atomic<int> max_live_threads{1};
  SharedMemoryWorker worker(std::move(worker_region), &ready, &start,
                            &live_threads, &max_live_threads);

  int worker_threads_created = 0;
  int worker_threads_joined = 0;
  int worker_creation_failures = 0;
  base::PlatformThreadHandle worker_handle;
  if (base::PlatformThread::Create(0, &worker, &worker_handle)) {
    ++worker_threads_created;
  } else {
    ++worker_creation_failures;
    Require(false, "concurrent_worker_create");
  }

  Require(ready.TimedWait(kPhaseTimeout), "concurrent_worker_ready");
  start.Signal();
  Require(WaitUntil([&worker] { return worker.active(); }),
          "concurrent_worker_active");

  const base::TimeTicks deadline =
      base::TimeTicks::Now() + kConcurrentWindow;
  base::span<uint8_t> application_bytes =
      base::span(application_mapping).first(kConcurrentSize / 2);
  int application_iterations = 0;
  bool overlap_observed = false;
  while (base::TimeTicks::Now() < deadline) {
    overlap_observed |= worker.active();
    WritePattern(application_bytes, 0xA3);
    ++application_iterations;
    base::PlatformThread::YieldCurrentThread();
  }

  base::PlatformThread::Join(worker_handle);
  ++worker_threads_joined;
  Require(worker.mapping_valid() && worker.wait_succeeded(),
          "concurrent_worker_mapping");
  Require(worker.iterations() > 0 && application_iterations > 0,
          "concurrent_iterations");
  Require(overlap_observed, "concurrent_overlap");
  Require(HasPattern(application_mapping, 0, kConcurrentSize / 2, 0xA3),
          "concurrent_application_bytes");
  Require(HasPattern(application_mapping, kConcurrentSize / 2,
                     kConcurrentSize / 2, 0xB4),
          "concurrent_worker_bytes");
  Require(worker_threads_created == 1 && worker_threads_joined == 1 &&
              worker_creation_failures == 0,
          "concurrent_worker_counts");
  Require(live_threads.load(std::memory_order_acquire) == 1,
          "concurrent_worker_still_live");
  Require(max_live_threads.load(std::memory_order_acquire) == 2,
          "concurrent_max_threads");

  metrics->Sample();
}

}  // namespace

int main() {
  if (emscripten_is_main_browser_thread()) {
    return Fail("application_main_on_browser_thread");
  }
  if (emscripten_is_main_runtime_thread()) {
    return Fail("application_main_on_runtime_thread");
  }
  if (!emscripten_has_threading_support()) {
    return Fail("pthread_support_unavailable");
  }
  Require(base::SysInfo::VMAllocationGranularity() ==
              kWasmAllocationGranularity,
          "vm_granularity");

  std::fprintf(stdout, "%s:RUNTIME_START\n", kPrefix);
  std::fflush(stdout);
  MemoryMetrics metrics;

  TestWritableAndReadOnly(&metrics);
  TestMappingAndRegionLifetime(&metrics);
  TestRangesAndCapabilities(&metrics);
  TestConcurrentThreads(&metrics);
  metrics.Sample();

  Require(metrics.initial_heap_bytes > 0,
          "initial_heap_bytes_invalid");
  Require(metrics.peak_heap_bytes >= metrics.initial_heap_bytes &&
              metrics.peak_heap_bytes <= metrics.max_heap_bytes,
          "peak_heap_bytes_invalid");
  Require(metrics.max_heap_bytes == kExpectedMaximumMemory,
          "max_heap_bytes_changed");

  std::fprintf(stdout, "%s:RUNTIME_END\n", kPrefix);
  std::fprintf(
      stdout,
      "%s:METRICS initial_heap_bytes=%" PRIu64
      " peak_heap_bytes=%" PRIu64 " max_heap_bytes=%" PRIu64 "\n",
      kPrefix, metrics.initial_heap_bytes, metrics.peak_heap_bytes,
      metrics.max_heap_bytes);
  std::fprintf(
      stdout,
      "%s:RESULT capability_handle=ok writable_create=ok writable_map=ok "
      "byte_round_trip=ok handle_move=ok serialization_round_trip=ok "
      "mapping_outlives_handle=ok writable_to_read_only=ok "
      "read_only_create=ok read_only_duplicate=ok "
      "read_only_write_rejected=ok mode_mismatch_rejected=ok "
      "writable_duplicate_rejected=ok invalid_capability_rejected=ok "
      "stale_capability_rejected=ok corrupt_metadata_rejected=ok "
      "corrupt_rights_rejected=ok "
      "unsafe_create=ok unsafe_duplicate=ok partial_map=ok "
      "invalid_range_rejected=ok zero_size_rejected=ok "
      "minimum_alignment=32 vm_alignment=65536 guid_identity=ok "
      "region_lifetime=ok concurrent_threads=ok "
      "concurrent_overlap=ok "
      "worker_threads_created=1 worker_threads_joined=1 "
      "worker_creation_failures=0 max_concurrent_test_threads=2 "
      "clean_shutdown=ok memory_metrics=ok "
      "browser_heartbeat=external\n",
      kPrefix);
  std::fprintf(stdout, "%s:PASS\n", kPrefix);
  std::fflush(stdout);
  return 0;
}
