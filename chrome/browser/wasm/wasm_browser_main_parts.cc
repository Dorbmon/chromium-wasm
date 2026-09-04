// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_main_parts.h"

#include <cstdio>
#include <memory>
#include <optional>
#include <string>

#include "base/check.h"
#include "base/command_line.h"
#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "base/functional/bind.h"
#include "base/logging.h"
#include "base/path_service.h"
#include "base/run_loop.h"
#include "base/strings/string_number_conversions.h"
#include "base/time/time.h"
#include "build/build_config.h"
#include "chrome/browser/ui/actions/chrome_actions.h"
#include "chrome/browser/ui/browser_manager_service_factory.h"
#include "chrome/browser/ui/color/chrome_color_mixers.h"
#include "chrome/browser/wasm/wasm_browser_host_clipboard.h"
#include "chrome/browser/wasm/wasm_browser_host_input.h"
#include "chrome/browser/wasm/wasm_browser_host_lifecycle.h"
#include "chrome/browser/wasm/wasm_browser_host_pointer.h"
#include "chrome/browser/wasm/wasm_browser_host_storage_estimate.h"
#include "chrome/browser/wasm/wasm_browser_host_text.h"
#include "chrome/browser/wasm/wasm_browser_lifecycle.h"
#include "chrome/browser/wasm/wasm_browser_manager.h"
#include "chrome/browser/wasm/wasm_downloads_ui.h"
#include "chrome/browser/wasm/wasm_history_ui.h"
#include "chrome/browser/wasm/wasm_m6_controlled_https_test_mode.h"
#include "chrome/browser/wasm/wasm_browser_process.h"
#include "chrome/browser/wasm/wasm_browser_smoke.h"
#include "chrome/browser/wasm/wasm_settings_ui.h"
#include "chrome/browser/wasm/wasm_version_ui.h"
#include "chrome/browser/wasm/wasm_profile.h"
#if !defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) && \
    !defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) && \
    !defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) && \
    !defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST) && \
    !defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE) && \
    !defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE) && \
    !defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) && \
    !defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) && \
    !defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) && \
    !defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
// The normal source-selected configuration alone supplies this target. GN's
// include checker does not evaluate target-specific definitions.
#include "chrome/browser/wasm/wasm_profile_shutdown_failure_latch.h"  // nogncheck
#endif
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
// GN's include checker does not evaluate this target-specific definition.
#include "chrome/browser/wasm/wasm_profile_bookmark_smoke.h"  // nogncheck
#endif
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
// GN's include checker does not evaluate this target-specific definition.
#include "chrome/browser/wasm/wasm_profile_preferences_smoke.h"  // nogncheck
#endif
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
// GN's include checker does not evaluate this target-specific definition.
#include "chrome/browser/wasm/wasm_profile_database_smoke.h"  // nogncheck
#endif
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
// GN's include checker does not evaluate this target-specific definition.
#include "chrome/browser/wasm/wasm_profile_local_storage_smoke.h"  // nogncheck
#endif
#if defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST)
// This source-selected witness owns one real renderer IndexedDB operation in
// its exact persistent child StoragePartition. GN's include checker does not
// evaluate target-specific definitions.
#include "chrome/browser/wasm/wasm_profile_indexed_db_smoke.h"  // nogncheck
#endif
#if defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
// The shutdown probe uses the same narrow test WebUI but supplies the already
// created default partition through its captured-config identity witness.
#include "chrome/browser/wasm/wasm_profile_renderer_indexed_db_ui.h"  // nogncheck
#endif
#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE)
// This helper is source-selected into the configuration-only probe. It must
// remain absent from normal Chrome and has no StoragePartition owner API.
#include "chrome/browser/wasm/wasm_profile_persistent_default_partition_policy_probe.h"  // nogncheck
#endif
#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
// This helper owns the actual default-partition construction/map-drop
// observation. Its positive markers never authorize clean storage retirement.
#include "chrome/browser/wasm/wasm_profile_persistent_default_partition_shutdown_probe.h"  // nogncheck
#endif
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
// This source-selected test-only WebUI is registered before its transient
// renderer WebContents exists. GN's include checker does not evaluate this
// target-specific definition.
#include "chrome/browser/wasm/wasm_profile_renderer_local_storage_ui.h"  // nogncheck
#endif
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
// The experimental M7 target alone constructs this base-only admission
// participant before WasmProfile begins its synchronous Preferences read.
// GN's include checker does not evaluate target-specific definitions.
#include "chrome/browser/wasm/wasm_profile_persistent_prefs_lifetime_participant.h"  // nogncheck
// The experimental M7 target alone supplies this header and dependency. GN's
// include checker does not evaluate target-specific definitions.
#include "chrome/browser/wasm/wasm_profile_storage.h"  // nogncheck
#endif
#include "chrome/browser/wasm/wasm_browser_view_smoke.h"
#include "chrome/browser/wasm/wasm_browser_window_core_smoke.h"
#include "chrome/browser/wasm/wasm_browser_window_lifecycle.h"
#include "chrome/browser/wasm/wasm_browser_window_view_smoke.h"
#include "chrome/browser/wasm/wasm_tab_core_smoke.h"
#include "chrome/common/chrome_paths.h"
#include "chrome/common/chrome_result_codes.h"
#include "components/color/color_mixers.h"
#include "content/public/browser/browser_task_traits.h"
#include "content/public/browser/browser_thread.h"
#include "content/public/common/result_codes.h"
#include "ui/color/color_provider_manager.h"
#include "ui/base/resource/resource_bundle.h"
#include "ui/display/screen.h"
#include "ui/ozone/public/ozone_platform.h"
#include "ui/views/layout/layout_provider.h"
#include "ui/views/views_delegate.h"
#include "ui/views/widget/desktop_aura/desktop_screen.h"
#include "ui/wm/core/wm_state.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_main_parts.cc must only be built for WebAssembly"
#endif

namespace {

// The generic delegate gives Views the process-global owner it requires while
// deliberately avoiding Chrome-specific profile, placement, and native
// desktop-widget policies.
class WasmViewsDelegate final : public views::ViewsDelegate {
 public:
  WasmViewsDelegate() = default;
  WasmViewsDelegate(const WasmViewsDelegate&) = delete;
  WasmViewsDelegate& operator=(const WasmViewsDelegate&) = delete;
  ~WasmViewsDelegate() override = default;
};

constexpr char kLocale[] = "en-US";
[[maybe_unused]] constexpr char kWasmBrowserViewSmokeSwitch[] =
    "wasm-browser-view-smoke";
[[maybe_unused]] constexpr char kWasmBrowserWindowCoreSmokeSwitch[] =
    "wasm-browser-window-core-smoke";
[[maybe_unused]] constexpr char kWasmBrowserSmokeSwitch[] =
    "wasm-browser-smoke";
[[maybe_unused]] constexpr char kWasmBrowserControlledHttpsSmokeSwitch[] =
    "wasm-browser-controlled-https-smoke";
[[maybe_unused]] constexpr char kWasmBrowserM9WispRecoverySmokeSwitch[] =
    "wasm-browser-m9-wisp-recovery-smoke";
[[maybe_unused]] constexpr char kWasmBrowserM9RepeatingTimerSmokeSwitch[] =
    "wasm-browser-m9-repeating-timer-smoke";
[[maybe_unused]] constexpr char kWasmBrowserM9RepeatingTimerSmokeTicksSwitch[] =
    "wasm-browser-m9-repeating-timer-smoke-ticks";
[[maybe_unused]] constexpr char kWasmBrowserLifecycleSmokeSwitch[] =
    "wasm-browser-lifecycle-smoke";
constexpr char kWasmBrowserDevToolsProtocolSmokeSwitch[] =
    "wasm-browser-devtools-protocol-smoke";
constexpr char kWasmBrowserM8PageJavaScriptSemanticsSmokeSwitch[] =
    "wasm-browser-m8-page-javascript-semantics-smoke";
constexpr char kWasmBrowserM8PageJavaScriptAsyncRejectionSmokeSwitch[] =
    "wasm-browser-m8-page-javascript-async-rejection-smoke";
constexpr char kWasmBrowserM8PageJavaScriptPlatformSemanticsSmokeSwitch[] =
    "wasm-browser-m8-page-javascript-platform-semantics-smoke";
constexpr char kWasmBrowserM8PageJavaScriptDataUrlFetchTextSmokeSwitch[] =
    "wasm-browser-m8-page-javascript-data-url-fetch-text-smoke";
constexpr char kWasmBrowserM8PageWebAssemblySmokeSwitch[] =
    "wasm-browser-m8-page-webassembly-smoke";
constexpr char kWasmBrowserM8PageWebAssemblyMemorySmokeSwitch[] =
    "wasm-browser-m8-page-webassembly-memory-smoke";
constexpr char kWasmBrowserM8PageWebAssemblyTableSmokeSwitch[] =
    "wasm-browser-m8-page-webassembly-table-smoke";
constexpr char kWasmBrowserM8PageWebAssemblyMemoryGrowthSmokeSwitch[] =
    "wasm-browser-m8-page-webassembly-memory-growth-smoke";
constexpr char kWasmBrowserM8PageWebAssemblyTableGrowthSmokeSwitch[] =
    "wasm-browser-m8-page-webassembly-table-growth-smoke";
constexpr char kWasmBrowserM8PageWebAssemblyExceptionsSmokeSwitch[] =
    "wasm-browser-m8-page-webassembly-exceptions-smoke";
constexpr char kWasmBrowserM8PageWebAssemblyWasmMemoryGrowOpcodeSmokeSwitch[] =
    "wasm-browser-m8-page-webassembly-wasm-memory-grow-opcode-smoke";
constexpr char kWasmBrowserM8PageWebAssemblyWasmTableGrowOpcodeSmokeSwitch[] =
    "wasm-browser-m8-page-webassembly-wasm-table-grow-opcode-smoke";
constexpr char kWasmBrowserM8PageWebAssemblyWasmThrowSmokeSwitch[] =
    "wasm-browser-m8-page-webassembly-wasm-throw-smoke";
constexpr char kWasmBrowserM8PageWebAssemblyWasmThrowPayloadSmokeSwitch[] =
    "wasm-browser-m8-page-webassembly-wasm-throw-payload-smoke";
constexpr char kWasmBrowserM8PageWebAssemblyJsThrowPayloadSmokeSwitch[] =
    "wasm-browser-m8-page-webassembly-js-throw-payload-smoke";
constexpr char kWasmBrowserM8PageWebAssemblyInstantiateStreamingSmokeSwitch[] =
    "wasm-browser-m8-page-webassembly-instantiate-streaming-smoke";
constexpr char
    kWasmBrowserM8PageWebAssemblyInstantiateFunctionImportSmokeSwitch[] =
        "wasm-browser-m8-page-webassembly-instantiate-function-import-smoke";
constexpr char kWasmBrowserAccessibilitySnapshotSmokeSwitch[] =
    "wasm-browser-accessibility-snapshot-smoke";
constexpr char kWasmBrowserHostAcceleratorSmokeSwitch[] =
    "wasm-browser-host-accelerator-smoke";
constexpr char kWasmBrowserHostTextSmokeSwitch[] =
    "wasm-browser-host-text-smoke";
constexpr char kWasmBrowserHostClipboardSmokeSwitch[] =
    "wasm-browser-host-clipboard-smoke";
constexpr char kWasmBrowserHostStorageEstimateSmokeSwitch[] =
    "wasm-browser-host-storage-estimate-smoke";
constexpr char kWasmBrowserHostPointerTabSmokeSwitch[] =
    "wasm-browser-host-pointer-tab-smoke";
constexpr char kWasmBrowserHostTabChurnSmokeSwitch[] =
    "wasm-browser-host-tab-churn-smoke";
constexpr char kWasmBrowserHostNavigationChurnSmokeSwitch[] =
    "wasm-browser-host-navigation-churn-smoke";
constexpr char kWasmBrowserHostPointerMenuSmokeSwitch[] =
    "wasm-browser-host-pointer-menu-smoke";
constexpr char kWasmBrowserHostSecurityWarningSmokeSwitch[] =
    "wasm-browser-host-security-warning-smoke";
constexpr char kWasmBrowserHostHistoryDownloadsSmokeSwitch[] =
    "wasm-browser-host-history-downloads-smoke";
constexpr char kWasmBrowserHostContinuousFlowSmokeSwitch[] =
    "wasm-browser-host-continuous-flow-smoke";
constexpr char kWasmBrowserHostContinuousFlowRestartSmokeSwitch[] =
    "wasm-browser-host-continuous-flow-restart-smoke";
constexpr char kWasmBrowserLifecycleSmokeReadyMarker[] =
    "CHROMIUM_WASM_M6_BROWSER_LIFECYCLE:READY";
constexpr char kWasmBrowserLifecycleSmokePassMarker[] =
    "CHROMIUM_WASM_M6_BROWSER_LIFECYCLE:PASS";
constexpr char kWasmBrowserHostAcceleratorSmokeReadyMarker[] =
    "CHROMIUM_WASM_M6_HOST_ACCELERATORS:READY";
[[maybe_unused]] constexpr char kWasmNormalBrowserReadyMarker[] =
    "CHROMIUM_WASM_M6_NORMAL_BROWSER:READY";
constexpr char kWasmNormalBrowserPassMarker[] =
    "CHROMIUM_WASM_M6_NORMAL_BROWSER:PASS";
constexpr base::TimeDelta kWasmBrowserLifecycleSmokeVisibleDuration =
    base::Milliseconds(250);
constexpr int kWasmBrowserM9RepeatingTimerSmokeTickCount = 3;
constexpr int kWasmBrowserM9RepeatingTimerSmokeStressTickCount = 100;
constexpr int kWasmBrowserM9RepeatingTimerSmokeLongStressTickCount = 1000;
constexpr base::TimeDelta kWasmBrowserM9RepeatingTimerSmokeInterval =
    base::Milliseconds(50);
constexpr base::TimeDelta kWasmBrowserM9RepeatingTimerSmokeQuiescenceDuration =
    base::Milliseconds(200);
constexpr base::TimeDelta kWasmBrowserM9RepeatingTimerSmokeTimeout =
    base::Seconds(5);
constexpr base::TimeDelta kWasmBrowserM9RepeatingTimerSmokeStressTimeout =
    base::Seconds(12);
constexpr base::TimeDelta kWasmBrowserM9RepeatingTimerSmokeLongStressTimeout =
    base::Seconds(75);
constexpr char kWasmBrowserM9RepeatingTimerSmokeReadyMarker[] =
    "CHROMIUM_WASM_M9_REPEATING_TIMER:READY";
constexpr char kWasmBrowserM9RepeatingTimerSmokeTickMarker[] =
    "CHROMIUM_WASM_M9_REPEATING_TIMER:TICK";
constexpr char kWasmBrowserM9RepeatingTimerSmokeQuiescentMarker[] =
    "CHROMIUM_WASM_M9_REPEATING_TIMER:QUIESCENT";
constexpr char kWasmBrowserM9RepeatingTimerSmokePassMarker[] =
    "CHROMIUM_WASM_M9_REPEATING_TIMER:PASS";
constexpr char kWasmBrowserM9RepeatingTimerSmokeTimeoutMarker[] =
    "CHROMIUM_WASM_M9_REPEATING_TIMER:TIMEOUT";
[[maybe_unused]] constexpr char kWasmBrowserWindowViewSmokeSwitch[] =
    "wasm-browser-window-view-smoke";
[[maybe_unused]] constexpr char kWasmBrowserWindowLifecycleSmokeSwitch[] =
    "wasm-browser-window-lifecycle-smoke";
constexpr char kWasmBrowserWindowLifecycleSmokeReadyMarker[] =
    "CHROMIUM_WASM_M6_BROWSER_WINDOW_LIFECYCLE:READY";
constexpr base::TimeDelta kWasmBrowserWindowLifecycleSmokeVisibleDuration =
    base::Milliseconds(250);
[[maybe_unused]] constexpr char kWasmTabCoreSmokeSwitch[] =
    "wasm-tab-core-smoke";
constexpr char kRequiredAssets[][24] = {
    "chrome_100_percent.pak",
    "chrome_200_percent.pak",
    "resources.pak",
    "locales/en-US.pak",
    "icudtl.dat",
    "Roboto-Regular.ttf",
};

#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
void FailCloseM7ProfileConstruction() {
  if (!chrome::AbortWasmProfileStorageProfileConstructionFailClosed()) {
    LOG(ERROR) << "chrome_wasm could not publish its fail-closed profile "
                  "construction abort; its OPFS profile lease remains retained";
  } else {
    LOG(ERROR) << "chrome_wasm will fail-close its incomplete OPFS profile "
                  "construction";
  }
}

void CompleteM7ProfileConstructionAdmissionAsFailed(
    std::optional<WasmProfileOrderedDrainLifecycle::ProfileIOHold>*
        profile_io_hold) {
  bool completed = false;
  if (profile_io_hold && *profile_io_hold) {
    completed = profile_io_hold->value().Complete(
        WasmProfileOrderedDrainLifecycle::ProfileIOCompletion::kFailed);
    profile_io_hold->reset();
  }
  if (!completed) {
    // A malformed or already-completed local holder must not prevent the
    // caller from selecting the outer fail-closed retirement path.
    LOG(ERROR) << "chrome_wasm could not complete its profile construction "
                  "admission as failed";
  }
}

void ResetProfileThenFailCloseM7ProfileStorage(
    std::unique_ptr<WasmProfile>& profile) {
  profile.reset();
  if (!chrome::NotifyWasmProfileStorageProfileShutdownFailClosed()) {
    LOG(ERROR) << "chrome_wasm could not publish its fail-closed profile "
                  "shutdown; its OPFS profile lease remains retained";
  } else {
    LOG(ERROR) << "chrome_wasm selected fail-closed profile shutdown; its "
                  "OPFS lease remains retained without a clean drain";
  }
}
#endif

}  // namespace

