// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "partition_alloc/partition_alloc_base/threading/platform_thread.h"

#include <errno.h>
#include <pthread.h>
#include <time.h>

#include <cstdint>

#include "partition_alloc/build_config.h"
#include "partition_alloc/partition_alloc_base/check.h"

#if !PA_BUILDFLAG(IS_WASM)
#error "platform_thread_wasm.cc must only be built for WebAssembly"
#endif

namespace partition_alloc::internal::base {

// static
PlatformThreadId PlatformThread::CurrentId() {
  return static_cast<PlatformThreadId>(pthread_self());
}

// static
PlatformThreadRef PlatformThread::CurrentRef() {
  return PlatformThreadRef(pthread_self());
}

// static
PlatformThreadHandle PlatformThread::CurrentHandle() {
  return PlatformThreadHandle(pthread_self());
}

// static
void PlatformThread::Sleep(TimeDelta duration) {
  if (!duration.is_positive()) {
    return;
  }

  struct timespec sleep_time;
  sleep_time.tv_sec = static_cast<time_t>(duration.InSeconds());
  duration -= Seconds(sleep_time.tv_sec);
  sleep_time.tv_nsec =
      static_cast<long>(duration.InNanoseconds() % Time::kNanosecondsPerSecond);

  struct timespec remaining;
  while (nanosleep(&sleep_time, &remaining) == -1) {
    PA_BASE_CHECK(errno == EINTR);
    sleep_time = remaining;
  }
}

}  // namespace partition_alloc::internal::base
