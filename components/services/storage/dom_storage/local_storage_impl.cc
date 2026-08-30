// Copyright 2016 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "components/services/storage/dom_storage/local_storage_impl.h"

#include <inttypes.h>

#include <algorithm>
#include <optional>
#include <set>
#include <string>
#include <string_view>
#include <utility>

#include "base/byte_size.h"
#include "base/files/file_path.h"
#include "base/functional/bind.h"
#include "base/memory/ref_counted.h"
#include "base/memory/raw_ptr.h"
#include "base/metrics/histogram_functions.h"
#include "base/strings/stringprintf.h"
#include "base/system/sys_info.h"
#include "base/task/sequenced_task_runner.h"
#include "base/task/thread_pool.h"
#include "base/trace_event/memory_dump_manager.h"
#include "build/build_config.h"
#include "components/services/storage/dom_storage/async_dom_storage_database.h"
#include "components/services/storage/dom_storage/db_status.h"
#include "components/services/storage/dom_storage/dom_storage_constants.h"
#include "components/services/storage/dom_storage/dom_storage_database.h"
#include "components/services/storage/dom_storage/features.h"
#include "components/services/storage/dom_storage/leveldb_status_helper.h"
#include "components/services/storage/dom_storage/storage_area_impl.h"
#include "storage/common/database/database_identifier.h"
#include "third_party/blink/public/common/storage_key/storage_key.h"

