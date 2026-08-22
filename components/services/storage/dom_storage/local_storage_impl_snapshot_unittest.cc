// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "components/services/storage/dom_storage/local_storage_impl.h"

#include <array>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "base/barrier_closure.h"
#include "base/files/file_path.h"
#include "base/functional/bind.h"
#include "base/functional/callback_helpers.h"
#include "base/run_loop.h"
#include "base/task/sequenced_task_runner.h"
#include "base/test/bind.h"
#include "base/test/scoped_feature_list.h"
#include "base/test/task_environment.h"
#include "base/threading/sequence_bound.h"
#include "components/services/storage/dom_storage/dom_storage_database.h"
#include "components/services/storage/dom_storage/features.h"
#include "components/services/storage/dom_storage/test_support/dom_storage_database_testing.h"
#include "components/services/storage/dom_storage/test_support/fake_dom_storage_database.h"
#include "components/services/storage/dom_storage/test_support/scoped_dom_storage_database_factory_for_testing.h"
#include "components/services/storage/dom_storage/test_support/storage_area_test_util.h"
#include "mojo/core/embedder/embedder.h"
#include "mojo/public/cpp/bindings/remote.h"
#include "testing/gtest/include/gtest/gtest.h"
#include "third_party/blink/public/common/storage_key/storage_key.h"
#include "third_party/blink/public/mojom/dom_storage/storage_area.mojom.h"

