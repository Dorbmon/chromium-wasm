// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_BOOKMARK_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_BOOKMARK_SMOKE_H_

#include <memory>

#include "base/files/file_path.h"
#include "base/functional/callback_forward.h"
#include "base/sequence_checker.h"
#include "chrome/browser/wasm/wasm_profile_ordered_drain_lifecycle.h"
#include "chrome/browser/wasm/wasm_profile_preferences_smoke.h"

namespace chrome {

// Owns one source-selected direct BookmarkModel for a WasmProfile. The caller
// transfers an admitted profile-I/O hold before Start(). A successful
// completion is reported only after the clear-text local write has returned
// its ImportantFileWriter result and the direct model/storage owner has been
// destroyed. Delivery is deferred one UI turn, and the participant keeps its
// admission active through that notification boundary. Cancellation keeps
// both the model and admission live until any already-started load or write
// reaches that terminal point.
//
// This deliberately does not use BookmarkModelFactory or become a keyed
// service. If the UI loop can no longer wait for asynchronous work, the active
// state is quarantined for process lifetime so the outer V4 drain refuses
// rather than racing the Bookmarks file.
class WasmProfileBookmarkLifetimeParticipant {
 public:
  WasmProfileBookmarkLifetimeParticipant(
      base::FilePath profile_path,
      WasmProfilePreferencesBookmarkSmokeInput input,
      WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold);
  WasmProfileBookmarkLifetimeParticipant(
      const WasmProfileBookmarkLifetimeParticipant&) = delete;
  WasmProfileBookmarkLifetimeParticipant& operator=(
      const WasmProfileBookmarkLifetimeParticipant&) = delete;
  ~WasmProfileBookmarkLifetimeParticipant();

  bool Start(base::OnceCallback<void(bool success)> completion);
  void Cancel();
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

#endif  // CHROME_BROWSER_WASM_WASM_PROFILE_BOOKMARK_SMOKE_H_
