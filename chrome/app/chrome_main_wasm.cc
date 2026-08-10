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

#if defined(CHROME_WASM_M6_CONTROLLED_HTTPS_TEST)
// Only the controlled M6 target supplies this header. GN's include checker
// does not evaluate the target-specific preprocessor definition.
#include "chrome/browser/wasm/wasm_m6_controlled_https_test_mode.h"  // nogncheck
#include "chrome/browser/wasm/wasm_m6_test_trust.h"  // nogncheck
#endif

#if !BUILDFLAG(IS_WASM)
#error "chrome_main_wasm.cc must only be built for WebAssembly"
#endif

namespace {

std::optional<base::CommandLine>& GetInitialCommandLineStorage() {
  static base::NoDestructor<std::optional<base::CommandLine>>
      initial_command_line;
  return *initial_command_line;
}

#if defined(CHROME_WASM_M6_CONTROLLED_HTTPS_TEST)
constexpr char kWasmBrowserControlledHttpsSmokeSwitch[] =
    "wasm-browser-controlled-https-smoke";
constexpr char kWasmBrowserHostHistoryDownloadsSmokeSwitch[] =
    "wasm-browser-host-history-downloads-smoke";
constexpr char kWasmBrowserHostContinuousFlowSmokeSwitch[] =
    "wasm-browser-host-continuous-flow-smoke";
constexpr char kWasmBrowserHostContinuousFlowRestartSmokeSwitch[] =
    "wasm-browser-host-continuous-flow-restart-smoke";
#endif

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

#if defined(CHROME_WASM_M6_CONTROLLED_HTTPS_TEST)
  const base::CommandLine* const controlled_test_command_line =
      base::CommandLine::ForCurrentProcess();
  if (controlled_test_command_line->HasSwitch(
          kWasmBrowserControlledHttpsSmokeSwitch) ||
      controlled_test_command_line->HasSwitch(
          kWasmBrowserHostHistoryDownloadsSmokeSwitch) ||
      controlled_test_command_line->HasSwitch(
          kWasmBrowserHostContinuousFlowSmokeSwitch) ||
      controlled_test_command_line->HasSwitch(
          kWasmBrowserHostContinuousFlowRestartSmokeSwitch)) {
    // Install only for dedicated controlled-HTTPS test routes, after Chrome
    // initialized its command line but before ContentMain can construct the
    // Network Service and its certificate verifier. The normal Wasm Chrome
    // target never calls this initializer, so a switch alone cannot add local
    // test trust to production.
    chrome::InstallWasmM6TestTrustRoot();
    chrome::EnableWasmM6ControlledHttpsTestMode();
  }
#endif

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
