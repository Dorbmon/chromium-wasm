// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef NET_SOCKET_WISP_TRANSPORT_WASM_H_
#define NET_SOCKET_WISP_TRANSPORT_WASM_H_

#include <stdint.h>

#include <string_view>

#include "net/base/net_export.h"

namespace net {

// The values in this enum are a narrow C++/JavaScript ABI. Keep them in sync
// with wisp_host_bridge_wasm.js. The browser main thread owns WebSocket event
// delivery; Chromium sequences only observe these states through synchronous
// Emscripten proxy calls.
enum class WasmWispStreamState : int {
  kUnavailable = 0,
  kConnecting = 1,
  kOpen = 2,
  kEof = 3,
  kFailed = 4,
};

// Returns whether the host supplied a valid, deliberately configured WISP
// endpoint. A missing endpoint is an explicit unsupported-network condition,
// not an invitation to fall back to host fetch() or native sockets.
NET_EXPORT bool IsWasmWispTransportConfigured();

// Opens one multiplexed TCP stream. |hostname| is copied by the host bridge
// before this call returns. A true return means that the bridge accepted the
// stream; it does not mean that the destination TCP connection has completed.
NET_EXPORT bool OpenWasmWispStream(uint32_t stream_id,
                                   std::string_view hostname,
                                   uint16_t port);

NET_EXPORT WasmWispStreamState GetWasmWispStreamState(uint32_t stream_id);

// Returns 0 for an orderly EOF or a negative Chromium net error for a failed
// stream. The host bridge is responsible for translating WISP close reasons.
NET_EXPORT int GetWasmWispStreamError(uint32_t stream_id);

// Returns bytes copied into or from the supplied buffer, 0 for would-block,
// or a negative Chromium net error. The host bridge copies all WebAssembly
// memory while handling the proxied import and never keeps a HEAPU8 view.
NET_EXPORT int ReadWasmWispStream(uint32_t stream_id,
                                  uint8_t* destination,
                                  int destination_length);
NET_EXPORT int WriteWasmWispStream(uint32_t stream_id,
                                   const uint8_t* source,
                                   int source_length);

// Returns the bounded number of received bytes that can be read without
// waiting. This is used to implement Chromium's ReadIfReady contract without
// consuming data speculatively.
NET_EXPORT int GetWasmWispStreamAvailableBytes(uint32_t stream_id);

// Sends a WISP CLOSE and drops host-side stream queues. |reason| is a WISP
// close reason byte, not a Chromium net error.
NET_EXPORT void CloseWasmWispStream(uint32_t stream_id, uint8_t reason);

}  // namespace net

#endif  // NET_SOCKET_WISP_TRANSPORT_WASM_H_
