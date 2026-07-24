// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <emscripten/threading.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <utility>
#include <vector>

#include "base/functional/bind.h"
#include "base/functional/callback.h"
#include "base/location.h"
#include "base/memory/scoped_refptr.h"
#include "base/message_loop/message_pump.h"
#include "base/message_loop/message_pump_type.h"
#include "base/run_loop.h"
#include "base/synchronization/waitable_event.h"
#include "base/task/single_thread_task_executor.h"
#include "base/task/single_thread_task_runner.h"
#include "base/threading/platform_thread.h"
#include "base/time/time.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "m1_task_smoke must be built for WebAssembly"
#endif

#if BUILDFLAG(IS_POSIX)
#error "WebAssembly must not inherit POSIX platform semantics"
#endif

namespace {

constexpr char kPrefix[] = "CHROMIUM_WASM_M1_TASK";
constexpr base::TimeDelta kPhaseTimeout = base::Seconds(3);
constexpr base::TimeDelta kWorkerWakeDelay = base::Milliseconds(90);
constexpr base::TimeDelta kIdleProbeDelay = base::Milliseconds(250);
constexpr int kMaximumIdleWaitCycles = 8;
constexpr int kExpectedTaskCount = 18;
constexpr int kExpectedDelayedWakeCount = 3;

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

struct SmokeCounters {
  std::atomic<int> task_count{0};
  std::atomic<int> delayed_wake_count{0};
  std::atomic<int> wake_count{0};
  int wait_count = 0;
  int idle_wake_return_count = 0;
  int max_nesting = 1;
  int nested_begin_count = 0;
  int nested_exit_count = 0;
  int joinable_thread_count = 0;
  int joined_thread_count = 0;
};

struct SmokeTimings {
  base::TimeDelta worker_to_application_latency;
  base::TimeDelta sleeping_quit_latency;
  base::TimeDelta idle_probe_elapsed;
  base::TimeDelta idle_wake_latency;
};

void RecordTask(SmokeCounters* counters, bool delayed_wake = false) {
  counters->task_count.fetch_add(1, std::memory_order_relaxed);
  if (delayed_wake) {
    counters->delayed_wake_count.fetch_add(1, std::memory_order_relaxed);
  }
}

class TaskWorker final : public base::PlatformThread::Delegate {
 public:
  explicit TaskWorker(std::atomic<int>* live_thread_count)
      : live_thread_count_(live_thread_count),
        started_(base::WaitableEvent::ResetPolicy::MANUAL,
                 base::WaitableEvent::InitialState::NOT_SIGNALED) {}

  TaskWorker(const TaskWorker&) = delete;
  TaskWorker& operator=(const TaskWorker&) = delete;

  void ThreadMain() override {
    live_thread_count_->fetch_add(1, std::memory_order_release);
    thread_id_ = base::PlatformThread::CurrentId();

    {
      base::SingleThreadTaskExecutor executor(base::MessagePumpType::DEFAULT);
      base::RunLoop run_loop;
      task_runner_ = executor.task_runner();
      run_loop_ = &run_loop;
      started_.Signal();
      run_loop.Run();
      run_loop_ = nullptr;
    }

    exited_.store(true, std::memory_order_release);
    live_thread_count_->fetch_sub(1, std::memory_order_release);
  }

  bool WaitUntilStarted() { return started_.TimedWait(kPhaseTimeout); }

  scoped_refptr<base::SingleThreadTaskRunner> task_runner() const {
    return task_runner_;
  }

  base::PlatformThreadId thread_id() const { return thread_id_; }

  bool exited() const { return exited_.load(std::memory_order_acquire); }

  void QuitWhenIdleOnWorker() {
    Require(base::PlatformThread::CurrentId() == thread_id_,
            "worker_quit_wrong_thread");
    Require(run_loop_ != nullptr, "worker_run_loop_missing");
    run_loop_->QuitWhenIdle();
  }

