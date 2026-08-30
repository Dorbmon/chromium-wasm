// Copyright 2019 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "components/services/storage/storage_service_impl.h"

#include "base/functional/bind.h"
#include "base/functional/callback_helpers.h"
#include "base/not_fatal_until.h"
#include "base/task/sequenced_task_runner.h"
#include "base/task/thread_pool.h"
#include "build/build_config.h"
#include "components/services/storage/dom_storage/dom_storage_database.h"
#include "components/services/storage/dom_storage/features.h"
#include "components/services/storage/dom_storage/local_storage_impl.h"
#include "components/services/storage/dom_storage/session_storage_impl.h"
#include "components/services/storage/dom_storage/storage_area_impl.h"
#include "components/services/storage/filesystem_proxy_factory.h"
#include "components/services/storage/public/cpp/filesystem/filesystem_proxy.h"
#include "components/services/storage/sandboxed_vfs_delegate.h"
#include "components/services/storage/test_api_stubs.h"
#include "mojo/public/cpp/bindings/pending_remote.h"
#include "sql/database.h"
#include "sql/sandboxed_vfs.h"
#include "third_party/leveldatabase/env_chromium.h"

namespace storage {

namespace {

// We don't use out-of-process Storage Service on Android, so we can avoid
// pulling all the related code (including Directory mojom) into the build.
#if !BUILDFLAG(IS_ANDROID)
// The name under which we register our own sandboxed VFS instance when running
// out-of-process.
constexpr char kVfsName[] = "storage_service";

using DirectoryBinder =
    base::RepeatingCallback<void(mojo::PendingReceiver<mojom::Directory>)>;
std::unique_ptr<FilesystemProxy> CreateRestrictedFilesystemProxy(
    const base::FilePath& directory_path,
    scoped_refptr<base::SequencedTaskRunner> io_task_runner,
    DirectoryBinder binder,
    scoped_refptr<base::SequencedTaskRunner> binder_task_runner) {
  mojo::PendingRemote<mojom::Directory> directory;
  binder_task_runner->PostTask(
      FROM_HERE,
      base::BindOnce(binder, directory.InitWithNewPipeAndPassReceiver()));
  return std::make_unique<FilesystemProxy>(FilesystemProxy::RESTRICTED,
                                           directory_path, std::move(directory),
                                           std::move(io_task_runner));
}
#endif

SessionStorageImpl::BackingMode GetSessionStorageBackingMode(
    bool has_path,
    bool clear_on_open) {
#if BUILDFLAG(IS_ANDROID)
  // On Android there is no support for session storage restoring, and since
  // the restoring code is responsible for database cleanup, we must
  // manually delete the old database here before we open a new one.
  return SessionStorageImpl::BackingMode::kClearDiskStateOnOpen;
#else
  // In-memory profiles (e.g. incognito) have no path and must always use
  // kNoDisk regardless of clear_on_open.
  if (!has_path) {
    return SessionStorageImpl::BackingMode::kNoDisk;
  }
  return clear_on_open ? SessionStorageImpl::BackingMode::kClearDiskStateOnOpen
                       : SessionStorageImpl::BackingMode::kRestoreDiskState;
#endif
}

#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST)

using WasmLocalStorageTestResult = mojom::WasmLocalStorageTestResult;

template <typename Callback>
void PostWasmLocalStorageTestResult(Callback callback,
                                    WasmLocalStorageTestResult result) {
  // The test API intentionally never replies inline. In particular, an early
  // failure must not turn a cross-pipe close into an accidentally synchronous
  // success observation.
  base::SequencedTaskRunner::GetCurrentDefault()->PostTask(
      FROM_HERE, base::BindOnce(std::move(callback), result));
}

WasmLocalStorageTestResult ClassifyWasmLocalStorageSnapshot(
    const LocalStorageImpl::ImmediateCommitSnapshotResult& snapshot,
    const blink::StorageKey& storage_key) {
  using ScopeOutcome =
      LocalStorageImpl::ImmediateCommitSnapshotResult::ScopeOutcome;
  using BackingStore =
      LocalStorageImpl::ImmediateCommitSnapshotResult::BackingStore;
  using AreaOutcome = StorageAreaImpl::ImmediateCommitSnapshotResult::Outcome;

  if (snapshot.scope_outcome == ScopeOutcome::kConnectionNotReady) {
    return WasmLocalStorageTestResult::kSnapshotConnectionNotReady;
  }
  if (snapshot.scope_outcome != ScopeOutcome::kAllAreasReported) {
    return WasmLocalStorageTestResult::kSnapshotUnexpectedAreaCount;
  }
  if (snapshot.backing_store != BackingStore::kOnDisk) {
    return WasmLocalStorageTestResult::kSnapshotNotOnDisk;
  }
  if (snapshot.area_results.size() != 1u) {
    return WasmLocalStorageTestResult::kSnapshotUnexpectedAreaCount;
  }

  const auto& area = snapshot.area_results.front();
  if (area.storage_key != storage_key) {
    return WasmLocalStorageTestResult::kSnapshotStorageKeyMismatch;
  }
  if (area.result.outcome != AreaOutcome::kCommittedMapUpdate ||
      !area.result.status.ok()) {
    return WasmLocalStorageTestResult::kSnapshotNotCommitted;
  }
  return WasmLocalStorageTestResult::kSuccess;
}

#endif  // M7 LocalStorage acceptance

}  // namespace

#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST)

class StorageServiceImpl::WasmLocalStorageCloseFence {
 public:
  enum class Phase {
    kPreparing,
    kPreparedForAreaRelease,
    kWaitingForAreaRelease,
    kArmedForClose,
    kWaitingForStorageRemoval,
    kWaitingForDatabaseFence,
  };

