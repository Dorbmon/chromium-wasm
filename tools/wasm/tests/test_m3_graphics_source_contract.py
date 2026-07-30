#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M3GraphicsSourceContractTest(unittest.TestCase):
    def test_software_only_wasm_gpu_fences_are_always_invalid(self) -> None:
        build = source("ui/gfx/BUILD.gn")
        handle = source("ui/gfx/gpu_fence_handle.h")
        wasm_handle = source("ui/gfx/gpu_fence_handle_wasm.h")
        implementation = source("ui/gfx/gpu_fence_handle.cc")

        self.assertIn(
            'if (is_wasm) {\n'
            '    sources += [ "gpu_fence_handle_wasm.h" ]\n'
            "  }",
            build,
        )
        self.assertIn(
            "#elif BUILDFLAG(IS_WASM)\n"
            "  using ScopedPlatformFence = ScopedWasmGpuFence;",
            handle,
        )
        self.assertIn("bool is_valid() const { return false; }", wasm_handle)
        self.assertNotIn("ScopedFD", wasm_handle)
        self.assertNotIn("PlatformHandle", wasm_handle)
        self.assertIn(
            "#elif BUILDFLAG(IS_WASM)\n"
            "  return true;\n"
            '#else\n#error "Unsupported platform."',
            implementation,
        )

    def test_ozone_buffer_enum_has_a_total_diagnostic_mapping(self) -> None:
        factory = source(
            "gpu/command_buffer/service/shared_image/"
            "shared_image_factory.cc"
        )
        mapping = factory.split(
            "const char* GmbTypeToString", 1
        )[1].split("gfx::GpuMemoryBufferType GetNativeBufferType", 1)[0]

        self.assertIn(
            "#if BUILDFLAG(IS_OZONE)\n"
            "    case gfx::NATIVE_PIXMAP:\n"
            '      return "platform";',
            mapping,
        )

    def test_ozone_native_pixmap_helpers_guard_optional_platform_data(
        self,
    ) -> None:
        factory = source(
            "gpu/command_buffer/service/shared_image/"
            "ozone_image_backing_factory.cc"
        )
        backing = source(
            "gpu/command_buffer/service/shared_image/"
            "ozone_image_backing.cc"
        )

        self.assertIn(
            "VulkanDeviceQueue* device_queue = nullptr;\n"
            "#if BUILDFLAG(ENABLE_VULKAN)",
            factory,
        )
        self.assertIn(
            "#if !BUILDFLAG(IS_LINUX) && !BUILDFLAG(IS_CHROMEOS)\n"
            '  NOTREACHED() << "Cannot get single plane',
            backing,
        )

    def test_raster_shared_memory_validation_is_libcxx_portable(self) -> None:
        decoder = source("gpu/command_buffer/service/raster_decoder.cc")

        self.assertIn(
            "if (!paint_buffer_opt || paint_buffer_opt->empty())", decoder
        )
        self.assertIn(
            "if (!font_buffer_opt || font_buffer_opt->empty())", decoder
        )
        self.assertNotIn(".value_or({}).empty()", decoder)

    def test_software_only_wasm_skia_keeps_raster_without_gpu_backends(
        self,
    ) -> None:
        features = source("skia/features.gni")
        build = source("skia/BUILD.gn")

        self.assertIn(
            "skia_support_gpu = use_blink && !is_wasm", features
        )
        self.assertIn("sources = skia_core_sources", build)
        self.assertIn(
            "if (skia_support_gpu || "
            "(is_wasm && enable_chromium_wasm_content)) {\n"
            "    workaround_header = "
            '"gpu/config/gpu_driver_bug_workaround_autogen.h"',
            build,
        )
        skia_target = build.split('component("skia") {', 1)[1]
        gpu_sources = skia_target.split(
            "if (skia_support_gpu) {", 1
        )[1].split("if (skia_support_pdf)", 1)[0]
        self.assertIn("sources += skia_ganesh_private", gpu_sources)
        self.assertIn(
            "public_deps += [ \":skia_graphite_public\" ]", gpu_sources
        )

    def test_wasm_omits_unused_tint_native_tooling(self) -> None:
        tint = source("build_overrides/tint.gni")

        for setting in (
            "tint_build_spv_writer = !is_wasm",
            "tint_build_unittests = !is_wasm",
            "tint_build_benchmarks = !is_wasm",
        ):
            with self.subTest(setting=setting):
                self.assertIn(setting, tint)

    def test_frame_bridge_is_linked_through_the_ozone_target(self) -> None:
        build = source("ui/ozone/platform/wasm/BUILD.gn")

        self.assertIn("--js-library=", build)
        self.assertIn('inputs = [ "wasm_host_bridge.js" ]', build)
        self.assertIn(
            'all_dependent_configs = [ ":wasm_host_bridge" ]', build
        )


if __name__ == "__main__":
    unittest.main()
