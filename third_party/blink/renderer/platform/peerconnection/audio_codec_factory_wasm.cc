// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "third_party/blink/renderer/platform/peerconnection/audio_codec_factory.h"

#include "third_party/webrtc/api/audio_codecs/audio_decoder_factory_template.h"
#include "third_party/webrtc/api/audio_codecs/audio_encoder_factory_template.h"
#include "third_party/webrtc/api/make_ref_counted.h"

namespace blink {

webrtc::scoped_refptr<webrtc::AudioEncoderFactory>
CreateWebrtcAudioEncoderFactory() {
  return webrtc::make_ref_counted<
      webrtc::audio_encoder_factory_template_impl::AudioEncoderFactoryT<>>();
}

webrtc::scoped_refptr<webrtc::AudioDecoderFactory>
CreateWebrtcAudioDecoderFactory() {
  return webrtc::make_ref_counted<
      webrtc::audio_decoder_factory_template_impl::AudioDecoderFactoryT<>>();
}

}  // namespace blink
