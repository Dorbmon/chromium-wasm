// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/process/process_handle.h"

#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "process_handle_wasm.cc must only be built for WebAssembly"
#endif

namespace base {
namespace {

constexpr ProcessId kCurrentProcessId = 1;
constexpr ProcessHandle kCurrentProcessHandle = 1;

}  // namespace

ProcessId GetCurrentProcId() {
  return kCurrentProcessId;
}

ProcessHandle GetCurrentProcessHandle() {
  return kCurrentProcessHandle;
}

ProcessId GetProcId(ProcessHandle process) {
  return process == kCurrentProcessHandle ? kCurrentProcessId : kNullProcessId;
}

ProcessId GetParentProcessId(ProcessHandle process) {
  if (process == kCurrentProcessHandle) {
    // The Wasm module is the root of its process-local model.
    return kNullProcessId;
  }
  return static_cast<ProcessId>(-1);
}

}  // namespace base
