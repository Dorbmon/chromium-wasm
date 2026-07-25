// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef NET_SOCKET_TCP_SOCKET_WASM_H_
#define NET_SOCKET_TCP_SOCKET_WASM_H_

#include <stdint.h>

#include <memory>

#include "net/base/address_family.h"
#include "net/base/completion_once_callback.h"
#include "net/base/ip_endpoint.h"
#include "net/base/net_export.h"
#include "net/base/network_handle.h"
#include "net/log/net_log_with_source.h"
#include "net/socket/socket_descriptor.h"
#include "net/socket/socket_performance_watcher.h"
#include "net/traffic_annotation/network_traffic_annotation.h"

namespace base {
class TimeDelta;
}

namespace net {

class AddressList;
class IOBuffer;
class NetLog;
struct NetLogSource;
class SocketTag;

// M3 has no TCP transport. This class keeps the platform-neutral socket graph
// type-complete while rejecting every operation that would create or use a
// native TCP socket. M5 replaces this boundary with a WISP stream transport.
class NET_EXPORT TCPSocketWasm {
 public:
  static std::unique_ptr<TCPSocketWasm> Create(
      std::unique_ptr<SocketPerformanceWatcher> socket_performance_watcher,
      NetLog* net_log,
      const NetLogSource& source);
  static std::unique_ptr<TCPSocketWasm> Create(
      std::unique_ptr<SocketPerformanceWatcher> socket_performance_watcher,
      NetLogWithSource net_log_source);

  TCPSocketWasm(const TCPSocketWasm&) = delete;
  TCPSocketWasm& operator=(const TCPSocketWasm&) = delete;

  ~TCPSocketWasm();

  int Open(AddressFamily family);
  int AdoptConnectedSocket(SocketDescriptor socket,
                           const IPEndPoint& peer_address);
  int AdoptUnconnectedSocket(SocketDescriptor socket);
  int Bind(const IPEndPoint& address);
  int Listen(int backlog);
  int Accept(std::unique_ptr<TCPSocketWasm>* socket,
             IPEndPoint* address,
             CompletionOnceCallback callback);
  int Connect(const IPEndPoint& address, CompletionOnceCallback callback);

  bool IsConnected() const;
  bool IsConnectedAndIdle() const;

  int Read(IOBuffer* buf, int buf_len, CompletionOnceCallback callback);
  int ReadIfReady(IOBuffer* buf,
                  int buf_len,
                  CompletionOnceCallback callback);
  int CancelReadIfReady();
  int Write(IOBuffer* buf,
            int buf_len,
            CompletionOnceCallback callback,
            const NetworkTrafficAnnotationTag& traffic_annotation);

  int GetLocalAddress(IPEndPoint* address) const;
  int GetPeerAddress(IPEndPoint* address) const;

  int SetDefaultOptionsForServer();
  void SetDefaultOptionsForClient();
  int AllowAddressReuse();
  int SetReceiveBufferSize(int32_t size);
  int SetSendBufferSize(int32_t size);
  bool SetKeepAlive(bool enable, int delay);
  bool SetNoDelay(bool no_delay);
  int SetIPv6Only(bool ipv6_only);
  [[nodiscard]] bool GetEstimatedRoundTripTime(
      base::TimeDelta* out_rtt) const;

  void Close();
  bool IsValid() const;
  void DetachFromThread();

  void StartLoggingMultipleConnectAttempts(const AddressList& addresses);
  void EndLoggingMultipleConnectAttempts(int net_error);

  const NetLogWithSource& net_log() const { return net_log_; }

  SocketDescriptor ReleaseSocketDescriptorForTesting();
  SocketDescriptor SocketDescriptorForTesting() const;

  void ApplySocketTag(const SocketTag& tag);

  SocketPerformanceWatcher* socket_performance_watcher() const {
    return socket_performance_watcher_.get();
  }

  int BindToNetwork(handles::NetworkHandle network);

 private:
  TCPSocketWasm(
      std::unique_ptr<SocketPerformanceWatcher> socket_performance_watcher,
      NetLog* net_log,
      const NetLogSource& source);
  TCPSocketWasm(
      std::unique_ptr<SocketPerformanceWatcher> socket_performance_watcher,
      NetLogWithSource net_log_source);

  std::unique_ptr<SocketPerformanceWatcher> socket_performance_watcher_;
  NetLogWithSource net_log_;
  bool logging_multiple_connect_attempts_ = false;
};

}  // namespace net

#endif  // NET_SOCKET_TCP_SOCKET_WASM_H_
