// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_indexed_db_smoke.h"

#include <algorithm>
#include <cstdio>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "base/check.h"
#include "base/command_line.h"
#include "base/functional/bind.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "base/no_destructor.h"
#include "base/strings/string_number_conversions.h"
#include "base/strings/stringprintf.h"
#include "base/time/time.h"
#include "base/timer/timer.h"
#include "build/build_config.h"
#include "chrome/browser/wasm/wasm_profile_indexed_db_close_receipt_lifetime.h"
#include "components/services/storage/privileged/mojom/indexed_db_control.mojom.h"
#include "components/services/storage/privileged/mojom/indexed_db_internals_types.mojom.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/navigation_controller.h"
#include "content/public/browser/navigation_entry.h"
#include "content/public/browser/navigation_handle.h"
#include "content/public/browser/render_frame_host.h"
#include "content/public/browser/storage_partition.h"
#include "content/public/browser/storage_partition_config.h"
#include "content/public/browser/web_contents.h"
#include "content/public/browser/web_contents_observer.h"
#include "crypto/hash.h"
#include "third_party/blink/public/common/storage_key/storage_key.h"
#include "url/gurl.h"
#include "url/origin.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_profile_indexed_db_smoke.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kSmokeSwitch[] = "wasm-profile-indexed-db-smoke";
constexpr char kTokenASwitch[] = "wasm-profile-indexed-db-token-a";
constexpr char kTokenBSwitch[] = "wasm-profile-indexed-db-token-b";
constexpr char kRendererWriteMode[] = "renderer-write";
constexpr char kRendererVerifyAWriteBMode[] = "renderer-verify-a-write-b";
constexpr char kRendererVerifyBMode[] = "renderer-verify-b";
constexpr size_t kOpaqueTokenLength = 64;
constexpr base::TimeDelta kRendererOperationTimeout = base::Seconds(10);

constexpr char kRendererIndexedDBPageURL[] = "chrome://m7-indexed-db/";
constexpr char16_t kRendererWriteTitle[] = u"m7-indexed-db-renderer-write-ok";
constexpr char16_t kRendererVerifyAWriteBTitle[] =
    u"m7-indexed-db-renderer-verify-a-write-b-ok";
constexpr char16_t kRendererVerifyBTitle[] =
    u"m7-indexed-db-renderer-verify-b-ok";
constexpr char16_t kRendererFailureTitle[] = u"m7-indexed-db-failed";
// Keep these values exactly aligned with WasmContentBrowserClient's
// source-selected child-partition configuration. They are part of the
// browser-side assertion that this renderer page did not fall back to the
// normal in-memory default StoragePartition.
constexpr char kIndexedDBPartitionDomain[] = "wasmindexeddb";
constexpr char kIndexedDBPartitionName[] = "indexeddb";
constexpr char kMarkerPrefix[] = "CHROMIUM_WASM_M7_INDEXED_DB:";

using SmokeMode = WasmProfileIndexedDBSmokeInput::Mode;

bool IsOpaqueToken(std::string_view token) {
  return token.size() == kOpaqueTokenLength &&
         std::ranges::all_of(token, [](char c) {
           return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
         });
}

const char* FailureStageName(WasmProfileIndexedDBSmokeFailureStage stage) {
  switch (stage) {
    case WasmProfileIndexedDBSmokeFailureStage::kArguments:
      return "arguments";
    case WasmProfileIndexedDBSmokeFailureStage::kCapability:
      return "capability";
    case WasmProfileIndexedDBSmokeFailureStage::kStorage:
      return "storage";
    case WasmProfileIndexedDBSmokeFailureStage::kProfile:
      return "profile";
    case WasmProfileIndexedDBSmokeFailureStage::kRead:
      return "read";
    case WasmProfileIndexedDBSmokeFailureStage::kCommit:
      return "commit";
    case WasmProfileIndexedDBSmokeFailureStage::kClose:
      return "close";
    case WasmProfileIndexedDBSmokeFailureStage::kFence:
      return "fence";
    case WasmProfileIndexedDBSmokeFailureStage::kLifecycle:
      return "lifecycle";
    case WasmProfileIndexedDBSmokeFailureStage::kContent:
      return "content";
    case WasmProfileIndexedDBSmokeFailureStage::kDrain:
      return "drain";
  }
  return "drain";
}

