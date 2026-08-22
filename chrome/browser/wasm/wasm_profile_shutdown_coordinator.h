// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_SHUTDOWN_COORDINATOR_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_SHUTDOWN_COORDINATOR_H_

#include <cstddef>
#include <optional>

#include "base/functional/callback_forward.h"
#include "base/memory/scoped_refptr.h"
#include "base/sequence_checker.h"

namespace base {
class SequencedTaskRunner;
}

// Coordinates shutdown of explicitly registered profile I/O. Its asynchronous
// result describes only that finite registered set, never profile-wide
// cleanliness or durability.
//
// This is a preparatory control-plane primitive. It does not itself register
// every profile I/O source, drain filesystem descriptors, close databases, or
// release a profile-storage lease. Those operations need their own
// result-bearing participants before this coordinator can be wired into
// WasmProfile shutdown.
class WasmProfileShutdownCoordinator {
 private:
  class State;

 public:
  // The explicit terminal outcome reported by a registered operation. A hold
  // must remain alive through the operation's final callback and resource
  // destruction before it reports either outcome.
  enum class ProfileIOCompletion {
    kSucceeded,
    kFailed,
  };

  enum class RegisteredProfileIOQuiesceStatus {
    // No registered operation was outstanding when BeginQuiesce() closed
    // admission. This is not a profile-wide success or durability claim.
    kNoOutstandingRegisteredOperations,
    kAllOutstandingRegisteredOperationsSucceeded,
    kOutstandingRegisteredOperationFailed,
    kOutstandingRegisteredOperationAbandoned,
  };

  // The aggregate for the one registered-I/O quiesce epoch. It includes only
  // holds that were outstanding while BeginQuiesce() atomically closed
  // admission; operations that completed before that point are outside this
  // result. This result never establishes profile-wide quiescence, durable
  // storage, descriptor drainage, or OPFS lease authority.
  struct RegisteredProfileIOQuiesceResult {
    RegisteredProfileIOQuiesceStatus status =
        RegisteredProfileIOQuiesceStatus::kNoOutstandingRegisteredOperations;
    size_t outstanding_at_begin = 0;
    size_t succeeded_after_begin = 0;
    size_t failed_after_begin = 0;
    size_t abandoned_after_begin = 0;

    bool AllOutstandingRegisteredOperationsSucceeded() const {
      return status ==
             RegisteredProfileIOQuiesceStatus::
                 kAllOutstandingRegisteredOperationsSucceeded;
    }
  };

  using QuiesceCallback =
      base::OnceCallback<void(RegisteredProfileIOQuiesceResult)>;

  // A move-only admission held from before registered profile I/O starts until
  // its final callback and resource destruction have completed. It can be
  // released from any sequence and never holds a raw WasmProfile pointer.
  class ProfileIOHold {
   public:
    ProfileIOHold(ProfileIOHold&& other) noexcept;
    ProfileIOHold& operator=(ProfileIOHold&& other) noexcept;
    ~ProfileIOHold();

    ProfileIOHold(const ProfileIOHold&) = delete;
    ProfileIOHold& operator=(const ProfileIOHold&) = delete;

    // Records an explicit terminal result and releases this hold. Returns
    // false when the hold was already completed, abandoned, or moved from.
    bool Complete(ProfileIOCompletion completion);

   private:
    friend class WasmProfileShutdownCoordinator;
    friend class State;

    explicit ProfileIOHold(scoped_refptr<State> state);
    void Reset();

    scoped_refptr<State> state_;
  };

  // Construction, BeginQuiesce(), Cancel(), and completion delivery run on
  // |owner_task_runner|. It must remain runnable until every ProfileIOHold
  // has released; otherwise this preparatory primitive suppresses completion
  // rather than reporting a false quiesce success.
  explicit WasmProfileShutdownCoordinator(
      scoped_refptr<base::SequencedTaskRunner> owner_task_runner);
  WasmProfileShutdownCoordinator(const WasmProfileShutdownCoordinator&) =
      delete;
  WasmProfileShutdownCoordinator& operator=(
      const WasmProfileShutdownCoordinator&) = delete;
  ~WasmProfileShutdownCoordinator();

  // Acquires admission for one registered profile I/O operation, or rejects it
  // after quiescence/cancellation has begun. This method is thread-safe.
  std::optional<ProfileIOHold> TryAcquireProfileIO();

  // Atomically closes new admissions and asynchronously invokes
  // |on_quiesced| on the owner sequence after all holds that were outstanding
  // at that point reach a terminal result. Returns false for a duplicate,
  // cancelled, or invalid request. Delivery is suppressed by Cancel() or an
  // owner-task-runner failure; neither case synthesizes a success result.
  bool BeginQuiesce(QuiesceCallback on_quiesced);

  // Permanently rejects new admissions and suppresses a pending completion.
  // It is idempotent and must run on the owner sequence.
  void Cancel();

 private:
  const scoped_refptr<State> state_;
  SEQUENCE_CHECKER(sequence_checker_);
};

#endif  // CHROME_BROWSER_WASM_WASM_PROFILE_SHUTDOWN_COORDINATOR_H_
