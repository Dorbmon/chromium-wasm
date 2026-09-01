// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <cerrno>
#include <optional>
#include <stdio.h>
#include <utility>

#include "base/command_line.h"
#include "base/no_destructor.h"
#include "base/sampling_heap_profiler/poisson_allocation_sampler.h"
#include "build/build_config.h"
#include "chrome/app/chrome_main.h"
#include "chrome/browser/wasm/wasm_chrome_main_delegate.h"
#if !defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) && \
    !defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) && \
    !defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) && \
    !defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST) && \
    !defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE) && \
    !defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) && \
    !defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) && \
    !defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) && \
    !defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
// The normal source-selected configuration alone supplies this target. GN's
// include checker does not evaluate target-specific definitions.
#include "chrome/browser/wasm/wasm_profile_shutdown_failure_latch.h"  // nogncheck
#endif
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
// The dedicated M7 GN configuration alone supplies this header and target.
// GN's include checker does not evaluate this target-specific definition.
#include "chrome/browser/wasm/wasm_profile_preferences_smoke.h"  // nogncheck
#endif
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
// The dedicated M7 database GN configuration alone supplies this header and
// target. GN's include checker does not evaluate this target-specific
// definition.
#include "chrome/browser/wasm/wasm_profile_database_smoke.h"  // nogncheck
#endif
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
// The dedicated M7 LocalStorage GN configuration alone supplies this header
// and target. GN's include checker does not evaluate target-specific defines.
#include "chrome/browser/wasm/wasm_profile_local_storage_smoke.h"  // nogncheck
#endif
#if defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST)
// The standalone renderer IndexedDB acceptance alone owns this private
// protocol; ordinary chrome_wasm never parses its switches or links it.
#include "chrome/browser/wasm/wasm_profile_indexed_db_smoke.h"  // nogncheck
#endif
#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE)
// Only the dedicated configuration probe owns this private switch and marker
// protocol; normal chrome_wasm neither links it nor changes its policy.
#include "chrome/browser/wasm/wasm_profile_persistent_default_partition_policy_probe.h"  // nogncheck
#endif
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
// The experimental M7 GN configurations alone supply this header and target.
// GN's include checker does not evaluate target-specific definitions.
#include "chrome/browser/wasm/wasm_profile_storage.h"  // nogncheck
#endif
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

#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
constexpr char kWasmM7ProfileFailureRetirementMarker[] =
    "CHROMIUM_WASM_M7_PROFILE_FAILURE_RETIREMENT:SEALED_LEASE_RETAINED";

// The explicit WasmFS failure disposition intentionally returns ESHUTDOWN
// after local descriptor cleanup. It is neither a clean profile handoff nor a
// generic failed drain: the backend is sealed and its Web Lock and worker
// tombstone deliberately remain retained. Keep the browser-test receipt exact
// so it cannot be emitted for a pre-drain lifecycle refusal or an ordinary
// post-release retirement error.
bool IsWasmM7ProfileFailureRetirement(
    const chrome::WasmProfileStorageDrainResult& result) {
  return result.error == -ESHUTDOWN && result.libc_flush_failed == 0 &&
         result.data_flush_failures == 0 && result.data_close_failures == 0 &&
         result.prior_close_failures == 0 &&
         result.lease_release_failures == 0 &&
         result.backend_retire_failures == 0 && result.backend_sealed &&
         !result.lease_released && !result.backend_retired;
}
#endif

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_OUTSTANDING_IO_REFUSAL_TEST)
constexpr char kWasmM7ProfileOutstandingIORefusalMarker[] =
    "CHROMIUM_WASM_M7_PROFILE_DRAIN_REFUSED:OUTSTANDING_IO";

