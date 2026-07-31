#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M3PlatformSourceContractTest(unittest.TestCase):
    def test_storage_file_paths_round_trip_as_utf8_on_wasm(
        self,
    ) -> None:
        file_system_util = source(
            "storage/common/file_system/file_system_util.cc"
        )
        encode = file_system_util.split(
            "std::string FilePathToString", 1
        )[1].split("base::FilePath StringToFilePath", 1)[0]
        decode = file_system_util.split(
            "base::FilePath StringToFilePath", 1
        )[1].split("bool GetFileSystemPublicType", 1)[0]

        wasm_encode = encode.split("#elif BUILDFLAG(IS_WASM)", 1)[1].split(
            "#endif", 1
        )[0]
        wasm_decode = decode.split("#elif BUILDFLAG(IS_WASM)", 1)[1].split(
            "#endif", 1
        )[0]
        self.assertIn(
            "Wasm filesystem paths are UTF-8 strings",
            wasm_encode,
        )
        self.assertIn("return file_path.value();", wasm_encode)
        self.assertIn(
            "Preserve the UTF-8 bytes used by Emscripten",
            wasm_decode,
        )
        self.assertIn(
            "return base::FilePath(file_path_string);",
            wasm_decode,
        )

    def test_wasm_resource_bundle_uses_staged_data_packs(
        self,
    ) -> None:
        build = source("ui/base/BUILD.gn")
        resource_bundle = source(
            "ui/base/resource/resource_bundle_wasm.cc"
        )

        self.assertIn(
            "if (is_wasm) {\n"
            '    sources += [ "resource/resource_bundle_wasm.cc" ]\n'
            "  }",
            build,
        )
        load_common = resource_bundle.split(
            "void ResourceBundle::LoadCommonResources()", 1
        )[1].split(
            "gfx::Image& ResourceBundle::GetNativeImageNamed", 1
        )[0]
        self.assertIn("staged in the module filesystem", load_common)
        self.assertIn("LoadChromeResources();", load_common)
        native_image = resource_bundle.split(
            "gfx::Image& ResourceBundle::GetNativeImageNamed", 1
        )[1]
        self.assertIn(
            "Wasm has no separate host-native image type",
            native_image,
        )
        self.assertIn("return GetImageNamed(resource_id);", native_image)
        self.assertNotIn("GetEmptyImage", native_image)

    def test_wasm_font_enumeration_does_not_probe_host_fonts(
        self,
    ) -> None:
        build = source("content/common/BUILD.gn")
        font_list = source("content/common/font_list_wasm.cc")

        self.assertIn(
            'if (is_wasm) {\n    sources += [ "font_list_wasm.cc" ]\n  }',
            build,
        )
        self.assertIn(
            "is_fuchsia || is_ios || is_wasm",
            build,
        )
        self.assertIn(
            'sources -= [ "font_list_fontconfig.cc" ]',
            build,
        )
        self.assertIn(
            "does not expose the outer browser's installed fonts",
            font_list,
        )
        self.assertIn("return base::ListValue();", font_list)
        self.assertNotIn("fontconfig", font_list.lower())

    def test_cloud_policy_does_not_fabricate_wasm_host_identity(
        self,
    ) -> None:
        policy = source(
            "components/policy/core/common/cloud/cloud_policy_util.cc"
        )
        machine_name = policy.split("std::string GetMachineName()", 1)[
            1
        ].split("std::string GetOSVersion()", 1)[0]
        os_version = policy.split("std::string GetOSVersion()", 1)[1].split(
            "std::string GetOSPlatform()", 1
        )[0]
        username = policy.split("std::string GetOSUsername()", 1)[1].split(
            "em::Channel ConvertToProtoChannel", 1
        )[0]

        wasm_machine_name = machine_name.split(
            "#elif BUILDFLAG(IS_WASM)", 1
        )[1].split("#else", 1)[0]
        self.assertIn(
            "The host page does not expose a stable machine identity",
            wasm_machine_name,
        )
        self.assertIn("return std::string();", wasm_machine_name)
        self.assertNotIn("gethostname", wasm_machine_name)
        self.assertIn(
            "BUILDFLAG(IS_FUCHSIA) || BUILDFLAG(IS_WASM)",
            os_version,
        )
        self.assertIn(
            "return base::SysInfo::OperatingSystemVersion();",
            os_version,
        )
        self.assertIn(
            "BUILDFLAG(IS_FUCHSIA) || BUILDFLAG(IS_WASM)",
            username,
        )
        self.assertIn("return std::string();", username)

    def test_trusted_vault_does_not_report_a_wasm_host_os(self) -> None:
        connection = source(
            "components/trusted_vault/trusted_vault_connection_impl.cc"
        )
        device_type = connection.split(
            "GetLocalPhysicalDeviceType()", 1
        )[1].split("CreateSecurityDomainMember", 1)[0]
        wasm_device_type = device_type.split(
            "#elif BUILDFLAG(IS_WASM)", 1
        )[1].split("#else", 1)[0]

        self.assertIn(
            "The host OS is outside the Wasm platform boundary",
            wasm_device_type,
        )
        self.assertIn(
            "return trusted_vault_pb::PhysicalDeviceMetadata::"
            "DEVICE_TYPE_UNKNOWN;",
            wasm_device_type,
        )
        for native_type in (
            "DEVICE_TYPE_ANDROID",
            "DEVICE_TYPE_CHROMEOS",
            "DEVICE_TYPE_IOS",
            "DEVICE_TYPE_LINUX",
            "DEVICE_TYPE_MAC_OS",
            "DEVICE_TYPE_WINDOWS",
        ):
            self.assertNotIn(native_type, wasm_device_type)

    def test_m3_sources_use_typed_optional_fallbacks(self) -> None:
        signin = source(
            "components/signin/public/base/hybrid_encryption_key.cc"
        )
        autofill = source(
            "components/autofill/core/browser/payments/"
            "full_card_request.cc"
        )
        service_worker = source(
            "content/browser/service_worker/service_worker_version.cc"
        )

        self.assertIn(
            "result.value_or(std::vector<uint8_t>{})",
            signin,
        )
        self.assertIn(
            "std::move(context_token).value_or(std::string{})",
            autofill,
        )
        self.assertIn(
            "request->timeout_iter.value_or(\n"
            "        std::set<InflightRequestTimeoutInfo>::iterator{})",
            service_worker,
        )
        for body in (signin, autofill, service_worker):
            self.assertNotIn(".value_or({})", body)

    def test_signin_builder_includes_destroyed_delegate_definition(
        self,
    ) -> None:
        builder = source(
            "components/signin/internal/identity_manager/"
            "profile_oauth2_token_service_builder.cc"
        )

        unconditional_includes = builder.split(
            "#if BUILDFLAG(IS_ANDROID)", 1
        )[0]
        self.assertIn(
            '#include "components/signin/internal/identity_manager/'
            'profile_oauth2_token_service_delegate.h"',
            unconditional_includes,
        )
        self.assertIn(
            "std::unique_ptr<ProfileOAuth2TokenServiceDelegate>\n"
            "CreateOAuth2TokenServiceDelegate(",
            builder,
        )

    def test_gin_uses_v8s_default_wasm_page_allocator(
        self,
    ) -> None:
        build = source("gin/BUILD.gn")
        platform = source("gin/v8_platform.cc")
        v8_allocation = source("v8/src/utils/allocation.cc")

        self.assertIn(
            'sources += [ "v8_platform_page_allocator.h" ]\n'
            "    if (!is_wasm) {\n"
            '      sources += [ "v8_platform_page_allocator.cc" ]\n'
            "    }",
            build,
        )
        self.assertIn(
            "if (use_partition_alloc && !is_wasm) {\n"
            '    sources += [ "v8_platform_page_allocator_unittest.cc" ]',
            build,
        )
        self.assertIn(
            "#if PA_BUILDFLAG(USE_PARTITION_ALLOC) && "
            "!BUILDFLAG(IS_WASM)\n\n"
            "base::LazyInstance<gin::PageAllocator>::Leaky "
            "g_page_allocator",
            platform,
        )
        get_allocator = platform.split(
            "PageAllocator* V8Platform::GetPageAllocator()", 1
        )[1].split(
            "#if PA_BUILDFLAG(ENABLE_THREAD_ISOLATION)", 1
        )[0]
        wasm_allocator = get_allocator.split(
            "#if BUILDFLAG(IS_WASM)", 1
        )[1].split("#else", 1)[0]
        self.assertIn(
            "V8's Emscripten allocator records every logical permission "
            "transition",
            wasm_allocator,
        )
        self.assertIn("return nullptr;", wasm_allocator)
        self.assertNotIn("g_page_allocator.Pointer()", wasm_allocator)
        self.assertIn(
            "if (page_allocator_ == nullptr) {\n"
            "      static base::LeakyObject<base::PageAllocator> "
            "default_page_allocator;",
            v8_allocation,
        )

    def test_wasm_sql_and_url_paths_use_explicit_utf8_semantics(
        self,
    ) -> None:
        database = source("sql/database.cc")
        url_fixer = source("components/url_formatter/url_fixer.cc")

        sql_path_conversion = database.split(
            "std::string AsUTF8ForSQL", 1
        )[1].split("// These values are persisted", 1)[0]
        self.assertIn(
            "#elif BUILDFLAG(IS_WASM)\n"
            "  // Emscripten virtual filesystem paths use UTF-8.\n"
            "  return path.value();",
            sql_path_conversion,
        )

        sql_error_diagnostics = database.split(
            "// System error information.", 1
        )[1].split("  if (stmt)", 1)[0]
        wasm_error_diagnostics = sql_error_diagnostics.split(
            "#elif BUILDFLAG(IS_WASM)", 1
        )[1].split("#else", 1)[0]
        self.assertIn(
            "// SQLite's Emscripten-backed VFS exposes filesystem failures "
            "through errno.",
            wasm_error_diagnostics,
        )
        self.assertIn(
            'base::StringAppendF(&debug_info, "errno: %d\\n", '
            "last_errno);",
            wasm_error_diagnostics,
        )
        self.assertIn(
            "diagnostics->last_errno = last_errno;",
            wasm_error_diagnostics,
        )

        relative_file_fixup = url_fixer.split(
            "GURL FixupRelativeFile", 1
        )[1].split("void OffsetComponent", 1)[0]
        self.assertIn(
            "#elif BUILDFLAG(IS_WASM)\n"
            "  // Emscripten virtual filesystem paths use UTF-8.\n"
            "  std::string text_utf8 = text.value();",
            relative_file_fixup,
        )

    def test_wasm_stack_bounds_use_current_emscripten_thread(self) -> None:
        stack_util = source(
            "third_party/blink/renderer/platform/wtf/stack_util.cc"
        )

        self.assertIn(
            "#if BUILDFLAG(IS_WASM)\n#include <emscripten/stack.h>",
            stack_util,
        )

        estimate = stack_util.split(
            "size_t GetUnderestimatedStackSize()", 1
        )[1].split("namespace {", 1)[0]
        wasm_estimate = estimate.split(
            "#elif BUILDFLAG(IS_WASM)", 1
        )[1].split("#else", 1)[0]
        self.assertIn(
            "const uintptr_t stack_base = emscripten_stack_get_base();",
            wasm_estimate,
        )
        self.assertIn(
            "const uintptr_t stack_end = emscripten_stack_get_end();",
            wasm_estimate,
        )
        self.assertIn("CHECK_GT(stack_base, stack_end);", wasm_estimate)
        self.assertIn("return stack_base - stack_end;", wasm_estimate)
        self.assertNotIn("return 0;", wasm_estimate)

        get_stack_start = stack_util.split(
            "void* GetStackStartImpl()", 1
        )[1].split("}  // namespace", 1)[0]
        wasm_stack_start = get_stack_start.split(
            "#elif BUILDFLAG(IS_WASM)", 1
        )[1].split(
            "#elif BUILDFLAG(IS_WIN)", 1
        )[0]
        self.assertIn(
            "const uintptr_t stack_base = emscripten_stack_get_base();",
            wasm_stack_start,
        )
        self.assertIn(
            "return reinterpret_cast<void*>(stack_base);",
            wasm_stack_start,
        )

    def test_wasm_flac_enables_its_required_libc_declarations(
        self,
    ) -> None:
        build = source("third_party/flac/BUILD.gn")
        public_config = build.split(
            'config("flac_config") {', 1
        )[1].split("}", 1)[0]
        flac_target = build.split(
            'source_set("flac") {', 1
        )[1]

        self.assertNotIn("_GNU_SOURCE", public_config)
        self.assertIn(
            "if (is_wasm) {\n"
            "    # Chromium's strict C11 Wasm configuration does not "
            "enable the libc\n"
            "    # declarations that libFLAC expects from GNU/POSIX "
            "environments.\n"
            '    defines += [ "_GNU_SOURCE" ]\n'
            "  }",
            flac_target,
        )

    def test_wasm_minizip_preserves_zip64_file_offsets(self) -> None:
        build = source("third_party/zlib/BUILD.gn")
        public_config = build.split(
            'config("zlib_config") {', 1
        )[1].split("}", 1)[0]
        minizip_target = build.split(
            'static_library("minizip") {', 1
        )[1].split('executable("zlib_bench")', 1)[0]
        wasm_features = minizip_target.split(
            "if (is_wasm) {", 1
        )[1].split("}", 1)[0]

        self.assertIn("Minizip's Zip64 path", wasm_features)
        self.assertIn("Emscripten's strict C11", wasm_features)
        self.assertIn(
            'defines = [ "_POSIX_C_SOURCE=200112L" ]',
            wasm_features,
        )
        self.assertNotIn("_GNU_SOURCE", wasm_features)
        self.assertNotIn("USE_FILE32API", wasm_features)
        for private_feature in (
            "_POSIX_C_SOURCE",
            "_GNU_SOURCE",
            "USE_FILE32API",
        ):
            self.assertNotIn(private_feature, public_config)

    def test_wasm_has_keyboard_code_values_without_posix_input(self) -> None:
        selector = source("ui/events/keycodes/keyboard_codes.h")
        wasm_codes = source("ui/events/keycodes/keyboard_codes_wasm.h")

        self.assertIn(
            '#elif BUILDFLAG(IS_WASM)\n'
            '#include "ui/events/keycodes/keyboard_codes_wasm.h"',
            selector,
        )
        self.assertIn(
            '#include "ui/events/keycodes/keyboard_codes_posix.h"',
            wasm_codes,
        )
        self.assertNotIn("BUILDFLAG(IS_POSIX)", wasm_codes)
        self.assertNotIn("PlatformEvent", wasm_codes)

    def test_wasm_denormal_fallback_has_no_virtual_final_destructor(
        self,
    ) -> None:
        disabler = source(
            "third_party/blink/renderer/platform/audio/"
            "denormal_disabler.h"
        )
        fallback = disabler.split(
            "// FIXME: add implementations for other architectures", 1
        )[1].split("#endif", 1)[0]

        self.assertIn("class DenormalModifier final", fallback)
        self.assertIn("~DenormalModifier() = default;", fallback)
        self.assertNotIn("virtual ~DenormalModifier()", fallback)

    def test_system_font_render_style_uses_only_supported_platforms(
        self,
    ) -> None:
        platform_data = source(
            "third_party/blink/renderer/platform/fonts/"
            "font_platform_data.cc"
        )
        query = platform_data.split(
            "WebFontRenderStyle FontPlatformData::QuerySystemRenderStyle", 1
        )[1].split("return result;", 1)[0]

        self.assertIn(
            "#if BUILDFLAG(IS_LINUX) || BUILDFLAG(IS_CHROMEOS)", query
        )
        self.assertIn("FontCache::DeviceScaleFactor()", query)
        self.assertNotIn(
            "#if !BUILDFLAG(IS_ANDROID) && !BUILDFLAG(IS_FUCHSIA)",
            query,
        )

    def test_blink_thread_id_can_hold_the_wasm_base_thread_id(
        self,
    ) -> None:
        scheduler_thread = source(
            "third_party/blink/renderer/platform/scheduler/common/thread.cc"
        )
        wasm_id_check = scheduler_thread.split(
            "#elif BUILDFLAG(IS_WASM)", 1
        )[1].split("#else", 1)[0]

        self.assertIn("sizeof(blink::PlatformThreadId)", wasm_id_check)
        self.assertIn(
            "sizeof(base::PlatformThreadId::UnderlyingType)",
            wasm_id_check,
        )
        self.assertNotIn("#error", wasm_id_check)

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

    def test_wasm_xml_libraries_use_the_pinned_portable_config(
        self,
    ) -> None:
        libxml = source("third_party/libxml/BUILD.gn")
        libxslt = source("third_party/libxslt/BUILD.gn")

        self.assertIn("is_android || is_fuchsia || is_wasm", libxml)
        self.assertIn(
            "if (is_linux || is_chromeos || is_wasm) {\n"
            '    sources += [ "linux/config.h" ]',
            libxslt,
        )
        self.assertIn(
            "is_android || is_fuchsia || is_wasm) {\n"
            '    include_dirs = [ "linux" ]',
            libxslt,
        )


if __name__ == "__main__":
    unittest.main()