 private:
  std::atomic<int>* const live_thread_count_;
  base::WaitableEvent started_;
  scoped_refptr<base::SingleThreadTaskRunner> task_runner_;
  base::PlatformThreadId thread_id_;
  base::RunLoop* run_loop_ = nullptr;
  std::atomic<bool> exited_{false};
};

class CountingNestingObserver final : public base::RunLoop::NestingObserver {
 public:
  explicit CountingNestingObserver(SmokeCounters* counters)
      : counters_(counters) {}

  void OnBeginNestedRunLoop() override {
    ++current_depth_;
    ++counters_->nested_begin_count;
    counters_->max_nesting = std::max(counters_->max_nesting, current_depth_);
  }

  void OnExitNestedRunLoop() override {
    ++counters_->nested_exit_count;
    --current_depth_;
    Require(current_depth_ >= 1, "nested_depth_underflow");
  }

  int current_depth() const { return current_depth_; }

 private:
  SmokeCounters* const counters_;
  int current_depth_ = 1;
};

// MessagePumpDefault has no public wait counter. For this isolated phase,
// every DoIdleWork() made by the pinned default pump is followed by one
// WaitableEvent::TimedWait(), unless the pump was synchronously quit. This
// delegate never quits from DoIdleWork(), so `wait_entries_` is a harness-level
// count of actual idle-wait entries. Each subsequent DoWork() is counted as the
// matching return from that wait. This deliberately does not claim to expose an
// internal production metric.
class IdlePumpDelegate final : public base::MessagePump::Delegate {
 public:
  IdlePumpDelegate(base::MessagePump* pump,
                   base::WaitableEvent* worker_may_wake,
                   std::atomic<bool>* wake_requested,
                   base::TimeTicks* wake_post_time)
      : pump_(pump),
        worker_may_wake_(worker_may_wake),
        wake_requested_(wake_requested),
        wake_post_time_(wake_post_time) {}

  NextWorkInfo DoWork() override {
    ++do_work_count_;
    if (wait_armed_) {
      ++wake_return_count_;
      wait_armed_ = false;
    }

    if (wake_requested_->load(std::memory_order_acquire)) {
      wake_observed_time_ = base::TimeTicks::Now();
      pump_->Quit();
    }
    return {.delayed_run_time = base::TimeTicks::Max()};
  }

  void DoIdleWork() override {
    ++wait_entries_;
    wait_armed_ = true;
    if (wait_entries_ == 1) {
      worker_may_wake_->Signal();
    }
  }

  void BeforeWait() override {}
  void BeginNativeWorkBeforeDoWork() override {}
  int RunDepth() override { return 0; }

  int do_work_count() const { return do_work_count_; }
  int wait_entries() const { return wait_entries_; }
  int wake_return_count() const { return wake_return_count_; }
  base::TimeTicks wake_observed_time() const { return wake_observed_time_; }
  base::TimeTicks wake_post_time() const { return *wake_post_time_; }

 private:
  void OnBeginWorkItem() override {}
  void OnEndWorkItem(int) override {}

