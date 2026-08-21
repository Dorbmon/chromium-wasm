// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "media/audio/audio_manager_base.h"

#include <memory>
#include <utility>

#include "base/check.h"
#include "media/audio/audio_device_description.h"
#include "media/audio/audio_device_name.h"
#include "media/audio/audio_output_stream_wasm.h"
#include "media/audio/wasm_audio_bridge.h"
#include "media/base/channel_layout.h"
#include "media/base/audio_parameters.h"

namespace media {

namespace {

bool IsSupportedOutputParameters(const AudioParameters& params) {
  return params.format() == AudioParameters::AUDIO_PCM_LOW_LATENCY &&
         params.channels() == static_cast<int>(wasm_audio::kChannels) &&
         params.sample_rate() == static_cast<int>(wasm_audio::kSampleRate) &&
         params.frames_per_buffer() ==
             static_cast<int>(wasm_audio::kFramesPerBuffer);
}

AudioParameters SupportedOutputParameters() {
  return AudioParameters(AudioParameters::AUDIO_PCM_LOW_LATENCY,
                         ChannelLayoutConfig::Stereo(),
                         wasm_audio::kSampleRate,
                         wasm_audio::kFramesPerBuffer);
}

// The Wasm platform exposes one output device only while the outer page has
// already completed its trusted-user-gesture WebAudio handshake.  A missing or
// unarmed bridge remains an unavailable device rather than a fake audio path.
// Input, output proxies, and device-change policy deliberately remain outside
// this narrow M8 bridge.
class AudioManagerWasm final : public AudioManagerBase {
 public:
  AudioManagerWasm(std::unique_ptr<AudioThread> audio_thread,
                   AudioLogFactory* audio_log_factory)
      : AudioManagerBase(std::move(audio_thread), audio_log_factory) {
    SetMaxOutputStreamsAllowed(1);
  }

  AudioManagerWasm(const AudioManagerWasm&) = delete;
  AudioManagerWasm& operator=(const AudioManagerWasm&) = delete;

  ~AudioManagerWasm() override = default;

  AudioOutputStream* MakeAudioOutputStream(
      const AudioParameters& params,
      const std::string& device_id,
      const LogCallback& log_callback) override {
    CHECK(GetTaskRunner()->BelongsToCurrentThread());
    // Do not delegate unsupported formats to AudioManagerBase: it accepts
    // AUDIO_FAKE, which would claim a stream without a WebAudio data path.
    if (!AudioDeviceDescription::IsDefaultDevice(device_id) ||
        !IsSupportedOutputParameters(params)) {
      return nullptr;
    }
    return AudioManagerBase::MakeAudioOutputStream(params, device_id,
                                                    log_callback);
  }

  AudioOutputStream* MakeAudioOutputStreamProxy(
      const AudioParameters& params,
      const std::string& device_id) override {
    CHECK(GetTaskRunner()->BelongsToCurrentThread());
    return nullptr;
  }

  AudioInputStream* MakeAudioInputStream(
      const AudioParameters& params,
      const std::string& device_id,
      const LogCallback& log_callback) override {
    CHECK(GetTaskRunner()->BelongsToCurrentThread());
    return nullptr;
  }

  bool HasAudioOutputDevices() override {
    CHECK(GetTaskRunner()->BelongsToCurrentThread());
    return wasm_audio::IsOutputArmed();
  }

  bool HasAudioInputDevices() override {
    CHECK(GetTaskRunner()->BelongsToCurrentThread());
    return false;
  }

  const std::string_view GetName() override { return "WebAssembly"; }

 protected:
  bool GetAudioInputDeviceNames(AudioDeviceNames* device_names) override {
    CHECK(GetTaskRunner()->BelongsToCurrentThread());
    CHECK(device_names->empty());
    return true;
  }

  bool GetAudioOutputDeviceNames(AudioDeviceNames* device_names) override {
    CHECK(GetTaskRunner()->BelongsToCurrentThread());
    CHECK(device_names->empty());
    if (wasm_audio::IsOutputArmed()) {
      device_names->push_back(AudioDeviceName::CreateDefault());
    }
    return true;
  }

  AudioOutputStream* MakeLinearOutputStream(
      const AudioParameters& params,
      const LogCallback& log_callback) override {
    return nullptr;
  }

  AudioOutputStream* MakeLowLatencyOutputStream(
      const AudioParameters& params,
      const std::string& device_id,
      const LogCallback& log_callback) override {
    CHECK(GetTaskRunner()->BelongsToCurrentThread());
    if (!AudioDeviceDescription::IsDefaultDevice(device_id) ||
        !IsSupportedOutputParameters(params)) {
      return nullptr;
    }
    return new AudioOutputStreamWasm(this, params);
  }

  AudioInputStream* MakeLinearInputStream(
      const AudioParameters& params,
      const std::string& device_id,
      const LogCallback& log_callback) override {
    return nullptr;
  }

  AudioInputStream* MakeLowLatencyInputStream(
      const AudioParameters& params,
      const std::string& device_id,
      const LogCallback& log_callback) override {
    return nullptr;
  }

  AudioParameters GetInputStreamParameters(
      const std::string& device_id) override {
    CHECK(GetTaskRunner()->BelongsToCurrentThread());
    return AudioParameters::UnavailableDeviceParams();
  }

  AudioParameters GetPreferredOutputStreamParameters(
      const std::string& output_device_id,
      const AudioParameters& input_params) override {
    CHECK(GetTaskRunner()->BelongsToCurrentThread());
    if (!wasm_audio::IsOutputArmed() ||
        !AudioDeviceDescription::IsDefaultDevice(output_device_id)) {
      return AudioParameters::UnavailableDeviceParams();
    }
    return SupportedOutputParameters();
  }
};

}  // namespace

std::unique_ptr<AudioManager> CreateAudioManager(
    std::unique_ptr<AudioThread> audio_thread,
    AudioLogFactory* audio_log_factory) {
  return std::make_unique<AudioManagerWasm>(std::move(audio_thread),
                                            audio_log_factory);
}

}  // namespace media
