#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Source contracts for the M7 three-module Preferences acceptance helper."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def _body_after_signature(text: str, signature: str) -> str:
    """Returns one balanced C++ function body without relying on line layout."""

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
    """Returns one balanced GN list body after |marker|."""

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


def _m7_macro_blocks(text: str) -> list[re.Match[str]]:
    return list(
        re.finditer(
            r"#if defined\(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST\)"
            r".*?#endif",
            text,
            re.DOTALL,
        )
    )


def _assert_only_in_m7_blocks(
    testcase: unittest.TestCase, text: str, token: str
) -> None:
    blocks = _m7_macro_blocks(text)
    positions = [match.start() for match in re.finditer(re.escape(token), text)]
    testcase.assertTrue(positions, f"missing {token}")
    for position in positions:
        with testcase.subTest(token=token, position=position):
            testcase.assertTrue(
                any(block.start() <= position < block.end() for block in blocks),
                f"{token} is not M7-config-gated",
            )


class M7ProfilePreferencesSmokeContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.header = source(
            "chrome/browser/wasm/wasm_profile_preferences_smoke.h"
        )
        self.smoke = source(
            "chrome/browser/wasm/wasm_profile_preferences_smoke.cc"
        )
        self.profile = source("chrome/browser/wasm/wasm_profile.cc")
        self.main_parts = source(
            "chrome/browser/wasm/wasm_browser_main_parts.cc"
        )
        self.chrome_main = source("chrome/app/chrome_main_wasm.cc")
        self.chrome_build = source("chrome/BUILD.gn")
        self.wasm_build = source("chrome/browser/wasm/BUILD.gn")
        self.m7_gni = source(
            "chrome/browser/wasm/wasm_profile_preferences_smoke.gni"
        )

    def test_strict_private_argument_and_digest_protocol(self) -> None:
        for token in (
            'constexpr char kSmokeSwitch[] = "wasm-profile-preferences-smoke";',
            'constexpr char kTokenASwitch[] = "wasm-profile-preferences-token-a";',
            'constexpr char kTokenBSwitch[] = "wasm-profile-preferences-token-b";',
            'constexpr char kWriteMode[] = "write";',
            'constexpr char kVerifyAndWriteMode[] = "verify-and-write";',
            'constexpr char kVerifyBMode[] = "verify-b";',
            "constexpr size_t kOpaqueTokenLength = 64;",
            "value.size() != kOpaqueTokenLength",
            "character >= '0' && character <= '9'",
            "character >= 'a' && character <= 'f'",
            '#include "crypto/hash.h"',
            "crypto::hash::Sha256(token)",
            "base::HexEncodeLower",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.smoke)

        self.assertNotIn('#include "crypto/sha2.h"', self.smoke)
        self.assertNotIn("SHA256HashString", self.smoke)
        self.assertIn(
            "--wasm-profile-preferences-smoke=verify-and-write", self.header
        )
        self.assertIn("--wasm-profile-preferences-smoke=verify-b", self.header)
        self.assertIn("token_b_ == token_a_", self.smoke)
        self.assertIn("token B must differ from token A", self.header)
        self.assertIn("if (has_token_a || !has_token_b)", self.smoke)
        self.assertIn("where |digest| is exactly 64 lowercase hexadecimal", self.header)
        self.assertIn("arguments, capability, storage, profile, read, fence", self.header)

    def test_markers_are_stderr_only_digest_or_fixed_failure_output(self) -> None:
        for token in (
            'constexpr char kMarkerPrefix[] = "CHROMIUM_WASM_M7_PREFS:";',
            'EmitMarker("READY")',
            'EmitDigestMarker("READ_A_OK", token_a_digest_)',
            'EmitDigestMarker("READ_B_OK", token_b_digest_)',
            'EmitDigestMarker("WRITE_ACCEPTED", token_b_digest_)',
            'EmitDigestMarker("WRITE_ACCEPTED", token_a_digest_)',
            'EmitDigestMarker("FENCE_OK", expected_fence_digest_)',
            'EmitMarker("LEASE_RELEASED")',
            'std::fprintf(stderr, "%sFAIL stage=%s\\n", kMarkerPrefix,',
            'std::fprintf(stderr, "%s%s sha256=%s\\n", kMarkerPrefix, marker,',
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.smoke)

        for token in (
            "token_a_.c_str()",
            "token_b_.c_str()",
            "kSmokePref.c_str()",
            "std::cout",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, self.smoke)

        emit_marker = _body_after_signature(
            self.smoke, "void EmitMarker(const char* marker)"
        )
        emit_digest_marker = _body_after_signature(
            self.smoke,
            "void EmitDigestMarker(const char* marker, const std::string& digest)",
        )
        self.assertNotIn("token_", emit_marker)
        self.assertNotIn("token_", emit_digest_marker)
        self.assertIn("digest.c_str()", emit_digest_marker)

        report_failure = _body_after_signature(
            self.smoke,
            "void ReportFailure(WasmProfilePreferencesSmokeFailureStage stage)",
        )
        self.assertLess(
            report_failure.index("ClearRawTokens();"),
            report_failure.index("std::fprintf(stderr"),
        )
        self.assertEqual(self.smoke.count("std::fprintf(stderr"), 3)
        for output_body in (emit_marker, emit_digest_marker, report_failure):
            for sensitive in (
                "kTokenASwitch",
                "kTokenBSwitch",
                "token_a_",
                "token_b_",
                "kSmokePref",
            ):
                with self.subTest(sensitive=sensitive):
                    self.assertNotIn(sensitive, output_body)
        clear_raw_tokens = _body_after_signature(self.smoke, "void ClearRawTokens()")
        self.assertIn("token_a_.clear();", clear_raw_tokens)
        self.assertIn("token_b_.clear();", clear_raw_tokens)

    def test_profile_action_writes_a_then_reads_a_writes_b_then_reads_b(self) -> None:
        start = _body_after_signature(self.smoke, "bool Start(PrefService* prefs)")
        ready = start.index('EmitMarker("READY");')
        verify = start.index("if (mode_ == SmokeMode::kVerifyAndWrite)")
        verify_b = start.index("else if (mode_ == SmokeMode::kVerifyB)")
        read = start.index("prefs->GetString(kSmokePref) != token_a_")
        read_marker = start.index('EmitDigestMarker("READ_A_OK", token_a_digest_);')
        write_b = start.index("prefs->SetString(kSmokePref, token_b_);")
        write_b_marker = start.index(
            'EmitDigestMarker("WRITE_ACCEPTED", token_b_digest_);'
        )
        write_a = start.index("prefs->SetString(kSmokePref, token_a_);")
        write_a_marker = start.index(
            'EmitDigestMarker("WRITE_ACCEPTED", token_a_digest_);'
        )
        read_b = start.index("prefs->GetString(kSmokePref) != token_b_")
        read_b_marker = start.index('EmitDigestMarker("READ_B_OK", token_b_digest_);')
        clear = start.index("ClearRawTokens();")

        self.assertLess(ready, verify)
        self.assertLess(verify, read)
        self.assertLess(read, read_marker)
        self.assertLess(read_marker, write_b)
        self.assertLess(write_b, write_b_marker)
        self.assertLess(write_a, write_a_marker)
        self.assertLess(write_b_marker, clear)
        self.assertLess(write_a_marker, clear)
        self.assertLess(verify_b, read_b)
        self.assertLess(read_b, read_b_marker)
        self.assertLess(read_b_marker, clear)
        self.assertNotIn("FENCE_OK", start)

        storage_lifecycle = _body_after_signature(
            self.smoke, "void NotifyStorageLifecycle(bool success)"
        )
        fence = _body_after_signature(
            self.smoke, "void NotifyFenceResult(bool success)"
        )
        backend_drain = _body_after_signature(
            self.smoke, "void NotifyBackendDrain(bool success)"
        )
        self.assertIn("if (fence_succeeded_)", fence)
        self.assertIn(
            "!success || !fence_succeeded_ || storage_lifecycle_succeeded_",
            storage_lifecycle,
        )
        self.assertIn("storage_lifecycle_succeeded_ = true;", storage_lifecycle)
        self.assertIn("storage_lifecycle_succeeded_", storage_lifecycle)
        self.assertIn("!storage_lifecycle_succeeded_", backend_drain)
        self.assertIn("if (lease_released_)", backend_drain)

    def test_test_pref_is_capability_gated_before_prefservice_construction(self) -> None:
        register = _body_after_signature(
            self.smoke,
            "void RegisterWasmProfilePreferencesSmokePref(",
        )
        self.assertIn("if (!IsWasmProfilePreferencesSmokeEnabled())", register)
        self.assertIn("registry->RegisterStringPref(kSmokePref, std::string());", register)
        registered = self.profile.index(
            "chrome::RegisterWasmProfilePreferencesSmokePref(pref_registry_.get());"
        )
        pref_service = self.profile.index("PrefServiceFactory pref_service_factory;")
        self.assertLess(registered, pref_service)
        _assert_only_in_m7_blocks(
            self,
            self.profile,
            "chrome::RegisterWasmProfilePreferencesSmokePref",
        )
        self.assertIn(
            '#include "chrome/browser/wasm/wasm_profile_preferences_smoke.h"  // nogncheck',
            self.profile,
        )

    def test_profile_branch_and_lifecycle_markers_follow_experimental_storage_boundaries(
        self,
    ) -> None:
        admitted = self.main_parts.index(
            "chrome::NotifyWasmProfileStorageProfileCreated()"
        )
        smoke_branch = self.main_parts.index(
            "if (chrome::IsWasmProfilePreferencesSmokeEnabled())"
        )
        host_input = self.main_parts.index(
            "chrome::InitializeWasmBrowserHostInput()"
        )
        browser_manager = self.main_parts.index(
            "BrowserManagerServiceFactory::GetForProfile(profile_.get())"
        )
        self.assertLess(admitted, smoke_branch)
        self.assertLess(smoke_branch, host_input)
        self.assertLess(smoke_branch, browser_manager)

        branch = self.main_parts[smoke_branch:host_input]
        self.assertIn(
            "chrome::StartWasmProfilePreferencesSmoke(profile_->GetPrefs())",
            branch,
        )
        self.assertIn("RequestShutdown();", branch)

        finish = _body_after_signature(
            self.main_parts, "void WasmBrowserMainParts::FinishShutdown()"
        )
        fence_begin = finish.index("profile_->BeginPrefsShutdownFence")
        fence_marker = finish.index(
            "chrome::NotifyWasmProfilePreferencesSmokeFenceResult(success);"
        )
        fence_reentry = finish.index("main_parts->FinishShutdown();")
        profile_reset = finish.index("profile_.reset();")
        storage_notify = finish.index(
            "chrome::NotifyWasmProfileStorageProfileShutdown();"
        )
        lifecycle_marker = finish.index(
            "chrome::NotifyWasmProfilePreferencesSmokeStorageLifecycle("
        )
        self.assertLess(fence_begin, fence_marker)
        self.assertLess(fence_marker, fence_reentry)
        self.assertLess(fence_reentry, profile_reset)
        self.assertLess(profile_reset, storage_notify)
        self.assertLess(storage_notify, lifecycle_marker)

        content_main = self.chrome_main.index("content::ContentMain(std::move(params))")
        drain = self.chrome_main.index(
            "chrome::DrainAndReleaseWasmProfileStorageBackend()"
        )
        drain_marker = self.chrome_main.index(
            "chrome::NotifyWasmProfilePreferencesSmokeBackendDrain("
        )
        process_exit = self.chrome_main.index(
            "chromium_wasm_report_process_exit(exit_code)"
        )
        self.assertLess(content_main, drain)
        self.assertLess(drain, drain_marker)
        self.assertLess(drain_marker, process_exit)
        self.assertIn(
            "chrome::NotifyWasmProfilePreferencesSmokeBackendDrain(\n"
            "        drain_result.Succeeded());",
            self.chrome_main,
        )

    def test_content_normal_exit_is_not_a_content_failure(self) -> None:
        normal_result = _body_after_signature(
            self.chrome_main, "bool IsNormalChromeMainResult(int result)"
        )
        self.assertIn(
            "return result == content::RESULT_CODE_NORMAL_EXIT ||\n"
            "         IsNormalResultCode(static_cast<ResultCode>(result));",
            normal_result,
        )

        content_failure = self.chrome_main[
            self.chrome_main.index("if (preferences_smoke_enabled &&") : self.chrome_main.index(
                "#endif", self.chrome_main.index("if (preferences_smoke_enabled &&")
            )
        ]
        self.assertIn("!IsNormalChromeMainResult(result)", content_failure)
        self.assertIn(
            "WasmProfilePreferencesSmokeFailureStage::kContent", content_failure
        )

        # The database acceptance target shares ChromeMain and has independent
        # normal-result checks. Verify the three decisions that affect the
        # Preferences target instead of constraining a file-wide occurrence
        # count owned by unrelated acceptance helpers.
        shared_drain_failure = _body_after_signature(
            self.chrome_main, "if (!drain_result.Succeeded())"
        )
        shared_drain_normal_result = _body_after_signature(
            shared_drain_failure, "if (IsNormalChromeMainResult(result))"
        )
        self.assertIn(
            "result = CHROME_RESULT_CODE_UNSUPPORTED_PARAM;",
            shared_drain_normal_result,
        )

        preferences_missing_drain = _body_after_signature(
            self.chrome_main, "} else if (preferences_smoke_enabled)"
        )
        self.assertIn(
            "chrome::NotifyWasmProfilePreferencesSmokeBackendDrain(false);",
            preferences_missing_drain,
        )
        preferences_missing_drain_normal_result = _body_after_signature(
            preferences_missing_drain, "if (IsNormalChromeMainResult(result))"
        )
        self.assertIn(
            "result = CHROME_RESULT_CODE_UNSUPPORTED_PARAM;",
            preferences_missing_drain_normal_result,
        )

        # Keep the final process-exit bridge responsible for preserving
        # non-normal ContentMain values after either Preferences drain path.
        final_exit = self.chrome_main[self.chrome_main.index("const int exit_code =") :]
        self.assertIn(
            "const int exit_code = IsNormalChromeMainResult(result)\n"
            "                            ? content::RESULT_CODE_NORMAL_EXIT\n"
            "                            : result;",
            final_exit,
        )

    def test_dedicated_gn_configuration_is_the_only_capability_grant(self) -> None:
        for token in (
            "enable_chromium_wasm_m7_profile_preferences_test = false",
            "is_wasm && enable_chromium_wasm_chrome",
            '"wasm-chrome-m7-profile-preferences"',
            "M7 Preferences acceptance must use "
            "out/wasm-chrome-m7-profile-preferences",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.m7_gni)

        for build_file in (self.chrome_build, self.wasm_build):
            self.assertIn(
                'import("//chrome/browser/wasm/wasm_profile_preferences_smoke.gni")',
                build_file,
            )

        target = _body_after_signature(
            self.chrome_build, 'executable("chrome_wasm")'
        )
        direct_deps = _bracket_body_after(target, "deps = [")
        self.assertNotIn("wasm_profile_preferences_smoke", direct_deps)
        self.assertNotIn('executable("chrome_wasm_m7_profile_preferences_test")', self.chrome_build)
        for token in (
            "if (enable_chromium_wasm_m7_profile_preferences_test)",
            'output_name = "chrome_wasm_m7_profile_preferences_test"',
            'defines = [ "CHROME_WASM_M7_PREFERENCES_SMOKE_TEST=1" ]',
            'deps += [ "//chrome/browser/wasm:wasm_profile_preferences_smoke" ]',
        ):
            with self.subTest(token=token):
                self.assertIn(token, target)
        for forbidden in (
            "wasm_m6_test_trust",
            "wasm_m6_controlled_https_test_mode",
            "CHROME_WASM_M6_CONTROLLED_HTTPS_TEST",
            "generate_wasm_m6_test_root_cert",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, target)

        for source_set in ("wasm_profile", "wasm_browser_main_parts"):
            target = _body_after_signature(
                self.wasm_build, f'source_set("{source_set}")'
            )
            direct_deps = _bracket_body_after(target, "deps = [")
            self.assertNotIn("wasm_profile_preferences_smoke", direct_deps)
            self.assertIn(
                "if (enable_chromium_wasm_m7_profile_preferences_test)", target
            )
            self.assertIn(
                'defines = [ "CHROME_WASM_M7_PREFERENCES_SMOKE_TEST=1" ]',
                target,
            )
            self.assertIn(
                'deps += [ ":wasm_profile_preferences_smoke" ]', target
            )

        helper_start = self.wasm_build.index(
            'if (enable_chromium_wasm_m7_profile_preferences_test) {\n'
            '  source_set("wasm_profile_preferences_smoke")'
        )
        self.assertGreater(helper_start, 0)
        self.assertIn("//crypto", self.wasm_build[helper_start:])

    def test_primary_configuration_has_no_helper_or_m7_switch_handling(self) -> None:
        # The helper is physically absent from the default GN graph. Shared
        # source files retain the M7 code only inside target-specific macro
        # blocks, whose includes are narrowly nogncheck-marked because GN does
        # not evaluate target-specific preprocessing during include checks.
        for text in (self.profile, self.main_parts, self.chrome_main):
            self.assertIn(
                '#include "chrome/browser/wasm/wasm_profile_preferences_smoke.h"  // nogncheck',
                text,
            )

        for text, token in (
            (
                self.profile,
                "chrome::RegisterWasmProfilePreferencesSmokePref",
            ),
            (self.main_parts, "chrome::IsWasmProfilePreferencesSmokeEnabled"),
            (self.main_parts, "chrome::StartWasmProfilePreferencesSmoke"),
            (self.main_parts, "chrome::NotifyWasmProfilePreferencesSmoke"),
            (self.chrome_main, "chrome::HasWasmProfilePreferencesSmokeArguments"),
            (self.chrome_main, "chrome::EnableWasmProfilePreferencesSmokeTestMode"),
            (self.chrome_main, "chrome::ReportWasmProfilePreferencesSmokeFailure"),
            (self.chrome_main, "chrome::NotifyWasmProfilePreferencesSmoke"),
        ):
            _assert_only_in_m7_blocks(self, text, token)

        self.assertNotIn(
            "WasmProfilePreferencesSmokeFailureStage::kCapability",
            self.chrome_main,
        )


if __name__ == "__main__":
    unittest.main()
