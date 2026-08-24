// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_PREFS_FENCE_CONTROLLER_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_PREFS_FENCE_CONTROLLER_H_

#include <memory>

#include "base/functional/callback.h"
#include "base/memory/scoped_refptr.h"
#include "base/memory/weak_ptr.h"
#include "base/sequence_checker.h"
#include "chrome/browser/wasm/wasm_profile_persistent_prefs_shutdown_participant.h"

namespace base {
class SequencedTaskRunner;
}

// Owns the one JsonPrefStore shutdown fence that the current WasmProfile can
// account for. It closes admission before starting that fence and reports a
// result only after the existing participant has reached a terminal outcome on
// the profile UI sequence.
//
// This is intentionally one registered owner, not a profile-wide cleanliness
// or OPFS durability claim. Additional profile services need their own
// result-bearing participants before this controller can take part in an OPFS
// handoff.
class WasmProfilePrefsFenceController {
 public:
  using FenceStarter =
      WasmProfilePersistentPrefsShutdownParticipant::FenceStarter;
  using FenceCompletionCallback = base::OnceCallback<void(bool success)>;

  explicit WasmProfilePrefsFenceController(
      scoped_refptr<base::SequencedTaskRunner> owner_task_runner);
  WasmProfilePrefsFenceController(const WasmProfilePrefsFenceController&) =
      delete;
  WasmProfilePrefsFenceController& operator=(
      const WasmProfilePrefsFenceController&) = delete;
  ~WasmProfilePrefsFenceController();

  // Starts exactly one already-defined Preferences fence. The completion is
  // always delivered asynchronously on the owner sequence. A rejected,
  // failed, cancelled, or abandoned participant reports |success == false|;
  // it must never be mistaken for a clean profile handoff.
  void Begin(FenceStarter starter, FenceCompletionCallback completion);

  // Explicitly fails a pending participant. This is used when its profile
  // owner cannot retain it through the terminal callback; it preserves a
  // result-bearing failure rather than relying on implicit hold destruction.
  void Cancel();

  bool IsPending() const;
  bool HasCompleted() const;
  bool DidSucceed() const;

 private:
  enum class State {
    kNotStarted,
    kPending,
    kSucceeded,
    kFailed,
  };

  void OnQuiesced(
      WasmProfileShutdownCoordinator::RegisteredProfileIOQuiesceResult
          result);

  const scoped_refptr<base::SequencedTaskRunner> owner_task_runner_;
  std::unique_ptr<WasmProfileShutdownCoordinator> coordinator_;
  std::unique_ptr<WasmProfilePersistentPrefsShutdownParticipant> participant_;
  FenceCompletionCallback completion_;
  State state_ = State::kNotStarted;

  SEQUENCE_CHECKER(sequence_checker_);
  base::WeakPtrFactory<WasmProfilePrefsFenceController> weak_ptr_factory_{
      this};
};

#endif  // CHROME_BROWSER_WASM_WASM_PROFILE_PREFS_FENCE_CONTROLLER_H_