  WasmLocalStorageCloseFence(
      base::FilePath profile_path,
      blink::StorageKey storage_key,
      uint64_t generation,
      scoped_refptr<base::SequencedTaskRunner> database_task_runner,
      mojom::WasmLocalStorageTestApi::PrepareCommitCloseFenceCallback
          prepare_callback)
      : profile_path(std::move(profile_path)),
        storage_key(std::move(storage_key)),
        generation(generation),
        database_task_runner(std::move(database_task_runner)),
        prepare_callback(std::move(prepare_callback)) {}

  WasmLocalStorageCloseFence(const WasmLocalStorageCloseFence&) = delete;
  WasmLocalStorageCloseFence& operator=(const WasmLocalStorageCloseFence&) =
      delete;
  ~WasmLocalStorageCloseFence() = default;

  Phase phase = Phase::kPreparing;
  const base::FilePath profile_path;
  const blink::StorageKey storage_key;
  const uint64_t generation;
  const scoped_refptr<base::SequencedTaskRunner> database_task_runner;
  mojom::WasmLocalStorageTestApi::PrepareCommitCloseFenceCallback
      prepare_callback;
  mojom::WasmLocalStorageTestApi::ArmCommitCloseFenceCallback arm_callback;
  mojom::WasmLocalStorageTestApi::WaitForCloseFenceCallback wait_callback;
  bool storage_removed = false;
  bool rebind_attempted = false;
};

#endif  // M7 LocalStorage acceptance

StorageServiceImpl::StorageServiceImpl(
    mojo::PendingReceiver<mojom::StorageService> receiver,
    scoped_refptr<base::SequencedTaskRunner> io_task_runner)
    : receiver_(this, std::move(receiver)),
      io_task_runner_(std::move(io_task_runner)) {}

StorageServiceImpl::~StorageServiceImpl() = default;

void StorageServiceImpl::EnableAggressiveDomStorageFlushing() {
  StorageAreaImpl::EnableAggressiveCommitDelay();
}

#if !BUILDFLAG(IS_ANDROID)
void StorageServiceImpl::SetDataDirectory(
    const base::FilePath& path,
    mojo::PendingRemote<mojom::Directory> directory) {
  remote_data_directory_path_ = path;
  remote_data_directory_.Bind(std::move(directory));

  // We can assume we must be sandboxed if we're getting a remote data
  // directory handle. Override the default FilesystemProxy factory to produce
  // instances restricted to operations within |path|, which can operate
  // from within a sandbox.
  SetFilesystemProxyFactory(base::BindRepeating(
      &CreateRestrictedFilesystemProxy, remote_data_directory_path_,
      io_task_runner_,
      base::BindRepeating(&StorageServiceImpl::BindDataDirectoryReceiver,
                          weak_ptr_factory_.GetWeakPtr()),
      base::SequencedTaskRunner::GetCurrentDefault()));

  // SQLite needs our VFS implementation to work over a FilesystemProxy. This
  // installs it as the default implementation for the service process.
  sql::SandboxedVfs::Register(
      kVfsName, std::make_unique<SandboxedVfsDelegate>(CreateFilesystemProxy()),
      /*make_default=*/true);
}
#endif  // !BUILDFLAG(IS_ANDROID)

void StorageServiceImpl::BindLocalStorageControl(
    const std::optional<base::FilePath>& path,
    mojo::PendingReceiver<mojom::LocalStorageControl> receiver) {
  if (path.has_value()) {
    if (!path->IsAbsolute()) {
      // Refuse to bind LocalStorage for relative paths.
      return;
    }

#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST)
    if (wasm_local_storage_close_fence_ &&
        wasm_local_storage_close_fence_->profile_path == *path) {
      // A prepared close fence is tied to the old instance. Replacing it here
      // would turn a later database no-op into a receipt for a different
      // LocalStorage object, so reject the rebind and make the fence fail.
      wasm_local_storage_close_fence_->rebind_attempted = true;
      if (wasm_local_storage_close_fence_->phase ==
          WasmLocalStorageCloseFence::Phase::kWaitingForAreaRelease) {
        // An Arm callback is retained while the StorageArea and test-API Mojo
        // pipes settle. Do not leave it waiting if the tracked LocalStorage
        // control was rebound in the meantime.
        CompleteWasmLocalStorageArmFence(
            WasmLocalStorageTestResult::kStorageRebound);
      }
      return;
    }
#endif

    // TODO(crbug.com/396030877): Remove this workaround to remove the
    // pre-existing LocalStorage once the issue is resolved.
    auto iter = persistent_local_storage_map_.find(*path);
    if (iter != persistent_local_storage_map_.end()) {
      ShutDownAndRemoveLocalStorage(iter->second);
    }
  }

  auto new_local_storage = std::make_unique<LocalStorageImpl>(
      path.value_or(base::FilePath()),
      base::BindOnce(&StorageServiceImpl::ShutDownAndRemoveLocalStorage,
                     weak_ptr_factory_.GetWeakPtr()),
      std::move(receiver));
  if (path.has_value()) {
    persistent_local_storage_map_[*path] = new_local_storage.get();
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST)
    persistent_local_storage_generations_[*path] =
        ++next_persistent_local_storage_generation_;
#endif
  }
  local_storages_.insert(std::move(new_local_storage));
}

