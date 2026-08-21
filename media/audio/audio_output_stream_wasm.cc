// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "media/audio/audio_output_stream_wasm.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <utility>

#include <emscripten/heap.h>

#include "base/check.h"
#include "base/functional/bind.h"
#include "base/time/time.h"
#include "media/audio/audio_manager_base.h"
#include "media/base/audio_bus.h"
#include "media/base/fake_audio_worker.h"

namespace media {

namespace {

static_assert(sizeof(std::atomic<uint32_t>) == sizeof(uint32_t));
static_assert((wasm_audio::kCapacityFrames &
               (wasm_audio::kCapacityFrames - 1)) == 0);

std::atomic<uint32_t> g_next_generation{1};

uint32_t NextGeneration() {
  uint32_t generation = g_next_generation.fetch_add(1, std::memory_order_relaxed);
  // Zero is intentionally invalid at the JS boundary.  It is extraordinarily
  // unlikely to be reached in practice, but keep the ABI total across wrap.
  if (generation == 0) {
    generation = g_next_generation.fetch_add(1, std::memory_order_relaxed);
  }
  return generation;
}

uint32_t ClampVolumeToMillionths(double volume) {
  if (!std::isfinite(volume)) {
    return 0;
  }
  const double clamped = std::clamp(volume, 0.0, 1.0);
  return static_cast<uint32_t>(clamped * 1000000.0 + 0.5);
}

}  // namespace

AudioOutputStreamWasm::AudioOutputStreamWasm(AudioManagerBase* audio_manager,
                                             const AudioParameters& params)
    : audio_manager_(audio_manager),
      params_(params),
      audio_bus_(AudioBus::Create(params)),
      audio_worker_(std::make_unique<FakeAudioWorker>(
          audio_manager->GetWorkerTaskRunner(), params)) {
  CHECK(audio_manager_);
  CHECK(audio_bus_);
  CHECK(params_.IsValid());
  CHECK_EQ(params_.channels(), static_cast<int>(wasm_audio::kChannels));
  CHECK_EQ(params_.sample_rate(), static_cast<int>(wasm_audio::kSampleRate));
  CHECK_EQ(params_.frames_per_buffer(),
           static_cast<int>(wasm_audio::kFramesPerBuffer));
}

AudioOutputStreamWasm::~AudioOutputStreamWasm() {
  DCHECK(!open_);
  DCHECK(!registered_);
  DCHECK(!callback_);
  DCHECK(!pending_error_callback_);
}

bool AudioOutputStreamWasm::Open() {
  CHECK(audio_manager_->GetTaskRunner()->BelongsToCurrentThread());
  DCHECK(!open_);

  InitializeHeader();
  initial_heap_size_ = emscripten_get_heap_size();
  generation_ = NextGeneration();
  header_[kHeaderGeneration].store(generation_, std::memory_order_seq_cst);
  if (!RegisterRing()) {
    generation_ = 0;
    return false;
  }

  open_ = true;
  return true;
}

void AudioOutputStreamWasm::Start(AudioSourceCallback* callback) {
  CHECK(audio_manager_->GetTaskRunner()->BelongsToCurrentThread());
  CHECK(callback);
  // Open() registers the descriptor before the physical browser click so the
  // host can construct its AudioWorklet.  Starting samples still requires the
  // post-gesture host arm; treating its absence as a stream error keeps a
  // normal client from silently producing into an unattached ring.
  if (!open_ || failed_.load(std::memory_order_acquire) ||
      !wasm_audio::IsOutputArmed()) {
    callback->OnError(AudioSourceCallback::ErrorType::kUnknown);
    return;
  }

  bool already_started = false;
  {
    base::AutoLock lock(callback_lock_);
    if (callback_) {
      already_started = true;
    } else {
      callback_ = callback;
    }
  }
  if (already_started) {
    callback->OnError(AudioSourceCallback::ErrorType::kUnknown);
    return;
  }

  // Stop() unregisters the host ring so subsequent Start() calls must obtain a
  // fresh generation.  This keeps browser-side ownership explicit and avoids
  // a disconnected AudioWorklet silently accepting samples after reuse.
  if (!registered_) {
    InitializeHeader();
    initial_heap_size_ = emscripten_get_heap_size();
    generation_ = NextGeneration();
    header_[kHeaderGeneration].store(generation_, std::memory_order_seq_cst);
    if (!RegisterRing()) {
      ReportError();
      return;
    }
  }

  // Fill a short lead before publishing the started state.  This prevents the
  // worklet from treating normal initial scheduling latency as an underrun.
  for (int i = 0; i < 4; ++i) {
    PumpSamples(base::TimeTicks::Now(), base::TimeTicks::Now());
    base::AutoLock lock(callback_lock_);
    if (!callback_) {
      return;
    }
  }

  header_[kHeaderProducerState].store(1, std::memory_order_seq_cst);
  audio_worker_->Start(base::BindRepeating(
      &AudioOutputStreamWasm::PumpSamples, base::Unretained(this)));
}

void AudioOutputStreamWasm::Stop() {
  CHECK(audio_manager_->GetTaskRunner()->BelongsToCurrentThread());
  {
    base::AutoLock lock(callback_lock_);
    callback_ = nullptr;
    // Stop() is a hard callback boundary.  A worker-detected error may already
    // have posted teardown to this sequence, but callers may destroy their
    // callback as soon as Stop() returns.
    pending_error_callback_ = nullptr;
  }
  audio_worker_->Stop();
  header_[kHeaderProducerState].store(2, std::memory_order_seq_cst);
  UnregisterRing();
}

void AudioOutputStreamWasm::SetVolume(double volume) {
  CHECK(audio_manager_->GetTaskRunner()->BelongsToCurrentThread());
  volume_millionths_.store(ClampVolumeToMillionths(volume),
                           std::memory_order_relaxed);
}

void AudioOutputStreamWasm::GetVolume(double* volume) {
  CHECK(audio_manager_->GetTaskRunner()->BelongsToCurrentThread());
  CHECK(volume);
  *volume = static_cast<double>(volume_millionths_.load(
                                std::memory_order_relaxed)) /
            1000000.0;
}

void AudioOutputStreamWasm::Close() {
  CHECK(audio_manager_->GetTaskRunner()->BelongsToCurrentThread());
  Stop();
  {
    base::AutoLock lock(callback_lock_);
    // A Close() may race the deferred error task by being called from the
    // client after it has already stopped the stream.  The stream is about to
    // release itself, so it cannot retain a non-owning callback pointer.
    pending_error_callback_ = nullptr;
  }
  open_ = false;

  // This is deliberately last: ReleaseOutputStream() deletes |this|.
  audio_manager_->ReleaseOutputStream(this);
}

void AudioOutputStreamWasm::Flush() {
  CHECK(audio_manager_->GetTaskRunner()->BelongsToCurrentThread());
  {
    base::AutoLock lock(callback_lock_);
    CHECK(!callback_);
  }
  const uint32_t read =
      header_[kHeaderReadFrame].load(std::memory_order_seq_cst);
  header_[kHeaderWriteFrame].store(read, std::memory_order_seq_cst);
}

uint32_t AudioOutputStreamWasm::GetConsumedFramesForTesting() const {
  return header_[kHeaderConsumedFrames].load(std::memory_order_seq_cst);
}

bool AudioOutputStreamWasm::IsHostStartedForTesting() const {
  return header_[kHeaderProducerError].load(std::memory_order_seq_cst) == 0 &&
         header_[kHeaderHostState].load(std::memory_order_seq_cst) ==
             kHostStarted;
}

bool AudioOutputStreamWasm::IsHostDrainedForTesting() const {
  return header_[kHeaderProducerError].load(std::memory_order_seq_cst) == 0 &&
         header_[kHeaderHostState].load(std::memory_order_seq_cst) ==
             kHostDrained;
}

bool AudioOutputStreamWasm::RegisterRing() {
  const bool registered = wasm_audio::RegisterOutputRing(
      reinterpret_cast<uintptr_t>(header_.data()),
      reinterpret_cast<uintptr_t>(samples_.data()), wasm_audio::kCapacityFrames,
      wasm_audio::kChannels, wasm_audio::kSampleRate,
      wasm_audio::kFramesPerBuffer, generation_);
  registered_ = registered;
  return registered;
}

void AudioOutputStreamWasm::UnregisterRing() {
  if (!registered_) {
    return;
  }
  wasm_audio::UnregisterOutputRing(generation_);
  registered_ = false;
}

void AudioOutputStreamWasm::PumpSamples(base::TimeTicks ideal_time,
                                        base::TimeTicks now) {
  if (emscripten_get_heap_size() != initial_heap_size_ ||
      header_[kHeaderProducerError].load(std::memory_order_seq_cst) != 0 ||
      header_[kHeaderHostState].load(std::memory_order_seq_cst) == kHostError) {
    ReportError();
    return;
  }

  const uint32_t write =
      header_[kHeaderWriteFrame].load(std::memory_order_seq_cst);
  const uint32_t read =
      header_[kHeaderReadFrame].load(std::memory_order_seq_cst);
  const uint32_t occupied = write - read;
  if (occupied > wasm_audio::kCapacityFrames ||
      wasm_audio::kFramesPerBuffer > wasm_audio::kCapacityFrames - occupied) {
    header_[kHeaderProducerError].store(1, std::memory_order_seq_cst);
    ReportError();
    return;
  }

  int frames_filled = 0;
  {
    base::AutoLock lock(callback_lock_);
    if (!callback_) {
      return;
    }
    const base::TimeDelta delay =
        FakeAudioWorker::ComputeFakeOutputDelay(params_) +
        std::max(base::TimeDelta(), ideal_time - now);
    frames_filled = callback_->OnMoreData(delay, now, {}, audio_bus_.get());
  }

  if (frames_filled < 0 || frames_filled > params_.frames_per_buffer()) {
    header_[kHeaderProducerError].store(1, std::memory_order_seq_cst);
    ReportError();
    return;
  }
  if (frames_filled == 0) {
    return;
  }

  const float volume = static_cast<float>(
      volume_millionths_.load(std::memory_order_relaxed)) / 1000000.0f;
  for (int frame = 0; frame < frames_filled; ++frame) {
    const uint32_t slot =
        (write + static_cast<uint32_t>(frame)) &
        (wasm_audio::kCapacityFrames - 1);
    for (uint32_t channel = 0; channel < wasm_audio::kChannels; ++channel) {
      samples_[slot * wasm_audio::kChannels + channel] =
          audio_bus_->channel(static_cast<int>(channel))[frame] * volume;
    }
  }

  // Atomics in the JS Uint32Array observe this seq-cst publication only after
  // every sample in the corresponding span has been written.
  const uint32_t next_write = write + static_cast<uint32_t>(frames_filled);
  header_[kHeaderWriteFrame].store(next_write, std::memory_order_seq_cst);
  header_[kHeaderProducedFrames].fetch_add(
      static_cast<uint32_t>(frames_filled), std::memory_order_seq_cst);
}

void AudioOutputStreamWasm::ReportError() {
  bool post_teardown = false;
  {
    base::AutoLock lock(callback_lock_);
    if (!error_teardown_posted_) {
      pending_error_callback_ = callback_;
      error_teardown_posted_ = true;
      failed_.store(true, std::memory_order_release);
      post_teardown = true;
    }
    callback_ = nullptr;
  }

  header_[kHeaderProducerError].store(1, std::memory_order_seq_cst);
  header_[kHeaderHostState].store(kHostError, std::memory_order_seq_cst);

  if (post_teardown) {
    // FakeAudioWorker invokes PumpSamples while holding its worker callback
    // lock.  Stop() takes that lock, so stopping inline would deadlock.  Post
    // back to the audio sequence after the callback returns, then synchronously
    // detach the exact host generation before any later Start() can proceed.
    audio_manager_->GetTaskRunner()->PostTask(
        FROM_HERE,
        base::BindOnce(&AudioOutputStreamWasm::FinishErrorOnAudioSequence,
                       weak_factory_.GetWeakPtr()));
  }
}

void AudioOutputStreamWasm::FinishErrorOnAudioSequence() {
  CHECK(audio_manager_->GetTaskRunner()->BelongsToCurrentThread());
  audio_worker_->Stop();
  header_[kHeaderProducerState].store(2, std::memory_order_seq_cst);
  UnregisterRing();

  AudioSourceCallback* callback = nullptr;
  {
    base::AutoLock lock(callback_lock_);
    callback = pending_error_callback_;
    pending_error_callback_ = nullptr;
  }
  if (callback) {
    // This must be the final use of |this|: AudioSourceCallback::OnError() is
    // allowed to synchronously Close() the stream, which releases it.
    callback->OnError(AudioSourceCallback::ErrorType::kUnknown);
  }
}

void AudioOutputStreamWasm::InitializeHeader() {
  for (std::atomic<uint32_t>& word : header_) {
    word.store(0, std::memory_order_relaxed);
  }
  header_[kHeaderProtocol].store(wasm_audio::kProtocol, std::memory_order_seq_cst);
  header_[kHeaderCapacityFrames].store(wasm_audio::kCapacityFrames,
                                       std::memory_order_seq_cst);
  header_[kHeaderChannels].store(wasm_audio::kChannels,
                                 std::memory_order_seq_cst);
  header_[kHeaderSampleRate].store(wasm_audio::kSampleRate,
                                   std::memory_order_seq_cst);
  header_[kHeaderFramesPerBuffer].store(wasm_audio::kFramesPerBuffer,
                                        std::memory_order_seq_cst);
}

}  // namespace media
