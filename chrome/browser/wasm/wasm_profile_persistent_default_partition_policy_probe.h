// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE_H_

#include "chrome/browser/wasm/wasm_profile_ordered_drain_lifecycle.h"
#include "content/public/browser/storage_partition_config.h"

namespace content {
class BrowserContext;
}  // namespace content

namespace chrome {

// Fixed failure grammar for the dedicated policy/configuration probe. None of
// these states claim that a StoragePartition service, reload, or crash
// persistence was exercised.
enum class WasmPersistentDefaultPartitionPolicyProbeFailureStage {
  kArguments,
  kStorage,
  kProfile,
  kConfiguration,
  kPolicyQuery,
  kAdmission,
  kFence,
  kLifecycle,
  kContent,
  kDrain,
};

// Kept separately testable so the runtime path can make the exact pure
// StoragePartitionConfig assertion without constructing a StoragePartition.
bool IsWasmPersistentDefaultPartitionConfigProperties(bool is_default,
                                                       bool in_memory);
bool IsWasmPersistentDefaultPartitionConfig(
    const content::StoragePartitionConfig& config);

bool HasWasmPersistentDefaultPartitionPolicyProbeArguments();
bool EnableWasmPersistentDefaultPartitionPolicyProbe();
bool IsWasmPersistentDefaultPartitionPolicyProbeEnabled();

// Records the policy virtual consulted by CreateDefault(). Run() arms exactly
// one such query around its pure configuration construction. An earlier,
// missing, or extra query fails the probe closed so profile construction cannot
// silently expand this configuration-only boundary.
void RecordWasmPersistentDefaultPartitionPolicyProbePolicyQuery();

// Performs the one permitted default-partition operation: a pure
// StoragePartitionConfig::CreateDefault() call. |profile_io_hold| is completed
// with the outcome so a failed policy observation can only use the existing
// fail-closed V4 retirement path. This function never calls the default
// partition accessor and cannot create a StoragePartition, WebContents,
// NetworkContext, or storage service.
bool RunWasmPersistentDefaultPartitionPolicyProbe(
    content::BrowserContext* browser_context,
    WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold);

bool DidWasmPersistentDefaultPartitionPolicyProbeConfigSucceed();
bool CanWasmPersistentDefaultPartitionPolicyProbeUseCleanShutdown();
bool DidWasmPersistentDefaultPartitionPolicyProbeComplete();

void NotifyWasmPersistentDefaultPartitionPolicyProbePrefsFenceResult(
    bool success);
void NotifyWasmPersistentDefaultPartitionPolicyProbeStorageLifecycle(
    bool success);
void NotifyWasmPersistentDefaultPartitionPolicyProbeBackendDrain(bool success);
void ReportWasmPersistentDefaultPartitionPolicyProbeFailure(
    WasmPersistentDefaultPartitionPolicyProbeFailureStage stage);

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_PROFILE_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE_H_
