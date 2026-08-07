// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_H_

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "base/files/file_path.h"
#include "base/memory/scoped_refptr.h"
#include "base/time/time.h"
#include "build/build_config.h"
#include "chrome/browser/profiles/profile.h"

class ChromeZoomLevelPrefs;
class ExtensionSpecialStoragePolicy;
class GURL;
class PrefService;
class ProfileKey;

namespace base {
class SequencedTaskRunner;
}

namespace content {
class BackgroundFetchDelegate;
class BackgroundSyncController;
class BrowserPluginGuestManager;
class BrowsingDataRemoverDelegate;
class ClientHintsControllerDelegate;
class ContentIndexProvider;
class DownloadManagerDelegate;
class FederatedIdentityApiPermissionContextDelegate;
class FederatedIdentityAutoReauthnPermissionContextDelegate;
class FederatedIdentityPermissionContextDelegate;
class FileSystemAccessPermissionContext;
class KAnonymityServiceDelegate;
class OriginTrialsControllerDelegate;
class PermissionControllerDelegate;
class PlatformNotificationService;
class PushMessagingService;
class ReduceAcceptLanguageControllerDelegate;
class SSLHostStateDelegate;
class StorageNotificationService;
class ZoomLevelDelegate;
}  // namespace content

namespace leveldb_proto {
class ProtoDatabaseProvider;
}

namespace policy {
class CloudPolicyManager;
class ProfileCloudPolicyManager;
class ProfilePolicyConnector;
class SchemaRegistryService;
class UserCloudPolicyManager;
}  // namespace policy

namespace storage {
class SpecialStoragePolicy;
}

namespace user_prefs {
class PrefRegistrySyncable;
}

// The Stage-A Chrome profile for the WebAssembly browser process.
//
// The path names an ephemeral Wasm filesystem namespace during M6. Preferences
// use a real in-memory PersistentPrefStore; this class does not claim durable
// profile storage. M7 replaces the backing with the OPFS implementation before
// profile persistence is enabled in the browser UI.
class WasmProfile final : public Profile {
 public:
  explicit WasmProfile(base::FilePath profile_path);
  WasmProfile(const WasmProfile&) = delete;
  WasmProfile& operator=(const WasmProfile&) = delete;
  ~WasmProfile() override;

  // Must run on the browser UI sequence after the last WebContents using this
  // profile has been destroyed. It is idempotent so main-parts teardown can
  // call it before ownership is released.
  void Shutdown();

  // content::BrowserContext:
  std::unique_ptr<content::ZoomLevelDelegate> CreateZoomLevelDelegate(
      const base::FilePath& partition_path) override;
  base::FilePath GetPath() const override;
  content::DownloadManagerDelegate* GetDownloadManagerDelegate() override;
  content::BrowserPluginGuestManager* GetGuestManager() override;
  storage::SpecialStoragePolicy* GetSpecialStoragePolicy() override;
  content::PlatformNotificationService* GetPlatformNotificationService()
      override;
  content::PushMessagingService* GetPushMessagingService() override;
  content::StorageNotificationService* GetStorageNotificationService()
      override;
  content::SSLHostStateDelegate* GetSSLHostStateDelegate() override;
  content::PermissionControllerDelegate* GetPermissionControllerDelegate()
      override;
  content::ClientHintsControllerDelegate* GetClientHintsControllerDelegate()
      override;
  content::BackgroundFetchDelegate* GetBackgroundFetchDelegate() override;
  content::BackgroundSyncController* GetBackgroundSyncController() override;
  content::BrowsingDataRemoverDelegate* GetBrowsingDataRemoverDelegate()
      override;
  content::ReduceAcceptLanguageControllerDelegate*
  GetReduceAcceptLanguageControllerDelegate() override;
  content::FileSystemAccessPermissionContext*
  GetFileSystemAccessPermissionContext() override;
  content::ContentIndexProvider* GetContentIndexProvider() override;
  content::FederatedIdentityApiPermissionContextDelegate*
  GetFederatedIdentityApiPermissionContext() override;
  content::FederatedIdentityAutoReauthnPermissionContextDelegate*
  GetFederatedIdentityAutoReauthnPermissionContext() override;
  content::FederatedIdentityPermissionContextDelegate*
  GetFederatedIdentityPermissionContext() override;
  content::KAnonymityServiceDelegate* GetKAnonymityServiceDelegate() override;
  content::OriginTrialsControllerDelegate* GetOriginTrialsControllerDelegate()
      override;
  std::unique_ptr<leveldb_proto::ProtoDatabaseProvider>
  TakeDefaultProtoDatabaseProvider() override;
  bool ShouldClearSessionStorageOnStartup() override;

