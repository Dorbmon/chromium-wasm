// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <emscripten/heap.h>
#include <emscripten/threading.h>
#include <fcntl.h>
#include <unistd.h>

#include <algorithm>
#include <array>
#include <cerrno>
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
#include "mojo/public/c/system/platform_handle.h"
#include "mojo/public/cpp/platform/platform_handle.h"

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
constexpr size_t kPlatformRegionSize = 512;
constexpr size_t kPlatformFileSize = 96;
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

void TestPlatformSharedMemoryRegionRoundTrip() {
  BeginPhase("platform_shared_memory_region_round_trip");

  base::UnsafeSharedMemoryRegion source_region =
      base::UnsafeSharedMemoryRegion::Create(kPlatformRegionSize);
  Require(source_region.IsValid(), "platform_region_create");
  base::WritableSharedMemoryMapping source_mapping = source_region.Map();
  Require(source_mapping.IsValid() &&
              source_mapping.size() == kPlatformRegionSize,
          "platform_region_source_map");
  WritePattern(base::span(source_mapping), 0x53);

  const base::subtle::PlatformSharedMemoryHandle raw_handle =
      source_region.GetPlatformHandle();
  const base::UnguessableToken guid = source_region.GetGUID();
  base::subtle::PlatformSharedMemoryRegion platform_region =
      base::UnsafeSharedMemoryRegion::TakeHandleForSerialization(
          std::move(source_region));
  Require(!source_region.IsValid() && platform_region.IsValid() &&
              platform_region.GetMode() ==
                  base::subtle::PlatformSharedMemoryRegion::Mode::kUnsafe &&
              platform_region.GetSize() == kPlatformRegionSize,
          "platform_region_serialize");

  mojo::PlatformHandle outbound_handle(
      platform_region.PassPlatformHandle());
  Require(!platform_region.IsValid() &&
              outbound_handle.is_wasm_shared_memory(),
          "platform_region_platform_handle");
  MojoPlatformHandle outbound_transport{};
  mojo::PlatformHandle::ToMojoPlatformHandle(
      std::move(outbound_handle), &outbound_transport);
  Require(outbound_transport.type ==
                  MOJO_PLATFORM_HANDLE_TYPE_WASM_SHARED_MEMORY &&
              outbound_transport.value != 0,
          "platform_region_transport_export");
  const uint64_t outbound_token = outbound_transport.value;

  MojoSharedBufferGuid outbound_guid{
      .high = guid.GetHighForSerialization(),
      .low = guid.GetLowForSerialization(),
  };
  MojoHandle wrapped_region = MOJO_HANDLE_INVALID;
  Require(MojoWrapPlatformSharedMemoryRegion(
              &outbound_transport, 1, kPlatformRegionSize, &outbound_guid,
              MOJO_PLATFORM_SHARED_MEMORY_REGION_ACCESS_MODE_UNSAFE, nullptr,
              &wrapped_region) == MOJO_RESULT_OK &&
              wrapped_region != MOJO_HANDLE_INVALID &&
              !base::subtle::wasm::ImportHandleForTransport(outbound_token)
                   .is_valid() &&
              base::subtle::wasm::IsHandleValid(raw_handle),
          "platform_region_wrap");

  MojoHandle failed_unwrap_duplicate = MOJO_HANDLE_INVALID;
  Require(MojoDuplicateBufferHandle(wrapped_region, nullptr,
                                    &failed_unwrap_duplicate) ==
                  MOJO_RESULT_OK &&
              failed_unwrap_duplicate != MOJO_HANDLE_INVALID,
          "platform_region_failed_unwrap_duplicate");
  MojoPlatformHandle rejected_transport{
      .struct_size = sizeof(rejected_transport),
      .type = MOJO_PLATFORM_HANDLE_TYPE_INVALID,
      .value = 0,
  };
  uint32_t rejected_handle_count = 0;
  uint64_t rejected_size = 0;
  MojoSharedBufferGuid rejected_guid{};
  MojoPlatformSharedMemoryRegionAccessMode rejected_mode =
      MOJO_PLATFORM_SHARED_MEMORY_REGION_ACCESS_MODE_READ_ONLY;
  MojoSharedBufferInfo preserved_info{.struct_size = sizeof(preserved_info)};
  Require(MojoUnwrapPlatformSharedMemoryRegion(
              failed_unwrap_duplicate, nullptr, &rejected_transport,
              &rejected_handle_count, &rejected_size, &rejected_guid,
              &rejected_mode) == MOJO_RESULT_INVALID_ARGUMENT &&
              MojoGetBufferInfo(wrapped_region, nullptr, &preserved_info) ==
                  MOJO_RESULT_OK &&
              preserved_info.size == kPlatformRegionSize,
          "platform_region_unwrap_failure_closes");
  failed_unwrap_duplicate = MOJO_HANDLE_INVALID;

  MojoSharedBufferInfo wrapped_info{.struct_size = sizeof(wrapped_info)};
  void* wrapped_address = nullptr;
  Require(MojoGetBufferInfo(wrapped_region, nullptr, &wrapped_info) ==
                  MOJO_RESULT_OK &&
              wrapped_info.size == kPlatformRegionSize &&
              MojoMapBuffer(wrapped_region, 0, kPlatformRegionSize, nullptr,
                            &wrapped_address) == MOJO_RESULT_OK &&
              wrapped_address,
          "platform_region_wrapped_map");
  base::span<uint8_t> wrapped_bytes(
      static_cast<uint8_t*>(wrapped_address), kPlatformRegionSize);
  Require(HasPattern(wrapped_bytes, 0x53),
          "platform_region_wrapped_pattern");
  WritePattern(wrapped_bytes, 0x75);
  Require(HasPattern(base::span(source_mapping), 0x75) &&
              MojoUnmapBuffer(wrapped_address) == MOJO_RESULT_OK,
          "platform_region_wrapped_alias");

  MojoPlatformHandle inbound_transport{
      .struct_size = sizeof(inbound_transport),
      .type = MOJO_PLATFORM_HANDLE_TYPE_INVALID,
      .value = 0,
  };
  uint32_t inbound_handle_count = 1;
  uint64_t inbound_size = 0;
  MojoSharedBufferGuid inbound_guid{};
  MojoPlatformSharedMemoryRegionAccessMode inbound_mode =
      MOJO_PLATFORM_SHARED_MEMORY_REGION_ACCESS_MODE_READ_ONLY;
  Require(MojoUnwrapPlatformSharedMemoryRegion(
              wrapped_region, nullptr, &inbound_transport,
              &inbound_handle_count, &inbound_size, &inbound_guid,
              &inbound_mode) == MOJO_RESULT_OK,
          "platform_region_unwrap");
  wrapped_region = MOJO_HANDLE_INVALID;
  Require(inbound_handle_count == 1 &&
              inbound_transport.type ==
                  MOJO_PLATFORM_HANDLE_TYPE_WASM_SHARED_MEMORY &&
              inbound_transport.value != 0 &&
              inbound_size == kPlatformRegionSize &&
              inbound_guid.high == guid.GetHighForSerialization() &&
              inbound_guid.low == guid.GetLowForSerialization() &&
              inbound_mode ==
                  MOJO_PLATFORM_SHARED_MEMORY_REGION_ACCESS_MODE_UNSAFE,
          "platform_region_metadata");

  const uint64_t inbound_token = inbound_transport.value;
  mojo::PlatformHandle inbound_handle =
      mojo::PlatformHandle::FromMojoPlatformHandle(&inbound_transport);
  Require(inbound_handle.is_wasm_shared_memory() &&
              !base::subtle::wasm::ImportHandleForTransport(inbound_token)
                   .is_valid(),
          "platform_region_transport_replay");

  base::WritableSharedMemoryMapping restored_mapping;
  {
    auto restored_platform_region =
        base::subtle::PlatformSharedMemoryRegion::TakeOrFail(
            inbound_handle.TakeSharedMemoryHandle(),
            base::subtle::PlatformSharedMemoryRegion::Mode::kUnsafe,
            inbound_size, guid);
    Require(restored_platform_region.has_value() &&
                restored_platform_region->IsValid(),
            "platform_region_restore_metadata");
    base::UnsafeSharedMemoryRegion restored_region =
        base::UnsafeSharedMemoryRegion::Deserialize(
            std::move(*restored_platform_region));
    Require(restored_region.IsValid() &&
                base::subtle::wasm::IsHandleValid(raw_handle),
            "platform_region_restore");
    restored_mapping = restored_region.Map();
    Require(restored_mapping.IsValid() &&
                HasPattern(base::span(restored_mapping), 0x75),
            "platform_region_restored_map");
    WritePattern(base::span(restored_mapping), 0x97);
    Require(HasPattern(base::span(source_mapping), 0x97),
            "platform_region_restored_alias");
  }

  Require(!base::subtle::wasm::IsHandleValid(raw_handle) &&
              source_mapping.IsValid() && restored_mapping.IsValid() &&
              HasPattern(base::span(source_mapping), 0x97) &&
              HasPattern(base::span(restored_mapping), 0x97),
          "platform_region_single_owner");
}

