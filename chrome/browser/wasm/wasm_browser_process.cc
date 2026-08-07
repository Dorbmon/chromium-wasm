// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_process.h"

#include <memory>
#include <utility>

#include "base/check.h"
#include "base/logging.h"
#include "base/memory/ref_counted.h"
#include "build/build_config.h"
#include "chrome/browser/ui/browser_window/public/global_browser_collection.h"
#include "chrome/browser/wasm/wasm_global_browser_collection.h"
#include "components/os_crypt/async/browser/key_provider.h"
#include "components/prefs/in_memory_pref_store.h"
#include "components/prefs/pref_registry_simple.h"
#include "components/prefs/pref_service.h"
#include "components/prefs/pref_service_factory.h"
#include "components/supervised_user/core/browser/device_parental_controls_noop_impl.h"
#include "services/network/public/cpp/shared_url_loader_factory.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_process.cc must only be built for WebAssembly"
#endif

namespace {

std::unique_ptr<PrefService> CreateInMemoryLocalState() {
  // Do not call Chrome's desktop RegisterLocalState() here. Its pref schema
  // owns desktop services that are intentionally source-excluded from M6.
  auto registry = base::MakeRefCounted<PrefRegistrySimple>();
  PrefServiceFactory factory;
  factory.set_user_prefs(base::MakeRefCounted<InMemoryPrefStore>());
  return factory.Create(std::move(registry));
}

}  // namespace

WasmBrowserProcess::WasmBrowserProcess()
    : local_state_(CreateInMemoryLocalState()),
      device_parental_controls_(
          std::make_unique<supervised_user::DeviceParentalControlsNoOpImpl>()) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  CHECK(!g_browser_process);
  CHECK(local_state_);
  CHECK(device_parental_controls_);
  g_browser_process = this;
  global_browser_collection_ = std::make_unique<GlobalBrowserCollection>();
  RegisterWasmGlobalBrowserCollection(global_browser_collection_.get());
}

WasmBrowserProcess::~WasmBrowserProcess() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  CHECK_EQ(g_browser_process, this);
  CHECK(global_browser_collection_);
  // The profile's interlocked keyed-service shutdown destroys its
  // BrowserManagerService (and all owned Browsers) before this process object.
  // Never clear the global owner while a browser might still hold observers.
  CHECK(global_browser_collection_->IsEmpty());
  UnregisterWasmGlobalBrowserCollection(global_browser_collection_.get());
  global_browser_collection_.reset();
  g_browser_process = nullptr;
}

void WasmBrowserProcess::SetProfileManager(ProfileManager* profile_manager) {
  CheckOnBrowserSequence();
  profile_manager_ = profile_manager;
}

void WasmBrowserProcess::SetSystemNetworkContextManager(
    SystemNetworkContextManager* system_network_context_manager) {
  CheckOnBrowserSequence();
  system_network_context_manager_ = system_network_context_manager;
}

void WasmBrowserProcess::SetSharedURLLoaderFactory(
    scoped_refptr<network::SharedURLLoaderFactory> shared_url_loader_factory) {
  CheckOnBrowserSequence();
  shared_url_loader_factory_ = std::move(shared_url_loader_factory);
}

void WasmBrowserProcess::SetNetworkQualityTracker(
    network::NetworkQualityTracker* network_quality_tracker) {
  CheckOnBrowserSequence();
  network_quality_tracker_ = network_quality_tracker;
}

ui::UnownedUserDataHost& WasmBrowserProcess::GetUnownedUserDataHost() {
  CheckOnBrowserSequence();
  return unowned_user_data_host_;
}

const ui::UnownedUserDataHost& WasmBrowserProcess::GetUnownedUserDataHost()
    const {
  CheckOnBrowserSequence();
  return unowned_user_data_host_;
}

void WasmBrowserProcess::EndSession() {
  CheckOnBrowserSequence();
  // `local_state_` is deliberately volatile in M6. Profile persistence is not
  // available until M7's OPFS backend is installed, so there is no fake flush.
  is_shutting_down_ = true;
}

metrics_services_manager::MetricsServicesManager*
WasmBrowserProcess::GetMetricsServicesManager() {
  FailUnavailableService("metrics services manager");
}

embedder_support::OriginTrialsSettingsStorage*
WasmBrowserProcess::GetOriginTrialsSettingsStorage() {
  FailUnavailableService("Chrome origin-trial settings storage");
}

