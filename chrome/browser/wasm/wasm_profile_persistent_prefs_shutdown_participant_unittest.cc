// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_persistent_prefs_shutdown_participant.h"

#include <memory>
#include <optional>
#include <utility>

#include "base/functional/bind.h"
#include "base/task/sequenced_task_runner.h"
#include "base/test/task_environment.h"
#include "build/build_config.h"
#include "testing/gtest/include/gtest/gtest.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_profile_persistent_prefs_shutdown_participant_unittests must only be built for WebAssembly"
#endif

namespace {

using Participant = WasmProfilePersistentPrefsShutdownParticipant;
using QuiesceResult =
    WasmProfileShutdownCoordinator::RegisteredProfileIOQuiesceResult;
using QuiesceStatus =
    WasmProfileShutdownCoordinator::RegisteredProfileIOQuiesceStatus;

class CapturingFenceStarter {
 public:
  explicit CapturingFenceStarter(bool accepts) : accepts_(accepts) {}
  CapturingFenceStarter(const CapturingFenceStarter&) = delete;
  CapturingFenceStarter& operator=(const CapturingFenceStarter&) = delete;
  ~CapturingFenceStarter() = default;

  bool Start(Participant::FenceCompletionCallback completion) {
    if (!accepts_) {
      return false;
    }
    completion_ = std::move(completion);
    return true;
  }

  bool has_completion() const { return completion_.has_value(); }

  void Complete(bool success) {
    ASSERT_TRUE(completion_.has_value());
    Participant::FenceCompletionCallback completion = std::move(*completion_);
    completion_.reset();
    std::move(completion).Run(success);
  }

 private:
  const bool accepts_;
  std::optional<Participant::FenceCompletionCallback> completion_;
};

class InlineFenceStarter {
 public:
  InlineFenceStarter(bool completion_result, bool accepts)
      : completion_result_(completion_result), accepts_(accepts) {}
  InlineFenceStarter(const InlineFenceStarter&) = delete;
  InlineFenceStarter& operator=(const InlineFenceStarter&) = delete;
  ~InlineFenceStarter() = default;

  bool Start(Participant::FenceCompletionCallback completion) {
    std::move(completion).Run(completion_result_);
    return accepts_;
  }

 private:
  const bool completion_result_;
  const bool accepts_;
};

class WasmProfilePersistentPrefsShutdownParticipantTest : public testing::Test {
 protected:
  std::unique_ptr<WasmProfileShutdownCoordinator> CreateCoordinator() {
    return std::make_unique<WasmProfileShutdownCoordinator>(
        base::SequencedTaskRunner::GetCurrentDefault());
  }

  base::test::TaskEnvironment task_environment_;
};

void RecordQuiesceResult(std::optional<QuiesceResult>* result,
                         QuiesceResult observed) {
  *result = observed;
}

TEST_F(WasmProfilePersistentPrefsShutdownParticipantTest,
       TrueFenceResultCompletesRegisteredOperationSuccessfully) {
  std::unique_ptr<WasmProfileShutdownCoordinator> coordinator =
      CreateCoordinator();
  std::optional<WasmProfileShutdownCoordinator::ProfileIOHold> hold =
      coordinator->TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());
  CapturingFenceStarter starter(/*accepts=*/true);
  auto participant =
      std::make_unique<Participant>(std::move(*hold),
                                    base::BindOnce(&CapturingFenceStarter::Start,
                                                   base::Unretained(&starter)));

  std::optional<QuiesceResult> result;
  EXPECT_TRUE(coordinator->BeginQuiesce(
      base::BindOnce(&RecordQuiesceResult, &result)));
  task_environment_.RunUntilIdle();
  EXPECT_FALSE(result.has_value());

  EXPECT_TRUE(participant->Start());
  EXPECT_TRUE(starter.has_completion());

  starter.Complete(true);
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

TEST_F(WasmProfilePersistentPrefsShutdownParticipantTest,
       FalseFenceResultCompletesRegisteredOperationAsFailed) {
  std::unique_ptr<WasmProfileShutdownCoordinator> coordinator =
      CreateCoordinator();
  std::optional<WasmProfileShutdownCoordinator::ProfileIOHold> hold =
      coordinator->TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());
  CapturingFenceStarter starter(/*accepts=*/true);
  auto participant =
      std::make_unique<Participant>(std::move(*hold),
                                    base::BindOnce(&CapturingFenceStarter::Start,
                                                   base::Unretained(&starter)));