namespace storage {
namespace {

// Limits on the cache size and number of areas in memory, over which the areas
// are purged.
#if BUILDFLAG(IS_ANDROID)
const unsigned kMaxLocalStorageAreaCount = 10;
const size_t kMaxLocalStorageCacheSize = 2 * 1024 * 1024;
#else
const unsigned kMaxLocalStorageAreaCount = 50;
const size_t kMaxLocalStorageCacheSize = 20 * 1024 * 1024;
#endif

void IgnoreStatus(base::OnceClosure callback, DbStatus status) {
  std::move(callback).Run();
}

StorageAreaImpl::Options createOptions() {
  // Delay for a moment after a value is set in anticipation
  // of other values being set, so changes are batched.
  static constexpr base::TimeDelta kCommitDefaultDelaySecs = base::Seconds(5);

  // To avoid excessive IO we apply limits to the amount of data being written
  // and the frequency of writes.
  static const size_t kMaxBytesPerHour = kPerStorageAreaQuota;
  static constexpr int kMaxCommitsPerHour = 60;

  StorageAreaImpl::Options options;
  options.max_size = kPerStorageAreaQuota + kPerStorageAreaOverQuotaAllowance;
  options.default_commit_delay = kCommitDefaultDelaySecs;
  options.max_bytes_per_hour = kMaxBytesPerHour;
  options.max_commits_per_hour = kMaxCommitsPerHour;
#if BUILDFLAG(IS_ANDROID)
    options.cache_mode = StorageAreaImpl::CacheMode::KEYS_ONLY_WHEN_POSSIBLE;
#else
    options.cache_mode = StorageAreaImpl::CacheMode::KEYS_AND_VALUES;
    if (base::SysInfo::IsLowEndDevice()) {
      options.cache_mode = StorageAreaImpl::CacheMode::KEYS_ONLY_WHEN_POSSIBLE;
    }
#endif
    return options;
}
}  // namespace

// Owns the aggregate callback independently from LocalStorageImpl. Each
// StorageAreaImpl owns the child completion until it has a terminal result, so
// LocalStorageImpl recovery or destruction must not make this callback vanish.
class LocalStorageImpl::CommitSnapshotState
    : public base::RefCounted<CommitSnapshotState> {
 public:
  explicit CommitSnapshotState(ImmediateCommitSnapshotCallback callback)
      : callback_(std::move(callback)),
        callback_task_runner_(base::SequencedTaskRunner::GetCurrentDefault()) {
  }

  CommitSnapshotState(const CommitSnapshotState&) = delete;
  CommitSnapshotState& operator=(const CommitSnapshotState&) = delete;

  void ResolveConnectionNotReady() {
    Resolve({ImmediateCommitSnapshotResult::ScopeOutcome::kConnectionNotReady,
             ImmediateCommitSnapshotResult::BackingStore::kUnavailable, {}});
  }

  void ResolveNoMaterializedAreas(
      ImmediateCommitSnapshotResult::BackingStore backing) {
    Resolve({
        ImmediateCommitSnapshotResult::ScopeOutcome::kNoMaterializedAreas,
        backing,
        {},
    });
  }

  void Initialize(std::vector<blink::StorageKey> storage_keys,
                  ImmediateCommitSnapshotResult::BackingStore backing) {
    DCHECK(!initialized_);
    DCHECK(!storage_keys.empty());
    initialized_ = true;
    backing_store_ = backing;
    storage_keys_ = std::move(storage_keys);
    area_results_.resize(storage_keys_.size());
    remaining_results_ = storage_keys_.size();
  }

  size_t size() const {
    DCHECK(initialized_);
    return storage_keys_.size();
  }

  const blink::StorageKey& storage_key(size_t index) const {
    DCHECK(initialized_);
    DCHECK_LT(index, storage_keys_.size());
    return storage_keys_[index];
  }

  void OnAreaResult(
      size_t index,
      StorageAreaImpl::ImmediateCommitSnapshotResult result) {
    DCHECK(initialized_);
    DCHECK_LT(index, area_results_.size());
    if (resolved_ || area_results_[index].has_value()) {
      return;
    }

    area_results_[index] = std::move(result);
    DCHECK_GT(remaining_results_, 0u);
    --remaining_results_;
    if (remaining_results_ != 0) {
      return;
    }

    std::vector<ImmediateCommitSnapshotResult::AreaResult> results;
    results.reserve(storage_keys_.size());
    for (size_t result_index = 0; result_index < storage_keys_.size();
         ++result_index) {
      DCHECK(area_results_[result_index].has_value());
      results.push_back(
          {std::move(storage_keys_[result_index]),
           std::move(*area_results_[result_index])});
    }
    Resolve({ImmediateCommitSnapshotResult::ScopeOutcome::kAllAreasReported,
             backing_store_, std::move(results)});
  }

 private:
  friend class base::RefCounted<CommitSnapshotState>;
  ~CommitSnapshotState() = default;

  void Resolve(ImmediateCommitSnapshotResult result) {
    if (resolved_) {
      return;
    }
    resolved_ = true;

    ImmediateCommitSnapshotCallback callback = std::move(callback_);
    if (!callback) {
      return;
    }
    callback_task_runner_->PostTask(FROM_HERE,
                                    base::BindOnce(std::move(callback),
                                                   std::move(result)));
  }

  ImmediateCommitSnapshotCallback callback_;
  const scoped_refptr<base::SequencedTaskRunner> callback_task_runner_;
  bool initialized_ = false;
  bool resolved_ = false;
  ImmediateCommitSnapshotResult::BackingStore backing_store_ =
      ImmediateCommitSnapshotResult::BackingStore::kUnavailable;
  std::vector<blink::StorageKey> storage_keys_;
  std::vector<
      std::optional<StorageAreaImpl::ImmediateCommitSnapshotResult>>
      area_results_;
  size_t remaining_results_ = 0;
};

class LocalStorageImpl::StorageAreaHolder final
    : public StorageAreaImpl::Delegate {
 public:
  StorageAreaHolder(LocalStorageImpl* context,
                    const blink::StorageKey& storage_key)
      : context_(context),
        storage_key_(storage_key),
        area_(context_->database_.get(),
              base::MakeRefCounted<DomStorageDatabase::SharedMapLocator>(
                  DomStorageDatabase::MapLocator(storage_key_)),
              this,
              createOptions()) {}

  ~StorageAreaHolder() override {
    // If we already wrote last_accessed we can skip writing it again.
    if (has_written_access_meta_data_) {
      return;
    }
    // We should not write last_accessed if the area is empty.
    if (storage_area()->empty()) {
      return;
    }

    if (!context_->database_) {
      // The database does not exist.
      return;
    }

    // We should not write last_accessed if the data will be purged.
    if (context_->origins_to_purge_on_shutdown_.find(storage_key_.origin()) !=
            context_->origins_to_purge_on_shutdown_.end() ||
        context_->origins_to_purge_on_shutdown_.find(
            url::Origin::Create(storage_key_.top_level_site().GetURL())) !=
            context_->origins_to_purge_on_shutdown_.end()) {
      return;
    }

    // Update the storage area map's last access time in the database.
    DomStorageDatabase::Metadata usage;
    usage.map_metadata.push_back({
        .map_locator{storage_key_},
        .last_accessed{base::Time::Now()},
    });
    context_->database_->PutMetadata(
        std::move(usage), base::BindOnce([](DbStatus status) {
          base::UmaHistogramBoolean(
              "LocalStorage.AccessMetaDataUpdateAtShutdown", status.ok());
        }));
  }

  StorageAreaImpl* storage_area() { return &area_; }

  void OnNoBindings() override {
    has_bindings_ = false;
    // Don't delete ourselves, but do schedule an immediate commit. Possible
    // deletion will happen under memory pressure or when another localstorage
    // area is opened.
    storage_area()->ScheduleImmediateCommit();
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST)
    // This is the authoritative binding transition for the M7 close-fence
    // test. It intentionally follows ScheduleImmediateCommit(): the test's
    // earlier snapshot was admitted while this holder was bound, and Arm only
    // observes that the cross-pipe receiver has now gone away.
    context_->OnStorageAreaNoBindingsForTesting();
#endif
  }

  std::optional<DomStorageDatabase::MapBatchUpdate::Usage>
  GetMapUsageMetadataToCommit() override {
    DomStorageDatabase::MapBatchUpdate::Usage map_usage;

    if (storage_area()->empty()) {
      // Delete this empty map's usage metadata from the database.
      map_usage.DeleteAllUsage();
      return map_usage;
    }

    // Update the last modified time and total size in the database.
    base::Time now = base::Time::Now();
    map_usage.SetLastModifiedAndTotalSize(
        now, base::ByteSize(storage_area()->storage_used()));

    if (!has_written_access_meta_data_) {
      // Update the last accessed time in the database.
      map_usage.SetLastAccessed(now);
      has_written_access_meta_data_ = true;
    }
    return map_usage;
  }

