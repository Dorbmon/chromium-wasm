// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_preferences_smoke.h"

#include <cstdio>
#include <string>
#include <string_view>

#include "base/command_line.h"
#include "base/no_destructor.h"
#include "base/strings/string_number_conversions.h"
#include "build/build_config.h"
#include "components/pref_registry/pref_registry_syncable.h"
#include "components/prefs/pref_service.h"
#include "crypto/hash.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_profile_preferences_smoke.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kSmokeSwitch[] = "wasm-profile-preferences-smoke";
constexpr char kTokenASwitch[] = "wasm-profile-preferences-token-a";
constexpr char kTokenBSwitch[] = "wasm-profile-preferences-token-b";
constexpr char kWriteMode[] = "write";
constexpr char kVerifyAndWriteMode[] = "verify-and-write";
constexpr char kVerifyBMode[] = "verify-b";
constexpr char kSmokePref[] = "wasm.profile.m7_preferences_smoke_token";
constexpr size_t kOpaqueTokenLength = 64;

constexpr char kMarkerPrefix[] = "CHROMIUM_WASM_M7_PREFS:";

enum class SmokeMode {
  kNone,
  kWrite,
  kVerifyAndWrite,
  kVerifyB,
};

class WasmProfilePreferencesSmokeState {
 public:
  WasmProfilePreferencesSmokeState() = default;
  WasmProfilePreferencesSmokeState(const WasmProfilePreferencesSmokeState&) =
      delete;
  WasmProfilePreferencesSmokeState& operator=(
      const WasmProfilePreferencesSmokeState&) = delete;
  ~WasmProfilePreferencesSmokeState() = default;

  bool EnableFromCommandLine() {
    if (configured_) {
      return enabled_;
    }
    configured_ = true;

    const base::CommandLine* command_line =
        base::CommandLine::ForCurrentProcess();
    const bool has_mode = command_line->HasSwitch(kSmokeSwitch);
    const bool has_token_a = command_line->HasSwitch(kTokenASwitch);
    const bool has_token_b = command_line->HasSwitch(kTokenBSwitch);
    if (!has_mode) {
      ReportFailure(WasmProfilePreferencesSmokeFailureStage::kArguments);
      return false;
    }

    const std::string mode = command_line->GetSwitchValueASCII(kSmokeSwitch);
    if (mode == kWriteMode) {
      if (!has_token_a || has_token_b) {
        ReportFailure(WasmProfilePreferencesSmokeFailureStage::kArguments);
        return false;
      }
      token_a_ = command_line->GetSwitchValueASCII(kTokenASwitch);
      if (!IsOpaqueToken(token_a_)) {
        ReportFailure(WasmProfilePreferencesSmokeFailureStage::kArguments);
        return false;
      }
      mode_ = SmokeMode::kWrite;
    } else if (mode == kVerifyAndWriteMode) {
      if (!has_token_a || !has_token_b) {
        ReportFailure(WasmProfilePreferencesSmokeFailureStage::kArguments);
        return false;
      }
      token_a_ = command_line->GetSwitchValueASCII(kTokenASwitch);
      token_b_ = command_line->GetSwitchValueASCII(kTokenBSwitch);
      if (!IsOpaqueToken(token_a_) || !IsOpaqueToken(token_b_) ||
          token_b_ == token_a_) {
        ReportFailure(WasmProfilePreferencesSmokeFailureStage::kArguments);
        return false;
      }
      mode_ = SmokeMode::kVerifyAndWrite;
    } else if (mode == kVerifyBMode) {
      if (has_token_a || !has_token_b) {
        ReportFailure(WasmProfilePreferencesSmokeFailureStage::kArguments);
        return false;
      }
      token_b_ = command_line->GetSwitchValueASCII(kTokenBSwitch);
      if (!IsOpaqueToken(token_b_)) {
        ReportFailure(WasmProfilePreferencesSmokeFailureStage::kArguments);
        return false;
      }
      mode_ = SmokeMode::kVerifyB;
    } else {
      ReportFailure(WasmProfilePreferencesSmokeFailureStage::kArguments);
      return false;
    }

    if (!token_a_.empty()) {
      token_a_digest_ = DigestToken(token_a_);
    }
    if (!token_b_.empty()) {
      token_b_digest_ = DigestToken(token_b_);
    }
    enabled_ = true;
    return true;
  }

