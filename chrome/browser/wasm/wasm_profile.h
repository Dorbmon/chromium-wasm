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
#include "base/functional/callback.h"
#include "base/memory/scoped_refptr.h"
#include "base/memory/weak_ptr.h"
#include "base/time/time.h"
#include "build/build_config.h"
#include "chrome/browser/profiles/profile.h"

class ChromeZoomLevelPrefs;
class ExtensionSpecialStoragePolicy;
class GURL;
class JsonPrefStore;
class PrefService;
class ProfileKey;
class WasmProfilePrefsFenceController;
class WasmSessionNavigationJournal;

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
// Its path resides at Chrome's configured user-data location. User preferences
// use a real JsonPrefStore at the canonical Preferences path; normal Wasm
// Chrome keeps that location volatile until the OPFS backend has the required
// pin, durability, locking, and recovery evidence. The Chrome-process Local
// State and all other profile stores remain independently scoped.
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

  // Starts the final user-preference write/readback fence after Shutdown(). It
  // writes pending preferences, reads the bounded Preferences file back on the
  // JsonPrefStore file sequence, and compares the parsed strict JSON dictionary
  // with a UI-sequence snapshot. |completion| runs exactly once on the UI
  // sequence while this profile remains alive. This validates orderly shutdown,
  // not reload durability on the volatile normal profile path.
  void BeginPrefsShutdownFence(
      base::OnceCallback<void(bool success)> completion);
  bool IsPrefsShutdownFencePending() const;
  bool HasPrefsShutdownFenceCompleted() const;
  bool DidPrefsShutdownFenceSucceed() const;

  // The M6 history bootstrap reads this process-local journal through a weak
  // reference. It is intentionally not HistoryService and becomes inert
  // before any Profile keyed-service shutdown begins.
  base::WeakPtr<WasmSessionNavigationJournal>
  GetSessionNavigationJournalWeakPtr();

  // content::BrowserContext:
  std::unique_ptr<content::ZoomLevelDelegate> CreateZoomLevelDelegate(
      const base::FilePath& partition_path) override;
  base::FilePath GetPath() const override;
  bool ShouldUseInMemoryDefaultStoragePartition() override;
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
  enum class PrefsShutdownFenceState {
    kNotStarted,
    kPending,
    kSucceeded,
    kFailed,
  };

  void OnPrefsShutdownFenceComplete(
      base::OnceCallback<void(bool success)> completion,
      bool success);
  bool StartPrefsShutdownFence(base::OnceCallback<void(bool success)> completion);

  base::FilePath profile_path_;
  base::FilePath last_selected_directory_;
  base::Time creation_time_;
  base::Time start_time_;

  // Chrome's UI/application sequence runs on the application pthread, never
  // the host browser's JavaScript main thread. PrefServiceFactory's initial
  // JsonPrefStore read remains synchronous there to preserve Profile
  // construction ordering; this shutdown-blocking runner is for asynchronous
  // writes and readback before the Wasm module tears down its worker pool.
  scoped_refptr<base::SequencedTaskRunner> io_task_runner_;

  // Keep the registry and the concrete user store alive for PrefService. The
  // JsonPrefStore uses |io_task_runner_| for its asynchronous write and
  // readback fence; Local State remains outside this profile and in-memory.
  scoped_refptr<user_prefs::PrefRegistrySyncable> pref_registry_;
  scoped_refptr<JsonPrefStore> json_pref_store_;
  std::unique_ptr<PrefService> prefs_;

  // ProfileKey is associated with this BrowserContext for the lifetime of the
  // profile and is torn down only after storage partitions have shut down.
  std::unique_ptr<ProfileKey> key_;

  // Direct profile ownership keeps the volatile M6 journal out of the
  // desktop HistoryService graph and gives profile shutdown one clear place
  // to invalidate every WebContents observer and WebUI data source.
  std::unique_ptr<WasmSessionNavigationJournal> session_navigation_journal_;

  // This owns the one explicitly admitted JsonPrefStore fence. It is not a
  // profile-wide storage drain or a persistence claim; other profile services
  // must become result-bearing participants before OPFS can be selected.
  std::unique_ptr<WasmProfilePrefsFenceController>
      prefs_shutdown_fence_controller_;

  bool shutdown_ = false;
  PrefsShutdownFenceState prefs_shutdown_fence_state_ =
      PrefsShutdownFenceState::kNotStarted;
  uint32_t primary_main_frame_navigations_ = 0;
  base::WeakPtrFactory<WasmProfile> weak_ptr_factory_{this};
};

#endif  // CHROME_BROWSER_WASM_WASM_PROFILE_H_