WasmBrowserMainParts::WasmBrowserMainParts(bool /*is_integration_test*/) {}

WasmBrowserMainParts::~WasmBrowserMainParts() {
  ShutdownFoundation();
}

int WasmBrowserMainParts::PreEarlyInitialization() {
  if (!PreflightResources()) {
    LOG(ERROR) << "chrome_wasm required resource preflight failed";
    return CHROME_RESULT_CODE_MISSING_DATA;
  }

  const std::string loaded_locale =
      ui::ResourceBundle::InitSharedInstanceWithLocale(
          kLocale, nullptr, ui::ResourceBundle::LOAD_COMMON_RESOURCES);
  if (loaded_locale.empty()) {
    LOG(ERROR) << "chrome_wasm could not load locale " << kLocale;
    return CHROME_RESULT_CODE_MISSING_DATA;
  }
  resource_bundle_initialized_ = true;

  base::FilePath resources_pack;
  if (!base::PathService::Get(chrome::FILE_RESOURCES_PACK, &resources_pack) ||
      !base::PathExists(resources_pack)) {
    LOG(ERROR) << "chrome_wasm missing resources pack";
    return CHROME_RESULT_CODE_MISSING_DATA;
  }
  ui::ResourceBundle::GetSharedInstance().AddDataPackFromPath(
      resources_pack, ui::kScaleFactorNone);

  return content::RESULT_CODE_NORMAL_EXIT;
}

void WasmBrowserMainParts::ToolkitInitialized() {
  // BrowserMainLoop has created Aura's Env before this callback, but has not
  // registered BrowserThread::UI yet. Install generic process-lifetime Views
  // state here rather than creating it transiently in a BrowserWidget smoke.
  if (!views::ViewsDelegate::GetInstance()) {
    views_delegate_ = std::make_unique<WasmViewsDelegate>();
  }
  CHECK(views::ViewsDelegate::GetInstance());

  if (!views::LayoutProvider::Get()) {
    layout_provider_ = std::make_unique<views::LayoutProvider>();
  }
  CHECK(views::LayoutProvider::Get());

  CHECK(!wm_state_);
  wm_state_ = std::make_unique<wm::WMState>();

  // Install the canonical component and Chrome color initializers before any
  // BrowserView or BrowserWidget can request a ColorProvider. The default
  // Wasm provider intentionally has no custom-theme or app-controller
  // supplier at this stage, but the canonical mixers preserve those later
  // extension points.
  ui::ColorProviderManager::Get().AppendColorProviderInitializer(
      base::BindRepeating(color::AddComponentsColorMixers));
  ui::ColorProviderManager::Get().AppendColorProviderInitializer(
      base::BindRepeating(AddChromeColorMixers));

  // This maps Chrome action IDs for source-selected Views code without
  // creating an ActionManager root or a Browser. Browser-owned actions remain
  // outside the M6 window-lifecycle boundary until BrowserView is admitted.
  InitializeActionIdStringMapping();
}

void WasmBrowserMainParts::PostCreateMainMessageLoop() {
  ui::OzonePlatform::GetInstance()->PostCreateMainMessageLoop(
      base::BindOnce(&WasmBrowserMainParts::RequestShutdown,
                     weak_ptr_factory_.GetWeakPtr()),
      content::GetUIThreadTaskRunner({content::BrowserTaskType::kUserInput}));
  ozone_main_loop_initialized_ = true;
}

int WasmBrowserMainParts::PreCreateThreads() {
  if (!resource_bundle_initialized_) {
    return CHROME_RESULT_CODE_MISSING_DATA;
  }

  CHECK(views::ViewsDelegate::GetInstance());
  CHECK(views::LayoutProvider::Get());
  CHECK(wm_state_);
  if (!display::Screen::Get()) {
    screen_ = views::CreateDesktopScreen();
  }
  CHECK(display::Screen::Get());

  browser_process_ = std::make_unique<WasmBrowserProcess>();
  return content::RESULT_CODE_NORMAL_EXIT;
}

int WasmBrowserMainParts::PreMainMessageLoopRun() {
  if (!browser_process_) {
    return CHROME_RESULT_CODE_MISSING_DATA;
  }
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  if (!chrome::IsWasmProfileStorageMounted()) {
    LOG(ERROR) << "chrome_wasm experimental profile storage is not mounted";
    return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
  }
#endif

#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  // The selected V4 mount can be reached while resolving /profile and
  // creating Default. Start the construction lifetime before either path
  // operation, then transfer this same hold into WasmProfile before its
  // synchronous JsonPrefStore/PrefService read.
  std::optional<WasmProfileOrderedDrainLifecycle::ProfileIOHold>
      preconstruction_profile_io_hold =
          chrome::BeginWasmProfileStorageProfileConstruction();
  if (!preconstruction_profile_io_hold) {
    LOG(ERROR) << "chrome_wasm could not admit its profile construction I/O";
    FailCloseM7ProfileConstruction();
    return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
  }
#endif

  base::FilePath user_data_directory;
  if (!base::PathService::Get(chrome::DIR_USER_DATA, &user_data_directory)) {
    LOG(ERROR) << "chrome_wasm could not resolve its profile root";
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    CompleteM7ProfileConstructionAdmissionAsFailed(
        &preconstruction_profile_io_hold);
    FailCloseM7ProfileConstruction();
#endif
    return CHROME_RESULT_CODE_MISSING_DATA;
  }

  const base::FilePath profile_path =
      user_data_directory.AppendASCII("Default");
  if (!base::CreateDirectory(profile_path)) {
    LOG(ERROR) << "chrome_wasm could not create its profile path";
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    CompleteM7ProfileConstructionAdmissionAsFailed(
        &preconstruction_profile_io_hold);
    FailCloseM7ProfileConstruction();
#endif
    return CHROME_RESULT_CODE_MISSING_DATA;
  }

// The policy-only and structural-shutdown artifacts own their exact first
// default-partition operation. Do not register Browser keyed-service factories
// or WebUI configurations, because either can create a profile service before
// the source-selected observation begins.
#if !defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE) && \
    !defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
  // Profile's base constructor marks its BrowserContext live. Register the
  // Wasm-owned factory first so its keyed-service lifecycle can be created and
  // shut down with the profile rather than arriving lazily after that point.
  EnsureWasmBrowserKeyedServiceFactoriesBuilt();

  // The source-selected WebUI configurations are process-global and must
  // exist before the first Wasm WebContents is created. This registration is
  // intentionally mutually exclusive with RegisterChromeWebUIConfigs(): the
  // generic desktop registry owns HistoryUI/DownloadsUI and would duplicate
  // these exact Wasm root hosts and pull unsupported service/resource graphs.
  chrome::EnsureWasmVersionWebUIConfigRegistered();
  chrome::EnsureWasmSettingsWebUIConfigRegistered();
  chrome::EnsureWasmHistoryWebUIConfigRegistered();
  chrome::EnsureWasmDownloadsWebUIConfigRegistered();
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  // The renderer LocalStorage witness is source-selected into the isolated M7
  // LocalStorage artifact. Register its exact test Chrome origin before any
  // WebContents is created; normal chrome_wasm has no such route.
  chrome::EnsureWasmProfileRendererLocalStorageWebUIConfigRegistered();
#endif
#if defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST)
  // The isolated IndexedDB document is the only WebUI route that selects the
  // persistent child partition. Register it before its transient WebContents
  // is created; normal chrome_wasm has neither this route nor that partition.
  chrome::EnsureWasmProfileRendererIndexedDBWebUIConfigRegistered();
#endif
#endif  // !policy-probe && !structural-shutdown-probe

#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
  // This test-only registration is intentionally the shutdown artifact's
  // only WebUI setup. It precedes the one renderer IndexedDB participant and
  // does not admit Chrome's ordinary browser, WebContents, or service graph.
  chrome::EnsureWasmProfileRendererIndexedDBWebUIConfigRegistered();
#endif

  // BrowserThread::IO and ThreadPool are live at this stage. The profile's
  // explicit I/O runner may therefore be created without racing startup.
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  // The construction hold has covered profile-path setup. Its participant now
  // moves into WasmProfile's member initializer, where it remains pending
  // through the synchronous JsonPrefStore/PrefService read and the strict
  // Preferences shutdown write/readback fence.
  auto prefs_lifetime_profile_io_participant =
      std::make_unique<WasmProfilePersistentPrefsLifetimeParticipant>(
          std::move(*preconstruction_profile_io_hold));
  profile_ = std::make_unique<WasmProfile>(
      profile_path, std::move(prefs_lifetime_profile_io_participant));
#else
  profile_ = std::make_unique<WasmProfile>(profile_path);
#endif
  if (!profile_) {
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    // This path does not publish ProfileCreated(). The local constructor
    // participant, if still present, records failure while unwinding after
    // the precreation lifecycle has been closed.
    FailCloseM7ProfileConstruction();
#endif
    return CHROME_RESULT_CODE_MISSING_DATA;
  }
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  if (!chrome::NotifyWasmProfileStorageProfileCreated()) {
    LOG(ERROR) << "chrome_wasm could not admit its profile storage lifecycle";
    // No ProfileCreated event was published. Destroy the constructor-held
    // admission before using the distinct precreation abort, so this path can
    // only retire the lease fail-closed rather than report normal shutdown.
    profile_.reset();
    FailCloseM7ProfileConstruction();
    return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
  }
#endif

#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE)
  // Stop immediately after the live BrowserContext's construction admission.
  // The probe calls only StoragePartitionConfig::CreateDefault() and returns
  // before any WebUI instance, Browser, BrowserView, WebContents,
  // NetworkContext, or StoragePartition startup path can run.
  if (!chrome::IsWasmPersistentDefaultPartitionPolicyProbeEnabled()) {
    chrome::ReportWasmPersistentDefaultPartitionPolicyProbeFailure(
        chrome::WasmPersistentDefaultPartitionPolicyProbeFailureStage::
            kArguments);
    RequestShutdown();
    return content::RESULT_CODE_NORMAL_EXIT;
  }
  auto policy_probe_profile_io_hold =
      chrome::TryAcquireWasmProfileStorageProfileIO();
  if (!policy_probe_profile_io_hold) {
    chrome::ReportWasmPersistentDefaultPartitionPolicyProbeFailure(
        chrome::WasmPersistentDefaultPartitionPolicyProbeFailureStage::
            kAdmission);
    RequestShutdown();
    return content::RESULT_CODE_NORMAL_EXIT;
  }
  if (!chrome::RunWasmPersistentDefaultPartitionPolicyProbe(
          profile_.get(), std::move(*policy_probe_profile_io_hold))) {
    LOG(ERROR) << "chrome_wasm persistent default StoragePartition policy "
                  "probe failed";
  }
  RequestShutdown();
  return content::RESULT_CODE_NORMAL_EXIT;
#endif

#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
  // This artifact admits exactly one real default StoragePartition after the
  // V4 Default mount and profile construction. It owns no ordinary Browser or
  // service graph, but creates one source-selected renderer WebUI document to
  // collect a selected IndexedDB close receipt, then closes that exact
  // partition's complete IndexedDB context. It starts profile teardown only
  // after direct LocalStorage, renderer IndexedDB/context, and persistent
  // CookieManager selected-owner receipts; it then always retires the backend
  // fail-closed after the map-drop boundary.
  if (!chrome::IsWasmPersistentDefaultPartitionShutdownProbeEnabled()) {
    chrome::ReportWasmPersistentDefaultPartitionShutdownProbeFailure(
        chrome::WasmPersistentDefaultPartitionShutdownProbeFailureStage::
            kArguments);
    RequestShutdown();
    return content::RESULT_CODE_NORMAL_EXIT;
  }
  auto shutdown_probe_profile_io_hold =
      chrome::TryAcquireWasmProfileStorageProfileIO();
  if (!shutdown_probe_profile_io_hold) {
    chrome::ReportWasmPersistentDefaultPartitionShutdownProbeFailure(
        chrome::WasmPersistentDefaultPartitionShutdownProbeFailureStage::
            kAdmission);
    RequestShutdown();
    return content::RESULT_CODE_NORMAL_EXIT;
  }
  if (!chrome::RunWasmPersistentDefaultPartitionShutdownProbe(
          profile_.get(), std::move(*shutdown_probe_profile_io_hold),
          base::BindOnce(
              &WasmBrowserMainParts::
                  OnWasmPersistentDefaultPartitionShutdownProbeSelectedOwnerReceiptsClosed,
              weak_ptr_factory_.GetWeakPtr()))) {
    LOG(ERROR) << "chrome_wasm persistent default StoragePartition selected "
                  "owner shutdown probe failed";
    RequestShutdown();
  }
  return content::RESULT_CODE_NORMAL_EXIT;
#endif

// Both dedicated artifacts return above before Chrome's host, Browser, and
// WebContents setup. Exclude the ordinary remainder at source selection time
// as well, preserving their exact first-partition boundary.
#if !defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE) && \
    !defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  // The preferences-only M7 acceptance intentionally stops here: its native
  // PrefService action runs after profile admission but before host, Browser,
  // WebContents, or BrowserWindow setup. The aggregate outer-reload witnesses
  // start the same action here, then fall through to normal Wasm host
  // initialization so the fixed Browser lifecycle can close before the fence.
  if (chrome::IsWasmProfilePreferencesSmokeEnabled()) {
    if (!chrome::StartWasmProfilePreferencesSmoke(profile_->GetPrefs())) {
      return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
    }
    if (!chrome::IsWasmProfilePreferencesBrowserSmokeEnabled()) {
      RequestShutdown();
      return content::RESULT_CODE_NORMAL_EXIT;
    }
  }
#endif

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST)
  // The M7 three-fresh-module SQLite/LevelDB acceptance stops after profile
  // admission, before host input, Browser, WebContents, or BrowserWindow
  // setup. Its completion requests ordinary asynchronous profile shutdown only
  // after the single database runner has closed and destroyed both engines.
  if (chrome::IsWasmProfileDatabaseSmokeEnabled()) {
    auto profile_io_hold = chrome::TryAcquireWasmProfileStorageProfileIO();
    if (!profile_io_hold) {
      LOG(ERROR) << "chrome_wasm could not admit its profile database I/O";
      RequestShutdown();
      return content::RESULT_CODE_NORMAL_EXIT;
    }
    // Transfer the database runner and its admission into WasmProfile before
    // the task begins. Profile teardown is then gated by the participant's
    // terminal callback instead of a BrowserMainParts-owned closure.
    if (!profile_->StartDatabaseSmoke(
            std::move(*profile_io_hold),
            base::BindOnce(
                &WasmBrowserMainParts::OnWasmProfileDatabaseSmokeComplete,
                weak_ptr_factory_.GetWeakPtr()))) {
      RequestShutdown();
    }
    return content::RESULT_CODE_NORMAL_EXIT;
  }