metrics::MetricsService* WasmBrowserProcess::metrics_service() {
  LogUnavailableService("metrics service");
  return nullptr;
}

ProfileManager* WasmBrowserProcess::profile_manager() {
  CheckOnBrowserSequence();
  if (!profile_manager_) {
    LogUnavailableService("profile manager before Wasm profile initialization");
  }
  return profile_manager_;
}

PrefService* WasmBrowserProcess::local_state() {
  CheckOnBrowserSequence();
  return local_state_.get();
}

scoped_refptr<network::SharedURLLoaderFactory>
WasmBrowserProcess::shared_url_loader_factory() {
  CheckOnBrowserSequence();
  if (!shared_url_loader_factory_) {
    LogUnavailableService(
        "Chrome shared URL loader factory before network initialization");
  }
  return shared_url_loader_factory_;
}

signin::ActivePrimaryAccountsMetricsRecorder*
WasmBrowserProcess::active_primary_accounts_metrics_recorder() {
  LogUnavailableService("active primary-account metrics");
  return nullptr;
}

variations::VariationsService* WasmBrowserProcess::variations_service() {
  LogUnavailableService("variations service");
  return nullptr;
}

BrowserProcessPlatformPart* WasmBrowserProcess::platform_part() {
  FailUnavailableService("desktop browser platform part");
}

NotificationUIManager* WasmBrowserProcess::notification_ui_manager() {
  FailUnavailableService("notification UI");
}

NotificationPlatformBridge* WasmBrowserProcess::notification_platform_bridge() {
  FailUnavailableService("notification platform bridge");
}

SystemNetworkContextManager*
WasmBrowserProcess::system_network_context_manager() {
  CheckOnBrowserSequence();
  if (!system_network_context_manager_) {
    LogUnavailableService(
        "Chrome system network context before Wasm network initialization");
  }
  return system_network_context_manager_;
}

network::NetworkQualityTracker* WasmBrowserProcess::network_quality_tracker() {
  CheckOnBrowserSequence();
  if (!network_quality_tracker_) {
    LogUnavailableService(
        "network-quality tracker before Wasm network initialization");
  }
  return network_quality_tracker_;
}

policy::ChromeBrowserPolicyConnector*
WasmBrowserProcess::browser_policy_connector() {
  FailUnavailableService("enterprise policy connector");
}

policy::PolicyService* WasmBrowserProcess::policy_service() {
  FailUnavailableService("enterprise policy service");
}

IconManager* WasmBrowserProcess::icon_manager() {
  FailUnavailableService("desktop icon manager");
}

GpuModeManager* WasmBrowserProcess::gpu_mode_manager() {
  FailUnavailableService("desktop GPU mode manager");
}

void WasmBrowserProcess::CreateDevToolsProtocolHandler() {
  FailUnavailableService("Chrome DevTools protocol handler");
}

void WasmBrowserProcess::CreateDevToolsAutoOpener() {
  FailUnavailableService("Chrome DevTools auto-opener");
}

bool WasmBrowserProcess::IsShuttingDown() {
  CheckOnBrowserSequence();
  return is_shutting_down_;
}

printing::PrintJobManager* WasmBrowserProcess::print_job_manager() {
  FailUnavailableService("printing");
}

printing::PrintPreviewDialogController*
WasmBrowserProcess::print_preview_dialog_controller() {
  FailUnavailableService("print preview");
}

printing::BackgroundPrintingManager*
WasmBrowserProcess::background_printing_manager() {
  FailUnavailableService("background printing");
}

supervised_user::DeviceParentalControls&
WasmBrowserProcess::device_parental_controls() {
  CheckOnBrowserSequence();
  return *device_parental_controls_;
}

#if !BUILDFLAG(IS_ANDROID)
IntranetRedirectDetector* WasmBrowserProcess::intranet_redirect_detector() {
  FailUnavailableService("intranet redirect detector");
}
#endif

const std::string& WasmBrowserProcess::GetApplicationLocale() {
  CheckOnBrowserSequence();
  return application_locale_;
}

void WasmBrowserProcess::SetApplicationLocale(
    const std::string& actual_locale) {
  CheckOnBrowserSequence();
  CHECK(!actual_locale.empty());
  application_locale_ = actual_locale;
}

DownloadStatusUpdater* WasmBrowserProcess::download_status_updater() {
  FailUnavailableService("desktop download status updater");
}

DownloadRequestLimiter* WasmBrowserProcess::download_request_limiter() {
  FailUnavailableService("download request limiter");
}

