// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_main_parts.h"

#include <cstdio>
#include <string>

#include "base/check.h"
#include "base/command_line.h"
#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "base/functional/bind.h"
#include "base/logging.h"
#include "base/path_service.h"
#include "base/run_loop.h"
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
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST)
// GN's include checker does not evaluate this target-specific definition.
#include "chrome/browser/wasm/wasm_profile_preferences_smoke.h"  // nogncheck
#endif
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST)
// GN's include checker does not evaluate this target-specific definition.
#include "chrome/browser/wasm/wasm_profile_database_smoke.h"  // nogncheck
#endif
#include "chrome/browser/wasm/wasm_profile_storage.h"
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
constexpr char kWasmBrowserViewSmokeSwitch[] = "wasm-browser-view-smoke";
constexpr char kWasmBrowserWindowCoreSmokeSwitch[] =
    "wasm-browser-window-core-smoke";
constexpr char kWasmBrowserSmokeSwitch[] = "wasm-browser-smoke";
constexpr char kWasmBrowserControlledHttpsSmokeSwitch[] =
    "wasm-browser-controlled-https-smoke";
constexpr char kWasmBrowserM9WispRecoverySmokeSwitch[] =
    "wasm-browser-m9-wisp-recovery-smoke";
constexpr char kWasmBrowserM9RepeatingTimerSmokeSwitch[] =
    "wasm-browser-m9-repeating-timer-smoke";
constexpr char kWasmBrowserLifecycleSmokeSwitch[] =
    "wasm-browser-lifecycle-smoke";
constexpr char kWasmBrowserDevToolsProtocolSmokeSwitch[] =
    "wasm-browser-devtools-protocol-smoke";
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
constexpr char kWasmNormalBrowserReadyMarker[] =
    "CHROMIUM_WASM_M6_NORMAL_BROWSER:READY";
constexpr char kWasmNormalBrowserPassMarker[] =
    "CHROMIUM_WASM_M6_NORMAL_BROWSER:PASS";
constexpr base::TimeDelta kWasmBrowserLifecycleSmokeVisibleDuration =
    base::Milliseconds(250);
constexpr int kWasmBrowserM9RepeatingTimerSmokeTickCount = 3;
constexpr base::TimeDelta kWasmBrowserM9RepeatingTimerSmokeInterval =
    base::Milliseconds(50);
constexpr base::TimeDelta kWasmBrowserM9RepeatingTimerSmokeQuiescenceDuration =
    base::Milliseconds(200);
constexpr base::TimeDelta kWasmBrowserM9RepeatingTimerSmokeTimeout =
    base::Seconds(5);
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
constexpr char kWasmBrowserWindowViewSmokeSwitch[] =
    "wasm-browser-window-view-smoke";
constexpr char kWasmBrowserWindowLifecycleSmokeSwitch[] =
    "wasm-browser-window-lifecycle-smoke";
constexpr char kWasmBrowserWindowLifecycleSmokeReadyMarker[] =
    "CHROMIUM_WASM_M6_BROWSER_WINDOW_LIFECYCLE:READY";
constexpr base::TimeDelta kWasmBrowserWindowLifecycleSmokeVisibleDuration =
    base::Milliseconds(250);
constexpr char kWasmTabCoreSmokeSwitch[] = "wasm-tab-core-smoke";
constexpr char kRequiredAssets[][24] = {
    "chrome_100_percent.pak",
    "chrome_200_percent.pak",
    "resources.pak",
    "locales/en-US.pak",
    "icudtl.dat",
    "Roboto-Regular.ttf",
};

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
  if (!chrome::IsWasmProfileStorageMounted()) {
    LOG(ERROR) << "chrome_wasm profile storage is not mounted";
    return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
  }

  base::FilePath user_data_directory;
  if (!base::PathService::Get(chrome::DIR_USER_DATA, &user_data_directory)) {
    LOG(ERROR) << "chrome_wasm could not resolve its mounted profile root";
    return CHROME_RESULT_CODE_MISSING_DATA;
  }

  const base::FilePath profile_path =
      user_data_directory.AppendASCII("Default");
  if (!base::CreateDirectory(profile_path)) {
    LOG(ERROR) << "chrome_wasm could not create its mounted profile path";
    return CHROME_RESULT_CODE_MISSING_DATA;
  }

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

  // BrowserThread::IO and ThreadPool are live at this stage. The profile's
  // explicit I/O runner may therefore be created without racing startup.
  profile_ = std::make_unique<WasmProfile>(profile_path);
  if (!profile_) {
    return CHROME_RESULT_CODE_MISSING_DATA;
  }
  if (!chrome::NotifyWasmProfileStorageProfileCreated()) {
    LOG(ERROR) << "chrome_wasm could not admit its profile storage lifecycle";
    return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
  }

