// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/process/launch.h"

#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "launch_wasm.cc must only be built for WebAssembly"
#endif

namespace base {

Process LaunchProcess(const CommandLine& /*cmdline*/,
                      const LaunchOptions& /*options*/) {
  // Chromium services run in-process on threads. Never interpret a command
  // line as permission to create a host browser or worker process.
  return Process();
}

bool GetAppOutput(const CommandLine& /*cl*/, std::string* output) {
  if (output) {
    output->clear();
  }
  return false;
}

bool GetAppOutputAndError(const CommandLine& /*cl*/, std::string* output) {
  if (output) {
    output->clear();
  }
  return false;
}

bool GetAppOutputWithExitCode(const CommandLine& /*cl*/,
                              std::string* output,
                              int* exit_code) {
  if (output) {
    output->clear();
  }
  if (exit_code) {
    *exit_code = -1;
  }
  return false;
}

void RaiseProcessToHighPriority() {
  // Scheduling priority is controlled by the browser's worker runtime.
}

}  // namespace base
