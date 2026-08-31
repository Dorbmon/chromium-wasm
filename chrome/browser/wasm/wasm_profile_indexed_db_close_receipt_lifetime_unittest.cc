// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_indexed_db_close_receipt_lifetime.h"

#include <memory>
#include <optional>
#include <utility>
#include <vector>

#include "base/functional/bind.h"
#include "base/memory/raw_ptr.h"
#include "base/no_destructor.h"
#include "base/test/task_environment.h"
#include "chrome/browser/wasm/wasm_profile_ordered_drain_lifecycle.h"
#include "testing/gtest/include/gtest/gtest.h"

namespace chrome {
namespace {

using Lifecycle = WasmProfileOrderedDrainLifecycle;
using ReceiptLifetime = WasmProfileIndexedDBCloseReceiptLifetime;

struct Events {
  bool cleanup_called = false;
  bool quarantine_called = false;
  bool quarantine_saw_cleanup = false;
  bool completion_called = false;
  bool completion_saw_cleanup = false;
  bool completion_result = true;
};

base::OnceCallback<void(bool)> RecordCompletion(Events* events) {
  return base::BindOnce(
      [](Events* events, bool success) {
        events->completion_called = true;
        events->completion_saw_cleanup = events->cleanup_called;
        events->completion_result = success;
      },
      events);
}

// Mirrors the production participant's ownership rule: a failure before the
// selected bucket's ForceClose callback moves the State into process lifetime,
// preserving the outstanding profile-I/O admission rather than abandoning it.
class TestOwner {
 public:
  TestOwner(Lifecycle::ProfileIOHold profile_io_hold, Events* events)
      : events_(events) {
    state_ = std::make_unique<State>(
        std::move(profile_io_hold), events,
        base::BindOnce(&TestOwner::OnQuarantine,
                       weak_ptr_factory_.GetWeakPtr()));
  }
  TestOwner(const TestOwner&) = delete;
  TestOwner& operator=(const TestOwner&) = delete;
  ~TestOwner() {
    if (!state_ || !state_->HasOutstandingAdmission()) {
      return;
    }
    state_->PrepareForOwnerQuarantine();
    Retain(std::move(state_));
  }

  bool Start() { return state_->Start(); }
  void Cancel() { state_->Cancel(); }
  void ReceiveSelectedBucketCloseReceipt() {
    state_->ReceiveSelectedBucketCloseReceipt();
  }
  void FailBeforeSelectedBucketCloseReceipt() {
    state_->FailBeforeSelectedBucketCloseReceipt();
  }
  bool IsActive() const { return state_ && state_->IsActive(); }

 private:
  class State {
   public:
    State(Lifecycle::ProfileIOHold profile_io_hold,
          Events* events,
          base::OnceClosure quarantine_callback)
        : events_(events),
          lifetime_(std::move(profile_io_hold),
                    std::move(quarantine_callback)) {}

    bool Start() { return lifetime_.Start(RecordCompletion(events_)); }
    void Cancel() {
      lifetime_.Cancel();
      if (lifetime_.IsActive() &&
          !lifetime_.HasSelectedBucketCloseReceipt()) {
        FailBeforeSelectedBucketCloseReceipt();
      }
    }
    bool IsActive() const { return lifetime_.IsActive(); }
    bool HasOutstandingAdmission() const {
      return lifetime_.HasOutstandingAdmission();
    }

    void ReceiveSelectedBucketCloseReceipt() {
      lifetime_.CompleteAfterSelectedBucketCloseReceipt(
          base::BindOnce(&State::Cleanup, base::Unretained(this)));
    }

    void FailBeforeSelectedBucketCloseReceipt() {
      lifetime_.FailBeforeSelectedBucketCloseReceipt(
          base::BindOnce(&State::Cleanup, base::Unretained(this)));
    }

    void PrepareForOwnerQuarantine() {
      lifetime_.Cancel();
      if (lifetime_.IsActive() &&
          !lifetime_.HasSelectedBucketCloseReceipt()) {
        FailBeforeSelectedBucketCloseReceipt();
        return;
      }
      Cleanup();
    }

   private:
    void Cleanup() { events_->cleanup_called = true; }

    raw_ptr<Events> events_;
    ReceiptLifetime lifetime_;
  };

  static void Retain(std::unique_ptr<State> state) {
    static base::NoDestructor<std::vector<std::unique_ptr<State>>>
        quarantined_states;
    quarantined_states->push_back(std::move(state));
  }

  void OnQuarantine() {
    if (!state_ || !state_->IsActive()) {
      return;
    }
    events_->quarantine_called = true;
    events_->quarantine_saw_cleanup = events_->cleanup_called;
    if (state_) {
      Retain(std::move(state_));
    }
  }

  raw_ptr<Events> events_;
  std::unique_ptr<State> state_;
  base::WeakPtrFactory<TestOwner> weak_ptr_factory_{this};
};

TEST(WasmProfileIndexedDBCloseReceiptLifetimeTest,
     SelectedBucketReceiptAndPostedDeliveryOwnAdmission) {
  base::test::TaskEnvironment task_environment;
  Lifecycle lifecycle;
  std::optional<Lifecycle::ProfileIOHold> hold =
      lifecycle.TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());
  scoped_refptr<Lifecycle::Observation> observation = lifecycle.BeginQuiesce();
  ASSERT_TRUE(observation);

