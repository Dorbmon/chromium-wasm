// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_main_parts.h"

#include <string>

#include "base/check.h"
#include "base/command_line.h"
#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "base/functional/bind.h"
#include "base/logging.h"
#include "base/path_service.h"
#include "base/run_loop.h"
#include "build/build_config.h"
#include "chrome/browser/ui/actions/chrome_actions.h"
#include "chrome/browser/ui/browser_manager_service_factory.h"
#include "chrome/browser/ui/color/chrome_color_mixers.h"
#include "chrome/browser/wasm/wasm_browser_manager.h"
#include "chrome/browser/wasm/wasm_browser_process.h"
#include "chrome/browser/wasm/wasm_profile.h"
#include "chrome/browser/wasm/wasm_browser_view_smoke.h"
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
constexpr char kWasmTabCoreSmokeSwitch[] = "wasm-tab-core-smoke";
constexpr char kRequiredAssets[][24] = {
    "chrome_100_percent.pak",
    "chrome_200_percent.pak",
    "resources.pak",
    "locales/en-US.pak",
    "icudtl.dat",
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

  // BrowserThread::IO and ThreadPool are live at this stage. The profile's
  // explicit I/O runner may therefore be created without racing startup.
  profile_ = std::make_unique<WasmProfile>(profile_path);
  if (!profile_) {
    return CHROME_RESULT_CODE_MISSING_DATA;
  }

  // Exercise the factory while the profile is live. Browser::Create() will
  // retrieve this same manager when the real window lifecycle is selected.
  CHECK(BrowserManagerServiceFactory::GetForProfile(profile_.get()));

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

  // Browser::Create() currently requires a keyed BrowserManagerService graph.
  // Launching it before the corresponding source-selected shutdown sequence
  // exists would risk profile/data corruption. Fail explicitly rather than
  // keeping the host page alive without a real Chrome browser window.
  LOG(ERROR)
      << "chrome_wasm M6 foundation initialized, but the source-selected "
         "Chrome Views browser lifecycle is not available yet";
  return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
}

void WasmBrowserMainParts::WillRunMainMessageLoop(
    std::unique_ptr<base::RunLoop>& run_loop) {
  main_message_loop_quit_closure_ = run_loop->QuitClosure();
  if (shutdown_requested_) {
    main_message_loop_quit_closure_.Run();
  }
}

void WasmBrowserMainParts::PostMainMessageLoopRun() {
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
  shutdown_requested_ = true;
  if (main_message_loop_quit_closure_) {
    main_message_loop_quit_closure_.Run();
  }
}

void WasmBrowserMainParts::ShutdownFoundation() {
  if (foundation_shutdown_) {
    return;
  }
  foundation_shutdown_ = true;

  if (profile_) {
    profile_->Shutdown();
    profile_.reset();
  }
  if (browser_process_) {
    browser_process_->EndSession();
    browser_process_.reset();
  }
  if (resource_bundle_initialized_) {
    ui::ResourceBundle::CleanupSharedInstance();
    resource_bundle_initialized_ = false;
  }
}
