// Copyright 2019 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef COMPONENTS_SERVICES_STORAGE_STORAGE_SERVICE_IMPL_H_
#define COMPONENTS_SERVICES_STORAGE_STORAGE_SERVICE_IMPL_H_

#include <cstdint>
#include <map>
#include <memory>
#include <optional>
#include <set>

#include "base/containers/unique_ptr_adapters.h"
#include "base/files/file_path.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "base/task/sequenced_task_runner.h"
#include "build/build_config.h"
#include "components/services/storage/public/mojom/filesystem/directory.mojom.h"
#include "components/services/storage/public/mojom/storage_service.mojom.h"
#include "mojo/public/cpp/bindings/pending_receiver.h"
#include "mojo/public/cpp/bindings/receiver.h"
#include "mojo/public/cpp/bindings/remote.h"

#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
#include "components/services/storage/public/mojom/wasm_local_storage_test_api.mojom.h"
#include "mojo/public/cpp/bindings/receiver_set.h"
#endif

namespace storage {

class LocalStorageImpl;
class SessionStorageImpl;
// Implementation of the main StorageService Mojo interface. This is the root
// owner of all Storage service instance state, managing the set of active
// persistent and in-memory local and session storage instances.
class StorageServiceImpl : public mojom::StorageService
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
                         , public mojom::WasmLocalStorageTestApi
#endif
{
 public:
  // NOTE: |io_task_runner| is only used in sandboxed environments and can be
  // null otherwise. If non-null, it should specify a task runner that will
  // never block and is thus capable of reliably facilitating IPC to the
  // browser.
  StorageServiceImpl(mojo::PendingReceiver<mojom::StorageService> receiver,
                     scoped_refptr<base::SequencedTaskRunner> io_task_runner);

  StorageServiceImpl(const StorageServiceImpl&) = delete;
  StorageServiceImpl& operator=(const StorageServiceImpl&) = delete;

  ~StorageServiceImpl() override;

  // mojom::StorageService implementation:
  void EnableAggressiveDomStorageFlushing() override;
#if !BUILDFLAG(IS_ANDROID)
  void SetDataDirectory(
      const base::FilePath& path,
      mojo::PendingRemote<mojom::Directory> directory) override;
#endif
  void BindLocalStorageControl(
      const std::optional<base::FilePath>& path,
      mojo::PendingReceiver<mojom::LocalStorageControl> receiver) override;
  void BindSessionStorageControl(
      const std::optional<base::FilePath>& path,
      bool clear_on_open,
      mojo::PendingReceiver<mojom::SessionStorageControl> receiver) override;
  void BindTestApi(mojo::ScopedMessagePipeHandle test_api_receiver) override;
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  void PrepareCommitCloseFence(
      const base::FilePath& profile_path,
      const blink::StorageKey& storage_key,
      PrepareCommitCloseFenceCallback callback) override;
  void ArmCommitCloseFence(ArmCommitCloseFenceCallback callback) override;
  void WaitForCloseFence(WaitForCloseFenceCallback callback) override;
#endif

  // These transfer ownership of the storage instance to a DeferredDeleter when
  // performing ShutDown. This allows the storage instance to be deleted after
  // ShutDown is complete. This prevents race conditions where a storage
  // instance for a user data directory is rebound while we wait for the
  // previous instance to ShutDown.
  void ShutDownAndRemoveSessionStorage(SessionStorageImpl* storage);
  void ShutDownAndRemoveLocalStorage(LocalStorageImpl* storage);

 private:
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  class WasmLocalStorageCloseFence;

  void OnWasmLocalStorageCloseFenceSnapshot(
      uint64_t generation,
      mojom::WasmLocalStorageTestResult result);
  void OnWasmLocalStorageCloseFenceAreasUnbound(uint64_t generation);
  void MaybeStartWasmLocalStorageCloseFence();
  void OnWasmLocalStorageCloseFenceNoOpComplete(uint64_t generation);
  void CompleteWasmLocalStoragePrepareFence(
      mojom::WasmLocalStorageTestResult result);
  void CompleteWasmLocalStorageArmFence(
      mojom::WasmLocalStorageTestResult result);
  void CompleteWasmLocalStorageWaitFence(
      mojom::WasmLocalStorageTestResult result);
#endif
#if !BUILDFLAG(IS_ANDROID)
  // Binds a Directory receiver to the same remote implementation to which
  // |remote_data_directory_| is bound. It is invalid to call this when
  // |remote_data_directory_| is unbound.
  void BindDataDirectoryReceiver(
      mojo::PendingReceiver<mojom::Directory> receiver);
#endif

  const mojo::Receiver<mojom::StorageService> receiver_;
  const scoped_refptr<base::SequencedTaskRunner> io_task_runner_;

#if !BUILDFLAG(IS_ANDROID)
  // If bound, the service will assume it should not perform certain filesystem
  // operations directly and will instead go through this interface.
  base::FilePath remote_data_directory_path_;
  mojo::Remote<mojom::Directory> remote_data_directory_;
#endif

  // Sets of all isolated local and session storages owned by the service. This
  // includes both persistent and in-memory storages.
  std::set<std::unique_ptr<LocalStorageImpl>, base::UniquePtrComparator>
      local_storages_;
  std::set<std::unique_ptr<SessionStorageImpl>, base::UniquePtrComparator>
      session_storages_;

  // Mappings from a profile directory within the user data directory to the
  // corresponding storage instance in `local_storages` or `session_storages_`.
  // The pointers in these maps are not owned by the map and must be removed
  // when removed from `local_storages_` or `session_storages_`. Only persistent
  // storages have entries in these maps.
  std::map<base::FilePath, raw_ptr<LocalStorageImpl, CtnExperimental>>
      persistent_local_storage_map_;
  std::map<base::FilePath, raw_ptr<SessionStorageImpl, CtnExperimental>>
      persistent_session_storage_map_;

#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  // These members are compiled only into the source-selected M7 test
  // artifact. They identify one persistent LocalStorage instance while its
  // close receipt is armed and prevent it from being silently rebound.
  mojo::ReceiverSet<mojom::WasmLocalStorageTestApi>
      wasm_local_storage_test_api_receivers_;
  std::map<base::FilePath, uint64_t> persistent_local_storage_generations_;
  uint64_t next_persistent_local_storage_generation_ = 0;
  std::unique_ptr<WasmLocalStorageCloseFence> wasm_local_storage_close_fence_;
#endif

  base::WeakPtrFactory<StorageServiceImpl> weak_ptr_factory_{this};
};

}  // namespace storage

#endif  // COMPONENTS_SERVICES_STORAGE_STORAGE_SERVICE_IMPL_H_
