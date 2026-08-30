// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_persistent_prefs_lifetime_participant.h"

#include <utility>

WasmProfilePersistentPrefsLifetimeParticipant::
    WasmProfilePersistentPrefsLifetimeParticipant(
        WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold)
    : profile_io_hold_(std::move(profile_io_hold)) {}

WasmProfilePersistentPrefsLifetimeParticipant::
    ~WasmProfilePersistentPrefsLifetimeParticipant() {
  Cancel();
}

bool WasmProfilePersistentPrefsLifetimeParticipant::CompleteAfterStrictFence(
    bool succeeded) {
  if (!profile_io_hold_) {
    return false;
  }

  const bool completed = profile_io_hold_->Complete(
      succeeded ? WasmProfileOrderedDrainLifecycle::ProfileIOCompletion::
                      kSucceeded
                : WasmProfileOrderedDrainLifecycle::ProfileIOCompletion::
                      kFailed);
  profile_io_hold_.reset();
  return completed;
}

void WasmProfilePersistentPrefsLifetimeParticipant::Cancel() {
  if (profile_io_hold_) {
    (void)CompleteAfterStrictFence(/*succeeded=*/false);
  }
}

bool WasmProfilePersistentPrefsLifetimeParticipant::IsPending() const {
  return profile_io_hold_.has_value();
}
