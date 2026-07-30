// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "ui/base/idle/idle.h"

#include "base/notimplemented.h"

namespace ui {

base::CallbackListSubscription AddScreenLockCallback(
    base::RepeatingCallback<void(bool)> callback) {
  // M3 has no host visibility or screen-lock bridge.
  NOTIMPLEMENTED_LOG_ONCE();
  return {};
}

int CalculateIdleTime() {
  // Conservatively treat the user as active until host input is available.
  NOTIMPLEMENTED_LOG_ONCE();
  return 0;
}

bool CheckIdleStateIsLocked() {
  // Do not claim a lock state that the Wasm application cannot observe.
  NOTIMPLEMENTED_LOG_ONCE();
  return false;
}

}  // namespace ui
