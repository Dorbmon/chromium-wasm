// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile.h"

#include <cstddef>
#include <cstdio>
#include <optional>
#include <string>
#include <utility>

#if defined(CHROME_WASM_M7_PREFERENCES_IMPORTANT_FILE_WRITER_PROXY_COMPLETION_TEST)
#include <emscripten/wasmfs_opfs_profile_drain.h>
#endif

#include "base/check.h"
#include "base/files/file.h"
#include "base/files/file_util.h"
#include "base/functional/bind.h"
#include "base/json/json_reader.h"
#include "base/logging.h"
#include "base/memory/scoped_refptr.h"
#include "base/task/bind_post_task.h"
#include "base/task/sequenced_task_runner.h"
#include "base/task/task_traits.h"
#include "base/task/thread_pool.h"
#include "base/uuid.h"
#include "build/build_config.h"
#if defined(CHROME_WASM_M7_PREFERENCES_IMPORTANT_FILE_WRITER_PROXY_COMPLETION_TEST)
#include "base/memory/ref_counted.h"
#include "base/synchronization/lock.h"
#endif
#include "chrome/browser/profiles/profile_key.h"
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
#include "chrome/browser/wasm/wasm_profile_cookie_smoke.h"  // nogncheck
#endif
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
// GN's include checker does not evaluate this target-specific definition.
#include "chrome/browser/wasm/wasm_profile_database_smoke.h"  // nogncheck
#endif
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
// GN's include checker does not evaluate this target-specific definition.
#include "chrome/browser/wasm/wasm_profile_history_smoke.h"  // nogncheck
#endif
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
// GN's include checker does not evaluate this target-specific definition.
#include "chrome/browser/wasm/wasm_profile_preferences_smoke.h"  // nogncheck
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
// GN's include checker does not evaluate this target-specific definition.
#include "chrome/browser/wasm/wasm_profile_indexed_db_smoke.h"  // nogncheck
#endif
#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE)
// GN's include checker does not evaluate this target-specific definition.
#include "chrome/browser/wasm/wasm_profile_persistent_default_partition_policy_probe.h"  // nogncheck
#endif
#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
// GN's include checker does not evaluate this target-specific definition.
#include "chrome/browser/wasm/wasm_profile_persistent_default_partition_shutdown_probe.h"  // nogncheck
#endif
#include "chrome/browser/wasm/wasm_profile_persistent_prefs_lifetime_participant.h"
#include "chrome/browser/wasm/wasm_profile_prefs_fence_controller.h"
#include "chrome/browser/wasm/wasm_session_navigation_journal.h"
#include "chrome/common/chrome_constants.h"
#include "chrome/common/pref_names.h"
#include "components/keyed_service/content/browser_context_dependency_manager.h"
#include "components/keyed_service/core/dependency_manager.h"
#include "components/keyed_service/core/simple_dependency_manager.h"
#include "components/keyed_service/core/simple_key_map.h"
#include "components/pref_registry/pref_registry_syncable.h"
#include "components/prefs/json_pref_store.h"
#include "components/prefs/pref_service.h"
#include "components/prefs/pref_service_factory.h"
#include "components/profile_metrics/browser_profile_type.h"
#include "components/user_prefs/user_prefs.h"
#include "content/public/browser/render_process_host.h"
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
// The source-selected Cookie participant clones the default partition's
// browser-process CookieManager before any asynchronous probe work begins.
#include "content/public/browser/storage_partition.h"  // nogncheck
#include "services/network/public/mojom/cookie_manager.mojom.h"  // nogncheck
#endif
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

// This private, non-default user preference creates a fresh pending write for
// every WasmProfile construction. It is never surfaced to the host or UI; its
// sole purpose is to ensure the M7 shutdown fence proves an actual Preferences
// write instead of accepting an untouched default dictionary.
constexpr char kWasmPersistentPrefsFenceUuid[] =
    "wasm.profile.persistent_prefs_fence_uuid";

// A Preferences file contains only the source-selected Wasm profile's user
// preferences. Bound its verification read so a malformed or unexpectedly
// large file cannot turn shutdown into unbounded profile I/O.
constexpr size_t kMaxPersistentPrefsFileSize = 1024 * 1024;

bool VerifyPersistentPrefsOnFileSequence(
    const base::FilePath& preferences_path,
    const base::DictValue& expected_values) {
  std::string serialized_preferences;
  if (!base::ReadFileToStringWithMaxSize(preferences_path,
                                         &serialized_preferences,
                                         kMaxPersistentPrefsFileSize)) {
    return false;
  }

  std::optional<base::DictValue> persisted_values = base::JSONReader::ReadDict(
      serialized_preferences, base::JSON_PARSE_RFC);
  return persisted_values && *persisted_values == expected_values;
}