  std::optional<QuiesceResult> result;
  EXPECT_TRUE(coordinator->BeginQuiesce(
      base::BindOnce(&RecordQuiesceResult, &result)));

  EXPECT_TRUE(participant->Start());

  starter.Complete(false);
  task_environment_.RunUntilIdle();
  ASSERT_TRUE(result.has_value());
  EXPECT_EQ(result->status,
            QuiesceStatus::kOutstandingRegisteredOperationFailed);
  EXPECT_EQ(result->outstanding_at_begin, 1u);
  EXPECT_EQ(result->succeeded_after_begin, 0u);
  EXPECT_EQ(result->failed_after_begin, 1u);
  EXPECT_EQ(result->abandoned_after_begin, 0u);
}

TEST_F(WasmProfilePersistentPrefsShutdownParticipantTest,
       RejectedStarterCompletesRegisteredOperationAsFailed) {
  std::unique_ptr<WasmProfileShutdownCoordinator> coordinator =
      CreateCoordinator();
  std::optional<WasmProfileShutdownCoordinator::ProfileIOHold> hold =
      coordinator->TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());
  CapturingFenceStarter starter(/*accepts=*/false);
  auto participant =
      std::make_unique<Participant>(std::move(*hold),
                                    base::BindOnce(&CapturingFenceStarter::Start,
                                                   base::Unretained(&starter)));
  std::optional<QuiesceResult> result;

  // The hold was admitted before quiesce. A later starter rejection must
  // therefore be visible as an explicit failure in that admission epoch.
  EXPECT_TRUE(coordinator->BeginQuiesce(
      base::BindOnce(&RecordQuiesceResult, &result)));
  EXPECT_FALSE(participant->Start());
  task_environment_.RunUntilIdle();

  ASSERT_TRUE(result.has_value());
  EXPECT_EQ(result->status,
            QuiesceStatus::kOutstandingRegisteredOperationFailed);
  EXPECT_EQ(result->outstanding_at_begin, 1u);
  EXPECT_EQ(result->succeeded_after_begin, 0u);
  EXPECT_EQ(result->failed_after_begin, 1u);
  EXPECT_EQ(result->abandoned_after_begin, 0u);
}

TEST_F(WasmProfilePersistentPrefsShutdownParticipantTest,
       InlineTrueCompletionIsReportedAfterAcceptedStart) {
  std::unique_ptr<WasmProfileShutdownCoordinator> coordinator =
      CreateCoordinator();
  std::optional<WasmProfileShutdownCoordinator::ProfileIOHold> hold =
      coordinator->TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());
  InlineFenceStarter starter(/*completion_result=*/true, /*accepts=*/true);
  auto participant =
      std::make_unique<Participant>(std::move(*hold),
                                    base::BindOnce(&InlineFenceStarter::Start,
                                                   base::Unretained(&starter)));
  std::optional<QuiesceResult> result;

  // An accepted inline completion releases the hold before Start() returns, so
  // begin the epoch after admission but before starting the fence.
  EXPECT_TRUE(coordinator->BeginQuiesce(
      base::BindOnce(&RecordQuiesceResult, &result)));
  EXPECT_TRUE(participant->Start());
  task_environment_.RunUntilIdle();

  ASSERT_TRUE(result.has_value());
  EXPECT_EQ(result->status,
            QuiesceStatus::kAllOutstandingRegisteredOperationsSucceeded);
  EXPECT_EQ(result->succeeded_after_begin, 1u);
  EXPECT_EQ(result->failed_after_begin, 0u);
}

TEST_F(WasmProfilePersistentPrefsShutdownParticipantTest,
       InlineTrueCompletionCannotOverrideRejectedStart) {
  std::unique_ptr<WasmProfileShutdownCoordinator> coordinator =
      CreateCoordinator();
  std::optional<WasmProfileShutdownCoordinator::ProfileIOHold> hold =
      coordinator->TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());
  InlineFenceStarter starter(/*completion_result=*/true, /*accepts=*/false);
  auto participant =
      std::make_unique<Participant>(std::move(*hold),
                                    base::BindOnce(&InlineFenceStarter::Start,
                                                   base::Unretained(&starter)));
  std::optional<QuiesceResult> result;

  EXPECT_TRUE(coordinator->BeginQuiesce(
      base::BindOnce(&RecordQuiesceResult, &result)));
  EXPECT_FALSE(participant->Start());
  task_environment_.RunUntilIdle();

  ASSERT_TRUE(result.has_value());
  EXPECT_EQ(result->status,
            QuiesceStatus::kOutstandingRegisteredOperationFailed);
  EXPECT_EQ(result->succeeded_after_begin, 0u);
  EXPECT_EQ(result->failed_after_begin, 1u);
  EXPECT_EQ(result->abandoned_after_begin, 0u);
}

