#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the bounded public-package reload observation."""

from __future__ import annotations

from copy import deepcopy
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest import mock


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

import package
import run_m9_package_outer_document_reload_stress as runner
from m0_common import M0Error


def _runtime_core_resource_receipt() -> list[dict[str, str]]:
    return [
        {"initiator_type": initiator_type, "path": path}
        for path, initiator_type in (
            runner.package_browser_smoke.RUNTIME_CORE_RESOURCE_RECEIPT
        )
    ]


def _runtime_core_server_receipt() -> list[dict[str, object]]:
    return [
        {"path": path, "successful_get_count": 1}
        for path, _initiator in (
            runner.package_browser_smoke.RUNTIME_CORE_RESOURCE_RECEIPT
        )
    ]


def _epoch(frame_count: int) -> dict[str, object]:
    return {
        "frames_presented": frame_count,
        "post_exit_frame_quiescent": True,
        "process_exit_code": 0,
        "runtime_core_resource_receipt": _runtime_core_resource_receipt(),
        "runtime_core_server_receipt": _runtime_core_server_receipt(),
        "runtime_exit_code": 0,
        "shutdown_disabled": True,
        "shutdown_requested": True,
    }


def _passing_result() -> dict[str, object]:
    return {
        "browser_version": "test-browser",
        "distinct_document_epoch_count": runner.EPOCH_COUNT,
        "distinct_document_time_origin_count": runner.EPOCH_COUNT,
        "epochs": [_epoch(1), _epoch(2), _epoch(3)],
        "limitations": list(runner.LIMITATIONS),
        "m9_gate_complete": False,
        "outer_document_epoch_count": runner.EPOCH_COUNT,
        "outer_document_restarts": runner.RESTART_COUNT,
        "performance_gate": False,
        "release_status": package.RELEASE_STATUS,
        "scope": runner.SCOPE,
        "served_version_json_sha256": "a" * 64,
    }


