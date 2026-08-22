// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// A browser smoke for the actual Wasm AudioManager/AudioOutputStream path.
// It deliberately does not instantiate AudioService or Blink media plumbing:
// those still require transferable SyncSocket data pipes that Wasm rejects.

#include <emscripten/threading.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <memory>
#include <utility>

#include "base/at_exit.h"
#include "base/command_line.h"
#include "base/functional/bind.h"
#include "base/memory/ref_counted.h"
#include "base/message_loop/message_pump_type.h"
#include "base/synchronization/waitable_event.h"
#include "base/task/single_thread_task_executor.h"
#include "base/task/thread_pool/thread_pool_instance.h"
#include "base/time/time.h"
#include "build/build_config.h"
#include "media/audio/audio_device_description.h"
#include "media/audio/audio_manager.h"
#include "media/audio/audio_output_stream_wasm.h"
#include "media/audio/audio_thread_impl.h"
#include "media/audio/fake_audio_log_factory.h"
#include "media/audio/wasm_audio_bridge.h"
#include "media/base/audio_bus.h"
#include "media/base/audio_parameters.h"
#include "media/base/channel_layout.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_audio_manager_output_smoke must only be built for WebAssembly"
#endif

#if BUILDFLAG(IS_POSIX)
#error "WebAssembly must not inherit POSIX platform semantics"
#endif

namespace {

constexpr char kPrefix[] = "CHROMIUM_WASM_M8_AUDIO_MANAGER";
constexpr uint32_t kTotalFrames = 12000;
constexpr base::TimeDelta kAudioTimeout = base::Seconds(20);
// This is a target-local M8.2 preparation check. It exercises one stream's
// normal volume API without selecting browser, device, mute, or tab policy.
constexpr double kFixedStreamGain = 0.5;
constexpr double kFixedStreamGainTolerance = 0.000001;

void EmitMarker(const char* marker) {
  std::fprintf(stderr, "%s:%s\n", kPrefix, marker);
  std::fflush(stderr);
}

int Fail(const char* stage) {
  std::fprintf(stderr, "%s:FAIL stage=%s\n", kPrefix, stage);
  std::fflush(stderr);
  return 1;
}

// The audio manager owns work on a separate sequence.  These objects must
// therefore remain live if one of the bounded waits below times out: the
// already-posted task is allowed to finish before AudioManager::Shutdown()
// joins its thread.
class FiniteSource final : public media::AudioOutputStream::AudioSourceCallback,
                           public base::RefCountedThreadSafe<FiniteSource> {
 public:
  FiniteSource() = default;

  int OnMoreData(base::TimeDelta /*delay*/,
                 base::TimeTicks /*delay_timestamp*/,
                 const media::AudioGlitchInfo& /*glitch_info*/,
                 media::AudioBus* dest) override {
    const uint32_t already_produced = produced_frames_.load(std::memory_order_relaxed);
    if (already_produced >= kTotalFrames) {
      return 0;
    }

    const uint32_t frames = std::min<uint32_t>(
        static_cast<uint32_t>(dest->frames()), kTotalFrames - already_produced);
    for (int channel = 0; channel < dest->channels(); ++channel) {
      for (uint32_t frame = 0; frame < frames; ++frame) {
        const uint32_t absolute = already_produced + frame;
        const float sample = ((absolute / 32) & 1) == 0 ? 0.20f : -0.20f;
        dest->channel(channel)[frame] = channel == 0 ? sample : -sample;
      }
    }

    const uint32_t total =
        produced_frames_.fetch_add(frames, std::memory_order_release) + frames;
    if (total == kTotalFrames) {
      completed_.Signal();
    }
    return static_cast<int>(frames);
  }

  void OnError(ErrorType type) override {
    error_.store(true, std::memory_order_release);
    completed_.Signal();
  }

  bool WaitForCompletion(base::TimeDelta timeout) {
    return completed_.TimedWait(timeout) &&
           !error_.load(std::memory_order_acquire) &&
           produced_frames_.load(std::memory_order_acquire) == kTotalFrames;
  }

 private:
  friend class base::RefCountedThreadSafe<FiniteSource>;

  ~FiniteSource() override = default;

  std::atomic<uint32_t> produced_frames_{0};
  std::atomic<bool> error_{false};
  base::WaitableEvent completed_;
};

class StreamState final : public base::RefCountedThreadSafe<StreamState> {
 public:
  media::AudioOutputStream* stream = nullptr;
  media::AudioOutputStreamWasm* wasm_stream = nullptr;
  bool opened = false;
  bool started = false;

