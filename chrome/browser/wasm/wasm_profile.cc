// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile.h"

#include <utility>

#include "base/check.h"
#include "base/logging.h"
#include "base/memory/scoped_refptr.h"
#include "base/task/sequenced_task_runner.h"
#include "base/task/task_traits.h"
#include "base/task/thread_pool.h"
#include "build/build_config.h"
#include "chrome/browser/profiles/profile_key.h"
#include "chrome/browser/wasm/wasm_session_navigation_journal.h"
#include "chrome/common/pref_names.h"
#include "components/keyed_service/content/browser_context_dependency_manager.h"
#include "components/keyed_service/core/dependency_manager.h"
#include "components/keyed_service/core/simple_dependency_manager.h"
#include "components/keyed_service/core/simple_key_map.h"
#include "components/pref_registry/pref_registry_syncable.h"
#include "components/prefs/in_memory_pref_store.h"
#include "components/prefs/pref_service.h"
#include "components/prefs/pref_service_factory.h"
#include "components/profile_metrics/browser_profile_type.h"
#include "components/user_prefs/user_prefs.h"
#include "url/gurl.h"
#include "url/url_constants.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_profile.cc must only be built for WebAssembly"
#endif

namespace {

// Keep the policy-controlled DevTools entry point unavailable until its full
// Chrome UI/controller slice is source-selected. This is the numeric value of
// DeveloperToolsPolicyHandler::Availability::kDisallowed, kept local to avoid
// pulling the desktop policy-factory graph into the bootstrap profile.
constexpr int kDevToolsAvailabilityDisallowed = 2;

}  // namespace

WasmProfile::WasmProfile(base::FilePath profile_path)
    : Profile(/*otr_profile_id=*/nullptr),
      profile_path_(std::move(profile_path)),
      creation_time_(base::Time::Now()),
      start_time_(creation_time_),
      io_task_runner_(base::ThreadPool::CreateSequencedTaskRunner(
          {base::MayBlock(), base::TaskShutdownBehavior::BLOCK_SHUTDOWN})),
      pref_registry_(base::MakeRefCounted<user_prefs::PrefRegistrySyncable>()),
      session_navigation_journal_(std::make_unique<WasmSessionNavigationJournal>()) {
  CHECK(!profile_path_.empty());
  CHECK(io_task_runner_);

  // These are Chrome's base profile preferences. Register the sole Browser
  // constructor pref now, then let every already-registered keyed-service
  // factory add its preferences before PrefService construction.
  Profile::RegisterProfilePrefs(pref_registry_.get());
  pref_registry_->RegisterIntegerPref(prefs::kDevToolsAvailability,
                                      kDevToolsAvailabilityDisallowed);
  SimpleDependencyManager::GetInstance()->RegisterProfilePrefsForServices(
      pref_registry_.get());
  BrowserContextDependencyManager::GetInstance()
      ->RegisterProfilePrefsForServices(pref_registry_.get());

  PrefServiceFactory pref_service_factory;
  pref_service_factory.set_user_prefs(
      base::MakeRefCounted<InMemoryPrefStore>());
  prefs_ = pref_service_factory.Create(pref_registry_);
  CHECK(prefs_);

  key_ = std::make_unique<ProfileKey>(profile_path_);
  key_->SetPrefs(prefs_.get());
  user_prefs::UserPrefs::Set(this, prefs_.get());
  SimpleKeyMap::GetInstance()->Associate(this, key_.get());
  profile_metrics::SetBrowserProfileType(
      this, profile_metrics::BrowserProfileType::kRegular);

  SimpleDependencyManager::GetInstance()->CreateServices(key_.get());
  BrowserContextDependencyManager::GetInstance()->CreateBrowserContextServices(
      this);

  NotifyProfileInitializationComplete();
}

WasmProfile::~WasmProfile() {
  Shutdown();
  key_.reset();
}

void WasmProfile::Shutdown() {
  if (shutdown_) {
    return;
  }
  shutdown_ = true;

  // The journal has weak observers on every model-owned WebContents. History
  // URLDataSources hold immutable snapshots instead of live profile state.
  // Permanently disarm the observers before profile notifications or
  // keyed-service teardown can run callbacks.
  if (session_navigation_journal_) {
    session_navigation_journal_->Shutdown();
    session_navigation_journal_.reset();
  }

  // Notify consumers before closing StoragePartition-backed services. This
  // establishes the same ordering required by BrowserContext and avoids
  // allowing late profile callbacks to manufacture a new storage partition.
  MaybeSendDestroyedNotification();

  // Profile and ProfileKey respectively mark the BrowserContext and simple
  // keyed-service contexts live during construction. Their shutdown must stay
  // interlocked: BrowserContext services can depend on simple-key services.
  // Today this source-selected profile creates no Chrome keyed services, but
  // doing the real two-phase teardown now keeps the lifetime correct once the
  // BrowserManagerService graph is admitted for Browser::Create().
  DependencyManager::PerformInterlockedTwoPhaseShutdown(
      BrowserContextDependencyManager::GetInstance(), this,
      SimpleDependencyManager::GetInstance(), key_.get());
  SimpleKeyMap::GetInstance()->Dissociate(this);
  ShutdownStoragePartitions();
}

