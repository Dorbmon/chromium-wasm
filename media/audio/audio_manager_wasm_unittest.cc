// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "media/audio/audio_manager.h"

#include <memory>

#include "base/test/test_message_loop.h"
#include "media/audio/audio_device_description.h"
#include "media/audio/audio_device_info_accessor_for_tests.h"
#include "media/audio/test_audio_thread.h"
#include "media/base/audio_parameters.h"
#include "media/base/channel_layout.h"
#include "testing/gtest/include/gtest/gtest.h"

namespace media {

namespace {

class AudioManagerWasmTest : public testing::Test {
 protected:
  AudioManagerWasmTest()
      : message_loop_(base::MessagePumpType::IO),
        audio_manager_(
            AudioManager::CreateForTesting(std::make_unique<TestAudioThread>())),
        device_info_(audio_manager_.get()) {}

  ~AudioManagerWasmTest() override { EXPECT_TRUE(audio_manager_->Shutdown()); }

  base::TestMessageLoop message_loop_;
  std::unique_ptr<AudioManager> audio_manager_;
  AudioDeviceInfoAccessorForTests device_info_;
};

TEST_F(AudioManagerWasmTest, ReportsUnavailableDevicesAndParameters) {
  EXPECT_EQ("WebAssembly", audio_manager_->GetName());
  EXPECT_FALSE(device_info_.HasAudioInputDevices());
  EXPECT_FALSE(device_info_.HasAudioOutputDevices());

  AudioDeviceDescriptions input_devices;
  AudioDeviceDescriptions output_devices;
  device_info_.GetAudioInputDeviceDescriptions(&input_devices);
  device_info_.GetAudioOutputDeviceDescriptions(&output_devices);
  EXPECT_TRUE(input_devices.empty());
  EXPECT_TRUE(output_devices.empty());

  const AudioParameters unavailable =
      AudioParameters::UnavailableDeviceParams();
  EXPECT_TRUE(device_info_
                  .GetInputStreamParameters(
                      AudioDeviceDescription::kDefaultDeviceId)
                  .Equals(unavailable));
  EXPECT_TRUE(device_info_
                  .GetOutputStreamParameters(
                      AudioDeviceDescription::kDefaultDeviceId)
                  .Equals(unavailable));
}

TEST_F(AudioManagerWasmTest, RejectsEveryStreamCreationPath) {
  const AudioParameters params(AudioParameters::AUDIO_PCM_LOW_LATENCY,
                               ChannelLayoutConfig::Stereo(), 48000, 480);
  const std::string device_id = AudioDeviceDescription::kDefaultDeviceId;

  EXPECT_EQ(nullptr,
            audio_manager_->MakeAudioOutputStream(
                params, device_id, AudioManager::LogCallback()));
  EXPECT_EQ(nullptr,
            audio_manager_->MakeAudioOutputStreamProxy(params, device_id));
  EXPECT_EQ(nullptr,
            audio_manager_->MakeAudioInputStream(
                params, device_id, AudioManager::LogCallback()));

  const AudioParameters unavailable =
      AudioParameters::UnavailableDeviceParams();
  EXPECT_EQ(nullptr,
            audio_manager_->MakeAudioOutputStream(
                unavailable, device_id, AudioManager::LogCallback()));
  EXPECT_EQ(nullptr,
            audio_manager_->MakeAudioInputStream(
                unavailable, device_id, AudioManager::LogCallback()));
}

}  // namespace

}  // namespace media
