#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M3ContentShellBuildContractTest(unittest.TestCase):
    def test_content_shell_is_a_dedicated_single_process_wasm_target(
        self,
    ) -> None:
        root_build = source("BUILD.gn")
        build = source("content/shell/BUILD.gn")
        delegate = source("content/shell/app/shell_main_delegate.cc")

        self.assertIn('group("gn_all") {\n    testonly = true', root_build)
        m3_profile = root_build.split(
            "if (enable_chromium_wasm_content) {", 1
        )[1].split("} else {", 1)[0]
        self.assertIn("//content/shell:content_shell_wasm", m3_profile)
        self.assertIn("//tools/wasm:m3_allocator_oom_smoke", m3_profile)
        self.assertNotIn("//tools/wasm:m1_", m3_profile)
        self.assertIn('executable("content_shell_wasm")', build)
        self.assertIn("assert(enable_chromium_wasm_content)", build)
        self.assertIn("command_line.AppendSwitch(switches::kSingleProcess);",
                      delegate)
        self.assertIn(
            "command_line.AppendSwitch(switches::kDisableQuic);", delegate
        )
        self.assertIn(
            "command_line.AppendSwitch(switches::kDisableGpuCompositing);",
            delegate,
        )
        self.assertNotIn(
            "command_line.AppendSwitch(switches::kDisableGpu);",
            delegate,
        )

    def test_content_shell_embeds_required_virtual_filesystem_assets(
        self,
    ) -> None:
        build = source("content/shell/BUILD.gn")

        self.assertIn("@/assets/content_shell.pak", build)
        self.assertIn("@/assets/icudtl.dat", build)
        self.assertIn('"$root_out_dir/content_shell.pak"', build)
        self.assertIn('"$root_out_dir/icudtl.dat"', build)
        self.assertIn('"//third_party/icu:icudata"', build)

    def test_m3_pak_keeps_only_data_page_and_aura_resources(self) -> None:
        build = source("content/shell/BUILD.gn")
        pak = build.split('repack("pak") {', 1)[1].split(
            "if (is_android) {", 1
        )[0]
        wasm_pak = pak.split("if (is_wasm) {", 1)[1].split(
            "if (enable_vr)", 1
        )[0]

        for resource in (
            "content/shell/shell_resources.pak",
            "net/net_resources.pak",
            "third_party/blink/public/resources/blink_resources.pak",
            "third_party/blink/public/resources/"
            "blink_scaled_resources_100_percent.pak",
            "third_party/blink/public/strings/blink_strings_en-US.pak",
            "ui/resources/ui_lottie_resources.pak",
            "ui/resources/ui_resources_100_percent.pak",
            "ui/strings/app_locale_settings_en-US.pak",
            "ui/strings/auto_image_annotation_strings_en-US.pak",
            "ui/strings/ax_strings_en-US.pak",
            "ui/strings/ui_strings_en-US.pak",
        ):
            with self.subTest(resource=resource):
                self.assertIn(resource, wasm_pak)

        for dependency in (
            ":resources",
            "//net:net_resources",
            "//third_party/blink/public:resources",
            "//third_party/blink/public:scaled_resources_100_percent",
            "//third_party/blink/public/strings",
            "//ui/resources",
            "//ui/strings",
        ):
            with self.subTest(dependency=dependency):
                self.assertIn(f'"{dependency}"', wasm_pak)

        for excluded in (
            "tracing",
            "ukm",
            "content/browser/resources",
            "media_internals",
            "webrtc_internals",
            "content_resources.pak",
            "web_ui_mojo",
            "mojo_bindings_resources",
            "inspector_overlay",
            "permission_element",
            "ui/webui/resources",
        ):
            with self.subTest(excluded=excluded):
                self.assertNotIn(excluded, wasm_pak)

        self.assertIn(
            "if (!is_android && !is_ios && !is_wasm) {",
            pak,
        )

    def test_content_shell_uses_an_honest_memfs_profile_directory(
        self,
    ) -> None:
        paths = source("content/shell/common/shell_paths.cc")

        wasm_default = paths.split(
            "#elif BUILDFLAG(IS_WASM)", 1
        )[1].split("#else", 1)[0]
        self.assertIn(
            "base::PathService::Get(base::DIR_HOME, &home)",
            wasm_default,
        )
        self.assertIn(
            '*result = home.Append(FILE_PATH_LITERAL("content_shell"));',
            wasm_default,
        )
        self.assertNotIn("NOTIMPLEMENTED", wasm_default)
        self.assertIn(
            "return base::DirectoryExists(path) || "
            "base::CreateDirectory(path);",
            paths,
        )
        self.assertIn(
            "if (!GetDefaultUserDataDirectory(&path) ||\n"
            "          !ShellPathProvider::CreateDir(path))",
            paths,
        )
        assignment = paths.rindex("*result = path;")
        creation_check = paths.rindex("!ShellPathProvider::CreateDir(path)")
        self.assertGreater(assignment, creation_check)

    def test_content_shell_does_not_link_apple_frameworks_on_wasm(
        self,
    ) -> None:
        build = source("components/webauthn/core/browser/BUILD.gn")
        passkey_model = build.split(
            'source_set("passkey_model") {', 1
        )[1].split('source_set("client_data") {', 1)[0]

        self.assertIn(
            'if (is_apple) {\n'
            '    frameworks = [ "Foundation.framework" ]\n'
            "  }",
            passkey_model,
        )
        self.assertNotIn(
            '\n  frameworks = [ "Foundation.framework" ]\n',
            passkey_model.split("if (is_apple)", 1)[0],
        )

    def test_wasm_child_process_launcher_is_an_explicit_failure_boundary(
        self,
    ) -> None:
        build = source("content/browser/BUILD.gn")
        header = source(
            "content/browser/child_process_launcher_helper.h"
        )
        wasm = source(
            "content/browser/child_process_launcher_helper_wasm.cc"
        )

        self.assertIn(
            'if (is_wasm) {\n'
            '    sources += [ "child_process_launcher_helper_wasm.cc" ]\n'
            "  } else if (is_fuchsia)",
            build,
        )
        self.assertIn(
            "#elif BUILDFLAG(IS_POSIX) || BUILDFLAG(IS_FUCHSIA)\n"
            '#include "content/public/browser/'
            'posix_file_descriptor_info.h"',
            header,
        )
        mapping_block = header.split(
            "namespace internal {", 1
        )[1].split("#if BUILDFLAG(IS_IOS)", 1)[0]
        wasm_mapping = mapping_block.split(
            "#elif BUILDFLAG(IS_WASM)", 1
        )[1].split("#else", 1)[0]
        self.assertIn("UnsupportedFileMappedForLaunch", wasm_mapping)
        self.assertNotIn("PosixFileDescriptorInfo", wasm_mapping)
        self.assertNotIn("HandlesToInheritVector", wasm_mapping)
        self.assertIn(
            "Child process launch is unsupported in single-process "
            "WebAssembly",
            wasm,
        )
        self.assertIn("*launch_result = LAUNCH_RESULT_FAILURE;", wasm)
        self.assertIn("TERMINATION_STATUS_LAUNCH_FAILED", wasm)
        self.assertNotIn("base::LaunchProcess(", wasm)

    def test_renderer_kill_debug_url_is_explicitly_unsupported(self) -> None:
        debug_urls = source(
            "third_party/blink/common/chrome_debug_urls.cc"
        )
        kill_handler = debug_urls.split(
            "} else if (url == kChromeUIKillURL)", 1
        )[1].split(
            "} else if (url == kChromeUIHangURL)", 1
        )[0]
        wasm_handler = kill_handler.split(
            "#elif BUILDFLAG(IS_WASM)", 1
        )[1].split("#else", 1)[0]

        self.assertIn(
            "chrome://kill is unsupported in single-process WebAssembly",
            wasm_handler,
        )
        self.assertIn("return;", wasm_handler)
        self.assertNotIn("TerminateCurrentProcessImmediately", wasm_handler)
        self.assertNotIn("kill(", wasm_handler)
        self.assertNotIn("zx_process_exit", wasm_handler)

    def test_m3_forces_host_navigation_and_one_top_level_shell(self) -> None:
        build = source("content/shell/BUILD.gn")
        shell = source("content/shell/browser/shell.cc")
        browser_client = source(
            "content/shell/browser/shell_content_browser_client.cc"
        )
        main_parts = source(
            "content/shell/browser/shell_browser_main_parts.cc"
        )

        startup = main_parts.split("GURL GetStartupURL()", 1)[1].split(
            "scoped_refptr<base::RefCountedMemory>", 1
        )[0]
        wasm_startup = startup.split(
            "#if BUILDFLAG(IS_WASM)", 1
        )[1].split("#else", 1)[0]
        self.assertIn("return GURL(url::kAboutBlankURL);", wasm_startup)
        self.assertNotIn("GetArgs()", wasm_startup)

        add_new_contents = shell.split(
            "WebContents* Shell::AddNewContents", 1
        )[1].split("void Shell::GoBackOrForward", 1)[0]
        self.assertIn("#if BUILDFLAG(IS_WASM)", add_new_contents)
        self.assertIn("*was_blocked = true;", add_new_contents)
        self.assertIn("return nullptr;", add_new_contents)

        open_from_tab = shell.split(
            "WebContents* Shell::OpenURLFromTab", 1
        )[1].split("void Shell::LoadingStateChanged", 1)[0]
        self.assertIn(
            "Additional Content Shell surfaces are unsupported until",
            open_from_tab,
        )
        self.assertIn("return nullptr;", open_from_tab)

        open_url = browser_client.split(
            "void ShellContentBrowserClient::OpenURL", 1
        )[1].split(
            "void ShellContentBrowserClient::CreateThrottlesForNavigation",
            1,
        )[0]
        wasm_open_url = open_url.split(
            "#if BUILDFLAG(IS_WASM)", 1
        )[1].split("#else", 1)[0]
        self.assertIn("std::move(callback).Run(nullptr);", wasm_open_url)
        self.assertNotIn("CreateNewWindow", wasm_open_url)

        bind_control = browser_client.split(
            "void ShellContentBrowserClient::BindBrowserControlInterface",
            1,
        )[1].split(
            "void ShellContentBrowserClient::set_browser_main_parts", 1
        )[0]
        self.assertIn("#if BUILDFLAG(IS_WASM)", bind_control)
        self.assertIn("pipe.reset();", bind_control)

        content_shell_lib = build.split(
            'static_library("content_shell_lib")', 1
        )[1].split('mojom("shell_controller_mojom")', 1)[0]
        wasm_lib = content_shell_lib.split("if (is_wasm) {", 1)[1]
        for omitted in (
            '"renderer/shell_render_frame_observer.cc"',
            '"renderer/shell_render_frame_observer.h"',
            '":shell_controller_mojom"',
        ):
            with self.subTest(omitted=omitted):
                self.assertIn(omitted, wasm_lib)
        self.assertIn(
            'if (!is_wasm) {\n  mojom("shell_controller_mojom")',
            build,
        )

        content_shell_app = build.split(
            'static_library("content_shell_app")', 1
        )[1].split('static_library("content_shell_lib")', 1)[0]
        app_wasm = content_shell_app.split("if (is_wasm) {", 1)[1].split(
            "} else {", 1
        )[0]
        self.assertIn(
            'deps += [ "//components/network_session_configurator/common" ]',
            app_wasm,
        )


if __name__ == "__main__":
    unittest.main()
