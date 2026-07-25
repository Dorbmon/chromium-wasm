// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "third_party/blink/renderer/platform/peerconnection/video_codec_factory.h"

#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "media/mojo/clients/mojo_video_encoder_metrics_provider.h"

namespace blink {

namespace {

// M3 keeps the WebRTC API and transport graph linkable, but media codecs are
// explicitly unsupported until the port supplies real implementations.
class UnavailableVideoEncoderFactory final
    : public webrtc::VideoEncoderFactory {
 public:
  std::vector<webrtc::SdpVideoFormat> GetSupportedFormats() const override {
    return {};
  }

  CodecSupport QueryCodecSupport(
      const webrtc::SdpVideoFormat&,
      std::optional<std::string>,
      std::optional<webrtc::Resolution>) const override {
    return {};
  }

  std::unique_ptr<webrtc::VideoEncoder> Create(
      const webrtc::Environment&,
      const webrtc::SdpVideoFormat&) override {
    return nullptr;
  }
};

class UnavailableVideoDecoderFactory final
    : public webrtc::VideoDecoderFactory {
 public:
  std::vector<webrtc::SdpVideoFormat> GetSupportedFormats() const override {
    return {};
  }

  CodecSupport QueryCodecSupport(
      const webrtc::SdpVideoFormat&,
      bool,
      std::optional<webrtc::Resolution>) const override {
    return {};
  }

  std::unique_ptr<webrtc::VideoDecoder> Create(
      const webrtc::Environment&,
      const webrtc::SdpVideoFormat&) override {
    return nullptr;
  }
};

}  // namespace

std::unique_ptr<webrtc::VideoEncoderFactory>
CreateWebrtcVideoEncoderFactory(
    media::GpuVideoAcceleratorFactories*,
    scoped_refptr<media::MojoVideoEncoderMetricsProviderFactory>,
    StatsCollector::StoreProcessingStatsCB) {
  return std::make_unique<UnavailableVideoEncoderFactory>();
}

std::unique_ptr<webrtc::VideoDecoderFactory>
CreateWebrtcVideoDecoderFactory(
    media::GpuVideoAcceleratorFactories*,
    const gfx::ColorSpace&,
    StatsCollector::StoreProcessingStatsCB) {
  return std::make_unique<UnavailableVideoDecoderFactory>();
}

std::unique_ptr<webrtc::VideoEncoderFactory>
CreateWebrtcVideoEncoderFactoryForUmaLogging(
    media::GpuVideoAcceleratorFactories*) {
  return std::make_unique<UnavailableVideoEncoderFactory>();
}

std::unique_ptr<webrtc::VideoDecoderFactory>
CreateWebrtcVideoDecoderFactoryForUmaLogging(
    media::GpuVideoAcceleratorFactories*,
    const gfx::ColorSpace&) {
  return std::make_unique<UnavailableVideoDecoderFactory>();
}

}  // namespace blink