  void DidCommit(DbStatus status) override { context_->OnCommitResult(status); }
  void Bind(mojo::PendingReceiver<blink::mojom::StorageArea> receiver) {
    has_bindings_ = true;
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST)
    context_->OnStorageAreaBoundForTesting();
#endif
    storage_area()->Bind(std::move(receiver));
  }

  bool has_bindings() const { return has_bindings_; }

 private:
  raw_ptr<LocalStorageImpl> context_;
  blink::StorageKey storage_key_;
  bool has_bindings_ = false;
  bool has_written_access_meta_data_ = false;
  StorageAreaImpl area_;
};

LocalStorageImpl::LocalStorageImpl(
    const base::FilePath& storage_partition_directory,
    DestructLocalStorageCallback destruct_callback,
    mojo::PendingReceiver<mojom::LocalStorageControl> receiver)
    : destruct_callback_(std::move(destruct_callback)),
      storage_partition_directory_(storage_partition_directory),
      memory_dump_id_(base::StringPrintf("LocalStorage/0x%" PRIXPTR,
                                         reinterpret_cast<uintptr_t>(this))) {
  base::trace_event::MemoryDumpManager::GetInstance()
      ->RegisterDumpProviderWithSequencedTaskRunner(
          this, "LocalStorage", base::SequencedTaskRunner::GetCurrentDefault(),
          MemoryDumpProvider::Options());

  if (receiver) {
    control_receiver_.Bind(std::move(receiver));
    control_receiver_.set_disconnect_handler(
        base::BindOnce(&LocalStorageImpl::OnReceiverDisconnected,
                       weak_ptr_factory_.GetWeakPtr()));
  }
}

void LocalStorageImpl::BindStorageArea(
    const blink::StorageKey& storage_key,
    mojo::PendingReceiver<blink::mojom::StorageArea> receiver) {
  if (connection_state_ != CONNECTION_FINISHED) {
    RunWhenConnected(base::BindOnce(&LocalStorageImpl::BindStorageArea,
                                    weak_ptr_factory_.GetWeakPtr(), storage_key,
                                    std::move(receiver)));
    return;
  }

  GetOrCreateStorageArea(storage_key)->Bind(std::move(receiver));
}

void LocalStorageImpl::GetUsage(GetUsageCallback callback) {
  RunWhenConnected(base::BindOnce(&LocalStorageImpl::RetrieveStorageUsage,
                                  weak_ptr_factory_.GetWeakPtr(),
                                  std::move(callback)));
}

void LocalStorageImpl::DeleteStorage(const blink::StorageKey& storage_key,
                                     DeleteStorageCallback callback) {
  if (connection_state_ != CONNECTION_FINISHED) {
    RunWhenConnected(base::BindOnce(&LocalStorageImpl::DeleteStorage,
                                    weak_ptr_factory_.GetWeakPtr(), storage_key,
                                    std::move(callback)));
    return;
  }

  auto found = areas_.find(storage_key);
  if (found != areas_.end()) {
    // We don't bother passing an observer because this is a one-shot event and
    // we only care about observing its completion, for which the reply alone is
    // sufficient.
    found->second->storage_area()->DeleteAll(
        /*source=*/nullptr,
        /*new_observer=*/mojo::NullRemote(), std::move(callback));
    found->second->storage_area()->ScheduleImmediateCommit();
  } else if (database_) {
    std::vector<DomStorageDatabase::MapLocator> maps_to_delete;
    maps_to_delete.emplace_back(storage_key);

    database_->DeleteStorageKeysFromSession(
        /*session_id=*/std::string(), /*metadata_to_delete=*/{storage_key},
        std::move(maps_to_delete),
        base::BindOnce([](base::OnceClosure callback,
                          DbStatus) { std::move(callback).Run(); },
                       std::move(callback)));
  } else {
    std::move(callback).Run();
  }
}

void LocalStorageImpl::CleanUpStorage(CleanUpStorageCallback callback) {
  if (connection_state_ != CONNECTION_FINISHED) {
    RunWhenConnected(base::BindOnce(&LocalStorageImpl::CleanUpStorage,
                                    weak_ptr_factory_.GetWeakPtr(),
                                    std::move(callback)));
    return;
  }

  if (database_) {
    // Try to commit all changes before cleaning up the database. If
    // an area is not ready to commit its changes, nothing breaks but the
    // clean up doesn't remove all traces of old data.
    Flush();
    database_->CleanUpStaleData(
        base::BindOnce(&IgnoreStatus, std::move(callback)));
  } else {
    std::move(callback).Run();
  }
}

