// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_local_storage_smoke.h"

#include <algorithm>
#include <cstdio>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "base/command_line.h"
#include "base/check.h"
#include "base/functional/bind.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "base/no_destructor.h"
#include "base/strings/string_number_conversions.h"
#include "build/build_config.h"
#include "components/services/storage/public/mojom/local_storage_control.mojom.h"
#include "components/services/storage/public/mojom/wasm_local_storage_test_api.mojom.h"
#include "content/public/browser/dom_storage_context.h"
#include "content/public/browser/storage_partition.h"
#include "content/public/browser/wasm_dom_storage_test_support.h"
#include "crypto/hash.h"
#include "mojo/public/cpp/bindings/remote.h"
#include "third_party/blink/public/common/storage_key/storage_key.h"
#include "third_party/blink/public/mojom/dom_storage/storage_area.mojom.h"
#include "url/gurl.h"
#include "url/origin.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_profile_local_storage_smoke.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kSmokeSwitch[] = "wasm-profile-local-storage-smoke";
constexpr char kTokenSwitch[] = "wasm-profile-local-storage-token";
constexpr char kWriteMode[] = "write";
constexpr char kVerifyMode[] = "verify";
constexpr size_t kOpaqueTokenLength = 64;

constexpr char kStorageOrigin[] = "https://m7-local-storage.test";
constexpr char kTokenKey[] = "m7-profile-local-storage-token-v1";
constexpr char kCloseFenceKey[] = "m7-profile-local-storage-close-fence-v1";
constexpr char kMarkerPrefix[] = "CHROMIUM_WASM_M7_LOCAL_STORAGE:";

enum class SmokeMode {
  kNone,
  kWrite,
  kVerify,
};

std::vector<uint8_t> ToBytes(std::string_view value) {
  return std::vector<uint8_t>(value.begin(), value.end());
}

class WasmProfileLocalStorageSmokeState {
 public:
  WasmProfileLocalStorageSmokeState() = default;
  WasmProfileLocalStorageSmokeState(const WasmProfileLocalStorageSmokeState&) =
      delete;
  WasmProfileLocalStorageSmokeState& operator=(
      const WasmProfileLocalStorageSmokeState&) = delete;
  ~WasmProfileLocalStorageSmokeState() = default;