#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST)
  // The M7 two-fresh-module Preferences acceptance intentionally stops here:
  // its native PrefService action runs after profile admission, but before any
  // host input, clipboard, pointer, storage-estimate, Browser, WebContents,
  // or BrowserWindow setup. RequestShutdown() lets the ordinary asynchronous
  // JsonPrefStore fence and Chrome-owned scoped OPFS drain prove the handoff.
  if (chrome::IsWasmProfilePreferencesSmokeEnabled()) {
    if (!chrome::StartWasmProfilePreferencesSmoke(profile_->GetPrefs())) {
      return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
    }
    RequestShutdown();
    return content::RESULT_CODE_NORMAL_EXIT;
  }
#endif

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST)
  // The M7 three-fresh-module SQLite/LevelDB acceptance stops after profile
  // admission, before host input, Browser, WebContents, or BrowserWindow
  // setup. Its completion requests ordinary asynchronous profile shutdown only
  // after the single database runner has closed and destroyed both engines.
  if (chrome::IsWasmProfileDatabaseSmokeEnabled()) {
    if (!chrome::StartWasmProfileDatabaseSmoke(
            profile_->GetPath(),
            base::BindOnce(&WasmBrowserMainParts::RequestShutdown,
                           weak_ptr_factory_.GetWeakPtr()))) {
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
  const bool browser_m9_repeating_timer_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserM9RepeatingTimerSmokeSwitch);
  const bool browser_devtools_protocol_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserDevToolsProtocolSmokeSwitch);
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

  m9_repeating_timer_smoke_started_ = true;
  m9_repeating_timer_smoke_observed_ticks_ = 0;
  m9_repeating_timer_smoke_timer_.Start(
      FROM_HERE, kWasmBrowserM9RepeatingTimerSmokeInterval,
      base::BindRepeating(&WasmBrowserMainParts::OnM9RepeatingTimerSmokeTick,
                          weak_ptr_factory_.GetWeakPtr()));
  m9_repeating_timer_smoke_timeout_timer_.Start(
      FROM_HERE, kWasmBrowserM9RepeatingTimerSmokeTimeout,
      base::BindOnce(&WasmBrowserMainParts::OnM9RepeatingTimerSmokeTimeout,
                     weak_ptr_factory_.GetWeakPtr()));
  std::fprintf(stderr, "%s ticks=%d interval_ms=%d\n",
               kWasmBrowserM9RepeatingTimerSmokeReadyMarker,
               kWasmBrowserM9RepeatingTimerSmokeTickCount,
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
           kWasmBrowserM9RepeatingTimerSmokeTickCount);
  CHECK(browser_lifecycle_->IsVisible());
  ++m9_repeating_timer_smoke_observed_ticks_;
  std::fprintf(stderr, "%s ordinal=%d\n",
               kWasmBrowserM9RepeatingTimerSmokeTickMarker,
               m9_repeating_timer_smoke_observed_ticks_);
  std::fflush(stderr);
  if (m9_repeating_timer_smoke_observed_ticks_ <
      kWasmBrowserM9RepeatingTimerSmokeTickCount) {
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
                         kWasmBrowserM9RepeatingTimerSmokeTickCount);
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
                    kWasmBrowserM9RepeatingTimerSmokeTickCount,
                    static_cast<int>(
                        kWasmBrowserM9RepeatingTimerSmokeQuiescenceDuration
                            .InMilliseconds()));
                std::fflush(stderr);
                std::fprintf(stderr, "%s ticks=%d\n",
                             kWasmBrowserM9RepeatingTimerSmokePassMarker,
                             kWasmBrowserM9RepeatingTimerSmokeTickCount);
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

