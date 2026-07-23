// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <emscripten/threading.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

#include "base/containers/span.h"
#include "base/rand_util.h"
#include "base/synchronization/condition_variable.h"
#include "base/synchronization/lock.h"
#include "base/synchronization/waitable_event.h"
#include "base/threading/platform_thread.h"
#include "base/threading/thread_local_storage.h"
#include "base/time/time.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "m1_base_smoke must be built for WebAssembly"
#endif

#if BUILDFLAG(IS_POSIX)
#error "WebAssembly must not inherit POSIX platform semantics"
#endif

namespace {

constexpr char kPrefix[] = "CHROMIUM_WASM_M1_BASE";
constexpr base::TimeDelta kPhaseTimeout = base::Seconds(3);
constexpr base::TimeDelta kPollInterval = base::Milliseconds(2);
constexpr int kCounterIterations = 2000;

int Fail(const char* reason) {
  std::fprintf(stderr, "%s:FAIL reason=%s\n", kPrefix, reason);
  std::fflush(stderr);
  return 1;
}

[[noreturn]] void FailImmediately(const char* reason) {
  Fail(reason);
  std::abort();
}

void Require(bool condition, const char* reason) {
  if (!condition) {
    FailImmediately(reason);
  }
}

void BeginPhase(const char* phase) {
  std::fprintf(stdout, "%s:PHASE name=%s\n", kPrefix, phase);
  std::fflush(stdout);
}

template <typename Predicate>
bool WaitUntil(Predicate predicate, base::TimeDelta timeout = kPhaseTimeout) {
  const base::TimeTicks deadline = base::TimeTicks::Now() + timeout;
  while (!predicate()) {
    const base::TimeDelta remaining = deadline - base::TimeTicks::Now();
    if (!remaining.is_positive()) {
      return predicate();
    }
    base::PlatformThread::YieldCurrentThread();
    base::PlatformThread::Sleep(std::min(remaining, kPollInterval));
  }
  return true;
}

bool HasNonZeroByte(base::span<const uint8_t> bytes) {
  return std::ranges::any_of(bytes, [](uint8_t byte) { return byte != 0; });
}

struct TlsPayload {
  std::atomic<int>* destructor_count;
  int marker;
};

void DestroyTlsPayload(void* value) {
  auto* payload = static_cast<TlsPayload*>(value);
  payload->destructor_count->fetch_add(1, std::memory_order_release);
}

class PlatformBasicsDelegate final
    : public base::PlatformThread::Delegate {
 public:
  PlatformBasicsDelegate(int index,
                         base::PlatformThreadId application_id,
                         base::ThreadLocalStorage::Slot* tls_slot,
                         base::WaitableEvent* release_event,
                         std::atomic<int>* started,
                         std::atomic<int>* handoff_bits,
                         std::atomic<int>* tls_destructor_count)
      : index_(index),
        application_id_(application_id),
        tls_slot_(tls_slot),
        release_event_(release_event),
        started_(started),
        handoff_bits_(handoff_bits),
        name_("m1-worker-" + std::to_string(index)),
        tls_payload_{tls_destructor_count, 0x5100 + index} {}

  void ThreadMain() override {
    bool ok = !emscripten_is_main_browser_thread() &&
              !emscripten_is_main_runtime_thread();

    id_ = base::PlatformThread::CurrentId();
    ok = ok && id_ != base::kInvalidThreadId && id_ != application_id_;

    base::PlatformThread::SetName(name_);
    const char* current_name = base::PlatformThread::GetName();
    ok = ok && current_name && std::strcmp(current_name, name_.c_str()) == 0;

    ok = ok && tls_slot_->Get() == nullptr;
    tls_slot_->Set(&tls_payload_);
    ok = ok && tls_slot_->Get() == &tls_payload_;

    std::array<uint8_t, 257> entropy{};
    base::RandBytes(entropy);
    entropy_ok_.store(HasNonZeroByte(entropy), std::memory_order_release);
    ok = ok && entropy_ok_.load(std::memory_order_acquire);

    const base::TimeTicks sleep_start = base::TimeTicks::Now();
    base::PlatformThread::YieldCurrentThread();
    base::PlatformThread::Sleep(base::Milliseconds(10));
    const base::TimeDelta elapsed = base::TimeTicks::Now() - sleep_start;
    ok = ok && elapsed >= base::Milliseconds(5) &&
         elapsed < base::Seconds(2);
    ok = ok && base::PlatformThread::CurrentId() == id_;
    ok = ok && tls_slot_->Get() == &tls_payload_;

    handoff_bits_->fetch_or(1 << index_, std::memory_order_release);
    started_->fetch_add(1, std::memory_order_release);

    ok = release_event_->TimedWait(kPhaseTimeout) && ok;
    ok = ok && tls_slot_->Get() == &tls_payload_;
    succeeded_.store(ok, std::memory_order_release);
    // Leave the value installed so pthread teardown exercises the Chromium TLS
    // destructor path before PlatformThread::Join() returns.
  }

  base::PlatformThreadId id() const { return id_; }

  bool succeeded() const {
    return succeeded_.load(std::memory_order_acquire);
  }

  bool entropy_ok() const {
    return entropy_ok_.load(std::memory_order_acquire);
  }

 private:
  const int index_;
  const base::PlatformThreadId application_id_;
  base::ThreadLocalStorage::Slot* const tls_slot_;
  base::WaitableEvent* const release_event_;
  std::atomic<int>* const started_;
  std::atomic<int>* const handoff_bits_;
  const std::string name_;
  TlsPayload tls_payload_;
  base::PlatformThreadId id_;
  std::atomic<bool> entropy_ok_{false};
  std::atomic<bool> succeeded_{false};
};

void TestPlatformThreadAndTls() {
  BeginPhase("platform_thread_tls");

  const base::PlatformThreadId application_id =
      base::PlatformThread::CurrentId();
  Require(application_id != base::kInvalidThreadId,
          "application_thread_id_invalid");
  Require(base::PlatformThread::CurrentId() == application_id,
          "application_thread_id_unstable");

  base::PlatformThread::SetName("m1-application");
  const char* application_name = base::PlatformThread::GetName();
  Require(application_name &&
              std::strcmp(application_name, "m1-application") == 0,
          "application_thread_name");

  const base::TimeTicks sleep_start = base::TimeTicks::Now();
  base::PlatformThread::YieldCurrentThread();
  base::PlatformThread::Sleep(base::Milliseconds(20));
  const base::TimeDelta slept = base::TimeTicks::Now() - sleep_start;
  Require(slept >= base::Milliseconds(10) && slept < base::Seconds(2),
          "platform_thread_sleep");

  std::atomic<int> tls_destructor_count{0};
  base::ThreadLocalStorage::Slot tls_slot(&DestroyTlsPayload);
  TlsPayload application_payload{&tls_destructor_count, 0x51A0};
  tls_slot.Set(&application_payload);
  Require(tls_slot.Get() == &application_payload,
          "application_tls_initial_value");

  base::WaitableEvent release_event(
      base::WaitableEvent::ResetPolicy::MANUAL,
      base::WaitableEvent::InitialState::NOT_SIGNALED);
  std::atomic<int> started{0};
  std::atomic<int> handoff_bits{0};
  PlatformBasicsDelegate first(0, application_id, &tls_slot, &release_event,
                               &started, &handoff_bits,
                               &tls_destructor_count);
  PlatformBasicsDelegate second(1, application_id, &tls_slot, &release_event,
                                &started, &handoff_bits,
                                &tls_destructor_count);
  std::array<base::PlatformThreadHandle, 2> handles;

  Require(base::PlatformThread::Create(0, &first, &handles[0]),
          "platform_thread_create_first");
  Require(base::PlatformThread::Create(0, &second, &handles[1]),
          "platform_thread_create_second");
  Require(!handles[0].is_null() && !handles[1].is_null(),
          "platform_thread_handle_null");
  Require(!handles[0].is_equal(handles[1]), "platform_thread_handles_equal");
  Require(WaitUntil([&started] {
            return started.load(std::memory_order_acquire) == 2;
          }),
          "platform_workers_start_timeout");
  Require(handoff_bits.load(std::memory_order_acquire) == 0b11,
          "atomic_handoff");
  Require(tls_slot.Get() == &application_payload, "application_tls_isolation");

  release_event.Signal();
  base::PlatformThread::Join(handles[0]);
  base::PlatformThread::Join(handles[1]);

  Require(first.id() != second.id(), "platform_worker_ids_equal");
  Require(first.id() != application_id && second.id() != application_id,
          "platform_worker_id_matches_application");
  Require(first.succeeded() && second.succeeded(),
          "platform_worker_contract");
  Require(first.entropy_ok() && second.entropy_ok(), "worker_secure_entropy");
  Require(tls_destructor_count.load(std::memory_order_acquire) == 2,
          "worker_tls_destructors");
  Require(tls_slot.Get() == &application_payload,
          "application_tls_changed_after_join");
  tls_slot.Set(nullptr);
}

class TryLockDelegate final : public base::PlatformThread::Delegate {
 public:
  explicit TryLockDelegate(base::Lock* lock) : lock_(lock) {}