base::WeakPtr<WasmSessionNavigationJournal>
WasmProfile::GetSessionNavigationJournalWeakPtr() {
  if (shutdown_ || !session_navigation_journal_) {
    return nullptr;
  }
  return session_navigation_journal_->GetWeakPtr();
}

std::unique_ptr<content::ZoomLevelDelegate>
WasmProfile::CreateZoomLevelDelegate(const base::FilePath& /*partition_path*/) {
  // M6 has no persisted per-host zoom service. Content uses its default zoom
  // behavior when the embedder has no delegate.
  return nullptr;
}

base::FilePath WasmProfile::GetPath() const {
  return profile_path_;
}

content::DownloadManagerDelegate* WasmProfile::GetDownloadManagerDelegate() {
  // Downloads are not exposed until the M7 OPFS/export delegate exists.
  return nullptr;
}

content::BrowserPluginGuestManager* WasmProfile::GetGuestManager() {
  // Guest views are disabled for the initial Wasm Chrome target.
  return nullptr;
}

storage::SpecialStoragePolicy* WasmProfile::GetSpecialStoragePolicy() {
  // There is no extensions special-storage policy in this configuration.
  return nullptr;
}

content::PlatformNotificationService*
WasmProfile::GetPlatformNotificationService() {
  // The host notification bridge has not been implemented.
  return nullptr;
}

content::PushMessagingService* WasmProfile::GetPushMessagingService() {
  // Push requires a durable service-worker/profile backend.
  return nullptr;
}

content::StorageNotificationService*
WasmProfile::GetStorageNotificationService() {
  // M6 has no Chrome-layer storage notification UI.
  return nullptr;
}

content::SSLHostStateDelegate* WasmProfile::GetSSLHostStateDelegate() {
  // A null delegate selects Content's default non-persisted certificate
  // exception handling; no certificate exception is silently stored.
  return nullptr;
}

content::PermissionControllerDelegate*
WasmProfile::GetPermissionControllerDelegate() {
  // PermissionControllerImpl treats a null delegate as an explicit denial.
  // M6 must not grant host permissions without a gesture-aware bridge.
  return nullptr;
}

content::ClientHintsControllerDelegate*
WasmProfile::GetClientHintsControllerDelegate() {
  // Per-origin client-hints persistence is not available before OPFS.
  return nullptr;
}

content::BackgroundFetchDelegate* WasmProfile::GetBackgroundFetchDelegate() {
  // Background Fetch has no durable download backend in M6.
  return nullptr;
}

content::BackgroundSyncController* WasmProfile::GetBackgroundSyncController() {
  // The host has no browser wake-up mechanism for Background Sync.
  return nullptr;
}

content::BrowsingDataRemoverDelegate*
WasmProfile::GetBrowsingDataRemoverDelegate() {
  // Content may still remove its own in-memory data; no Chrome UI delegate is
  // registered until the full profile service graph is available.
  return nullptr;
}

content::ReduceAcceptLanguageControllerDelegate*
WasmProfile::GetReduceAcceptLanguageControllerDelegate() {
  // The initial profile has no persisted per-origin language negotiation.
  return nullptr;
}

content::FileSystemAccessPermissionContext*
WasmProfile::GetFileSystemAccessPermissionContext() {
  // File System Access is disabled until the user-gesture-aware picker bridge
  // and OPFS permission model are available.
  return nullptr;
}

content::ContentIndexProvider* WasmProfile::GetContentIndexProvider() {
  // Content Index requires a persistent service-worker backend.
  return nullptr;
}

content::FederatedIdentityApiPermissionContextDelegate*
WasmProfile::GetFederatedIdentityApiPermissionContext() {
  // FedCM is intentionally unavailable in the initial profile.
  return nullptr;
}

content::FederatedIdentityAutoReauthnPermissionContextDelegate*
WasmProfile::GetFederatedIdentityAutoReauthnPermissionContext() {
  // FedCM is intentionally unavailable in the initial profile.
  return nullptr;
}

content::FederatedIdentityPermissionContextDelegate*
WasmProfile::GetFederatedIdentityPermissionContext() {
  // FedCM is intentionally unavailable in the initial profile.
  return nullptr;
}

content::KAnonymityServiceDelegate*
WasmProfile::GetKAnonymityServiceDelegate() {
  // No profile-owned k-anonymity service is configured in M6.
  return nullptr;
}

content::OriginTrialsControllerDelegate*
WasmProfile::GetOriginTrialsControllerDelegate() {
  // Origin-trial persistence requires the durable profile storage gate.
  return nullptr;
}

std::unique_ptr<leveldb_proto::ProtoDatabaseProvider>
WasmProfile::TakeDefaultProtoDatabaseProvider() {
  // No startup-owned provider exists; Content creates only its ordinary
  // in-memory storage services for this ephemeral profile.
  return nullptr;
}

bool WasmProfile::ShouldClearSessionStorageOnStartup() {
  // A recreated M6 profile must never reuse an earlier in-memory session.
  return true;
}