void LocalStorageImpl::Flush() {
  if (connection_state_ != CONNECTION_FINISHED) {
    RunWhenConnected(base::BindOnce(&LocalStorageImpl::Flush,
                                    weak_ptr_factory_.GetWeakPtr()));
    return;
  }

  for (const auto& it : areas_)
    it.second->storage_area()->ScheduleImmediateCommit();
}

void LocalStorageImpl::FlushStorageKeyForTesting(
    const blink::StorageKey& storage_key) {
  if (connection_state_ != CONNECTION_FINISHED)
    return;
  const auto& it = areas_.find(storage_key);
  if (it == areas_.end())
    return;
  it->second->storage_area()->ScheduleImmediateCommit();
}

void LocalStorageImpl::PutValueForTesting(
    const blink::StorageKey& storage_key,
    const std::vector<uint8_t>& key,
    const std::vector<uint8_t>& value,
    base::OnceCallback<void(bool)> callback) {
  if (connection_state_ != CONNECTION_FINISHED) {
    return;
  }

  const auto& it = areas_.find(storage_key);
  if (it == areas_.end()) {
    return;
  }

  it->second->storage_area()->Put(key, value, /*client_old_value=*/std::nullopt,
                                  /*source=*/nullptr, std::move(callback));
}

void LocalStorageImpl::RequestImmediateCommitSnapshot(
    ImmediateCommitSnapshotCallback callback) {
  auto snapshot =
      base::MakeRefCounted<CommitSnapshotState>(std::move(callback));
  if (connection_state_ != CONNECTION_FINISHED) {
    // Do not call RunWhenConnected(): queued callbacks are weak-bound to this
    // object and can otherwise disappear during connection failure or teardown.
    snapshot->ResolveConnectionNotReady();
    return;
  }

  const ImmediateCommitSnapshotResult::BackingStore backing_store =
      !database_ ? ImmediateCommitSnapshotResult::BackingStore::kUnavailable
      : in_memory_ ? ImmediateCommitSnapshotResult::BackingStore::kInMemory
                   : ImmediateCommitSnapshotResult::BackingStore::kOnDisk;

  std::vector<blink::StorageKey> storage_keys;
  storage_keys.reserve(areas_.size());
  for (const auto& area : areas_) {
    storage_keys.push_back(area.first);
  }
  if (storage_keys.empty()) {
    snapshot->ResolveNoMaterializedAreas(backing_store);
    return;
  }

  // Initialize every result slot before asking an area to start work. The
  // state has no LocalStorageImpl or holder reference, so it survives recovery
  // and destruction until every captured area has a terminal result.
  snapshot->Initialize(std::move(storage_keys), backing_store);
  for (size_t index = 0; index < snapshot->size(); ++index) {
    auto area_it = areas_.find(snapshot->storage_key(index));
    if (area_it == areas_.end()) {
      snapshot->OnAreaResult(
          index,
          {StorageAreaImpl::ImmediateCommitSnapshotResult::Outcome::kCancelled,
           DbStatus::IOError("Storage area was removed before snapshot "
                             "admission.")});
      continue;
    }
    area_it->second->storage_area()->RequestImmediateCommitSnapshot(
        base::BindOnce(&CommitSnapshotState::OnAreaResult, snapshot, index));
  }
}

base::FilePath LocalStorageImpl::GetDatabasePath() const {
  return DomStorageDatabase::GetPath(StorageType::kLocalStorage,
                                     storage_partition_directory_);
}

void LocalStorageImpl::ShutDown() {
  control_receiver_.reset();

  // Nothing to do if no connection to the database was ever finished.
  if (connection_state_ == CONNECTION_FINISHED) {
    // Flush any uncommitted data.
    for (const auto& it : areas_) {
      auto* area = it.second->storage_area();
      base::UmaHistogramBoolean("Storage.LocalStorage.ShutdownDroppedChanges",
                                area->has_pending_load_read_write_tasks());
      area->ScheduleImmediateCommit();
      // TODO(crbug.com/503422295): Monitor the above histogram, and if dropping
      // changes is common then handle that here.
      area->CancelAllPendingRequests();
    }

    if (database_ && !force_keep_session_state_ &&
        !origins_to_purge_on_shutdown_.empty()) {
      database_->PurgeOriginsForShutdown(
          std::move(origins_to_purge_on_shutdown_));
    }
  }
}

void LocalStorageImpl::PurgeMemory() {
  for (auto it = areas_.begin(); it != areas_.end();) {
    if (it->second->has_bindings()) {
      it->second->storage_area()->PurgeMemory();
      ++it;
    } else {
      it = areas_.erase(it);
    }
  }
}

void LocalStorageImpl::ApplyPolicyUpdates(
    std::vector<mojom::StoragePolicyUpdatePtr> policy_updates) {
  for (const auto& update : policy_updates) {
    const url::Origin origin = update->origin;
    if (!update->purge_on_shutdown)
      origins_to_purge_on_shutdown_.erase(origin);
    else
      origins_to_purge_on_shutdown_.insert(std::move(origin));
  }
}