  void ThreadMain() override {
    started_.store(true, std::memory_order_release);
    const bool acquired = lock_->Try();
    acquired_.store(acquired, std::memory_order_release);
    if (acquired) {
      lock_->Release();
    }
    completed_.store(true, std::memory_order_release);
  }

  bool started() const { return started_.load(std::memory_order_acquire); }
  bool completed() const {
    return completed_.load(std::memory_order_acquire);
  }
  bool acquired() const { return acquired_.load(std::memory_order_acquire); }

 private:
  base::Lock* const lock_;
  std::atomic<bool> started_{false};
  std::atomic<bool> completed_{false};
  std::atomic<bool> acquired_{false};
};

class CounterDelegate final : public base::PlatformThread::Delegate {
 public:
  CounterDelegate(base::Lock* lock,
                  int* counter,
                  std::atomic<int>* started)
      : lock_(lock), counter_(counter), started_(started) {}

  void ThreadMain() override {
    started_->fetch_add(1, std::memory_order_release);
    for (int i = 0; i < kCounterIterations; ++i) {
      {
        base::AutoLock guard(*lock_);
        ++*counter_;
      }
      if ((i & 127) == 0) {
        base::PlatformThread::YieldCurrentThread();
      }
    }
  }

 private:
  base::Lock* const lock_;
  int* const counter_;
  std::atomic<int>* const started_;
};

void TestLock() {
  BeginPhase("lock");

  base::Lock lock;
  lock.Acquire();
  TryLockDelegate try_delegate(&lock);
  base::PlatformThreadHandle try_handle;
  Require(base::PlatformThread::Create(0, &try_delegate, &try_handle),
          "try_lock_thread_create");
  Require(WaitUntil([&try_delegate] { return try_delegate.started(); }),
          "try_lock_thread_start_timeout");
  const bool try_completed_while_held =
      WaitUntil([&try_delegate] { return try_delegate.completed(); },
                base::Milliseconds(250));
  lock.Release();
  Require(WaitUntil([&try_delegate] { return try_delegate.completed(); }),
          "try_lock_thread_completion_timeout");
  base::PlatformThread::Join(try_handle);
  Require(try_completed_while_held, "lock_try_blocked");
  Require(!try_delegate.acquired(), "lock_try_acquired_held_lock");

  if (!lock.Try()) {
    FailImmediately("lock_try_uncontended");
  }
  lock.Release();

  int counter = 0;
  std::atomic<int> started{0};
  CounterDelegate first(&lock, &counter, &started);
  CounterDelegate second(&lock, &counter, &started);
  std::array<base::PlatformThreadHandle, 2> handles;
  Require(base::PlatformThread::Create(0, &first, &handles[0]),
          "lock_counter_create_first");
  Require(base::PlatformThread::Create(0, &second, &handles[1]),
          "lock_counter_create_second");
  Require(WaitUntil([&started] {
            return started.load(std::memory_order_acquire) == 2;
          }),
          "lock_counter_start_timeout");

  for (int i = 0; i < kCounterIterations; ++i) {
    base::AutoLock guard(lock);
    ++counter;
  }
  base::PlatformThread::Join(handles[0]);
  base::PlatformThread::Join(handles[1]);
  Require(counter == 3 * kCounterIterations, "lock_shared_counter");
}

struct ConditionState {
  ConditionState() : condition(&lock) {}

