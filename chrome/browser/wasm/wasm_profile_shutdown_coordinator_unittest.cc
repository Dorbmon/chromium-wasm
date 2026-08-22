// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_shutdown_coordinator.h"

#include <memory>
#include <optional>
#include <utility>

#include "base/check.h"
#include "base/functional/bind.h"
#include "base/synchronization/waitable_event.h"
#include "base/task/sequenced_task_runner.h"
#include "base/test/task_environment.h"
#include "base/threading/thread.h"
#include "build/build_config.h"
#include "testing/gtest/include/gtest/gtest.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_profile_shutdown_coordinator_unittests must only be built for WebAssembly"
#endif

namespace {

class WasmProfileShutdownCoordinatorTest : public testing::Test {
 protected:
  std::unique_ptr<WasmProfileShutdownCoordinator> CreateCoordinator() {
    return std::make_unique<WasmProfileShutdownCoordinator>(
        base::SequencedTaskRunner::GetCurrentDefault());
  }

  base::test::TaskEnvironment task_environment_;
};

using ProfileIOCompletion =
    WasmProfileShutdownCoordinator::ProfileIOCompletion;
using QuiesceResult =
    WasmProfileShutdownCoordinator::RegisteredProfileIOQuiesceResult;
using QuiesceStatus =
    WasmProfileShutdownCoordinator::RegisteredProfileIOQuiesceStatus;

void RecordQuiesceResult(std::optional<QuiesceResult>* result,
                         QuiesceResult observed) {
  *result = observed;
}

void RecordQuiesceResultOnOwnerSequence(
    scoped_refptr<base::SequencedTaskRunner> owner_task_runner,
    bool* completed,
    std::optional<QuiesceResult>* result,
    QuiesceResult observed) {
  EXPECT_TRUE(owner_task_runner->RunsTasksInCurrentSequence());
  *completed = true;
  *result = observed;
}

TEST_F(WasmProfileShutdownCoordinatorTest,
       ZeroOutstandingHoldsCompleteAsynchronously) {
  std::unique_ptr<WasmProfileShutdownCoordinator> coordinator =
      CreateCoordinator();
  std::optional<QuiesceResult> result;

  EXPECT_TRUE(coordinator->BeginQuiesce(
      base::BindOnce(&RecordQuiesceResult, &result)));
  EXPECT_FALSE(result.has_value());
  EXPECT_FALSE(coordinator->TryAcquireProfileIO().has_value());

  task_environment_.RunUntilIdle();
  ASSERT_TRUE(result.has_value());
  EXPECT_EQ(result->status,
            QuiesceStatus::kNoOutstandingRegisteredOperations);
  EXPECT_EQ(result->outstanding_at_begin, 0u);
  EXPECT_EQ(result->succeeded_after_begin, 0u);
  EXPECT_EQ(result->failed_after_begin, 0u);
  EXPECT_EQ(result->abandoned_after_begin, 0u);
  EXPECT_FALSE(result->AllOutstandingRegisteredOperationsSucceeded());
}

TEST_F(WasmProfileShutdownCoordinatorTest,
       OutstandingSuccessfulHoldDefersCompletionAndClosesAdmissions) {
  std::unique_ptr<WasmProfileShutdownCoordinator> coordinator =
      CreateCoordinator();
  std::optional<WasmProfileShutdownCoordinator::ProfileIOHold> hold =
      coordinator->TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());
  std::optional<QuiesceResult> result;

  EXPECT_TRUE(coordinator->BeginQuiesce(
      base::BindOnce(&RecordQuiesceResult, &result)));
  EXPECT_FALSE(coordinator->TryAcquireProfileIO().has_value());
  task_environment_.RunUntilIdle();
  EXPECT_FALSE(result.has_value());