  bool EnableFromCommandLine() {
    if (configured_) {
      return enabled_;
    }
    configured_ = true;

    const base::CommandLine* command_line =
        base::CommandLine::ForCurrentProcess();
    const bool has_mode = command_line->HasSwitch(kSmokeSwitch);
    const bool has_token = command_line->HasSwitch(kTokenSwitch);
    if (!has_mode || !has_token) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kArguments);
      return false;
    }

    const std::string mode = command_line->GetSwitchValueASCII(kSmokeSwitch);
    token_ = command_line->GetSwitchValueASCII(kTokenSwitch);
    if (!IsOpaqueToken(token_)) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kArguments);
      return false;
    }
    if (mode == kWriteMode) {
      mode_ = SmokeMode::kWrite;
    } else if (mode == kVerifyMode) {
      mode_ = SmokeMode::kVerify;
    } else {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kArguments);
      return false;
    }

    token_digest_ = base::HexEncodeLower(crypto::hash::Sha256(token_));
    token_bytes_ = ToBytes(token_);
    enabled_ = true;
    return true;
  }

  bool enabled() const { return enabled_; }

  bool Start(content::StoragePartition* storage_partition,
             const base::FilePath& profile_path,
             base::OnceClosure completion) {
    if (!enabled_ || started_ || !storage_partition || profile_path.empty() ||
        !completion) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kProfile);
      return false;
    }
    started_ = true;
    completion_ = std::move(completion);
    profile_path_ = profile_path;
    dom_storage_context_ = storage_partition->GetDOMStorageContext();
    if (!dom_storage_context_) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kStorage);
      return false;
    }

    if (!content::BindWasmLocalStorageTestApi(
            dom_storage_context_,
            test_api_.BindNewPipeAndPassReceiver())) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kCapability);
      return false;
    }
    test_api_.set_disconnect_handler(base::BindOnce(
        &WasmProfileLocalStorageSmokeState::OnTestApiDisconnected,
        weak_ptr_factory_.GetWeakPtr()));

    storage::mojom::LocalStorageControl* local_storage_control =
        storage_partition->GetLocalStorageControl();
    if (!local_storage_control) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kStorage);
      return false;
    }

    storage_key_ = blink::StorageKey::CreateFirstParty(
        url::Origin::Create(GURL(kStorageOrigin)));
    local_storage_control->BindStorageArea(
        *storage_key_, storage_area_.BindNewPipeAndPassReceiver());
    storage_area_.set_disconnect_handler(base::BindOnce(
        &WasmProfileLocalStorageSmokeState::OnStorageAreaDisconnected,
        weak_ptr_factory_.GetWeakPtr()));

    EmitMarker("READY");
    if (mode_ == SmokeMode::kWrite) {
      PutTokenForWrite();
    } else if (mode_ == SmokeMode::kVerify) {
      ReadTokenForVerify();
    } else {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kProfile);
      return false;
    }
    return true;
  }

  bool succeeded() const { return close_succeeded_ && !failure_reported_; }

  void NotifyFenceResult(bool success) {
    if (!enabled_ || failure_reported_) {
      return;
    }
    if (!success || !close_succeeded_ || fence_succeeded_) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kFence);
      return;
    }
    fence_succeeded_ = true;
    EmitDigestMarker("FENCE_OK");
  }

  void NotifyStorageLifecycle(bool success) {
    if (!enabled_ || failure_reported_) {
      return;
    }
    if (!success || !close_succeeded_ || !fence_succeeded_ ||
        storage_lifecycle_succeeded_) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kLifecycle);
      return;
    }
    storage_lifecycle_succeeded_ = true;
  }

  void NotifyBackendDrain(bool success) {
    if (!enabled_ || failure_reported_) {
      return;
    }
    if (!success || !close_succeeded_ || !fence_succeeded_ ||
        !storage_lifecycle_succeeded_ || lease_released_) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kDrain);
      return;
    }
    lease_released_ = true;
    EmitMarker("LEASE_RELEASED");
  }

  void ReportFailure(WasmProfileLocalStorageSmokeFailureStage stage) {
    if (failure_reported_) {
      return;
    }
    failure_reported_ = true;
    close_succeeded_ = false;
    ClearRawToken();
    std::fprintf(stderr, "%sFAIL stage=%s\n", kMarkerPrefix,
                 FailureStageName(stage));
    std::fflush(stderr);
    FinishOperation();
  }

 private:
  static bool IsOpaqueToken(std::string_view value) {
    if (value.size() != kOpaqueTokenLength) {
      return false;
    }
    for (const char character : value) {
      if (!((character >= '0' && character <= '9') ||
            (character >= 'a' && character <= 'f'))) {
        return false;
      }
    }
    return true;
  }

  static const char* FailureStageName(
      WasmProfileLocalStorageSmokeFailureStage stage) {
    switch (stage) {
      case WasmProfileLocalStorageSmokeFailureStage::kArguments:
        return "arguments";
      case WasmProfileLocalStorageSmokeFailureStage::kCapability:
        return "capability";
      case WasmProfileLocalStorageSmokeFailureStage::kStorage:
        return "storage";
      case WasmProfileLocalStorageSmokeFailureStage::kProfile:
        return "profile";
      case WasmProfileLocalStorageSmokeFailureStage::kRead:
        return "read";
      case WasmProfileLocalStorageSmokeFailureStage::kCommit:
        return "commit";
      case WasmProfileLocalStorageSmokeFailureStage::kClose:
        return "close";
      case WasmProfileLocalStorageSmokeFailureStage::kFence:
        return "fence";
      case WasmProfileLocalStorageSmokeFailureStage::kLifecycle:
        return "lifecycle";
      case WasmProfileLocalStorageSmokeFailureStage::kContent:
        return "content";
      case WasmProfileLocalStorageSmokeFailureStage::kDrain:
        return "drain";
    }
    return "drain";
  }

  void PutTokenForWrite() {
    DCHECK(storage_area_.is_bound());
    storage_area_->Put(
        ToBytes(kTokenKey), token_bytes_, /*client_old_value=*/std::nullopt,
        /*source=*/nullptr,
        base::BindOnce(&WasmProfileLocalStorageSmokeState::OnTokenWritten,
                       weak_ptr_factory_.GetWeakPtr()));
  }

  void ReadTokenForVerify() {
    DCHECK(storage_area_.is_bound());
    storage_area_->GetAll(
        /*new_observer=*/mojo::NullRemote(),
        base::BindOnce(&WasmProfileLocalStorageSmokeState::OnTokenRead,
                       weak_ptr_factory_.GetWeakPtr()));
  }

  void OnTokenWritten(bool success) {
    if (failure_reported_ || mode_ != SmokeMode::kWrite || !success) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kStorage);
      return;
    }
    EmitDigestMarker("WRITE_ACCEPTED");
    // Prepare must admit the pending UpdateMaps work while our sole
    // StorageArea is still bound. Releasing it first schedules a separate
    // immediate commit that may make the snapshot correctly report no pending
    // map update.
    PrepareCloseFence();
  }

  void OnTokenRead(std::vector<blink::mojom::KeyValuePtr> values) {
    if (failure_reported_ || mode_ != SmokeMode::kVerify) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kRead);
      return;
    }
    const std::vector<uint8_t> token_key = ToBytes(kTokenKey);
    const auto found = std::find_if(
        values.begin(), values.end(), [&token_key](const auto& key_value) {
          return key_value && key_value->key == token_key;
        });
    if (found == values.end() || (*found)->value != token_bytes_) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kRead);
      return;
    }
    EmitDigestMarker("REOPEN_READ_OK");

    // A same-value Put would intentionally be a no-op in StorageAreaImpl and
    // could not satisfy the immediate UpdateMaps snapshot contract. Mutate a
    // distinct test-only key in this same StorageArea instead. Its value is
    // opaque and unique to the run, and it is never emitted outside Chromium.
    storage_area_->Put(
        ToBytes(kCloseFenceKey), token_bytes_, /*client_old_value=*/std::nullopt,
        /*source=*/nullptr,
        base::BindOnce(&WasmProfileLocalStorageSmokeState::OnCloseFenceWritten,
                       weak_ptr_factory_.GetWeakPtr()));
  }

  void OnCloseFenceWritten(bool success) {
    if (failure_reported_ || mode_ != SmokeMode::kVerify || !success) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kStorage);
      return;
    }
    PrepareCloseFence();
  }

  void PrepareCloseFence() {
    if (failure_reported_ || !storage_area_ || !test_api_ || !storage_key_) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kCommit);
      return;
    }
    test_api_->PrepareCommitCloseFence(
        profile_path_, *storage_key_,
        base::BindOnce(&WasmProfileLocalStorageSmokeState::OnCloseFencePrepared,
                       weak_ptr_factory_.GetWeakPtr()));
  }

  void OnCloseFencePrepared(
      storage::mojom::WasmLocalStorageTestResult result) {
    if (failure_reported_ ||
        result != storage::mojom::WasmLocalStorageTestResult::kSuccess) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kCommit);
      return;
    }
    EmitDigestMarker("ON_DISK_COMMIT_OK");

    ReleaseAreaThenArmCloseFence();
  }

  void ReleaseAreaThenArmCloseFence() {
    if (failure_reported_ || !storage_area_ || !test_api_) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kClose);
      return;
    }

    // LocalStorageImpl records the area's binding transition on its receiver
    // disconnect. Arm is deliberately a result-bearing wait rather than a
    // one-shot state probe, so it safely covers the independent StorageArea
    // and test-API Mojo-pipe ordering after this reset.
    storage_area_.reset();
    test_api_->ArmCommitCloseFence(
        base::BindOnce(&WasmProfileLocalStorageSmokeState::OnCloseFenceArmed,
                       weak_ptr_factory_.GetWeakPtr()));
  }

  void OnCloseFenceArmed(
      storage::mojom::WasmLocalStorageTestResult result) {
    if (failure_reported_ ||
        result != storage::mojom::WasmLocalStorageTestResult::kSuccess) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kClose);
      return;
    }

    // The no-live-area arm receipt now exists. Seal and reset the sole
    // LocalStorageControl before asking for the final owner-destruction/FIFO
    // receipt; the content bridge suppresses a replacement instance first.
    if (!content::SealWasmLocalStorageForTest(dom_storage_context_)) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kClose);
      return;
    }
    test_api_->WaitForCloseFence(
        base::BindOnce(&WasmProfileLocalStorageSmokeState::OnCloseFenceReady,
                       weak_ptr_factory_.GetWeakPtr()));
  }

  void OnCloseFenceReady(storage::mojom::WasmLocalStorageTestResult result) {
    if (failure_reported_ ||
        result != storage::mojom::WasmLocalStorageTestResult::kSuccess) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kClose);
      return;
    }
    close_succeeded_ = true;
    EmitDigestMarker("DB_CLOSE_OK");
    FinishOperation();
  }

  void OnStorageAreaDisconnected() {
    if (!failure_reported_ && storage_area_) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kStorage);
    }
  }

  void OnTestApiDisconnected() {
    if (!failure_reported_ && !close_succeeded_) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kCapability);
    }
  }

  void FinishOperation() {
    if (operation_finished_) {
      return;
    }
    operation_finished_ = true;
    storage_area_.reset();
    test_api_.reset();
    dom_storage_context_ = nullptr;
    profile_path_.clear();
    storage_key_.reset();
    ClearRawToken();
    if (completion_) {
      std::move(completion_).Run();
    }
  }

  void ClearRawToken() {
    token_.clear();
    token_bytes_.clear();
  }

  void EmitMarker(const char* marker) {
    std::fprintf(stderr, "%s%s\n", kMarkerPrefix, marker);
    std::fflush(stderr);
  }

  void EmitDigestMarker(const char* marker) {
    std::fprintf(stderr, "%s%s sha256=%s\n", kMarkerPrefix, marker,
                 token_digest_.c_str());
    std::fflush(stderr);
  }

  bool configured_ = false;
  bool enabled_ = false;
  bool started_ = false;
  bool operation_finished_ = false;
  bool close_succeeded_ = false;
  bool fence_succeeded_ = false;
  bool storage_lifecycle_succeeded_ = false;
  bool lease_released_ = false;
  bool failure_reported_ = false;
  SmokeMode mode_ = SmokeMode::kNone;
  std::string token_;
  std::string token_digest_;
  std::vector<uint8_t> token_bytes_;
  base::FilePath profile_path_;
  std::optional<blink::StorageKey> storage_key_;
  raw_ptr<content::DOMStorageContext> dom_storage_context_ = nullptr;
  mojo::Remote<blink::mojom::StorageArea> storage_area_;
  mojo::Remote<storage::mojom::WasmLocalStorageTestApi> test_api_;
  base::OnceClosure completion_;
  base::WeakPtrFactory<WasmProfileLocalStorageSmokeState> weak_ptr_factory_{
      this};
};

