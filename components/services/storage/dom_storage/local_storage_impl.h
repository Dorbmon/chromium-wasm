// Copyright 2016 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef COMPONENTS_SERVICES_STORAGE_DOM_STORAGE_LOCAL_STORAGE_IMPL_H_
#define COMPONENTS_SERVICES_STORAGE_DOM_STORAGE_LOCAL_STORAGE_IMPL_H_

#include <stdint.h>

#include <map>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <vector>

#include "base/files/file_path.h"
#include "base/functional/callback_forward.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/scoped_refptr.h"
#include "base/threading/sequence_bound.h"
#include "base/trace_event/memory_allocator_dump.h"
#include "base/trace_event/memory_dump_provider.h"
#include "components/services/storage/dom_storage/async_dom_storage_database.h"
#include "components/services/storage/dom_storage/db_status.h"
#include "components/services/storage/dom_storage/dom_storage_database.h"
#include "components/services/storage/dom_storage/dom_storage_histogram_helper.h"
#include "components/services/storage/dom_storage/storage_area_impl.h"
#include "components/services/storage/public/mojom/local_storage_control.mojom.h"
#include "components/services/storage/public/mojom/storage_policy_update.mojom.h"
#include "components/services/storage/public/mojom/storage_usage_info.mojom.h"
#include "mojo/public/cpp/bindings/pending_receiver.h"
#include "mojo/public/cpp/bindings/receiver.h"
#include "third_party/blink/public/common/storage_key/storage_key.h"
#include "third_party/blink/public/mojom/dom_storage/storage_area.mojom.h"