  EXPECT_TRUE(hold->Complete(ProfileIOCompletion::kSucceeded));
  EXPECT_FALSE(hold->Complete(ProfileIOCompletion::kSucceeded));
  EXPECT_FALSE(result.has_value());
  task_environment_.RunUntilIdle();
  ASSERT_TRUE(result.has_value());
  EXPECT_EQ(result->status,
            QuiesceStatus::kAllOutstandingRegisteredOperationsSucceeded);
  EXPECT_EQ(result->outstanding_at_begin, 1u);
  EXPECT_EQ(result->succeeded_after_begin, 1u);
  EXPECT_EQ(result->failed_after_begin, 0u);
  EXPECT_EQ(result->abandoned_after_begin, 0u);
  EXPECT_TRUE(result->AllOutstandingRegisteredOperationsSucceeded());
}

TEST_F(WasmProfileShutdownCoordinatorTest,
       ExplicitFailureIsReportedAfterAllOutstandingHoldsComplete) {
  std::unique_ptr<WasmProfileShutdownCoordinator> coordinator =
      CreateCoordinator();
  std::optional<WasmProfileShutdownCoordinator::ProfileIOHold> succeeded =
      coordinator->TryAcquireProfileIO();
  std::optional<WasmProfileShutdownCoordinator::ProfileIOHold> failed =
      coordinator->TryAcquireProfileIO();
  ASSERT_TRUE(succeeded.has_value());
  ASSERT_TRUE(failed.has_value());
  std::optional<QuiesceResult> result;

  EXPECT_TRUE(coordinator->BeginQuiesce(
      base::BindOnce(&RecordQuiesceResult, &result)));
  EXPECT_TRUE(succeeded->Complete(ProfileIOCompletion::kSucceeded));
  task_environment_.RunUntilIdle();
  EXPECT_FALSE(result.has_value());
  EXPECT_TRUE(failed->Complete(ProfileIOCompletion::kFailed));

  task_environment_.RunUntilIdle();
  ASSERT_TRUE(result.has_value());
  EXPECT_EQ(result->status,
            QuiesceStatus::kOutstandingRegisteredOperationFailed);
  EXPECT_EQ(result->outstanding_at_begin, 2u);
  EXPECT_EQ(result->succeeded_after_begin, 1u);
  EXPECT_EQ(result->failed_after_begin, 1u);
  EXPECT_EQ(result->abandoned_after_begin, 0u);
  EXPECT_FALSE(result->AllOutstandingRegisteredOperationsSucceeded());
}

TEST_F(WasmProfileShutdownCoordinatorTest,
       UncompletedOutstandingHoldIsReportedAsAbandoned) {
  std::unique_ptr<WasmProfileShutdownCoordinator> coordinator =
      CreateCoordinator();
  std::optional<WasmProfileShutdownCoordinator::ProfileIOHold> hold =
      coordinator->TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());
  std::optional<QuiesceResult> result;

  EXPECT_TRUE(coordinator->BeginQuiesce(
      base::BindOnce(&RecordQuiesceResult, &result)));
  hold.reset();

  task_environment_.RunUntilIdle();
  ASSERT_TRUE(result.has_value());
  EXPECT_EQ(result->status,
            QuiesceStatus::kOutstandingRegisteredOperationAbandoned);
  EXPECT_EQ(result->outstanding_at_begin, 1u);
  EXPECT_EQ(result->succeeded_after_begin, 0u);
  EXPECT_EQ(result->failed_after_begin, 0u);
  EXPECT_EQ(result->abandoned_after_begin, 1u);
  EXPECT_FALSE(result->AllOutstandingRegisteredOperationsSucceeded());
}

