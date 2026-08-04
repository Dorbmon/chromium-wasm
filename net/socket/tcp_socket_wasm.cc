// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "net/socket/tcp_socket_wasm.h"

#include <utility>

#include "base/functional/bind.h"
#include "base/memory/ptr_util.h"
#include "base/notreached.h"
#include "base/rand_util.h"
#include "base/time/time.h"
#include "base/trace_event/trace_event.h"
#include "build/build_config.h"
#include "net/base/address_list.h"
#include "net/base/io_buffer.h"
#include "net/base/net_errors.h"
#include "net/base/network_activity_monitor.h"
#include "net/log/net_log_event_type.h"
#include "net/log/net_log_source_type.h"
#include "net/socket/socket_net_log_params.h"
#include "net/socket/wisp_transport_wasm.h"

#if !BUILDFLAG(IS_WASM)
#error "tcp_socket_wasm.cc must only be built for WebAssembly"
#endif

namespace net {

namespace {

constexpr base::TimeDelta kWispPollInterval = base::Milliseconds(10);
constexpr uint8_t kWispCloseReasonVoluntary = 0x02;

bool IsUsableFamily(AddressFamily family) {
  return family == ADDRESS_FAMILY_IPV4 || family == ADDRESS_FAMILY_IPV6;
}

}  // namespace

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
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  Close();
  if (logging_multiple_connect_attempts_)
    EndLoggingMultipleConnectAttempts(ERR_ABORTED);
  net_log_.EndEvent(NetLogEventType::SOCKET_ALIVE);
}

int TCPSocketWasm::Open(AddressFamily family) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  DCHECK_EQ(state_, State::kClosed);

  if (state_ != State::kClosed || !IsUsableFamily(family))
    return ERR_ADDRESS_INVALID;

  family_ = family;
  state_ = State::kOpen;
  return OK;
}

int TCPSocketWasm::AdoptConnectedSocket(SocketDescriptor socket,
                                        const IPEndPoint& peer_address) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return ERR_NOT_IMPLEMENTED;
}

int TCPSocketWasm::AdoptUnconnectedSocket(SocketDescriptor socket) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return ERR_NOT_IMPLEMENTED;
}

int TCPSocketWasm::Bind(const IPEndPoint& address) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return ERR_NOT_IMPLEMENTED;
}

int TCPSocketWasm::Listen(int backlog) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return ERR_NOT_IMPLEMENTED;
}

int TCPSocketWasm::Accept(std::unique_ptr<TCPSocketWasm>* socket,
                          IPEndPoint* address,
                          CompletionOnceCallback callback) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return ERR_NOT_IMPLEMENTED;
}

int TCPSocketWasm::Connect(const IPEndPoint& address,
                           CompletionOnceCallback callback) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  DCHECK(!callback.is_null());

  if (callback.is_null())
    return ERR_INVALID_ARGUMENT;
  if (state_ == State::kConnected || state_ == State::kEof)
    return ERR_SOCKET_IS_CONNECTED;
  if (state_ != State::kOpen)
    return ERR_SOCKET_NOT_CONNECTED;
  if (!address.address().IsValid() || address.GetFamily() != family_ ||
      address.port() == 0) {
    return ERR_ADDRESS_INVALID;
  }
  if (!IsWasmWispTransportConfigured())
    return ERR_NOT_IMPLEMENTED;

  BeginConnectLogging(address);

  // WISP stream identifiers are client-chosen, nonzero uint32 values. The
  // bridge rejects collisions, so retry a few statistically independent IDs
  // instead of treating a collision as a successful connection.
  bool opened = false;
  for (int attempt = 0; attempt < 4 && !opened; ++attempt) {
    stream_id_ = static_cast<uint32_t>(base::RandUint64());
    if (stream_id_ == 0)
      continue;
    opened = OpenWasmWispStream(stream_id_, address.ToStringWithoutPort(),
                                address.port());
  }
  if (!opened) {
    stream_id_ = 0;
    EndConnectLogging(ERR_CONNECTION_FAILED);
    return ERR_CONNECTION_FAILED;
  }

  peer_address_ = address;
  stream_error_ = OK;
  state_ = State::kConnecting;
  UpdateStateFromTransport();
  if (state_ == State::kConnected) {
    EndConnectLogging(OK);
    return OK;
  }
  if (state_ == State::kFailed || state_ == State::kEof) {
    const int result = StreamFailureResult();
    EndConnectLogging(result);
    return result;
  }

  connect_callback_ = std::move(callback);
  SchedulePoll();
  return ERR_IO_PENDING;
}

