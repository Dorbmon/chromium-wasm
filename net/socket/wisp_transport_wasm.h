// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef NET_SOCKET_WISP_TRANSPORT_WASM_H_
#define NET_SOCKET_WISP_TRANSPORT_WASM_H_

#include <stdint.h>

#include <optional>
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

// A bounded, redacted snapshot of the browser-side WISP bridge. The bit flags
// deliberately carry no endpoint, destination, stream ID, or payload data.
// They exist for a public-network smoke to prove the configured WebSocket
// completed a WISP handshake and confirmed at least one TCP stream.
constexpr int kWasmWispDiagnosticWebSocketOpened = 1 << 0;
constexpr int kWasmWispDiagnosticHandshakeReady = 1 << 1;
constexpr int kWasmWispDiagnosticStreamConfirmed = 1 << 2;
constexpr int kWasmWispDiagnosticAllRequired =
    kWasmWispDiagnosticWebSocketOpened |
    kWasmWispDiagnosticHandshakeReady |
    kWasmWispDiagnosticStreamConfirmed;

struct WasmWispTransportDiagnostics {
  int completion_flags;
};

// Returns whether the host supplied a valid, deliberately configured WISP
// endpoint. A missing endpoint is an explicit unsupported-network condition,
// not an invitation to fall back to host fetch() or native sockets.
NET_EXPORT bool IsWasmWispTransportConfigured();

// Starts a private diagnostic evidence window for |hostname| and |port|.
// Until a matching TCP stream is confirmed after this call,
// GetWasmWispTransportDiagnostics() omits the stream-confirmed bit even when
// an earlier or unrelated stream completed. This is intended for a bounded
// test to tie transport evidence to one subsequent navigation; it never
// exposes a stream count, endpoint, destination, or payload.
NET_EXPORT bool BeginWasmWispTransportDiagnostics(std::string_view hostname,
                                                  uint16_t port);

// Returns nullopt if the host has no configured WISP transport or returned an
// invalid diagnostic state. Callers must treat this as failed transport
// evidence rather than fabricating a successful snapshot. After an evidence
// window begins, the stream-confirmed bit proves a post-window TCP confirmation.
NET_EXPORT std::optional<WasmWispTransportDiagnostics>
GetWasmWispTransportDiagnostics();

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
