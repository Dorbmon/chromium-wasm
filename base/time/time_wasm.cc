// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/time/time.h"

#include <cmath>

#include <emscripten/emscripten.h>
#include <emscripten/html5.h>

#include "base/check.h"
#include "base/time/time_override.h"

namespace base {

namespace {

double WallClockMilliseconds() {
  const double now = emscripten_date_now();
  CHECK(std::isfinite(now));
  return now;
}

double MonotonicClockMilliseconds() {
  const double now = emscripten_get_now();
  CHECK(std::isfinite(now));
  return now;
}

}  // namespace

// Time -----------------------------------------------------------------------

namespace subtle {

Time TimeNowIgnoringOverride() {
  return Time::FromMillisecondsSinceUnixEpoch(WallClockMilliseconds());
}

Time TimeNowFromSystemTimeIgnoringOverride() {
  return TimeNowIgnoringOverride();
}

}  // namespace subtle

// TimeTicks ------------------------------------------------------------------

namespace subtle {

TimeTicks TimeTicksNowIgnoringOverride() {
  return TimeTicks() + Milliseconds(MonotonicClockMilliseconds());
}

TimeTicks TimeTicksLowResolutionNowIgnoringOverride() {
  return TimeTicksNowIgnoringOverride();
}

}  // namespace subtle

// static
TimeTicks::Clock TimeTicks::GetClock() {
  return Clock::WASM_EMSCRIPTEN_GET_NOW;
}

// static
bool TimeTicks::IsHighResolution() {
  return true;
}

// static
bool TimeTicks::IsConsistentAcrossProcesses() {
  // All Chromium services share one Emscripten process, and the pthread
  // runtime synchronizes this clock across its workers.
  return true;
}

// ThreadTicks ----------------------------------------------------------------

namespace subtle {

ThreadTicks ThreadTicksNowIgnoringOverride() {
  // Emscripten does not expose per-thread CPU time. `ThreadTicks::IsSupported`
  // reports false for Wasm, and a null value is the API's unsupported state.
  return ThreadTicks();
}

}  // namespace subtle

}  // namespace base