void TestPlatformFileRoundTrip() {
  BeginPhase("platform_file_round_trip");

  MojoPlatformHandle oversized_file{
      .struct_size = sizeof(oversized_file),
      .type = MOJO_PLATFORM_HANDLE_TYPE_FILE_DESCRIPTOR,
      .value =
          static_cast<uint64_t>(std::numeric_limits<int>::max()) + 1,
  };
  MojoHandle rejected_file = MOJO_HANDLE_INVALID;
  Require(MojoWrapPlatformHandle(&oversized_file, nullptr, &rejected_file) ==
                  MOJO_RESULT_INVALID_ARGUMENT &&
              rejected_file == MOJO_HANDLE_INVALID,
          "platform_file_oversized_descriptor");

  constexpr char kPath[] = "/tmp/chromium_wasm_mojo_platform_file";
  std::ignore = unlink(kPath);
  int file_descriptor =
      open(kPath, O_CREAT | O_EXCL | O_RDWR, 0600);
  Require(file_descriptor >= 0, "platform_file_create");

  std::array<uint8_t, kPlatformFileSize> expected{};
  WritePattern(base::span(expected), 0x6b);
  Require(write(file_descriptor, expected.data(), expected.size()) ==
                  static_cast<ssize_t>(expected.size()) &&
              lseek(file_descriptor, 0, SEEK_SET) == 0,
          "platform_file_prepare");

  const int close_test_descriptor = dup(file_descriptor);
  Require(close_test_descriptor >= 0, "platform_file_close_test_duplicate");
  MojoPlatformHandle close_test_file{
      .struct_size = sizeof(close_test_file),
      .type = MOJO_PLATFORM_HANDLE_TYPE_FILE_DESCRIPTOR,
      .value = static_cast<uint64_t>(close_test_descriptor),
  };
  MojoHandle close_test_wrapper = MOJO_HANDLE_INVALID;
  Require(MojoWrapPlatformHandle(&close_test_file, nullptr,
                                 &close_test_wrapper) == MOJO_RESULT_OK &&
              close_test_wrapper != MOJO_HANDLE_INVALID &&
              MojoClose(close_test_wrapper) == MOJO_RESULT_OK,
          "platform_file_close_adopted");
  errno = 0;
  Require(fcntl(close_test_descriptor, F_GETFD) == -1 && errno == EBADF,
          "platform_file_close_retained_descriptor");

  const int clone_source_descriptor = dup(file_descriptor);
  Require(clone_source_descriptor >= 0,
          "platform_file_clone_source_duplicate");
  mojo::PlatformHandle original_file{
      base::ScopedFD(clone_source_descriptor)};
  mojo::PlatformHandle cloned_file = original_file.Clone();
  Require(original_file.is_valid() && cloned_file.is_valid() &&
              original_file.GetFD().get() == clone_source_descriptor &&
              cloned_file.GetFD().get() != clone_source_descriptor,
          "platform_file_clone");
  const int cloned_descriptor = cloned_file.GetFD().get();
  original_file.reset();
  errno = 0;
  Require(fcntl(clone_source_descriptor, F_GETFD) == -1 && errno == EBADF &&
              lseek(cloned_descriptor, 0, SEEK_SET) == 0,
          "platform_file_clone_independent_owner");
  std::array<uint8_t, kPlatformFileSize> cloned_actual{};
  Require(read(cloned_descriptor, cloned_actual.data(),
               cloned_actual.size()) ==
                  static_cast<ssize_t>(cloned_actual.size()) &&
              cloned_actual == expected,
          "platform_file_clone_read");
  cloned_file.reset();
  errno = 0;
  Require(fcntl(cloned_descriptor, F_GETFD) == -1 && errno == EBADF &&
              lseek(file_descriptor, 0, SEEK_SET) == 0,
          "platform_file_clone_close");

  MojoPlatformHandle outbound_file{
      .struct_size = sizeof(outbound_file),
      .type = MOJO_PLATFORM_HANDLE_TYPE_FILE_DESCRIPTOR,
      .value = static_cast<uint64_t>(file_descriptor),
  };
  MojoHandle wrapped_file = MOJO_HANDLE_INVALID;
  Require(MojoWrapPlatformHandle(&outbound_file, nullptr, &wrapped_file) ==
                  MOJO_RESULT_OK &&
              wrapped_file != MOJO_HANDLE_INVALID,
          "platform_file_wrap");
  file_descriptor = -1;

  MojoHandle sender = MOJO_HANDLE_INVALID;
  MojoHandle receiver = MOJO_HANDLE_INVALID;
  Require(MojoCreateMessagePipe(nullptr, &sender, &receiver) ==
                  MOJO_RESULT_OK &&
              sender != MOJO_HANDLE_INVALID &&
              receiver != MOJO_HANDLE_INVALID,
          "platform_file_pipe_create");

  MojoMessageHandle outgoing = MOJO_MESSAGE_HANDLE_INVALID;
  Require(MojoCreateMessage(nullptr, &outgoing) == MOJO_RESULT_OK &&
              outgoing != MOJO_MESSAGE_HANDLE_INVALID,
          "platform_file_message_create");
  MojoAppendMessageDataOptions append_options{
      .struct_size = sizeof(append_options),
      .flags = MOJO_APPEND_MESSAGE_DATA_FLAG_COMMIT_SIZE,
  };
  void* outgoing_payload = nullptr;
  uint32_t outgoing_capacity = 0;
  Require(MojoAppendMessageData(
              outgoing, 1, &wrapped_file, 1, &append_options,
              &outgoing_payload, &outgoing_capacity) == MOJO_RESULT_OK &&
              outgoing_payload && outgoing_capacity >= 1,
          "platform_file_attach");
  wrapped_file = MOJO_HANDLE_INVALID;
  *static_cast<uint8_t*>(outgoing_payload) = 0xa7;
  Require(MojoWriteMessage(sender, outgoing, nullptr) == MOJO_RESULT_OK,
          "platform_file_send");
  outgoing = MOJO_MESSAGE_HANDLE_INVALID;

  MojoMessageHandle incoming = MOJO_MESSAGE_HANDLE_INVALID;
  Require(MojoReadMessage(receiver, nullptr, &incoming) == MOJO_RESULT_OK &&
              incoming != MOJO_MESSAGE_HANDLE_INVALID,
          "platform_file_receive");
  void* incoming_payload = nullptr;
  uint32_t incoming_size = 0;
  MojoHandle received_file = MOJO_HANDLE_INVALID;
  uint32_t incoming_handle_count = 1;
  Require(MojoGetMessageData(
              incoming, nullptr, &incoming_payload, &incoming_size,
              &received_file, &incoming_handle_count) == MOJO_RESULT_OK &&
              incoming_payload && incoming_size == 1 &&
              *static_cast<uint8_t*>(incoming_payload) == 0xa7 &&
              incoming_handle_count == 1 &&
              received_file != MOJO_HANDLE_INVALID &&
              MojoDestroyMessage(incoming) == MOJO_RESULT_OK,
          "platform_file_extract");
  incoming = MOJO_MESSAGE_HANDLE_INVALID;

  MojoPlatformHandle inbound_file{
      .struct_size = sizeof(inbound_file),
      .type = MOJO_PLATFORM_HANDLE_TYPE_INVALID,
      .value = 0,
  };
  Require(MojoUnwrapPlatformHandle(received_file, nullptr, &inbound_file) ==
                  MOJO_RESULT_OK &&
              inbound_file.type ==
                  MOJO_PLATFORM_HANDLE_TYPE_FILE_DESCRIPTOR &&
              inbound_file.value <=
                  static_cast<uint64_t>(std::numeric_limits<int>::max()),
          "platform_file_unwrap");
  received_file = MOJO_HANDLE_INVALID;

  file_descriptor = static_cast<int>(inbound_file.value);
  std::array<uint8_t, kPlatformFileSize> actual{};
  Require(read(file_descriptor, actual.data(), actual.size()) ==
                  static_cast<ssize_t>(actual.size()) &&
              actual == expected,
          "platform_file_read");
  Require(close(file_descriptor) == 0 && unlink(kPath) == 0 &&
              MojoClose(sender) == MOJO_RESULT_OK &&
              MojoClose(receiver) == MOJO_RESULT_OK,
          "platform_file_cleanup");
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

  base::UnsafeSharedMemoryRegion generic_region =
      base::UnsafeSharedMemoryRegion::Create(64);
  Require(generic_region.IsValid(), "generic_shared_memory_region_create");
  auto generic_platform_region =
      base::UnsafeSharedMemoryRegion::TakeHandleForSerialization(
          std::move(generic_region));
  MojoPlatformHandle platform_handle{};
  mojo::PlatformHandle::ToMojoPlatformHandle(
      mojo::PlatformHandle(generic_platform_region.PassPlatformHandle()),
      &platform_handle);
  Require(platform_handle.type ==
                  MOJO_PLATFORM_HANDLE_TYPE_WASM_SHARED_MEMORY &&
              platform_handle.value != 0,
          "generic_shared_memory_handle_export");
  MojoHandle wrapped_platform_handle = MOJO_HANDLE_INVALID;
  Require(MojoWrapPlatformHandle(&platform_handle, nullptr,
                                 &wrapped_platform_handle) ==
                  MOJO_RESULT_UNIMPLEMENTED &&
              wrapped_platform_handle == MOJO_HANDLE_INVALID,
          "generic_shared_memory_handle_claimed_supported");

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
  TestPlatformSharedMemoryRegionRoundTrip();
  TestPlatformFileRoundTrip();
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
      "platform_region_wrap=ok platform_region_unwrap=ok "
      "platform_region_metadata=ok transport_token_one_shot=ok "
      "platform_region_aliasing=ok platform_region_single_owner=ok "
      "platform_region_unwrap_failure_closes=ok "
      "platform_file_wrap=ok platform_file_transfer=ok "
      "platform_file_unwrap=ok platform_file_read=ok "
      "remote_transport_rejected=ok driver_failures_rejected=ok "
      "mapping_outlives_handles=ok all_handles_closed=ok "
      "clean_shutdown=ok memory_metrics=ok browser_heartbeat=external\n",
      kPrefix);
  std::fprintf(stdout, "%s:PASS\n", kPrefix);
  std::fflush(stdout);
  return 0;
}
