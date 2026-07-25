// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/memory/shared_memory_switch.h"

#include <string_view>

#include "base/check.h"
#include "base/types/expected.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "shared_memory_switch_wasm.cc must only be built for WebAssembly"
#endif

namespace base::shared_memory {

SharedMemorySwitch::SharedMemorySwitch(
    std::string_view switch_name_in,
    [[maybe_unused]] RendezvousKey rendezvous_key_in,
    [[maybe_unused]] DescriptorKey descriptor_key_in)
    : switch_name(switch_name_in) {}

SharedMemorySwitch::~SharedMemorySwitch() = default;
SharedMemorySwitch::SharedMemorySwitch(SharedMemorySwitch&&) = default;
SharedMemorySwitch& SharedMemorySwitch::operator=(SharedMemorySwitch&&) =
    default;

void SharedMemorySwitch::AddToLaunchParameters(
    const ReadOnlySharedMemoryRegion& read_only_memory_region,
    CommandLine* command_line,
    LaunchOptions* launch_options) {
  CHECK(false) << "Wasm cannot pass shared memory to a child process";
}

void SharedMemorySwitch::AddToLaunchParameters(
    const UnsafeSharedMemoryRegion& unsafe_memory_region,
    CommandLine* command_line,
    LaunchOptions* launch_options) {
  CHECK(false) << "Wasm cannot pass shared memory to a child process";
}

expected<UnsafeSharedMemoryRegion, SharedMemoryError>
UnsafeSharedMemoryRegionFrom(std::string_view switch_value) {
  return unexpected(SharedMemoryError::kUnsupportedPlatform);
}

expected<ReadOnlySharedMemoryRegion, SharedMemoryError>
ReadOnlySharedMemoryRegionFrom(std::string_view switch_value) {
  return unexpected(SharedMemoryError::kUnsupportedPlatform);
}

}  // namespace base::shared_memory
