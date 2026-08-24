#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the normal volatile profile shutdown-failure receipt."""

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


class M7NormalProfileShutdownFailureLatchContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.header = source(
            "chrome/browser/wasm/wasm_profile_shutdown_failure_latch.h"
        )
        self.implementation = source(
            "chrome/browser/wasm/wasm_profile_shutdown_failure_latch.cc"
        )
        self.main_parts = source(
            "chrome/browser/wasm/wasm_browser_main_parts.cc"
        )
        self.chrome_main = source("chrome/app/chrome_main_wasm.cc")
        self.wasm_build = source("chrome/browser/wasm/BUILD.gn")
        self.chrome_build = source("chrome/BUILD.gn")

    def test_latch_is_process_result_only_and_fails_closed(self) -> None:
        for token in (
            "ResetWasmProfileShutdownFailureLatch();",
            "RecordWasmProfileShutdownFailure();",
            "WasmProfileShutdownFailureWasRecorded();",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.header)

        for token in (
            "base::NoDestructor<WasmProfileShutdownFailureLatch>",
            "base::AutoLock lock(lock_);",
            "failure_recorded_ = false;",
            "failure_recorded_ = true;",
            "return failure_recorded_;",
            "#if !BUILDFLAG(IS_WASM)",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.implementation)

        for text in (self.header, self.implementation):
            for forbidden in (
                "wasm_profile_storage",
                "wasmfs_",
                "<emscripten/",
            ):
                with self.subTest(forbidden=forbidden):
                    self.assertNotIn(forbidden, text)

    def test_normal_profile_failure_is_recorded_before_release(self) -> None:
        finish = _body_after_signature(
            self.main_parts, "void WasmBrowserMainParts::FinishShutdown()"
        )
        failure = finish.rindex("if (!prefs_shutdown_fence_succeeded)")
        record = finish.rindex("chrome::RecordWasmProfileShutdownFailure();")
        normal_reset = finish.rindex("profile_.reset();")
        self.assertLess(failure, record)
        self.assertLess(record, normal_reset)

        foundation = _body_after_signature(
            self.main_parts, "void WasmBrowserMainParts::ShutdownFoundation()"
        )
        foundation_record = foundation.index(
            "chrome::RecordWasmProfileShutdownFailure();"
        )
        foundation_reset = foundation.index(
            "profile_.reset();", foundation_record
        )
        self.assertLess(foundation_record, foundation_reset)
        self.assertIn(
            "after an incomplete Preferences shutdown fence", foundation
        )

    def test_chrome_main_resets_then_converts_only_a_normal_result(self) -> None:
        reset = self.chrome_main.index(
            "chrome::ResetWasmProfileShutdownFailureLatch();"
        )
        content_main = self.chrome_main.rindex(
            "content::ContentMain(std::move(params))"
        )
        read = self.chrome_main.index(
            "chrome::WasmProfileShutdownFailureWasRecorded()"
        )
        exit_code = self.chrome_main.index("const int exit_code =")

        self.assertLess(reset, content_main)
        self.assertLess(content_main, read)
        self.assertLess(read, exit_code)

        mapping_start = self.chrome_main.index(
            "if (chrome::WasmProfileShutdownFailureWasRecorded() &&"
        )
        mapping = self.chrome_main[
            mapping_start : self.chrome_main.index("#endif", mapping_start)
        ]
        self.assertIn("IsNormalChromeMainResult(result)", mapping)
        self.assertIn("result = CHROME_RESULT_CODE_UNSUPPORTED_PARAM;", mapping)
        self.assertIn(
            "!defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST)",
            self.chrome_main,
        )
        self.assertIn(
            "!defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST)",
            self.chrome_main,
        )

    def test_latch_has_direct_source_selected_build_edges(self) -> None:
        target = 'source_set("wasm_profile_shutdown_failure_latch")'
        test_target = 'test("wasm_profile_shutdown_failure_latch_unittests")'
        self.assertIn(target, self.wasm_build)
        self.assertIn(
            'public = [ "wasm_profile_shutdown_failure_latch.h" ]',
            self.wasm_build,
        )
        self.assertIn(
            'sources = [ "wasm_profile_shutdown_failure_latch.cc" ]',
            self.wasm_build,
        )
        self.assertIn(test_target, self.wasm_build)
        self.assertIn(":wasm_profile_shutdown_failure_latch", self.wasm_build)
        self.assertIn(
            '"//chrome/browser/wasm:wasm_profile_shutdown_failure_latch",',
            self.chrome_build,
        )


if __name__ == "__main__":
    unittest.main()