  base::MessagePump* const pump_;
  base::WaitableEvent* const worker_may_wake_;
  std::atomic<bool>* const wake_requested_;
  base::TimeTicks* const wake_post_time_;
  bool wait_armed_ = false;
  int do_work_count_ = 0;
  int wait_entries_ = 0;
  int wake_return_count_ = 0;
  base::TimeTicks wake_observed_time_;
};

void TestImmediateTasks(
    const scoped_refptr<base::SingleThreadTaskRunner>& application_runner,
    SmokeCounters* counters) {
  BeginPhase("immediate");

  base::RunLoop run_loop;
  std::vector<int> order;
  for (int value = 1; value <= 3; ++value) {
    Require(
        application_runner->PostTask(
            FROM_HERE, base::BindOnce(
                           [](SmokeCounters* counters, std::vector<int>* order,
                              base::RunLoop* run_loop, int value) {
                             RecordTask(counters);
                             order->push_back(value);
                             if (value == 3) {
                               run_loop->QuitWhenIdle();
                             }
                           },
                           counters, &order, &run_loop, value)),
        "immediate_post_failed");
  }
  run_loop.Run();

  Require(order == std::vector<int>({1, 2, 3}), "immediate_fifo_order");
}

void TestDelayedTasks(
    const scoped_refptr<base::SingleThreadTaskRunner>& application_runner,
    SmokeCounters* counters) {
  BeginPhase("delayed");

  constexpr std::array<base::TimeDelta, 3> kDelays = {
      base::Milliseconds(60),
      base::Milliseconds(110),
      base::Milliseconds(170),
  };
  base::RunLoop run_loop;
  std::vector<int> order;
  std::array<base::TimeTicks, 3> run_times;

  auto post_delayed = [&](int index, bool quits_loop) {
    const base::TimeTicks post_time = base::TimeTicks::Now();
    const bool posted = application_runner->PostDelayedTask(
        FROM_HERE,
        base::BindOnce(
            [](SmokeCounters* counters,
               std::array<base::TimeTicks, 3>* run_times,
               std::vector<int>* order, base::RunLoop* run_loop, int index,
               bool quits_loop, base::TimeTicks no_earlier_than) {
              (*run_times)[index] = base::TimeTicks::Now();
              Require((*run_times)[index] >= no_earlier_than,
                      "delayed_task_ran_early");
              RecordTask(counters, /*delayed_wake=*/true);
              order->push_back(index);
              if (quits_loop) {
                run_loop->Quit();
              }
            },
            counters, &run_times, &order, &run_loop, index, quits_loop,
            post_time + kDelays[index]),
        kDelays[index]);
    Require(posted, "delayed_post_failed");
  };

  // Deliberately post in reverse deadline order. The queue must still run tasks
  // in deadline order.
  post_delayed(2, /*quits_loop=*/true);
  post_delayed(0, /*quits_loop=*/false);
  post_delayed(1, /*quits_loop=*/false);
  run_loop.Run();

  Require(order == std::vector<int>({0, 1, 2}), "delayed_deadline_order");
}

void TestBidirectionalWake(
    const scoped_refptr<base::SingleThreadTaskRunner>& application_runner,
    const scoped_refptr<base::SingleThreadTaskRunner>& worker_runner,
    base::PlatformThreadId application_thread_id,
    base::PlatformThreadId worker_thread_id,
    SmokeCounters* counters,
    SmokeTimings* timings) {
  BeginPhase("bidirectional_wake");

  base::WaitableEvent worker_may_post(
      base::WaitableEvent::ResetPolicy::MANUAL,
      base::WaitableEvent::InitialState::NOT_SIGNALED);
  std::atomic<int> stage{0};
  base::TimeTicks worker_post_time;
  base::RunLoop run_loop;

  Require(
      worker_runner->PostTask(
          FROM_HERE,
          base::BindOnce(
              [](SmokeCounters* counters,
                 base::PlatformThreadId worker_thread_id,
                 base::WaitableEvent* worker_may_post, std::atomic<int>* stage,
                 base::TimeTicks* worker_post_time,
                 scoped_refptr<base::SingleThreadTaskRunner> application_runner,
                 base::PlatformThreadId application_thread_id,
                 SmokeTimings* timings,
                 scoped_refptr<base::SingleThreadTaskRunner> worker_runner,
                 base::RunLoop* run_loop) {
                RecordTask(counters);
                Require(base::PlatformThread::CurrentId() == worker_thread_id,
                        "worker_to_application_wrong_worker");
                Require(worker_may_post->TimedWait(kPhaseTimeout),
                        "worker_to_application_arm_timeout");
                base::PlatformThread::Sleep(kWorkerWakeDelay);
                Require(stage->load(std::memory_order_acquire) == 0,
                        "worker_to_application_stage_before_post");
                *worker_post_time = base::TimeTicks::Now();
                stage->store(1, std::memory_order_release);
                Require(
                    application_runner->PostTask(
                        FROM_HERE,
                        base::BindOnce(
                            [](SmokeCounters* counters,
                               base::PlatformThreadId application_thread_id,
                               std::atomic<int>* stage, SmokeTimings* timings,
                               base::TimeTicks* worker_post_time,
                               scoped_refptr<base::SingleThreadTaskRunner>
                                   worker_runner,
                               base::PlatformThreadId worker_thread_id,
                               scoped_refptr<base::SingleThreadTaskRunner>
                                   application_runner,
                               base::RunLoop* run_loop) {
                              RecordTask(counters);
                              Require(
                                  base::PlatformThread::CurrentId() ==
                                      application_thread_id,
                                  "worker_to_application_wrong_application");
                              Require(
                                  stage->load(std::memory_order_acquire) == 1,
                                  "worker_to_application_stage");
                              timings->worker_to_application_latency =
                                  base::TimeTicks::Now() - *worker_post_time;
                              Require(
                                  !timings->worker_to_application_latency
                                          .is_negative() &&
                                      timings->worker_to_application_latency <
                                          base::Seconds(1),
                                  "worker_to_application_wake_latency");
                              counters->wake_count.fetch_add(
                                  1, std::memory_order_relaxed);
                              stage->store(2, std::memory_order_release);

                              Require(
                                  worker_runner->PostTask(
                                      FROM_HERE,
                                      base::BindOnce(
                                          [](SmokeCounters* counters,
                                             base::PlatformThreadId
                                                 worker_thread_id,
                                             std::atomic<int>* stage,
                                             scoped_refptr<
                                                 base::SingleThreadTaskRunner>
                                                 application_runner,
                                             base::PlatformThreadId
                                                 application_thread_id,
                                             base::RunLoop* run_loop) {
                                            RecordTask(counters);
                                            Require(
                                                base::PlatformThread::
                                                        CurrentId() ==
                                                    worker_thread_id,
                                                "application_to_worker_wrong_"
                                                "worker");
                                            Require(
                                                stage->load(
                                                    std::
                                                        memory_order_acquire) ==
                                                    2,
                                                "application_to_worker_stage");
                                            stage->store(
                                                3, std::memory_order_release);
                                            Require(
                                                application_runner->PostTask(
                                                    FROM_HERE,
                                                    base::BindOnce(
                                                        [](SmokeCounters*
                                                               counters,
                                                           base::PlatformThreadId
                                                               application_thread_id,
                                                           std::atomic<int>*
                                                               stage,
                                                           base::RunLoop*
                                                               run_loop) {
                                                          RecordTask(counters);
                                                          Require(
                                                              base::PlatformThread::
                                                                      CurrentId() ==
                                                                  application_thread_id,
                                                              "worker_reply_"
                                                              "wrong_"
                                                              "application");
                                                          Require(
                                                              stage->load(
                                                                  std::
                                                                      memory_order_acquire) ==
                                                                  3,
                                                              "worker_reply_"
                                                              "stage");
                                                          stage->store(
                                                              4,
                                                              std::
                                                                  memory_order_release);
                                                          run_loop->Quit();
                                                        },
                                                        counters,
                                                        application_thread_id,
                                                        stage, run_loop)),
                                                "worker_reply_post_failed");
                                          },
                                          counters, worker_thread_id, stage,
                                          application_runner,
                                          application_thread_id, run_loop)),
                                  "application_to_worker_post_failed");
                            },
                            counters, application_thread_id, stage, timings,
                            worker_post_time, worker_runner, worker_thread_id,
                            application_runner, run_loop)),
                    "worker_to_application_post_failed");
              },
              counters, worker_thread_id, &worker_may_post, &stage,
              &worker_post_time, application_runner, application_thread_id,
              timings, worker_runner, &run_loop)),
      "worker_wake_task_post_failed");

  Require(application_runner->PostTask(
              FROM_HERE, base::BindOnce(
                             [](SmokeCounters* counters,
                                base::WaitableEvent* worker_may_post) {
                               RecordTask(counters);
                               worker_may_post->Signal();
                             },
                             counters, &worker_may_post)),
          "worker_wake_arm_post_failed");

  const base::TimeTicks run_start = base::TimeTicks::Now();
  run_loop.Run();
  const base::TimeDelta run_elapsed = base::TimeTicks::Now() - run_start;
  Require(stage.load(std::memory_order_acquire) == 4,
          "bidirectional_final_stage");
  Require(
      run_elapsed >= base::Milliseconds(60) && run_elapsed < base::Seconds(2),
      "worker_to_application_did_not_sleep_and_wake");
}

void TestNestedRunLoop(
    const scoped_refptr<base::SingleThreadTaskRunner>& application_runner,
    SmokeCounters* counters) {
  BeginPhase("nested_run_loop");

  base::RunLoop outer_loop;
  std::vector<int> order;
  Require(
      application_runner->PostTask(
          FROM_HERE,
          base::BindOnce(
              [](SmokeCounters* counters, std::vector<int>* order,
                 scoped_refptr<base::SingleThreadTaskRunner> application_runner,
                 base::RunLoop* outer_loop) {
                RecordTask(counters);
                order->push_back(1);

                base::RunLoop nested_loop(
                    base::RunLoop::Type::kNestableTasksAllowed);
                Require(
                    application_runner->PostTask(
                        FROM_HERE,
                        base::BindOnce(
                            [](SmokeCounters* counters, std::vector<int>* order,
                               base::RunLoop* nested_loop) {
                              RecordTask(counters);
                              Require(base::RunLoop::IsNestedOnCurrentThread(),
                                      "nested_loop_not_reported_nested");
                              order->push_back(2);
                              nested_loop->Quit();
                            },
                            counters, order, &nested_loop)),
                    "nested_body_post_failed");
                nested_loop.Run();
                order->push_back(3);

                Require(
                    application_runner->PostTask(
                        FROM_HERE,
                        base::BindOnce(
                            [](SmokeCounters* counters, std::vector<int>* order,
                               base::RunLoop* outer_loop) {
                              RecordTask(counters);
                              Require(!base::RunLoop::IsNestedOnCurrentThread(),
                                      "outer_continuation_still_nested");
                              order->push_back(4);
                              outer_loop->Quit();
                            },
                            counters, order, outer_loop)),
                    "outer_continuation_post_failed");
              },
              counters, &order, application_runner, &outer_loop)),
      "outer_entry_post_failed");

  outer_loop.Run();
  Require(order == std::vector<int>({1, 2, 3, 4}),
          "nested_independent_quit_order");
}

void TestQuitWhileSleeping(
    const scoped_refptr<base::SingleThreadTaskRunner>& application_runner,
    const scoped_refptr<base::SingleThreadTaskRunner>& worker_runner,
    base::PlatformThreadId worker_thread_id,
    SmokeCounters* counters,
    SmokeTimings* timings) {
  BeginPhase("quit_while_sleeping");

  base::WaitableEvent worker_may_quit(
      base::WaitableEvent::ResetPolicy::MANUAL,
      base::WaitableEvent::InitialState::NOT_SIGNALED);
  std::atomic<bool> quit_posted{false};
  base::TimeTicks quit_post_time;
  base::RunLoop run_loop;
  base::RepeatingClosure quit_closure = run_loop.QuitClosure();

  Require(worker_runner->PostTask(
              FROM_HERE,
              base::BindOnce(
                  [](SmokeCounters* counters,
                     base::PlatformThreadId worker_thread_id,
                     base::WaitableEvent* worker_may_quit,
                     base::TimeTicks* quit_post_time,
                     std::atomic<bool>* quit_posted,
                     base::RepeatingClosure quit_closure) {
                    RecordTask(counters);
                    Require(
                        base::PlatformThread::CurrentId() == worker_thread_id,
                        "sleeping_quit_wrong_worker");
                    Require(worker_may_quit->TimedWait(kPhaseTimeout),
                            "sleeping_quit_arm_timeout");
                    base::PlatformThread::Sleep(kWorkerWakeDelay);
                    *quit_post_time = base::TimeTicks::Now();
                    quit_posted->store(true, std::memory_order_release);
                    quit_closure.Run();
                  },
                  counters, worker_thread_id, &worker_may_quit, &quit_post_time,
                  &quit_posted, std::move(quit_closure))),
          "sleeping_quit_worker_post_failed");
  Require(application_runner->PostTask(
              FROM_HERE, base::BindOnce(
                             [](SmokeCounters* counters,
                                base::WaitableEvent* worker_may_quit) {
                               RecordTask(counters);
                               worker_may_quit->Signal();
                             },
                             counters, &worker_may_quit)),
          "sleeping_quit_arm_post_failed");

  const base::TimeTicks run_start = base::TimeTicks::Now();
  run_loop.Run();
  const base::TimeTicks run_end = base::TimeTicks::Now();
  Require(quit_posted.load(std::memory_order_acquire),
          "sleeping_quit_not_posted");
  const base::TimeDelta run_elapsed = run_end - run_start;
  timings->sleeping_quit_latency = run_end - quit_post_time;
  Require(
      run_elapsed >= base::Milliseconds(60) && run_elapsed < base::Seconds(2),
      "sleeping_quit_did_not_wait");
  Require(!timings->sleeping_quit_latency.is_negative() &&
              timings->sleeping_quit_latency < base::Seconds(1),
          "sleeping_quit_wake_latency");
  counters->wake_count.fetch_add(1, std::memory_order_relaxed);
}

void TestIdlePump(
    const scoped_refptr<base::SingleThreadTaskRunner>& worker_runner,
    SmokeCounters* counters,
    SmokeTimings* timings) {
  BeginPhase("idle_pump");

  std::unique_ptr<base::MessagePump> pump =
      base::MessagePump::Create(base::MessagePumpType::DEFAULT);
  Require(pump != nullptr, "default_message_pump_create");

  base::WaitableEvent worker_may_wake(
      base::WaitableEvent::ResetPolicy::MANUAL,
      base::WaitableEvent::InitialState::NOT_SIGNALED);
  base::WaitableEvent worker_finished(
      base::WaitableEvent::ResetPolicy::MANUAL,
      base::WaitableEvent::InitialState::NOT_SIGNALED);
  std::atomic<bool> wake_requested{false};
  base::TimeTicks wake_post_time;
  IdlePumpDelegate delegate(pump.get(), &worker_may_wake, &wake_requested,
                            &wake_post_time);

  Require(
      worker_runner->PostTask(
          FROM_HERE,
          base::BindOnce(
              [](SmokeCounters* counters, base::WaitableEvent* worker_may_wake,
                 base::TimeTicks* wake_post_time,
                 std::atomic<bool>* wake_requested, base::MessagePump* pump,
                 base::WaitableEvent* worker_finished) {
                RecordTask(counters);
                Require(worker_may_wake->TimedWait(kPhaseTimeout),
                        "idle_probe_arm_timeout");
                base::PlatformThread::Sleep(kIdleProbeDelay);
                *wake_post_time = base::TimeTicks::Now();
                wake_requested->store(true, std::memory_order_release);
                pump->ScheduleWork();
                worker_finished->Signal();
              },
              counters, &worker_may_wake, &wake_post_time, &wake_requested,
              pump.get(), &worker_finished)),
      "idle_probe_worker_post_failed");

  const base::TimeTicks idle_start = base::TimeTicks::Now();
  pump->Run(&delegate);
  timings->idle_probe_elapsed = base::TimeTicks::Now() - idle_start;
  Require(worker_finished.TimedWait(kPhaseTimeout),
          "idle_probe_worker_completion_timeout");

  Require(wake_requested.load(std::memory_order_acquire),
          "idle_probe_wake_missing");
  Require(delegate.wait_entries() >= 1 &&
              delegate.wait_entries() <= kMaximumIdleWaitCycles,
          "idle_probe_unbounded_wait_loop");
  Require(delegate.wake_return_count() == delegate.wait_entries(),
          "idle_probe_wait_wake_mismatch");
  Require(delegate.do_work_count() == delegate.wake_return_count() + 1,
          "idle_probe_do_work_count");
  Require(timings->idle_probe_elapsed >= base::Milliseconds(200) &&
              timings->idle_probe_elapsed < base::Seconds(2),
          "idle_probe_elapsed");

  timings->idle_wake_latency =
      delegate.wake_observed_time() - delegate.wake_post_time();
  Require(!timings->idle_wake_latency.is_negative() &&
              timings->idle_wake_latency < base::Seconds(1),
          "idle_probe_wake_latency");

  counters->wait_count = delegate.wait_entries();
  counters->idle_wake_return_count = delegate.wake_return_count();
  counters->wake_count.fetch_add(delegate.wake_return_count(),
                                 std::memory_order_relaxed);
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

  SmokeCounters counters;
  SmokeTimings timings;
  std::atomic<int> live_worker_count{0};
  const base::PlatformThreadId application_thread_id =
      base::PlatformThread::CurrentId();

  {
    base::SingleThreadTaskExecutor application_executor(
        base::MessagePumpType::DEFAULT);
    const scoped_refptr<base::SingleThreadTaskRunner> application_runner =
        application_executor.task_runner();
    Require(application_runner != nullptr, "application_task_runner_missing");
    Require(base::SingleThreadTaskRunner::HasCurrentDefault(),
            "application_default_task_runner_missing");
    Require(
        base::SingleThreadTaskRunner::GetCurrentDefault() == application_runner,
        "application_default_task_runner_mismatch");
    Require(application_runner->RunsTasksInCurrentSequence(),
            "application_task_runner_wrong_sequence");

    CountingNestingObserver nesting_observer(&counters);
    base::RunLoop::AddNestingObserverOnCurrentThread(&nesting_observer);

    TaskWorker worker(&live_worker_count);
    base::PlatformThreadHandle worker_handle;
    Require(base::PlatformThread::Create(0, &worker, &worker_handle),
            "task_worker_create");
    ++counters.joinable_thread_count;
    Require(worker.WaitUntilStarted(), "task_worker_start_timeout");
    const scoped_refptr<base::SingleThreadTaskRunner> worker_runner =
        worker.task_runner();
    Require(worker_runner != nullptr, "worker_task_runner_missing");
    Require(worker.thread_id() != base::kInvalidThreadId &&
                worker.thread_id() != application_thread_id,
            "worker_thread_id");
    Require(live_worker_count.load(std::memory_order_acquire) == 1,
            "worker_live_count_after_start");

    TestImmediateTasks(application_runner, &counters);
    TestDelayedTasks(application_runner, &counters);
    TestBidirectionalWake(application_runner, worker_runner,
                          application_thread_id, worker.thread_id(), &counters,
                          &timings);
    TestNestedRunLoop(application_runner, &counters);
    TestQuitWhileSleeping(application_runner, worker_runner, worker.thread_id(),
                          &counters, &timings);
    TestIdlePump(worker_runner, &counters, &timings);

    BeginPhase("clean_shutdown");
    Require(worker_runner->PostTask(
                FROM_HERE, base::BindOnce(
                               [](SmokeCounters* counters, TaskWorker* worker) {
                                 RecordTask(counters);
                                 worker->QuitWhenIdleOnWorker();
                               },
                               &counters, &worker)),
            "worker_shutdown_post_failed");
    base::PlatformThread::Join(worker_handle);
    ++counters.joined_thread_count;
    Require(worker.exited(), "worker_did_not_exit");
    Require(live_worker_count.load(std::memory_order_acquire) == 0,
            "worker_live_count_after_join");
    Require(!worker_runner->PostTask(FROM_HERE, base::BindOnce([] {})),
            "worker_runner_accepted_task_after_join");

    base::RunLoop::RemoveNestingObserverOnCurrentThread(&nesting_observer);
    Require(nesting_observer.current_depth() == 1, "nested_depth_not_restored");
  }

  Require(!base::SingleThreadTaskRunner::HasCurrentDefault(),
          "application_executor_not_destroyed");
  Require(
      counters.task_count.load(std::memory_order_acquire) == kExpectedTaskCount,
      "task_count");
  // Each delayed callback is counted only after proving its own distinct
  // no-earlier deadline.
  Require(counters.delayed_wake_count.load(std::memory_order_acquire) ==
              kExpectedDelayedWakeCount,
          "delayed_wake_count");
  Require(counters.wake_count.load(std::memory_order_acquire) >= 3 &&
              counters.wake_count.load(std::memory_order_acquire) <=
                  2 + kMaximumIdleWaitCycles,
          "wake_count");
  Require(
      counters.wait_count >= 1 && counters.wait_count <= kMaximumIdleWaitCycles,
      "wait_count");
  Require(counters.max_nesting == 2 && counters.nested_begin_count == 1 &&
              counters.nested_exit_count == 1,
          "nesting_counters");
  Require(
      counters.joinable_thread_count == 1 && counters.joined_thread_count == 1,
      "worker_join_counters");

  std::fprintf(stdout, "%s:RUNTIME_END\n", kPrefix);
  std::fprintf(
      stdout,
      "%s:RESULT immediate=ok delayed_not_early=ok "
      "delayed_deadline_order=ok worker_to_app_wake=ok "
      "app_to_worker=ok nested_quit_independent=ok outer_continues=ok "
      "sleeping_quit_wake=ok idle_wait_bounded=ok clean_shutdown=ok "
      "task_count=%d delayed_wake_count=%d "
      "wake_count_bounded_nonzero=ok wait_count_bounded_nonzero=ok "
      "wake_count=%d wait_count=%d "
      "idle_wake_returns=%d max_nesting=%d nested_begin_count=%d "
      "nested_exit_count=%d joinable_created=%d joinable_joined=%d "
      "worker_to_app_latency_ms=%lld sleeping_quit_latency_ms=%lld "
      "idle_elapsed_ms=%lld idle_wake_latency_ms=%lld "
      "wait_counter_source=delegate_idle_cycles "
      "browser_heartbeat=external\n",
      kPrefix, counters.task_count.load(std::memory_order_acquire),
      counters.delayed_wake_count.load(std::memory_order_acquire),
      counters.wake_count.load(std::memory_order_acquire), counters.wait_count,
      counters.idle_wake_return_count, counters.max_nesting,
      counters.nested_begin_count, counters.nested_exit_count,
      counters.joinable_thread_count, counters.joined_thread_count,
      static_cast<long long>(
          timings.worker_to_application_latency.InMilliseconds()),
      static_cast<long long>(timings.sleeping_quit_latency.InMilliseconds()),
      static_cast<long long>(timings.idle_probe_elapsed.InMilliseconds()),
      static_cast<long long>(timings.idle_wake_latency.InMilliseconds()));
  std::fprintf(stdout, "%s:PASS\n", kPrefix);
  std::fflush(stdout);
  return 0;
}
