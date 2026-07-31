#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from pathlib import Path
import unittest


ROOT_DIR = Path(__file__).resolve().parents[3]


def source(path: str) -> str:
    return (ROOT_DIR / path).read_text(encoding="utf-8")


class M3MediaSourceContractTest(unittest.TestCase):
    def test_webaudio_keeps_intentional_denormal_scopes(self) -> None:
        denormal_header = source(
            "third_party/blink/renderer/platform/audio/"
            "denormal_disabler.h"
        )
        destinations = (
            (
                "offline",
                source(
                    "third_party/blink/renderer/modules/webaudio/"
                    "offline_audio_destination_handler.cc"
                ),
            ),
            (
                "realtime",
                source(
                    "third_party/blink/renderer/modules/webaudio/"
                    "realtime_audio_destination_handler.cc"
                ),
            ),
        )

        for name, destination in destinations:
            with self.subTest(destination=name):
                self.assertIn(
                    "[[maybe_unused]] DenormalDisabler "
                    "denormal_disabler;",
                    destination,
                )
        unsupported_architecture = denormal_header.split(
            "#else\n"
            "// FIXME: add implementations for other architectures and "
            "compilers",
            1,
        )[1].split("#endif", 1)[0]
        self.assertIn(
            "DenormalDisabler() = default;\n"
            "  ~DenormalDisabler() = default;",
            unsupported_architecture,
        )
        self.assertIn(
            "return (fabs(f) < FLT_MIN) ? 0.0f : f;",
            unsupported_architecture,
        )

    def test_thread_wrapper_defers_wasm_sockets_to_wisp(self) -> None:
        wrapper = source("components/webrtc/thread_wrapper.cc")
        overrides = source("third_party/webrtc_overrides/BUILD.gn")
        rtc_base_build = source("third_party/webrtc/rtc_base/BUILD.gn")
        null_server = source(
            "third_party/webrtc/rtc_base/null_socket_server.cc"
        )

        self.assertIn(
            "#if BUILDFLAG(IS_WASM)\n"
            '#include "third_party/webrtc/rtc_base/null_socket_server.h"\n'
            "#else\n"
            '#include "third_party/webrtc/rtc_base/'
            'physical_socket_server.h"\n'
            "#endif",
            wrapper,
        )
        socket_factory = wrapper.split(
            "std::unique_ptr<SocketServer> "
            "CreateThreadWrapperSocketServer() {",
            1,
        )[1].split("}", 1)[0]
        self.assertIn(
            "#if BUILDFLAG(IS_WASM)\n"
            "  return std::make_unique<NullSocketServer>();\n"
            "#else\n"
            "  return std::make_unique<PhysicalSocketServer>();\n"
            "#endif",
            socket_factory,
        )
        self.assertIn(
            ": Thread(CreateThreadWrapperSocketServer()),",
            wrapper,
        )
        wasm_deps = overrides.split("if (is_wasm) {", 1)[1].split(
            "}", 1
        )[0]
        self.assertIn(
            "//third_party/webrtc/rtc_base:null_socket_server",
            wasm_deps,
        )
        threading_target = rtc_base_build.split(
            'rtc_library("threading") {', 1
        )[1].split('rtc_source_set("socket_factory")', 1)[0]
        native_threading_sources = threading_target.split(
            "  if (!is_wasm) {", 1
        )[1].split("  }", 1)[0]
        for physical_source in (
            "physical_socket_server.cc",
            "physical_socket_server.h",
        ):
            with self.subTest(physical_source=physical_source):
                self.assertIn(physical_source, native_threading_sources)
                self.assertNotIn(
                    physical_source,
                    threading_target.split("  if (!is_wasm) {", 1)[0],
                )
        self.assertIn(
            "RTC_DCHECK_NOTREACHED();\n  return nullptr;",
            null_server,
        )

    def test_blink_webrtc_exports_its_webrtc_dependency(self) -> None:
        build = source(
            "third_party/blink/renderer/modules/webrtc/BUILD.gn"
        )
        audio_device = source(
            "third_party/blink/renderer/modules/webrtc/"
            "webrtc_audio_device_not_impl.h"
        )
        audio_renderer = source(
            "third_party/blink/renderer/modules/webrtc/"
            "webrtc_audio_renderer.cc"
        )
        forwarding_header = source(
            "third_party/webrtc/modules/audio_device/include/audio_device.h"
        )

        self.assertIn(
            'public_deps = '
            '[ "//third_party/webrtc_overrides:webrtc_component" ]',
            build,
        )
        self.assertEqual(
            build.count(
                "//third_party/webrtc_overrides:webrtc_component"
            ),
            1,
        )
        private_deps = build.split("  deps = [", 1)[1].split("]", 1)[0]
        self.assertNotIn(
            "//third_party/webrtc_overrides:webrtc_component",
            private_deps,
        )
        self.assertIn(
            '#include "third_party/webrtc/modules/audio_device/include/'
            'audio_device.h"',
            audio_device,
        )
        self.assertIn(
            '#include "api/audio/audio_device.h"',
            forwarding_header,
        )
        self.assertIn(
            '#include "third_party/webrtc/api/media_stream_interface.h"',
            audio_renderer,
        )

    def test_generated_module_bindings_import_webrtc_config(self) -> None:
        build = source(
            "third_party/blink/renderer/bindings/modules/v8/BUILD.gn"
        )
        rtc_certificate = source(
            "third_party/blink/renderer/modules/peerconnection/"
            "rtc_certificate.h"
        )
        rtc_data_channel = source(
            "third_party/blink/renderer/modules/peerconnection/"
            "rtc_data_channel.h"
        )
        webrtc_certificate = source(
            "third_party/webrtc/rtc_base/rtc_certificate.h"
        )
        webrtc_data_channel = source(
            "third_party/webrtc/api/data_channel_interface.h"
        )

        v8_target = build.split(
            'blink_modules_sources("v8") {', 1
        )[1].split('source_set("testing")', 1)[0]
        private_deps = v8_target.split("  deps = [", 1)[1].split(
            "  ]", 1
        )[0]
        self.assertIn(
            "//third_party/webrtc_overrides:webrtc_component",
            private_deps,
        )
        self.assertNotIn("public_deps", v8_target)
        self.assertIn(
            '#include "third_party/webrtc/rtc_base/rtc_certificate.h"',
            rtc_certificate,
        )
        self.assertIn(
            '#include "third_party/webrtc/api/data_channel_interface.h"',
            rtc_data_channel,
        )
        self.assertIn(
            '#include "api/ref_counted_base.h"', webrtc_certificate
        )
        self.assertIn('#include "api/priority.h"', webrtc_data_channel)

    def test_breakout_box_avoids_unused_webrtc_dependency(self) -> None:
        build = source(
            "third_party/blink/renderer/modules/breakout_box/BUILD.gn"
        )
        frame_source = source(
            "third_party/blink/renderer/modules/breakout_box/"
            "frame_queue_underlying_source.cc"
        )

        breakout_box_target = build.split(
            'blink_modules_sources("breakout_box") {', 1
        )[1].split('source_set("unit_tests")', 1)[0]
        self.assertNotIn("//third_party/webrtc", breakout_box_target)
        self.assertNotIn("frame_transformer_interface", frame_source)

    def test_media_capabilities_keeps_webrtc_implementation_private(
        self,
    ) -> None:
        build = source(
            "third_party/blink/renderer/modules/media_capabilities/BUILD.gn"
        )
        header = source(
            "third_party/blink/renderer/modules/media_capabilities/"
            "media_capabilities.h"
        )
        implementation = source(
            "third_party/blink/renderer/modules/media_capabilities/"
            "media_capabilities.cc"
        )
        unit_test = source(
            "third_party/blink/renderer/modules/media_capabilities/"
            "media_capabilities_test.cc"
        )

        target = build.split(
            'blink_modules_sources("media_capabilities") {', 1
        )[1].split(
            'fuzzable_proto_library("fuzzer_media_configuration_proto")',
            1,
        )[0]
        private_deps = target.split("  deps = [", 1)[1].split(
            "  ]", 1
        )[0]
        self.assertIn(
            "//third_party/webrtc_overrides:webrtc_component",
            private_deps,
        )
        self.assertNotIn("public_deps", target)

        handlers = (
            "webrtc_decoding_info_handler.h",
            "webrtc_encoding_info_handler.h",
        )
        for handler in handlers:
            with self.subTest(handler=handler):
                self.assertNotIn(handler, header)
                self.assertIn(handler, implementation)
                self.assertIn(handler, unit_test)
        self.assertIn("class WebrtcDecodingInfoHandler;", header)
        self.assertIn("class WebrtcEncodingInfoHandler;", header)
        self.assertIn(
            "third_party/webrtc/api/audio_codecs/audio_format.h",
            implementation,
        )
        self.assertIn(
            "third_party/webrtc/api/video_codecs/sdp_video_format.h",
            implementation,
        )

    def test_webrtc_factories_advertise_no_wasm_codecs(self) -> None:
        platform_build = source(
            "third_party/blink/renderer/platform/BUILD.gn"
        )
        audio_factory = source(
            "third_party/blink/renderer/platform/peerconnection/"
            "audio_codec_factory_wasm.cc"
        )
        video_factory = source(
            "third_party/blink/renderer/platform/peerconnection/"
            "video_codec_factory_wasm.cc"
        )

        wasm_sources = platform_build.split("if (is_wasm) {", 1)[1].split(
            "}", 1
        )[0]
        for native_source in (
            "peerconnection/audio_codec_factory.cc",
            "peerconnection/video_codec_factory.cc",
        ):
            with self.subTest(native_source=native_source):
                self.assertIn(native_source, wasm_sources)
        for wasm_source in (
            "peerconnection/audio_codec_factory_wasm.cc",
            "peerconnection/video_codec_factory_wasm.cc",
        ):
            with self.subTest(wasm_source=wasm_source):
                self.assertIn(wasm_source, wasm_sources)

        self.assertIn("AudioEncoderFactoryT<>>()", audio_factory)
        self.assertIn("AudioDecoderFactoryT<>>()", audio_factory)
        self.assertNotIn("AudioEncoderOpus", audio_factory)
        self.assertNotIn("AudioDecoderOpus", audio_factory)
        self.assertIn(
            "class UnavailableVideoEncoderFactory final", video_factory
        )
        self.assertIn(
            "class UnavailableVideoDecoderFactory final", video_factory
        )
        self.assertEqual(video_factory.count("return nullptr;"), 2)
        self.assertGreaterEqual(video_factory.count("return {};"), 4)

    def test_webrtc_concrete_codec_dependencies_are_native_only(self) -> None:
        overrides = source("third_party/webrtc_overrides/BUILD.gn")
        video_build = source("third_party/webrtc/video/BUILD.gn")
        receive_stream = source(
            "third_party/webrtc/video/video_receive_stream2.cc"
        )
        dependency_factory = source(
            "third_party/blink/renderer/modules/peerconnection/"
            "peer_connection_dependency_factory.cc"
        )
        native_deps = overrides.split("if (!is_wasm) {", 1)[1].split(
            "}", 1
        )[0]
        common_deps = overrides.split("if (!is_wasm) {", 1)[0]

        concrete_deps = (
            "//third_party/webrtc/api/audio_codecs/L16:audio_decoder_L16",
            "//third_party/webrtc/api/audio_codecs/g711:audio_encoder_g711",
            "//third_party/webrtc/api/audio_codecs/g722:audio_decoder_g722",
            "//third_party/webrtc/api/audio_codecs/opus:audio_encoder_opus",
            "//third_party/webrtc/api/video_codecs:"
            "builtin_video_decoder_factory",
            "//third_party/webrtc/media:rtc_internal_video_codecs",
            "//third_party/webrtc/modules/video_coding:webrtc_h264",
            "//third_party/webrtc/video:null_video_decoder",
        )
        for dependency in concrete_deps:
            with self.subTest(dependency=dependency):
                self.assertIn(dependency, native_deps)
                self.assertNotIn(dependency, common_deps)

        self.assertIn(
            "#if !BUILDFLAG(IS_WASM)\n"
            '#include "third_party/webrtc/media/engine/'
            'fake_video_codec_factory.h"',
            dependency_factory,
        )
        self.assertIn(
            "#if !BUILDFLAG(IS_WASM)\n"
            "  if (Platform::Current()->UsesFakeCodecForPeerConnection())",
            dependency_factory,
        )
        self.assertIn(
            'if (!is_wasm) {\n'
            '    deps += [ ":null_video_decoder" ]',
            video_build,
        )
        common_video_deps = video_build.split("if (!is_wasm) {", 1)[0]
        self.assertNotIn(":null_video_decoder", common_video_deps)
        self.assertIn(
            "#if !defined(WEBRTC_WASM)\n"
            '#include "video/null_video_decoder.h"  // nogncheck',
            receive_stream,
        )
        self.assertIn(
            "#if defined(WEBRTC_WASM)\n"
            '    RTC_LOG(LS_ERROR) << "Video decoder creation is unsupported '
            'on Wasm.";\n'
            "    return;",
            receive_stream,
        )
        wasm_failure = receive_stream.split(
            "#if defined(WEBRTC_WASM)", 1
        )[1].split("#else", 1)[0]
        self.assertNotIn("NullVideoDecoder", wasm_failure)

    def test_media_recorder_rejects_codec_capability_on_wasm(self) -> None:
        build = source(
            "third_party/blink/renderer/modules/mediarecorder/BUILD.gn"
        )
        handler = source(
            "third_party/blink/renderer/modules/mediarecorder/"
            "media_recorder_handler.cc"
        )
        audio_recorder = source(
            "third_party/blink/renderer/modules/mediarecorder/"
            "audio_track_recorder.cc"
        )
        video_recorder = source(
            "third_party/blink/renderer/modules/mediarecorder/"
            "video_track_recorder.cc"
        )

        native_sources = build.split("if (!is_wasm) {", 1)[1].split(
            "}", 1
        )[0]
        common_sources = build.split("if (!is_wasm) {", 1)[0]
        for concrete_source in (
            "audio_track_mojo_encoder.cc",
            "audio_track_opus_encoder.cc",
            "audio_track_pcm_encoder.cc",
            "//third_party/opus",
        ):
            with self.subTest(concrete_source=concrete_source):
                self.assertIn(concrete_source, native_sources)
                self.assertNotIn(concrete_source, common_sources)

        self.assertEqual(
            handler.count("#if BUILDFLAG(IS_WASM)\n  return false;"), 2
        )
        self.assertIn(
            "#if BUILDFLAG(IS_WASM)\n"
            "  return media::AudioCodec::kUnknown;",
            audio_recorder,
        )
        self.assertIn(
            "media::EncoderStatus::Codes::kEncoderUnsupportedConfig",
            audio_recorder,
        )
        self.assertIn(
            "#if BUILDFLAG(IS_WASM)\n"
            "  return media::VideoCodec::kUnknown;",
            video_recorder,
        )
        self.assertIn(
            "GetMediaVideoCodecProfileForSwEncoder(\n"
            "    media::VideoCodec codec) {\n"
            "#if BUILDFLAG(IS_WASM)\n"
            "  return std::nullopt;",
            video_recorder,
        )
        self.assertIn(
            "double framerate) {\n"
            "#if BUILDFLAG(IS_WASM)\n"
            "  return false;",
            video_recorder,
        )

    def test_webcodecs_audio_encoder_is_explicitly_unavailable(self) -> None:
        media_build = source("media/BUILD.gn")
        media_audio_build = source("media/audio/BUILD.gn")
        build = source(
            "third_party/blink/renderer/modules/webcodecs/BUILD.gn"
        )
        encoder = source(
            "third_party/blink/renderer/modules/webcodecs/audio_encoder.cc"
        )

        self.assertIn(
            'if (!is_wasm) {\n    deps += [ "//third_party/opus" ]',
            build,
        )
        self.assertIn(
            'if (is_wasm) {\n'
            '    sources -= [ "audio_encoder_test.cc" ]',
            build,
        )
        self.assertIn(
            "#if BUILDFLAG(IS_WASM)\n"
            "  static_cast<void>(config);\n"
            '  *js_error_message = "Audio encoding is unsupported on Wasm.";\n'
            "  return false;",
            encoder,
        )
        self.assertIn(
            "AudioEncoder::CreateMediaAudioEncoder(\n"
            "    const ParsedConfig& config) {\n"
            "#if BUILDFLAG(IS_WASM)\n"
            "  static_cast<void>(config);\n"
            "  return nullptr;",
            encoder,
        )
        self.assertIn(
            "#if !BUILDFLAG(IS_WASM)\n"
            "std::unique_ptr<media::AudioEncoder> "
            "CreateSoftwareAudioEncoder(",
            encoder,
        )
        native_audio = media_audio_build.split(
            "if (!is_wasm) {\n"
            "    sources += [\n"
            '      "audio_opus_encoder.cc",',
            1,
        )[1].split("}", 1)[0]
        self.assertIn("audio_opus_encoder.h", native_audio)
        self.assertIn("//third_party/opus", native_audio)
        self.assertNotIn(
            "audio_opus_encoder.cc",
            media_audio_build.split("if (!is_wasm) {", 1)[0],
        )
        self.assertIn(
            "if (!is_wasm) {\n"
            "    # The test needs OPUS_FIXED_POINT conditional define.\n"
            '    configs += [ "//third_party/opus:opus_config" ]',
            media_build,
        )

    def test_optional_codec_and_tflite_deps_stay_out_of_wasm(self) -> None:
        media_build = source("media/BUILD.gn")
        filters_build = source("media/filters/BUILD.gn")
        decoder_factory = source(
            "media/renderers/default_decoder_factory.cc"
        )
        video_build = source("media/video/BUILD.gn")
        webrtc_build = source("media/webrtc/BUILD.gn")
        helpers = source("media/webrtc/helpers.cc")
        modules_build = source(
            "third_party/blink/renderer/modules/BUILD.gn"
        )

        self.assertIn(
            'if (media_use_libvpx) {\n'
            "    sources += [\n"
            '      "alpha_video_encoder_wrapper_unittest.cc",\n'
            '      "software_video_encoder_test.cc",\n'
            "    ]\n"
            '    deps += [ "//third_party/libvpx" ]',
            video_build,
        )
        self.assertIn(
            "if (!is_fuchsia && !is_wasm) {\n"
            '    deps += [ "//components/optimization_guide/core/'
            'inference:op_resolver" ]',
            webrtc_build,
        )
        self.assertIn(
            "public_deps =\n"
            '      [ "//third_party/webrtc_overrides:webrtc_component" ]',
            webrtc_build,
        )
        private_deps = webrtc_build.split("  deps = [", 1)[1].split(
            "  ]", 1
        )[0]
        self.assertNotIn(
            "//third_party/webrtc_overrides:webrtc_component",
            private_deps,
        )
        self.assertIn(
            'if (!is_wasm) {\n'
            '    public_deps += [ "//third_party/tflite" ]',
            webrtc_build,
        )
        self.assertIn(
            "Neural residual echo estimation is unsupported on Wasm.",
            helpers,
        )
        self.assertIn(
            "BUILDFLAG(IS_CAST_ANDROID) || BUILDFLAG(IS_WASM)",
            helpers,
        )
        native_filters = filters_build.split(
            "if (!is_wasm) {\n"
            "    sources += [\n"
            '      "opus_audio_decoder.cc",',
            1,
        )[1].split("}", 1)[0]
        self.assertIn("opus_audio_decoder.h", native_filters)
        self.assertIn("//third_party/opus", native_filters)
        self.assertNotIn(
            "opus_audio_decoder.cc",
            filters_build.split("if (!is_wasm) {", 1)[0],
        )
        self.assertIn(
            'if (media_use_libvpx) {\n'
            '  fuzzer_test("media_vpx_video_decoder_fuzzer")',
            media_build,
        )
        self.assertIn(
            "#if !BUILDFLAG(IS_WASM)\n"
            '#include "media/filters/opus_audio_decoder.h"',
            decoder_factory,
        )
        self.assertIn(
            "#if !BUILDFLAG(IS_WASM)\n"
            "  if (base::FeatureList::IsEnabled("
            "kDirectOpusAudioDecoding))",
            decoder_factory,
        )
        wasm_test_selection = modules_build.split(
            "if (is_wasm) {\n    sources -= [\n"
            '      "mediarecorder/audio_track_mojo_encoder_unittest.cc",',
            1,
        )[1].split("}", 1)[0]
        self.assertIn(
            "mediarecorder/audio_track_recorder_unittest.cc",
            wasm_test_selection,
        )
        self.assertIn(
            "mediarecorder/video_track_recorder_unittest.cc",
            wasm_test_selection,
        )
        self.assertIn(
            'deps -= [ "//third_party/opus" ]', wasm_test_selection
        )


if __name__ == "__main__":
    unittest.main()
