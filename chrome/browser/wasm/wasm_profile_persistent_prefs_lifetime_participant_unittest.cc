// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_persistent_prefs_lifetime_participant.h"

#include <memory>
#include <optional>
#include <utility>

#include "build/build_config.h"
#include "testing/gtest/include/gtest/gtest.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_profile_persistent_prefs_lifetime_participant_unittests must only be built for WebAssembly"
#endif

namespace {

using Lifecycle = WasmProfileOrderedDrainLifecycle;
using Participant = WasmProfilePersistentPrefsLifetimeParticipant;

std::unique_ptr<Lifecycle> CreateLifecycle() {
  return std::make_unique<Lifecycle>();
}

TEST(WasmProfilePersistentPrefsLifetimeParticipantTest,
     StrictFenceSuccessCompletesTheProfileLifetimeAdmission) {
  std::unique_ptr<Lifecycle> lifecycle = CreateLifecycle();
  std::optional<Lifecycle::ProfileIOHold> profile_io_hold =
      lifecycle->TryAcquireProfileIO();
  ASSERT_TRUE(profile_io_hold.has_value());
  Participant participant(std::move(*profile_io_hold));

  scoped_refptr<Lifecycle::Observation> observation = lifecycle->BeginQuiesce();
  ASSERT_TRUE(observation);
  EXPECT_EQ(observation->GetResult().status,
            Lifecycle::Status::kWaitingForRegisteredProfileIO);
  EXPECT_TRUE(participant.IsPending());

  EXPECT_TRUE(participant.CompleteAfterStrictFence(/*succeeded=*/true));
  EXPECT_FALSE(participant.IsPending());

  const Lifecycle::Result result = observation->GetResult();
  EXPECT_EQ(result.status, Lifecycle::Status::kReadyForPostContentDrain);
  EXPECT_EQ(result.profile_io.admitted_operations, 1u);
  EXPECT_EQ(result.profile_io.outstanding_at_begin, 1u);
  EXPECT_EQ(result.profile_io.succeeded_operations, 1u);
  EXPECT_EQ(result.profile_io.failed_operations, 0u);
  EXPECT_EQ(result.profile_io.abandoned_operations, 0u);
}

TEST(WasmProfilePersistentPrefsLifetimeParticipantTest,
     UniqueOwnerTransferPreservesTheConstructionAdmission) {
  std::unique_ptr<Lifecycle> lifecycle = CreateLifecycle();
  std::optional<Lifecycle::ProfileIOHold> profile_io_hold =
      lifecycle->TryAcquireProfileIO();
  ASSERT_TRUE(profile_io_hold.has_value());

  // BrowserMainParts owns this participant before WasmProfile construction,
  // then moves its unique owner into WasmProfile's member initializer before
  // JsonPrefStore/PrefService can synchronously read Preferences.
  std::unique_ptr<Participant> construction_owner =
      std::make_unique<Participant>(std::move(*profile_io_hold));
  ASSERT_TRUE(construction_owner->IsPending());
  std::unique_ptr<Participant> profile_owner = std::move(construction_owner);
  EXPECT_FALSE(construction_owner);
  EXPECT_TRUE(profile_owner->IsPending());

  scoped_refptr<Lifecycle::Observation> observation =
      lifecycle->BeginQuiesce();
  ASSERT_TRUE(observation);
  EXPECT_EQ(observation->GetResult().status,
            Lifecycle::Status::kWaitingForRegisteredProfileIO);

  EXPECT_TRUE(profile_owner->CompleteAfterStrictFence(/*succeeded=*/true));
  const Lifecycle::Result result = observation->GetResult();
  EXPECT_EQ(result.status, Lifecycle::Status::kReadyForPostContentDrain);
  EXPECT_EQ(result.profile_io.admitted_operations, 1u);
  EXPECT_EQ(result.profile_io.succeeded_operations, 1u);
  EXPECT_EQ(result.profile_io.failed_operations, 0u);
  EXPECT_EQ(result.profile_io.abandoned_operations, 0u);
}

TEST(WasmProfilePersistentPrefsLifetimeParticipantTest,
     StrictFenceFailureSelectsFailureRetirement) {
  std::unique_ptr<Lifecycle> lifecycle = CreateLifecycle();
  std::optional<Lifecycle::ProfileIOHold> profile_io_hold =
      lifecycle->TryAcquireProfileIO();
  ASSERT_TRUE(profile_io_hold.has_value());
  Participant participant(std::move(*profile_io_hold));

  scoped_refptr<Lifecycle::Observation> observation = lifecycle->BeginQuiesce();
  ASSERT_TRUE(observation);
  EXPECT_TRUE(participant.CompleteAfterStrictFence(/*succeeded=*/false));

  const Lifecycle::Result result = observation->GetResult();
  EXPECT_EQ(result.status, Lifecycle::Status::kRegisteredProfileIONotClean);
  EXPECT_EQ(result.profile_io.admitted_operations, 1u);
  EXPECT_EQ(result.profile_io.succeeded_operations, 0u);
  EXPECT_EQ(result.profile_io.failed_operations, 1u);
  EXPECT_EQ(result.profile_io.abandoned_operations, 0u);
  EXPECT_FALSE(observation->ClaimPostContentDrain().has_value());
  EXPECT_TRUE(observation->ClaimPostContentFailureRetirement().has_value());
}

TEST(WasmProfilePersistentPrefsLifetimeParticipantTest,
     DestructionFailsPendingAdmissionInsteadOfAbandoningIt) {
  std::unique_ptr<Lifecycle> lifecycle = CreateLifecycle();
  std::optional<Lifecycle::ProfileIOHold> profile_io_hold =
      lifecycle->TryAcquireProfileIO();
  ASSERT_TRUE(profile_io_hold.has_value());
  scoped_refptr<Lifecycle::Observation> observation = lifecycle->BeginQuiesce();
  ASSERT_TRUE(observation);

  {
    Participant participant(std::move(*profile_io_hold));
    EXPECT_TRUE(participant.IsPending());
  }

  const Lifecycle::Result result = observation->GetResult();
  EXPECT_EQ(result.status, Lifecycle::Status::kRegisteredProfileIONotClean);
  EXPECT_EQ(result.profile_io.succeeded_operations, 0u);
  EXPECT_EQ(result.profile_io.failed_operations, 1u);
  EXPECT_EQ(result.profile_io.abandoned_operations, 0u);
}

TEST(WasmProfilePersistentPrefsLifetimeParticipantTest,
     DuplicateFenceResultCannotChangeTheTerminalAdmission) {
  std::unique_ptr<Lifecycle> lifecycle = CreateLifecycle();
  std::optional<Lifecycle::ProfileIOHold> profile_io_hold =
      lifecycle->TryAcquireProfileIO();
  ASSERT_TRUE(profile_io_hold.has_value());
  Participant participant(std::move(*profile_io_hold));

  scoped_refptr<Lifecycle::Observation> observation = lifecycle->BeginQuiesce();
  ASSERT_TRUE(observation);
  EXPECT_TRUE(participant.CompleteAfterStrictFence(/*succeeded=*/true));
  EXPECT_FALSE(participant.CompleteAfterStrictFence(/*succeeded=*/false));

  const Lifecycle::Result result = observation->GetResult();
  EXPECT_EQ(result.status, Lifecycle::Status::kReadyForPostContentDrain);
  EXPECT_EQ(result.profile_io.succeeded_operations, 1u);
  EXPECT_EQ(result.profile_io.failed_operations, 0u);
}

}  // namespace
