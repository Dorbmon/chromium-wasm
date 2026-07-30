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


class M3BaseSourceContractTest(unittest.TestCase):
    def test_content_installs_a_checked_allocation_policy(
        self,
    ) -> None:
        memory = source("base/process/memory_wasm.cc")

        self.assertIn("g_terminate_on_out_of_memory.store", memory)
        self.assertIn("emscripten_builtin_malloc", memory)
        self.assertIn("emscripten_builtin_calloc", memory)
        self.assertIn("emscripten_builtin_free", memory)
        self.assertIn("void* malloc(size_t size)", memory)
        self.assertIn("bool UncheckedMalloc", memory)
        self.assertIn("if (!IsValidPosixAlignment(alignment))", memory)
        self.assertNotIn("-sABORTING_MALLOC=1",
                         source("build/toolchain/wasm/BUILD.gn"))

    def test_content_memory_budgets_use_the_linear_memory_capacity(
        self,
    ) -> None:
        config = source("build/config/wasm.gni")
        build = source("base/BUILD.gn")
        sys_info = source("base/system/sys_info_wasm.cc")

        self.assertIn(
            "chromium_wasm_maximum_memory_bytes = 2147483648", config
        )
        self.assertIn(
            "-sMAXIMUM_MEMORY=$chromium_wasm_maximum_memory_bytes",
            source("build/toolchain/wasm/BUILD.gn"),
        )
        self.assertIn(
            "CHROMIUM_WASM_MAXIMUM_MEMORY_BYTES="
            "$chromium_wasm_maximum_memory_bytes",
            build,
        )
        self.assertIn(
            "ByteSize(CHROMIUM_WASM_MAXIMUM_MEMORY_BYTES)", sys_info
        )
        self.assertIn("emscripten_get_heap_size()", sys_info)

    def test_process_metrics_do_not_label_linear_memory_as_host_rss(
        self,
    ) -> None:
        metrics = source("base/process/process_metrics_wasm.cc")

        self.assertIn(
            "return unexpected(ProcessUsageError::kSystemError);", metrics
        )
        self.assertNotIn("resident_set_bytes = emscripten_get_heap_size()",
                         metrics)
        self.assertIn(
            "Browsers do not expose system-wide committed memory.", metrics
        )

    def test_wasm_filename_icu_uses_its_utf8_file_path_contract(
        self,
    ) -> None:
        file_path = source("base/files/file_path.h")
        file_util_icu = source("base/i18n/file_util_icu.cc")

        self.assertIn(
            "#elif BUILDFLAG(IS_POSIX) || BUILDFLAG(IS_FUCHSIA) || "
            "BUILDFLAG(IS_WASM)\n"
            "  // On most platforms, native pathnames are char arrays",
            file_path,
        )
        self.assertIn(
            "#elif BUILDFLAG(IS_WASM)\n"
            "  // Wasm FilePath values use UTF-8 encoding.\n"
            "  U8_NEXT(",
            file_util_icu,
        )
        self.assertIn(
            "#elif BUILDFLAG(IS_WASM)\n"
            "  // Wasm FilePath values use UTF-8 encoding.\n"
            "  return CompareString16WithCollator("
            "*collator, a.AsUTF16Unsafe(),",
            file_util_icu,
        )

    def test_wasm_threads_preserve_full_base_lifecycle_invariants(
        self,
    ) -> None:
        platform = source("base/threading/platform_thread_wasm.cc")
        metrics = source("base/threading/platform_thread_metrics_wasm.cc")

        self.assertIn("base::DisallowSingleton();", platform)
        self.assertIn("RegisterThread(", platform)
        self.assertIn("RemoveName(", platform)
        self.assertIn(
            "ScopedBlockingCallWithBaseSyncPrimitives", platform
        )
        self.assertIn("new PlatformThreadMetrics()", metrics)
        self.assertIn("return std::nullopt;", metrics)

    def test_unsupported_base_capabilities_fail_honestly(self) -> None:
        stack = source("base/debug/stack_trace.cc")
        kill = source("base/process/kill_wasm.cc")
        shared_memory = source(
            "base/memory/shared_memory_switch_wasm.cc"
        )

        self.assertIn(
            "BUILDFLAG(IS_ANDROID) || BUILDFLAG(IS_WASM)", stack
        )
        self.assertIn("CHECK(!process.IsValid())", kill)
        self.assertNotIn("NOTIMPLEMENTED", kill)
        self.assertEqual(
            shared_memory.count(
                'CHECK(false) << "Wasm cannot pass shared memory '
                'to a child process";'
            ),
            2,
        )
        self.assertNotIn("NOTIMPLEMENTED", shared_memory)

    def test_mojo_native_shared_memory_wrapping_is_explicitly_unsupported(
        self,
    ) -> None:
        wrapper = source("mojo/public/cpp/system/platform_handle.cc")
        ipcz = source("mojo/core/core_ipcz.cc")

        self.assertEqual(
            wrapper.count(
                "Wasm shared-memory handles are process-local capabilities"
            ),
            1,
        )
        self.assertIn(
            "Process-local Wasm capabilities\n"
            "  // cannot be reconstructed",
            wrapper,
        )
        self.assertGreaterEqual(
            ipcz.count(
                "#if BUILDFLAG(IS_WASM)\n"
                "  return MOJO_RESULT_UNIMPLEMENTED;"
            ),
            4,
        )

    def test_mojo_platform_file_transport_is_explicitly_unsupported(
        self,
    ) -> None:
        file_traits = source("mojo/public/cpp/base/file_mojom_traits.cc")
        read_only_traits = source(
            "mojo/public/cpp/base/read_only_file_mojom_traits.cc"
        )
        platform_handle = source(
            "mojo/public/cpp/platform/platform_handle.h"
        )
        unsupported = (
            'CHECK(false) << "Mojo platform file transport is unsupported '
            'on Wasm";'
        )

        self.assertEqual(file_traits.count(unsupported), 1)
        self.assertEqual(read_only_traits.count(unsupported), 1)
        self.assertIn(
            "#if BUILDFLAG(IS_WASM)\n  return false;", file_traits
        )
        self.assertIn(
            "#if BUILDFLAG(IS_WASM)\n  return false;", read_only_traits
        )
        self.assertIn(
            "#elif BUILDFLAG(IS_WASM)\n"
            "  // Native platform handles do not exist",
            platform_handle,
        )
        self.assertNotIn(
            "BUILDFLAG(IS_WASM)\n  explicit PlatformHandle(",
            platform_handle,
        )

    def test_content_mojo_restores_full_base_dependencies(self) -> None:
        m1_only = (
            "is_wasm && enable_chromium_wasm_port && "
            "!enable_chromium_wasm_content"
        )
        for path in (
            "mojo/core/BUILD.gn",
            "mojo/core/embedder/BUILD.gn",
            "mojo/public/c/system/BUILD.gn",
            "mojo/public/cpp/platform/BUILD.gn",
        ):
            with self.subTest(path=path):
                self.assertIn(m1_only, source(path))

        ipcz = source("third_party/ipcz/src/BUILD.gn")
        self.assertEqual(
            ipcz.count("_is_wasm_port && !enable_chromium_wasm_content"),
            2,
        )

        bindings_tests = source(
            "mojo/public/cpp/bindings/tests/BUILD.gn"
        )
        self.assertIn(
            "if (!is_wasm) {\n"
            "    deps += [ "
            '"//third_party/ipcz/src:ipcz_test_support_chromium" ]\n'
            "  }",
            bindings_tests,
        )


if __name__ == "__main__":
    unittest.main()