void StorageServiceImpl::BindSessionStorageControl(
    const std::optional<base::FilePath>& path,
    bool clear_on_open,
    mojo::PendingReceiver<mojom::SessionStorageControl> receiver) {
  if (path.has_value()) {
    if (!path->IsAbsolute()) {
      // Refuse to bind SessionStorage for relative paths.
      return;
    }

    // TODO(crbug.com/396030877): Remove this workaround to remove the
    // pre-existing SessionStorage once the issue is resolved.
    auto iter = persistent_session_storage_map_.find(*path);
    if (iter != persistent_session_storage_map_.end()) {
      ShutDownAndRemoveSessionStorage(iter->second);
    }
  }

  auto new_session_storage = std::make_unique<SessionStorageImpl>(
      path.value_or(base::FilePath()),
      GetSessionStorageBackingMode(path.has_value(), clear_on_open),
      base::OnceCallback<void(SessionStorageImpl*)>(
          base::BindOnce(&StorageServiceImpl::ShutDownAndRemoveSessionStorage,
                         weak_ptr_factory_.GetWeakPtr())),
      std::move(receiver));
  if (path.has_value()) {
    persistent_session_storage_map_[*path] = new_session_storage.get();
  }
  session_storages_.insert(std::move(new_session_storage));
}

void StorageServiceImpl::BindTestApi(
    mojo::ScopedMessagePipeHandle test_api_receiver) {
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST)
  // The source-selected close receipt is instance-bound: it observes this
  // StorageServiceImpl's actual LocalStorage owner set rather than a process
  // global test singleton.
  wasm_local_storage_test_api_receivers_.Add(
      this, mojo::PendingReceiver<mojom::WasmLocalStorageTestApi>(
                std::move(test_api_receiver)));
