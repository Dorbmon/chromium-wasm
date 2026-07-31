#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M3FeatureBoundarySourceContractTest(unittest.TestCase):
    def test_language_detection_is_explicitly_unavailable_on_wasm(
        self,
    ) -> None:
        core_build = source("components/language_detection/core/BUILD.gn")
        core_stub = source(
            "components/language_detection/core/"
            "language_detection_model_wasm.cc"
        )
        translate_build = source(
            "components/translate/core/language_detection/BUILD.gn"
        )
        translate_util = source(
            "components/translate/core/language_detection/"
            "language_detection_util.cc"
        )
        accessibility_build = source("ui/accessibility/BUILD.gn")
        accessibility_header = source(
            "ui/accessibility/ax_language_detection.h"
        )
        accessibility_impl = source(
            "ui/accessibility/ax_language_detection.cc"
        )

        self.assertIn(
            'if (is_wasm) {\n'
            '    sources += [ "language_detection_model_wasm.cc" ]',
            core_build,
        )
        self.assertIn('if (!is_wasm) {\n    deps += [', core_build)
        self.assertIn("//third_party/tflite", core_build)
        self.assertIn(
            'CHECK(IsAvailable()) << "language detection is unsupported '
            'on Wasm";',
            core_stub,
        )
        self.assertIn(
            "bool LanguageDetectionModel::IsAvailable() const", core_stub
        )
        self.assertIn('return "unsupported-wasm";', core_stub)
        self.assertIn(
            "base::ThreadPool::PostTaskAndReply(",
            core_stub,
        )
        self.assertIn('if (!is_wasm) {\n    deps += [', translate_build)
        self.assertIn("//third_party/cld_3", translate_build)
        self.assertIn("#if BUILDFLAG(IS_WASM)", translate_util)
        self.assertIn(
            "return language_detection::kUnknownLanguageCode;",
            translate_util,
        )
        self.assertIn(
            'if (!is_wasm) {\n'
            '    deps += [ "//third_party/cld_3/src/src:cld_3" ]',
            accessibility_build,
        )
        self.assertIn(
            "#if !BUILDFLAG(IS_WASM)\n"
            "  std::unique_ptr<chrome_lang_id::NNetLanguageIdentifier>",
            accessibility_header,
        )
        self.assertIn(
            "#if BUILDFLAG(IS_WASM)\n  return false;",
            accessibility_impl,
        )
        self.assertIn(
            "#if BUILDFLAG(IS_WASM)\n"
            "  return language_annotation;",
            accessibility_impl,
        )

    def test_webrtc_media_codecs_are_explicitly_unavailable_on_wasm(
        self,
    ) -> None:
        platform_build = source(
            "third_party/blink/renderer/platform/BUILD.gn"
        )
        webrtc_overrides = source("third_party/webrtc_overrides/BUILD.gn")
        audio_factory = source(
            "third_party/blink/renderer/platform/peerconnection/"
            "audio_codec_factory_wasm.cc"
        )
        video_factory = source(
            "third_party/blink/renderer/platform/peerconnection/"
            "video_codec_factory_wasm.cc"
        )
        dependency_factory = source(
            "third_party/blink/renderer/modules/peerconnection/"
            "peer_connection_dependency_factory.cc"
        )

        self.assertIn(
            'if (is_wasm) {\n'
            '    sources -= [\n'
            '      "peerconnection/audio_codec_factory.cc",',
            platform_build,
        )
        self.assertIn(
            '"peerconnection/audio_codec_factory_wasm.cc"',
            platform_build,
        )
        self.assertIn(
            '"peerconnection/video_codec_factory_wasm.cc"',
            platform_build,
        )
        native_codec_deps = webrtc_overrides.split(
            "if (!is_wasm) {", 1
        )[1].split("}", 1)[0]
        for dependency in (
            "//third_party/webrtc/api/audio_codecs/L16:"
            "audio_decoder_L16",
            "//third_party/webrtc/api/audio_codecs/opus:"
            "audio_encoder_opus",
            "//third_party/webrtc/api/video_codecs:"
            "builtin_video_decoder_factory",
            "//third_party/webrtc/media:rtc_internal_video_codecs",
        ):
            with self.subTest(dependency=dependency):
                self.assertIn(dependency, native_codec_deps)
        self.assertIn("AudioEncoderFactoryT<>>()", audio_factory)
        self.assertIn("AudioDecoderFactoryT<>>()", audio_factory)
        self.assertIn(
            "class UnavailableVideoEncoderFactory final",
            video_factory,
        )
        self.assertIn(
            "class UnavailableVideoDecoderFactory final",
            video_factory,
        )
        self.assertIn("return nullptr;", video_factory)
        self.assertIn(
            "#if !BUILDFLAG(IS_WASM)\n"
            '#include "third_party/webrtc/media/engine/'
            'fake_video_codec_factory.h"',
            dependency_factory,
        )

    def test_fake_capture_does_not_claim_a_native_wasm_camera_api(
        self,
    ) -> None:
        factory = source(
            "media/capture/video/fake_video_capture_device_factory.cc"
        )

        wasm_api = factory.split(
            "#elif BUILDFLAG(IS_WASM)", 1
        )[1].split("#elif BUILDFLAG(IS_IOS)", 1)[0]
        self.assertIn("VideoCaptureApi::UNKNOWN;", wasm_api)
        self.assertIn("no native camera backend", wasm_api)
        for native_api in (
            "LINUX_V4L2_SINGLE_PLANE",
            "MACOSX_AVFOUNDATION",
            "WIN_DIRECT_SHOW",
            "ANDROID_API2_LEGACY",
            "FUCHSIA_CAMERA3",
        ):
            with self.subTest(native_api=native_api):
                self.assertNotIn(native_api, wasm_api)

    def test_m3_avoids_tflite_inference_at_feature_boundaries(
        self,
    ) -> None:
        permissions_build = source(
            "components/permissions/prediction_service/BUILD.gn"
        )
        optimization_guide_build = source(
            "components/optimization_guide/core/BUILD.gn"
        )
        media_build = source("media/webrtc/BUILD.gn")
        media_helpers = source("media/webrtc/helpers.cc")
        webrtc_overrides = source("third_party/webrtc_overrides/BUILD.gn")

        permissions_wasm = permissions_build.split(
            "if (is_wasm) {", 1
        )[1].split("}", 1)[0]
        for dependency in (
            "//components/optimization_guide/core",
            "//third_party/tflite:tflite_public_headers",
            "//third_party/tflite_support",
        ):
            with self.subTest(dependency=dependency):
                self.assertIn(dependency, permissions_wasm)
        self.assertIn("permissions_aiv4_executor.cc", permissions_wasm)
        self.assertIn("prediction_model_executor.cc", permissions_wasm)
        permissions_tests = permissions_build.split(
            'source_set("unit_tests") {', 1
        )[1]
        native_test_block = permissions_tests.split(
            "if (!is_wasm) {", 1
        )[1].split("}", 1)[0]
        self.assertIn(
            "permissions_aiv4_handler_unittest.cc",
            native_test_block,
        )
        self.assertIn(
            "//components/optimization_guide/core:test_support",
            native_test_block,
        )
        self.assertIn(
            'if (!is_wasm) {\n'
            "    public_deps += [ "
            '"//components/optimization_guide/core/inference" ]',
            optimization_guide_build,
        )

        self.assertIn("if (!is_fuchsia && !is_wasm)", media_build)
        self.assertIn(
            'if (!is_wasm) {\n'
            '    public_deps += [ "//third_party/tflite" ]',
            media_build,
        )
        self.assertIn(
            "Neural residual echo estimation is unsupported on Wasm.",
            media_helpers,
        )
        native_webrtc_deps = webrtc_overrides.split(
            "if (!is_wasm) {", 1
        )[1].split("}", 1)[0]
        self.assertIn(
            "//third_party/webrtc/api/audio:"
            "neural_residual_echo_estimator_creator",
            native_webrtc_deps,
        )

    def test_unavailable_ai_and_local_speech_fail_at_the_boundary(
        self,
    ) -> None:
        browser_build = source("content/browser/BUILD.gn")
        binders = source("content/browser/browser_interface_binders.cc")
        browser_client = source(
            "content/public/browser/content_browser_client.cc"
        )
        speech = source(
            "content/browser/speech/speech_recognition_manager_impl.cc"
        )

        browser_wasm = browser_build.split(
            "# Echo AI and Optimization Guide-backed on-device speech",
            1,
        )[1].split("\n  }\n}", 1)[0]
        self.assertIn(
            "//components/optimization_guide/core",
            browser_wasm,
        )
        self.assertNotIn(
            "//components/optimization_guide/public/mojom",
            browser_wasm,
        )
        self.assertIn(
            "map->Add<optimization_guide::mojom::ModelBroker>",
            binders,
        )
        self.assertIn(
            "&EmptyBinderForFrame<optimization_guide::mojom::ModelBroker>",
            binders,
        )
        self.assertIn("receiver.reset();", browser_client)

        selector = speech.split(
            "bool SpeechRecognitionManagerImpl::"
            "UseOnDeviceSpeechRecognition", 1
        )[1].split(
            "void SpeechRecognitionManagerImpl::"
            "AbortAllSessionsForRenderFrame", 1
        )[0]
        self.assertNotIn("BUILDFLAG(IS_WASM)", selector)
        self.assertIn("!config.allow_cloud_fallback", selector)
        unavailable_error = speech.split(
            "if (!is_on_device_speech_recognition_installed)", 1
        )[1].split("}", 1)[0]
        self.assertIn("kLanguageNotSupported", unavailable_error)

    def test_wasm_keeps_portable_webui_error_and_usb_brokers(self) -> None:
        browser_build = source("content/browser/BUILD.gn")
        usb_observer = source(
            "content/browser/service_worker/"
            "service_worker_usb_delegate_observer.cc"
        )

        portable_error_reporting = browser_build.split(
            "if (!is_fuchsia) {", 1
        )[1].split("}", 1)[0]
        self.assertIn(
            "//components/crash/content/browser/error_reporting",
            portable_error_reporting,
        )

        native_speech = browser_build.split(
            "if (!is_fuchsia && !is_wasm) {", 1
        )[1].split("}", 1)[0]
        self.assertIn(
            "speech/on_device_speech_recognition_engine_impl.cc",
            native_speech,
        )
        self.assertIn(
            "//media/mojo/mojom:web_speech_recognition",
            native_speech,
        )
        self.assertNotIn(
            "//components/crash/content/browser/error_reporting",
            native_speech,
        )

        usb_platforms = browser_build.split(
            "if (is_win || is_apple || is_linux || is_chromeos || "
            "is_desktop_android ||",
            1,
        )[1].split("}", 1)[0]
        self.assertIn("is_fuchsia || is_wasm", usb_platforms)
        self.assertIn(
            "service_worker/service_worker_usb_delegate_observer.cc",
            usb_platforms,
        )
        self.assertIn(
            "return delegate && delegate->HasDevicePermission",
            usb_observer,
        )
        self.assertIn(
            "if (delegate) {\n      usb_delegate_observation.Observe(delegate);",
            usb_observer,
        )

    def test_partition_alloc_dumping_tracks_allocator_availability(
        self,
    ) -> None:
        build = source(
            "third_party/blink/renderer/platform/instrumentation/BUILD.gn"
        )
        platform = source(
            "third_party/blink/renderer/platform/exported/platform.cc"
        )

        provider_sources = build.split(
            "if (use_partition_alloc) {", 1
        )[1].split("}", 1)[0]
        self.assertIn(
            '"partition_alloc_memory_dump_provider.cc"', provider_sources
        )
        self.assertIn(
            '"partition_alloc_memory_dump_provider.h"', provider_sources
        )
        self.assertIn(
            "#if PA_BUILDFLAG(USE_PARTITION_ALLOC)\n"
            '#include "third_party/blink/renderer/platform/'
            'instrumentation/partition_alloc_memory_dump_provider.h"',
            platform,
        )
        registration = platform.split(
            "PartitionAllocMemoryDumpProvider::Instance()", 1
        )[0].rsplit("#if PA_BUILDFLAG(USE_PARTITION_ALLOC)", 1)[1]
        self.assertNotIn("#endif", registration)


if __name__ == "__main__":
    unittest.main()
