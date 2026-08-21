// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef MEDIA_AUDIO_WASM_AUDIO_BRIDGE_H_
#define MEDIA_AUDIO_WASM_AUDIO_BRIDGE_H_

#include <stdint.h>

namespace media::wasm_audio {

// This ABI is implemented by wasm_audio_bridge.js.  It deliberately contains
// only control-plane calls.  Audio samples remain in the shared Wasm linear
// memory ring and are never copied through a JavaScript import per quantum.
constexpr uint32_t kProtocol = 1;
constexpr uint32_t kChannels = 2;
constexpr uint32_t kSampleRate = 48000;
constexpr uint32_t kFramesPerBuffer = 480;
constexpr uint32_t kCapacityFrames = 4096;
constexpr uint32_t kHeaderWords = 16;

// Returns true only after the outer host has synchronously established a
// trusted-user-gesture AudioContext and its AudioWorklet is ready to accept a
// descriptor.  A missing or malformed host bridge is unavailable, never a
// fake output device.
bool IsOutputArmed();

// Registers one shared-memory output ring.  All values are validated again by
// the browser-main JS bridge before it retains the descriptor.  Returns false
// on any missing host capability, invalid descriptor, or host failure.
bool RegisterOutputRing(uintptr_t header_address,
                        uintptr_t samples_address,
                        uint32_t capacity_frames,
                        uint32_t channels,
                        uint32_t sample_rate,
                        uint32_t frames_per_buffer,
                        uint32_t generation);

// Stops and drops a previously registered ring.  This operation is
// idempotent at the JS boundary so a failed Open()/Close() pair cannot leave a
// browser-owned AudioWorklet retaining a Wasm memory view.
void UnregisterOutputRing(uint32_t generation);

}  // namespace media::wasm_audio

#endif  // MEDIA_AUDIO_WASM_AUDIO_BRIDGE_H_
