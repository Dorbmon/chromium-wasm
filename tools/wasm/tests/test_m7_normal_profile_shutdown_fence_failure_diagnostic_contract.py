#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the normal volatile-profile fence failure diagnostic."""

from __future__ import annotations

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


class M7NormalProfileShutdownFenceFailureDiagnosticContractTest(
    unittest.TestCase
):
    def setUp(self) -> None:
        self.diagnostic_gni = source(
            "chrome/browser/wasm/wasm_profile_shutdown_fence_failure_diagnostic.gni"
        )
        self.chrome_build = source("chrome/BUILD.gn")
        self.wasm_build = source("chrome/browser/wasm/BUILD.gn")
        self.profile = source("chrome/browser/wasm/wasm_profile.cc")
        self.chrome_main = source("chrome/app/chrome_main_wasm.cc")

    def test_gn_capability_is_isolated_to_a_fresh_normal_profile_artifact(
        self,
    ) -> None:
        for token in (
            "enable_chromium_wasm_m7_normal_profile_fence_failure_diagnostic = false",
            "is_wasm && enable_chromium_wasm_chrome",
            "!enable_chromium_wasm_m7_profile_preferences_test",
            "!enable_chromium_wasm_m7_profile_database_test",
            '"wasm-chrome-m7-normal-profile-fence-failure"',
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.diagnostic_gni)

        self.assertIn(
            'import("//chrome/browser/wasm/'
            'wasm_profile_shutdown_fence_failure_diagnostic.gni")',
            self.chrome_build,
        )
        self.assertIn(
            'import("//chrome/browser/wasm/'
            'wasm_profile_shutdown_fence_failure_diagnostic.gni")',
            self.wasm_build,
        )

        diagnostic = self.chrome_build[
            self.chrome_build.index(
                "if (enable_chromium_wasm_m7_normal_profile_fence_failure_diagnostic)"
            ) : self.chrome_build.index(
                "if (enable_chromium_wasm_m7_profile_database_test)"
            )
        ]
        self.assertIn(
            'output_name = "chrome_wasm_m7_normal_profile_fence_failure_diagnostic"',
            diagnostic,
        )
        self.assertNotIn("chrome_wasm_profile_storage", diagnostic)
        self.assertNotIn("wasm_profile_storage", diagnostic)

    def test_only_wasm_profile_receives_the_diagnostic_define(self) -> None:
        profile_target = self.wasm_build[
            self.wasm_build.index('source_set("wasm_profile")') : self.wasm_build.index(
                'source_set("wasm_profile_prefs_fence_controller")'
            )
        ]
        self.assertIn(
            'defines = [ "CHROME_WASM_M7_NORMAL_PROFILE_FENCE_FAILURE_DIAGNOSTIC=1" ]',
            profile_target,
        )
        self.assertEqual(
            self.wasm_build.count(
                "CHROME_WASM_M7_NORMAL_PROFILE_FENCE_FAILURE_DIAGNOSTIC=1"
            ),
            1,
        )
        self.assertNotIn(
            "CHROME_WASM_M7_NORMAL_PROFILE_FENCE_FAILURE_DIAGNOSTIC",
            self.chrome_main,
        )

    def test_forced_failure_can_only_follow_a_successful_bounded_readback(self) -> None:
        verify = _body_after_signature(
            self.profile, "bool VerifyPersistentPrefsOnFileSequence("
        )
        self.assertIn("ReadFileToStringWithMaxSize", verify)
        self.assertIn("kMaxPersistentPrefsFileSize", verify)
        self.assertIn("base::JSONReader::ReadDict", verify)
        self.assertIn("*persisted_values == expected_values", verify)

        reply = _body_after_signature(
            self.profile, "void VerifyPersistentPrefsAndReplyOnFileSequence("
        )
        self.assertIn("CHROMIUM_WASM_M7_NORMAL_PROFILE_FENCE_DIAGNOSTIC:", reply)
        self.assertIn("READBACK_OK_FORCED_FAILURE", reply)
        readback = reply.index("VerifyPersistentPrefsOnFileSequence")
        diagnostic = reply.index(
            "CHROME_WASM_M7_NORMAL_PROFILE_FENCE_FAILURE_DIAGNOSTIC"
        )
        marker_index = reply.index("CHROMIUM_WASM_M7_NORMAL_PROFILE_FENCE_DIAGNOSTIC:")
        forced_failure = reply.index("std::move(reply).Run(false);")
        normal_reply = reply.rindex("std::move(reply).Run(readback_succeeded);")
        self.assertLess(readback, diagnostic)
        self.assertLess(diagnostic, marker_index)
        self.assertLess(marker_index, forced_failure)
        self.assertLess(forced_failure, normal_reply)
        self.assertIn("if (readback_succeeded)", reply)


if __name__ == "__main__":
    unittest.main()
