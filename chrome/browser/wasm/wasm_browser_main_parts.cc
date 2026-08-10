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
#include "chrome/browser/wasm/wasm_browser_host_input.h"
#include "chrome/browser/wasm/wasm_browser_host_lifecycle.h"
#include "chrome/browser/wasm/wasm_browser_lifecycle.h"
#include "chrome/browser/wasm/wasm_browser_manager.h"
#include "chrome/browser/wasm/wasm_m6_controlled_https_test_mode.h"
#include "chrome/browser/wasm/wasm_browser_process.h"
#include "chrome/browser/wasm/wasm_browser_smoke.h"
#include "chrome/browser/wasm/wasm_settings_ui.h"
#include "chrome/browser/wasm/wasm_version_ui.h"
#include "chrome/browser/wasm/wasm_profile.h"
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
constexpr char kWasmBrowserLifecycleSmokeSwitch[] =
    "wasm-browser-lifecycle-smoke";
constexpr char kWasmBrowserHostAcceleratorSmokeSwitch[] =
    "wasm-browser-host-accelerator-smoke";
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

  base::FilePath user_data_directory;
  if (!base::PathService::Get(chrome::DIR_USER_DATA, &user_data_directory)) {
    LOG(ERROR) << "chrome_wasm could not resolve its volatile profile root";
    return CHROME_RESULT_CODE_MISSING_DATA;
  }

  const base::FilePath profile_path =
      user_data_directory.AppendASCII("Default");
  if (!base::CreateDirectory(profile_path)) {
    LOG(ERROR) << "chrome_wasm could not create its volatile profile path";
    return CHROME_RESULT_CODE_MISSING_DATA;
  }

  // Profile's base constructor marks its BrowserContext live. Register the
  // Wasm-owned factory first so its keyed-service lifecycle can be created and
  // shut down with the profile rather than arriving lazily after that point.
  EnsureWasmBrowserKeyedServiceFactoriesBuilt();

  // The source-selected WebUI configurations are process-global and must
  // exist before the first Wasm WebContents is created. They intentionally
  // add only VersionUI plus the explicit Wasm settings bootstrap rather than
  // the desktop Chrome WebUI registry.
  chrome::EnsureWasmVersionWebUIConfigRegistered();
  chrome::EnsureWasmSettingsWebUIConfigRegistered();

  // BrowserThread::IO and ThreadPool are live at this stage. The profile's
  // explicit I/O runner may therefore be created without racing startup.
  profile_ = std::make_unique<WasmProfile>(profile_path);
  if (!profile_) {
    return CHROME_RESULT_CODE_MISSING_DATA;
  }

  // Keep Chrome's bounded physical-key ABI separate from Content Shell's test
  // bridge. It must capture Ozone's injector while the UI sequence and Ozone
  // platform are live, and PostMainMessageLoopRun releases it before Ozone.
  if (!chrome::InitializeWasmBrowserHostInput()) {
    LOG(ERROR) << "chrome_wasm could not create its Ozone input injector";
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
  const bool browser_host_accelerator_smoke =
      base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserHostAcceleratorSmokeSwitch);
  if (browser_lifecycle_smoke || browser_host_accelerator_smoke) {
    CHECK(!(browser_lifecycle_smoke && browser_host_accelerator_smoke));
    CHECK(!browser_lifecycle_);
    CHECK(!browser_lifecycle_smoke_requested_);
    CHECK(!browser_window_lifecycle_);
    browser_lifecycle_smoke_requested_ = true;
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
  // modal, menu, history, or Settings lifecycle.
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
  // Shut down the lifecycle request ABI first: it owns a callback into these
  // main-parts and must become inert before the profile/Ozone teardown path.
  chrome::ShutdownWasmBrowserHostLifecycle();
  // Invalidate the host ABI and release its SystemInputInjector while its
  // Ozone owner is still live. Queued records carry a generation token and
  // safely drop after this point.
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
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kWasmBrowserHostAcceleratorSmokeSwitch)) {
    // Install the UI verifier before reporting READY: host stdout callbacks
    // may synchronously invoke the exported ABI in response to that marker.
    browser_lifecycle_->StartHostAcceleratorSmoke();
    std::fprintf(stderr, "%s\n", kWasmBrowserHostAcceleratorSmokeReadyMarker);
    std::fflush(stderr);
    return;
  }
  std::fprintf(stderr, "%s\n", kWasmBrowserLifecycleSmokeReadyMarker);
  std::fflush(stderr);
  RequestShutdown();
}

void WasmBrowserMainParts::OnBrowserLifecycleShutdownComplete() {
  CHECK(browser_lifecycle_);
  CHECK(browser_lifecycle_->IsShutdownComplete());
  browser_lifecycle_smoke_shutdown_timer_.Stop();
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
    profile_.reset();
  }
  if (browser_process_) {
    browser_process_.reset();
  }
  if (resource_bundle_initialized_) {
    ui::ResourceBundle::CleanupSharedInstance();
    resource_bundle_initialized_ = false;
  }
}
