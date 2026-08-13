#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the bounded M9 fresh-run reliability runner."""

from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zlib


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
ARTIFACT_IDENTITY = {
    "artifact_delivery": continuous_flow.ARTIFACT_DELIVERY,
    "artifact_source_provenance": continuous_flow.ARTIFACT_SOURCE_PROVENANCE,
    "loader": {"bytes": 10, "sha256": "a" * 64},
    "module_name": continuous_flow.DEFAULT_MODULE_NAME,
    "wasm": {"bytes": 20, "sha256": "b" * 64},
}
NORMAL_ARTIFACT_IDENTITY = {
    "artifact_delivery": normal_lifecycle.ARTIFACT_DELIVERY,
    "artifact_source_provenance": normal_lifecycle.ARTIFACT_SOURCE_PROVENANCE,
    "loader": {"bytes": 10, "sha256": "d" * 64},
    "module_name": runner.DEFAULT_NORMAL_MODULE_NAME,
    "wasm": {"bytes": 20, "sha256": "e" * 64},
}


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + chunk_type
        + payload
        + struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF)
    )


def _solid_rgba_png(width: int, height: int, pixel: bytes) -> bytes:
    if len(pixel) != 4:
        raise ValueError("pixel must be one RGBA value")
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    rows = (b"\x00" + pixel * width) * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(rows, level=9))
        + _png_chunk(b"IEND", b"")
    )


