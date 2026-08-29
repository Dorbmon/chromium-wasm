// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_ordered_drain_lifecycle.h"

#include <utility>

#include "base/check.h"

scoped_refptr<WasmProfileOrderedDrainLifecycle::Observation>
WasmProfileOrderedDrainLifecycle::Observation::Create() {
  return base::WrapRefCounted(new Observation());
}

WasmProfileOrderedDrainLifecycle::Observation::Observation() = default;

WasmProfileOrderedDrainLifecycle::Observation::~Observation() = default;

std::optional<WasmProfileOrderedDrainLifecycle::ProfileIOHold>
WasmProfileOrderedDrainLifecycle::Observation::TryAcquireProfileIO() {
  base::AutoLock lock(lock_);
  if (status_ != Status::kAcceptingRegisteredProfileIO) {
    return std::nullopt;
  }
  ++admitted_operations_;
  ++active_holds_;
  return ProfileIOHold(base::WrapRefCounted(this));
}

bool WasmProfileOrderedDrainLifecycle::Observation::BeginQuiesce() {
  base::AutoLock lock(lock_);
  if (status_ != Status::kAcceptingRegisteredProfileIO) {
    return false;
  }

  outstanding_at_begin_ = active_holds_;
  status_ = Status::kWaitingForRegisteredProfileIO;
  UpdateQuiesceStatusLocked();
  return true;
}

bool WasmProfileOrderedDrainLifecycle::Observation::
    AbortBeforePostContentDrain() {
  base::AutoLock lock(lock_);
  switch (status_) {
    case Status::kAcceptingRegisteredProfileIO:
    case Status::kWaitingForRegisteredProfileIO:
    case Status::kReadyForPostContentDrain:
      status_ = Status::kAbortedBeforePostContentDrain;
      return true;
    case Status::kRegisteredProfileIONotClean:
    case Status::kAbortedBeforePostContentDrain:
    case Status::kPostContentDrainPermitClaimed:
    case Status::kPostContentDrainPermitRetired:
    case Status::kPostContentFailureRetirementPermitClaimed:
    case Status::kPostContentFailureRetirementPermitRetired:
      return false;
  }
  return false;
}

void WasmProfileOrderedDrainLifecycle::Observation::ReleaseProfileIOHold(
    ProfileIOHoldDisposition disposition) {
  base::AutoLock lock(lock_);
  CHECK_GT(active_holds_, 0u);
  --active_holds_;
  switch (disposition) {
    case ProfileIOHoldDisposition::kSucceeded:
      ++succeeded_operations_;
      break;
    case ProfileIOHoldDisposition::kFailed:
      ++failed_operations_;
      break;
    case ProfileIOHoldDisposition::kAbandoned:
      ++abandoned_operations_;
      break;
  }
  UpdateQuiesceStatusLocked();
}

WasmProfileOrderedDrainLifecycle::Result
WasmProfileOrderedDrainLifecycle::Observation::GetResult() const {
  base::AutoLock lock(lock_);
  Result result;
  result.status = status_;
  result.profile_io = BuildProfileIOQuiesceResultLocked();
  return result;
}

std::optional<WasmProfileOrderedDrainLifecycle::PostContentDrainPermit>
WasmProfileOrderedDrainLifecycle::Observation::ClaimPostContentDrain() {
  base::AutoLock lock(lock_);
  if (status_ != Status::kReadyForPostContentDrain) {
    return std::nullopt;
  }

  ProfileIOQuiesceResult profile_io = BuildProfileIOQuiesceResultLocked();
  CHECK(profile_io.Succeeded());
  status_ = Status::kPostContentDrainPermitClaimed;
  return PostContentDrainPermit(base::WrapRefCounted(this),
                                 std::move(profile_io));
}

std::optional<
    WasmProfileOrderedDrainLifecycle::PostContentFailureRetirementPermit>
