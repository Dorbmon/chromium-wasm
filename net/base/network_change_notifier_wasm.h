// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef NET_BASE_NETWORK_CHANGE_NOTIFIER_WASM_H_
#define NET_BASE_NETWORK_CHANGE_NOTIFIER_WASM_H_

#include "base/sequence_checker.h"
#include "base/synchronization/lock.h"
#include "base/thread_annotations.h"
#include "base/timer/timer.h"
#include "net/base/net_export.h"
#include "net/base/network_change_notifier.h"

namespace net {

// A deliberately narrow browser-host connectivity hint for WebAssembly.
//
// The JavaScript host owns `navigator.onLine` and its online/offline events.
// Chromium polls one versioned scalar through a synchronous Emscripten proxy,
// so browser-main DOM events never directly invoke Chromium callbacks. The
// scalar only distinguishes offline from an otherwise unknown connection: it
// does not identify an interface, a connection technology, DNS configuration,
// WISP state, or reachability to a particular origin.
class NET_EXPORT_PRIVATE NetworkChangeNotifierWasm final
    : public NetworkChangeNotifier {
 public:
  NetworkChangeNotifierWasm();
  NetworkChangeNotifierWasm(const NetworkChangeNotifierWasm&) = delete;
  NetworkChangeNotifierWasm& operator=(const NetworkChangeNotifierWasm&) =
      delete;
  ~NetworkChangeNotifierWasm() override;

 private:
  enum class HostConnectionState : int {
    kUnknown = 0,
    kOffline = 1,
    kOnline = 2,
  };

  static NetworkChangeCalculatorParams NetworkChangeCalculatorParamsWasm();
  static HostConnectionState HostConnectionStateFromBridge(int state);
  static ConnectionType ConnectionTypeForHostState(HostConnectionState state);

  // Runs only on the Chromium sequence which creates and destroys this
  // notifier. Query methods remain cheap and thread-safe for their callers.
  void PollHostConnectionState();

  // NetworkChangeNotifier:
  ConnectionCost GetCurrentConnectionCost() override;
  ConnectionType GetCurrentConnectionType() const override;
  ConnectionSubtype GetCurrentConnectionSubtype() const override;
  void GetCurrentMaxBandwidthAndConnectionType(
      double* max_bandwidth_mbps,
      ConnectionType* connection_type) const override;

  mutable base::Lock connection_type_lock_;
  ConnectionType connection_type_ GUARDED_BY(connection_type_lock_) =
      CONNECTION_UNKNOWN;

  base::RepeatingTimer poll_timer_;
  SEQUENCE_CHECKER(sequence_checker_);
};

}  // namespace net

#endif  // NET_BASE_NETWORK_CHANGE_NOTIFIER_WASM_H_