void LocalStorageImpl::PurgeUnusedAreasIfNeeded() {
  size_t total_cache_size, unused_area_count;
  GetStatistics(&total_cache_size, &unused_area_count);

  // Nothing to purge.
  if (!unused_area_count)
    return;

  // No purge is needed.
  if (total_cache_size <= kMaxLocalStorageCacheSize &&
      areas_.size() <= kMaxLocalStorageAreaCount &&
      !base::SysInfo::IsLowEndDevice()) {
    return;
  }

  for (auto it = areas_.begin(); it != areas_.end();) {
    if (it->second->has_bindings())
      ++it;
    else
      it = areas_.erase(it);
  }
}

void LocalStorageImpl::ForceKeepSessionState() {
  SetForceKeepSessionState();
}

bool LocalStorageImpl::OnMemoryDump(
    const base::trace_event::MemoryDumpArgs& args,
    base::trace_event::ProcessMemoryDump* pmd) {
  if (connection_state_ != CONNECTION_FINISHED)
    return true;

  std::string context_name =
      base::StringPrintf("site_storage/localstorage/0x%" PRIXPTR,
                         reinterpret_cast<uintptr_t>(this));

  // Account for database memory usage, which actually lives in the file
  // service.
  auto* global_dump = pmd->CreateSharedGlobalAllocatorDump(memory_dump_id_);
  // The size of the database dump will be added by the database service.
  auto* db_mad = pmd->CreateAllocatorDump(
      context_name +
      (ShouldUseSqliteBackend(in_memory_) ? "/sqlite" : "/leveldb"));
  // Specifies that the current context is responsible for keeping memory alive.
  int kImportance = 2;
  pmd->AddOwnershipEdge(db_mad->guid(), global_dump->guid(), kImportance);

  if (args.level_of_detail ==
      base::trace_event::MemoryDumpLevelOfDetail::kBackground) {
    size_t total_cache_size, unused_area_count;
    GetStatistics(&total_cache_size, &unused_area_count);
    auto* mad = pmd->CreateAllocatorDump(context_name + "/cache_size");
    mad->AddScalar(base::trace_event::MemoryAllocatorDump::kNameSize,
                   base::trace_event::MemoryAllocatorDump::kUnitsBytes,
                   total_cache_size);
    mad->AddScalar("total_areas",
                   base::trace_event::MemoryAllocatorDump::kUnitsObjects,
                   areas_.size());
    return true;
  }
  for (const auto& it : areas_) {
    std::string storage_key_str =
        it.first.GetMemoryDumpString(/*max_length=*/50);
    std::string area_dump_name = base::StringPrintf(
        "%s/%s/0x%" PRIXPTR, context_name.c_str(), storage_key_str.c_str(),
        reinterpret_cast<uintptr_t>(it.second->storage_area()));
    it.second->storage_area()->OnMemoryDump(area_dump_name, pmd);
  }
  return true;
}

const base::FilePath& LocalStorageImpl::GetStoragePartitionDirectory() const {
  return storage_partition_directory_;
}

#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST)
bool LocalStorageImpl::HasExactlyOneBoundStorageAreaForTesting(
    const blink::StorageKey& storage_key) const {
  if (areas_.size() != 1u) {
    return false;
  }

  const auto area = areas_.find(storage_key);
  return area != areas_.end() && area->second->has_bindings();
}

bool LocalStorageImpl::HasBoundStorageAreasForTesting() const {
  for (const auto& area : areas_) {
    if (area.second->has_bindings()) {
      return true;
    }
  }
  return false;
}

void LocalStorageImpl::RunWhenNoStorageAreasBoundForTesting(
    base::OnceClosure callback) {
  DCHECK(callback);

  // The latch is set by StorageAreaHolder::OnNoBindings(), rather than by a
  // one-shot inspection here. That preserves the event when the area receiver
  // closes before an independently ordered test-API Arm request arrives.
  if (no_storage_area_bindings_latched_for_testing_) {
    std::move(callback).Run();
    return;
  }
  on_no_storage_area_bindings_callbacks_for_testing_.push_back(
      std::move(callback));
}

void LocalStorageImpl::OnStorageAreaBoundForTesting() {
  // A later Arm receipt must wait for a fresh last-unbind transition. This
  // prevents a stale latch from accepting a StorageArea rebound on another
  // Mojo pipe.
  no_storage_area_bindings_latched_for_testing_ = false;
}

void LocalStorageImpl::OnStorageAreaNoBindingsForTesting() {
  if (HasBoundStorageAreasForTesting()) {
    return;
  }

  no_storage_area_bindings_latched_for_testing_ = true;
  auto callbacks =
      std::move(on_no_storage_area_bindings_callbacks_for_testing_);
  on_no_storage_area_bindings_callbacks_for_testing_.clear();
  for (auto& callback : callbacks) {
    std::move(callback).Run();
  }
}
#endif

void LocalStorageImpl::SetDatabaseOpenCallbackForTesting(
    base::OnceClosure callback) {
  RunWhenConnected(std::move(callback));
}

void LocalStorageImpl::OverrideDeleteStaleStorageAreasDelayForTesting(
    const base::TimeDelta& delay) {
  delete_stale_storage_areas_delay_ = delay;
}

