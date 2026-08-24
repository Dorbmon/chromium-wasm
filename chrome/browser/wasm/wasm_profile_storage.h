// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_STORAGE_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_STORAGE_H_

#include "chrome/browser/wasm/wasm_profile_storage_drain_result.h"

namespace chrome {

// Mounts the database acceptance probe's profile root on the leased OPFS
// WasmFS backend. This must run on Chromium's application pthread before
// ContentMain can register or resolve DIR_USER_DATA.
bool InitializeWasmProfileStorage();

#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST)
// Mounts the Preferences acceptance probe's leased OPFS backend only at
// /profile/Default. Its /profile parent remains on WasmFS's default memory
// backend, which the initializer validates before and after the child mount.
// This is available only in the dedicated Preferences test artifact.
bool InitializeWasmProfilePreferencesStorage();
#endif

// Returns true only while the exact leased OPFS mount remains available.
bool IsWasmProfileStorageMounted();

// Returns true when ChromeMain must drain the exact leased backend after its
// ContentMain delegate scope is gone. This is also true after a failed mount
// if backend construction acquired the lease: cleanup must not race startup
// object destruction.
bool NeedsWasmProfileStorageBackendDrain();

// Marks the lifetime of Chrome's profile services. Browser main parts calls
// these around WasmProfile construction and shutdown; a live profile's lease
// cannot be released before its shutdown completes.
bool NotifyWasmProfileStorageProfileCreated();
bool NotifyWasmProfileStorageProfileShutdown();

// Attempts to permanently seal only Chrome's leased OPFS backend, release its
// profile lease, and retire its dedicated worker. ChromeMain calls this only
// after ContentMain returns, because the profile backend must be quiesced after
// all Content teardown. Unrelated WasmFS operations and the normal Emscripten
// exit tail remain usable.
WasmProfileStorageDrainResult DrainAndReleaseWasmProfileStorageBackend();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_PROFILE_STORAGE_H_
