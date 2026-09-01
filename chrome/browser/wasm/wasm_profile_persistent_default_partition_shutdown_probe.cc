// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_persistent_default_partition_shutdown_probe.h"

#include <cstdio>
#include <memory>
#include <optional>
#include <string>
#include <utility>

#include "base/check.h"
#include "base/command_line.h"
#include "base/files/file_path.h"
#include "base/functional/bind.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "base/no_destructor.h"
#include "base/sequence_checker.h"
#include "base/strings/strcat.h"
#include "base/strings/string_number_conversions.h"
#include "base/task/sequenced_task_runner.h"
#include "base/time/time.h"
#include "base/timer/timer.h"
#include "chrome/browser/wasm/wasm_profile_local_storage_smoke.h"
#include "chrome/browser/wasm/wasm_profile_storage.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/storage_partition.h"
#include "content/public/browser/storage_partition_config.h"
#include "content/public/browser/wasm_storage_partition_shutdown_test_support.h"
#include "crypto/hash.h"
#include "crypto/random.h"
#include "mojo/public/cpp/bindings/remote.h"
#include "net/cookies/canonical_cookie.h"
#include "net/cookies/cookie_access_result.h"
#include "net/cookies/cookie_inclusion_status.h"
#include "net/cookies/cookie_options.h"
#include "net/cookies/cookie_partition_key_collection.h"
#include "services/network/public/mojom/cookie_manager.mojom.h"
#include "url/gurl.h"

namespace chrome {

namespace {

constexpr char kProbeSwitch[] =
    "wasm-persistent-default-partition-shutdown-probe";
constexpr char kMarkerPrefix[] =
    "CHROMIUM_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN:";
constexpr char kCookieUrl[] =
    "https://wasm-persistent-default-partition-shutdown.test/";
constexpr char kCookieName[] =
    "wasm_m7_persistent_default_partition_shutdown";
constexpr base::TimeDelta kLocalStorageOperationTimeout = base::Seconds(20);
constexpr base::TimeDelta kCookieOperationTimeout = base::Seconds(20);

WasmProfileLocalStorageSmokeInput CreateLocalStorageReceiptInput() {
  WasmProfileLocalStorageSmokeInput input;
  input.mode = WasmProfileLocalStorageSmokeInput::Mode::kWrite;
  // A same-value StorageArea::Put is intentionally a no-op. Use a new opaque
  // value for every probe so PrepareCommitCloseFence must observe a real map
  // update. Neither this token nor its digest leaves the embedded receipt.
  input.token = base::HexEncodeLower(crypto::RandBytesAsArray<32>());
  input.token_digest = base::HexEncodeLower(crypto::hash::Sha256(input.token));
  input.emit_protocol_markers = false;
  return input;
}

const char* FailureStageName(
    WasmPersistentDefaultPartitionShutdownProbeFailureStage stage) {
  switch (stage) {
    case WasmPersistentDefaultPartitionShutdownProbeFailureStage::kArguments:
      return "arguments";
    case WasmPersistentDefaultPartitionShutdownProbeFailureStage::kStorage:
      return "storage";
    case WasmPersistentDefaultPartitionShutdownProbeFailureStage::kProfile:
      return "profile";
    case WasmPersistentDefaultPartitionShutdownProbeFailureStage::
        kConfiguration:
      return "configuration";
    case WasmPersistentDefaultPartitionShutdownProbeFailureStage::kPartition:
      return "partition";
    case WasmPersistentDefaultPartitionShutdownProbeFailureStage::kLocalStorage:
      return "local_storage";
    case WasmPersistentDefaultPartitionShutdownProbeFailureStage::kCookie:
      return "cookie";
    case WasmPersistentDefaultPartitionShutdownProbeFailureStage::
        kNotification:
      return "notification";
    case WasmPersistentDefaultPartitionShutdownProbeFailureStage::kMap:
      return "map";
    case WasmPersistentDefaultPartitionShutdownProbeFailureStage::kAdmission:
      return "admission";
    case WasmPersistentDefaultPartitionShutdownProbeFailureStage::kFence:
      return "fence";
    case WasmPersistentDefaultPartitionShutdownProbeFailureStage::kRetirement:
      return "retirement";
    case WasmPersistentDefaultPartitionShutdownProbeFailureStage::kDrain:
      return "drain";
  }
  return "drain";
}

class WasmPersistentDefaultPartitionShutdownProbeState {
 public:
  bool EnableFromCommandLine() {
    if (configured_) {
      return enabled_;
    }
    configured_ = true;

    const base::CommandLine* command_line =
        base::CommandLine::ForCurrentProcess();
    if (!command_line->HasSwitch(kProbeSwitch) ||
        !command_line->GetSwitchValueASCII(kProbeSwitch).empty()) {
      ReportFailure(
          WasmPersistentDefaultPartitionShutdownProbeFailureStage::kArguments);
      return false;
    }

    enabled_ = true;
    return true;
  }

