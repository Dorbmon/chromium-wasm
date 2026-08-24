// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_SHUTDOWN_FAILURE_LATCH_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_SHUTDOWN_FAILURE_LATCH_H_

namespace chrome {

// Keeps a normal volatile WasmProfile shutdown failure observable after
// ContentMain has destroyed browser-main parts. It is a process-result latch,
// not a profile health, storage, or persistence result.
//
// ChromeMain resets it before each normal ContentMain invocation. Once
// recorded, failure remains sticky until that next reset so an orderly-looking
// ContentMain return cannot hide a failed Preferences shutdown fence.
void ResetWasmProfileShutdownFailureLatch();
void RecordWasmProfileShutdownFailure();
bool WasmProfileShutdownFailureWasRecorded();

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_PROFILE_SHUTDOWN_FAILURE_LATCH_H_
