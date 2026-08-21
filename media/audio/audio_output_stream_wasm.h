// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef MEDIA_AUDIO_AUDIO_OUTPUT_STREAM_WASM_H_
#define MEDIA_AUDIO_AUDIO_OUTPUT_STREAM_WASM_H_

#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <memory>

#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "base/synchronization/lock.h"
#include "base/thread_annotations.h"
#include "media/audio/audio_io.h"
#include "media/audio/wasm_audio_bridge.h"
#include "media/base/audio_parameters.h"

namespace base {
class TimeDelta;
class TimeTicks;
}  // namespace base

namespace media {

class AudioBus;
class AudioManagerBase;
class FakeAudioWorker;

// A deliberately narrow WebAssembly AudioOutputStream.  It provides one
// stereo 48 kHz low-latency PCM stream to an outer-page AudioWorklet through a
// bounded SharedArrayBuffer view of Wasm linear memory.  It is not an
// AudioService, a general device implementation, or a host audio fallback.
class AudioOutputStreamWasm final : public AudioOutputStream {
 public:
  AudioOutputStreamWasm(AudioManagerBase* audio_manager,
                        const AudioParameters& params);

  AudioOutputStreamWasm(const AudioOutputStreamWasm&) = delete;
  AudioOutputStreamWasm& operator=(const AudioOutputStreamWasm&) = delete;

  // AudioOutputStream:
  bool Open() override;
  void Start(AudioSourceCallback* callback) override;
  void Stop() override;
  void SetVolume(double volume) override;
  void GetVolume(double* volume) override;
  void Close() override;
  void Flush() override;

  // Used solely by wasm_audio_manager_output_smoke after its finite callback
  // has completed.  It observes the worklet's atomic read counter; production
  // users never need a browser-side completion import.
  uint32_t GetConsumedFramesForTesting() const;

  // The smoke opens and registers its ring before the physical browser click,
  // then waits for the host to complete its trusted WebAudio setup before it
  // calls Start().  This observes that exact fixed host state without exposing
  // it through the bridge ABI.
  bool IsHostStartedForTesting() const;

  // Likewise, DRAINED is emitted only after the worklet publishes its terminal
  // state, rather than merely after it has incremented the consumed counter.
  bool IsHostDrainedForTesting() const;

 private:
  ~AudioOutputStreamWasm() override;

  enum HeaderWord : size_t {
    kHeaderProtocol = 0,
    kHeaderCapacityFrames,
    kHeaderChannels,
    kHeaderSampleRate,
    kHeaderFramesPerBuffer,
    kHeaderGeneration,
    kHeaderProducerState,
    kHeaderWriteFrame,
    kHeaderReadFrame,
    kHeaderProducedFrames,
    kHeaderConsumedFrames,
    kHeaderUnderrunFrames,
    kHeaderProducerError,
    kHeaderHostState,
    kHeaderReserved0,
    kHeaderReserved1,
  };

  static constexpr uint32_t kHostStarted = 1;
  static constexpr uint32_t kHostDrained = 2;
  static constexpr uint32_t kHostError = UINT32_MAX;

  bool RegisterRing();
  void UnregisterRing();
  void PumpSamples(base::TimeTicks ideal_time, base::TimeTicks now);
  void ReportError();
  void FinishErrorOnAudioSequence();
  void InitializeHeader();

  const raw_ptr<AudioManagerBase> audio_manager_;
  const AudioParameters params_;
  std::unique_ptr<AudioBus> audio_bus_;
  std::unique_ptr<FakeAudioWorker> audio_worker_;

  // C++ and the AudioWorklet share only this fixed-size, atomically published
  // metadata.  Uint32Array/Atomics is used in JS so index wraparound has the
  // same defined modulo-2^32 behavior on both sides.
  alignas(64) std::array<std::atomic<uint32_t>, wasm_audio::kHeaderWords>
      header_;
  alignas(64) std::array<float,
                           wasm_audio::kCapacityFrames * wasm_audio::kChannels>
      samples_;

  base::Lock callback_lock_;
  raw_ptr<AudioSourceCallback> callback_ GUARDED_BY(callback_lock_) = nullptr;
  // A callback error detected from FakeAudioWorker must be delivered only
  // after its repeating callback has returned.  In particular, an error
  // handler is allowed to synchronously Stop() or Close() this stream.
  raw_ptr<AudioSourceCallback> pending_error_callback_
      GUARDED_BY(callback_lock_) = nullptr;

  std::atomic<uint32_t> volume_millionths_{1000000};
  size_t initial_heap_size_ = 0;
  uint32_t generation_ = 0;
  bool open_ = false;
  bool registered_ = false;
  // ReportError() can run on FakeAudioWorker while Start() runs on the audio
  // sequence.  It is terminal once set, so use an atomic rather than relying
  // on the callback lock for an unrelated caller.
  std::atomic<bool> failed_{false};
  bool error_teardown_posted_ = false;

  // Error detection can occur inside FakeAudioWorker's repeating callback.
  // The deferred teardown must not outlive a Close() that releases this stream.
  base::WeakPtrFactory<AudioOutputStreamWasm> weak_factory_{this};
};

}  // namespace media

#endif  // MEDIA_AUDIO_AUDIO_OUTPUT_STREAM_WASM_H_