  bool enabled() const { return enabled_; }

  void RecordPolicyQuery() {
    ++policy_query_count_;
    if (!enabled_ || !policy_query_armed_ || policy_query_count_ != 1) {
      ReportFailure(
          WasmPersistentDefaultPartitionShutdownProbeFailureStage::kProfile);
    }
  }

  bool Run(content::BrowserContext* browser_context,
           WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold,
           base::OnceCallback<void(bool success)>
               on_selected_owner_receipts_closed) {
    DCHECK_CALLED_ON_VALID_SEQUENCE(cookie_sequence_checker_);
    if (profile_io_hold_) {
      (void)profile_io_hold.Complete(
          WasmProfileOrderedDrainLifecycle::ProfileIOCompletion::kFailed);
      ReportFailure(
          WasmPersistentDefaultPartitionShutdownProbeFailureStage::kProfile);
      return false;
    }
    profile_io_hold_.emplace(std::move(profile_io_hold));

    if (!enabled_ || failure_reported_ || partition_created_ ||
        !browser_context || !on_selected_owner_receipts_closed) {
      ReportFailure(
          WasmPersistentDefaultPartitionShutdownProbeFailureStage::kProfile);
      return false;
    }

    // No profile or startup service may have touched the default partition
    // before this one accessor. The policy virtual is armed only while
    // GetDefaultStoragePartition() internally creates its default config.
    if (browser_context->GetLoadedStoragePartitionCount() != 0u ||
        policy_query_armed_ || policy_query_count_ != 0) {
      ReportFailure(
          WasmPersistentDefaultPartitionShutdownProbeFailureStage::kProfile);
      return false;
    }
    policy_query_armed_ = true;
    // This is deliberately the first partition accessor in this artifact.
    // StoragePartitionImplMap::Get() synchronously creates and initializes
    // the default partition's service graph before returning this pointer.
    content::StoragePartition* const partition =
        browser_context->GetDefaultStoragePartition();
    policy_query_armed_ = false;
    if (failure_reported_ || policy_query_count_ != 1) {
      ReportFailure(
          WasmPersistentDefaultPartitionShutdownProbeFailureStage::kProfile);
      return false;
    }

    const content::StoragePartitionConfig* const config =
        partition ? &partition->GetConfig() : nullptr;
    if (!config || !config->is_default() || config->in_memory()) {
      ReportFailure(WasmPersistentDefaultPartitionShutdownProbeFailureStage::
                        kConfiguration);
      return false;
    }
    if (!IsWasmPersistentDefaultPartitionStructuralWitness(
            config->is_default(), config->in_memory(),
            /*partition_present=*/true,
            partition->GetPath() == browser_context->GetPath(),
            browser_context->GetLoadedStoragePartitionCount())) {
      ReportFailure(
          WasmPersistentDefaultPartitionShutdownProbeFailureStage::kPartition);
      return false;
    }

    if (!content::ArmWasmStoragePartitionShutdownNotificationForTest(
            partition,
            base::BindOnce(&WasmPersistentDefaultPartitionShutdownProbeState::
                               NotifyPartitionDestroyNotification,
                           base::Unretained(this)))) {
      ReportFailure(WasmPersistentDefaultPartitionShutdownProbeFailureStage::
                        kNotification);
      return false;
    }
    notification_armed_ = true;
    partition_created_ = true;
    browser_context_ = browser_context;
    partition_ = partition;
    owner_receipts_completion_ = std::move(on_selected_owner_receipts_closed);
    EmitMarker("DEFAULT_PARTITION_CREATED");

    // The first selected owner is a direct LocalStorage participant. Its
    // close-fence API accepts only an on-disk LevelDB commit followed by the
    // exact LocalStorage instance's database-sequence close receipt. The
    // later CookieManager sequence is deliberately separate; neither turns
    // these two selected receipts into an aggregate partition close.
    StartLocalStorageReceipt();
    return true;
  }