  // Profile:
  base::Time GetCreationTime() const override;
  scoped_refptr<base::SequencedTaskRunner> GetIOTaskRunner() override;
  std::string GetProfileUserName() const override;
  Profile* GetOffTheRecordProfile(const OTRProfileID& otr_profile_id,
                                  bool create_if_needed) override;
  std::vector<Profile*> GetAllOffTheRecordProfiles() override;
  void DestroyOffTheRecordProfile(Profile* otr_profile) override;
  bool HasOffTheRecordProfile(const OTRProfileID& otr_profile_id) override;
  bool HasAnyOffTheRecordProfile() override;
  Profile* GetOriginalProfile() override;
  const Profile* GetOriginalProfile() const override;
  bool IsChild() const override;
  ExtensionSpecialStoragePolicy* GetExtensionSpecialStoragePolicy() override;
  PrefService* GetPrefs() override;
  const PrefService* GetPrefs() const override;
  ChromeZoomLevelPrefs* GetZoomLevelPrefs() override;
  bool IsSameOrParent(Profile* profile) override;
  base::Time GetStartTime() const override;
  ProfileKey* GetProfileKey() const override;
  policy::SchemaRegistryService* GetPolicySchemaRegistryService() override;
#if BUILDFLAG(IS_CHROMEOS)
  policy::UserCloudPolicyManagerAsh* GetUserCloudPolicyManagerAsh() override;
#else
  policy::UserCloudPolicyManager* GetUserCloudPolicyManager() override;
  policy::ProfileCloudPolicyManager* GetProfileCloudPolicyManager() override;
#endif
  policy::CloudPolicyManager* GetCloudPolicyManager() override;
  policy::ProfilePolicyConnector* GetProfilePolicyConnector() override;
  const policy::ProfilePolicyConnector* GetProfilePolicyConnector()
      const override;
  base::FilePath last_selected_directory() override;
  void set_last_selected_directory(const base::FilePath& path) override;
  GURL GetHomePage() override;
  bool WasCreatedByVersionOrLater(const std::string& version) override;
  bool ShouldRestoreOldSessionCookies() override;
  bool ShouldPersistSessionCookies() const override;
  bool IsNewProfile() const override;
  void SetCreationTimeForTesting(base::Time creation_time) override;
  void RecordPrimaryMainFrameNavigation() override;

 protected:
  bool IsSignedIn() override;

 private:
  base::FilePath profile_path_;
  base::FilePath last_selected_directory_;
  base::Time creation_time_;
  base::Time start_time_;

  // Profile I/O must not run on the UI/application sequence. The runner is
  // shutdown-blocking so storage cleanup completes before the Wasm module
  // tears down its worker pool.
  scoped_refptr<base::SequencedTaskRunner> io_task_runner_;

  // Keep the registry alive for the PrefService. The in-memory store is owned
  // by |prefs_| and is deliberately discarded at shutdown.
  scoped_refptr<user_prefs::PrefRegistrySyncable> pref_registry_;
  std::unique_ptr<PrefService> prefs_;

  // ProfileKey is associated with this BrowserContext for the lifetime of the
  // profile and is torn down only after storage partitions have shut down.
  std::unique_ptr<ProfileKey> key_;

  bool shutdown_ = false;
  uint32_t primary_main_frame_navigations_ = 0;
};

#endif  // CHROME_BROWSER_WASM_WASM_PROFILE_H_
