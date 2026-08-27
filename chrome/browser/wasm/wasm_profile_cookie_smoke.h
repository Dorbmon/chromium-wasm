// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_COOKIE_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_COOKIE_SMOKE_H_

#include "base/functional/callback_forward.h"
#include "chrome/browser/wasm/wasm_profile_preferences_smoke.h"

class WasmProfile;

namespace chrome {

// Starts the test-only CookieManager persistence probe selected by the
// optional Preferences acceptance argument. The completion runs on the
// initiating UI sequence after CookieManager's FlushCookieStore callback and
// its dedicated SQLite backend-close fence. It reports only the bounded
// write/read/flush/close result and never exposes a cookie value, database
// path, or backend diagnostic.
bool StartWasmProfileCookieSmoke(
    WasmProfile* profile,
    WasmProfilePreferencesCookieSmokeInput input,
    base::OnceCallback<void(bool success)> completion);

// True only after the enabled test-only CookieManager probe completed its
// local validation, FlushCookieStore callback, and the test-only exact
// SQLitePersistentCookieStore backend-close callback.
bool DidWasmProfileCookieSmokeSucceed();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_PROFILE_COOKIE_SMOKE_H_
