// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <array>
#include <stdio.h>

#include "components/variations/client_filterable_state.h"
#include "components/variations/study_filtering.h"

namespace {

constexpr char kPrefix[] = "CHROMIUM_WASM_M3_VARIATIONS";

int Fail(const char* reason, variations::Study::Platform platform) {
  fprintf(stderr, "%s:FAIL reason=%s platform=%d\n", kPrefix, reason,
          static_cast<int>(platform));
  return 1;
}

}  // namespace

int main() {
  using variations::Study;

  printf("%s:RUNTIME_START\n", kPrefix);

  constexpr auto kSeedPlatforms = std::to_array<Study::Platform>(
      {Study::PLATFORM_WINDOWS, Study::PLATFORM_MAC, Study::PLATFORM_LINUX,
       Study::PLATFORM_CHROMEOS, Study::PLATFORM_ANDROID, Study::PLATFORM_IOS,
       Study::PLATFORM_ANDROID_WEBLAYER, Study::PLATFORM_FUCHSIA,
       Study::PLATFORM_ANDROID_WEBVIEW});
  static_assert(kSeedPlatforms.size() == Study::Platform_ARRAYSIZE,
                "|kSeedPlatforms| must include every seed platform.");

  const Study::Platform current_platform =
      variations::ClientFilterableState::GetCurrentPlatform();
  if (current_platform != Study::PLATFORM_UNKNOWN) {
    return Fail("platform_not_unknown", current_platform);
  }

  for (Study::Platform seed_platform : kSeedPlatforms) {
    Study::Filter filter;
    filter.add_platform(seed_platform);
    if (variations::internal::CheckStudyPlatform(filter, current_platform)) {
      return Fail("matched_seed_platform", seed_platform);
    }
  }

  Study::Filter invalid_filter;
  invalid_filter.add_platform(Study::PLATFORM_UNKNOWN);
  if (variations::internal::CheckStudyPlatform(invalid_filter,
                                               current_platform)) {
    return Fail("matched_unknown_seed_sentinel", current_platform);
  }

  printf("%s:PASS current_platform=%d seed_platforms=%zu\n", kPrefix,
         static_cast<int>(current_platform), kSeedPlatforms.size());
  return 0;
}
