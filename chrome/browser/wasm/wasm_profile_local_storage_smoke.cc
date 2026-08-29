// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_local_storage_smoke.h"

#include <algorithm>
#include <cstdio>
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)
#include <memory>
#endif
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "base/auto_reset.h"
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

#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)
#include "base/strings/stringprintf.h"
#include "base/task/sequenced_task_runner.h"
#include "base/time/time.h"
#include "base/timer/timer.h"
#include "chrome/browser/wasm/wasm_profile.h"
#include "content/public/browser/navigation_controller.h"
#include "content/public/browser/navigation_entry.h"
#include "content/public/browser/navigation_handle.h"
#include "content/public/browser/render_frame_host.h"
#include "content/public/browser/web_contents.h"
#include "content/public/browser/web_contents_observer.h"
#endif

#if !BUILDFLAG(IS_WASM)
#error "wasm_profile_local_storage_smoke.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kSmokeSwitch[] = "wasm-profile-local-storage-smoke";
constexpr char kTokenSwitch[] = "wasm-profile-local-storage-token";
constexpr char kWriteMode[] = "write";
constexpr char kVerifyMode[] = "verify";
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)
constexpr char kRendererWriteMode[] = "renderer-write";
constexpr char kRendererVerifyMode[] = "renderer-verify";
constexpr base::TimeDelta kRendererOperationTimeout = base::Seconds(10);
#endif
constexpr size_t kOpaqueTokenLength = 64;

constexpr char kStorageOrigin[] = "https://m7-local-storage.test";
constexpr char kTokenKey[] = "m7-profile-local-storage-token-v1";
constexpr char kCloseFenceKey[] = "m7-profile-local-storage-close-fence-v1";
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)
constexpr char kRendererLocalStoragePageURL[] =
    "chrome://m7-local-storage/";
constexpr char16_t kRendererWriteTitle[] =
    u"m7-local-storage-renderer-write-ok";
constexpr char16_t kRendererVerifyTitle[] =
    u"m7-local-storage-renderer-verify-ok";
constexpr char16_t kRendererFailureTitle[] = u"m7-local-storage-failed";
#endif
constexpr char kMarkerPrefix[] = "CHROMIUM_WASM_M7_LOCAL_STORAGE:";

enum class SmokeMode {
  kNone,
  kWrite,
  kVerify,
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)
  kRendererWrite,
  kRendererVerify,
#endif
};

std::vector<uint8_t> ToBytes(std::string_view value) {
  return std::vector<uint8_t>(value.begin(), value.end());
}

class WasmProfileLocalStorageSmokeState final
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)
    : public content::WebContentsObserver
