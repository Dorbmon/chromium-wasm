// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE_H_

#include <cstddef>
#include <optional>

#include "base/functional/callback_forward.h"
#include "chrome/browser/wasm/wasm_profile_ordered_drain_lifecycle.h"
#include "content/public/browser/storage_partition_config.h"

namespace content {
class BrowserContext;
}  // namespace content

class GURL;

namespace chrome {

// Fixed failure grammar for the source-selected shutdown probe. Its narrow
// positive observations are one persistent default StoragePartition's direct
// LocalStorage map-update/close receipt, a renderer IndexedDB
// write/selected-bucket-close receipt, CookieManager
// write/flush/SQLite-row-readback/close receipts, and the later map-drop
// boundary. It fails closed before the one initial default-partition config
// derivation, then permits later nonallocating SiteInfo/frame-host config
// derivations and proves renderer use from the actual committed partition plus
// sole-map/no-create observations.
// It deliberately does not claim an aggregate partition close, a durable
// profile flush, recovery, or fresh-document persistence.
enum class WasmPersistentDefaultPartitionShutdownProbeFailureStage {
  kArguments,
  kStorage,
  kProfile,
  kConfiguration,
  kPartition,
  kLocalStorage,
  kIndexedDB,
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

// This probe has receipts for exactly three selected persistent owners: the
// LocalStorage LevelDB close-fence participant, one renderer-created IndexedDB
// bucket, and CookieManager's SQLite store. The LocalStorage result means only
// an on-disk LevelDB map-update snapshot/commit result followed by exact
// LocalStorage destruction and a database-sequence FIFO receipt; it is not an
// fsync or physical-crash durability result. The IndexedDB result is only the
// renderer-selected bucket's ForceClose callback after the renderer closed its
// database. Its receipt also requires captured-config reuse, the committed
// renderer frame's exact default-partition identity, and sole-map/no-create
// checks at the renderer handoff boundaries. Their conjunction deliberately
// does not classify an aggregate StoragePartition close, a durable profile
// flush, or profile persistence.
bool IsWasmPersistentDefaultPartitionSelectedOwnerReceiptWitness(
    bool local_storage_receipt_started,
    bool local_storage_on_disk_commit_and_close_acknowledged,
    bool renderer_default_partition_config_reuse_witness,
    bool indexed_db_renderer_write_and_close_acknowledged,
    bool cookie_write_accepted,
    bool cookie_store_flush_acknowledged,
    bool cookie_sqlite_row_readback_succeeded,
    bool cookie_store_close_acknowledged);

bool HasWasmPersistentDefaultPartitionShutdownProbeArguments();
bool EnableWasmPersistentDefaultPartitionShutdownProbe();
bool IsWasmPersistentDefaultPartitionShutdownProbeEnabled();

// Records the default-partition policy virtual for |browser_context|. Run()
// accepts exactly one initial CreateDefault() derivation while it constructs
// the real default partition, and fails closed before that creation. Chromium
// can legitimately derive the same config later for SiteInfo/frame-host
// bookkeeping; those later nonallocating calls are not a renderer witness.
void RecordWasmPersistentDefaultPartitionShutdownProbePolicyQuery(
    content::BrowserContext* browser_context);

// Gives the source-selected ContentBrowserClient the exact config captured from
// the real persistent default partition for the one test WebUI site's canonical
// root and exact generated document. Returning the captured config makes the
// renderer's later SiteInfo derivations reuse that exact config. It returns
// nullopt for every other context or site.
std::optional<content::StoragePartitionConfig>
TakeWasmPersistentDefaultPartitionShutdownProbeRendererConfigForSite(
    content::BrowserContext* browser_context,
    const GURL& site);

// Creates the actual default StoragePartition after verifying that
// CreateDefault() selected a non-memory configuration. It first drives one
// direct LocalStorage write through the existing selected close-fence
// participant, which requires an on-disk LevelDB map-update snapshot/commit
// result and the same LocalStorage instance's database-sequence FIFO close
// receipt. It then creates one unassigned renderer SiteInstance and performs
// one renderer IndexedDB write and selected-bucket close receipt in that same
// default partition. The renderer witness checks the captured config, actual
// committed frame partition pointer/config/profile path, and sole
// partition-map no-create lookups before and after the selected close. It then
// writes one persistent test cookie through the partition's cloned
// CookieManager, awaits the backing-store flush acknowledgement, performs a
// network-owned matching SQLite logical-row readback, and receives the
// test-only cookie-store close completion receipt before invoking
// |on_selected_owner_receipts_closed|. The helper retains its primary
// profile-I/O hold through the later synchronous partition-map drop. These
// remain three selected receipts only; callers must choose failure retirement
// rather than a clean V4 handoff.
bool RunWasmPersistentDefaultPartitionShutdownProbe(
    content::BrowserContext* browser_context,
    WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold,
    base::OnceCallback<void(bool success)> on_selected_owner_receipts_closed);

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
