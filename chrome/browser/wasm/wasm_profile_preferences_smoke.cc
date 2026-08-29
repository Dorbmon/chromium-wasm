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
constexpr char kBrowserSmokeSwitch[] =
    "wasm-profile-preferences-browser-smoke";
constexpr char kHistorySmokeSwitch[] =
    "wasm-profile-preferences-history-smoke";
constexpr char kCookieSmokeSwitch[] =
    "wasm-profile-preferences-cookie-smoke";
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
    const bool has_browser_smoke =
        command_line->HasSwitch(kBrowserSmokeSwitch);
    const bool has_history_smoke =
        command_line->HasSwitch(kHistorySmokeSwitch);
    const bool has_cookie_smoke =
        command_line->HasSwitch(kCookieSmokeSwitch);
    if (!has_mode) {
      ReportFailure(WasmProfilePreferencesSmokeFailureStage::kArguments);
      return false;
    }
    if (has_browser_smoke &&
        !command_line->GetSwitchValueASCII(kBrowserSmokeSwitch).empty()) {
      ReportFailure(WasmProfilePreferencesSmokeFailureStage::kArguments);
      return false;
    }
    if (has_history_smoke &&
        (!has_browser_smoke ||
         !command_line->GetSwitchValueASCII(kHistorySmokeSwitch).empty())) {
      ReportFailure(WasmProfilePreferencesSmokeFailureStage::kArguments);
      return false;
    }
    if (has_cookie_smoke &&
        (!has_browser_smoke ||
         !command_line->GetSwitchValueASCII(kCookieSmokeSwitch).empty())) {
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
    browser_smoke_required_ = has_browser_smoke;
    history_smoke_required_ = has_history_smoke;
    cookie_smoke_required_ = has_cookie_smoke;
    enabled_ = true;
    return true;
  }

  bool enabled() const { return enabled_; }

  bool browser_smoke_required() const {
    return enabled_ && browser_smoke_required_;
  }

  bool history_smoke_required() const {
    return enabled_ && history_smoke_required_;
  }

  bool cookie_smoke_required() const {
    return enabled_ && cookie_smoke_required_;
  }

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
    // asynchronous fence marker unless the separately opt-in CookieManager
    // probe must take the same opaque inputs after the Browser lifecycle.
    if (!cookie_smoke_required_) {
      ClearRawTokens();
    }
    return true;
  }

  std::optional<WasmProfilePreferencesCookieSmokeInput>
  TakeCookieSmokeInput() {
    if (!enabled_ || failure_reported_ || !started_ ||
        !cookie_smoke_required_ || cookie_smoke_input_taken_ ||
        !browser_smoke_completed_) {
      ReportFailure(WasmProfilePreferencesSmokeFailureStage::kCapability);
      return std::nullopt;
    }

    cookie_smoke_input_taken_ = true;
    WasmProfilePreferencesCookieSmokeInput input;
    switch (mode_) {
      case SmokeMode::kWrite:
        input.mode = WasmProfilePreferencesCookieSmokeInput::Mode::kWrite;
        break;
      case SmokeMode::kVerifyAndWrite:
        input.mode =
            WasmProfilePreferencesCookieSmokeInput::Mode::kVerifyAndWrite;
        break;
      case SmokeMode::kVerifyB:
        input.mode = WasmProfilePreferencesCookieSmokeInput::Mode::kVerifyB;
        break;
      case SmokeMode::kNone:
        ReportFailure(WasmProfilePreferencesSmokeFailureStage::kCapability);
        return std::nullopt;
    }
    input.token_a = std::move(token_a_);
    input.token_b = std::move(token_b_);
    input.token_a_digest = token_a_digest_;
    input.token_b_digest = token_b_digest_;
    ClearRawTokens();
    return input;
  }

  void NotifyBrowserSmokeResult(bool success) {
    if (!enabled_ || failure_reported_) {
      return;
    }
    if (!success || !started_ || !browser_smoke_required_ ||
        browser_smoke_completed_) {
      ReportFailure(WasmProfilePreferencesSmokeFailureStage::kBrowser);
      return;
    }
    browser_smoke_completed_ = true;
    EmitMarker("BROWSER_SMOKE_CLOSED");
  }

  void NotifyHistorySmokeResult(bool success) {
    if (!enabled_ || failure_reported_) {
      return;
    }
    if (!success || !started_ || !history_smoke_required_ ||
        !browser_smoke_completed_ ||
        (cookie_smoke_required_ && !cookie_smoke_completed_) ||
        history_smoke_completed_) {
      ReportFailure(WasmProfilePreferencesSmokeFailureStage::kHistory);
      return;
    }
    history_smoke_completed_ = true;
    EmitMarker("HISTORY_BACKEND_CLOSED");
  }

  bool history_smoke_succeeded() const {
    return enabled_ && history_smoke_required_ && history_smoke_completed_ &&
           !failure_reported_;
  }

  void NotifyCookieSmokeResult(bool success) {
    if (!enabled_ || failure_reported_) {
      return;
    }
    if (!success || !started_ || !cookie_smoke_required_ ||
        !browser_smoke_completed_ || !cookie_smoke_input_taken_ ||
        cookie_smoke_completed_) {
      ReportFailure(WasmProfilePreferencesSmokeFailureStage::kCookie);
      return;
    }
    cookie_smoke_completed_ = true;
  }

  bool cookie_smoke_succeeded() const {
    return enabled_ && cookie_smoke_required_ && cookie_smoke_completed_ &&
           !failure_reported_;
  }

  void NotifyFenceResult(bool success) {
    if (!enabled_ || failure_reported_) {
      return;
    }
    if (browser_smoke_required_ && !browser_smoke_completed_) {
      ReportFailure(WasmProfilePreferencesSmokeFailureStage::kBrowser);
      return;
    }
    if (cookie_smoke_required_ && !cookie_smoke_completed_) {
      ReportFailure(WasmProfilePreferencesSmokeFailureStage::kCookie);
      return;
    }
    if (history_smoke_required_ && !history_smoke_completed_) {
      ReportFailure(WasmProfilePreferencesSmokeFailureStage::kHistory);
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
      case WasmProfilePreferencesSmokeFailureStage::kBrowser:
        return "browser";
      case WasmProfilePreferencesSmokeFailureStage::kCookie:
        return "cookie";
      case WasmProfilePreferencesSmokeFailureStage::kHistory:
        return "history";
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
  bool browser_smoke_required_ = false;
  bool browser_smoke_completed_ = false;
  bool cookie_smoke_required_ = false;
  bool cookie_smoke_input_taken_ = false;
  bool cookie_smoke_completed_ = false;
  bool history_smoke_required_ = false;
  bool history_smoke_completed_ = false;
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
         command_line->HasSwitch(kTokenBSwitch) ||
         command_line->HasSwitch(kBrowserSmokeSwitch) ||
         command_line->HasSwitch(kHistorySmokeSwitch) ||
         command_line->HasSwitch(kCookieSmokeSwitch);
}

bool EnableWasmProfilePreferencesSmokeTestMode() {
  return GetWasmProfilePreferencesSmokeState().EnableFromCommandLine();
}

bool IsWasmProfilePreferencesSmokeEnabled() {
  return GetWasmProfilePreferencesSmokeState().enabled();
}

bool IsWasmProfilePreferencesBrowserSmokeEnabled() {
  return GetWasmProfilePreferencesSmokeState().browser_smoke_required();
}

bool IsWasmProfilePreferencesHistorySmokeEnabled() {
  return GetWasmProfilePreferencesSmokeState().history_smoke_required();
}

bool IsWasmProfilePreferencesCookieSmokeEnabled() {
  return GetWasmProfilePreferencesSmokeState().cookie_smoke_required();
}

std::optional<WasmProfilePreferencesCookieSmokeInput>
TakeWasmProfilePreferencesCookieSmokeInput() {
  return GetWasmProfilePreferencesSmokeState().TakeCookieSmokeInput();
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

void NotifyWasmProfilePreferencesBrowserSmokeResult(bool success) {
  GetWasmProfilePreferencesSmokeState().NotifyBrowserSmokeResult(success);
}

void NotifyWasmProfilePreferencesHistorySmokeResult(bool success) {
  GetWasmProfilePreferencesSmokeState().NotifyHistorySmokeResult(success);
}

bool DidWasmProfilePreferencesHistorySmokeSucceed() {
  return GetWasmProfilePreferencesSmokeState().history_smoke_succeeded();
}

void NotifyWasmProfilePreferencesCookieSmokeResult(bool success) {
  GetWasmProfilePreferencesSmokeState().NotifyCookieSmokeResult(success);
}

bool DidWasmProfilePreferencesCookieSmokeSucceed() {
  return GetWasmProfilePreferencesSmokeState().cookie_smoke_succeeded();
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
