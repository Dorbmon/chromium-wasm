#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the real single-process Wasm discardable-memory owner."""

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M6WasmDiscardableMemoryContractTest(unittest.TestCase):
    def test_browser_registers_the_existing_wasm_service_manager(self) -> None:
        browser_main_loop = source("content/browser/browser_main_loop.cc")

        registration = browser_main_loop.index(
            "if ((!parsed_command_line_->HasSwitch(switches::kSingleProcess) ||"
        )
        registration_body = browser_main_loop[registration : registration + 900]
        for expected in (
            "BUILDFLAG(IS_WASM)",
            "!base::DiscardableMemoryAllocator::HasInstance()",
            "discardable_memory::DiscardableSharedMemoryManager::Get()",
            "CHECK(discardable_memory_manager);",
            "base::DiscardableMemoryAllocator::SetInstance("
            "discardable_memory_manager);",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, registration_body)

        # The shared-memory service is owned by ContentMainRunner before this
        # BrowserMainLoop hook. This remains a real allocator, not a test or
        # smoke-local replacement.
        self.assertNotIn("TestDiscardableMemoryAllocator", registration_body)

    def test_wasm_renderer_preserves_its_client_lifecycle_without_replacing_global_allocator(
        self,
    ) -> None:
        renderer = source("content/renderer/render_thread_impl.cc")

        setup = renderer.index(
            "mojo::PendingRemote<discardable_memory::mojom::"
            "DiscardableSharedMemoryManager>"
        )
        setup_body = renderer[setup : setup + 1250]
        for expected in (
            "BindHostReceiver(manager_remote.InitWithNewPipeAndPassReceiver());",
            "discardable_memory_allocator_ = base::MakeRefCounted<",
            "#if BUILDFLAG(IS_WASM)",
            "CHECK(base::DiscardableMemoryAllocator::HasInstance());",
            "#else",
            "base::DiscardableMemoryAllocator::SetInstance(",
            "#endif",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, setup_body)

        wasm_branch = setup_body.index("#if BUILDFLAG(IS_WASM)")
        non_wasm_set_instance = setup_body.index(
            "base::DiscardableMemoryAllocator::SetInstance(", wasm_branch
        )
        self.assertLess(wasm_branch, non_wasm_set_instance)
        self.assertIn("#else", setup_body[wasm_branch:non_wasm_set_instance])

        for expected in (
            "discardable_memory_allocator_->OnBackgrounded();",
            "discardable_memory_allocator_->OnForegrounded();",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, renderer)


if __name__ == "__main__":
    unittest.main()