#endif
{
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
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)
    } else if (mode == kRendererWriteMode) {
      mode_ = SmokeMode::kRendererWrite;
    } else if (mode == kRendererVerifyMode) {
      mode_ = SmokeMode::kRendererVerify;
#endif
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
  bool renderer_enabled() const {
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)
    return mode_ == SmokeMode::kRendererWrite ||
           mode_ == SmokeMode::kRendererVerify;
#else
    return false;
#endif
  }

  bool Start(content::StoragePartition* storage_partition,
             const base::FilePath& profile_path,
             base::OnceClosure completion) {
    if (!enabled_ || started_ || !storage_partition || profile_path.empty() ||
        !completion || renderer_enabled()) {
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

  bool StartRenderer(WasmProfile* profile, base::OnceClosure completion) {
#if !defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)
    static_cast<void>(profile);
    static_cast<void>(completion);
    ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kProfile);
    return false;
#else
    if (!enabled_ || started_ || !renderer_enabled() || !profile ||
        profile->GetPath().empty() || !completion) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kProfile);
      return false;
    }

    content::StoragePartition* const storage_partition =
        profile->GetDefaultStoragePartition();
    if (!storage_partition) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kStorage);
      return false;
    }

    started_ = true;
    renderer_primary_commit_seen_ = false;
    renderer_page_completed_ = false;
    completion_ = std::move(completion);
    profile_path_ = profile->GetPath();
    renderer_profile_ = profile;
    renderer_storage_partition_ = storage_partition;
    dom_storage_context_ = storage_partition->GetDOMStorageContext();
    if (!dom_storage_context_) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kStorage);
      return false;
    }
    if (!content::BindWasmLocalStorageTestApi(
            dom_storage_context_, test_api_.BindNewPipeAndPassReceiver())) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kCapability);
      return false;
    }
    test_api_.set_disconnect_handler(base::BindOnce(
        &WasmProfileLocalStorageSmokeState::OnTestApiDisconnected,
        weak_ptr_factory_.GetWeakPtr()));

    content::WebContents::CreateParams create_params(profile);
    renderer_web_contents_ = content::WebContents::Create(create_params);
    if (!renderer_web_contents_) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kContent);
      return false;
    }
    Observe(renderer_web_contents_.get());

    const char* const mode = mode_ == SmokeMode::kRendererWrite
                                 ? kRendererWriteMode
                                 : kRendererVerifyMode;
    renderer_page_url_ = GURL(base::StringPrintf(
        "%s?mode=%s&token=%s", kRendererLocalStoragePageURL, mode,
        token_.c_str()));
    if (!renderer_page_url_.is_valid()) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kContent);
      return false;
    }

    EmitMarker("READY");
    renderer_operation_timeout_.Start(
        FROM_HERE, kRendererOperationTimeout,
        base::BindOnce(
            &WasmProfileLocalStorageSmokeState::OnRendererOperationTimeout,
            weak_ptr_factory_.GetWeakPtr()));
    content::NavigationController::LoadURLParams load_params(
        renderer_page_url_);
    renderer_web_contents_->GetController().LoadURLWithParams(load_params);
    return true;
#endif
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
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)
    if (renderer_observer_callback_active_) {
      // WebContents can continue notifying its observers after a title or
      // navigation callback returns. Do not destroy the observed object from
      // within that callback; defer its teardown to the next UI task.
      base::SequencedTaskRunner::GetCurrentDefault()->PostTask(
          FROM_HERE,
          base::BindOnce(&WasmProfileLocalStorageSmokeState::FinishOperation,
                         weak_ptr_factory_.GetWeakPtr()));
      return;
    }
#endif
    FinishOperation();
  }

 private:
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)
  bool IsRendererExpectedTitle(const std::u16string& title) const {
    return (mode_ == SmokeMode::kRendererWrite &&
            title == kRendererWriteTitle) ||
           (mode_ == SmokeMode::kRendererVerify &&
            title == kRendererVerifyTitle);
  }

  const char* RendererSuccessMarker() const {
    return mode_ == SmokeMode::kRendererWrite ? "RENDERER_WRITE_OK"
                                               : "RENDERER_REOPEN_READ_OK";
  }

  static bool IsRetryableRendererPrepareResult(
      storage::mojom::WasmLocalStorageTestResult result) {
    return result ==
               storage::mojom::WasmLocalStorageTestResult::kStorageNotFound ||
           result == storage::mojom::WasmLocalStorageTestResult::
                         kStorageAreaNotBound ||
           result ==
               storage::mojom::WasmLocalStorageTestResult::kDatabaseNotReady ||
           result == storage::mojom::WasmLocalStorageTestResult::
                         kSnapshotConnectionNotReady ||
           result == storage::mojom::WasmLocalStorageTestResult::
                         kSnapshotNotCommitted;
  }
#endif

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

