// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/time/time.h"

#include "base/synchronization/waitable_event.h"
#include "base/threading/platform_thread.h"
#include "testing/gtest/include/gtest/gtest.h"

namespace base {
namespace {

constexpr int kPthreadHandoffIterations = 4096;

// Exchanges timestamps with the test thread through automatic-reset events.
// WaitableEvent::Wait() happens after the corresponding Signal(), so each
// timestamp comparison below has a real cross-pthread happens-before edge.
class PthreadTimeTicksHandoff final : public PlatformThread::Delegate {
 public:
  explicit PthreadTimeTicksHandoff(int iterations)
      : iterations_(iterations),
        worker_may_sample_(WaitableEvent::ResetPolicy::AUTOMATIC,
                           WaitableEvent::InitialState::NOT_SIGNALED),
        worker_sampled_(WaitableEvent::ResetPolicy::AUTOMATIC,
                        WaitableEvent::InitialState::NOT_SIGNALED),
        worker_may_sample_after_main_(
            WaitableEvent::ResetPolicy::AUTOMATIC,
            WaitableEvent::InitialState::NOT_SIGNALED),
        worker_sampled_after_main_(
            WaitableEvent::ResetPolicy::AUTOMATIC,
            WaitableEvent::InitialState::NOT_SIGNALED) {}

  PthreadTimeTicksHandoff(const PthreadTimeTicksHandoff&) = delete;
  PthreadTimeTicksHandoff& operator=(const PthreadTimeTicksHandoff&) = delete;

  void RequestWorkerSample() { worker_may_sample_.Signal(); }

  TimeTicks WaitForWorkerSample() {
    worker_sampled_.Wait();
    return worker_sample_;
  }

  void RequestWorkerSampleAfterMain() {
    worker_may_sample_after_main_.Signal();
  }

  TimeTicks WaitForWorkerSampleAfterMain() {
    worker_sampled_after_main_.Wait();
    return worker_sample_after_main_;
  }

 private:
  void ThreadMain() override {
    for (int iteration = 0; iteration < iterations_; ++iteration) {
      worker_may_sample_.Wait();
      worker_sample_ = TimeTicks::Now();
      worker_sampled_.Signal();

      worker_may_sample_after_main_.Wait();
      worker_sample_after_main_ = TimeTicks::Now();
      worker_sampled_after_main_.Signal();
    }
  }

  const int iterations_;
  WaitableEvent worker_may_sample_;
  WaitableEvent worker_sampled_;
  WaitableEvent worker_may_sample_after_main_;
  WaitableEvent worker_sampled_after_main_;
  TimeTicks worker_sample_;
  TimeTicks worker_sample_after_main_;
};

TEST(TimeWasmTest, TimeTicksRemainOrderedAcrossPthreadHandoffs) {
  PthreadTimeTicksHandoff handoff(kPthreadHandoffIterations);
  PlatformThreadHandle worker;
  ASSERT_TRUE(PlatformThread::Create(0, &handoff, &worker));

  for (int iteration = 0; iteration < kPthreadHandoffIterations;
       ++iteration) {
    handoff.RequestWorkerSample();
    const TimeTicks worker_sample = handoff.WaitForWorkerSample();
    const TimeTicks main_sample = TimeTicks::Now();
    EXPECT_LE(worker_sample, main_sample) << "iteration " << iteration;

    const TimeTicks main_sample_before_worker = TimeTicks::Now();
    handoff.RequestWorkerSampleAfterMain();
    const TimeTicks worker_sample_after_main =
        handoff.WaitForWorkerSampleAfterMain();
    EXPECT_LE(main_sample_before_worker, worker_sample_after_main)
        << "iteration " << iteration;
  }

  PlatformThread::Join(worker);
}

}  // namespace
}  // namespace base
