// Copyright 2013 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "content/browser/dom_storage/dom_storage_context_wrapper.h"

#include <algorithm>
#include <optional>
#include <string>
#include <vector>

#include "base/command_line.h"
#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "base/functional/bind.h"
#include "base/functional/callback_helpers.h"
#include "base/location.h"
#include "base/memory/weak_ptr.h"
#include "base/metrics/histogram_functions.h"
#include "base/numerics/safe_conversions.h"
#include "base/strings/strcat.h"
#include "base/strings/utf_string_conversions.h"
#include "base/syslog_logging.h"
#include "base/task/sequenced_task_runner.h"
#include "base/task/single_thread_task_runner.h"
#include "base/task/thread_pool.h"
#include "build/build_config.h"
#include "components/services/storage/dom_storage/local_storage_impl.h"
#include "components/services/storage/dom_storage/session_storage_impl.h"
#include "components/services/storage/public/cpp/constants.h"
#include "components/services/storage/public/mojom/storage_policy_update.mojom.h"
#include "components/services/storage/public/mojom/storage_service.mojom.h"
#include "components/services/storage/public/mojom/storage_usage_info.mojom.h"
#include "content/browser/dom_storage/session_storage_namespace_impl.h"
#include "content/browser/renderer_host/frame_tree.h"
#include "content/browser/renderer_host/render_frame_host_impl.h"
#include "content/browser/storage_partition_impl.h"
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)
#include "content/public/browser/browser_context.h"
#include "content/public/browser/storage_partition_config.h"
#endif
#include "content/public/browser/browser_task_traits.h"
#include "content/public/browser/browser_thread.h"
#include "content/public/browser/content_browser_client.h"
#include "content/public/browser/permission_controller.h"
#include "content/public/browser/session_storage_usage_info.h"
#include "content/public/browser/storage_usage_info.h"
#include "content/public/common/content_client.h"
#include "content/public/common/content_features.h"
#include "content/public/common/content_switches.h"
#include "storage/browser/quota/special_storage_policy.h"
#include "third_party/blink/public/common/features.h"
#include "third_party/blink/public/common/permissions/permission_utils.h"
#include "third_party/blink/public/common/storage_key/storage_key.h"

namespace content {

namespace {

std::optional<base::FilePath> GetLocalStoragePath(
    StoragePartitionImpl* partition) {
#if BUILDFLAG(IS_WASM)
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)
  // The M7 LocalStorage acceptance intentionally leaves the partition itself
  // in memory. It supplies the browser-context path only to LocalStorage so
  // no other partition-owned store gains an implicit persistence claim. The
  // source-selected test uses the default partition, whose relative path is
  // empty and therefore exactly identifies the browser profile directory.
  if (!partition->GetConfig().is_default()) {
    return std::nullopt;
  }
  BrowserContext* const browser_context = partition->browser_context();
  return browser_context
             ? std::optional<base::FilePath>(browser_context->GetPath())
             : std::nullopt;
#else
  // The regular Wasm profile has no durable StoragePartition lifecycle yet.
  // Keep LocalStorage in memory rather than creating a LevelDB store which
  // cannot report a terminal, result-bearing drain to WasmProfile.
  static_cast<void>(partition);
  return std::nullopt;
#endif
#else
  return partition->GetStoragePartitionPath();
#endif
}

std::optional<base::FilePath> GetSessionStoragePath(
    StoragePartitionImpl* partition) {
#if BUILDFLAG(IS_WASM)
  // SessionStorage remains in memory even in the dedicated LocalStorage
  // acceptance. It has no result-bearing persistent shutdown protocol.
  static_cast<void>(partition);
  return std::nullopt;
#else
  return partition->GetStoragePartitionPath();
#endif
}

void AdaptSessionStorageUsageInfo(
    DOMStorageContextWrapper::GetSessionStorageUsageCallback callback,
    std::vector<storage::mojom::SessionStorageUsageInfoPtr> usage) {
  std::vector<SessionStorageUsageInfo> result;
  result.reserve(usage.size());
  for (const auto& entry : usage) {
    SessionStorageUsageInfo info;
    info.storage_key = entry->storage_key;
    info.namespace_id = entry->namespace_id;
    result.push_back(std::move(info));
  }
  std::move(callback).Run(result);
}

void AdaptStorageUsageInfo(
    DOMStorageContext::GetLocalStorageUsageCallback callback,
    std::vector<storage::mojom::StorageUsageInfoPtr> usage) {
  std::vector<StorageUsageInfo> result;
  result.reserve(usage.size());
  for (const auto& info : usage) {
    result.emplace_back(info->storage_key, info->total_size_bytes,
                        info->last_modified);
  }
  std::move(callback).Run(result);
}

}  // namespace