class WasmProfileIndexedDBProtocolState {
 public:
  bool EnableFromCommandLine() {
    if (configured_) {
      return enabled_;
    }
    configured_ = true;

    const base::CommandLine* command_line =
        base::CommandLine::ForCurrentProcess();
    if (!command_line->HasSwitch(kSmokeSwitch)) {
      ReportFailure(WasmProfileIndexedDBSmokeFailureStage::kArguments);
      return false;
    }

    const std::string mode = command_line->GetSwitchValueASCII(kSmokeSwitch);
    const bool has_token_a = command_line->HasSwitch(kTokenASwitch);
    const bool has_token_b = command_line->HasSwitch(kTokenBSwitch);
    if (mode == kRendererWriteMode && has_token_a && !has_token_b) {
      input_.mode = SmokeMode::kRendererWrite;
      input_.token_a = command_line->GetSwitchValueASCII(kTokenASwitch);
      if (!IsOpaqueToken(input_.token_a)) {
        ReportFailure(WasmProfileIndexedDBSmokeFailureStage::kArguments);
        return false;
      }
    } else if (mode == kRendererVerifyAWriteBMode && has_token_a &&
               has_token_b) {
      input_.mode = SmokeMode::kRendererVerifyAWriteB;
      input_.token_a = command_line->GetSwitchValueASCII(kTokenASwitch);
      input_.token_b = command_line->GetSwitchValueASCII(kTokenBSwitch);
      if (!IsOpaqueToken(input_.token_a) || !IsOpaqueToken(input_.token_b) ||
          input_.token_a == input_.token_b) {
        ReportFailure(WasmProfileIndexedDBSmokeFailureStage::kArguments);
        return false;
      }
    } else if (mode == kRendererVerifyBMode && !has_token_a && has_token_b) {
      input_.mode = SmokeMode::kRendererVerifyB;
      input_.token_b = command_line->GetSwitchValueASCII(kTokenBSwitch);
      if (!IsOpaqueToken(input_.token_b)) {
        ReportFailure(WasmProfileIndexedDBSmokeFailureStage::kArguments);
        return false;
      }
    } else {
      ReportFailure(WasmProfileIndexedDBSmokeFailureStage::kArguments);
      return false;
    }

    if (!input_.token_a.empty()) {
      input_.token_a_digest =
          base::HexEncodeLower(crypto::hash::Sha256(input_.token_a));
    }
    if (!input_.token_b.empty()) {
      input_.token_b_digest =
          base::HexEncodeLower(crypto::hash::Sha256(input_.token_b));
    }
    enabled_ = true;
    return true;
  }

  bool enabled() const { return enabled_; }
  SmokeMode mode() const { return enabled_ ? input_.mode : SmokeMode::kNone; }

  std::optional<WasmProfileIndexedDBSmokeInput> TakeInput() {
    if (!enabled_ || input_taken_ || input_.mode == SmokeMode::kNone) {
      ReportFailure(WasmProfileIndexedDBSmokeFailureStage::kArguments);
      return std::nullopt;
    }
    input_taken_ = true;
    // Retain the redacted digests in the protocol state. The participant owns
    // and clears the raw tokens, while the later fence/lifecycle callbacks
    // still need the digest for their fixed receipt marker.
    WasmProfileIndexedDBSmokeInput result;
    result.mode = input_.mode;
    result.token_a = std::move(input_.token_a);
    result.token_b = std::move(input_.token_b);
    input_.token_a.clear();
    input_.token_b.clear();
    result.token_a_digest = input_.token_a_digest;
    result.token_b_digest = input_.token_b_digest;
    return result;
  }

  void RecordCloseResult(bool success) {
    if (!success) {
      ReportFailure(WasmProfileIndexedDBSmokeFailureStage::kClose);
      return;
    }
    close_succeeded_ = true;
  }

  bool succeeded() const { return close_succeeded_ && !failure_reported_; }

  void NotifyFenceResult(bool success) {
    if (!enabled_ || failure_reported_) {
      return;
    }
    if (!success || !close_succeeded_ || fence_succeeded_) {
      ReportFailure(WasmProfileIndexedDBSmokeFailureStage::kFence);
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
      ReportFailure(WasmProfileIndexedDBSmokeFailureStage::kLifecycle);
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
      ReportFailure(WasmProfileIndexedDBSmokeFailureStage::kDrain);
      return;
    }
    lease_released_ = true;
    EmitMarker("LEASE_RELEASED");
  }