  bool enabled() const { return enabled_; }

  bool Start(PrefService* prefs) {
    if (!enabled_ || started_ || !prefs) {
      ReportFailure(WasmProfilePreferencesSmokeFailureStage::kProfile);
      return false;
    }
    started_ = true;
    EmitMarker("READY");

    if (mode_ == SmokeMode::kVerifyAndWrite) {
      // The first module persisted raw token A through JsonPrefStore. Compare
      // only inside the application and emit its SHA-256 digest on success.
      if (prefs->GetString(kSmokePref) != token_a_) {
        ReportFailure(WasmProfilePreferencesSmokeFailureStage::kRead);
        return false;
      }
      EmitDigestMarker("READ_A_OK", token_a_digest_);
      prefs->SetString(kSmokePref, token_b_);
      expected_fence_digest_ = token_b_digest_;
      EmitDigestMarker("WRITE_ACCEPTED", token_b_digest_);
    } else if (mode_ == SmokeMode::kVerifyB) {
      // The second module persisted raw token B through JsonPrefStore.
      // Compare only inside the application and expose only its digest.
      if (prefs->GetString(kSmokePref) != token_b_) {
        ReportFailure(WasmProfilePreferencesSmokeFailureStage::kRead);
        return false;
      }
      expected_fence_digest_ = token_b_digest_;
      EmitDigestMarker("READ_B_OK", token_b_digest_);
    } else if (mode_ == SmokeMode::kWrite) {
      prefs->SetString(kSmokePref, token_a_);
      expected_fence_digest_ = token_a_digest_;
      EmitDigestMarker("WRITE_ACCEPTED", token_a_digest_);
    } else {
      ReportFailure(WasmProfilePreferencesSmokeFailureStage::kProfile);
      return false;
    }

    // The pref store now owns the raw value. Retain only its digest for the
    // asynchronous fence marker; no later diagnostic needs the token itself.
    ClearRawTokens();
    return true;
  }

  void NotifyFenceResult(bool success) {
    if (!enabled_ || failure_reported_) {
      return;
    }
    if (!success || !started_ || expected_fence_digest_.empty()) {
      ReportFailure(WasmProfilePreferencesSmokeFailureStage::kFence);
      return;
    }
    if (fence_succeeded_) {
      ReportFailure(WasmProfilePreferencesSmokeFailureStage::kFence);
      return;
    }
    fence_succeeded_ = true;
    EmitDigestMarker("FENCE_OK", expected_fence_digest_);
  }

  void NotifyStorageLifecycle(bool success) {
    if (!enabled_ || failure_reported_) {
      return;
    }
    if (!success || !fence_succeeded_ || storage_lifecycle_succeeded_) {
      ReportFailure(WasmProfilePreferencesSmokeFailureStage::kLifecycle);
      return;
    }
    storage_lifecycle_succeeded_ = true;
  }

  void NotifyBackendDrain(bool success) {
    if (!enabled_ || failure_reported_) {
      return;
    }
    if (!success || !fence_succeeded_ || !storage_lifecycle_succeeded_) {
      ReportFailure(WasmProfilePreferencesSmokeFailureStage::kDrain);
      return;
    }
    if (lease_released_) {
      ReportFailure(WasmProfilePreferencesSmokeFailureStage::kDrain);
      return;
    }
    lease_released_ = true;
    EmitMarker("LEASE_RELEASED");
  }

  void ReportFailure(WasmProfilePreferencesSmokeFailureStage stage) {
    if (failure_reported_) {
      return;
    }
    // Do not retain an opaque raw token across an arguments, read, or startup
    // failure. The command line remains process-owned, but this helper's
    // state must retain only a digest after it reports its fixed marker.
    ClearRawTokens();
    failure_reported_ = true;
    std::fprintf(stderr, "%sFAIL stage=%s\n", kMarkerPrefix,
                 FailureStageName(stage));
    std::fflush(stderr);
  }

 private:
  static bool IsOpaqueToken(std::string_view value) {
    if (value.size() != kOpaqueTokenLength) {
      return false;
    }
    for (const char character : value) {
      if (!((character >= '0' && character <= '9') ||
            (character >= 'a' && character <= 'f'))) {
        return false;
      }
    }
    return true;
  }

