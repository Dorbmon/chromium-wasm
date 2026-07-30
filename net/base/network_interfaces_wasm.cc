// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "net/base/network_interfaces.h"

#include <string>

namespace net {

bool GetNetworkList(NetworkInterfaceList* networks, int policy) {
  if (!networks) {
    return false;
  }

  // The browser page does not expose its host's interfaces to WebAssembly.
  // Clear any caller-owned snapshot and report that enumeration is unavailable
  // so connection-type inference remains CONNECTION_UNKNOWN.
  networks->clear();
  return false;
}

std::string GetWifiSSID() {
  // The host page does not expose Wi-Fi association details.
  return std::string();
}

}  // namespace net