// EBUSY has other meanings in the storage adapter, including a duplicate drain
// attempt. The test receipt accepts only the explicit pre-outer-drain refusal
// for an admitted profile-I/O admission that has not reached terminal
// completion.
bool IsWasmM7ProfileOutstandingIORefusal(
    const chrome::WasmProfileStorageDrainResult& result) {
  return result.error == -EBUSY && result.refused_for_outstanding_profile_io &&
         result.detached_descriptors == 0 && result.data_file_states == 0 &&
         result.libc_flush_failed == 0 && result.data_flush_failures == 0 &&
         result.data_close_failures == 0 && result.prior_close_failures == 0 &&
         result.lease_release_failures == 0 &&
         result.backend_retire_failures == 0 && !result.backend_sealed &&
         !result.lease_released && !result.backend_retired;
}
#endif

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
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  bool preferences_smoke_enabled = false;
#endif
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  bool database_smoke_enabled = false;
#endif
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  bool local_storage_smoke_enabled = false;
#endif
#if defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST)
  bool indexed_db_smoke_enabled = false;
#endif
#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE)
  bool persistent_default_partition_policy_probe_enabled = false;
#endif
#if defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  bool aggregate_smoke_enabled = false;
#endif
  {
    WasmChromeMainDelegate chrome_main_delegate;
    content::ContentMainParams params(&chrome_main_delegate);
    params.argc = argc;
    params.argv = argv;

    base::CommandLine::Init(params.argc, params.argv);

#if !defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) && \
    !defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) && \
    !defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) && \
    !defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST) && \
    !defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE) && \
    !defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) && \
    !defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) && \
    !defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) && \
    !defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    // Browser-main parts may be destroyed before ContentMain returns. Reset
    // its per-run failure receipt before that lifecycle begins.
    chrome::ResetWasmProfileShutdownFailureLatch();
#endif

    // The M7 Preferences protocol is compiled only into its source-selected
    // GN configurations. The primary chrome_wasm build neither parses these
    // private switches nor links the helper that owns their raw tokens.
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    const bool preferences_smoke_requested =
        chrome::HasWasmProfilePreferencesSmokeArguments();
    if (preferences_smoke_requested) {
      preferences_smoke_enabled =
          chrome::EnableWasmProfilePreferencesSmokeTestMode();
    }
#endif
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    // The M7 three-module database acceptance is compiled only into its
    // dedicated GN configuration. Primary chrome_wasm neither parses these
    // private switches nor links the helper that owns their raw tokens.
    const bool database_smoke_requested =
        chrome::HasWasmProfileDatabaseSmokeArguments();
    if (database_smoke_requested) {
      database_smoke_enabled =
          chrome::EnableWasmProfileDatabaseSmokeTestMode();
    }
#endif
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    // The default-partition LocalStorage receipt is source-selected into its
    // own executable. Normal chrome_wasm never parses these private switches
    // and cannot select the narrow persistent LocalStorage path.
    const bool local_storage_smoke_requested =
        chrome::HasWasmProfileLocalStorageSmokeArguments();
    if (local_storage_smoke_requested) {
      local_storage_smoke_enabled =
          chrome::EnableWasmProfileLocalStorageSmokeTestMode();
    }
#endif
#if defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST)
    // This dedicated artifact recognizes only its renderer-owned protocol.
    // The tokens remain in Chromium and are never forwarded to the outer host.
    const bool indexed_db_smoke_requested =
        chrome::HasWasmProfileIndexedDBSmokeArguments();
    if (indexed_db_smoke_requested) {
      indexed_db_smoke_enabled =
          chrome::EnableWasmProfileIndexedDBSmokeTestMode();
    }
#endif
#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE)
    // This private switch selects a configuration-only default-partition
    // policy witness. It never enables a StoragePartition service path.
    const bool persistent_default_partition_policy_probe_requested =
        chrome::HasWasmPersistentDefaultPartitionPolicyProbeArguments();
    if (persistent_default_partition_policy_probe_requested) {
      persistent_default_partition_policy_probe_enabled =
          chrome::EnableWasmPersistentDefaultPartitionPolicyProbe();
    }
