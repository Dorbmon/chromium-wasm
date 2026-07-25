// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/process/process_metrics.h"

#include <sys/time.h>
#include <unistd.h>

#include <memory>

#include "base/process/process_handle.h"
#include "base/time/time.h"
#include "base/types/expected.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "process_metrics_wasm.cc must only be built for WebAssembly"
#endif

namespace base {

int64_t TimeValToMicroseconds(const struct timeval& value) {
  return static_cast<int64_t>(value.tv_sec) * Time::kMicrosecondsPerSecond +
         value.tv_usec;
}

size_t GetMaxFds() {
  const long open_max = sysconf(_SC_OPEN_MAX);
  return open_max > 0 ? static_cast<size_t>(open_max) : 256u;
}

size_t GetHandleLimit() {
  return GetMaxFds();
}

ProcessMetrics::ProcessMetrics(ProcessHandle process) : process_(process) {}

std::unique_ptr<ProcessMetrics> ProcessMetrics::CreateProcessMetrics(
    ProcessHandle process) {
  return std::unique_ptr<ProcessMetrics>(new ProcessMetrics(process));
}

base::expected<ProcessMemoryInfo, ProcessUsageError>
ProcessMetrics::GetMemoryInfo() const {
  if (process_ != GetCurrentProcessHandle()) {
    return unexpected(ProcessUsageError::kProcessNotFound);
  }
  // Linear-memory size is not host-resident memory. Do not publish it as RSS.
  return unexpected(ProcessUsageError::kSystemError);
}

base::expected<TimeDelta, ProcessCPUUsageError>
ProcessMetrics::GetCumulativeCPUUsage() {
  // Browsers do not expose per-WebAssembly-process CPU time.
  return unexpected(ProcessCPUUsageError::kSystemError);
}

size_t ProcessMetrics::GetMallocUsage() {
  // Emscripten exposes linear-memory size, but not a portable allocator usage
  // counter across its supported allocators.
  return 0;
}

size_t GetSystemCommitCharge() {
  // Browsers do not expose system-wide committed memory.
  return 0;
}

bool GetSystemMemoryInfo(SystemMemoryInfo* meminfo) {
  // Host-wide physical memory information is intentionally unavailable.
  return false;
}

ByteSize SystemMemoryInfo::GetAvailablePhysicalMemory() const {
  return ByteSize();
}

}  // namespace base
