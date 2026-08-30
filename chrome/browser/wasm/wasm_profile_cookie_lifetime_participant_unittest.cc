// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <memory>
#include <optional>
#include <string>
#include <utility>

#include "base/check.h"
#include "base/command_line.h"
#include "base/functional/bind.h"
#include "base/test/scoped_command_line.h"
#include "base/test/task_environment.h"
#include "build/build_config.h"
#include "chrome/browser/wasm/wasm_profile_cookie_smoke.h"
#include "chrome/browser/wasm/wasm_profile_ordered_drain_lifecycle.h"
#include "chrome/browser/wasm/wasm_profile_preferences_smoke.h"
#include "mojo/core/embedder/embedder.h"
#include "mojo/public/cpp/bindings/receiver.h"
#include "net/cookies/canonical_cookie.h"
#include "net/cookies/cookie_access_result.h"
#include "services/network/test/test_cookie_manager.h"
#include "testing/gtest/include/gtest/gtest.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_profile_cookie_lifetime_participant_unittests must only be built for WebAssembly"
#endif

namespace chrome {
namespace {

using Lifecycle = WasmProfileOrderedDrainLifecycle;

WasmProfilePreferencesCookieSmokeInput WriteInput(char token_character) {
  WasmProfilePreferencesCookieSmokeInput input;
  input.mode = WasmProfilePreferencesCookieSmokeInput::Mode::kWrite;
  input.token_a = std::string(64, token_character);
  input.token_a_digest = std::string(64, token_character);
  return input;
}

class ControllableCookieManager final : public network::TestCookieManager {
 public:
  ControllableCookieManager() = default;
  ControllableCookieManager(const ControllableCookieManager&) = delete;
  ControllableCookieManager& operator=(const ControllableCookieManager&) =
      delete;
  ~ControllableCookieManager() override = default;

  mojo::PendingRemote<network::mojom::CookieManager> BindNewRemote() {
    return receiver_.BindNewPipeAndPassRemote();
  }

  void GetCookieList(
      const GURL&,
      const net::CookieOptions&,
      const net::CookiePartitionKeyCollection&,
      GetCookieListCallback callback) override {
    CHECK(!get_cookie_list_callback_);
    ++get_cookie_list_calls_;
    get_cookie_list_callback_ = std::move(callback);
  }

  void SetCanonicalCookie(const net::CanonicalCookie& cookie,
                          const GURL&,
                          const net::CookieOptions&,
                          SetCanonicalCookieCallback callback) override {
    CHECK(!set_cookie_callback_);
    stored_cookie_ = std::make_unique<net::CanonicalCookie>(cookie);
    ++set_cookie_calls_;
    set_cookie_callback_ = std::move(callback);
  }

  void FlushCookieStore(FlushCookieStoreCallback callback) override {
    CHECK(!flush_callback_);
    ++flush_calls_;
    flush_callback_ = std::move(callback);
  }

  void CloseCookieStoreForTesting(
      CloseCookieStoreForTestingCallback callback) override {
    CHECK(!close_callback_);
    ++close_calls_;
    close_callback_ = std::move(callback);
  }

  void ReplyWithNoCookies() {
    CHECK(get_cookie_list_callback_);
    std::move(get_cookie_list_callback_)
        .Run(net::CookieAccessResultList(), net::CookieAccessResultList());
  }

  void ReplyWithStoredCookie() {
    CHECK(get_cookie_list_callback_);
    CHECK(stored_cookie_);
    net::CookieAccessResultList included;
    included.emplace_back(*stored_cookie_, net::CookieAccessResult());
    std::move(get_cookie_list_callback_)
        .Run(included, net::CookieAccessResultList());
  }

  void ReplySetCookie() {
    CHECK(set_cookie_callback_);
    std::move(set_cookie_callback_).Run(net::CookieAccessResult());
  }

  void ReplyFlush() {
    CHECK(flush_callback_);
    std::move(flush_callback_).Run();
  }

  void ReplyClose(bool success) {
    CHECK(close_callback_);
    std::move(close_callback_).Run(success);
  }

  int get_cookie_list_calls() const { return get_cookie_list_calls_; }
  int set_cookie_calls() const { return set_cookie_calls_; }
  int flush_calls() const { return flush_calls_; }
  int close_calls() const { return close_calls_; }