  Events events;
  TestOwner owner(std::move(*hold), &events);
  ASSERT_TRUE(owner.Start());
  EXPECT_EQ(observation->GetResult().status,
            Lifecycle::Status::kWaitingForRegisteredProfileIO);
  EXPECT_FALSE(observation->ClaimPostContentDrain().has_value());

  owner.ReceiveSelectedBucketCloseReceipt();
  EXPECT_TRUE(events.cleanup_called);
  EXPECT_TRUE(owner.IsActive());
  EXPECT_FALSE(events.completion_called);
  EXPECT_EQ(observation->GetResult().status,
            Lifecycle::Status::kWaitingForRegisteredProfileIO);
  EXPECT_FALSE(observation->ClaimPostContentDrain().has_value());

  task_environment.RunUntilIdle();
  EXPECT_TRUE(events.completion_called);
  EXPECT_TRUE(events.completion_saw_cleanup);
  EXPECT_TRUE(events.completion_result);
  EXPECT_FALSE(owner.IsActive());
  const Lifecycle::Result result = observation->GetResult();
  EXPECT_EQ(result.status, Lifecycle::Status::kReadyForPostContentDrain);
  EXPECT_EQ(result.profile_io.succeeded_operations, 1u);
  EXPECT_EQ(result.profile_io.failed_operations, 0u);
  EXPECT_EQ(result.profile_io.abandoned_operations, 0u);
  EXPECT_TRUE(observation->ClaimPostContentDrain().has_value());
}

TEST(WasmProfileIndexedDBCloseReceiptLifetimeTest,
     CancellationBeforePostedDeliveryIsTerminalFailure) {
  base::test::TaskEnvironment task_environment;
  Lifecycle lifecycle;
  std::optional<Lifecycle::ProfileIOHold> hold =
      lifecycle.TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());
  scoped_refptr<Lifecycle::Observation> observation = lifecycle.BeginQuiesce();
  ASSERT_TRUE(observation);

  Events events;
  TestOwner owner(std::move(*hold), &events);
  ASSERT_TRUE(owner.Start());
  owner.ReceiveSelectedBucketCloseReceipt();
  owner.Cancel();
  EXPECT_TRUE(events.cleanup_called);
  EXPECT_FALSE(events.completion_called);
  EXPECT_EQ(observation->GetResult().status,
            Lifecycle::Status::kWaitingForRegisteredProfileIO);

  task_environment.RunUntilIdle();
  EXPECT_TRUE(events.completion_called);
  EXPECT_TRUE(events.completion_saw_cleanup);
  EXPECT_FALSE(events.completion_result);
  const Lifecycle::Result result = observation->GetResult();
  EXPECT_EQ(result.status, Lifecycle::Status::kRegisteredProfileIONotClean);
  EXPECT_EQ(result.profile_io.succeeded_operations, 0u);
  EXPECT_EQ(result.profile_io.failed_operations, 1u);
  EXPECT_EQ(result.profile_io.abandoned_operations, 0u);
  EXPECT_FALSE(observation->ClaimPostContentDrain().has_value());
  EXPECT_TRUE(observation->ClaimPostContentFailureRetirement().has_value());
}

TEST(WasmProfileIndexedDBCloseReceiptLifetimeTest,
     CancellationBeforeReceiptQuarantinesOutstandingAdmission) {
  base::test::TaskEnvironment task_environment;
  Lifecycle lifecycle;
  std::optional<Lifecycle::ProfileIOHold> hold =
      lifecycle.TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());
  scoped_refptr<Lifecycle::Observation> observation = lifecycle.BeginQuiesce();
  ASSERT_TRUE(observation);

  Events events;
  TestOwner owner(std::move(*hold), &events);
  ASSERT_TRUE(owner.Start());
  owner.Cancel();
  EXPECT_TRUE(events.cleanup_called);
  EXPECT_FALSE(events.completion_called);

  task_environment.RunUntilIdle();
  EXPECT_TRUE(events.quarantine_called);
  EXPECT_TRUE(events.quarantine_saw_cleanup);
  EXPECT_TRUE(events.completion_called);
  EXPECT_TRUE(events.completion_saw_cleanup);
  EXPECT_FALSE(events.completion_result);
  const Lifecycle::Result result = observation->GetResult();
  EXPECT_EQ(result.status,
            Lifecycle::Status::kWaitingForRegisteredProfileIO);
  EXPECT_EQ(result.profile_io.outstanding_at_begin, 1u);
  EXPECT_EQ(result.profile_io.succeeded_operations, 0u);
  EXPECT_EQ(result.profile_io.failed_operations, 0u);
  EXPECT_EQ(result.profile_io.abandoned_operations, 0u);
  EXPECT_FALSE(observation->ClaimPostContentDrain().has_value());
  EXPECT_FALSE(
      observation->ClaimPostContentFailureRetirement().has_value());
}