scoped_refptr<DOMStorageContextWrapper> DOMStorageContextWrapper::Create(
    StoragePartitionImpl* partition,
    scoped_refptr<storage::SpecialStoragePolicy> special_storage_policy) {
  auto wrapper = base::MakeRefCounted<DOMStorageContextWrapper>(partition);
  if (special_storage_policy) {
    wrapper->storage_policy_observer_.emplace(
        // `storage_policy_observer_` is owned by `wrapper` and so it is safe
        // to use base::Unretained here.
        base::BindRepeating(&DOMStorageContextWrapper::ApplyPolicyUpdates,
                            base::Unretained(wrapper.get())),
        GetIOThreadTaskRunner({}), std::move(special_storage_policy));
  }

  wrapper->local_storage_control_->GetUsage(base::BindOnce(
      &DOMStorageContextWrapper::OnStartupUsageRetrieved, wrapper));
  return wrapper;
}

DOMStorageContextWrapper::DOMStorageContextWrapper(
    StoragePartitionImpl* partition)
    : partition_(partition) {
  // `partition_` can be null in test environments.
  if (!partition_) {
    return;
  }

  bool clear_session_storage = partition_->ShouldClearSessionStorageOnStartup();
  base::UmaHistogramBoolean(
      "Storage.SessionStorage.ClearDiskStateAtStoragePartitionInit",
      clear_session_storage);
  MaybeBindSessionStorageControl(clear_session_storage);
  MaybeBindLocalStorageControl();

  // Report on disk LocalStorage db size.
  if (const std::optional<base::FilePath> dom_storage_path =
          GetLocalStoragePath(partition_)) {
    // Path to the LocalStorage leveldb directory.
    base::FilePath db_path = storage::GetLocalStorageDatabasePath(
        *dom_storage_path);

    // Offload the blocking file operation and report the result.
    base::ThreadPool::PostTaskAndReplyWithResult(
        FROM_HERE, {base::MayBlock()},
        base::BindOnce(
            [](const base::FilePath& path) -> int64_t {
              return base::ComputeDirectorySize(path);
            },
            db_path),
        base::BindOnce([](int64_t db_size) {
          int size_kb = base::saturated_cast<int>(db_size / 1024);
          base::UmaHistogramMemoryKB("LocalStorage.DatabaseOnDiskSizeKB",
                                     size_kb);
        }));
  }
}

DOMStorageContextWrapper::~DOMStorageContextWrapper() {
  DCHECK(!local_storage_control_)
      << "Shutdown should be called before destruction";
}

storage::mojom::SessionStorageControl*
DOMStorageContextWrapper::GetSessionStorageControl() {
  if (!session_storage_control_)
    return nullptr;
  return session_storage_control_.get();
}

storage::mojom::LocalStorageControl*
DOMStorageContextWrapper::GetLocalStorageControl() {
  DCHECK(local_storage_control_);
  return local_storage_control_.get();
}

void DOMStorageContextWrapper::GetLocalStorageUsage(
    GetLocalStorageUsageCallback callback) {
  if (!local_storage_control_) {
    // Shutdown() has been called.
    std::move(callback).Run(std::vector<StorageUsageInfo>());
    return;
  }

  local_storage_control_->GetUsage(
      base::BindOnce(&AdaptStorageUsageInfo, std::move(callback)));
}

void DOMStorageContextWrapper::GetSessionStorageUsage(
    GetSessionStorageUsageCallback callback) {
  if (!session_storage_control_) {
    // Shutdown() has been called.
    std::move(callback).Run(std::vector<SessionStorageUsageInfo>());
    return;
  }

  session_storage_control_->GetUsage(
      base::BindOnce(&AdaptSessionStorageUsageInfo, std::move(callback)));
}

