// Copyright 2019 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "components/variations/client_filterable_state.h"

#include <array>

#include "base/functional/bind.h"
#include "base/time/time.h"
#include "build/build_config.h"
#include "components/prefs/testing_pref_service.h"
#include "components/variations/pref_names.h"
#include "components/variations/study_filtering.h"
#include "components/variations/variations_seed_store.h"
#include "testing/gtest/include/gtest/gtest.h"

namespace variations {
namespace {

TEST(ClientFilterableStateTest, IsEnterprise) {
  // Test, for non enterprise clients, is_enterprise_function_ is called once.
  ClientFilterableState client_non_enterprise;
  EXPECT_FALSE(client_non_enterprise.IsEnterprise());
  EXPECT_FALSE(client_non_enterprise.IsEnterprise());

  // Test, for enterprise clients, is_enterprise_function_ is called once.
  std::unique_ptr<ClientFilterableState> client_enterprise =
      ClientFilterableState::CreateWithIsEnterprise(
          base::BindOnce([] { return true; }));
  EXPECT_TRUE(client_enterprise->IsEnterprise());
  EXPECT_TRUE(client_enterprise->IsEnterprise());
}

TEST(ClientFilterableStateTest, GoogleGroups) {
  // Test that google_groups_function_ is called once.
  base::flat_set<uint64_t> expected_google_groups({1234, 5678});
  std::unique_ptr<ClientFilterableState> client =
      ClientFilterableState::CreateWithGoogleGroups(base::BindOnce(
          [] { return base::flat_set<uint64_t>({1234, 5678}); }));
  EXPECT_EQ(client->GoogleGroups(), expected_google_groups);
  EXPECT_EQ(client->GoogleGroups(), expected_google_groups);
}

TEST(ClientFilterableStateTest, GetHardwareManufacturer) {
  std::string manufacturer = ClientFilterableState::GetHardwareManufacturer();
#if BUILDFLAG(IS_ANDROID)
  // On Android, the value is not hardcoded, but it should not be empty.
  EXPECT_FALSE(manufacturer.empty());
#else
  // For all other platforms, we expect the empty string fallback.
  EXPECT_TRUE(manufacturer.empty());
#endif
}

#if BUILDFLAG(IS_WASM)
TEST(ClientFilterableStateTest,
     WasmPlatformIsUnknownAndRejectsEverySeedPlatform) {
  constexpr auto seed_platforms = std::to_array<Study::Platform>(
      {Study::PLATFORM_WINDOWS, Study::PLATFORM_MAC, Study::PLATFORM_LINUX,
       Study::PLATFORM_CHROMEOS, Study::PLATFORM_ANDROID, Study::PLATFORM_IOS,
       Study::PLATFORM_ANDROID_WEBLAYER, Study::PLATFORM_FUCHSIA,
       Study::PLATFORM_ANDROID_WEBVIEW});
  static_assert(seed_platforms.size() == Study::Platform_ARRAYSIZE,
                "|seed_platforms| must include every seed platform.");

  EXPECT_EQ(Study::PLATFORM_UNKNOWN,
            ClientFilterableState::GetCurrentPlatform());

  // PLATFORM_UNKNOWN is a client-side sentinel, not a seed platform. Verify
  // that a study targeting any encoded platform cannot match this client.
  for (Study::Platform seed_platform : seed_platforms) {
    Study::Filter filter;
    filter.add_platform(seed_platform);
    EXPECT_FALSE(internal::CheckStudyPlatform(
        filter, ClientFilterableState::GetCurrentPlatform()))
        << "Seed platform " << seed_platform;
  }

  // Reject the sentinel even if a malformed seed tries to target it.
  Study::Filter invalid_filter;
  invalid_filter.add_platform(Study::PLATFORM_UNKNOWN);
  EXPECT_FALSE(internal::CheckStudyPlatform(
      invalid_filter, ClientFilterableState::GetCurrentPlatform()));
}
#endif

TEST(ClientFilterableStateTest, EnterpriseGroups) {
  // Test that enterprise_groups_function_ is called once.
  base::flat_set<std::string> expected_enterprise_groups({"abcd", "efgh"});
  std::unique_ptr<ClientFilterableState> client =
      ClientFilterableState::CreateWithEnterpriseGroups(base::BindOnce(
          [] { return base::flat_set<std::string>({"abcd", "efgh"}); }));
  EXPECT_EQ(client->EnterpriseGroups(), expected_enterprise_groups);
  EXPECT_EQ(client->EnterpriseGroups(), expected_enterprise_groups);
}

}  // namespace
}  // namespace variations