  void StartLocalStorageReceipt() {
    if (!enabled_ || failure_reported_ || !partition_created_ ||
        !browser_context_ || !partition_ ||
        partition_->GetPath() != browser_context_->GetPath() ||
        browser_context_->GetLoadedStoragePartitionCount() != 1u ||
        local_storage_receipt_started_ ||
        local_storage_receipt_completed_ || !owner_receipts_completion_) {
      FailLocalStorageReceipt();
      return;
    }

    std::optional<WasmProfileOrderedDrainLifecycle::ProfileIOHold>
        local_storage_profile_io_hold = TryAcquireWasmProfileStorageProfileIO();
    if (!local_storage_profile_io_hold) {
      FailLocalStorageReceipt(
          WasmPersistentDefaultPartitionShutdownProbeFailureStage::kAdmission);
      return;
    }

    WasmProfileLocalStorageSmokeInput input = CreateLocalStorageReceiptInput();
    local_storage_participant_ =
        std::make_unique<WasmProfileLocalStorageLifetimeParticipant>(
            browser_context_, partition_, partition_->GetPath(), std::move(input),
            std::move(*local_storage_profile_io_hold));
    local_storage_receipt_started_ = true;
    local_storage_operation_timeout_.Start(
        FROM_HERE, kLocalStorageOperationTimeout,
        base::BindOnce(&WasmPersistentDefaultPartitionShutdownProbeState::
                           OnLocalStorageOperationTimeout,
                       weak_ptr_factory_.GetWeakPtr()));
    if (!local_storage_participant_->Start(base::BindOnce(
            &WasmPersistentDefaultPartitionShutdownProbeState::
                OnLocalStorageReceiptClosed,
            weak_ptr_factory_.GetWeakPtr()))) {
      FailLocalStorageReceipt();
      return;
    }
  }

  void OnLocalStorageReceiptClosed(bool success) {
    local_storage_operation_timeout_.Stop();
    if (!local_storage_receipt_started_ || local_storage_receipt_completed_ ||
        failure_reported_ || !local_storage_participant_ || !success ||
        !local_storage_participant_->DidSucceed() || !browser_context_ ||
        !partition_) {
      FailLocalStorageReceipt();
      return;
    }

    local_storage_receipt_completed_ = true;
    local_storage_on_disk_commit_and_close_acknowledged_ = true;
    local_storage_participant_.reset();
    EmitMarker("PERSISTENT_LOCAL_STORAGE_ON_DISK_MAP_UPDATE_AND_CLOSE_OK");
    StartCookieReceipt();
  }

  void OnLocalStorageOperationTimeout() {
    if (!local_storage_receipt_started_ || local_storage_receipt_completed_) {
      return;
    }
    FailLocalStorageReceipt();
  }

  void StartCookieReceipt() {
    if (!enabled_ || failure_reported_ || !partition_created_ ||
        !partition_ || !local_storage_receipt_completed_ ||
        !local_storage_on_disk_commit_and_close_acknowledged_ ||
        cookie_phase_started_ || !owner_receipts_completion_) {
      ReportFailure(
          WasmPersistentDefaultPartitionShutdownProbeFailureStage::kCookie);
      ScheduleSelectedOwnerReceiptsCompletion(/*success=*/false);
      return;
    }

    // The second selected owner is a network-owned Cookies SQLite store. Its
    // logical-row readback and backend-close receipt must follow the closed
    // LocalStorage receipt before BrowserMainParts begins profile teardown.
    network::mojom::CookieManager* const cookie_manager =
        partition_->GetCookieManagerForBrowserProcess();
    if (!cookie_manager) {
      ReportFailure(
          WasmPersistentDefaultPartitionShutdownProbeFailureStage::kCookie);
      ScheduleSelectedOwnerReceiptsCompletion(/*success=*/false);
      return;
    }
    cookie_manager->CloneInterface(
        cookie_manager_.BindNewPipeAndPassReceiver());
    if (!cookie_manager_.is_bound()) {
      ReportFailure(
          WasmPersistentDefaultPartitionShutdownProbeFailureStage::kCookie);
      ScheduleSelectedOwnerReceiptsCompletion(/*success=*/false);
      return;
    }

    cookie_phase_started_ = true;
    cookie_manager_.set_disconnect_handler(base::BindOnce(
        &WasmPersistentDefaultPartitionShutdownProbeState::
            OnCookieManagerDisconnected,
        weak_ptr_factory_.GetWeakPtr()));

    net::CookieInclusionStatus syntax_status;
    const std::string cookie_value = base::NumberToString(
        base::Time::Now().ToDeltaSinceWindowsEpoch().InMicroseconds());
    pending_cookie_ = net::CanonicalCookie::Create(
        GURL(kCookieUrl),
        base::StrCat({kCookieName, "=", cookie_value,
                      "; Max-Age=31536000; Path=/; Secure; HttpOnly; "
                      "SameSite=Lax"}),
        base::Time::Now(), /*server_time=*/std::nullopt,
        /*cookie_partition_key=*/std::nullopt,
        net::CookieSourceType::kOther, &syntax_status);
    if (!pending_cookie_ || !syntax_status.IsInclude() ||
        !pending_cookie_->IsPersistent() || !BeginCookieOperation()) {
      FailCookieReceipt();
      return;
    }

    cookie_operation_timeout_.Start(
        FROM_HERE, kCookieOperationTimeout,
        base::BindOnce(&WasmPersistentDefaultPartitionShutdownProbeState::
                           OnCookieOperationTimeout,
                       weak_ptr_factory_.GetWeakPtr()));
    cookie_manager_->SetCanonicalCookie(
        *pending_cookie_, GURL(kCookieUrl),
        net::CookieOptions::MakeAllInclusive(),
        base::BindOnce(&WasmPersistentDefaultPartitionShutdownProbeState::
                           OnCookieSet,
                       weak_ptr_factory_.GetWeakPtr()));
  }