void DOMStorageContextWrapper::DeleteLocalStorage(
    const blink::StorageKey& storage_key,
    base::OnceClosure callback) {
  DCHECK(callback);
  if (!local_storage_control_) {
    // Shutdown() has been called.
    std::move(callback).Run();
    return;
  }

  local_storage_control_->DeleteStorage(storage_key, std::move(callback));
}

void DOMStorageContextWrapper::PerformLocalStorageCleanup(
    base::OnceClosure callback) {
  DCHECK(callback);
  if (!local_storage_control_) {
    // Shutdown() has been called.
    std::move(callback).Run();
    return;
  }

  local_storage_control_->CleanUpStorage(std::move(callback));
}

void DOMStorageContextWrapper::DeleteSessionStorage(
    const SessionStorageUsageInfo& usage_info,
    base::OnceClosure callback) {
  if (!session_storage_control_) {
    // Shutdown() has been called.
    std::move(callback).Run();
    return;
  }
  session_storage_control_->DeleteStorage(
      usage_info.storage_key, usage_info.namespace_id, std::move(callback));
}

void DOMStorageContextWrapper::PerformSessionStorageCleanup(
    base::OnceClosure callback) {
  DCHECK(callback);
  if (!session_storage_control_) {
    // Shutdown() has been called.
    std::move(callback).Run();
    return;
  }

  session_storage_control_->CleanUpStorage(std::move(callback));
}

scoped_refptr<SessionStorageNamespace>
DOMStorageContextWrapper::RecreateSessionStorage(
    const std::string& namespace_id) {
  return SessionStorageNamespaceImpl::Create(this, namespace_id);
}

void DOMStorageContextWrapper::StartScavengingUnusedSessionStorage() {
  if (!session_storage_control_) {
    // Shutdown() has been called.
    return;
  }

  session_storage_control_->ScavengeUnusedNamespaces();
}

void DOMStorageContextWrapper::SetForceKeepSessionState() {
  if (!local_storage_control_) {
    // Shutdown() has been called.
    return;
  }

  local_storage_control_->ForceKeepSessionState();
}

void DOMStorageContextWrapper::Shutdown() {
  // |partition_| is about to be destroyed, so we must not dereference it after
  // this call.
  partition_ = nullptr;

  // Signals the implementation to perform shutdown operations.
  session_storage_control_.reset();
  local_storage_control_.reset();

  // Make sure the observer drops its reference to |this|.
  storage_policy_observer_.reset();
}

void DOMStorageContextWrapper::Flush() {
  if (session_storage_control_)
    session_storage_control_->Flush();
  if (local_storage_control_)
    local_storage_control_->Flush();
}

void DOMStorageContextWrapper::OpenLocalStorage(
    const blink::StorageKey& storage_key,
    std::optional<blink::LocalFrameToken> local_frame_token,
    mojo::PendingReceiver<blink::mojom::StorageArea> receiver,
    ChildProcessSecurityPolicyImpl::Handle security_policy_handle,
    mojo::ReportBadMessageCallback bad_message_callback) {
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)
  // The dedicated close receipt has sealed new LocalStorage admission. Do not
  // bind a new area to a control remote that the close path has already
  // detached.
  if (local_storage_rebind_sealed_for_wasm_profile_test_ ||
      !local_storage_control_) {
    return;
  }
#endif
  if (!IsRequestValid(StorageType::kLocalStorage, storage_key,
                      local_frame_token, std::move(security_policy_handle),
                      std::move(bad_message_callback))) {
    return;
  }
  DCHECK(local_storage_control_);
  local_storage_control_->BindStorageArea(storage_key, std::move(receiver));
  if (storage_policy_observer_) {
    storage_policy_observer_->StartTrackingOrigin(storage_key.origin());
  }
}

void DOMStorageContextWrapper::BindNamespace(
    const std::string& namespace_id,
    mojo::ReportBadMessageCallback bad_message_callback,
    mojo::PendingReceiver<blink::mojom::SessionStorageNamespace> receiver) {
  DCHECK(session_storage_control_);
  session_storage_control_->BindNamespace(namespace_id, std::move(receiver));
}