#endif

#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)
  // This source-selected probe starts after profile lifecycle admission but
  // before host input, Browser, or BrowserWindow setup. Browser-side modes
  // bind a privileged StorageArea; renderer modes create one transient test
  // WebContents whose external chrome:// script owns the StorageArea. Both
  // require a real map-update snapshot and same-runner database-close receipt
  // before releasing the profile-I/O hold.
  if (chrome::IsWasmProfileLocalStorageSmokeEnabled()) {
    auto local_storage_input =
        chrome::TakeWasmProfileLocalStorageSmokeInput();
    if (!local_storage_input) {
      LOG(ERROR) << "chrome_wasm could not consume its LocalStorage request";
      RequestShutdown();
      return content::RESULT_CODE_NORMAL_EXIT;
    }
    auto profile_io_hold = chrome::TryAcquireWasmProfileStorageProfileIO();
    if (!profile_io_hold) {
      LOG(ERROR) << "chrome_wasm could not admit its profile LocalStorage I/O";
      RequestShutdown();
      return content::RESULT_CODE_NORMAL_EXIT;
    }
    auto local_storage_completion = base::BindOnce(
        [](base::WeakPtr<WasmBrowserMainParts> main_parts, bool success) {
          const bool participant_succeeded =
              success && main_parts && main_parts->profile_ &&
              main_parts->profile_->DidLocalStorageSmokeSucceed();
          chrome::NotifyWasmProfileLocalStorageSmokeOperationResult(
              participant_succeeded);
          if (!participant_succeeded) {
            LOG(ERROR) << "chrome_wasm LocalStorage close did not complete "
                          "cleanly";
          }
          if (main_parts) {
            main_parts->RequestShutdown();
            // RequestShutdown() is intentionally idempotent. If cancellation
            // deferred an already-requested shutdown, explicitly resume its
            // profile-owner gate after the terminal close delivery.
            main_parts->MaybeStartShutdown();
          }
        },
        weak_ptr_factory_.GetWeakPtr());
    const bool local_storage_started = profile_->StartLocalStorageSmoke(
        std::move(*local_storage_input), std::move(*profile_io_hold),
        std::move(local_storage_completion));
    if (!local_storage_started) {
      RequestShutdown();
    }
    return content::RESULT_CODE_NORMAL_EXIT;
  }
#endif

#if defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST)
  // The standalone renderer IndexedDB witness starts after the V4 Default
  // mount and profile admission, before ordinary host input or Browser setup.
  // The renderer itself commits and closes the database; this profile-owned
  // participant then verifies the actual persistent child partition and waits
  // for the selected bucket's backing-store close receipt before handoff.
  if (chrome::IsWasmProfileIndexedDBSmokeEnabled()) {
    auto indexed_db_input = chrome::TakeWasmProfileIndexedDBSmokeInput();
    if (!indexed_db_input) {
      LOG(ERROR) << "chrome_wasm could not consume its IndexedDB request";
      chrome::NotifyWasmProfileIndexedDBSmokeOperationResult(false);
      RequestShutdown();
      return content::RESULT_CODE_NORMAL_EXIT;
    }
    auto profile_io_hold = chrome::TryAcquireWasmProfileStorageProfileIO();
    if (!profile_io_hold) {
      LOG(ERROR) << "chrome_wasm could not admit its IndexedDB profile I/O";
      chrome::ReportWasmProfileIndexedDBSmokeFailure(
          chrome::WasmProfileIndexedDBSmokeFailureStage::kStorage);
      chrome::NotifyWasmProfileIndexedDBSmokeOperationResult(false);
      RequestShutdown();
      return content::RESULT_CODE_NORMAL_EXIT;
    }
    auto indexed_db_completion = base::BindOnce(
        [](base::WeakPtr<WasmBrowserMainParts> main_parts, bool success) {
          const bool participant_succeeded =
              success && main_parts && main_parts->profile_ &&
              main_parts->profile_->DidIndexedDBSmokeSucceed();
          chrome::NotifyWasmProfileIndexedDBSmokeOperationResult(
              participant_succeeded);
          if (!participant_succeeded) {
            LOG(ERROR) << "chrome_wasm IndexedDB backing-store close receipt "
                          "did not complete cleanly";
          }
          if (main_parts) {
            main_parts->RequestShutdown();
            // A failed or cancelled close may complete after an earlier
            // shutdown request; resume the profile-owner gate on its terminal
            // UI-sequence delivery rather than leaving it deferred.
            main_parts->MaybeStartShutdown();
          }
        },
        weak_ptr_factory_.GetWeakPtr());
    const bool indexed_db_started = profile_->StartIndexedDBSmoke(
        std::move(*indexed_db_input), std::move(*profile_io_hold),
        std::move(indexed_db_completion));
    if (!indexed_db_started) {
      chrome::NotifyWasmProfileIndexedDBSmokeOperationResult(false);
      RequestShutdown();
    }
    return content::RESULT_CODE_NORMAL_EXIT;
  }
#endif

  // Keep Chrome's bounded physical-key ABI separate from Content Shell's test
  // bridge. It must capture Ozone's injector while the UI sequence and Ozone
  // platform are live, and PostMainMessageLoopRun releases it before Ozone.
  if (!chrome::InitializeWasmBrowserHostInput()) {
    LOG(ERROR) << "chrome_wasm could not create its Ozone input injector";
    return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
  }

  // Committed trusted-DOM text follows the Ozone TextInputClient boundary,
  // not the physical-key bridge. Browser lifecycle binds its single widget
  // later, after the real BrowserView exists.
  if (!chrome::InitializeWasmBrowserHostText()) {
    LOG(ERROR) << "chrome_wasm could not initialize its host text bridge";
    chrome::ShutdownWasmBrowserHostInput();
    return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
  }

  // Trusted DOM paste imports only text/plain into the existing volatile
  // copy/paste buffer, then emits a complete normal Ozone Ctrl+V chord. It is
  // intentionally separate from committed text and the physical-key ABI.
  if (!chrome::InitializeWasmBrowserHostClipboard()) {
    LOG(ERROR) << "chrome_wasm could not initialize its host clipboard bridge";
    chrome::ShutdownWasmBrowserHostText();
    chrome::ShutdownWasmBrowserHostInput();
    return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
  }

  // The ordinary Chrome host maps trusted DOM mouse records into physical
  // canvas coordinates and submits them through this distinct Ozone bridge.
  // Keep it separate from the narrow physical-key ABI: pointer lifetime has
  // no authority to invoke Browser commands or manipulate Chrome Views.
  if (!chrome::InitializeWasmBrowserHostPointer()) {
    LOG(ERROR) << "chrome_wasm could not create its Ozone pointer injector";
    chrome::ShutdownWasmBrowserHostClipboard();
    chrome::ShutdownWasmBrowserHostText();
    chrome::ShutdownWasmBrowserHostInput();
    return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
  }

  // This does not mount OPFS or make a persistence claim. It schedules one
  // read-only outer-host navigator.storage.estimate() diagnostic whose
  // immutable result can be shown by the native chrome://settings WebUI.
  // Missing host support becomes an explicit unavailable snapshot instead of
  // making the browser fail to start.
  if (!chrome::InitializeWasmBrowserHostStorageEstimate()) {
    LOG(ERROR) << "chrome_wasm could not initialize its host storage estimate";
    chrome::ShutdownWasmBrowserHostPointer();
    chrome::ShutdownWasmBrowserHostClipboard();
    chrome::ShutdownWasmBrowserHostText();
    chrome::ShutdownWasmBrowserHostInput();
    return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
  }

  // Exercise the factory while the profile is live. Browser::Create() will
  // retrieve this same manager when the real window lifecycle is selected.
  CHECK(BrowserManagerServiceFactory::GetForProfile(profile_.get()));

#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  if (chrome::IsWasmProfilePreferencesBrowserSmokeEnabled()) {
    if (!chrome::RunWasmBrowserSmoke(profile_.get())) {
      chrome::NotifyWasmProfilePreferencesBrowserSmokeResult(false);
      return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
    }
    chrome::NotifyWasmProfilePreferencesBrowserSmokeResult(true);
#if defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    StartWasmProfileBookmarkSmokeOrCookieOrHistoryOrShutdown();
#elif defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST)
    StartWasmProfileCookieSmokeOrHistoryOrShutdown();
#else
    StartWasmProfileBookmarkSmokeOrCookieOrHistoryOrShutdown();
#endif
    return content::RESULT_CODE_NORMAL_EXIT;
  }