def normal_execution(
    cycle: int = 1, *, artifact: object = NORMAL_ARTIFACT_IDENTITY
) -> runner.ChildExecution:
    summary = {
        "artifact": copy.deepcopy(artifact),
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
    cycle: int = 1,
    *,
    restart_versions: object = VERSIONS,
    flow_artifact: object = ARTIFACT_IDENTITY,
    restart_artifact: object = ARTIFACT_IDENTITY,
) -> runner.ChildExecution:
    flow = {
        "versions": VERSIONS,
        "artifact": copy.deepcopy(flow_artifact),
        "frameReports": [{"id": 1}],
    }
    restart = {
        "versions": restart_versions,
        "artifact": copy.deepcopy(restart_artifact),
        "frameReports": [{"id": 1}],
    }
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

    def _retained_screenshot_policy(
        self,
    ) -> tuple[dict[str, object], bytes, dict[str, object]]:
        contract, baseline_png, identity = (
            runner._snapshot_controlled_screenshot_policy()
        )
        return contract, baseline_png, identity

    def test_normal_child_requires_unique_markers_and_summary_schema(self) -> None:
        result = runner.validate_normal_lifecycle_execution(
            normal_execution(), expected_module_name=runner.DEFAULT_NORMAL_MODULE_NAME
        )
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
        self.assertEqual(NORMAL_ARTIFACT_IDENTITY, result["artifact"])

        duplicate = normal_execution()
        duplicate = runner.ChildExecution(
            **{
                **duplicate.__dict__,
                "stdout": duplicate.stdout + normal_lifecycle.PASS_MARKER + "\n",
            }
        )
        with self.assertRaisesRegex(M0Error, "exactly one"):
            runner.validate_normal_lifecycle_execution(
                duplicate, expected_module_name=runner.DEFAULT_NORMAL_MODULE_NAME
            )

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
            runner.validate_normal_lifecycle_execution(
                malformed, expected_module_name=runner.DEFAULT_NORMAL_MODULE_NAME
            )

        missing = normal_execution()
        missing = runner.ChildExecution(
            **{
                **missing.__dict__,
                "stdout": missing.stdout.replace(normal_lifecycle.NODE_PASS_MARKER, ""),
            }
        )
        with self.assertRaisesRegex(M0Error, "exactly one"):
            runner.validate_normal_lifecycle_execution(
                missing, expected_module_name=runner.DEFAULT_NORMAL_MODULE_NAME
            )

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
            runner.validate_normal_lifecycle_execution(
                invalid_json, expected_module_name=runner.DEFAULT_NORMAL_MODULE_NAME
            )

    def test_normal_child_requires_configured_exact_snapshot_identity(self) -> None:
        cases = (
            (
                "wrong module",
                lambda value: value.__setitem__("module_name", "other_module"),
            ),
            (
                "wrong delivery",
                lambda value: value.__setitem__("artifact_delivery", "live-output"),
            ),
            (
                "wrong provenance",
                lambda value: value.__setitem__(
                    "artifact_source_provenance", "verified"
                ),
            ),
            (
                "bool byte count",
                lambda value: value.__setitem__(
                    "loader", {"bytes": True, "sha256": "d" * 64}
                ),
            ),
            (
                "extra field",
                lambda value: value.__setitem__("extra", "field"),
            ),
        )
        for name, mutate in cases:
            with self.subTest(name=name):
                artifact = copy.deepcopy(NORMAL_ARTIFACT_IDENTITY)
                mutate(artifact)
                with self.assertRaisesRegex(M0Error, "invalid artifact identity"):
                    runner.validate_normal_lifecycle_execution(
                        normal_execution(artifact=artifact),
                        expected_module_name=runner.DEFAULT_NORMAL_MODULE_NAME,
                    )

        substituted = copy.deepcopy(NORMAL_ARTIFACT_IDENTITY)
        substituted["wasm"] = {"bytes": 21, "sha256": "f" * 64}
        with self.assertRaisesRegex(M0Error, "prior cycle"):
            runner.validate_normal_lifecycle_execution(
                normal_execution(artifact=substituted),
                expected_module_name=runner.DEFAULT_NORMAL_MODULE_NAME,
                expected_artifact_identity=NORMAL_ARTIFACT_IDENTITY,
            )

    def test_controlled_flow_delegates_to_existing_complete_validators(
        self,
    ) -> None:
        execution = flow_execution()
        screenshot_contract = {"contract": "value"}
        expected_artifact_identity = copy.deepcopy(ARTIFACT_IDENTITY)
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
            result = runner.validate_controlled_flow_execution(
                execution,
                expected_module_name=runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME,
                expected_artifact_identity=expected_artifact_identity,
            )

        self.assertEqual(1, result["cycle"])
        self.assertTrue(result["outerPageFreshRestart"])
        self.assertEqual("controlled flow", result["child"]["name"])
        self.assertEqual(
            {"flowPass": 1, "flowResult": 1, "restartResult": 1},
            result["child"]["terminalMarkers"],
        )
        self.assertEqual(VERSIONS, result["versions"])
        self.assertEqual(ARTIFACT_IDENTITY, result["artifact"])
        load_contract.assert_called_once_with()
        validate_flow.assert_called_once_with(
            {
                "versions": VERSIONS,
                "artifact": ARTIFACT_IDENTITY,
                "frameReports": [{"id": 1}],
            },
            expected_versions=VERSIONS,
            expected_artifact_identity=expected_artifact_identity,
            screenshot_contract=screenshot_contract,
        )
        validate_restart.assert_called_once_with(
            {
                "versions": VERSIONS,
                "artifact": ARTIFACT_IDENTITY,
                "frameReports": [{"id": 1}],
            },
            expected_versions=VERSIONS,
            expected_artifact_identity=expected_artifact_identity,
        )
        self.assertIs(
            expected_artifact_identity,
            validate_flow.call_args.kwargs["expected_artifact_identity"],
        )
        self.assertIs(
            expected_artifact_identity,
            validate_restart.call_args.kwargs["expected_artifact_identity"],
        )

    def test_controlled_flow_uses_one_retained_parent_visual_policy(self) -> None:
        contract, baseline_png, policy_identity = self._retained_screenshot_policy()
        expected_artifact_identity = copy.deepcopy(ARTIFACT_IDENTITY)
        with (
            mock.patch.object(
                runner.continuous_flow.controlled_https,
                "load_controlled_https_screenshot_contract",
            ) as load_contract,
            mock.patch.object(
                runner.continuous_flow,
                "validate_flow_result",
                return_value=baseline_png,
            ) as validate_flow,
            mock.patch.object(runner.continuous_flow, "validate_restart_result"),
        ):
            result = runner.validate_controlled_flow_execution(
                flow_execution(),
                expected_module_name=runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME,
                expected_artifact_identity=expected_artifact_identity,
                screenshot_contract=contract,
                screenshot_baseline_png=baseline_png,
                expected_screenshot_policy_identity=policy_identity,
            )

        load_contract.assert_not_called()
        self.assertEqual(policy_identity, result["screenshotPolicy"])
        self.assertIs(contract, validate_flow.call_args.kwargs["screenshot_contract"])
        self.assertEqual(
            expected_artifact_identity,
            validate_flow.call_args.kwargs["expected_artifact_identity"],
        )

    def test_screenshot_policy_identity_requires_exact_schema_and_snapshot(self) -> None:
        identity = runner.screenshot_policy_identity(b'{"contract":1}', b"baseline")
        self.assertEqual(
            {
                "contract": {
                    "bytes": len(b'{"contract":1}'),
                    "sha256": hashlib.sha256(b'{"contract":1}').hexdigest(),
                },
                "baseline": {
                    "bytes": len(b"baseline"),
                    "sha256": hashlib.sha256(b"baseline").hexdigest(),
                },
            },
            identity,
        )
        cases = (
            ("missing section", lambda value: value.pop("baseline")),
            ("extra section", lambda value: value.__setitem__("extra", {})),
            (
                "missing byte field",
                lambda value: value["contract"].pop("sha256"),
            ),
            (
                "boolean byte count",
                lambda value: value["baseline"].__setitem__("bytes", True),
            ),
            (
                "upper-case digest",
                lambda value: value["contract"].__setitem__("sha256", "A" * 64),
            ),
        )
        for name, mutate in cases:
            with self.subTest(name=name):
                malformed = copy.deepcopy(identity)
                mutate(malformed)
                with self.assertRaisesRegex(M0Error, "policy identity is invalid"):
                    runner.validate_screenshot_policy_identity(malformed)

        drifted = copy.deepcopy(identity)
        drifted["baseline"]["sha256"] = "f" * 64
        with self.assertRaisesRegex(M0Error, "retained M9 snapshot"):
            runner.validate_screenshot_policy_identity(
                drifted, expected_screenshot_policy_identity=identity
            )

    def test_snapshot_retained_policy_requires_exact_contract_schema(self) -> None:
        contract, baseline_png, identity = self._retained_screenshot_policy()
        canonical_contract = json.dumps(
            contract,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
        self.assertEqual(
            {
                "bytes": len(canonical_contract),
                "sha256": hashlib.sha256(canonical_contract).hexdigest(),
            },
            identity["contract"],
        )
        self.assertEqual(
            {
                "bytes": len(baseline_png),
                "sha256": hashlib.sha256(baseline_png).hexdigest(),
            },
            identity["baseline"],
        )
        cases = (
            ("missing field", lambda value: value.pop("comparison")),
            ("extra field", lambda value: value.__setitem__("extra", "field")),
            (
                "boolean schema version",
                lambda value: value.__setitem__("schema_version", True),
            ),
            (
                "boolean dimension",
                lambda value: value.__setitem__("width", True),
            ),
            (
                "bad baseline name",
                lambda value: value.__setitem__("baseline", "../baseline.png"),
            ),
        )
        for name, mutate in cases:
            with self.subTest(name=name):
                malformed = copy.deepcopy(contract)
                mutate(malformed)
                with (
                    mock.patch.object(
                        runner.continuous_flow.controlled_https,
                        "load_controlled_https_screenshot_contract",
                        return_value=malformed,
                    ),
                    mock.patch.object(
                        runner.continuous_flow,
                        "_snapshot_reviewed_screenshot_baseline",
                    ) as snapshot_baseline,
                    self.assertRaisesRegex(M0Error, "screenshot contract is invalid"),
                ):
                    runner._snapshot_controlled_screenshot_policy()
                snapshot_baseline.assert_not_called()

    def test_controlled_flow_rejects_disagreeing_restart_provenance(self) -> None:
        mismatched = dict(VERSIONS)
        mismatched["port"] = "other-port"
        with self.assertRaisesRegex(M0Error, "version identifiers disagree"):
            runner.validate_controlled_flow_execution(
                flow_execution(restart_versions=mismatched),
                expected_module_name=runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME,
            )

    def test_controlled_flow_rejects_restart_artifact_substitution_and_aliases(
        self,
    ) -> None:
        substituted = copy.deepcopy(ARTIFACT_IDENTITY)
        substituted["wasm"] = {"bytes": 21, "sha256": "c" * 64}
        with self.assertRaisesRegex(M0Error, "artifact identities disagree"):
            runner.validate_controlled_flow_execution(
                flow_execution(restart_artifact=substituted),
                expected_module_name=runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME,
            )
        bool_alias = copy.deepcopy(ARTIFACT_IDENTITY)
        bool_alias["loader"] = {"bytes": True, "sha256": "a" * 64}
        with self.assertRaisesRegex(M0Error, "invalid artifact identity"):
            runner.validate_controlled_flow_execution(
                flow_execution(flow_artifact=bool_alias),
                expected_module_name=runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME,
            )

    def test_controlled_flow_rejects_prior_cycle_artifact_drift(self) -> None:
        substituted = copy.deepcopy(ARTIFACT_IDENTITY)
        substituted["wasm"] = {"bytes": 21, "sha256": "c" * 64}
        with self.assertRaisesRegex(M0Error, "prior cycle"):
            runner.validate_controlled_flow_execution(
                flow_execution(
                    flow_artifact=substituted,
                    restart_artifact=substituted,
                ),
                expected_module_name=runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME,
                expected_artifact_identity=ARTIFACT_IDENTITY,
            )

    def test_controlled_flow_rejects_artifact_module_disagreeing_with_configuration(
        self,
    ) -> None:
        wrong_module = copy.deepcopy(ARTIFACT_IDENTITY)
        wrong_module["module_name"] = "different_controlled_flow_module"
        with self.assertRaisesRegex(
            M0Error, "disagrees with configured controlled-flow module"
        ):
            runner.validate_controlled_flow_execution(
                flow_execution(
                    flow_artifact=wrong_module,
                    restart_artifact=wrong_module,
                ),
                expected_module_name=runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME,
            )

    def test_run_aggregates_only_fresh_cycles_and_forwards_isolated_paths(self) -> None:
        temporary, out_dir = self._make_out_dir()
        self.addCleanup(temporary.cleanup)
        executions: list[tuple[str, int, list[str], float]] = []
        normal_validation_inputs: list[tuple[str, object]] = []
        controlled_flow_validation_inputs: list[
            tuple[str, object, object, object, object]
        ] = []

        def fake_run_child(
            name: str, cycle: int, command: list[str], timeout: float
        ) -> runner.ChildExecution:
            executions.append((name, cycle, command, timeout))
            return (
                normal_execution(cycle)
                if name == "normal lifecycle"
                else flow_execution(cycle)
            )

        def fake_normal(
            execution: runner.ChildExecution,
            *,
            expected_module_name: str,
            expected_artifact_identity: dict[str, object] | None,
        ) -> dict[str, object]:
            normal_validation_inputs.append(
                (expected_module_name, copy.deepcopy(expected_artifact_identity))
            )
            return {
                "cycle": execution.cycle,
                "artifact": copy.deepcopy(NORMAL_ARTIFACT_IDENTITY),
                "elapsedMs": float(execution.cycle),
            }

        def fake_flow(
            execution: runner.ChildExecution,
            *,
            expected_module_name: str,
            expected_artifact_identity: dict[str, object] | None,
            screenshot_contract: dict[str, object],
            screenshot_baseline_png: bytes,
            expected_screenshot_policy_identity: dict[str, object],
        ) -> dict[str, object]:
            self.assertEqual(
                runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME, expected_module_name
            )
            controlled_flow_validation_inputs.append(
                (
                    expected_module_name,
                    copy.deepcopy(expected_artifact_identity),
                    screenshot_contract,
                    screenshot_baseline_png,
                    copy.deepcopy(expected_screenshot_policy_identity),
                )
            )
            return {
                "cycle": execution.cycle,
                "artifact": copy.deepcopy(ARTIFACT_IDENTITY),
                "elapsedMs": 10.0 * execution.cycle,
                "screenshotPolicy": copy.deepcopy(expected_screenshot_policy_identity),
            }

        with (
            mock.patch.object(runner, "run_child", side_effect=fake_run_child),
            mock.patch.object(
                runner, "validate_normal_lifecycle_execution", side_effect=fake_normal
            ),
            mock.patch.object(
                runner, "validate_controlled_flow_execution", side_effect=fake_flow
            ),
            mock.patch.object(
                runner.continuous_flow.controlled_https,
                "load_controlled_https_screenshot_contract",
                wraps=(
                    runner.continuous_flow.controlled_https
                    .load_controlled_https_screenshot_contract
                ),
            ) as load_contract,
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
        self.assertEqual(
            NORMAL_ARTIFACT_IDENTITY, result["normalLifecycle"]["artifact"]
        )
        self.assertEqual(2, result["controlledFlow"]["completedCycles"])
        self.assertEqual(ARTIFACT_IDENTITY, result["controlledFlow"]["artifact"])
        self.assertEqual(
            continuous_flow.ARTIFACT_SOURCE_PROVENANCE,
            result["controlledFlow"]["artifact"]["artifact_source_provenance"],
        )
        self.assertEqual(
            "fresh-node-module-process", result["normalLifecycle"]["kind"]
        )
        self.assertEqual(
            "fresh-real-host-browser-profile-and-outer-restart",
            result["controlledFlow"]["kind"],
        )
        self.assertEqual(list(runner.LIMITATIONS), result["limitations"])
        self.assertEqual(5, len(executions))
        self.assertEqual(
            [
                (runner.DEFAULT_NORMAL_MODULE_NAME, None),
                (runner.DEFAULT_NORMAL_MODULE_NAME, NORMAL_ARTIFACT_IDENTITY),
                (runner.DEFAULT_NORMAL_MODULE_NAME, NORMAL_ARTIFACT_IDENTITY),
            ],
            normal_validation_inputs,
        )
        self.assertEqual(
            [
                (
                    runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME,
                    None,
                    controlled_flow_validation_inputs[0][2],
                    controlled_flow_validation_inputs[0][3],
                    controlled_flow_validation_inputs[0][4],
                ),
                (
                    runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME,
                    ARTIFACT_IDENTITY,
                    controlled_flow_validation_inputs[0][2],
                    controlled_flow_validation_inputs[0][3],
                    controlled_flow_validation_inputs[0][4],
                ),
            ],
            controlled_flow_validation_inputs,
        )
        self.assertIs(
            controlled_flow_validation_inputs[0][2],
            controlled_flow_validation_inputs[1][2],
        )
        self.assertIs(
            controlled_flow_validation_inputs[0][3],
            controlled_flow_validation_inputs[1][3],
        )
        self.assertEqual(
            controlled_flow_validation_inputs[0][4],
            result["controlledFlow"]["screenshotPolicy"],
        )
        load_contract.assert_called_once_with()
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

    def test_controlled_flow_artifact_drift_stops_before_later_cycles(self) -> None:
        temporary, out_dir = self._make_out_dir()
        self.addCleanup(temporary.cleanup)
        screenshot_contract, baseline_png, screenshot_policy = (
            self._retained_screenshot_policy()
        )
        substituted = copy.deepcopy(ARTIFACT_IDENTITY)
        substituted["wasm"] = {"bytes": 21, "sha256": "c" * 64}
        child_names: list[tuple[str, int]] = []

        def fake_run_child(
            name: str, cycle: int, command: list[str], timeout: float
        ) -> runner.ChildExecution:
            child_names.append((name, cycle))
            if name == "normal lifecycle":
                return normal_execution(cycle)
            return flow_execution(
                cycle,
                flow_artifact=(
                    ARTIFACT_IDENTITY if cycle == 1 else substituted
                ),
                restart_artifact=(
                    ARTIFACT_IDENTITY if cycle == 1 else substituted
                ),
            )

        with (
            mock.patch.object(runner, "run_child", side_effect=fake_run_child),
            mock.patch.object(
                runner,
                "_snapshot_controlled_screenshot_policy",
                return_value=(
                    screenshot_contract,
                    baseline_png,
                    screenshot_policy,
                ),
            ) as snapshot_policy,
            mock.patch.object(
                runner.continuous_flow,
                "validate_flow_result",
                return_value=baseline_png,
            ) as validate_flow,
            mock.patch.object(
                runner.continuous_flow, "validate_restart_result"
            ) as validate_restart,
        ):
            with self.assertRaisesRegex(M0Error, "prior cycle"):
                runner.run_reliability(
                    out_dir=out_dir,
                    normal_module_name=runner.DEFAULT_NORMAL_MODULE_NAME,
                    controlled_flow_module_name=(
                        runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME
                    ),
                    normal_lifecycle_iterations=1,
                    controlled_flow_iterations=3,
                    normal_timeout=7.0,
                    controlled_flow_timeout=11.0,
                    diagnostics_dir=out_dir / "diagnostics",
                    browser=None,
                    node=None,
                    relay_script=None,
                    no_sandbox=False,
                )

        self.assertEqual(
            [
                ("normal lifecycle", 1),
                ("controlled flow", 1),
                ("controlled flow", 2),
            ],
            child_names,
        )
        snapshot_policy.assert_called_once_with()
        validate_flow.assert_called_once()
        validate_restart.assert_called_once()

    def test_retained_visual_policy_rejects_cycle_two_drift_before_cycle_three(
        self,
    ) -> None:
        temporary, out_dir = self._make_out_dir()
        self.addCleanup(temporary.cleanup)
        screenshot_contract, baseline_png, screenshot_policy = (
            self._retained_screenshot_policy()
        )
        drifted_png = _solid_rgba_png(640, 480, bytes((255, 0, 0, 255)))
        child_names: list[tuple[str, int]] = []

        def fake_run_child(
            name: str, cycle: int, command: list[str], timeout: float
        ) -> runner.ChildExecution:
            del command, timeout
            child_names.append((name, cycle))
            if name == "normal lifecycle":
                return normal_execution(cycle)
            return flow_execution(cycle)

        # The second PNG represents a child that could have accepted a later
        # on-disk policy. M9 must still compare it to policy A, retained before
        # its first controlled child, and never reach cycle three.
        with (
            mock.patch.object(runner, "run_child", side_effect=fake_run_child),
            mock.patch.object(
                runner,
                "_snapshot_controlled_screenshot_policy",
                return_value=(
                    screenshot_contract,
                    baseline_png,
                    screenshot_policy,
                ),
            ) as snapshot_policy,
            mock.patch.object(
                runner.continuous_flow,
                "validate_flow_result",
                side_effect=(baseline_png, drifted_png),
            ) as validate_flow,
            mock.patch.object(
                runner.continuous_flow,
                "validate_restart_result",
            ) as validate_restart,
            mock.patch.object(
                runner.continuous_flow.controlled_https,
                "load_controlled_https_screenshot_contract",
            ) as load_contract,
        ):
            with self.assertRaisesRegex(M0Error, "retained M9 reviewed baseline"):
                runner.run_reliability(
                    out_dir=out_dir,
                    normal_module_name=runner.DEFAULT_NORMAL_MODULE_NAME,
                    controlled_flow_module_name=(
                        runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME
                    ),
                    normal_lifecycle_iterations=1,
                    controlled_flow_iterations=3,
                    normal_timeout=7.0,
                    controlled_flow_timeout=11.0,
                    diagnostics_dir=out_dir / "diagnostics",
                    browser=None,
                    node=None,
                    relay_script=None,
                    no_sandbox=False,
                )

        self.assertEqual(
            [
                ("normal lifecycle", 1),
                ("controlled flow", 1),
                ("controlled flow", 2),
            ],
            child_names,
        )
        snapshot_policy.assert_called_once_with()
        load_contract.assert_not_called()
        self.assertEqual(2, validate_flow.call_count)
        self.assertEqual(2, validate_restart.call_count)
        self.assertTrue(
            all(
                call.kwargs["screenshot_contract"] is screenshot_contract
                for call in validate_flow.call_args_list
            )
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

    def test_normal_artifact_drift_stops_before_later_cycles_or_controlled_flow(
        self,
    ) -> None:
        temporary, out_dir = self._make_out_dir()
        self.addCleanup(temporary.cleanup)
        substituted = copy.deepcopy(NORMAL_ARTIFACT_IDENTITY)
        substituted["loader"] = {"bytes": 11, "sha256": "f" * 64}
        child_names: list[str] = []

        def fake_run_child(
            name: str, cycle: int, command: list[str], timeout: float
        ) -> runner.ChildExecution:
            child_names.append(name)
            if name != "normal lifecycle":
                self.fail("controlled flow must not start after normal artifact drift")
            return normal_execution(
                cycle,
                artifact=(
                    NORMAL_ARTIFACT_IDENTITY if cycle == 1 else substituted
                ),
            )

        with mock.patch.object(runner, "run_child", side_effect=fake_run_child):
            with self.assertRaisesRegex(M0Error, "prior cycle"):
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
        self.assertEqual(["normal lifecycle", "normal lifecycle"], child_names)

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

    def test_run_child_preserves_normal_bounded_output(self) -> None:
        execution = runner.run_child(
            "normal lifecycle",
            1,
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "sys.stdout.buffer.write(b'normal output\\n'); "
                    "sys.stderr.buffer.write(b'diagnostic output\\n')"
                ),
            ],
            5.0,
        )
        self.assertEqual(0, execution.returncode)
        self.assertEqual("normal output\n", execution.stdout)
        self.assertEqual("diagnostic output\n", execution.stderr)

    def test_child_output_cap_uses_raw_shared_bytes_before_utf8_decoding(self) -> None:
        command = [
            sys.executable,
            "-c",
            (
                "import sys; "
                "sys.stdout.buffer.write(b'\\xc3\\xa9' * 2); "
                "sys.stdout.flush()"
            ),
        ]
        with (
            mock.patch.object(runner, "MAX_CHILD_OUTPUT_BYTES", 3),
            mock.patch.object(runner, "OUTPUT_READ_CHUNK_BYTES", 1),
            self.assertRaisesRegex(M0Error, "output exceeds the configured byte bound"),
        ):
            runner.run_child("capped output", 1, command, 5.0)

        shared_stream_command = [
            sys.executable,
            "-c",
            (
                "import sys; "
                "sys.stdout.buffer.write(b'ab'); "
                "sys.stderr.buffer.write(b'cd'); "
                "sys.stdout.flush(); sys.stderr.flush()"
            ),
        ]
        with (
            mock.patch.object(runner, "MAX_CHILD_OUTPUT_BYTES", 3),
            self.assertRaisesRegex(M0Error, "output exceeds the configured byte bound"),
        ):
            runner.run_child("shared capped output", 1, shared_stream_command, 5.0)

        # The newline used only to combine streams for marker parsing must
        # not consume the child-output byte budget.
        with mock.patch.object(runner, "MAX_CHILD_OUTPUT_BYTES", 3):
            self.assertEqual(
                "abc\n",
                runner._validated_child_output(
                    runner.ChildExecution(
                        name="exact cap",
                        cycle=1,
                        elapsed_ms=0.0,
                        returncode=0,
                        stdout="abc",
                        stderr="",
                    )
                ),
            )

    def test_cooperative_timeout_cleanup_signals_only_the_child_group(self) -> None:
        process = mock.Mock()
        process.pid = 1234
        # A reaped leader must not suppress a signal to remaining descendants
        # in its dedicated process group.
        process.poll.return_value = 0
        with (
            mock.patch.object(runner.os, "killpg") as killpg,
            mock.patch.object(
                runner, "_wait_for_process_and_output", side_effect=[False, True]
            ),
        ):
            forced_kill = runner._stop_child_cooperatively(process, ())

        self.assertTrue(forced_kill)
        self.assertEqual(
            [
                mock.call(1234, signal.SIGINT),
                mock.call(1234, signal.SIGKILL),
            ],
            killpg.call_args_list,
        )

        graceful_process = mock.Mock()
        graceful_process.pid = 1235
        graceful_process.poll.return_value = 0
        with (
            mock.patch.object(runner.os, "killpg") as graceful_killpg,
            mock.patch.object(runner, "_wait_for_process_and_output", return_value=True),
        ):
            self.assertFalse(runner._stop_child_cooperatively(graceful_process, ()))
        graceful_killpg.assert_called_once_with(1235, signal.SIGINT)

    def test_reader_fault_requires_group_absence_before_any_success_result(self) -> None:
        process = mock.Mock()
        process.pid = 1237
        process.poll.return_value = 0
        with (
            mock.patch.object(runner.os, "killpg") as killpg,
            mock.patch.object(
                runner, "_wait_for_process_and_output", side_effect=[False, True]
            ),
        ):
            self.assertTrue(runner._stop_child_cooperatively(process, ()))
        self.assertEqual(
            [
                mock.call(1237, signal.SIGINT),
                mock.call(1237, signal.SIGKILL),
            ],
            killpg.call_args_list,
        )

    def test_group_absence_probe_fails_closed_on_permission_error(self) -> None:
        process = mock.Mock()
        process.pid = 1238
        process.poll.return_value = 0
        with (
            mock.patch.object(runner.os, "killpg", side_effect=PermissionError("denied")),
            self.assertRaisesRegex(M0Error, "cannot verify child runner process-group"),
        ):
            runner._child_process_group_exists(process)

    def test_forced_child_group_kill_is_never_success_evidence(self) -> None:
        process = mock.Mock()
        process.pid = 1236
        process.stdout = io.BytesIO()
        process.stderr = io.BytesIO()
        # The loop observes a running process; the exception cleanup observes
        # the already stopped runner after the mocked forced cleanup.
        process.poll.side_effect = [None, 0]
        process.returncode = 0
        with (
            mock.patch.object(runner.subprocess, "Popen", return_value=process) as popen,
            mock.patch.object(
                runner, "_stop_child_cooperatively", return_value=True
            ) as stop_child,
            mock.patch.object(runner.time, "monotonic", side_effect=[0.0, 999.0]),
            self.assertRaisesRegex(M0Error, "force-killed only the child runner"),
        ):
            runner.run_child("normal lifecycle", 1, ["child"], 1.0)

        stop_child.assert_called_once_with(process, mock.ANY)
        popen.assert_called_once_with(
            ["child"],
            cwd=runner.REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )

    def test_partial_reader_start_is_retained_for_common_cleanup(self) -> None:
        capture = runner._CappedPipeCapture(32)
        process = mock.Mock()
        process.stdout = io.BytesIO()
        process.stderr = io.BytesIO()
        starts = 0
        original_start = runner.threading.Thread.start

        def start_then_fail_second(thread: object) -> None:
            nonlocal starts
            starts += 1
            if starts == 2:
                raise RuntimeError("second reader did not start")
            original_start(thread)

        with (
            mock.patch.object(
                runner.threading.Thread,
                "start",
                autospec=True,
                side_effect=start_then_fail_second,
            ),
            self.assertRaisesRegex(RuntimeError, "second reader"),
        ):
            capture.start(process)

        self.assertEqual(1, len(capture.started_threads))
        runner._join_output_threads(capture.started_threads)

    def test_primary_failure_survives_cleanup_failure(self) -> None:
        process = mock.Mock()
        process.stdout = io.BytesIO()
        process.stderr = io.BytesIO()
        process.poll.return_value = 0
        with (
            mock.patch.object(runner.subprocess, "Popen", return_value=process),
            mock.patch.object(
                runner._CappedPipeCapture,
                "start",
                side_effect=RuntimeError("primary reader-start failure"),
            ),
            mock.patch.object(
                runner,
                "_stop_child_cooperatively",
                side_effect=M0Error("cleanup failure"),
            ),
            self.assertRaisesRegex(RuntimeError, "primary reader-start failure"),
        ):
            runner.run_child("normal lifecycle", 1, ["child"], 1.0)

    def test_reaped_leader_pipe_holder_is_force_killed_before_return(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            child_pid_path = Path(temporary_directory) / "child.pid"
            # The shell exits immediately. Its background child ignores SIGINT
            # and keeps inherited stdout/stderr open until the runner sends
            # SIGKILL to the original process group.
            command = [
                "/bin/sh",
                "-c",
                (
                    "trap '' INT; (trap '' INT; sleep 60) & "
                    f"printf '%s' \"$!\" > {child_pid_path}"
                ),
            ]
            try:
                with (
                    mock.patch.object(runner, "FORCED_KILL_GRACE_SECONDS", 0.25),
                    mock.patch.object(runner, "COOPERATIVE_STOP_GRACE_SECONDS", 0.1),
                    mock.patch.object(runner, "OUTPUT_POLL_SECONDS", 0.01),
                    self.assertRaisesRegex(M0Error, "force-killed only the child runner"),
                ):
                    runner.run_child("pipe holder", 1, command, 1.0)
                child_pid = int(child_pid_path.read_text(encoding="utf-8"))
                for _ in range(50):
                    try:
                        os.kill(child_pid, 0)
                    except ProcessLookupError:
                        break
                    runner.time.sleep(0.01)
                else:
                    self.fail("force-killed pipe-holder descendant is still alive")
            finally:
                if child_pid_path.exists():
                    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
                    try:
                        os.kill(child_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_nonzero_reaped_leader_cannot_orphan_a_devnull_descendant(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            child_pid_path = Path(temporary_directory) / "child.pid"
            command = [
                "/bin/sh",
                "-c",
                (
                    "trap '' INT; (trap '' INT; sleep 60 </dev/null >/dev/null 2>&1) & "
                    f"printf '%s' \"$!\" > {child_pid_path}; exit 1"
                ),
            ]
            try:
                with (
                    mock.patch.object(runner, "FORCED_KILL_GRACE_SECONDS", 0.25),
                    mock.patch.object(runner, "COOPERATIVE_STOP_GRACE_SECONDS", 0.1),
                    mock.patch.object(runner, "OUTPUT_POLL_SECONDS", 0.01),
                    self.assertRaisesRegex(M0Error, "force-killed only the child runner"),
                ):
                    runner.run_child("nonzero descendant", 1, command, 1.0)
                child_pid = int(child_pid_path.read_text(encoding="utf-8"))
                for _ in range(50):
                    try:
                        os.kill(child_pid, 0)
                    except ProcessLookupError:
                        break
                    runner.time.sleep(0.01)
                else:
                    self.fail("force-killed devnull descendant is still alive")
            finally:
                if child_pid_path.exists():
                    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
                    try:
                        os.kill(child_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_timeout_and_iteration_inputs_are_bounded(self) -> None:
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