  base::Lock lock;
  base::ConditionVariable condition;
  int permits = 0;
  bool broadcast = false;
  std::atomic<int> entered{0};
  std::atomic<int> signaled{0};
  std::atomic<bool> timed_out{false};
};

class ConditionDelegate final : public base::PlatformThread::Delegate {
 public:
  explicit ConditionDelegate(ConditionState* state) : state_(state) {}

  void ThreadMain() override {
    const base::TimeTicks deadline = base::TimeTicks::Now() + kPhaseTimeout;
    base::AutoLock guard(state_->lock);
    state_->entered.fetch_add(1, std::memory_order_release);

    while (state_->permits == 0 && !state_->broadcast) {
      const base::TimeDelta remaining = deadline - base::TimeTicks::Now();
      if (!remaining.is_positive()) {
        state_->timed_out.store(true, std::memory_order_release);
        return;
      }
      state_->condition.TimedWait(remaining);
    }

    if (state_->permits > 0) {
      --state_->permits;
      state_->signaled.fetch_add(1, std::memory_order_release);
    }

    while (!state_->broadcast) {
      const base::TimeDelta remaining = deadline - base::TimeTicks::Now();
      if (!remaining.is_positive()) {
        state_->timed_out.store(true, std::memory_order_release);
        return;
      }
      state_->condition.TimedWait(remaining);
    }
  }

