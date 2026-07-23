// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/rand_util.h"

#include <stddef.h>
#include <stdint.h>
#include <unistd.h>

#include <algorithm>
#include <array>

#include "base/check.h"
#include "base/containers/span.h"

namespace base {

namespace {

constexpr size_t kMaxGetEntropySize = 256;

void GetEntropy(span<uint8_t> output) {
  while (!output.empty()) {
    const size_t chunk_size = std::min(output.size(), kMaxGetEntropySize);

    // Emscripten 5.0.6's Node implementation returns the filled typed array
    // instead of the required WASI success code. A one-byte typed array coerces
    // to its random byte value, while a multi-byte typed array coerces to zero.
    // Request two secure bytes and discard one for singleton tails until the
    // pinned runtime is rolled.
    if (chunk_size == 1) {
      std::array<uint8_t, 2> padded_chunk;
      PCHECK(getentropy(padded_chunk.data(), padded_chunk.size()) == 0);
      output.front() = padded_chunk.front();
      output = output.subspan(size_t{1});
      continue;
    }

    span<uint8_t> chunk = output.first(chunk_size);
    PCHECK(getentropy(chunk.data(), chunk.size()) == 0);
    output = output.subspan(chunk_size);
  }
}

}  // namespace

namespace internal {

void ConfigureBoringSSLBackedRandBytesFieldTrial() {
  // Wasm always uses Emscripten's host-backed secure entropy provider.
}

double RandDoubleAvoidAllocation() {
  uint64_t number;
  GetEntropy(byte_span_from_ref(number));
  // This transformation is explained in rand_util.cc.
  return (number >> 11) * 0x1.0p-53;
}

}  // namespace internal

void RandBytes(span<uint8_t> output) {
  GetEntropy(output);
}

}  // namespace base
