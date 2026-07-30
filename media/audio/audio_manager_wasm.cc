// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "media/audio/audio_manager_base.h"

#include <memory>
#include <utility>

#include "base/check.h"
#include "media/base/audio_parameters.h"

namespace media {

namespace {

// M3 has no host audio bridge. Keep the platform factory available so browser
// services can initialize, while reporting the absence of devices and refusing
// every stream request. A later milestone will replace these semantics with
// asynchronous host-page audio imports.
class AudioManagerWasm final : public AudioManagerBase {
 public:
  AudioManagerWasm(std::unique_ptr<AudioThread> audio_thread,
                   AudioLogFactory* audio_log_factory)
      : AudioManagerBase(std::move(audio_thread), audio_log_factory) {}

  AudioManagerWasm(const AudioManagerWasm&) = delete;
  AudioManagerWasm& operator=(const AudioManagerWasm&) = delete;

  ~AudioManagerWasm() override = default;

  AudioOutputStream* MakeAudioOutputStream(
      const AudioParameters& params,
      const std::string& device_id,
      const LogCallback& log_callback) override {
    CHECK(GetTaskRunner()->BelongsToCurrentThread());
    return nullptr;
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
    return false;
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
    return nullptr;
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
    return AudioParameters::UnavailableDeviceParams();
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
