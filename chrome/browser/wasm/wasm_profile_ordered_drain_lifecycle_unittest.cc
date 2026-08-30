// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_ordered_drain_lifecycle.h"

#include <memory>
#include <optional>
#include <utility>

#include "base/check.h"
#include "base/functional/bind.h"
#include "base/location.h"
#include "base/synchronization/waitable_event.h"
#include "base/threading/thread.h"
#include "build/build_config.h"
#include "testing/gtest/include/gtest/gtest.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_profile_ordered_drain_lifecycle_unittests must only be built for WebAssembly"
#endif

namespace {

using Lifecycle = WasmProfileOrderedDrainLifecycle;
using Observation = Lifecycle::Observation;
using Permit = Lifecycle::PostContentDrainPermit;
using FailureRetirementPermit = Lifecycle::PostContentFailureRetirementPermit;
using ProfileIOCompletion = Lifecycle::ProfileIOCompletion;
using ProfileIOQuiesceStatus = Lifecycle::ProfileIOQuiesceStatus;
using Status = Lifecycle::Status;

std::unique_ptr<Lifecycle> CreateLifecycle() {
  return std::make_unique<Lifecycle>();
}

TEST(WasmProfileOrderedDrainLifecycleTest,
     ZeroHoldEpochPublishesOneCleanPostContentPermit) {
  std::unique_ptr<Lifecycle> lifecycle = CreateLifecycle();

  scoped_refptr<Observation> observation = lifecycle->BeginQuiesce();
  ASSERT_TRUE(observation);
  EXPECT_FALSE(lifecycle->TryAcquireProfileIO().has_value());

  Lifecycle::Result result = observation->GetResult();
  EXPECT_TRUE(result.ReadyForPostContentDrain());
  EXPECT_EQ(result.status, Status::kReadyForPostContentDrain);
  EXPECT_EQ(result.profile_io.status,
            ProfileIOQuiesceStatus::kAllRegisteredOperationsSucceeded);
  EXPECT_EQ(result.profile_io.admitted_operations, 0u);
  EXPECT_EQ(result.profile_io.outstanding_at_begin, 0u);

  std::optional<Permit> permit = observation->ClaimPostContentDrain();
  ASSERT_TRUE(permit.has_value());
  EXPECT_EQ(observation->GetResult().status,
            Status::kPostContentDrainPermitClaimed);
  EXPECT_FALSE(observation->ClaimPostContentDrain().has_value());

  std::optional<Lifecycle::ProfileIOQuiesceResult> permit_result =
      permit->GetProfileIOQuiesceResult();
  ASSERT_TRUE(permit_result.has_value());
  EXPECT_TRUE(permit_result->Succeeded());
  permit.reset();
  EXPECT_EQ(observation->GetResult().status,
            Status::kPostContentDrainPermitRetired);
}

TEST(WasmProfileOrderedDrainLifecycleTest,
     HistoricFailureBeforeQuiesceRejectsTheWholeEpoch) {
  std::unique_ptr<Lifecycle> lifecycle = CreateLifecycle();
  std::optional<Lifecycle::ProfileIOHold> hold =
      lifecycle->TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());
  EXPECT_TRUE(hold->Complete(ProfileIOCompletion::kFailed));

  scoped_refptr<Observation> observation = lifecycle->BeginQuiesce();
  ASSERT_TRUE(observation);
  Lifecycle::Result result = observation->GetResult();
  EXPECT_EQ(result.status, Status::kRegisteredProfileIONotClean);
  EXPECT_EQ(result.profile_io.status,
            ProfileIOQuiesceStatus::kRegisteredOperationFailed);
  EXPECT_EQ(result.profile_io.admitted_operations, 1u);
  EXPECT_EQ(result.profile_io.succeeded_operations, 0u);
  EXPECT_EQ(result.profile_io.failed_operations, 1u);
  EXPECT_EQ(result.profile_io.abandoned_operations, 0u);
  EXPECT_FALSE(observation->ClaimPostContentDrain().has_value());
}

