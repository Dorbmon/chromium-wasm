#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Static contracts for Cookie + History + renderer LocalStorage persistence."""

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


_FLAG = "enable_chromium_wasm_m7_profile_cookie_history_local_storage_test"
_MACRO = "CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST"
_PREFS_MACRO = "CHROME_WASM_M7_PREFERENCES_SMOKE_TEST"
_LOCAL_STORAGE_MACRO = "CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST"
_COOKIE_LOCAL_STORAGE_MACRO = (
    "CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST"
)


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


class M7ProfileCookieHistoryLocalStorageContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.wasm_args = source("build/config/wasm.gni")
        self.aggregate_gni = source(
            "chrome/browser/wasm/"
            "wasm_profile_cookie_history_local_storage_smoke.gni"
        )
        self.chrome_build = source("chrome/BUILD.gn")
        self.wasm_build = source("chrome/browser/wasm/BUILD.gn")
        self.chrome_main = source("chrome/app/chrome_main_wasm.cc")
        self.main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        self.profile = source("chrome/browser/wasm/wasm_profile.cc")
        self.profile_header = source("chrome/browser/wasm/wasm_profile.h")
        self.profile_storage = source("chrome/browser/wasm/wasm_profile_storage.cc")
        self.content_client = source(
            "chrome/browser/wasm/wasm_content_browser_client.cc"
        )
        self.history_smoke = source(
            "chrome/browser/wasm/wasm_profile_history_smoke.cc"
        )
        self.dom_storage = source(
            "content/browser/dom_storage/dom_storage_context_wrapper.cc"
        )
        self.dom_storage_header = source(
            "content/browser/dom_storage/dom_storage_context_wrapper.h"
        )
        self.dom_storage_test_support = source(
            "content/public/browser/wasm_dom_storage_test_support.h"
        )
        self.local_storage_impl = source(
            "components/services/storage/dom_storage/local_storage_impl.cc"
        )
        self.local_storage_impl_header = source(
            "components/services/storage/dom_storage/local_storage_impl.h"
        )
        self.storage_service = source(
            "components/services/storage/storage_service_impl.cc"
        )
        self.storage_service_header = source(
            "components/services/storage/storage_service_impl.h"
        )
        self.content_build = source("content/browser/BUILD.gn")
        self.content_public_build = source("content/public/browser/BUILD.gn")
        self.storage_build = source("components/services/storage/BUILD.gn")
        self.storage_mojom_build = source(
            "components/services/storage/public/mojom/BUILD.gn"
        )

    def test_fresh_artifact_selects_exactly_the_three_profile_stores(self) -> None:
        args = _body_after_marker(self.wasm_args, "declare_args()")
        self.assertIn(f"{_FLAG} = false", args)
        self.assertIn(f"assert(!{_FLAG} ||", self.wasm_args)

        aggregate_gate = _body_after_marker(self.aggregate_gni, f"if ({_FLAG})")
        for expected in (
            "!enable_chromium_wasm_m7_profile_preferences_test",
            "!enable_chromium_wasm_m7_profile_database_test",
            "!enable_chromium_wasm_m7_default_partition_local_storage_test",
            "!enable_chromium_wasm_m7_profile_cookie_local_storage_test",
            "!enable_chromium_wasm_m7_normal_profile_fence_failure_diagnostic",
            '"wasm-chrome-m7-profile-cookie-history-local-storage"',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, aggregate_gate)

        executable = _body_after_marker(
            self.chrome_build, 'executable("chrome_wasm")'
        )
        selected = _body_after_marker(executable, f"if ({_FLAG})")
        self.assertIn(
            '"chrome_wasm_m7_profile_cookie_history_local_storage_test"',
            selected,
        )
        self.assertIn(f'"{_MACRO}=1"', selected)
        self.assertNotIn(_PREFS_MACRO, selected)
        self.assertNotIn(_LOCAL_STORAGE_MACRO, selected)
        self.assertNotIn(_COOKIE_LOCAL_STORAGE_MACRO, selected)

        deps_start = executable.index("deps = [")
        deps_gate = executable[
            executable.index(f"if ({_FLAG})", deps_start) :
        ]
        deps_gate = _body_after_marker(deps_gate, f"if ({_FLAG})")
        for helper in (
            "wasm_profile_preferences_smoke",
            "wasm_profile_cookie_smoke",
            "wasm_profile_history_smoke",
            "wasm_profile_local_storage_smoke",
        ):
            with self.subTest(helper=helper):
                self.assertIn(helper, deps_gate)
        self.assertNotIn("bookmark", deps_gate.lower())

        profile_target = _body_after_marker(
            self.wasm_build, 'source_set("wasm_profile")'
        )
        profile_gate = _body_after_marker(profile_target, f"if ({_FLAG})")
        self.assertIn("public_configs =", profile_gate)
        self.assertIn(
            '":wasm_profile_m7_cookie_history_local_storage_smoke_config"',
            profile_gate,
        )
        for helper in (
            '":wasm_profile_preferences_smoke"',
            '":wasm_profile_cookie_smoke"',
            '":wasm_profile_history_smoke"',
            '":wasm_profile_local_storage_smoke"',
        ):
            with self.subTest(profile_helper=helper):
                self.assertIn(helper, profile_gate)
        self.assertNotIn("bookmark", profile_gate.lower())

    def test_phase_pair_and_owner_set_are_validated_before_mount(self) -> None:
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
            "WasmProfileLocalStorageSmokeInput::Mode::",
            "kRendererWrite",
            "kRendererVerify",
            "IsWasmProfilePreferencesBrowserSmokeEnabled()",
            "IsWasmProfilePreferencesCookieSmokeEnabled()",
            "!chrome::IsWasmProfilePreferencesBookmarkSmokeEnabled()",
            "IsWasmProfileRendererLocalStorageSmokeEnabled()",
            "if (!aggregate_smoke_enabled)",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, validation)
        self.assertIn(
            f"#if defined({_MACRO})\n"
            "          chrome::IsWasmProfilePreferencesHistorySmokeEnabled() &&\n"
            "#else\n"
            "          !chrome::IsWasmProfilePreferencesHistorySmokeEnabled() &&\n"
            "#endif",
            validation,
        )

    def test_runtime_orders_browser_cookie_history_then_local_storage(self) -> None:
        startup = _body_after_marker(
            self.main_parts, "int WasmBrowserMainParts::PreMainMessageLoopRun()"
        )
        browser_result = startup.index("RunWasmBrowserSmoke(profile_.get())")
        cookie_start = startup.index(
            "StartWasmProfileCookieSmokeOrHistoryOrShutdown();"
        )
        self.assertLess(browser_result, cookie_start)
        aggregate_guard_start = startup.rfind("#if defined(", 0, cookie_start)
        self.assertGreaterEqual(aggregate_guard_start, 0)
        aggregate_guard = startup[aggregate_guard_start:cookie_start]
        self.assertIn(
            "CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST",
            aggregate_guard,
        )
        self.assertIn(_MACRO, aggregate_guard)

        cookie_complete = _body_after_marker(
            self.main_parts,
            "void WasmBrowserMainParts::OnWasmProfileCookieSmokeComplete(",
        )
        cookie_receipt = cookie_complete.index("DidCookieSmokeSucceed()")
        history_start = cookie_complete.index(
            "StartWasmProfileHistorySmokeOrShutdown();"
        )
        self.assertLess(cookie_receipt, history_start)

        history_start_body = _body_after_marker(
            self.main_parts,
            "void WasmBrowserMainParts::StartWasmProfileHistorySmokeOrShutdown()",
        )
        acquire_io = history_start_body.index(
            "TryAcquireWasmProfileStorageProfileIO()"
        )
        start_owner = history_start_body.index("profile_->StartHistorySmoke(")
        self.assertLess(acquire_io, start_owner)

        history_complete = _body_after_marker(
            self.main_parts,
            "void WasmBrowserMainParts::OnWasmProfileHistorySmokeComplete(",
        )
        history_receipt = history_complete.index("DidHistorySmokeSucceed()")
        local_storage_start = history_complete.index(
            "StartWasmProfileRendererLocalStorageSmokeOrShutdown();"
        )
        self.assertLess(history_receipt, local_storage_start)

        history_close = _body_after_marker(self.history_smoke, "void Close()")
        install_close_receipt = history_close.index("SetOnBackendDestroyTask(")
        shutdown = history_close.index("history_service_->Shutdown()")
        release_owner = history_close.index("history_service_.reset()")
        self.assertLess(install_close_receipt, shutdown)
        self.assertLess(shutdown, release_owner)
        backend_destroyed = _body_after_marker(
            self.history_smoke, "void OnBackendDestroyed()"
        )
        self.assertIn("CompleteAfterBackendClose", backend_destroyed)
        history_completion = _body_after_marker(
            self.history_smoke,
            "void CompleteAfterBackendClose(bool operation_succeeded)",
        )
        retire_io = history_completion.index("profile_io_hold_->Complete(")
        notify_browser = history_completion.index(
            "std::move(completion_).Run(succeeded_)"
        )
        self.assertLess(retire_io, notify_browser)

        local_storage_complete = _body_after_marker(
            self.main_parts,
            "void WasmBrowserMainParts::\n"
            "    OnWasmProfileRendererLocalStorageSmokeComplete(bool success)",
        )
        self.assertIn("DidLocalStorageSmokeSucceed()", local_storage_complete)
        self.assertIn("RequestShutdown();", local_storage_complete)

    def test_shutdown_gates_and_quarantines_all_three_participants(self) -> None:
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
            history = body.index("HasActiveHistorySmoke()")
            local_storage = body.index("HasActiveLocalStorageSmoke()")
            self.assertLess(cookie, history)
            self.assertLess(history, local_storage)
        for body in (foundation, destructor):
            self.assertIn("QuarantineCookieSmokeForFailureShutdown()", body)
            self.assertIn("QuarantineHistorySmokeForFailureShutdown()", body)
            self.assertIn("QuarantineLocalStorageSmokeForFailureShutdown()", body)

        for owner in (
            "cookie_lifetime_participant_",
            "history_lifetime_participant_",
            "local_storage_lifetime_participant_",
        ):
            with self.subTest(owner=owner):
                self.assertIn(owner, self.profile_header)

    def test_one_backend_drain_fans_out_one_result_to_both_protocols(self) -> None:
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

    def test_only_cookie_history_and_local_storage_gain_persistent_paths(self) -> None:
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
            with self.subTest(cookie_path=expected):
                self.assertIn(expected, network_params)
        self.assertIn(f"defined({_MACRO})", self.content_client)

        history_owner = _body_after_marker(
            self.profile, "bool WasmProfile::StartHistorySmoke("
        )
        self.assertIn("profile_path_", history_owner)
        self.assertIn("WasmProfileHistoryLifetimeParticipant", history_owner)
        self.assertIn(
            "history::HistoryDatabaseParamsForPath(\n"
            "            profile_path_, version_info::Channel::UNKNOWN)",
            self.history_smoke,
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

    def test_macro_and_bridge_source_selection_are_closed_over_consumers(self) -> None:
        for build_file in (
            self.chrome_build,
            self.wasm_build,
            self.content_build,
            self.content_public_build,
            self.storage_build,
        ):
            with self.subTest(build_file=build_file[:40]):
                self.assertIn(_FLAG, build_file)
                self.assertIn(_MACRO, build_file)
        self.assertIn(_FLAG, self.storage_mojom_build)

        for implementation in (
            self.chrome_main,
            self.main_parts,
            self.profile,
            self.profile_header,
            self.content_client,
            self.dom_storage,
            self.dom_storage_header,
            self.dom_storage_test_support,
            self.local_storage_impl,
            self.local_storage_impl_header,
            self.storage_service,
            self.storage_service_header,
        ):
            with self.subTest(implementation=implementation[:40]):
                self.assertIn(_MACRO, implementation)

        profile_config = _body_after_marker(
            self.wasm_build,
            'config("wasm_profile_m7_cookie_history_local_storage_smoke_config")',
        )
        self.assertIn(f'"{_MACRO}=1"', profile_config)

        content_target = _body_after_marker(
            self.content_build, 'source_set("browser")'
        )
        for expected in (
            '"dom_storage/wasm_dom_storage_test_support.cc",',
            '"//components/services/storage/public/mojom:wasm_local_storage_test_api",',
        ):
            with self.subTest(content=expected):
                self.assertIn(expected, content_target)
        content_gate = _body_after_marker(content_target, f"if ({_FLAG})")
        self.assertIn("defines +=", content_gate)
        self.assertIn(f'"{_MACRO}=1"', content_gate)

        storage_target = _body_after_marker(
            self.storage_build, 'source_set("storage")'
        )
        self.assertIn("public_configs =", storage_target)
        self.assertIn(
            '":wasm_m7_profile_cookie_history_local_storage_test"',
            storage_target,
        )
        self.assertIn(
            '"//components/services/storage/public/mojom:wasm_local_storage_test_api",',
            storage_target,
        )


if __name__ == "__main__":
    unittest.main()
