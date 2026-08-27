// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_history_smoke.h"

#include <cstdint>
#include <cstdio>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "base/command_line.h"
#include "base/functional/bind.h"
#include "base/functional/callback.h"
#include "base/no_destructor.h"
#include "base/task/cancelable_task_tracker.h"
#include "base/time/time.h"
#include "build/build_config.h"
#include "chrome/browser/wasm/wasm_profile_preferences_smoke.h"
#include "components/history/content/browser/history_database_helper.h"
#include "components/history/core/browser/history_backend_client.h"
#include "components/history/core/browser/history_client.h"
#include "components/history/core/browser/history_database_params.h"
#include "components/history/core/browser/history_service.h"
#include "components/history/core/browser/history_service_observer.h"
#include "components/history/core/browser/history_types.h"
#include "components/history/core/browser/visit_delegate.h"
#include "components/version_info/channel.h"
#include "sql/init_status.h"
#include "url/gurl.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_profile_history_smoke.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kPreferencesSmokeSwitch[] = "wasm-profile-preferences-smoke";
constexpr char kWriteMode[] = "write";
constexpr char kVerifyAndWriteMode[] = "verify-and-write";
constexpr char kVerifyBMode[] = "verify-b";

constexpr char kMarkerPrefix[] = "CHROMIUM_WASM_M7_PREFS:";
constexpr char kHistoryAUrl[] = "https://wasm-history.test/m7-a";
constexpr char kHistoryBUrl[] = "https://wasm-history.test/m7-b";
constexpr char16_t kHistoryATitle[] = u"chromium-wasm-history-m7-a";
constexpr char16_t kHistoryBTitle[] = u"chromium-wasm-history-m7-b";

enum class SmokeMode {
  kNone,
  kWrite,
  kVerifyAndWrite,
  kVerifyB,
};

void EmitHistoryMarker(const char* marker) {
  std::fprintf(stderr, "%s%s\n", kMarkerPrefix, marker);
  std::fflush(stderr);
}

// Keeps the dedicated probe on the supported HistoryService constructor rather
// than its unit-test-only empty-client constructor. This intentionally provides
// no bookmark or visited-link integration: the bounded artifact owns one core
// service directly and must not admit the desktop HistoryServiceFactory graph.
class WasmProfileHistorySmokeBackendClient final
    : public history::HistoryBackendClient {
 public:
  WasmProfileHistorySmokeBackendClient() = default;
  WasmProfileHistorySmokeBackendClient(
      const WasmProfileHistorySmokeBackendClient&) = delete;
  WasmProfileHistorySmokeBackendClient& operator=(
      const WasmProfileHistorySmokeBackendClient&) = delete;
  ~WasmProfileHistorySmokeBackendClient() override = default;

  bool IsPinnedURL(const GURL&) override { return false; }
  std::vector<history::URLAndTitle> GetPinnedURLs() override { return {}; }
  bool IsWebSafe(const GURL& url) override { return url.is_valid(); }
};

class WasmProfileHistorySmokeClient final : public history::HistoryClient {
 public:
  explicit WasmProfileHistorySmokeClient(base::RepeatingClosure on_error)
      : on_error_(std::move(on_error)) {}
  WasmProfileHistorySmokeClient(const WasmProfileHistorySmokeClient&) =
      delete;
  WasmProfileHistorySmokeClient& operator=(
      const WasmProfileHistorySmokeClient&) = delete;
  ~WasmProfileHistorySmokeClient() override = default;

  void OnHistoryServiceCreated(history::HistoryService*) override {}
  void Shutdown() override {}

  history::CanAddURLCallback GetThreadSafeCanAddURLCallback() const override {
    return base::BindRepeating([](const GURL& url) {
      return url.is_valid() && url.SchemeIsHTTPOrHTTPS();
    });
  }

  void NotifyProfileError(sql::InitStatus, const std::string&) override {
    // Do not expose the supplied SQL diagnostics or profile path. This fixed
    // failure-only checkpoint distinguishes database open from later query or
    // close failures in the acceptance harness.
    EmitHistoryMarker("HISTORY_DATABASE_PROFILE_ERROR");
    on_error_.Run();
  }

  std::unique_ptr<history::HistoryBackendClient> CreateBackendClient()
      override {
    return std::make_unique<WasmProfileHistorySmokeBackendClient>();
  }

  void UpdateBookmarkLastUsedTime(int64_t, base::Time) override {}

 private:
  base::RepeatingClosure on_error_;
};

class WasmProfileHistorySmokeState : public history::HistoryServiceObserver {
 public:
  WasmProfileHistorySmokeState() = default;
  WasmProfileHistorySmokeState(const WasmProfileHistorySmokeState&) = delete;
  WasmProfileHistorySmokeState& operator=(
      const WasmProfileHistorySmokeState&) = delete;
  ~WasmProfileHistorySmokeState() = default;