#endif

  // This dedicated Chrome target installs Chromium's local test root before
  // ContentMain. The smoke then reaches one exact H2 fixture through the
  // visible address field and a host-configured WISP transport. Production
  // chrome_wasm neither links that root nor accepts this test-only contract.
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserControlledHttpsSmokeSwitch)) {
    if (!chrome::IsWasmM6ControlledHttpsTestModeEnabled()) {
      LOG(ERROR) << "chrome_wasm rejects the controlled HTTPS smoke switch "
                    "outside its dedicated test executable";
      return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
    }
    if (!chrome::RunWasmBrowserControlledHttpsSmoke(profile_.get())) {
      LOG(ERROR) << "chrome_wasm controlled HTTPS browser smoke failed";
      return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
    }
    RequestShutdown();
    return content::RESULT_CODE_NORMAL_EXIT;
  }

  // M9's bounded carrier-close proof is another privileged fixture route in
  // the same dedicated executable: only its local root may trust a.test, and
  // the tab itself still reaches the canonical URL solely through Ozone input.
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM9WispRecoverySmokeSwitch)) {
    if (!chrome::IsWasmM6ControlledHttpsTestModeEnabled()) {
      LOG(ERROR) << "chrome_wasm rejects the M9 WISP recovery smoke switch "
                    "outside its dedicated test executable";
      return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
    }
    if (!chrome::RunWasmBrowserM9WispRecoverySmoke(profile_.get())) {
      LOG(ERROR) << "chrome_wasm M9 WISP recovery smoke failed";
      return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
    }
    RequestShutdown();
    return content::RESULT_CODE_NORMAL_EXIT;
  }

  // This switch-gated proof creates the first real Wasm Browser through the
  // normal BrowserWindow factory/deleter seam, attaches one model-owned tab,
  // then verifies the ordered BrowserWindowFeatures and manager destruction
  // path. It remains deliberately narrower than ordinary Chrome startup.
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserSmokeSwitch)) {
    if (!chrome::RunWasmBrowserSmoke(profile_.get())) {
      LOG(ERROR) << "chrome_wasm Wasm Browser smoke failed";
      return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
    }
    RequestShutdown();
    return content::RESULT_CODE_NORMAL_EXIT;
  }

  // This opt-in lifecycle proof keeps one real source-selected Browser alive
  // across a browser-main loop turn, then waits for manager physical
  // destruction before profile shutdown. It remains one blank no-unload tab,
  // not ordinary Chrome startup or a general Browser lifecycle.
  const bool browser_lifecycle_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserLifecycleSmokeSwitch);
  const bool browser_m9_repeating_timer_default_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM9RepeatingTimerSmokeSwitch);
  const bool browser_m9_repeating_timer_stress_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM9RepeatingTimerSmokeTicksSwitch);
  int m9_repeating_timer_smoke_expected_ticks =
      kWasmBrowserM9RepeatingTimerSmokeTickCount;
  if (browser_m9_repeating_timer_stress_smoke) {
    const std::string stress_ticks =
        base::CommandLine::ForCurrentProcess()->GetSwitchValueASCII(
            kWasmBrowserM9RepeatingTimerSmokeTicksSwitch);
    int parsed_stress_ticks = 0;
    if (!base::StringToInt(stress_ticks, &parsed_stress_ticks) ||
        (parsed_stress_ticks !=
             kWasmBrowserM9RepeatingTimerSmokeStressTickCount &&
         parsed_stress_ticks !=
             kWasmBrowserM9RepeatingTimerSmokeLongStressTickCount) ||
        stress_ticks != base::NumberToString(parsed_stress_ticks)) {
      LOG(ERROR) << "chrome_wasm rejects an unsupported M9 repeating timer "
                    "stress tick count";
      return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
    }
    m9_repeating_timer_smoke_expected_ticks = parsed_stress_ticks;
  }
  if (browser_m9_repeating_timer_default_smoke &&
      browser_m9_repeating_timer_stress_smoke) {
    LOG(ERROR) << "chrome_wasm rejects combined M9 repeating timer smoke "
                  "switches";
    return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
  }
  const bool browser_m9_repeating_timer_smoke =
      browser_m9_repeating_timer_default_smoke ||
      browser_m9_repeating_timer_stress_smoke;
  const bool browser_devtools_protocol_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserDevToolsProtocolSmokeSwitch);
  const bool browser_m8_page_javascript_semantics_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageJavaScriptSemanticsSmokeSwitch);
  const bool browser_m8_page_javascript_async_rejection_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageJavaScriptAsyncRejectionSmokeSwitch);
  const bool browser_m8_page_javascript_platform_semantics_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageJavaScriptPlatformSemanticsSmokeSwitch);
  const bool browser_m8_page_javascript_data_url_fetch_text_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageJavaScriptDataUrlFetchTextSmokeSwitch);
  const bool browser_m8_page_webassembly_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageWebAssemblySmokeSwitch);
  const bool browser_m8_page_webassembly_memory_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageWebAssemblyMemorySmokeSwitch);
  const bool browser_m8_page_webassembly_table_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageWebAssemblyTableSmokeSwitch);
  const bool browser_m8_page_webassembly_memory_growth_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageWebAssemblyMemoryGrowthSmokeSwitch);
  const bool browser_m8_page_webassembly_table_growth_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageWebAssemblyTableGrowthSmokeSwitch);
  const bool browser_m8_page_webassembly_exceptions_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageWebAssemblyExceptionsSmokeSwitch);
  const bool browser_m8_page_webassembly_wasm_memory_grow_opcode_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageWebAssemblyWasmMemoryGrowOpcodeSmokeSwitch);
  const bool browser_m8_page_webassembly_wasm_table_grow_opcode_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageWebAssemblyWasmTableGrowOpcodeSmokeSwitch);
  const bool browser_m8_page_webassembly_wasm_throw_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageWebAssemblyWasmThrowSmokeSwitch);
  const bool browser_m8_page_webassembly_wasm_throw_payload_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageWebAssemblyWasmThrowPayloadSmokeSwitch);
  const bool browser_m8_page_webassembly_js_throw_payload_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageWebAssemblyJsThrowPayloadSmokeSwitch);
  const bool browser_m8_page_webassembly_instantiate_streaming_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageWebAssemblyInstantiateStreamingSmokeSwitch);
  const bool browser_m8_page_webassembly_instantiate_function_import_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageWebAssemblyInstantiateFunctionImportSmokeSwitch);
  const bool browser_accessibility_snapshot_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserAccessibilitySnapshotSmokeSwitch);
  const bool browser_host_accelerator_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserHostAcceleratorSmokeSwitch);
  const bool browser_host_text_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserHostTextSmokeSwitch);
  const bool browser_host_clipboard_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserHostClipboardSmokeSwitch);
  const bool browser_host_storage_estimate_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserHostStorageEstimateSmokeSwitch);
  const bool browser_host_pointer_tab_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserHostPointerTabSmokeSwitch);
  const bool browser_host_tab_churn_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserHostTabChurnSmokeSwitch);
  const bool browser_host_navigation_churn_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserHostNavigationChurnSmokeSwitch);
  const bool browser_host_pointer_menu_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserHostPointerMenuSmokeSwitch);
  const bool browser_host_security_warning_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserHostSecurityWarningSmokeSwitch);
  const bool browser_host_history_downloads_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserHostHistoryDownloadsSmokeSwitch);
  const bool browser_host_continuous_flow_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserHostContinuousFlowSmokeSwitch);
  const bool browser_host_continuous_flow_restart_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserHostContinuousFlowRestartSmokeSwitch);
  if ((browser_host_history_downloads_smoke ||
       browser_host_continuous_flow_smoke ||
       browser_host_continuous_flow_restart_smoke) &&
      !chrome::IsWasmM6ControlledHttpsTestModeEnabled()) {
    LOG(ERROR) << "chrome_wasm rejects the controlled M6 host flow "
                  "outside its dedicated controlled HTTPS test executable";
    return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
  }
  if (browser_lifecycle_smoke || browser_m9_repeating_timer_smoke ||
      browser_devtools_protocol_smoke ||
      browser_m8_page_javascript_semantics_smoke ||
      browser_m8_page_javascript_async_rejection_smoke ||
      browser_m8_page_javascript_platform_semantics_smoke ||
      browser_m8_page_javascript_data_url_fetch_text_smoke ||
      browser_m8_page_webassembly_smoke ||
      browser_m8_page_webassembly_memory_smoke ||
      browser_m8_page_webassembly_table_smoke ||
      browser_m8_page_webassembly_memory_growth_smoke ||
      browser_m8_page_webassembly_table_growth_smoke ||
      browser_m8_page_webassembly_exceptions_smoke ||
      browser_m8_page_webassembly_wasm_memory_grow_opcode_smoke ||
      browser_m8_page_webassembly_wasm_table_grow_opcode_smoke ||
      browser_m8_page_webassembly_wasm_throw_smoke ||
      browser_m8_page_webassembly_wasm_throw_payload_smoke ||
      browser_m8_page_webassembly_js_throw_payload_smoke ||
      browser_m8_page_webassembly_instantiate_streaming_smoke ||
      browser_m8_page_webassembly_instantiate_function_import_smoke ||
      browser_accessibility_snapshot_smoke ||
      browser_host_accelerator_smoke ||
      browser_host_text_smoke || browser_host_clipboard_smoke ||
      browser_host_storage_estimate_smoke ||
      browser_host_pointer_tab_smoke ||
      browser_host_tab_churn_smoke ||
      browser_host_navigation_churn_smoke ||
      browser_host_pointer_menu_smoke || browser_host_security_warning_smoke ||
      browser_host_history_downloads_smoke ||
      browser_host_continuous_flow_smoke ||
      browser_host_continuous_flow_restart_smoke) {
    CHECK_EQ(static_cast<int>(browser_lifecycle_smoke) +
                 static_cast<int>(browser_m9_repeating_timer_smoke) +
                 static_cast<int>(browser_devtools_protocol_smoke) +
                 static_cast<int>(
                     browser_m8_page_javascript_semantics_smoke) +
                 static_cast<int>(
                     browser_m8_page_javascript_async_rejection_smoke) +
                 static_cast<int>(
                     browser_m8_page_javascript_platform_semantics_smoke) +
                 static_cast<int>(
                     browser_m8_page_javascript_data_url_fetch_text_smoke) +
                 static_cast<int>(browser_m8_page_webassembly_smoke) +
                 static_cast<int>(browser_m8_page_webassembly_memory_smoke) +
                 static_cast<int>(browser_m8_page_webassembly_table_smoke) +
                 static_cast<int>(
                     browser_m8_page_webassembly_memory_growth_smoke) +
                 static_cast<int>(
                     browser_m8_page_webassembly_table_growth_smoke) +
                 static_cast<int>(
                     browser_m8_page_webassembly_exceptions_smoke) +
                static_cast<int>(
                    browser_m8_page_webassembly_wasm_memory_grow_opcode_smoke) +
                static_cast<int>(
                    browser_m8_page_webassembly_wasm_table_grow_opcode_smoke) +
                static_cast<int>(browser_m8_page_webassembly_wasm_throw_smoke) +
                static_cast<int>(
                    browser_m8_page_webassembly_wasm_throw_payload_smoke) +
                static_cast<int>(
                    browser_m8_page_webassembly_js_throw_payload_smoke) +
                 static_cast<int>(
                     browser_m8_page_webassembly_instantiate_streaming_smoke) +
                 static_cast<int>(
                     browser_m8_page_webassembly_instantiate_function_import_smoke) +
                 static_cast<int>(browser_accessibility_snapshot_smoke) +
                 static_cast<int>(browser_host_accelerator_smoke) +
                 static_cast<int>(browser_host_text_smoke) +
                 static_cast<int>(browser_host_clipboard_smoke) +
                 static_cast<int>(browser_host_storage_estimate_smoke) +
                 static_cast<int>(browser_host_pointer_tab_smoke) +
                 static_cast<int>(browser_host_tab_churn_smoke) +
                 static_cast<int>(browser_host_navigation_churn_smoke) +
                 static_cast<int>(browser_host_pointer_menu_smoke) +
                 static_cast<int>(browser_host_security_warning_smoke) +
                 static_cast<int>(browser_host_history_downloads_smoke) +
                 static_cast<int>(browser_host_continuous_flow_smoke) +
                 static_cast<int>(browser_host_continuous_flow_restart_smoke),
             1);
    CHECK(!browser_lifecycle_);
    CHECK(!browser_lifecycle_smoke_requested_);
    CHECK(!browser_window_lifecycle_);
    browser_lifecycle_smoke_requested_ = true;
    m9_repeating_timer_smoke_requested_ = browser_m9_repeating_timer_smoke;
    m9_repeating_timer_smoke_expected_ticks_ =
        m9_repeating_timer_smoke_expected_ticks;
    browser_lifecycle_ = std::make_unique<chrome::WasmBrowserLifecycle>(
        profile_.get(),
        base::BindOnce(&WasmBrowserMainParts::OnBrowserLifecycleShutdownComplete,
                       weak_ptr_factory_.GetWeakPtr()));
    browser_lifecycle_->Initialize();
    return content::RESULT_CODE_NORMAL_EXIT;
  }

  // This test-only switch registers an empty source-selected
  // BrowserWindowInterface with the real manager and feature UDD lifecycles,
  // then proves its close notification and asynchronous destruction order.
  // It deliberately creates no Browser, BrowserView, WebContents, or window.
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserWindowCoreSmokeSwitch)) {
    if (!chrome::RunWasmBrowserWindowCoreSmoke(profile_.get())) {
      LOG(ERROR) << "chrome_wasm Wasm BrowserWindowInterface core smoke failed";
      return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
    }
    RequestShutdown();
    return content::RESULT_CODE_NORMAL_EXIT;
  }

  // This test-only switch binds one real model-owned WebContents and a
  // temporary BaseWindow to the structural BrowserView, verifies active-tab
  // relay and bounded close ordering, then releases both owners. It
  // deliberately creates no Browser or general browser-window lifecycle.
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserWindowViewSmokeSwitch)) {
    if (!chrome::RunWasmBrowserWindowViewSmoke(profile_.get())) {
      LOG(ERROR) << "chrome_wasm Wasm BrowserWindow/View smoke failed";
      return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
    }
    RequestShutdown();
    return content::RESULT_CODE_NORMAL_EXIT;
  }

  // This separate opt-in lifecycle proof owns one visible bounded no-unload
  // tab through a main-loop turn, then defers exit until BrowserManagerService
  // has physically destroyed its Core. It remains distinct from
  // Browser::Create(), ordinary startup, and the richer navigation/modal
  // composition smoke above.
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserWindowLifecycleSmokeSwitch)) {
    CHECK(!browser_window_lifecycle_);
    CHECK(!browser_window_lifecycle_smoke_requested_);
    browser_window_lifecycle_smoke_requested_ = true;
    browser_window_lifecycle_ =
        std::make_unique<chrome::WasmBrowserWindowLifecycle>(
            profile_.get(),
            base::BindOnce(
                &WasmBrowserMainParts::OnBrowserWindowLifecycleShutdownComplete,
                weak_ptr_factory_.GetWeakPtr()));
    browser_window_lifecycle_->Initialize();
    return content::RESULT_CODE_NORMAL_EXIT;
  }

  // This test-only switch source-selects the structural Views/Aura/Ozone
  // BrowserView path against the live Wasm profile, then exits after its
  // client-owned Widget teardown. It never constructs a Browser or admits the
  // BrowserWindowFeatures lifecycle; the ordinary path below remains explicit.
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserViewSmokeSwitch)) {
    if (!chrome::RunWasmBrowserViewSmoke(profile_.get())) {
      LOG(ERROR) << "chrome_wasm Wasm BrowserView smoke failed";
      return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
    }
    RequestShutdown();
    return content::RESULT_CODE_NORMAL_EXIT;
  }

  // This test-only switch proves the real source-selected tab ownership path
  // against the live Wasm profile, then exits before a Browser or Chrome Views
  // window can be created. The ordinary chrome_wasm path below remains the
  // explicit M6 foundation result until that lifecycle is complete.
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmTabCoreSmokeSwitch)) {
    if (!chrome::RunWasmTabCoreSmoke(profile_.get())) {
      LOG(ERROR) << "chrome_wasm Wasm tab-core smoke failed";
      return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
    }
    RequestShutdown();
    return content::RESULT_CODE_NORMAL_EXIT;
  }

  // The ordinary Wasm path retains one real Browser through the main loop.
  // Its host ABI can request shutdown once, but browser-main owns all actual
  // window close, manager-drain, and profile-teardown work. This is still the
  // bounded M6 surface: one blank tab at fixed bounds, no general OpenURL,
  // page-modal, menu, history, or Settings lifecycle. The selected Browser
  // may expose its explicit security-boundary child warning through Views.
  CHECK(!browser_lifecycle_);
  CHECK(!browser_lifecycle_smoke_requested_);
  CHECK(!browser_window_lifecycle_);
  if (!chrome::InitializeWasmBrowserHostLifecycle(base::BindRepeating(
          &WasmBrowserMainParts::RequestShutdown,
          weak_ptr_factory_.GetWeakPtr()))) {
    LOG(ERROR) << "chrome_wasm could not initialize its host shutdown bridge";
    return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
  }
  browser_lifecycle_ = std::make_unique<chrome::WasmBrowserLifecycle>(
      profile_.get(),
      base::BindOnce(&WasmBrowserMainParts::OnBrowserLifecycleShutdownComplete,
                     weak_ptr_factory_.GetWeakPtr()));
  browser_lifecycle_->Initialize();
  CHECK(browser_lifecycle_->IsVisible());
  std::fprintf(stderr, "%s\n", kWasmNormalBrowserReadyMarker);
  std::fflush(stderr);
  return content::RESULT_CODE_NORMAL_EXIT;