  void ReportFailure(WasmProfileIndexedDBSmokeFailureStage stage) {
    if (failure_reported_) {
      return;
    }
    failure_reported_ = true;
    input_.token_a.clear();
    input_.token_b.clear();
    std::fprintf(stderr, "%sFAIL stage=%s\n", kMarkerPrefix,
                 FailureStageName(stage));
    std::fflush(stderr);
  }

  void EmitMarker(const char* marker) {
    std::fprintf(stderr, "%s%s\n", kMarkerPrefix, marker);
    std::fflush(stderr);
  }

  void EmitDigestMarker(const char* marker) {
    const std::string& digest = ActiveDigest();
    std::fprintf(stderr, "%s%s sha256=%s\n", kMarkerPrefix, marker,
                 digest.c_str());
    std::fflush(stderr);
  }

 private:
  const std::string& ActiveDigest() const {
    return input_.mode == SmokeMode::kRendererWrite ? input_.token_a_digest
                                                     : input_.token_b_digest;
  }

  bool configured_ = false;
  bool enabled_ = false;
  bool input_taken_ = false;
  bool close_succeeded_ = false;
  bool fence_succeeded_ = false;
  bool storage_lifecycle_succeeded_ = false;
  bool lease_released_ = false;
  bool failure_reported_ = false;
  WasmProfileIndexedDBSmokeInput input_;
};

WasmProfileIndexedDBProtocolState& GetWasmProfileIndexedDBProtocolState() {
  static base::NoDestructor<WasmProfileIndexedDBProtocolState> state;
  return *state;
}

}  // namespace