  bool Start(base::FilePath profile_path,
             base::OnceCallback<void(bool success)> completion) {
    if (!IsWasmProfilePreferencesHistorySmokeEnabled() || started_ ||
        profile_path.empty() || !completion) {
      ReportFailure();
      return false;
    }

    const base::CommandLine* command_line =
        base::CommandLine::ForCurrentProcess();
    const std::string mode =
        command_line->GetSwitchValueASCII(kPreferencesSmokeSwitch);
    if (mode == kWriteMode) {
      mode_ = SmokeMode::kWrite;
    } else if (mode == kVerifyAndWriteMode) {
      mode_ = SmokeMode::kVerifyAndWrite;
    } else if (mode == kVerifyBMode) {
      mode_ = SmokeMode::kVerifyB;
    } else {
      ReportFailure();
      return false;
    }

    started_ = true;
    completion_ = std::move(completion);
    history_service_ = std::make_unique<history::HistoryService>(
        std::make_unique<WasmProfileHistorySmokeClient>(base::BindRepeating(
            &WasmProfileHistorySmokeState::OnProfileError,
            base::Unretained(this))),
        /*visit_delegate=*/nullptr,
        /*device_info_tracker=*/nullptr,
        /*local_device_info_provider=*/nullptr);
    if (!history_service_->Init(history::HistoryDatabaseParamsForPath(
            profile_path, version_info::Channel::UNKNOWN))) {
      history_service_.reset();
      FinishWithoutBackendClose();
      return true;
    }
    history_service_->AddObserver(this);
    return true;
  }

  bool DidSucceed() const { return started_ && succeeded_ && completed_; }

 private:
  // HistoryService construction starts database initialization asynchronously.
  // Do not submit the first write merely because Init() queued that work: this
  // observer is the core service's own UI-sequence readiness notification.
  void OnHistoryServiceLoaded(
      history::HistoryService* history_service) override {
    if (history_service != history_service_.get() || operations_started_ ||
        closing_ || failed_) {
      FailAndClose();
      return;
    }
    operations_started_ = true;
    switch (mode_) {
      case SmokeMode::kWrite:
        WriteAndVerify(GURL(kHistoryAUrl), kHistoryATitle,
                       "HISTORY_A_WRITE_ACCEPTED",
                       base::BindOnce(&WasmProfileHistorySmokeState::Close,
                                      base::Unretained(this)));
        break;
      case SmokeMode::kVerifyAndWrite:
        Verify(GURL(kHistoryAUrl), kHistoryATitle, "HISTORY_A_READ_OK",
               base::BindOnce(&WasmProfileHistorySmokeState::WriteAndVerify,
                              base::Unretained(this), GURL(kHistoryBUrl),
                              kHistoryBTitle, "HISTORY_B_WRITE_ACCEPTED",
                              base::BindOnce(
                                  &WasmProfileHistorySmokeState::Close,
                                  base::Unretained(this))));
        break;
      case SmokeMode::kVerifyB:
        Verify(GURL(kHistoryAUrl), kHistoryATitle, "HISTORY_A_READ_OK",
               base::BindOnce(&WasmProfileHistorySmokeState::Verify,
                              base::Unretained(this), GURL(kHistoryBUrl),
                              kHistoryBTitle, "HISTORY_B_READ_OK",
                              base::BindOnce(
                                  &WasmProfileHistorySmokeState::Close,
                                  base::Unretained(this))));
        break;
      case SmokeMode::kNone:
        FinishWithoutBackendClose();
        break;
    }
  }

  void WriteAndVerify(GURL url,
                      std::u16string title,
                      const char* marker,
                      base::OnceClosure next) {
    if (!history_service_ || waiting_for_visit_ || closing_ || failed_) {
      FailAndClose();
      return;
    }

    // AddPage only queues work to HistoryBackend. Wait for its UI-sequence
    // visit notification before scheduling the dependent title update and
    // query. This is Chromium's own commitment notification, rather than an
    // assumption about cross-thread task ordering in the Wasm runtime.
    waiting_for_visit_ = true;
    pending_url_ = std::move(url);
    pending_title_ = std::move(title);
    pending_marker_ = marker;
    pending_next_ = std::move(next);
    history_service_->AddPage(pending_url_, base::Time::Now(),
                              history::SOURCE_BROWSED);
  }

  void OnURLVisited(history::HistoryService* history_service,
                    const history::VisitedURLInfo& visited_url_info) override {
    if (history_service != history_service_.get() || !waiting_for_visit_ ||
        closing_ || failed_ || visited_url_info.url_row.url() != pending_url_) {
      FailAndClose();
      return;
    }

    waiting_for_visit_ = false;
    history_service_->SetPageTitle(pending_url_, pending_title_);
    history_service_->FlushForTest(base::BindOnce(
        &WasmProfileHistorySmokeState::Verify, base::Unretained(this),
        std::move(pending_url_), std::move(pending_title_), pending_marker_,
        std::move(pending_next_)));
    pending_marker_ = nullptr;
  }