void VerifyPersistentPrefsAndReplyOnFileSequence(
    base::FilePath preferences_path,
    base::DictValue expected_values,
    base::OnceCallback<void(bool success)> reply) {
  // JsonPrefStore invokes CommitPendingWrite's synchronous callback on its
  // file runner after all already-queued writes. Keep the bounded readback on
  // that same sequence; neither operation blocks Chrome's UI sequence.
  const bool readback_succeeded =
      VerifyPersistentPrefsOnFileSequence(preferences_path, expected_values);
#if defined(CHROME_WASM_M7_NORMAL_PROFILE_FENCE_FAILURE_DIAGNOSTIC)
  if (readback_succeeded) {
    // This distinct test artifact reaches this point only after the bounded
    // JSON readback matched JsonPrefStore's expected dictionary. Convert that
    // successful result into a failed fence to prove the normal volatile
    // profile's result latch cannot report a clean process exit. A natural
    // write/readback failure emits no marker and remains a test failure.
    std::fputs(
        "CHROMIUM_WASM_M7_NORMAL_PROFILE_FENCE_DIAGNOSTIC:"
        "READBACK_OK_FORCED_FAILURE\n",
        stderr);
    std::fflush(stderr);
    std::move(reply).Run(false);
    return;
  }
#endif
  std::move(reply).Run(readback_succeeded);
}

#if defined(CHROME_WASM_M7_PREFERENCES_IMPORTANT_FILE_WRITER_PROXY_COMPLETION_TEST)
// This receipt is the only object shared with JsonPrefStore's file sequence.
// It deliberately contains no Profile, PrefService, JsonPrefStore, or raw
// preference data. The final UI-sequence callback accepts the controlled
// failure only when every field matches this one replacement attempt.
class WasmProfileImportantFileWriterProxyCompletionReceipt final
    : public base::RefCountedThreadSafe<
          WasmProfileImportantFileWriterProxyCompletionReceipt> {
 public:
  void RecordReplaceResult(int arm_result,
                           bool replace_result,
                           bool had_error,
                           base::File::Error replace_file_error,
                           int latch_count,
                           int proxies_after_latch) {
    base::AutoLock lock(lock_);
    ++callback_count_;
    arm_result_ = arm_result;
    replace_result_ = replace_result;
    had_error_ = had_error;
    replace_file_error_ = replace_file_error;
    latch_count_ = latch_count;
    proxies_after_latch_ = proxies_after_latch;
  }

  bool MatchesExpectedFailure() {
    base::AutoLock lock(lock_);
    return callback_count_ == 1 && arm_result_ == 1 && !replace_result_ &&
           had_error_ && replace_file_error_ == base::File::FILE_ERROR_IO &&
           latch_count_ == 1 && proxies_after_latch_ == 0;
  }

 private:
  friend class base::RefCountedThreadSafe<
      WasmProfileImportantFileWriterProxyCompletionReceipt>;

  ~WasmProfileImportantFileWriterProxyCompletionReceipt() = default;

  base::Lock lock_;
  int callback_count_ GUARDED_BY(lock_) = 0;
  int arm_result_ GUARDED_BY(lock_) = 0;
  bool replace_result_ GUARDED_BY(lock_) = true;
  bool had_error_ GUARDED_BY(lock_) = false;
  base::File::Error replace_file_error_ GUARDED_BY(lock_) =
      base::File::FILE_ERROR_FAILED;
  int latch_count_ GUARDED_BY(lock_) = 0;
  int proxies_after_latch_ GUARDED_BY(lock_) = -1;
};

bool ReplaceFileWithWasmProfileProxyCompletionFailure(
    scoped_refptr<WasmProfileImportantFileWriterProxyCompletionReceipt>
        receipt,
    const base::FilePath& from_path,
    const base::FilePath& to_path,
    base::File::Error* error) {
  const int arm_result =
      wasmfs_opfs_profile_log_v4_test_proxy_completion_arm();
  const bool replace_result = base::ReplaceFile(from_path, to_path, error);

  // The V4 test seam is armed on this file-runner thread only after
  // ImportantFileWriter has flushed and closed its temporary file. Snapshot
  // its exact post-replacement state before returning the real result.
  const bool had_error = error != nullptr;
  const base::File::Error replace_file_error =
      had_error ? *error : base::File::FILE_ERROR_FAILED;
  receipt->RecordReplaceResult(
      arm_result, replace_result, had_error, replace_file_error,
      wasmfs_opfs_profile_log_v4_test_proxy_completion_latch_count(),
      wasmfs_opfs_profile_log_v4_test_proxies_after_latch());
  return replace_result;
}

void VerifyWasmProfileProxyCompletionFailureAndReplyOnFileSequence(
    base::FilePath preferences_path,
    base::DictValue expected_b_values,
    scoped_refptr<WasmProfileImportantFileWriterProxyCompletionReceipt>
        receipt,
    base::OnceCallback<void(bool success)> reply) {
  // A poisoned V4 backend may make this bounded read fail as well as leave A
  // readable. Either way, only a strict mismatch with expected B is relevant;
  // this does not assert a crash-recovery or directory-durability outcome.
  const bool b_was_not_published =
      !VerifyPersistentPrefsOnFileSequence(preferences_path, expected_b_values);
  std::move(reply).Run(b_was_not_published &&
                       receipt->MatchesExpectedFailure());
}
#endif

}  // namespace

