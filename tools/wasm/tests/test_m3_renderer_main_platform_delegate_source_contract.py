#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M3RendererMainPlatformDelegateSourceContractTest(
    unittest.TestCase
):
    def test_wasm_selects_its_renderer_main_platform_delegate(self) -> None:
        build = source("content/renderer/BUILD.gn")
        wasm_sources = build.split("  if (is_wasm) {", 1)[1].split(
            "  if (is_android)", 1
        )[0]

        self.assertIn(
            'sources += [ "renderer_main_platform_delegate_wasm.cc" ]',
            wasm_sources,
        )
        for native_source in (
            "renderer_main_platform_delegate_android.cc",
            "renderer_main_platform_delegate_fuchsia.cc",
            "renderer_main_platform_delegate_linux.cc",
            "renderer_main_platform_delegate_mac.mm",
            "renderer_main_platform_delegate_win.cc",
        ):
            with self.subTest(native_source=native_source):
                self.assertNotIn(native_source, wasm_sources)

    def test_wasm_delegate_rejects_native_sandboxing(self) -> None:
        implementation = source(
            "content/renderer/renderer_main_platform_delegate_wasm.cc"
        )
        sandbox = implementation.split(
            "bool RendererMainPlatformDelegate::EnableSandbox() {", 1
        )[1].split("}", 1)[0]

        self.assertIn(
            '#if !BUILDFLAG(IS_WASM)\n'
            '#error "renderer_main_platform_delegate_wasm.cc is only for '
            'WebAssembly"\n'
            "#endif",
            implementation,
        )
        for definition in (
            "RendererMainPlatformDelegate::RendererMainPlatformDelegate(",
            "RendererMainPlatformDelegate::~RendererMainPlatformDelegate()",
            "RendererMainPlatformDelegate::PlatformInitialize()",
            "RendererMainPlatformDelegate::PlatformUninitialize()",
            "RendererMainPlatformDelegate::EnableSandbox()",
        ):
            with self.subTest(definition=definition):
                self.assertIn(definition, implementation)
        self.assertIn(
            "Renderer process sandboxing is unsupported on WebAssembly.",
            sandbox,
        )
        self.assertIn("return false;", sandbox)
        self.assertNotIn("return true;", sandbox)

    def test_delegate_is_link_reachable_but_not_used_in_process(self) -> None:
        runner = source("content/app/content_main_runner_impl.cc")
        in_process = source(
            "content/renderer/in_process_renderer_thread.cc"
        )

        self.assertIn(
            "{switches::kRendererProcess, RendererMain}",
            runner,
        )
        self.assertIn(
            "In single-process mode, we never enter the sandbox",
            in_process,
        )
        self.assertIn("client->PostSandboxInitialized();", in_process)


if __name__ == "__main__":
    unittest.main()