#else
  GetTestApiBinderForTesting().Run(std::move(test_api_receiver));
#endif
}

#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST)

void StorageServiceImpl::PrepareCommitCloseFence(
    const base::FilePath& profile_path,
    const blink::StorageKey& storage_key,
    PrepareCommitCloseFenceCallback callback) {
  if (!profile_path.IsAbsolute()) {
    PostWasmLocalStorageTestResult(
        std::move(callback), WasmLocalStorageTestResult::kInvalidProfilePath);
    return;
  }
  if (storage_key.origin().opaque() || storage_key.top_level_site().opaque()) {
    PostWasmLocalStorageTestResult(
        std::move(callback), WasmLocalStorageTestResult::kOpaqueStorageKey);
    return;
  }
  if (wasm_local_storage_close_fence_) {
    PostWasmLocalStorageTestResult(
        std::move(callback), WasmLocalStorageTestResult::kFenceAlreadyArmed);
    return;
  }

  const auto storage_it = persistent_local_storage_map_.find(profile_path);
  const auto generation_it =
      persistent_local_storage_generations_.find(profile_path);
  if (storage_it == persistent_local_storage_map_.end() ||
      generation_it == persistent_local_storage_generations_.end()) {
    PostWasmLocalStorageTestResult(
        std::move(callback), WasmLocalStorageTestResult::kStorageNotFound);
    return;
  }

  LocalStorageImpl* const storage = storage_it->second;
  if (storage->GetStoragePartitionDirectory() != profile_path) {
    PostWasmLocalStorageTestResult(
        std::move(callback), WasmLocalStorageTestResult::kStorageDisconnected);
    return;
  }
  // Request the snapshot while the sole target area is still bound. That
  // makes this request itself admit and force the immediate UpdateMaps work;
  // waiting until OnNoBindings() would race its own immediate commit and can
  // legitimately observe kNoPendingMapUpdate instead.
  if (!storage->HasExactlyOneBoundStorageAreaForTesting(storage_key)) {
    PostWasmLocalStorageTestResult(
        std::move(callback), WasmLocalStorageTestResult::kStorageAreaNotBound);
    return;
  }
  if (ShouldUseSqliteBackend(/*in_memory=*/false)) {
    PostWasmLocalStorageTestResult(
        std::move(callback), WasmLocalStorageTestResult::kNotLevelDb);
    return;
  }
  if (!storage->GetDatabaseForTesting()) {
    PostWasmLocalStorageTestResult(
        std::move(callback), WasmLocalStorageTestResult::kDatabaseNotReady);
    return;
  }

  // AsyncDomStorageDatabase creates its SequenceBound object with this exact
  // resource-keyed runner. Holding the returned runner lets WaitForCloseFence
  // enqueue its no-op after LocalStorageImpl's SequenceBound destruction task.
  const base::FilePath database_path =
      DomStorageDatabase::GetPath(StorageType::kLocalStorage, profile_path);
  scoped_refptr<base::SequencedTaskRunner> database_task_runner =
      GetTaskRunnerForDb(database_path);
  if (!database_task_runner) {
    PostWasmLocalStorageTestResult(
        std::move(callback), WasmLocalStorageTestResult::kDatabaseNotReady);
    return;
  }

  const uint64_t generation = generation_it->second;
  wasm_local_storage_close_fence_ =
      std::make_unique<WasmLocalStorageCloseFence>(
          profile_path, storage_key, generation,
          std::move(database_task_runner), std::move(callback));
  storage->RequestImmediateCommitSnapshot(base::BindOnce(
      [](base::WeakPtr<StorageServiceImpl> service, uint64_t generation,
         blink::StorageKey storage_key,
         LocalStorageImpl::ImmediateCommitSnapshotResult snapshot) {
        if (!service) {
          return;
        }
        service->OnWasmLocalStorageCloseFenceSnapshot(
            generation,
            ClassifyWasmLocalStorageSnapshot(snapshot, storage_key));
      },
      weak_ptr_factory_.GetWeakPtr(), generation, storage_key));
}

