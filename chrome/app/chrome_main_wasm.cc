// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <optional>
#include <utility>

#include "base/command_line.h"
#include "base/no_destructor.h"
#include "base/sampling_heap_profiler/poisson_allocation_sampler.h"
#include "build/build_config.h"
#include "chrome/app/chrome_main.h"
#include "chrome/browser/wasm/wasm_chrome_main_delegate.h"
#include "chrome/common/chrome_result_codes.h"
#include "content/public/app/content_main.h"
#include "content/public/common/content_switches.h"

#if !BUILDFLAG(IS_WASM)
#error "chrome_main_wasm.cc must only be built for WebAssembly"
#endif

namespace {

std::optional<base::CommandLine>& GetInitialCommandLineStorage() {
  static base::NoDestructor<std::optional<base::CommandLine>>
      initial_command_line;
  return *initial_command_line;
}

}  // namespace

const base::CommandLine& GetInitialBrowserCommandLine() {
  return GetInitialCommandLineStorage().value();
}

extern "C" int ChromeMain(int argc, const char** argv) {
  WasmChromeMainDelegate chrome_main_delegate;
  content::ContentMainParams params(&chrome_main_delegate);
  params.argc = argc;
  params.argv = argv;

  base::CommandLine::Init(params.argc, params.argv);

  base::CommandLine* command_line = base::CommandLine::ForCurrentProcess();
  if (!command_line->HasSwitch(switches::kProcessType)) {
    GetInitialCommandLineStorage() = *command_line;
  }

  // Set up PartitionAlloc's sampling TLS before Content creates its thread
  // pool, matching Chrome's desktop entry point without selecting any native
  // headless, crash-handler, or process-launch integration.
  base::PoissonAllocationSampler::Init();

  const int result = content::ContentMain(std::move(params));
  if (IsNormalResultCode(static_cast<ResultCode>(result))) {
    return content::RESULT_CODE_NORMAL_EXIT;
  }
  return result;
}
