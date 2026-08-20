// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_STORAGE_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_STORAGE_H_

#include <cstdint>

namespace chrome {

// The observable result of draining just Chrome's leased OPFS backend. A
// successful result means WasmFS sealed that exact backend, flushed and closed
// its detached data files, and synchronously released its OPFS profile lock.
// It does not stop unrelated WasmFS mounts or stdio.
// |detached_descriptors| and |data_file_states| describe work performed, not
// failures; every other counter must be zero for Succeeded().
struct WasmProfileStorageDrainResult {
  int error = 0;
  uint32_t detached_descriptors = 0;
  uint32_t data_file_states = 0;
  uint32_t libc_flush_failed = 0;
  uint32_t data_flush_failures = 0;
  uint32_t data_close_failures = 0;
  uint32_t prior_close_failures = 0;
  uint32_t lease_release_failures = 0;
  bool backend_sealed = false;
  bool lease_released = false;

  bool Succeeded() const;
};

// Mounts the one supported Chrome profile root on the leased OPFS WasmFS
// backend. This must run on Chromium's application pthread before ContentMain
// can register or resolve DIR_USER_DATA.
bool InitializeWasmProfileStorage();

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

// Permanently seals only Chrome's leased OPFS backend and releases its profile
// lease. ChromeMain calls this only after ContentMain returns, because the
// profile backend must be quiesced after all Content teardown. Unrelated
// WasmFS operations and the normal Emscripten exit tail remain usable.
WasmProfileStorageDrainResult DrainAndReleaseWasmProfileStorageBackend();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_PROFILE_STORAGE_H_
