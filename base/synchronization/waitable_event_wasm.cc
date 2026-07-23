// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/synchronization/waitable_event.h"

#include "base/check.h"
#include "base/functional/bind.h"
#include "base/time/time.h"

namespace base {

WaitableEvent::~WaitableEvent() = default;

void WaitableEvent::Signal() {
  SignalImpl();
}

void WaitableEvent::Wait(const Location& location) {
  CHECK(TimedWait(TimeDelta::Max(), location));
}

bool WaitableEvent::TimedWait(TimeDelta wait_delta, const Location&) {
  if (wait_delta <= TimeDelta()) {
    return IsSignaled();
  }
  return TimedWaitImpl(wait_delta);
}

// static
size_t WaitableEvent::WaitMany(base::span<WaitableEvent*> events) {
  CHECK(!events.empty());
  for (size_t i = 0; i < events.size(); ++i) {
    if (events[i]->IsSignaled()) {
      return i;
    }
  }
  return WaitManyImpl(events);
}

OnceClosure WaitableEvent::GetWaitCallbackForTesting() {
  return BindOnce(&WaitableEvent::Wait, Unretained(this), FROM_HERE);
}

}  // namespace base
