// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "net/socket/tcp_socket_wasm.h"

#include <utility>

#include "base/memory/ptr_util.h"
#include "base/notimplemented.h"
#include "base/notreached.h"
#include "build/build_config.h"
#include "net/base/address_list.h"
#include "net/base/net_errors.h"
#include "net/log/net_log_event_type.h"
#include "net/log/net_log_source_type.h"
#include "net/socket/socket_performance_watcher.h"

#if !BUILDFLAG(IS_WASM)
#error "tcp_socket_wasm.cc must only be built for WebAssembly"
#endif

namespace net {

// static
std::unique_ptr<TCPSocketWasm> TCPSocketWasm::Create(
    std::unique_ptr<SocketPerformanceWatcher> socket_performance_watcher,
    NetLog* net_log,
    const NetLogSource& source) {
  return base::WrapUnique(new TCPSocketWasm(
      std::move(socket_performance_watcher), net_log, source));
}

// static
std::unique_ptr<TCPSocketWasm> TCPSocketWasm::Create(
    std::unique_ptr<SocketPerformanceWatcher> socket_performance_watcher,
    NetLogWithSource net_log_source) {
  return base::WrapUnique(new TCPSocketWasm(
      std::move(socket_performance_watcher), std::move(net_log_source)));
}

TCPSocketWasm::TCPSocketWasm(
    std::unique_ptr<SocketPerformanceWatcher> socket_performance_watcher,
    NetLog* net_log,
    const NetLogSource& source)
    : socket_performance_watcher_(std::move(socket_performance_watcher)),
      net_log_(NetLogWithSource::Make(net_log, NetLogSourceType::SOCKET)) {
  net_log_.BeginEventReferencingSource(NetLogEventType::SOCKET_ALIVE, source);
}

TCPSocketWasm::TCPSocketWasm(
    std::unique_ptr<SocketPerformanceWatcher> socket_performance_watcher,
    NetLogWithSource net_log_source)
    : socket_performance_watcher_(std::move(socket_performance_watcher)),
      net_log_(std::move(net_log_source)) {
  net_log_.BeginEvent(NetLogEventType::SOCKET_ALIVE);
}

TCPSocketWasm::~TCPSocketWasm() {
  if (logging_multiple_connect_attempts_)
    EndLoggingMultipleConnectAttempts(ERR_ABORTED);
  net_log_.EndEvent(NetLogEventType::SOCKET_ALIVE);
}

int TCPSocketWasm::Open(AddressFamily family) {
  return ERR_NOT_IMPLEMENTED;
}

int TCPSocketWasm::AdoptConnectedSocket(SocketDescriptor socket,
                                        const IPEndPoint& peer_address) {
  return ERR_NOT_IMPLEMENTED;
}

int TCPSocketWasm::AdoptUnconnectedSocket(SocketDescriptor socket) {
  return ERR_NOT_IMPLEMENTED;
}

int TCPSocketWasm::Bind(const IPEndPoint& address) {
  return ERR_NOT_IMPLEMENTED;
}

int TCPSocketWasm::Listen(int backlog) {
  return ERR_NOT_IMPLEMENTED;
}

int TCPSocketWasm::Accept(std::unique_ptr<TCPSocketWasm>* socket,
                          IPEndPoint* address,
                          CompletionOnceCallback callback) {
  return ERR_NOT_IMPLEMENTED;
}

int TCPSocketWasm::Connect(const IPEndPoint& address,
                           CompletionOnceCallback callback) {
  return ERR_NOT_IMPLEMENTED;
}

bool TCPSocketWasm::IsConnected() const {
  return false;
}

bool TCPSocketWasm::IsConnectedAndIdle() const {
  return false;
}

int TCPSocketWasm::Read(IOBuffer* buf,
                        int buf_len,
                        CompletionOnceCallback callback) {
  return ERR_NOT_IMPLEMENTED;
}

int TCPSocketWasm::ReadIfReady(IOBuffer* buf,
                               int buf_len,
                               CompletionOnceCallback callback) {
  return ERR_NOT_IMPLEMENTED;
}

int TCPSocketWasm::CancelReadIfReady() {
  return ERR_NOT_IMPLEMENTED;
}

int TCPSocketWasm::Write(
    IOBuffer* buf,
    int buf_len,
    CompletionOnceCallback callback,
    const NetworkTrafficAnnotationTag& traffic_annotation) {
  return ERR_NOT_IMPLEMENTED;
}

int TCPSocketWasm::GetLocalAddress(IPEndPoint* address) const {
  return ERR_NOT_IMPLEMENTED;
}

int TCPSocketWasm::GetPeerAddress(IPEndPoint* address) const {
  return ERR_NOT_IMPLEMENTED;
}

int TCPSocketWasm::SetDefaultOptionsForServer() {
  return ERR_NOT_IMPLEMENTED;
}

void TCPSocketWasm::SetDefaultOptionsForClient() {
  NOTIMPLEMENTED_LOG_ONCE();
}

int TCPSocketWasm::AllowAddressReuse() {
  return ERR_NOT_IMPLEMENTED;
}

int TCPSocketWasm::SetReceiveBufferSize(int32_t size) {
  return ERR_NOT_IMPLEMENTED;
}

int TCPSocketWasm::SetSendBufferSize(int32_t size) {
  return ERR_NOT_IMPLEMENTED;
}

bool TCPSocketWasm::SetKeepAlive(bool enable, int delay) {
  return false;
}

bool TCPSocketWasm::SetNoDelay(bool no_delay) {
  return false;
}

int TCPSocketWasm::SetIPv6Only(bool ipv6_only) {
  return ERR_NOT_IMPLEMENTED;
}

bool TCPSocketWasm::GetEstimatedRoundTripTime(
    base::TimeDelta* out_rtt) const {
  return false;
}

void TCPSocketWasm::Close() {}

bool TCPSocketWasm::IsValid() const {
  return false;
}

void TCPSocketWasm::DetachFromThread() {}

void TCPSocketWasm::StartLoggingMultipleConnectAttempts(
    const AddressList& addresses) {
  if (!logging_multiple_connect_attempts_) {
    logging_multiple_connect_attempts_ = true;
    net_log_.BeginEvent(NetLogEventType::TCP_CONNECT,
                        [&] { return addresses.NetLogParams(); });
  } else {
    NOTREACHED();
  }
}

void TCPSocketWasm::EndLoggingMultipleConnectAttempts(int net_error) {
  if (logging_multiple_connect_attempts_) {
    if (net_error == OK) {
      net_log_.EndEvent(NetLogEventType::TCP_CONNECT);
    } else {
      net_log_.EndEventWithNetErrorCode(NetLogEventType::TCP_CONNECT,
                                        net_error);
    }
    logging_multiple_connect_attempts_ = false;
  } else {
    NOTREACHED();
  }
}

SocketDescriptor TCPSocketWasm::ReleaseSocketDescriptorForTesting() {
  return kInvalidSocket;
}

SocketDescriptor TCPSocketWasm::SocketDescriptorForTesting() const {
  return kInvalidSocket;
}

void TCPSocketWasm::ApplySocketTag(const SocketTag& tag) {
  NOTIMPLEMENTED_LOG_ONCE();
}

int TCPSocketWasm::BindToNetwork(handles::NetworkHandle network) {
  return ERR_NOT_IMPLEMENTED;
}

}  // namespace net