TEST_F(WasmProfileShutdownCoordinatorTest,
       CompletionBeforeQuiesceIsOutsideTheNewEpoch) {
  std::unique_ptr<WasmProfileShutdownCoordinator> coordinator =
      CreateCoordinator();
  std::optional<WasmProfileShutdownCoordinator::ProfileIOHold> hold =
      coordinator->TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());
  ASSERT_TRUE(hold->Complete(ProfileIOCompletion::kFailed));
  std::optional<QuiesceResult> result;

  EXPECT_TRUE(coordinator->BeginQuiesce(
      base::BindOnce(&RecordQuiesceResult, &result)));

  task_environment_.RunUntilIdle();
  ASSERT_TRUE(result.has_value());
  EXPECT_EQ(result->status,
            QuiesceStatus::kNoOutstandingRegisteredOperations);
  EXPECT_EQ(result->outstanding_at_begin, 0u);
  EXPECT_EQ(result->failed_after_begin, 0u);
}

TEST_F(WasmProfileShutdownCoordinatorTest,
       CancellationSuppressesPendingCompletionAndDuplicateBegin) {
  std::unique_ptr<WasmProfileShutdownCoordinator> coordinator =
      CreateCoordinator();
  std::optional<WasmProfileShutdownCoordinator::ProfileIOHold> hold =
      coordinator->TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());
  std::optional<QuiesceResult> result;

  EXPECT_TRUE(coordinator->BeginQuiesce(
      base::BindOnce(&RecordQuiesceResult, &result)));
  EXPECT_FALSE(coordinator->BeginQuiesce(base::BindOnce(
      [](QuiesceResult) {})));
  coordinator->Cancel();
  EXPECT_FALSE(coordinator->TryAcquireProfileIO().has_value());

  EXPECT_TRUE(hold->Complete(ProfileIOCompletion::kSucceeded));
  task_environment_.RunUntilIdle();
  EXPECT_FALSE(result.has_value());
}

TEST_F(WasmProfileShutdownCoordinatorTest,
       CancellationSuppressesAlreadyPostedZeroHoldCompletion) {
  std::unique_ptr<WasmProfileShutdownCoordinator> coordinator =
      CreateCoordinator();
  std::optional<QuiesceResult> result;

  EXPECT_TRUE(coordinator->BeginQuiesce(
      base::BindOnce(&RecordQuiesceResult, &result)));
  coordinator->Cancel();

  task_environment_.RunUntilIdle();
  EXPECT_FALSE(result.has_value());
  EXPECT_FALSE(coordinator->TryAcquireProfileIO().has_value());
}

TEST_F(WasmProfileShutdownCoordinatorTest,
       CrossThreadReleaseDeliversCompletionOnOwnerSequence) {
  std::unique_ptr<WasmProfileShutdownCoordinator> coordinator =
      CreateCoordinator();
  std::optional<WasmProfileShutdownCoordinator::ProfileIOHold> hold =
      coordinator->TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());

  bool completed = false;
  std::optional<QuiesceResult> result;
  scoped_refptr<base::SequencedTaskRunner> owner_task_runner =
      base::SequencedTaskRunner::GetCurrentDefault();
  EXPECT_TRUE(coordinator->BeginQuiesce(base::BindOnce(
      &RecordQuiesceResultOnOwnerSequence, std::move(owner_task_runner),
      &completed, &result)));

  base::Thread worker("WasmProfileShutdownCoordinatorTest");
  ASSERT_TRUE(worker.Start());
  base::WaitableEvent released;
  ASSERT_TRUE(worker.task_runner()->PostTask(
      FROM_HERE,
      base::BindOnce(
          [](std::optional<WasmProfileShutdownCoordinator::ProfileIOHold> hold,
             base::WaitableEvent* released) {
            CHECK(hold->Complete(ProfileIOCompletion::kSucceeded));
            released->Signal();
          },
          std::move(hold), &released)));
  released.Wait();
  EXPECT_FALSE(completed);

  task_environment_.RunUntilIdle();
  EXPECT_TRUE(completed);
  ASSERT_TRUE(result.has_value());
  EXPECT_EQ(result->status,
            QuiesceStatus::kAllOutstandingRegisteredOperationsSucceeded);
  EXPECT_EQ(result->outstanding_at_begin, 1u);
  EXPECT_EQ(result->succeeded_after_begin, 1u);
  worker.Stop();
}

}  // namespace
