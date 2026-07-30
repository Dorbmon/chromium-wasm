// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "partition_alloc/partition_alloc_base/time/time.h"

#include <cmath>

#include <emscripten/emscripten.h>
#include <emscripten/html5.h>

#include "partition_alloc/build_config.h"
#include "partition_alloc/partition_alloc_base/check.h"
#include "partition_alloc/partition_alloc_base/time/time_override.h"

#if !PA_BUILDFLAG(IS_WASM)
#error "time_wasm.cc must only be built for WebAssembly"
#endif

namespace partition_alloc::internal::base {
namespace {

double WallClockMilliseconds() {
  const double now = emscripten_date_now();
  PA_BASE_CHECK(std::isfinite(now));
  return now;
}

double MonotonicClockMilliseconds() {
  const double now = emscripten_get_now();
  PA_BASE_CHECK(std::isfinite(now));
  return now;
}

}  // namespace

namespace subtle {

Time TimeNowIgnoringOverride() {
  return Time::FromMillisecondsSinceUnixEpoch(WallClockMilliseconds());
}

Time TimeNowFromSystemTimeIgnoringOverride() {
  return TimeNowIgnoringOverride();
}

TimeTicks TimeTicksNowIgnoringOverride() {
  return TimeTicks() + Milliseconds(MonotonicClockMilliseconds());
}

ThreadTicks ThreadTicksNowIgnoringOverride() {
  // Emscripten exposes no per-thread CPU clock. ThreadTicks::IsSupported()
  // reports false for Wasm; a null value is the unsupported state.
  return ThreadTicks();
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
  // All services share one Emscripten process and its worker clock domain.
  return true;
}

}  // namespace partition_alloc::internal::base
