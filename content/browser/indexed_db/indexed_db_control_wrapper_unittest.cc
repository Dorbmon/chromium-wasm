// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "content/browser/indexed_db/indexed_db_control_wrapper.h"

#include "base/files/scoped_temp_dir.h"
#include "base/memory/ref_counted.h"
#include "base/run_loop.h"
#include "base/task/bind_post_task.h"
#include "base/task/sequenced_task_runner.h"
#include "base/task/single_thread_task_runner.h"
#include "base/test/task_environment.h"
#include "components/services/storage/privileged/cpp/bucket_client_info.h"
#include "components/services/storage/privileged/mojom/indexed_db_client_state_checker.mojom.h"
#include "components/services/storage/public/cpp/buckets/bucket_locator.h"
#include "mojo/public/cpp/bindings/receiver.h"
#include "mojo/public/cpp/bindings/remote.h"
#include "storage/browser/test/mock_quota_manager.h"
#include "storage/browser/test/mock_quota_manager_proxy.h"
#include "storage/browser/test/mock_special_storage_policy.h"
#include "testing/gtest/include/gtest/gtest.h"
#include "third_party/blink/public/common/storage_key/storage_key.h"

#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
#include "content/test/wasm_mojo_core_test_support.h"

namespace content::indexed_db {
namespace {

class TestIndexedDBClientStateChecker final
    : public storage::mojom::IndexedDBClientStateChecker {
 public:
  void DisallowInactiveClient(
      int32_t connection_id,
      storage::mojom::DisallowInactiveClientReason reason,
      mojo::PendingReceiver<storage::mojom::IndexedDBClientKeepActive>
          keep_active,
      storage::mojom::IndexedDBClientStateChecker::
          DisallowInactiveClientCallback callback) override {}
  void MakeClone(
      mojo::PendingReceiver<storage::mojom::IndexedDBClientStateChecker>
          checker) override {}
};

class TestSpecialStoragePolicy final
    : public storage::MockSpecialStoragePolicy {
 public:
  bool HasObserverForTesting() const {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    return !observers_.empty();
  }

 private:
  ~TestSpecialStoragePolicy() override = default;
};

TEST(IndexedDBControlWrapperTest,
     PolicyNotificationAfterResultCloseDoesNotUseClosedControl) {
  base::test::TaskEnvironment task_environment;
  content::test::InitializeMojoCoreForWasmTests();
  base::ScopedTempDir temp_dir;
  ASSERT_TRUE(temp_dir.CreateUniqueTempDir());

  auto special_storage_policy =
      base::MakeRefCounted<TestSpecialStoragePolicy>();
  auto quota_manager = base::MakeRefCounted<storage::MockQuotaManager>(
      /*is_incognito=*/false, temp_dir.GetPath(),
      base::SingleThreadTaskRunner::GetCurrentDefault(),
      special_storage_policy);
  auto quota_manager_proxy =
      base::MakeRefCounted<storage::MockQuotaManagerProxy>(
          quota_manager.get(), base::SequencedTaskRunner::GetCurrentDefault());

  IndexedDBControlWrapper wrapper(
      temp_dir.GetPath(), special_storage_policy, quota_manager_proxy,
      mojo::PendingRemote<storage::mojom::BlobStorageContext>(),
      mojo::PendingRemote<storage::mojom::FileSystemAccessContext>(),
      base::SequencedTaskRunner::GetCurrentDefault());

  // The StoragePolicyObserver's SequenceBound observer must be installed
  // before the later policy notification. BindIndexedDB synchronously starts
  // tracking this origin and also binds the wrapper's control remote.
  task_environment.RunUntilIdle();
  ASSERT_TRUE(special_storage_policy->HasObserverForTesting());
  const blink::StorageKey storage_key =
      blink::StorageKey::CreateFromStringForTesting("https://example.test");
  mojo::Remote<blink::mojom::IDBFactory> factory;
  TestIndexedDBClientStateChecker client_state_checker;
  mojo::Receiver<storage::mojom::IndexedDBClientStateChecker>
      client_state_checker_receiver(&client_state_checker);
  wrapper.BindIndexedDB(storage::BucketLocator::ForDefaultBucket(storage_key),
                        storage::BucketClientInfo{},
                        client_state_checker_receiver.BindNewPipeAndPassRemote(),
                        factory.BindNewPipeAndPassReceiver());
  task_environment.RunUntilIdle();

  base::RunLoop close_loop;
  ASSERT_TRUE(wrapper.ShutdownAndReply(base::BindPostTask(
      base::SequencedTaskRunner::GetCurrentDefault(),
      close_loop.QuitClosure())));
  close_loop.Run();
  task_environment.RunUntilIdle();
  ASSERT_FALSE(special_storage_policy->HasObserverForTesting());

  // Before the terminal close handling, this delivered an update to the
  // observer, which tried to use the disconnected (or null) control remote.
  // The close must remove that observer and control path instead.
  special_storage_policy->AddSessionOnly(storage_key.origin().GetURL());
  special_storage_policy->NotifyPolicyChanged();
  task_environment.RunUntilIdle();
}

}  // namespace
}  // namespace content::indexed_db
#endif