#if defined(CHROME_WASM_M7_PREFERENCES_IMPORTANT_FILE_WRITER_PROXY_COMPLETION_TEST)
// Keeps the three serial JsonPrefStore commits on WasmProfile's UI sequence.
// The file sequence receives only immutable paths/dictionaries, a lock-safe
// receipt, and a BindPostTask reply. In particular, no PrefService or
// JsonPrefStore reference can survive off the UI sequence.
class WasmProfileImportantFileWriterProxyCompletionFlow final
    : public base::RefCountedThreadSafe<
          WasmProfileImportantFileWriterProxyCompletionFlow> {
 public:
  WasmProfileImportantFileWriterProxyCompletionFlow(
      base::WeakPtr<WasmProfile> profile,
      scoped_refptr<base::SequencedTaskRunner> ui_task_runner,
      base::OnceCallback<void(bool success)> completion)
      : profile_(std::move(profile)),
        ui_task_runner_(std::move(ui_task_runner)),
        completion_(std::move(completion)),
        receipt_(base::MakeRefCounted<
                 WasmProfileImportantFileWriterProxyCompletionReceipt>()) {
    CHECK(ui_task_runner_);
    CHECK(completion_);
  }

  bool Start() {
    if (!profile_ || !profile_->prefs_ || !profile_->json_pref_store_) {
      return false;
    }
    CommitBaselineOne();
    return true;
  }

 private:
  friend class base::RefCountedThreadSafe<
      WasmProfileImportantFileWriterProxyCompletionFlow>;

  using CompletionHandler =
      void (WasmProfileImportantFileWriterProxyCompletionFlow::*)(bool);

  ~WasmProfileImportantFileWriterProxyCompletionFlow() = default;

  base::OnceCallback<void(bool)> BindReplyToUi(CompletionHandler handler) {
    return base::BindPostTask(
        ui_task_runner_,
        base::BindOnce(handler, base::WrapRefCounted(this)));
  }

  void CommitBaselineOne() {
    WasmProfile* profile = profile_.get();
    if (!profile || !profile->prefs_ || !profile->json_pref_store_) {
      Finish(false);
      return;
    }

    // Drain the constructor and D2 read of A through the ordinary replacement
    // path before changing the private fence UUID. This prevents a prior
    // scheduled write from consuming the source-selected replacement callback.
    profile->prefs_->CommitPendingWrite(
        base::OnceClosure(),
        base::BindOnce(
            &VerifyPersistentPrefsAndReplyOnFileSequence,
            profile->profile_path_.Append(chrome::kPreferencesFilename),
            profile->json_pref_store_->GetValues(),
            BindReplyToUi(&WasmProfileImportantFileWriterProxyCompletionFlow::
                              OnBaselineOneComplete)));
  }

  void OnBaselineOneComplete(bool success) {
    if (!success) {
      Finish(false);
      return;
    }

    WasmProfile* profile = profile_.get();
    if (!profile || !profile->prefs_ || !profile->json_pref_store_) {
      Finish(false);
      return;
    }

    // Generate a distinct private value so the second ordinary baseline has a
    // fresh JsonPrefStore mutation independent of the D2 A read.
    const std::string prior_uuid =
        profile->prefs_->GetString(kWasmPersistentPrefsFenceUuid);
    const std::string fresh_uuid = base::Uuid::GenerateRandomV4().AsLowercaseString();
    if (fresh_uuid.empty() || fresh_uuid == prior_uuid) {
      Finish(false);
      return;
    }
    profile->prefs_->SetString(kWasmPersistentPrefsFenceUuid, fresh_uuid);
    CommitBaselineTwo();
  }

  void CommitBaselineTwo() {
    WasmProfile* profile = profile_.get();
    if (!profile || !profile->prefs_ || !profile->json_pref_store_) {
      Finish(false);
      return;
    }

    profile->prefs_->CommitPendingWrite(
        base::OnceClosure(),
        base::BindOnce(
            &VerifyPersistentPrefsAndReplyOnFileSequence,
            profile->profile_path_.Append(chrome::kPreferencesFilename),
            profile->json_pref_store_->GetValues(),
            BindReplyToUi(&WasmProfileImportantFileWriterProxyCompletionFlow::
                              OnBaselineTwoComplete)));
  }

  void OnBaselineTwoComplete(bool success) {
    if (!success) {
      Finish(false);
      return;
    }

    WasmProfile* profile = profile_.get();
    if (!profile || !profile->prefs_ || !profile->json_pref_store_) {
      Finish(false);
      return;
    }

    // WriteNowWithBackgroundDataProducer copies this callback into its queued
    // file task synchronously. Restore the default on this UI turn immediately
    // after CommitPendingWrite so no later Preferences write inherits it.
    profile->json_pref_store_->SetReplaceFileCallbackForTesting(
        base::BindRepeating(
            &ReplaceFileWithWasmProfileProxyCompletionFailure, receipt_));
    if (!chrome::WriteWasmProfilePreferencesImportantFileWriterProxyCompletionValue(
            profile->prefs_.get())) {
      profile->json_pref_store_->SetReplaceFileCallbackForTesting(
          base::BindRepeating(&base::ReplaceFile));
      Finish(false);
      return;
    }

    base::DictValue expected_b_values =
        profile->json_pref_store_->GetValues();
    profile->prefs_->CommitPendingWrite(
        base::OnceClosure(),
        base::BindOnce(
            &VerifyWasmProfileProxyCompletionFailureAndReplyOnFileSequence,
            profile->profile_path_.Append(chrome::kPreferencesFilename),
            std::move(expected_b_values), receipt_,
            BindReplyToUi(&WasmProfileImportantFileWriterProxyCompletionFlow::
                              OnFinalCommitComplete)));
    profile->json_pref_store_->SetReplaceFileCallbackForTesting(
        base::BindRepeating(&base::ReplaceFile));
  }

  void OnFinalCommitComplete(bool exact_failure_and_unpublished_b) {
    if (!exact_failure_and_unpublished_b ||
        !chrome::NotifyWasmProfilePreferencesImportantFileWriterProxyCompletionEvidence()) {
      Finish(false);
      return;
    }

    // The controlled post-flush replacement loss is evidence for fail-closed
    // retirement only. Complete the existing fence as failed so it cannot
    // authorize a clean V4 profile handoff.
    Finish(false);
  }

  void Finish(bool success) {
    if (completion_.is_null()) {
      return;
    }
    base::OnceCallback<void(bool success)> completion = std::move(completion_);
    std::move(completion).Run(success);
  }

  const base::WeakPtr<WasmProfile> profile_;
  const scoped_refptr<base::SequencedTaskRunner> ui_task_runner_;
  base::OnceCallback<void(bool success)> completion_;
  const scoped_refptr<WasmProfileImportantFileWriterProxyCompletionReceipt>
      receipt_;
};
#endif

