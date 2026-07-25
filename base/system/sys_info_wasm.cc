// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/system/sys_info.h"

#include <algorithm>
#include <optional>
#include <string>

#include <emscripten/heap.h>
#include <emscripten/html5.h>
#include <emscripten/threading.h>
#include <emscripten/version.h>

#include "base/byte_size.h"
#include "base/time/time.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "sys_info_wasm.cc must only be built for WebAssembly"
#endif

#define BASE_WASM_STRINGIFY_INNER(value) #value
#define BASE_WASM_STRINGIFY(value) BASE_WASM_STRINGIFY_INNER(value)

namespace base {

// static
int SysInfo::NumberOfProcessors() {
  return std::max(1, emscripten_num_logical_cores());
}

#if defined(BASE_WASM_FULL_COMPONENT)
// static
int SysInfo::NumberOfEfficientProcessorsImpl() {
  return 0;
}

// static
ByteSize SysInfo::AmountOfTotalPhysicalMemoryImpl() {
  // Browsers do not expose host physical RAM. Use the configured linear-memory
  // ceiling as the in-process capacity from which Chromium derives budgets.
  return ByteSize(CHROMIUM_WASM_MAXIMUM_MEMORY_BYTES);
}

// static
ByteSize SysInfo::AmountOfAvailablePhysicalMemoryImpl() {
  // This is remaining linear-memory capacity, not host available RAM.
  const uint64_t committed = emscripten_get_heap_size();
  constexpr uint64_t maximum = CHROMIUM_WASM_MAXIMUM_MEMORY_BYTES;
  return ByteSize(committed < maximum ? maximum - committed : 0);
}

// static
SysInfo::HardwareInfo SysInfo::GetHardwareInfoSync() {
  return HardwareInfo();
}
#else
// static
ByteSize SysInfo::AmountOfTotalPhysicalMemory() {
  // Browsers do not expose host physical RAM to a Wasm module.
  return ByteSize();
}

// static
ByteSize SysInfo::AmountOfAvailablePhysicalMemory() {
  // Browsers do not expose host available RAM to a Wasm module.
  return ByteSize();
}
#endif

// static
ByteSize SysInfo::AmountOfVirtualMemory() {
  // This is the configured maximum of this module's WebAssembly.Memory, not
  // host physical memory or the amount currently committed.
  return ByteSize(emscripten_get_heap_max());
}

// static
std::optional<int64_t> SysInfo::AmountOfFreeDiskSpace(const FilePath&) {
  // MEMFS does not expose a real capacity and OPFS quota is not mounted in M1.
  return std::nullopt;
}

// static
std::optional<int64_t> SysInfo::AmountOfTotalDiskSpace(const FilePath&) {
  // MEMFS does not expose a real capacity and OPFS quota is not mounted in M1.
  return std::nullopt;
}

// static
std::optional<SysInfo::DiskSpaceInfo> SysInfo::AmountOfDiskSpace(
    const FilePath&) {
  // Emscripten's statvfs values are synthetic and must not be reported as
  // persistent storage capacity.
  return std::nullopt;
}

#if !defined(BASE_WASM_FULL_COMPONENT)
// static
TimeDelta SysInfo::Uptime() {
  // performance.now() is monotonic and relative to this runtime's time origin;
  // it is not host operating-system uptime.
  return Milliseconds(emscripten_performance_now());
}
#endif

// static
std::string SysInfo::OperatingSystemName() {
  // Do not identify the browser host as Linux, macOS, or Windows.
  return "Emscripten";
}

// static
std::string SysInfo::OperatingSystemVersion() {
  return BASE_WASM_STRINGIFY(__EMSCRIPTEN_MAJOR__) "." BASE_WASM_STRINGIFY(
      __EMSCRIPTEN_MINOR__) "." BASE_WASM_STRINGIFY(__EMSCRIPTEN_TINY__);
}

// static
void SysInfo::OperatingSystemVersionNumbers(int32_t* major_version,
                                            int32_t* minor_version,
                                            int32_t* bugfix_version) {
  *major_version = __EMSCRIPTEN_MAJOR__;
  *minor_version = __EMSCRIPTEN_MINOR__;
  *bugfix_version = __EMSCRIPTEN_TINY__;
}

// static
std::string SysInfo::OperatingSystemArchitecture() {
  return "wasm32";
}

#if !defined(BASE_WASM_FULL_COMPONENT)
// static
std::string SysInfo::ProcessCPUArchitecture() {
  return "wasm32";
}
#endif

// static
std::string SysInfo::CPUModelName() {
  // The host CPU model is intentionally not exposed to the module.
  return std::string();
}

// static
size_t SysInfo::VMAllocationGranularity() {
  static_assert(WASM_PAGE_SIZE == 65536);
  return WASM_PAGE_SIZE;
}

}  // namespace base

#undef BASE_WASM_STRINGIFY
#undef BASE_WASM_STRINGIFY_INNER
