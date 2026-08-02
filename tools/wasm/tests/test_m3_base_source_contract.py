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

    def test_content_thread_budget_fits_the_prewarmed_worker_pool(
        self,
    ) -> None:
        config = source("build/config/wasm.gni")
        build = source("base/BUILD.gn")
        sys_info = source("base/system/sys_info_wasm.cc")

        self.assertIn(
            "chromium_wasm_logical_processor_limit = 2", config
        )
        self.assertIn(
            "chromium_wasm_logical_processor_limit <=\n"
            "               chromium_wasm_pthread_pool_size",
            config,
        )
        self.assertIn(
            "CHROMIUM_WASM_LOGICAL_PROCESSOR_LIMIT="
            "$chromium_wasm_logical_processor_limit",
            build,
        )
        self.assertIn(
            "#if defined(BASE_WASM_FULL_COMPONENT)", sys_info
        )
        self.assertIn(
            "std::min(logical_cores, "
            "CHROMIUM_WASM_LOGICAL_PROCESSOR_LIMIT)",
            sys_info,
        )
        self.assertIn(
            "// Preserve the passing M0-M2 primitive/runtime behavior.",
            sys_info,
        )

    def test_content_ui_and_io_sequences_use_worker_message_pumps(
        self,
    ) -> None:
        pump = source("base/message_loop/message_pump.cc")
        ui_branch = pump.split(
            "case MessagePumpType::UI:", 1
        )[1].split("case MessagePumpType::IO:", 1)[0]
        io_branch = pump.split(
            "case MessagePumpType::IO:", 1
        )[1].split("case MessagePumpType::CUSTOM:", 1)[0]

        for branch in (ui_branch, io_branch):
            with self.subTest(branch=branch[:40]):
                wasm = branch.split(
                    "#if BUILDFLAG(IS_WASM)", 1
                )[1].split("#elif", 1)[0]
                self.assertIn(
                    "return std::make_unique<MessagePumpDefault>();", wasm
                )
                self.assertNotIn("NOTREACHED", wasm)

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

    def test_content_restores_file_trace_serialization(self) -> None:
        for path in ("base/files/file.cc", "base/files/file_path.cc"):
            with self.subTest(path=path):
                implementation = source(path)
                self.assertIn(
                    '#include "base/tracing_buildflags.h"', implementation
                )
                self.assertIn(
                    "#if !BUILDFLAG(IS_WASM) || "
                    "BUILDFLAG(CHROMIUM_WASM_CONTENT)\n"
                    "void ",
                    implementation,
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

    def test_mojo_transfers_process_local_shared_memory_capabilities(
        self,
    ) -> None:
        registry = source(
            "base/memory/process_local_shared_memory_wasm.cc"
        )
        registry_header = source(
            "base/memory/process_local_shared_memory_wasm.h"
        )
        platform_handle = source(
            "mojo/public/cpp/platform/platform_handle_wasm.cc"
        )
        wrapper = source("mojo/public/cpp/system/platform_handle.cc")
        ipcz = source("mojo/core/core_ipcz.cc")
        shared_buffer = source(
            "mojo/core/ipcz_driver/shared_buffer.cc"
        )

        self.assertIn("ExportHandleForTransport", registry)
        self.assertIn("ImportHandleForTransport", registry)
        self.assertIn("DiscardTransportHandle", registry)
        self.assertIn(
            "[[nodiscard]] uint64_t ExportHandleForTransport",
            registry_header,
        )
        self.assertIn(
            "MOJO_PLATFORM_HANDLE_TYPE_WASM_SHARED_MEMORY",
            platform_handle,
        )
        self.assertIn("if (token == 0)", platform_handle)
        self.assertNotIn("CHECK_NE(token", platform_handle)
        self.assertIn(
            "PlatformHandle(std::move(handle)), &platform_handles[0]",
            wrapper,
        )
        self.assertIn(
            "PlatformHandle::FromMojoPlatformHandle(&platform_handles[0])",
            wrapper,
        )
        wrap = ipcz.split(
            "MojoResult MojoWrapPlatformSharedMemoryRegionIpcz", 1
        )[1].split(
            "MojoResult MojoUnwrapPlatformSharedMemoryRegionIpcz", 1
        )[0]
        unwrap = ipcz.split(
            "MojoResult MojoUnwrapPlatformSharedMemoryRegionIpcz", 1
        )[1].split("MojoResult MojoCreateInvitationIpcz", 1)[0]
        self.assertIn(
            "MOJO_WRAP_PLATFORM_SHARED_BUFFER_HANDLE_FLAG_NONE",
            wrap,
        )
        self.assertIn(
            "MOJO_UNWRAP_PLATFORM_SHARED_BUFFER_HANDLE_FLAG_NONE",
            unwrap,
        )
        self.assertIn("!num_bytes || !mojo_guid || !access_mode", unwrap)
        self.assertIn(
            "BestEffortScopedIpczHandle owned_handle(mojo_handle)",
            unwrap,
        )
        self.assertIn("SharedBuffer::FromBox(owned_handle.get())", unwrap)
        self.assertIn(
            "SharedBuffer::Unbox(owned_handle.release())", unwrap
        )
        self.assertNotIn("MOJO_RESULT_RESOURCE_EXHAUSTED", unwrap)

        create = shared_buffer.split(
            "SharedBuffer::CreateForMojoWrapper", 1
        )[1].split("void SharedBuffer::Close", 1)[0]
        self.assertIn(
            "return handles[0].TakeSharedMemoryHandle();",
            shared_buffer,
        )
        self.assertNotIn(
            "#if BUILDFLAG(IS_WASM)\n  return nullptr;", create
        )
        self.assertLess(
            create.index("PlatformHandle::FromMojoPlatformHandle"),
            create.index("mojo_platform_handles.size() != 1"),
        )
        self.assertIn(
            "base::IsValueInRangeForNumericType<uint32_t>(size)",
            create,
        )
        self.assertIn(
            "PlatformSharedMemoryRegion::TakeOrFail", create
        )
        self.assertNotIn("PlatformSharedMemoryRegion::Take(", create)

        dimensions = shared_buffer.split(
            "bool SharedBuffer::GetSerializedDimensions", 1
        )[1].split("bool SharedBuffer::Serialize", 1)[0]
        serialize = shared_buffer.split(
            "bool SharedBuffer::Serialize", 1
        )[1].split(
            "scoped_refptr<SharedBuffer> SharedBuffer::Deserialize", 1
        )[0]
        deserialize = shared_buffer.split(
            "scoped_refptr<SharedBuffer> SharedBuffer::Deserialize", 1
        )[1]
        self.assertIn(
            "#if BUILDFLAG(IS_WASM)\n  return false;", dimensions
        )
        self.assertIn(
            "#if BUILDFLAG(IS_WASM)\n  return false;", serialize
        )
        self.assertIn(
            "#if BUILDFLAG(IS_WASM)\n  return nullptr;", deserialize
        )

    def test_full_base_uses_alias_aware_shared_memory_mappings(
        self,
    ) -> None:
        build = source("base/BUILD.gn")
        mapping = source("base/memory/shared_memory_mapping_wasm.cc")
        full_base_wasm = build.split(
            'if (is_wasm) {\n'
            '    sources -= [ "memory/shared_memory_mapping.cc" ]',
            1,
        )[1].split("\n  }", 1)[0]

        self.assertIn(
            '"memory/shared_memory_mapping_wasm.cc"',
            full_base_wasm,
        )
        self.assertNotIn(
            '"memory/shared_memory_mapping.cc"',
            full_base_wasm,
        )
        self.assertIn(
            "process-local Wasm\n"
            "  // mappings intentionally alias one allocation",
            mapping,
        )
        self.assertNotIn(
            '#include "base/memory/shared_memory_tracker.h"',
            mapping,
        )
        self.assertNotIn(
            "SharedMemoryTracker::GetInstance()",
            mapping,
        )

    def test_mojo_transfers_virtual_files_with_process_local_ownership(
        self,
    ) -> None:
        file_traits = source("mojo/public/cpp/base/file_mojom_traits.cc")
        read_only_traits = source(
            "mojo/public/cpp/base/read_only_file_mojom_traits.cc"
        )
        platform_handle = source(
            "mojo/public/cpp/platform/platform_handle.h"
        )
        wasm_handle = source(
            "mojo/public/cpp/platform/platform_handle_wasm.cc"
        )
        ipcz = source("mojo/core/core_ipcz.cc")

        for traits in (file_traits, read_only_traits):
            with self.subTest(traits=traits[:40]):
                self.assertNotIn(
                    "Mojo platform file transport is unsupported", traits
                )
                self.assertIn("file.TakePlatformFile()", traits)
                self.assertIn(
                    "data.TakeFd().TakePlatformFile()", traits
                )
        self.assertIn("BUILDFLAG(IS_WASM)", read_only_traits)
        self.assertIn("fcntl(file.GetPlatformFile(), F_GETFL)", read_only_traits)
        self.assertIn("S_ISREG(st.st_mode)", read_only_traits)

        self.assertIn(
            "BUILDFLAG(IS_FUCHSIA) || BUILDFLAG(IS_WASM)",
            platform_handle,
        )
        self.assertIn("return is_valid_fd() ||", platform_handle)
        self.assertIn("return TakeFD();", platform_handle)
        self.assertIn("return ReleaseFD();", platform_handle)
        self.assertIn(
            "explicit PlatformHandle(\n"
            "      base::subtle::ScopedPlatformSharedMemoryHandle handle);",
            platform_handle,
        )
        self.assertIn(
            "PlatformHandle::PlatformHandle(base::ScopedFD fd)", wasm_handle
        )
        self.assertIn(
            "MOJO_PLATFORM_HANDLE_TYPE_FILE_DESCRIPTOR", wasm_handle
        )
        self.assertIn(
            "IsValueInRangeForNumericType<int>(handle->value)", wasm_handle
        )
        self.assertIn("HANDLE_EINTR(dup(fd_.get()))", wasm_handle)
        self.assertIn(
            "MOJO_PLATFORM_HANDLE_TYPE_WASM_SHARED_MEMORY", wasm_handle
        )

        wrap = ipcz.split(
            "MojoResult MojoWrapPlatformHandleIpcz", 1
        )[1].split("MojoResult MojoUnwrapPlatformHandleIpcz", 1)[0]
        unwrap = ipcz.split(
            "MojoResult MojoUnwrapPlatformHandleIpcz", 1
        )[1].split(
            "MojoResult MojoWrapPlatformSharedMemoryRegionIpcz", 1
        )[0]
        self.assertIn(
            "MOJO_PLATFORM_HANDLE_TYPE_FILE_DESCRIPTOR", wrap
        )
        self.assertIn(
            "IsValueInRangeForNumericType<int>(platform_handle->value)",
            wrap,
        )
        self.assertIn(
            "MOJO_PLATFORM_HANDLE_TYPE_WASM_SHARED_MEMORY", wrap
        )
        self.assertIn("return MOJO_RESULT_UNIMPLEMENTED;", wrap)
        self.assertIn("BestEffortScopedIpczHandle owned_handle(mojo_handle);", unwrap)
        self.assertIn("WrappedPlatformHandle::Unbox(owned_handle.get())", unwrap)
        self.assertIn("owned_handle.release();", unwrap)
        self.assertNotIn("return MOJO_RESULT_UNIMPLEMENTED;", unwrap)

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

    def test_content_shell_omits_native_test_target_closure(self) -> None:
        build = source("content/test/BUILD.gn")
        test_support = build.split(
            'static_library("test_support") {', 1
        )[1]
        test_support = test_support.split(
            'group("telemetry_gpu_integration_test_scripts_only")', 1
        )[0]
        self.assertIn(
            "if (!is_wasm) {\n"
            '    deps += [ ":web_ui_mojo_test_resources" ]\n'
            "  }",
            test_support,
        )

        telemetry = build.index(
            'group("telemetry_gpu_integration_test_scripts_only")'
        )
        telemetry_guard = build.rfind("if (!is_wasm) {", 0, telemetry)
        self.assertGreater(telemetry_guard, 0)
        self.assertLess(telemetry - telemetry_guard, 40)

        browser_tests = build.index('test("content_browsertests")')
        browser_tests_guard = build.rfind(
            "if (!is_wasm) {", 0, browser_tests
        )
        self.assertGreater(browser_tests_guard, 0)
        self.assertLess(browser_tests - browser_tests_guard, 250)

    def test_m3_prunes_native_only_resource_generators(self) -> None:
        webauthn = source("components/webauthn/core/browser/BUILD.gn")
        self.assertIn(
            'if (is_apple) {\n'
            '    frameworks = [ "Foundation.framework" ]\n'
            "  }",
            webauthn,
        )

        self.assertIn(
            "if (use_blink && !is_wasm) {",
            source("ipc/BUILD.gn"),
        )
        self.assertIn(
            "if (enable_pdf) {\n"
            '  import("//third_party/pdfium/pdfium.gni")\n'
            "}",
            source("pdf/BUILD.gn"),
        )
        self.assertIn(
            "use_cpuinfo = !is_wasm &&",
            source("third_party/cpuinfo/cpuinfo.gni"),
        )

        wasm_config = source("build/config/wasm.gni")
        blink_public = source("third_party/blink/public/BUILD.gn")
        self.assertIn(
            "enable_chromium_wasm_devtools_resources = false",
            wasm_config,
        )
        self.assertIn(
            "_enable_blink_devtools_resources =\n"
            "    !is_wasm || enable_chromium_wasm_devtools_resources",
            blink_public,
        )
        self.assertIn(
            "if (_enable_blink_devtools_resources) {\n"
            '  grit("devtools_inspector_resources")',
            blink_public,
        )


if __name__ == "__main__":
    unittest.main()
