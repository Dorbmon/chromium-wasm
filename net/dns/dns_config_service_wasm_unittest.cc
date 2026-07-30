// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "net/dns/dns_config_service.h"

#include "testing/gtest/include/gtest/gtest.h"

namespace net {

TEST(DnsConfigServiceWasmTest, SystemServiceIsUnsupported) {
  EXPECT_EQ(nullptr, DnsConfigService::CreateSystemService());
}

}  // namespace net
