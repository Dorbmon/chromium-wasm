// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "net/dns/dns_config_service.h"

#include <memory>

namespace net {

// static
std::unique_ptr<DnsConfigService> DnsConfigService::CreateSystemService() {
  // The Wasm application cannot read or watch the host browser's system DNS
  // configuration. DNS transport is provided separately through WISP.
  return nullptr;
}

}  // namespace net