bool TCPSocketWasm::IsConnected() const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return state_ == State::kConnected && stream_id_ != 0 &&
         GetWasmWispStreamState(stream_id_) == WasmWispStreamState::kOpen;
}

bool TCPSocketWasm::IsConnectedAndIdle() const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (!IsConnected() || !connect_callback_.is_null() ||
      !read_callback_.is_null() || !read_if_ready_callback_.is_null() ||
      !write_callback_.is_null()) {
    return false;
  }
  return GetWasmWispStreamAvailableBytes(stream_id_) == 0;
}

int TCPSocketWasm::Read(IOBuffer* buf,
                        int buf_len,
                        CompletionOnceCallback callback) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  DCHECK(!callback.is_null());
  DCHECK(read_callback_.is_null());
  DCHECK(read_if_ready_callback_.is_null());

  if (!buf || buf_len <= 0 || callback.is_null())
    return ERR_INVALID_ARGUMENT;
  if (!read_callback_.is_null() || !read_if_ready_callback_.is_null())
    return ERR_IO_PENDING;

  const int result = ReadNow(buf, buf_len);
  if (result != ERR_IO_PENDING)
    return result;

  read_buffer_ = base::WrapRefCounted(buf);
  read_buffer_length_ = buf_len;
  read_callback_ = std::move(callback);
  SchedulePoll();
  return ERR_IO_PENDING;
}

int TCPSocketWasm::ReadIfReady(IOBuffer* buf,
                               int buf_len,
                               CompletionOnceCallback callback) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  DCHECK(!callback.is_null());
  DCHECK(read_callback_.is_null());
  DCHECK(read_if_ready_callback_.is_null());

  if (!buf || buf_len <= 0 || callback.is_null())
    return ERR_INVALID_ARGUMENT;
  if (!read_callback_.is_null() || !read_if_ready_callback_.is_null())
    return ERR_IO_PENDING;

  const int result = ReadNow(buf, buf_len);
  if (result != ERR_IO_PENDING)
    return result;

  // The ReadIfReady contract deliberately does not retain |buf|. The
  // callback is a readiness notification; the caller retries and owns its
  // buffer when it gets that notification.
  read_if_ready_callback_ = std::move(callback);
  SchedulePoll();
  return ERR_IO_PENDING;
}

int TCPSocketWasm::CancelReadIfReady() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  DCHECK(read_callback_.is_null());
  DCHECK(!read_if_ready_callback_.is_null());

  if (!read_callback_.is_null() || read_if_ready_callback_.is_null())
    return ERR_INVALID_ARGUMENT;
  read_if_ready_callback_.Reset();
  return OK;
}

int TCPSocketWasm::Write(
    IOBuffer* buf,
    int buf_len,
    CompletionOnceCallback callback,
    const NetworkTrafficAnnotationTag& traffic_annotation) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  DCHECK(!callback.is_null());
  DCHECK(write_callback_.is_null());

  if (!buf || buf_len <= 0 || callback.is_null())
    return ERR_INVALID_ARGUMENT;
  if (!write_callback_.is_null())
    return ERR_IO_PENDING;

  const int result = WriteNow(buf, buf_len);
  if (result != ERR_IO_PENDING)
    return result;

  write_buffer_ = base::WrapRefCounted(buf);
  write_buffer_length_ = buf_len;
  write_callback_ = std::move(callback);
  SchedulePoll();
  return ERR_IO_PENDING;
}

int TCPSocketWasm::GetLocalAddress(IPEndPoint* address) const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  DCHECK(address);
  if (!IsValid())
    return ERR_SOCKET_NOT_CONNECTED;

  // The browser-side WebSocket is the only host-visible transport endpoint;
  // it is not the TCP endpoint WISP opened for this Chromium socket. Do not
  // fabricate a local address.
  return ERR_NOT_IMPLEMENTED;
}

int TCPSocketWasm::GetPeerAddress(IPEndPoint* address) const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  DCHECK(address);
  if (!IsConnected())
    return ERR_SOCKET_NOT_CONNECTED;
  *address = peer_address_;
  return OK;
}

int TCPSocketWasm::SetDefaultOptionsForServer() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return ERR_NOT_IMPLEMENTED;
}