 private:
  friend class base::RefCountedThreadSafe<StreamState>;

  ~StreamState() = default;
};

class OperationCompletion final
    : public base::RefCountedThreadSafe<OperationCompletion> {
 public:
  OperationCompletion() = default;

  void Signal() { completed_.Signal(); }

  bool TimedWait(base::TimeDelta timeout) {
    return completed_.TimedWait(timeout);
  }

 private:
  friend class base::RefCountedThreadSafe<OperationCompletion>;

  ~OperationCompletion() = default;

  base::WaitableEvent completed_;
};

enum class OperationResult {
  kSuccess,
  kCompletedFailure,
  kPostRejected,
  kTimedOut,
};

bool RequiresTerminalTombstone(OperationResult result) {
  return result == OperationResult::kPostRejected ||
         result == OperationResult::kTimedOut;
}

OperationResult PostOpen(media::AudioManager* manager,
                         scoped_refptr<StreamState> state) {
  scoped_refptr<OperationCompletion> completion =
      base::MakeRefCounted<OperationCompletion>();
  if (!manager->GetTaskRunner()->PostTask(
          FROM_HERE,
          base::BindOnce(
              [](media::AudioManager* manager, scoped_refptr<StreamState> state,
                 scoped_refptr<OperationCompletion> completion) {
                const media::AudioParameters params(
                    media::AudioParameters::AUDIO_PCM_LOW_LATENCY,
                    media::ChannelLayoutConfig::Stereo(),
                    media::wasm_audio::kSampleRate,
                    media::wasm_audio::kFramesPerBuffer);
                state->stream = manager->MakeAudioOutputStream(
                    params, media::AudioDeviceDescription::kDefaultDeviceId,
                    media::AudioManager::LogCallback());
                if (state->stream && state->stream->Open()) {
                  state->opened = true;
                  // This is the sole supported platform implementation for
                  // these exact parameters, as constrained by AudioManagerWasm.
                  state->wasm_stream =
                      static_cast<media::AudioOutputStreamWasm*>(state->stream);
                } else if (state->stream) {
                  // AudioOutputStream requires Close() after a failed Open().
                  state->stream->Close();
                  state->stream = nullptr;
                }
                completion->Signal();
              },
              manager, state, completion))) {
    return OperationResult::kPostRejected;
  }
  if (!completion->TimedWait(kAudioTimeout)) {
    return OperationResult::kTimedOut;
  }
  return state->opened && state->wasm_stream != nullptr
             ? OperationResult::kSuccess
             : OperationResult::kCompletedFailure;
}

OperationResult PostStart(media::AudioManager* manager,
                          scoped_refptr<FiniteSource> source,
                          scoped_refptr<StreamState> state) {
  scoped_refptr<OperationCompletion> completion =
      base::MakeRefCounted<OperationCompletion>();
  if (!manager->GetTaskRunner()->PostTask(
          FROM_HERE,
          base::BindOnce(
              [](scoped_refptr<FiniteSource> source,
                 scoped_refptr<StreamState> state,
                 scoped_refptr<OperationCompletion> completion) {
                if (state->stream && state->wasm_stream) {
                  // Keep the complete SetVolume/GetVolume/Start transaction on
                  // AudioManager's sequence. The fixed source writes +/-0.20,
                  // so the worklet can later prove the expected +/-0.10 stereo
                  // samples without exporting any samples from the host.
                  state->stream->SetVolume(kFixedStreamGain);
                  double observed_stream_gain = 0.0;
                  state->stream->GetVolume(&observed_stream_gain);
                  if (std::abs(observed_stream_gain - kFixedStreamGain) <=
                      kFixedStreamGainTolerance) {
                    state->stream->Start(source.get());
                    state->started = true;
                  }
                }
                completion->Signal();
              },
              source, state, completion))) {
    return OperationResult::kPostRejected;
  }
  if (!completion->TimedWait(kAudioTimeout)) {
    return OperationResult::kTimedOut;
  }
  return state->started ? OperationResult::kSuccess
                        : OperationResult::kCompletedFailure;
}

OperationResult PostStopAndClose(media::AudioManager* manager,
                                 scoped_refptr<StreamState> state) {
  scoped_refptr<OperationCompletion> completion =
      base::MakeRefCounted<OperationCompletion>();
  if (!manager->GetTaskRunner()->PostTask(
          FROM_HERE,
          base::BindOnce(
              [](scoped_refptr<StreamState> state,
                 scoped_refptr<OperationCompletion> completion) {
                if (state->stream) {
                  state->stream->Stop();
                  state->stream->Close();
                  state->stream = nullptr;
                  state->wasm_stream = nullptr;
                }
                completion->Signal();
              },
              state, completion))) {
    return OperationResult::kPostRejected;
  }
  return completion->TimedWait(kAudioTimeout) ? OperationResult::kSuccess
                                               : OperationResult::kTimedOut;
}

bool WaitForHostStart(const media::AudioOutputStreamWasm* stream) {
  if (!stream) {
    return false;
  }
  const base::TimeTicks deadline = base::TimeTicks::Now() + kAudioTimeout;
  while (base::TimeTicks::Now() < deadline) {
    if (stream->IsHostStartedForTesting()) {
      return true;
    }
    emscripten_thread_sleep(5);
  }
  return false;
}

bool WaitForDrained(const media::AudioOutputStreamWasm* stream) {
  const base::TimeTicks deadline = base::TimeTicks::Now() + kAudioTimeout;
  while (base::TimeTicks::Now() < deadline) {
    if (stream->GetConsumedFramesForTesting() >= kTotalFrames &&
        stream->IsHostDrainedForTesting()) {
      return true;
    }
    emscripten_thread_sleep(2);
  }
  return false;
}

// AudioThreadImpl creates AudioThreadHangMonitor, which posts its timer work
// through base::ThreadPool.  This standalone browser smoke therefore needs the
// same minimal base process bootstrap as other Wasm smoke executables; Chrome
// proper provides it before AudioManager construction.
class ThreadPoolForSmoke final {
 public:
  ThreadPoolForSmoke() {
    base::ThreadPoolInstance::CreateAndStartWithDefaultParams(
        "wasm_audio_manager_output_smoke");
  }

