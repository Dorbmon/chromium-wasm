// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// A narrow M8.3 feature-boundary smoke for the Wasm media build. It verifies
// the media capability API's answer for three open video codecs with the
// currently selected no-software-video-decoder configuration. It does not
// create a WebContents, fetch media, demux a stream, decode a frame, render a
// frame, or establish browser media playback.

#include <cstdio>
#include <string>
#include <vector>

#include "base/at_exit.h"
#include "base/command_line.h"
#include "build/build_config.h"
#include "media/base/mime_util.h"
#include "media/base/supported_types.h"
#include "media/base/video_codecs.h"
#include "media/media_buildflags.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_software_video_capability_smoke must only be built for WebAssembly"
#endif

#if BUILDFLAG(IS_POSIX)
#error "WebAssembly must not inherit POSIX platform semantics"
#endif

namespace {

constexpr char kPrefix[] = "CHROMIUM_WASM_M8_SOFTWARE_VIDEO";

void Emit(const char* marker) {
  std::fprintf(stdout, "%s:%s\n", kPrefix, marker);
  std::fflush(stdout);
}

int Fail(const char* stage) {
  std::fprintf(stderr, "%s:FAIL stage=%s\n", kPrefix, stage);
  std::fflush(stderr);
  return 1;
}

const char* SupportsTypeName(media::SupportsType support) {
  switch (support) {
    case media::SupportsType::kNotSupported:
      return "not_supported";
    case media::SupportsType::kSupported:
      return "supported";
    case media::SupportsType::kMaybeSupported:
      return "maybe_supported";
  }
  return "invalid";
}

}  // namespace

int main(int argc, char** argv) {
  base::AtExitManager at_exit;
  base::CommandLine::Init(argc, argv);

  Emit("RUNTIME_START");

  // These build flags select every general-purpose software video decoder in
  // DefaultDecoderFactory. Do not replace this check with a host-page codec
  // probe: capability must come from Chromium's selected media closure.
  // Volatile prevents the current all-disabled configuration from turning the
  // following explicit failure boundary into an unreachable-code warning. A
  // profile that enables one of these decoders still builds this target and
  // reports its changed state rather than silently reusing this witness.
  const volatile bool software_decoder_buildflags_disabled =
      !BUILDFLAG(ENABLE_LIBVPX) &&
      !BUILDFLAG(ENABLE_FFMPEG_VIDEO_DECODERS) &&
      !BUILDFLAG(ENABLE_AV1_DECODER);
  if (!software_decoder_buildflags_disabled) {
    return Fail("software_decoder_unexpectedly_enabled");
  }
  if (media::IsDecoderBuiltInVideoCodec(media::VideoCodec::kVP8) ||
      media::IsDecoderBuiltInVideoCodec(media::VideoCodec::kVP9) ||
      media::IsDecoderBuiltInVideoCodec(media::VideoCodec::kAV1)) {
    return Fail("built_in_video_codec_unexpectedly_available");
  }
  Emit("PHASE name=software_decoder_buildflags status=disabled");

  const media::SupportsType vp8 =
      media::IsSupportedMediaFormat("video/webm", {"vp8"});
  const media::SupportsType vp9 =
      media::IsSupportedMediaFormat("video/webm", {"vp09.00.10.08"});
  const media::SupportsType av1 =
      media::IsSupportedMediaFormat("video/webm", {"av01.0.00M.08"});
  if (vp8 != media::SupportsType::kNotSupported ||
      vp9 != media::SupportsType::kNotSupported ||
      av1 != media::SupportsType::kNotSupported) {
    return Fail("mime_video_capability_unexpectedly_available");
  }
  Emit("PHASE name=video_mime_capabilities status=not_supported");

  std::fprintf(
      stdout,
      "%s:RESULT libvpx=disabled ffmpeg_video=disabled av1_decoder=disabled "
      "vp8=%s vp9=%s av1=%s browser_playback=not_proven "
      "webcodecs=not_proven\n",
      kPrefix, SupportsTypeName(vp8), SupportsTypeName(vp9),
      SupportsTypeName(av1));
  std::fflush(stdout);
  Emit("RUNTIME_END");
  Emit("PASS");
  return 0;
}