class WasmProfileIndexedDBLifetimeParticipant::State final
    : public content::WebContentsObserver {
 public:
  State(content::BrowserContext* browser_context,
        base::FilePath profile_path,
        WasmProfileIndexedDBSmokeInput input,
        WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold,
        base::OnceClosure quarantine_callback)
      : mode_(input.mode),
        browser_context_(browser_context),
        close_receipt_lifetime_(std::move(profile_io_hold),
                                std::move(quarantine_callback)),
        token_a_(std::move(input.token_a)),
        token_b_(std::move(input.token_b)),
        token_a_digest_(std::move(input.token_a_digest)),
        token_b_digest_(std::move(input.token_b_digest)),
        profile_path_(std::move(profile_path)) {}

  ~State() override = default;

  bool Start(base::OnceCallback<void(bool)> completion) {
    if (close_receipt_lifetime_.IsActive() ||
        close_receipt_lifetime_.HasCompleted()) {
      return false;
    }
    if (!browser_context_ || profile_path_.empty() || !completion ||
        !IsValidMode()) {
      GetWasmProfileIndexedDBProtocolState().ReportFailure(
          WasmProfileIndexedDBSmokeFailureStage::kProfile);
      CleanupProfileBoundResources();
      (void)close_receipt_lifetime_.RejectBeforeStart();
      return false;
    }
    if (!close_receipt_lifetime_.Start(std::move(completion))) {
      return false;
    }

    renderer_browser_context_ = browser_context_;
    content::WebContents::CreateParams create_params(browser_context_);
    renderer_web_contents_ = content::WebContents::Create(create_params);
    if (!renderer_web_contents_) {
      ReportFailure(WasmProfileIndexedDBSmokeFailureStage::kContent);
      return true;
    }
    Observe(renderer_web_contents_.get());
    renderer_page_url_ = BuildRendererPageURL();
    if (!renderer_page_url_.is_valid()) {
      ReportFailure(WasmProfileIndexedDBSmokeFailureStage::kContent);
      return true;
    }

    EmitMarker("READY");
    renderer_operation_timeout_.Start(
        FROM_HERE, kRendererOperationTimeout,
        base::BindOnce(&State::OnRendererOperationTimeout,
                       weak_ptr_factory_.GetWeakPtr()));
    content::NavigationController::LoadURLParams load_params(
        renderer_page_url_);
    renderer_web_contents_->GetController().LoadURLWithParams(load_params);
    return true;
  }

  void Cancel() {
    close_receipt_lifetime_.Cancel();
    if (close_receipt_lifetime_.IsActive() &&
        !close_receipt_lifetime_.HasSelectedBucketCloseReceipt()) {
      ReportFailure(WasmProfileIndexedDBSmokeFailureStage::kClose);
    }
  }

  bool IsActive() const { return close_receipt_lifetime_.IsActive(); }
  bool DidSucceed() const { return close_receipt_lifetime_.DidSucceed(); }
  bool HasOutstandingAdmission() const {
    return close_receipt_lifetime_.HasOutstandingAdmission();
  }

  void PrepareForOwnerQuarantine() {
    close_receipt_lifetime_.Cancel();
    if (IsActive() &&
        !close_receipt_lifetime_.HasSelectedBucketCloseReceipt()) {
      ReportFailure(WasmProfileIndexedDBSmokeFailureStage::kClose);
      return;
    }
    CleanupProfileBoundResources();
  }

 private:
  bool IsValidMode() const {
    switch (mode_) {
      case SmokeMode::kRendererWrite:
        return IsOpaqueToken(token_a_) && token_b_.empty() &&
               token_a_digest_.size() == kOpaqueTokenLength;
      case SmokeMode::kRendererVerifyAWriteB:
        return IsOpaqueToken(token_a_) && IsOpaqueToken(token_b_) &&
               token_a_ != token_b_ &&
               token_a_digest_.size() == kOpaqueTokenLength &&
               token_b_digest_.size() == kOpaqueTokenLength;
      case SmokeMode::kRendererVerifyB:
        return token_a_.empty() && IsOpaqueToken(token_b_) &&
               token_b_digest_.size() == kOpaqueTokenLength;
      case SmokeMode::kNone:
        return false;
    }
    return false;
  }

  GURL BuildRendererPageURL() const {
    switch (mode_) {
      case SmokeMode::kRendererWrite:
        return GURL(base::StringPrintf("%s?mode=%s&token-a=%s",
                                       kRendererIndexedDBPageURL,
                                       kRendererWriteMode, token_a_.c_str()));
      case SmokeMode::kRendererVerifyAWriteB:
        return GURL(base::StringPrintf("%s?mode=%s&token-a=%s&token-b=%s",
                                       kRendererIndexedDBPageURL,
                                       kRendererVerifyAWriteBMode,
                                       token_a_.c_str(), token_b_.c_str()));
      case SmokeMode::kRendererVerifyB:
        return GURL(base::StringPrintf("%s?mode=%s&token-b=%s",
                                       kRendererIndexedDBPageURL,
                                       kRendererVerifyBMode, token_b_.c_str()));
      case SmokeMode::kNone:
        return GURL();
    }
    return GURL();
  }

  bool IsRendererExpectedTitle(const std::u16string& title) const {
    return (mode_ == SmokeMode::kRendererWrite &&
            title == kRendererWriteTitle) ||
           (mode_ == SmokeMode::kRendererVerifyAWriteB &&
            title == kRendererVerifyAWriteBTitle) ||
           (mode_ == SmokeMode::kRendererVerifyB &&
            title == kRendererVerifyBTitle);
  }

  const std::string& ActiveDigest() const {
    return mode_ == SmokeMode::kRendererWrite ? token_a_digest_
                                               : token_b_digest_;
  }

  void CleanupProfileBoundResources() {
    if (profile_bound_cleanup_completed_) {
      return;
    }
    profile_bound_cleanup_completed_ = true;
    operation_finished_ = true;
    weak_ptr_factory_.InvalidateWeakPtrs();
    Observe(nullptr);
    renderer_operation_timeout_.Stop();
    renderer_web_contents_.reset();
    renderer_browser_context_ = nullptr;
    renderer_storage_partition_ = nullptr;
    renderer_page_url_ = GURL();
    browser_context_ = nullptr;
    profile_path_.clear();
    storage_key_.reset();
    token_a_.clear();
    token_b_.clear();
  }

  void ReportFailure(WasmProfileIndexedDBSmokeFailureStage stage) {
    if (failure_reported_) {
      return;
    }
    failure_reported_ = true;
    GetWasmProfileIndexedDBProtocolState().ReportFailure(stage);
    close_receipt_lifetime_.FailBeforeSelectedBucketCloseReceipt(base::BindOnce(
        &State::CleanupProfileBoundResources, base::Unretained(this)));
  }

  void EmitMarker(const char* marker) {
    std::fprintf(stderr, "%s%s\n", kMarkerPrefix, marker);
    std::fflush(stderr);
  }

  void EmitDigestMarker(const char* marker, const std::string& digest) {
    std::fprintf(stderr, "%s%s sha256=%s\n", kMarkerPrefix, marker,
                 digest.c_str());
    std::fflush(stderr);
  }

  // content::WebContentsObserver:
  void TitleWasSet(content::NavigationEntry* entry) override {
    if (failure_reported_ || !renderer_web_contents_ ||
        web_contents() != renderer_web_contents_.get() || !entry ||
        entry->GetURL() != renderer_page_url_) {
      return;
    }
    MaybeCompleteRendererPage();
  }

  void DidFinishNavigation(
      content::NavigationHandle* navigation_handle) override {
    if (failure_reported_ || !navigation_handle ||
        !navigation_handle->IsInPrimaryMainFrame() ||
        navigation_handle->GetURL() != renderer_page_url_) {
      return;
    }
    if (!navigation_handle->HasCommitted() ||
        navigation_handle->IsErrorPage()) {
      ReportFailure(WasmProfileIndexedDBSmokeFailureStage::kContent);
      return;
    }
    renderer_primary_commit_seen_ = true;
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
      ReportFailure(WasmProfileIndexedDBSmokeFailureStage::kContent);
      return;
    }
    if (!IsRendererExpectedTitle(title)) {
      return;
    }
    renderer_page_completed_ = true;
    if (!ValidateRendererStorageBoundary()) {
      ReportFailure(WasmProfileIndexedDBSmokeFailureStage::kProfile);
      return;
    }

    if (mode_ == SmokeMode::kRendererWrite) {
      EmitDigestMarker("RENDERER_WRITE_OK", token_a_digest_);
    } else if (mode_ == SmokeMode::kRendererVerifyAWriteB) {
      EmitDigestMarker("RENDERER_REOPEN_READ_A_OK", token_a_digest_);
      EmitDigestMarker("RENDERER_WRITE_B_OK", token_b_digest_);
    } else if (mode_ == SmokeMode::kRendererVerifyB) {
      EmitDigestMarker("RENDERER_REOPEN_READ_B_OK", token_b_digest_);
    } else {
      ReportFailure(WasmProfileIndexedDBSmokeFailureStage::kProfile);
      return;
    }
    RequestSelectedBucketDetails();
  }

  void OnRendererOperationTimeout() {
    if (!failure_reported_ && !operation_finished_) {
      ReportFailure(renderer_page_completed_
                        ? WasmProfileIndexedDBSmokeFailureStage::kClose
                        : WasmProfileIndexedDBSmokeFailureStage::kContent);
    }
  }

  bool ValidateRendererStorageBoundary() {
    if (!renderer_browser_context_ || !renderer_web_contents_ ||
        !renderer_primary_commit_seen_ ||
        renderer_web_contents_->GetBrowserContext() !=
            renderer_browser_context_ ||
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
            url::Origin::Create(GURL(kRendererIndexedDBPageURL)));
    if (actual_storage_key.origin().opaque() ||
        actual_storage_key.top_level_site().opaque() ||
        actual_storage_key != expected_storage_key) {
      return false;
    }

    content::StoragePartition* const actual_partition =
        render_frame_host->GetStoragePartition();
    const content::StoragePartitionConfig expected_config =
        content::StoragePartitionConfig::Create(
            renderer_browser_context_, kIndexedDBPartitionDomain,
            kIndexedDBPartitionName, /*in_memory=*/false);
    if (!actual_partition || expected_config.in_memory() ||
        actual_partition ==
            renderer_browser_context_->GetDefaultStoragePartition() ||
        renderer_browser_context_->GetStoragePartition(expected_config,
                                                        /*can_create=*/false) !=
            actual_partition ||
        actual_partition->GetPath().empty() ||
        !profile_path_.IsParent(actual_partition->GetPath())) {
      return false;
    }

    renderer_storage_partition_ = actual_partition;
    storage_key_ = actual_storage_key;
    return true;
  }

  void RequestSelectedBucketDetails() {
    if (failure_reported_ || !renderer_storage_partition_ || !storage_key_) {
      ReportFailure(WasmProfileIndexedDBSmokeFailureStage::kStorage);
      return;
    }
    renderer_storage_partition_->GetIndexedDBControl().GetAllBucketsDetails(
        base::BindOnce(&State::OnSelectedBucketDetails,
                       weak_ptr_factory_.GetWeakPtr()));
  }

  void OnSelectedBucketDetails(
      bool incognito,
      std::vector<storage::mojom::IdbOriginMetadataPtr> origin_list) {
    if (failure_reported_ || incognito || !renderer_storage_partition_ ||
        !storage_key_) {
      ReportFailure(WasmProfileIndexedDBSmokeFailureStage::kStorage);
      return;
    }

    std::optional<storage::BucketId> selected_bucket_id;
    for (const storage::mojom::IdbOriginMetadataPtr& origin : origin_list) {
      if (!origin) {
        continue;
      }
      for (const storage::mojom::IdbStorageKeyMetadataPtr& storage_key :
           origin->storage_keys) {
        if (!storage_key) {
          continue;
        }
        for (const storage::mojom::IdbBucketMetadataPtr& bucket :
             storage_key->buckets) {
          if (!bucket || bucket->bucket_locator.storage_key != *storage_key_ ||
              !bucket->bucket_locator.is_default) {
            continue;
          }
          const bool paths_are_partition_bound = std::ranges::all_of(
              bucket->paths, [this](const base::FilePath& path) {
                return !path.empty() &&
                       renderer_storage_partition_->GetPath().IsParent(path);
              });
          if (selected_bucket_id || bucket->paths.empty() ||
              !paths_are_partition_bound || bucket->clients.empty() ||
              bucket->connection_count != 0) {
            ReportFailure(WasmProfileIndexedDBSmokeFailureStage::kStorage);
            return;
          }
          selected_bucket_id = bucket->bucket_locator.id;
        }
      }
    }

    if (!selected_bucket_id) {
      ReportFailure(WasmProfileIndexedDBSmokeFailureStage::kStorage);
      return;
    }

    // The nonempty client list proves this is still the live BucketContext
    // bound by the renderer page. ForceClose(false) therefore executes that
    // selected context's ResetBackingStore path rather than a no-op lookup.
    renderer_storage_partition_->GetIndexedDBControl().ForceClose(
        *selected_bucket_id,
        base::BindOnce(&State::OnSelectedBucketForceClosed,
                       weak_ptr_factory_.GetWeakPtr()));
  }

  void OnSelectedBucketForceClosed() {
    if (failure_reported_ || !renderer_storage_partition_ ||
        !renderer_web_contents_ || !storage_key_) {
      ReportFailure(WasmProfileIndexedDBSmokeFailureStage::kClose);
      return;
    }
    EmitDigestMarker("BACKING_STORES_CLOSED", ActiveDigest());
    close_receipt_lifetime_.CompleteAfterSelectedBucketCloseReceipt(
        base::BindOnce(&State::CleanupProfileBoundResources,
                       base::Unretained(this)));
  }

  bool operation_finished_ = false;
  bool failure_reported_ = false;
  bool profile_bound_cleanup_completed_ = false;
  bool renderer_primary_commit_seen_ = false;
  bool renderer_page_completed_ = false;
  SmokeMode mode_ = SmokeMode::kNone;
  raw_ptr<content::BrowserContext> browser_context_ = nullptr;
  WasmProfileIndexedDBCloseReceiptLifetime close_receipt_lifetime_;
  std::string token_a_;
  std::string token_b_;
  std::string token_a_digest_;
  std::string token_b_digest_;
  base::FilePath profile_path_;
  std::optional<blink::StorageKey> storage_key_;
  raw_ptr<content::BrowserContext> renderer_browser_context_ = nullptr;
  raw_ptr<content::StoragePartition> renderer_storage_partition_ = nullptr;
  std::unique_ptr<content::WebContents> renderer_web_contents_;
  GURL renderer_page_url_;
  base::OneShotTimer renderer_operation_timeout_;
  base::WeakPtrFactory<State> weak_ptr_factory_{this};
};