WasmProfileOrderedDrainLifecycle::Observation::
    ClaimPostContentFailureRetirement() {
  base::AutoLock lock(lock_);
  if (status_ != Status::kRegisteredProfileIONotClean) {
    return std::nullopt;
  }

  ProfileIOQuiesceResult profile_io = BuildProfileIOQuiesceResultLocked();
  CHECK(!profile_io.Succeeded());
  CHECK_NE(profile_io.status, ProfileIOQuiesceStatus::kWaiting);
  status_ = Status::kPostContentFailureRetirementPermitClaimed;
  return PostContentFailureRetirementPermit(base::WrapRefCounted(this),
                                             std::move(profile_io));
}

void WasmProfileOrderedDrainLifecycle::Observation::
    RetirePostContentDrainPermit() {
  base::AutoLock lock(lock_);
  if (status_ == Status::kPostContentDrainPermitClaimed) {
    status_ = Status::kPostContentDrainPermitRetired;
  }
}

void WasmProfileOrderedDrainLifecycle::Observation::
    RetirePostContentFailureRetirementPermit() {
  base::AutoLock lock(lock_);
  if (status_ == Status::kPostContentFailureRetirementPermitClaimed) {
    status_ = Status::kPostContentFailureRetirementPermitRetired;
  }
}

void WasmProfileOrderedDrainLifecycle::Observation::
    UpdateQuiesceStatusLocked() {
  if (status_ != Status::kWaitingForRegisteredProfileIO ||
      active_holds_ != 0) {
    return;
  }

  status_ = BuildProfileIOQuiesceResultLocked().Succeeded()
                ? Status::kReadyForPostContentDrain
                : Status::kRegisteredProfileIONotClean;
}

WasmProfileOrderedDrainLifecycle::ProfileIOQuiesceResult
WasmProfileOrderedDrainLifecycle::Observation::
    BuildProfileIOQuiesceResultLocked() const {
  ProfileIOQuiesceResult result;
  result.admitted_operations = admitted_operations_;
  result.outstanding_at_begin = outstanding_at_begin_;
  result.succeeded_operations = succeeded_operations_;
  result.failed_operations = failed_operations_;
  result.abandoned_operations = abandoned_operations_;

  if (active_holds_ != 0) {
    result.status = ProfileIOQuiesceStatus::kWaiting;
  } else if (abandoned_operations_ != 0) {
    result.status = ProfileIOQuiesceStatus::kRegisteredOperationAbandoned;
  } else if (failed_operations_ != 0) {
    result.status = ProfileIOQuiesceStatus::kRegisteredOperationFailed;
  } else {
    CHECK_EQ(succeeded_operations_, admitted_operations_);
    result.status =
        ProfileIOQuiesceStatus::kAllRegisteredOperationsSucceeded;
  }
  return result;
}

WasmProfileOrderedDrainLifecycle::ProfileIOHold::ProfileIOHold(
    scoped_refptr<Observation> observation)
    : observation_(std::move(observation)) {}

WasmProfileOrderedDrainLifecycle::ProfileIOHold::ProfileIOHold(
    ProfileIOHold&& other) noexcept = default;

WasmProfileOrderedDrainLifecycle::ProfileIOHold&
WasmProfileOrderedDrainLifecycle::ProfileIOHold::operator=(
    ProfileIOHold&& other) noexcept {
  if (this != &other) {
    Reset();
    observation_ = std::move(other.observation_);
  }
  return *this;
}

WasmProfileOrderedDrainLifecycle::ProfileIOHold::~ProfileIOHold() {
  Reset();
}

bool WasmProfileOrderedDrainLifecycle::ProfileIOHold::Complete(
    ProfileIOCompletion completion) {
  if (!observation_) {
    return false;
  }
  CHECK(completion == ProfileIOCompletion::kSucceeded ||
        completion == ProfileIOCompletion::kFailed);
  scoped_refptr<Observation> observation = std::move(observation_);
  observation->ReleaseProfileIOHold(
      completion == ProfileIOCompletion::kSucceeded
          ? Observation::ProfileIOHoldDisposition::kSucceeded
          : Observation::ProfileIOHoldDisposition::kFailed);
  return true;
}

void WasmProfileOrderedDrainLifecycle::ProfileIOHold::Reset() {
  if (!observation_) {
    return;
  }
  scoped_refptr<Observation> observation = std::move(observation_);
  observation->ReleaseProfileIOHold(
      Observation::ProfileIOHoldDisposition::kAbandoned);
}