void StorageServiceImpl::WaitForCloseFence(WaitForCloseFenceCallback callback) {
  if (!wasm_local_storage_close_fence_) {
    PostWasmLocalStorageTestResult(
        std::move(callback), WasmLocalStorageTestResult::kNoPreparedFence);
    return;
  }

  WasmLocalStorageCloseFence& fence = *wasm_local_storage_close_fence_;
  if (fence.phase == WasmLocalStorageCloseFence::Phase::kPreparing) {
    PostWasmLocalStorageTestResult(
        std::move(callback), WasmLocalStorageTestResult::kFenceNotPrepared);
    return;
  }
  if (fence.phase ==
          WasmLocalStorageCloseFence::Phase::kPreparedForAreaRelease ||
      fence.phase ==
          WasmLocalStorageCloseFence::Phase::kWaitingForAreaRelease) {
    PostWasmLocalStorageTestResult(
        std::move(callback), WasmLocalStorageTestResult::kFenceNotArmed);
    return;
  }
  if (fence.phase != WasmLocalStorageCloseFence::Phase::kArmedForClose) {
    PostWasmLocalStorageTestResult(
        std::move(callback), WasmLocalStorageTestResult::kWaitAlreadyPending);
    return;
  }

  fence.wait_callback = std::move(callback);
  fence.phase = WasmLocalStorageCloseFence::Phase::kWaitingForStorageRemoval;
  MaybeStartWasmLocalStorageCloseFence();
}

void StorageServiceImpl::OnWasmLocalStorageCloseFenceSnapshot(
    uint64_t generation,
    WasmLocalStorageTestResult result) {
  if (!wasm_local_storage_close_fence_ ||
      wasm_local_storage_close_fence_->generation != generation ||
      wasm_local_storage_close_fence_->phase !=
          WasmLocalStorageCloseFence::Phase::kPreparing) {
    return;
  }

  WasmLocalStorageCloseFence& fence = *wasm_local_storage_close_fence_;
  if (result != WasmLocalStorageTestResult::kSuccess) {
    CompleteWasmLocalStoragePrepareFence(result);
    return;
  }
  if (fence.rebind_attempted) {
    CompleteWasmLocalStoragePrepareFence(
        WasmLocalStorageTestResult::kStorageRebound);
    return;
  }

  const auto storage_it =
      persistent_local_storage_map_.find(fence.profile_path);
  const auto generation_it =
      persistent_local_storage_generations_.find(fence.profile_path);
  if (storage_it == persistent_local_storage_map_.end() ||
      generation_it == persistent_local_storage_generations_.end() ||
      generation_it->second != fence.generation) {
    CompleteWasmLocalStoragePrepareFence(
        WasmLocalStorageTestResult::kStorageDisconnected);
    return;
  }
  // The StorageArea remains bound until this successful snapshot has returned
  // to the browser helper. ArmCommitCloseFence() verifies its later closure.
  fence.phase = WasmLocalStorageCloseFence::Phase::kPreparedForAreaRelease;
  CompleteWasmLocalStoragePrepareFence(WasmLocalStorageTestResult::kSuccess);
}