void WasmBrowserMainParts::FinishShutdown() {
  CHECK(shutdown_requested_);
  CHECK(!browser_lifecycle_);
  CHECK(!browser_window_lifecycle_);

  if (profile_) {
    // Browser/Core destruction completed before this method can run. Shut the
    // profile's keyed services down first, then keep the UI loop alive until
    // the JsonPrefStore has committed and strictly read back Preferences on
    // its file sequence. Do not use a nested RunLoop or block this sequence.
    profile_->Shutdown();
    if (!profile_->HasPersistentPrefsShutdownFenceCompleted()) {
      if (!profile_->IsPersistentPrefsShutdownFencePending()) {
        profile_->BeginPersistentPrefsShutdownFence(base::BindOnce(
            [](base::WeakPtr<WasmBrowserMainParts> main_parts, bool success) {
              if (!main_parts) {
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST)
                chrome::NotifyWasmProfilePreferencesSmokeFenceResult(false);
#endif
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST)
                chrome::NotifyWasmProfileDatabaseSmokeFenceResult(false);
#endif
                return;
              }
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST)
              chrome::NotifyWasmProfilePreferencesSmokeFenceResult(success);
#endif
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST)
              chrome::NotifyWasmProfileDatabaseSmokeFenceResult(success);
#endif
              if (!success) {
                LOG(ERROR) << "chrome_wasm Preferences persistence fence "
                              "failed";
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
    if (!profile_->DidPersistentPrefsShutdownFenceSucceed()) {
      // ShutdownFoundation intentionally withholds the storage lifecycle
      // acknowledgement. ChromeMain's scoped backend drain will then
      // retain the lease and turn this otherwise normal Content result into a
      // non-normal process exit.
      LOG(ERROR) << "chrome_wasm will retain its OPFS profile lease after a "
                    "failed Preferences persistence fence";
    } else {
      // Complete the Chrome-owned profile handoff before quitting the UI loop.
      // PostMainMessageLoopRun must never be the first place that releases
      // this Profile or acknowledges its storage lifecycle: ContentMain's
      // outer scoped drain follows that hook and needs this ordering.
      profile_.reset();
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST)
      if (chrome::IsWasmProfileDatabaseSmokeEnabled() &&
          !chrome::DidWasmProfileDatabaseSmokeSucceed()) {
        // A database task failure has already requested normal shutdown, but
        // must not turn into a storage handoff. Retain the created-but-not-
        // shutdown lifecycle state so ChromeMain's scoped drain fails closed,
        // converts the otherwise normal result, and emits no LEASE_RELEASED.
        chrome::NotifyWasmProfileDatabaseSmokeStorageLifecycle(false);
      } else {
#endif
      const bool storage_lifecycle_notified =
          chrome::NotifyWasmProfileStorageProfileShutdown();
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST)
      chrome::NotifyWasmProfilePreferencesSmokeStorageLifecycle(
          storage_lifecycle_notified);
#endif
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST)
        chrome::NotifyWasmProfileDatabaseSmokeStorageLifecycle(
            storage_lifecycle_notified);
#endif
      if (!storage_lifecycle_notified) {
        // Do not synthesize a clean handoff. The outer scoped drain observes
        // this missing acknowledgement, retains the lease, and changes the
        // process result to non-normal.
        LOG(ERROR) << "chrome_wasm could not complete its profile storage "
                      "lifecycle";
      }
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST)
      }
#endif
    }
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
    profile_->Shutdown();
    // A normal FinishShutdown() releases the profile and acknowledges storage
    // before it quits the UI loop. Reaching this fallback means startup or
    // persistence failed before that fence, so retain the leased OPFS backend
    // by neither resetting |profile_| nor notifying storage.
    LOG(ERROR) << "chrome_wasm retains its OPFS profile lease because "
                  "Preferences did not pass their shutdown fence";
  }
  if (browser_process_) {
    browser_process_.reset();
  }
  if (resource_bundle_initialized_) {
    ui::ResourceBundle::CleanupSharedInstance();
    resource_bundle_initialized_ = false;
  }
}