  static std::string DigestToken(std::string_view token) {
    return base::HexEncodeLower(crypto::hash::Sha256(token));
  }

  static const char* FailureStageName(
      WasmProfilePreferencesSmokeFailureStage stage) {
    switch (stage) {
      case WasmProfilePreferencesSmokeFailureStage::kArguments:
        return "arguments";
      case WasmProfilePreferencesSmokeFailureStage::kCapability:
        return "capability";
      case WasmProfilePreferencesSmokeFailureStage::kStorage:
        return "storage";
      case WasmProfilePreferencesSmokeFailureStage::kProfile:
        return "profile";
      case WasmProfilePreferencesSmokeFailureStage::kRead:
        return "read";
      case WasmProfilePreferencesSmokeFailureStage::kFence:
        return "fence";
      case WasmProfilePreferencesSmokeFailureStage::kLifecycle:
        return "lifecycle";
      case WasmProfilePreferencesSmokeFailureStage::kContent:
        return "content";
      case WasmProfilePreferencesSmokeFailureStage::kDrain:
        return "drain";
    }
    return "drain";
  }

  void EmitMarker(const char* marker) {
    std::fprintf(stderr, "%s%s\n", kMarkerPrefix, marker);
    std::fflush(stderr);
  }

  void EmitDigestMarker(const char* marker, const std::string& digest) {
    std::fprintf(stderr, "%s%s sha256=%s\n", kMarkerPrefix, marker,
                 digest.c_str());
    std::fflush(stderr);
  }

  void ClearRawTokens() {
    token_a_.clear();
    token_b_.clear();
  }

  bool configured_ = false;
  bool enabled_ = false;
  bool started_ = false;
  bool fence_succeeded_ = false;
  bool storage_lifecycle_succeeded_ = false;
  bool lease_released_ = false;
  bool failure_reported_ = false;
  SmokeMode mode_ = SmokeMode::kNone;
  std::string token_a_;
  std::string token_b_;
  std::string token_a_digest_;
  std::string token_b_digest_;
  std::string expected_fence_digest_;
};

WasmProfilePreferencesSmokeState& GetWasmProfilePreferencesSmokeState() {
  static base::NoDestructor<WasmProfilePreferencesSmokeState> state;
  return *state;
}

}  // namespace

bool HasWasmProfilePreferencesSmokeArguments() {
  const base::CommandLine* command_line = base::CommandLine::ForCurrentProcess();
  return command_line->HasSwitch(kSmokeSwitch) ||
         command_line->HasSwitch(kTokenASwitch) ||
         command_line->HasSwitch(kTokenBSwitch);
}

bool EnableWasmProfilePreferencesSmokeTestMode() {
  return GetWasmProfilePreferencesSmokeState().EnableFromCommandLine();
}

bool IsWasmProfilePreferencesSmokeEnabled() {
  return GetWasmProfilePreferencesSmokeState().enabled();
}

void RegisterWasmProfilePreferencesSmokePref(
    user_prefs::PrefRegistrySyncable* registry) {
  if (!IsWasmProfilePreferencesSmokeEnabled()) {
    return;
  }
  registry->RegisterStringPref(kSmokePref, std::string());
}

bool StartWasmProfilePreferencesSmoke(PrefService* prefs) {
  return GetWasmProfilePreferencesSmokeState().Start(prefs);
}

void NotifyWasmProfilePreferencesSmokeFenceResult(bool success) {
  GetWasmProfilePreferencesSmokeState().NotifyFenceResult(success);
}

void NotifyWasmProfilePreferencesSmokeStorageLifecycle(bool success) {
  GetWasmProfilePreferencesSmokeState().NotifyStorageLifecycle(success);
}

void NotifyWasmProfilePreferencesSmokeBackendDrain(bool success) {
  GetWasmProfilePreferencesSmokeState().NotifyBackendDrain(success);
}

void ReportWasmProfilePreferencesSmokeFailure(
    WasmProfilePreferencesSmokeFailureStage stage) {
  GetWasmProfilePreferencesSmokeState().ReportFailure(stage);
}

}  // namespace chrome