void StorageServiceImpl::ArmCommitCloseFence(
    ArmCommitCloseFenceCallback callback) {
  if (!wasm_local_storage_close_fence_) {
    PostWasmLocalStorageTestResult(
        std::move(callback), WasmLocalStorageTestResult::kNoPreparedFence);
    return;
  }

  WasmLocalStorageCloseFence& fence = *wasm_local_storage_close_fence_;
  if (fence.phase == WasmLocalStorageCloseFence::Phase::kPreparing) {
    PostWasmLocalStorageTestResult(
        std::move(callback), WasmLocalStorageTestResult::kFenceNotPrepared);
    return;
  }
  if (fence.phase !=
      WasmLocalStorageCloseFence::Phase::kPreparedForAreaRelease) {
    PostWasmLocalStorageTestResult(
        std::move(callback), WasmLocalStorageTestResult::kFenceAlreadyArmed);
    return;
  }

  // Retain the callback before checking the tracked instance. Arm must not
  // fail merely because the StorageArea disconnect on another Mojo pipe has
  // not been dispatched yet; LocalStorageImpl owns the notification/latch for
  // that transition and will call OnWasmLocalStorageCloseFenceAreasUnbound().
  fence.arm_callback = std::move(callback);
  if (fence.rebind_attempted) {
    CompleteWasmLocalStorageArmFence(
        WasmLocalStorageTestResult::kStorageRebound);
    return;
  }

  const auto storage_it =
      persistent_local_storage_map_.find(fence.profile_path);
  const auto generation_it =
      persistent_local_storage_generations_.find(fence.profile_path);
  if (storage_it == persistent_local_storage_map_.end() ||
      generation_it == persistent_local_storage_generations_.end() ||
      generation_it->second != fence.generation ||
      storage_it->second->GetStoragePartitionDirectory() != fence.profile_path) {
    CompleteWasmLocalStorageArmFence(
        WasmLocalStorageTestResult::kStorageDisconnected);
    return;
  }

  // This is the explicit cross-pipe closure admission. A helper-side
  // StorageArea reset is asynchronous, so Arm is a notification-backed wait,
  // not a one-shot HasBoundStorageAreasForTesting() poll. The local instance's
  // latch also covers the case where its last OnNoBindings() arrived before
  // this independently ordered Arm request.
  fence.phase = WasmLocalStorageCloseFence::Phase::kWaitingForAreaRelease;
  storage_it->second->RunWhenNoStorageAreasBoundForTesting(base::BindOnce(
      &StorageServiceImpl::OnWasmLocalStorageCloseFenceAreasUnbound,
      weak_ptr_factory_.GetWeakPtr(), fence.generation));
}