void LocalStorageImpl::ForceFakeOpenStorageAreaForTesting(
    const blink::StorageKey& storage_key) {
  areas_[storage_key] = std::make_unique<StorageAreaHolder>(this, storage_key);
}

LocalStorageImpl::~LocalStorageImpl() {
  ShutDown();
  base::trace_event::MemoryDumpManager::GetInstance()->UnregisterDumpProvider(
      this);
}

void LocalStorageImpl::RunWhenConnected(base::OnceClosure callback) {
  // If we don't have a database connection, we'll need to establish one.
  if (connection_state_ == NO_CONNECTION) {
    connection_state_ = CONNECTION_IN_PROGRESS;
    InitiateConnection();
  }

  if (connection_state_ == CONNECTION_IN_PROGRESS) {
    // Queue this OpenLocalStorage call for when we have a level db pointer.
    on_database_opened_callbacks_.push_back(std::move(callback));
    return;
  }

  std::move(callback).Run();
}

void LocalStorageImpl::PurgeAllStorageAreas() {
  for (const auto& it : areas_)
    it.second->storage_area()->CancelAllPendingRequests();
  areas_.clear();
}

void LocalStorageImpl::InitiateConnection(bool in_memory_only) {
  CHECK_EQ(connection_state_, CONNECTION_IN_PROGRESS);

  if (!storage_partition_directory_.empty() &&
      storage_partition_directory_.IsAbsolute() && !in_memory_only) {
    // We were given a subdirectory to write to, so use a disk-backed database.
    in_memory_ = false;
    database_ = AsyncDomStorageDatabase::Open(
        StorageType::kLocalStorage, GetDatabasePath(), memory_dump_id_,
        base::BindOnce(&LocalStorageImpl::OnDatabaseOpened,
                       weak_ptr_factory_.GetWeakPtr()));
    return;
  }

  // We were not given a subdirectory. Use a memory backed database.
  in_memory_ = true;
  database_ = AsyncDomStorageDatabase::Open(
      StorageType::kLocalStorage,
      /*database_path=*/base::FilePath(), memory_dump_id_,
      base::BindOnce(&LocalStorageImpl::OnDatabaseOpened,
                     weak_ptr_factory_.GetWeakPtr()));
}

void LocalStorageImpl::OnDatabaseOpened(DbStatus status) {
  if (!status.ok()) {
    // If we failed to open the database, try to delete and recreate the
    // database, or ultimately fallback to an in-memory database.
    DeleteAndRecreateDatabase(DomStorageRecoveryReason::kOpenFailure);
    return;
  }

  OnConnectionFinished();
}

void LocalStorageImpl::OnConnectionFinished() {
  CHECK_EQ(connection_state_, CONNECTION_IN_PROGRESS);
  // If connection was opened successfully, reset tried_to_recreate_during_open_
  // to enable recreating the database on future errors.
  if (database_)
    tried_to_recreate_during_open_ = false;

  // Emit recovery histogram if we just completed a recovery cycle.
  if (recovery_state_) {
    LogDomStorageRecoveryOutcome("LocalStorage", *recovery_state_,
                                 /*has_database=*/database_ != nullptr,
                                 in_memory_);
    recovery_state_.reset();
  }

  // Clear stale storage areas after a delay to prevent blocking session
  // restoration.
  if (database_ && !in_memory_) {
    base::SequencedTaskRunner::GetCurrentDefault()->PostDelayedTask(
        FROM_HERE,
        base::BindOnce(&LocalStorageImpl::DeleteStaleStorageAreas,
                       weak_ptr_factory_.GetWeakPtr()),
        delete_stale_storage_areas_delay_);
  }

  // |database_| should be known to either be valid or invalid by now. Run our
  // delayed bindings.
  connection_state_ = CONNECTION_FINISHED;
  for (size_t i = 0; i < on_database_opened_callbacks_.size(); ++i)
    std::move(on_database_opened_callbacks_[i]).Run();
  on_database_opened_callbacks_.clear();
}

void LocalStorageImpl::DeleteAndRecreateDatabase(
    DomStorageRecoveryReason reason) {
  // Record the reason that initiated this recovery cycle. The first reason
  // wins: subsequent calls during the same recovery cycle (e.g. an open
  // failure after a destroy triggered by kCommitErrorThresholdExceeded) do not
  // overwrite it. So, the histogram correctly attributes the outcome to the
  // original reason.
  if (!recovery_state_) {
    recovery_state_.emplace(reason, in_memory_);
  }

  // We're about to set database_ to null, so delete the StorageAreaImpls
  // that might still be using the old database.
  PurgeAllStorageAreas();

  // Reset state to be in process of connecting. This will cause requests for
  // StorageAreas to be queued until the connection is complete.
  connection_state_ = CONNECTION_IN_PROGRESS;
  RecordCommitErrorCountAtReset("LocalStorage", commit_error_count_);
  commit_error_count_ = 0;
  database_.reset();

  bool recreate_in_memory = false;

  // If tried to recreate database on disk already, try again but this time
  // in memory.
  if (tried_to_recreate_during_open_) {
    if (in_memory_) {
      // Give up completely, run without any database.
      OnConnectionFinished();
      return;
    }
    recreate_in_memory = true;
  }

  tried_to_recreate_during_open_ = true;

  // Destroy database, and try again.
  if (!in_memory_) {
    DomStorageDatabaseFactory::Destroy(
        GetDatabasePath(),
        base::BindOnce(&LocalStorageImpl::OnDBDestroyed,
                       weak_ptr_factory_.GetWeakPtr(), recreate_in_memory));
  } else {
    // No directory, so nothing to destroy. Retrying to recreate will probably
    // fail, but try anyway.
    InitiateConnection(recreate_in_memory);
  }
}