TEST_F(WasmProfilePersistentPrefsShutdownParticipantTest,
       InlineFalseCompletionIsReportedAfterAcceptedStart) {
  std::unique_ptr<WasmProfileShutdownCoordinator> coordinator =
      CreateCoordinator();
  std::optional<WasmProfileShutdownCoordinator::ProfileIOHold> hold =
      coordinator->TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());
  InlineFenceStarter starter(/*completion_result=*/false, /*accepts=*/true);
  auto participant =
      std::make_unique<Participant>(std::move(*hold),
                                    base::BindOnce(&InlineFenceStarter::Start,
                                                   base::Unretained(&starter)));
  std::optional<QuiesceResult> result;

  EXPECT_TRUE(coordinator->BeginQuiesce(
      base::BindOnce(&RecordQuiesceResult, &result)));
  EXPECT_TRUE(participant->Start());
  task_environment_.RunUntilIdle();

  ASSERT_TRUE(result.has_value());
  EXPECT_EQ(result->status,
            QuiesceStatus::kOutstandingRegisteredOperationFailed);
  EXPECT_EQ(result->succeeded_after_begin, 0u);
  EXPECT_EQ(result->failed_after_begin, 1u);
  EXPECT_EQ(result->abandoned_after_begin, 0u);
}

TEST_F(WasmProfilePersistentPrefsShutdownParticipantTest,
       MissingStarterCompletesRegisteredOperationAsFailed) {
  std::unique_ptr<WasmProfileShutdownCoordinator> coordinator =
      CreateCoordinator();
  std::optional<WasmProfileShutdownCoordinator::ProfileIOHold> hold =
      coordinator->TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());
  auto participant = std::make_unique<Participant>(
      std::move(*hold), Participant::FenceStarter());
  std::optional<QuiesceResult> result;

  EXPECT_TRUE(coordinator->BeginQuiesce(
      base::BindOnce(&RecordQuiesceResult, &result)));
  EXPECT_FALSE(participant->Start());
  task_environment_.RunUntilIdle();

  ASSERT_TRUE(result.has_value());
  EXPECT_EQ(result->status,
            QuiesceStatus::kOutstandingRegisteredOperationFailed);
  EXPECT_EQ(result->succeeded_after_begin, 0u);
  EXPECT_EQ(result->failed_after_begin, 1u);
  EXPECT_EQ(result->abandoned_after_begin, 0u);
}

TEST_F(WasmProfilePersistentPrefsShutdownParticipantTest,
       RepeatStartDoesNotChangePendingFenceOutcome) {
  std::unique_ptr<WasmProfileShutdownCoordinator> coordinator =
      CreateCoordinator();
  std::optional<WasmProfileShutdownCoordinator::ProfileIOHold> hold =
      coordinator->TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());
  CapturingFenceStarter starter(/*accepts=*/true);
  auto participant =
      std::make_unique<Participant>(std::move(*hold),
                                    base::BindOnce(&CapturingFenceStarter::Start,
                                                   base::Unretained(&starter)));

  std::optional<QuiesceResult> result;
  EXPECT_TRUE(coordinator->BeginQuiesce(
      base::BindOnce(&RecordQuiesceResult, &result)));

  EXPECT_TRUE(participant->Start());
  EXPECT_FALSE(participant->Start());

  starter.Complete(true);
  task_environment_.RunUntilIdle();
  ASSERT_TRUE(result.has_value());
  EXPECT_EQ(result->status,
            QuiesceStatus::kAllOutstandingRegisteredOperationsSucceeded);
  EXPECT_EQ(result->succeeded_after_begin, 1u);
  EXPECT_EQ(result->failed_after_begin, 0u);
}

