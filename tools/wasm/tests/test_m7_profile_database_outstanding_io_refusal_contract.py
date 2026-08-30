#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Source contracts for the M7 outstanding-profile-I/O drain refusal probe."""

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


class M7ProfileDatabaseOutstandingIORefusalContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.gni = source("chrome/browser/wasm/wasm_profile_database_smoke.gni")
        self.chrome_build = source("chrome/BUILD.gn")
        self.wasm_build = source("chrome/browser/wasm/BUILD.gn")
        self.chrome_main = source("chrome/app/chrome_main_wasm.cc")
        self.main_parts = source(
            "chrome/browser/wasm/wasm_browser_main_parts.cc"
        )
        self.storage = source("chrome/browser/wasm/wasm_profile_storage.cc")
        self.storage_header = source("chrome/browser/wasm/wasm_profile_storage.h")
        self.result = source(
            "chrome/browser/wasm/wasm_profile_storage_drain_result.h"
        )
        self.result_unittest = source(
            "chrome/browser/wasm/wasm_profile_storage_drain_result_unittest.cc"
        )

    def test_gn_selects_a_separate_database_artifact(self) -> None:
        for token in (
            "enable_chromium_wasm_m7_profile_database_outstanding_io_refusal_test = false",
            "M7 outstanding-I/O refusal probe requires the M7 database smoke configuration",
            "wasm-chrome-m7-profile-database-outstanding-io-refusal",
            "out/wasm-chrome-m7-profile-database-outstanding-io-refusal",
            "CHROME_WASM_M7_PROFILE_DATABASE_OUTSTANDING_IO_REFUSAL_TEST=1",
            "chrome_wasm_m7_profile_database_outstanding_io_refusal_test",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.gni + self.chrome_build + self.wasm_build)

        self.assertIn(
            "enable_chromium_wasm_m7_profile_database_abort_pc_diagnostic &&\n"
            "          enable_chromium_wasm_m7_profile_database_outstanding_io_refusal_test",
            self.gni,
        )
        self.assertIn(
            "enable_chromium_wasm_m7_profile_database_lock_test &&\n"
            "          enable_chromium_wasm_m7_profile_database_outstanding_io_refusal_test",
            self.gni,
        )

    def test_probe_retains_only_the_completed_task_admission(self) -> None:
        marker = "CHROME_WASM_M7_PROFILE_DATABASE_OUTSTANDING_IO_REFUSAL_TEST"
        self.assertIn(marker, self.main_parts)
        self.assertIn(
            "RetainWasmProfileStorageOutstandingIOForRefusalTest(", self.main_parts
        )
        self.assertIn(
            "outstanding_profile_io_hold_for_refusal_test_", self.storage
        )
        self.assertIn(
            "outstanding_profile_io_refusal_observed_", self.storage
        )
        self.assertIn(
            "CompleteWasmProfileStorageOutstandingIORefusalAsFailedForTest",
            self.storage_header,
        )
        self.assertIn(
            "ProfileIOCompletion::kFailed", self.storage
        )

        database_branch = self.main_parts[
            self.main_parts.index("if (chrome::IsWasmProfileDatabaseSmokeEnabled())") :
        ]
        retain = database_branch.index(
            "RetainWasmProfileStorageOutstandingIOForRefusalTest("
        )
        request_shutdown = database_branch.index("main_parts->RequestShutdown();")
        self.assertLess(retain, request_shutdown)
        self.assertIn("released any storage resources it opened", database_branch)
        self.assertIn("#else", database_branch[retain:request_shutdown])

    def test_waiting_admission_refuses_the_outer_backend_transaction(self) -> None:
        drain = _body_after_signature(
            self.storage, "WasmProfileStorageDrainResult DrainAndReleaseBackend()"
        )
        waiting = drain.index("kWaitingForRegisteredProfileIO")
        refusal = drain.index("result.refused_for_outstanding_profile_io = true;")
        return_result = drain.index("return result;", refusal)
        attempt = drain.index("backend_drain_attempted_ = true;")
        self.assertLess(waiting, refusal)
        self.assertLess(refusal, return_result)
        self.assertLess(return_result, attempt)
        self.assertIn("result.error = -EBUSY;", drain[waiting:return_result])
        self.assertIn(
            "bool refused_for_outstanding_profile_io = false;", self.result
        )
        self.assertIn("!refused_for_outstanding_profile_io", self.result)
        self.assertIn(
            "OutstandingProfileIORefusalFailsADrain", self.result_unittest
        )
        self.assertIn(
            "outstanding_profile_io_refusal_observed_ = true;", self.storage
        )

        for token in (
            "CHROMIUM_WASM_M7_PROFILE_DRAIN_REFUSED:OUTSTANDING_IO",
            "bool IsWasmM7ProfileOutstandingIORefusal(",
            "result.error == -EBUSY",
            "result.refused_for_outstanding_profile_io",
            "result.detached_descriptors == 0",
            "result.data_file_states == 0",
            "result.libc_flush_failed == 0",
            "result.data_flush_failures == 0",
            "result.data_close_failures == 0",
            "result.prior_close_failures == 0",
            "result.lease_release_failures == 0",
            "result.backend_retire_failures == 0",
            "!result.backend_sealed",
            "!result.lease_released",
            "!result.backend_retired",
            "if (IsWasmM7ProfileOutstandingIORefusal(drain_result))",
            "CompleteWasmProfileStorageOutstandingIORefusalAsFailedForTest()",
            "CHROMIUM_WASM_M7_PROFILE_FAILURE_RETIREMENT:SEALED_LEASE_RETAINED",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.chrome_main)

        receipt = self.chrome_main.index(
            "if (IsWasmM7ProfileOutstandingIORefusal(drain_result))"
        )
        first_backend_drain = self.chrome_main.index(
            "chrome::DrainAndReleaseWasmProfileStorageBackend()"
        )
        complete_outstanding_hold = self.chrome_main.index(
            "CompleteWasmProfileStorageOutstandingIORefusalAsFailedForTest()"
        )
        second_backend_drain = self.chrome_main.index(
            "drain_result = chrome::DrainAndReleaseWasmProfileStorageBackend()"
        )
        failure_retirement = self.chrome_main.index(
            "if (IsWasmM7ProfileFailureRetirement(drain_result))", receipt
        )
        database_result = self.chrome_main.index(
            "chrome::NotifyWasmProfileDatabaseSmokeBackendDrain("
        )
        process_exit = self.chrome_main.index(
            "chromium_wasm_report_process_exit(exit_code)"
        )
        self.assertLess(first_backend_drain, receipt)
        self.assertLess(receipt, complete_outstanding_hold)
        self.assertLess(complete_outstanding_hold, second_backend_drain)
        self.assertLess(second_backend_drain, failure_retirement)
        self.assertLess(failure_retirement, database_result)
        self.assertLess(receipt, process_exit)


if __name__ == "__main__":
    unittest.main()
