// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_prefs_fence_controller.h"

#include <memory>
#include <optional>
#include <utility>

#include "base/functional/bind.h"
#include "base/task/sequenced_task_runner.h"
#include "base/test/task_environment.h"
#include "build/build_config.h"
#include "testing/gtest/include/gtest/gtest.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_profile_prefs_fence_controller_unittests must only be built for WebAssembly"
#endif

namespace {

using Controller = WasmProfilePrefsFenceController;

class CapturingFenceStarter {
 public:
  explicit CapturingFenceStarter(bool accepts) : accepts_(accepts) {}
  CapturingFenceStarter(const CapturingFenceStarter&) = delete;
  CapturingFenceStarter& operator=(const CapturingFenceStarter&) = delete;
  ~CapturingFenceStarter() = default;

  bool Start(Controller::FenceCompletionCallback completion) {
    if (!accepts_) {
      return false;
    }
    completion_ = std::move(completion);
    return true;
  }

  bool has_completion() const { return completion_.has_value(); }

  void Complete(bool success) {
    ASSERT_TRUE(completion_.has_value());
    Controller::FenceCompletionCallback completion = std::move(*completion_);
    completion_.reset();
    std::move(completion).Run(success);
  }

 private:
  const bool accepts_;
  std::optional<Controller::FenceCompletionCallback> completion_;
};

class WasmProfilePrefsFenceControllerTest : public testing::Test {
 protected:
  std::unique_ptr<Controller> CreateController() {
    return std::make_unique<Controller>(
        base::SequencedTaskRunner::GetCurrentDefault());
  }

  base::test::TaskEnvironment task_environment_{
      base::test::TaskEnvironment::MainThreadType::UI};
};

void RecordCompletionOnOwnerSequence(
    scoped_refptr<base::SequencedTaskRunner> owner_task_runner,
    bool* completed,
    std::optional<bool>* result,
    bool success) {
  EXPECT_TRUE(owner_task_runner->RunsTasksInCurrentSequence());
  *completed = true;
  *result = success;
}

TEST_F(WasmProfilePrefsFenceControllerTest,
       SuccessfulFenceCompletesOnOwnerSequence) {
  std::unique_ptr<Controller> controller = CreateController();
  CapturingFenceStarter starter(/*accepts=*/true);
  bool completed = false;
  std::optional<bool> result;
  scoped_refptr<base::SequencedTaskRunner> owner_task_runner =
      base::SequencedTaskRunner::GetCurrentDefault();

  controller->Begin(
      base::BindOnce(&CapturingFenceStarter::Start, base::Unretained(&starter)),
      base::BindOnce(&RecordCompletionOnOwnerSequence,
                     std::move(owner_task_runner), &completed, &result));
  EXPECT_TRUE(controller->IsPending());
  EXPECT_TRUE(starter.has_completion());
  task_environment_.RunUntilIdle();
  EXPECT_FALSE(completed);

  starter.Complete(true);
  task_environment_.RunUntilIdle();

  EXPECT_TRUE(completed);
  ASSERT_TRUE(result.has_value());
  EXPECT_TRUE(*result);
  EXPECT_TRUE(controller->HasCompleted());
  EXPECT_TRUE(controller->DidSucceed());
}

TEST_F(WasmProfilePrefsFenceControllerTest,
       FailedFenceCompletesOnOwnerSequence) {
  std::unique_ptr<Controller> controller = CreateController();
  CapturingFenceStarter starter(/*accepts=*/true);
  bool completed = false;
  std::optional<bool> result;
  scoped_refptr<base::SequencedTaskRunner> owner_task_runner =
      base::SequencedTaskRunner::GetCurrentDefault();

  controller->Begin(
      base::BindOnce(&CapturingFenceStarter::Start, base::Unretained(&starter)),
      base::BindOnce(&RecordCompletionOnOwnerSequence,
                     std::move(owner_task_runner), &completed, &result));
  starter.Complete(false);
  task_environment_.RunUntilIdle();

  EXPECT_TRUE(completed);
  ASSERT_TRUE(result.has_value());
  EXPECT_FALSE(*result);
  EXPECT_TRUE(controller->HasCompleted());
  EXPECT_FALSE(controller->DidSucceed());
}

TEST_F(WasmProfilePrefsFenceControllerTest,
       RejectedStarterCompletesAsFailure) {
  std::unique_ptr<Controller> controller = CreateController();
  CapturingFenceStarter starter(/*accepts=*/false);
  bool completed = false;
  std::optional<bool> result;
  scoped_refptr<base::SequencedTaskRunner> owner_task_runner =
      base::SequencedTaskRunner::GetCurrentDefault();

  controller->Begin(
      base::BindOnce(&CapturingFenceStarter::Start, base::Unretained(&starter)),
      base::BindOnce(&RecordCompletionOnOwnerSequence,
                     std::move(owner_task_runner), &completed, &result));
  task_environment_.RunUntilIdle();

  EXPECT_TRUE(completed);
  ASSERT_TRUE(result.has_value());
  EXPECT_FALSE(*result);
  EXPECT_TRUE(controller->HasCompleted());
  EXPECT_FALSE(controller->DidSucceed());
}

TEST_F(WasmProfilePrefsFenceControllerTest,
       ProfileOwnerAbandonmentIsReportedAsFailure) {
  std::unique_ptr<Controller> controller = CreateController();
  CapturingFenceStarter starter(/*accepts=*/true);
  bool completed = false;
  std::optional<bool> result;
  scoped_refptr<base::SequencedTaskRunner> owner_task_runner =
      base::SequencedTaskRunner::GetCurrentDefault();

  controller->Begin(
      base::BindOnce(&CapturingFenceStarter::Start, base::Unretained(&starter)),
      base::BindOnce(&RecordCompletionOnOwnerSequence,
                     std::move(owner_task_runner), &completed, &result));
  ASSERT_TRUE(starter.has_completion());

  // A profile owner that cannot retain its pending fence must explicitly
  // classify it as failure. The late success must remain inert.
  controller->Cancel();
  task_environment_.RunUntilIdle();

  EXPECT_TRUE(completed);
  ASSERT_TRUE(result.has_value());
  EXPECT_FALSE(*result);
  EXPECT_TRUE(controller->HasCompleted());
  EXPECT_FALSE(controller->DidSucceed());

  starter.Complete(true);
  task_environment_.RunUntilIdle();
  EXPECT_FALSE(controller->DidSucceed());
}

}  // namespace
