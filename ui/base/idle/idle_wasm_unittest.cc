// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "ui/base/idle/idle.h"

#include "base/functional/bind.h"
#include "testing/gtest/include/gtest/gtest.h"

namespace ui {

TEST(IdleWasmTest, ReportsConservativeUnsupportedState) {
  EXPECT_EQ(0, CalculateIdleTime());
  EXPECT_FALSE(CheckIdleStateIsLocked());
  EXPECT_EQ(IDLE_STATE_ACTIVE, CalculateIdleState(/*idle_threshold=*/1));
}

TEST(IdleWasmTest, DoesNotFabricateScreenLockNotifications) {
  bool callback_called = false;
  auto subscription = AddScreenLockCallback(
      base::BindRepeating([](bool* callback_called, bool locked) {
        *callback_called = true;
      }, &callback_called));

  EXPECT_FALSE(subscription);
  EXPECT_FALSE(callback_called);
}

}  // namespace ui
