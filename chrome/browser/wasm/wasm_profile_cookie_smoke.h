// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_COOKIE_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_COOKIE_SMOKE_H_

#include <memory>

#include "base/functional/callback_forward.h"
#include "base/sequence_checker.h"
#include "chrome/browser/wasm/wasm_profile_ordered_drain_lifecycle.h"
#include "chrome/browser/wasm/wasm_profile_preferences_smoke.h"
#include "mojo/public/cpp/bindings/pending_remote.h"
#include "services/network/public/mojom/cookie_manager.mojom-forward.h"

namespace chrome {

// Owns one source-selected CookieManager connection for a WasmProfile. The
// caller transfers an admitted profile-I/O hold before Start(). A successful
// completion is reported only after the bounded cookie probe, FlushCookieStore,
// and SQLite backend-close receipt have all completed. Cancellation stops the
// probe at its next CookieManager reply and closes the backend before failing
// the admission.
//
// The cloned Mojo connection deliberately does not keep NetworkContext alive.
// If profile teardown disconnects it before the close receipt, an active State
// is retained for process lifetime together with its still-outstanding hold.
// The outer V4 drain therefore refuses instead of racing an unobserved SQLite
// close. This is a test-only lifetime witness, not a production cookie-store
// shutdown API.
class WasmProfileCookieLifetimeParticipant {
 public:
  WasmProfileCookieLifetimeParticipant(
      mojo::PendingRemote<network::mojom::CookieManager> cookie_manager,
      WasmProfilePreferencesCookieSmokeInput input,
      WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold);
  WasmProfileCookieLifetimeParticipant(
      const WasmProfileCookieLifetimeParticipant&) = delete;
  WasmProfileCookieLifetimeParticipant& operator=(
      const WasmProfileCookieLifetimeParticipant&) = delete;
  ~WasmProfileCookieLifetimeParticipant();

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

#endif  // CHROME_BROWSER_WASM_WASM_PROFILE_COOKIE_SMOKE_H_
