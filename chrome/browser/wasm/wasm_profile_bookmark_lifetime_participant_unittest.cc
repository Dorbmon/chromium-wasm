// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <memory>
#include <optional>
#include <string>
#include <utility>

#include "base/command_line.h"
#include "base/files/important_file_writer.h"
#include "base/files/file_util.h"
#include "base/files/scoped_temp_dir.h"
#include "base/functional/bind.h"
#include "base/run_loop.h"
#include "base/task/execution_fence.h"
#include "base/task/thread_pool/thread_pool_instance.h"
#include "base/test/scoped_command_line.h"
#include "base/test/scoped_feature_list.h"
#include "base/test/task_environment.h"
#include "build/build_config.h"
#include "chrome/browser/wasm/wasm_profile_bookmark_smoke.h"
#include "chrome/browser/wasm/wasm_profile_ordered_drain_lifecycle.h"
#include "chrome/browser/wasm/wasm_profile_preferences_smoke.h"
#include "components/bookmarks/common/bookmark_features.h"
#include "components/signin/public/base/signin_switches.h"
#include "testing/gmock/include/gmock/gmock.h"
#include "testing/gtest/include/gtest/gtest.h"
#include "ui/base/resource/mock_resource_bundle_delegate.h"
#include "ui/base/resource/resource_bundle.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_profile_bookmark_lifetime_participant_unittests must only be built for WebAssembly"
#endif

