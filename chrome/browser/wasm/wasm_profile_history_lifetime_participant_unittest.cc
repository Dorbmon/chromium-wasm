// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <memory>
#include <optional>
#include <string>
#include <utility>

#include "base/command_line.h"
#include "base/files/scoped_temp_dir.h"
#include "base/functional/bind.h"
#include "base/run_loop.h"
#include "base/test/scoped_command_line.h"
#include "base/test/task_environment.h"
#include "build/build_config.h"
#include "chrome/browser/wasm/wasm_profile_history_smoke.h"
#include "chrome/browser/wasm/wasm_profile_ordered_drain_lifecycle.h"
#include "chrome/browser/wasm/wasm_profile_preferences_smoke.h"
#include "testing/gtest/include/gtest/gtest.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_profile_history_lifetime_participant_unittests must only be built for WebAssembly"
#endif

namespace chrome {
namespace {

using Lifecycle = WasmProfileOrderedDrainLifecycle;

TEST(WasmProfileHistoryLifetimeParticipantTest,
     FoundationFallbackQuarantineRetainsProfileIOUntilBackendDestroyReceipt) {
  // HistoryService owns its backend on a worker sequence. Keep the default
  // ThreadPool mode so the real History/Favicons close can finish while the
  // UI sequence waits for its SetOnBackendDestroyTask receipt.
  base::test::TaskEnvironment task_environment;
  base::test::ScopedCommandLine scoped_command_line;
  base::CommandLine* command_line =
      scoped_command_line.GetProcessCommandLine();
  command_line->AppendSwitchASCII("wasm-profile-preferences-smoke", "write");
  command_line->AppendSwitchASCII("wasm-profile-preferences-token-a",
                                  std::string(64, 'a'));
  command_line->AppendSwitch("wasm-profile-preferences-browser-smoke");
  command_line->AppendSwitch("wasm-profile-preferences-history-smoke");
  ASSERT_TRUE(EnableWasmProfilePreferencesSmokeTestMode());

  base::ScopedTempDir profile_dir;
  ASSERT_TRUE(profile_dir.CreateUniqueTempDir());
  Lifecycle lifecycle;
  std::optional<Lifecycle::ProfileIOHold> profile_io_hold =
      lifecycle.TryAcquireProfileIO();
  ASSERT_TRUE(profile_io_hold.has_value());

  scoped_refptr<Lifecycle::Observation> observation = lifecycle.BeginQuiesce();
  ASSERT_TRUE(observation);
  EXPECT_EQ(observation->GetResult().status,
            Lifecycle::Status::kWaitingForRegisteredProfileIO);

  base::RunLoop backend_destroyed_loop;
  bool completion_called = false;
  bool completion_succeeded = true;
  auto participant = std::make_unique<WasmProfileHistoryLifetimeParticipant>(
      profile_dir.GetPath(), std::move(*profile_io_hold));
  ASSERT_TRUE(participant->Start(base::BindOnce(
      [](bool* completion_called, bool* completion_succeeded,
         base::OnceClosure quit, bool succeeded) {
        *completion_called = true;
        *completion_succeeded = succeeded;
        std::move(quit).Run();
      },
      &completion_called, &completion_succeeded,
      backend_destroyed_loop.QuitClosure())));
  ASSERT_TRUE(participant->IsActive());
  // The profile owns this participant, so this is defensive API coverage: a
  // duplicate request must not replace the first completion or release its
  // admission while the HistoryService is already running.
  EXPECT_FALSE(participant->Start(base::BindOnce([](bool) {})));
  EXPECT_TRUE(participant->IsActive());
  EXPECT_FALSE(completion_called);
  EXPECT_EQ(observation->GetResult().status,
            Lifecycle::Status::kWaitingForRegisteredProfileIO);

  // Cancel requests HistoryService::Shutdown(), but the participant must keep
  // the Chrome-owned admission pending until HistoryBackend's destroy task.
  // In particular, neither a clean drain nor a failure-retirement transaction
  // may begin while the backend still owns History/Favicons files.
  participant->Cancel();
  EXPECT_TRUE(participant->IsActive());
  EXPECT_FALSE(completion_called);
  EXPECT_EQ(observation->GetResult().status,
            Lifecycle::Status::kWaitingForRegisteredProfileIO);
  EXPECT_FALSE(observation->ClaimPostContentDrain().has_value());
  EXPECT_FALSE(observation->ClaimPostContentFailureRetirement().has_value());

  // ShutdownFoundation can lose its WasmProfile owner after the UI loop is no
  // longer available to await this receipt. The participant transfers its
  // State to a process-lifetime quarantine instead of destroying the still
  // pending admission. That keeps both V4 backend operations blocked until
  // HistoryBackend has actually finished closing its files.
  EXPECT_TRUE(participant->QuarantineForFailureShutdown());
  EXPECT_FALSE(participant->IsActive());
  EXPECT_FALSE(completion_called);
  EXPECT_EQ(observation->GetResult().status,
            Lifecycle::Status::kWaitingForRegisteredProfileIO);
  EXPECT_FALSE(observation->ClaimPostContentDrain().has_value());
  EXPECT_FALSE(observation->ClaimPostContentFailureRetirement().has_value());

  // Destroy the profile-owned participant while its History/Favicons close is
  // still outstanding. The quarantine must retain the State and admission;
  // owner loss cannot cause an early terminal result or authorize either V4
  // backend operation before the actual destruction receipt.
  participant.reset();
  EXPECT_FALSE(completion_called);
  EXPECT_EQ(observation->GetResult().status,
            Lifecycle::Status::kWaitingForRegisteredProfileIO);
  EXPECT_FALSE(observation->ClaimPostContentDrain().has_value());
  EXPECT_FALSE(observation->ClaimPostContentFailureRetirement().has_value());

  backend_destroyed_loop.Run();

  EXPECT_TRUE(completion_called);
  EXPECT_FALSE(completion_succeeded);

  const Lifecycle::Result result = observation->GetResult();
  EXPECT_EQ(result.status, Lifecycle::Status::kRegisteredProfileIONotClean);
  EXPECT_EQ(result.profile_io.admitted_operations, 1u);
  EXPECT_EQ(result.profile_io.outstanding_at_begin, 1u);
  EXPECT_EQ(result.profile_io.succeeded_operations, 0u);
  EXPECT_EQ(result.profile_io.failed_operations, 1u);
  EXPECT_EQ(result.profile_io.abandoned_operations, 0u);
  EXPECT_FALSE(observation->ClaimPostContentDrain().has_value());
  EXPECT_TRUE(observation->ClaimPostContentFailureRetirement().has_value());
}

}  // namespace
}  // namespace chrome