 private:
  int get_cookie_list_calls_ = 0;
  int set_cookie_calls_ = 0;
  int flush_calls_ = 0;
  int close_calls_ = 0;
  std::unique_ptr<net::CanonicalCookie> stored_cookie_;
  GetCookieListCallback get_cookie_list_callback_;
  SetCanonicalCookieCallback set_cookie_callback_;
  FlushCookieStoreCallback flush_callback_;
  CloseCookieStoreForTestingCallback close_callback_;
  mojo::Receiver<network::mojom::CookieManager> receiver_{this};
};

TEST(WasmProfileCookieLifetimeParticipantTest,
     CloseReceiptAndQuarantineOwnTheProfileIOAdmission) {
  base::test::TaskEnvironment task_environment;
  mojo::core::Init();
  base::test::ScopedCommandLine scoped_command_line;
  base::CommandLine* command_line =
      scoped_command_line.GetProcessCommandLine();
  command_line->AppendSwitchASCII("wasm-profile-preferences-smoke", "write");
  command_line->AppendSwitchASCII("wasm-profile-preferences-token-a",
                                  std::string(64, 'a'));
  command_line->AppendSwitch("wasm-profile-preferences-browser-smoke");
  command_line->AppendSwitch("wasm-profile-preferences-cookie-smoke");
  ASSERT_TRUE(EnableWasmProfilePreferencesSmokeTestMode());

  // A successful probe cannot make the outer drain ready at its logical write,
  // readback, or flush boundary. Only the CookieManager's SQLite close receipt
  // followed by the posted owner notification may complete the admission.
  ControllableCookieManager successful_cookie_manager;
  Lifecycle successful_lifecycle;
  std::optional<Lifecycle::ProfileIOHold> successful_hold =
      successful_lifecycle.TryAcquireProfileIO();
  ASSERT_TRUE(successful_hold.has_value());
  scoped_refptr<Lifecycle::Observation> successful_observation =
      successful_lifecycle.BeginQuiesce();
  ASSERT_TRUE(successful_observation);

  bool successful_completion_called = false;
  bool successful_completion_result = false;
  auto successful_participant =
      std::make_unique<WasmProfileCookieLifetimeParticipant>(
          successful_cookie_manager.BindNewRemote(), WriteInput('a'),
          std::move(*successful_hold));
  ASSERT_TRUE(successful_participant->Start(base::BindOnce(
      [](bool* called, bool* result, bool success) {
        *called = true;
        *result = success;
      },
      &successful_completion_called, &successful_completion_result)));
  EXPECT_FALSE(successful_participant->Start(base::BindOnce([](bool) {})));
  task_environment.RunUntilIdle();
  ASSERT_EQ(successful_cookie_manager.get_cookie_list_calls(), 1);
  EXPECT_EQ(successful_observation->GetResult().status,
            Lifecycle::Status::kWaitingForRegisteredProfileIO);

  successful_cookie_manager.ReplyWithNoCookies();
  task_environment.RunUntilIdle();
  ASSERT_EQ(successful_cookie_manager.set_cookie_calls(), 1);
  successful_cookie_manager.ReplySetCookie();
  task_environment.RunUntilIdle();
  ASSERT_EQ(successful_cookie_manager.get_cookie_list_calls(), 2);
  successful_cookie_manager.ReplyWithStoredCookie();
  task_environment.RunUntilIdle();
  ASSERT_EQ(successful_cookie_manager.flush_calls(), 1);
  successful_cookie_manager.ReplyFlush();
  task_environment.RunUntilIdle();
  ASSERT_EQ(successful_cookie_manager.close_calls(), 1);
  EXPECT_TRUE(successful_participant->IsActive());
  EXPECT_FALSE(successful_completion_called);
  EXPECT_EQ(successful_observation->GetResult().status,
            Lifecycle::Status::kWaitingForRegisteredProfileIO);
  EXPECT_FALSE(successful_observation->ClaimPostContentDrain().has_value());

  successful_cookie_manager.ReplyClose(/*success=*/true);
  EXPECT_TRUE(successful_participant->IsActive());
  EXPECT_FALSE(successful_completion_called);
  EXPECT_EQ(successful_observation->GetResult().status,
            Lifecycle::Status::kWaitingForRegisteredProfileIO);
  task_environment.RunUntilIdle();
  EXPECT_TRUE(successful_completion_called);
  EXPECT_TRUE(successful_completion_result);
  EXPECT_FALSE(successful_participant->IsActive());
  EXPECT_TRUE(successful_participant->HasCompleted());
  EXPECT_TRUE(successful_participant->DidSucceed());
  EXPECT_EQ(successful_observation->GetResult().status,
            Lifecycle::Status::kReadyForPostContentDrain);
  EXPECT_TRUE(successful_observation->ClaimPostContentDrain().has_value());

  // A complete, uncancelled probe still fails closed when CookieManager does
  // not certify that it closed a persistent backend. The callback receipt is
  // terminal, but it may retire only through the failure path.
  ControllableCookieManager rejected_close_cookie_manager;
  Lifecycle rejected_close_lifecycle;
  std::optional<Lifecycle::ProfileIOHold> rejected_close_hold =
      rejected_close_lifecycle.TryAcquireProfileIO();
  ASSERT_TRUE(rejected_close_hold.has_value());
  scoped_refptr<Lifecycle::Observation> rejected_close_observation =
      rejected_close_lifecycle.BeginQuiesce();
  ASSERT_TRUE(rejected_close_observation);

  bool rejected_close_completion_called = false;
  bool rejected_close_completion_result = true;
  auto rejected_close_participant =
      std::make_unique<WasmProfileCookieLifetimeParticipant>(
          rejected_close_cookie_manager.BindNewRemote(), WriteInput('d'),
          std::move(*rejected_close_hold));
  ASSERT_TRUE(rejected_close_participant->Start(base::BindOnce(
      [](bool* called, bool* result, bool success) {
        *called = true;
        *result = success;
      },
      &rejected_close_completion_called, &rejected_close_completion_result)));
  task_environment.RunUntilIdle();
  rejected_close_cookie_manager.ReplyWithNoCookies();
  task_environment.RunUntilIdle();
  rejected_close_cookie_manager.ReplySetCookie();
  task_environment.RunUntilIdle();
  rejected_close_cookie_manager.ReplyWithStoredCookie();
  task_environment.RunUntilIdle();
  rejected_close_cookie_manager.ReplyFlush();
  task_environment.RunUntilIdle();
  ASSERT_EQ(rejected_close_cookie_manager.close_calls(), 1);

  rejected_close_cookie_manager.ReplyClose(/*success=*/false);
  EXPECT_TRUE(rejected_close_participant->IsActive());
  EXPECT_FALSE(rejected_close_completion_called);
  EXPECT_EQ(rejected_close_observation->GetResult().status,
            Lifecycle::Status::kWaitingForRegisteredProfileIO);
  task_environment.RunUntilIdle();
  EXPECT_TRUE(rejected_close_completion_called);
  EXPECT_FALSE(rejected_close_completion_result);
  EXPECT_FALSE(rejected_close_participant->IsActive());
  EXPECT_TRUE(rejected_close_participant->HasCompleted());
  EXPECT_FALSE(rejected_close_participant->DidSucceed());
  const Lifecycle::Result rejected_close_result =
      rejected_close_observation->GetResult();
  EXPECT_EQ(rejected_close_result.status,
            Lifecycle::Status::kRegisteredProfileIONotClean);
  EXPECT_EQ(rejected_close_result.profile_io.admitted_operations, 1u);
  EXPECT_EQ(rejected_close_result.profile_io.succeeded_operations, 0u);
  EXPECT_EQ(rejected_close_result.profile_io.failed_operations, 1u);
  EXPECT_EQ(rejected_close_result.profile_io.abandoned_operations, 0u);
  EXPECT_FALSE(
      rejected_close_observation->ClaimPostContentDrain().has_value());
  EXPECT_TRUE(rejected_close_observation->ClaimPostContentFailureRetirement()
                  .has_value());

  // Cancellation cannot race a pending CookieManager request with backend
  // close. It waits for that reply, requests one close, and quarantine keeps
  // State plus admission alive after the profile-owned wrapper is destroyed.
  ControllableCookieManager cancelled_cookie_manager;
  Lifecycle cancelled_lifecycle;
  std::optional<Lifecycle::ProfileIOHold> cancelled_hold =
      cancelled_lifecycle.TryAcquireProfileIO();
  ASSERT_TRUE(cancelled_hold.has_value());
  scoped_refptr<Lifecycle::Observation> cancelled_observation =
      cancelled_lifecycle.BeginQuiesce();
  ASSERT_TRUE(cancelled_observation);

  bool cancelled_completion_called = false;
  bool cancelled_completion_result = true;
  auto cancelled_participant =
      std::make_unique<WasmProfileCookieLifetimeParticipant>(
          cancelled_cookie_manager.BindNewRemote(), WriteInput('b'),
          std::move(*cancelled_hold));
  ASSERT_TRUE(cancelled_participant->Start(base::BindOnce(
      [](bool* called, bool* result, bool success) {
        *called = true;
        *result = success;
      },
      &cancelled_completion_called, &cancelled_completion_result)));
  task_environment.RunUntilIdle();
  ASSERT_EQ(cancelled_cookie_manager.get_cookie_list_calls(), 1);

  cancelled_participant->Cancel();
  EXPECT_TRUE(cancelled_participant->IsActive());
  EXPECT_EQ(cancelled_cookie_manager.close_calls(), 0);
  EXPECT_EQ(cancelled_observation->GetResult().status,
            Lifecycle::Status::kWaitingForRegisteredProfileIO);
  cancelled_cookie_manager.ReplyWithNoCookies();
  task_environment.RunUntilIdle();
  ASSERT_EQ(cancelled_cookie_manager.close_calls(), 1);
  EXPECT_EQ(cancelled_cookie_manager.set_cookie_calls(), 0);
  EXPECT_FALSE(cancelled_completion_called);

  EXPECT_TRUE(cancelled_participant->QuarantineForFailureShutdown());
  EXPECT_FALSE(cancelled_participant->IsActive());
  cancelled_participant.reset();
  EXPECT_FALSE(cancelled_completion_called);
  EXPECT_EQ(cancelled_observation->GetResult().status,
            Lifecycle::Status::kWaitingForRegisteredProfileIO);
  EXPECT_FALSE(cancelled_observation->ClaimPostContentDrain().has_value());
  EXPECT_FALSE(cancelled_observation->ClaimPostContentFailureRetirement()
                   .has_value());

  cancelled_cookie_manager.ReplyClose(/*success=*/true);
  task_environment.RunUntilIdle();
  EXPECT_TRUE(cancelled_completion_called);
  EXPECT_FALSE(cancelled_completion_result);
  const Lifecycle::Result cancelled_result =
      cancelled_observation->GetResult();
  EXPECT_EQ(cancelled_result.status,
            Lifecycle::Status::kRegisteredProfileIONotClean);
  EXPECT_EQ(cancelled_result.profile_io.admitted_operations, 1u);
  EXPECT_EQ(cancelled_result.profile_io.succeeded_operations, 0u);
  EXPECT_EQ(cancelled_result.profile_io.failed_operations, 1u);
  EXPECT_EQ(cancelled_result.profile_io.abandoned_operations, 0u);
  EXPECT_FALSE(cancelled_observation->ClaimPostContentDrain().has_value());
  EXPECT_TRUE(cancelled_observation->ClaimPostContentFailureRetirement()
                  .has_value());

  // A cloned Mojo connection is not ownership of NetworkContext. If that owner
  // disappears before a close receipt, quarantine must deliberately leave the
  // admission outstanding rather than reinterpret disconnect as a safe close.
  auto disconnected_cookie_manager =
      std::make_unique<ControllableCookieManager>();
  Lifecycle disconnected_lifecycle;
  std::optional<Lifecycle::ProfileIOHold> disconnected_hold =
      disconnected_lifecycle.TryAcquireProfileIO();
  ASSERT_TRUE(disconnected_hold.has_value());
  scoped_refptr<Lifecycle::Observation> disconnected_observation =
      disconnected_lifecycle.BeginQuiesce();
  ASSERT_TRUE(disconnected_observation);

  auto disconnected_participant =
      std::make_unique<WasmProfileCookieLifetimeParticipant>(
          disconnected_cookie_manager->BindNewRemote(), WriteInput('c'),
          std::move(*disconnected_hold));
  ASSERT_TRUE(disconnected_participant->Start(base::BindOnce([](bool) {})));
  task_environment.RunUntilIdle();
  ASSERT_EQ(disconnected_cookie_manager->get_cookie_list_calls(), 1);
  disconnected_participant->Cancel();
  EXPECT_TRUE(
      disconnected_participant->QuarantineForFailureShutdown());
  disconnected_participant.reset();
  disconnected_cookie_manager.reset();
  task_environment.RunUntilIdle();

  const Lifecycle::Result disconnected_result =
      disconnected_observation->GetResult();
  EXPECT_EQ(disconnected_result.status,
            Lifecycle::Status::kWaitingForRegisteredProfileIO);
  EXPECT_EQ(disconnected_result.profile_io.admitted_operations, 1u);
  EXPECT_EQ(disconnected_result.profile_io.outstanding_at_begin, 1u);
  EXPECT_EQ(disconnected_result.profile_io.succeeded_operations, 0u);
  EXPECT_EQ(disconnected_result.profile_io.failed_operations, 0u);
  EXPECT_EQ(disconnected_result.profile_io.abandoned_operations, 0u);
  EXPECT_FALSE(disconnected_observation->ClaimPostContentDrain().has_value());
  EXPECT_FALSE(disconnected_observation->ClaimPostContentFailureRetirement()
                   .has_value());
}

}  // namespace
}  // namespace chrome