  void NotifyCreationSealed(content::BrowserContext* browser_context) {
    if (!enabled_ || failure_reported_ || !partition_created_ ||
        !HasSelectedOwnerReceiptWitness() ||
        creation_sealed_ || !browser_context) {
      ReportFailure(WasmPersistentDefaultPartitionShutdownProbeFailureStage::
                        kMap);
      return;
    }

    browser_context->SealStoragePartitionCreationForShutdown();
    if (!browser_context->IsStoragePartitionCreationSealedForShutdown()) {
      ReportFailure(WasmPersistentDefaultPartitionShutdownProbeFailureStage::
                        kMap);
      return;
    }
    creation_sealed_ = true;
    EmitMarker("PARTITION_CREATION_SEALED");

    // Exercise the sealed lazy-creation path against a configuration that
    // cannot name the loaded default partition. This must neither create a
    // partition nor recreate a map later in the shutdown transition.
    const content::StoragePartitionConfig late_partition_config =
        content::StoragePartitionConfig::Create(
            browser_context, "wasmshutdownprobe", "late-partition",
            /*in_memory=*/true);
    if (browser_context->GetStoragePartition(late_partition_config,
                                             /*can_create=*/true) != nullptr ||
        browser_context->GetLoadedStoragePartitionCount() != 1u) {
      ReportFailure(WasmPersistentDefaultPartitionShutdownProbeFailureStage::
                        kMap);
      return;
    }
    EmitMarker("LATE_PARTITION_CREATION_REJECTED");
  }

  void NotifyMapDropped(content::BrowserContext* browser_context) {
    if (!enabled_ || failure_reported_ || !partition_created_ ||
        !HasSelectedOwnerReceiptWitness() ||
        !creation_sealed_ ||
        !IsWasmPersistentDefaultPartitionShutdownNotificationWitness(
            notification_armed_, notification_dispatched_,
            content::DidWasmStoragePartitionShutdownNotificationForTest()) ||
        map_dropped_ || !browser_context ||
        !IsWasmPersistentDefaultPartitionMapDropped(
            browser_context->HasStoragePartitionMap(),
            browser_context->GetLoadedStoragePartitionCount())) {
      ReportFailure(
          WasmPersistentDefaultPartitionShutdownProbeFailureStage::kMap);
      return;
    }
    // The admission spans construction through the actual map-drop boundary.
    // Even this successful result does not permit clean storage retirement;
    // the caller explicitly selects the V4 failure-retirement disposition.
    if (!CompleteProfileIOHold(
            WasmProfileOrderedDrainLifecycle::ProfileIOCompletion::
                kSucceeded)) {
      ReportFailure(
          WasmPersistentDefaultPartitionShutdownProbeFailureStage::kAdmission);
      return;
    }
    map_dropped_ = true;
    EmitMarker("PARTITION_MAP_DROPPED");
  }

  void NotifyPrefsFenceResult(bool success) {
    if (!enabled_ || failure_reported_ || !partition_created_ ||
        !map_dropped_ || !success || prefs_fence_succeeded_) {
      ReportFailure(
          WasmPersistentDefaultPartitionShutdownProbeFailureStage::kFence);
      return;
    }
    prefs_fence_succeeded_ = true;
    EmitMarker("PREFERENCES_FENCE_OK");
  }

  bool CanUseFailureRetirement() const {
    return enabled_ && partition_created_ && creation_sealed_ &&
           HasSelectedOwnerReceiptWitness() &&
           IsWasmPersistentDefaultPartitionShutdownNotificationWitness(
               notification_armed_, notification_dispatched_,
               content::DidWasmStoragePartitionShutdownNotificationForTest()) &&
           map_dropped_ && prefs_fence_succeeded_ && !failure_reported_;
  }

  void NotifyFailureRetirement(bool success) {
    if (!CanUseFailureRetirement() || !success || retired_ || completed_) {
      ReportFailure(
          WasmPersistentDefaultPartitionShutdownProbeFailureStage::kRetirement);
      return;
    }
    retired_ = true;
    completed_ = true;
    EmitMarker("FAIL_CLOSED_RETIREMENT");
  }

  bool completed() const { return completed_ && !failure_reported_; }

