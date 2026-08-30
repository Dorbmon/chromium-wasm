// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_cookie_smoke.h"

#include <cstdio>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "base/check.h"
#include "base/functional/bind.h"
#include "base/no_destructor.h"
#include "base/strings/strcat.h"
#include "base/task/sequenced_task_runner.h"
#include "base/time/time.h"
#include "build/build_config.h"
#include "mojo/public/cpp/bindings/remote.h"
#include "net/cookies/canonical_cookie.h"
#include "net/cookies/cookie_access_result.h"
#include "net/cookies/cookie_inclusion_status.h"
#include "net/cookies/cookie_options.h"
#include "net/cookies/cookie_partition_key_collection.h"
#include "services/network/public/mojom/cookie_manager.mojom.h"
#include "url/gurl.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_profile_cookie_smoke.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kMarkerPrefix[] = "CHROMIUM_WASM_M7_PREFS:";
constexpr char kCookieName[] = "wasm_m7_profile_cookie";
constexpr char kCookieUrl[] = "https://wasm-profile-cookie.test/";

void EmitDigestMarker(const char* marker, const std::string& digest) {
  std::fprintf(stderr, "%s%s sha256=%s\n", kMarkerPrefix, marker,
               digest.c_str());
  std::fflush(stderr);
}

bool HasExpectedCookie(const net::CookieAccessResultList& cookies,
                       const std::string& expected_value) {
  for (const auto& result : cookies) {
    const net::CanonicalCookie& cookie = result.cookie;
    if (result.access_result.status.IsInclude() &&
        cookie.Name() == kCookieName && cookie.Value() == expected_value &&
        cookie.Path() == "/" && cookie.SecureAttribute() &&
        cookie.IsHttpOnly() && cookie.IsPersistent()) {
      return true;
    }
  }
  return false;
}

const net::CanonicalCookie* FindExpectedCookie(
    const net::CookieAccessResultList& cookies,
    const std::string& expected_value) {
  for (const auto& result : cookies) {
    const net::CanonicalCookie& cookie = result.cookie;
    if (result.access_result.status.IsInclude() &&
        cookie.Name() == kCookieName && cookie.Value() == expected_value &&
        cookie.Path() == "/" && cookie.SecureAttribute() &&
        cookie.IsHttpOnly() && cookie.IsPersistent()) {
      return &cookie;
    }
  }
  return nullptr;
}

bool HasAnyTestCookie(const net::CookieAccessResultList& cookies) {
  for (const auto& result : cookies) {
    if (result.cookie.Name() == kCookieName) {
      return true;
    }
  }
  return false;
}

}  // namespace

