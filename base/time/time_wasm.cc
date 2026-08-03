// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/time/time.h"

#include <atomic>
#include <cmath>

#include <emscripten/emscripten.h>
#include <emscripten/html5.h>

#include "base/check.h"
#include "base/time/time_override.h"

namespace base {

namespace {

// `performance.timeOrigin + performance.now()` is comparable between workers,
// but worker clocks can still differ by a few microseconds due to their
// independently rounded browser readings. Chromium tasks retain a queue time
// on the posting sequence and compare it with their start time on the target
// sequence, so preserve the TimeTicks contract across the shared Wasm memory.
std::atomic<int64_t> g_last_monotonic_microseconds{0};

TimeTicks MakeGloballyMonotonicTimeTicks(TimeTicks candidate) {
  const int64_t candidate_microseconds =
      (candidate - TimeTicks()).InMicroseconds();
  int64_t observed =
      g_last_monotonic_microseconds.load(std::memory_order_relaxed);
  while (candidate_microseconds > observed) {
    if (g_last_monotonic_microseconds.compare_exchange_weak(
            observed, candidate_microseconds, std::memory_order_relaxed,
            std::memory_order_relaxed)) {
      return candidate;
    }
  }
  return TimeTicks() + Microseconds(observed);
}

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
  return MakeGloballyMonotonicTimeTicks(
      TimeTicks() + Milliseconds(MonotonicClockMilliseconds()));
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
  // All Chromium services share one Emscripten process. Emscripten aligns the
  // workers' clock origins, and the shared high-water mark in
  // TimeTicksNowIgnoringOverride() closes the remaining rounding gap.
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