  void Fail() {
    if (local_storage_receipt_started_ && !local_storage_receipt_completed_) {
      FailLocalStorageReceipt();
      return;
    }
    if (cookie_phase_started_ && !cookie_phase_completed_) {
      FailCookieReceipt();
      return;
    }
    if (owner_receipts_completion_delivery_pending_) {
      // The selected-owner callback has returned but its UI-sequence handoff
      // has not yet run. A fallback shutdown must win over a stale success
      // result and leave the primary profile admission terminal-failed.
      owner_receipts_completion_success_ = false;
    }
    ReportFailure(
        WasmPersistentDefaultPartitionShutdownProbeFailureStage::kProfile);
    if (owner_receipts_completion_ &&
        !owner_receipts_completion_delivery_pending_) {
      ScheduleSelectedOwnerReceiptsCompletion(/*success=*/false);
    }
  }

  void ReportFailure(
      WasmPersistentDefaultPartitionShutdownProbeFailureStage stage) {
    if (failure_reported_) {
      return;
    }
    failure_reported_ = true;
    if (notification_armed_ && !notification_dispatched_) {
      // A failure before the real notification returns must not leave the
      // source-selected singleton holding a stale partition pointer.
      content::CancelWasmStoragePartitionShutdownNotificationForTest();
    }
    if (owner_receipts_completion_delivery_pending_) {
      owner_receipts_completion_success_ = false;
    }
    // Before the direct LocalStorage close receipt, move the participant and
    // its independent admission into process-lifetime quarantine. Before the
    // network-owned SQLite row readback and close receipt, retain the cloned
    // CookieManager and primary admission the same way. The outer V4 seam
    // must refuse rather than retire an OPFS backend while either owner may
    // still use its storage sequence.
    if (local_storage_receipt_started_ && !local_storage_receipt_completed_) {
      local_storage_operation_timeout_.Stop();
      if (local_storage_participant_) {
        local_storage_participant_->Cancel();
        (void)local_storage_participant_->QuarantineForFailureShutdown();
        local_storage_participant_.reset();
      }
    }
    // Once every active LocalStorage participant has moved its own
    // profile-bound state into quarantine, this singleton must not retain a
    // non-owning BrowserContext or StoragePartition pointer across the
    // terminal failure/shutdown boundary.
    ClearProfileBoundPointers();
    if (cookie_phase_started_ && !cookie_phase_completed_) {
      cookie_quarantined_ = true;
      cookie_operation_timeout_.Stop();
    } else {
      (void)CompleteProfileIOHold(
          WasmProfileOrderedDrainLifecycle::ProfileIOCompletion::kFailed);
    }
    std::fprintf(stderr, "%sFAIL stage=%s\n", kMarkerPrefix,
                 FailureStageName(stage));
    std::fflush(stderr);
  }

 private:
  void ClearProfileBoundPointers() {
    partition_ = nullptr;
    browser_context_ = nullptr;
  }

  bool HasSelectedOwnerReceiptWitness() const {
    return IsWasmPersistentDefaultPartitionSelectedOwnerReceiptWitness(
        local_storage_receipt_started_,
        local_storage_on_disk_commit_and_close_acknowledged_,
        cookie_write_accepted_, cookie_store_flush_acknowledged_,
        cookie_sqlite_row_readback_succeeded_,
        cookie_store_close_acknowledged_);
  }

  bool BeginCookieOperation() {
    DCHECK_CALLED_ON_VALID_SEQUENCE(cookie_sequence_checker_);
    if (!cookie_phase_started_ || cookie_phase_completed_ ||
        cookie_quarantined_ || operation_pending_ ||
        !cookie_manager_.is_bound()) {
      return false;
    }
    operation_pending_ = true;
    return true;
  }

  bool ConsumeCookieOperationReply() {
    DCHECK_CALLED_ON_VALID_SEQUENCE(cookie_sequence_checker_);
    if (!cookie_phase_started_ || cookie_phase_completed_ ||
        cookie_quarantined_) {
      return false;
    }
    if (!operation_pending_) {
      FailCookieReceipt();
      return false;
    }
    operation_pending_ = false;
    return true;
  }

  void OnCookieSet(net::CookieAccessResult access_result) {
    DCHECK_CALLED_ON_VALID_SEQUENCE(cookie_sequence_checker_);
    if (!ConsumeCookieOperationReply()) {
      return;
    }
    if (!access_result.status.IsInclude()) {
      FailCookieReceipt();
      return;
    }

    cookie_write_accepted_ = true;
    EmitMarker("PERSISTENT_COOKIE_WRITE_ACCEPTED");
    if (!BeginCookieOperation()) {
      FailCookieReceipt();
      return;
    }
    cookie_manager_->FlushCookieStore(base::BindOnce(
        &WasmPersistentDefaultPartitionShutdownProbeState::OnCookieFlushed,
        weak_ptr_factory_.GetWeakPtr()));
  }

