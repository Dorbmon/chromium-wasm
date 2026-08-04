// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "net/socket/wisp_transport_wasm.h"

#include <limits>

#include "base/check_op.h"
#include "build/build_config.h"
#include "net/base/net_errors.h"

#if !BUILDFLAG(IS_WASM)
#error "wisp_transport_wasm.cc must only be built for WebAssembly"
#endif

namespace {

extern "C" {

int chromium_wasm_wisp_stream_is_configured();
int chromium_wasm_wisp_stream_open(uint32_t stream_id,
                                   const char* hostname,
                                   int hostname_length,
                                   uint16_t port);
int chromium_wasm_wisp_stream_state(uint32_t stream_id);
int chromium_wasm_wisp_stream_error(uint32_t stream_id);
int chromium_wasm_wisp_stream_read(uint32_t stream_id,
                                   uint8_t* destination,
                                   int destination_length);
int chromium_wasm_wisp_stream_write(uint32_t stream_id,
                                    const uint8_t* source,
                                    int source_length);
int chromium_wasm_wisp_stream_available(uint32_t stream_id);
int chromium_wasm_wisp_stream_close(uint32_t stream_id, int reason);

}  // extern "C"

bool IsValidStreamId(uint32_t stream_id) {
  return stream_id != 0;
}

int NormalizeByteResult(int result, int capacity) {
  if (result < 0)
    return result;
  if (result <= capacity)
    return result;
  return net::ERR_FAILED;
}

}  // namespace

namespace net {

bool IsWasmWispTransportConfigured() {
  return chromium_wasm_wisp_stream_is_configured() == 1;
}

bool OpenWasmWispStream(uint32_t stream_id,
                        std::string_view hostname,
                        uint16_t port) {
  if (!IsValidStreamId(stream_id) || hostname.empty() || port == 0 ||
      hostname.size() >
          static_cast<size_t>(std::numeric_limits<int>::max())) {
    return false;
  }

  return chromium_wasm_wisp_stream_open(
             stream_id, hostname.data(), static_cast<int>(hostname.size()),
             port) == 1;
}

WasmWispStreamState GetWasmWispStreamState(uint32_t stream_id) {
  if (!IsValidStreamId(stream_id))
    return WasmWispStreamState::kUnavailable;

  switch (chromium_wasm_wisp_stream_state(stream_id)) {
    case static_cast<int>(WasmWispStreamState::kConnecting):
      return WasmWispStreamState::kConnecting;
    case static_cast<int>(WasmWispStreamState::kOpen):
      return WasmWispStreamState::kOpen;
    case static_cast<int>(WasmWispStreamState::kEof):
      return WasmWispStreamState::kEof;
    case static_cast<int>(WasmWispStreamState::kFailed):
      return WasmWispStreamState::kFailed;
    case static_cast<int>(WasmWispStreamState::kUnavailable):
    default:
      return WasmWispStreamState::kUnavailable;
  }
}

int GetWasmWispStreamError(uint32_t stream_id) {
  if (!IsValidStreamId(stream_id))
    return ERR_SOCKET_NOT_CONNECTED;

  const int result = chromium_wasm_wisp_stream_error(stream_id);
  return result <= 0 ? result : ERR_FAILED;
}

int ReadWasmWispStream(uint32_t stream_id,
                       uint8_t* destination,
                       int destination_length) {
  if (!IsValidStreamId(stream_id) || !destination || destination_length <= 0)
    return ERR_INVALID_ARGUMENT;

  return NormalizeByteResult(
      chromium_wasm_wisp_stream_read(stream_id, destination,
                                     destination_length),
      destination_length);
}

int WriteWasmWispStream(uint32_t stream_id,
                        const uint8_t* source,
                        int source_length) {
  if (!IsValidStreamId(stream_id) || !source || source_length <= 0)
    return ERR_INVALID_ARGUMENT;

  return NormalizeByteResult(
      chromium_wasm_wisp_stream_write(stream_id, source, source_length),
      source_length);
}

int GetWasmWispStreamAvailableBytes(uint32_t stream_id) {
  if (!IsValidStreamId(stream_id))
    return ERR_SOCKET_NOT_CONNECTED;

  const int available = chromium_wasm_wisp_stream_available(stream_id);
  return available >= 0 ? available : ERR_FAILED;
}

void CloseWasmWispStream(uint32_t stream_id, uint8_t reason) {
  if (!IsValidStreamId(stream_id))
    return;

  const int result = chromium_wasm_wisp_stream_close(stream_id, reason);
  DCHECK(result == 0 || result == 1);
}

}  // namespace net