  void Verify(GURL url,
              std::u16string title,
              const char* marker,
              base::OnceClosure next) {
    if (!history_service_ || closing_ || failed_) {
      FailAndClose();
      return;
    }
    // Construct the callback before passing |url| to the query. Moving the
    // same object into a later function argument would leave evaluation order
    // unspecified and can submit a moved-from URL to HistoryService.
    auto on_query = base::BindOnce(&WasmProfileHistorySmokeState::OnQuery,
                                   base::Unretained(this), url, title, marker,
                                   std::move(next));
    history_service_->QueryURLAndVisits(
        url, history::VisitQuery404sPolicy::kInclude404s,
        std::move(on_query),
        &task_tracker_);
  }

  void OnQuery(GURL expected_url,
               std::u16string expected_title,
               const char* marker,
               base::OnceClosure next,
               history::QueryURLAndVisitsResult result) {
    if (!result.success || result.row.url() != expected_url ||
        result.row.title() != expected_title || result.visits.empty()) {
      if (!result.success) {
        EmitMarker("HISTORY_QUERY_NOT_FOUND");
      } else if (result.row.url() != expected_url) {
        EmitMarker("HISTORY_QUERY_URL_MISMATCH");
      } else if (result.row.title() != expected_title) {
        EmitMarker("HISTORY_QUERY_TITLE_MISMATCH");
      } else {
        EmitMarker("HISTORY_QUERY_NO_VISITS");
      }
      // Keep this failure breadcrumb structural. It distinguishes a completed
      // core-service query that did not satisfy the exact test record from a
      // database-open failure, without reporting the row, URL, title, or
      // visit details.
      EmitMarker("HISTORY_QUERY_VALIDATION_FAILED");
      FailAndClose();
      return;
    }
    EmitMarker(marker);
    std::move(next).Run();
  }

  void OnProfileError() { FailAndClose(); }

  void Close() {
    if (!history_service_ || closing_) {
      FailAndClose();
      return;
    }
    closing_ = true;
    waiting_for_visit_ = false;
    pending_marker_ = nullptr;
    pending_next_.Reset();
    history_service_->RemoveObserver(this);
    history_service_->SetOnBackendDestroyTask(base::BindOnce(
        &WasmProfileHistorySmokeState::OnBackendDestroyed,
        base::Unretained(this)));
    history_service_->Shutdown();
    history_service_.reset();
  }

  void FailAndClose() {
    failed_ = true;
    if (closing_) {
      return;
    }
    if (!history_service_) {
      FinishWithoutBackendClose();
      return;
    }
    Close();
  }

  void OnBackendDestroyed() {
    if (!closing_ || completed_) {
      ReportFailure();
      return;
    }
    completed_ = true;
    succeeded_ = !failed_;
    if (!succeeded_) {
      ReportFailure();
    }
    if (completion_) {
      std::move(completion_).Run(succeeded_);
    }
  }

  void FinishWithoutBackendClose() {
    failed_ = true;
    completed_ = true;
    succeeded_ = false;
    ReportFailure();
    if (completion_) {
      std::move(completion_).Run(false);
    }
  }

  void ReportFailure() {
    ReportWasmProfilePreferencesSmokeFailure(
        WasmProfilePreferencesSmokeFailureStage::kHistory);
  }

  void EmitMarker(const char* marker) {
    EmitHistoryMarker(marker);
  }

  bool started_ = false;
  bool closing_ = false;
  bool failed_ = false;
  bool completed_ = false;
  bool succeeded_ = false;
  bool operations_started_ = false;
  bool waiting_for_visit_ = false;
  SmokeMode mode_ = SmokeMode::kNone;
  std::unique_ptr<history::HistoryService> history_service_;
  base::CancelableTaskTracker task_tracker_;
  GURL pending_url_;
  std::u16string pending_title_;
  const char* pending_marker_ = nullptr;
  base::OnceClosure pending_next_;
  base::OnceCallback<void(bool success)> completion_;
};

WasmProfileHistorySmokeState& GetWasmProfileHistorySmokeState() {
  static base::NoDestructor<WasmProfileHistorySmokeState> state;
  return *state;
}

}  // namespace

bool StartWasmProfileHistorySmoke(
    base::FilePath profile_path,
    base::OnceCallback<void(bool success)> completion) {
  return GetWasmProfileHistorySmokeState().Start(std::move(profile_path),
                                                 std::move(completion));
}

bool DidWasmProfileHistorySmokeSucceed() {
  return GetWasmProfileHistorySmokeState().DidSucceed();
}

}  // namespace chrome