  void OnCookieFlushed() {
    DCHECK_CALLED_ON_VALID_SEQUENCE(cookie_sequence_checker_);
    if (!ConsumeCookieOperationReply()) {
      return;
    }

    cookie_store_flush_acknowledged_ = true;
    EmitMarker("PERSISTENT_COOKIE_STORE_FLUSH_ACKNOWLEDGED");
    if (!pending_cookie_ || !BeginCookieOperation()) {
      FailCookieReceipt();
      return;
    }
    cookie_manager_->VerifyPersistentCookieStoreReadbackForTesting(
        *pending_cookie_,
        base::BindOnce(&WasmPersistentDefaultPartitionShutdownProbeState::
                           OnCookieStoreReadback,
                       weak_ptr_factory_.GetWeakPtr()));
  }

  void OnCookieStoreReadback(bool success) {
    DCHECK_CALLED_ON_VALID_SEQUENCE(cookie_sequence_checker_);
    if (!ConsumeCookieOperationReply()) {
      return;
    }
    if (!success) {
      FailCookieReceipt();
      return;
    }

    cookie_sqlite_row_readback_succeeded_ = true;
    EmitMarker("PERSISTENT_COOKIE_SQLITE_ROW_READBACK_OK");
    if (!BeginCookieOperation()) {
      FailCookieReceipt();
      return;
    }
    cookie_manager_->CloseCookieStoreForTesting(base::BindOnce(
        &WasmPersistentDefaultPartitionShutdownProbeState::OnCookieStoreClosed,
        weak_ptr_factory_.GetWeakPtr()));
  }

  void OnCookieStoreClosed(bool success) {
    DCHECK_CALLED_ON_VALID_SEQUENCE(cookie_sequence_checker_);
    if (!ConsumeCookieOperationReply()) {
      return;
    }
    if (!success) {
      FailCookieReceipt();
      return;
    }

    cookie_store_close_acknowledged_ = true;
    EmitMarker("PERSISTENT_COOKIE_STORE_CLOSED");
    CompleteCookiePhase(/*success=*/true);
  }

  void OnCookieManagerDisconnected() {
    DCHECK_CALLED_ON_VALID_SEQUENCE(cookie_sequence_checker_);
    if (!cookie_phase_started_ || cookie_phase_completed_ ||
        cookie_store_close_acknowledged_) {
      return;
    }
    FailCookieReceipt();
  }

  void OnCookieOperationTimeout() {
    DCHECK_CALLED_ON_VALID_SEQUENCE(cookie_sequence_checker_);
    if (!cookie_phase_started_ || cookie_phase_completed_) {
      return;
    }
    FailCookieReceipt();
  }

  void FailCookieReceipt() {
    DCHECK_CALLED_ON_VALID_SEQUENCE(cookie_sequence_checker_);
    if (!cookie_phase_started_ || cookie_phase_completed_) {
      return;
    }
    ReportFailure(
        WasmPersistentDefaultPartitionShutdownProbeFailureStage::kCookie);
    CompleteCookiePhase(/*success=*/false);
  }

  void CompleteCookiePhase(bool success) {
    DCHECK_CALLED_ON_VALID_SEQUENCE(cookie_sequence_checker_);
    if (!cookie_phase_started_ || cookie_phase_completed_) {
      return;
    }
    cookie_operation_timeout_.Stop();
    operation_pending_ = false;
    cookie_phase_completed_ = true;
    pending_cookie_.reset();
    if (success) {
      // The selected SQLite row readback and close completion callback have
      // returned. Drop the remote before profile teardown.
      cookie_manager_.reset();
    } else {
      // Do not turn a Mojo disconnect or timeout into a close acknowledgement.
      // Keep the remote and primary admission quarantined so V4 refuses its
      // post-ContentMain drain/retirement transaction.
      cookie_quarantined_ = true;
    }

    ScheduleSelectedOwnerReceiptsCompletion(success);
  }

  void FailLocalStorageReceipt(
      WasmPersistentDefaultPartitionShutdownProbeFailureStage stage =
          WasmPersistentDefaultPartitionShutdownProbeFailureStage::
              kLocalStorage) {
    DCHECK_CALLED_ON_VALID_SEQUENCE(cookie_sequence_checker_);
    local_storage_operation_timeout_.Stop();
    if (local_storage_participant_) {
      // The participant owns an independent profile-I/O admission. A timeout
      // or failed result before WaitForCloseFence must retain that admission
      // and its detached resources process-wide instead of allowing the
      // primary probe hold to disguise an unobserved close as terminal.
      local_storage_participant_->Cancel();
      (void)local_storage_participant_->QuarantineForFailureShutdown();
      local_storage_participant_.reset();
    }
    ReportFailure(stage);
    ScheduleSelectedOwnerReceiptsCompletion(/*success=*/false);
  }

