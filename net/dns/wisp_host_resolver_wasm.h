// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef NET_DNS_WISP_HOST_RESOLVER_WASM_H_
#define NET_DNS_WISP_HOST_RESOLVER_WASM_H_

#include <optional>
#include <string>

#include "net/base/net_export.h"

namespace net {

class IPAddress;

// Installs the system-resolver override used by the in-process Network
// Service. The override returns a bounded synthetic address for each hostname
// and leaves actual destination resolution to the configured WISP gateway.
// It never consults the browser host's DNS configuration.
NET_EXPORT void InstallWasmWispSystemDnsResolver();

// Drops the process-local hostname-to-synthetic-address registry after all
// NetworkContexts have been destroyed. This prevents one Network Service
// lifetime from retaining destinations for the next one.
NET_EXPORT void ResetWasmWispDestinationRegistry();

// Returns the hostname associated with a synthetic WISP address. A missing
// entry means that |address| was an IP literal or did not originate from the
// Wasm resolver and must be passed to WISP as that literal.
NET_EXPORT std::optional<std::string> GetWasmWispDestinationHostname(
    const IPAddress& address);

}  // namespace net

#endif  // NET_DNS_WISP_HOST_RESOLVER_WASM_H_
