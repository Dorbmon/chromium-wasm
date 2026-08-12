#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the bounded M9 fresh-run reliability runner."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m6_wasm_browser_continuous_flow_dom_smoke as continuous_flow
import run_m6_wasm_browser_normal_lifecycle_smoke as normal_lifecycle
import run_m9_wasm_browser_reliability_smoke as runner


VERSIONS = {
    "chromium": "chromium-revision",
    "v8": "v8-revision",
    "emscripten": "emscripten-revision",
    "port": "port-revision",
}


def normal_execution(cycle: int = 1) -> runner.ChildExecution:
    summary = {
        "artifact": "out/wasm-chrome-m6/chrome_wasm.js",
        "canvasCopies": 2,
        "focusReports": 1,
        "frameReports": 3,
        "readinessReports": 1,
        "startupMs": 12.5,
    }
    return runner.ChildExecution(
        name="normal lifecycle",
        cycle=cycle,
        elapsed_ms=17.25,
        returncode=0,
        stdout="\n".join(
            (
                normal_lifecycle.PASS_MARKER,
                runner.NORMAL_RESULT_PREFIX
                + json.dumps(summary, sort_keys=True, separators=(",", ":")),
                normal_lifecycle.NODE_PASS_MARKER,
            )
        )
        + "\n",
        stderr="",
    )


def flow_execution(
    cycle: int = 1, *, restart_versions: object = VERSIONS
) -> runner.ChildExecution:
    flow = {"versions": VERSIONS, "frameReports": [{"id": 1}]}
    restart = {"versions": restart_versions, "frameReports": [{"id": 1}]}
    return runner.ChildExecution(
        name="controlled flow",
        cycle=cycle,
        elapsed_ms=90.0,
        returncode=0,
        stdout="\n".join(
            (
                f"{continuous_flow.SENTINEL}:PASS",
                f"{continuous_flow.SENTINEL}:FLOW_RESULT "
                + json.dumps(flow, sort_keys=True, separators=(",", ":")),
                f"{continuous_flow.SENTINEL}:RESTART_RESULT "
                + json.dumps(restart, sort_keys=True, separators=(",", ":")),
            )
        )
        + "\n",
        stderr="",
    )