void TCPSocketWasm::SetDefaultOptionsForClient() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  // TCP_NODELAY and SO_KEEPALIVE configure a kernel TCP socket. This object
  // owns no such socket, and WISP makes no equivalent promise.
}

int TCPSocketWasm::AllowAddressReuse() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return ERR_NOT_IMPLEMENTED;
}

int TCPSocketWasm::SetReceiveBufferSize(int32_t size) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return ERR_NOT_IMPLEMENTED;
}

int TCPSocketWasm::SetSendBufferSize(int32_t size) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return ERR_NOT_IMPLEMENTED;
}

bool TCPSocketWasm::SetKeepAlive(bool enable, int delay) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return false;
}

bool TCPSocketWasm::SetNoDelay(bool no_delay) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return false;
}

int TCPSocketWasm::SetIPv6Only(bool ipv6_only) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return ERR_NOT_IMPLEMENTED;
}

bool TCPSocketWasm::GetEstimatedRoundTripTime(
    base::TimeDelta* out_rtt) const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  DCHECK(out_rtt);
  return false;
}

void TCPSocketWasm::Close() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  TRACE_EVENT("base", perfetto::StaticString{"CloseSocketTCP"});

  poll_timer_.Stop();
  weak_ptr_factory_.InvalidateWeakPtrs();
  if (connect_attempt_logged_)
    EndConnectLogging(ERR_ABORTED);
  if (stream_id_ != 0)
    CloseWasmWispStream(stream_id_, kWispCloseReasonVoluntary);

  connect_callback_.Reset();
  read_callback_.Reset();
  read_if_ready_callback_.Reset();
  write_callback_.Reset();
  read_buffer_.reset();
  write_buffer_.reset();
  read_buffer_length_ = 0;
  write_buffer_length_ = 0;
  stream_id_ = 0;
  stream_error_ = OK;
  peer_address_ = IPEndPoint();
  family_ = ADDRESS_FAMILY_UNSPECIFIED;
  state_ = State::kClosed;
}

bool TCPSocketWasm::IsValid() const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return state_ != State::kClosed;
}

void TCPSocketWasm::DetachFromThread() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  DCHECK(!HasPendingOperation());
  DCHECK(!poll_timer_.IsRunning());
  DETACH_FROM_SEQUENCE(sequence_checker_);
}

void TCPSocketWasm::StartLoggingMultipleConnectAttempts(
    const AddressList& addresses) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (!logging_multiple_connect_attempts_) {
    logging_multiple_connect_attempts_ = true;
    net_log_.BeginEvent(NetLogEventType::TCP_CONNECT,
                        [&] { return addresses.NetLogParams(); });
  } else {
    NOTREACHED();
  }
}

void TCPSocketWasm::EndLoggingMultipleConnectAttempts(int net_error) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
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
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  DCHECK(!HasPendingOperation());
  Close();
  return kInvalidSocket;
}

SocketDescriptor TCPSocketWasm::SocketDescriptorForTesting() const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return kInvalidSocket;
}

void TCPSocketWasm::ApplySocketTag(const SocketTag& tag) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  // Socket tags apply to an operating-system socket descriptor. The WISP
  // bridge cannot silently pretend to apply one to its shared WebSocket.
}

int TCPSocketWasm::BindToNetwork(handles::NetworkHandle network) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return ERR_NOT_IMPLEMENTED;
}

void TCPSocketWasm::SchedulePoll() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (!HasPendingOperation() || poll_timer_.IsRunning())
    return;

  poll_timer_.Start(
      FROM_HERE, kWispPollInterval,
      base::BindOnce(&TCPSocketWasm::PollWispStream,
                     weak_ptr_factory_.GetWeakPtr()));
}

