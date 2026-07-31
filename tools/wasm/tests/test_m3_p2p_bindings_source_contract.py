#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M3P2PBindingsSourceContractTest(unittest.TestCase):
    def test_wasm_generates_client_bindings_without_runtime_p2p(self) -> None:
        features = source("services/network/public/cpp/features.gni")
        cpp_build = source("services/network/public/cpp/BUILD.gn")
        mojom_build = source("services/network/public/mojom/BUILD.gn")
        network_mojom_target = mojom_build.split(
            'mojom("mojom") {', 1
        )[1].split(
            '# This target is split from "mojom" target', 1
        )[0]

        self.assertIn(
            "is_p2p_mojo_bindings_enabled = is_p2p_enabled || is_wasm",
            features,
        )

        cpp_bindings = cpp_build.split(
            "if (is_p2p_mojo_bindings_enabled) {", 1
        )[1].split('mojom("test_interfaces")', 1)[0]
        self.assertIn('component("cpp_p2p")', cpp_bindings)
        self.assertIn('"p2p_param_traits.cc"', cpp_bindings)
        self.assertIn(
            "//third_party/webrtc_overrides:webrtc_component",
            cpp_bindings,
        )

        mojom_bindings = network_mojom_target.split(
            "if (is_p2p_mojo_bindings_enabled) {", 1
        )[1].split("}", 1)[0]
        self.assertIn('"p2p.mojom"', mojom_bindings)
        self.assertNotIn('"p2p_trusted.mojom"', mojom_bindings)

        runtime_p2p = network_mojom_target.split(
            "if (is_p2p_enabled) {", 1
        )[1].split("}", 1)[0]
        self.assertIn(
            'enabled_features += [ "is_p2p_enabled" ]', runtime_p2p
        )
        self.assertIn('"p2p_trusted.mojom"', runtime_p2p)
        self.assertNotIn('"p2p.mojom"', runtime_p2p)

        shared_typemaps = network_mojom_target.split(
            "# Typemaps which apply to both Blink and non-Blink bindings.",
            1,
        )[1].split("# Typemaps applied only to non-Blink bindings", 1)[0]
        self.assertIn(
            "if (is_p2p_mojo_bindings_enabled) {", shared_typemaps
        )
        self.assertIn(
            "//services/network/public/cpp:cpp_p2p", shared_typemaps
        )

    def test_runtime_p2p_surfaces_remain_disabled_for_m3_wasm(self) -> None:
        content_build = source("content/browser/BUILD.gn")
        network_build = source("services/network/BUILD.gn")
        network_cpp_build = source("services/network/public/cpp/BUILD.gn")
        manifest = source("tools/wasm/toolchain_manifest.json")

        content_runtime = content_build.split(
            "if (is_p2p_enabled) {", 1
        )[1].split("}", 1)[0]
        self.assertIn(
            "renderer_host/p2p/socket_dispatcher_host.cc",
            content_runtime,
        )

        network_runtime = network_build.split(
            "if (is_p2p_enabled) {", 1
        )[1].split("}", 1)[0]
        self.assertIn("p2p/socket_manager.cc", network_runtime)
        self.assertIn(
            '"IS_P2P_ENABLED=$is_p2p_enabled"', network_cpp_build
        )
        self.assertIn('"is_p2p_enabled = false"', manifest)


if __name__ == "__main__":
    unittest.main()
