// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "net/socket/socket_options.h"

#include "build/build_config.h"
#include "net/base/net_errors.h"

#if !BUILDFLAG(IS_WASM)
#error "socket_options_wasm.cc must only be built for WebAssembly"
#endif

namespace net {

int SetTCPNoDelay(SocketDescriptor fd, bool no_delay) {
  return ERR_NOT_IMPLEMENTED;
}

int SetReuseAddr(SocketDescriptor fd, bool reuse) {
  return ERR_NOT_IMPLEMENTED;
}

int SetSocketReceiveBufferSize(SocketDescriptor fd, int32_t size) {
  return ERR_NOT_IMPLEMENTED;
}

int SetSocketSendBufferSize(SocketDescriptor fd, int32_t size) {
  return ERR_NOT_IMPLEMENTED;
}

int SetIPv6Only(SocketDescriptor fd, bool ipv6_only) {
  return ERR_NOT_IMPLEMENTED;
}

}  // namespace net
