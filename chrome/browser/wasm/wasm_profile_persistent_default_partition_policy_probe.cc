// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_persistent_default_partition_policy_probe.h"

#include <cstdio>
#include <utility>

#include "base/command_line.h"
#include "content/public/browser/browser_context.h"

namespace chrome {

namespace {

constexpr char kProbeSwitch[] =
    "wasm-persistent-default-partition-policy-probe";
constexpr char kMarkerPrefix[] =
    "CHROMIUM_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY:";

const char* FailureStageName(
    WasmPersistentDefaultPartitionPolicyProbeFailureStage stage) {
  switch (stage) {
    case WasmPersistentDefaultPartitionPolicyProbeFailureStage::kArguments:
      return "arguments";
    case WasmPersistentDefaultPartitionPolicyProbeFailureStage::kStorage:
      return "storage";
    case WasmPersistentDefaultPartitionPolicyProbeFailureStage::kProfile:
      return "profile";
    case WasmPersistentDefaultPartitionPolicyProbeFailureStage::kConfiguration:
      return "configuration";
    case WasmPersistentDefaultPartitionPolicyProbeFailureStage::kPolicyQuery:
      return "policy-query";
    case WasmPersistentDefaultPartitionPolicyProbeFailureStage::kAdmission:
      return "admission";
    case WasmPersistentDefaultPartitionPolicyProbeFailureStage::kFence:
      return "fence";
    case WasmPersistentDefaultPartitionPolicyProbeFailureStage::kLifecycle:
      return "lifecycle";
    case WasmPersistentDefaultPartitionPolicyProbeFailureStage::kContent:
      return "content";
    case WasmPersistentDefaultPartitionPolicyProbeFailureStage::kDrain:
      return "drain";
  }
  return "lifecycle";
}

class WasmPersistentDefaultPartitionPolicyProbeState {
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
          WasmPersistentDefaultPartitionPolicyProbeFailureStage::kArguments);
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
          WasmPersistentDefaultPartitionPolicyProbeFailureStage::kPolicyQuery);
    }
  }

  bool Run(content::BrowserContext* browser_context,
           WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold) {
    bool succeeded = false;
    if (!enabled_ || failure_reported_ || config_checked_ || !browser_context) {
      ReportFailure(
          WasmPersistentDefaultPartitionPolicyProbeFailureStage::kProfile);
    } else if (policy_query_armed_ || policy_query_count_ != 0) {
      // A BrowserContext service queried the policy before this exact
      // configuration witness. Do not issue the witness query after that
      // boundary has already been crossed.
      ReportFailure(
          WasmPersistentDefaultPartitionPolicyProbeFailureStage::kPolicyQuery);
    } else {
      // CreateDefault() asks only the BrowserContext policy virtuals. It does
      // not reach StoragePartitionImplMap::Get(), so this probe cannot create a
      // StoragePartition or any partition-owned browser service.
      policy_query_armed_ = true;
      const content::StoragePartitionConfig config =
          content::StoragePartitionConfig::CreateDefault(browser_context);
      policy_query_armed_ = false;
      if (policy_query_count_ != 1) {
        ReportFailure(
            WasmPersistentDefaultPartitionPolicyProbeFailureStage::kPolicyQuery);
      } else if (!IsWasmPersistentDefaultPartitionConfig(config)) {
        ReportFailure(WasmPersistentDefaultPartitionPolicyProbeFailureStage::
                          kConfiguration);
      } else {
        config_checked_ = true;
        succeeded = true;
        EmitMarker("DEFAULT_CONFIG_DEFAULT_NOT_IN_MEMORY");
      }
    }

    if (!profile_io_hold.Complete(
            succeeded
                ? WasmProfileOrderedDrainLifecycle::ProfileIOCompletion::
                      kSucceeded
                : WasmProfileOrderedDrainLifecycle::ProfileIOCompletion::
                      kFailed)) {
      ReportFailure(
          WasmPersistentDefaultPartitionPolicyProbeFailureStage::kAdmission);
      return false;
    }
    return succeeded;
  }

  bool config_succeeded() const {
    return config_checked_ && policy_query_count_ == 1 &&
           !policy_query_armed_ && !failure_reported_;
  }

  bool CanUseCleanShutdown() const {
    return enabled_ && config_checked_ && fence_succeeded_ &&
           policy_query_count_ == 1 && !policy_query_armed_ &&
           !failure_reported_;
  }

  bool completed() const { return completed_ && !failure_reported_; }

  void NotifyPrefsFenceResult(bool success) {
    if (!enabled_ || failure_reported_ || !config_checked_ || !success ||
        fence_succeeded_) {
      ReportFailure(
          WasmPersistentDefaultPartitionPolicyProbeFailureStage::kFence);
      return;
    }
    fence_succeeded_ = true;
    EmitMarker("FENCE_OK");
  }

  void NotifyStorageLifecycle(bool success) {
    if (!CanUseCleanShutdown() || !success || storage_lifecycle_succeeded_) {
      ReportFailure(
          WasmPersistentDefaultPartitionPolicyProbeFailureStage::kLifecycle);
      return;
    }
    storage_lifecycle_succeeded_ = true;
  }

  void NotifyBackendDrain(bool success) {
    if (!enabled_ || failure_reported_ || !config_checked_ ||
        policy_query_count_ != 1 || policy_query_armed_ || !fence_succeeded_ ||
        !storage_lifecycle_succeeded_ || !success || completed_) {
      ReportFailure(
          WasmPersistentDefaultPartitionPolicyProbeFailureStage::kDrain);
      return;
    }
    completed_ = true;
    // This is a policy/configuration completion receipt only. It is never a
    // claim that a default StoragePartition service persisted, recovered after
    // a crash, or survived a fresh browser document.
    EmitMarker("POLICY_PROBE_COMPLETE");
  }

  void ReportFailure(
      WasmPersistentDefaultPartitionPolicyProbeFailureStage stage) {
    if (failure_reported_) {
      return;
    }
    failure_reported_ = true;
    std::fprintf(stderr, "%sFAIL stage=%s\n", kMarkerPrefix,
                 FailureStageName(stage));
    std::fflush(stderr);
  }

 private:
  void EmitMarker(const char* marker) {
    std::fprintf(stderr, "%s%s\n", kMarkerPrefix, marker);
    std::fflush(stderr);
  }

  bool configured_ = false;
  bool enabled_ = false;
  bool config_checked_ = false;
  bool policy_query_armed_ = false;
  int policy_query_count_ = 0;
  bool fence_succeeded_ = false;
  bool storage_lifecycle_succeeded_ = false;
  bool completed_ = false;
  bool failure_reported_ = false;
};