void LocalStorageImpl::OnDBDestroyed(bool recreate_in_memory, DbStatus status) {
  // Destroy is only called when the database is on disk (see !in_memory_ guard
  // in DeleteAndRecreateDatabase), so in_memory is always false here.
  status.Log("Storage.LocalStorage.DestroyDatabase", /*in_memory=*/false);
  recovery_state_.value().AddDestroyResult(status.ok());
  InitiateConnection(recreate_in_memory);
}

LocalStorageImpl::StorageAreaHolder* LocalStorageImpl::GetOrCreateStorageArea(
    const blink::StorageKey& storage_key) {
  CHECK_EQ(connection_state_, CONNECTION_FINISHED);
  auto found = areas_.find(storage_key);
  if (found != areas_.end()) {
    return found->second.get();
  }

  PurgeUnusedAreasIfNeeded();

  auto holder = std::make_unique<StorageAreaHolder>(this, storage_key);
  StorageAreaHolder* holder_ptr = holder.get();
  areas_[storage_key] = std::move(holder);
  return holder_ptr;
}

void LocalStorageImpl::RetrieveStorageUsage(GetUsageCallback callback) {
  CHECK_EQ(connection_state_, ConnectionState::CONNECTION_FINISHED);

  if (!database_) {
    // If for whatever reason no database is available, no storage is
    // used, so return an array only containing the current areas.
    std::vector<mojom::StorageUsageInfoPtr> result;
    base::Time now = base::Time::Now();
    for (const auto& it : areas_) {
      result.emplace_back(mojom::StorageUsageInfo::New(it.first, 0, now));
    }
    std::move(callback).Run(std::move(result));
  } else {
    database_->ReadAllMetadata(
        base::BindOnce(&LocalStorageImpl::OnGotWriteMetaData,
                       weak_ptr_factory_.GetWeakPtr(), std::move(callback)));
  }
}

void LocalStorageImpl::OnGotWriteMetaData(
    GetUsageCallback callback,
    StatusOr<DomStorageDatabase::Metadata> all_metadata) {
  std::vector<mojom::StorageUsageInfoPtr> result;
  std::set<blink::StorageKey> storage_keys;

  // Update `result` to include maps that have committed data to disk.
  if (all_metadata.has_value()) {
    for (const DomStorageDatabase::MapMetadata& usage_metadata :
         all_metadata->map_metadata) {
      if (usage_metadata.last_modified && usage_metadata.total_size) {
        const blink::StorageKey& storage_key =
            usage_metadata.map_locator.storage_key();
        storage_keys.insert(storage_key);

        result.emplace_back(mojom::StorageUsageInfo::New(
            storage_key, usage_metadata.total_size->InBytes(),
            *usage_metadata.last_modified));
      }
    }
  }

  // Add any storage keys for which StorageAreas exist, but which haven't
  // committed any data to disk yet.
  base::Time now = base::Time::Now();
  for (const auto& it : areas_) {
    if (storage_keys.find(it.first) != storage_keys.end())
      continue;
    StorageAreaImpl* storage_area = it.second->storage_area();
    // Skip any storage keys that definitely don't have any data.
    if (!storage_area->has_pending_load_tasks() && storage_area->empty()) {
      continue;
    }
    result.emplace_back(mojom::StorageUsageInfo::New(
        it.first, storage_area->storage_used(), now));
  }
  std::move(callback).Run(std::move(result));
}

void LocalStorageImpl::GetStatistics(size_t* total_cache_size,
                                     size_t* unused_area_count) {
  *total_cache_size = 0;
  *unused_area_count = 0;
  for (const auto& it : areas_) {
    *total_cache_size += it.second->storage_area()->memory_used();
    if (!it.second->has_bindings())
      (*unused_area_count)++;
  }
}

