#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import json
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M3ServiceSourceContractTest(unittest.TestCase):
    def test_software_ozone_omits_unused_modifier_filter_state(self) -> None:
        gpu_init = source("gpu/ipc/service/gpu_init.cc")

        guarded_state = gpu_init.split(
            "#if BUILDFLAG(ENABLE_VULKAN) || \\\n"
            "    (BUILDFLAG(SKIA_USE_DAWN) && BUILDFLAG(IS_CHROMEOS))",
            1,
        )[1].split("#endif", 1)[0]
        self.assertIn("auto* factory =", guarded_state)
        self.assertIn("bool filter_set = false;", guarded_state)

    def test_utility_service_boundary_keeps_only_m3_services_on_wasm(
        self,
    ) -> None:
        build = source("content/utility/BUILD.gn")
        services = source("content/utility/services.cc")
        utility_main = source("content/utility/utility_main.cc")
        manifest = source("tools/wasm/toolchain_manifest.json")

        wasm_deferred = build.split("if (!is_wasm) {", 1)[1].split(
            "}", 1
        )[0]
        for dependency in (
            "//content/services/auction_worklet",
            "//services/audio",
            "//services/on_device_model:on_device_model_service",
            "//services/shape_detection:lib",
            "//services/video_capture:lib",
        ):
            with self.subTest(dependency=dependency):
                self.assertIn(dependency, wasm_deferred)
        for service in (
            "services.Add(RunDataDecoder);",
            "services.Add(RunStorageService);",
            "services.Add(RunTracing);",
        ):
            with self.subTest(service=service):
                self.assertIn(service, services)
        self.assertIn("services.Add(RunNetworkService);", services)
        self.assertIn(
            "#if !BUILDFLAG(IS_WASM)\n"
            "  services.Add(RunAuctionWorkletService);",
            services,
        )
        self.assertIn(
            "#if !BUILDFLAG(IS_WASM)\n"
            "  if (utility_sub_type == "
            "on_device_model::mojom::OnDeviceModelService::Name_)",
            utility_main,
        )
        for argument in (
            '"media_use_ffmpeg = false"',
            '"media_use_openh264 = false"',
            '"media_use_libvpx = false"',
            '"media_use_symphonia = false"',
            '"rtc_include_builtin_audio_codecs = false"',
            '"rtc_include_opus = false"',
            '"rtc_build_opus = false"',
            '"rtc_build_libvpx = false"',
            '"rtc_libvpx_build_vp9 = false"',
            '"rtc_include_dav1d_in_internal_decoder_factory = false"',
            '"enable_media_remoting = false"',
            '"enable_media_remoting_rpc = false"',
            '"enable_pdf = false"',
            '"enable_pdf_ink2 = false"',
            '"enable_pdf_save_to_drive = false"',
            '"enable_extensions = false"',
            '"enable_guest_view = false"',
            '"enable_plugins = false"',
            '"enable_printing = false"',
            '"enable_oop_printing = false"',
            '"enable_paint_preview = false"',
            '"enable_compute_pressure = false"',
            '"is_p2p_enabled = false"',
            '"enable_libaom = false"',
            '"enable_dav1d_decoder = false"',
            '"enable_av1_decoder = false"',
            '"dawn_use_swiftshader = false"',
            '"build_tflite_with_xnnpack = false"',
            '"build_with_model_execution = false"',
        ):
            with self.subTest(argument=argument):
                self.assertIn(argument, manifest)
        self.assertIn(
            "use_cpuinfo = !is_wasm &&",
            source("third_party/cpuinfo/cpuinfo.gni"),
        )

    def test_perfetto_keeps_in_process_tracing_without_socket_ipc(
        self,
    ) -> None:
        manifest = json.loads(source("tools/wasm/toolchain_manifest.json"))
        perfetto_build = source("third_party/perfetto/BUILD.gn")

        self.assertIn(
            "enable_perfetto_ipc = false",
            manifest["m3_content_gn_args"],
        )
        self.assertIn(
            "enable_perfetto_trace_processor_httpd = false",
            manifest["m3_content_gn_args"],
        )
        libperfetto = perfetto_build.split(
            'component("libperfetto") {', 1
        )[1].split("# TODO(altimin)", 1)[0]
        self.assertIn('"src/tracing:client_api"', libperfetto)
        self.assertIn('"src/tracing/core"', libperfetto)
        ipc_block = libperfetto.split(
            "if (enable_perfetto_ipc) {", 1
        )[1].split("}", 1)[0]
        self.assertIn('"src/tracing/ipc/producer"', ipc_block)
        self.assertIn('"src/tracing/ipc/service"', ipc_block)

    def test_native_only_component_test_labels_are_not_aggregated(self) -> None:
        components = source("components/BUILD.gn")

        self.assertIn(
            "if (!is_fuchsia && !is_wasm)",
            components,
        )
        for label in (
            "//components/custom_handlers:unit_tests",
            "//components/origin_trials:unit_tests",
            "//components/custom_handlers:browser_tests",
        ):
            with self.subTest(label=label):
                position = components.index(label)
                guard = components.rfind(
                    "if (!is_wasm)",
                    0,
                    position,
                )
                self.assertGreater(guard, 0)
                self.assertLess(position - guard, 300)

    def test_dwa_recording_avoids_private_metrics_uploads_on_wasm(
        self,
    ) -> None:
        dwa_build = source("components/metrics/dwa/BUILD.gn")
        builders = source(
            "tools/metrics/private_metrics/"
            "gen_private_metrics_builders.gni"
        )

        self.assertIn('source_set("dwa_entry_builder_base")', dwa_build)
        self.assertIn('"dwa_entry_builder_base.cc"', dwa_build)
        self.assertIn(
            "//components/metrics/private_metrics:dwa_recorder",
            dwa_build,
        )
        wasm_deps = builders.split(
            'if (is_wasm && invoker.type == "dwa") {', 1
        )[1].split("} else {", 1)[0]
        self.assertIn(
            "//components/metrics/dwa:dwa_entry_builder_base",
            wasm_deps,
        )
        self.assertNotIn(
            '"//components/metrics/private_metrics"',
            wasm_deps,
        )
        self.assertNotIn("federated_compute", wasm_deps)
        self.assertIn(
            'deps += [ "//components/metrics/private_metrics" ]',
            builders,
        )

        privacy_sandbox = source("components/privacy_sandbox/BUILD.gn")
        production_target = privacy_sandbox.split(
            'source_set("privacy_sandbox") {', 1
        )[1].split('source_set("test_support") {', 1)[0]
        privacy_sandbox_wasm_deps = production_target.split(
            "if (is_wasm) {", 1
        )[1].split("} else {", 1)[0]
        self.assertIn(
            "//components/metrics/private_metrics:dwa_recorder",
            privacy_sandbox_wasm_deps,
        )
        self.assertNotIn(
            '"//components/metrics/private_metrics"',
            privacy_sandbox_wasm_deps,
        )
        self.assertIn(
            'deps += [ "//components/metrics/private_metrics" ]',
            production_target,
        )


if __name__ == "__main__":
    unittest.main()