WasmProfileIndexedDBLifetimeParticipant::
    WasmProfileIndexedDBLifetimeParticipant(
        content::BrowserContext* browser_context,
        base::FilePath profile_path,
        WasmProfileIndexedDBSmokeInput input,
        WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold) {
  state_ = std::make_unique<State>(
      browser_context, std::move(profile_path), std::move(input),
      std::move(profile_io_hold),
      base::BindOnce(
          &WasmProfileIndexedDBLifetimeParticipant::
              OnOperationRequiresQuarantine,
          weak_ptr_factory_.GetWeakPtr()));
}

WasmProfileIndexedDBLifetimeParticipant::
    ~WasmProfileIndexedDBLifetimeParticipant() {
  (void)QuarantineForFailureShutdown();
}

bool WasmProfileIndexedDBLifetimeParticipant::Start(
    base::OnceCallback<void(bool)> completion) {
  return state_ && state_->Start(std::move(completion));
}

void WasmProfileIndexedDBLifetimeParticipant::Cancel() {
  if (state_) {
    state_->Cancel();
  }
}

bool WasmProfileIndexedDBLifetimeParticipant::QuarantineForFailureShutdown() {
  if (!state_ || !state_->HasOutstandingAdmission()) {
    return true;
  }
  state_->PrepareForOwnerQuarantine();
  RetainQuarantinedState(std::move(state_));
  return true;
}

