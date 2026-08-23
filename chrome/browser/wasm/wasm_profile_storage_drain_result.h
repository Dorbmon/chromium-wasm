// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_STORAGE_DRAIN_RESULT_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_STORAGE_DRAIN_RESULT_H_

#include <cstdint>

namespace chrome {

// The observable result of draining just Chrome's leased OPFS backend. A
// successful result means WasmFS sealed that exact backend, flushed and closed
// its detached data files, synchronously released its OPFS profile lock, and
// safely retired its dedicated OPFS worker before the normal Emscripten exit
// tail. It does not stop unrelated WasmFS mounts or stdio.
// |detached_descriptors| and |data_file_states| describe work performed, not
// failures; every other counter must be zero for Succeeded(). A failure before
// acknowledged lease release has no safe handoff. A post-release worker
// retirement failure may already have released the lease, but remains sealed
// and terminal.
struct WasmProfileStorageDrainResult {
  int error = 0;
  uint32_t detached_descriptors = 0;
  uint32_t data_file_states = 0;
  uint32_t libc_flush_failed = 0;
  uint32_t data_flush_failures = 0;
  uint32_t data_close_failures = 0;
  uint32_t prior_close_failures = 0;
  uint32_t lease_release_failures = 0;
  uint32_t backend_retire_failures = 0;
  bool backend_sealed = false;
  bool lease_released = false;
  bool backend_retired = false;

  bool Succeeded() const {
    return error == 0 && libc_flush_failed == 0 && data_flush_failures == 0 &&
           data_close_failures == 0 && prior_close_failures == 0 &&
           lease_release_failures == 0 && backend_retire_failures == 0 &&
           backend_sealed && lease_released && backend_retired;
  }
};

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_PROFILE_STORAGE_DRAIN_RESULT_H_
