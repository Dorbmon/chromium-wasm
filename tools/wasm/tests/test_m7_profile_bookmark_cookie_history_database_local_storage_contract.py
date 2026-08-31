#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Native contracts for the five-store M7 profile aggregate."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


_FLAG = (
    "enable_chromium_wasm_m7_profile_"
    "bookmark_cookie_history_database_local_storage_test"
)
_MACRO = (
    "CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_"
    "DATABASE_LOCAL_STORAGE_TEST"
)
_OLD_MACRO = (
    "CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST"
)
_DATABASE_MACRO = "CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST"
_CONFIG = (
    "wasm_profile_m7_bookmark_cookie_history_database_"
    "local_storage_smoke_config"
)
_BRIDGE_CONFIG = (
    "wasm_m7_profile_bookmark_cookie_history_database_local_storage_test"
)
_OUTPUT = (
    "chrome_wasm_m7_profile_bookmark_cookie_history_database_"
    "local_storage_test"
)
_OUT_DIR = (
    "wasm-chrome-m7-profile-bookmark-cookie-history-database-local-storage"
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


class M7ProfileFiveStoreNativeContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.wasm_args = source("build/config/wasm.gni")
        self.aggregate_gni = source(
            "chrome/browser/wasm/"
            "wasm_profile_bookmark_cookie_history_database_"
            "local_storage_smoke.gni"
        )
        self.chrome_build = source("chrome/BUILD.gn")
        self.wasm_build = source("chrome/browser/wasm/BUILD.gn")
        self.chrome_main = source("chrome/app/chrome_main_wasm.cc")
        self.main_parts = source(
            "chrome/browser/wasm/wasm_browser_main_parts.cc"
        )
        self.main_parts_header = source(
            "chrome/browser/wasm/wasm_browser_main_parts.h"
        )
        self.profile = source("chrome/browser/wasm/wasm_profile.cc")
        self.profile_header = source("chrome/browser/wasm/wasm_profile.h")
        self.database_header = source(
            "chrome/browser/wasm/wasm_profile_database_smoke.h"
        )
        self.database_source = source(
            "chrome/browser/wasm/wasm_profile_database_smoke.cc"
        )
        self.content_build = source("content/browser/BUILD.gn")
        self.content_public_build = source("content/public/browser/BUILD.gn")
        self.storage_build = source("components/services/storage/BUILD.gn")
        self.storage_mojom_build = source(
            "components/services/storage/public/mojom/BUILD.gn"
        )

    def test_fresh_identity_and_mutual_exclusion(self) -> None:
        args = _body_after_marker(self.wasm_args, "declare_args()")
        self.assertRegex(args, rf"{re.escape(_FLAG)}\s*=\s*false")
        self.assertIn(f"if ({_FLAG})", self.aggregate_gni)
        self.assertIn(f'"{_OUT_DIR}"', self.aggregate_gni)
        for excluded in (
            "enable_chromium_wasm_m7_profile_preferences_test",
            "enable_chromium_wasm_m7_profile_database_test",
            "enable_chromium_wasm_m7_default_partition_local_storage_test",
            "enable_chromium_wasm_m7_profile_cookie_local_storage_test",
            "enable_chromium_wasm_m7_profile_cookie_history_local_storage_test",
            "enable_chromium_wasm_m7_profile_bookmark_cookie_history_local_storage_test",
            "enable_chromium_wasm_m7_normal_profile_fence_failure_diagnostic",
        ):
            self.assertIn(f"!{excluded}", self.aggregate_gni)

        executable = _body_after_marker(
            self.chrome_build, 'executable("chrome_wasm")'
        )
        selected = _body_after_marker(executable, f"if ({_FLAG})")
        self.assertIn(f'"{_OUTPUT}"', selected)
        self.assertIn(f'"{_MACRO}=1"', selected)
        self.assertNotIn(_OLD_MACRO, selected)
        self.assertNotIn(_DATABASE_MACRO, selected)

    def test_gn_links_all_six_helpers_with_one_public_layout(self) -> None:
        executable = _body_after_marker(
            self.chrome_build, 'executable("chrome_wasm")'
        )
        deps_tail = executable[executable.index("deps = [") :]
        selected = _body_after_marker(deps_tail, f"if ({_FLAG})")
        for helper in (
            "wasm_profile_preferences_smoke",
            "wasm_profile_bookmark_smoke",
            "wasm_profile_cookie_smoke",
            "wasm_profile_history_smoke",
            "wasm_profile_local_storage_smoke",
            "wasm_profile_database_smoke",
        ):
            self.assertIn(helper, selected)

        profile_target = _body_after_marker(
            self.wasm_build, 'source_set("wasm_profile")'
        )
        profile_gate = _body_after_marker(profile_target, f"if ({_FLAG})")
        self.assertIn(f'":{_CONFIG}"', profile_gate)
        self.assertIn("public_configs", profile_gate)
        for helper in (
            ":wasm_profile_preferences_smoke",
            ":wasm_profile_bookmark_smoke",
            ":wasm_profile_cookie_smoke",
            ":wasm_profile_history_smoke",
            ":wasm_profile_local_storage_smoke",
            ":wasm_profile_database_smoke",
        ):
            self.assertIn(helper, profile_gate)

        database_condition = re.search(
            r"if \(enable_chromium_wasm_m7_profile_database_test\s*\|\|\s*"
            + re.escape(_FLAG)
            + r"\)\s*\{\s*source_set\(\"wasm_profile_database_smoke\"\)",
            self.wasm_build,
        )
        self.assertIsNotNone(database_condition)
        database_target = _body_after_marker(
            self.wasm_build, 'source_set("wasm_profile_database_smoke")'
        )
        aggregate_database_config = _body_after_marker(
            database_target, f"if ({_FLAG})"
        )
        self.assertIn("configs +=", aggregate_database_config)
        self.assertIn(f'":{_CONFIG}"', aggregate_database_config)

    def test_all_three_protocols_are_paired_before_mount(self) -> None:
        validation_start = self.chrome_main.index(
            "const chrome::WasmProfilePreferencesSmokeMode preferences_mode"
        )
        mount = self.chrome_main.index(
            "chrome::InitializeWasmProfilePreferencesStorage()"
        )
        content_main = self.chrome_main.index(
            "content::ContentMain(std::move(params))"
        )
        self.assertLess(validation_start, mount)
        self.assertLess(mount, content_main)
        validation = self.chrome_main[validation_start:mount]
        for phase in ("kWriteA", "kVerifyAWriteB", "kVerifyB"):
            self.assertIn(
                f"chrome::WasmProfileDatabaseSmokeMode::{phase}", validation
            )
        for required in (
            "database_smoke_enabled",
            "database_smoke_requested",
            "chrome::IsWasmProfileDatabaseSmokeEnabled()",
            "chrome::IsWasmProfilePreferencesBrowserSmokeEnabled()",
            "chrome::IsWasmProfilePreferencesBookmarkSmokeEnabled()",
            "chrome::IsWasmProfilePreferencesCookieSmokeEnabled()",
            "chrome::IsWasmProfilePreferencesHistorySmokeEnabled()",
            "chrome::IsWasmProfileRendererLocalStorageSmokeEnabled()",
        ):
            self.assertIn(required, validation)
        self.assertIn(
            "WasmProfileDatabaseSmokeFailureStage::kArguments", validation
        )

    def test_database_mode_getter_is_redacted_and_normal_only(self) -> None:
        self.assertIn("enum class WasmProfileDatabaseSmokeMode", self.database_header)
        self.assertIn(
            "WasmProfileDatabaseSmokeMode GetWasmProfileDatabaseSmokeMode()",
            self.database_header,
        )
        getter = _body_after_marker(
            self.database_source,
            "WasmProfileDatabaseSmokeMode GetWasmProfileDatabaseSmokeMode()",
        )
        for phase in ("kWriteA", "kVerifyAWriteB", "kVerifyB"):
            self.assertIn(f"SmokeMode::{phase}", getter)
            self.assertIn(f"WasmProfileDatabaseSmokeMode::{phase}", getter)
        self.assertIn("WasmProfileDatabaseSmokeMode::kNone", getter)
        for raw_name in ("token_a_", "token_b_", "expected_digest_", "profile_path"):
            self.assertNotIn(raw_name, getter)

    def test_database_task_phases_are_suppressed_only_for_this_aggregate(
        self,
    ) -> None:
        configuration = self.database_source[
            self.database_source.index("constexpr char kPhasePrefix") :
            self.database_source.index("enum class SmokeMode")
        ]
        aggregate_gate = f"#if defined(\\\n    {_MACRO})"
        self.assertIn(aggregate_gate, configuration)
        self.assertIn(
            "constexpr bool kEmitDatabaseTaskPhases = false;", configuration
        )
        self.assertIn(
            "constexpr bool kEmitDatabaseTaskPhases = true;", configuration
        )
        self.assertNotIn(_OLD_MACRO, configuration)
        self.assertNotIn(_DATABASE_MACRO, configuration)
        emitter = _body_after_marker(
            self.database_source,
            "void EmitDatabaseTaskPhase(DatabaseTaskPhase phase)",
        )
        self.assertIn("if (!kEmitDatabaseTaskPhases)", emitter)
        self.assertLess(emitter.index("return;"), emitter.index("std::fprintf"))
        self.assertNotIn(_OLD_MACRO, emitter)
        self.assertNotIn(_DATABASE_MACRO, emitter)

    def test_native_sequence_is_local_storage_then_database_then_shutdown(self) -> None:
        local_completion = _body_after_marker(
            self.main_parts,
            "OnWasmProfileRendererLocalStorageSmokeComplete(bool success)",
        )
        self.assertIn("local_storage_succeeded", local_completion)
        self.assertIn(
            "StartWasmProfileDatabaseSmokeOrShutdown()", local_completion
        )
        self.assertLess(
            local_completion.index("StartWasmProfileDatabaseSmokeOrShutdown()"),
            local_completion.rindex("RequestShutdown()"),
        )

        database_start = _body_after_marker(
            self.main_parts, "StartWasmProfileDatabaseSmokeOrShutdown()"
        )
        self.assertIn("TryAcquireWasmProfileStorageProfileIO()", database_start)
        self.assertIn("profile_->StartDatabaseSmoke", database_start)
        self.assertIn("OnWasmProfileDatabaseSmokeComplete", database_start)

        database_completion = _body_after_marker(
            self.main_parts,
            "OnWasmProfileDatabaseSmokeComplete(bool success)",
        )
        self.assertIn("profile_->DidDatabaseSmokeSucceed()", database_completion)
        self.assertIn("RequestShutdown()", database_completion)
        self.assertIn("MaybeStartShutdown()", database_completion)

        standalone = self.main_parts.index(
            "The M7 three-fresh-module SQLite/LevelDB acceptance stops"
        )
        standalone_prefix = self.main_parts[max(0, standalone - 180) : standalone]
        self.assertIn(f"#if defined({_DATABASE_MACRO})", standalone_prefix)
        self.assertNotIn(_MACRO, standalone_prefix)

    def test_database_is_profile_owned_through_cancel_and_quarantine(self) -> None:
        for declaration in (
            "StartDatabaseSmoke",
            "HasActiveDatabaseSmoke",
            "DidDatabaseSmokeSucceed",
            "CancelDatabaseSmokeForShutdown",
            "QuarantineDatabaseSmokeForFailureShutdown",
            "database_lifetime_participant_",
        ):
            self.assertIn(declaration, self.profile_header)
        for call in (
            "CancelDatabaseSmokeForShutdown()",
            "QuarantineDatabaseSmokeForFailureShutdown()",
            "NotifyWasmProfileDatabaseSmokeFenceResult(false)",
            "NotifyWasmProfileDatabaseSmokeFenceResult(success)",
            "NotifyWasmProfileDatabaseSmokeStorageLifecycle(",
        ):
            self.assertIn(call, self.main_parts)

        self.assertRegex(
            self.profile,
            r"bool WasmProfile::ShouldUseInMemoryDefaultStoragePartition\(\)\s*"
            r"\{[^}]*return true;",
        )

    def test_one_drain_fans_out_preferences_database_local_storage(self) -> None:
        drain = _body_after_marker(
            self.chrome_main,
            "if (chrome::NeedsWasmProfileStorageBackendDrain())",
        )
        self.assertEqual(
            drain.count("DrainAndReleaseWasmProfileStorageBackend()"), 2
        )
        # The second call is source-selected only by the standalone outstanding
        # I/O refusal diagnostic; this aggregate never defines that macro.
        self.assertIn(
            "CHROME_WASM_M7_PROFILE_DATABASE_OUTSTANDING_IO_REFUSAL_TEST",
            drain,
        )
        preferences = drain.index(
            "NotifyWasmProfilePreferencesSmokeBackendDrain("
        )
        database = drain.index("NotifyWasmProfileDatabaseSmokeBackendDrain(")
        local_storage = drain.index(
            "NotifyWasmProfileLocalStorageSmokeBackendDrain("
        )
        self.assertLess(preferences, database)
        self.assertLess(database, local_storage)

    def test_content_and_storage_bridge_share_the_new_macro(self) -> None:
        for build_text in (
            self.content_public_build,
            self.content_build,
            self.storage_build,
            self.storage_mojom_build,
        ):
            self.assertIn(_FLAG, build_text)
        self.assertIn(f'config("{_BRIDGE_CONFIG}")', self.content_public_build)
        self.assertIn(f'config("{_BRIDGE_CONFIG}")', self.storage_build)
        self.assertIn("public_configs", self.content_public_build)
        self.assertIn("public_configs", self.storage_build)

        for path in (
            "chrome/browser/wasm/wasm_content_browser_client.cc",
            "chrome/browser/wasm/wasm_profile_local_storage_smoke.cc",
            "chrome/browser/wasm/wasm_profile_storage.cc",
            "chrome/browser/wasm/wasm_profile_storage.h",
            "content/public/browser/wasm_dom_storage_test_support.h",
            "content/browser/dom_storage/dom_storage_context_wrapper.cc",
            "content/browser/dom_storage/dom_storage_context_wrapper.h",
            "components/services/storage/dom_storage/local_storage_impl.cc",
            "components/services/storage/dom_storage/local_storage_impl.h",
            "components/services/storage/storage_service_impl.cc",
            "components/services/storage/storage_service_impl.h",
        ):
            with self.subTest(path=path):
                self.assertIn(_MACRO, source(path))


if __name__ == "__main__":
    unittest.main()