class WasmProfileCookieLifetimeParticipant::State {
 public:
  State(mojo::PendingRemote<network::mojom::CookieManager> cookie_manager,
        WasmProfilePreferencesCookieSmokeInput input,
        WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold)
      : cookie_manager_(std::move(cookie_manager)),
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
      CompleteBeforeStartAsFailed();
      return false;
    }

    started_ = true;
    completion_ = std::move(completion);
    if (cookie_manager_.is_bound()) {
      cookie_manager_.set_disconnect_handler(base::BindOnce(
          &State::OnCookieManagerDisconnected, base::Unretained(this)));
    }
    if (!IsWasmProfilePreferencesCookieSmokeEnabled() ||
        !cookie_manager_.is_bound() || !HasValidInput()) {
      FailAndClose();
      return true;
    }

    switch (input_.mode) {
      case WasmProfilePreferencesCookieSmokeInput::Mode::kWrite:
        ReadInitial(std::nullopt);
        break;
      case WasmProfilePreferencesCookieSmokeInput::Mode::kVerifyAndWrite:
        ReadInitial(input_.token_a);
        break;
      case WasmProfilePreferencesCookieSmokeInput::Mode::kVerifyB:
        ReadInitial(input_.token_b);
        break;
    }
    return true;
  }

  void Cancel() {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    if (completed_ || completion_delivery_pending_) {
      return;
    }
    failed_ = true;
    ReportFailure();
    if (!started_) {
      CompleteBeforeStartAsFailed();
      return;
    }
    if (operation_pending_ || close_started_) {
      return;
    }
    BeginBackendClose();
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
      case WasmProfilePreferencesCookieSmokeInput::Mode::kWrite:
        return !input_.token_a.empty() && !input_.token_a_digest.empty() &&
               input_.token_b.empty() && input_.token_b_digest.empty();
      case WasmProfilePreferencesCookieSmokeInput::Mode::kVerifyAndWrite:
        return !input_.token_a.empty() && !input_.token_a_digest.empty() &&
               !input_.token_b.empty() && !input_.token_b_digest.empty() &&
               input_.token_a != input_.token_b;
      case WasmProfilePreferencesCookieSmokeInput::Mode::kVerifyB:
        return input_.token_a.empty() && input_.token_a_digest.empty() &&
               !input_.token_b.empty() && !input_.token_b_digest.empty();
    }
    return false;
  }

  bool BeginOperationReply() {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    if (!operation_pending_ || completed_ || completion_delivery_pending_ ||
        close_started_) {
      FailAndClose();
      return false;
    }
    operation_pending_ = false;
    if (failed_) {
      BeginBackendClose();
      return false;
    }
    return true;
  }

  bool CanIssueOperation() {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    if (!cookie_manager_.is_bound() || cookie_manager_disconnected_ ||
        operation_pending_ || close_started_ || completed_ ||
        completion_delivery_pending_) {
      FailAndClose();
      return false;
    }
    operation_pending_ = true;
    return true;
  }

  void ReadInitial(std::optional<std::string> expected_value) {
    if (!CanIssueOperation()) {
      return;
    }
    cookie_manager_->GetCookieList(
        GURL(kCookieUrl), net::CookieOptions::MakeAllInclusive(),
        net::CookiePartitionKeyCollection(),
        base::BindOnce(&State::OnInitialRead, base::Unretained(this),
                       std::move(expected_value)));
  }

  void OnInitialRead(std::optional<std::string> expected_value,
                     const net::CookieAccessResultList& included,
                     const net::CookieAccessResultList& excluded) {
    if (!BeginOperationReply()) {
      return;
    }
    const net::CanonicalCookie* expected_cookie =
        expected_value ? FindExpectedCookie(included, *expected_value)
                       : nullptr;
    const bool has_expected = expected_cookie != nullptr;
    const bool has_any = HasAnyTestCookie(included) || HasAnyTestCookie(excluded);
    if ((expected_value && !has_expected) || (!expected_value && has_any)) {
      FailAndClose();
      return;
    }

    switch (input_.mode) {
      case WasmProfilePreferencesCookieSmokeInput::Mode::kWrite:
        WriteAndValidate(input_.token_a, input_.token_a_digest,
                         "COOKIE_A_WRITE_FLUSHED");
        return;
      case WasmProfilePreferencesCookieSmokeInput::Mode::kVerifyAndWrite:
        EmitDigestMarker("COOKIE_A_READ_OK", input_.token_a_digest);
        WriteAndValidate(input_.token_b, input_.token_b_digest,
                         "COOKIE_B_WRITE_FLUSHED");
        return;
      case WasmProfilePreferencesCookieSmokeInput::Mode::kVerifyB:
        EmitDigestMarker("COOKIE_B_READ_OK", input_.token_b_digest);
        DeleteAndFlush(*expected_cookie);
        return;
    }
    FailAndClose();
  }

  void WriteAndValidate(std::string expected_value,
                        std::string expected_digest,
                        const char* flushed_marker) {
    net::CookieInclusionStatus syntax_status;
    pending_cookie_ = net::CanonicalCookie::Create(
        GURL(kCookieUrl),
        base::StrCat({kCookieName, "=", expected_value,
                      "; Max-Age=31536000; Path=/; Secure; HttpOnly; "
                      "SameSite=Lax"}),
        base::Time::Now(), /*server_time=*/std::nullopt,
        /*cookie_partition_key=*/std::nullopt, net::CookieSourceType::kOther,
        &syntax_status);
    if (!pending_cookie_ || !syntax_status.IsInclude() ||
        !pending_cookie_->IsPersistent() || !CanIssueOperation()) {
      FailAndClose();
      return;
    }

    cookie_manager_->SetCanonicalCookie(
        *pending_cookie_, GURL(kCookieUrl),
        net::CookieOptions::MakeAllInclusive(),
        base::BindOnce(&State::OnSetCookie, base::Unretained(this),
                       std::move(expected_value), std::move(expected_digest),
                       flushed_marker));
  }

  void OnSetCookie(std::string expected_value,
                   std::string expected_digest,
                   const char* flushed_marker,
                   net::CookieAccessResult access_result) {
    pending_cookie_.reset();
    if (!BeginOperationReply()) {
      return;
    }
    if (!access_result.status.IsInclude() || !CanIssueOperation()) {
      FailAndClose();
      return;
    }

    cookie_manager_->GetCookieList(
        GURL(kCookieUrl), net::CookieOptions::MakeAllInclusive(),
        net::CookiePartitionKeyCollection(),
        base::BindOnce(&State::OnWriteReadback, base::Unretained(this),
                       std::move(expected_value), std::move(expected_digest),
                       flushed_marker));
  }

  void OnWriteReadback(std::string expected_value,
                       std::string expected_digest,
                       const char* flushed_marker,
                       const net::CookieAccessResultList& included,
                       const net::CookieAccessResultList& excluded) {
    if (!BeginOperationReply()) {
      return;
    }
    if (!HasExpectedCookie(included, expected_value) ||
        HasAnyTestCookie(excluded)) {
      FailAndClose();
      return;
    }
    FlushAndEmit(flushed_marker, std::move(expected_digest));
  }

  void DeleteAndFlush(const net::CanonicalCookie& cookie) {
    if (!CanIssueOperation()) {
      return;
    }
    cookie_manager_->DeleteCanonicalCookie(
        cookie,
        base::BindOnce(&State::OnDeleted, base::Unretained(this)));
  }

  void OnDeleted(bool success) {
    if (!BeginOperationReply()) {
      return;
    }
    if (!success) {
      FailAndClose();
      return;
    }
    FlushAndEmit(/*marker=*/nullptr, std::string());
  }

  void FlushAndEmit(const char* marker, std::string digest) {
    if ((marker && digest.empty()) || (!marker && !digest.empty()) ||
        !CanIssueOperation()) {
      FailAndClose();
      return;
    }
    cookie_manager_->FlushCookieStore(base::BindOnce(
        &State::OnFlushed, base::Unretained(this), marker, std::move(digest)));
  }

  void OnFlushed(const char* marker, std::string digest) {
    if (!BeginOperationReply()) {
      return;
    }
    if (marker) {
      EmitDigestMarker(marker, digest);
    }
    probe_succeeded_ = true;
    BeginBackendClose();
  }

  void FailAndClose() {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    if (completed_ || completion_delivery_pending_) {
      return;
    }
    failed_ = true;
    ReportFailure();
    pending_cookie_.reset();
    if (!started_) {
      CompleteBeforeStartAsFailed();
      return;
    }
    if (operation_pending_ || close_started_) {
      return;
    }
    if (!cookie_manager_.is_bound()) {
      ScheduleCompletion(/*operation_succeeded=*/false);
      return;
    }
    BeginBackendClose();
  }

  void BeginBackendClose() {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    if (completed_ || completion_delivery_pending_ || operation_pending_ ||
        close_started_) {
      return;
    }
    if (!cookie_manager_.is_bound() || cookie_manager_disconnected_) {
      // There is no backend-close receipt. Keep the hold outstanding so the
      // outer V4 transaction cannot race NetworkContext destruction.
      failed_ = true;
      ReportFailure();
      return;
    }

    close_started_ = true;
    input_ = WasmProfilePreferencesCookieSmokeInput();
    cookie_manager_->CloseCookieStoreForTesting(base::BindOnce(
        &State::OnBackendClosed, base::Unretained(this)));
  }

  void OnBackendClosed(bool success) {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    if (!close_started_ || completed_ || completion_delivery_pending_) {
      return;
    }
    close_receipt_received_ = true;
    const bool operation_succeeded = success && probe_succeeded_ && !failed_;
    if (operation_succeeded) {
      std::fprintf(stderr, "%sCOOKIE_BACKEND_CLOSED\n", kMarkerPrefix);
      std::fflush(stderr);
    }
    cookie_manager_.reset();
    ScheduleCompletion(operation_succeeded);
  }

  void OnCookieManagerDisconnected() {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    cookie_manager_disconnected_ = true;
    operation_pending_ = false;
    if (completed_ || completion_delivery_pending_ || close_receipt_received_) {
      return;
    }
    // The connection does not own NetworkContext. A disconnect cannot stand in
    // for its SQLite close receipt, so leave the admission non-terminal.
    failed_ = true;
    ReportFailure();
  }

  void ScheduleCompletion(bool operation_succeeded) {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    if (completed_ || completion_delivery_pending_) {
      return;
    }
    CHECK(started_);
    CHECK(!operation_pending_);
    completion_delivery_pending_ = true;
    pending_operation_succeeded_ = operation_succeeded;
    pending_cookie_.reset();
    input_ = WasmProfilePreferencesCookieSmokeInput();
    CHECK(base::SequencedTaskRunner::GetCurrentDefault()->PostTask(
        FROM_HERE,
        base::BindOnce(&State::DeliverCompletion, base::Unretained(this))));
  }

  void DeliverCompletion() {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    CHECK(completion_delivery_pending_);
    CHECK(!completed_);

    bool profile_io_completed = false;
    if (profile_io_hold_) {
      profile_io_completed = profile_io_hold_->Complete(
          pending_operation_succeeded_
              ? WasmProfileOrderedDrainLifecycle::ProfileIOCompletion::
                    kSucceeded
              : WasmProfileOrderedDrainLifecycle::ProfileIOCompletion::kFailed);
      profile_io_hold_.reset();
    }
    completion_delivery_pending_ = false;
    completed_ = true;
    succeeded_ = pending_operation_succeeded_ && profile_io_completed;
    if (!succeeded_) {
      ReportFailure();
    }
    CHECK(completion_);
    base::OnceCallback<void(bool success)> completion = std::move(completion_);
    const bool succeeded = succeeded_;
    // The callback may synchronously destroy this profile-owned or quarantined
    // State. Do not access members after returning control to its owner.
    std::move(completion).Run(succeeded);
  }

  void CompleteBeforeStartAsFailed() {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    if (completed_) {
      return;
    }
    if (profile_io_hold_) {
      (void)profile_io_hold_->Complete(
          WasmProfileOrderedDrainLifecycle::ProfileIOCompletion::kFailed);
      profile_io_hold_.reset();
    }
    completed_ = true;
    failed_ = true;
    input_ = WasmProfilePreferencesCookieSmokeInput();
    ReportFailure();
  }

  void ReportFailure() {
    if (failure_reported_) {
      return;
    }
    failure_reported_ = true;
    ReportWasmProfilePreferencesSmokeFailure(
        WasmProfilePreferencesSmokeFailureStage::kCookie);
  }

  bool started_ = false;
  bool operation_pending_ = false;
  bool close_started_ = false;
  bool close_receipt_received_ = false;
  bool cookie_manager_disconnected_ = false;
  bool failed_ = false;
  bool failure_reported_ = false;
  bool probe_succeeded_ = false;
  bool completion_delivery_pending_ = false;
  bool pending_operation_succeeded_ = false;
  bool completed_ = false;
  bool succeeded_ = false;
  mojo::Remote<network::mojom::CookieManager> cookie_manager_;
  WasmProfilePreferencesCookieSmokeInput input_;
  std::optional<WasmProfileOrderedDrainLifecycle::ProfileIOHold>
      profile_io_hold_;
  std::unique_ptr<net::CanonicalCookie> pending_cookie_;
  base::OnceCallback<void(bool success)> completion_;
  SEQUENCE_CHECKER(sequence_checker_);
};