WasmProfile::WasmProfile(base::FilePath profile_path)
    : WasmProfile(std::move(profile_path), nullptr) {}

WasmProfile::WasmProfile(
    base::FilePath profile_path,
    std::unique_ptr<WasmProfilePersistentPrefsLifetimeParticipant>
        prefs_lifetime_profile_io_participant)
    : Profile(/*otr_profile_id=*/nullptr),
      profile_path_(std::move(profile_path)),
      creation_time_(base::Time::Now()),
      start_time_(creation_time_),
      io_task_runner_(base::ThreadPool::CreateSequencedTaskRunner(
          {base::MayBlock(), base::TaskShutdownBehavior::BLOCK_SHUTDOWN})),
      pref_registry_(base::MakeRefCounted<user_prefs::PrefRegistrySyncable>()),
      session_navigation_journal_(
          std::make_unique<WasmSessionNavigationJournal>()),
      prefs_lifetime_profile_io_participant_(
          std::move(prefs_lifetime_profile_io_participant)) {
  CHECK(!profile_path_.empty());
  CHECK(io_task_runner_);
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
  // The M7 caller must have transferred the construction-start admission
  // before the synchronous JsonPrefStore/PrefService read below can begin.
  CHECK(prefs_lifetime_profile_io_participant_);
  CHECK(prefs_lifetime_profile_io_participant_->IsPending());
#endif

  // These are Chrome's base profile preferences. Register the sole Browser
  // constructor pref now, then let every already-registered keyed-service
  // factory add its preferences before PrefService construction.
  Profile::RegisterProfilePrefs(pref_registry_.get());
  pref_registry_->RegisterIntegerPref(prefs::kDevToolsAvailability,
                                      kDevToolsAvailabilityDisallowed);
  pref_registry_->RegisterStringPref(kWasmPersistentPrefsFenceUuid,
                                     std::string());
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  // This narrow pref exists only in the source-selected M7 acceptance
  // artifacts. The helper registers it before PrefService construction and
  // keeps its opaque test value out of normal Chrome profiles and diagnostics.
  chrome::RegisterWasmProfilePreferencesSmokePref(pref_registry_.get());
#endif
  SimpleDependencyManager::GetInstance()->RegisterProfilePrefsForServices(
      pref_registry_.get());
  BrowserContextDependencyManager::GetInstance()
      ->RegisterProfilePrefsForServices(pref_registry_.get());

  PrefServiceFactory pref_service_factory;
  json_pref_store_ = base::MakeRefCounted<JsonPrefStore>(
      profile_path_.Append(chrome::kPreferencesFilename), nullptr,
      io_task_runner_);
  pref_service_factory.set_user_prefs(json_pref_store_);
  prefs_ = pref_service_factory.Create(pref_registry_);
  CHECK(prefs_);

  // Do not print or expose this UUID: it is only a private non-default value
  // that forces an independently observable JsonPrefStore write during every
  // M7 profile shutdown.
  const std::string persistence_fence_uuid =
      base::Uuid::GenerateRandomV4().AsLowercaseString();
  CHECK(!persistence_fence_uuid.empty());
  prefs_->SetString(kWasmPersistentPrefsFenceUuid, persistence_fence_uuid);

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
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  // Retain an unfinished model load/write and its profile admission if owner
  // loss occurs after the UI loop can no longer wait for its terminal result.
  if (bookmark_lifetime_participant_) {
    QuarantineBookmarkSmokeForFailureShutdown();
  }
#endif
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  // CookieManager belongs to the default StoragePartition. Keep its cloned
  // connection and admission alive if owner loss races the SQLite close
  // receipt; the outer V4 transaction must then refuse.
  if (cookie_lifetime_participant_) {
    QuarantineCookieSmokeForFailureShutdown();
  }
#endif
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  // The database runner can still own live SQLite or LevelDB handles when a
  // fallback destroys the profile after the UI loop has stopped. Keep that
  // task and its admitted profile I/O outstanding so V4 refuses its drain.
  if (database_lifetime_participant_) {
    QuarantineDatabaseSmokeForFailureShutdown();
  }
#endif
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  // BrowserMainParts normally retains this profile until the direct History
  // witness has its backend-destroy receipt. A fallback owner loss must retain
  // an active close as outstanding so the outer V4 drain refuses before it can
  // race History/Favicons file ownership.
  if (history_lifetime_participant_) {
    QuarantineHistorySmokeForFailureShutdown();
  }
#endif
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  if (local_storage_lifetime_participant_) {
    QuarantineLocalStorageSmokeForFailureShutdown();
  }
#endif
#if defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST)
  // The renderer participant owns a non-default persistent child partition.
  // If profile destruction races its selected-bucket close receipt, retain
  // its admitted I/O as outstanding so the outer V4 backend drain refuses.
  if (indexed_db_lifetime_participant_) {
    QuarantineIndexedDBSmokeForFailureShutdown();
  }
#endif
  // Do not let destruction classify the source-selected profile admission as
  // abandoned. An owner loss before the strict JsonPrefStore fence is a
  // failed profile operation, not a clean storage handoff.
  if (prefs_lifetime_profile_io_participant_) {
    prefs_lifetime_profile_io_participant_->Cancel();
  }
  if (prefs_shutdown_fence_controller_) {
    prefs_shutdown_fence_controller_->Cancel();
  }
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

  // Single-process render hosts intentionally survive ordinary ref-count
  // cleanup until process shutdown. Browser/Core destruction has completed
  // before this terminal profile shutdown, so release the host before tearing
  // down the profile services and storage it still references.
  if (content::RenderProcessHost::run_renderer_in_process()) {
    content::RenderProcessHost::ShutDownInProcessRenderer();
  }

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

void WasmProfile::BeginPrefsShutdownFence(
    base::OnceCallback<void(bool success)> completion) {
  CHECK(shutdown_);
  CHECK(completion);
  CHECK_EQ(prefs_shutdown_fence_state_, PrefsShutdownFenceState::kNotStarted);
  CHECK(prefs_);
  CHECK(json_pref_store_);
  CHECK(!prefs_shutdown_fence_controller_);

  prefs_shutdown_fence_state_ = PrefsShutdownFenceState::kPending;
  prefs_shutdown_fence_controller_ =
      std::make_unique<WasmProfilePrefsFenceController>(
          base::SequencedTaskRunner::GetCurrentDefault());
  prefs_shutdown_fence_controller_->Begin(
      base::BindOnce(&WasmProfile::StartPrefsShutdownFence,
                     base::Unretained(this)),
      base::BindOnce(&WasmProfile::OnPrefsShutdownFenceComplete,
                     weak_ptr_factory_.GetWeakPtr(), std::move(completion)));
}

bool WasmProfile::StartPrefsShutdownFence(
    base::OnceCallback<void(bool success)> completion) {
  CHECK(shutdown_);
  CHECK(completion);
  CHECK_EQ(prefs_shutdown_fence_state_, PrefsShutdownFenceState::kPending);
  CHECK(prefs_);
  CHECK(json_pref_store_);
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
  // A source-selected strict fence is not independently admissible. Its
  // profile-lifetime holder must remain live until this callback reports the
  // bounded write/readback result to the outer storage lifecycle.
  CHECK(prefs_lifetime_profile_io_participant_);
  CHECK(prefs_lifetime_profile_io_participant_->IsPending());
#endif

#if defined(CHROME_WASM_M7_PREFERENCES_IMPORTANT_FILE_WRITER_PROXY_COMPLETION_TEST)
  if (chrome::IsWasmProfilePreferencesImportantFileWriterProxyCompletionFailureEnabled()) {
    auto flow = base::MakeRefCounted<
        WasmProfileImportantFileWriterProxyCompletionFlow>(
        weak_ptr_factory_.GetWeakPtr(),
        base::SequencedTaskRunner::GetCurrentDefault(), std::move(completion));
    return flow->Start();
  }
#endif

  // Bind the result back to the UI sequence before handing it to the
  // JsonPrefStore file runner. The registered participant receives it there,
  // then the profile completes its source-selected lifetime admission only
  // after that terminal result has been aggregated. The file runner merely
  // owns the completion callback while it verifies the file.
  auto complete_on_ui = base::BindPostTask(
      base::SequencedTaskRunner::GetCurrentDefault(),
      std::move(completion));
  prefs_->CommitPendingWrite(
      base::OnceClosure(),
      base::BindOnce(&VerifyPersistentPrefsAndReplyOnFileSequence,
                     profile_path_.Append(chrome::kPreferencesFilename),
                     json_pref_store_->GetValues(), std::move(complete_on_ui)));
  return true;
}

bool WasmProfile::IsPrefsShutdownFencePending() const {
  return prefs_shutdown_fence_state_ == PrefsShutdownFenceState::kPending;
}

bool WasmProfile::HasPrefsShutdownFenceCompleted() const {
  return prefs_shutdown_fence_state_ == PrefsShutdownFenceState::kSucceeded ||
         prefs_shutdown_fence_state_ == PrefsShutdownFenceState::kFailed;
}

bool WasmProfile::DidPrefsShutdownFenceSucceed() const {
  return prefs_shutdown_fence_state_ == PrefsShutdownFenceState::kSucceeded;
}

#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
bool WasmProfile::StartBookmarkSmoke(
    chrome::WasmProfilePreferencesBookmarkSmokeInput input,
    WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold,
    base::OnceCallback<void(bool success)> completion) {
  if (shutdown_ || bookmark_lifetime_participant_ || !completion) {
    (void)profile_io_hold.Complete(
        WasmProfileOrderedDrainLifecycle::ProfileIOCompletion::kFailed);
    return false;
  }

  bookmark_lifetime_participant_ =
      std::make_unique<chrome::WasmProfileBookmarkLifetimeParticipant>(
          profile_path_, std::move(input), std::move(profile_io_hold));
  if (!bookmark_lifetime_participant_->Start(std::move(completion))) {
    bookmark_lifetime_participant_.reset();
    return false;
  }
  return true;
}

bool WasmProfile::HasActiveBookmarkSmoke() const {
  return bookmark_lifetime_participant_ &&
         bookmark_lifetime_participant_->IsActive();
}

bool WasmProfile::DidBookmarkSmokeSucceed() const {
  return bookmark_lifetime_participant_ &&
         bookmark_lifetime_participant_->DidSucceed();
}

void WasmProfile::CancelBookmarkSmokeForShutdown() {
  if (bookmark_lifetime_participant_) {
    bookmark_lifetime_participant_->Cancel();
  }
}

void WasmProfile::QuarantineBookmarkSmokeForFailureShutdown() {
  if (bookmark_lifetime_participant_ &&
      !bookmark_lifetime_participant_->QuarantineForFailureShutdown()) {
    LOG(ERROR) << "chrome_wasm could not quarantine an active BookmarkModel "
                  "operation for fail-closed shutdown";
  }
}
#endif

#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
bool WasmProfile::StartCookieSmoke(
    chrome::WasmProfilePreferencesCookieSmokeInput input,
    WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold,
    base::OnceCallback<void(bool success)> completion) {
  if (shutdown_ || cookie_lifetime_participant_ || !completion) {
    (void)profile_io_hold.Complete(
        WasmProfileOrderedDrainLifecycle::ProfileIOCompletion::kFailed);
    return false;
  }

  content::StoragePartition* storage_partition = GetDefaultStoragePartition();
  network::mojom::CookieManager* cookie_manager =
      storage_partition
          ? storage_partition->GetCookieManagerForBrowserProcess()
          : nullptr;
  if (!cookie_manager) {
    (void)profile_io_hold.Complete(
        WasmProfileOrderedDrainLifecycle::ProfileIOCompletion::kFailed);
    return false;
  }

  mojo::PendingRemote<network::mojom::CookieManager> participant_remote;
  cookie_manager->CloneInterface(
      participant_remote.InitWithNewPipeAndPassReceiver());
  cookie_lifetime_participant_ =
      std::make_unique<chrome::WasmProfileCookieLifetimeParticipant>(
          std::move(participant_remote), std::move(input),
          std::move(profile_io_hold));
  if (!cookie_lifetime_participant_->Start(std::move(completion))) {
    // Start() has already retired the transferred admission as failed. Drop
    // the inert owner so a retry cannot reinterpret that terminal result.
    cookie_lifetime_participant_.reset();
    return false;
  }
  return true;
}

bool WasmProfile::HasActiveCookieSmoke() const {
  return cookie_lifetime_participant_ &&
         cookie_lifetime_participant_->IsActive();
}

bool WasmProfile::DidCookieSmokeSucceed() const {
  return cookie_lifetime_participant_ &&
         cookie_lifetime_participant_->DidSucceed();
}

void WasmProfile::CancelCookieSmokeForShutdown() {
  if (cookie_lifetime_participant_) {
    cookie_lifetime_participant_->Cancel();
  }
}

void WasmProfile::QuarantineCookieSmokeForFailureShutdown() {
  if (cookie_lifetime_participant_ &&
      !cookie_lifetime_participant_->QuarantineForFailureShutdown()) {
    LOG(ERROR) << "chrome_wasm could not quarantine an active CookieManager "
                  "close for fail-closed shutdown";
  }
}
#endif

#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
bool WasmProfile::StartHistorySmoke(
    WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold,
    base::OnceCallback<void(bool success)> completion) {
  if (shutdown_ || history_lifetime_participant_ || !completion) {
    (void)profile_io_hold.Complete(
        WasmProfileOrderedDrainLifecycle::ProfileIOCompletion::kFailed);
    return false;
  }

  history_lifetime_participant_ =
      std::make_unique<chrome::WasmProfileHistoryLifetimeParticipant>(
          profile_path_, std::move(profile_io_hold));
  if (!history_lifetime_participant_->Start(std::move(completion))) {
    // Start() has already retired the transferred admission as failed. Drop
    // the inert owner so a retry cannot reinterpret that terminal result.
    history_lifetime_participant_.reset();
    return false;
  }
  return true;
}

bool WasmProfile::HasActiveHistorySmoke() const {
  return history_lifetime_participant_ &&
         history_lifetime_participant_->IsActive();
}

bool WasmProfile::DidHistorySmokeSucceed() const {
  return history_lifetime_participant_ &&
         history_lifetime_participant_->DidSucceed();
}

void WasmProfile::CancelHistorySmokeForShutdown() {
  if (history_lifetime_participant_) {
    history_lifetime_participant_->Cancel();
  }
}

void WasmProfile::QuarantineHistorySmokeForFailureShutdown() {
  if (history_lifetime_participant_ &&
      !history_lifetime_participant_->QuarantineForFailureShutdown()) {
    LOG(ERROR) << "chrome_wasm could not quarantine an active History/Favicons "
                  "close for fail-closed shutdown";
  }
}
#endif

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
bool WasmProfile::StartDatabaseSmoke(
    WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold,
    base::OnceCallback<void(bool success)> completion) {
  if (shutdown_ || database_lifetime_participant_ || !completion) {
    (void)profile_io_hold.Complete(
        WasmProfileOrderedDrainLifecycle::ProfileIOCompletion::kFailed);
    return false;
  }

  database_lifetime_participant_ =
      std::make_unique<chrome::WasmProfileDatabaseLifetimeParticipant>(
          profile_path_, std::move(profile_io_hold));
  if (!database_lifetime_participant_->Start(std::move(completion))) {
    // Start() has retired an otherwise unstarted admission as failed. Drop
    // the inert participant so no later shutdown path can reinterpret it.
    database_lifetime_participant_.reset();
    return false;
  }
  return true;
}

bool WasmProfile::HasActiveDatabaseSmoke() const {
  return database_lifetime_participant_ &&
         database_lifetime_participant_->IsActive();
}

bool WasmProfile::DidDatabaseSmokeSucceed() const {
  return database_lifetime_participant_ &&
         database_lifetime_participant_->DidSucceed();
}

void WasmProfile::CancelDatabaseSmokeForShutdown() {
  if (database_lifetime_participant_) {
    database_lifetime_participant_->Cancel();
  }
}

void WasmProfile::QuarantineDatabaseSmokeForFailureShutdown() {
  if (database_lifetime_participant_ &&
      !database_lifetime_participant_->QuarantineForFailureShutdown()) {
    LOG(ERROR) << "chrome_wasm could not quarantine active SQLite/LevelDB "
                  "work for fail-closed shutdown";
  }
}
#endif

#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
bool WasmProfile::StartLocalStorageSmoke(
    chrome::WasmProfileLocalStorageSmokeInput input,
    WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold,
    base::OnceCallback<void(bool success)> completion) {
  if (shutdown_ || local_storage_lifetime_participant_ || !completion) {
    (void)profile_io_hold.Complete(
        WasmProfileOrderedDrainLifecycle::ProfileIOCompletion::kFailed);
    return false;
  }
  local_storage_lifetime_participant_ = std::make_unique<
      chrome::WasmProfileLocalStorageLifetimeParticipant>(
      this, profile_path_, std::move(input), std::move(profile_io_hold));
  if (!local_storage_lifetime_participant_->Start(std::move(completion))) {
    local_storage_lifetime_participant_.reset();
    return false;
  }
  return true;
}

bool WasmProfile::HasActiveLocalStorageSmoke() const {
  return local_storage_lifetime_participant_ &&
         local_storage_lifetime_participant_->IsActive();
}

bool WasmProfile::DidLocalStorageSmokeSucceed() const {
  return local_storage_lifetime_participant_ &&
         local_storage_lifetime_participant_->DidSucceed();
}

void WasmProfile::CancelLocalStorageSmokeForShutdown() {
  if (local_storage_lifetime_participant_) {
    local_storage_lifetime_participant_->Cancel();
  }
}

void WasmProfile::QuarantineLocalStorageSmokeForFailureShutdown() {
  if (local_storage_lifetime_participant_ &&
      !local_storage_lifetime_participant_->QuarantineForFailureShutdown()) {
    LOG(ERROR) << "chrome_wasm could not quarantine active LocalStorage I/O";
  }
}
#endif

#if defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST)
bool WasmProfile::StartIndexedDBSmoke(
    chrome::WasmProfileIndexedDBSmokeInput input,
    WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold,
    base::OnceCallback<void(bool success)> completion) {
  if (shutdown_ || indexed_db_lifetime_participant_ || !completion) {
    (void)profile_io_hold.Complete(
        WasmProfileOrderedDrainLifecycle::ProfileIOCompletion::kFailed);
    return false;
  }

  indexed_db_lifetime_participant_ = std::make_unique<
      chrome::WasmProfileIndexedDBLifetimeParticipant>(
      this, profile_path_, std::move(input), std::move(profile_io_hold));
  if (!indexed_db_lifetime_participant_->Start(std::move(completion))) {
    // Start() has retired an unstarted admission as failed. Drop the inert
    // participant so a later shutdown path cannot reinterpret that terminal
    // result as a selected-bucket close receipt.
    indexed_db_lifetime_participant_.reset();
    return false;
  }
  return true;
}

bool WasmProfile::HasActiveIndexedDBSmoke() const {
  return indexed_db_lifetime_participant_ &&
         indexed_db_lifetime_participant_->IsActive();
}

bool WasmProfile::DidIndexedDBSmokeSucceed() const {
  return indexed_db_lifetime_participant_ &&
         indexed_db_lifetime_participant_->DidSucceed();
}

void WasmProfile::CancelIndexedDBSmokeForShutdown() {
  if (indexed_db_lifetime_participant_) {
    indexed_db_lifetime_participant_->Cancel();
  }
}

void WasmProfile::QuarantineIndexedDBSmokeForFailureShutdown() {
  if (indexed_db_lifetime_participant_ &&
      !indexed_db_lifetime_participant_->QuarantineForFailureShutdown()) {
    LOG(ERROR) << "chrome_wasm could not quarantine active IndexedDB I/O";
  }
}
#endif

void WasmProfile::OnPrefsShutdownFenceComplete(
    base::OnceCallback<void(bool success)> completion,
    bool success) {
  CHECK_EQ(prefs_shutdown_fence_state_, PrefsShutdownFenceState::kPending);
  CHECK(prefs_shutdown_fence_controller_);
  CHECK(prefs_shutdown_fence_controller_->HasCompleted());
  CHECK_EQ(prefs_shutdown_fence_controller_->DidSucceed(), success);
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
  // The outer M7 admission remains active until the inner controller has
  // observed the strict JsonPrefStore write/readback result. A missing or
  // previously completed participant is an explicit failure, never a clean
  // profile-storage handoff.
  if (!prefs_lifetime_profile_io_participant_ ||
      !prefs_lifetime_profile_io_participant_->CompleteAfterStrictFence(
          success)) {
    success = false;
  }
#endif
  prefs_shutdown_fence_state_ = success ? PrefsShutdownFenceState::kSucceeded
                                        : PrefsShutdownFenceState::kFailed;
  std::move(completion).Run(success);
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

bool WasmProfile::ShouldUseInMemoryDefaultStoragePartition() {
#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE)
  // The dedicated policy-only artifact calls StoragePartitionConfig::CreateDefault()
  // and exits before any StoragePartition is requested. This changes no normal
  // Chrome path and does not claim that a partition service is safe to persist.
  chrome::RecordWasmPersistentDefaultPartitionPolicyProbePolicyQuery();
  return false;
#elif defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
  // The source-selected shutdown probe performs exactly one default partition
  // accessor and one selected persistent CookieManager SQLite-row-readback/
  // close receipt. It keeps normal Chrome's default partition volatile and
  // always chooses failure retirement after its map-drop observation.
  chrome::RecordWasmPersistentDefaultPartitionShutdownProbePolicyQuery();
  return false;
#else
  // Keep the default StoragePartition volatile while this regular profile has
  // no durable backing for its partition-owned services. Separately admitted
  // Preferences I/O remains outside this partition policy.
  return true;
#endif
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
