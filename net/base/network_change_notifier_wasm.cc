// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "net/base/network_change_notifier_wasm.h"

#include <limits>

#include "base/functional/bind.h"
#include "base/time/time.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "network_change_notifier_wasm.cc must only be built for WebAssembly"
#endif

namespace {

// Keep this in sync with network_change_notifier_wasm.js. The ABI deliberately
// carries only one advisory host state and no network metadata.
constexpr int kHostBridgeVersion = 1;
constexpr base::TimeDelta kHostStatePollInterval = base::Milliseconds(500);

extern "C" int chromium_wasm_network_change_notifier_state(
    int bridge_version);

}  // namespace

namespace net {

NetworkChangeNotifierWasm::NetworkChangeNotifierWasm()
    : NetworkChangeNotifier(NetworkChangeCalculatorParamsWasm()) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);

  // Do not synchronously query in the constructor. The generic initial type is
  // CONNECTION_NONE, but that would overstate what the Web host can know. Keep
  // UNKNOWN until the first scheduled browser-host observation instead.
  poll_timer_.Start(
      FROM_HERE, kHostStatePollInterval,
      base::BindRepeating(&NetworkChangeNotifierWasm::PollHostConnectionState,
                          base::Unretained(this)));
}

NetworkChangeNotifierWasm::~NetworkChangeNotifierWasm() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  poll_timer_.Stop();
  ClearGlobalPointer();
}

// static
NetworkChangeNotifier::NetworkChangeCalculatorParams
NetworkChangeNotifierWasm::NetworkChangeCalculatorParamsWasm() {
  NetworkChangeCalculatorParams params;
  // DOM online/offline is only advisory. Debounce its browser-host state just
  // as other platforms debounce link-state notifications.
  params.connection_type_offline_delay_ = base::Milliseconds(500);
  params.connection_type_online_delay_ = base::Milliseconds(500);
  return params;
}

// static
NetworkChangeNotifierWasm::HostConnectionState
NetworkChangeNotifierWasm::HostConnectionStateFromBridge(int state) {
  switch (state) {
    case static_cast<int>(HostConnectionState::kOffline):
      return HostConnectionState::kOffline;
    case static_cast<int>(HostConnectionState::kOnline):
      return HostConnectionState::kOnline;
    case static_cast<int>(HostConnectionState::kUnknown):
    default:
      return HostConnectionState::kUnknown;
  }
}

// static
NetworkChangeNotifier::ConnectionType
NetworkChangeNotifierWasm::ConnectionTypeForHostState(
    HostConnectionState state) {
  // `navigator.onLine` does not identify a transport or prove reachability.
  // Its online state is therefore represented only as CONNECTION_UNKNOWN.
  return state == HostConnectionState::kOffline ? CONNECTION_NONE
                                                : CONNECTION_UNKNOWN;
}

void NetworkChangeNotifierWasm::PollHostConnectionState() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);

  const ConnectionType next_connection_type = ConnectionTypeForHostState(
      HostConnectionStateFromBridge(
          chromium_wasm_network_change_notifier_state(kHostBridgeVersion)));
  {
    base::AutoLock lock(connection_type_lock_);
    if (connection_type_ == next_connection_type)
      return;
    connection_type_ = next_connection_type;
  }

  // Do not manufacture IP-address, DNS, interface, connection-cost, or WISP
  // notifications. The two standard notifications below carry only the narrow
  // offline/unknown transition and let NetworkChangeCalculator preserve normal
  // destructive-before-constructive observer ordering.
  NotifyObserversOfConnectionTypeChange();
  NotifyObserversOfMaxBandwidthChange(
      next_connection_type == CONNECTION_NONE
          ? 0.0
          : std::numeric_limits<double>::infinity(),
      next_connection_type);
}

NetworkChangeNotifier::ConnectionCost
NetworkChangeNotifierWasm::GetCurrentConnectionCost() {
  // The browser host exposes no metering information through this ABI.
  return CONNECTION_COST_UNKNOWN;
}

NetworkChangeNotifier::ConnectionType
NetworkChangeNotifierWasm::GetCurrentConnectionType() const {
  base::AutoLock lock(connection_type_lock_);
  return connection_type_;
}

NetworkChangeNotifier::ConnectionSubtype
NetworkChangeNotifierWasm::GetCurrentConnectionSubtype() const {
  // This notifier never claims a network technology.
  return SUBTYPE_UNKNOWN;
}

void NetworkChangeNotifierWasm::GetCurrentMaxBandwidthAndConnectionType(
    double* max_bandwidth_mbps,
    ConnectionType* connection_type) const {
  base::AutoLock lock(connection_type_lock_);
  *connection_type = connection_type_;
  *max_bandwidth_mbps =
      connection_type_ == CONNECTION_NONE
          ? 0.0
          : std::numeric_limits<double>::infinity();
}

}  // namespace net
