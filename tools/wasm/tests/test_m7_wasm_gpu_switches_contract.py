#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for Wasm's explicit GPU shader-disk-cache refusal."""

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def _body_after_signature(text: str, signature: str) -> str:
    """Returns one balanced C++ body without depending on source layout."""

    start = text.index(signature)
    opening_brace = text.index("{", start)
    depth = 0
    for index in range(opening_brace, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[opening_brace + 1 : index]
    raise AssertionError(f"missing closing brace for {signature}")


def _gn_target_body(text: str, target: str) -> str:
    """Returns a balanced source_set body without relying on line layout."""

    signature = f'source_set("{target}")'
    start = text.index(signature)
    opening_brace = text.index("{", start)
    depth = 0
    for index in range(opening_brace, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[opening_brace + 1 : index]
    raise AssertionError(f"missing closing brace for {signature}")


class M7WasmGpuSwitchesContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.delegate = source(
            "chrome/browser/wasm/wasm_chrome_main_delegate.cc"
        )
        self.wasm_build = source("chrome/browser/wasm/BUILD.gn")
        self.gpu_features = source("gpu/config/gpu_finch_features.cc")

    def test_wasm_startup_refuses_only_shader_disk_caching(self) -> None:
        self.assertIn('#include "gpu/config/gpu_switches.h"', self.delegate)
        startup = _body_after_signature(
            self.delegate,
            "std::optional<int> WasmChromeMainDelegate::BasicStartupComplete()",
        )
        self.assertIn("command_line.RemoveSwitch(switches::kDisableGpu);", startup)
        self.assertNotIn("command_line.AppendSwitch(switches::kDisableGpu);", startup)
        self.assertIn(
            "if (!command_line.HasSwitch("
            "switches::kDisableGpuShaderDiskCache)) {\n"
            "    command_line.AppendSwitch("
            "switches::kDisableGpuShaderDiskCache);\n"
            "  }",
            startup,
        )
        self.assertIn(
            "command_line.AppendSwitch(switches::kDisableGpuCompositing);",
            startup,
        )

    def test_switch_is_the_authoritative_shader_cache_refusal(self) -> None:
        feature_gate = _body_after_signature(
            self.gpu_features,
            "bool IsShaderDiskCacheEnabled(",
        )
        self.assertIn(
            "command_line->HasSwitch(switches::kDisableGpuShaderDiskCache)",
            feature_gate,
        )
        self.assertIn("return false;", feature_gate)

    def test_delegate_owns_only_the_private_gpu_config_dependency(self) -> None:
        target = _gn_target_body(self.wasm_build, "wasm_chrome_main_delegate")
        self.assertIn('"//gpu/config:config",', target)
        for desktop_target in (
            "//chrome/gpu",
            "//chrome/renderer",
            "//chrome/utility",
        ):
            with self.subTest(desktop_target=desktop_target):
                self.assertNotIn(f'"{desktop_target}",', target)


if __name__ == "__main__":
    unittest.main()
