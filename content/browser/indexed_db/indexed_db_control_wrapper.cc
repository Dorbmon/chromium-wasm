// Copyright 2020 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "content/browser/indexed_db/indexed_db_control_wrapper.h"

#include <ostream>
#include <utility>

#include "base/check.h"
#include "base/functional/bind.h"
#include "components/services/storage/public/cpp/buckets/bucket_locator.h"
#include "components/services/storage/public/mojom/storage_policy_update.mojom.h"
#include "content/browser/indexed_db/indexed_db_context_impl.h"
#include "mojo/public/cpp/bindings/pending_receiver.h"
#include "mojo/public/cpp/bindings/pending_remote.h"
#include "third_party/blink/public/common/storage_key/storage_key.h"

namespace content::indexed_db {

IndexedDBControlWrapper::IndexedDBControlWrapper(
    const base::FilePath& data_path,
    scoped_refptr<storage::SpecialStoragePolicy> special_storage_policy,
    scoped_refptr<storage::QuotaManagerProxy> quota_manager_proxy,
    mojo::PendingRemote<storage::mojom::BlobStorageContext>
        blob_storage_context,
    mojo::PendingRemote<storage::mojom::FileSystemAccessContext>
        file_system_access_context,
    scoped_refptr<base::SequencedTaskRunner> io_task_runner) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  context_ = std::make_unique<IndexedDBContextImpl>(
      data_path, std::move(quota_manager_proxy),
      std::move(blob_storage_context), std::move(file_system_access_context),
      /*custom_task_runner=*/nullptr);

  if (special_storage_policy) {
    storage_policy_observer_.emplace(
        base::BindRepeating(
            &IndexedDBControlWrapper::OnSpecialStoragePolicyUpdated,
            base::Unretained(this)),
        io_task_runner, std::move(special_storage_policy));
  }
}

IndexedDBControlWrapper::~IndexedDBControlWrapper() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);

#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
  if (context_) {
    IndexedDBContextImpl::Shutdown(std::move(context_));
  }
#else
  IndexedDBContextImpl::Shutdown(std::move(context_));
#endif
}

void IndexedDBControlWrapper::BindIndexedDB(
    const storage::BucketLocator& bucket_locator,
    const storage::BucketClientInfo& client_info,
    mojo::PendingRemote<storage::mojom::IndexedDBClientStateChecker>
        client_state_checker_remote,
    mojo::PendingReceiver<blink::mojom::IDBFactory> receiver) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
  // A successful result-bearing shutdown consumes the context. Do not revive
  // its control pipe or begin policy tracking after that terminal transition;
  // dropping |receiver| deliberately disconnects late renderer ingress.
  if (!context_) {
    return;
  }
#endif
  if (storage_policy_observer_) {
    storage_policy_observer_->StartTrackingOrigin(
        bucket_locator.storage_key.origin());
  }
  GetIndexedDBControl().BindIndexedDB(bucket_locator, client_info,
                                      std::move(client_state_checker_remote),
                                      std::move(receiver));
}

storage::mojom::IndexedDBControl&
IndexedDBControlWrapper::GetIndexedDBControl() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
  CHECK(context_);
#endif
  DCHECK(
      !(indexed_db_control_.is_bound() && !indexed_db_control_.is_connected()))
      << "Rebinding is not supported yet.";

  if (!indexed_db_control_.is_bound()) {
    context_->BindControl(indexed_db_control_.BindNewPipeAndPassReceiver());
  }

  return *indexed_db_control_;
}

#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
bool IndexedDBControlWrapper::ShutdownAndReply(base::OnceClosure completion) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (!context_ || !completion) {
    return false;
  }

  if (!IndexedDBContextImpl::ShutdownAndReply(&context_,
                                              std::move(completion))) {
    return false;
  }

  // The context close clears the control receiver. Keeping this observer alive
  // would let a later policy notification invoke a disconnected control pipe
  // (or try to bind a new one) after the terminal close transition.
  storage_policy_observer_.reset();
  indexed_db_control_.reset();
  return true;
}
#endif

void IndexedDBControlWrapper::OnSpecialStoragePolicyUpdated(
    std::vector<storage::mojom::StoragePolicyUpdatePtr> policy_updates) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
  if (!context_) {
    return;
  }
#endif
  GetIndexedDBControl().ApplyPolicyUpdates(std::move(policy_updates));
}

}  // namespace content::indexed_db
