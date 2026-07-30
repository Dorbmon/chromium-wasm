// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "partition_alloc/partition_alloc_base/rand_util.h"

#include <unistd.h>

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>

#include "partition_alloc/build_config.h"
#include "partition_alloc/partition_alloc_base/check.h"
#include "partition_alloc/partition_alloc_base/compiler_specific.h"

#if !PA_BUILDFLAG(IS_WASM)
#error "rand_util_wasm.cc must only be built for WebAssembly"
#endif

namespace partition_alloc::internal::base {
namespace {

constexpr size_t kMaxGetEntropySize = 256;

}  // namespace

void RandBytes(void* output, size_t output_length) {
  auto* bytes = static_cast<uint8_t*>(output);
  while (output_length > 0) {
    const size_t chunk_size =
        std::min(output_length, kMaxGetEntropySize);

    // The pinned Emscripten Node runtime returns the filled typed array rather
    // than a WASI success code. A one-byte typed array coerces to the random
    // byte value, so use two bytes and discard one for singleton tails.
    if (chunk_size == 1) {
      std::array<uint8_t, 2> padded_chunk;
      PA_BASE_CHECK(getentropy(padded_chunk.data(), padded_chunk.size()) == 0);
      PA_MSAN_UNPOISON(padded_chunk.data(), padded_chunk.size());
      *bytes = padded_chunk.front();
      ++bytes;
      --output_length;
      continue;
    }

    PA_BASE_CHECK(getentropy(bytes, chunk_size) == 0);
    PA_MSAN_UNPOISON(bytes, chunk_size);
    PA_UNSAFE_TODO(bytes += chunk_size);
    output_length -= chunk_size;
  }
}

}  // namespace partition_alloc::internal::base
