// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <utility>

#include "content/browser/indexed_db/instance/bucket_context.h"

#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
#include "base/files/file_path.h"
#include "base/functional/bind.h"
#include "base/functional/callback_helpers.h"
#include "base/memory/ref_counted.h"
#include "base/test/test_mock_time_task_runner.h"
#include "components/services/storage/public/cpp/buckets/bucket_info.h"
#include "components/services/storage/public/cpp/buckets/constants.h"
#include "storage/browser/quota/quota_manager_proxy.h"
#include "testing/gtest/include/gtest/gtest.h"
#include "third_party/blink/public/common/storage_key/storage_key.h"

namespace content::indexed_db {
namespace {

class RejectNextPostTaskRunner final : public base::TestMockTimeTaskRunner {
 public:
  RejectNextPostTaskRunner() = default;
  RejectNextPostTaskRunner(const RejectNextPostTaskRunner&) = delete;
  RejectNextPostTaskRunner& operator=(const RejectNextPostTaskRunner&) =
      delete;

  void RejectNextPost() { reject_next_post_ = true; }
  int rejected_post_count() const { return rejected_post_count_; }

  bool PostDelayedTask(const base::Location& from_here,
                       base::OnceClosure task,
                       base::TimeDelta delay) override {
    if (reject_next_post_) {
      reject_next_post_ = false;
      ++rejected_post_count_;
      return false;
    }
    return base::TestMockTimeTaskRunner::PostDelayedTask(
        from_here, std::move(task), delay);
  }

 private:
  ~RejectNextPostTaskRunner() override = default;

  bool reject_next_post_ = false;
  int rejected_post_count_ = 0;
};

TEST(BucketContextShutdownReceiptTest,
     SealForContextShutdownWithholdsAckWhenFinalPostRejected) {
  auto task_runner = base::MakeRefCounted<RejectNextPostTaskRunner>();
  const blink::StorageKey storage_key =
      blink::StorageKey::CreateFromStringForTesting(
          "https://final-post-rejection.example");
  storage::BucketInfo bucket(
      storage::BucketId::FromUnsafeValue(1), storage_key,
      storage::kDefaultBucketName, base::Time(), /*quota=*/0,
      /*persistent=*/false, blink::mojom::BucketDurability::kRelaxed);
  bool destruction_step_ran = false;
  bool existing_after_destruction_ran = false;
  bool shutdown_ack_ran = false;

  // Static test hooks must not survive a fatal assertion into fixture teardown.
  // Declared after |task_runner|, so it clears before that runner is released.
  base::ScopedClosureRunner reset_destruction_step(base::BindOnce([] {
    BucketContext::InsertDestructionStepForTesting(base::OnceClosure());
  }));

  {
    // ScopedContext installs this runner as GetCurrentDefault(). It is declared
    // before the BucketContext, so it remains installed through its destructor.
    base::TestMockTimeTaskRunner::ScopedContext task_runner_context(
        task_runner);
    BucketContext::Delegate delegate;
    delegate.on_destroyed_after_destruction = base::BindOnce(
        [](bool* ran) { *ran = true; }, &existing_after_destruction_ran);
    BucketContext bucket_context(
        bucket, base::FilePath(), std::move(delegate),
        /*quota_manager_proxy=*/nullptr,
        mojo::PendingRemote<storage::mojom::BlobStorageContext>(),
        mojo::PendingRemote<storage::mojom::FileSystemAccessContext>());

    // This hook is immediately before BucketContext's only final
    // post-destruction acknowledgement. No earlier close post is affected.
    BucketContext::InsertDestructionStepForTesting(base::BindOnce(
        [](scoped_refptr<RejectNextPostTaskRunner> task_runner,
           bool* hook_ran) {
          *hook_ran = true;
          task_runner->RejectNextPost();
        },
        task_runner, &destruction_step_ran));
    bucket_context.SealForContextShutdown(
        base::BindOnce([](bool* ran) { *ran = true; }, &shutdown_ack_ran));
  }

  // The combined pre-existing delegate and shutdown barrier leg run only from
  // the final post-destruction task. A rejected post deliberately withholds
  // both, leaving FinishShutdownAndReply() unreachable in the owning context.
  task_runner->RunUntilIdle();
  EXPECT_TRUE(destruction_step_ran);
  EXPECT_EQ(1, task_runner->rejected_post_count());
  EXPECT_FALSE(existing_after_destruction_ran);
  EXPECT_FALSE(shutdown_ack_ran);
}

}  // namespace
}  // namespace content::indexed_db
#endif