 private:
  ConditionState* const state_;
};

void TestConditionVariable() {
  BeginPhase("condition_variable");

  ConditionState state;
  ConditionDelegate first(&state);
  ConditionDelegate second(&state);
  std::array<base::PlatformThreadHandle, 2> handles;
  Require(base::PlatformThread::Create(0, &first, &handles[0]),
          "condition_create_first");
  Require(base::PlatformThread::Create(0, &second, &handles[1]),
          "condition_create_second");
  Require(WaitUntil([&state] {
            return state.entered.load(std::memory_order_acquire) == 2;
          }),
          "condition_workers_start_timeout");

  {
    base::AutoLock guard(state.lock);
    state.permits = 1;
    state.condition.Signal();
  }
  Require(WaitUntil([&state] {
            return state.signaled.load(std::memory_order_acquire) == 1;
          }),
          "condition_signal_timeout");
  base::PlatformThread::Sleep(base::Milliseconds(25));
  Require(state.signaled.load(std::memory_order_acquire) == 1,
          "condition_signal_woke_multiple");

  {
    base::AutoLock guard(state.lock);
    state.broadcast = true;
    state.condition.Broadcast();
  }
  base::PlatformThread::Join(handles[0]);
  base::PlatformThread::Join(handles[1]);
  Require(!state.timed_out.load(std::memory_order_acquire),
          "condition_worker_timed_out");

  base::Lock timeout_lock;
  base::ConditionVariable timeout_condition(&timeout_lock);
  const base::TimeTicks timeout_start = base::TimeTicks::Now();
  const base::TimeTicks timeout_deadline =
      timeout_start + base::Milliseconds(60);
  {
    base::AutoLock guard(timeout_lock);
    while (base::TimeTicks::Now() < timeout_deadline) {
      timeout_condition.TimedWait(timeout_deadline -
                                  base::TimeTicks::Now());
    }
  }
  const base::TimeDelta elapsed = base::TimeTicks::Now() - timeout_start;
  Require(elapsed >= base::Milliseconds(45) && elapsed < base::Seconds(2),
          "condition_timeout_elapsed");
}

class EventWaitDelegate final : public base::PlatformThread::Delegate {
 public:
  EventWaitDelegate(base::WaitableEvent* event,
                    std::atomic<int>* started,
                    std::atomic<int>* released)
      : event_(event), started_(started), released_(released) {}

  void ThreadMain() override {
    started_->fetch_add(1, std::memory_order_release);
    const bool result = event_->TimedWait(kPhaseTimeout);
    result_.store(result, std::memory_order_release);
    if (result) {
      released_->fetch_add(1, std::memory_order_release);
    }
  }

  bool result() const { return result_.load(std::memory_order_acquire); }

 private:
  base::WaitableEvent* const event_;
  std::atomic<int>* const started_;
  std::atomic<int>* const released_;
  std::atomic<bool> result_{false};
};

class DelayedSignalDelegate final : public base::PlatformThread::Delegate {
 public:
  explicit DelayedSignalDelegate(base::WaitableEvent* event) : event_(event) {}

