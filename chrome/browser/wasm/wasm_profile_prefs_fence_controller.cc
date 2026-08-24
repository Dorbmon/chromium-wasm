// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_prefs_fence_controller.h"

#include <optional>
#include <utility>

#include "base/check.h"
#include "base/functional/bind.h"
#include "base/task/sequenced_task_runner.h"

WasmProfilePrefsFenceController::WasmProfilePrefsFenceController(
    scoped_refptr<base::SequencedTaskRunner> owner_task_runner)
    : owner_task_runner_(std::move(owner_task_runner)) {
  CHECK(owner_task_runner_);
  CHECK(owner_task_runner_->RunsTasksInCurrentSequence());
  coordinator_ =
      std::make_unique<WasmProfileShutdownCoordinator>(owner_task_runner_);
}

WasmProfilePrefsFenceController::~WasmProfilePrefsFenceController() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  Cancel();
}

void WasmProfilePrefsFenceController::Begin(
    FenceStarter starter,
    FenceCompletionCallback completion) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  CHECK(!starter.is_null());
  CHECK(completion);
  CHECK_EQ(state_, State::kNotStarted);
  CHECK(coordinator_);

  std::optional<WasmProfileShutdownCoordinator::ProfileIOHold> hold =
      coordinator_->TryAcquireProfileIO();
  CHECK(hold.has_value());

  completion_ = std::move(completion);
  participant_ = std::make_unique<WasmProfilePersistentPrefsShutdownParticipant>(
      std::move(*hold), std::move(starter));
  state_ = State::kPending;

  // BeginQuiesce must precede Start(): a valid starter may invoke its
  // completion inline, and this controller must still observe that one
  // admitted operation in its terminal result.
  CHECK(coordinator_->BeginQuiesce(base::BindOnce(
      &WasmProfilePrefsFenceController::OnQuiesced,
      weak_ptr_factory_.GetWeakPtr())));

  // A rejected starter explicitly completes the participant as failed. The
  // result remains asynchronous, so callers always receive the terminal
  // success/failure callback through OnQuiesced().
  (void)participant_->Start();
}

void WasmProfilePrefsFenceController::Cancel() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (state_ != State::kPending) {
    return;
  }

  CHECK(participant_);
  // The participant turns a lost owner into an explicit failed operation. Do
  // not cancel the coordinator here: it must still post the false result if
  // this controller remains alive through the owner-sequence callback.
  participant_->Cancel();
}

bool WasmProfilePrefsFenceController::IsPending() const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return state_ == State::kPending;
}

bool WasmProfilePrefsFenceController::HasCompleted() const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return state_ == State::kSucceeded || state_ == State::kFailed;
}

bool WasmProfilePrefsFenceController::DidSucceed() const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return state_ == State::kSucceeded;
}

void WasmProfilePrefsFenceController::OnQuiesced(
    WasmProfileShutdownCoordinator::RegisteredProfileIOQuiesceResult result) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  CHECK_EQ(state_, State::kPending);

  // This controller owns exactly one registered Preferences operation. Do not
  // accept a zero-hold or multi-hold result as a successful fence: either
  // would be evidence that its lifecycle accounting changed without a new
  // profile-owner review.
  const bool success =
      result.status == WasmProfileShutdownCoordinator::
                           RegisteredProfileIOQuiesceStatus::
                               kAllOutstandingRegisteredOperationsSucceeded &&
      result.outstanding_at_begin == 1 && result.succeeded_after_begin == 1 &&
      result.failed_after_begin == 0 && result.abandoned_after_begin == 0;

  participant_.reset();
  state_ = success ? State::kSucceeded : State::kFailed;
  FenceCompletionCallback completion = std::move(completion_);
  std::move(completion).Run(success);
}
