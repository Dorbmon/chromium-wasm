// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef NET_SOCKET_UDP_SOCKET_WASM_H_
#define NET_SOCKET_UDP_SOCKET_WASM_H_

#include <stdint.h>

#include "net/base/address_family.h"
#include "net/base/completion_once_callback.h"
#include "net/base/ip_endpoint.h"
#include "net/base/net_export.h"
#include "net/base/network_handle.h"
#include "net/log/net_log_with_source.h"
#include "net/socket/datagram_socket.h"
#include "net/socket/diff_serv_code_point.h"
#include "net/socket/socket_descriptor.h"
#include "net/traffic_annotation/network_traffic_annotation.h"

namespace net {

class IPAddress;
class IOBuffer;
class IPEndPoint;
class NetLog;
struct NetLogSource;
class SocketTag;

// M3 has no UDP transport. This class keeps the platform-neutral socket graph
// type-complete while rejecting every operation that would create or use a
// datagram socket.
class NET_EXPORT UDPSocketWasm {
 public:
  UDPSocketWasm(DatagramSocket::BindType bind_type,
                net::NetLog* net_log,
                const NetLogSource& source);
  UDPSocketWasm(DatagramSocket::BindType bind_type,
                NetLogWithSource source_net_log);

  UDPSocketWasm(const UDPSocketWasm&) = delete;
  UDPSocketWasm& operator=(const UDPSocketWasm&) = delete;

  ~UDPSocketWasm();

  int Open(AddressFamily address_family);
  int BindToNetwork(handles::NetworkHandle network);
  int Connect(const IPEndPoint& address);
  int Bind(const IPEndPoint& address);
  void Close();

  int GetPeerAddress(IPEndPoint* address) const;
  int GetLocalAddress(IPEndPoint* address) const;

  int Read(IOBuffer* buf, int buf_len, CompletionOnceCallback callback);
  int Write(IOBuffer* buf,
            int buf_len,
            CompletionOnceCallback callback,
            const NetworkTrafficAnnotationTag& traffic_annotation);
  int RecvFrom(IOBuffer* buf,
               int buf_len,
               IPEndPoint* address,
               CompletionOnceCallback callback);
  int SendTo(IOBuffer* buf,
             int buf_len,
             const IPEndPoint& address,
             CompletionOnceCallback callback);

  int SetReceiveBufferSize(int32_t size);
  int SetSendBufferSize(int32_t size);
  int SetDoNotFragment();
  int SetRecvTos();
  void SetMsgConfirm(bool confirm);

  bool is_connected() const { return false; }
  const NetLogWithSource& NetLog() const { return net_log_; }

  int AllowAddressReuse();
  int SetBroadcast(bool broadcast);
  int AllowAddressSharingForMulticast();
  int JoinGroup(const IPAddress& group_address) const;
  int LeaveGroup(const IPAddress& group_address) const;
  int JoinSourceGroup(const IPAddress& group_address,
                      const IPAddress& source_address) const;
  int LeaveSourceGroup(const IPAddress& group_address,
                       const IPAddress& source_address) const;
  int SetMulticastInterface(uint32_t interface_index);
  int SetMulticastTimeToLive(int time_to_live);
  int SetMulticastLoopbackMode(bool loopback);
  int SetDiffServCodePoint(DiffServCodePoint dscp);
  int SetTos(DiffServCodePoint dscp, EcnCodePoint ecn);
  int SetIPv6Only(bool ipv6_only);

  SocketDescriptor SocketDescriptorForTesting() const {
    return kInvalidSocket;
  }

  void DetachFromThread();
  void ApplySocketTag(const SocketTag& tag);
  int AdoptOpenedSocket(AddressFamily address_family, SocketDescriptor socket);

  uint32_t get_multicast_interface_for_testing() const { return 0; }
  bool get_msg_confirm_for_testing() const { return false; }
  bool get_experimental_recv_optimization_enabled_for_testing() const {
    return false;
  }

  DscpAndEcn GetLastTos() const {
    return {.dscp = DSCP_DEFAULT, .ecn = ECN_DEFAULT};
  }

 private:
  NetLogWithSource net_log_;
};

}  // namespace net

#endif  // NET_SOCKET_UDP_SOCKET_WASM_H_