  void ThreadMain() override {
    started_.store(true, std::memory_order_release);
    base::PlatformThread::Sleep(base::Milliseconds(40));
    event_->Signal();
  }

  bool started() const { return started_.load(std::memory_order_acquire); }

 private:
  base::WaitableEvent* const event_;
  std::atomic<bool> started_{false};
};

void TestWaitableEvent() {
  BeginPhase("waitable_event");

  {
    base::WaitableEvent initially_signaled(
        base::WaitableEvent::ResetPolicy::MANUAL,
        base::WaitableEvent::InitialState::SIGNALED);
    Require(initially_signaled.IsSignaled(),
            "manual_initial_signal_missing");
    initially_signaled.Wait();
    Require(initially_signaled.IsSignaled(),
            "manual_initial_signal_consumed");
    initially_signaled.Reset();
    Require(!initially_signaled.IsSignaled(), "manual_reset_failed");
  }

  {
    base::WaitableEvent event(
        base::WaitableEvent::ResetPolicy::MANUAL,
        base::WaitableEvent::InitialState::NOT_SIGNALED);
    std::atomic<int> started{0};
    std::atomic<int> released{0};
    EventWaitDelegate first(&event, &started, &released);
    EventWaitDelegate second(&event, &started, &released);
    std::array<base::PlatformThreadHandle, 2> handles;
    Require(base::PlatformThread::Create(0, &first, &handles[0]),
            "manual_event_create_first");
    Require(base::PlatformThread::Create(0, &second, &handles[1]),
            "manual_event_create_second");
    Require(WaitUntil([&started] {
              return started.load(std::memory_order_acquire) == 2;
            }),
            "manual_event_workers_start_timeout");
    event.Signal();
    Require(WaitUntil([&released] {
              return released.load(std::memory_order_acquire) == 2;
            }),
            "manual_event_release_timeout");
    base::PlatformThread::Join(handles[0]);
    base::PlatformThread::Join(handles[1]);
    Require(first.result() && second.result(), "manual_event_wait_result");
    Require(event.IsSignaled(), "manual_event_not_sticky");
    event.Reset();
    Require(!event.IsSignaled(), "manual_event_reset");
  }

  {
    base::WaitableEvent initially_signaled(
        base::WaitableEvent::ResetPolicy::AUTOMATIC,
        base::WaitableEvent::InitialState::SIGNALED);
    Require(initially_signaled.IsSignaled(),
            "auto_initial_signal_missing");
    Require(!initially_signaled.IsSignaled(),
            "auto_initial_signal_not_consumed");
  }

  {
    base::WaitableEvent event(
        base::WaitableEvent::ResetPolicy::AUTOMATIC,
        base::WaitableEvent::InitialState::NOT_SIGNALED);
    std::atomic<int> started{0};
    std::atomic<int> released{0};
    EventWaitDelegate first(&event, &started, &released);
    EventWaitDelegate second(&event, &started, &released);
    std::array<base::PlatformThreadHandle, 2> handles;
    Require(base::PlatformThread::Create(0, &first, &handles[0]),
            "auto_event_create_first");
    Require(base::PlatformThread::Create(0, &second, &handles[1]),
            "auto_event_create_second");
    Require(WaitUntil([&started] {
              return started.load(std::memory_order_acquire) == 2;
            }),
            "auto_event_workers_start_timeout");

    event.Signal();
    Require(WaitUntil([&released] {
              return released.load(std::memory_order_acquire) >= 1;
            }),
            "auto_event_first_release_timeout");
    base::PlatformThread::Sleep(base::Milliseconds(25));
    Require(released.load(std::memory_order_acquire) == 1,
            "auto_event_single_signal_released_multiple");
    event.Signal();
    Require(WaitUntil([&released] {
              return released.load(std::memory_order_acquire) == 2;
            }),
            "auto_event_second_release_timeout");
    base::PlatformThread::Join(handles[0]);
    base::PlatformThread::Join(handles[1]);
    Require(first.result() && second.result(), "auto_event_wait_result");
    Require(!event.IsSignaled(), "auto_event_signal_not_consumed");
  }

  {
    base::WaitableEvent timeout_event(
        base::WaitableEvent::ResetPolicy::AUTOMATIC,
        base::WaitableEvent::InitialState::NOT_SIGNALED);
    Require(!timeout_event.TimedWait(base::TimeDelta()),
            "event_zero_timeout");
    Require(!timeout_event.TimedWait(base::Milliseconds(-1)),
            "event_negative_timeout");
    const base::TimeTicks start = base::TimeTicks::Now();
    Require(!timeout_event.TimedWait(base::Milliseconds(60)),
            "event_timeout_reported_signal");
    const base::TimeDelta elapsed = base::TimeTicks::Now() - start;
    Require(elapsed >= base::Milliseconds(45) &&
                elapsed < base::Seconds(2),
            "event_timeout_elapsed");
  }

  {
    base::WaitableEvent first(
        base::WaitableEvent::ResetPolicy::AUTOMATIC,
        base::WaitableEvent::InitialState::SIGNALED);
    base::WaitableEvent second(
        base::WaitableEvent::ResetPolicy::AUTOMATIC,
        base::WaitableEvent::InitialState::SIGNALED);
    std::array<base::WaitableEvent*, 2> waitables{&first, &second};
    Require(base::WaitableEvent::WaitMany(base::span(waitables)) == 0,
            "event_wait_many_lowest_index");
    Require(!first.IsSignaled(), "event_wait_many_did_not_consume_winner");
    Require(second.IsSignaled(), "event_wait_many_consumed_non_winner");
  }

  {
    base::WaitableEvent first(
        base::WaitableEvent::ResetPolicy::AUTOMATIC,
        base::WaitableEvent::InitialState::NOT_SIGNALED);
    base::WaitableEvent second(
        base::WaitableEvent::ResetPolicy::AUTOMATIC,
        base::WaitableEvent::InitialState::NOT_SIGNALED);
    DelayedSignalDelegate delegate(&second);
    base::PlatformThreadHandle handle;
    Require(base::PlatformThread::Create(0, &delegate, &handle),
            "event_wait_many_create");
    Require(WaitUntil([&delegate] { return delegate.started(); }),
            "event_wait_many_worker_start_timeout");
    std::array<base::WaitableEvent*, 2> waitables{&first, &second};
    const base::TimeTicks start = base::TimeTicks::Now();
    Require(base::WaitableEvent::WaitMany(base::span(waitables)) == 1,
            "event_wait_many_blocking_index");
    const base::TimeDelta elapsed = base::TimeTicks::Now() - start;
    Require(elapsed >= base::Milliseconds(20) &&
                elapsed < base::Seconds(2),
            "event_wait_many_blocking_elapsed");
    base::PlatformThread::Join(handle);
  }
}

class HandshakeDelegate final : public base::PlatformThread::Delegate {
 public:
  HandshakeDelegate(base::WaitableEvent* worker_to_application,
                    base::WaitableEvent* application_to_worker,
                    std::atomic<int>* payload)
      : worker_to_application_(worker_to_application),
        application_to_worker_(application_to_worker),
        payload_(payload) {}