  void ScheduleSelectedOwnerReceiptsCompletion(bool success) {
    DCHECK_CALLED_ON_VALID_SEQUENCE(cookie_sequence_checker_);
    if (owner_receipts_completion_delivery_pending_) {
      // A fallback shutdown may race the posted successful handoff. Preserve
      // the one callback but make its result fail closed.
      if (!success) {
        owner_receipts_completion_success_ = false;
      }
      return;
    }
    if (!owner_receipts_completion_) {
      ReportFailure(
          WasmPersistentDefaultPartitionShutdownProbeFailureStage::kProfile);
      return;
    }
    if (success && !HasSelectedOwnerReceiptWitness()) {
      ReportFailure(
          WasmPersistentDefaultPartitionShutdownProbeFailureStage::kCookie);
      success = false;
    }

    // BrowserMainParts may synchronously call WasmProfile::Shutdown() when
    // this posted callback runs. No non-owning profile or partition pointer
    // may survive across that boundary; later map observations use their
    // explicit BrowserContext argument only.
    ClearProfileBoundPointers();
    owner_receipts_completion_delivery_pending_ = true;
    owner_receipts_completion_success_ = success;
    CHECK(base::SequencedTaskRunner::GetCurrentDefault()->PostTask(
        FROM_HERE,
        base::BindOnce(&WasmPersistentDefaultPartitionShutdownProbeState::
                           DeliverSelectedOwnerReceiptsCompletion,
                       base::Unretained(this))));
  }

  void DeliverSelectedOwnerReceiptsCompletion() {
    DCHECK_CALLED_ON_VALID_SEQUENCE(cookie_sequence_checker_);
    if (!owner_receipts_completion_delivery_pending_) {
      ReportFailure(
          WasmPersistentDefaultPartitionShutdownProbeFailureStage::kProfile);
      return;
    }
    owner_receipts_completion_delivery_pending_ = false;
    CHECK(owner_receipts_completion_);
    base::OnceCallback<void(bool success)> completion =
        std::move(owner_receipts_completion_);
    const bool success = owner_receipts_completion_success_;
    // The profile owner may synchronously begin shutdown. This singleton is
    // process-lifetime, but do not touch its state after handing control back
    // to BrowserMainParts.
    std::move(completion).Run(success);
  }

  void NotifyPartitionDestroyNotification() {
    if (!enabled_ || failure_reported_ || !partition_created_ ||
        !HasSelectedOwnerReceiptWitness() ||
        !creation_sealed_ || !notification_armed_ ||
        notification_dispatched_ ||
        !content::DidWasmStoragePartitionShutdownNotificationForTest()) {
      ReportFailure(WasmPersistentDefaultPartitionShutdownProbeFailureStage::
                        kNotification);
      return;
    }
    notification_dispatched_ = true;
    EmitMarker("PARTITION_DESTROY_NOTIFICATION_DISPATCHED");
  }

  bool CompleteProfileIOHold(
      WasmProfileOrderedDrainLifecycle::ProfileIOCompletion completion) {
    if (!profile_io_hold_) {
      return false;
    }
    const bool completed = profile_io_hold_->Complete(completion);
    profile_io_hold_.reset();
    return completed;
  }

  void EmitMarker(const char* marker) {
    std::fprintf(stderr, "%s%s\n", kMarkerPrefix, marker);
    std::fflush(stderr);
  }