#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)
  // content::WebContentsObserver:
  void TitleWasSet(content::NavigationEntry* entry) override {
    base::AutoReset<bool> observer_callback(
        &renderer_observer_callback_active_, true);
    if (failure_reported_ || !renderer_enabled() ||
        !renderer_web_contents_ ||
        web_contents() != renderer_web_contents_.get() || !entry ||
        entry->GetURL() != renderer_page_url_) {
      return;
    }
    MaybeCompleteRendererPage();
  }

  void DidFinishNavigation(
      content::NavigationHandle* navigation_handle) override {
    base::AutoReset<bool> observer_callback(
        &renderer_observer_callback_active_, true);
    if (failure_reported_ || !renderer_enabled() || !navigation_handle ||
        !navigation_handle->IsInPrimaryMainFrame() ||
        navigation_handle->GetURL() != renderer_page_url_) {
      return;
    }
    if (!navigation_handle->HasCommitted() ||
        navigation_handle->IsErrorPage()) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kContent);
      return;
    }
    renderer_primary_commit_seen_ = true;
    // TitleWasSet can precede this commit callback. Sample the current title
    // after the exact primary commit as well, so the external renderer script
    // cannot be lost to that observer ordering.
    MaybeCompleteRendererPage();
  }

  void MaybeCompleteRendererPage() {
    if (failure_reported_ || renderer_page_completed_ ||
        !renderer_primary_commit_seen_ || !renderer_web_contents_ ||
        renderer_web_contents_->GetLastCommittedURL() != renderer_page_url_) {
      return;
    }
    const std::u16string title = renderer_web_contents_->GetTitle();
    if (title == kRendererFailureTitle) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kContent);
      return;
    }
    if (!IsRendererExpectedTitle(title)) {
      return;
    }
    renderer_page_completed_ = true;
    if (!ValidateRendererStorageBoundary()) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kProfile);
      return;
    }
    EmitDigestMarker(RendererSuccessMarker());
    PrepareRendererCloseFence();
  }

  void OnRendererOperationTimeout() {
    if (!failure_reported_ && !operation_finished_) {
      ReportFailure(renderer_page_completed_
                        ? WasmProfileLocalStorageSmokeFailureStage::kClose
                        : WasmProfileLocalStorageSmokeFailureStage::kContent);
    }
  }

  bool ValidateRendererStorageBoundary() {
    if (!renderer_profile_ || !renderer_storage_partition_ ||
        !renderer_web_contents_ || !renderer_primary_commit_seen_ ||
        renderer_web_contents_->GetBrowserContext() != renderer_profile_ ||
        renderer_profile_->GetDefaultStoragePartition() !=
            renderer_storage_partition_ ||
        renderer_web_contents_->GetBrowserContext()
                ->GetDefaultStoragePartition() !=
            renderer_storage_partition_ ||
        renderer_web_contents_->GetLastCommittedURL() != renderer_page_url_) {
      return false;
    }
    content::RenderFrameHost* const render_frame_host =
        renderer_web_contents_->GetPrimaryMainFrame();
    if (!render_frame_host || !render_frame_host->IsRenderFrameLive() ||
        render_frame_host->GetLastCommittedURL() != renderer_page_url_) {
      return false;
    }
    const blink::StorageKey actual_storage_key =
        render_frame_host->GetStorageKey();
    const blink::StorageKey expected_storage_key =
        blink::StorageKey::CreateFirstParty(
            url::Origin::Create(GURL(kRendererLocalStoragePageURL)));
    if (actual_storage_key.origin().opaque() ||
        actual_storage_key.top_level_site().opaque() ||
        actual_storage_key != expected_storage_key) {
      return false;
    }
    storage_key_ = actual_storage_key;
    return true;
  }

  void PrepareRendererCloseFence() {
    if (failure_reported_ || !renderer_web_contents_ || !test_api_ ||
        !storage_key_) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kCommit);
      return;
    }
    test_api_->PrepareCommitCloseFence(
        profile_path_, *storage_key_,
        base::BindOnce(
            &WasmProfileLocalStorageSmokeState::OnRendererCloseFencePrepared,
            weak_ptr_factory_.GetWeakPtr()));
  }

  void OnRendererCloseFencePrepared(
      storage::mojom::WasmLocalStorageTestResult result) {
    if (failure_reported_) {
      return;
    }
    if (result == storage::mojom::WasmLocalStorageTestResult::kSuccess) {
      EmitDigestMarker("ON_DISK_COMMIT_OK");
      DestroyRendererWebContentsThenArmCloseFence();
      return;
    }
    // Title assignment follows renderer-side localStorage.setItem(), but the
    // renderer Mojo message can arrive later on a cold storage connection.
    // Retain the real page while it converges. A successful snapshot remains
    // the authoritative disk receipt.
    if (IsRetryableRendererPrepareResult(result) &&
        renderer_operation_timeout_.IsRunning()) {
      base::SequencedTaskRunner::GetCurrentDefault()->PostDelayedTask(
          FROM_HERE,
          base::BindOnce(
              &WasmProfileLocalStorageSmokeState::PrepareRendererCloseFence,
              weak_ptr_factory_.GetWeakPtr()),
          base::Milliseconds(10));
      return;
    }
    ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kCommit);
  }
