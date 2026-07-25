// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/sync_socket.h"

#include "base/check.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "sync_socket_wasm.cc must only be built for WebAssembly"
#endif

namespace base {

// static
bool SyncSocket::CreatePair(SyncSocket* socket_a, SyncSocket* socket_b) {
  DCHECK_NE(socket_a, socket_b);
  DCHECK(!socket_a->IsValid());
  DCHECK(!socket_b->IsValid());
  // Cross-process synchronization sockets have no role in the single-process
  // Wasm model. In-process users must use Chromium synchronization primitives.
  return false;
}

void SyncSocket::Close() {
  handle_.reset();
}

size_t SyncSocket::Send(span<const uint8_t> data) {
  return 0;
}

size_t SyncSocket::Receive(span<uint8_t> buffer) {
  return 0;
}

size_t SyncSocket::ReceiveWithTimeout(span<uint8_t> buffer,
                                      TimeDelta timeout) {
  return 0;
}

size_t SyncSocket::Peek() {
  return 0;
}

bool SyncSocket::IsValid() const {
  return handle_.is_valid();
}

SyncSocket::Handle SyncSocket::handle() const {
  return handle_.get();
}

SyncSocket::Handle SyncSocket::Release() {
  return handle_.release();
}

bool CancelableSyncSocket::Shutdown() {
  return false;
}

size_t CancelableSyncSocket::Send(span<const uint8_t> data) {
  return 0;
}

// static
bool CancelableSyncSocket::CreatePair(CancelableSyncSocket* socket_a,
                                      CancelableSyncSocket* socket_b) {
  return SyncSocket::CreatePair(socket_a, socket_b);
}

}  // namespace base
