// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_PERSISTENT_PREFS_LIFETIME_PARTICIPANT_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_PERSISTENT_PREFS_LIFETIME_PARTICIPANT_H_

#include <optional>

#include "chrome/browser/wasm/wasm_profile_ordered_drain_lifecycle.h"

// Retains one source-selected construction admission from before the profile
// path is resolved and WasmProfile synchronously creates PrefService through
// its strict Preferences write/readback fence terminal result. A lost profile
// owner is explicitly failed instead of allowing the outer lifecycle to
// classify the admission as abandoned.
//
// This is only an admission/result adapter. It does not start PrefService I/O,
// close profile services, drain descriptors, prove profile-wide quiescence, or
// establish persistence, recovery, or OPFS lease authority.
class WasmProfilePersistentPrefsLifetimeParticipant {
 public:
  explicit WasmProfilePersistentPrefsLifetimeParticipant(
      WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold);
  WasmProfilePersistentPrefsLifetimeParticipant(
      const WasmProfilePersistentPrefsLifetimeParticipant&) = delete;
  WasmProfilePersistentPrefsLifetimeParticipant& operator=(
      const WasmProfilePersistentPrefsLifetimeParticipant&) = delete;
  ~WasmProfilePersistentPrefsLifetimeParticipant();

  // Records the exact terminal result of the already-strict JsonPrefStore
  // write/readback fence. It returns false if this admission was already
  // completed or cancelled; a repeated result must not recreate a clean
  // handoff.
  bool CompleteAfterStrictFence(bool succeeded);

  // Explicitly records a failed operation if the WasmProfile cannot remain
  // alive through its strict fence result. This is idempotent.
  void Cancel();

  bool IsPending() const;

 private:
  std::optional<WasmProfileOrderedDrainLifecycle::ProfileIOHold>
      profile_io_hold_;
};

#endif  // CHROME_BROWSER_WASM_WASM_PROFILE_PERSISTENT_PREFS_LIFETIME_PARTICIPANT_H_