  void ThreadMain() override {
    bool ok = !emscripten_is_main_browser_thread() &&
              !emscripten_is_main_runtime_thread();
    worker_to_application_->Signal();
    ok = application_to_worker_->TimedWait(kPhaseTimeout) && ok;
    const int request = payload_->load(std::memory_order_acquire);
    ok = ok && request == 0x51A1;
    payload_->store(request + 1, std::memory_order_release);
    succeeded_.store(ok, std::memory_order_release);
    worker_to_application_->Signal();
  }

  bool succeeded() const {
    return succeeded_.load(std::memory_order_acquire);
  }

 private:
  base::WaitableEvent* const worker_to_application_;
  base::WaitableEvent* const application_to_worker_;
  std::atomic<int>* const payload_;
  std::atomic<bool> succeeded_{false};
};

void TestBidirectionalHandshake() {
  BeginPhase("bidirectional_handshake");

  base::WaitableEvent worker_to_application(
      base::WaitableEvent::ResetPolicy::AUTOMATIC,
      base::WaitableEvent::InitialState::NOT_SIGNALED);
  base::WaitableEvent application_to_worker(
      base::WaitableEvent::ResetPolicy::AUTOMATIC,
      base::WaitableEvent::InitialState::NOT_SIGNALED);
  std::atomic<int> payload{0};
  HandshakeDelegate delegate(&worker_to_application, &application_to_worker,
                             &payload);
  base::PlatformThreadHandle handle;
  Require(base::PlatformThread::Create(0, &delegate, &handle),
          "handshake_thread_create");
  Require(worker_to_application.TimedWait(kPhaseTimeout),
          "worker_to_application_timeout");
  payload.store(0x51A1, std::memory_order_release);
  application_to_worker.Signal();
  Require(worker_to_application.TimedWait(kPhaseTimeout),
          "worker_reply_timeout");
  base::PlatformThread::Join(handle);
  Require(delegate.succeeded(), "bidirectional_worker_contract");
  Require(payload.load(std::memory_order_acquire) == 0x51A2,
          "bidirectional_payload");
}

}  // namespace

