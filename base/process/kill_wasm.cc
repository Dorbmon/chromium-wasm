// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/process/kill.h"

#include "base/check.h"
#include "base/process/process_iterator.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "kill_wasm.cc must only be built for WebAssembly"
#endif

namespace base {

TerminationStatus GetTerminationStatus(ProcessHandle handle, int* exit_code) {
  DCHECK(exit_code);
  *exit_code = -1;
  return handle == GetCurrentProcessHandle()
             ? TERMINATION_STATUS_STILL_RUNNING
             : TERMINATION_STATUS_LAUNCH_FAILED;
}

void EnsureProcessTerminated(Process process) {
  // LaunchProcess() never returns a valid child process in the single-process
  // Wasm model.
  CHECK(!process.IsValid())
      << "A child process cannot exist in the single-process Wasm runtime";
}

bool WaitForProcessesToExit(const FilePath::StringType& executable_name,
                            TimeDelta wait,
                            const ProcessFilter* filter) {
  // There is no process namespace to contain matching child processes.
  return true;
}

bool CleanupProcesses(const FilePath::StringType& executable_name,
                      TimeDelta wait,
                      int exit_code,
                      const ProcessFilter* filter) {
  // There is no process namespace to contain matching child processes.
  return true;
}

}  // namespace base
