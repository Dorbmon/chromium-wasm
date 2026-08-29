// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_PREFERENCES_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_PREFERENCES_SMOKE_H_

#include <optional>
#include <string>

namespace user_prefs {
class PrefRegistrySyncable;
}

class PrefService;

namespace chrome {

// The raw token bundle is transferred exactly once from the Preferences
// protocol to the optional CookieManager probe after the bounded Browser
// lifecycle. Its fields must never be placed in a marker or diagnostic.
struct WasmProfilePreferencesCookieSmokeInput {
  enum class Mode {
    kWrite,
    kVerifyAndWrite,
    kVerifyB,
  };

  Mode mode = Mode::kWrite;
  std::string token_a;
  std::string token_b;
  std::string token_a_digest;
  std::string token_b_digest;
};

// Fixed, test-only protocol for the three-fresh-module Preferences acceptance.
//
// Only chrome_wasm_m7_profile_preferences_test enables this capability. Its
// host supplies one of these complete argument sets:
//
//   --wasm-profile-preferences-smoke=write
//   --wasm-profile-preferences-token-a=<64 lowercase hex>
//   [--wasm-profile-preferences-browser-smoke]
//   [--wasm-profile-preferences-history-smoke]
//   [--wasm-profile-preferences-cookie-smoke]
//
//   --wasm-profile-preferences-smoke=verify-and-write
//   --wasm-profile-preferences-token-a=<64 lowercase hex>
//   --wasm-profile-preferences-token-b=<64 lowercase hex>
//   [--wasm-profile-preferences-browser-smoke]
//   [--wasm-profile-preferences-history-smoke]
//   [--wasm-profile-preferences-cookie-smoke]
//
//   --wasm-profile-preferences-smoke=verify-b
//   --wasm-profile-preferences-token-b=<64 lowercase hex>
//   [--wasm-profile-preferences-browser-smoke]
//   [--wasm-profile-preferences-history-smoke]
//   [--wasm-profile-preferences-cookie-smoke]
//
// In verify-and-write mode token B must differ from token A.
//
// The raw tokens are written through PrefService but never leave this process
// in a marker or diagnostic. The host may consume only the following stderr
// grammar, where |digest| is exactly 64 lowercase hexadecimal characters and
// |stage| is one of arguments, capability, storage, profile, browser, cookie,
// history, read, fence, lifecycle, content, or drain:
//
//   CHROMIUM_WASM_M7_PREFS:READY
//   CHROMIUM_WASM_M7_PREFS:READ_A_OK sha256=<64 lowercase hex>
//   CHROMIUM_WASM_M7_PREFS:READ_B_OK sha256=<64 lowercase hex>
//   CHROMIUM_WASM_M7_PREFS:WRITE_ACCEPTED sha256=<64 lowercase hex>
//   CHROMIUM_WASM_M7_PREFS:BROWSER_SMOKE_CLOSED
//   CHROMIUM_WASM_M7_PREFS:HISTORY_A_WRITE_ACCEPTED
//   CHROMIUM_WASM_M7_PREFS:HISTORY_A_READ_OK
//   CHROMIUM_WASM_M7_PREFS:HISTORY_B_WRITE_ACCEPTED
//   CHROMIUM_WASM_M7_PREFS:HISTORY_B_READ_OK
//   CHROMIUM_WASM_M7_PREFS:HISTORY_BACKEND_CLOSED
//   CHROMIUM_WASM_M7_PREFS:COOKIE_A_WRITE_FLUSHED sha256=<64 lowercase hex>
//   CHROMIUM_WASM_M7_PREFS:COOKIE_A_READ_OK sha256=<64 lowercase hex>
//   CHROMIUM_WASM_M7_PREFS:COOKIE_B_WRITE_FLUSHED sha256=<64 lowercase hex>
//   CHROMIUM_WASM_M7_PREFS:COOKIE_B_READ_OK sha256=<64 lowercase hex>
//   CHROMIUM_WASM_M7_PREFS:COOKIE_BACKEND_CLOSED
//   CHROMIUM_WASM_M7_PREFS:FENCE_OK sha256=<64 lowercase hex>
//   CHROMIUM_WASM_M7_PREFS:LEASE_RELEASED
//   CHROMIUM_WASM_M7_PREFS:FAIL stage=<fixed lowercase stage>
//
// The |write| mode emits READY, WRITE_ACCEPTED(A), FENCE_OK(A), and
// LEASE_RELEASED. The |verify-and-write| mode emits READY, READ_A_OK(A),
// WRITE_ACCEPTED(B), FENCE_OK(B), and LEASE_RELEASED. The |verify-b| mode
// emits READY, READ_B_OK(B), FENCE_OK(B), and LEASE_RELEASED. A failure emits
// at most one fixed FAIL line and no raw preference/token content.
//
// When the bare Browser switch is present, every successful mode additionally
// emits BROWSER_SMOKE_CLOSED after a fixed real Browser lifecycle has torn
// down and before its Preferences shutdown fence can succeed.
//
// The bare History switch requires the Browser switch. It starts a separately
// owned core HistoryService after that Browser lifecycle, verifies its fixed
// History/Favicons SQLite read or write sequence, and holds V4 profile I/O
// admission until HistoryBackend has closed both databases. A successful
// history run emits its fixed progress markers and HISTORY_BACKEND_CLOSED
// before the Preferences fence. This is a test-only core-service witness, not
// a claim that desktop navigation, History UI, bookmarks, or every normal
// profile store has been made persistent.

// The bare Cookie switch also requires the Browser switch. It enables only the
// default in-memory StoragePartition's CookieManager to select a persistent
// Cookie database under the V4-mounted Default profile. All other
// StoragePartition stores remain in memory. The probe writes or reads one
// persistent HttpOnly cookie, validates it through CookieManager, then waits
// for FlushCookieStore and the dedicated test-only SQLite backend-close fence
// before profile shutdown. It is deliberately an unencrypted, test-only
// persistence witness: it does not claim persistent session cookies, HTTP
// cache, DOM storage, service workers, or general profile-service coverage.
//
// A History database-open failure or query-validation failure additionally
// emits the fixed, redacted HISTORY_DATABASE_PROFILE_ERROR or
// HISTORY_QUERY_VALIDATION_FAILED checkpoint before the single FAIL
// stage=history line. The latter is preceded by one fixed cause marker:
// HISTORY_QUERY_NOT_FOUND, HISTORY_QUERY_URL_MISMATCH,
// HISTORY_QUERY_TITLE_MISMATCH, or HISTORY_QUERY_NO_VISITS. None carries SQL
// diagnostics, a filesystem path, a query value, or a token.

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

// Whether this validated Preferences test run must complete the bounded real
// Browser lifecycle before its durable Preferences shutdown fence.
bool IsWasmProfilePreferencesBrowserSmokeEnabled();

// Whether this validated Preferences test run must also complete the
// test-only HistoryService read/write and backend-close witness. It is valid
// only together with the bounded Browser lifecycle switch.
bool IsWasmProfilePreferencesHistorySmokeEnabled();

// Whether this validated Preferences test run must complete the test-only
// CookieManager write/read, FlushCookieStore, and SQLite backend-close witness.
// It is valid only together with the bounded Browser lifecycle switch.
bool IsWasmProfilePreferencesCookieSmokeEnabled();

// Transfers the opaque raw inputs to the optional CookieManager probe exactly
// once after Preferences has used them. Returning no value is a fixed
// capability failure. No caller may log the returned values.
std::optional<WasmProfilePreferencesCookieSmokeInput>
TakeWasmProfilePreferencesCookieSmokeInput();

// Registers the one dedicated non-default user preference only while this
// test capability is enabled. This must run before PrefService construction.
void RegisterWasmProfilePreferencesSmokePref(
    user_prefs::PrefRegistrySyncable* registry);

// Starts the profile-side acceptance action after the profile storage lifecycle
// admitted the profile. It writes token A in the first module, verifies A
// before writing B in the second, and verifies B in the third. Returns false
// after emitting a redacted failure marker.
bool StartWasmProfilePreferencesSmoke(PrefService* prefs);

// Records the terminal result from the fixed real Browser smoke. A successful
// result emits the fixed BROWSER_SMOKE_CLOSED marker; an invalid sequence or
// failed Browser path reports the redacted browser failure stage.
void NotifyWasmProfilePreferencesBrowserSmokeResult(bool success);

// Records the terminal result from the test-only HistoryService probe. A
// successful result emits HISTORY_BACKEND_CLOSED; an invalid sequence or
// failed History path reports the redacted history failure stage.
void NotifyWasmProfilePreferencesHistorySmokeResult(bool success);

// True only when the optional HistoryService probe closed successfully.
bool DidWasmProfilePreferencesHistorySmokeSucceed();

// Records the terminal result from the test-only CookieManager probe. The
// probe itself emits the redacted fixed/digest cookie markers after its local
// validation, FlushCookieStore callback, and backend-close fence. A failed
// path reports the redacted cookie failure stage.
void NotifyWasmProfilePreferencesCookieSmokeResult(bool success);

// True only when the optional CookieManager probe completed its local
// validation, FlushCookieStore callback, and SQLite backend-close callback
// successfully.
bool DidWasmProfilePreferencesCookieSmokeSucceed();

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
  kBrowser,
  kCookie,
  kHistory,
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
