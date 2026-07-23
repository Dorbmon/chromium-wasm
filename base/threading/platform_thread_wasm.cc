// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/threading/platform_thread.h"

#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <time.h>

#include <algorithm>
#include <memory>
#include <optional>
#include <string>
#include <tuple>

#include <emscripten/threading.h>

#include "base/check.h"
#include "base/time/time.h"

namespace base {
namespace {

struct ThreadParams {
  PlatformThread::Delegate* delegate;
  ThreadType thread_type;
};

thread_local std::string g_thread_name;

internal::ThreadTypeManager* GetThreadTypeManager() {
  constinit thread_local internal::ThreadTypeManager thread_type_manager;
  return &thread_type_manager;
}

void* ThreadFunc(void* params) {
  std::unique_ptr<ThreadParams> thread_params(
      static_cast<ThreadParams*>(params));
  PlatformThread::SetCurrentThreadType(thread_params->thread_type);
  thread_params->delegate->ThreadMain();
  return nullptr;
}

bool CreateThread(size_t stack_size,
                  bool joinable,
                  PlatformThread::Delegate* delegate,
                  PlatformThreadHandle* thread_handle,
                  ThreadType thread_type) {
  CHECK(delegate);
  CHECK(thread_handle);

  pthread_attr_t attributes;
  int rv = pthread_attr_init(&attributes);
  if (rv != 0) {
    errno = rv;
    *thread_handle = PlatformThreadHandle();
    return false;
  }

  if (!joinable) {
    rv = pthread_attr_setdetachstate(&attributes, PTHREAD_CREATE_DETACHED);
  }
  if (rv == 0 && stack_size > 0) {
    rv = pthread_attr_setstacksize(&attributes, stack_size);
  }
  if (rv != 0) {
    errno = rv;
    CHECK(pthread_attr_destroy(&attributes) == 0);
    *thread_handle = PlatformThreadHandle();
    return false;
  }

  auto params =
      std::make_unique<ThreadParams>(ThreadParams{delegate, thread_type});
  pthread_t handle = 0;
  rv = pthread_create(&handle, &attributes, ThreadFunc, params.get());
  CHECK(pthread_attr_destroy(&attributes) == 0);
  if (rv != 0) {
    errno = rv;
    *thread_handle = PlatformThreadHandle();
    return false;
  }

  std::ignore = params.release();
  *thread_handle = PlatformThreadHandle(handle);
  return true;
}

}  // namespace

// static
PlatformThreadId PlatformThreadBase::CurrentId() {
  return PlatformThreadId(static_cast<uintptr_t>(pthread_self()));
}

// static
PlatformThreadRef PlatformThreadBase::CurrentRef() {
  return PlatformThreadRef(pthread_self());
}

// static
PlatformThreadHandle PlatformThreadBase::CurrentHandle() {
  return PlatformThreadHandle(pthread_self());
}

// static
void PlatformThreadBase::YieldCurrentThread() {
  CHECK(sched_yield() == 0);
}

// static
void PlatformThreadBase::Sleep(TimeDelta duration) {
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
    CHECK(errno == EINTR);
    sleep_time = remaining;
  }
}

// static
void PlatformThreadBase::SetName(const std::string& name) {
  SetNameCommon(name);
  // This is a diagnostic best effort. Emscripten only exposes the name to host
  // tooling when thread profiling is enabled.
  emscripten_set_thread_name(pthread_self(), name.c_str());
}

// static
const char* PlatformThreadBase::GetName() {
  return g_thread_name.c_str();
}

// static
bool PlatformThreadBase::CreateWithType(size_t stack_size,
                                        Delegate* delegate,
                                        PlatformThreadHandle* thread_handle,
                                        ThreadType thread_type,
                                        MessagePumpType) {
  return CreateThread(stack_size, true, delegate, thread_handle, thread_type);
}

// static
bool PlatformThreadBase::CreateNonJoinable(size_t stack_size,
                                           Delegate* delegate) {
  return CreateNonJoinableWithType(stack_size, delegate, ThreadType::kDefault);
}

// static
bool PlatformThreadBase::CreateNonJoinableWithType(
    size_t stack_size,
    Delegate* delegate,
    ThreadType thread_type,
    MessagePumpType) {
  PlatformThreadHandle unused;
  return CreateThread(stack_size, false, delegate, &unused, thread_type);
}

// static
void PlatformThreadBase::Join(PlatformThreadHandle thread_handle) {
  CHECK(!thread_handle.is_null());
  CHECK(pthread_join(thread_handle.platform_handle(), nullptr) == 0);
}

// static
void PlatformThreadBase::Detach(PlatformThreadHandle thread_handle) {
  CHECK(!thread_handle.is_null());
  CHECK(pthread_detach(thread_handle.platform_handle()) == 0);
}

// static
bool PlatformThreadBase::CanChangeThreadType(ThreadType from, ThreadType to) {
  // Web Workers expose no scheduling priority controls.
  return from == to;
}

