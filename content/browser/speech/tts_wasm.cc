// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "content/browser/speech/tts_platform_impl.h"

#include <utility>

#include "base/functional/callback.h"
#include "base/no_destructor.h"

namespace content {

// The M3 Wasm host bridge does not expose a speech synthesis service. Keep the
// native platform boundary present so Content can query it, while reporting
// every operation as explicitly unsupported.
class TtsPlatformImplWasm final : public TtsPlatformImpl {
 public:
  TtsPlatformImplWasm() = default;
  TtsPlatformImplWasm(const TtsPlatformImplWasm&) = delete;
  TtsPlatformImplWasm& operator=(const TtsPlatformImplWasm&) = delete;

  bool PlatformImplSupported() override { return false; }
  bool PlatformImplInitialized() override { return false; }

  void Speak(
      int utterance_id,
      const std::string& utterance,
      const std::string& lang,
      const VoiceData& voice,
      const UtteranceContinuousParameters& params,
      base::OnceCallback<void(bool)> did_start_speaking_callback) override {
    std::move(did_start_speaking_callback).Run(false);
  }

  bool StopSpeaking() override { return false; }
  bool IsSpeaking() override { return false; }

  void GetVoices(std::vector<VoiceData>* out_voices) override {
    // The unavailable platform contributes no voices to the caller's list.
  }

  void Pause() override {}
  void Resume() override {}

  static TtsPlatformImplWasm* GetInstance() {
    static base::NoDestructor<TtsPlatformImplWasm> tts_platform;
    return tts_platform.get();
  }
};

// static
TtsPlatformImpl* TtsPlatformImpl::GetInstance() {
  return TtsPlatformImplWasm::GetInstance();
}

}  // namespace content