class M9WasmBrowserReliabilitySmokeTest(unittest.TestCase):
    def _make_out_dir(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        out_dir = Path(temporary.name) / "out"
        out_dir.mkdir()
        for module in (
            runner.DEFAULT_NORMAL_MODULE_NAME,
            runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME,
        ):
            (out_dir / f"{module}.js").write_text("loader", encoding="utf-8")
            (out_dir / f"{module}.wasm").write_bytes(b"wasm")
        return temporary, out_dir

    def test_normal_child_requires_unique_markers_and_summary_schema(self) -> None:
        result = runner.validate_normal_lifecycle_execution(normal_execution())
        self.assertEqual(1, result["cycle"])
        self.assertEqual(2, result["canvasCopies"])
        self.assertEqual(12.5, result["startupMs"])
        self.assertEqual(
            {
                "name": "normal lifecycle",
                "cycle": 1,
                "returncode": 0,
                "elapsedMs": 17.25,
                "stdoutBytes": len(normal_execution().stdout.encode("utf-8")),
                "stderrBytes": 0,
                "stdoutSha256": hashlib.sha256(
                    normal_execution().stdout.encode("utf-8")
                ).hexdigest(),
                "stderrSha256": hashlib.sha256(b"").hexdigest(),
                "terminalMarkers": {
                    "lifecyclePass": 1,
                    "nodePass": 1,
                    "summary": 1,
                },
            },
            result["child"],
        )
        self.assertEqual("out/wasm-chrome-m6/chrome_wasm.js", result["artifact"])

        duplicate = normal_execution()
        duplicate = runner.ChildExecution(
            **{
                **duplicate.__dict__,
                "stdout": duplicate.stdout + normal_lifecycle.PASS_MARKER + "\n",
            }
        )
        with self.assertRaisesRegex(M0Error, "exactly one"):
            runner.validate_normal_lifecycle_execution(duplicate)

        malformed = normal_execution()
        malformed = runner.ChildExecution(
            **{
                **malformed.__dict__,
                "stdout": malformed.stdout.replace(
                    '"canvasCopies":2', '"canvasCopies":0'
                ),
            }
        )
        with self.assertRaisesRegex(M0Error, "canvas copies"):
            runner.validate_normal_lifecycle_execution(malformed)

        missing = normal_execution()
        missing = runner.ChildExecution(
            **{
                **missing.__dict__,
                "stdout": missing.stdout.replace(normal_lifecycle.NODE_PASS_MARKER, ""),
            }
        )
        with self.assertRaisesRegex(M0Error, "exactly one"):
            runner.validate_normal_lifecycle_execution(missing)

        invalid_json = normal_execution()
        invalid_json = runner.ChildExecution(
            **{
                **invalid_json.__dict__,
                "stdout": invalid_json.stdout.replace(
                    '{"artifact"', '{not-json"artifact"'
                ),
            }
        )
        with self.assertRaisesRegex(M0Error, "malformed JSON"):
            runner.validate_normal_lifecycle_execution(invalid_json)

    def test_controlled_flow_delegates_to_existing_complete_validators(
        self,
    ) -> None:
        execution = flow_execution()
        screenshot_contract = {"contract": "value"}
        with (
            mock.patch.object(
                runner.continuous_flow.controlled_https,
                "load_controlled_https_screenshot_contract",
                return_value=screenshot_contract,
            ) as load_contract,
            mock.patch.object(
                runner.continuous_flow, "validate_flow_result"
            ) as validate_flow,
            mock.patch.object(
                runner.continuous_flow, "validate_restart_result"
            ) as validate_restart,
        ):
            result = runner.validate_controlled_flow_execution(execution)

        self.assertEqual(1, result["cycle"])
        self.assertTrue(result["outerPageFreshRestart"])
        self.assertEqual("controlled flow", result["child"]["name"])
        self.assertEqual(
            {"flowPass": 1, "flowResult": 1, "restartResult": 1},
            result["child"]["terminalMarkers"],
        )
        self.assertEqual(VERSIONS, result["versions"])
        load_contract.assert_called_once_with()
        validate_flow.assert_called_once_with(
            {"versions": VERSIONS, "frameReports": [{"id": 1}]},
            expected_versions=VERSIONS,
            screenshot_contract=screenshot_contract,
        )
        validate_restart.assert_called_once_with(
            {"versions": VERSIONS, "frameReports": [{"id": 1}]},
            expected_versions=VERSIONS,
        )

    def test_controlled_flow_rejects_disagreeing_restart_provenance(self) -> None:
        mismatched = dict(VERSIONS)
        mismatched["port"] = "other-port"
        with self.assertRaisesRegex(M0Error, "version identifiers disagree"):
            runner.validate_controlled_flow_execution(
                flow_execution(restart_versions=mismatched)
            )

    def test_run_aggregates_only_fresh_cycles_and_forwards_isolated_paths(self) -> None:
        temporary, out_dir = self._make_out_dir()
        self.addCleanup(temporary.cleanup)
        executions: list[tuple[str, int, list[str], float]] = []

        def fake_run_child(
            name: str, cycle: int, command: list[str], timeout: float
        ) -> runner.ChildExecution:
            executions.append((name, cycle, command, timeout))
            return (
                normal_execution(cycle)
                if name == "normal lifecycle"
                else flow_execution(cycle)
            )

        def fake_normal(execution: runner.ChildExecution) -> dict[str, object]:
            return {"cycle": execution.cycle, "elapsedMs": float(execution.cycle)}

        def fake_flow(execution: runner.ChildExecution) -> dict[str, object]:
            return {"cycle": execution.cycle, "elapsedMs": 10.0 * execution.cycle}

        with (
            mock.patch.object(runner, "run_child", side_effect=fake_run_child),
            mock.patch.object(
                runner, "validate_normal_lifecycle_execution", side_effect=fake_normal
            ),
            mock.patch.object(
                runner, "validate_controlled_flow_execution", side_effect=fake_flow
            ),
        ):
            result = runner.run_reliability(
                out_dir=out_dir,
                normal_module_name=runner.DEFAULT_NORMAL_MODULE_NAME,
                controlled_flow_module_name=runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME,
                normal_lifecycle_iterations=3,
                controlled_flow_iterations=2,
                normal_timeout=7.0,
                controlled_flow_timeout=11.0,
                diagnostics_dir=out_dir / "diagnostics",
                browser=Path("/browser"),
                node=Path("/node"),
                relay_script=Path("/relay.js"),
                no_sandbox=True,
            )

        self.assertEqual("pass", result["status"])
        self.assertEqual(3, result["normalLifecycle"]["completedCycles"])
        self.assertEqual(2, result["controlledFlow"]["completedCycles"])
        self.assertEqual(
            "fresh-node-module-process", result["normalLifecycle"]["kind"]
        )
        self.assertEqual(
            "fresh-real-host-browser-profile-and-outer-restart",
            result["controlledFlow"]["kind"],
        )
        self.assertEqual(list(runner.LIMITATIONS), result["limitations"])
        self.assertEqual(5, len(executions))
        normal_commands = [record[2] for record in executions[:3]]
        self.assertTrue(
            all(
                "--module-name" in command
                and runner.DEFAULT_NORMAL_MODULE_NAME in command
                for command in normal_commands
            )
        )
        flow_commands = [record[2] for record in executions[3:]]
        self.assertIn("--no-sandbox", flow_commands[0])
        self.assertIn(
            str(out_dir / "diagnostics" / "controlled-flow-01"), flow_commands[0]
        )
        self.assertIn(
            str(out_dir / "diagnostics" / "controlled-flow-02"), flow_commands[1]
        )

    def test_artifact_and_module_validation_fail_before_a_child_starts(self) -> None:
        temporary, out_dir = self._make_out_dir()
        self.addCleanup(temporary.cleanup)
        (out_dir / "chrome_wasm.wasm").unlink()
        with mock.patch.object(runner, "run_child") as run_child:
            with self.assertRaisesRegex(
                M0Error, "normal lifecycle artifact is missing"
            ):
                runner.run_reliability(
                    out_dir=out_dir,
                    normal_module_name="chrome_wasm",
                    controlled_flow_module_name=(
                        runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME
                    ),
                    normal_lifecycle_iterations=1,
                    controlled_flow_iterations=1,
                    normal_timeout=7.0,
                    controlled_flow_timeout=11.0,
                    diagnostics_dir=out_dir / "diagnostics",
                    browser=None,
                    node=None,
                    relay_script=None,
                    no_sandbox=False,
                )
        run_child.assert_not_called()

        with self.assertRaisesRegex(M0Error, "must contain only"):
            runner._require_artifacts(out_dir, "../chrome_wasm", "normal lifecycle")

    def test_child_failure_stops_before_later_cycles(self) -> None:
        temporary, out_dir = self._make_out_dir()
        self.addCleanup(temporary.cleanup)
        failed = runner.ChildExecution(
            name="normal lifecycle",
            cycle=1,
            elapsed_ms=1.0,
            returncode=1,
            stdout="",
            stderr="failure",
        )
        with mock.patch.object(runner, "run_child", return_value=failed) as run_child:
            with self.assertRaisesRegex(M0Error, "exited with status 1"):
                runner.run_reliability(
                    out_dir=out_dir,
                    normal_module_name=runner.DEFAULT_NORMAL_MODULE_NAME,
                    controlled_flow_module_name=(
                        runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME
                    ),
                    normal_lifecycle_iterations=3,
                    controlled_flow_iterations=1,
                    normal_timeout=7.0,
                    controlled_flow_timeout=11.0,
                    diagnostics_dir=out_dir / "diagnostics",
                    browser=None,
                    node=None,
                    relay_script=None,
                    no_sandbox=False,
                )
        run_child.assert_called_once()

    def test_timeout_and_iteration_inputs_are_bounded(self) -> None:
        with mock.patch.object(
            runner.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["child"], 1),
        ):
            with self.assertRaisesRegex(M0Error, "process timeout"):
                runner.run_child("normal lifecycle", 1, ["child"], 1.0)
        for value in ("0", str(runner.MAX_ITERATIONS + 1), "not-a-number"):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    runner.positive_iteration_count(value)
        for count in (0, runner.MAX_ITERATIONS + 1, True):
            with self.subTest(count=count):
                with self.assertRaisesRegex(M0Error, "normal lifecycle count"):
                    runner._require_iteration_count(count, "normal lifecycle count")
        for timeout in (0.0, float("nan"), float("inf")):
            with self.subTest(timeout=timeout):
                with self.assertRaisesRegex(M0Error, "normal lifecycle timeout"):
                    runner._require_timeout(timeout, "normal lifecycle timeout")

    def test_default_child_commands_propagate_exact_defaults(self) -> None:
        normal = runner.normal_lifecycle_command(
            out_dir=Path("/out"),
            module_name=runner.DEFAULT_NORMAL_MODULE_NAME,
            timeout=runner.DEFAULT_NORMAL_TIMEOUT,
        )
        self.assertEqual(sys.executable, normal[0])
        self.assertIn("run_m6_wasm_browser_normal_lifecycle_smoke.py", normal[1])
        self.assertEqual(
            [
                "--out-dir",
                "/out",
                "--module-name",
                runner.DEFAULT_NORMAL_MODULE_NAME,
                "--timeout",
                "30",
            ],
            normal[2:],
        )
        flow = runner.controlled_flow_command(
            out_dir=Path("/out"),
            module_name=runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME,
            timeout=runner.DEFAULT_CONTROLLED_FLOW_TIMEOUT,
            diagnostics_dir=Path("/diagnostics"),
            browser=None,
            node=None,
            relay_script=None,
            no_sandbox=False,
        )
        self.assertIn("run_m6_wasm_browser_continuous_flow_dom_smoke.py", flow[1])
        self.assertEqual(
            [
                "--out-dir",
                "/out",
                "--module-name",
                runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME,
                "--timeout",
                "120",
                "--diagnostics-dir",
                "/diagnostics",
            ],
            flow[2:],
        )

    def test_failure_diagnostic_is_small_and_does_not_copy_child_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            diagnostic = runner.write_failure_diagnostics(
                Path(temporary),
                error=M0Error("failure\nwith\tspace"),
                stage="run_fresh_cycles",
            )
            payload = json.loads(diagnostic.read_text(encoding="utf-8"))
        self.assertEqual("fail", payload["status"])
        self.assertEqual("failure with space", payload["failure"]["message"])
        self.assertEqual(list(runner.LIMITATIONS), payload["limitations"])
        self.assertNotIn("stdout", payload)
        self.assertNotIn("stderr", payload)


if __name__ == "__main__":
    unittest.main()
