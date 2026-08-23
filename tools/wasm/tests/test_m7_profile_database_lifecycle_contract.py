#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Target-isolation and lifecycle contracts for M7 database acceptance."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def _body_after_signature(text: str, signature: str) -> str:
    start = text.index(signature)
    opening = text.index("{", start)
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[opening + 1 : index]
    raise AssertionError(f"missing closing brace for {signature}")


def _bracket_body_after(text: str, marker: str) -> str:
    start = text.index(marker)
    opening = text.index("[", start)
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "[":
            depth += 1
        elif text[index] == "]":
            depth -= 1
            if depth == 0:
                return text[opening + 1 : index]
    raise AssertionError(f"missing closing bracket for {marker}")


def _is_in_database_macro_block(text: str, position: int) -> bool:
    """Returns whether |position| is nested below the dedicated DB macro.

    The primary sources intentionally contain nested independent feature
    conditionals. A non-greedy regex stops at the first inner #endif and can
    therefore mistake a correctly guarded database call for production code.
    """

    macro = "CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST"
    active_stack: list[bool] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        if offset <= position < offset + len(line):
            return any(active_stack)

        directive = line.lstrip()
        if re.match(r"#\s*(if|ifdef|ifndef)\b", directive):
            active_stack.append(macro in directive)
        elif re.match(r"#\s*elif\b", directive):
            if active_stack:
                active_stack[-1] = macro in directive
        elif re.match(r"#\s*else\b", directive):
            if active_stack:
                active_stack[-1] = False
        elif re.match(r"#\s*endif\b", directive):
            if active_stack:
                active_stack.pop()
        offset += len(line)
    return False


def _assert_only_in_database_blocks(
    testcase: unittest.TestCase, text: str, token: str
) -> None:
    positions = [match.start() for match in re.finditer(re.escape(token), text)]
    testcase.assertTrue(positions, f"missing {token}")
    for position in positions:
        with testcase.subTest(token=token, position=position):
            testcase.assertTrue(_is_in_database_macro_block(text, position),
                                 f"{token} is not target-config-gated")


class M7ProfileDatabaseLifecycleContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.gni = source("chrome/browser/wasm/wasm_profile_database_smoke.gni")
        self.chrome_build = source("chrome/BUILD.gn")
        self.wasm_build = source("chrome/browser/wasm/BUILD.gn")
        self.chrome_main = source("chrome/app/chrome_main_wasm.cc")
        self.main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")

    def test_dedicated_gn_configuration_is_the_only_database_capability_grant(self) -> None:
        for token in (
            "enable_chromium_wasm_m7_profile_database_test = false",
            "is_wasm && enable_chromium_wasm_chrome",
            '"wasm-chrome-m7-profile-database"',
            "out/wasm-chrome-m7-profile-database",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.gni)

        for build in (self.chrome_build, self.wasm_build):
            self.assertIn(
                'import("//chrome/browser/wasm/wasm_profile_database_smoke.gni")',
                build,
            )
            self.assertIn(
                "!enable_chromium_wasm_m7_profile_preferences_test", build
            )
            self.assertIn(
                "M7 database and Preferences acceptances require separate fresh output configurations",
                build,
            )

        target = _body_after_signature(self.chrome_build, 'executable("chrome_wasm")')
        direct_deps = _bracket_body_after(target, "deps = [")
        self.assertNotIn("wasm_profile_database_smoke", direct_deps)
        database_condition = "if (enable_chromium_wasm_m7_profile_database_test)"
        database_config = _body_after_signature(target, database_condition)
        database_deps = _body_after_signature(
            target[target.rindex(database_condition) :], database_condition
        )
        for token in (
            'output_name = "chrome_wasm_m7_profile_database_test"',
            'defines = [ "CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST=1" ]',
        ):
            with self.subTest(token=token):
                self.assertIn(token, database_config)
        self.assertIn(
            'deps += [ "//chrome/browser/wasm:wasm_profile_database_smoke" ]',
            database_deps,
        )
        for forbidden in (
            "wasm_m6_test_trust",
            "wasm_m6_controlled_https_test_mode",
            "CHROME_WASM_M6_CONTROLLED_HTTPS_TEST",
            "wasm_profile_preferences_smoke",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, database_config)
                self.assertNotIn(forbidden, database_deps)

        main_parts_target = _body_after_signature(
            self.wasm_build, 'source_set("wasm_browser_main_parts")'
        )
        main_parts_deps = _bracket_body_after(main_parts_target, "deps = [")
        self.assertNotIn("wasm_profile_database_smoke", main_parts_deps)
        self.assertIn(
            'defines = [ "CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST=1" ]',
            main_parts_target,
        )
        self.assertIn(
            'deps += [ ":wasm_profile_database_smoke" ]', main_parts_target
        )
        self.assertIn(
            'if (enable_chromium_wasm_m7_profile_database_test) {\n'
            '  source_set("wasm_profile_database_smoke")',
            self.wasm_build,
        )
        self.assertIn('"//sql",', self.wasm_build)
        self.assertIn('"//third_party/leveldatabase",', self.wasm_build)

        profile_target = _body_after_signature(
            self.wasm_build, 'source_set("wasm_profile")'
        )
        self.assertNotIn("wasm_profile_database_smoke", profile_target)

    def test_primary_sources_have_no_database_switch_or_helper_behavior(self) -> None:
        helper_include = (
            '#include "chrome/browser/wasm/wasm_profile_database_smoke.h"'
            "  // nogncheck"
        )
        for text in (self.chrome_main, self.main_parts):
            self.assertIn(helper_include, text)

        for text, token in (
            (self.chrome_main, "chrome::HasWasmProfileDatabaseSmokeArguments"),
            (self.chrome_main, "chrome::EnableWasmProfileDatabaseSmokeTestMode"),
            (self.chrome_main, "chrome::ReportWasmProfileDatabaseSmokeFailure"),
            (self.chrome_main, "chrome::NotifyWasmProfileDatabaseSmoke"),
            (self.main_parts, "chrome::IsWasmProfileDatabaseSmokeEnabled"),
            (self.main_parts, "chrome::StartWasmProfileDatabaseSmoke"),
            (self.main_parts, "chrome::DidWasmProfileDatabaseSmokeSucceed"),
            (self.main_parts, "chrome::NotifyWasmProfileDatabaseSmoke"),
        ):
            _assert_only_in_database_blocks(self, text, token)

    def test_database_branch_runs_after_profile_admission_before_host_or_browser_setup(self) -> None:
        admitted = self.main_parts.index("chrome::NotifyWasmProfileStorageProfileCreated()")
        database_branch = self.main_parts.index(
            "if (chrome::IsWasmProfileDatabaseSmokeEnabled())"
        )
        host_input = self.main_parts.index("chrome::InitializeWasmBrowserHostInput()")
        browser_manager = self.main_parts.index(
            "BrowserManagerServiceFactory::GetForProfile(profile_.get())"
        )
        self.assertLess(admitted, database_branch)
        self.assertLess(database_branch, host_input)
        self.assertLess(database_branch, browser_manager)

        branch = self.main_parts[database_branch:host_input]
        self.assertIn("profile_->GetPath()", branch)
        self.assertIn("base::BindOnce(&WasmBrowserMainParts::RequestShutdown", branch)
        self.assertIn("return content::RESULT_CODE_NORMAL_EXIT;", branch)

    def test_database_close_then_fence_then_lifecycle_then_drain_order(self) -> None:
        finish = _body_after_signature(
            self.main_parts, "void WasmBrowserMainParts::FinishShutdown()"
        )
        fence_begin = finish.index("profile_->BeginPersistentPrefsShutdownFence")
        fence_marker = finish.index(
            "chrome::NotifyWasmProfileDatabaseSmokeFenceResult(success);"
        )
        fence_reentry = finish.index("main_parts->FinishShutdown();")
        profile_reset = finish.index("profile_.reset();")
        storage_notify = finish.index("chrome::NotifyWasmProfileStorageProfileShutdown();")
        lifecycle_marker = finish.index(
            "chrome::NotifyWasmProfileDatabaseSmokeStorageLifecycle(\n"
            "            storage_lifecycle_notified);"
        )
        self.assertLess(fence_begin, fence_marker)
        self.assertLess(fence_marker, fence_reentry)
        self.assertLess(fence_reentry, profile_reset)
        self.assertLess(profile_reset, storage_notify)
        self.assertLess(storage_notify, lifecycle_marker)

        content_main = self.chrome_main.index("content::ContentMain(std::move(params))")
        drain = self.chrome_main.index("chrome::DrainAndReleaseWasmProfileStorageBackend()")
        drain_marker = self.chrome_main.index(
            "chrome::NotifyWasmProfileDatabaseSmokeBackendDrain("
        )
        process_exit = self.chrome_main.index("chromium_wasm_report_process_exit(exit_code)")
        self.assertLess(content_main, drain)
        self.assertLess(drain, drain_marker)
        self.assertLess(drain_marker, process_exit)

    def test_database_failure_withholds_lifecycle_and_converts_normal_result(self) -> None:
        finish = _body_after_signature(
            self.main_parts, "void WasmBrowserMainParts::FinishShutdown()"
        )
        failed = finish.index("!chrome::DidWasmProfileDatabaseSmokeSucceed()")
        withheld = finish.index(
            "chrome::NotifyWasmProfileDatabaseSmokeStorageLifecycle(false);"
        )
        storage_notify = finish.index("chrome::NotifyWasmProfileStorageProfileShutdown();")
        self.assertLess(failed, withheld)
        self.assertLess(withheld, storage_notify)
        self.assertIn("created-but-not-\n        // shutdown lifecycle state", finish)
        self.assertIn("emits no LEASE_RELEASED", finish)

        drain = _body_after_signature(
            self.chrome_main,
            "extern \"C\" int ChromeMain(int argc, const char** argv)",
        )
        self.assertIn("if (!drain_result.Succeeded())", drain)
        self.assertIn("result = CHROME_RESULT_CODE_UNSUPPORTED_PARAM;", drain)
        self.assertIn("database_smoke_enabled", drain)


if __name__ == "__main__":
    unittest.main()
