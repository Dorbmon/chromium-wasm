// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_persistent_prefs_shutdown_participant.h"

#include <utility>

#include "base/functional/bind.h"

WasmProfilePersistentPrefsShutdownParticipant::
    WasmProfilePersistentPrefsShutdownParticipant(
        WasmProfileShutdownCoordinator::ProfileIOHold hold,
        FenceStarter starter)
    : hold_(std::move(hold)), starter_(std::move(starter)) {}

WasmProfilePersistentPrefsShutdownParticipant::
    ~WasmProfilePersistentPrefsShutdownParticipant() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  Cancel();
}

bool WasmProfilePersistentPrefsShutdownParticipant::Start() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (cancelled_ || started_) {
    return false;
  }
  started_ = true;

  if (starter_.is_null()) {
    Cancel();
    return false;
  }

  FenceStarter starter = std::move(starter_);
  base::WeakPtr<WasmProfilePersistentPrefsShutdownParticipant> weak_this =
      weak_ptr_factory_.GetWeakPtr();
  starter_running_ = true;
  const bool accepted = std::move(starter).Run(base::BindOnce(
      &WasmProfilePersistentPrefsShutdownParticipant::OnFenceComplete,
      weak_ptr_factory_.GetWeakPtr()));
  if (!weak_this) {
    // The injected starter may synchronously destroy this object's owner.
    // Nothing may touch a member after that boundary.
    return false;
  }
  starter_running_ = false;
  std::optional<bool> inline_completion =
      std::move(completion_while_starter_running_);
  completion_while_starter_running_.reset();

  if (cancelled_ || !accepted) {
    // A rejected or cancelled start has no callback that can establish success.
    Cancel();
    return false;
  }
  if (inline_completion.has_value()) {
    Complete(*inline_completion
                 ? WasmProfileShutdownCoordinator::ProfileIOCompletion::
                       kSucceeded
                 : WasmProfileShutdownCoordinator::ProfileIOCompletion::
                       kFailed);
  }
  return true;
}

void WasmProfilePersistentPrefsShutdownParticipant::Cancel() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (cancelled_) {
    return;
  }
  cancelled_ = true;
  starter_.Reset();
  completion_while_starter_running_.reset();
  weak_ptr_factory_.InvalidateWeakPtrs();
  // A profile owner can disappear while WasmProfile's weak-bound fence
  // completion is still pending. Preserve that uncertainty as an explicit
  // failed registered operation rather than allowing ProfileIOHold's
  // destructor to classify it only as abandoned.
  Complete(WasmProfileShutdownCoordinator::ProfileIOCompletion::kFailed);
}

void WasmProfilePersistentPrefsShutdownParticipant::OnFenceComplete(
    bool success) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (starter_running_) {
    completion_while_starter_running_ = success;
    return;
  }
  Complete(success
               ? WasmProfileShutdownCoordinator::ProfileIOCompletion::
                     kSucceeded
               : WasmProfileShutdownCoordinator::ProfileIOCompletion::kFailed);
}

void WasmProfilePersistentPrefsShutdownParticipant::Complete(
    WasmProfileShutdownCoordinator::ProfileIOCompletion completion) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (!hold_) {
    return;
  }
  hold_->Complete(completion);
  hold_.reset();
}