  bool configured_ = false;
  bool enabled_ = false;
  bool policy_query_armed_ = false;
  int policy_query_count_ = 0;
  bool partition_created_ = false;
  bool local_storage_receipt_started_ = false;
  bool local_storage_receipt_completed_ = false;
  bool local_storage_on_disk_commit_and_close_acknowledged_ = false;
  bool cookie_phase_started_ = false;
  bool cookie_phase_completed_ = false;
  bool cookie_quarantined_ = false;
  bool operation_pending_ = false;
  bool cookie_write_accepted_ = false;
  bool cookie_store_flush_acknowledged_ = false;
  bool cookie_store_close_acknowledged_ = false;
  bool cookie_sqlite_row_readback_succeeded_ = false;
  bool owner_receipts_completion_delivery_pending_ = false;
  bool owner_receipts_completion_success_ = false;
  bool creation_sealed_ = false;
  bool notification_armed_ = false;
  bool notification_dispatched_ = false;
  bool map_dropped_ = false;
  bool prefs_fence_succeeded_ = false;
  bool retired_ = false;
  bool completed_ = false;
  bool failure_reported_ = false;
  std::optional<WasmProfileOrderedDrainLifecycle::ProfileIOHold>
      profile_io_hold_;
  raw_ptr<content::BrowserContext> browser_context_ = nullptr;
  raw_ptr<content::StoragePartition> partition_ = nullptr;
  std::unique_ptr<WasmProfileLocalStorageLifetimeParticipant>
      local_storage_participant_;
  mojo::Remote<network::mojom::CookieManager> cookie_manager_;
  std::unique_ptr<net::CanonicalCookie> pending_cookie_;
  base::OnceCallback<void(bool success)> owner_receipts_completion_;
  base::OneShotTimer local_storage_operation_timeout_;
  base::OneShotTimer cookie_operation_timeout_;
  SEQUENCE_CHECKER(cookie_sequence_checker_);
  base::WeakPtrFactory<WasmPersistentDefaultPartitionShutdownProbeState>
      weak_ptr_factory_{this};
};

WasmPersistentDefaultPartitionShutdownProbeState& GetProbeState() {
  static base::NoDestructor<WasmPersistentDefaultPartitionShutdownProbeState>
      state;
  return *state;
}

}  // namespace

bool IsWasmPersistentDefaultPartitionStructuralWitness(
    bool is_default,
    bool in_memory,
    bool partition_present,
    bool partition_path_matches_profile,
    size_t loaded_partition_count) {
  return is_default && !in_memory && partition_present &&
         partition_path_matches_profile && loaded_partition_count == 1u;
}

bool IsWasmPersistentDefaultPartitionMapDropped(bool has_partition_map,
                                                size_t loaded_partition_count) {
  return !has_partition_map && loaded_partition_count == 0u;
}

bool IsWasmPersistentDefaultPartitionShutdownNotificationWitness(
    bool notification_armed,
    bool notification_dispatched,
    bool content_notification_returned) {
  return notification_armed && notification_dispatched &&
         content_notification_returned;
}

bool IsWasmPersistentDefaultPartitionCookieStoreReceiptWitness(
    bool cookie_write_accepted,
    bool cookie_store_flush_acknowledged,
    bool cookie_sqlite_row_readback_succeeded,
    bool cookie_store_close_acknowledged) {
  return cookie_write_accepted && cookie_store_flush_acknowledged &&
         cookie_sqlite_row_readback_succeeded &&
         cookie_store_close_acknowledged;
}

bool IsWasmPersistentDefaultPartitionSelectedOwnerReceiptWitness(
    bool local_storage_receipt_started,
    bool local_storage_on_disk_commit_and_close_acknowledged,
    bool cookie_write_accepted,
    bool cookie_store_flush_acknowledged,
    bool cookie_sqlite_row_readback_succeeded,
    bool cookie_store_close_acknowledged) {
  return local_storage_receipt_started &&
         local_storage_on_disk_commit_and_close_acknowledged &&
         IsWasmPersistentDefaultPartitionCookieStoreReceiptWitness(
             cookie_write_accepted, cookie_store_flush_acknowledged,
             cookie_sqlite_row_readback_succeeded,
             cookie_store_close_acknowledged);
}

bool HasWasmPersistentDefaultPartitionShutdownProbeArguments() {
  return base::CommandLine::ForCurrentProcess()->HasSwitch(kProbeSwitch);
}

bool EnableWasmPersistentDefaultPartitionShutdownProbe() {
  return GetProbeState().EnableFromCommandLine();
}

bool IsWasmPersistentDefaultPartitionShutdownProbeEnabled() {
  return GetProbeState().enabled();
}

void RecordWasmPersistentDefaultPartitionShutdownProbePolicyQuery() {
  GetProbeState().RecordPolicyQuery();
}

bool RunWasmPersistentDefaultPartitionShutdownProbe(
    content::BrowserContext* browser_context,
    WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold,
    base::OnceCallback<void(bool success)> on_selected_owner_receipts_closed) {
  return GetProbeState().Run(browser_context, std::move(profile_io_hold),
                             std::move(on_selected_owner_receipts_closed));
}

void NotifyWasmPersistentDefaultPartitionShutdownProbeCreationSealed(
    content::BrowserContext* browser_context) {
  GetProbeState().NotifyCreationSealed(browser_context);
}

void NotifyWasmPersistentDefaultPartitionShutdownProbeMapDropped(
    content::BrowserContext* browser_context) {
  GetProbeState().NotifyMapDropped(browser_context);
}

void NotifyWasmPersistentDefaultPartitionShutdownProbePrefsFenceResult(
    bool success) {
  GetProbeState().NotifyPrefsFenceResult(success);
}

void FailWasmPersistentDefaultPartitionShutdownProbe() {
  GetProbeState().Fail();
}

bool CanWasmPersistentDefaultPartitionShutdownProbeUseFailureRetirement() {
  return GetProbeState().CanUseFailureRetirement();
}

void NotifyWasmPersistentDefaultPartitionShutdownProbeFailureRetirement(
    bool success) {
  GetProbeState().NotifyFailureRetirement(success);
}

bool DidWasmPersistentDefaultPartitionShutdownProbeComplete() {
  return GetProbeState().completed();
}

void ReportWasmPersistentDefaultPartitionShutdownProbeFailure(
    WasmPersistentDefaultPartitionShutdownProbeFailureStage stage) {
  GetProbeState().ReportFailure(stage);
}

}  // namespace chrome