#endif  // !policy-probe && !structural-shutdown-probe
}

void WasmBrowserMainParts::WillRunMainMessageLoop(
    std::unique_ptr<base::RunLoop>& run_loop) {
  main_message_loop_quit_closure_ = run_loop->QuitClosure();
  StartBrowserLifecycleSmokeShutdownTimer();
  StartBrowserWindowLifecycleSmokeShutdownTimer();
  MaybeStartShutdown();
}

void WasmBrowserMainParts::PostMainMessageLoopRun() {
  StopM9RepeatingTimerSmoke();
  // Shut down the lifecycle request ABI first: it owns a callback into these
  // main-parts and must become inert before the profile/Ozone teardown path.
  chrome::ShutdownWasmBrowserHostLifecycle();
  chrome::ShutdownWasmBrowserHostStorageEstimate();
  // Invalidate the host ABI and release its SystemInputInjector while its
  // Ozone owner is still live. Queued records carry a generation token and
  // safely drop after this point.
  chrome::ShutdownWasmBrowserHostPointer();
  chrome::ShutdownWasmBrowserHostClipboard();
  chrome::ShutdownWasmBrowserHostText();
  chrome::ShutdownWasmBrowserHostInput();
  if (ozone_main_loop_initialized_) {
    ui::OzonePlatform::GetInstance()->PostMainMessageLoopRun();
    ozone_main_loop_initialized_ = false;
  }
  weak_ptr_factory_.InvalidateWeakPtrs();
  ShutdownFoundation();
}

bool WasmBrowserMainParts::PreflightResources() {
  base::FilePath assets_directory;
  if (!base::PathService::Get(base::DIR_ASSETS, &assets_directory)) {
    LOG(ERROR) << "chrome_wasm has no asset directory";
    return false;
  }

  for (const char* asset : kRequiredAssets) {
    const base::FilePath asset_path = assets_directory.AppendASCII(asset);
    if (!base::PathExists(asset_path)) {
      LOG(ERROR) << "chrome_wasm missing required asset "
                 << asset_path.AsUTF8Unsafe();
      return false;
    }
  }
  return true;
}

void WasmBrowserMainParts::RequestShutdown() {
  if (shutdown_requested_) {
    return;
  }
#if defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  // Database is the final aggregate participant. Any first shutdown request
  // before it starts is a terminal aggregate failure, while a request after
  // its result-bearing close is the expected success path. Report this here so
  // an upstream owner failure cannot be misclassified later as a fence error.
  if (profile_ && chrome::IsWasmProfileDatabaseSmokeEnabled() &&
      !profile_->HasActiveDatabaseSmoke() &&
      !chrome::DidWasmProfileDatabaseSmokeSucceed()) {
    chrome::ReportWasmProfileDatabaseSmokeFailure(
        chrome::WasmProfileDatabaseSmokeFailureStage::kLifecycle);
  }
#endif
#if defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST)
  // This dedicated artifact must not make a lifecycle request look clean
  // before its renderer bucket has delivered its selected close receipt.
  if (profile_ && chrome::IsWasmProfileIndexedDBSmokeEnabled() &&
      !profile_->HasActiveIndexedDBSmoke() &&
      !chrome::DidWasmProfileIndexedDBSmokeSucceed()) {
    chrome::ReportWasmProfileIndexedDBSmokeFailure(
        chrome::WasmProfileIndexedDBSmokeFailureStage::kLifecycle);
  }
#endif
  StopM9RepeatingTimerSmoke();
  shutdown_requested_ = true;
  // Creation status uses BrowserProcess shutdown state. Set it as soon as
  // shutdown is requested so no bounded Browser can be admitted while a
  // lifecycle is draining its non-nestable close work.
  if (browser_process_) {
    browser_process_->EndSession();
  }
  MaybeStartShutdown();
}

#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
void WasmBrowserMainParts::
    OnWasmPersistentDefaultPartitionShutdownProbeSelectedOwnerReceiptsClosed(
        bool success) {
  if (!success) {
    LOG(ERROR) << "chrome_wasm persistent default LocalStorage/IndexedDB-"
                  "context/Cookie selected-owner receipt failed";
  }
  // The probe posts this handoff after all selected owner callbacks have
  // returned. From this point ordinary profile teardown can observe the real
  // default partition notification and map-drop boundaries.
  RequestShutdown();
}
#endif

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
#if defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
void WasmBrowserMainParts::StartWasmProfileDatabaseSmokeOrShutdown() {
  CHECK(profile_);
  if (shutdown_requested_) {
    chrome::ReportWasmProfileDatabaseSmokeFailure(
        chrome::WasmProfileDatabaseSmokeFailureStage::kLifecycle);
    MaybeStartShutdown();
    return;
  }
  if (!chrome::IsWasmProfileDatabaseSmokeEnabled()) {
    chrome::ReportWasmProfileDatabaseSmokeFailure(
        chrome::WasmProfileDatabaseSmokeFailureStage::kCapability);
    RequestShutdown();
    return;
  }

  auto profile_io_hold = chrome::TryAcquireWasmProfileStorageProfileIO();
  if (!profile_io_hold) {
    chrome::ReportWasmProfileDatabaseSmokeFailure(
        chrome::WasmProfileDatabaseSmokeFailureStage::kStorage);
    RequestShutdown();
    return;
  }
  if (!profile_->StartDatabaseSmoke(
          std::move(*profile_io_hold),
          base::BindOnce(
              &WasmBrowserMainParts::OnWasmProfileDatabaseSmokeComplete,
              weak_ptr_factory_.GetWeakPtr()))) {
    chrome::ReportWasmProfileDatabaseSmokeFailure(
        chrome::WasmProfileDatabaseSmokeFailureStage::kLifecycle);
    RequestShutdown();
  }
}
#endif

void WasmBrowserMainParts::OnWasmProfileDatabaseSmokeComplete(bool success) {
  const bool database_succeeded =
      success && profile_ && profile_->DidDatabaseSmokeSucceed();
  if (!database_succeeded) {
    LOG(ERROR) << "chrome_wasm SQLite/LevelDB close witness failed";
  }

  // A shutdown request can race the shutdown-blocking database runner. Its
  // idempotent RequestShutdown() would not resume the deferred profile-owner
  // gate, so re-enter it directly after the participant becomes terminal.
  if (shutdown_requested_) {
    MaybeStartShutdown();
    return;
  }
  RequestShutdown();
}
#endif

void WasmBrowserMainParts::MaybeStartShutdown() {
  // A lifecycle close posts non-nestable UI work. If Ozone requests shutdown
  // before Content has installed the main RunLoop, defer that work until the
  // loop can service it rather than abandoning a bound Views window.
  if (!shutdown_requested_ || !main_message_loop_quit_closure_) {
    return;
  }

  CHECK(!(browser_lifecycle_ && browser_window_lifecycle_));
  if (browser_lifecycle_) {
    if (!browser_shutdown_started_) {
      browser_shutdown_started_ = true;
      if (!browser_lifecycle_->IsShutdownStarted()) {
        browser_lifecycle_->BeginShutdown();
      }
    }
    return;
  }

  if (browser_window_lifecycle_) {
    if (!browser_window_shutdown_started_) {
      browser_window_shutdown_started_ = true;
      if (!browser_window_lifecycle_->IsShutdownStarted()) {
        browser_window_lifecycle_->BeginShutdown();
      }
    }
    return;
  }

#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  // BookmarkModel load and ImportantFileWriter work are profile-owned but
  // asynchronous. Cancellation must reach a terminal model-owner result
  // before Profile teardown; its callback resumes this state machine.
  if (profile_ && profile_->HasActiveBookmarkSmoke()) {
    profile_->CancelBookmarkSmokeForShutdown();
    return;
  }
#endif

#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  // CookieManager belongs to the profile's default StoragePartition. Its
  // profile-owned participant must receive the SQLite backend-close result
  // before synchronous Profile teardown can destroy that partition.
  if (profile_ && profile_->HasActiveCookieSmoke()) {
    profile_->CancelCookieSmokeForShutdown();
    return;
  }
#endif

#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  // The direct source-selected HistoryService is profile-owned but closes its
  // History/Favicons backends asynchronously. Do not enter synchronous
  // Profile teardown until its backend-destroy receipt has made the admitted
  // profile I/O terminal. Its callback re-enters this method instead of a
  // duplicate RequestShutdown(), which is intentionally idempotent.
  if (profile_ && profile_->HasActiveHistorySmoke()) {
    profile_->CancelHistorySmokeForShutdown();
    return;
  }
#endif

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  // SQLite and LevelDB run on a shutdown-blocking sequence but remain owned
  // by WasmProfile. Cancellation records failure without racing their open
  // handles; the terminal UI callback resumes this shutdown state machine.
  if (profile_ && profile_->HasActiveDatabaseSmoke()) {
    profile_->CancelDatabaseSmokeForShutdown();
    return;
  }
#endif

#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  if (profile_ && profile_->HasActiveLocalStorageSmoke()) {
    profile_->CancelLocalStorageSmokeForShutdown();
    return;
  }
#endif

#if defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST)
  // The selected persistent child partition has a real backing store outside
  // WasmProfile's default in-memory partition. Do not start the Preferences
  // fence or destroy the profile while its close receipt is still pending.
  if (profile_ && profile_->HasActiveIndexedDBSmoke()) {
    profile_->CancelIndexedDBSmokeForShutdown();
    return;
  }
#endif

  FinishShutdown();
}

void WasmBrowserMainParts::StartBrowserLifecycleSmokeShutdownTimer() {
  if (!browser_lifecycle_smoke_requested_ || shutdown_requested_) {
    return;
  }
  CHECK(browser_lifecycle_);
  CHECK(!browser_lifecycle_smoke_shutdown_timer_.IsRunning());
  browser_lifecycle_smoke_shutdown_timer_.Start(
      FROM_HERE, kWasmBrowserLifecycleSmokeVisibleDuration,
      base::BindOnce(&WasmBrowserMainParts::OnBrowserLifecycleSmokeShutdownTimer,
                     weak_ptr_factory_.GetWeakPtr()));
}