TEST(WasmProfileOrderedDrainLifecycleTest,
     FailedEpochIssuesOneTerminalFailureRetirementPermit) {
  std::unique_ptr<Lifecycle> lifecycle = CreateLifecycle();
  std::optional<Lifecycle::ProfileIOHold> hold =
      lifecycle->TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());
  EXPECT_TRUE(hold->Complete(ProfileIOCompletion::kFailed));

  scoped_refptr<Observation> observation = lifecycle->BeginQuiesce();
  ASSERT_TRUE(observation);
  EXPECT_EQ(observation->GetResult().status,
            Status::kRegisteredProfileIONotClean);
  EXPECT_FALSE(observation->ClaimPostContentDrain().has_value());

  std::optional<FailureRetirementPermit> permit =
      observation->ClaimPostContentFailureRetirement();
  ASSERT_TRUE(permit.has_value());
  EXPECT_EQ(observation->GetResult().status,
            Status::kPostContentFailureRetirementPermitClaimed);
  std::optional<Lifecycle::ProfileIOQuiesceResult> permit_result =
      permit->GetProfileIOQuiesceResult();
  ASSERT_TRUE(permit_result.has_value());
  EXPECT_FALSE(permit_result->Succeeded());
  EXPECT_EQ(permit_result->status,
            ProfileIOQuiesceStatus::kRegisteredOperationFailed);
  EXPECT_FALSE(observation->ClaimPostContentFailureRetirement().has_value());

  permit.reset();
  EXPECT_EQ(observation->GetResult().status,
            Status::kPostContentFailureRetirementPermitRetired);
  EXPECT_FALSE(observation->ClaimPostContentDrain().has_value());
}

TEST(WasmProfileOrderedDrainLifecycleTest,
     CleanEpochRejectsFailureRetirementPermit) {
  std::unique_ptr<Lifecycle> lifecycle = CreateLifecycle();
  scoped_refptr<Observation> observation = lifecycle->BeginQuiesce();
  ASSERT_TRUE(observation);

  EXPECT_TRUE(observation->GetResult().ReadyForPostContentDrain());
  EXPECT_FALSE(observation->ClaimPostContentFailureRetirement().has_value());
}

TEST(WasmProfileOrderedDrainLifecycleTest,
     HistoricAbandonmentBeforeQuiesceRejectsTheWholeEpoch) {
  std::unique_ptr<Lifecycle> lifecycle = CreateLifecycle();
  std::optional<Lifecycle::ProfileIOHold> hold =
      lifecycle->TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());
  hold.reset();

  scoped_refptr<Observation> observation = lifecycle->BeginQuiesce();
  ASSERT_TRUE(observation);
  Lifecycle::Result result = observation->GetResult();
  EXPECT_EQ(result.status, Status::kRegisteredProfileIONotClean);
  EXPECT_EQ(result.profile_io.status,
            ProfileIOQuiesceStatus::kRegisteredOperationAbandoned);
  EXPECT_EQ(result.profile_io.abandoned_operations, 1u);
  EXPECT_FALSE(observation->ClaimPostContentDrain().has_value());

  std::optional<FailureRetirementPermit> permit =
      observation->ClaimPostContentFailureRetirement();
  ASSERT_TRUE(permit.has_value());
  std::optional<Lifecycle::ProfileIOQuiesceResult> permit_result =
      permit->GetProfileIOQuiesceResult();
  ASSERT_TRUE(permit_result.has_value());
  EXPECT_EQ(permit_result->status,
            ProfileIOQuiesceStatus::kRegisteredOperationAbandoned);
  permit.reset();
  EXPECT_EQ(observation->GetResult().status,
            Status::kPostContentFailureRetirementPermitRetired);
}

