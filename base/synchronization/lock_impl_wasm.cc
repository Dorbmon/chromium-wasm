// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/synchronization/lock_impl.h"

#include <pthread.h>

#include "base/check.h"

namespace base::internal {

LockImpl::LockImpl() {
  pthread_mutexattr_t attributes;
  CHECK(pthread_mutexattr_init(&attributes) == 0);
#ifndef NDEBUG
  CHECK(pthread_mutexattr_settype(&attributes, PTHREAD_MUTEX_ERRORCHECK) == 0);
#endif
  CHECK(pthread_mutex_init(&native_handle_, &attributes) == 0);
  CHECK(pthread_mutexattr_destroy(&attributes) == 0);
}

LockImpl::~LockImpl() {
  CHECK(pthread_mutex_destroy(&native_handle_) == 0);
}

void LockImpl::LockInternal() {
  CHECK(pthread_mutex_lock(&native_handle_) == 0);
}

// static
bool LockImpl::PriorityInheritanceAvailable() {
  // Web Workers expose no scheduling priority controls.
  return false;
}

}  // namespace base::internal

namespace base {

bool KernelSupportsPriorityInheritanceFutex() {
  return false;
}

}  // namespace base
