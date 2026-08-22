// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_PERSISTENT_PREFS_SHUTDOWN_PARTICIPANT_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_PERSISTENT_PREFS_SHUTDOWN_PARTICIPANT_H_

#include <optional>

#include "base/functional/callback.h"
#include "base/memory/weak_ptr.h"
#include "base/sequence_checker.h"
#include "chrome/browser/wasm/wasm_profile_shutdown_coordinator.h"

// Adapts one already-admitted persistent-Preferences shutdown fence to the
// explicit registered-I/O result protocol. This is deliberately independent
// of WasmProfile so it can be tested without starting a Profile or changing
// profile shutdown ownership.
//
// The caller acquires |hold| before constructing this object, then supplies a
// one-shot starter for an already-defined Preferences fence. A successful
// starter must eventually invoke its completion on this object's sequence. A
// rejected starter must not invoke the completion. If this object is destroyed
// before a terminal callback, it explicitly reports failure rather than
// leaving its hold abandoned. A future WasmProfile integration must own this
// participant for the lifetime of the started fence.
//
// This is not a durable-storage, profile-quiescence, descriptor-drain,
// filesystem-flush, shutdown, recovery, or OPFS-lease primitive. It does not
// invoke WasmProfile, PrefService, or JsonPrefStore itself.
class WasmProfilePersistentPrefsShutdownParticipant {
 public:
  using FenceCompletionCallback = base::OnceCallback<void(bool success)>;
  using FenceStarter =
      base::OnceCallback<bool(FenceCompletionCallback completion)>;

  // |hold| must be a successfully acquired ProfileIOHold. |starter| receives
  // the one terminal completion callback and returns whether it accepted the
  // operation. It is valid for the starter to invoke the completion before
  // returning. A false return remains authoritative and fails the operation
  // even if a malformed starter invoked its completion inline.
  WasmProfilePersistentPrefsShutdownParticipant(
      WasmProfileShutdownCoordinator::ProfileIOHold hold,
      FenceStarter starter);
  WasmProfilePersistentPrefsShutdownParticipant(
      const WasmProfilePersistentPrefsShutdownParticipant&) = delete;
  WasmProfilePersistentPrefsShutdownParticipant& operator=(
      const WasmProfilePersistentPrefsShutdownParticipant&) = delete;
  ~WasmProfilePersistentPrefsShutdownParticipant();

  // Starts the supplied fence once. Returns false for a missing or rejected
  // starter, and reports failure for that admission. A repeat call is rejected
  // without changing the already-started operation's terminal result.
  // Because an accepted starter may complete inline, a caller that needs its
  // result included in a quiesce epoch must call BeginQuiesce() after acquiring
  // |hold| but before calling Start().
  bool Start();

  // Invalidates a pending fence callback and explicitly reports failure while
  // this admission still holds a pending result. It cannot reverse an already
  // terminal result. This is idempotent and must run on this object's sequence.
  void Cancel();

 private:
  void OnFenceComplete(bool success);
  void Complete(
      WasmProfileShutdownCoordinator::ProfileIOCompletion completion);

  std::optional<WasmProfileShutdownCoordinator::ProfileIOHold> hold_;
  FenceStarter starter_;
  bool started_ = false;
  bool cancelled_ = false;
  bool starter_running_ = false;
  std::optional<bool> completion_while_starter_running_;

  SEQUENCE_CHECKER(sequence_checker_);
  // Keep this last. The destructor invalidates its weak pointers before it
  // releases the hold, making a late fence callback inert.
  base::WeakPtrFactory<WasmProfilePersistentPrefsShutdownParticipant>
      weak_ptr_factory_{this};
};

#endif  // CHROME_BROWSER_WASM_WASM_PROFILE_PERSISTENT_PREFS_SHUTDOWN_PARTICIPANT_H_