void DOMStorageContextWrapper::BindStorageArea(
    const blink::StorageKey& storage_key,
    std::optional<blink::LocalFrameToken> local_frame_token,
    const std::string& namespace_id,
    mojo::PendingReceiver<blink::mojom::StorageArea> receiver,
    ChildProcessSecurityPolicyImpl::Handle security_policy_handle,
    mojo::ReportBadMessageCallback bad_message_callback) {
  if (!IsRequestValid(StorageType::kSessionStorage, storage_key,
                      local_frame_token, std::move(security_policy_handle),
                      std::move(bad_message_callback))) {
    return;
  }
  DCHECK(session_storage_control_);
  session_storage_control_->BindStorageArea(storage_key, namespace_id,
                                            std::move(receiver));
}

bool DOMStorageContextWrapper::IsRequestValid(
    const StorageType type,
    const blink::StorageKey& storage_key,
    std::optional<blink::LocalFrameToken> local_frame_token,
    ChildProcessSecurityPolicyImpl::Handle security_policy_handle,
    mojo::ReportBadMessageCallback bad_message_callback) {
  bool host_storage_key_matched_or_missing = true;
  if (local_frame_token) {
    RenderFrameHostImpl* host = RenderFrameHostImpl::FromFrameToken(
        security_policy_handle.child_id(), *local_frame_token,
        &bad_message_callback);
    if (!host) {
      return false;
    }
    // If the storage keys did not match, but storage access has been granted
    // and the request was for a first-party storage key on the same origin as
    // the frame's storage key, we can allow the request to proceed. See:
    // third_party/blink/renderer/modules/storage_access/README.md
    host_storage_key_matched_or_missing =
        host->GetStorageKey() == storage_key ||
        (host->IsFullCookieAccessAllowed() &&
         blink::StorageKey::CreateFirstParty(host->GetStorageKey().origin()) ==
             storage_key);
  }
  if (!security_policy_handle.CanAccessDataForOrigin(storage_key.origin())) {
    const std::string type_string =
        type == StorageType::kLocalStorage ? "localStorage" : "sessionStorage";
    SYSLOG(WARNING) << "Denying illegal " << type_string
                    << " request due to ChildProcessSecurityPolicy.";
    std::move(bad_message_callback)
        .Run(base::StrCat({"Access denied for ", type_string,
                           " request due to ChildProcessSecurityPolicy."}));
    return false;
  }
  if (!host_storage_key_matched_or_missing) {
    // Ideally we would kill the renderer here, but it's possible this is the
    // result of a race condition between committing the new document and
    // binding the DOM Storage. For now, we'll just fail to bind.
    return false;
  }
  return true;
}

void DOMStorageContextWrapper::OnSessionStorageDisconnected() {
  DCHECK(partition_);
  MaybeBindSessionStorageControl(/*clear_on_open=*/false);

  // Make sure the service is aware of namespaces we asked a previous instance
  // to create, so it can properly service renderers trying to manipulate those
  // namespaces.
  base::AutoLock lock(alive_namespaces_lock_);
  for (const auto& entry : alive_namespaces_)
    session_storage_control_->CreateNamespace(entry.first);
  session_storage_control_->ScavengeUnusedNamespaces();

  partition_->ResetSessionStorageConnections();
}

void DOMStorageContextWrapper::MaybeBindSessionStorageControl(
    bool clear_on_open) {
  if (!partition_)
    return;
  session_storage_control_.reset();
  partition_->GetStorageService()->BindSessionStorageControl(
      GetSessionStoragePath(partition_), clear_on_open,
      session_storage_control_.BindNewPipeAndPassReceiver());
  session_storage_control_.set_disconnect_handler(
      base::BindOnce(&DOMStorageContextWrapper::OnSessionStorageDisconnected,
                     base::Unretained(this)));
}

void DOMStorageContextWrapper::OnLocalStorageDisconnected() {
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)
  if (local_storage_rebind_sealed_for_wasm_profile_test_) {
    return;
  }
#endif
  DCHECK(partition_);

  MaybeBindLocalStorageControl();
  partition_->ResetLocalStorageConnections();
}