namespace chrome {
namespace {

using Lifecycle = WasmProfileOrderedDrainLifecycle;

class FailingDataSerializer final
    : public base::ImportantFileWriter::DataSerializer {
 public:
  std::optional<std::string> SerializeData() override { return std::nullopt; }
};

class FailingBackgroundDataSerializer final
    : public base::ImportantFileWriter::BackgroundDataSerializer {
 public:
  base::ImportantFileWriter::BackgroundDataProducerCallback
  GetSerializedDataProducerForBackgroundSequence() override {
    return base::BindOnce(
        []() -> std::optional<std::string> { return std::nullopt; });
  }
};

WasmProfilePreferencesBookmarkSmokeInput WriteInput(char digest_character) {
  WasmProfilePreferencesBookmarkSmokeInput input;
  input.mode = WasmProfilePreferencesBookmarkSmokeInput::Mode::kWrite;
  input.token_a_digest = std::string(64, digest_character);
  return input;
}

TEST(WasmProfileBookmarkImportantFileWriterTest,
     SerializationFailureDeliversResultWithoutBeforeWrite) {
  base::test::TaskEnvironment task_environment;
  base::ScopedTempDir temp_dir;
  ASSERT_TRUE(temp_dir.CreateUniqueTempDir());

  {
    base::RunLoop loop;
    bool before_write_called = false;
    bool after_write_called = false;
    bool write_succeeded = true;
    base::ImportantFileWriter writer(
        temp_dir.GetPath().AppendASCII("foreground"),
        base::SequencedTaskRunner::GetCurrentDefault());
    FailingDataSerializer serializer;
    writer.ScheduleWrite(&serializer);
    writer.RegisterOnNextWriteCallbacks(
        base::BindOnce([](bool* called) { *called = true; },
                       &before_write_called),
        base::BindOnce(
            [](bool* called, bool* succeeded, base::OnceClosure quit,
               bool result) {
              *called = true;
              *succeeded = result;
              std::move(quit).Run();
            },
            &after_write_called, &write_succeeded, loop.QuitClosure()));
    writer.DoScheduledWrite();
    loop.Run();

    EXPECT_FALSE(before_write_called);
    EXPECT_TRUE(after_write_called);
    EXPECT_FALSE(write_succeeded);
    EXPECT_FALSE(base::PathExists(writer.path()));
  }

  {
    base::RunLoop loop;
    bool before_write_called = false;
    bool after_write_called = false;
    bool write_succeeded = true;
    base::ImportantFileWriter writer(
        temp_dir.GetPath().AppendASCII("background"),
        base::SequencedTaskRunner::GetCurrentDefault());
    FailingBackgroundDataSerializer serializer;
    writer.ScheduleWriteWithBackgroundDataSerializer(&serializer);
    writer.RegisterOnNextWriteCallbacks(
        base::BindOnce([](bool* called) { *called = true; },
                       &before_write_called),
        base::BindOnce(
            [](bool* called, bool* succeeded, base::OnceClosure quit,
               bool result) {
              *called = true;
              *succeeded = result;
              std::move(quit).Run();
            },
            &after_write_called, &write_succeeded, loop.QuitClosure()));
    writer.DoScheduledWrite();
    loop.Run();

    EXPECT_FALSE(before_write_called);
    EXPECT_TRUE(after_write_called);
    EXPECT_FALSE(write_succeeded);
    EXPECT_FALSE(base::PathExists(writer.path()));
  }
}

TEST(WasmProfileBookmarkLifetimeParticipantTest,
     DeliveryWriteAndFlushCancellationRetainAdmissionUntilTerminalResult) {
  base::test::TaskEnvironment task_environment;
  testing::NiceMock<ui::MockResourceBundleDelegate> resource_delegate;
  ON_CALL(resource_delegate, GetLocalizedString(testing::_, testing::_))
      .WillByDefault(testing::DoAll(
          testing::SetArgPointee<1>(std::u16string(u"bookmark")),
          testing::Return(true)));
  ui::ResourceBundle resource_bundle(&resource_delegate);
  ui::ResourceBundle::SharedInstanceSwapperForTesting resource_bundle_swapper(
      &resource_bundle);
  base::test::ScopedFeatureList scoped_features;
  scoped_features.InitWithFeatures(
      {}, {bookmarks::kEncryptBookmarks,
           switches::kSyncEnableBookmarksInTransportMode});
  base::test::ScopedCommandLine scoped_command_line;
  base::CommandLine* command_line =
      scoped_command_line.GetProcessCommandLine();
  command_line->AppendSwitchASCII("wasm-profile-preferences-smoke", "write");
  command_line->AppendSwitchASCII("wasm-profile-preferences-token-a",
                                  std::string(64, 'a'));
  command_line->AppendSwitch("wasm-profile-preferences-browser-smoke");
  command_line->AppendSwitch("wasm-profile-preferences-bookmark-smoke");
  ASSERT_TRUE(EnableWasmProfilePreferencesSmokeTestMode());

  // A synchronously detected operation failure still delivers completion on a
  // later UI turn. Until then, keep the admission active so a re-entrant
  // shutdown cannot tear down the profile between model close and its owner
  // notification.
  Lifecycle delayed_lifecycle;
  std::optional<Lifecycle::ProfileIOHold> delayed_hold =
      delayed_lifecycle.TryAcquireProfileIO();
  ASSERT_TRUE(delayed_hold.has_value());
  scoped_refptr<Lifecycle::Observation> delayed_observation =
      delayed_lifecycle.BeginQuiesce();
  ASSERT_TRUE(delayed_observation);

  base::RunLoop delayed_loop;
  bool delayed_completion_called = false;
  bool delayed_completion_succeeded = true;
  bool active_during_delayed_completion = true;
  auto delayed_participant =
      std::make_unique<WasmProfileBookmarkLifetimeParticipant>(
          base::FilePath(), WriteInput('c'), std::move(*delayed_hold));
  WasmProfileBookmarkLifetimeParticipant* delayed_participant_raw =
      delayed_participant.get();
  ASSERT_TRUE(delayed_participant->Start(base::BindOnce(
      [](WasmProfileBookmarkLifetimeParticipant* participant, bool* called,
         bool* succeeded, bool* active_during_completion,
         base::OnceClosure quit, bool result) {
        *called = true;
        *succeeded = result;
        *active_during_completion = participant->IsActive();
        std::move(quit).Run();
      },
      delayed_participant_raw, &delayed_completion_called,
      &delayed_completion_succeeded, &active_during_delayed_completion,
      delayed_loop.QuitClosure())));
  EXPECT_TRUE(delayed_participant->IsActive());
  EXPECT_FALSE(delayed_participant->HasCompleted());
  EXPECT_FALSE(delayed_completion_called);
  EXPECT_EQ(delayed_observation->GetResult().status,
            Lifecycle::Status::kWaitingForRegisteredProfileIO);

  delayed_participant->Cancel();
  EXPECT_TRUE(delayed_participant->IsActive());
  EXPECT_FALSE(delayed_completion_called);
  EXPECT_EQ(delayed_observation->GetResult().status,
            Lifecycle::Status::kWaitingForRegisteredProfileIO);
  delayed_loop.Run();

  EXPECT_TRUE(delayed_completion_called);
  EXPECT_FALSE(delayed_completion_succeeded);
  EXPECT_FALSE(active_during_delayed_completion);
  EXPECT_FALSE(delayed_participant->IsActive());
  EXPECT_TRUE(delayed_participant->HasCompleted());
  EXPECT_FALSE(delayed_participant->DidSucceed());
  const Lifecycle::Result delayed_result = delayed_observation->GetResult();
  EXPECT_EQ(delayed_result.status,
            Lifecycle::Status::kRegisteredProfileIONotClean);
  EXPECT_EQ(delayed_result.profile_io.failed_operations, 1u);
  EXPECT_EQ(delayed_result.profile_io.abandoned_operations, 0u);

  // First prove the normal terminal boundary: the write result arrives, the
  // direct model/storage owner is destroyed, and only then can its admitted
  // profile operation authorize the outer clean-drain permit.
  base::ScopedTempDir successful_profile_dir;
  ASSERT_TRUE(successful_profile_dir.CreateUniqueTempDir());
  Lifecycle successful_lifecycle;
  std::optional<Lifecycle::ProfileIOHold> successful_hold =
      successful_lifecycle.TryAcquireProfileIO();
  ASSERT_TRUE(successful_hold.has_value());
  scoped_refptr<Lifecycle::Observation> successful_observation =
      successful_lifecycle.BeginQuiesce();
  ASSERT_TRUE(successful_observation);

  base::RunLoop successful_loop;
  bool successful_completion = false;
  auto successful_participant =
      std::make_unique<WasmProfileBookmarkLifetimeParticipant>(
          successful_profile_dir.GetPath(), WriteInput('a'),
          std::move(*successful_hold));
  ASSERT_TRUE(successful_participant->Start(base::BindOnce(
      [](bool* completion, base::OnceClosure quit, bool succeeded) {
        *completion = succeeded;
        std::move(quit).Run();
      },
      &successful_completion, successful_loop.QuitClosure())));
  EXPECT_FALSE(successful_participant->Start(base::BindOnce([](bool) {})));
  successful_loop.Run();

  EXPECT_TRUE(successful_completion);
  EXPECT_TRUE(successful_participant->HasCompleted());
  EXPECT_TRUE(successful_participant->DidSucceed());
  EXPECT_TRUE(base::PathExists(
      successful_profile_dir.GetPath().AppendASCII("Bookmarks")));
  EXPECT_EQ(successful_observation->GetResult().status,
            Lifecycle::Status::kReadyForPostContentDrain);
  EXPECT_TRUE(successful_observation->ClaimPostContentDrain().has_value());

  // Then finish a second real model's background load without pumping its UI
  // reply. Fence newly posted ThreadPool work while that reply starts the
  // ImportantFileWriter flush, then cancel. Quarantining and destroying the
  // profile-owned wrapper must retain the model and admission through the
  // in-flight write result.
  base::ScopedTempDir cancelled_profile_dir;
  ASSERT_TRUE(cancelled_profile_dir.CreateUniqueTempDir());
  Lifecycle cancelled_lifecycle;
  std::optional<Lifecycle::ProfileIOHold> cancelled_hold =
      cancelled_lifecycle.TryAcquireProfileIO();
  ASSERT_TRUE(cancelled_hold.has_value());
  scoped_refptr<Lifecycle::Observation> cancelled_observation =
      cancelled_lifecycle.BeginQuiesce();
  ASSERT_TRUE(cancelled_observation);

  base::RunLoop cancelled_loop;
  bool cancelled_completion_called = false;
  bool cancelled_completion_succeeded = true;
  auto cancelled_participant =
      std::make_unique<WasmProfileBookmarkLifetimeParticipant>(
          cancelled_profile_dir.GetPath(), WriteInput('b'),
          std::move(*cancelled_hold));
  ASSERT_TRUE(cancelled_participant->Start(base::BindOnce(
      [](bool* called, bool* succeeded, base::OnceClosure quit, bool result) {
        *called = true;
        *succeeded = result;
        std::move(quit).Run();
      },
      &cancelled_completion_called, &cancelled_completion_succeeded,
      cancelled_loop.QuitClosure())));
  base::ThreadPoolInstance::Get()->FlushForTesting();
  {
    base::ScopedThreadPoolExecutionFence write_fence;
    base::RunLoop().RunUntilIdle();

    ASSERT_TRUE(cancelled_participant->IsActive());
    cancelled_participant->Cancel();
    EXPECT_TRUE(cancelled_participant->IsActive());
    EXPECT_FALSE(cancelled_completion_called);
    EXPECT_EQ(cancelled_observation->GetResult().status,
              Lifecycle::Status::kWaitingForRegisteredProfileIO);
    EXPECT_FALSE(cancelled_observation->ClaimPostContentDrain().has_value());
    EXPECT_FALSE(cancelled_observation->ClaimPostContentFailureRetirement()
                     .has_value());

    EXPECT_TRUE(cancelled_participant->QuarantineForFailureShutdown());
    EXPECT_FALSE(cancelled_participant->IsActive());
    cancelled_participant.reset();
    EXPECT_FALSE(cancelled_completion_called);
    EXPECT_EQ(cancelled_observation->GetResult().status,
              Lifecycle::Status::kWaitingForRegisteredProfileIO);
    EXPECT_FALSE(cancelled_observation->ClaimPostContentDrain().has_value());
    EXPECT_FALSE(cancelled_observation->ClaimPostContentFailureRetirement()
                     .has_value());
  }

  cancelled_loop.Run();

  EXPECT_TRUE(cancelled_completion_called);
  EXPECT_FALSE(cancelled_completion_succeeded);
  const Lifecycle::Result cancelled_result =
      cancelled_observation->GetResult();
  EXPECT_EQ(cancelled_result.status,
            Lifecycle::Status::kRegisteredProfileIONotClean);
  EXPECT_EQ(cancelled_result.profile_io.admitted_operations, 1u);
  EXPECT_EQ(cancelled_result.profile_io.outstanding_at_begin, 1u);
  EXPECT_EQ(cancelled_result.profile_io.succeeded_operations, 0u);
  EXPECT_EQ(cancelled_result.profile_io.failed_operations, 1u);
  EXPECT_EQ(cancelled_result.profile_io.abandoned_operations, 0u);
  EXPECT_FALSE(cancelled_observation->ClaimPostContentDrain().has_value());
  EXPECT_TRUE(
      cancelled_observation->ClaimPostContentFailureRetirement().has_value());
}

}  // namespace
}  // namespace chrome