TEST(WasmProfileIndexedDBCloseReceiptLifetimeTest,
     FailureBeforeReceiptQuarantinesOutstandingAdmission) {
  base::test::TaskEnvironment task_environment;
  Lifecycle lifecycle;
  std::optional<Lifecycle::ProfileIOHold> hold =
      lifecycle.TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());
  scoped_refptr<Lifecycle::Observation> observation = lifecycle.BeginQuiesce();
  ASSERT_TRUE(observation);

  Events events;
  TestOwner owner(std::move(*hold), &events);
  ASSERT_TRUE(owner.Start());
  owner.FailBeforeSelectedBucketCloseReceipt();
  EXPECT_TRUE(events.cleanup_called);
  EXPECT_FALSE(events.quarantine_called);
  EXPECT_FALSE(events.completion_called);
  EXPECT_EQ(observation->GetResult().status,
            Lifecycle::Status::kWaitingForRegisteredProfileIO);

  task_environment.RunUntilIdle();
  EXPECT_TRUE(events.quarantine_called);
  EXPECT_TRUE(events.quarantine_saw_cleanup);
  EXPECT_TRUE(events.completion_called);
  EXPECT_TRUE(events.completion_saw_cleanup);
  EXPECT_FALSE(events.completion_result);
  const Lifecycle::Result result = observation->GetResult();
  EXPECT_EQ(result.status,
            Lifecycle::Status::kWaitingForRegisteredProfileIO);
  EXPECT_EQ(result.profile_io.admitted_operations, 1u);
  EXPECT_EQ(result.profile_io.outstanding_at_begin, 1u);
  EXPECT_EQ(result.profile_io.succeeded_operations, 0u);
  EXPECT_EQ(result.profile_io.failed_operations, 0u);
  EXPECT_EQ(result.profile_io.abandoned_operations, 0u);
  EXPECT_FALSE(observation->ClaimPostContentDrain().has_value());
  EXPECT_FALSE(
      observation->ClaimPostContentFailureRetirement().has_value());
}

TEST(WasmProfileIndexedDBCloseReceiptLifetimeTest,
     OwnerDestructionBeforeQueuedFailureCannotAbandonOrUseAfterFree) {
  base::test::TaskEnvironment task_environment;
  Lifecycle lifecycle;
  std::optional<Lifecycle::ProfileIOHold> hold =
      lifecycle.TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());
  scoped_refptr<Lifecycle::Observation> observation = lifecycle.BeginQuiesce();
  ASSERT_TRUE(observation);

  Events events;
  auto owner = std::make_unique<TestOwner>(std::move(*hold), &events);
  ASSERT_TRUE(owner->Start());
  owner->FailBeforeSelectedBucketCloseReceipt();
  ASSERT_TRUE(events.cleanup_called);
  owner.reset();
  EXPECT_FALSE(events.completion_called);

  task_environment.RunUntilIdle();
  EXPECT_FALSE(events.quarantine_called);
  EXPECT_TRUE(events.completion_called);
  EXPECT_TRUE(events.completion_saw_cleanup);
  EXPECT_FALSE(events.completion_result);
  const Lifecycle::Result result = observation->GetResult();
  EXPECT_EQ(result.status,
            Lifecycle::Status::kWaitingForRegisteredProfileIO);
  EXPECT_EQ(result.profile_io.admitted_operations, 1u);
  EXPECT_EQ(result.profile_io.outstanding_at_begin, 1u);
  EXPECT_EQ(result.profile_io.succeeded_operations, 0u);
  EXPECT_EQ(result.profile_io.failed_operations, 0u);
  EXPECT_EQ(result.profile_io.abandoned_operations, 0u);
  EXPECT_FALSE(observation->ClaimPostContentDrain().has_value());
  EXPECT_FALSE(
      observation->ClaimPostContentFailureRetirement().has_value());
}

TEST(WasmProfileIndexedDBCloseReceiptLifetimeTest,
     RejectedStartRetiresAdmissionAsFailedNotAbandoned) {
  Lifecycle lifecycle;
  std::optional<Lifecycle::ProfileIOHold> hold =
      lifecycle.TryAcquireProfileIO();
  ASSERT_TRUE(hold.has_value());
  scoped_refptr<Lifecycle::Observation> observation = lifecycle.BeginQuiesce();
  ASSERT_TRUE(observation);

  ReceiptLifetime lifetime(std::move(*hold), base::OnceClosure());
  EXPECT_TRUE(lifetime.RejectBeforeStart());
  EXPECT_FALSE(lifetime.HasOutstandingAdmission());
  const Lifecycle::Result result = observation->GetResult();
  EXPECT_EQ(result.status, Lifecycle::Status::kRegisteredProfileIONotClean);
  EXPECT_EQ(result.profile_io.failed_operations, 1u);
  EXPECT_EQ(result.profile_io.abandoned_operations, 0u);
  EXPECT_TRUE(observation->ClaimPostContentFailureRetirement().has_value());
}

}  // namespace
}  // namespace chrome