// static
void PlatformThreadBase::SetCurrentThreadType(ThreadType thread_type) {
  GetThreadTypeManager()->SetDefault(thread_type);
}

// static
ThreadType PlatformThreadBase::GetCurrentThreadType() {
  return GetThreadTypeManager()->GetCurrent();
}

// static
TimeDelta PlatformThreadBase::GetRealtimePeriod(Delegate*) {
  return TimeDelta();
}

// static
std::optional<TimeDelta> PlatformThreadBase::GetThreadLeewayOverride() {
  return std::nullopt;
}

// static
size_t PlatformThreadBase::GetDefaultThreadStackSize() {
  // Preserve Emscripten's configured pthread stack size.
  return 0;
}

// static
ThreadType PlatformThreadBase::GetCurrentEffectiveThreadTypeForTest() {
  // Requested types are retained as Chromium scheduling metadata, but the host
  // cannot apply them to a Web Worker.
  return ThreadType::kDefault;
}

// static
bool PlatformThreadBase::CurrentThreadHasLeases() {
  return GetThreadTypeManager()->HasLeases();
}

// static
void PlatformThreadBase::SetNameCommon(const std::string& name) {
  g_thread_name = name;
}

PlatformThreadBase::RaiseThreadTypeLease::RaiseThreadTypeLease(
    ThreadType thread_type)
    : RaiseThreadTypeLease(thread_type, GetThreadTypeManager()) {}

PlatformThreadBase::RaiseThreadTypeLease::RaiseThreadTypeLease(
    ThreadType thread_type,
    internal::ThreadTypeManager* manager)
    : leased_thread_type_(thread_type), manager_(manager) {
  manager_->AcquireRaiseLease(thread_type);
}

PlatformThreadBase::RaiseThreadTypeLease::~RaiseThreadTypeLease() {
  manager_->DropRaiseLease(leased_thread_type_);
}

namespace internal {

void ThreadTypeManager::SetDefault(ThreadType type) {
  CHECK(type <= ThreadType::kMaxValue);
  default_thread_type_ = type;
  MaybeUpdate();
}

ThreadType ThreadTypeManager::GetCurrent() const {
  return effective_thread_type_.value_or(ThreadType::kDefault);
}

void ThreadTypeManager::MaybeUpdate() {
  const std::optional<ThreadType> highest_lease =
      raise_leases_.GetHighestLease();
  ThreadType type;
  if (!highest_lease.has_value() && !default_thread_type_.has_value()) {
    type = ThreadType::kDefault;
  } else {
    type = std::max(highest_lease.value_or(ThreadType::kBackground),
                    default_thread_type_.value_or(ThreadType::kBackground));
  }
  if (type == effective_thread_type_) {
    return;
  }
  effective_thread_type_ = type;
  SetCurrentThreadTypeImpl(type, MessagePumpType::DEFAULT);
}

void ThreadTypeManager::AcquireRaiseLease(ThreadType type) {
  CHECK(type <= ThreadType::kMaxValue);
  raise_leases_.Acquire(type);
  MaybeUpdate();
}

void ThreadTypeManager::DropRaiseLease(ThreadType type) {
  CHECK(type <= ThreadType::kMaxValue);
  raise_leases_.Drop(type);
  MaybeUpdate();
}

void ThreadTypeManager::RaiseLeases::Acquire(ThreadType thread_type) {
  const auto type = static_cast<uint32_t>(thread_type);
  ++leases[type];
  bitmask |= 1u << type;
}

void ThreadTypeManager::RaiseLeases::Drop(ThreadType thread_type) {
  const auto type = static_cast<uint32_t>(thread_type);
  CHECK(leases[type] > 0u);
  if (--leases[type] == 0) {
    bitmask &= ~(1u << type);
  }
}

std::optional<ThreadType> ThreadTypeManager::RaiseLeases::GetHighestLease()
    const {
  for (int type = static_cast<int>(ThreadType::kMaxValue); type >= 0; --type) {
    if (bitmask & (1u << type)) {
      return static_cast<ThreadType>(type);
    }
  }
  return std::nullopt;
}

void ThreadTypeManager::SetCurrentThreadTypeImpl(
    ThreadType thread_type,
    MessagePumpType pump_type_hint) {
  base::internal::SetCurrentThreadTypeImpl(thread_type, pump_type_hint);
}

bool ThreadTypeManager::HasLeases() const {
  return raise_leases_.GetHighestLease().has_value();
}

void SetCurrentThreadTypeImpl(ThreadType, MessagePumpType) {
  // The ThreadTypeManager retains the requested type as Chromium metadata.
  // Web Workers expose no host scheduling control to apply here.
}

PlatformPriorityOverride SetThreadTypeOverride(PlatformThreadHandle,
                                               ThreadType) {
  return false;
}

void RemoveThreadTypeOverride(
    PlatformThreadHandle,
    const PlatformPriorityOverride& priority_override_handle,
    ThreadType) {
  CHECK(!priority_override_handle);
}

}  // namespace internal
}  // namespace base
