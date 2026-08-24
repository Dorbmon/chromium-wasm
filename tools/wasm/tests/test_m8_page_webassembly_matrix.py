#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the closed M8 page-WebAssembly matrix wrapper."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m8_page_webassembly_matrix as matrix


def options(**overrides: object) -> matrix.MatrixOptions:
    values: dict[str, object] = {
        "build_profile": matrix.M8_CHROME_CODEGEN_EXPERIMENT_BUILD_PROFILE,
        "browser": Path("/usr/bin/google-chrome-stable"),
        "out_dir": Path("out/wasm-chrome-m8-codegen-experiment"),
        "module_name": "chrome_wasm",
        "diagnostics_dir": Path("out/wasm-chrome-m8-codegen-experiment/diagnostics"),
        "no_sandbox": True,
        "timeout": 120.0,
    }
    values.update(overrides)
    return matrix.MatrixOptions(**values)  # type: ignore[arg-type]


class M8PageWebAssemblyMatrixTest(unittest.TestCase):
    def test_command_is_profile_bound_and_uses_one_fixed_mode(self) -> None:
        command = matrix.runner_command(
            "--page-webassembly-memory", options()
        )

        self.assertEqual(
            command,
            [
                sys.executable,
                "-B",
                str(matrix.RUNNER_PATH),
                "--build-profile",
                "m8-codegen-experiment",
                "--browser",
                "/usr/bin/google-chrome-stable",
                "--out-dir",
                "out/wasm-chrome-m8-codegen-experiment",
                "--module-name",
                "chrome_wasm",
                "--diagnostics-dir",
                "out/wasm-chrome-m8-codegen-experiment/diagnostics",
                "--no-sandbox",
                "--timeout",
                "120.0",
                "--page-webassembly-memory",
            ],
        )

    def test_matrix_runs_each_closed_mode_once_and_stays_false_only(self) -> None:
        completed = subprocess.CompletedProcess(args=[], returncode=0)
        with mock.patch.object(
            matrix.subprocess,
            "run",
            side_effect=[completed] * len(matrix.PAGE_WEBASSEMBLY_MODE_FLAGS),
        ) as run:
            result = matrix.run_matrix(options())

        self.assertEqual(run.call_count, len(matrix.PAGE_WEBASSEMBLY_MODE_FLAGS))
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(
            [command[-1] for command in commands],
            list(matrix.PAGE_WEBASSEMBLY_MODE_FLAGS),
        )
        self.assertTrue(
            all(
                command[command.index("--build-profile") + 1]
                == matrix.M8_CHROME_CODEGEN_EXPERIMENT_BUILD_PROFILE
                for command in commands
            )
        )
        self.assertEqual(result["status"], "pass")
        self.assertIs(result["m8GateComplete"], False)
        self.assertEqual(
            result["pageWebAssemblyModes"],
            list(matrix.PAGE_WEBASSEMBLY_MODE_FLAGS),
        )

    def test_omitted_mode_is_rejected(self) -> None:
        with self.assertRaisesRegex(M0Error, "exactly 12 modes"):
            matrix.validate_page_webassembly_mode_flags(
                matrix.PAGE_WEBASSEMBLY_MODE_FLAGS[:-1]
            )

    def test_duplicate_mode_is_rejected(self) -> None:
        duplicated = (
            matrix.PAGE_WEBASSEMBLY_MODE_FLAGS[:-1]
            + (matrix.PAGE_WEBASSEMBLY_MODE_FLAGS[0],)
        )

        with self.assertRaisesRegex(M0Error, "duplicate mode"):
            matrix.validate_page_webassembly_mode_flags(duplicated)

    def test_non_codegen_profile_is_rejected_before_a_child_starts(self) -> None:
        with mock.patch.object(matrix.subprocess, "run") as run:
            with self.assertRaisesRegex(
                M0Error, "requires --build-profile m8-codegen-experiment"
            ):
                matrix.run_matrix(options(build_profile="m6"))

        run.assert_not_called()

    def test_mode_failure_stops_the_matrix_and_reports_the_mode(self) -> None:
        failed = subprocess.CompletedProcess(args=[], returncode=17)
        with mock.patch.object(
            matrix.subprocess, "run", return_value=failed
        ) as run:
            with self.assertRaisesRegex(
                M0Error,
                r"--page-webassembly: exit status 17",
            ):
                matrix.run_matrix(options())

        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
