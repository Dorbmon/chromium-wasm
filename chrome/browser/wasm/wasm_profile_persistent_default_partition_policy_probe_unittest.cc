// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_persistent_default_partition_policy_probe.h"

#include "base/files/file_path.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/zoom_level_delegate.h"
#include "content/public/test/browser_task_environment.h"
#include "testing/gtest/include/gtest/gtest.h"

namespace chrome {

namespace {

// This is deliberately the smallest local BrowserContext used only to prove
// StoragePartitionConfig::CreateDefault() consults the policy virtual. It owns
// no StoragePartition and this test never calls any partition accessor.
class PolicyProbeBrowserContext : public content::BrowserContext {
 public:
  PolicyProbeBrowserContext() = default;
  PolicyProbeBrowserContext(const PolicyProbeBrowserContext&) = delete;
  PolicyProbeBrowserContext& operator=(const PolicyProbeBrowserContext&) =
      delete;
  ~PolicyProbeBrowserContext() override { NotifyWillBeDestroyed(); }

  std::unique_ptr<content::ZoomLevelDelegate> CreateZoomLevelDelegate(
      const base::FilePath& /*partition_path*/) override {
    return nullptr;
  }
  base::FilePath GetPath() const override { return base::FilePath(); }
  bool IsOffTheRecord() override { return false; }
  bool ShouldUseInMemoryDefaultStoragePartition() override {
    ++policy_query_count_;
    return false;
  }
  content::DownloadManagerDelegate* GetDownloadManagerDelegate() override {
    return nullptr;
  }
  content::BrowserPluginGuestManager* GetGuestManager() override {
    return nullptr;
  }
  storage::SpecialStoragePolicy* GetSpecialStoragePolicy() override {
    return nullptr;
  }
  content::PlatformNotificationService* GetPlatformNotificationService()
      override {
    return nullptr;
  }
  content::PushMessagingService* GetPushMessagingService() override {
    return nullptr;
  }
  content::StorageNotificationService* GetStorageNotificationService()
      override {
    return nullptr;
  }
  content::SSLHostStateDelegate* GetSSLHostStateDelegate() override {
    return nullptr;
  }
  content::PermissionControllerDelegate* GetPermissionControllerDelegate()
      override {
    return nullptr;
  }
  content::ReduceAcceptLanguageControllerDelegate*
  GetReduceAcceptLanguageControllerDelegate() override {
    return nullptr;
  }
  content::ClientHintsControllerDelegate* GetClientHintsControllerDelegate()
      override {
    return nullptr;
  }
  content::BackgroundFetchDelegate* GetBackgroundFetchDelegate() override {
    return nullptr;
  }
  content::BackgroundSyncController* GetBackgroundSyncController() override {
    return nullptr;
  }
  content::BrowsingDataRemoverDelegate* GetBrowsingDataRemoverDelegate()
      override {
    return nullptr;
  }

  int policy_query_count() const { return policy_query_count_; }

 private:
  int policy_query_count_ = 0;
};

}  // namespace

TEST(WasmPersistentDefaultPartitionPolicyProbeTest,
     AcceptsOnlyDefaultNonInMemoryProperties) {
  EXPECT_TRUE(
      IsWasmPersistentDefaultPartitionConfigProperties(/*is_default=*/true,
                                                        /*in_memory=*/false));
  EXPECT_FALSE(
      IsWasmPersistentDefaultPartitionConfigProperties(/*is_default=*/true,
                                                        /*in_memory=*/true));
  EXPECT_FALSE(
      IsWasmPersistentDefaultPartitionConfigProperties(/*is_default=*/false,
                                                        /*in_memory=*/false));
  EXPECT_FALSE(
      IsWasmPersistentDefaultPartitionConfigProperties(/*is_default=*/false,
                                                        /*in_memory=*/true));
}

TEST(WasmPersistentDefaultPartitionPolicyProbeTest,
     RecognizesCreateDefaultFromMinimalBrowserContextWithoutAPartition) {
  content::BrowserTaskEnvironment task_environment;
  PolicyProbeBrowserContext browser_context;

  const content::StoragePartitionConfig config =
      content::StoragePartitionConfig::CreateDefault(&browser_context);

  EXPECT_TRUE(IsWasmPersistentDefaultPartitionConfig(config));
  EXPECT_EQ(1, browser_context.policy_query_count());
}

}  // namespace chrome
