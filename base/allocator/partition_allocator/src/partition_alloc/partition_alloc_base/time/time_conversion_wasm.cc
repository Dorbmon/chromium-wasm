// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "partition_alloc/partition_alloc_base/time/time.h"

#include <sys/time.h>

#include <cstdint>
#include <ctime>
#include <limits>

#include "partition_alloc/build_config.h"
#include "partition_alloc/partition_alloc_base/check.h"

#if !PA_BUILDFLAG(IS_WASM)
#error "time_conversion_wasm.cc must only be built for WebAssembly"
#endif

namespace partition_alloc::internal::base {

// static
TimeDelta TimeDelta::FromTimeSpec(const timespec& ts) {
  return TimeDelta(ts.tv_sec * Time::kMicrosecondsPerSecond +
                   ts.tv_nsec / Time::kNanosecondsPerMicrosecond);
}

struct timespec TimeDelta::ToTimeSpec() const {
  int64_t microseconds = InMicroseconds();
  time_t seconds = 0;
  if (microseconds >= Time::kMicrosecondsPerSecond) {
    seconds = InSeconds();
    microseconds -= seconds * Time::kMicrosecondsPerSecond;
  }
  return {
      seconds,
      static_cast<long>(microseconds * Time::kNanosecondsPerMicrosecond)};
}

// static
Time Time::FromTimeVal(struct timeval value) {
  PA_BASE_DCHECK(value.tv_usec <
                 static_cast<int>(Time::kMicrosecondsPerSecond));
  PA_BASE_DCHECK(value.tv_usec >= 0);
  if (value.tv_usec == 0 && value.tv_sec == 0) {
    return Time();
  }
  if (value.tv_usec ==
          static_cast<suseconds_t>(Time::kMicrosecondsPerSecond) - 1 &&
      value.tv_sec == std::numeric_limits<time_t>::max()) {
    return Max();
  }
  return Time(
      (static_cast<int64_t>(value.tv_sec) * Time::kMicrosecondsPerSecond) +
      value.tv_usec + kTimeTToMicrosecondsOffset);
}

struct timeval Time::ToTimeVal() const {
  if (is_null()) {
    return {0, 0};
  }
  if (is_max()) {
    return {std::numeric_limits<time_t>::max(),
            static_cast<suseconds_t>(Time::kMicrosecondsPerSecond) - 1};
  }
  int64_t microseconds = us_ - kTimeTToMicrosecondsOffset;
  return {static_cast<time_t>(microseconds / Time::kMicrosecondsPerSecond),
          static_cast<suseconds_t>(microseconds %
                                   Time::kMicrosecondsPerSecond)};
}

}  // namespace partition_alloc::internal::base
