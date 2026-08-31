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
    """Returns whether |position| is nested below a DB-capable macro.

    The primary sources intentionally contain nested independent feature
    conditionals. A non-greedy regex stops at the first inner #endif and can
    therefore mistake a correctly guarded database call for production code.
    """

    macros = (
        "CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST",
        "CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_"
        "DATABASE_LOCAL_STORAGE_TEST",
    )
    active_stack: list[bool] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        if offset <= position < offset + len(line):
            return any(active_stack)

        directive = line.lstrip()
        if re.match(r"#\s*(if|ifdef|ifndef)\b", directive):
            active_stack.append(any(macro in directive for macro in macros))
        elif re.match(r"#\s*elif\b", directive):
            if active_stack:
                active_stack[-1] = any(
                    macro in directive for macro in macros
                )
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
            self.assertRegex(
                build,
                r"!\(enable_chromium_wasm_m7_profile_database_test\s*&&\s*"
                r"enable_chromium_wasm_m7_profile_preferences_test\)",
            )
            self.assertIn(
                "M7 persistence acceptances require separate fresh output configurations",
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
            'configs += [ ":wasm_profile_m7_database_smoke_config" ]',
            main_parts_target,
        )
        self.assertIn(
            'deps += [ ":wasm_profile_database_smoke" ]', main_parts_target
        )

        content_client_target = _body_after_signature(
            self.wasm_build, 'source_set("wasm_content_browser_client")'
        )
        self.assertIn(
            'if (enable_chromium_wasm_m7_profile_database_test) {',
            content_client_target,
        )
        self.assertIn(
            'configs += [ ":wasm_profile_m7_database_smoke_config" ]',
            content_client_target,
        )
        self.assertRegex(
            self.wasm_build,
            r"if \(enable_chromium_wasm_m7_profile_database_test\s*\|\|\s*"
            r"enable_chromium_wasm_m7_profile_bookmark_cookie_history_"
            r"database_local_storage_test\) \{\s*"
            r"source_set\(\"wasm_profile_database_smoke\"\)",
        )
        self.assertIn('"//sql",', self.wasm_build)
        self.assertIn('"//third_party/leveldatabase",', self.wasm_build)

        layout_config = _body_after_signature(
            self.wasm_build,
            'config("wasm_profile_m7_database_smoke_config")',
        )
        self.assertIn(
            'defines = [ "CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST=1" ]',
            layout_config,
        )

        profile_target = _body_after_signature(
            self.wasm_build, 'source_set("wasm_profile")'
        )
        profile_deps = _bracket_body_after(profile_target, "deps = [")
        self.assertNotIn("wasm_profile_database_smoke", profile_deps)
        database_profile_gate = _body_after_signature(
            profile_target, "if (enable_chromium_wasm_m7_profile_database_test)"
        )
        self.assertIn(
            'public_configs = [ ":wasm_profile_m7_database_smoke_config" ]',
            database_profile_gate,
        )
        self.assertIn(
            'deps += [ ":wasm_profile_database_smoke" ]',
            database_profile_gate,
        )

    def test_primary_sources_have_no_database_switch_or_helper_behavior(self) -> None:
        helper_include = (
            '#include "chrome/browser/wasm/wasm_profile_database_smoke.h"'
            "  // nogncheck"
        )
        for text in (self.chrome_main, self.main_parts, self.profile):
            self.assertIn(helper_include, text)

        for text in (
            self.database_header,
            self.database_source,
            self.profile,
            self.chrome_main,
        ):
            self.assertNotIn("StartWasmProfileDatabaseSmoke", text)
        self.assertIn(
            "StartWasmProfileDatabaseSmokeOrShutdown", self.main_parts
        )
        _assert_only_in_database_blocks(
            self, self.main_parts, "StartWasmProfileDatabaseSmokeOrShutdown"
        )

        for text, token in (
            (self.chrome_main, "chrome::HasWasmProfileDatabaseSmokeArguments"),
            (self.chrome_main, "chrome::EnableWasmProfileDatabaseSmokeTestMode"),
            (self.chrome_main, "chrome::ReportWasmProfileDatabaseSmokeFailure"),
            (self.chrome_main, "chrome::NotifyWasmProfileDatabaseSmoke"),
            (self.main_parts, "chrome::IsWasmProfileDatabaseSmokeEnabled"),
            (self.main_parts, "chrome::DidWasmProfileDatabaseSmokeSucceed"),
            (self.main_parts, "chrome::NotifyWasmProfileDatabaseSmoke"),
            (self.profile, "WasmProfileDatabaseLifetimeParticipant"),
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
        self.assertIn(
            "chrome::TryAcquireWasmProfileStorageProfileIO()", branch
        )
        self.assertIn("profile_->StartDatabaseSmoke(", branch)
        self.assertIn("std::move(*profile_io_hold)", branch)
        self.assertIn(
            "&WasmBrowserMainParts::OnWasmProfileDatabaseSmokeComplete",
            branch,
        )
        self.assertNotIn("profile_io_hold->Complete(", branch)
        self.assertNotIn("StartWasmProfileDatabaseSmoke", branch)
        self.assertLess(
            branch.index("chrome::TryAcquireWasmProfileStorageProfileIO()"),
            branch.index("profile_->StartDatabaseSmoke("),
        )
        self.assertLess(
            branch.index("profile_->StartDatabaseSmoke("),
            branch.index("std::move(*profile_io_hold)"),
        )
        self.assertIn("return content::RESULT_CODE_NORMAL_EXIT;", branch)

    def test_profile_owned_participant_keeps_task_and_admission_together(self) -> None:
        for token in (
            "class WasmProfileDatabaseLifetimeParticipant",
            "WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold",
            "bool Start(base::OnceCallback<void(bool success)> completion);",
            "void Cancel();",
            "bool QuarantineForFailureShutdown();",
            "bool IsActive() const;",
            "bool HasCompleted() const;",
            "bool DidSucceed() const;",
        ):
            with self.subTest(header_token=token):
                self.assertIn(token, self.database_header)

        state = _body_after_signature(
            self.database_source,
            "class WasmProfileDatabaseLifetimeParticipant::State",
        )
        for token in (
            "profile_io_hold_(std::move(profile_io_hold))",
            "base::TaskShutdownBehavior::BLOCK_SHUTDOWN",
            "scoped_refptr<base::SequencedTaskRunner> task_runner_",
            "base::OnceCallback<void(bool success)> completion_",
            "profile_io_hold_",
            "bool cancelled_ = false",
        ):
            with self.subTest(state_token=token):
                self.assertIn(token, state)

        start = _body_after_signature(
            self.database_source,
            "bool Start(base::OnceCallback<void(bool success)> completion)",
        )
        begin = start.index("BeginDatabaseTask(")
        runner = start.index("base::ThreadPool::CreateSequencedTaskRunner(")
        post = start.index("PostTaskAndReplyWithResult(")
        self.assertLess(begin, runner)
        self.assertLess(runner, post)
        self.assertIn("std::move(*input)", start)
        self.assertIn("&State::OnDatabaseTaskComplete", start)

        cancel = _body_after_signature(self.database_source, "void Cancel()")
        self.assertIn("cancelled_ = true;", cancel)
        self.assertNotIn("CompleteProfileIO", cancel)
        self.assertNotIn("profile_io_hold_.reset", cancel)

        task_complete = _body_after_signature(
            self.database_source,
            "void OnDatabaseTaskComplete(DatabaseTaskResult result)",
        )
        runner_reset = task_complete.index("task_runner_.reset();")
        latch = task_complete.index("CompleteDatabaseTask(")
        admission = task_complete.index("CompleteProfileIO(")
        self.assertLess(runner_reset, latch)
        self.assertLess(latch, admission)
        self.assertIn("/*operation_allowed=*/!cancelled_", task_complete)

        complete = _body_after_signature(
            self.database_source,
            "void CompleteProfileIO(bool operation_succeeded)",
        )
        hold_complete = complete.index("profile_io_hold_->Complete(")
        hold_reset = complete.index("profile_io_hold_.reset();")
        completed = complete.index("completed_ = true;")
        callback = complete.index("std::move(completion).Run(succeeded);")
        self.assertLess(hold_complete, hold_reset)
        self.assertLess(hold_reset, completed)
        self.assertLess(completed, callback)

        destructor = _body_after_signature(
            self.database_source,
            "~WasmProfileDatabaseLifetimeParticipant()",
        )
        self.assertIn("QuarantineForFailureShutdown();", destructor)
        quarantine = _body_after_signature(
            self.database_source,
            "bool WasmProfileDatabaseLifetimeParticipant::\n"
            "    QuarantineForFailureShutdown()",
        )
        cancel_call = quarantine.index("state_->Cancel();")
        retain = quarantine.index("quarantined_states->push_back(std::move(state_));")
        self.assertLess(cancel_call, retain)
        self.assertIn(
            "base::NoDestructor<std::vector<std::unique_ptr<State>>>",
            quarantine,
        )
        self.assertNotIn("CompleteProfileIO", quarantine)

    def test_profile_and_main_parts_gate_active_database_shutdown(self) -> None:
        self.assertIn(
            "void OnWasmProfileDatabaseSmokeComplete(bool success);",
            self.main_parts_header,
        )
        for token in (
            "bool StartDatabaseSmoke(",
            "bool HasActiveDatabaseSmoke() const;",
            "bool DidDatabaseSmokeSucceed() const;",
            "void CancelDatabaseSmokeForShutdown();",
            "void QuarantineDatabaseSmokeForFailureShutdown();",
            "database_lifetime_participant_",
        ):
            with self.subTest(profile_header_token=token):
                self.assertIn(token, self.profile_header)

        profile_start = _body_after_signature(
            self.profile, "bool WasmProfile::StartDatabaseSmoke("
        )
        self.assertIn(
            "std::make_unique<chrome::WasmProfileDatabaseLifetimeParticipant>",
            profile_start,
        )
        self.assertIn("std::move(profile_io_hold)", profile_start)
        self.assertIn("database_lifetime_participant_->Start", profile_start)
        self.assertIn("ProfileIOCompletion::kFailed", profile_start)

        profile_destructor = _body_after_signature(
            self.profile, "WasmProfile::~WasmProfile()"
        )
        self.assertIn(
            "QuarantineDatabaseSmokeForFailureShutdown();", profile_destructor
        )

        completion = _body_after_signature(
            self.main_parts,
            "void WasmBrowserMainParts::OnWasmProfileDatabaseSmokeComplete(",
        )
        self.assertIn(
            "success && profile_ && profile_->DidDatabaseSmokeSucceed()",
            completion,
        )
        self.assertIn("if (shutdown_requested_)", completion)
        self.assertIn("MaybeStartShutdown();", completion)
        self.assertIn("RequestShutdown();", completion)

        maybe_shutdown = _body_after_signature(
            self.main_parts, "void WasmBrowserMainParts::MaybeStartShutdown()"
        )
        active = maybe_shutdown.index("profile_->HasActiveDatabaseSmoke()")
        cancel = maybe_shutdown.index(
            "profile_->CancelDatabaseSmokeForShutdown()"
        )
        finish = maybe_shutdown.index("FinishShutdown();")
        self.assertLess(active, cancel)
        self.assertLess(cancel, finish)

        finish_shutdown = _body_after_signature(
            self.main_parts, "void WasmBrowserMainParts::FinishShutdown()"
        )
        active = finish_shutdown.index("profile_->HasActiveDatabaseSmoke()")
        cancel = finish_shutdown.index(
            "profile_->CancelDatabaseSmokeForShutdown()"
        )
        profile_shutdown = finish_shutdown.index("profile_->Shutdown();")
        self.assertLess(active, cancel)
        self.assertLess(cancel, profile_shutdown)

        foundation = _body_after_signature(
            self.main_parts, "void WasmBrowserMainParts::ShutdownFoundation()"
        )
        quarantine = foundation.index(
            "profile_->QuarantineDatabaseSmokeForFailureShutdown();"
        )
        profile_shutdown = foundation.index("profile_->Shutdown();")
        self.assertLess(quarantine, profile_shutdown)

    def test_normal_chrome_keeps_the_default_partition_in_memory(self) -> None:
        policy = _body_after_signature(
            self.profile,
            "bool WasmProfile::ShouldUseInMemoryDefaultStoragePartition()",
        )
        self.assertIn("return true;", policy)
        self.assertNotIn("CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST", policy)

        profile_target = _body_after_signature(
            self.wasm_build, 'source_set("wasm_profile")'
        )
        direct_deps = _bracket_body_after(profile_target, "deps = [")
        self.assertNotIn("wasm_profile_database_smoke", direct_deps)
        self.assertNotIn(
            "CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST", direct_deps
        )

    def test_database_close_then_prefs_fence_then_lifecycle_then_drain_order(
        self,
    ) -> None:
        finish = _body_after_signature(
            self.main_parts, "void WasmBrowserMainParts::FinishShutdown()"
        )
        fence_begin = finish.index("profile_->BeginPrefsShutdownFence")
        fence_marker = finish.index(
            "chrome::NotifyWasmProfileDatabaseSmokeFenceResult(success);"
        )
        fence_reentry = finish.index("main_parts->FinishShutdown();")
        profile_reset = finish.index("profile_.reset();")
        storage_notify = finish.index("chrome::NotifyWasmProfileStorageProfileShutdown();")
        lifecycle_marker = finish.index(
            "chrome::NotifyWasmProfileDatabaseSmokeStorageLifecycle(\n"
            "        smoke_allows_storage_lifecycle);"
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

    def test_database_failure_publishes_terminal_shutdown_then_fails_closed(self) -> None:
        finish = _body_after_signature(
            self.main_parts, "void WasmBrowserMainParts::FinishShutdown()"
        )
        failed = finish.index("!chrome::DidWasmProfileDatabaseSmokeSucceed()")
        storage_notify = finish.index(
            "chrome::NotifyWasmProfileStorageProfileShutdown();"
        )
        lifecycle_marker = finish.index(
            "chrome::NotifyWasmProfileDatabaseSmokeStorageLifecycle(\n"
            "        smoke_allows_storage_lifecycle);"
        )
        profile_reset = finish.index("profile_.reset();")
        self.assertLess(profile_reset, storage_notify)
        self.assertLess(storage_notify, failed)
        self.assertLess(failed, lifecycle_marker)
        self.assertLess(storage_notify, lifecycle_marker)
        self.assertIn("terminal failed hold must select failure retirement", finish)
        self.assertIn("handoff or LEASE_RELEASED receipt", finish)

        self.assertIn("if (!drain_result.Succeeded())", self.chrome_main)
        self.assertIn(
            "result = CHROME_RESULT_CODE_UNSUPPORTED_PARAM;", self.chrome_main
        )
        self.assertIn("database_smoke_enabled", self.chrome_main)


if __name__ == "__main__":
    unittest.main()
