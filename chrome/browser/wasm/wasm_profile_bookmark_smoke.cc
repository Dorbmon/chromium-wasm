// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_bookmark_smoke.h"

#include <cstdio>
#include <memory>
#include <string>
#include <string_view>
#include <utility>

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

  bool CanSetPermanentNodeTitle(
      const bookmarks::BookmarkNode*) override {
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

  DecodeAccountBookmarkSyncMetadataResult
  DecodeAccountBookmarkSyncMetadata(
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

  void GetEncryptor(base::OnceCallback<void(
                        scoped_refptr<os_crypt_async::Encryptor>)> callback)
      override {
    std::move(callback).Run(nullptr);
  }
};

class WasmProfileBookmarkSmokeState {
 public:
  WasmProfileBookmarkSmokeState() = default;
  WasmProfileBookmarkSmokeState(const WasmProfileBookmarkSmokeState&) =
      delete;
  WasmProfileBookmarkSmokeState& operator=(
      const WasmProfileBookmarkSmokeState&) = delete;
  ~WasmProfileBookmarkSmokeState() = default;

  bool Start(base::FilePath profile_path,
             WasmProfilePreferencesBookmarkSmokeInput input,
             base::OnceCallback<void(bool success)> completion) {
    if (!IsWasmProfilePreferencesBookmarkSmokeEnabled() || started_ ||
        profile_path.empty() || completion.is_null() || !HasValidInput(input)) {
      return false;
    }

    started_ = true;
    input_ = std::move(input);
    completion_ = std::move(completion);

    // This result-bearing primitive covers exactly one clear-text local
    // Bookmarks file. Do not let an encrypted or account store turn its
    // callback into a false aggregate-close acknowledgement.
    if (base::FeatureList::IsEnabled(bookmarks::kEncryptBookmarks) ||
        bookmarks::ShouldWriteBookmarksToSecondaryFileOnDisk() ||
        bookmarks::ShouldUseEncryptedBookmarksAsPrimarySource() ||
        base::FeatureList::IsEnabled(
            switches::kSyncEnableBookmarksInTransportMode)) {
      FinishWithoutModel(false);
      return true;
    }

    model_ = std::make_unique<bookmarks::BookmarkModel>(
        std::make_unique<WasmProfileBookmarkSmokeClient>());
    model_->Load(profile_path);
    bookmarks::ScheduleCallbackOnBookmarkModelLoad(
        *model_, base::BindOnce(&WasmProfileBookmarkSmokeState::OnModelLoaded,
                                base::Unretained(this)));
    return true;
  }

  bool DidSucceed() const { return started_ && completed_ && succeeded_; }

 private:
  static bool HasValidInput(
      const WasmProfilePreferencesBookmarkSmokeInput& input) {
    switch (input.mode) {
      case WasmProfilePreferencesBookmarkSmokeInput::Mode::kWrite:
        return IsDigest(input.token_a_digest) && input.token_b_digest.empty();
      case WasmProfilePreferencesBookmarkSmokeInput::Mode::kVerifyAndWrite:
        return IsDigest(input.token_a_digest) &&
               IsDigest(input.token_b_digest) &&
               input.token_a_digest != input.token_b_digest;
      case WasmProfilePreferencesBookmarkSmokeInput::Mode::kVerifyB:
        return input.token_a_digest.empty() && IsDigest(input.token_b_digest);
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
    if (completed_ || !model_ || flush_pending_) {
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
    if (!model_ || flush_pending_) {
      FailAndClose();
      return;
    }

    flush_pending_ = true;
    auto completion = base::BindPostTask(
        base::SequencedTaskRunner::GetCurrentDefault(),
        base::BindOnce(&WasmProfileBookmarkSmokeState::OnWriteFlushed,
                       base::Unretained(this), marker, std::move(digest),
                       succeed_on_write));
    if (!model_->FlushLocalOrSyncablePendingWriteForTesting(
            std::move(completion))) {
      flush_pending_ = false;
      CloseAndFinish(false);
    }
  }

  void OnWriteFlushed(const char* marker,
                      std::string digest,
                      bool succeed_on_write,
                      bool write_succeeded) {
    if (completed_ || !flush_pending_) {
      return;
    }
    flush_pending_ = false;
    if (write_succeeded && marker) {
      if (digest.empty()) {
        EmitMarker(marker);
      } else {
        EmitDigestMarker(marker, digest);
      }
    }
    CloseAndFinish(write_succeeded && succeed_on_write);
  }

  void FailAndClose() {
    if (completed_ || flush_pending_) {
      return;
    }
    if (model_ && model_->LocalOrSyncableStorageHasPendingWriteForTest()) {
      // A recovery load can schedule a write before validation fails. Drain
      // it rather than destructing BookmarkStorage with a pending write, but
      // never turn that cleanup write into a successful witness result.
      FlushAndClose(/*marker=*/nullptr, std::string(),
                    /*succeed_on_write=*/false);
      return;
    }
    CloseAndFinish(false);
  }

  void CloseAndFinish(bool success) {
    if (model_) {
      model_.reset();
    }
    FinishWithoutModel(success);
  }

  void FinishWithoutModel(bool success) {
    if (completed_) {
      return;
    }
    completed_ = true;
    succeeded_ = success;
    input_ = WasmProfilePreferencesBookmarkSmokeInput();
    if (!completion_.is_null()) {
      std::move(completion_).Run(success);
    }
  }

  bool started_ = false;
  bool completed_ = false;
  bool succeeded_ = false;
  bool flush_pending_ = false;
  WasmProfilePreferencesBookmarkSmokeInput input_;
  std::unique_ptr<bookmarks::BookmarkModel> model_;
  base::OnceCallback<void(bool success)> completion_;
};

WasmProfileBookmarkSmokeState& GetWasmProfileBookmarkSmokeState() {
  static base::NoDestructor<WasmProfileBookmarkSmokeState> state;
  return *state;
}

}  // namespace

bool StartWasmProfileBookmarkSmoke(
    base::FilePath profile_path,
    WasmProfilePreferencesBookmarkSmokeInput input,
    base::OnceCallback<void(bool success)> completion) {
  return GetWasmProfileBookmarkSmokeState().Start(
      std::move(profile_path), std::move(input), std::move(completion));
}

bool DidWasmProfileBookmarkSmokeSucceed() {
  return GetWasmProfileBookmarkSmokeState().DidSucceed();
}

}  // namespace chrome