class M9PackageOuterDocumentReloadStressTest(unittest.TestCase):
    def test_post_exit_frame_quiescence_rejects_a_late_canvas_presentation(
        self,
    ) -> None:
        status = {
            "fatalCount": 0,
            "framesPresented": 7,
            "processExitCode": 0,
            "runtimeExitCode": 0,
            "shutdownDisabled": True,
            "shutdownRequested": True,
        }

        self.assertIsNone(
            runner.package_browser_smoke._require_post_exit_frame_quiescence_sample(
                status, 7
            )
        )
        for name, field, replacement, message in (
            ("late frame", "framesPresented", 8, "presented a frame"),
            ("missing frame", "framesPresented", 0, "frame count is invalid"),
            ("unclean native exit", "processExitCode", 1, "exit codes 0"),
        ):
            with self.subTest(name=name):
                invalid = deepcopy(status)
                invalid[field] = replacement
                with self.assertRaisesRegex(M0Error, message):
                    runner.package_browser_smoke._require_post_exit_frame_quiescence_sample(
                        invalid, 7
                    )

    def test_result_requires_three_clean_distinct_package_lifetimes(self) -> None:
        result = _passing_result()

        self.assertEqual(result, runner.validate_reload_stress_result(result))

        invalid_cases = (
            ("false M9 gate", "m9_gate_complete", True, "must not complete M9"),
            (
                "performance gate",
                "performance_gate",
                True,
                "must not set a performance gate",
            ),
            ("epoch count", "outer_document_epoch_count", 2, "epoch count"),
            ("restart count", "outer_document_restarts", 1, "restart count"),
            (
                "reused document epoch",
                "distinct_document_epoch_count",
                2,
                "distinct_document_epoch_count",
            ),
            (
                "reused time origin",
                "distinct_document_time_origin_count",
                2,
                "distinct_document_time_origin_count",
            ),
            (
                "version identity",
                "served_version_json_sha256",
                "not-a-sha256",
                "VERSION.json identity",
            ),
        )
        for name, field, replacement, message in invalid_cases:
            with self.subTest(name=name):
                invalid = deepcopy(result)
                invalid[field] = replacement
                with self.assertRaisesRegex(M0Error, message):
                    runner.validate_reload_stress_result(invalid)

        for name, field, replacement, message in (
            ("missing frame", "frames_presented", 0, "lacks a frame"),
            (
                "post-exit frame quiescence",
                "post_exit_frame_quiescent",
                False,
                "lacks post-exit frame quiescence",
            ),
            ("boolean exit", "runtime_exit_code", False, "exit is unclean"),
            ("nonzero exit", "process_exit_code", 1, "exit is unclean"),
            ("not requested", "shutdown_requested", False, "shutdown is invalid"),
        ):
            with self.subTest(epoch_field=name):
                invalid = deepcopy(result)
                invalid["epochs"][1][field] = replacement
                with self.assertRaisesRegex(M0Error, message):
                    runner.validate_reload_stress_result(invalid)

    def test_result_rejects_missing_or_forged_runtime_resource_receipts(self) -> None:
        result = _passing_result()
        missing_epoch_field = deepcopy(result)
        del missing_epoch_field["epochs"][1]["runtime_core_resource_receipt"]
        missing_resource = deepcopy(result)
        missing_resource["epochs"][1]["runtime_core_resource_receipt"].pop()
        wrong_path = deepcopy(result)
        wrong_path["epochs"][1]["runtime_core_resource_receipt"][0][
            "path"
        ] = "forged-host-bridge.js"
        wrong_initiator = deepcopy(result)
        fetch_index = next(
            index
            for index, receipt in enumerate(
                wrong_initiator["epochs"][1]["runtime_core_resource_receipt"]
            )
            if receipt["initiator_type"] == "fetch"
        )
        wrong_initiator["epochs"][1]["runtime_core_resource_receipt"][
            fetch_index
        ]["initiator_type"] = "script"
        malformed = deepcopy(result)
        del malformed["epochs"][1]["runtime_core_resource_receipt"][0][
            "initiator_type"
        ]
        missing_server_epoch_field = deepcopy(result)
        del missing_server_epoch_field["epochs"][1]["runtime_core_server_receipt"]
        missing_server_resource = deepcopy(result)
        missing_server_resource["epochs"][1]["runtime_core_server_receipt"].pop()
        repeated_server_get = deepcopy(result)
        repeated_server_get["epochs"][1]["runtime_core_server_receipt"][0][
            "successful_get_count"
        ] = 2

        for name, invalid, message in (
            ("missing epoch field", missing_epoch_field, "epoch 2 fields are invalid"),
            ("missing resource", missing_resource, "runtime resource receipt"),
            ("wrong path", wrong_path, "runtime resource receipt"),
            ("wrong initiator", wrong_initiator, "runtime resource receipt"),
            ("malformed", malformed, "runtime resource receipt"),
            (
                "missing server epoch field",
                missing_server_epoch_field,
                "epoch 2 fields are invalid",
            ),
            (
                "missing server resource",
                missing_server_resource,
                "runtime server receipt",
            ),
            (
                "repeated server GET",
                repeated_server_get,
                "runtime server receipt",
            ),
        ):
            with self.subTest(name=name), self.assertRaisesRegex(M0Error, message):
                runner.validate_reload_stress_result(invalid)

    def test_run_uses_only_the_fixed_wisp_disabled_three_epoch_path(self) -> None:
        result = _passing_result()
        with mock.patch.object(
            runner.package_browser_smoke,
            "run_package_browser_smoke",
            return_value=result,
        ) as run_package_browser_smoke:
            self.assertEqual(
                result,
                runner.run_package_outer_document_reload_stress(
                    dist_dir=Path("/fake/package"),
                    browser_argument=Path("/fake/browser"),
                    no_sandbox=True,
                    timeout=90.0,
                ),
            )

        run_package_browser_smoke.assert_called_once_with(
            dist_dir=Path("/fake/package"),
            browser_argument=Path("/fake/browser"),
            no_sandbox=True,
            timeout=90.0,
            outer_document_restart=False,
            outer_document_restart_count=runner.RESTART_COUNT,
            release_wisp_endpoint=None,
            emit_package_observation=False,
        )

    def test_main_prints_false_only_observation_and_no_success_on_failure(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        result = _passing_result()
        with (
            mock.patch.object(
                runner,
                "run_package_outer_document_reload_stress",
                return_value=result,
            ) as run_stress,
            mock.patch.object(
                sys,
                "argv",
                ["reload-stress", "--dist-dir", "/fake/package"],
            ),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(0, runner.main())
        run_stress.assert_called_once_with(
            dist_dir=Path("/fake/package"),
            browser_argument=None,
            no_sandbox=False,
            timeout=120.0,
        )
        self.assertEqual("", stderr.getvalue())
        self.assertIn('"m9_gate_complete":false', stdout.getvalue())
        self.assertIn('"performance_gate":false', stdout.getvalue())
        self.assertIn(runner.PASS_MARKER, stdout.getvalue())

        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(
                runner,
                "run_package_outer_document_reload_stress",
                side_effect=M0Error("forced failure"),
            ),
            mock.patch.object(
                sys,
                "argv",
                ["reload-stress", "--dist-dir", "/fake/package"],
            ),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(1, runner.main())
        self.assertEqual("", stdout.getvalue())
        self.assertIn(runner.FAIL_MARKER, stderr.getvalue())
        self.assertNotIn(runner.PASS_MARKER, stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