void WasmBrowserMainParts::OnBrowserLifecycleSmokeShutdownTimer() {
  // A direct BrowserView close can already be draining through the Browser
  // lifecycle's did-close barrier. That completion quits without re-entering
  // the Browser close path.
  if (shutdown_requested_ || !browser_lifecycle_ ||
      browser_lifecycle_->IsShutdownStarted()) {
    return;
  }

  CHECK(browser_lifecycle_smoke_requested_);
  CHECK(browser_lifecycle_->IsVisible());
  if (m9_repeating_timer_smoke_requested_) {
    StartM9RepeatingTimerSmoke();
    return;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserDevToolsProtocolSmokeSwitch)) {
    browser_lifecycle_->StartDevToolsProtocolSmoke();
    return;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageJavaScriptSemanticsSmokeSwitch)) {
    browser_lifecycle_->StartPageJavaScriptSemanticsDevToolsProtocolSmoke();
    return;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageJavaScriptAsyncRejectionSmokeSwitch)) {
    browser_lifecycle_->StartPageJavaScriptAsyncRejectionDevToolsProtocolSmoke();
    return;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageJavaScriptPlatformSemanticsSmokeSwitch)) {
    browser_lifecycle_
        ->StartPageJavaScriptPlatformSemanticsDevToolsProtocolSmoke();
    return;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageJavaScriptDataUrlFetchTextSmokeSwitch)) {
    browser_lifecycle_
        ->StartPageJavaScriptDataUrlFetchTextDevToolsProtocolSmoke();
    return;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageWebAssemblySmokeSwitch)) {
    browser_lifecycle_->StartPageWebAssemblyDevToolsProtocolSmoke();
    return;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageWebAssemblyMemorySmokeSwitch)) {
    browser_lifecycle_->StartPageWebAssemblyMemoryDevToolsProtocolSmoke();
    return;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageWebAssemblyTableSmokeSwitch)) {
    browser_lifecycle_->StartPageWebAssemblyTableDevToolsProtocolSmoke();
    return;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageWebAssemblyMemoryGrowthSmokeSwitch)) {
    browser_lifecycle_->StartPageWebAssemblyMemoryGrowthDevToolsProtocolSmoke();
    return;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageWebAssemblyTableGrowthSmokeSwitch)) {
    browser_lifecycle_->StartPageWebAssemblyTableGrowthDevToolsProtocolSmoke();
    return;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageWebAssemblyExceptionsSmokeSwitch)) {
    browser_lifecycle_->StartPageWebAssemblyExceptionDevToolsProtocolSmoke();
    return;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageWebAssemblyWasmMemoryGrowOpcodeSmokeSwitch)) {
    browser_lifecycle_
        ->StartPageWebAssemblyWasmMemoryGrowOpcodeDevToolsProtocolSmoke();
    return;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageWebAssemblyWasmTableGrowOpcodeSmokeSwitch)) {
    browser_lifecycle_
        ->StartPageWebAssemblyWasmTableGrowOpcodeDevToolsProtocolSmoke();
    return;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageWebAssemblyWasmThrowSmokeSwitch)) {
    browser_lifecycle_->StartPageWebAssemblyWasmThrowDevToolsProtocolSmoke();
    return;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageWebAssemblyWasmThrowPayloadSmokeSwitch)) {
    browser_lifecycle_
        ->StartPageWebAssemblyWasmThrowPayloadDevToolsProtocolSmoke();
    return;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageWebAssemblyJsThrowPayloadSmokeSwitch)) {
    browser_lifecycle_
        ->StartPageWebAssemblyJsThrowPayloadDevToolsProtocolSmoke();
    return;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageWebAssemblyInstantiateStreamingSmokeSwitch)) {
    browser_lifecycle_
        ->StartPageWebAssemblyInstantiateStreamingDevToolsProtocolSmoke();
    return;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM8PageWebAssemblyInstantiateFunctionImportSmokeSwitch)) {
    browser_lifecycle_
        ->StartPageWebAssemblyInstantiateFunctionImportDevToolsProtocolSmoke();
    return;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserAccessibilitySnapshotSmokeSwitch)) {
    browser_lifecycle_->StartAccessibilitySnapshotSmoke();
    return;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserHostAcceleratorSmokeSwitch)) {
    // Install the UI verifier before reporting READY: host stdout callbacks
    // may synchronously invoke the exported ABI in response to that marker.
    browser_lifecycle_->StartHostAcceleratorSmoke();
    std::fprintf(stderr, "%s\n", kWasmBrowserHostAcceleratorSmokeReadyMarker);
    std::fflush(stderr);
    return;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserHostTextSmokeSwitch) ||
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserHostClipboardSmokeSwitch)) {
    browser_lifecycle_->StartHostTextSmoke();
    return;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserHostStorageEstimateSmokeSwitch)) {
    browser_lifecycle_->StartHostStorageEstimateSmoke();
    return;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserHostPointerTabSmokeSwitch)) {
    browser_lifecycle_->StartHostPointerTabSmoke();
    return;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserHostTabChurnSmokeSwitch)) {
    browser_lifecycle_->StartHostTabChurnSmoke();
    return;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserHostNavigationChurnSmokeSwitch)) {
    browser_lifecycle_->StartHostNavigationChurnSmoke();
    return;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserHostPointerMenuSmokeSwitch)) {
    browser_lifecycle_->StartHostPointerMenuSmoke();
    return;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserHostSecurityWarningSmokeSwitch)) {
    browser_lifecycle_->StartHostSecurityWarningSmoke();
    return;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserHostHistoryDownloadsSmokeSwitch)) {
    browser_lifecycle_->StartHostHistoryDownloadsSmoke();
    return;
  }
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserHostContinuousFlowSmokeSwitch) ||
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserHostContinuousFlowRestartSmokeSwitch)) {
    browser_lifecycle_->StartHostContinuousFlowSmoke();
    return;
  }
  std::fprintf(stderr, "%s\n", kWasmBrowserLifecycleSmokeReadyMarker);
  std::fflush(stderr);
  RequestShutdown();
}

void WasmBrowserMainParts::StartM9RepeatingTimerSmoke() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(browser_lifecycle_smoke_requested_);
  CHECK(m9_repeating_timer_smoke_requested_);
  CHECK(!m9_repeating_timer_smoke_started_);
  CHECK(!shutdown_requested_);
  CHECK(browser_lifecycle_);
  CHECK(browser_lifecycle_->IsVisible());
  CHECK(!m9_repeating_timer_smoke_timer_.IsRunning());
  CHECK(!m9_repeating_timer_smoke_timeout_timer_.IsRunning());
  CHECK(m9_repeating_timer_smoke_expected_ticks_ ==
            kWasmBrowserM9RepeatingTimerSmokeTickCount ||
        m9_repeating_timer_smoke_expected_ticks_ ==
            kWasmBrowserM9RepeatingTimerSmokeStressTickCount ||
        m9_repeating_timer_smoke_expected_ticks_ ==
            kWasmBrowserM9RepeatingTimerSmokeLongStressTickCount);

  m9_repeating_timer_smoke_started_ = true;
  m9_repeating_timer_smoke_observed_ticks_ = 0;
  m9_repeating_timer_smoke_timer_.Start(
      FROM_HERE, kWasmBrowserM9RepeatingTimerSmokeInterval,
      base::BindRepeating(&WasmBrowserMainParts::OnM9RepeatingTimerSmokeTick,
                          weak_ptr_factory_.GetWeakPtr()));
  m9_repeating_timer_smoke_timeout_timer_.Start(
      FROM_HERE,
      m9_repeating_timer_smoke_expected_ticks_ ==
              kWasmBrowserM9RepeatingTimerSmokeLongStressTickCount
          ? kWasmBrowserM9RepeatingTimerSmokeLongStressTimeout
          : m9_repeating_timer_smoke_expected_ticks_ ==
              kWasmBrowserM9RepeatingTimerSmokeStressTickCount
              ? kWasmBrowserM9RepeatingTimerSmokeStressTimeout
              : kWasmBrowserM9RepeatingTimerSmokeTimeout,
      base::BindOnce(&WasmBrowserMainParts::OnM9RepeatingTimerSmokeTimeout,
                     weak_ptr_factory_.GetWeakPtr()));
  std::fprintf(stderr, "%s ticks=%d interval_ms=%d\n",
               kWasmBrowserM9RepeatingTimerSmokeReadyMarker,
               m9_repeating_timer_smoke_expected_ticks_,
               static_cast<int>(
                   kWasmBrowserM9RepeatingTimerSmokeInterval.InMilliseconds()));
  std::fflush(stderr);
}

void WasmBrowserMainParts::OnM9RepeatingTimerSmokeTick() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!m9_repeating_timer_smoke_started_ || shutdown_requested_ ||
      !browser_lifecycle_ || browser_lifecycle_->IsShutdownStarted()) {
    return;
  }

  CHECK_LT(m9_repeating_timer_smoke_observed_ticks_,
           m9_repeating_timer_smoke_expected_ticks_);
  CHECK(browser_lifecycle_->IsVisible());
  ++m9_repeating_timer_smoke_observed_ticks_;
  std::fprintf(stderr, "%s ordinal=%d\n",
               kWasmBrowserM9RepeatingTimerSmokeTickMarker,
               m9_repeating_timer_smoke_observed_ticks_);
  std::fflush(stderr);
  if (m9_repeating_timer_smoke_observed_ticks_ <
      m9_repeating_timer_smoke_expected_ticks_) {
    return;
  }

  // Keep the real Browser alive after stopping its timer. The delayed UI
  // continuation is intentionally separate from teardown: it proves this
  // timer remains quiescent while its owner is still visible, rather than
  // merely disappearing because BrowserMain started to exit.
  m9_repeating_timer_smoke_timer_.Stop();
  CHECK(m9_repeating_timer_smoke_timeout_timer_.IsRunning());
  content::GetUIThreadTaskRunner({content::BrowserTaskType::kUserInput})
      ->PostDelayedTask(
          FROM_HERE,
          base::BindOnce(
              [](base::WeakPtr<WasmBrowserMainParts> main_parts) {
                if (!main_parts || main_parts->shutdown_requested_) {
                  return;
                }

                CHECK_CURRENTLY_ON(content::BrowserThread::UI);
                CHECK(main_parts->m9_repeating_timer_smoke_started_);
                CHECK(main_parts->m9_repeating_timer_smoke_requested_);
                CHECK_EQ(main_parts->m9_repeating_timer_smoke_observed_ticks_,
                         main_parts->m9_repeating_timer_smoke_expected_ticks_);
                CHECK(!main_parts->m9_repeating_timer_smoke_timer_.IsRunning());
                CHECK(main_parts->m9_repeating_timer_smoke_timeout_timer_
                          .IsRunning());
                CHECK(main_parts->browser_lifecycle_);
                CHECK(!main_parts->browser_lifecycle_->IsShutdownStarted());
                CHECK(main_parts->browser_lifecycle_->IsVisible());

                main_parts->m9_repeating_timer_smoke_timeout_timer_.Stop();
                std::fprintf(
                    stderr, "%s ticks=%d duration_ms=%d\n",
                    kWasmBrowserM9RepeatingTimerSmokeQuiescentMarker,
                    main_parts->m9_repeating_timer_smoke_expected_ticks_,
                    static_cast<int>(
                        kWasmBrowserM9RepeatingTimerSmokeQuiescenceDuration
                            .InMilliseconds()));
                std::fflush(stderr);
                std::fprintf(stderr, "%s ticks=%d\n",
                             kWasmBrowserM9RepeatingTimerSmokePassMarker,
                             main_parts->m9_repeating_timer_smoke_expected_ticks_);
                std::fflush(stderr);
                main_parts->RequestShutdown();
              },
              weak_ptr_factory_.GetWeakPtr()),
          kWasmBrowserM9RepeatingTimerSmokeQuiescenceDuration);
}

void WasmBrowserMainParts::OnM9RepeatingTimerSmokeTimeout() {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!m9_repeating_timer_smoke_started_ || shutdown_requested_) {
    return;
  }

  StopM9RepeatingTimerSmoke();
  std::fprintf(stderr, "%s observed=%d\n",
               kWasmBrowserM9RepeatingTimerSmokeTimeoutMarker,
               m9_repeating_timer_smoke_observed_ticks_);
  std::fflush(stderr);
  LOG(ERROR) << "chrome_wasm M9 repeating timer smoke timed out";
  RequestShutdown();
}

void WasmBrowserMainParts::StopM9RepeatingTimerSmoke() {
  m9_repeating_timer_smoke_timer_.Stop();
  m9_repeating_timer_smoke_timeout_timer_.Stop();
}

void WasmBrowserMainParts::OnBrowserLifecycleShutdownComplete() {
  CHECK(browser_lifecycle_);
  CHECK(browser_lifecycle_->IsShutdownComplete());
  browser_lifecycle_smoke_shutdown_timer_.Stop();
  StopM9RepeatingTimerSmoke();
  const bool lifecycle_smoke = browser_lifecycle_smoke_requested_;
  std::fprintf(stderr, "%s\n",
               lifecycle_smoke ? kWasmBrowserLifecycleSmokePassMarker
                               : kWasmNormalBrowserPassMarker);
  std::fflush(stderr);
  browser_lifecycle_.reset();

  // A direct BrowserView close does not pass through RequestShutdown(). Once
  // the physical destruction barrier has completed, turn it into the same
  // browser-main exit sequence as the timer-driven path.
  if (!shutdown_requested_) {
    RequestShutdown();
    return;
  }
  FinishShutdown();
}

void WasmBrowserMainParts::StartBrowserWindowLifecycleSmokeShutdownTimer() {
  if (!browser_window_lifecycle_smoke_requested_ || shutdown_requested_) {
    return;
  }
  CHECK(browser_window_lifecycle_);
  CHECK(!browser_window_lifecycle_smoke_shutdown_timer_.IsRunning());
  browser_window_lifecycle_smoke_shutdown_timer_.Start(
      FROM_HERE, kWasmBrowserWindowLifecycleSmokeVisibleDuration,
      base::BindOnce(
          &WasmBrowserMainParts::OnBrowserWindowLifecycleSmokeShutdownTimer,
          weak_ptr_factory_.GetWeakPtr()));
}

void WasmBrowserMainParts::OnBrowserWindowLifecycleSmokeShutdownTimer() {
  // A direct BrowserView/host close can already be draining through the
  // lifecycle-owned did-close barrier. In that case its completion will quit
  // the main loop without trying to re-enter the Core close path.
  if (shutdown_requested_ || !browser_window_lifecycle_ ||
      browser_window_lifecycle_->IsShutdownStarted()) {
    return;
  }

  CHECK(browser_window_lifecycle_smoke_requested_);
  CHECK(browser_window_lifecycle_->IsVisible());
  std::fprintf(stderr, "%s\n", kWasmBrowserWindowLifecycleSmokeReadyMarker);
  std::fflush(stderr);
  RequestShutdown();
}

void WasmBrowserMainParts::OnBrowserWindowLifecycleShutdownComplete() {
  CHECK(browser_window_lifecycle_);
  CHECK(browser_window_lifecycle_->IsShutdownComplete());
  browser_window_lifecycle_smoke_shutdown_timer_.Stop();
  browser_window_lifecycle_.reset();

  // A direct BrowserView/host close does not pass through RequestShutdown().
  // Once its did-close barrier has physically destroyed the Core, convert that
  // terminal one-window close into the same browser-main shutdown sequence.
  if (!shutdown_requested_) {
    RequestShutdown();
    return;
  }
  FinishShutdown();
}

#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
void WasmBrowserMainParts::
    StartWasmProfileBookmarkSmokeOrCookieOrHistoryOrShutdown() {
  CHECK(profile_);
  if (!chrome::IsWasmProfilePreferencesBookmarkSmokeEnabled()) {
#if defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    chrome::ReportWasmProfilePreferencesSmokeFailure(
        chrome::WasmProfilePreferencesSmokeFailureStage::kBookmark);
    chrome::ReportWasmProfileLocalStorageSmokeFailure(
        chrome::WasmProfileLocalStorageSmokeFailureStage::kLifecycle);
    RequestShutdown();
#else
    StartWasmProfileCookieSmokeOrHistoryOrShutdown();
#endif
    return;
  }

  // BookmarkModel is deliberately outside WasmProfile's keyed-service graph.
  // Transfer both its model and admission into the profile-owned participant
  // before any asynchronous load or write begins.
  std::optional<chrome::WasmProfilePreferencesBookmarkSmokeInput>
      bookmark_input = chrome::TakeWasmProfilePreferencesBookmarkSmokeInput();
  if (!bookmark_input) {
    chrome::NotifyWasmProfilePreferencesBookmarkSmokeResult(false);
#if defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    chrome::ReportWasmProfileLocalStorageSmokeFailure(
        chrome::WasmProfileLocalStorageSmokeFailureStage::kLifecycle);