WasmPersistentDefaultPartitionPolicyProbeState& GetProbeState() {
  // The state is trivially destructible, so Chromium requires a direct local
  // static rather than base::NoDestructor.
  static WasmPersistentDefaultPartitionPolicyProbeState state;
  return state;
}

}  // namespace

bool IsWasmPersistentDefaultPartitionConfigProperties(bool is_default,
                                                       bool in_memory) {
  return is_default && !in_memory;
}

bool IsWasmPersistentDefaultPartitionConfig(
    const content::StoragePartitionConfig& config) {
  return IsWasmPersistentDefaultPartitionConfigProperties(config.is_default(),
                                                           config.in_memory());
}

bool HasWasmPersistentDefaultPartitionPolicyProbeArguments() {
  return base::CommandLine::ForCurrentProcess()->HasSwitch(kProbeSwitch);
}

bool EnableWasmPersistentDefaultPartitionPolicyProbe() {
  return GetProbeState().EnableFromCommandLine();
}

bool IsWasmPersistentDefaultPartitionPolicyProbeEnabled() {
  return GetProbeState().enabled();
}

void RecordWasmPersistentDefaultPartitionPolicyProbePolicyQuery() {
  GetProbeState().RecordPolicyQuery();
}

bool RunWasmPersistentDefaultPartitionPolicyProbe(
    content::BrowserContext* browser_context,
    WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold) {
  return GetProbeState().Run(browser_context, std::move(profile_io_hold));
}

bool DidWasmPersistentDefaultPartitionPolicyProbeConfigSucceed() {
  return GetProbeState().config_succeeded();
}

bool CanWasmPersistentDefaultPartitionPolicyProbeUseCleanShutdown() {
  return GetProbeState().CanUseCleanShutdown();
}

bool DidWasmPersistentDefaultPartitionPolicyProbeComplete() {
  return GetProbeState().completed();
}

void NotifyWasmPersistentDefaultPartitionPolicyProbePrefsFenceResult(
    bool success) {
  GetProbeState().NotifyPrefsFenceResult(success);
}

void NotifyWasmPersistentDefaultPartitionPolicyProbeStorageLifecycle(
    bool success) {
  GetProbeState().NotifyStorageLifecycle(success);
}

void NotifyWasmPersistentDefaultPartitionPolicyProbeBackendDrain(bool success) {
  GetProbeState().NotifyBackendDrain(success);
}

void ReportWasmPersistentDefaultPartitionPolicyProbeFailure(
    WasmPersistentDefaultPartitionPolicyProbeFailureStage stage) {
  GetProbeState().ReportFailure(stage);
}

}  // namespace chrome