bool WasmProfileIndexedDBLifetimeParticipant::IsActive() const {
  return state_ && state_->IsActive();
}

bool WasmProfileIndexedDBLifetimeParticipant::DidSucceed() const {
  return state_ && state_->DidSucceed();
}

void WasmProfileIndexedDBLifetimeParticipant::OnOperationRequiresQuarantine() {
  if (!state_ || !state_->IsActive()) {
    return;
  }
  RetainQuarantinedState(std::move(state_));
}

void WasmProfileIndexedDBLifetimeParticipant::RetainQuarantinedState(
    std::unique_ptr<State> state) {
  static base::NoDestructor<std::vector<std::unique_ptr<State>>>
      quarantined_states;
  quarantined_states->push_back(std::move(state));
}

bool HasWasmProfileIndexedDBSmokeArguments() {
  const base::CommandLine* command_line =
      base::CommandLine::ForCurrentProcess();
  return command_line->HasSwitch(kSmokeSwitch) ||
         command_line->HasSwitch(kTokenASwitch) ||
         command_line->HasSwitch(kTokenBSwitch);
}

bool EnableWasmProfileIndexedDBSmokeTestMode() {
  return GetWasmProfileIndexedDBProtocolState().EnableFromCommandLine();
}

bool IsWasmProfileIndexedDBSmokeEnabled() {
  return GetWasmProfileIndexedDBProtocolState().enabled();
}