void LocalStorageImpl::OnCommitResult(DbStatus status) {
  if (status.ok()) {
    if (commit_error_count_ > 0 && tried_to_recover_from_commit_errors_) {
      base::UmaHistogramEnumeration(
          "Storage.LocalStorage.Recovery.CommitErrorThresholdExceeded",
          DomStorageDatabaseRecoveryOutcome::
              kTransientErrorsAfterAttemptedRecovery);
    }
    RecordCommitErrorCountAtReset("LocalStorage", commit_error_count_);
    commit_error_count_ = 0;
    return;
  }

  if (connection_state_ != CONNECTION_FINISHED) {
    // Previous commit errors deleted and recreated the database below.  Ignore
    // additional errors from the old database while waiting for the new
    // database to open.
    return;
  }

  commit_error_count_++;
  if (commit_error_count_ > kCommitErrorThreshold) {
    if (tried_to_recover_from_commit_errors_) {
      // We already tried to recover from a high commit error rate before, but
      // are still having problems: there isn't really anything left to try, so
      // just ignore errors.
      base::UmaHistogramEnumeration(
          "Storage.LocalStorage.Recovery.CommitErrorThresholdExceeded",
          DomStorageDatabaseRecoveryOutcome::
              kOngoingErrorsAfterAttemptedRecovery);
      return;
    }
    tried_to_recover_from_commit_errors_ = true;

    // Deleting StorageAreas in here could cause more commits (and commit
    // errors), but those commits won't reach OnCommitResult because the area
    // will have been deleted before the commit finishes.
    DeleteAndRecreateDatabase(
        DomStorageRecoveryReason::kCommitErrorThresholdExceeded);
  }
}

void LocalStorageImpl::DeleteStaleStorageAreas() {
  if (!database_ || connection_state_ != CONNECTION_FINISHED) {
    // Due to the delay before LocalStorageImpl::DeleteStaleStorageAreas is invoked
    // it's possible `database_` existed before, but no longer.
    return;
  }
  database_->ReadAllMetadata(
      base::BindOnce(&LocalStorageImpl::OnGotMetaDataToDeleteStaleStorageAreas,
                     weak_ptr_factory_.GetWeakPtr()));
}

void LocalStorageImpl::OnGotMetaDataToDeleteStaleStorageAreas(
    StatusOr<DomStorageDatabase::Metadata> all_metadata) {
  if (!database_ || connection_state_ != CONNECTION_FINISHED) {
    // This method is provided as a callback to an off thread task. Between the
    // time that the task is posted and now when this callback is invoked, the
    // `database_` member may have been reset.
    return;
  }
  if (!all_metadata.has_value()) {
    // ERROR: Failed to read from the database!
    return;
  }
  // Filter and collect stale storage areas for deletion.
  std::vector<blink::StorageKey> stale_storage_keys;
  std::vector<DomStorageDatabase::MapLocator> maps_to_delete;
  uint64_t orphans_found = 0;
  for (const DomStorageDatabase::MapMetadata& usage_metadata :
       all_metadata->map_metadata) {
    const blink::StorageKey& storage_key =
        usage_metadata.map_locator.storage_key();
    if (areas_.find(storage_key) != areas_.end()) {
      // If the storage area is currently loaded it must not be cleared.
      continue;
    }

    // Use the most recent last accessed time or last modified time.
    base::Time accessed_or_modified_time;
    if (usage_metadata.last_accessed && usage_metadata.last_modified) {
      accessed_or_modified_time = std::max(*usage_metadata.last_accessed,
                                           *usage_metadata.last_modified);
    } else if (usage_metadata.last_modified) {
      accessed_or_modified_time = *usage_metadata.last_modified;
    } else {
      accessed_or_modified_time = usage_metadata.last_accessed.value();
    }

    if ((base::Time::Now() - accessed_or_modified_time) >=
        base::Days(kLocalStorageStaleBucketCutoffInDays)) {
      // If the storage area has not been accessed or modified within 400 days
      // it can be cleared.
      stale_storage_keys.push_back(storage_key);
      maps_to_delete.emplace_back(storage_key);
    } else if ((storage_key.nonce().has_value() ||
                storage_key.top_level_site().opaque()) &&
               (base::Time::Now() - accessed_or_modified_time) >=
                   base::Days(1)) {
      // If the storage area has not been accessed or modified in this browsing
      // session and is transient (has a nonce) then it can be cleared.
      stale_storage_keys.push_back(storage_key);
      maps_to_delete.emplace_back(storage_key);
      orphans_found++;
    }
  }
  // These are counted independently to better track errors in rollout.
  base::UmaHistogramCounts100000(
      "LocalStorage.OrphanStorageAreasOnStartupCount", orphans_found);

  // Delete stale storage areas and count results.
  size_t deleted_count = stale_storage_keys.size();
  database_->DeleteStorageKeysFromSession(
      /*session_id=*/std::string(),
      /*metadata_to_delete=*/std::move(stale_storage_keys),
      std::move(maps_to_delete),
      base::BindOnce(
          [](size_t keys_deleted, DbStatus status) {
            base::UmaHistogramBoolean(
                "LocalStorage.StaleStorageAreasDeletedOnStartupSuccess",
                status.ok());
            if (status.ok()) {
              base::UmaHistogramCounts100000(
                  "LocalStorage.StaleStorageAreasDeletedOnStartupCount",
                  keys_deleted);
            }
          },
          deleted_count));
}

void LocalStorageImpl::OnReceiverDisconnected() {
  std::move(destruct_callback_).Run(this);
}

}  // namespace storage
