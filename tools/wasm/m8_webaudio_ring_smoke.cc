// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// A deliberately target-local WebAudio feasibility smoke.  The producer runs
// on a C++ pthread and writes deterministic stereo PCM into the shared Wasm
// linear-memory ring.  JavaScript owns the WebAudio graph and AudioWorklet;
// neither Chromium's AudioManager nor AudioService is selected by this target.

#include <emscripten/emscripten.h>
#include <emscripten/threading.h>

#include <pthread.h>

#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>

#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "m8_webaudio_ring_smoke must only be built for WebAssembly"
#endif

#if BUILDFLAG(IS_POSIX)
#error "WebAssembly must not inherit POSIX platform semantics"
#endif

extern "C" int m8_webaudio_ring_register(uintptr_t header_address,
                                           uintptr_t samples_address,
                                           int capacity_frames,
                                           int channels,
                                           int total_frames);
extern "C" int m8_webaudio_ring_report_producer_started(void);
extern "C" int m8_webaudio_ring_report_producer_finished(int total_frames);

namespace {

constexpr char kPrefix[] = "CHROMIUM_WASM_M8_WEBAUDIO_RING";
constexpr int32_t kProtocol = 1;
constexpr int32_t kChannels = 2;
constexpr int32_t kCapacityFrames = 4096;
constexpr int32_t kTotalFrames = 12288;

// Keep this exact word-index ABI in sync with m8_webaudio_ring_bridge.js and
// m8_webaudio_ring_worklet.js.  These words are intentionally the only data
// the browser-facing code may retain from Wasm linear memory.
enum HeaderWord : size_t {
  kHeaderProtocol = 0,
  kHeaderCapacityFrames,
  kHeaderChannels,
  kHeaderStartRequested,
  kHeaderProducerStarted,
  kHeaderProducerDone,
  kHeaderWriteFrame,
  kHeaderReadFrame,
  kHeaderProducedFrames,
  kHeaderConsumedFrames,
  kHeaderUnderrunFrames,
  kHeaderProducerError,
  kHeaderWords,
};

static_assert(sizeof(std::atomic<int32_t>) == sizeof(int32_t));
static_assert(kCapacityFrames > 0 &&
              (kCapacityFrames & (kCapacityFrames - 1)) == 0);

alignas(64) std::array<std::atomic<int32_t>, kHeaderWords> g_header;
alignas(64) std::array<float, kCapacityFrames * kChannels> g_samples;

int Fail(const char* reason) {
  std::fprintf(stderr, "%s:FAIL reason=%s\n", kPrefix, reason);
  std::fflush(stderr);
  return 1;
}

void Store(HeaderWord word, int32_t value) {
  g_header[word].store(value, std::memory_order_seq_cst);
}

int32_t Load(HeaderWord word) {
  return g_header[word].load(std::memory_order_seq_cst);
}

void InitializeRing() {
  for (std::atomic<int32_t>& word : g_header) {
    word.store(0, std::memory_order_relaxed);
  }
  Store(kHeaderProtocol, kProtocol);
  Store(kHeaderCapacityFrames, kCapacityFrames);
  Store(kHeaderChannels, kChannels);
}

float SampleForFrame(int32_t frame) {
  // A deterministic, non-silent square wave avoids depending on a libm
  // implementation in this standalone tool.  The worklet independently
  // records non-silent frames before declaring the graph productive.
  return ((frame / 32) & 1) == 0 ? 0.20f : -0.20f;
}

bool WriteOneFrame(int32_t frame) {
  const int32_t write = Load(kHeaderWriteFrame);
  const int32_t read = Load(kHeaderReadFrame);
  const int32_t occupied = write - read;
  if (occupied < 0 || occupied > kCapacityFrames) {
    Store(kHeaderProducerError, 1);
    return false;
  }
  if (occupied == kCapacityFrames) {
    return false;
  }

  const int32_t slot = write & (kCapacityFrames - 1);
  const float sample = SampleForFrame(frame);
  g_samples[slot * kChannels] = sample;
  g_samples[slot * kChannels + 1] = -sample;
  Store(kHeaderWriteFrame, write + 1);
  Store(kHeaderProducedFrames, frame + 1);
  return true;
}

void* ProducePcm(void*) {
  // The browser must not be asked to start audio before a trusted click.  The
  // host sets this shared word only after AudioContext.resume() has been
  // initiated from that click and the AudioWorkletNode is connected.
  while (Load(kHeaderStartRequested) != 1) {
    emscripten_thread_sleep(1);
  }

  Store(kHeaderProducerStarted, 1);
  if (m8_webaudio_ring_report_producer_started() != 1) {
    Store(kHeaderProducerError, 2);
    return nullptr;
  }
  std::fprintf(stdout, "%s:PRODUCER_STARTED\n", kPrefix);
  std::fflush(stdout);

  for (int32_t frame = 0; frame < kTotalFrames;) {
    if (WriteOneFrame(frame)) {
      ++frame;
      continue;
    }
    if (Load(kHeaderProducerError) != 0) {
      return nullptr;
    }
    // This runs only on the producer pthread. It must never block the browser
    // main thread while the AudioWorklet drains the ring.
    emscripten_thread_sleep(1);
  }

  Store(kHeaderProducerDone, 1);
  if (m8_webaudio_ring_report_producer_finished(kTotalFrames) != 1) {
    Store(kHeaderProducerError, 3);
    return nullptr;
  }
  std::fprintf(stdout, "%s:PRODUCER_DONE frames=%d\n", kPrefix,
               kTotalFrames);
  std::fflush(stdout);
  return nullptr;
}

}  // namespace

int main() {
  if (!emscripten_has_threading_support()) {
    return Fail("pthread_support_unavailable");
  }

  InitializeRing();
  if (m8_webaudio_ring_register(
          reinterpret_cast<uintptr_t>(g_header.data()),
          reinterpret_cast<uintptr_t>(g_samples.data()), kCapacityFrames,
          kChannels, kTotalFrames) != 1) {
    return Fail("browser_ring_registration");
  }

  pthread_t producer;
  if (pthread_create(&producer, nullptr, &ProducePcm, nullptr) != 0) {
    return Fail("producer_pthread_create");
  }

  std::fprintf(stdout,
               "%s:READY capacity_frames=%d channels=%d total_frames=%d\n",
               kPrefix, kCapacityFrames, kChannels, kTotalFrames);
  std::fflush(stdout);

  // Do not return from main: the target-local browser host needs the module
  // and producer pthread to remain live until the worklet reports that it has
  // drained the finite ring.  The runner closes only the AudioContext and then
  // terminates its isolated browser process; this is not normal Chromium or
  // Emscripten shutdown coverage.
  emscripten_exit_with_live_runtime();
}
