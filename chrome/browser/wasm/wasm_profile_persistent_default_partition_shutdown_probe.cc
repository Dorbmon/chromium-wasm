// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_persistent_default_partition_shutdown_probe.h"

#include <cstdio>
#include <optional>
#include <utility>

#include "base/command_line.h"
#include "base/files/file_path.h"
#include "base/functional/bind.h"
#include "base/no_destructor.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/storage_partition.h"
#include "content/public/browser/storage_partition_config.h"
#include "content/public/browser/wasm_storage_partition_shutdown_test_support.h"

namespace chrome {

namespace {

constexpr char kProbeSwitch[] =
    "wasm-persistent-default-partition-shutdown-probe";
constexpr char kMarkerPrefix[] =
    "CHROMIUM_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN:";

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
           WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold) {
    if (profile_io_hold_) {
      (void)profile_io_hold.Complete(
          WasmProfileOrderedDrainLifecycle::ProfileIOCompletion::kFailed);
      ReportFailure(
          WasmPersistentDefaultPartitionShutdownProbeFailureStage::kProfile);
      return false;
    }
    profile_io_hold_.emplace(std::move(profile_io_hold));

    if (!enabled_ || failure_reported_ || partition_created_ ||
        !browser_context) {
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
    return true;
  }

  void NotifyCreationSealed(content::BrowserContext* browser_context) {
    if (!enabled_ || failure_reported_ || !partition_created_ ||
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
    (void)CompleteProfileIOHold(
        WasmProfileOrderedDrainLifecycle::ProfileIOCompletion::kFailed);
    std::fprintf(stderr, "%sFAIL stage=%s\n", kMarkerPrefix,
                 FailureStageName(stage));
    std::fflush(stderr);
  }

 private:
  void NotifyPartitionDestroyNotification() {
    if (!enabled_ || failure_reported_ || !partition_created_ ||
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
    WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold) {
  return GetProbeState().Run(browser_context, std::move(profile_io_hold));
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