void TCPSocketWasm::PollWispStream() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);

  if (state_ == State::kClosed)
    return;

  UpdateStateFromTransport();
  if (!connect_callback_.is_null()) {
    if (state_ == State::kConnected) {
      base::WeakPtr<TCPSocketWasm> self = weak_ptr_factory_.GetWeakPtr();
      CompleteConnect(OK);
      if (!self)
        return;
    } else if (state_ == State::kFailed || state_ == State::kEof) {
      const int result = StreamFailureResult();
      base::WeakPtr<TCPSocketWasm> self = weak_ptr_factory_.GetWeakPtr();
      CompleteConnect(result);
      if (!self)
        return;
    }
  }

  if (!read_callback_.is_null()) {
    const int result = ReadNow(read_buffer_.get(), read_buffer_length_);
    if (result != ERR_IO_PENDING) {
      base::WeakPtr<TCPSocketWasm> self = weak_ptr_factory_.GetWeakPtr();
      CompleteRead(result);
      if (!self)
        return;
    }
  }

  if (!read_if_ready_callback_.is_null()) {
    const int available = GetWasmWispStreamAvailableBytes(stream_id_);
    int result = ERR_IO_PENDING;
    if (available > 0 || state_ == State::kEof) {
      result = OK;
    } else if (available < 0 || state_ == State::kFailed) {
      result = StreamFailureResult();
    }
    if (result != ERR_IO_PENDING) {
      base::WeakPtr<TCPSocketWasm> self = weak_ptr_factory_.GetWeakPtr();
      CompleteReadIfReady(result);
      if (!self)
        return;
    }
  }

  if (!write_callback_.is_null()) {
    const int result = WriteNow(write_buffer_.get(), write_buffer_length_);
    if (result != ERR_IO_PENDING) {
      base::WeakPtr<TCPSocketWasm> self = weak_ptr_factory_.GetWeakPtr();
      CompleteWrite(result);
      if (!self)
        return;
    }
  }

  SchedulePoll();
}

bool TCPSocketWasm::HasPendingOperation() const {
  return !connect_callback_.is_null() || !read_callback_.is_null() ||
         !read_if_ready_callback_.is_null() || !write_callback_.is_null();
}

int TCPSocketWasm::ReadNow(IOBuffer* buf, int buf_len) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  DCHECK(buf);
  DCHECK_GT(buf_len, 0);

  if (state_ == State::kClosed || state_ == State::kOpen)
    return ERR_SOCKET_NOT_CONNECTED;

  UpdateStateFromTransport();
  if (state_ == State::kConnecting)
    return ERR_IO_PENDING;
  if (state_ == State::kFailed) {
    const int result = StreamFailureResult();
    LogReadResult(buf, result);
    return result;
  }

  const int available = GetWasmWispStreamAvailableBytes(stream_id_);
  if (available < 0) {
    state_ = State::kFailed;
    stream_error_ = ERR_FAILED;
    LogReadResult(buf, stream_error_);
    return stream_error_;
  }
  if (available == 0) {
    if (state_ == State::kEof)
      return OK;
    return ERR_IO_PENDING;
  }

  const int result = ReadWasmWispStream(stream_id_, buf->bytes(), buf_len);
  if (result > 0) {
    LogReadResult(buf, result);
    return result;
  }
  if (result < 0) {
    state_ = State::kFailed;
    stream_error_ = result;
    LogReadResult(buf, result);
    return result;
  }

  UpdateStateFromTransport();
  if (state_ == State::kEof)
    return OK;
  if (state_ == State::kFailed) {
    const int failure = StreamFailureResult();
    LogReadResult(buf, failure);
    return failure;
  }
  return ERR_IO_PENDING;
}

int TCPSocketWasm::WriteNow(IOBuffer* buf, int buf_len) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  DCHECK(buf);
  DCHECK_GT(buf_len, 0);

  if (state_ == State::kClosed || state_ == State::kOpen ||
      state_ == State::kConnecting) {
    return ERR_SOCKET_NOT_CONNECTED;
  }

  UpdateStateFromTransport();
  if (state_ == State::kEof)
    return ERR_CONNECTION_CLOSED;
  if (state_ == State::kFailed) {
    const int result = StreamFailureResult();
    LogWriteResult(buf, result);
    return result;
  }

  const int result = WriteWasmWispStream(stream_id_, buf->bytes(), buf_len);
  if (result > 0) {
    LogWriteResult(buf, result);
    return result;
  }
  if (result < 0) {
    state_ = State::kFailed;
    stream_error_ = result;
    LogWriteResult(buf, result);
    return result;
  }

  UpdateStateFromTransport();
  if (state_ == State::kEof)
    return ERR_CONNECTION_CLOSED;
  if (state_ == State::kFailed) {
    const int failure = StreamFailureResult();
    LogWriteResult(buf, failure);
    return failure;
  }
  return ERR_IO_PENDING;
}