namespace storage {

class StorageServiceImpl;
// The Local Storage implementation. An instance of this class exists for each
// profile directory (within the user data directory) that is using Local
// Storage. It manages storage for all StorageKeys and namespaces within that
// partition.
class LocalStorageImpl : public base::trace_event::MemoryDumpProvider,
                         public mojom::LocalStorageControl {
 public:
  using DestructLocalStorageCallback =
      base::OnceCallback<void(LocalStorageImpl*)>;

  // A terminal report for the StorageAreaImpl holders that existed at this
  // request's admission point. No ScopeOutcome is a Flush, shutdown,
  // durability, profile-quiescence, or OPFS-lease success signal.
  struct ImmediateCommitSnapshotResult {
    enum class ScopeOutcome {
      // Every captured holder supplied a terminal area result. Callers must
      // inspect each result rather than treating this as a persistence success.
      kAllAreasReported,
      // No holder was materialized at admission. This says nothing about
      // unmaterialized or on-disk Local Storage areas.
      kNoMaterializedAreas,
      // The database connection had not finished at admission.
      kConnectionNotReady,
    };

    // This describes the selected backing store at admission. kOnDisk is not
    // a durability signal.
    enum class BackingStore {
      kOnDisk,
      kInMemory,
      kUnavailable,
    };

    struct AreaResult {
      blink::StorageKey storage_key;
      StorageAreaImpl::ImmediateCommitSnapshotResult result;
    };

    ScopeOutcome scope_outcome;
    BackingStore backing_store;
    std::vector<AreaResult> area_results;
  };

  using ImmediateCommitSnapshotCallback =
      base::OnceCallback<void(ImmediateCommitSnapshotResult)>;

  // Constructs a Local Storage implementation which will create its root
  // "Local Storage" directory in `storage_partition_directory` if non-empty.If
  // valid, |receiver| will be bound to this object to allow for remote control
  // via the LocalStorageControl interface.
  LocalStorageImpl(const base::FilePath& storage_partition_directory,
                   DestructLocalStorageCallback destruct_callback,
                   mojo::PendingReceiver<mojom::LocalStorageControl> receiver);
  ~LocalStorageImpl() override;

  void FlushStorageKeyForTesting(const blink::StorageKey& storage_key);
  void PutValueForTesting(const blink::StorageKey& storage_key,
                          const std::vector<uint8_t>& key,
                          const std::vector<uint8_t>& value,
                          base::OnceCallback<void(bool)> callback);

  // Requests a terminal report for the currently materialized storage-area
  // holders. Each child result preserves StorageAreaImpl's admitted UpdateMaps
  // outcome verbatim. This is not a mutation boundary: later writes may join a
  // captured area operation, and later-created or unmaterialized areas are not
  // included.
  //
  // This request does not initiate a database connection. It reports
  // kConnectionNotReady before a connection finishes. A finished failed
  // connection instead reports captured holders with kUnavailable backing and
  // their individual terminal results. This does not invoke Flush() and never
  // observes CloneMap, metadata writes, deletion/cleanup, database close,
  // filesystem flush, shutdown, recovery, profile quiescence, or OPFS lease
  // state. The callback is posted asynchronously while its captured task
  // runner remains runnable.
  void RequestImmediateCommitSnapshot(ImmediateCommitSnapshotCallback callback);

  // Used by content settings to alter the behavior around
  // what data to keep and what data to discard at shutdown.
  // The policy is not so straight forward to describe, see
  // the implementation for details.
  void SetForceKeepSessionState() { force_keep_session_state_ = true; }

  // Clears unused storage areas, when thresholds are reached.
  void PurgeUnusedAreasIfNeeded();

  // mojom::LocalStorageControl implementation:
  void BindStorageArea(
      const blink::StorageKey& storage_key,
      mojo::PendingReceiver<blink::mojom::StorageArea> receiver) override;
  void GetUsage(GetUsageCallback callback) override;
  void DeleteStorage(const blink::StorageKey& storage_key,
                     DeleteStorageCallback callback) override;
  void CleanUpStorage(CleanUpStorageCallback callback) override;
  void Flush() override;
  void PurgeMemory() override;
  void ApplyPolicyUpdates(
      std::vector<mojom::StoragePolicyUpdatePtr> policy_updates) override;
  void ForceKeepSessionState() override;

  // base::trace_event::MemoryDumpProvider implementation.
  bool OnMemoryDump(const base::trace_event::MemoryDumpArgs& args,
                    base::trace_event::ProcessMemoryDump* pmd) override;

  const base::FilePath& GetStoragePartitionDirectory() const;

  // Access the underlying AsyncDomStorageDatabase. May be null if the database
  // is not yet open.
  AsyncDomStorageDatabase* GetDatabaseForTesting() { return database_.get(); }

#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  // Returns whether |storage_key| is the only materialized StorageArea and it
  // still has a live Mojo binding. This is only an admission check for the M7
  // close-fence snapshot; it is not a close or durability result.
  bool HasExactlyOneBoundStorageAreaForTesting(
      const blink::StorageKey& storage_key) const;

  // Returns whether any currently materialized StorageArea still has a live
  // Mojo binding. This is intentionally a narrow test inspection: callers
  // must not treat an unbound holder as a database-close or durability result.
  bool HasBoundStorageAreasForTesting() const;

  // Runs |callback| after this exact LocalStorageImpl has observed that none
  // of its materialized StorageAreas has a live Mojo binding. The notification
  // is backed by a latch maintained from StorageAreaHolder::OnNoBindings(), so
  // it also covers a cross-pipe area disconnect that arrived before this
  // request. It is not a database-close or durability signal.
  void RunWhenNoStorageAreasBoundForTesting(base::OnceClosure callback);
#endif

  // Wait for the database to be opened, or for opening to fail. If the database
  // is already opened, |callback| is invoked immediately.
  void SetDatabaseOpenCallbackForTesting(base::OnceClosure callback);

  void OverrideDeleteStaleStorageAreasDelayForTesting(
      const base::TimeDelta& delay);

  void ForceFakeOpenStorageAreaForTesting(const blink::StorageKey& storage_key);

 private:
  friend class DOMStorageBrowserTest;

  class StorageAreaHolder;
  class CommitSnapshotState;

  // Constructs an absolute path to the database using
  // `storage_partition_directory_`.
  base::FilePath GetDatabasePath() const;

  // Does dtor work. This is a distinct function mainly to retain git history.
  void ShutDown();

  // Runs |callback| immediately if already connected to a database, otherwise
  // delays running |callback| untill after a connection has been established.
  // Initiates connecting to the database if no connection is in progress yet.
  void RunWhenConnected(base::OnceClosure callback);

  // StorageAreas held by this LocalStorageImpl retain an unmanaged reference to
  // `database_`. This deletes them and is used any time `database_` is reset.
  void PurgeAllStorageAreas();

  // Part of asynchronous database opening called from `RunWhenConnected()`. If
  // opening the database on disk fails twice, falls back to in memory. If
  // opening the database in memory fails, runs without a database.
  void InitiateConnection(bool in_memory_only = false);
  void OnDatabaseOpened(DbStatus status);
  void OnConnectionFinished();
  void DeleteAndRecreateDatabase(DomStorageRecoveryReason reason);
  void OnDBDestroyed(bool recreate_in_memory, DbStatus status);

  StorageAreaHolder* GetOrCreateStorageArea(
      const blink::StorageKey& storage_key);

  // The (possibly delayed) implementation of GetUsage(). Can be called directly
  // from that function, or through |on_database_open_callbacks_|.
  void RetrieveStorageUsage(GetUsageCallback callback);
  void OnGotWriteMetaData(GetUsageCallback callback,
                          StatusOr<DomStorageDatabase::Metadata> all_metadata);

  void GetStatistics(size_t* total_cache_size, size_t* unused_area_count);
  void OnCommitResult(DbStatus status);

  // These clear stale storage areas (not read/written to within 400 days) from
  // the database. See crbug.com/40281870 for more info.
  void DeleteStaleStorageAreas();
  void OnGotMetaDataToDeleteStaleStorageAreas(
      StatusOr<DomStorageDatabase::Metadata> all_metadata);
  void OnReceiverDisconnected();

#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  // Test-only bookkeeping called by the exact StorageAreaHolder that changed
  // binding state. The no-binding latch makes the Arm receipt independent of
  // delivery ordering between the StorageArea and test-API Mojo pipes.
  void OnStorageAreaBoundForTesting();
  void OnStorageAreaNoBindingsForTesting();
#endif

  // Passed in by the StorageServiceImpl that owns this object. Used to signal
  // that this LocalStorageImpl can be destructed when the Receiver is
  // disconnected.
  DestructLocalStorageCallback destruct_callback_;

  // The profile data directory, which is an ancestor of the database path.
  // Empty for in-memory databases. When not empty, the owner of
  // `LocalStorageImpl` uses this path as an ID for the `LocalStorageImpl`
  // instance.
  const base::FilePath storage_partition_directory_;

  enum ConnectionState {
    NO_CONNECTION,
    CONNECTION_IN_PROGRESS,
    CONNECTION_FINISHED
  } connection_state_ = NO_CONNECTION;

  bool force_keep_session_state_ = false;

  base::trace_event::MemoryAllocatorDumpGuid memory_dump_id_;

  // `database_` is null after failing to open repeatedly.
  std::unique_ptr<AsyncDomStorageDatabase> database_;
  bool tried_to_recreate_during_open_ = false;
  bool in_memory_ = false;

  std::vector<base::OnceClosure> on_database_opened_callbacks_;

  // Counts consecutive commit errors. If this number reaches a threshold, the
  // whole database is thrown away.
  int commit_error_count_ = 0;
  bool tried_to_recover_from_commit_errors_ = false;

  // Tracks the state of the current recovery cycle, including what triggered
  // it and the outcome of each Destroy() attempt. Populated in
  // DeleteAndRecreateDatabase() and consumed in OnConnectionFinished().
  std::optional<DomStorageRecoveryState> recovery_state_;

  // The set of Origins which should be cleared on shutdown.
  // this is used by ApplyPolicyUpdates to store which origin
  // to clear based on the provided StoragePolicyUpdate.
  std::set<url::Origin> origins_to_purge_on_shutdown_;

  mojo::Receiver<mojom::LocalStorageControl> control_receiver_{this};

  // We need to delay deleting stale storage areas until after any session
  // restore has taken place, otherwise we might fail to record current usage.
  // See crbug.com/40281870 for more info.
  base::TimeDelta delete_stale_storage_areas_delay_{base::Minutes(1)};

#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  // A persistent latch is necessary because the StorageArea disconnect and
  // ArmCommitCloseFence request use different Mojo pipes. It is cleared by
  // every new area binding and set only after the last holder reports
  // OnNoBindings().
  bool no_storage_area_bindings_latched_for_testing_ = false;
  std::vector<base::OnceClosure>
      on_no_storage_area_bindings_callbacks_for_testing_;
#endif

  // Maps between a StorageKey and its view of the map's key/value pairs in the
  // database.  Declared near the bottom of this class so it destructs
  // before its dependencies accessed by `StorageAreaHolder::context_` in
  // `~StorageAreaHolder()`.
  std::map<blink::StorageKey, std::unique_ptr<StorageAreaHolder>> areas_;

  base::WeakPtrFactory<LocalStorageImpl> weak_ptr_factory_{this};
};

}  // namespace storage

#endif  // COMPONENTS_SERVICES_STORAGE_DOM_STORAGE_LOCAL_STORAGE_IMPL_H_