#if BUILDFLAG(ENABLE_BACKGROUND_MODE)
BackgroundModeManager* WasmBrowserProcess::background_mode_manager() {
  FailUnavailableService("background mode manager");
}

void WasmBrowserProcess::set_background_mode_manager_for_test(
    std::unique_ptr<BackgroundModeManager>) {
  FailUnavailableService("background mode manager test hook");
}
#endif

StatusTray* WasmBrowserProcess::status_tray() {
  LogUnavailableService("system status tray");
  return nullptr;
}

#if BUILDFLAG(SAFE_BROWSING_AVAILABLE)
safe_browsing::SafeBrowsingService*
WasmBrowserProcess::safe_browsing_service() {
  FailUnavailableService("Safe Browsing service");
}
#endif

subresource_filter::RulesetService*
WasmBrowserProcess::subresource_filter_ruleset_service() {
  FailUnavailableService("subresource-filter ruleset service");
}

StartupData* WasmBrowserProcess::startup_data() {
  FailUnavailableService("desktop startup data");
}

#if BUILDFLAG(IS_WIN) || BUILDFLAG(IS_LINUX)
void WasmBrowserProcess::StartAutoupdateTimer() {
  FailUnavailableService("autoupdate timer");
}
#endif

activity_reporter::ActivityReporter* WasmBrowserProcess::activity_reporter() {
  FailUnavailableService("activity reporter");
}

component_updater::ComponentUpdateService*
WasmBrowserProcess::component_updater() {
  FailUnavailableService("component updater");
}

#if BUILDFLAG(IS_CHROMEOS)
MediaFileSystemRegistry* WasmBrowserProcess::media_file_system_registry() {
  FailUnavailableService("ChromeOS media-file-system registry");
}
#endif

WebRtcLogUploader* WasmBrowserProcess::webrtc_log_uploader() {
  FailUnavailableService("WebRTC log uploader");
}

network_time::NetworkTimeTracker* WasmBrowserProcess::network_time_tracker() {
  FailUnavailableService("network time tracker");
}

#if !BUILDFLAG(IS_ANDROID)
gcm::GCMDriver* WasmBrowserProcess::gcm_driver() {
  FailUnavailableService("GCM driver");
}
#endif

resource_coordinator::TabManager* WasmBrowserProcess::GetTabManager() {
  LogUnavailableService("tab manager");
  return nullptr;
}

resource_coordinator::ResourceCoordinatorParts*
WasmBrowserProcess::resource_coordinator_parts() {
  FailUnavailableService("resource coordinator");
}

SerialPolicyAllowedPorts* WasmBrowserProcess::serial_policy_allowed_ports() {
  FailUnavailableService("serial policy allowed ports");
}

os_crypt_async::OSCryptAsync* WasmBrowserProcess::os_crypt_async() {
  FailUnavailableService("OS cryptographic key store");
}

void WasmBrowserProcess::set_additional_os_crypt_async_provider_for_test(
    size_t,
    std::unique_ptr<os_crypt_async::KeyProvider>) {
  FailUnavailableService("OS cryptographic key-provider test hook");
}

BuildState* WasmBrowserProcess::GetBuildState() {
  FailUnavailableService("desktop build-state service");
}

GlobalFeatures* WasmBrowserProcess::GetFeatures() {
  FailUnavailableService("Chrome global features before Wasm initialization");
}

void WasmBrowserProcess::CheckOnBrowserSequence() const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  DCHECK_EQ(g_browser_process, this);
}

[[noreturn]] void WasmBrowserProcess::FailUnavailableService(
    const char* service) const {
  CheckOnBrowserSequence();
  LOG(FATAL) << "chrome_wasm M6 has no real implementation for required "
             << service;
}

void WasmBrowserProcess::LogUnavailableService(const char* service) const {
  CheckOnBrowserSequence();
  // This helper is only for BrowserProcess APIs that explicitly permit a null
  // result, or for a documented injection access point before its real owner
  // has initialized. The M6 GN args set `enable_updater=false`,
  // `enable_background_mode=false`, `enable_chrome_notifications=false`,
  // `enable_extensions=false`, `enable_printing=false`, and
  // `safe_browsing_mode=0`; source selection also omits their desktop
  // integrations. Do not add a successful-looking stub for persistence,
  // networking, or security-sensitive services here.
  LOG(ERROR) << "chrome_wasm M6 does not provide " << service;
}
