#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Static contracts for the aggregate Cookie + renderer LocalStorage gate."""

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


_FLAG = "enable_chromium_wasm_m7_profile_cookie_local_storage_test"
_MACRO = "CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST"
_HISTORY_AGGREGATE_MACRO = (
    "CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST"
)
_BOOKMARK_HISTORY_AGGREGATE_MACRO = (
    "CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST"
)
_BOOKMARK_HISTORY_DATABASE_AGGREGATE_MACRO = (
    "CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST"
)
_PREFS_MACRO = "CHROME_WASM_M7_PREFERENCES_SMOKE_TEST"
_LOCAL_STORAGE_MACRO = "CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST"


def _body_after_marker(text: str, marker: str) -> str:
    start = text.index(marker)
    opening = text.index("{", start)
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[opening + 1 : index]
    raise AssertionError(f"missing closing brace for {marker}")


class M7ProfileCookieLocalStorageContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.wasm_args = source("build/config/wasm.gni")
        self.aggregate_gni = source(
            "chrome/browser/wasm/wasm_profile_cookie_local_storage_smoke.gni"
        )
        self.chrome_build = source("chrome/BUILD.gn")
        self.wasm_build = source("chrome/browser/wasm/BUILD.gn")
        self.chrome_main = source("chrome/app/chrome_main_wasm.cc")
        self.main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        self.profile = source("chrome/browser/wasm/wasm_profile.cc")
        self.profile_header = source("chrome/browser/wasm/wasm_profile.h")
        self.profile_storage = source(
            "chrome/browser/wasm/wasm_profile_storage.cc"
        )
        self.content_client = source(
            "chrome/browser/wasm/wasm_content_browser_client.cc"
        )
        self.dom_storage = source(
            "content/browser/dom_storage/dom_storage_context_wrapper.cc"
        )
        self.content_build = source("content/browser/BUILD.gn")
        self.content_public_build = source("content/public/browser/BUILD.gn")
        self.storage_build = source("components/services/storage/BUILD.gn")
        self.storage_mojom_build = source(
            "components/services/storage/public/mojom/BUILD.gn"
        )

    def test_fresh_artifact_has_one_distinct_capability(self) -> None:
        args = _body_after_marker(self.wasm_args, "declare_args()")
        self.assertIn(f"{_FLAG} = false", args)
        self.assertIn(f"assert(!{_FLAG} ||", self.wasm_args)

        aggregate_gate = _body_after_marker(
            self.aggregate_gni, f"if ({_FLAG})"
        )
        for expected in (
            "!enable_chromium_wasm_m7_profile_preferences_test",
            "!enable_chromium_wasm_m7_profile_database_test",
            "!enable_chromium_wasm_m7_default_partition_local_storage_test",
            "!enable_chromium_wasm_m7_normal_profile_fence_failure_diagnostic",
            '"wasm-chrome-m7-profile-cookie-local-storage"',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, aggregate_gate)

        executable = _body_after_marker(
            self.chrome_build, 'executable("chrome_wasm")'
        )
        selected = _body_after_marker(executable, f"if ({_FLAG})")
        self.assertIn(
            'output_name = "chrome_wasm_m7_profile_cookie_local_storage_test"',
            selected,
        )
        self.assertIn(f'defines = [ "{_MACRO}=1" ]', selected)
        self.assertNotIn(_PREFS_MACRO, selected)
        self.assertNotIn(_LOCAL_STORAGE_MACRO, selected)
        self.assertNotIn(_BOOKMARK_HISTORY_AGGREGATE_MACRO, selected)
        self.assertNotIn(_BOOKMARK_HISTORY_DATABASE_AGGREGATE_MACRO, selected)
        for helper in (
            "wasm_profile_preferences_smoke",
            "wasm_profile_cookie_smoke",
            "wasm_profile_local_storage_smoke",
        ):
            with self.subTest(helper=helper):
                self.assertIn(helper, executable)

        profile_target = _body_after_marker(
            self.wasm_build, 'source_set("wasm_profile")'
        )
        profile_gate = _body_after_marker(profile_target, f"if ({_FLAG})")
        self.assertIn(
            'public_configs = [ ":wasm_profile_m7_cookie_local_storage_smoke_config" ]',
            profile_gate,
        )
        self.assertIn('":wasm_profile_cookie_smoke",', profile_gate)
        self.assertIn('":wasm_profile_local_storage_smoke",', profile_gate)
        self.assertIn('":wasm_profile_preferences_smoke",', profile_gate)
        self.assertNotIn("bookmark", profile_gate.lower())
        self.assertNotIn("history", profile_gate.lower())

    def test_phase_pair_is_validated_before_mount(self) -> None:
        phase_validation = self.chrome_main.index("const bool phases_match =")
        mount = self.chrome_main.index(
            "chrome::InitializeWasmProfilePreferencesStorage()"
        )
        content_main = self.chrome_main.index(
            "content::ContentMain(std::move(params))"
        )
        self.assertLess(phase_validation, mount)
        self.assertLess(mount, content_main)

        validation = self.chrome_main[phase_validation:mount]
        for expected in (
            "WasmProfilePreferencesSmokeMode::kWrite",
            "WasmProfilePreferencesSmokeMode::kVerifyAndWrite",
            "WasmProfileLocalStorageSmokeInput::Mode::\n"
            "                   kRendererWrite",
            "WasmProfileLocalStorageSmokeInput::Mode::\n"
            "                   kRendererVerify",
            "IsWasmProfilePreferencesBrowserSmokeEnabled()",
            "IsWasmProfilePreferencesCookieSmokeEnabled()",
            "!chrome::IsWasmProfilePreferencesBookmarkSmokeEnabled()",
            "!chrome::IsWasmProfilePreferencesHistorySmokeEnabled()",
            "IsWasmProfileRendererLocalStorageSmokeEnabled()",
            "if (!aggregate_smoke_enabled)",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, validation)
        self.assertIn(
            f"#if defined({_HISTORY_AGGREGATE_MACRO}) || \\\n"
            f"    defined({_BOOKMARK_HISTORY_AGGREGATE_MACRO})\n"
            "          chrome::IsWasmProfilePreferencesHistorySmokeEnabled() &&\n"
            "#else\n"
            "          !chrome::IsWasmProfilePreferencesHistorySmokeEnabled() &&\n"
            "#endif",
            validation,
        )

    def test_profile_owners_run_browser_cookie_then_renderer_local_storage(self) -> None:
        startup = _body_after_marker(
            self.main_parts, "int WasmBrowserMainParts::PreMainMessageLoopRun()"
        )
        browser_result = startup.index("RunWasmBrowserSmoke(profile_.get())")
        cookie_start = startup.index(
            "StartWasmProfileCookieSmokeOrHistoryOrShutdown();"
        )
        self.assertLess(browser_result, cookie_start)
        self.assertIn(
            f"#if defined({_BOOKMARK_HISTORY_AGGREGATE_MACRO}) || \\\n"
            f"    defined({_BOOKMARK_HISTORY_DATABASE_AGGREGATE_MACRO})\n"
            "    StartWasmProfileBookmarkSmokeOrCookieOrHistoryOrShutdown();\n"
            f"#elif defined({_MACRO}) || \\\n"
            f"    defined({_HISTORY_AGGREGATE_MACRO})\n"
            "    StartWasmProfileCookieSmokeOrHistoryOrShutdown();\n"
            "#else\n"
            "    StartWasmProfileBookmarkSmokeOrCookieOrHistoryOrShutdown();\n"
            "#endif",
            startup,
        )

        cookie_complete = _body_after_marker(
            self.main_parts,
            "void WasmBrowserMainParts::OnWasmProfileCookieSmokeComplete(",
        )
        cookie_success = cookie_complete.index("DidCookieSmokeSucceed()")
        local_storage_start = cookie_complete.index(
            "StartWasmProfileRendererLocalStorageSmokeOrShutdown();"
        )
        self.assertLess(cookie_success, local_storage_start)

        local_storage_start_body = _body_after_marker(
            self.main_parts,
            "void WasmBrowserMainParts::\n"
            "    StartWasmProfileRendererLocalStorageSmokeOrShutdown()",
        )
        take_input = local_storage_start_body.index(
            "TakeWasmProfileLocalStorageSmokeInput()"
        )
        acquire_io = local_storage_start_body.index(
            "TryAcquireWasmProfileStorageProfileIO()"
        )
        start_owner = local_storage_start_body.index(
            "profile_->StartLocalStorageSmoke("
        )
        self.assertLess(take_input, acquire_io)
        self.assertLess(acquire_io, start_owner)

        local_storage_complete = _body_after_marker(
            self.main_parts,
            "void WasmBrowserMainParts::\n"
            "    OnWasmProfileRendererLocalStorageSmokeComplete(bool success)",
        )
        self.assertIn("DidLocalStorageSmokeSucceed()", local_storage_complete)
        self.assertIn("RequestShutdown();", local_storage_complete)

    def test_shutdown_gates_and_quarantines_both_profile_participants(self) -> None:
        maybe_shutdown = _body_after_marker(
            self.main_parts, "void WasmBrowserMainParts::MaybeStartShutdown()"
        )
        finish_shutdown = _body_after_marker(
            self.main_parts, "void WasmBrowserMainParts::FinishShutdown()"
        )
        foundation = _body_after_marker(
            self.main_parts, "void WasmBrowserMainParts::ShutdownFoundation()"
        )
        destructor = _body_after_marker(self.profile, "WasmProfile::~WasmProfile()")

        for body in (maybe_shutdown, finish_shutdown):
            cookie = body.index("HasActiveCookieSmoke()")
            local_storage = body.index("HasActiveLocalStorageSmoke()")
            self.assertLess(cookie, local_storage)
        for body in (foundation, destructor):
            self.assertIn("QuarantineCookieSmokeForFailureShutdown()", body)
            self.assertIn("QuarantineLocalStorageSmokeForFailureShutdown()", body)

        for owner in (
            "cookie_lifetime_participant_",
            "local_storage_lifetime_participant_",
        ):
            with self.subTest(owner=owner):
                self.assertIn(owner, self.profile_header)

    def test_one_backend_drain_fans_out_the_same_result(self) -> None:
        drain_body = _body_after_marker(
            self.chrome_main,
            "if (chrome::NeedsWasmProfileStorageBackendDrain())",
        )
        self.assertEqual(
            drain_body.count(
                "WasmProfileStorageDrainResult drain_result =\n"
                "        chrome::DrainAndReleaseWasmProfileStorageBackend();"
            ),
            1,
        )
        for notification in (
            "NotifyWasmProfilePreferencesSmokeBackendDrain",
            "NotifyWasmProfileLocalStorageSmokeBackendDrain",
        ):
            with self.subTest(notification=notification):
                self.assertIn(
                    f"chrome::{notification}(\n        drain_result.Succeeded());",
                    drain_body,
                )

        missing_drain = _body_after_marker(
            self.chrome_main, "} else if (aggregate_smoke_enabled)"
        )
        self.assertIn(
            "NotifyWasmProfilePreferencesSmokeBackendDrain(false)", missing_drain
        )
        self.assertIn(
            "NotifyWasmProfileLocalStorageSmokeBackendDrain(false)", missing_drain
        )

    def test_only_cookie_and_local_storage_gain_narrow_persistent_paths(self) -> None:
        default_partition = _body_after_marker(
            self.profile,
            "bool WasmProfile::ShouldUseInMemoryDefaultStoragePartition()",
        )
        self.assertIn("return true;", default_partition)
        self.assertNotIn(_MACRO, default_partition)

        network_params = _body_after_marker(
            self.content_client,
            "void WasmContentBrowserClient::ConfigureNetworkContextParams(",
        )
        for expected in (
            "IsWasmProfilePreferencesCookieSmokeEnabled()",
            "profile_path.AppendASCII(kWasmNetworkDataDirectory)",
            'base::FilePath(FILE_PATH_LITERAL("Cookies"))',
            "http_cache_enabled = false",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, network_params)
        self.assertIn(
            f"defined({_PREFS_MACRO}) || \\\n    defined({_MACRO})",
            self.content_client,
        )

        local_storage_path = _body_after_marker(
            self.dom_storage, "std::optional<base::FilePath> GetLocalStoragePath("
        )
        self.assertIn("partition->GetConfig().is_default()", local_storage_path)
        self.assertIn("browser_context->GetPath()", local_storage_path)
        self.assertIn(f"defined({_MACRO})", self.dom_storage)

        self.assertIn(
            "ProfileStorageMount::kDefaultProfile",
            _body_after_marker(
                self.profile_storage,
                "bool InitializeWasmProfilePreferencesStorage()",
            ),
        )

    def test_content_and_storage_close_bridges_share_the_aggregate_macro(self) -> None:
        for build_file in (
            self.content_build,
            self.content_public_build,
            self.storage_build,
        ):
            with self.subTest(build_file=build_file[:40]):
                self.assertIn(_FLAG, build_file)
                self.assertIn(_MACRO, build_file)
        self.assertIn(_FLAG, self.storage_mojom_build)

        content_target = _body_after_marker(
            self.content_build, 'source_set("browser")'
        )
        for expected in (
            '"dom_storage/wasm_dom_storage_test_support.cc",',
            '"//components/services/storage/public/mojom:wasm_local_storage_test_api",',
            f'defines += [ "{_MACRO}=1" ]',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, content_target)

        storage_target = _body_after_marker(
            self.storage_build, 'source_set("storage")'
        )
        self.assertIn(
            'public_configs = [ ":wasm_m7_profile_cookie_local_storage_test" ]',
            storage_target,
        )
        self.assertIn(
            '"//components/services/storage/public/mojom:wasm_local_storage_test_api",',
            storage_target,
        )


if __name__ == "__main__":
    unittest.main()