#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)
void DOMStorageContextWrapper::BindWasmLocalStorageTestApi(
    mojo::PendingReceiver<storage::mojom::WasmLocalStorageTestApi> receiver) {
  if (!partition_ || local_storage_rebind_sealed_for_wasm_profile_test_) {
    return;
  }

  // StorageService deliberately exposes test APIs through an untyped pipe so
  // production StorageService does not depend on a source-selected interface.
  partition_->GetStorageService()->BindTestApi(receiver.PassPipe());
}

bool DOMStorageContextWrapper::
    ResetLocalStorageConnectionsForWasmProfileTest() {
  if (!partition_ || local_storage_rebind_sealed_for_wasm_profile_test_) {
    return false;
  }

  // Use StoragePartition's existing renderer broadcast rather than touching
  // a LocalStorage implementation directly. Blink's process-global
  // StorageController owns the cached renderer StorageArea and turns this
  // reset request into its real Mojo disconnect.
  partition_->ResetLocalStorageConnections();
  return true;
}

bool DOMStorageContextWrapper::SealLocalStorageForWasmProfileTest() {
  if (!partition_ || local_storage_rebind_sealed_for_wasm_profile_test_) {
    return false;
  }

  // Set the seal before closing the remote. A peer disconnect can otherwise
  // run OnLocalStorageDisconnected() and immediately bind a replacement
  // LocalStorageImpl while the test waits for the old instance's close fence.
  local_storage_rebind_sealed_for_wasm_profile_test_ = true;
  const bool had_control = local_storage_control_.is_bound();
  local_storage_control_.reset();
  return had_control;
}
#endif

void DOMStorageContextWrapper::MaybeBindLocalStorageControl() {
  if (!partition_) {
    return;
  }
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)
  if (local_storage_rebind_sealed_for_wasm_profile_test_) {
    return;
  }
#endif
  local_storage_control_.reset();
  partition_->GetStorageService()->BindLocalStorageControl(
      GetLocalStoragePath(partition_),
      local_storage_control_.BindNewPipeAndPassReceiver());
  local_storage_control_.set_disconnect_handler(
      base::BindOnce(&DOMStorageContextWrapper::OnLocalStorageDisconnected,
                     base::Unretained(this)));
}

scoped_refptr<SessionStorageNamespaceImpl>
DOMStorageContextWrapper::MaybeGetExistingNamespace(
    const std::string& namespace_id) const {
  base::AutoLock lock(alive_namespaces_lock_);
  auto it = alive_namespaces_.find(namespace_id);
  return (it != alive_namespaces_.end()) ? it->second.get() : nullptr;
}

void DOMStorageContextWrapper::AddNamespace(
    const std::string& namespace_id,
    SessionStorageNamespaceImpl* session_namespace) {
  base::AutoLock lock(alive_namespaces_lock_);
  DCHECK(!alive_namespaces_.contains(namespace_id));
  alive_namespaces_[namespace_id] = session_namespace;
}

void DOMStorageContextWrapper::RemoveNamespace(
    const std::string& namespace_id) {
  base::AutoLock lock(alive_namespaces_lock_);
  DCHECK(alive_namespaces_.contains(namespace_id));
  alive_namespaces_.erase(namespace_id);
}

void DOMStorageContextWrapper::PurgeMemory(PurgeOption purge_option) {
  if (!local_storage_control_) {
    // Shutdown was called.
    return;
  }

  if (purge_option == PURGE_AGGRESSIVE) {
    DCHECK(session_storage_control_);
    session_storage_control_->PurgeMemory();
    local_storage_control_->PurgeMemory();
  }
}

void DOMStorageContextWrapper::OnStartupUsageRetrieved(
    std::vector<storage::mojom::StorageUsageInfoPtr> usage) {
  if (!storage_policy_observer_)
    return;

  std::vector<url::Origin> origins;
  for (const auto& info : usage) {
    origins.emplace_back(std::move(info->storage_key.origin()));
  }
  storage_policy_observer_->StartTrackingOrigins(std::move(origins));
}

void DOMStorageContextWrapper::ApplyPolicyUpdates(
    std::vector<storage::mojom::StoragePolicyUpdatePtr> policy_updates) {
  if (!local_storage_control_)
    return;

  if (!policy_updates.empty())
    local_storage_control_->ApplyPolicyUpdates(std::move(policy_updates));
}

}  // namespace content
