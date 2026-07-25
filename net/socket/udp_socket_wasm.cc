// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "net/socket/udp_socket_wasm.h"

#include <utility>

#include "base/notimplemented.h"
#include "build/build_config.h"
#include "net/base/net_errors.h"
#include "net/log/net_log_event_type.h"
#include "net/log/net_log_source_type.h"

#if !BUILDFLAG(IS_WASM)
#error "udp_socket_wasm.cc must only be built for WebAssembly"
#endif

namespace net {

UDPSocketWasm::UDPSocketWasm(DatagramSocket::BindType bind_type,
                             net::NetLog* net_log,
                             const NetLogSource& source)
    : net_log_(
          NetLogWithSource::Make(net_log, NetLogSourceType::UDP_SOCKET)) {
  net_log_.BeginEventReferencingSource(NetLogEventType::SOCKET_ALIVE, source);
}

UDPSocketWasm::UDPSocketWasm(DatagramSocket::BindType bind_type,
                             NetLogWithSource source_net_log)
    : net_log_(std::move(source_net_log)) {
  net_log_.BeginEventReferencingSource(NetLogEventType::SOCKET_ALIVE,
                                       net_log_.source());
}

UDPSocketWasm::~UDPSocketWasm() {
  net_log_.EndEvent(NetLogEventType::SOCKET_ALIVE);
}

int UDPSocketWasm::Open(AddressFamily address_family) {
  return ERR_NOT_IMPLEMENTED;
}

int UDPSocketWasm::BindToNetwork(handles::NetworkHandle network) {
  return ERR_NOT_IMPLEMENTED;
}

int UDPSocketWasm::Connect(const IPEndPoint& address) {
  return ERR_NOT_IMPLEMENTED;
}

int UDPSocketWasm::Bind(const IPEndPoint& address) {
  return ERR_NOT_IMPLEMENTED;
}

void UDPSocketWasm::Close() {}

int UDPSocketWasm::GetPeerAddress(IPEndPoint* address) const {
  return ERR_NOT_IMPLEMENTED;
}

int UDPSocketWasm::GetLocalAddress(IPEndPoint* address) const {
  return ERR_NOT_IMPLEMENTED;
}

int UDPSocketWasm::Read(IOBuffer* buf,
                        int buf_len,
                        CompletionOnceCallback callback) {
  return ERR_NOT_IMPLEMENTED;
}

int UDPSocketWasm::Write(
    IOBuffer* buf,
    int buf_len,
    CompletionOnceCallback callback,
    const NetworkTrafficAnnotationTag& traffic_annotation) {
  return ERR_NOT_IMPLEMENTED;
}

int UDPSocketWasm::RecvFrom(IOBuffer* buf,
                            int buf_len,
                            IPEndPoint* address,
                            CompletionOnceCallback callback) {
  return ERR_NOT_IMPLEMENTED;
}

int UDPSocketWasm::SendTo(IOBuffer* buf,
                          int buf_len,
                          const IPEndPoint& address,
                          CompletionOnceCallback callback) {
  return ERR_NOT_IMPLEMENTED;
}

int UDPSocketWasm::SetReceiveBufferSize(int32_t size) {
  return ERR_NOT_IMPLEMENTED;
}

int UDPSocketWasm::SetSendBufferSize(int32_t size) {
  return ERR_NOT_IMPLEMENTED;
}

int UDPSocketWasm::SetDoNotFragment() {
  return ERR_NOT_IMPLEMENTED;
}

int UDPSocketWasm::SetRecvTos() {
  return ERR_NOT_IMPLEMENTED;
}

void UDPSocketWasm::SetMsgConfirm(bool confirm) {
  NOTIMPLEMENTED_LOG_ONCE();
}

int UDPSocketWasm::AllowAddressReuse() {
  return ERR_NOT_IMPLEMENTED;
}

int UDPSocketWasm::SetBroadcast(bool broadcast) {
  return ERR_NOT_IMPLEMENTED;
}

int UDPSocketWasm::AllowAddressSharingForMulticast() {
  return ERR_NOT_IMPLEMENTED;
}

int UDPSocketWasm::JoinGroup(const IPAddress& group_address) const {
  return ERR_NOT_IMPLEMENTED;
}

int UDPSocketWasm::LeaveGroup(const IPAddress& group_address) const {
  return ERR_NOT_IMPLEMENTED;
}

int UDPSocketWasm::JoinSourceGroup(const IPAddress& group_address,
                                   const IPAddress& source_address) const {
  return ERR_NOT_IMPLEMENTED;
}

int UDPSocketWasm::LeaveSourceGroup(const IPAddress& group_address,
                                    const IPAddress& source_address) const {
  return ERR_NOT_IMPLEMENTED;
}

int UDPSocketWasm::SetMulticastInterface(uint32_t interface_index) {
  return ERR_NOT_IMPLEMENTED;
}

int UDPSocketWasm::SetMulticastTimeToLive(int time_to_live) {
  return ERR_NOT_IMPLEMENTED;
}

int UDPSocketWasm::SetMulticastLoopbackMode(bool loopback) {
  return ERR_NOT_IMPLEMENTED;
}

int UDPSocketWasm::SetDiffServCodePoint(DiffServCodePoint dscp) {
  return ERR_NOT_IMPLEMENTED;
}

int UDPSocketWasm::SetTos(DiffServCodePoint dscp, EcnCodePoint ecn) {
  return ERR_NOT_IMPLEMENTED;
}

int UDPSocketWasm::SetIPv6Only(bool ipv6_only) {
  return ERR_NOT_IMPLEMENTED;
}

void UDPSocketWasm::DetachFromThread() {}

void UDPSocketWasm::ApplySocketTag(const SocketTag& tag) {
  NOTIMPLEMENTED_LOG_ONCE();
}

int UDPSocketWasm::AdoptOpenedSocket(AddressFamily address_family,
                                     SocketDescriptor socket) {
  return ERR_NOT_IMPLEMENTED;
}

}  // namespace net