  ThreadPoolForSmoke(const ThreadPoolForSmoke&) = delete;
  ThreadPoolForSmoke& operator=(const ThreadPoolForSmoke&) = delete;

  ~ThreadPoolForSmoke() {
    base::ThreadPoolInstance* thread_pool = base::ThreadPoolInstance::Get();
    CHECK(thread_pool);
    thread_pool->Shutdown();
  }
};

// AudioManager may not be deleted after Shutdown() reports that its audio
// thread is hung.  A timed-out task can still hold the stream's callback and
// state, so the terminal path must retain the whole run rather than leaving a
// queued audio-thread task with dangling smoke-owned pointers.  The enclosing
// Wasm module is about to exit in that case, making this a deliberately
// bounded terminal tombstone rather than a normal lifecycle mechanism.
class TerminalAudioTombstone final {
 public:
  TerminalAudioTombstone(std::unique_ptr<ThreadPoolForSmoke> thread_pool,
                         std::unique_ptr<media::FakeAudioLogFactory> log_factory,
                         std::unique_ptr<media::AudioManager> manager,
                         scoped_refptr<FiniteSource> source,
                         scoped_refptr<StreamState> state)
      : thread_pool_(std::move(thread_pool)),
        log_factory_(std::move(log_factory)),
        manager_(std::move(manager)),
        source_(std::move(source)),
        state_(std::move(state)) {}

