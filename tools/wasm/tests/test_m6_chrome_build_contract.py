#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import json
import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M6ChromeBuildContractTest(unittest.TestCase):
    @staticmethod
    def _braced_body(build_file: str, body_start: int, description: str) -> str:
        """Returns the contents of the braced GN/C++ block at |body_start|."""
        if body_start == -1:
            raise AssertionError(f"{description} has no opening brace")

        depth = 0
        for index in range(body_start, len(build_file)):
            if build_file[index] == "{":
                depth += 1
            elif build_file[index] == "}":
                depth -= 1
                if depth == 0:
                    return build_file[body_start + 1:index]
        raise AssertionError(f"{description} has no closing brace")

    @staticmethod
    def _gn_target_body(
        build_file: str, target: str, *target_kinds: str
    ) -> str:
        """Returns a GN target body without depending on whitespace/layout."""
        kinds = target_kinds or ("source_set",)
        target_pattern = "|".join(re.escape(kind) for kind in kinds)
        match = re.search(
            rf"\b(?:{target_pattern})\s*\(\s*\"{re.escape(target)}\"\s*\)",
            build_file,
        )
        if not match:
            raise AssertionError(
                f"could not find {'/'.join(kinds)} target {target!r}"
            )

        return M6ChromeBuildContractTest._braced_body(
            build_file, build_file.find("{", match.end()), f"target {target!r}"
        )

    @classmethod
    def _source_set_body(cls, build_file: str, target: str) -> str:
        return cls._gn_target_body(build_file, target, "source_set")

    @classmethod
    def _wasm_chrome_target(cls) -> str:
        return cls._gn_target_body(
            source("chrome/BUILD.gn"), "chrome_wasm", "executable"
        )

    @classmethod
    def _wasm_chrome_section(cls) -> str:
        chrome_build = source("chrome/BUILD.gn")
        match = re.search(
            r"if\s*\(\s*is_wasm\s*&&\s*"
            r"enable_chromium_wasm_chrome\s*\)\s*\{",
            chrome_build,
        )
        if not match:
            raise AssertionError("could not find the Wasm Chrome GN section")
        return cls._braced_body(
            chrome_build, chrome_build.find("{", match.start()), "Wasm Chrome section"
        )

    def test_m6_profile_extends_the_passing_m3_profile(self) -> None:
        manifest = json.loads(source("tools/wasm/toolchain_manifest.json"))
        m3_arguments = manifest["m3_content_gn_args"]
        m6_arguments = manifest["m6_chrome_gn_args"]

        self.assertEqual(len(m6_arguments), len(set(m6_arguments)))
        self.assertTrue(set(m3_arguments).issubset(m6_arguments))

        assignments = {}
        for argument in m6_arguments:
            name, value = argument.split(" = ", 1)
            self.assertNotIn(name, assignments)
            assignments[name] = value

        self.assertEqual(
            {
                "enable_chromium_wasm_chrome": "true",
                "enable_chromium_wasm_content": "true",
                "enable_chromium_wasm_v8": "true",
                "use_aura": "true",
                "use_ozone": "true",
                "toolkit_views": "true",
                "enable_hidpi": "true",
                "enable_supervised_users": "false",
                "enable_background_contents": "false",
                "enable_background_mode": "false",
                "enable_downgrade_processing": "false",
                "enable_session_service": "false",
                "enable_chrome_notifications": "false",
                "enable_message_center": "false",
                "enable_platform_experience": "false",
                "enable_updater": "false",
                "enable_update_notifications": "false",
                "enterprise_watermark": "false",
                "chrome_root_store_cert_management_ui": "false",
                "enable_webui_certificate_viewer": "false",
                "enable_extensions": "false",
                "enable_library_cdms": "false",
                "enable_widevine": "false",
                "enable_printing": "false",
                "enable_oop_printing": "false",
            }.items(),
            {name: assignments[name] for name in (
                "enable_chromium_wasm_chrome",
                "enable_chromium_wasm_content",
                "enable_chromium_wasm_v8",
                "use_aura",
                "use_ozone",
                "toolkit_views",
                "enable_hidpi",
                "enable_supervised_users",
                "enable_background_contents",
                "enable_background_mode",
                "enable_downgrade_processing",
                "enable_session_service",
                "enable_chrome_notifications",
                "enable_message_center",
                "enable_platform_experience",
                "enable_updater",
                "enable_update_notifications",
                "enterprise_watermark",
                "chrome_root_store_cert_management_ui",
                "enable_webui_certificate_viewer",
                "enable_extensions",
                "enable_library_cdms",
                "enable_widevine",
                "enable_printing",
                "enable_oop_printing",
            )}.items(),
        )

    def test_m6_selects_a_dedicated_chrome_target(self) -> None:
        root_build = source("BUILD.gn")
        chrome_build = source("chrome/BUILD.gn")

        for assertion in (
            "assert(!enable_chromium_wasm_chrome || enable_chromium_wasm_content,",
            "assert(!enable_chromium_wasm_chrome || chromium_wasm_pthread_pool_size >= 4,",
            "if (enable_chromium_wasm_chrome) {\n"
            "      deps = [ \"//chrome:chrome_wasm($default_toolchain)\" ]",
        ):
            with self.subTest(assertion=assertion):
                self.assertIn(assertion, root_build)

        wasm_target = self._wasm_chrome_section()
        self.assertIn('executable("chrome_wasm")', wasm_target)
        self.assertIn('assert(use_aura)', wasm_target)
        self.assertIn('assert(use_ozone)', wasm_target)
        self.assertIn('assert(toolkit_views)', wasm_target)
        self.assertIn('"//ui/ozone",', wasm_target)
        self.assertNotIn('"//ui/ozone/platform/wasm:wasm",', wasm_target)

    def test_m6_embeds_the_complete_initial_chrome_resource_set(self) -> None:
        chrome_build = source("chrome/BUILD.gn")
        wasm_target = self._wasm_chrome_section()

        for asset in (
            "chrome_100_percent.pak",
            "chrome_200_percent.pak",
            "resources.pak",
            "locales/en-US.pak",
            "icudtl.dat",
        ):
            with self.subTest(asset=asset):
                self.assertIn(f"@/assets/{asset}", wasm_target)
                self.assertIn(f'\"$root_out_dir/{asset}\"', wasm_target)

    def test_m6_resource_closure_avoids_desktop_resource_aggregates(self) -> None:
        chrome_build = source("chrome/BUILD.gn")
        paks = source("chrome/chrome_paks.gni")
        browser_resources = source("chrome/browser/wasm/BUILD.gn")

        wasm_target = self._wasm_chrome_section()

        self.assertIn('chrome_repack_wasm_percent("wasm_packed_resources_100_percent")', wasm_target)
        self.assertIn('chrome_repack_wasm_percent("wasm_packed_resources_200_percent")', wasm_target)
        self.assertIn('chrome_repack_wasm_locales("wasm_packed_resources_locales")', wasm_target)
        self.assertIn('"//chrome/browser/wasm:browser_resources",', wasm_target)
        self.assertNotIn('"//chrome/browser:resources",', wasm_target)
        self.assertIn('template("chrome_repack_wasm_percent")', paks)
        self.assertIn('template("chrome_repack_wasm_locales")', paks)
        self.assertNotIn('"//components/resources",', paks.split(
            'template("chrome_repack_wasm_percent")', 1
        )[1].split('template("chrome_repack_wasm_locales")', 1)[0])
        self.assertIn('assert(is_wasm && enable_chromium_wasm_chrome)', browser_resources)
        self.assertIn('source = "../browser_resources.grd"', browser_resources)
        self.assertIn('source = "../resources/app_icon/app_icon_resources.grd"', browser_resources)

    def test_m6_extends_the_wasm_aura_and_ozone_selectors(self) -> None:
        ui_config = source("build/config/ui.gni")
        ozone_config = source("build/config/ozone.gni")

        for config in (ui_config, ozone_config):
            self.assertIn("enable_chromium_wasm_content || enable_chromium_wasm_chrome", config)
        self.assertIn("(is_wasm && enable_chromium_wasm_chrome)", ui_config)
        self.assertIn("ozone_auto_platforms = use_ozone && !is_wasm", ozone_config)

    def test_m6_source_selects_a_direct_wasm_browser_foundation(self) -> None:
        wasm_build = source("chrome/browser/wasm/BUILD.gn")
        browser_process_header = source(
            "chrome/browser/wasm/wasm_browser_process.h"
        )
        browser_process_source = source(
            "chrome/browser/wasm/wasm_browser_process.cc"
        )
        profile_header = source("chrome/browser/wasm/wasm_profile.h")
        profile_source = source("chrome/browser/wasm/wasm_profile.cc")

        # The Wasm foundation is deliberately separate from BrowserProcessImpl
        # and ProfileImpl: those desktop aggregates pull unsupported services
        # into the initial Chrome graph.
        self.assertRegex(
            browser_process_header,
            r"class\s+WasmBrowserProcess(?:\s+final)?\s*:\s*public\s+"
            r"BrowserProcess\b",
        )
        self.assertNotRegex(
            browser_process_header,
            r"class\s+WasmBrowserProcess[^\{]*:\s*public\s+"
            r"BrowserProcessImpl\b",
        )
        self.assertRegex(
            profile_header,
            r"class\s+WasmProfile(?:\s+final)?\s*:\s*public\s+Profile\b",
        )
        self.assertNotRegex(
            profile_header,
            r"class\s+WasmProfile[^\{]*:\s*public\s+"
            r"(?:TestingProfile|ProfileImpl)\b",
        )

        # The bootstrap profile and local state are intentionally volatile
        # until M7 mounts an OPFS-backed profile.  Keep both ownership and the
        # production in-memory PrefService construction explicit.
        for token in ("InMemoryPrefStore", "PrefServiceFactory", "PrefRegistrySimple"):
            with self.subTest(token=token):
                self.assertIn(token, browser_process_source)
        self.assertRegex(
            browser_process_header,
            r"std::unique_ptr\s*<\s*PrefService\s*>\s*\w+_",
        )
        self.assertIn("InMemoryPrefStore", profile_source)
        self.assertIn("SimpleKeyMap", profile_source)
        self.assertRegex(
            profile_header,
            r"std::unique_ptr\s*<\s*PrefService\s*>\s*\w+_",
        )
        self.assertRegex(
            profile_header,
            r"std::unique_ptr\s*<\s*ProfileKey\s*>\s*\w+_",
        )

        # BrowserProcess consumers must see the Wasm instance for precisely
        # its lifetime; this also prevents a later generic process singleton
        # from being retained accidentally.
        self.assertRegex(
            browser_process_source, r"\bg_browser_process\s*=\s*this\s*;"
        )
        self.assertRegex(
            browser_process_source, r"\bg_browser_process\s*=\s*nullptr\s*;"
        )
        for token in (
            "DeviceParentalControlsNoOpImpl",
            "ui::UnownedUserDataHost",
            "SEQUENCE_CHECKER",
            "SetProfileManager",
            "SetSystemNetworkContextManager",
            "SetSharedURLLoaderFactory",
            "SetNetworkQualityTracker",
        ):
            with self.subTest(token=token):
                self.assertIn(token, browser_process_header + browser_process_source)

        # The implementation is selected only by the M6 Wasm target.  In
        # particular, depend on profile_key directly rather than the desktop
        # profiles/misc aggregate.
        self.assertIn("assert(is_wasm && enable_chromium_wasm_chrome)", wasm_build)
        browser_process_target = self._source_set_body(
            wasm_build, "wasm_browser_process"
        )
        profile_target = self._source_set_body(wasm_build, "wasm_profile")
        for filename in (
            "wasm_browser_process.cc",
            "wasm_browser_process.h",
        ):
            with self.subTest(filename=filename):
                self.assertIn(f'"{filename}"', browser_process_target)
        for filename in ("wasm_profile.cc", "wasm_profile.h"):
            with self.subTest(filename=filename):
                self.assertIn(f'"{filename}"', profile_target)
        self.assertIn('"//chrome/browser/profiles:profile_key",', profile_target)
        self.assertNotRegex(
            browser_process_target,
            r'"//chrome/browser:browser_process"\s*,?',
        )
        for target in (browser_process_target, profile_target):
            with self.subTest(target=target):
                self.assertNotIn('"//chrome/browser",', target)
                self.assertNotIn("//chrome/browser:core", target)
                self.assertNotIn("//chrome/browser/profiles:misc", target)
                self.assertNotIn("//chrome/browser/profiles:profiles", target)

    def test_m6_uses_the_wasm_main_delegate_and_lifecycle_targets(self) -> None:
        chrome_wasm_target = self._wasm_chrome_target()
        app_main = source("chrome/app/chrome_main_wasm.cc")
        wasm_build = source("chrome/browser/wasm/BUILD.gn")
        delegate_header = source(
            "chrome/browser/wasm/wasm_chrome_main_delegate.h"
        )
        delegate_source = source(
            "chrome/browser/wasm/wasm_chrome_main_delegate.cc"
        )
        client_header = source(
            "chrome/browser/wasm/wasm_content_browser_client.h"
        )
        client_source = source(
            "chrome/browser/wasm/wasm_content_browser_client.cc"
        )
        main_parts_header = source(
            "chrome/browser/wasm/wasm_browser_main_parts.h"
        )
        main_parts_source = source(
            "chrome/browser/wasm/wasm_browser_main_parts.cc"
        )

        # The Wasm executable must use its direct ContentMainDelegate from a
        # platform-owned entry point, not compile the desktop main/delegate
        # behind a broad conditional.
        self.assertRegex(
            delegate_header,
            r"class\s+WasmChromeMainDelegate(?:\s+final)?\s*:\s*public\s+"
            r"content::ContentMainDelegate\b",
        )
        self.assertIn("WasmChromeMainDelegate chrome_main_delegate", app_main)
        self.assertIn('"app/chrome_main_wasm.cc",', chrome_wasm_target)
        self.assertNotIn('"app/chrome_main.cc",', chrome_wasm_target)
        self.assertEqual(1, app_main.count("base::CommandLine::Init("))
        self.assertIn(
            '"//chrome/browser/wasm:wasm_chrome_main_delegate",',
            chrome_wasm_target,
        )
        for desktop_source in (
            '"app/chrome_main_delegate.cc",',
            '"app/chrome_main_delegate.h",',
        ):
            with self.subTest(desktop_source=desktop_source):
                self.assertNotIn(desktop_source, chrome_wasm_target)

        # Keep the direct browser lifecycle split into small Wasm-owned GN
        # targets. This catches a regression where one of these files gets
        # added to the executable or a desktop aggregate instead of remaining
        # independently selectable.
        target_specs = {
            "wasm_chrome_main_delegate": (
                ("wasm_chrome_main_delegate.cc", "wasm_chrome_main_delegate.h"),
                (":wasm_content_browser_client",),
            ),
            "wasm_content_browser_client": (
                (
                    "wasm_content_browser_client.cc",
                    "wasm_content_browser_client.h",
                ),
                (":wasm_browser_main_parts",),
            ),
            "wasm_browser_main_parts": (
                ("wasm_browser_main_parts.cc", "wasm_browser_main_parts.h"),
                (":wasm_browser_process", ":wasm_profile"),
            ),
        }
        lifecycle_targets = []
        for target, (filenames, direct_deps) in target_specs.items():
            target_body = self._source_set_body(wasm_build, target)
            lifecycle_targets.append(target_body)
            for filename in filenames:
                with self.subTest(target=target, filename=filename):
                    self.assertIn(f'"{filename}"', target_body)
            for direct_dep in direct_deps:
                with self.subTest(target=target, direct_dep=direct_dep):
                    self.assertIn(f'"{direct_dep}"', target_body)

        # The return path itself must be direct: Content calls the Wasm
        # browser client, which returns only the Wasm main-parts object.
        self.assertRegex(
            client_header,
            r"class\s+WasmContentBrowserClient(?:\s+final)?\s*:\s*public\s+"
            r"content::ContentBrowserClient\b",
        )
        self.assertRegex(
            client_source,
            r"std::make_unique\s*<\s*WasmBrowserMainParts\s*>",
        )
        self.assertRegex(
            main_parts_header,
            r"class\s+WasmBrowserMainParts(?:\s+final)?\s*:\s*public\s+"
            r"content::BrowserMainParts\b",
        )
        self.assertNotIn("ChromeBrowserMainPartsWasm", main_parts_source)
        self.assertNotRegex(
            delegate_source,
            r"std::make_unique\s*<\s*ChromeContentBrowserClient\s*>",
        )

        # `//chrome/browser` is a desktop aggregate. The explicit browser
        # process/profile dependency remains valid inside Wasm targets, but
        # neither the executable nor lifecycle targets may regain the generic
        # browser, browser-client, or old Wasm-main-parts path.
        selected_text = "\n".join([chrome_wasm_target, *lifecycle_targets])
        self.assertNotRegex(
            selected_text, r'(?m)^\s*"//chrome/browser"\s*,?\s*$'
        )
        self.assertNotRegex(
            selected_text,
            r'"(?:[^"\n]*/)?chrome_content_browser_client"',
        )
        self.assertNotIn("ChromeBrowserMainPartsWasm", selected_text)

    def test_m6_chrome_common_boundary_is_source_selected(self) -> None:
        chrome_wasm_target = self._wasm_chrome_target()
        wasm_build = source("chrome/browser/wasm/BUILD.gn")
        common_build = source("chrome/common/BUILD.gn")
        profiles_build = source("chrome/browser/profiles/BUILD.gn")
        delegate_source = source(
            "chrome/browser/wasm/wasm_chrome_main_delegate.cc"
        )
        content_client_header = source(
            "chrome/browser/wasm/wasm_chrome_content_client.h"
        )
        content_client_source = source(
            "chrome/browser/wasm/wasm_chrome_content_client.cc"
        )

        delegate_target = self._source_set_body(
            wasm_build, "wasm_chrome_main_delegate"
        )
        content_client_target = self._source_set_body(
            wasm_build, "wasm_chrome_content_client"
        )
        result_codes_target = self._source_set_body(
            wasm_build, "wasm_chrome_result_codes"
        )
        selected_target_names = (
            "wasm_chrome_main_delegate",
            "wasm_chrome_content_client",
            "wasm_chrome_result_codes",
            "wasm_content_browser_client",
            "wasm_browser_main_parts",
            "wasm_browser_process",
            "wasm_profile",
            "wasm_chrome_paths",
        )
        selected_text = "\n".join(
            [
                chrome_wasm_target,
                *[
                    self._source_set_body(wasm_build, target)
                    for target in selected_target_names
                ],
            ]
        )

        for aggregate in (
            "//chrome/common",
            "//chrome/common:common",
            "//chrome/common:common_lib",
            "//chrome/common:constants",
            "//components/update_client",
            "//components/crash/core/app",
            "//third_party/crashpad/crashpad/util",
        ):
            with self.subTest(aggregate=aggregate):
                self.assertNotRegex(
                    selected_text,
                    rf'"{re.escape(aggregate)}"\s*,?',
                )

        self.assertIn(
            '":wasm_chrome_content_client",', delegate_target
        )
        self.assertIn('":wasm_chrome_result_codes",', delegate_target)
        self.assertIn(
            '"//chrome/browser/wasm:wasm_chrome_result_codes",',
            chrome_wasm_target,
        )
        self.assertIn('"../../common/chrome_result_codes.cc",', result_codes_target)
        self.assertIn(
            "class WasmChromeContentClient final : public content::ContentClient",
            content_client_header,
        )
        for resource_bridge in (
            "GetLocalizedString",
            "HasDataResource",
            "GetDataResourceBytes",
            "GetNativeImageNamed",
            "ResourceBundle::GetSharedInstance",
        ):
            with self.subTest(resource_bridge=resource_bridge):
                self.assertIn(
                    resource_bridge,
                    content_client_header + content_client_source,
                )
        self.assertIn("WasmChromeContentClient content_client", delegate_source)
        self.assertNotRegex(delegate_source, r"\bChromeContentClient\b")

        pref_names_target = self._source_set_body(common_build, "pref_names")
        profile_target = self._source_set_body(profiles_build, "profile")
        self.assertIn('public = [ "pref_names.h" ]', pref_names_target)
        self.assertRegex(
            profile_target,
            r"(?s)if\s*\(is_wasm\s*&&\s*enable_chromium_wasm_chrome\)\s*"
            r"\{.*?//chrome/common:pref_names.*?\}\s*else\s*"
            r"\{.*?//chrome/common:constants",
        )

    def test_m6_main_delegate_stays_inside_the_single_process_boundary(
        self,
    ) -> None:
        wasm_build = source("chrome/browser/wasm/BUILD.gn")
        delegate_target = self._source_set_body(
            wasm_build, "wasm_chrome_main_delegate"
        )
        delegate_source = source(
            "chrome/browser/wasm/wasm_chrome_main_delegate.cc"
        )

        # The browser-only Wasm delegate does not launch or embed standalone
        # Chrome GPU, renderer, or utility clients. Those desktop targets can
        # silently recreate process-oriented startup behavior even when
        # --single-process is present on the command line.
        for desktop_target in (
            "//chrome/gpu",
            "//chrome/renderer",
            "//chrome/utility",
        ):
            with self.subTest(desktop_target=desktop_target):
                self.assertNotRegex(
                    delegate_target, rf'"{re.escape(desktop_target)}"\s*,?'
                )

        for desktop_client in (
            "ChromeContentGpuClient",
            "ChromeContentRendererClient",
            "ChromeContentUtilityClient",
        ):
            with self.subTest(desktop_client=desktop_client):
                self.assertNotIn(desktop_client, delegate_source)

    def test_m6_admits_unowned_user_data_only_for_wasm_chrome(self) -> None:
        unowned_user_data_build = source("ui/base/unowned_user_data/BUILD.gn")
        platform_admission = unowned_user_data_build.split(
            'component("unowned_user_data")', 1
        )[0]

        # This support library remains unavailable to M3/content-only builds;
        # M6 is the sole Wasm consumer that needs BrowserProcess' host.
        self.assertRegex(
            platform_admission,
            r"\(\s*is_wasm\s*&&\s*enable_chromium_wasm_chrome\s*\)",
        )
        self.assertNotRegex(platform_admission, r"\|\|\s*is_wasm\s*(?:\)|\|\|)")


if __name__ == "__main__":
    unittest.main()