base::Time WasmProfile::GetCreationTime() const {
  return creation_time_;
}

scoped_refptr<base::SequencedTaskRunner> WasmProfile::GetIOTaskRunner() {
  return io_task_runner_;
}

std::string WasmProfile::GetProfileUserName() const {
  // M6 has no signed-in identity or profile-picker account.
  return std::string();
}

Profile* WasmProfile::GetOffTheRecordProfile(
    const OTRProfileID& /*otr_profile_id*/,
    bool create_if_needed) {
  if (create_if_needed) {
    LOG(ERROR) << "Off-the-record profiles are not enabled for the M6 "
                  "Wasm profile.";
  }
  return nullptr;
}

std::vector<Profile*> WasmProfile::GetAllOffTheRecordProfiles() {
  return {};
}

void WasmProfile::DestroyOffTheRecordProfile(Profile* otr_profile) {
  if (otr_profile) {
    LOG(ERROR) << "Off-the-record profiles are not enabled for the M6 "
                  "Wasm profile.";
  }
}

bool WasmProfile::HasOffTheRecordProfile(
    const OTRProfileID& /*otr_profile_id*/) {
  return false;
}

bool WasmProfile::HasAnyOffTheRecordProfile() {
  return false;
}

Profile* WasmProfile::GetOriginalProfile() {
  return this;
}

const Profile* WasmProfile::GetOriginalProfile() const {
  return this;
}

bool WasmProfile::IsChild() const {
  // Supervised-user policy is disabled in the Wasm M6 configuration.
  return false;
}

ExtensionSpecialStoragePolicy* WasmProfile::GetExtensionSpecialStoragePolicy() {
  // Extensions are disabled at the feature boundary for M6.
  return nullptr;
}

PrefService* WasmProfile::GetPrefs() {
  return prefs_.get();
}

const PrefService* WasmProfile::GetPrefs() const {
  return prefs_.get();
}

ChromeZoomLevelPrefs* WasmProfile::GetZoomLevelPrefs() {
  return nullptr;
}

bool WasmProfile::IsSameOrParent(Profile* profile) {
  return profile == this;
}

base::Time WasmProfile::GetStartTime() const {
  return start_time_;
}

ProfileKey* WasmProfile::GetProfileKey() const {
  return key_.get();
}

policy::SchemaRegistryService* WasmProfile::GetPolicySchemaRegistryService() {
  // Enterprise policy is disabled for the initial browser target.
  return nullptr;
}

#if BUILDFLAG(IS_CHROMEOS)
policy::UserCloudPolicyManagerAsh* WasmProfile::GetUserCloudPolicyManagerAsh() {
  // Enterprise policy is disabled for the initial browser target.
  return nullptr;
}
#else
policy::UserCloudPolicyManager* WasmProfile::GetUserCloudPolicyManager() {
  // Enterprise policy is disabled for the initial browser target.
  return nullptr;
}

policy::ProfileCloudPolicyManager* WasmProfile::GetProfileCloudPolicyManager() {
  // Enterprise policy is disabled for the initial browser target.
  return nullptr;
}
#endif

policy::CloudPolicyManager* WasmProfile::GetCloudPolicyManager() {
  // Enterprise policy is disabled for the initial browser target.
  return nullptr;
}

policy::ProfilePolicyConnector* WasmProfile::GetProfilePolicyConnector() {
  // Enterprise policy is disabled for the initial browser target.
  return nullptr;
}

const policy::ProfilePolicyConnector* WasmProfile::GetProfilePolicyConnector()
    const {
  // Enterprise policy is disabled for the initial browser target.
  return nullptr;
}

base::FilePath WasmProfile::last_selected_directory() {
  return last_selected_directory_;
}

void WasmProfile::set_last_selected_directory(const base::FilePath& path) {
  // This state is intentionally process-local until an OPFS profile exists.
  last_selected_directory_ = path;
}

GURL WasmProfile::GetHomePage() {
  // chrome://newtab is not registered until the WebUI/profile service slice is
  // complete. A local about:blank WebContents is the M6 Stage-A entry point.
  return GURL(url::kAboutBlankURL);
}

bool WasmProfile::WasCreatedByVersionOrLater(const std::string& /*version*/) {
  // No creation version is persisted in M6. Callers must not skip migrations
  // based on a fabricated version marker.
  return false;
}

bool WasmProfile::ShouldRestoreOldSessionCookies() {
  // Session cookies have no durable M6 profile store.
  return false;
}

bool WasmProfile::ShouldPersistSessionCookies() const {
  // Session cookies have no durable M6 profile store.
  return false;
}

bool WasmProfile::IsNewProfile() const {
  return true;
}

void WasmProfile::SetCreationTimeForTesting(base::Time creation_time) {
  creation_time_ = creation_time;
}

void WasmProfile::RecordPrimaryMainFrameNavigation() {
  ++primary_main_frame_navigations_;
}

bool WasmProfile::IsSignedIn() {
  // Identity services are not enabled for the initial Wasm profile.
  return false;
}
