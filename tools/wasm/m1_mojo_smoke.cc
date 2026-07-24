// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <emscripten/heap.h>
#include <emscripten/threading.h>

#include <algorithm>
#include <array>
#include <cinttypes>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <utility>

#include "base/containers/span.h"
#include "base/memory/platform_shared_memory_handle.h"
#include "base/memory/platform_shared_memory_region.h"
#include "base/memory/process_local_shared_memory_wasm.h"
#include "base/memory/unsafe_shared_memory_region.h"
#include "base/threading/platform_thread.h"
#include "base/time/time.h"
#include "build/build_config.h"
#include "mojo/core/embedder/embedder.h"
#include "mojo/core/ipcz_api.h"
#include "mojo/public/c/system/core.h"

#if !BUILDFLAG(IS_WASM)
#error "m1_mojo_smoke must be built for WebAssembly"
#endif

#if BUILDFLAG(IS_POSIX)
#error "WebAssembly must not inherit POSIX platform semantics"
#endif

namespace {

constexpr char kPrefix[] = "CHROMIUM_WASM_M1_MOJO";
constexpr size_t kBufferSize = 4096;
constexpr size_t kPayloadSize = 24;
constexpr uint64_t kExpectedMaximumMemory = UINT64_C(2147483648);
constexpr base::TimeDelta kResponsiveWindow = base::Milliseconds(300);

static_assert(sizeof(size_t) == 4);

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

struct MemoryMetrics {
  uint64_t initial_heap_bytes = emscripten_get_heap_size();
  uint64_t peak_heap_bytes = initial_heap_bytes;
  uint64_t max_heap_bytes = emscripten_get_heap_max();