WasmProfileIndexedDBSmokeInput::Mode GetWasmProfileIndexedDBSmokeMode() {
  return GetWasmProfileIndexedDBProtocolState().mode();
}

std::optional<WasmProfileIndexedDBSmokeInput>
TakeWasmProfileIndexedDBSmokeInput() {
  return GetWasmProfileIndexedDBProtocolState().TakeInput();
}

bool DidWasmProfileIndexedDBSmokeSucceed() {
  return GetWasmProfileIndexedDBProtocolState().succeeded();
}

void NotifyWasmProfileIndexedDBSmokeOperationResult(bool success) {
  GetWasmProfileIndexedDBProtocolState().RecordCloseResult(success);
}

void NotifyWasmProfileIndexedDBSmokeFenceResult(bool success) {
  GetWasmProfileIndexedDBProtocolState().NotifyFenceResult(success);
}

void NotifyWasmProfileIndexedDBSmokeStorageLifecycle(bool success) {
  GetWasmProfileIndexedDBProtocolState().NotifyStorageLifecycle(success);
}

void NotifyWasmProfileIndexedDBSmokeBackendDrain(bool success) {
  GetWasmProfileIndexedDBProtocolState().NotifyBackendDrain(success);
}

void ReportWasmProfileIndexedDBSmokeFailure(
    WasmProfileIndexedDBSmokeFailureStage stage) {
  GetWasmProfileIndexedDBProtocolState().ReportFailure(stage);
}

}  // namespace chrome