#endif

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

#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)
  void DestroyRendererWebContentsThenArmCloseFence() {
    if (failure_reported_ || !renderer_web_contents_ || !test_api_) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kClose);
      return;
    }

    // The only renderer-owned StorageArea belongs to this WebContents. Detach
    // before destruction so no observer destruction callback can become a
    // second lifecycle signal. Blink's process-global StorageController can
    // retain a CachedStorageArea after the LocalDOMWindow is gone, so use
    // StoragePartition's real reset broadcast to make that renderer-owned
    // remote disconnect. Arm remains the result-bearing wait for its final
    // cross-pipe unbind; do not shut the renderer down first, because that
    // would race delivery of the reset request.
    Observe(nullptr);
    renderer_web_contents_.reset();
    if (!content::ResetWasmLocalStorageConnectionsForTest(
            dom_storage_context_)) {
      ReportFailure(WasmProfileLocalStorageSmokeFailureStage::kClose);
      return;
    }
    renderer_profile_ = nullptr;
    renderer_storage_partition_ = nullptr;
    renderer_page_url_ = GURL();
    test_api_->ArmCommitCloseFence(
        base::BindOnce(&WasmProfileLocalStorageSmokeState::OnCloseFenceArmed,
                       weak_ptr_factory_.GetWeakPtr()));
  }
#endif

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
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)
    // Failure can arrive before the renderer-owned close path. Do not depend
    // on WebContentsDestroyed: detach first and make its destruction local.
    Observe(nullptr);
    renderer_operation_timeout_.Stop();
    renderer_web_contents_.reset();
    renderer_profile_ = nullptr;
    renderer_storage_partition_ = nullptr;
    renderer_page_url_ = GURL();
#endif
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
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)
  bool renderer_observer_callback_active_ = false;
  bool renderer_primary_commit_seen_ = false;
  bool renderer_page_completed_ = false;
#endif
  SmokeMode mode_ = SmokeMode::kNone;
  std::string token_;
  std::string token_digest_;
  std::vector<uint8_t> token_bytes_;
  base::FilePath profile_path_;
  std::optional<blink::StorageKey> storage_key_;
  raw_ptr<content::DOMStorageContext> dom_storage_context_ = nullptr;
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)
  raw_ptr<WasmProfile> renderer_profile_ = nullptr;
  raw_ptr<content::StoragePartition> renderer_storage_partition_ = nullptr;
  std::unique_ptr<content::WebContents> renderer_web_contents_;
  GURL renderer_page_url_;
  base::OneShotTimer renderer_operation_timeout_;
#endif
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

bool IsWasmProfileRendererLocalStorageSmokeEnabled() {
  return GetWasmProfileLocalStorageSmokeState().renderer_enabled();
}

bool StartWasmProfileLocalStorageSmoke(
    content::StoragePartition* storage_partition,
    const base::FilePath& profile_path,
    base::OnceClosure completion) {
  return GetWasmProfileLocalStorageSmokeState().Start(
      storage_partition, profile_path, std::move(completion));
}

bool StartWasmProfileRendererLocalStorageSmoke(WasmProfile* profile,
                                               base::OnceClosure completion) {
  return GetWasmProfileLocalStorageSmokeState().StartRenderer(
      profile, std::move(completion));
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