TEST(WasmProfileOrderedDrainLifecycleTest,
     MixedLifetimeOutcomesRemainVisibleInTheDurableObservation) {
  std::unique_ptr<Lifecycle> lifecycle = CreateLifecycle();
  std::optional<Lifecycle::ProfileIOHold> succeeded_before =
      lifecycle->TryAcquireProfileIO();
  std::optional<Lifecycle::ProfileIOHold> failed_before =
      lifecycle->TryAcquireProfileIO();
  std::optional<Lifecycle::ProfileIOHold> succeeded_after =
      lifecycle->TryAcquireProfileIO();
  std::optional<Lifecycle::ProfileIOHold> abandoned_after =
      lifecycle->TryAcquireProfileIO();
  ASSERT_TRUE(succeeded_before.has_value());
  ASSERT_TRUE(failed_before.has_value());
  ASSERT_TRUE(succeeded_after.has_value());
  ASSERT_TRUE(abandoned_after.has_value());
  EXPECT_TRUE(succeeded_before->Complete(ProfileIOCompletion::kSucceeded));
  EXPECT_TRUE(failed_before->Complete(ProfileIOCompletion::kFailed));

  scoped_refptr<Observation> observation = lifecycle->BeginQuiesce();
  ASSERT_TRUE(observation);
  EXPECT_EQ(observation->GetResult().status,
            Status::kWaitingForRegisteredProfileIO);
  EXPECT_TRUE(succeeded_after->Complete(ProfileIOCompletion::kSucceeded));
  abandoned_after.reset();

  Lifecycle::Result result = observation->GetResult();
  EXPECT_EQ(result.status, Status::kRegisteredProfileIONotClean);
  EXPECT_EQ(result.profile_io.status,
            ProfileIOQuiesceStatus::kRegisteredOperationAbandoned);
  EXPECT_EQ(result.profile_io.admitted_operations, 4u);
  EXPECT_EQ(result.profile_io.outstanding_at_begin, 2u);
  EXPECT_EQ(result.profile_io.succeeded_operations, 2u);
  EXPECT_EQ(result.profile_io.failed_operations, 1u);
  EXPECT_EQ(result.profile_io.abandoned_operations, 1u);
  EXPECT_FALSE(observation->ClaimPostContentDrain().has_value());
}

TEST(WasmProfileOrderedDrainLifecycleTest,
     FailedCompletionAfterQuiesceRejectsThePermit) {
  std::unique_ptr<Lifecycle> lifecycle = CreateLifecycle();
  std::optional<Lifecycle::ProfileIOHold> hold =
      lifecycle->TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());

  scoped_refptr<Observation> observation = lifecycle->BeginQuiesce();
  ASSERT_TRUE(observation);
  EXPECT_EQ(observation->GetResult().status,
            Status::kWaitingForRegisteredProfileIO);
  EXPECT_TRUE(hold->Complete(ProfileIOCompletion::kFailed));

  Lifecycle::Result result = observation->GetResult();
  EXPECT_EQ(result.status, Status::kRegisteredProfileIONotClean);
  EXPECT_EQ(result.profile_io.status,
            ProfileIOQuiesceStatus::kRegisteredOperationFailed);
  EXPECT_EQ(result.profile_io.outstanding_at_begin, 1u);
  EXPECT_FALSE(observation->ClaimPostContentDrain().has_value());

  std::optional<FailureRetirementPermit> failure_retirement_permit =
      observation->ClaimPostContentFailureRetirement();
  ASSERT_TRUE(failure_retirement_permit.has_value());
  std::optional<Lifecycle::ProfileIOQuiesceResult> failure_result =
      failure_retirement_permit->GetProfileIOQuiesceResult();
  ASSERT_TRUE(failure_result.has_value());
  EXPECT_EQ(failure_result->status,
            ProfileIOQuiesceStatus::kRegisteredOperationFailed);
  EXPECT_FALSE(failure_result->Succeeded());
  EXPECT_FALSE(observation->ClaimPostContentDrain().has_value());
  failure_retirement_permit.reset();
  EXPECT_EQ(observation->GetResult().status,
            Status::kPostContentFailureRetirementPermitRetired);
}