#endif

#if defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    // Validate all three redacted phase identities before mounting. Runtime
    // ownership still starts Database only after renderer LocalStorage closes.
    if (preferences_smoke_enabled && database_smoke_enabled &&
        local_storage_smoke_enabled) {
      const chrome::WasmProfilePreferencesSmokeMode preferences_mode =
          chrome::GetWasmProfilePreferencesSmokeMode();
      const chrome::WasmProfileLocalStorageSmokeInput::Mode local_storage_mode =
          chrome::GetWasmProfileLocalStorageSmokeMode();
      const chrome::WasmProfileDatabaseSmokeMode database_mode =
          chrome::GetWasmProfileDatabaseSmokeMode();
      const bool all_phases_match =
          (preferences_mode ==
               chrome::WasmProfilePreferencesSmokeMode::kWrite &&
           local_storage_mode ==
               chrome::WasmProfileLocalStorageSmokeInput::Mode::
                   kRendererWrite &&
           database_mode == chrome::WasmProfileDatabaseSmokeMode::kWriteA) ||
          (preferences_mode ==
               chrome::WasmProfilePreferencesSmokeMode::kVerifyAndWrite &&
           local_storage_mode ==
               chrome::WasmProfileLocalStorageSmokeInput::Mode::
                   kRendererVerify &&
           database_mode ==
               chrome::WasmProfileDatabaseSmokeMode::kVerifyAWriteB) ||
          (preferences_mode ==
               chrome::WasmProfilePreferencesSmokeMode::kVerifyB &&
           local_storage_mode ==
               chrome::WasmProfileLocalStorageSmokeInput::Mode::
                   kRendererVerify &&
           database_mode == chrome::WasmProfileDatabaseSmokeMode::kVerifyB);
      aggregate_smoke_enabled =
          all_phases_match &&
          chrome::IsWasmProfilePreferencesBrowserSmokeEnabled() &&
          chrome::IsWasmProfilePreferencesBookmarkSmokeEnabled() &&
          chrome::IsWasmProfilePreferencesCookieSmokeEnabled() &&
          chrome::IsWasmProfilePreferencesHistorySmokeEnabled() &&
          chrome::IsWasmProfileRendererLocalStorageSmokeEnabled() &&
          chrome::IsWasmProfileDatabaseSmokeEnabled();
    }
    if (!aggregate_smoke_enabled) {
      chrome::ReportWasmProfilePreferencesSmokeFailure(
          chrome::WasmProfilePreferencesSmokeFailureStage::kArguments);
      chrome::ReportWasmProfileDatabaseSmokeFailure(
          chrome::WasmProfileDatabaseSmokeFailureStage::kArguments);
      chrome::ReportWasmProfileLocalStorageSmokeFailure(
          chrome::WasmProfileLocalStorageSmokeFailureStage::kArguments);
    }
