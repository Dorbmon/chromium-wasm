// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE_H_

#include <cstddef>

#include "base/functional/callback_forward.h"
#include "chrome/browser/wasm/wasm_profile_ordered_drain_lifecycle.h"

namespace content {
class BrowserContext;
}  // namespace content

namespace chrome {

// Fixed failure grammar for the source-selected shutdown probe. Its narrow
// positive observations are one persistent default StoragePartition's
// CookieManager write/flush/SQLite-row-readback/close receipts and the later
// map-drop boundary.
// It deliberately does not claim an aggregate partition close, a durable
// profile flush, recovery, or fresh-document persistence.
enum class WasmPersistentDefaultPartitionShutdownProbeFailureStage {
  kArguments,
  kStorage,
  kProfile,
  kConfiguration,
  kPartition,
  kCookie,
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

// The source-selected probe accepts a persistent cookie write, awaits a
// backing-store flush acknowledgement, asks the selected CookieManager's
// SQLite owner to read a matching logical row on its own sequence, then
// requires its test-only close completion receipt. This classifies one
// selected cookie-store receipt; it is deliberately neither an aggregate
// StoragePartition close nor a profile durability acknowledgement.
bool IsWasmPersistentDefaultPartitionCookieStoreReceiptWitness(
    bool cookie_write_accepted,
    bool cookie_store_flush_acknowledged,
    bool cookie_sqlite_row_readback_succeeded,
    bool cookie_store_close_acknowledged);

bool HasWasmPersistentDefaultPartitionShutdownProbeArguments();
bool EnableWasmPersistentDefaultPartitionShutdownProbe();
bool IsWasmPersistentDefaultPartitionShutdownProbeEnabled();

// Records the default-partition policy virtual. Run() arms exactly one query
// around its one default-partition accessor; an early, missing, or extra query
// fails the structural probe before it can be mistaken for a controlled
// default-partition construction.
void RecordWasmPersistentDefaultPartitionShutdownProbePolicyQuery();

// Creates the actual default StoragePartition after verifying that
// CreateDefault() selected a non-memory configuration. It then writes one
// persistent test cookie through that partition's cloned CookieManager,
// awaits the backing-store flush acknowledgement, performs a network-owned
// matching SQLite logical-row readback, and receives the test-only
// cookie-store close completion receipt before invoking
// |on_cookie_store_closed|. The helper retains the profile-I/O hold through
// the later synchronous partition-map drop. Callers must still choose failure
// retirement rather than a clean V4 handoff.
bool RunWasmPersistentDefaultPartitionShutdownProbe(
    content::BrowserContext* browser_context,
    WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold,
    base::OnceCallback<void(bool success)> on_cookie_store_closed);

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