  void Sample() {
    peak_heap_bytes =
        std::max<uint64_t>(peak_heap_bytes, emscripten_get_heap_size());
  }
};

void WritePattern(base::span<uint8_t> bytes, uint8_t seed) {
  for (size_t index = 0; index < bytes.size(); ++index) {
    bytes[index] =
        static_cast<uint8_t>(seed + (index * 37U) % 251U);
  }
}

bool HasPattern(base::span<const uint8_t> bytes, uint8_t seed) {
  for (size_t index = 0; index < bytes.size(); ++index) {
    const uint8_t expected =
        static_cast<uint8_t>(seed + (index * 37U) % 251U);
    if (bytes[index] != expected) {
      return false;
    }
  }
  return true;
}

void TestCapabilityValidation() {
  BeginPhase("capability_validation");

  base::subtle::PlatformSharedMemoryHandle stale;
  {
    base::UnsafeSharedMemoryRegion stale_region =
        base::UnsafeSharedMemoryRegion::Create(64);
    Require(stale_region.IsValid(), "stale_region_create");
    stale = stale_region.GetPlatformHandle();
    Require(base::subtle::wasm::IsHandleValid(stale),
            "stale_region_initially_invalid");
  }
  Require(!base::subtle::wasm::IsHandleValid(stale) &&
              !base::subtle::wasm::Map(stale, true, 0, 1).has_value(),
          "use_after_final_handle_close");

  base::UnsafeSharedMemoryRegion region =
      base::UnsafeSharedMemoryRegion::Create(128);
  Require(region.IsValid(), "metadata_region_create");

  base::subtle::PlatformSharedMemoryHandle forged =
      region.GetPlatformHandle();
  forged.region_id ^= UINT64_C(1) << 63;
  Require(forged.region_id != 0 &&
              !base::subtle::wasm::IsHandleValid(forged) &&
              !base::subtle::wasm::GetRegionMetadata(forged).has_value() &&
              !base::subtle::wasm::Map(forged, true, 0, 1).has_value(),
          "forged_region_id_accepted");

  base::UnsafeSharedMemoryRegion duplicate = region.Duplicate();
  Require(duplicate.IsValid(), "metadata_region_duplicate");
  base::subtle::PlatformSharedMemoryRegion platform =
      base::UnsafeSharedMemoryRegion::TakeHandleForSerialization(
          std::move(duplicate));
  const size_t size = platform.GetSize();
  const base::UnguessableToken guid = platform.GetGUID();
  auto corrupt_size = base::subtle::PlatformSharedMemoryRegion::TakeOrFail(
      platform.PassPlatformHandle(),
      base::subtle::PlatformSharedMemoryRegion::Mode::kUnsafe, size + 1,
      guid);
  Require(!corrupt_size.has_value() || !corrupt_size->IsValid(),
          "corrupt_metadata_accepted");
}

void TestDriverSharedMemoryFailures() {
  BeginPhase("driver_shared_memory_failures");

  const IpczDriver& driver = mojo::core::GetIpczDriverForMojo();
  IpczDriverHandle driver_memory = IPCZ_INVALID_DRIVER_HANDLE;
  Require(driver.AllocateSharedMemory(64, IPCZ_NO_FLAGS, nullptr, nullptr) ==
              IPCZ_RESULT_INVALID_ARGUMENT,
          "driver_null_output_accepted");
  Require(driver.AllocateSharedMemory(0, IPCZ_NO_FLAGS, nullptr,
                                      &driver_memory) ==
                  IPCZ_RESULT_INVALID_ARGUMENT &&
              driver_memory == IPCZ_INVALID_DRIVER_HANDLE,
          "driver_zero_allocation_accepted");
  Require(driver.AllocateSharedMemory(
              std::numeric_limits<size_t>::max(), IPCZ_NO_FLAGS, nullptr,
              &driver_memory) == IPCZ_RESULT_RESOURCE_EXHAUSTED &&
              driver_memory == IPCZ_INVALID_DRIVER_HANDLE,
          "driver_failed_allocation_reported_success");
  Require(driver.AllocateSharedMemory(64, IPCZ_NO_FLAGS, nullptr,
                                      &driver_memory) == IPCZ_RESULT_OK &&
              driver_memory != IPCZ_INVALID_DRIVER_HANDLE,
          "driver_allocation_failed");

  IpczDriverHandle driver_mapping = IPCZ_INVALID_DRIVER_HANDLE;
  Require(driver.MapSharedMemory(driver_memory, IPCZ_NO_FLAGS, nullptr,
                                 nullptr, &driver_mapping) ==
                  IPCZ_RESULT_INVALID_ARGUMENT &&
              driver_mapping == IPCZ_INVALID_DRIVER_HANDLE,
          "driver_null_mapping_address_accepted");
  Require(driver.Close(driver_memory, IPCZ_NO_FLAGS, nullptr) ==
              IPCZ_RESULT_OK,
          "driver_memory_close");
}

void TestMojoTransfer(MemoryMetrics* metrics) {
  BeginPhase("message_pipe_shared_buffer");

  MojoHandle sender = MOJO_HANDLE_INVALID;
  MojoHandle receiver = MOJO_HANDLE_INVALID;
  Require(MojoCreateMessagePipe(nullptr, &sender, &receiver) ==
              MOJO_RESULT_OK &&
              sender != MOJO_HANDLE_INVALID &&
              receiver != MOJO_HANDLE_INVALID,
          "message_pipe_create");

  MojoMessageHandle empty_message = MOJO_MESSAGE_HANDLE_INVALID;
  Require(MojoReadMessage(receiver, nullptr, &empty_message) ==
                  MOJO_RESULT_SHOULD_WAIT &&
              empty_message == MOJO_MESSAGE_HANDLE_INVALID,
          "empty_pipe_result");

  MojoHandle buffer = MOJO_HANDLE_INVALID;
  Require(MojoCreateSharedBuffer(kBufferSize, nullptr, &buffer) ==
                  MOJO_RESULT_OK &&
              buffer != MOJO_HANDLE_INVALID,
          "shared_buffer_create");

  MojoSharedBufferInfo info{.struct_size = sizeof(info)};
  Require(MojoGetBufferInfo(buffer, nullptr, &info) == MOJO_RESULT_OK &&
              info.size == kBufferSize,
          "shared_buffer_info");

  void* sender_address = nullptr;
  Require(MojoMapBuffer(buffer, 0, kBufferSize, nullptr,
                        &sender_address) == MOJO_RESULT_OK &&
              sender_address,
          "sender_map");
  base::span<uint8_t> sender_bytes(static_cast<uint8_t*>(sender_address),
                                   kBufferSize);
  WritePattern(sender_bytes, 0x29);

  MojoMessageHandle outgoing = MOJO_MESSAGE_HANDLE_INVALID;
  Require(MojoCreateMessage(nullptr, &outgoing) == MOJO_RESULT_OK &&
              outgoing != MOJO_MESSAGE_HANDLE_INVALID,
          "outgoing_message_create");
  MojoAppendMessageDataOptions append_options{
      .struct_size = sizeof(append_options),
      .flags = MOJO_APPEND_MESSAGE_DATA_FLAG_COMMIT_SIZE,
  };
  void* outgoing_payload = nullptr;
  uint32_t outgoing_capacity = 0;
  Require(MojoAppendMessageData(
              outgoing, kPayloadSize, &buffer, 1, &append_options,
              &outgoing_payload, &outgoing_capacity) == MOJO_RESULT_OK &&
              outgoing_payload && outgoing_capacity >= kPayloadSize,
          "shared_buffer_attach");
  buffer = MOJO_HANDLE_INVALID;

  std::array<uint8_t, kPayloadSize> expected_payload{};
  WritePattern(base::span(expected_payload), 0x41);
  std::memcpy(outgoing_payload, expected_payload.data(),
              expected_payload.size());
  Require(MojoWriteMessage(sender, outgoing, nullptr) == MOJO_RESULT_OK,
          "message_write");
  outgoing = MOJO_MESSAGE_HANDLE_INVALID;

  MojoMessageHandle incoming = MOJO_MESSAGE_HANDLE_INVALID;
  Require(MojoReadMessage(receiver, nullptr, &incoming) == MOJO_RESULT_OK &&
              incoming != MOJO_MESSAGE_HANDLE_INVALID,
          "message_read");

  void* incoming_payload = nullptr;
  uint32_t incoming_size = 0;
  uint32_t incoming_handle_count = 0;
  Require(MojoGetMessageData(incoming, nullptr, &incoming_payload,
                             &incoming_size, nullptr,
                             &incoming_handle_count) ==
                  MOJO_RESULT_RESOURCE_EXHAUSTED &&
              incoming_handle_count == 1,
          "message_handle_capacity");

  MojoHandle received_buffer = MOJO_HANDLE_INVALID;
  incoming_handle_count = 1;
  Require(MojoGetMessageData(
              incoming, nullptr, &incoming_payload, &incoming_size,
              &received_buffer, &incoming_handle_count) == MOJO_RESULT_OK &&
              incoming_payload && incoming_size == kPayloadSize &&
              incoming_handle_count == 1 &&
              received_buffer != MOJO_HANDLE_INVALID,
          "shared_buffer_extract");
  Require(std::memcmp(incoming_payload, expected_payload.data(),
                      expected_payload.size()) == 0,
          "payload_verification");
  Require(MojoDestroyMessage(incoming) == MOJO_RESULT_OK,
          "incoming_message_destroy");
  incoming = MOJO_MESSAGE_HANDLE_INVALID;

  void* receiver_address = nullptr;
  Require(MojoMapBuffer(received_buffer, 0, kBufferSize, nullptr,
                        &receiver_address) == MOJO_RESULT_OK &&
              receiver_address == sender_address,
          "receiver_map");
  base::span<uint8_t> receiver_bytes(
      static_cast<uint8_t*>(receiver_address), kBufferSize);
  Require(HasPattern(receiver_bytes, 0x29), "receiver_pattern");

  MojoHandle unsafe_duplicate = MOJO_HANDLE_INVALID;
  Require(MojoDuplicateBufferHandle(received_buffer, nullptr,
                                    &unsafe_duplicate) == MOJO_RESULT_OK &&
              unsafe_duplicate != MOJO_HANDLE_INVALID,
          "unsafe_duplicate");
  void* duplicate_address = nullptr;
  Require(MojoMapBuffer(unsafe_duplicate, 0, kBufferSize, nullptr,
                        &duplicate_address) == MOJO_RESULT_OK &&
              duplicate_address == sender_address,
          "unsafe_duplicate_map");

  constexpr size_t kModificationOffset = 113;
  constexpr uint8_t kModifiedValue = 0xE7;
  static_cast<uint8_t*>(duplicate_address)[kModificationOffset] =
      kModifiedValue;
  Require(receiver_bytes[kModificationOffset] == kModifiedValue &&
              sender_bytes[kModificationOffset] == kModifiedValue,
          "mapping_modification_not_shared");

  MojoDuplicateBufferHandleOptions read_only_options{
      .struct_size = sizeof(read_only_options),
      .flags = MOJO_DUPLICATE_BUFFER_HANDLE_FLAG_READ_ONLY,
  };
  MojoHandle rejected_read_only = MOJO_HANDLE_INVALID;
  Require(MojoDuplicateBufferHandle(received_buffer, &read_only_options,
                                    &rejected_read_only) ==
                  MOJO_RESULT_FAILED_PRECONDITION &&
              rejected_read_only == MOJO_HANDLE_INVALID,
          "read_only_after_unsafe_allowed");

  const uint64_t oversized =
      static_cast<uint64_t>(std::numeric_limits<size_t>::max()) + 1;
  void* invalid_mapping = nullptr;
  Require(MojoMapBuffer(received_buffer, 0, oversized, nullptr,
                        &invalid_mapping) == MOJO_RESULT_INVALID_ARGUMENT &&
              !invalid_mapping,
          "oversized_map_allowed");
  Require(MojoMapBuffer(received_buffer, kBufferSize - 1, 2, nullptr,
                        &invalid_mapping) == MOJO_RESULT_INVALID_ARGUMENT &&
              !invalid_mapping,
          "out_of_range_map_allowed");
  Require(MojoMapBuffer(received_buffer, 0, 0, nullptr,
                        &invalid_mapping) == MOJO_RESULT_INVALID_ARGUMENT &&
              !invalid_mapping,
          "zero_map_allowed");

  Require(MojoClose(received_buffer) == MOJO_RESULT_OK,
          "received_buffer_close");
  received_buffer = MOJO_HANDLE_INVALID;
  Require(MojoClose(unsafe_duplicate) == MOJO_RESULT_OK,
          "unsafe_duplicate_close");
  unsafe_duplicate = MOJO_HANDLE_INVALID;

  sender_bytes[kModificationOffset + 1] = 0x9B;
  Require(receiver_bytes[kModificationOffset + 1] == 0x9B &&
              static_cast<uint8_t*>(
                  duplicate_address)[kModificationOffset + 1] == 0x9B,
          "mapping_did_not_outlive_handles");

  Require(MojoUnmapBuffer(duplicate_address) == MOJO_RESULT_OK &&
              MojoUnmapBuffer(receiver_address) == MOJO_RESULT_OK &&
              MojoUnmapBuffer(sender_address) == MOJO_RESULT_OK &&
              MojoUnmapBuffer(sender_address) ==
                  MOJO_RESULT_INVALID_ARGUMENT,
          "duplicate_address_unmap_accounting");

  MojoHandle read_only_source = MOJO_HANDLE_INVALID;
  MojoHandle read_only_duplicate = MOJO_HANDLE_INVALID;
  Require(MojoCreateSharedBuffer(256, nullptr, &read_only_source) ==
                  MOJO_RESULT_OK &&
              MojoDuplicateBufferHandle(read_only_source, &read_only_options,
                                        &read_only_duplicate) ==
                  MOJO_RESULT_OK,
          "read_only_duplicate");
  MojoHandle rejected_unsafe = MOJO_HANDLE_INVALID;
  Require(MojoDuplicateBufferHandle(read_only_source, nullptr,
                                    &rejected_unsafe) ==
                  MOJO_RESULT_FAILED_PRECONDITION &&
              rejected_unsafe == MOJO_HANDLE_INVALID,
          "unsafe_after_read_only_allowed");
  Require(MojoClose(read_only_duplicate) == MOJO_RESULT_OK &&
              MojoClose(read_only_source) == MOJO_RESULT_OK,
          "read_only_handles_close");

  MojoHandle oversized_buffer = MOJO_HANDLE_INVALID;
  Require(MojoCreateSharedBuffer(oversized, nullptr, &oversized_buffer) ==
                  MOJO_RESULT_RESOURCE_EXHAUSTED &&
              oversized_buffer == MOJO_HANDLE_INVALID,
          "oversized_create_allowed");

  MojoPlatformHandle platform_handle{
      .struct_size = sizeof(platform_handle),
      .type = MOJO_PLATFORM_HANDLE_TYPE_INVALID,
      .value = 0,
  };
  MojoHandle wrapped_platform_handle = MOJO_HANDLE_INVALID;
  Require(MojoWrapPlatformHandle(&platform_handle, nullptr,
                                 &wrapped_platform_handle) ==
                  MOJO_RESULT_UNIMPLEMENTED &&
              wrapped_platform_handle == MOJO_HANDLE_INVALID,
          "platform_handle_claimed_supported");

  MojoInvitationTransportEndpoint remote_endpoint{
      .struct_size = sizeof(remote_endpoint),
      .type = MOJO_INVITATION_TRANSPORT_TYPE_CHANNEL,
  };
  MojoHandle remote_invitation = MOJO_HANDLE_INVALID;
  Require(MojoAcceptInvitation(&remote_endpoint, nullptr,
                               &remote_invitation) ==
                  MOJO_RESULT_UNIMPLEMENTED &&
              remote_invitation == MOJO_HANDLE_INVALID,
          "remote_transport_claimed_supported");

  Require(MojoClose(sender) == MOJO_RESULT_OK &&
              MojoClose(receiver) == MOJO_RESULT_OK,
          "message_pipe_close");
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

  std::fprintf(stdout, "%s:RUNTIME_START\n", kPrefix);
  std::fflush(stdout);
  MemoryMetrics metrics;

  mojo::core::Configuration configuration{
      .is_broker_process = true,
  };
  mojo::core::Init(configuration);
  Require(mojo::core::GetIpczNode() != IPCZ_INVALID_HANDLE,
          "ipcz_node_not_initialized");

  TestCapabilityValidation();
  TestDriverSharedMemoryFailures();
  TestMojoTransfer(&metrics);

  BeginPhase("browser_responsiveness");
  base::PlatformThread::Sleep(kResponsiveWindow);
  mojo::core::ShutDown();
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
      "%s:RESULT single_node=ok message_pipe_create=ok "
      "empty_pipe_should_wait=ok shared_buffer_create=ok sender_map=ok "
      "deterministic_write=ok shared_buffer_attach=ok message_write=ok "
      "message_read=ok shared_buffer_extract=ok receiver_map=ok "
      "payload_verified=ok unsafe_duplicate=ok duplicate_map=ok "
      "receiver_modify=ok sender_observed_modify=ok "
      "duplicate_unmap_accounting=ok invalid_region_rejected=ok "
      "use_after_final_close_rejected=ok oversized_create_rejected=ok "
      "oversized_map_rejected=ok readonly_after_unsafe_rejected=ok "
      "readonly_mode_mismatch_rejected=ok corrupt_metadata_rejected=ok "
      "remote_transport_rejected=ok driver_failures_rejected=ok "
      "mapping_outlives_handles=ok all_handles_closed=ok "
      "clean_shutdown=ok memory_metrics=ok browser_heartbeat=external\n",
      kPrefix);
  std::fprintf(stdout, "%s:PASS\n", kPrefix);
  std::fflush(stdout);
  return 0;
}