WasmProfileLocalStorageSmokeState& GetWasmProfileLocalStorageSmokeState() {
  static base::NoDestructor<WasmProfileLocalStorageSmokeState> state;
  return *state;
}

}  // namespace

bool HasWasmProfileLocalStorageSmokeArguments() {
  const base::CommandLine* command_line = base::CommandLine::ForCurrentProcess();
  return command_line->HasSwitch(kSmokeSwitch) ||
         command_line->HasSwitch(kTokenSwitch);
}

bool EnableWasmProfileLocalStorageSmokeTestMode() {
  return GetWasmProfileLocalStorageSmokeState().EnableFromCommandLine();
}

bool IsWasmProfileLocalStorageSmokeEnabled() {
  return GetWasmProfileLocalStorageSmokeState().enabled();
}

bool StartWasmProfileLocalStorageSmoke(
    content::StoragePartition* storage_partition,
    const base::FilePath& profile_path,
    base::OnceClosure completion) {
  return GetWasmProfileLocalStorageSmokeState().Start(
      storage_partition, profile_path, std::move(completion));
}

bool DidWasmProfileLocalStorageSmokeSucceed() {
  return GetWasmProfileLocalStorageSmokeState().succeeded();
}

void NotifyWasmProfileLocalStorageSmokeFenceResult(bool success) {
  GetWasmProfileLocalStorageSmokeState().NotifyFenceResult(success);
}

void NotifyWasmProfileLocalStorageSmokeStorageLifecycle(bool success) {
  GetWasmProfileLocalStorageSmokeState().NotifyStorageLifecycle(success);
}

void NotifyWasmProfileLocalStorageSmokeBackendDrain(bool success) {
  GetWasmProfileLocalStorageSmokeState().NotifyBackendDrain(success);
}

void ReportWasmProfileLocalStorageSmokeFailure(
    WasmProfileLocalStorageSmokeFailureStage stage) {
  GetWasmProfileLocalStorageSmokeState().ReportFailure(stage);
}

}  // namespace chrome
