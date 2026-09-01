// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE_H_

#include <cstddef>

#include "chrome/browser/wasm/wasm_profile_ordered_drain_lifecycle.h"

namespace content {
class BrowserContext;
}  // namespace content

namespace chrome {

// Fixed failure grammar for the source-selected structural shutdown probe.
// Its only positive result is that Chromium constructed the real persistent
// default StoragePartition and then synchronously dropped its map during
// Profile shutdown. It deliberately does not claim an aggregate partition
// close, a durable flush, recovery, or fresh-document persistence.
enum class WasmPersistentDefaultPartitionShutdownProbeFailureStage {
  kArguments,
  kStorage,
  kProfile,
  kConfiguration,
  kPartition,
  kNotification,
  kMap,
  kAdmission,
  kFence,
  kRetirement,
  kDrain,
};

// Kept separately testable so the live probe's exact structural requirements
// cannot drift from its focused unit test. |partition_path_matches_profile|
// is true only when StoragePartition::GetPath() is exactly BrowserContext's
// profile path, which is the expected path for the default partition.
bool IsWasmPersistentDefaultPartitionStructuralWitness(
    bool is_default,
    bool in_memory,
    bool partition_present,
    bool partition_path_matches_profile,
    size_t loaded_partition_count);

// BrowserContext::ShutdownStoragePartitions() resets its map synchronously,
// but individual StoragePartitionImpl owners may continue asynchronous
// teardown. This classification requires the map itself to be absent, not just
// empty, and remains only an instantaneous map-drop observation.
bool IsWasmPersistentDefaultPartitionMapDropped(bool has_partition_map,
                                                size_t loaded_partition_count);

// The structural probe requires the exact default partition's real
// OnBrowserContextWillBeDestroyed() notification to return before accepting a
// later map drop. This remains distinct from an asynchronous service-close or
// durable-storage acknowledgement.
bool IsWasmPersistentDefaultPartitionShutdownNotificationWitness(
    bool notification_armed,
    bool notification_dispatched,
    bool content_notification_returned);

bool HasWasmPersistentDefaultPartitionShutdownProbeArguments();
bool EnableWasmPersistentDefaultPartitionShutdownProbe();
bool IsWasmPersistentDefaultPartitionShutdownProbeEnabled();

// Records the default-partition policy virtual. Run() arms exactly one query
// around its one default-partition accessor; an early, missing, or extra query
// fails the structural probe before it can be mistaken for a controlled
// default-partition construction.
void RecordWasmPersistentDefaultPartitionShutdownProbePolicyQuery();

// Creates the actual default StoragePartition after verifying that
// CreateDefault() selected a non-memory configuration. The helper retains the
// profile-I/O hold until the profile has synchronously dropped its partition
// map. Callers must still choose failure retirement rather than a clean V4
// handoff.
bool RunWasmPersistentDefaultPartitionShutdownProbe(
    content::BrowserContext* browser_context,
    WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold);

// Seals BrowserContext's lazy partition-creation entry point before profile
// teardown. It is deliberately separate from the later map-drop observation:
// the helper also requires the core accessor to reject one new configuration
// before the first map is destroyed.
void NotifyWasmPersistentDefaultPartitionShutdownProbeCreationSealed(
    content::BrowserContext* browser_context);

// Must run immediately after WasmProfile::Shutdown() and before a shutdown
// fence can permit Profile destruction. It accepts only an absent map.
void NotifyWasmPersistentDefaultPartitionShutdownProbeMapDropped(
    content::BrowserContext* browser_context);
void NotifyWasmPersistentDefaultPartitionShutdownProbePrefsFenceResult(
    bool success);

// Completes a retained probe admission as failed when BrowserMainParts loses
// its normal profile owner before the map-drop observation. This prevents an
// abandoned hold from disguising a structural probe failure as a generic
// outstanding-I/O condition.
void FailWasmPersistentDefaultPartitionShutdownProbe();

// This probe never permits clean storage shutdown. It returns true only if
// its bounded structural observations succeeded and the caller has selected
// the mandatory sealed/lease-retained failure-retirement path.
bool CanWasmPersistentDefaultPartitionShutdownProbeUseFailureRetirement();
void NotifyWasmPersistentDefaultPartitionShutdownProbeFailureRetirement(
    bool success);
bool DidWasmPersistentDefaultPartitionShutdownProbeComplete();

void ReportWasmPersistentDefaultPartitionShutdownProbeFailure(
    WasmPersistentDefaultPartitionShutdownProbeFailureStage stage);

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_PROFILE_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE_H_