int TCPSocketWasm::StreamFailureResult() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (state_ == State::kEof)
    return ERR_CONNECTION_CLOSED;
  if (state_ != State::kFailed)
    return ERR_IO_PENDING;
  return stream_error_ < 0 ? stream_error_ : ERR_CONNECTION_FAILED;
}

void TCPSocketWasm::UpdateStateFromTransport() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (stream_id_ == 0 || state_ == State::kClosed)
    return;

  switch (GetWasmWispStreamState(stream_id_)) {
    case WasmWispStreamState::kConnecting:
      return;
    case WasmWispStreamState::kOpen:
      if (state_ == State::kConnecting)
        state_ = State::kConnected;
      return;
    case WasmWispStreamState::kEof:
      state_ = State::kEof;
      stream_error_ = OK;
      return;
    case WasmWispStreamState::kFailed:
      state_ = State::kFailed;
      stream_error_ = GetWasmWispStreamError(stream_id_);
      if (stream_error_ >= 0)
        stream_error_ = ERR_CONNECTION_FAILED;
      return;
    case WasmWispStreamState::kUnavailable:
      state_ = State::kFailed;
      stream_error_ = ERR_CONNECTION_FAILED;
      return;
  }
}

void TCPSocketWasm::CompleteConnect(int result) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  DCHECK_NE(result, ERR_IO_PENDING);
  EndConnectLogging(result);
  if (!connect_callback_.is_null())
    std::move(connect_callback_).Run(result);
}

void TCPSocketWasm::CompleteRead(int result) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  DCHECK_NE(result, ERR_IO_PENDING);
  scoped_refptr<IOBuffer> buffer = std::move(read_buffer_);
  read_buffer_length_ = 0;
  if (!read_callback_.is_null())
    std::move(read_callback_).Run(result);
}

void TCPSocketWasm::CompleteReadIfReady(int result) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  DCHECK_NE(result, ERR_IO_PENDING);
  if (!read_if_ready_callback_.is_null())
    std::move(read_if_ready_callback_).Run(result);
}

void TCPSocketWasm::CompleteWrite(int result) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  DCHECK_NE(result, ERR_IO_PENDING);
  scoped_refptr<IOBuffer> buffer = std::move(write_buffer_);
  write_buffer_length_ = 0;
  if (!write_callback_.is_null())
    std::move(write_callback_).Run(result);
}

void TCPSocketWasm::BeginConnectLogging(const IPEndPoint& address) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (!logging_multiple_connect_attempts_) {
    net_log_.BeginEvent(NetLogEventType::TCP_CONNECT,
                        [&] { return AddressList(address).NetLogParams(); });
  }
  net_log_.BeginEvent(NetLogEventType::TCP_CONNECT_ATTEMPT, [&] {
    return CreateNetLogIPEndPointParams(&address);
  });
  connect_attempt_logged_ = true;
}

void TCPSocketWasm::EndConnectLogging(int result) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (!connect_attempt_logged_)
    return;

  if (result == OK) {
    net_log_.EndEvent(NetLogEventType::TCP_CONNECT_ATTEMPT);
  } else {
    net_log_.EndEventWithNetErrorCode(NetLogEventType::TCP_CONNECT_ATTEMPT,
                                      result);
  }
  if (!logging_multiple_connect_attempts_) {
    if (result == OK) {
      net_log_.EndEvent(NetLogEventType::TCP_CONNECT);
    } else {
      net_log_.EndEventWithNetErrorCode(NetLogEventType::TCP_CONNECT, result);
    }
  }
  connect_attempt_logged_ = false;
}

void TCPSocketWasm::LogReadResult(IOBuffer* buf, int result) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (result < 0) {
    net_log_.AddEventWithIntParams(NetLogEventType::SOCKET_READ_ERROR,
                                   "net_error", result);
    return;
  }
  if (result == 0)
    return;
  net_log_.AddByteTransferEvent(NetLogEventType::SOCKET_BYTES_RECEIVED,
                                result, buf->data());
  activity_monitor::IncrementBytesReceived(result);
}

void TCPSocketWasm::LogWriteResult(IOBuffer* buf, int result) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (result < 0) {
    net_log_.AddEventWithIntParams(NetLogEventType::SOCKET_WRITE_ERROR,
                                   "net_error", result);
    return;
  }
  if (result == 0)
    return;
  net_log_.AddByteTransferEvent(NetLogEventType::SOCKET_BYTES_SENT, result,
                                buf->data());
}

}  // namespace net