TEST(WasmProfileOrderedDrainLifecycleTest,
     AbandonedCompletionAfterQuiesceRejectsThePermit) {
  std::unique_ptr<Lifecycle> lifecycle = CreateLifecycle();
  std::optional<Lifecycle::ProfileIOHold> hold =
      lifecycle->TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());

  scoped_refptr<Observation> observation = lifecycle->BeginQuiesce();
  ASSERT_TRUE(observation);
  hold.reset();

  Lifecycle::Result result = observation->GetResult();
  EXPECT_EQ(result.status, Status::kRegisteredProfileIONotClean);
  EXPECT_EQ(result.profile_io.status,
            ProfileIOQuiesceStatus::kRegisteredOperationAbandoned);
  EXPECT_FALSE(observation->ClaimPostContentDrain().has_value());
}

TEST(WasmProfileOrderedDrainLifecycleTest,
     WorkerCompletionPublishesToAObservationThatOutlivesItsOwner) {
  std::unique_ptr<Lifecycle> lifecycle = CreateLifecycle();
  std::optional<Lifecycle::ProfileIOHold> hold =
      lifecycle->TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());
  scoped_refptr<Observation> observation = lifecycle->BeginQuiesce();
  ASSERT_TRUE(observation);
  lifecycle.reset();

  base::Thread worker("WasmProfileOrderedDrainLifecycleTest");
  ASSERT_TRUE(worker.Start());
  base::WaitableEvent completed;
  ASSERT_TRUE(worker.task_runner()->PostTask(
      FROM_HERE,
      base::BindOnce(
          [](std::optional<Lifecycle::ProfileIOHold> hold,
             base::WaitableEvent* completed) {
            CHECK(hold.has_value());
            CHECK(hold->Complete(ProfileIOCompletion::kSucceeded));
            completed->Signal();
          },
          std::move(hold), &completed)));
  completed.Wait();
  worker.Stop();

  Lifecycle::Result result = observation->GetResult();
  EXPECT_TRUE(result.ReadyForPostContentDrain());
  EXPECT_EQ(result.profile_io.outstanding_at_begin, 1u);
  EXPECT_EQ(result.profile_io.succeeded_operations, 1u);
  std::optional<Permit> permit = observation->ClaimPostContentDrain();
  ASSERT_TRUE(permit.has_value());
  EXPECT_TRUE(permit->GetProfileIOQuiesceResult().has_value());
  permit.reset();
  EXPECT_EQ(observation->GetResult().status,
            Status::kPostContentDrainPermitRetired);
}

TEST(WasmProfileOrderedDrainLifecycleTest,
     AbortRecordsLaterHoldsButPreventsPostContentHandoff) {
  std::unique_ptr<Lifecycle> lifecycle = CreateLifecycle();
  std::optional<Lifecycle::ProfileIOHold> hold =
      lifecycle->TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());
  scoped_refptr<Observation> observation = lifecycle->BeginQuiesce();
  ASSERT_TRUE(observation);

  EXPECT_TRUE(lifecycle->AbortBeforePostContentDrain());
  EXPECT_FALSE(lifecycle->TryAcquireProfileIO().has_value());
  EXPECT_TRUE(hold->Complete(ProfileIOCompletion::kSucceeded));

  Lifecycle::Result result = observation->GetResult();
  EXPECT_EQ(result.status, Status::kAbortedBeforePostContentDrain);
  EXPECT_EQ(result.profile_io.status,
            ProfileIOQuiesceStatus::kAllRegisteredOperationsSucceeded);
  EXPECT_EQ(result.profile_io.succeeded_operations, 1u);
  EXPECT_FALSE(observation->ClaimPostContentDrain().has_value());
}

TEST(WasmProfileOrderedDrainLifecycleTest,
     AbortAfterQuiescePreventsAnOtherwiseCleanHandoff) {
  std::unique_ptr<Lifecycle> lifecycle = CreateLifecycle();
  scoped_refptr<Observation> observation = lifecycle->BeginQuiesce();
  ASSERT_TRUE(observation);
  EXPECT_TRUE(observation->GetResult().ReadyForPostContentDrain());

  EXPECT_TRUE(lifecycle->AbortBeforePostContentDrain());
  EXPECT_EQ(observation->GetResult().status,
            Status::kAbortedBeforePostContentDrain);
  EXPECT_FALSE(observation->ClaimPostContentDrain().has_value());
}