void StorageServiceImpl::OnWasmLocalStorageCloseFenceAreasUnbound(
    uint64_t generation) {
  if (!wasm_local_storage_close_fence_ ||
      wasm_local_storage_close_fence_->generation != generation ||
      wasm_local_storage_close_fence_->phase !=
          WasmLocalStorageCloseFence::Phase::kWaitingForAreaRelease) {
    return;
  }

  WasmLocalStorageCloseFence& fence = *wasm_local_storage_close_fence_;
  if (fence.rebind_attempted) {
    CompleteWasmLocalStorageArmFence(
        WasmLocalStorageTestResult::kStorageRebound);
    return;
  }

  const auto storage_it = persistent_local_storage_map_.find(fence.profile_path);
  const auto generation_it =
      persistent_local_storage_generations_.find(fence.profile_path);
  if (storage_it == persistent_local_storage_map_.end() ||
      generation_it == persistent_local_storage_generations_.end() ||
      generation_it->second != fence.generation ||
      storage_it->second->GetStoragePartitionDirectory() != fence.profile_path) {
    CompleteWasmLocalStorageArmFence(
        WasmLocalStorageTestResult::kStorageDisconnected);
    return;
  }

  LocalStorageImpl* const storage = storage_it->second;
  if (storage->HasBoundStorageAreasForTesting()) {
    // A new area binding won the race after the earlier last-unbind signal.
    // Re-register with this same instance; do not turn the transient state
    // into a false close admission and do not poll or time out.
    storage->RunWhenNoStorageAreasBoundForTesting(base::BindOnce(
        &StorageServiceImpl::OnWasmLocalStorageCloseFenceAreasUnbound,
        weak_ptr_factory_.GetWeakPtr(), generation));
    return;
  }

  fence.phase = WasmLocalStorageCloseFence::Phase::kArmedForClose;
  CompleteWasmLocalStorageArmFence(WasmLocalStorageTestResult::kSuccess);
}

void StorageServiceImpl::MaybeStartWasmLocalStorageCloseFence() {
  if (!wasm_local_storage_close_fence_) {
    return;
  }

  WasmLocalStorageCloseFence& fence = *wasm_local_storage_close_fence_;
  if (fence.phase !=
      WasmLocalStorageCloseFence::Phase::kWaitingForStorageRemoval) {
    return;
  }
  if (fence.rebind_attempted) {
    CompleteWasmLocalStorageWaitFence(
        WasmLocalStorageTestResult::kStorageRebound);
    return;
  }
  if (!fence.storage_removed) {
    return;
  }
  if (!fence.database_task_runner) {
    CompleteWasmLocalStorageWaitFence(
        WasmLocalStorageTestResult::kDatabaseFencePostFailed);
    return;
  }

  fence.phase = WasmLocalStorageCloseFence::Phase::kWaitingForDatabaseFence;
  const bool posted = fence.database_task_runner->PostTaskAndReply(
      FROM_HERE, base::DoNothing(),
      base::BindOnce(&StorageServiceImpl::OnWasmLocalStorageCloseFenceNoOpComplete,
                     weak_ptr_factory_.GetWeakPtr(), fence.generation));
  if (!posted) {
    CompleteWasmLocalStorageWaitFence(
        WasmLocalStorageTestResult::kDatabaseFencePostFailed);
  }
}

void StorageServiceImpl::OnWasmLocalStorageCloseFenceNoOpComplete(
    uint64_t generation) {
  if (!wasm_local_storage_close_fence_ ||
      wasm_local_storage_close_fence_->generation != generation ||
      wasm_local_storage_close_fence_->phase !=
          WasmLocalStorageCloseFence::Phase::kWaitingForDatabaseFence) {
    return;
  }

  CompleteWasmLocalStorageWaitFence(
      wasm_local_storage_close_fence_->rebind_attempted
          ? WasmLocalStorageTestResult::kStorageRebound
          : WasmLocalStorageTestResult::kSuccess);
}

void StorageServiceImpl::CompleteWasmLocalStoragePrepareFence(
    WasmLocalStorageTestResult result) {
  if (!wasm_local_storage_close_fence_) {
    return;
  }

  auto callback =
      std::move(wasm_local_storage_close_fence_->prepare_callback);
  if (result != WasmLocalStorageTestResult::kSuccess) {
    wasm_local_storage_close_fence_.reset();
  }
  PostWasmLocalStorageTestResult(std::move(callback), result);
}

void StorageServiceImpl::CompleteWasmLocalStorageArmFence(
    WasmLocalStorageTestResult result) {
  if (!wasm_local_storage_close_fence_) {
    return;
  }

  auto callback = std::move(wasm_local_storage_close_fence_->arm_callback);
  if (result != WasmLocalStorageTestResult::kSuccess) {
    wasm_local_storage_close_fence_.reset();
  }
  PostWasmLocalStorageTestResult(std::move(callback), result);
}

