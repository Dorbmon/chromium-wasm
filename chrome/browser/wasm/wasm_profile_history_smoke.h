// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_HISTORY_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_HISTORY_SMOKE_H_

#include <memory>

#include "base/files/file_path.h"
#include "base/functional/callback_forward.h"
#include "base/sequence_checker.h"
#include "chrome/browser/wasm/wasm_profile_ordered_drain_lifecycle.h"

namespace chrome {

// Owns the source-selected direct HistoryService witness for one WasmProfile.
// The caller transfers an admitted profile-I/O hold before Start(). A true
// completion is reported only after HistoryBackend has closed both History and
// Favicons and that hold has reached its terminal success result. Cancellation
// requests the same backend close and can only report failure. If the UI loop
// cannot wait for that receipt, owner loss quarantines the still-live holder so
// the outer profile drain refuses before touching the V4 backend.
//
// This deliberately does not use HistoryServiceFactory or become a keyed
// service. The test-only core HistoryService remains outside the unsupported
// desktop history/bookmark graph while its lifetime is explicitly owned by the
// selected WasmProfile.
class WasmProfileHistoryLifetimeParticipant {
 public:
  WasmProfileHistoryLifetimeParticipant(
      base::FilePath profile_path,
      WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold);
  WasmProfileHistoryLifetimeParticipant(
      const WasmProfileHistoryLifetimeParticipant&) = delete;
  WasmProfileHistoryLifetimeParticipant& operator=(
      const WasmProfileHistoryLifetimeParticipant&) = delete;
  ~WasmProfileHistoryLifetimeParticipant();

  // Starts the bounded read/write witness. |completion| runs on the UI
  // sequence after the profile-I/O admission has a terminal result. Returning
  // false before the first start fails the transferred admission. A duplicate
  // start is rejected without disturbing the existing asynchronous operation.
  bool Start(base::OnceCallback<void(bool success)> completion);

  // Requests a failed backend-close path. While a HistoryService exists, the
  // profile-I/O admission remains pending until its backend-destroy receipt;
  // cancellation cannot turn that still-live operation into a clean result.
  void Cancel();

  // Moves an active failed close into a process-lifetime quarantine when the
  // UI loop has already stopped and cannot await HistoryBackend destruction.
  // The retained admission makes the outer V4 drain refuse before any backend
  // transaction until that receipt; it can never authorize a clean handoff.
  bool QuarantineForFailureShutdown();

  bool IsActive() const;
  bool HasCompleted() const;
  bool DidSucceed() const;

 private:
  class State;

  SEQUENCE_CHECKER(sequence_checker_);
  std::unique_ptr<State> state_;
};

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_PROFILE_HISTORY_SMOKE_H_
