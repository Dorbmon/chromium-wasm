// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_shutdown_coordinator.h"

#include <cstdint>
#include <utility>

#include "base/check.h"
#include "base/functional/bind.h"
#include "base/location.h"
#include "base/memory/ref_counted.h"
#include "base/synchronization/lock.h"
#include "base/task/sequenced_task_runner.h"

namespace {

enum class ProfileIOHoldDisposition {
  kSucceeded,
  kFailed,
  kAbandoned,
};

}  // namespace

class WasmProfileShutdownCoordinator::State final
    : public base::RefCountedThreadSafe<WasmProfileShutdownCoordinator::State> {
 public:
  explicit State(scoped_refptr<base::SequencedTaskRunner> owner_task_runner)
      : owner_task_runner_(std::move(owner_task_runner)) {
    CHECK(owner_task_runner_);
  }

  bool RunsTasksInCurrentSequence() const {
    return owner_task_runner_->RunsTasksInCurrentSequence();
  }

  std::optional<ProfileIOHold> TryAcquireProfileIO() {
    base::AutoLock lock(lock_);
    if (!accepting_profile_io_) {
      return std::nullopt;
    }
    ++profile_io_holds_;
    return ProfileIOHold(base::WrapRefCounted(this));
  }

  bool BeginQuiesce(QuiesceCallback on_quiesced) {
    if (on_quiesced.is_null()) {
      return false;
    }

    bool post_completion = false;
    uint64_t completion_generation = 0;
    {
      base::AutoLock lock(lock_);
      if (!accepting_profile_io_ || quiesce_started_ || cancelled_) {
        return false;
      }

      accepting_profile_io_ = false;
      quiesce_started_ = true;
      on_quiesced_ = std::move(on_quiesced);
      outstanding_at_begin_ = profile_io_holds_;
      if (profile_io_holds_ == 0) {
        completion_posted_ = true;
        completion_generation = cancellation_generation_;
        post_completion = true;
      }
    }

    if (post_completion && !PostCompletion(completion_generation)) {
      // A future profile-shutdown integration must surface this as a terminal
      // failure. This primitive cannot safely deliver its registered-I/O
      // result after the owner task runner fails, so it suppresses completion
      // rather than claiming quiescence.
      Cancel();
      return false;
    }
    return true;
  }

  void Cancel() {
    base::AutoLock lock(lock_);
    accepting_profile_io_ = false;
    cancelled_ = true;
    ++cancellation_generation_;
    on_quiesced_.Reset();
  }

 private:
  friend class base::RefCountedThreadSafe<State>;
  friend class WasmProfileShutdownCoordinator::ProfileIOHold;

  ~State() = default;

  void ReleaseProfileIOHold(ProfileIOHoldDisposition disposition) {
    bool post_completion = false;
    uint64_t completion_generation = 0;
    {
      base::AutoLock lock(lock_);
      CHECK_GT(profile_io_holds_, 0u);
      --profile_io_holds_;
      if (quiesce_started_) {
        switch (disposition) {
          case ProfileIOHoldDisposition::kSucceeded:
            ++succeeded_after_begin_;
            break;
          case ProfileIOHoldDisposition::kFailed:
            ++failed_after_begin_;
            break;
          case ProfileIOHoldDisposition::kAbandoned:
            ++abandoned_after_begin_;
            break;
        }
      }
      if (profile_io_holds_ == 0 && quiesce_started_ && !cancelled_ &&
          !completion_posted_) {
        completion_posted_ = true;
        completion_generation = cancellation_generation_;
        post_completion = true;
      }
    }

    if (post_completion && !PostCompletion(completion_generation)) {
      // There is no safe synchronous substitute for owner-sequence delivery.
      // Suppress success rather than reporting a quiesce completion that the
      // owner cannot observe. A future profile-shutdown integration needs a
      // separate terminal failure channel for this lifecycle breach.
      Cancel();
    }
  }

  bool PostCompletion(uint64_t completion_generation) {
    return owner_task_runner_->PostTask(
        FROM_HERE,
        base::BindOnce(&State::DeliverCompletion, base::WrapRefCounted(this),
                       completion_generation));
  }

  void DeliverCompletion(uint64_t completion_generation) {
    DCHECK(RunsTasksInCurrentSequence());
    QuiesceCallback on_quiesced;
    RegisteredProfileIOQuiesceResult result;
    {
      base::AutoLock lock(lock_);
      if (cancelled_ || completion_generation != cancellation_generation_) {
        return;
      }
      on_quiesced = std::move(on_quiesced_);
      result = BuildQuiesceResultLocked();
    }
    if (!on_quiesced.is_null()) {
      std::move(on_quiesced).Run(result);
    }
  }

  RegisteredProfileIOQuiesceResult BuildQuiesceResultLocked() const
      EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    RegisteredProfileIOQuiesceResult result;
    result.outstanding_at_begin = outstanding_at_begin_;
    result.succeeded_after_begin = succeeded_after_begin_;
    result.failed_after_begin = failed_after_begin_;
    result.abandoned_after_begin = abandoned_after_begin_;

    const size_t completed_after_begin =
        result.succeeded_after_begin + result.failed_after_begin +
        result.abandoned_after_begin;
    CHECK_EQ(completed_after_begin, result.outstanding_at_begin);
    if (result.outstanding_at_begin == 0) {
      result.status =
          RegisteredProfileIOQuiesceStatus::
              kNoOutstandingRegisteredOperations;
    } else if (result.abandoned_after_begin != 0) {
      result.status =
          RegisteredProfileIOQuiesceStatus::
              kOutstandingRegisteredOperationAbandoned;
    } else if (result.failed_after_begin != 0) {
      result.status =
          RegisteredProfileIOQuiesceStatus::
              kOutstandingRegisteredOperationFailed;
    } else {
      result.status =
          RegisteredProfileIOQuiesceStatus::
              kAllOutstandingRegisteredOperationsSucceeded;
    }
    return result;
  }

  const scoped_refptr<base::SequencedTaskRunner> owner_task_runner_;
  base::Lock lock_;
  bool accepting_profile_io_ GUARDED_BY(lock_) = true;
  bool quiesce_started_ GUARDED_BY(lock_) = false;
  bool cancelled_ GUARDED_BY(lock_) = false;
  bool completion_posted_ GUARDED_BY(lock_) = false;
  size_t profile_io_holds_ GUARDED_BY(lock_) = 0;
  size_t outstanding_at_begin_ GUARDED_BY(lock_) = 0;
  size_t succeeded_after_begin_ GUARDED_BY(lock_) = 0;
  size_t failed_after_begin_ GUARDED_BY(lock_) = 0;
  size_t abandoned_after_begin_ GUARDED_BY(lock_) = 0;
  uint64_t cancellation_generation_ GUARDED_BY(lock_) = 0;
  QuiesceCallback on_quiesced_ GUARDED_BY(lock_);
};