TEST(WasmProfileOrderedDrainLifecycleTest,
     DroppedPermitIsTerminalAndCannotBeClaimedAgain) {
  std::unique_ptr<Lifecycle> lifecycle = CreateLifecycle();
  scoped_refptr<Observation> observation = lifecycle->BeginQuiesce();
  ASSERT_TRUE(observation);

  {
    std::optional<Permit> permit = observation->ClaimPostContentDrain();
    ASSERT_TRUE(permit.has_value());
    EXPECT_EQ(observation->GetResult().status,
              Status::kPostContentDrainPermitClaimed);
  }

  EXPECT_EQ(observation->GetResult().status,
            Status::kPostContentDrainPermitRetired);
  EXPECT_FALSE(observation->ClaimPostContentDrain().has_value());
  EXPECT_FALSE(lifecycle->AbortBeforePostContentDrain());
}

TEST(WasmProfileOrderedDrainLifecycleTest,
     WorkerDroppedPermitIsAThreadSafeTerminalRetirement) {
  std::unique_ptr<Lifecycle> lifecycle = CreateLifecycle();
  scoped_refptr<Observation> observation = lifecycle->BeginQuiesce();
  ASSERT_TRUE(observation);
  std::optional<Permit> permit = observation->ClaimPostContentDrain();
  ASSERT_TRUE(permit.has_value());

  base::Thread worker("WasmProfileOrderedDrainLifecyclePermitTest");
  ASSERT_TRUE(worker.Start());
  base::WaitableEvent completed;
  ASSERT_TRUE(worker.task_runner()->PostTask(
      FROM_HERE,
      base::BindOnce(
          [](Permit permit, base::WaitableEvent* completed) {
            {
              Permit local_permit = std::move(permit);
              CHECK(local_permit.GetProfileIOQuiesceResult().has_value());
            }
            completed->Signal();
          },
          std::move(*permit), &completed)));
  permit.reset();
  completed.Wait();
  worker.Stop();

  EXPECT_EQ(observation->GetResult().status,
            Status::kPostContentDrainPermitRetired);
  EXPECT_FALSE(observation->ClaimPostContentDrain().has_value());
}

TEST(WasmProfileOrderedDrainLifecycleTest,
     MovedPermitDefersRetirementUntilTheMovedToPermitIsDropped) {
  std::unique_ptr<Lifecycle> lifecycle = CreateLifecycle();
  scoped_refptr<Observation> observation = lifecycle->BeginQuiesce();
  ASSERT_TRUE(observation);

  {
    std::optional<Permit> permit = observation->ClaimPostContentDrain();
    ASSERT_TRUE(permit.has_value());
    Permit moved_permit = std::move(*permit);
    permit.reset();
    EXPECT_TRUE(moved_permit.GetProfileIOQuiesceResult().has_value());
    EXPECT_EQ(observation->GetResult().status,
              Status::kPostContentDrainPermitClaimed);
  }

  EXPECT_EQ(observation->GetResult().status,
            Status::kPostContentDrainPermitRetired);
  EXPECT_FALSE(observation->ClaimPostContentDrain().has_value());
}

TEST(WasmProfileOrderedDrainLifecycleTest,
     AbortBeforeQuiescePermanentlyRejectsTheEpoch) {
  std::unique_ptr<Lifecycle> lifecycle = CreateLifecycle();
  std::optional<Lifecycle::ProfileIOHold> hold =
      lifecycle->TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());

  EXPECT_TRUE(lifecycle->AbortBeforePostContentDrain());
  EXPECT_FALSE(lifecycle->BeginQuiesce());
  EXPECT_TRUE(hold->Complete(ProfileIOCompletion::kSucceeded));
}

}  // namespace
