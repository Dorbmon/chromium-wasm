// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_PROCESS_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_PROCESS_H_

#include <cstddef>
#include <memory>
#include <string>

#include "base/memory/raw_ptr.h"
#include "base/memory/scoped_refptr.h"
#include "base/sequence_checker.h"
#include "chrome/browser/browser_process.h"
#include "ui/base/unowned_user_data/unowned_user_data_host.h"

class GlobalBrowserCollection;

// The browser-process implementation used by the source-selected Wasm Chrome
// target. This deliberately owns only process state that has a real M6
// implementation. Desktop BrowserProcessImpl is not part of the Wasm graph.
class WasmBrowserProcess final : public BrowserProcess {
 public:
  WasmBrowserProcess();
  ~WasmBrowserProcess() override;

  WasmBrowserProcess(const WasmBrowserProcess&) = delete;
  WasmBrowserProcess& operator=(const WasmBrowserProcess&) = delete;

  // Installs the real profile manager when the Wasm profile lifecycle has
  // initialized it. Its lifecycle remains with that startup slice, which must
  // clear this access point before destroying the manager. `profile_manager()`
  // is nullable, as BrowserProcess permits, until this is installed.
  void SetProfileManager(ProfileManager* profile_manager);

  // These objects are owned by their respective Wasm browser services. The
  // BrowserProcess only keeps their non-owning process-wide access points.
  // Until they are installed, these documented injection accessors return
  // nullptr rather than substituting a host-network or desktop implementation.
  void SetSystemNetworkContextManager(
      SystemNetworkContextManager* system_network_context_manager);
  void SetSharedURLLoaderFactory(
      scoped_refptr<network::SharedURLLoaderFactory> shared_url_loader_factory);
  void SetNetworkQualityTracker(
      network::NetworkQualityTracker* network_quality_tracker);

  // BrowserProcess:
  ui::UnownedUserDataHost& GetUnownedUserDataHost() override;
  const ui::UnownedUserDataHost& GetUnownedUserDataHost() const override;
  void EndSession() override;
  metrics_services_manager::MetricsServicesManager* GetMetricsServicesManager()
      override;
  embedder_support::OriginTrialsSettingsStorage*
  GetOriginTrialsSettingsStorage() override;
  metrics::MetricsService* metrics_service() override;
  ProfileManager* profile_manager() override;
  PrefService* local_state() override;
  scoped_refptr<network::SharedURLLoaderFactory> shared_url_loader_factory()
      override;
  signin::ActivePrimaryAccountsMetricsRecorder*
  active_primary_accounts_metrics_recorder() override;
  variations::VariationsService* variations_service() override;
  BrowserProcessPlatformPart* platform_part() override;
  NotificationUIManager* notification_ui_manager() override;
  NotificationPlatformBridge* notification_platform_bridge() override;
  SystemNetworkContextManager* system_network_context_manager() override;
  network::NetworkQualityTracker* network_quality_tracker() override;
  policy::ChromeBrowserPolicyConnector* browser_policy_connector() override;
  policy::PolicyService* policy_service() override;
  IconManager* icon_manager() override;
  GpuModeManager* gpu_mode_manager() override;
  void CreateDevToolsProtocolHandler() override;
  void CreateDevToolsAutoOpener() override;
  bool IsShuttingDown() override;
  printing::PrintJobManager* print_job_manager() override;
  printing::PrintPreviewDialogController* print_preview_dialog_controller()
      override;
  printing::BackgroundPrintingManager* background_printing_manager() override;
  supervised_user::DeviceParentalControls& device_parental_controls() override;
#if !BUILDFLAG(IS_ANDROID)
  IntranetRedirectDetector* intranet_redirect_detector() override;
#endif
  const std::string& GetApplicationLocale() override;
  void SetApplicationLocale(const std::string& actual_locale) override;
  DownloadStatusUpdater* download_status_updater() override;
  DownloadRequestLimiter* download_request_limiter() override;
#if BUILDFLAG(ENABLE_BACKGROUND_MODE)
  BackgroundModeManager* background_mode_manager() override;
  void set_background_mode_manager_for_test(
      std::unique_ptr<BackgroundModeManager> manager) override;
#endif
  StatusTray* status_tray() override;
#if BUILDFLAG(SAFE_BROWSING_AVAILABLE)
  safe_browsing::SafeBrowsingService* safe_browsing_service() override;
#endif
  subresource_filter::RulesetService* subresource_filter_ruleset_service()
      override;
  StartupData* startup_data() override;
#if BUILDFLAG(IS_WIN) || BUILDFLAG(IS_LINUX)
  void StartAutoupdateTimer() override;
#endif
  activity_reporter::ActivityReporter* activity_reporter() override;
  component_updater::ComponentUpdateService* component_updater() override;
#if BUILDFLAG(IS_CHROMEOS)
  MediaFileSystemRegistry* media_file_system_registry() override;
#endif
  WebRtcLogUploader* webrtc_log_uploader() override;
  network_time::NetworkTimeTracker* network_time_tracker() override;
#if !BUILDFLAG(IS_ANDROID)
  gcm::GCMDriver* gcm_driver() override;
#endif
  resource_coordinator::TabManager* GetTabManager() override;
  resource_coordinator::ResourceCoordinatorParts* resource_coordinator_parts()
      override;
  SerialPolicyAllowedPorts* serial_policy_allowed_ports() override;
  os_crypt_async::OSCryptAsync* os_crypt_async() override;
  void set_additional_os_crypt_async_provider_for_test(
      size_t precedence,
      std::unique_ptr<os_crypt_async::KeyProvider> provider) override;
  BuildState* GetBuildState() override;
  GlobalFeatures* GetFeatures() override;

 private:
  void CheckOnBrowserSequence() const;
  [[noreturn]] void FailUnavailableService(const char* service) const;
  void LogUnavailableService(const char* service) const;

  // M6 source selection enables no persistent profile backend. Keep this
  // process-local state genuinely in memory; M7 must replace it with the
  // OPFS-backed implementation rather than treating it as durable storage.
  ui::UnownedUserDataHost unowned_user_data_host_;
  std::unique_ptr<PrefService> local_state_;
  std::unique_ptr<supervised_user::DeviceParentalControls>
      device_parental_controls_;
  // This must outlive every profile-owned BrowserManagerService. It is cleared
  // only after the profile has shut down its keyed-service graph.
  std::unique_ptr<GlobalBrowserCollection> global_browser_collection_;
  raw_ptr<ProfileManager> profile_manager_ = nullptr;
  raw_ptr<SystemNetworkContextManager> system_network_context_manager_ =
      nullptr;
  scoped_refptr<network::SharedURLLoaderFactory> shared_url_loader_factory_;
  raw_ptr<network::NetworkQualityTracker> network_quality_tracker_ = nullptr;
  std::string application_locale_ = "en-US";
  bool is_shutting_down_ = false;

  SEQUENCE_CHECKER(sequence_checker_);
};

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_PROCESS_H_
