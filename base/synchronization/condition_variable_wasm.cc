// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/synchronization/condition_variable.h"

#include <errno.h>
#include <time.h>

#include "base/check.h"
#include "base/time/time.h"

namespace base {

ConditionVariable::ConditionVariable(Lock* user_lock)
    : user_mutex_(user_lock->lock_.native_handle())
#if DCHECK_IS_ON()
      ,
      user_lock_(user_lock)
#endif
{
  pthread_condattr_t attributes;
  CHECK(pthread_condattr_init(&attributes) == 0);
  CHECK(pthread_condattr_setclock(&attributes, CLOCK_MONOTONIC) == 0);
  CHECK(pthread_cond_init(&condition_, &attributes) == 0);
  CHECK(pthread_condattr_destroy(&attributes) == 0);
}

ConditionVariable::~ConditionVariable() {
  CHECK(pthread_cond_destroy(&condition_) == 0);
}

void ConditionVariable::Wait(const Location&) {
#if DCHECK_IS_ON()
  user_lock_->CheckHeldAndUnmark();
#endif
  CHECK(pthread_cond_wait(&condition_, user_mutex_) == 0);
#if DCHECK_IS_ON()
  user_lock_->CheckUnheldAndMark();
#endif
}

void ConditionVariable::TimedWait(const TimeDelta& max_time, const Location&) {
  struct timespec deadline;
  CHECK(clock_gettime(CLOCK_MONOTONIC, &deadline) == 0);

  const int64_t nanoseconds = max_time.InNanoseconds();
  deadline.tv_sec +=
      static_cast<time_t>(nanoseconds / Time::kNanosecondsPerSecond);
  deadline.tv_nsec +=
      static_cast<long>(nanoseconds % Time::kNanosecondsPerSecond);
  if (deadline.tv_nsec >= Time::kNanosecondsPerSecond) {
    ++deadline.tv_sec;
    deadline.tv_nsec -= Time::kNanosecondsPerSecond;
  } else if (deadline.tv_nsec < 0) {
    --deadline.tv_sec;
    deadline.tv_nsec += Time::kNanosecondsPerSecond;
  }

#if DCHECK_IS_ON()
  user_lock_->CheckHeldAndUnmark();
#endif
  const int rv =
      pthread_cond_timedwait(&condition_, user_mutex_, &deadline);
  CHECK(rv == 0 || rv == ETIMEDOUT);
#if DCHECK_IS_ON()
  user_lock_->CheckUnheldAndMark();
#endif
}

void ConditionVariable::Broadcast() {
  CHECK(pthread_cond_broadcast(&condition_) == 0);
}

void ConditionVariable::Signal() {
  CHECK(pthread_cond_signal(&condition_) == 0);
}

}  // namespace base