int main() {
  if (emscripten_is_main_browser_thread()) {
    return Fail("application_main_on_browser_thread");
  }
  if (emscripten_is_main_runtime_thread()) {
    return Fail("application_main_on_runtime_thread");
  }
  if (!emscripten_has_threading_support()) {
    return Fail("pthread_support_unavailable");
  }

  std::fprintf(stdout, "%s:RUNTIME_START\n", kPrefix);
  std::fflush(stdout);

  const base::Time wall_start = base::Time::Now();
  if (wall_start.InMillisecondsSinceUnixEpoch() < 1577836800000LL) {
    return Fail("wall_clock_not_plausible");
  }

  base::TimeTicks previous = base::TimeTicks::Now();
  for (int i = 0; i < 1000; ++i) {
    const base::TimeTicks current = base::TimeTicks::Now();
    if (current < previous) {
      return Fail("monotonic_clock_went_backwards");
    }
    previous = current;
  }

  const base::TimeTicks sleep_start = base::TimeTicks::Now();
  base::PlatformThread::Sleep(base::Milliseconds(250));
  const base::TimeDelta slept = base::TimeTicks::Now() - sleep_start;
  if (slept < base::Milliseconds(200) || slept > base::Seconds(5)) {
    return Fail("bounded_sleep_elapsed");
  }
  if (base::Time::Now() <= wall_start) {
    return Fail("wall_clock_did_not_progress");
  }
  if (!base::TimeTicks::IsHighResolution() ||
      !base::TimeTicks::IsConsistentAcrossProcesses() ||
      base::TimeTicks::GetClock() !=
          base::TimeTicks::Clock::WASM_EMSCRIPTEN_GET_NOW) {
    return Fail("monotonic_clock_metadata");
  }
  if (base::ThreadTicks::IsSupported()) {
    return Fail("thread_cpu_clock_claimed_supported");
  }

  std::array<uint8_t, 513> first{};
  std::array<uint8_t, 513> second{};
  base::RandBytes(first);
  base::RandBytes(second);
  if (!HasNonZeroByte(first) || !HasNonZeroByte(second)) {
    return Fail("secure_entropy_all_zero");
  }
  if (first == second) {
    return Fail("secure_entropy_buffers_equal");
  }

  TestPlatformThreadAndTls();
  TestLock();
  TestConditionVariable();
  TestWaitableEvent();
  TestBidirectionalHandshake();

  std::fprintf(stdout, "%s:RUNTIME_END\n", kPrefix);
  std::fprintf(
      stdout,
      "%s:RESULT wall_time=ok monotonic_time=ok bounded_sleep=ok "
      "secure_entropy=ok worker_entropy=ok platform_thread=ok "
      "thread_ids=ok thread_names=diagnostic_ok yield_sleep=ok "
      "atomic_handoff=ok tls=ok tls_destructors=ok lock=ok lock_try=ok "
      "condition_signal=ok condition_broadcast=ok condition_timeout=ok "
      "event_manual=ok event_auto=ok event_reset=ok event_timeout=ok "
      "event_wait_many=ok bidirectional=ok joins=ok browser_main_free=ok\n",
      kPrefix);
  std::fprintf(stdout, "%s:PASS\n", kPrefix);
  std::fflush(stdout);
  return 0;
}