#endif
    RequestShutdown();
    return;
  }

  auto profile_io_hold = chrome::TryAcquireWasmProfileStorageProfileIO();
  if (!profile_io_hold) {
    chrome::ReportWasmProfilePreferencesSmokeFailure(
        chrome::WasmProfilePreferencesSmokeFailureStage::kStorage);
    chrome::NotifyWasmProfilePreferencesBookmarkSmokeResult(false);
#if defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    chrome::ReportWasmProfileLocalStorageSmokeFailure(
        chrome::WasmProfileLocalStorageSmokeFailureStage::kStorage);
#endif
    RequestShutdown();
    return;
  }

  if (!profile_->StartBookmarkSmoke(
          std::move(*bookmark_input), std::move(*profile_io_hold),
          base::BindOnce(
              &WasmBrowserMainParts::OnWasmProfileBookmarkSmokeComplete,
              weak_ptr_factory_.GetWeakPtr()))) {
    chrome::NotifyWasmProfilePreferencesBookmarkSmokeResult(false);
#if defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    chrome::ReportWasmProfileLocalStorageSmokeFailure(
        chrome::WasmProfileLocalStorageSmokeFailureStage::kLifecycle);
#endif
    RequestShutdown();
  }
}

void WasmBrowserMainParts::OnWasmProfileBookmarkSmokeComplete(bool success) {
  const bool bookmark_succeeded =
      success && profile_ && profile_->DidBookmarkSmokeSucceed();
  chrome::NotifyWasmProfilePreferencesBookmarkSmokeResult(bookmark_succeeded);
  if (!bookmark_succeeded) {
    LOG(ERROR) << "chrome_wasm BookmarkModel close witness failed";
  }

  if (shutdown_requested_) {
#if defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    chrome::ReportWasmProfileLocalStorageSmokeFailure(
        chrome::WasmProfileLocalStorageSmokeFailureStage::kLifecycle);
#endif
    MaybeStartShutdown();
    return;
  }
  if (bookmark_succeeded) {
    StartWasmProfileCookieSmokeOrHistoryOrShutdown();
  } else {
#if defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    chrome::ReportWasmProfileLocalStorageSmokeFailure(
        chrome::WasmProfileLocalStorageSmokeFailureStage::kLifecycle);
#endif
    RequestShutdown();
  }
}
#endif

#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
void WasmBrowserMainParts::StartWasmProfileCookieSmokeOrHistoryOrShutdown() {
  CHECK(profile_);
  if (!chrome::IsWasmProfilePreferencesCookieSmokeEnabled()) {
#if defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    chrome::ReportWasmProfilePreferencesSmokeFailure(
        chrome::WasmProfilePreferencesSmokeFailureStage::kCookie);
    chrome::ReportWasmProfileLocalStorageSmokeFailure(
        chrome::WasmProfileLocalStorageSmokeFailureStage::kLifecycle);
    RequestShutdown();
#else
    StartWasmProfileHistorySmokeOrShutdown();
#endif
    return;
  }

  // CookieManager is outside WasmProfile's keyed-service graph. Transfer its
  // cloned connection and admission into the profile-owned participant before
  // any asynchronous read/write begins. It retains both through the real
  // SQLite backend-close receipt, then sequences the selected next profile
  // owner before shutdown.
  std::optional<chrome::WasmProfilePreferencesCookieSmokeInput> cookie_input =
      chrome::TakeWasmProfilePreferencesCookieSmokeInput();
  if (!cookie_input) {
    chrome::NotifyWasmProfilePreferencesCookieSmokeResult(false);
#if defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    chrome::ReportWasmProfileLocalStorageSmokeFailure(
        chrome::WasmProfileLocalStorageSmokeFailureStage::kLifecycle);
#endif
    RequestShutdown();
    return;
  }

  auto profile_io_hold = chrome::TryAcquireWasmProfileStorageProfileIO();
  if (!profile_io_hold) {
    chrome::ReportWasmProfilePreferencesSmokeFailure(
        chrome::WasmProfilePreferencesSmokeFailureStage::kStorage);
    chrome::NotifyWasmProfilePreferencesCookieSmokeResult(false);
#if defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    chrome::ReportWasmProfileLocalStorageSmokeFailure(
        chrome::WasmProfileLocalStorageSmokeFailureStage::kStorage);
#endif
    RequestShutdown();
    return;
  }

  if (!profile_->StartCookieSmoke(
          std::move(*cookie_input), std::move(*profile_io_hold),
          base::BindOnce(
              &WasmBrowserMainParts::OnWasmProfileCookieSmokeComplete,
              weak_ptr_factory_.GetWeakPtr()))) {
    chrome::NotifyWasmProfilePreferencesCookieSmokeResult(false);
#if defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    chrome::ReportWasmProfileLocalStorageSmokeFailure(
        chrome::WasmProfileLocalStorageSmokeFailureStage::kLifecycle);
#endif
    RequestShutdown();
  }
}

void WasmBrowserMainParts::OnWasmProfileCookieSmokeComplete(bool success) {
  const bool cookie_succeeded =
      success && profile_ && profile_->DidCookieSmokeSucceed();
  chrome::NotifyWasmProfilePreferencesCookieSmokeResult(cookie_succeeded);
  if (!cookie_succeeded) {
    LOG(ERROR) << "chrome_wasm CookieManager close witness failed";
  }

  // A host/foundation shutdown can arrive while a CookieManager operation or
  // SQLite close is pending. Resume the deferred state machine only after the
  // profile-owned participant has delivered its terminal receipt.
  if (shutdown_requested_) {
#if defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    chrome::ReportWasmProfileLocalStorageSmokeFailure(
        chrome::WasmProfileLocalStorageSmokeFailureStage::kLifecycle);
#endif
    MaybeStartShutdown();
    return;
  }
  if (cookie_succeeded) {
#if defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    StartWasmProfileHistorySmokeOrShutdown();
#elif defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST)
    StartWasmProfileRendererLocalStorageSmokeOrShutdown();
#else
    StartWasmProfileHistorySmokeOrShutdown();
#endif
  } else {
#if defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    chrome::ReportWasmProfileLocalStorageSmokeFailure(
        chrome::WasmProfileLocalStorageSmokeFailureStage::kLifecycle);
#endif
    RequestShutdown();
  }
}
#endif

#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
void WasmBrowserMainParts::StartWasmProfileHistorySmokeOrShutdown() {
  CHECK(profile_);
  if (!chrome::IsWasmProfilePreferencesHistorySmokeEnabled()) {
    RequestShutdown();
    return;
  }

  auto profile_io_hold = chrome::TryAcquireWasmProfileStorageProfileIO();
  if (!profile_io_hold) {
    chrome::ReportWasmProfilePreferencesSmokeFailure(
        chrome::WasmProfilePreferencesSmokeFailureStage::kStorage);
    chrome::NotifyWasmProfilePreferencesHistorySmokeResult(false);
#if defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    chrome::ReportWasmProfileLocalStorageSmokeFailure(
        chrome::WasmProfileLocalStorageSmokeFailureStage::kStorage);
#endif
    RequestShutdown();
    return;
  }

  // Transfer the admission into WasmProfile before the direct HistoryService
  // starts. Its participant owns the service, task tracker, and hold through
  // the HistoryBackend destruction receipt, rather than letting BrowserMain
  // retain a process-global test singleton or a detached I/O holder.
  if (!profile_->StartHistorySmoke(
          std::move(*profile_io_hold),
          base::BindOnce(&WasmBrowserMainParts::OnWasmProfileHistorySmokeComplete,
                         weak_ptr_factory_.GetWeakPtr()))) {
    chrome::NotifyWasmProfilePreferencesHistorySmokeResult(false);
#if defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    chrome::ReportWasmProfileLocalStorageSmokeFailure(
        chrome::WasmProfileLocalStorageSmokeFailureStage::kLifecycle);
#endif
    RequestShutdown();
  }
}

void WasmBrowserMainParts::OnWasmProfileHistorySmokeComplete(bool success) {
  const bool history_succeeded =
      success && profile_ && profile_->DidHistorySmokeSucceed();
  chrome::NotifyWasmProfilePreferencesHistorySmokeResult(history_succeeded);
  if (!history_succeeded) {
    LOG(ERROR) << "chrome_wasm History/Favicons close witness failed";
  }

  // A shutdown can arrive while the History backend is still closing. A
  // second RequestShutdown() would be intentionally ignored, so resume the
  // deferred state machine directly only after the profile-owned participant
  // has delivered its terminal close receipt.
  if (shutdown_requested_) {
#if defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    chrome::ReportWasmProfileLocalStorageSmokeFailure(
        chrome::WasmProfileLocalStorageSmokeFailureStage::kLifecycle);
#endif
    MaybeStartShutdown();
    return;
  }
#if defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  if (history_succeeded) {
    StartWasmProfileRendererLocalStorageSmokeOrShutdown();
  } else {
    chrome::ReportWasmProfileLocalStorageSmokeFailure(
        chrome::WasmProfileLocalStorageSmokeFailureStage::kLifecycle);
    RequestShutdown();
  }
#else
  RequestShutdown();
#endif
}
#endif

#if defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
void WasmBrowserMainParts::
    StartWasmProfileRendererLocalStorageSmokeOrShutdown() {
  CHECK(profile_);
  if (!chrome::IsWasmProfileLocalStorageSmokeEnabled() ||
      !chrome::IsWasmProfileRendererLocalStorageSmokeEnabled()) {
    chrome::ReportWasmProfileLocalStorageSmokeFailure(
        chrome::WasmProfileLocalStorageSmokeFailureStage::kCapability);
    chrome::ReportWasmProfilePreferencesSmokeFailure(
        chrome::WasmProfilePreferencesSmokeFailureStage::kLifecycle);
    RequestShutdown();
    return;
  }

  // Consume the validated raw token before requesting a profile-I/O
  // admission. A failed one-shot transfer must not create an abandoned hold.
  auto local_storage_input = chrome::TakeWasmProfileLocalStorageSmokeInput();
  if (!local_storage_input) {
    chrome::ReportWasmProfilePreferencesSmokeFailure(
        chrome::WasmProfilePreferencesSmokeFailureStage::kLifecycle);
    RequestShutdown();
    return;
  }

  auto profile_io_hold = chrome::TryAcquireWasmProfileStorageProfileIO();
  if (!profile_io_hold) {
    chrome::ReportWasmProfileLocalStorageSmokeFailure(
        chrome::WasmProfileLocalStorageSmokeFailureStage::kStorage);
    chrome::ReportWasmProfilePreferencesSmokeFailure(
        chrome::WasmProfilePreferencesSmokeFailureStage::kStorage);
    RequestShutdown();
    return;
  }

  if (!profile_->StartLocalStorageSmoke(
          std::move(*local_storage_input), std::move(*profile_io_hold),
          base::BindOnce(
              &WasmBrowserMainParts::
                  OnWasmProfileRendererLocalStorageSmokeComplete,
              weak_ptr_factory_.GetWeakPtr()))) {
    chrome::NotifyWasmProfileLocalStorageSmokeOperationResult(false);
    chrome::ReportWasmProfilePreferencesSmokeFailure(
        chrome::WasmProfilePreferencesSmokeFailureStage::kLifecycle);
    RequestShutdown();
  }
}

void WasmBrowserMainParts::
    OnWasmProfileRendererLocalStorageSmokeComplete(bool success) {
  const bool local_storage_succeeded =
      success && profile_ && profile_->DidLocalStorageSmokeSucceed();
  chrome::NotifyWasmProfileLocalStorageSmokeOperationResult(
      local_storage_succeeded);
  if (!local_storage_succeeded) {
    LOG(ERROR) << "chrome_wasm aggregate renderer LocalStorage close witness "
                  "failed";
    chrome::ReportWasmProfilePreferencesSmokeFailure(
        chrome::WasmProfilePreferencesSmokeFailureStage::kLifecycle);
  }

  if (shutdown_requested_) {
#if defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    chrome::ReportWasmProfileDatabaseSmokeFailure(
        chrome::WasmProfileDatabaseSmokeFailureStage::kLifecycle);
#endif
    MaybeStartShutdown();
    return;
  }
#if defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  if (local_storage_succeeded) {
    StartWasmProfileDatabaseSmokeOrShutdown();
  } else {
    chrome::ReportWasmProfileDatabaseSmokeFailure(
        chrome::WasmProfileDatabaseSmokeFailureStage::kLifecycle);
    RequestShutdown();
  }
#else
  RequestShutdown();
#endif
}
#endif

void WasmBrowserMainParts::FinishShutdown() {
  CHECK(shutdown_requested_);
  CHECK(!browser_lifecycle_);
  CHECK(!browser_window_lifecycle_);

#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  if (profile_ && profile_->HasActiveBookmarkSmoke()) {
    profile_->CancelBookmarkSmokeForShutdown();
    return;
  }
#endif
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  if (profile_ && profile_->HasActiveCookieSmoke()) {
    profile_->CancelCookieSmokeForShutdown();
    return;
  }
#endif
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  // Browser lifecycle completions can enter here directly. Preserve the same
  // no-profile-teardown-before-backend-close rule as MaybeStartShutdown().
  if (profile_ && profile_->HasActiveHistorySmoke()) {
    profile_->CancelHistorySmokeForShutdown();
    return;
  }
#endif

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  // Lifecycle completions may enter FinishShutdown() directly. Keep the same
  // no-profile-teardown-before-database-task rule as MaybeStartShutdown().
  if (profile_ && profile_->HasActiveDatabaseSmoke()) {
    profile_->CancelDatabaseSmokeForShutdown();
    return;
  }
#endif

#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  if (profile_ && profile_->HasActiveLocalStorageSmoke()) {
    profile_->CancelLocalStorageSmokeForShutdown();
    return;
  }
#endif

#if defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST)
  // FinishShutdown() can be reached directly from a browser lifecycle result.
  // Preserve the same selected-bucket close-receipt gate as MaybeStartShutdown.
  if (profile_ && profile_->HasActiveIndexedDBSmoke()) {
    profile_->CancelIndexedDBSmokeForShutdown();
    return;
  }