void StorageServiceImpl::CompleteWasmLocalStorageWaitFence(
    WasmLocalStorageTestResult result) {
  if (!wasm_local_storage_close_fence_) {
    return;
  }

  auto callback = std::move(wasm_local_storage_close_fence_->wait_callback);
  wasm_local_storage_close_fence_.reset();
  PostWasmLocalStorageTestResult(std::move(callback), result);
}

#endif  // M7 LocalStorage acceptance

void StorageServiceImpl::ShutDownAndRemoveSessionStorage(
    SessionStorageImpl* storage) {
  if (!storage->GetStoragePartitionDirectory().empty()) {
    persistent_session_storage_map_.erase(
        storage->GetStoragePartitionDirectory());
  }

  auto it = session_storages_.find(storage);
  if (it != session_storages_.end()) {
    session_storages_.erase(it);
  }
}

void StorageServiceImpl::ShutDownAndRemoveLocalStorage(
    LocalStorageImpl* storage) {
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST)
  const base::FilePath storage_partition_directory =
      storage->GetStoragePartitionDirectory();
  bool removed_fenced_storage = false;
  if (!storage_partition_directory.empty()) {
    const auto storage_it =
        persistent_local_storage_map_.find(storage_partition_directory);
    const auto generation_it = persistent_local_storage_generations_.find(
        storage_partition_directory);
    if (storage_it != persistent_local_storage_map_.end() &&
        generation_it != persistent_local_storage_generations_.end() &&
        storage_it->second == storage) {
      removed_fenced_storage =
          wasm_local_storage_close_fence_ &&
          wasm_local_storage_close_fence_->profile_path ==
              storage_partition_directory &&
          wasm_local_storage_close_fence_->generation == generation_it->second;
      persistent_local_storage_map_.erase(storage_it);
      persistent_local_storage_generations_.erase(generation_it);
    }
  }
#else
  if (!storage->GetStoragePartitionDirectory().empty()) {
    persistent_local_storage_map_.erase(
        storage->GetStoragePartitionDirectory());
  }
#endif

  auto it = local_storages_.find(storage);
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST)
  bool storage_erased = false;
#endif
  if (it != local_storages_.end()) {
    local_storages_.erase(it);
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST)
    storage_erased = true;
#endif
  }

#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST)
  if (removed_fenced_storage && storage_erased &&
      wasm_local_storage_close_fence_) {
    if (wasm_local_storage_close_fence_->phase ==
        WasmLocalStorageCloseFence::Phase::kWaitingForAreaRelease) {
      // The exact LocalStorageImpl that owned the retained Arm notification
      // vanished before its last StorageAreaHolder could report
      // OnNoBindings(). Do not strand the test API callback or turn teardown
      // into an implicit area-close receipt.
      CompleteWasmLocalStorageArmFence(
          WasmLocalStorageTestResult::kStorageDisconnected);
      return;
    }

    // Erasing the owner has synchronously run LocalStorageImpl destruction.
    // Its AsyncDomStorageDatabase SequenceBound destruction task is now ahead
    // of the FIFO no-op posted by MaybeStartWasmLocalStorageCloseFence().
    if (wasm_local_storage_close_fence_->phase ==
            WasmLocalStorageCloseFence::Phase::kArmedForClose ||
        wasm_local_storage_close_fence_->phase ==
            WasmLocalStorageCloseFence::Phase::kWaitingForStorageRemoval) {
      wasm_local_storage_close_fence_->storage_removed = true;
      MaybeStartWasmLocalStorageCloseFence();
    }
  }
#endif
}

#if !BUILDFLAG(IS_ANDROID)
void StorageServiceImpl::BindDataDirectoryReceiver(
    mojo::PendingReceiver<mojom::Directory> receiver) {
  DCHECK(remote_data_directory_.is_bound());
  remote_data_directory_->Clone(std::move(receiver));
}
#endif

}  // namespace storage
