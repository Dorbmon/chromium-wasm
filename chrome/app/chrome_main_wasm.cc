// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <optional>
#include <stdio.h>
#include <utility>

#include "base/command_line.h"
#include "base/no_destructor.h"
#include "base/sampling_heap_profiler/poisson_allocation_sampler.h"
#include "build/build_config.h"
#include "chrome/app/chrome_main.h"
#include "chrome/browser/wasm/wasm_chrome_main_delegate.h"
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST)
// The dedicated M7 GN configuration alone supplies this header and target.
// GN's include checker does not evaluate this target-specific definition.
#include "chrome/browser/wasm/wasm_profile_preferences_smoke.h"  // nogncheck
#endif
#include "chrome/browser/wasm/wasm_profile_storage.h"
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

extern "C" int chromium_wasm_report_process_exit(int exit_code);

namespace {

std::optional<base::CommandLine>& GetInitialCommandLineStorage() {
  static base::NoDestructor<std::optional<base::CommandLine>>
      initial_command_line;
  return *initial_command_line;
}

bool IsNormalChromeMainResult(int result) {
  return result == content::RESULT_CODE_NORMAL_EXIT ||
         IsNormalResultCode(static_cast<ResultCode>(result));
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
constexpr char kWasmBrowserM9WispRecoverySmokeSwitch[] =
    "wasm-browser-m9-wisp-recovery-smoke";
#endif

}  // namespace

const base::CommandLine& GetInitialBrowserCommandLine() {
  return GetInitialCommandLineStorage().value();
}

extern "C" int ChromeMain(int argc, const char** argv) {
  int result = CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
  bool profile_storage_initialized = false;
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST)
  bool preferences_smoke_enabled = false;
#endif
  {
    WasmChromeMainDelegate chrome_main_delegate;
    content::ContentMainParams params(&chrome_main_delegate);
    params.argc = argc;
    params.argv = argv;

    base::CommandLine::Init(params.argc, params.argv);

    // The M7 two-module Preferences acceptance is compiled only into its
    // dedicated GN configuration. The primary chrome_wasm build neither
    // parses these private switches nor links the helper that owns their raw
    // tokens.
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST)
    const bool preferences_smoke_requested =
        chrome::HasWasmProfilePreferencesSmokeArguments();
    if (preferences_smoke_requested) {
      preferences_smoke_enabled =
          chrome::EnableWasmProfilePreferencesSmokeTestMode();
    }
#endif

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
            kWasmBrowserHostContinuousFlowRestartSmokeSwitch) ||
        controlled_test_command_line->HasSwitch(
            kWasmBrowserM9WispRecoverySmokeSwitch)) {
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

    // This must happen before Content's delegate can register or resolve the
    // /profile path. The leased backend has no in-memory or unleased fallback:
    // a missing Web Locks/OPFS/pthread capability is a startup failure.
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST)
    if (preferences_smoke_requested && !preferences_smoke_enabled) {
      // Invalid test input stops before the profile mount. The helper already
      // emitted its fixed redacted failure marker.
      result = CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
    } else if (!(profile_storage_initialized =
#else
    if (!(profile_storage_initialized =
#endif
                     chrome::InitializeWasmProfileStorage())) {
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST)
      chrome::ReportWasmProfilePreferencesSmokeFailure(
          chrome::WasmProfilePreferencesSmokeFailureStage::kStorage);
#endif
      // A failed mount can still have acquired a lease. Its scoped cleanup
      // runs after this delegate scope, while the non-normal result reaches
      // the host through chromium_wasm_report_process_exit below.
      result = CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
    } else {
      // Set up PartitionAlloc's sampling TLS before Content creates its thread
      // pool, matching Chrome's desktop entry point without selecting any
      // native headless, crash-handler, or process-launch integration.
      base::PoissonAllocationSampler::Init();

      result = content::ContentMain(std::move(params));
    }
  }

#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST)
  if (preferences_smoke_enabled &&
      !IsNormalChromeMainResult(result)) {
    chrome::ReportWasmProfilePreferencesSmokeFailure(
        chrome::WasmProfilePreferencesSmokeFailureStage::kContent);
  }
#endif

  // BrowserMainParts records the profile-service shutdown boundary. Seal and
  // drain the exact leased OPFS backend only after ContentMain and its
  // delegate have both returned, when no Content teardown can issue another
  // profile operation. A failed mount can also require this cleanup if
  // leased-backend construction succeeded before mounting failed.
  if (chrome::NeedsWasmProfileStorageBackendDrain()) {
    const chrome::WasmProfileStorageDrainResult drain_result =
        chrome::DrainAndReleaseWasmProfileStorageBackend();
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST)
    chrome::NotifyWasmProfilePreferencesSmokeBackendDrain(
        drain_result.Succeeded());
#endif
    if (!drain_result.Succeeded()) {
      // Before acknowledged Web Locks release, a drain failure has no safe
      // handoff. A post-release worker-retirement failure has already released
      // its lease and cannot be retried. Either outcome leaves a sealed backend
      // unavailable. Keep the structured result in the storage component and
      // communicate the failure through the existing process-exit bridge.
      if (IsNormalChromeMainResult(result)) {
        result = CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
      }
    }
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST)
  } else if (preferences_smoke_enabled) {
    chrome::NotifyWasmProfilePreferencesSmokeBackendDrain(false);
    if (IsNormalChromeMainResult(result)) {
      result = CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
    }
#endif
  }

  const int exit_code = IsNormalChromeMainResult(result)
                            ? content::RESULT_CODE_NORMAL_EXIT
                            : result;
  if (chromium_wasm_report_process_exit(exit_code) != 1) {
    // A scoped profile drain leaves standard error intact, unlike a
    // process-global filesystem teardown.
    fputs("CHROMIUM_WASM: host rejected process-exit report\n", stderr);
    return exit_code == 0 ? 1 : exit_code;
  }
  return exit_code;
}
