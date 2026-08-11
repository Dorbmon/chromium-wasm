// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_HOST_STORAGE_ESTIMATE_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_HOST_STORAGE_ESTIMATE_H_

#include <stdint.h>

#include "base/memory/ref_counted.h"

namespace chrome {

// An immutable result of the outer host page's navigator.storage.estimate()
// call. This is intentionally an aggregate estimate for the outer origin. It
// is not Chromium Wasm profile usage, an OPFS reservation, a persistence
// grant, or an enforcement quota.
class WasmBrowserHostStorageEstimateSnapshot
    : public base::RefCountedThreadSafe<WasmBrowserHostStorageEstimateSnapshot> {
 public:
  enum class State {
    kPending,
    kAvailable,
    kUnavailable,
    kError,
  };

  WasmBrowserHostStorageEstimateSnapshot(uint32_t generation,
                                        State state,
                                        uint64_t usage_bytes,
                                        uint64_t quota_bytes);

  WasmBrowserHostStorageEstimateSnapshot(
      const WasmBrowserHostStorageEstimateSnapshot&) = delete;
  WasmBrowserHostStorageEstimateSnapshot& operator=(
      const WasmBrowserHostStorageEstimateSnapshot&) = delete;

  uint32_t generation() const { return generation_; }
  State state() const { return state_; }
  uint64_t usage_bytes() const { return usage_bytes_; }
  uint64_t quota_bytes() const { return quota_bytes_; }

 private:
  friend class base::RefCountedThreadSafe<
      WasmBrowserHostStorageEstimateSnapshot>;
  ~WasmBrowserHostStorageEstimateSnapshot();

  const uint32_t generation_;
  const State state_;
  const uint64_t usage_bytes_;
  const uint64_t quota_bytes_;
};

// Starts one asynchronous, read-only host-origin capacity diagnostic while
// the Chrome UI thread is live. A missing host API is published as
// unavailable; a rejected or malformed result is published as error. Neither
// outcome makes Chromium startup fail.
bool InitializeWasmBrowserHostStorageEstimate();

// Invalidates the active host request before browser teardown. A late Promise
// completion is rejected by its generation and cannot update a later state.
void ShutdownWasmBrowserHostStorageEstimate();

// Returns an immutable snapshot for a native WebUI document. Callers must
// retain this snapshot rather than querying the live host state while serving
// URLDataSource I/O.
scoped_refptr<const WasmBrowserHostStorageEstimateSnapshot>
GetWasmBrowserHostStorageEstimateSnapshot();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_HOST_STORAGE_ESTIMATE_H_