#elif defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST)
    // Preserve the published aggregate phase/owner contract independently of
    // the distinct five-store capability.
    if (preferences_smoke_enabled && local_storage_smoke_enabled) {
      const chrome::WasmProfilePreferencesSmokeMode preferences_mode =
          chrome::GetWasmProfilePreferencesSmokeMode();
      const chrome::WasmProfileLocalStorageSmokeInput::Mode local_storage_mode =
          chrome::GetWasmProfileLocalStorageSmokeMode();
      const bool phases_match =
          (preferences_mode ==
               chrome::WasmProfilePreferencesSmokeMode::kWrite &&
           local_storage_mode ==
               chrome::WasmProfileLocalStorageSmokeInput::Mode::
                   kRendererWrite) ||
          (preferences_mode ==
               chrome::WasmProfilePreferencesSmokeMode::kVerifyAndWrite &&
           local_storage_mode ==
               chrome::WasmProfileLocalStorageSmokeInput::Mode::
                   kRendererVerify)
#if defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST)
          ||
          (preferences_mode ==
               chrome::WasmProfilePreferencesSmokeMode::kVerifyB &&
           local_storage_mode ==
               chrome::WasmProfileLocalStorageSmokeInput::Mode::
                   kRendererVerify)
#endif
          ;
      aggregate_smoke_enabled =
          phases_match &&
          chrome::IsWasmProfilePreferencesBrowserSmokeEnabled() &&
          chrome::IsWasmProfilePreferencesCookieSmokeEnabled() &&
#if defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST)
          chrome::IsWasmProfilePreferencesBookmarkSmokeEnabled() &&
#else
          !chrome::IsWasmProfilePreferencesBookmarkSmokeEnabled() &&
#endif
#if defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST)
          chrome::IsWasmProfilePreferencesHistorySmokeEnabled() &&
#else
          !chrome::IsWasmProfilePreferencesHistorySmokeEnabled() &&
#endif
          chrome::IsWasmProfileRendererLocalStorageSmokeEnabled();
    }
    if (!aggregate_smoke_enabled) {
      chrome::ReportWasmProfilePreferencesSmokeFailure(
          chrome::WasmProfilePreferencesSmokeFailureStage::kArguments);
      chrome::ReportWasmProfileLocalStorageSmokeFailure(
          chrome::WasmProfileLocalStorageSmokeFailureStage::kArguments);
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

    // The experimental M7 V4 profile filesystem must mount before Content's
    // delegate can register or resolve /profile. The dedicated Preferences
    // artifact scopes its lease to /profile/Default; normal Chrome deliberately
    // keeps its configured profile path volatile rather than selecting this
    // isolated persistence acceptance backend.
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
#if defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    if (!preferences_smoke_requested || !local_storage_smoke_requested ||
#if defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
        !database_smoke_requested ||
#endif
        !aggregate_smoke_enabled) {
      // The combined artifact never mounts unless both protocols describe the
      // same accepted outer-document phase and the exact owner set was enabled.
      result = CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
#elif defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST)
    if (!preferences_smoke_requested || !preferences_smoke_enabled) {
      // The dedicated artifact must never fall through to ordinary Chrome
      // startup with a V4 leased profile mount: only its known Preferences
      // owner participates in the M7 test storage-I/O epoch. Invalid test
      // input already emitted its fixed redacted failure marker.
      result = CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
#elif defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST)
    if (!database_smoke_requested || !database_smoke_enabled) {
      // The dedicated artifact must never fall through to ordinary Chrome
      // startup with a V4 leased profile mount: only its known database and
      // Preferences owners participate in the M7 test storage-I/O epoch.
      // Invalid test input already emitted its fixed redacted failure marker.
      result = CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
#elif defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)
    if (!local_storage_smoke_requested || !local_storage_smoke_enabled) {
      // This dedicated artifact must not fall through to ordinary startup
      // while /profile/Default is V4-mounted. Its one explicit LocalStorage
      // owner is the only admitted non-Preferences profile store.
      result = CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
#elif defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST)
    if (!indexed_db_smoke_requested || !indexed_db_smoke_enabled) {
      // Keep /profile/Default unmounted unless this one exact renderer-owned
      // IndexedDB protocol was accepted before Content can create a profile.
      result = CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
#elif defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE)
    if (!persistent_default_partition_policy_probe_requested ||
        !persistent_default_partition_policy_probe_enabled) {
      // Do not mount V4 or fall through to normal Chrome when the sole
      // configuration-only protocol was absent or malformed.
      if (!persistent_default_partition_policy_probe_requested) {
        chrome::ReportWasmPersistentDefaultPartitionPolicyProbeFailure(
            chrome::WasmPersistentDefaultPartitionPolicyProbeFailureStage::
                kArguments);
      }
      result = CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
#endif
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    } else if (!chrome::InitializeWasmProfilePreferencesStorage()) {
#elif defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)
    } else if (!chrome::InitializeWasmProfilePreferencesStorage()) {
#elif defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST)
    } else if (!chrome::InitializeWasmProfilePreferencesStorage()) {
#elif defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE)
    } else if (!chrome::InitializeWasmProfilePreferencesStorage()) {
#else
    } else if (!chrome::InitializeWasmProfileStorage()) {
#endif
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
      chrome::ReportWasmProfilePreferencesSmokeFailure(
          chrome::WasmProfilePreferencesSmokeFailureStage::kStorage);
#endif
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
      if (database_smoke_requested) {
        chrome::ReportWasmProfileDatabaseSmokeFailure(
            chrome::WasmProfileDatabaseSmokeFailureStage::kStorage);
      }
#endif
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
      if (local_storage_smoke_requested) {
        chrome::ReportWasmProfileLocalStorageSmokeFailure(
            chrome::WasmProfileLocalStorageSmokeFailureStage::kStorage);
      }
#endif
#if defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST)
      if (indexed_db_smoke_requested) {
        chrome::ReportWasmProfileIndexedDBSmokeFailure(
            chrome::WasmProfileIndexedDBSmokeFailureStage::kStorage);
      }
#endif
#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE)
      if (persistent_default_partition_policy_probe_requested) {
        chrome::ReportWasmPersistentDefaultPartitionPolicyProbeFailure(
            chrome::WasmPersistentDefaultPartitionPolicyProbeFailureStage::
                kStorage);
      }
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
#else
    // The normal and M6 targets use /profile on the volatile filesystem. Do
    // not select the M7-only V4 OPFS/WasmFS backend merely to boot
    // Chrome; path setup remains owned by the Wasm Chrome paths component.
    base::PoissonAllocationSampler::Init();
    result = content::ContentMain(std::move(params));
#endif
  }

#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  if (preferences_smoke_enabled &&
      !IsNormalChromeMainResult(result)) {
    chrome::ReportWasmProfilePreferencesSmokeFailure(
        chrome::WasmProfilePreferencesSmokeFailureStage::kContent);
  }
#endif
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  if (database_smoke_enabled && !IsNormalChromeMainResult(result)) {
    chrome::ReportWasmProfileDatabaseSmokeFailure(
        chrome::WasmProfileDatabaseSmokeFailureStage::kContent);
  }
#endif
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  if (local_storage_smoke_enabled && !IsNormalChromeMainResult(result)) {
    chrome::ReportWasmProfileLocalStorageSmokeFailure(
        chrome::WasmProfileLocalStorageSmokeFailureStage::kContent);
  }
#endif
#if defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST)
  if (indexed_db_smoke_enabled && !IsNormalChromeMainResult(result)) {
    chrome::ReportWasmProfileIndexedDBSmokeFailure(
        chrome::WasmProfileIndexedDBSmokeFailureStage::kContent);
  }
#endif
#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE)
  if (persistent_default_partition_policy_probe_enabled &&
      !IsNormalChromeMainResult(result)) {
    chrome::ReportWasmPersistentDefaultPartitionPolicyProbeFailure(
        chrome::WasmPersistentDefaultPartitionPolicyProbeFailureStage::
            kContent);
  }
#endif

  // The dedicated M7 probes seal and drain their exact V4 leased OPFS backend
  // only after ContentMain and its delegate have both returned, when no
  // Content teardown can issue another profile operation. A failed mount can
  // also require cleanup if leased-backend construction partially succeeded.
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  if (chrome::NeedsWasmProfileStorageBackendDrain()) {
    chrome::WasmProfileStorageDrainResult drain_result =
        chrome::DrainAndReleaseWasmProfileStorageBackend();
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_OUTSTANDING_IO_REFUSAL_TEST)
    if (IsWasmM7ProfileOutstandingIORefusal(drain_result)) {
      fputs(kWasmM7ProfileOutstandingIORefusalMarker, stderr);
      fputc('\n', stderr);
      fflush(stderr);

      // The first result is the test's required pre-transaction refusal: it
      // returned before the storage owner selected either backend operation.
      // The retained admission belongs to a task that already emitted its
      // database failure and released SQLite/LevelDB resources, so finish it
      // as failed—not successfully or by destruction—before requesting one
      // separate fail-closed cleanup. That cleanup makes the later ordinary
      // Emscripten exit destructor-safe without converting this failure into
      // a clean profile handoff.
      if (chrome::CompleteWasmProfileStorageOutstandingIORefusalAsFailedForTest()) {
        drain_result = chrome::DrainAndReleaseWasmProfileStorageBackend();
      }
    }
#endif
    if (IsWasmM7ProfileFailureRetirement(drain_result)) {
      fputs(kWasmM7ProfileFailureRetirementMarker, stderr);
      fputc('\n', stderr);
      fflush(stderr);
    }
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    chrome::NotifyWasmProfilePreferencesSmokeBackendDrain(
        drain_result.Succeeded());
#endif
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    chrome::NotifyWasmProfileDatabaseSmokeBackendDrain(
        drain_result.Succeeded());
#endif
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    chrome::NotifyWasmProfileLocalStorageSmokeBackendDrain(
        drain_result.Succeeded());
#endif
#if defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST)
    chrome::NotifyWasmProfileIndexedDBSmokeBackendDrain(
        drain_result.Succeeded());
#endif
#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE)
    chrome::NotifyWasmPersistentDefaultPartitionPolicyProbeBackendDrain(
        drain_result.Succeeded());
    if (!chrome::DidWasmPersistentDefaultPartitionPolicyProbeComplete() &&
        IsNormalChromeMainResult(result)) {
      // A marker-protocol failure is not a normal policy probe result, even if
      // the storage adapter itself was able to complete its cleanup.
      result = CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
    }
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
#if defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  } else if (aggregate_smoke_enabled) {
    chrome::NotifyWasmProfilePreferencesSmokeBackendDrain(false);
#if defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    chrome::NotifyWasmProfileDatabaseSmokeBackendDrain(false);
#endif
    chrome::NotifyWasmProfileLocalStorageSmokeBackendDrain(false);
    if (IsNormalChromeMainResult(result)) {
      result = CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
    }
#elif defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST)
  } else if (preferences_smoke_enabled) {
    chrome::NotifyWasmProfilePreferencesSmokeBackendDrain(false);
    if (IsNormalChromeMainResult(result)) {
      result = CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
    }
#elif defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST)
  } else if (database_smoke_enabled) {
    chrome::NotifyWasmProfileDatabaseSmokeBackendDrain(false);
    if (IsNormalChromeMainResult(result)) {
      result = CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
    }
#elif defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)
  } else if (local_storage_smoke_enabled) {
    chrome::NotifyWasmProfileLocalStorageSmokeBackendDrain(false);
    if (IsNormalChromeMainResult(result)) {
      result = CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
    }
#elif defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST)
  } else if (indexed_db_smoke_enabled) {
    chrome::NotifyWasmProfileIndexedDBSmokeBackendDrain(false);
    if (IsNormalChromeMainResult(result)) {
      result = CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
    }
#elif defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE)
  } else if (persistent_default_partition_policy_probe_enabled) {
    chrome::NotifyWasmPersistentDefaultPartitionPolicyProbeBackendDrain(false);
    if (IsNormalChromeMainResult(result)) {
      result = CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
    }
#endif
  }
#endif

#if !defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) && \
    !defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) && \
    !defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) && \
    !defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST) && \
    !defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE) && \
    !defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) && \
    !defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) && \
    !defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) && \
    !defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  if (chrome::WasmProfileShutdownFailureWasRecorded() &&
      IsNormalChromeMainResult(result)) {
    // A failed volatile Preferences fence is not durable-storage evidence,
    // but it must not be reported as a normal process exit.
    result = CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
  }
#endif

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
