// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "net/base/network_interfaces.h"
#include "net/base/platform_mime_util.h"

#include <string>
#include <unordered_set>

#include "base/files/file_path.h"
#include "net/base/mime_util.h"
#include "net/cert/internal/system_trust_store.h"
#include "net/http/url_security_manager.h"
#include "testing/gtest/include/gtest/gtest.h"
#include "url/scheme_host_port.h"

namespace net {

namespace {

class ExposedPlatformMimeUtil : public PlatformMimeUtil {
 public:
  using PlatformMimeUtil::GetPlatformExtensionsForMimeType;
  using PlatformMimeUtil::GetPlatformMimeTypeFromExtension;
  using PlatformMimeUtil::GetPlatformPreferredExtensionForMimeType;
};

TEST(NetPlatformWasmTest, ReportsNetworkInterfaceEnumerationUnavailable) {
  NetworkInterfaceList networks(1);

  EXPECT_FALSE(
      GetNetworkList(&networks, INCLUDE_HOST_SCOPE_VIRTUAL_INTERFACES));
  EXPECT_TRUE(networks.empty());
  EXPECT_TRUE(GetWifiSSID().empty());
}

TEST(NetPlatformWasmTest, PlatformMimeLookupsDoNotInventHostMappings) {
  ExposedPlatformMimeUtil platform_mime_util;

  std::string mime_type = "unchanged";
  EXPECT_FALSE(platform_mime_util.GetPlatformMimeTypeFromExtension(
      FILE_PATH_LITERAL("host-only"), &mime_type));
  EXPECT_EQ("unchanged", mime_type);

  base::FilePath::StringType extension = FILE_PATH_LITERAL("unchanged");
  EXPECT_FALSE(platform_mime_util.GetPlatformPreferredExtensionForMimeType(
      "application/x-host-only", &extension));
  EXPECT_EQ(FILE_PATH_LITERAL("unchanged"), extension);

  std::unordered_set<base::FilePath::StringType> extensions = {
      FILE_PATH_LITERAL("kept")};
  platform_mime_util.GetPlatformExtensionsForMimeType(
      "application/x-host-only", &extensions);
  EXPECT_EQ(1u, extensions.size());
  EXPECT_TRUE(extensions.contains(FILE_PATH_LITERAL("kept")));
}

TEST(NetPlatformWasmTest, BuiltInMimeMappingsRemainAvailable) {
  std::string mime_type;
  EXPECT_TRUE(GetMimeTypeFromExtension(FILE_PATH_LITERAL("wasm"), &mime_type));
  EXPECT_EQ("application/wasm", mime_type);

  base::FilePath::StringType extension;
  EXPECT_TRUE(
      GetPreferredExtensionForMimeType("application/wasm", &extension));
  EXPECT_EQ(FILE_PATH_LITERAL("wasm"), extension);
}

TEST(NetPlatformWasmTest, EmptySecurityAllowlistsDenyAmbientCredentials) {
  std::unique_ptr<URLSecurityManager> security_manager =
      URLSecurityManager::Create();
  ASSERT_TRUE(security_manager);

  const url::SchemeHostPort endpoint("https", "example.test", 443);
  EXPECT_FALSE(security_manager->CanUseDefaultCredentials(endpoint));
  EXPECT_FALSE(security_manager->CanDelegate(endpoint));
}

TEST(NetPlatformWasmTest, TrustStoreUsesOnlyChromiumRoots) {
  std::unique_ptr<SystemTrustStore> trust_store =
      CreateSslSystemTrustStoreChromeRoot(
          std::make_unique<TrustStoreChrome>());
  ASSERT_TRUE(trust_store);
  EXPECT_EQ(nullptr, trust_store->GetPlatformTrustStore());
}

}  // namespace

}  // namespace net
