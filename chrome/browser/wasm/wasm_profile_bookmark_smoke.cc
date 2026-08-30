// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_bookmark_smoke.h"

#include <cstdio>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "base/check.h"
#include "base/feature_list.h"
#include "base/functional/bind.h"
#include "base/no_destructor.h"
#include "base/strings/strcat.h"
#include "base/strings/utf_string_conversions.h"
#include "base/task/bind_post_task.h"
#include "base/task/sequenced_task_runner.h"
#include "build/build_config.h"
#include "components/bookmarks/browser/bookmark_client.h"
#include "components/bookmarks/browser/bookmark_model.h"
#include "components/bookmarks/browser/bookmark_model_load_waiter.h"
#include "components/bookmarks/browser/bookmark_node.h"
#include "components/bookmarks/common/bookmark_features.h"
#include "components/signin/public/base/signin_switches.h"
#include "url/gurl.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_profile_bookmark_smoke.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kMarkerPrefix[] = "CHROMIUM_WASM_M7_PREFS:";
constexpr char kBookmarkUrlPrefix[] = "https://wasm-bookmark.test/m7/";
constexpr char kBookmarkTitlePrefix[] = "chromium-wasm-bookmark-m7-";
constexpr size_t kDigestLength = 64;

void EmitMarker(const char* marker) {
  std::fprintf(stderr, "%s%s\n", kMarkerPrefix, marker);
  std::fflush(stderr);
}

void EmitDigestMarker(const char* marker, const std::string& digest) {
  std::fprintf(stderr, "%s%s sha256=%s\n", kMarkerPrefix, marker,
               digest.c_str());
  std::fflush(stderr);
}