WasmProfileOrderedDrainLifecycle::PostContentDrainPermit::
    PostContentDrainPermit(scoped_refptr<Observation> observation,
                           ProfileIOQuiesceResult profile_io)
    : observation_(std::move(observation)),
      profile_io_(std::move(profile_io)) {}

WasmProfileOrderedDrainLifecycle::PostContentDrainPermit::
    PostContentDrainPermit(PostContentDrainPermit&& other) noexcept = default;

WasmProfileOrderedDrainLifecycle::PostContentDrainPermit&
WasmProfileOrderedDrainLifecycle::PostContentDrainPermit::operator=(
    PostContentDrainPermit&& other) noexcept {
  if (this != &other) {
    Reset();
    observation_ = std::move(other.observation_);
    profile_io_ = std::move(other.profile_io_);
  }
  return *this;
}

WasmProfileOrderedDrainLifecycle::PostContentDrainPermit::
    ~PostContentDrainPermit() {
  Reset();
}

std::optional<WasmProfileOrderedDrainLifecycle::ProfileIOQuiesceResult>
WasmProfileOrderedDrainLifecycle::PostContentDrainPermit::
    GetProfileIOQuiesceResult() const {
  if (!observation_) {
    return std::nullopt;
  }
  return profile_io_;
}

void WasmProfileOrderedDrainLifecycle::PostContentDrainPermit::Reset() {
  if (!observation_) {
    return;
  }
  scoped_refptr<Observation> observation = std::move(observation_);
  observation->RetirePostContentDrainPermit();
}

WasmProfileOrderedDrainLifecycle::PostContentFailureRetirementPermit::
    PostContentFailureRetirementPermit(scoped_refptr<Observation> observation,
                                       ProfileIOQuiesceResult profile_io)
    : observation_(std::move(observation)),
      profile_io_(std::move(profile_io)) {}

WasmProfileOrderedDrainLifecycle::PostContentFailureRetirementPermit::
    PostContentFailureRetirementPermit(
        PostContentFailureRetirementPermit&& other) noexcept = default;

WasmProfileOrderedDrainLifecycle::PostContentFailureRetirementPermit&
WasmProfileOrderedDrainLifecycle::PostContentFailureRetirementPermit::
operator=(PostContentFailureRetirementPermit&& other) noexcept {
  if (this != &other) {
    Reset();
    observation_ = std::move(other.observation_);
    profile_io_ = std::move(other.profile_io_);
  }
  return *this;
}

WasmProfileOrderedDrainLifecycle::PostContentFailureRetirementPermit::
    ~PostContentFailureRetirementPermit() {
  Reset();
}

std::optional<WasmProfileOrderedDrainLifecycle::ProfileIOQuiesceResult>
WasmProfileOrderedDrainLifecycle::PostContentFailureRetirementPermit::
    GetProfileIOQuiesceResult() const {
  if (!observation_) {
    return std::nullopt;
  }
  return profile_io_;
}

void WasmProfileOrderedDrainLifecycle::PostContentFailureRetirementPermit::
    Reset() {
  if (!observation_) {
    return;
  }
  scoped_refptr<Observation> observation = std::move(observation_);
  observation->RetirePostContentFailureRetirementPermit();
}

WasmProfileOrderedDrainLifecycle::WasmProfileOrderedDrainLifecycle()
    : observation_(Observation::Create()) {}

WasmProfileOrderedDrainLifecycle::~WasmProfileOrderedDrainLifecycle() = default;

std::optional<WasmProfileOrderedDrainLifecycle::ProfileIOHold>
WasmProfileOrderedDrainLifecycle::TryAcquireProfileIO() {
  return observation_->TryAcquireProfileIO();
}

scoped_refptr<WasmProfileOrderedDrainLifecycle::Observation>
WasmProfileOrderedDrainLifecycle::BeginQuiesce() {
  if (!observation_->BeginQuiesce()) {
    return nullptr;
  }
  return observation_;
}

bool WasmProfileOrderedDrainLifecycle::AbortBeforePostContentDrain() {
  return observation_->AbortBeforePostContentDrain();
}