WasmProfileShutdownCoordinator::ProfileIOHold::ProfileIOHold(
    scoped_refptr<State> state)
    : state_(std::move(state)) {}

WasmProfileShutdownCoordinator::ProfileIOHold::ProfileIOHold(
    ProfileIOHold&& other) noexcept = default;

WasmProfileShutdownCoordinator::ProfileIOHold&
WasmProfileShutdownCoordinator::ProfileIOHold::operator=(
    ProfileIOHold&& other) noexcept {
  if (this != &other) {
    Reset();
    state_ = std::move(other.state_);
  }
  return *this;
}

WasmProfileShutdownCoordinator::ProfileIOHold::~ProfileIOHold() {
  Reset();
}

bool WasmProfileShutdownCoordinator::ProfileIOHold::Complete(
    ProfileIOCompletion completion) {
  if (!state_) {
    return false;
  }
  CHECK(completion == ProfileIOCompletion::kSucceeded ||
        completion == ProfileIOCompletion::kFailed);
  state_->ReleaseProfileIOHold(
      completion == ProfileIOCompletion::kSucceeded
          ? ProfileIOHoldDisposition::kSucceeded
          : ProfileIOHoldDisposition::kFailed);
  state_.reset();
  return true;
}

void WasmProfileShutdownCoordinator::ProfileIOHold::Reset() {
  if (state_) {
    state_->ReleaseProfileIOHold(ProfileIOHoldDisposition::kAbandoned);
    state_.reset();
  }
}

WasmProfileShutdownCoordinator::WasmProfileShutdownCoordinator(
    scoped_refptr<base::SequencedTaskRunner> owner_task_runner)
    : state_(base::MakeRefCounted<State>(std::move(owner_task_runner))) {
  CHECK(state_->RunsTasksInCurrentSequence());
}

WasmProfileShutdownCoordinator::~WasmProfileShutdownCoordinator() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  Cancel();
}

std::optional<WasmProfileShutdownCoordinator::ProfileIOHold>
WasmProfileShutdownCoordinator::TryAcquireProfileIO() {
  return state_->TryAcquireProfileIO();
}

bool WasmProfileShutdownCoordinator::BeginQuiesce(
    QuiesceCallback on_quiesced) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  DCHECK(state_->RunsTasksInCurrentSequence());
  return state_->BeginQuiesce(std::move(on_quiesced));
}

void WasmProfileShutdownCoordinator::Cancel() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  DCHECK(state_->RunsTasksInCurrentSequence());
  state_->Cancel();
}