  TerminalAudioTombstone(const TerminalAudioTombstone&) = delete;
  TerminalAudioTombstone& operator=(const TerminalAudioTombstone&) = delete;

 private:
  // Member order keeps all process state alive until manager destruction.  If
  // this terminal object is ever reclaimed, destruction runs state/source,
  // manager, factory, then ThreadPool; the normal timeout path deliberately
  // retains it, rather than shutting down a pool underneath a live manager.
  const std::unique_ptr<ThreadPoolForSmoke> thread_pool_;
  const std::unique_ptr<media::FakeAudioLogFactory> log_factory_;
  const std::unique_ptr<media::AudioManager> manager_;
  const scoped_refptr<FiniteSource> source_;
  const scoped_refptr<StreamState> state_;
};

void RetainTerminalAudioRun(
    std::unique_ptr<ThreadPoolForSmoke>* thread_pool,
    std::unique_ptr<media::AudioManager>* manager,
    std::unique_ptr<media::FakeAudioLogFactory>* log_factory,
    scoped_refptr<FiniteSource>* source,
    scoped_refptr<StreamState>* state) {
  CHECK(thread_pool);
  CHECK(manager);
  CHECK(log_factory);
  CHECK(source);
  CHECK(state);
  static_cast<void>(new TerminalAudioTombstone(
      std::move(*thread_pool), std::move(*log_factory), std::move(*manager),
      std::move(*source), std::move(*state)));
}

bool ShutdownAudioManagerForSmoke(
    std::unique_ptr<ThreadPoolForSmoke>* thread_pool,
    std::unique_ptr<media::AudioManager>* manager,
    std::unique_ptr<media::FakeAudioLogFactory>* log_factory,
    scoped_refptr<FiniteSource>* source,
    scoped_refptr<StreamState>* state) {
  CHECK(thread_pool);
  CHECK(manager);
  CHECK(log_factory);
  CHECK(source);
  CHECK(state);
  if (!*manager) {
    return true;
  }

  // A successful shutdown joins the audio sequence.  Even then, retain the
  // manager if its last queued Stop()/Close() did not clear the output stream:
  // AudioManagerBase's destructor DCHECKs that no output stream remains.
  if (!(*manager)->Shutdown() || ((*state) && (*state)->stream)) {
    RetainTerminalAudioRun(thread_pool, manager, log_factory, source, state);
    return false;
  }
  manager->reset();
  return true;
}

}  // namespace