namespace storage {
namespace {

using SnapshotResult = LocalStorageImpl::ImmediateCommitSnapshotResult;
using ScopeOutcome = SnapshotResult::ScopeOutcome;
using BackingStore = SnapshotResult::BackingStore;
using AreaOutcome = StorageAreaImpl::ImmediateCommitSnapshotResult::Outcome;

std::vector<uint8_t> ToBytes(std::string_view value) {
  return std::vector<uint8_t>(value.begin(), value.end());
}

void InitializeMojoCoreForLocalStorageSnapshotTests() {
  static const bool initialized = [] {
    mojo::core::Init();
    return true;
  }();
  static_cast<void>(initialized);
}

const SnapshotResult::AreaResult* FindAreaResult(
    const SnapshotResult& result,
    const blink::StorageKey& storage_key) {
  for (const auto& area_result : result.area_results) {
    if (area_result.storage_key == storage_key) {
      return &area_result;
    }
  }
  return nullptr;
}

class LocalStorageImplSnapshotTest
    : public testing::Test,
      public testing::WithParamInterface<bool> {
 public:
  LocalStorageImplSnapshotTest() {
    feature_list_.InitWithFeatureStates(
        {{kDomStorageSqlite, GetParam()},
         {kDomStorageSqliteInMemory, GetParam()}});
    task_environment_ = std::make_unique<base::test::TaskEnvironment>();
    InitializeMojoCoreForLocalStorageSnapshotTests();
    storage_ = std::make_unique<LocalStorageImpl>(
        base::FilePath(), base::NullCallback(), mojo::NullReceiver());
  }

  LocalStorageImplSnapshotTest(const LocalStorageImplSnapshotTest&) = delete;
  LocalStorageImplSnapshotTest& operator=(
      const LocalStorageImplSnapshotTest&) = delete;

  ~LocalStorageImplSnapshotTest() override { DestroyStorage(); }

 protected:
  LocalStorageImpl* storage() {
    DCHECK(storage_);
    return storage_.get();
  }

  void Connect() {
    base::RunLoop loop;
    storage()->SetDatabaseOpenCallbackForTesting(loop.QuitClosure());
    loop.Run();
    ASSERT_NE(storage()->GetDatabaseForTesting(), nullptr);
  }

  mojo::Remote<blink::mojom::StorageArea> BindArea(
      const blink::StorageKey& storage_key) {
    mojo::Remote<blink::mojom::StorageArea> area;
    storage()->BindStorageArea(storage_key,
                               area.BindNewPipeAndPassReceiver());
    return area;
  }

  void ExpectStoredValue(const blink::StorageKey& storage_key,
                         std::string_view key,
                         std::string_view value) {
    std::map<DomStorageDatabase::Key, DomStorageDatabase::Value> entries;
    ReadMapKeyValuesSync(*storage()->GetDatabaseForTesting(),
                         DomStorageDatabase::MapLocator(storage_key),
                         &entries);
    EXPECT_EQ(entries, (std::map<DomStorageDatabase::Key,
                                 DomStorageDatabase::Value>{
                           {ToBytes(key), ToBytes(value)}}));
  }

  void DestroyStorage() {
    if (!storage_) {
      return;
    }

    scoped_refptr<base::SequencedTaskRunner> database_task_runner;
    if (storage()->GetDatabaseForTesting()) {
      base::RunLoop get_runner;
      storage()->GetDatabaseForTesting()->database().PostTaskWithThisObject(
          base::BindLambdaForTesting(
              [&](DomStorageDatabase*) {
                database_task_runner =
                    base::SequencedTaskRunner::GetCurrentDefault();
                get_runner.Quit();
              }));
      get_runner.Run();
    }

    storage_.reset();
    if (database_task_runner) {
      base::RunLoop flush_database;
      database_task_runner->PostTask(FROM_HERE, flush_database.QuitClosure());
      flush_database.Run();
    }
  }

  void RunUntilIdle() { task_environment_->RunUntilIdle(); }

 private:
  base::test::ScopedFeatureList feature_list_;
  std::unique_ptr<base::test::TaskEnvironment> task_environment_;
  std::unique_ptr<LocalStorageImpl> storage_;
};

INSTANTIATE_TEST_SUITE_P(
    /*no prefix*/,
    LocalStorageImplSnapshotTest,
    testing::Bool(),
    [](const testing::TestParamInfo<LocalStorageImplSnapshotTest::ParamType>&
           info) { return info.param ? "SQLite" : "LevelDB"; });

TEST_P(LocalStorageImplSnapshotTest,
       ImmediateCommitSnapshotDoesNotStartConnection) {
  EXPECT_EQ(storage()->GetDatabaseForTesting(), nullptr);

  std::optional<SnapshotResult> result;
  storage()->RequestImmediateCommitSnapshot(
      base::BindLambdaForTesting([&](SnapshotResult callback_result) {
        result.emplace(std::move(callback_result));
      }));

  EXPECT_FALSE(result.has_value());
  RunUntilIdle();

  ASSERT_TRUE(result.has_value());
  EXPECT_EQ(ScopeOutcome::kConnectionNotReady, result->scope_outcome);
  EXPECT_EQ(BackingStore::kUnavailable, result->backing_store);
  EXPECT_TRUE(result->area_results.empty());
  EXPECT_EQ(storage()->GetDatabaseForTesting(), nullptr);
}

TEST_P(LocalStorageImplSnapshotTest,
       ImmediateCommitSnapshotDoesNotWaitForConnection) {
  const blink::StorageKey storage_key =
      blink::StorageKey::CreateFromStringForTesting("https://opening.test");
  mojo::Remote<blink::mojom::StorageArea> area = BindArea(storage_key);
  ASSERT_TRUE(area.is_bound());

  std::optional<SnapshotResult> result;
  storage()->RequestImmediateCommitSnapshot(
      base::BindLambdaForTesting([&](SnapshotResult callback_result) {
        result.emplace(std::move(callback_result));
      }));

  EXPECT_FALSE(result.has_value());
  RunUntilIdle();

  ASSERT_TRUE(result.has_value());
  EXPECT_EQ(ScopeOutcome::kConnectionNotReady, result->scope_outcome);
  EXPECT_EQ(BackingStore::kUnavailable, result->backing_store);
  EXPECT_TRUE(result->area_results.empty());
}

TEST_P(LocalStorageImplSnapshotTest,
       ImmediateCommitSnapshotReportsNoMaterializedAreas) {
  Connect();

  std::optional<SnapshotResult> result;
  base::RunLoop loop;
  storage()->RequestImmediateCommitSnapshot(
      base::BindLambdaForTesting([&](SnapshotResult callback_result) {
        result.emplace(std::move(callback_result));
        loop.Quit();
      }));

  EXPECT_FALSE(result.has_value());
  loop.Run();

  ASSERT_TRUE(result.has_value());
  EXPECT_EQ(ScopeOutcome::kNoMaterializedAreas, result->scope_outcome);
  EXPECT_EQ(BackingStore::kInMemory, result->backing_store);
  EXPECT_TRUE(result->area_results.empty());
}

TEST_P(LocalStorageImplSnapshotTest,
       ImmediateCommitSnapshotReportsAllCurrentDirtyAreas) {
  Connect();
  const blink::StorageKey first_key =
      blink::StorageKey::CreateFromStringForTesting("https://first.test");
  const blink::StorageKey second_key =
      blink::StorageKey::CreateFromStringForTesting("https://second.test");
  mojo::Remote<blink::mojom::StorageArea> first_area = BindArea(first_key);
  mojo::Remote<blink::mojom::StorageArea> second_area = BindArea(second_key);

  ASSERT_TRUE(test::PutSync(first_area.get(), ToBytes("first-key"),
                            ToBytes("first-value"), std::nullopt,
                            test::MakeStorageAreaSource()));
  ASSERT_TRUE(test::PutSync(second_area.get(), ToBytes("second-key"),
                            ToBytes("second-value"), std::nullopt,
                            test::MakeStorageAreaSource()));

  std::optional<SnapshotResult> result;
  base::RunLoop loop;
  storage()->RequestImmediateCommitSnapshot(
      base::BindLambdaForTesting([&](SnapshotResult callback_result) {
        result.emplace(std::move(callback_result));
        loop.Quit();
      }));

  EXPECT_FALSE(result.has_value());
  loop.Run();

  ASSERT_TRUE(result.has_value());
  EXPECT_EQ(ScopeOutcome::kAllAreasReported, result->scope_outcome);
  EXPECT_EQ(BackingStore::kInMemory, result->backing_store);
  ASSERT_EQ(2u, result->area_results.size());
  const SnapshotResult::AreaResult* first = FindAreaResult(*result, first_key);
  const SnapshotResult::AreaResult* second =
      FindAreaResult(*result, second_key);
  ASSERT_NE(first, nullptr);
  ASSERT_NE(second, nullptr);
  EXPECT_EQ(AreaOutcome::kCommittedMapUpdate, first->result.outcome);
  EXPECT_TRUE(first->result.status.ok());
  EXPECT_EQ(AreaOutcome::kCommittedMapUpdate, second->result.outcome);
  EXPECT_TRUE(second->result.status.ok());
  ExpectStoredValue(first_key, "first-key", "first-value");
  ExpectStoredValue(second_key, "second-key", "second-value");
}

TEST_P(LocalStorageImplSnapshotTest,
       ImmediateCommitSnapshotDistinguishesCleanAndDirtyAreas) {
  Connect();
  const blink::StorageKey clean_key =
      blink::StorageKey::CreateFromStringForTesting("https://clean.test");
  const blink::StorageKey dirty_key =
      blink::StorageKey::CreateFromStringForTesting("https://dirty.test");
  mojo::Remote<blink::mojom::StorageArea> clean_area = BindArea(clean_key);
  mojo::Remote<blink::mojom::StorageArea> dirty_area = BindArea(dirty_key);

  ASSERT_TRUE(test::PutSync(dirty_area.get(), ToBytes("dirty-key"),
                            ToBytes("dirty-value"), std::nullopt,
                            test::MakeStorageAreaSource()));

  std::optional<SnapshotResult> result;
  base::RunLoop loop;
  storage()->RequestImmediateCommitSnapshot(
      base::BindLambdaForTesting([&](SnapshotResult callback_result) {
        result.emplace(std::move(callback_result));
        loop.Quit();
      }));
  loop.Run();

  ASSERT_TRUE(result.has_value());
  EXPECT_EQ(ScopeOutcome::kAllAreasReported, result->scope_outcome);
  ASSERT_EQ(2u, result->area_results.size());
  const SnapshotResult::AreaResult* clean = FindAreaResult(*result, clean_key);
  const SnapshotResult::AreaResult* dirty = FindAreaResult(*result, dirty_key);
  ASSERT_NE(clean, nullptr);
  ASSERT_NE(dirty, nullptr);
  EXPECT_EQ(AreaOutcome::kNoPendingMapUpdate, clean->result.outcome);
  EXPECT_TRUE(clean->result.status.IsNotFound());
  EXPECT_EQ(AreaOutcome::kCommittedMapUpdate, dirty->result.outcome);
  EXPECT_TRUE(dirty->result.status.ok());
  ExpectStoredValue(dirty_key, "dirty-key", "dirty-value");
}

TEST_P(LocalStorageImplSnapshotTest,
       ImmediateCommitSnapshotSharesActiveAreaOperation) {
  Connect();
  const blink::StorageKey storage_key =
      blink::StorageKey::CreateFromStringForTesting("https://shared.test");
  mojo::Remote<blink::mojom::StorageArea> area = BindArea(storage_key);
  ASSERT_TRUE(test::PutSync(area.get(), ToBytes("shared-key"),
                            ToBytes("shared-value"), std::nullopt,
                            test::MakeStorageAreaSource()));

  std::array<std::optional<SnapshotResult>, 2> results;
  base::RunLoop loop;
  base::RepeatingClosure done =
      base::BarrierClosure(results.size(), loop.QuitClosure());
  for (size_t index = 0; index < results.size(); ++index) {
    storage()->RequestImmediateCommitSnapshot(
        base::BindLambdaForTesting([&, index](SnapshotResult callback_result) {
          results[index].emplace(std::move(callback_result));
          done.Run();
        }));
  }

  EXPECT_FALSE(results[0].has_value());
  EXPECT_FALSE(results[1].has_value());
  loop.Run();

  for (const auto& result : results) {
    ASSERT_TRUE(result.has_value());
    EXPECT_EQ(ScopeOutcome::kAllAreasReported, result->scope_outcome);
    ASSERT_EQ(1u, result->area_results.size());
    EXPECT_EQ(AreaOutcome::kCommittedMapUpdate,
              result->area_results[0].result.outcome);
    EXPECT_TRUE(result->area_results[0].result.status.ok());
  }
}

TEST_P(LocalStorageImplSnapshotTest,
       ImmediateCommitSnapshotSurvivesLocalStorageDestruction) {
  Connect();
  const blink::StorageKey storage_key =
      blink::StorageKey::CreateFromStringForTesting("https://cancel.test");
  storage()->ForceFakeOpenStorageAreaForTesting(storage_key);
  storage()->PutValueForTesting(storage_key, ToBytes("cancel-key"),
                                ToBytes("cancel-value"), base::DoNothing());

  int callback_count = 0;
  std::optional<SnapshotResult> result;
  storage()->RequestImmediateCommitSnapshot(
      base::BindLambdaForTesting([&](SnapshotResult callback_result) {
        ++callback_count;
        result.emplace(std::move(callback_result));
      }));
  DestroyStorage();
  RunUntilIdle();

  EXPECT_EQ(1, callback_count);
  ASSERT_TRUE(result.has_value());
  EXPECT_EQ(ScopeOutcome::kAllAreasReported, result->scope_outcome);
  ASSERT_EQ(1u, result->area_results.size());
  EXPECT_EQ(AreaOutcome::kCancelled, result->area_results[0].result.outcome);
  EXPECT_FALSE(result->area_results[0].result.status.ok());
}

TEST_P(LocalStorageImplSnapshotTest,
       ImmediateCommitSnapshotPreservesAreaCommitFailure) {
  ScopedDomStorageDatabaseFactoryForTesting scoped_factory(
      base::BindLambdaForTesting(
          [](StorageType,
             bool,
             scoped_refptr<base::SequencedTaskRunner> task_runner)
              -> base::SequenceBound<DomStorageDatabase> {
            auto database = base::SequenceBound<FakeDomStorageDatabase>(
                std::move(task_runner), DbStatus::OK());
            database.AsyncCall(&FakeDomStorageDatabase::SetUpdateMapsStatus)
                .WithArgs(DbStatus::IOError("test failure"));
            return database;
          }));
  Connect();
  const blink::StorageKey storage_key =
      blink::StorageKey::CreateFromStringForTesting("https://failure.test");
  mojo::Remote<blink::mojom::StorageArea> area = BindArea(storage_key);
  ASSERT_TRUE(test::PutSync(area.get(), ToBytes("failure-key"),
                            ToBytes("failure-value"), std::nullopt,
                            test::MakeStorageAreaSource()));

  std::optional<SnapshotResult> result;
  base::RunLoop loop;
  storage()->RequestImmediateCommitSnapshot(
      base::BindLambdaForTesting([&](SnapshotResult callback_result) {
        result.emplace(std::move(callback_result));
        loop.Quit();
      }));
  loop.Run();

  ASSERT_TRUE(result.has_value());
  EXPECT_EQ(ScopeOutcome::kAllAreasReported, result->scope_outcome);
  ASSERT_EQ(1u, result->area_results.size());
  EXPECT_EQ(AreaOutcome::kCommitFailed, result->area_results[0].result.outcome);
  EXPECT_FALSE(result->area_results[0].result.status.ok());
}

}  // namespace
}  // namespace storage
