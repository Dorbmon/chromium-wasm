// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "media/audio/wasm_audio_bridge.h"

namespace {

// The matching Emscripten library marks each entry synchronously proxied to
// the browser main thread.  Keep these C-linkage declarations separate from
// the C++ namespace so the generated imports retain their exact JS names.
extern "C" int chromium_wasm_audio_output_is_armed();
extern "C" int chromium_wasm_audio_output_register(
    uintptr_t header_address,
    uintptr_t samples_address,
    uint32_t capacity_frames,
    uint32_t channels,
    uint32_t sample_rate,
    uint32_t frames_per_buffer,
    uint32_t generation);
extern "C" void chromium_wasm_audio_output_unregister(uint32_t generation);

}  // namespace

namespace media::wasm_audio {

bool IsOutputArmed() {
  return chromium_wasm_audio_output_is_armed() == 1;
}

bool RegisterOutputRing(uintptr_t header_address,
                        uintptr_t samples_address,
                        uint32_t capacity_frames,
                        uint32_t channels,
                        uint32_t sample_rate,
                        uint32_t frames_per_buffer,
                        uint32_t generation) {
  return chromium_wasm_audio_output_register(
             header_address, samples_address, capacity_frames, channels,
             sample_rate, frames_per_buffer, generation) == 1;
}

void UnregisterOutputRing(uint32_t generation) {
  chromium_wasm_audio_output_unregister(generation);
}

}  // namespace media::wasm_audio