int main(int argc, char** argv) {
  if (!emscripten_has_threading_support()) {
    return Fail("pthread");
  }

  base::AtExitManager at_exit_manager;
  base::CommandLine::Init(argc, argv);
  base::SingleThreadTaskExecutor application_executor(
      base::MessagePumpType::DEFAULT);
  std::unique_ptr<ThreadPoolForSmoke> thread_pool =
      std::make_unique<ThreadPoolForSmoke>();

  // The trusted handler itself owns AudioContext creation/resume.  The native
  // side first opens and registers its ring, which lets the host construct the
  // AudioWorklet before the physical click arms this stream.
  EmitMarker("READY");

  std::unique_ptr<media::FakeAudioLogFactory> log_factory =
      std::make_unique<media::FakeAudioLogFactory>();
  std::unique_ptr<media::AudioManager> manager = media::AudioManager::Create(
      std::make_unique<media::AudioThreadImpl>(), log_factory.get());
  if (!manager) {
    return Fail("manager");
  }

  scoped_refptr<FiniteSource> source = base::MakeRefCounted<FiniteSource>();
  scoped_refptr<StreamState> state = base::MakeRefCounted<StreamState>();
  const OperationResult open_result = PostOpen(manager.get(), state);
  if (open_result != OperationResult::kSuccess) {
    // Do not turn the bounded Open() wait into an unbounded manager shutdown:
    // an in-flight synchronous host bridge can still own the audio sequence.
    // Retaining the terminal run keeps its manager, factory, callback state,
    // and ThreadPool alive until module exit.
    if (RequiresTerminalTombstone(open_result)) {
      RetainTerminalAudioRun(&thread_pool, &manager, &log_factory, &source,
                             &state);
      return Fail("open");
    }
    const OperationResult stop_result = PostStopAndClose(manager.get(), state);
    if (RequiresTerminalTombstone(stop_result)) {
      RetainTerminalAudioRun(&thread_pool, &manager, &log_factory, &source,
                             &state);
      return Fail("open");
    }
    if (!ShutdownAudioManagerForSmoke(&thread_pool, &manager, &log_factory,
                                      &source, &state)) {
      return Fail("shutdown");
    }
    return Fail("open");
  }
  EmitMarker("OPENED");

  if (!WaitForHostStart(state->wasm_stream)) {
    // A host-start timeout leaves an outer-page operation outstanding.  Keep
    // this terminal failure bounded rather than synchronously waiting for an
    // audio sequence that could be blocked in a proxied host call.
    RetainTerminalAudioRun(&thread_pool, &manager, &log_factory, &source,
                           &state);
    return Fail("start");
  }

  const OperationResult start_result = PostStart(manager.get(), source, state);
  if (start_result != OperationResult::kSuccess) {
    if (RequiresTerminalTombstone(start_result)) {
      RetainTerminalAudioRun(&thread_pool, &manager, &log_factory, &source,
                             &state);
      return Fail("start");
    }
    const OperationResult stop_result = PostStopAndClose(manager.get(), state);
    if (RequiresTerminalTombstone(stop_result)) {
      RetainTerminalAudioRun(&thread_pool, &manager, &log_factory, &source,
                             &state);
      return Fail("start");
    }
    if (!ShutdownAudioManagerForSmoke(&thread_pool, &manager, &log_factory,
                                      &source, &state)) {
      return Fail("shutdown");
    }
    return Fail("start");
  }
  EmitMarker("STARTED");

  if (!source->WaitForCompletion(kAudioTimeout) || !state->wasm_stream ||
      !WaitForDrained(state->wasm_stream)) {
    // Completion/drain timeouts can coincide with an active FakeAudioWorker
    // callback or a proxied worklet state update.  Preserve the whole
    // terminal run instead of attempting a potentially unbounded teardown.
    RetainTerminalAudioRun(&thread_pool, &manager, &log_factory, &source,
                           &state);
    return Fail("drain");
  }
  EmitMarker("DRAINED");

  const OperationResult stop_result = PostStopAndClose(manager.get(), state);
  if (stop_result != OperationResult::kSuccess) {
    if (RequiresTerminalTombstone(stop_result)) {
      RetainTerminalAudioRun(&thread_pool, &manager, &log_factory, &source,
                             &state);
      return Fail("stop");
    }
    if (!ShutdownAudioManagerForSmoke(&thread_pool, &manager, &log_factory,
                                      &source, &state)) {
      return Fail("shutdown");
    }
    return Fail("stop");
  }
  EmitMarker("STOPPED");
  EmitMarker("CLOSED");

  if (!ShutdownAudioManagerForSmoke(&thread_pool, &manager, &log_factory,
                                    &source, &state)) {
    return Fail("shutdown");
  }
  return 0;
}
