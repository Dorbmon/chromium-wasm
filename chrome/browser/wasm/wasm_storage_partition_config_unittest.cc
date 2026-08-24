// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/files/file_path.h"
#include "build/build_config.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/storage_partition_config.h"
#include "content/public/browser/zoom_level_delegate.h"
#include "content/public/test/browser_task_environment.h"
#include "testing/gtest/include/gtest/gtest.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_storage_partition_config_unittests must only be built for WebAssembly"
#endif

namespace chrome {
namespace {

class ConfigTestBrowserContext : public content::BrowserContext {
 public:
  explicit ConfigTestBrowserContext(bool use_in_memory_default)
      : use_in_memory_default_(use_in_memory_default) {}
  ConfigTestBrowserContext(const ConfigTestBrowserContext&) = delete;
  ConfigTestBrowserContext& operator=(const ConfigTestBrowserContext&) =
      delete;
  ~ConfigTestBrowserContext() override { NotifyWillBeDestroyed(); }

  std::unique_ptr<content::ZoomLevelDelegate> CreateZoomLevelDelegate(
      const base::FilePath& partition_path) override {
    return nullptr;
  }
  base::FilePath GetPath() const override { return base::FilePath(); }
  bool IsOffTheRecord() override { return false; }
  bool ShouldUseInMemoryDefaultStoragePartition() override {
    return use_in_memory_default_;
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

 private:
  const bool use_in_memory_default_;
};

TEST(WasmStoragePartitionConfigTest, DefaultPolicyIsOptIn) {
  content::BrowserTaskEnvironment task_environment;
  ConfigTestBrowserContext browser_context(/*use_in_memory_default=*/false);

  const content::StoragePartitionConfig config =
      content::StoragePartitionConfig::CreateDefault(&browser_context);

  EXPECT_TRUE(config.is_default());
  EXPECT_FALSE(browser_context.IsOffTheRecord());
  EXPECT_FALSE(config.in_memory());
}

TEST(WasmStoragePartitionConfigTest,
     InMemoryDefaultDoesNotChangeBrowserContextIdentity) {
  content::BrowserTaskEnvironment task_environment;
  ConfigTestBrowserContext browser_context(/*use_in_memory_default=*/true);

  const content::StoragePartitionConfig config =
      content::StoragePartitionConfig::CreateDefault(&browser_context);

  EXPECT_TRUE(config.is_default());
  EXPECT_FALSE(browser_context.IsOffTheRecord());
  EXPECT_TRUE(config.in_memory());
}

TEST(WasmStoragePartitionConfigTest,
     ExplicitNonDefaultConfigKeepsCallersPersistenceChoice) {
  content::BrowserTaskEnvironment task_environment;
  ConfigTestBrowserContext browser_context(/*use_in_memory_default=*/true);

  const content::StoragePartitionConfig explicit_on_disk =
      content::StoragePartitionConfig::Create(
          &browser_context, "wasm-test", "explicit-on-disk",
          /*in_memory=*/false);
  const content::StoragePartitionConfig explicit_in_memory =
      content::StoragePartitionConfig::Create(
          &browser_context, "wasm-test", "explicit-in-memory",
          /*in_memory=*/true);

  EXPECT_FALSE(explicit_on_disk.is_default());
  EXPECT_FALSE(explicit_on_disk.in_memory());
  EXPECT_FALSE(explicit_in_memory.is_default());
  EXPECT_TRUE(explicit_in_memory.in_memory());
}

}  // namespace
}  // namespace chrome
