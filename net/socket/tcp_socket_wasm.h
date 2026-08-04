// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef NET_SOCKET_TCP_SOCKET_WASM_H_
#define NET_SOCKET_TCP_SOCKET_WASM_H_

#include <stdint.h>

#include <memory>

#include "base/memory/scoped_refptr.h"
#include "base/memory/weak_ptr.h"
#include "base/sequence_checker.h"
#include "base/timer/timer.h"
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

// A Chromium TCP socket backed by a multiplexed host-side WISP connection.
//
// The application sequence owns all socket state and callbacks. JavaScript
// WebSocket events never call into this object: synchronous proxied bridge
// calls are polled from this sequence instead. That keeps Chromium's socket
// callback affinity intact while the browser JavaScript main thread remains
// free to service Web APIs and canvas work.
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

  enum class State {
    kClosed,
    kOpen,
    kConnecting,
    kConnected,
    kEof,
    kFailed,
  };

  // Starts a short, sequence-affine poll only while a connect, read, or write
  // callback is outstanding. Host-side queues are bounded, so polling does
  // not create an unbounded pending work source.
  void SchedulePoll();
  void PollWispStream();
  bool HasPendingOperation() const;

  int ReadNow(IOBuffer* buf, int buf_len);
  int WriteNow(IOBuffer* buf, int buf_len);
  int StreamFailureResult();
  void UpdateStateFromTransport();

  void CompleteConnect(int result);
  void CompleteRead(int result);
  void CompleteReadIfReady(int result);
  void CompleteWrite(int result);

  void BeginConnectLogging(const IPEndPoint& address);
  void EndConnectLogging(int result);
  void LogReadResult(IOBuffer* buf, int result);
  void LogWriteResult(IOBuffer* buf, int result);

  std::unique_ptr<SocketPerformanceWatcher> socket_performance_watcher_;
  NetLogWithSource net_log_;
  bool logging_multiple_connect_attempts_ = false;

  State state_ = State::kClosed;
  AddressFamily family_ = ADDRESS_FAMILY_UNSPECIFIED;
  uint32_t stream_id_ = 0;
  int stream_error_ = 0;
  IPEndPoint peer_address_;
  bool connect_attempt_logged_ = false;

  CompletionOnceCallback connect_callback_;

  scoped_refptr<IOBuffer> read_buffer_;
  int read_buffer_length_ = 0;
  CompletionOnceCallback read_callback_;
  CompletionOnceCallback read_if_ready_callback_;

  scoped_refptr<IOBuffer> write_buffer_;
  int write_buffer_length_ = 0;
  CompletionOnceCallback write_callback_;

  base::OneShotTimer poll_timer_;
  SEQUENCE_CHECKER(sequence_checker_);
  base::WeakPtrFactory<TCPSocketWasm> weak_ptr_factory_{this};
};

}  // namespace net

#endif  // NET_SOCKET_TCP_SOCKET_WASM_H_