bool IsDigest(std::string_view value) {
  if (value.size() != kDigestLength) {
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

GURL BookmarkUrlForDigest(const std::string& digest) {
  return GURL(base::StrCat({kBookmarkUrlPrefix, digest}));
}

std::u16string BookmarkTitleForDigest(const std::string& digest) {
  return base::ASCIIToUTF16(base::StrCat({kBookmarkTitlePrefix, digest}));
}

// This source-selected client deliberately implements no managed bookmarks,
// sync metadata, undo retention, metrics timer, or encryption. The direct
// BookmarkModel witness must not admit the desktop keyed-service graph.
class WasmProfileBookmarkSmokeClient final : public bookmarks::BookmarkClient {
 public:
  WasmProfileBookmarkSmokeClient() = default;
  WasmProfileBookmarkSmokeClient(const WasmProfileBookmarkSmokeClient&) =
      delete;
  WasmProfileBookmarkSmokeClient& operator=(
      const WasmProfileBookmarkSmokeClient&) = delete;
  ~WasmProfileBookmarkSmokeClient() override = default;

  bookmarks::LoadManagedNodeCallback GetLoadManagedNodeCallback() override {
    return base::BindOnce(
        [](int64_t*) -> std::unique_ptr<bookmarks::BookmarkPermanentNode> {
          return nullptr;
        });
  }

  bool IsSyncFeatureEnabledIncludingBookmarks() override { return false; }

  bool CanSetPermanentNodeTitle(const bookmarks::BookmarkNode*) override {
    return false;
  }

  bool IsNodeManaged(const bookmarks::BookmarkNode*) override { return false; }

  bookmarks::BookmarkFormFactor GetBookmarkFormFactor() override {
    return bookmarks::BookmarkFormFactor::kDesktop;
  }

  std::string EncodeLocalOrSyncableBookmarkSyncMetadata() override {
    return std::string();
  }

  std::string EncodeAccountBookmarkSyncMetadata() override {
    return std::string();
  }

  void DecodeLocalOrSyncableBookmarkSyncMetadata(
      const std::string&,
      const base::RepeatingClosure&) override {}

  DecodeAccountBookmarkSyncMetadataResult DecodeAccountBookmarkSyncMetadata(
      const std::string&,
      const base::RepeatingClosure&) override {
    return DecodeAccountBookmarkSyncMetadataResult::kSuccess;
  }

  void OnBookmarkNodeRemovedUndoable(
      const bookmarks::BookmarkNode*,
      size_t,
      std::unique_ptr<bookmarks::BookmarkNode>) override {}

  void SchedulePersistentTimerForDailyMetrics(
      base::RepeatingClosure) override {}

  void GetEncryptor(
      base::OnceCallback<void(scoped_refptr<os_crypt_async::Encryptor>)>
          callback) override {
    std::move(callback).Run(nullptr);
  }
};

}  // namespace

class WasmProfileBookmarkLifetimeParticipant::State {
 public:
  State(base::FilePath profile_path,
        WasmProfilePreferencesBookmarkSmokeInput input,
        WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold)
      : profile_path_(std::move(profile_path)),
        input_(std::move(input)),
        profile_io_hold_(std::move(profile_io_hold)) {}
  State(const State&) = delete;
  State& operator=(const State&) = delete;
  ~State() = default;

  bool Start(base::OnceCallback<void(bool success)> completion) {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    if (started_ || completed_) {
      return false;
    }
    if (!profile_io_hold_ || !completion) {
      if (profile_io_hold_) {
        (void)profile_io_hold_->Complete(
            WasmProfileOrderedDrainLifecycle::ProfileIOCompletion::kFailed);
        profile_io_hold_.reset();
      }
      completed_ = true;
      input_ = WasmProfilePreferencesBookmarkSmokeInput();
      ReportWasmProfilePreferencesSmokeFailure(
          WasmProfilePreferencesSmokeFailureStage::kBookmark);
      return false;
    }

    started_ = true;
    // Keep shutdown cancellation non-reentrant: completing a model owner can
    // be synchronous, but BrowserMainParts must resume its state machine on a
    // later UI turn just like an asynchronous write/load receipt.
    // CompleteAfterModelClose() performs that post while retaining admission.
    completion_ = std::move(completion);
    if (!IsWasmProfilePreferencesBookmarkSmokeEnabled() ||
        profile_path_.empty() || !HasValidInput()) {
      FinishWithoutModel(/*operation_succeeded=*/false);
      return true;
    }

    // This result-bearing primitive covers exactly one clear-text local
    // Bookmarks file. Do not let an encrypted or account store turn its
    // callback into a false aggregate-close acknowledgement.
    if (base::FeatureList::IsEnabled(bookmarks::kEncryptBookmarks) ||
        bookmarks::ShouldWriteBookmarksToSecondaryFileOnDisk() ||
        bookmarks::ShouldUseEncryptedBookmarksAsPrimarySource() ||
        base::FeatureList::IsEnabled(
            switches::kSyncEnableBookmarksInTransportMode)) {
      FinishWithoutModel(/*operation_succeeded=*/false);
      return true;
    }

    model_ = std::make_unique<bookmarks::BookmarkModel>(
        std::make_unique<WasmProfileBookmarkSmokeClient>());
    model_->Load(profile_path_);
    bookmarks::ScheduleCallbackOnBookmarkModelLoad(
        *model_, base::BindOnce(&State::OnModelLoaded,
                                base::Unretained(this)));
    return true;
  }

  void Cancel() {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    if (completed_ || completion_delivery_pending_) {
      return;
    }
    failed_ = true;
    if (flush_pending_) {
      return;
    }
    if (!model_) {
      FinishWithoutModel(/*operation_succeeded=*/false);
      return;
    }
    // BookmarkModel's load waiter owns the only readiness receipt. Retain the
    // model until it fires; destroying it here would discard that receipt
    // while its CONTINUE_ON_SHUTDOWN load work can still touch the profile.
    if (!model_->loaded()) {
      return;
    }
    FailAndClose();
  }

  bool IsActive() const {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    return started_ && !completed_;
  }
  bool HasCompleted() const {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    return completed_;
  }
  bool DidSucceed() const {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    return started_ && completed_ && succeeded_;
  }

 private:
  bool HasValidInput() const {
    switch (input_.mode) {
      case WasmProfilePreferencesBookmarkSmokeInput::Mode::kWrite:
        return IsDigest(input_.token_a_digest) &&
               input_.token_b_digest.empty();
      case WasmProfilePreferencesBookmarkSmokeInput::Mode::kVerifyAndWrite:
        return IsDigest(input_.token_a_digest) &&
               IsDigest(input_.token_b_digest) &&
               input_.token_a_digest != input_.token_b_digest;
      case WasmProfilePreferencesBookmarkSmokeInput::Mode::kVerifyB:
        return input_.token_a_digest.empty() &&
               IsDigest(input_.token_b_digest);
    }
    return false;
  }

  const bookmarks::BookmarkNode* FindProbeNode(
      const std::string& digest) const {
    if (!model_) {
      return nullptr;
    }

    const GURL url = BookmarkUrlForDigest(digest);
    const std::u16string title = BookmarkTitleForDigest(digest);
    const auto nodes = model_->GetNodesByURL(url);
    for (const auto& node : nodes) {
      if (node->GetTitle() == title) {
        return node.get();
      }
    }
    return nullptr;
  }

  bool AddProbeNode(const std::string& digest) {
    if (!model_) {
      return false;
    }

    const GURL url = BookmarkUrlForDigest(digest);
    const bookmarks::BookmarkNode* bookmark = model_->AddNewURL(
        model_->bookmark_bar_node(),
        model_->bookmark_bar_node()->children().size(),
        BookmarkTitleForDigest(digest), url);
    return bookmark && FindProbeNode(digest) == bookmark;
  }

  bool RemoveProbeNode(const std::string& digest) {
    const bookmarks::BookmarkNode* bookmark = FindProbeNode(digest);
    if (!bookmark || !model_) {
      return false;
    }

    model_->Remove(bookmark, bookmarks::metrics::BookmarkEditSource::kOther,
                   FROM_HERE);
    return FindProbeNode(digest) == nullptr;
  }

  void OnModelLoaded() {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    if (completed_ || completion_delivery_pending_ || !model_ ||
        flush_pending_ || failed_) {
      FailAndClose();
      return;
    }

    switch (input_.mode) {
      case WasmProfilePreferencesBookmarkSmokeInput::Mode::kWrite:
        if (FindProbeNode(input_.token_a_digest) ||
            !AddProbeNode(input_.token_a_digest)) {
          FailAndClose();
          return;
        }
        FlushAndClose("BOOKMARK_A_WRITE_FLUSHED", input_.token_a_digest,
                      /*succeed_on_write=*/true);
        return;
      case WasmProfilePreferencesBookmarkSmokeInput::Mode::kVerifyAndWrite:
        if (!FindProbeNode(input_.token_a_digest)) {
          FailAndClose();
          return;
        }
        EmitDigestMarker("BOOKMARK_A_READ_OK", input_.token_a_digest);
        if (!RemoveProbeNode(input_.token_a_digest) ||
            FindProbeNode(input_.token_b_digest) ||
            !AddProbeNode(input_.token_b_digest)) {
          FailAndClose();
          return;
        }
        FlushAndClose("BOOKMARK_B_WRITE_FLUSHED", input_.token_b_digest,
                      /*succeed_on_write=*/true);
        return;
      case WasmProfilePreferencesBookmarkSmokeInput::Mode::kVerifyB:
        if (!FindProbeNode(input_.token_b_digest)) {
          FailAndClose();
          return;
        }
        EmitDigestMarker("BOOKMARK_B_READ_OK", input_.token_b_digest);
        if (!RemoveProbeNode(input_.token_b_digest)) {
          FailAndClose();
          return;
        }
        FlushAndClose("BOOKMARK_CLEANUP_FLUSHED", std::string(),
                      /*succeed_on_write=*/true);
        return;
    }
    FailAndClose();
  }

  void FlushAndClose(const char* marker,
                     std::string digest,
                     bool succeed_on_write) {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    if (!model_ || flush_pending_ || !model_->loaded()) {
      FailAndClose();
      return;
    }

    flush_pending_ = true;
    auto completion = base::BindPostTask(
        base::SequencedTaskRunner::GetCurrentDefault(),
        base::BindOnce(&State::OnWriteFlushed, base::Unretained(this), marker,
                       std::move(digest), succeed_on_write));
    if (!model_->FlushLocalOrSyncablePendingWriteForTesting(
            std::move(completion))) {
      flush_pending_ = false;
      CloseAndFinish(/*operation_succeeded=*/false);
    }
  }

  void OnWriteFlushed(const char* marker,
                      std::string digest,
                      bool succeed_on_write,
                      bool write_succeeded) {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    if (completed_ || completion_delivery_pending_ || !flush_pending_) {
      return;
    }
    flush_pending_ = false;
    const bool operation_succeeded =
        write_succeeded && succeed_on_write && !failed_;
    if (operation_succeeded && marker) {
      if (digest.empty()) {
        EmitMarker(marker);
      } else {
        EmitDigestMarker(marker, digest);
      }
    }
    CloseAndFinish(operation_succeeded);
  }

  void FailAndClose() {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    failed_ = true;
    if (completed_ || completion_delivery_pending_ || flush_pending_) {
      return;
    }
    if (!model_) {
      FinishWithoutModel(/*operation_succeeded=*/false);
      return;
    }
    if (!model_->loaded()) {
      return;
    }
    if (model_->LocalOrSyncableStorageHasPendingWriteForTest()) {
      // A recovery load can schedule a write before validation fails. Drain
      // it rather than destructing BookmarkStorage with a pending write, but
      // never turn that cleanup write into a successful witness result.
      FlushAndClose(/*marker=*/nullptr, std::string(),
                    /*succeed_on_write=*/false);
      return;
    }
    CloseAndFinish(/*operation_succeeded=*/false);
  }

  void CloseAndFinish(bool operation_succeeded) {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    model_.reset();
    CompleteAfterModelClose(operation_succeeded);
  }

  void FinishWithoutModel(bool operation_succeeded) {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    CHECK(!model_);
    CompleteAfterModelClose(operation_succeeded);
  }

  void CompleteAfterModelClose(bool operation_succeeded) {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    if (completed_ || completion_delivery_pending_) {
      return;
    }

    CHECK(started_);
    CHECK(!model_);
    completion_delivery_pending_ = true;
    pending_operation_succeeded_ = operation_succeeded;
    input_ = WasmProfilePreferencesBookmarkSmokeInput();
    CHECK(base::SequencedTaskRunner::GetCurrentDefault()->PostTask(
        FROM_HERE,
        base::BindOnce(&State::DeliverCompletion, base::Unretained(this))));
  }

  void DeliverCompletion() {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    CHECK(completion_delivery_pending_);
    CHECK(!completed_);
    CHECK(!model_);

    bool profile_io_completed = false;
    if (profile_io_hold_) {
      profile_io_completed = profile_io_hold_->Complete(
          pending_operation_succeeded_
              ? WasmProfileOrderedDrainLifecycle::ProfileIOCompletion::
                    kSucceeded
              : WasmProfileOrderedDrainLifecycle::ProfileIOCompletion::
                    kFailed);
      profile_io_hold_.reset();
    }
    completion_delivery_pending_ = false;
    completed_ = true;
    succeeded_ = pending_operation_succeeded_ && profile_io_completed;
    if (!succeeded_) {
      ReportWasmProfilePreferencesSmokeFailure(
          WasmProfilePreferencesSmokeFailureStage::kBookmark);
    }
    CHECK(completion_);
    base::OnceCallback<void(bool success)> completion = std::move(completion_);
    const bool succeeded = succeeded_;
    // The callback may synchronously destroy this quarantined or profile-owned
    // state. Do not access any member after handing control back to its owner.
    std::move(completion).Run(succeeded);
  }

  bool started_ = false;
  bool failed_ = false;
  bool completed_ = false;
  bool succeeded_ = false;
  bool flush_pending_ = false;
  bool completion_delivery_pending_ = false;
  bool pending_operation_succeeded_ = false;
  base::FilePath profile_path_;
  WasmProfilePreferencesBookmarkSmokeInput input_;
  std::optional<WasmProfileOrderedDrainLifecycle::ProfileIOHold>
      profile_io_hold_;
  std::unique_ptr<bookmarks::BookmarkModel> model_;
  base::OnceCallback<void(bool success)> completion_;
  SEQUENCE_CHECKER(sequence_checker_);
};

WasmProfileBookmarkLifetimeParticipant::
    WasmProfileBookmarkLifetimeParticipant(
        base::FilePath profile_path,
        WasmProfilePreferencesBookmarkSmokeInput input,
        WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold)
    : state_(std::make_unique<State>(std::move(profile_path), std::move(input),
                                     std::move(profile_io_hold))) {}

WasmProfileBookmarkLifetimeParticipant::
    ~WasmProfileBookmarkLifetimeParticipant() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  (void)QuarantineForFailureShutdown();
}

bool WasmProfileBookmarkLifetimeParticipant::Start(
    base::OnceCallback<void(bool success)> completion) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return state_ && state_->Start(std::move(completion));
}

void WasmProfileBookmarkLifetimeParticipant::Cancel() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (state_) {
    state_->Cancel();
  }
}

bool WasmProfileBookmarkLifetimeParticipant::QuarantineForFailureShutdown() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (!state_ || !state_->IsActive()) {
    return true;
  }

  state_->Cancel();
  if (!state_->IsActive()) {
    return true;
  }

  static base::NoDestructor<std::vector<std::unique_ptr<State>>>
      quarantined_states;
  quarantined_states->push_back(std::move(state_));
  return true;
}

bool WasmProfileBookmarkLifetimeParticipant::IsActive() const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return state_ && state_->IsActive();
}

bool WasmProfileBookmarkLifetimeParticipant::HasCompleted() const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return state_ && state_->HasCompleted();
}

bool WasmProfileBookmarkLifetimeParticipant::DidSucceed() const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return state_ && state_->DidSucceed();
}

}  // namespace chrome
