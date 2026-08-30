// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_STORAGE_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_STORAGE_H_

#include <optional>

#include "chrome/browser/wasm/wasm_profile_ordered_drain_lifecycle.h"
#include "chrome/browser/wasm/wasm_profile_storage_drain_result.h"

namespace chrome {

// Mounts the database acceptance probe's profile root on the V4 leased-OPFS
// WasmFS filesystem backend. It must run on Chromium's application pthread
// before ContentMain can register or resolve DIR_USER_DATA.
bool InitializeWasmProfileStorage();

#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST)
// Mounts one dedicated Default-profile acceptance's leased V4 OPFS backend
// only at /profile/Default. Its /profile parent remains on WasmFS's default
// memory backend, which the initializer validates before and after the child
// mount. This is unavailable from normal Chrome.
bool InitializeWasmProfilePreferencesStorage();
#endif

// Returns true only while the exact V4 leased-OPFS mount remains available.
bool IsWasmProfileStorageMounted();

// Returns true when ChromeMain must drain the exact V4 leased backend after its
// ContentMain delegate scope is gone. This is also true after a failed mount
// if backend construction acquired the lease: cleanup must not race startup
// object destruction.
bool NeedsWasmProfileStorageBackendDrain();

// Starts the source-selected profile construction epoch before BrowserMainParts
// resolves /profile or creates Default, and before WasmProfile can
// synchronously read Preferences. It creates the registered-I/O lifecycle and
// returns the one construction admission; BrowserMainParts must transfer that
// hold into WasmProfile before JsonPrefStore/PrefService construction begins.
// ProfileCreated remains a distinct post-construction notification.
std::optional<WasmProfileOrderedDrainLifecycle::ProfileIOHold>
BeginWasmProfileStorageProfileConstruction();

// Permanently selects fail-closed retirement when construction cannot acquire
// its admission or cannot reach post-construction ProfileCreated(). This is
// only for the precreation path; it closes admission, retains the profile
// lease, and never authorizes a clean backend handoff.
// A mounted backend that reaches final drain without ProfileCreated() takes
// the same fail-closed retirement path even if construction never began.
bool AbortWasmProfileStorageProfileConstructionFailClosed();

// Marks the lifetime of successfully constructed Chrome profile services.
// Browser main parts calls this only after WasmProfile construction succeeds;
// a live profile's lease cannot be released before its shutdown completes.
bool NotifyWasmProfileStorageProfileCreated();
bool NotifyWasmProfileStorageProfileShutdown();

// Records terminal profile destruction after the UI-loop shutdown path could
// not certify a complete profile handoff. This still closes profile-I/O
// admission and requires quiescence, but it permanently selects WasmFS's
// fail-closed retirement instead of releasing the profile lease. It is only
// for BrowserMainParts' foundation fallback; normal shutdown must use the
// ordinary notification above.
bool NotifyWasmProfileStorageProfileShutdownFailClosed();

// Admits one known profile-storage operation while the mounted test profile is
// live. Ordinary returned holds must report a terminal result. The dedicated
// source-selected outstanding-I/O refusal diagnostic briefly retains one
// completed task's admission so it can prove the post-ContentMain drain
// refuses an unfinished epoch. Once profile shutdown begins, new admissions
// are refused and a normal post-ContentMain backend drain requires the
// resulting one-shot permit. This is intentionally exposed only to the
// narrowly source-selected M7 test profile owners; it does not imply that
// normal Chrome profile services are persistent.
std::optional<WasmProfileOrderedDrainLifecycle::ProfileIOHold>
TryAcquireWasmProfileStorageProfileIO();

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_OUTSTANDING_IO_REFUSAL_TEST)
// Transfers the deliberately retained admission from the completed database
// task into the storage owner. ChromeMain records the resulting first drain
// refusal, then completes this hold as failed before it asks the same storage
// owner to make a separate fail-closed cleanup transaction. This is a
// source-selected diagnostic seam, not an admission mechanism for Chrome
// services.
bool RetainWasmProfileStorageOutstandingIOForRefusalTest(
    WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold);

// Completes the retained diagnostic admission as failed after ChromeMain has
// recorded the exact pre-transaction refusal. This intentionally selects a
// later fail-closed cleanup rather than authorizing a clean lease handoff.
bool CompleteWasmProfileStorageOutstandingIORefusalAsFailedForTest();
#endif

// Attempts to permanently seal Chrome's V4 leased OPFS filesystem backend.
// After construction starts, it first requires an explicit shutdown
// quiescence observation and one one-shot post-ContentMain permit. A clean
// epoch uses the normal WasmFS drain, releases its profile lease, and retires
// its dedicated worker. A failed or abandoned epoch, a precreation abort, or
// a foundation-fallback notification uses WasmFS's explicit fail-closed
// retirement instead: it closes private OPFS handles but retains the lease
// and reports a non-success result. An outstanding admitted epoch refuses
// before either outer backend drain/retirement transaction and leaves that
// individual transaction unstarted. The source-selected refusal diagnostic
// may later complete its retained admission as failed and make a separate
// fail-closed cleanup call. ChromeMain calls this only after ContentMain
// returns, because the profile backend must be quiesced after all Content
// teardown. Unrelated WasmFS operations and the normal Emscripten exit tail
// remain usable.
WasmProfileStorageDrainResult DrainAndReleaseWasmProfileStorageBackend();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_PROFILE_STORAGE_H_
