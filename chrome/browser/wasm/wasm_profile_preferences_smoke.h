// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_PREFERENCES_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_PREFERENCES_SMOKE_H_

namespace user_prefs {
class PrefRegistrySyncable;
}

class PrefService;

namespace chrome {

// Fixed, test-only protocol for the two-fresh-module Preferences acceptance.
//
// Only chrome_wasm_m7_profile_preferences_test enables this capability. Its
// host supplies one of these complete argument sets:
//
//   --wasm-profile-preferences-smoke=write
//   --wasm-profile-preferences-token-a=<64 lowercase hex>
//
//   --wasm-profile-preferences-smoke=verify-and-write
//   --wasm-profile-preferences-token-a=<64 lowercase hex>
//   --wasm-profile-preferences-token-b=<64 lowercase hex>
//
// In verify-and-write mode token B must differ from token A.
//
// The raw tokens are written through PrefService but never leave this process
// in a marker or diagnostic. The host may consume only the following stderr
// grammar, where |digest| is exactly 64 lowercase hexadecimal characters and
// |stage| is one of arguments, capability, storage, profile, read, fence,
// lifecycle, content, or drain:
//
//   CHROMIUM_WASM_M7_PREFS:READY
//   CHROMIUM_WASM_M7_PREFS:READ_A_OK sha256=<64 lowercase hex>
//   CHROMIUM_WASM_M7_PREFS:WRITE_ACCEPTED sha256=<64 lowercase hex>
//   CHROMIUM_WASM_M7_PREFS:FENCE_OK sha256=<64 lowercase hex>
//   CHROMIUM_WASM_M7_PREFS:LEASE_RELEASED
//   CHROMIUM_WASM_M7_PREFS:FAIL stage=<fixed lowercase stage>
//
// The |write| mode emits READY, WRITE_ACCEPTED(A), FENCE_OK(A), and
// LEASE_RELEASED. The |verify-and-write| mode emits READY, READ_A_OK(A),
// WRITE_ACCEPTED(B), FENCE_OK(B), and LEASE_RELEASED. A failure emits at most
// one fixed FAIL line and no raw preference/token content.

// True when any switch in the test-only Preferences protocol is present. This
// includes orphaned token switches so ChromeMain can fail them before startup
// rather than silently falling through to ordinary browser startup.
bool HasWasmProfilePreferencesSmokeArguments();

// Validates the test-only command-line protocol and enables this module's
// process-local capability. ChromeMain calls this only in the dedicated test
// executable. On invalid input it emits the redacted arguments failure marker.
bool EnableWasmProfilePreferencesSmokeTestMode();

// Whether the dedicated test executable enabled a valid smoke configuration.
bool IsWasmProfilePreferencesSmokeEnabled();

// Registers the one dedicated non-default user preference only while this
// test capability is enabled. This must run before PrefService construction.
void RegisterWasmProfilePreferencesSmokePref(
    user_prefs::PrefRegistrySyncable* registry);

// Starts the profile-side acceptance action after the profile storage lifecycle
// admitted the profile. It verifies token A before writing B in the second
// module, and otherwise writes token A. Returns false after emitting a
// redacted failure marker.
bool StartWasmProfilePreferencesSmoke(PrefService* prefs);

// These result-bearing lifecycle notifications complete the fixed marker
// sequence. Callers supply only fixed booleans, never an underlying error or
// token, so the smoke cannot expose Preferences content through diagnostics.
void NotifyWasmProfilePreferencesSmokeFenceResult(bool success);
void NotifyWasmProfilePreferencesSmokeStorageLifecycle(bool success);
void NotifyWasmProfilePreferencesSmokeBackendDrain(bool success);

// Reports one fixed failure stage. Repeated calls are intentionally silent so
// a host never has to interpret a partial sequence with multiple failures.
enum class WasmProfilePreferencesSmokeFailureStage {
  kArguments,
  kCapability,
  kStorage,
  kProfile,
  kRead,
  kFence,
  kLifecycle,
  kContent,
  kDrain,
};
void ReportWasmProfilePreferencesSmokeFailure(
    WasmProfilePreferencesSmokeFailureStage stage);

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_PROFILE_PREFERENCES_SMOKE_H_