#endif

  if (profile_) {
    // Browser/Core destruction completed before this method can run. Shut the
    // profile's keyed services down first, then keep the UI loop alive until
    // the JsonPrefStore has committed and strictly read back Preferences on
    // its file sequence. Do not use a nested RunLoop or block this sequence.
#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
    // Seal the real BrowserContext map before any shutdown notification can
    // run a late partition accessor. The probe has already received direct
    // LocalStorage map-update/close, renderer IndexedDB selected-bucket-close,
    // complete default-context close, and CookieManager SQLite-row-readback/
    // close receipts, and retains its explicit admission from construction
    // through the later synchronous map-drop boundary. A later re-entry sees
    // the already-pending/completed fence and does not duplicate either
    // one-shot observation.
    if (!profile_->IsPrefsShutdownFencePending() &&
        !profile_->HasPrefsShutdownFenceCompleted()) {
      chrome::NotifyWasmPersistentDefaultPartitionShutdownProbeCreationSealed(
          profile_.get());
    }
#endif
    profile_->Shutdown();
#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
    if (!profile_->IsPrefsShutdownFencePending() &&
        !profile_->HasPrefsShutdownFenceCompleted()) {
      chrome::NotifyWasmPersistentDefaultPartitionShutdownProbeMapDropped(
          profile_.get());
    }
#endif
    if (!profile_->HasPrefsShutdownFenceCompleted()) {
      if (!profile_->IsPrefsShutdownFencePending()) {
        profile_->BeginPrefsShutdownFence(base::BindOnce(
            [](base::WeakPtr<WasmBrowserMainParts> main_parts, bool success) {
              if (!main_parts) {
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
                chrome::NotifyWasmProfilePreferencesSmokeFenceResult(false);
#endif
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
                chrome::NotifyWasmProfileDatabaseSmokeFenceResult(false);
#endif
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
                chrome::NotifyWasmProfileLocalStorageSmokeFenceResult(false);
#endif
#if defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST)
                chrome::NotifyWasmProfileIndexedDBSmokeFenceResult(false);
#endif
#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE)
                chrome::NotifyWasmPersistentDefaultPartitionPolicyProbePrefsFenceResult(
                    false);
#endif
#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
                chrome::NotifyWasmPersistentDefaultPartitionShutdownProbePrefsFenceResult(
                    false);
#endif
                return;
              }
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
              chrome::NotifyWasmProfilePreferencesSmokeFenceResult(success);
#endif
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
              chrome::NotifyWasmProfileDatabaseSmokeFenceResult(success);
#endif
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
              chrome::NotifyWasmProfileLocalStorageSmokeFenceResult(success);
#endif
#if defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST)
              chrome::NotifyWasmProfileIndexedDBSmokeFenceResult(success);
#endif
              if (!success) {
                LOG(ERROR) << "chrome_wasm Preferences shutdown write/readback "
                              "fence failed";
              }
              // Re-enter only after the UI-sequence state changed to a
              // terminal result. This is the sole path that may quit the UI
              // loop after a live profile has begun shutdown.
              main_parts->FinishShutdown();
            },
            weak_ptr_factory_.GetWeakPtr()));
      }
      return;
    }
    const bool prefs_shutdown_fence_succeeded =
        profile_->DidPrefsShutdownFenceSucceed();
    if (!prefs_shutdown_fence_succeeded) {
      LOG(ERROR) << "chrome_wasm Preferences shutdown write/readback fence "
                    "failed";
    }
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    // Destroy the Profile before closing new profile-I/O admission. In ordinary
    // M7 artifacts every admitted I/O holder is terminal at this point. The
    // dedicated outstanding-I/O refusal artifact instead deliberately keeps
    // the admission for its completed database task live, so BeginQuiesce()
    // must report waiting rather than select either outer drain operation.
    // Only ChromeMain may complete that source-selected admission after it
    // records the first refusal, and it then selects explicit fail-closed
    // cleanup rather than a clean handoff.
    // This notification publishes a quiescence observation only; it never
    // acknowledges a clean backend handoff.
#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE)
    // The policy witness may use a clean V4 handoff only after the exact
    // configuration observation and this strict Preferences fence succeeded.
    // Any failed configuration, disabled protocol, or admission refusal must
    // select a sticky fail-closed shutdown before the outer drain. Marker state
    // alone is not an ownership signal for WasmProfileStorageState.
    chrome::NotifyWasmPersistentDefaultPartitionPolicyProbePrefsFenceResult(
        prefs_shutdown_fence_succeeded);
#endif
#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
    chrome::NotifyWasmPersistentDefaultPartitionShutdownProbePrefsFenceResult(
        prefs_shutdown_fence_succeeded);
    const bool shutdown_probe_can_use_failure_retirement =
        chrome::CanWasmPersistentDefaultPartitionShutdownProbeUseFailureRetirement();
#endif
    profile_.reset();
#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE)
    // Profile destruction can still run source-selected keyed-service teardown.
    // Recheck the policy-query counter after that boundary before selecting a
    // clean handoff; any extra query must instead retain the lease fail-closed.
    const bool policy_probe_can_clean_shutdown =
        chrome::CanWasmPersistentDefaultPartitionPolicyProbeUseCleanShutdown();
    const bool profile_shutdown_notified =
        policy_probe_can_clean_shutdown
            ? chrome::NotifyWasmProfileStorageProfileShutdown()
            : chrome::NotifyWasmProfileStorageProfileShutdownFailClosed();
#elif defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
    // Dropping BrowserContext's map is not a whole-StoragePartition close
    // receipt. Preserve the V4 lease until such receipts exist rather than
    // turning this structural observation into a clean persistence handoff.
    const bool profile_shutdown_notified =
        chrome::NotifyWasmProfileStorageProfileShutdownFailClosed();
#else
    const bool profile_shutdown_notified =
        chrome::NotifyWasmProfileStorageProfileShutdown();
#endif
    [[maybe_unused]] bool smoke_allows_storage_lifecycle =
        prefs_shutdown_fence_succeeded && profile_shutdown_notified;
#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE)
    smoke_allows_storage_lifecycle &= policy_probe_can_clean_shutdown;
#endif
#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
    // No amount of local success authorizes clean lifecycle reporting for a
    // map-only observation. ChromeMain will validate the exact sealed,
    // lease-retained failure-retirement receipt instead.
    smoke_allows_storage_lifecycle = false;
    if (!shutdown_probe_can_use_failure_retirement) {
      LOG(ERROR) << "chrome_wasm persistent default StoragePartition shutdown "
                    "probe did not reach its map-drop/fence boundary";
    }
#endif
    if (!prefs_shutdown_fence_succeeded) {
      // The failed preference holder is now visible to the outer failure
      // retirement permit. Do not report a smoke lifecycle success or let a
      // normal lease-release drain run.
      LOG(ERROR) << "chrome_wasm will fail-close its OPFS profile backend "
                    "after a failed Preferences shutdown write/readback "
                    "fence";
      smoke_allows_storage_lifecycle = false;
    }
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    if (chrome::IsWasmProfilePreferencesBookmarkSmokeEnabled() &&
        !chrome::DidWasmProfilePreferencesBookmarkSmokeSucceed()) {
      // This profile-owned direct BookmarkModel must have received its local
      // write result, destroyed its model/storage owner, and completed its
      // admitted I/O before a clean handoff can be considered.
      smoke_allows_storage_lifecycle = false;
    }
#endif
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    if (chrome::IsWasmProfilePreferencesCookieSmokeEnabled() &&
        !chrome::DidWasmProfilePreferencesCookieSmokeSucceed()) {
      // The CookieManager probe has a real SQLite backend-close fence. Its
      // failed hold stays visible to the outer failure-retirement permit.
      smoke_allows_storage_lifecycle = false;
    }
#endif
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    if (chrome::IsWasmProfilePreferencesHistorySmokeEnabled() &&
        !chrome::DidWasmProfilePreferencesHistorySmokeSucceed()) {
      // This direct, test-only HistoryService is outside WasmProfile's
      // keyed-service graph. Its backend-destroy callback must have closed
      // History and Favicons before a clean handoff can be considered.
      smoke_allows_storage_lifecycle = false;
    }
#endif
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    if (chrome::IsWasmProfileDatabaseSmokeEnabled() &&
        !chrome::DidWasmProfileDatabaseSmokeSucceed()) {
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_OUTSTANDING_IO_REFUSAL_TEST)
      // The controlled verify-b task has returned and closed its own database
      // resources, but this diagnostic intentionally preserves its admission.
      // The outer seam must refuse before a backend-drain or retirement
      // transaction; it must not misclassify this hold as terminal failure.
      smoke_allows_storage_lifecycle = false;
#else
      // A database task failure has already requested normal shutdown. Its
      // terminal failed hold must select failure retirement, never a clean
      // handoff or LEASE_RELEASED receipt.
      smoke_allows_storage_lifecycle = false;
#endif
    }
#endif
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    if (chrome::IsWasmProfileLocalStorageSmokeEnabled() &&
        !chrome::DidWasmProfileLocalStorageSmokeSucceed()) {
      // A LocalStorage close result failure must select failure retirement;
      // it cannot become a V4 storage handoff or lease-success marker.
      smoke_allows_storage_lifecycle = false;
    }
#endif
#if defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST)
    if (chrome::IsWasmProfileIndexedDBSmokeEnabled() &&
        !chrome::DidWasmProfileIndexedDBSmokeSucceed()) {
      // A selected-bucket close result failure must select failure retirement;
      // it cannot become a V4 handoff or a lease-success marker.
      smoke_allows_storage_lifecycle = false;
    }
#endif
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    chrome::NotifyWasmProfilePreferencesSmokeStorageLifecycle(
        smoke_allows_storage_lifecycle);
#endif
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    chrome::NotifyWasmProfileDatabaseSmokeStorageLifecycle(
        smoke_allows_storage_lifecycle);
#endif
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    chrome::NotifyWasmProfileLocalStorageSmokeStorageLifecycle(
        smoke_allows_storage_lifecycle);
#endif
#if defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST)
    chrome::NotifyWasmProfileIndexedDBSmokeStorageLifecycle(
        smoke_allows_storage_lifecycle);
#endif
#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE)
    chrome::NotifyWasmPersistentDefaultPartitionPolicyProbeStorageLifecycle(
        smoke_allows_storage_lifecycle);
#endif
    if (!profile_shutdown_notified) {
      // Do not synthesize a clean handoff. The outer scoped drain observes
      // this missing acknowledgement, retains the lease, and changes the
      // process result to non-normal.
      LOG(ERROR) << "chrome_wasm could not complete its profile storage "
                    "lifecycle";
    }
#else
    // Normal Chrome's profile path is volatile. The completed fence verifies
    // orderly write/readback shutdown but does not establish reload durability.
    if (!prefs_shutdown_fence_succeeded) {
      chrome::RecordWasmProfileShutdownFailure();
    }
    profile_.reset();
#endif
  }

  if (main_message_loop_quit_closure_) {
    main_message_loop_quit_closure_.Run();
  }
}

void WasmBrowserMainParts::ShutdownFoundation() {
  if (foundation_shutdown_) {
    return;
  }
  foundation_shutdown_ = true;
  browser_lifecycle_smoke_shutdown_timer_.Stop();
  browser_window_lifecycle_smoke_shutdown_timer_.Stop();
  StopM9RepeatingTimerSmoke();

  // Profile's interlocked keyed-service shutdown includes BrowserManagerService.
  // Never let it be the mechanism that destroys a Core still bound to the
  // Views host: the lifecycle's physical-destruction barrier must have run
  // while the UI loop and profile were still live.
  CHECK(!browser_lifecycle_);
  CHECK(!browser_window_lifecycle_);

  if (browser_process_) {
    browser_process_->EndSession();
  }
  if (profile_) {
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    // The normal UI-loop path waits for each profile-owned participant. This
    // fallback has no loop left to service them, so retain any active model or
    // backend close together with its ProfileIOHold. ChromeMain must observe
    // the resulting outstanding admission and refuse before touching V4.
    if (profile_->HasActiveBookmarkSmoke()) {
      profile_->QuarantineBookmarkSmokeForFailureShutdown();
    }
#endif
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    if (profile_->HasActiveCookieSmoke()) {
      profile_->QuarantineCookieSmokeForFailureShutdown();
    }
#endif
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    if (profile_->HasActiveHistorySmoke()) {
      profile_->QuarantineHistorySmokeForFailureShutdown();
    }
#endif
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    if (profile_->HasActiveDatabaseSmoke()) {
      profile_->QuarantineDatabaseSmokeForFailureShutdown();
    }
#endif
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    if (profile_->HasActiveLocalStorageSmoke()) {
      profile_->QuarantineLocalStorageSmokeForFailureShutdown();
    }
#endif
#if defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST)
    if (profile_->HasActiveIndexedDBSmoke()) {
      profile_->QuarantineIndexedDBSmokeForFailureShutdown();
    }
#endif
#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
    // The normal FinishShutdown() path completes this retained admission only
    // after observing the map drop. With no UI loop left, make the probe's
    // admission terminal-failed before profile destruction selects the same
    // mandatory V4 fail-closed retirement path.
    chrome::FailWasmPersistentDefaultPartitionShutdownProbe();
#endif
    profile_->Shutdown();
    // A normal FinishShutdown() releases the profile before it quits the UI
    // loop. Reaching this fallback means startup or the write/readback fence
    // failed before that terminal handoff.
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    // The UI loop is already gone, so this fallback cannot await or certify
    // the Preferences/smoke lifecycle.
    // It must never derive a clean handoff from a merely terminal profile epoch.
    // Once all admitted I/O is terminal,
    // ChromeMain may close private OPFS handles while retaining the lease.
    // chrome_wasm retains its OPFS profile lease because an outstanding
    // History/Favicons close instead makes ChromeMain refuse before any
    // backend transaction. Neither outcome is a clean handoff.
    ResetProfileThenFailCloseM7ProfileStorage(profile_);
#else
    chrome::RecordWasmProfileShutdownFailure();
    LOG(ERROR) << "chrome_wasm releases its incomplete volatile profile "
                  "after an incomplete Preferences shutdown fence";
    profile_.reset();
#endif
  }
  if (browser_process_) {
    browser_process_.reset();
  }
  if (resource_bundle_initialized_) {
    ui::ResourceBundle::CleanupSharedInstance();
    resource_bundle_initialized_ = false;
  }
}
