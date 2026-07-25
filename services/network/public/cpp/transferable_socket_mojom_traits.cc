// Copyright 2022 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "services/network/public/cpp/transferable_socket_mojom_traits.h"

#include <algorithm>
#include <vector>

#include "base/dcheck_is_on.h"
#include "build/build_config.h"
#include "mojo/public/cpp/bindings/struct_traits.h"

namespace mojo {

#if BUILDFLAG(IS_WIN)
// static
const std::vector<uint8_t>&
StructTraits<network::mojom::TransferableSocketDataView,
             network::TransferableSocket>::
    protocol_info(const network::TransferableSocket& value) {
#if DCHECK_IS_ON()
  DCHECK(!value.has_been_transferred_) << "Can only transfer once.";
#endif
  return value.wsa_info_buffer_;
}
#else
mojo::PlatformHandle StructTraits<
    network::mojom::TransferableSocketDataView,
    network::TransferableSocket>::socket(network::TransferableSocket& value) {
#if DCHECK_IS_ON()
  DCHECK(!value.has_been_transferred_) << "Can only transfer once.";
#endif
#if BUILDFLAG(IS_WASM)
  // M3 can serialize only the empty handle representing kInvalidSocket.
  return mojo::PlatformHandle();
#else
  mojo::PlatformHandle output;
  std::swap(value.socket_, output);
  return output;
#endif  // BUILDFLAG(IS_WASM)
}
#endif  // BUILDFLAG(IS_WIN)

// static
bool StructTraits<network::mojom::TransferableSocketDataView,
                  network::TransferableSocket>::
    Read(network::mojom::TransferableSocketDataView in,
         network::TransferableSocket* out) {
#if BUILDFLAG(IS_WIN)
  if (!in.ReadProtocolInfo(&out->wsa_info_buffer_))
    return false;
#elif BUILDFLAG(IS_WASM)
  mojo::PlatformHandle socket = in.TakeSocket();
  if (socket.type() != mojo::PlatformHandle::Type::kNone)
    return false;
  *out = network::TransferableSocket();
#else
  *out = network::TransferableSocket(in.TakeSocket());
#endif
#if DCHECK_IS_ON()
  out->has_been_transferred_ = true;
#endif
  return true;
}

}  // namespace mojo
