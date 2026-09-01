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
#include "base/memory/weak_ptr.h"
#include "base/no_destructor.h"
#include "base/sequence_checker.h"
#include "base/strings/strcat.h"
#include "base/strings/string_number_conversions.h"
#include "base/task/sequenced_task_runner.h"
#include "base/time/time.h"
#include "base/timer/timer.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/storage_partition.h"
#include "content/public/browser/storage_partition_config.h"
#include "content/public/browser/wasm_storage_partition_shutdown_test_support.h"
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
constexpr base::TimeDelta kCookieOperationTimeout = base::Seconds(20);

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
           base::OnceCallback<void(bool success)> on_cookie_store_closed) {
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
        !browser_context || !on_cookie_store_closed) {
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
    EmitMarker("DEFAULT_PARTITION_CREATED");

    // This source-selected clone is the only asynchronous owner retained by
    // the probe. Its network-owned SQLite row readback and backend-close
    // receipts must both return before BrowserMainParts begins ordinary
    // profile teardown; the primary admission remains live until the later
    // map-drop boundary.
    network::mojom::CookieManager* const cookie_manager =
        partition->GetCookieManagerForBrowserProcess();
    if (!cookie_manager) {
      ReportFailure(
          WasmPersistentDefaultPartitionShutdownProbeFailureStage::kCookie);
      return false;
    }
    cookie_manager->CloneInterface(
        cookie_manager_.BindNewPipeAndPassReceiver());
    if (!cookie_manager_.is_bound()) {
      ReportFailure(
          WasmPersistentDefaultPartitionShutdownProbeFailureStage::kCookie);
      return false;
    }

    cookie_phase_started_ = true;
    cookie_completion_ = std::move(on_cookie_store_closed);
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
      return true;
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
    return true;
  }

  void NotifyCreationSealed(content::BrowserContext* browser_context) {
    if (!enabled_ || failure_reported_ || !partition_created_ ||
        !IsWasmPersistentDefaultPartitionCookieStoreReceiptWitness(
            cookie_write_accepted_, cookie_store_flush_acknowledged_,
            cookie_sqlite_row_readback_succeeded_,
            cookie_store_close_acknowledged_) ||
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
        !IsWasmPersistentDefaultPartitionCookieStoreReceiptWitness(
            cookie_write_accepted_, cookie_store_flush_acknowledged_,
            cookie_sqlite_row_readback_succeeded_,
            cookie_store_close_acknowledged_) ||
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
           IsWasmPersistentDefaultPartitionCookieStoreReceiptWitness(
               cookie_write_accepted_, cookie_store_flush_acknowledged_,
               cookie_sqlite_row_readback_succeeded_,
               cookie_store_close_acknowledged_) &&
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
    if (cookie_phase_started_ && !cookie_phase_completed_) {
      FailCookieReceipt();
      return;
    }
    if (cookie_completion_delivery_pending_) {
      // The backend-close completion callback has returned but its UI-sequence
      // handoff has not yet run. A fallback shutdown must win over a stale
      // success result and leave the profile admission terminal-failed.
      cookie_completion_success_ = false;
    }
    ReportFailure(
        WasmPersistentDefaultPartitionShutdownProbeFailureStage::kProfile);
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
    // Before the network-owned SQLite row readback and close receipt, retain
    // the clone and its admission for process lifetime. The outer V4 seam
    // must refuse rather than retire an OPFS backend while CookieManager may
    // still use its SQLite task sequence. Once those receipts exist, an
    // unrelated later failure can make the admission terminal-failed normally.
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

    CHECK(cookie_completion_);
    // Do not let the CookieManager Mojo dispatch synchronously tear down its
    // owning NetworkContext. BrowserMainParts resumes on the next UI turn,
    // after this callback has completely unwound.
    cookie_completion_delivery_pending_ = true;
    cookie_completion_success_ = success;
    CHECK(base::SequencedTaskRunner::GetCurrentDefault()->PostTask(
        FROM_HERE,
        base::BindOnce(&WasmPersistentDefaultPartitionShutdownProbeState::
                           DeliverCookiePhaseCompletion,
                       base::Unretained(this))));
  }

  void DeliverCookiePhaseCompletion() {
    DCHECK_CALLED_ON_VALID_SEQUENCE(cookie_sequence_checker_);
    if (!cookie_completion_delivery_pending_) {
      ReportFailure(
          WasmPersistentDefaultPartitionShutdownProbeFailureStage::kCookie);
      return;
    }
    cookie_completion_delivery_pending_ = false;
    CHECK(cookie_completion_);
    base::OnceCallback<void(bool success)> completion =
        std::move(cookie_completion_);
    const bool success = cookie_completion_success_;
    // The profile owner may synchronously begin shutdown. This singleton is
    // process-lifetime, but do not touch this callback state after handing
    // control back to BrowserMainParts.
    std::move(completion).Run(success);
  }

  void NotifyPartitionDestroyNotification() {
    if (!enabled_ || failure_reported_ || !partition_created_ ||
        !IsWasmPersistentDefaultPartitionCookieStoreReceiptWitness(
            cookie_write_accepted_, cookie_store_flush_acknowledged_,
            cookie_sqlite_row_readback_succeeded_,
            cookie_store_close_acknowledged_) ||
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
  bool cookie_phase_started_ = false;
  bool cookie_phase_completed_ = false;
  bool cookie_quarantined_ = false;
  bool operation_pending_ = false;
  bool cookie_write_accepted_ = false;
  bool cookie_store_flush_acknowledged_ = false;
  bool cookie_store_close_acknowledged_ = false;
  bool cookie_sqlite_row_readback_succeeded_ = false;
  bool cookie_completion_delivery_pending_ = false;
  bool cookie_completion_success_ = false;
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
  mojo::Remote<network::mojom::CookieManager> cookie_manager_;
  std::unique_ptr<net::CanonicalCookie> pending_cookie_;
  base::OnceCallback<void(bool success)> cookie_completion_;
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
    base::OnceCallback<void(bool success)> on_cookie_store_closed) {
  return GetProbeState().Run(browser_context, std::move(profile_io_hold),
                             std::move(on_cookie_store_closed));
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