WasmProfileCookieLifetimeParticipant::WasmProfileCookieLifetimeParticipant(
    mojo::PendingRemote<network::mojom::CookieManager> cookie_manager,
    WasmProfilePreferencesCookieSmokeInput input,
    WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold)
    : state_(std::make_unique<State>(std::move(cookie_manager), std::move(input),
                                     std::move(profile_io_hold))) {}

WasmProfileCookieLifetimeParticipant::~WasmProfileCookieLifetimeParticipant() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  (void)QuarantineForFailureShutdown();
}

bool WasmProfileCookieLifetimeParticipant::Start(
    base::OnceCallback<void(bool success)> completion) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return state_ && state_->Start(std::move(completion));
}

void WasmProfileCookieLifetimeParticipant::Cancel() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (state_) {
    state_->Cancel();
  }
}

bool WasmProfileCookieLifetimeParticipant::QuarantineForFailureShutdown() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (!state_) {
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

bool WasmProfileCookieLifetimeParticipant::IsActive() const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return state_ && state_->IsActive();
}

bool WasmProfileCookieLifetimeParticipant::HasCompleted() const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return state_ && state_->HasCompleted();
}

bool WasmProfileCookieLifetimeParticipant::DidSucceed() const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return state_ && state_->DidSucceed();
}

}  // namespace chrome