TEST_F(WasmProfilePersistentPrefsShutdownParticipantTest,
       DestructionFailsPendingFenceAndLateCallbackCannotRestoreSuccess) {
  std::unique_ptr<WasmProfileShutdownCoordinator> coordinator =
      CreateCoordinator();
  std::optional<WasmProfileShutdownCoordinator::ProfileIOHold> hold =
      coordinator->TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());
  CapturingFenceStarter starter(/*accepts=*/true);
  auto participant =
      std::make_unique<Participant>(std::move(*hold),
                                    base::BindOnce(&CapturingFenceStarter::Start,
                                                   base::Unretained(&starter)));

  std::optional<QuiesceResult> result;
  EXPECT_TRUE(coordinator->BeginQuiesce(
      base::BindOnce(&RecordQuiesceResult, &result)));

  EXPECT_TRUE(participant->Start());
  participant.reset();
  task_environment_.RunUntilIdle();

  ASSERT_TRUE(result.has_value());
  EXPECT_EQ(result->status,
            QuiesceStatus::kOutstandingRegisteredOperationFailed);
  EXPECT_EQ(result->outstanding_at_begin, 1u);
  EXPECT_EQ(result->succeeded_after_begin, 0u);
  EXPECT_EQ(result->failed_after_begin, 1u);
  EXPECT_EQ(result->abandoned_after_begin, 0u);

  starter.Complete(true);
  task_environment_.RunUntilIdle();
  EXPECT_EQ(result->status,
            QuiesceStatus::kOutstandingRegisteredOperationFailed);
  EXPECT_EQ(result->succeeded_after_begin, 0u);
  EXPECT_EQ(result->failed_after_begin, 1u);
}

TEST_F(WasmProfilePersistentPrefsShutdownParticipantTest,
       CancelFailsPendingFenceAndLateCallbackCannotRestoreSuccess) {
  std::unique_ptr<WasmProfileShutdownCoordinator> coordinator =
      CreateCoordinator();
  std::optional<WasmProfileShutdownCoordinator::ProfileIOHold> hold =
      coordinator->TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());
  CapturingFenceStarter starter(/*accepts=*/true);
  auto participant =
      std::make_unique<Participant>(std::move(*hold),
                                    base::BindOnce(&CapturingFenceStarter::Start,
                                                   base::Unretained(&starter)));

  std::optional<QuiesceResult> result;
  EXPECT_TRUE(coordinator->BeginQuiesce(
      base::BindOnce(&RecordQuiesceResult, &result)));

  EXPECT_TRUE(participant->Start());
  participant->Cancel();
  participant->Cancel();
  task_environment_.RunUntilIdle();

  ASSERT_TRUE(result.has_value());
  EXPECT_EQ(result->status,
            QuiesceStatus::kOutstandingRegisteredOperationFailed);
  EXPECT_EQ(result->outstanding_at_begin, 1u);
  EXPECT_EQ(result->succeeded_after_begin, 0u);
  EXPECT_EQ(result->failed_after_begin, 1u);
  EXPECT_EQ(result->abandoned_after_begin, 0u);

  starter.Complete(true);
  task_environment_.RunUntilIdle();
  EXPECT_EQ(result->status,
            QuiesceStatus::kOutstandingRegisteredOperationFailed);
  EXPECT_EQ(result->succeeded_after_begin, 0u);
  EXPECT_EQ(result->failed_after_begin, 1u);
}

TEST_F(WasmProfilePersistentPrefsShutdownParticipantTest,
       ReentrantStarterOwnerDestructionFailsWithoutUseAfterFree) {
  std::unique_ptr<WasmProfileShutdownCoordinator> coordinator =
      CreateCoordinator();
  std::optional<WasmProfileShutdownCoordinator::ProfileIOHold> hold =
      coordinator->TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());
  std::unique_ptr<Participant> participant;
  participant =
      std::make_unique<Participant>(std::move(*hold),
                                    base::BindOnce(
                                        [](std::unique_ptr<Participant>* owner,
                                           Participant::FenceCompletionCallback
                                               /*completion*/) {
                                          owner->reset();
                                          return true;
                                        },
                                        &participant));
  std::optional<QuiesceResult> result;

  EXPECT_TRUE(coordinator->BeginQuiesce(
      base::BindOnce(&RecordQuiesceResult, &result)));
  EXPECT_FALSE(participant->Start());
  EXPECT_FALSE(participant);
  task_environment_.RunUntilIdle();

  ASSERT_TRUE(result.has_value());
  EXPECT_EQ(result->status,
            QuiesceStatus::kOutstandingRegisteredOperationFailed);
  EXPECT_EQ(result->outstanding_at_begin, 1u);
  EXPECT_EQ(result->succeeded_after_begin, 0u);
  EXPECT_EQ(result->failed_after_begin, 1u);
  EXPECT_EQ(result->abandoned_after_begin, 0u);
}

}  // namespace
