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
HOST_RESOURCE_SNAPSHOTS = continuous_flow.snapshot_host_resources()
HOST_RESOURCE_IDENTITY = continuous_flow.host_resource_snapshot_identity(
    HOST_RESOURCE_SNAPSHOTS
)


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
                runner.NORMAL_RESULT_PREFIX
                + json.dumps(summary, sort_keys=True, separators=(",", ":")),
                normal_lifecycle.NODE_PASS_MARKER,
            )
        )
        + "\n",
        stderr="\n".join(
            (
                normal_lifecycle.READY_MARKER,
                normal_lifecycle.PASS_MARKER,
            )
        )
        + "\n",
    )


def valid_screenshot_comparison() -> dict[str, object]:
    """Return the successful M6 comparison for its retained test baseline."""

    return {
        "matches": True,
        "width": 640,
        "height": 480,
        "differentPixels": 0,
        "differentPixelRatio": 0.0,
        "maximumChannelDelta": 0,
        "meanChannelDelta": 0.0,
        "channelTolerance": 2,
        "maximumDifferentPixelRatio": 0.0025,
    }


def flow_execution(
    cycle: int = 1,
    *,
    flow_versions: object = VERSIONS,
    restart_versions: object = VERSIONS,
    flow_artifact: object = ARTIFACT_IDENTITY,
    restart_artifact: object = ARTIFACT_IDENTITY,
    flow_host_resources: object = HOST_RESOURCE_IDENTITY,
    restart_host_resources: object = HOST_RESOURCE_IDENTITY,
    screenshot_comparison: object | None = None,
    stderr: str = "",
) -> runner.ChildExecution:
    if screenshot_comparison is None:
        screenshot_comparison = valid_screenshot_comparison()
    flow = {
        "versions": flow_versions,
        "artifact": copy.deepcopy(flow_artifact),
        "hostResources": copy.deepcopy(flow_host_resources),
        "frameReports": [{"id": 1}],
    }
    restart = {
        "versions": restart_versions,
        "artifact": copy.deepcopy(restart_artifact),
        "hostResources": copy.deepcopy(restart_host_resources),
        "frameReports": [{"id": 1}],
    }
    return runner.ChildExecution(
        name="controlled flow",
        cycle=cycle,
        elapsed_ms=90.0,
        returncode=0,
        stdout="\n".join(
            (
                f"{continuous_flow.SENTINEL}:SCREENSHOT "
                + json.dumps(
                    screenshot_comparison, sort_keys=True, separators=(",", ":")
                ),
                f"{continuous_flow.SENTINEL}:FLOW_RESULT "
                + json.dumps(flow, sort_keys=True, separators=(",", ":")),
                f"{continuous_flow.SENTINEL}:RESTART_RESULT "
                + json.dumps(restart, sort_keys=True, separators=(",", ":")),
                f"{continuous_flow.SENTINEL}:PASS",
            )
        )
        + "\n",
        stderr=stderr,
    )


class M9WasmBrowserReliabilityVersionSnapshotTest(unittest.TestCase):
    def test_parent_version_snapshot_uses_one_manifest_and_head_observation(
        self,
    ) -> None:
        manifest = {"manifest": "test"}
        with (
            mock.patch.object(
                runner, "checked_output", return_value="p" * 40
            ) as checked,
            mock.patch.object(
                runner, "manifest_versions", return_value=copy.deepcopy(VERSIONS)
            ) as versions,
        ):
            snapshot = runner.snapshot_parent_run_version_identity(manifest)

        self.assertEqual(VERSIONS, snapshot)
        checked.assert_called_once_with(["git", "rev-parse", "HEAD"])
        versions.assert_called_once_with(manifest, "p" * 40)

    def test_parent_version_snapshot_rejects_malformed_identity(self) -> None:
        with (
            mock.patch.object(runner, "checked_output", return_value="p" * 40),
            mock.patch.object(
                runner,
                "manifest_versions",
                return_value={"chromium": "chromium-only"},
            ),
            self.assertRaisesRegex(M0Error, "parent run version snapshot is invalid"),
        ):
            runner.snapshot_parent_run_version_identity({"manifest": "test"})


class M9WasmBrowserReliabilitySmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        parent_snapshot = mock.patch.object(
            runner,
            "snapshot_parent_run_version_identity",
            return_value=copy.deepcopy(VERSIONS),
        )
        self.parent_snapshot = parent_snapshot.start()
        self.addCleanup(parent_snapshot.stop)

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

    def _preflight_artifact_identities(
        self, out_dir: Path
    ) -> tuple[dict[str, object], dict[str, object]]:
        return (
            runner._snapshot_normal_lifecycle_preflight_artifact_identity(
                out_dir, runner.DEFAULT_NORMAL_MODULE_NAME
            ),
            runner._snapshot_controlled_flow_preflight_artifact_identity(
                out_dir, runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME
            ),
        )

    @staticmethod
    def _replace_child_execution(
        execution: runner.ChildExecution,
        *,
        stdout: str | None = None,
        stderr: str | None = None,
    ) -> runner.ChildExecution:
        return runner.ChildExecution(
            name=execution.name,
            cycle=execution.cycle,
            elapsed_ms=execution.elapsed_ms,
            returncode=execution.returncode,
            stdout=execution.stdout if stdout is None else stdout,
            stderr=execution.stderr if stderr is None else stderr,
        )

    def _assert_controlled_flow_terminal_rejected(
        self, execution: runner.ChildExecution, error: str
    ) -> None:
        with (
            mock.patch.object(
                runner.continuous_flow, "validate_flow_result"
            ) as validate_flow,
            mock.patch.object(
                runner.continuous_flow, "validate_restart_result"
            ) as validate_restart,
            self.assertRaisesRegex(M0Error, error),
        ):
            runner.validate_controlled_flow_execution(
                execution,
                expected_module_name=runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME,
                expected_host_resource_identity=HOST_RESOURCE_IDENTITY,
            )
        validate_flow.assert_not_called()
        validate_restart.assert_not_called()

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
                "stderrBytes": len(normal_execution().stderr.encode("utf-8")),
                "stdoutSha256": hashlib.sha256(
                    normal_execution().stdout.encode("utf-8")
                ).hexdigest(),
                "stderrSha256": hashlib.sha256(
                    normal_execution().stderr.encode("utf-8")
                ).hexdigest(),
                "terminalMarkers": {
                    "nativeReady": 1,
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
                "stderr": duplicate.stderr + normal_lifecycle.PASS_MARKER + "\n",
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

        strict_json_cases = (
            (
                "duplicate summary key",
                '"canvasCopies":2',
                '"canvasCopies":0,"canvasCopies":2',
            ),
            (
                "nonstandard summary number",
                '"startupMs":12.5',
                '"startupMs":NaN',
            ),
        )
        for name, original, replacement in strict_json_cases:
            with self.subTest(case=name):
                malformed = normal_execution()
                malformed = self._replace_child_execution(
                    malformed,
                    stdout=malformed.stdout.replace(original, replacement, 1),
                )
                with self.assertRaisesRegex(M0Error, "malformed JSON"):
                    runner.validate_normal_lifecycle_execution(
                        malformed,
                        expected_module_name=runner.DEFAULT_NORMAL_MODULE_NAME,
                    )

    def test_normal_child_requires_real_split_stream_terminal_transcript(self) -> None:
        def summary_line(execution: runner.ChildExecution) -> str:
            return next(
                line
                for line in execution.stdout.splitlines()
                if line.startswith(runner.NORMAL_RESULT_PREFIX)
            )

        cases = (
            (
                "native ready on stdout",
                lambda execution: self._replace_child_execution(
                    execution,
                    stdout=normal_lifecycle.READY_MARKER + "\n" + execution.stdout,
                    stderr=execution.stderr.replace(
                        normal_lifecycle.READY_MARKER + "\n", "", 1
                    ),
                ),
                "native success terminal record on stdout",
            ),
            (
                "native pass on stdout",
                lambda execution: self._replace_child_execution(
                    execution,
                    stdout=normal_lifecycle.PASS_MARKER + "\n" + execution.stdout,
                    stderr=execution.stderr.replace(
                        normal_lifecycle.PASS_MARKER + "\n", "", 1
                    ),
                ),
                "native success terminal record on stdout",
            ),
            (
                "summary on stderr",
                lambda execution: self._replace_child_execution(
                    execution,
                    stdout="\n".join(
                        line
                        for line in execution.stdout.splitlines()
                        if not line.startswith(runner.NORMAL_RESULT_PREFIX)
                    )
                    + "\n",
                    stderr=execution.stderr + summary_line(execution) + "\n",
                ),
                "wrapper success terminal record on stderr",
            ),
            (
                "node pass on stderr",
                lambda execution: self._replace_child_execution(
                    execution,
                    stdout=execution.stdout.replace(
                        normal_lifecycle.NODE_PASS_MARKER + "\n", "", 1
                    ),
                    stderr=execution.stderr + normal_lifecycle.NODE_PASS_MARKER + "\n",
                ),
                "wrapper success terminal record on stderr",
            ),
            (
                "failure marker on stdout after valid transcript",
                lambda execution: self._replace_child_execution(
                    execution,
                    stdout=execution.stdout
                    + f"{normal_lifecycle.SENTINEL}:NODE_FAIL reason=forged\n",
                ),
                "child failure marker",
            ),
            (
                "failure marker on stderr after valid transcript",
                lambda execution: self._replace_child_execution(
                    execution,
                    stderr=execution.stderr
                    + f"{normal_lifecycle.SENTINEL}:NODE_FAIL reason=forged\n",
                ),
                "child failure marker",
            ),
            (
                "duplicate native pass on stderr",
                lambda execution: self._replace_child_execution(
                    execution,
                    stderr=execution.stderr + normal_lifecycle.PASS_MARKER + "\n",
                ),
                "exactly one stderr",
            ),
            (
                "native stderr markers out of order",
                lambda execution: self._replace_child_execution(
                    execution,
                    stderr="\n".join(
                        (
                            normal_lifecycle.PASS_MARKER,
                            normal_lifecycle.READY_MARKER,
                        )
                    )
                    + "\n",
                ),
                "native terminal records are unordered",
            ),
            (
                "duplicate node pass on stdout",
                lambda execution: self._replace_child_execution(
                    execution,
                    stdout=execution.stdout + normal_lifecycle.NODE_PASS_MARKER + "\n",
                ),
                "exactly one stdout",
            ),
            (
                "summary after node pass on stdout",
                lambda execution: self._replace_child_execution(
                    execution,
                    stdout="\n".join(
                        (
                            normal_lifecycle.NODE_PASS_MARKER,
                            summary_line(execution),
                        )
                    )
                    + "\n",
                ),
                "wrapper terminal records are unordered",
            ),
        )
        for name, mutate, error in cases:
            with self.subTest(case=name):
                with self.assertRaisesRegex(M0Error, error):
                    runner.validate_normal_lifecycle_execution(
                        mutate(normal_execution()),
                        expected_module_name=runner.DEFAULT_NORMAL_MODULE_NAME,
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

    def test_parent_preflight_artifact_identities_are_exact_and_type_safe(
        self,
    ) -> None:
        temporary, out_dir = self._make_out_dir()
        self.addCleanup(temporary.cleanup)
        normal_identity, controlled_flow_identity = (
            self._preflight_artifact_identities(out_dir)
        )
        normal_bytes = {
            "loader": (out_dir / "chrome_wasm.js").read_bytes(),
            "wasm": (out_dir / "chrome_wasm.wasm").read_bytes(),
        }
        controlled_flow_bytes = {
            "loader": (out_dir / "chrome_wasm_m6_https_test.js").read_bytes(),
            "wasm": (out_dir / "chrome_wasm_m6_https_test.wasm").read_bytes(),
        }
        self.assertEqual(
            {
                "artifact_delivery": normal_lifecycle.ARTIFACT_DELIVERY,
                "artifact_source_provenance": (
                    normal_lifecycle.ARTIFACT_SOURCE_PROVENANCE
                ),
                "loader": {
                    "bytes": len(normal_bytes["loader"]),
                    "sha256": hashlib.sha256(normal_bytes["loader"]).hexdigest(),
                },
                "module_name": runner.DEFAULT_NORMAL_MODULE_NAME,
                "wasm": {
                    "bytes": len(normal_bytes["wasm"]),
                    "sha256": hashlib.sha256(normal_bytes["wasm"]).hexdigest(),
                },
            },
            normal_identity,
        )
        self.assertEqual(
            {
                "artifact_delivery": continuous_flow.ARTIFACT_DELIVERY,
                "artifact_source_provenance": (
                    continuous_flow.ARTIFACT_SOURCE_PROVENANCE
                ),
                "loader": {
                    "bytes": len(controlled_flow_bytes["loader"]),
                    "sha256": hashlib.sha256(
                        controlled_flow_bytes["loader"]
                    ).hexdigest(),
                },
                "module_name": runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME,
                "wasm": {
                    "bytes": len(controlled_flow_bytes["wasm"]),
                    "sha256": hashlib.sha256(
                        controlled_flow_bytes["wasm"]
                    ).hexdigest(),
                },
            },
            controlled_flow_identity,
        )
        normal_lifecycle.validate_artifact_identity(
            normal_identity,
            expected_module_name=runner.DEFAULT_NORMAL_MODULE_NAME,
            expected_artifact_identity=normal_identity,
        )
        continuous_flow.validate_artifact_identity(
            controlled_flow_identity,
            expected_artifact_identity=controlled_flow_identity,
        )
        self.assertEqual(
            "unverified", normal_identity["artifact_source_provenance"]
        )
        self.assertEqual(
            "unverified", controlled_flow_identity["artifact_source_provenance"]
        )

        malformed_snapshots = (
            (
                "boolean module name",
                normal_lifecycle.ArtifactSnapshot(
                    module_name=True, loader=b"loader", wasm=b"wasm"
                ),
                "module name",
            ),
            (
                "unexpected module name",
                normal_lifecycle.ArtifactSnapshot(
                    module_name="other_module", loader=b"loader", wasm=b"wasm"
                ),
                "disagrees with configured module",
            ),
            (
                "mutable loader",
                normal_lifecycle.ArtifactSnapshot(
                    module_name=runner.DEFAULT_NORMAL_MODULE_NAME,
                    loader=bytearray(b"loader"),
                    wasm=b"wasm",
                ),
                "snapshot is invalid",
            ),
        )
        for name, malformed_snapshot, normal_error in malformed_snapshots:
            with self.subTest(name=name), mock.patch.object(
                runner.normal_lifecycle,
                "capture_artifact_snapshot",
                return_value=malformed_snapshot,
            ):
                with self.assertRaisesRegex(M0Error, normal_error):
                    runner._snapshot_normal_lifecycle_preflight_artifact_identity(
                        out_dir, runner.DEFAULT_NORMAL_MODULE_NAME
                    )
                with self.assertRaisesRegex(M0Error, "preflight artifact snapshot"):
                    runner._snapshot_controlled_flow_preflight_artifact_identity(
                        out_dir, runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME
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
                expected_host_resource_identity=HOST_RESOURCE_IDENTITY,
                expected_artifact_identity=expected_artifact_identity,
            )

        self.assertEqual(1, result["cycle"])
        self.assertTrue(result["outerPageFreshRestart"])
        self.assertEqual("controlled flow", result["child"]["name"])
        self.assertEqual(
            {
                "flowPass": 1,
                "flowResult": 1,
                "restartResult": 1,
                "screenshot": 1,
            },
            result["child"]["terminalMarkers"],
        )
        self.assertEqual(valid_screenshot_comparison(), result["screenshotComparison"])
        self.assertEqual(VERSIONS, result["versions"])
        self.assertEqual(ARTIFACT_IDENTITY, result["artifact"])
        load_contract.assert_called_once_with()
        validate_flow.assert_called_once_with(
            {
                "versions": VERSIONS,
                "artifact": ARTIFACT_IDENTITY,
                "hostResources": HOST_RESOURCE_IDENTITY,
                "frameReports": [{"id": 1}],
            },
            expected_versions=VERSIONS,
            expected_artifact_identity=expected_artifact_identity,
            expected_host_resource_identity=HOST_RESOURCE_IDENTITY,
            screenshot_contract=screenshot_contract,
        )
        validate_restart.assert_called_once_with(
            {
                "versions": VERSIONS,
                "artifact": ARTIFACT_IDENTITY,
                "hostResources": HOST_RESOURCE_IDENTITY,
                "frameReports": [{"id": 1}],
            },
            expected_versions=VERSIONS,
            expected_artifact_identity=expected_artifact_identity,
            expected_host_resource_identity=HOST_RESOURCE_IDENTITY,
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
                expected_host_resource_identity=HOST_RESOURCE_IDENTITY,
                expected_artifact_identity=expected_artifact_identity,
                screenshot_contract=contract,
                screenshot_baseline_png=baseline_png,
                expected_screenshot_policy_identity=policy_identity,
            )

        load_contract.assert_not_called()
        self.assertEqual(policy_identity, result["screenshotPolicy"])
        self.assertEqual(valid_screenshot_comparison(), result["screenshotComparison"])
        self.assertIs(contract, validate_flow.call_args.kwargs["screenshot_contract"])
        self.assertEqual(
            expected_artifact_identity,
            validate_flow.call_args.kwargs["expected_artifact_identity"],
        )

    def test_controlled_flow_binds_server_host_identity_for_both_phases(
        self,
    ) -> None:
        """M9 accepts only the raw identity M6 captured from its server bytes."""

        with (
            mock.patch.object(
                runner.continuous_flow.controlled_https,
                "load_controlled_https_screenshot_contract",
                return_value={"contract": "value"},
            ),
            mock.patch.object(runner.continuous_flow, "validate_flow_result") as flow,
            mock.patch.object(
                runner.continuous_flow, "validate_restart_result"
            ) as restart,
        ):
            result = runner.validate_controlled_flow_execution(
                flow_execution(),
                expected_module_name=runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME,
                expected_host_resource_identity=HOST_RESOURCE_IDENTITY,
            )

        self.assertEqual(HOST_RESOURCE_IDENTITY, result["hostResources"])
        self.assertEqual(
            HOST_RESOURCE_IDENTITY,
            flow.call_args.kwargs["expected_host_resource_identity"],
        )
        self.assertEqual(
            HOST_RESOURCE_IDENTITY,
            restart.call_args.kwargs["expected_host_resource_identity"],
        )

        cases = (
            (
                "flow",
                lambda value: value.pop("host_html"),
            ),
            (
                "flow",
                lambda value: value.__setitem__("extra", {}),
            ),
            (
                "flow",
                lambda value: value["host_js"].__setitem__("bytes", True),
            ),
            (
                "flow",
                lambda value: value["host_js"].__setitem__("sha256", "0" * 64),
            ),
            (
                "restart",
                lambda value: value.pop("pointer_input_js"),
            ),
            (
                "restart",
                lambda value: value.__setitem__("extra", {}),
            ),
            (
                "restart",
                lambda value: value["host_js"].__setitem__("bytes", True),
            ),
            (
                "restart",
                lambda value: value["host_js"].__setitem__("sha256", "0" * 64),
            ),
        )
        for phase, mutate in cases:
            with self.subTest(phase=phase, mutation=mutate):
                flow_resources = copy.deepcopy(HOST_RESOURCE_IDENTITY)
                restart_resources = copy.deepcopy(HOST_RESOURCE_IDENTITY)
                mutate(
                    flow_resources if phase == "flow" else restart_resources
                )
                with self.assertRaisesRegex(
                    M0Error,
                    rf"controlled-flow {phase} host resource identity disagrees",
                ):
                    runner.validate_controlled_flow_execution(
                        flow_execution(
                            flow_host_resources=flow_resources,
                            restart_host_resources=restart_resources,
                        ),
                        expected_module_name=(
                            runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME
                        ),
                        expected_host_resource_identity=HOST_RESOURCE_IDENTITY,
                    )

    def test_controlled_flow_requires_one_ordered_stdout_terminal_transcript(
        self,
    ) -> None:
        execution = flow_execution()
        screenshot, flow_result, restart_result, passed = execution.stdout.splitlines()
        records = (screenshot, flow_result, restart_result, passed)
        prefixes = (
            "SCREENSHOT",
            "FLOW_RESULT",
            "RESTART_RESULT",
            "PASS",
        )
        for name, record, prefix in zip(
            ("screenshot", "flow", "restart", "pass"), records, prefixes
        ):
            with self.subTest(case=f"missing {name}"):
                stdout = "\n".join(item for item in records if item != record) + "\n"
                self._assert_controlled_flow_terminal_rejected(
                    self._replace_child_execution(execution, stdout=stdout),
                    rf"exactly one stdout .*{prefix}",
                )
            with self.subTest(case=f"duplicate {name}"):
                stdout = "\n".join((*records, record)) + "\n"
                self._assert_controlled_flow_terminal_rejected(
                    self._replace_child_execution(execution, stdout=stdout),
                    rf"exactly one stdout .*{prefix}",
                )
            with self.subTest(case=f"{name} on stderr"):
                self._assert_controlled_flow_terminal_rejected(
                    self._replace_child_execution(execution, stderr=record + "\n"),
                    "success terminal record on stderr",
                )

        reordered = "\n".join((flow_result, screenshot, restart_result, passed)) + "\n"
        self._assert_controlled_flow_terminal_rejected(
            self._replace_child_execution(execution, stdout=reordered),
            "terminal records are missing or unordered",
        )

    def test_controlled_flow_rejects_failure_markers_in_combined_output(self) -> None:
        execution = flow_execution()
        for marker in runner._CONTROLLED_FLOW_FAILURE_MARKERS:
            for stream in ("stdout", "stderr"):
                with self.subTest(marker=marker, stream=stream):
                    failure = marker + " reason=synthetic\n"
                    if stream == "stdout":
                        rejected = self._replace_child_execution(
                            execution, stdout=execution.stdout + failure
                        )
                    else:
                        rejected = self._replace_child_execution(
                            execution, stderr=failure
                        )
                    self._assert_controlled_flow_terminal_rejected(
                        rejected, "child failure marker"
                    )

    def test_controlled_flow_rejects_malformed_terminal_json_records(self) -> None:
        execution = flow_execution()
        screenshot, flow_result, restart_result, passed = execution.stdout.splitlines()
        cases = (
            (
                "malformed screenshot",
                (
                    runner.CONTROLLED_FLOW_SCREENSHOT_PREFIX + "{not-json",
                    flow_result,
                    restart_result,
                    passed,
                ),
                "malformed JSON",
            ),
            (
                "duplicate screenshot key",
                (
                    runner.CONTROLLED_FLOW_SCREENSHOT_PREFIX
                    + '{"matches":true,"matches":true}',
                    flow_result,
                    restart_result,
                    passed,
                ),
                "malformed JSON",
            ),
            (
                "nonstandard screenshot number",
                (
                    runner.CONTROLLED_FLOW_SCREENSHOT_PREFIX + '{"matches":NaN}',
                    flow_result,
                    restart_result,
                    passed,
                ),
                "malformed JSON",
            ),
            (
                "malformed flow result",
                (
                    screenshot,
                    runner.CONTROLLED_FLOW_RESULT_PREFIX + "{not-json",
                    restart_result,
                    passed,
                ),
                "malformed JSON",
            ),
            (
                "malformed restart result",
                (
                    screenshot,
                    flow_result,
                    runner.CONTROLLED_FLOW_RESTART_RESULT_PREFIX + "{not-json",
                    passed,
                ),
                "malformed JSON",
            ),
        )
        for name, records, error in cases:
            with self.subTest(case=name):
                self._assert_controlled_flow_terminal_rejected(
                    self._replace_child_execution(
                        execution, stdout="\n".join(records) + "\n"
                    ),
                    error,
                )

    def test_controlled_flow_rejects_invalid_screenshot_comparison_schema_and_types(
        self,
    ) -> None:
        cases = (
            ("missing metric", lambda value: value.pop("meanChannelDelta")),
            ("extra metric", lambda value: value.__setitem__("extra", 1)),
            ("integer matches alias", lambda value: value.__setitem__("matches", 1)),
            ("boolean width alias", lambda value: value.__setitem__("width", True)),
            (
                "boolean different-pixel count alias",
                lambda value: value.__setitem__("differentPixels", False),
            ),
            (
                "integer different-pixel ratio alias",
                lambda value: value.__setitem__("differentPixelRatio", 0),
            ),
            (
                "boolean maximum delta alias",
                lambda value: value.__setitem__("maximumChannelDelta", True),
            ),
            (
                "integer mean delta alias",
                lambda value: value.__setitem__("meanChannelDelta", 0),
            ),
            (
                "boolean channel tolerance alias",
                lambda value: value.__setitem__("channelTolerance", False),
            ),
            (
                "integer maximum ratio alias",
                lambda value: value.__setitem__("maximumDifferentPixelRatio", 0),
            ),
            (
                "inconsistent pixel metrics",
                lambda value: value.__setitem__("differentPixels", 1),
            ),
        )
        for name, mutate in cases:
            with self.subTest(case=name):
                comparison = valid_screenshot_comparison()
                mutate(comparison)
                self._assert_controlled_flow_terminal_rejected(
                    flow_execution(screenshot_comparison=comparison),
                    "screenshot comparison is invalid",
                )

    def test_controlled_flow_requires_metrics_to_match_parent_recomputation(
        self,
    ) -> None:
        contract, baseline_png, policy_identity = self._retained_screenshot_policy()
        child_metrics = valid_screenshot_comparison()
        child_metrics["maximumChannelDelta"] = 1
        with (
            mock.patch.object(
                runner.continuous_flow,
                "validate_flow_result",
                return_value=baseline_png,
            ),
            mock.patch.object(runner.continuous_flow, "validate_restart_result"),
            self.assertRaisesRegex(
                M0Error,
                "screenshot comparison disagrees with the retained M9 parent "
                "recomputation",
            ),
        ):
            runner.validate_controlled_flow_execution(
                flow_execution(screenshot_comparison=child_metrics),
                expected_module_name=runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME,
                expected_host_resource_identity=HOST_RESOURCE_IDENTITY,
                expected_artifact_identity=ARTIFACT_IDENTITY,
                screenshot_contract=contract,
                screenshot_baseline_png=baseline_png,
                expected_screenshot_policy_identity=policy_identity,
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

    def test_controlled_flow_host_fixture_identity_is_exact_and_unverified(self) -> None:
        snapshots = {
            name: f"{name} fixture bytes".encode("ascii")
            for name in continuous_flow.HOST_RESOURCE_FILES
        }
        identity = runner.controlled_flow_host_fixture_identity(snapshots)
        self.assertEqual(
            runner.CONTROLLED_FLOW_HOST_FIXTURE_DELIVERY, identity["delivery"]
        )
        self.assertEqual("unverified", identity["source_provenance"])
        self.assertEqual(
            hashlib.sha256(snapshots["host_js"]).hexdigest(),
            identity["host_js"]["sha256"],
        )
        cases = (
            ("missing fixture", lambda value: value.pop("host_html")),
            ("extra fixture", lambda value: value.__setitem__("extra", {})),
            (
                "verified provenance",
                lambda value: value.__setitem__("source_provenance", "verified"),
            ),
            (
                "boolean byte count",
                lambda value: value["host_js"].__setitem__("bytes", True),
            ),
        )
        for name, mutate in cases:
            with self.subTest(name=name):
                malformed = copy.deepcopy(identity)
                mutate(malformed)
                with self.assertRaisesRegex(
                    M0Error, "host fixture identity is invalid"
                ):
                    runner.validate_controlled_flow_host_fixture_identity(malformed)

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
                expected_host_resource_identity=HOST_RESOURCE_IDENTITY,
            )

    def test_controlled_flow_rejects_matching_child_versions_outside_parent_snapshot(
        self,
    ) -> None:
        drifted = dict(VERSIONS)
        drifted["port"] = "later-port-revision"
        with (
            mock.patch.object(
                runner.continuous_flow, "validate_flow_result"
            ) as validate_flow,
            mock.patch.object(
                runner.continuous_flow, "validate_restart_result"
            ) as validate_restart,
            self.assertRaisesRegex(
                M0Error, "frozen M9 parent run version snapshot"
            ),
        ):
            runner.validate_controlled_flow_execution(
                flow_execution(
                    flow_versions=drifted,
                    restart_versions=drifted,
                ),
                expected_module_name=runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME,
                expected_host_resource_identity=HOST_RESOURCE_IDENTITY,
                expected_run_version_snapshot=VERSIONS,
            )
        validate_flow.assert_not_called()
        validate_restart.assert_not_called()

    def test_controlled_flow_rejects_restart_artifact_substitution_and_aliases(
        self,
    ) -> None:
        substituted = copy.deepcopy(ARTIFACT_IDENTITY)
        substituted["wasm"] = {"bytes": 21, "sha256": "c" * 64}
        with self.assertRaisesRegex(M0Error, "artifact identities disagree"):
            runner.validate_controlled_flow_execution(
                flow_execution(restart_artifact=substituted),
                expected_module_name=runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME,
                expected_host_resource_identity=HOST_RESOURCE_IDENTITY,
            )
        bool_alias = copy.deepcopy(ARTIFACT_IDENTITY)
        bool_alias["loader"] = {"bytes": True, "sha256": "a" * 64}
        with self.assertRaisesRegex(M0Error, "invalid artifact identity"):
            runner.validate_controlled_flow_execution(
                flow_execution(flow_artifact=bool_alias),
                expected_module_name=runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME,
                expected_host_resource_identity=HOST_RESOURCE_IDENTITY,
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
                expected_host_resource_identity=HOST_RESOURCE_IDENTITY,
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
                expected_host_resource_identity=HOST_RESOURCE_IDENTITY,
            )

    def test_run_aggregates_only_fresh_cycles_and_forwards_isolated_paths(self) -> None:
        temporary, out_dir = self._make_out_dir()
        self.addCleanup(temporary.cleanup)
        normal_preflight = runner._snapshot_normal_lifecycle_preflight_artifact_identity(
            out_dir, runner.DEFAULT_NORMAL_MODULE_NAME
        )
        controlled_flow_preflight = (
            runner._snapshot_controlled_flow_preflight_artifact_identity(
                out_dir, runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME
            )
        )
        executions: list[tuple[str, int, list[str], float]] = []
        normal_validation_inputs: list[tuple[str, object, str]] = []
        controlled_flow_validation_inputs: list[
            tuple[str, object, str, object, object, object, object, object]
        ] = []
        controlled_flow_version_snapshots: list[dict[str, str] | None] = []

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
            expected_artifact_identity_context: str,
        ) -> dict[str, object]:
            normal_validation_inputs.append(
                (
                    expected_module_name,
                    copy.deepcopy(expected_artifact_identity),
                    expected_artifact_identity_context,
                )
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
            expected_host_resource_identity: dict[str, object],
            expected_artifact_identity: dict[str, object] | None,
            expected_artifact_identity_context: str,
            expected_run_version_snapshot: dict[str, str] | None,
            screenshot_contract: dict[str, object],
            screenshot_baseline_png: bytes,
            expected_screenshot_policy_identity: dict[str, object],
        ) -> dict[str, object]:
            self.assertEqual(
                runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME, expected_module_name
            )
            controlled_flow_version_snapshots.append(expected_run_version_snapshot)
            controlled_flow_validation_inputs.append(
                (
                    expected_module_name,
                    copy.deepcopy(expected_artifact_identity),
                    expected_artifact_identity_context,
                    copy.deepcopy(expected_run_version_snapshot),
                    copy.deepcopy(expected_host_resource_identity),
                    screenshot_contract,
                    screenshot_baseline_png,
                    copy.deepcopy(expected_screenshot_policy_identity),
                )
            )
            return {
                "cycle": execution.cycle,
                "artifact": copy.deepcopy(ARTIFACT_IDENTITY),
                "hostResources": copy.deepcopy(expected_host_resource_identity),
                "versions": copy.deepcopy(expected_run_version_snapshot),
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
            normal_preflight, result["normalLifecycle"]["artifact"]
        )
        self.assertEqual(2, result["controlledFlow"]["completedCycles"])
        self.assertEqual(
            controlled_flow_preflight, result["controlledFlow"]["artifact"]
        )
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
        self.assertEqual(
            VERSIONS, result["controlledFlow"]["runVersionSnapshot"]
        )
        self.assertNotIn(
            "source_provenance", result["controlledFlow"]["runVersionSnapshot"]
        )
        host_fixture = runner.validate_controlled_flow_host_fixture_identity(
            result["controlledFlow"]["hostFixture"]
        )
        self.assertEqual(
            runner.CONTROLLED_FLOW_HOST_FIXTURE_DELIVERY,
            host_fixture["delivery"],
        )
        self.assertEqual(list(runner.LIMITATIONS), result["limitations"])
        self.assertEqual(5, len(executions))
        self.assertEqual(
            [
                (
                    runner.DEFAULT_NORMAL_MODULE_NAME,
                    normal_preflight,
                    "the M9 parent preflight snapshot",
                ),
                (
                    runner.DEFAULT_NORMAL_MODULE_NAME,
                    normal_preflight,
                    "the M9 parent preflight snapshot",
                ),
                (
                    runner.DEFAULT_NORMAL_MODULE_NAME,
                    normal_preflight,
                    "the M9 parent preflight snapshot",
                ),
            ],
            normal_validation_inputs,
        )
        self.assertEqual(
            [
                (
                    runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME,
                    controlled_flow_preflight,
                    "the M9 parent preflight snapshot",
                    VERSIONS,
                    controlled_flow_validation_inputs[0][4],
                    controlled_flow_validation_inputs[0][5],
                    controlled_flow_validation_inputs[0][6],
                    controlled_flow_validation_inputs[0][7],
                ),
                (
                    runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME,
                    controlled_flow_preflight,
                    "the M9 parent preflight snapshot",
                    VERSIONS,
                    controlled_flow_validation_inputs[0][4],
                    controlled_flow_validation_inputs[0][5],
                    controlled_flow_validation_inputs[0][6],
                    controlled_flow_validation_inputs[0][7],
                ),
            ],
            controlled_flow_validation_inputs,
        )
        self.assertIs(
            controlled_flow_validation_inputs[0][5],
            controlled_flow_validation_inputs[1][5],
        )
        self.assertIs(
            controlled_flow_validation_inputs[0][6],
            controlled_flow_validation_inputs[1][6],
        )
        self.assertEqual(
            controlled_flow_validation_inputs[0][7],
            result["controlledFlow"]["screenshotPolicy"],
        )
        self.assertEqual(
            {
                name: host_fixture[name]
                for name in continuous_flow.HOST_RESOURCE_FILES
            },
            controlled_flow_validation_inputs[0][4],
        )
        self.assertEqual([VERSIONS, VERSIONS], controlled_flow_version_snapshots)
        self.assertIsNot(
            controlled_flow_version_snapshots[0],
            controlled_flow_version_snapshots[1],
        )
        self.parent_snapshot.assert_called_once()
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
        fixture_dirs = [
            Path(command[command.index("--host-dir") + 1])
            for command in flow_commands
        ]
        self.assertEqual(1, len(set(fixture_dirs)))
        self.assertFalse(fixture_dirs[0].exists())

    def test_controlled_flow_uses_one_private_host_fixture_after_source_mutation(
        self,
    ) -> None:
        temporary, out_dir = self._make_out_dir()
        self.addCleanup(temporary.cleanup)
        normal_preflight, controlled_preflight = self._preflight_artifact_identities(
            out_dir
        )
        source_temporary = tempfile.TemporaryDirectory()
        self.addCleanup(source_temporary.cleanup)
        source_dir = Path(source_temporary.name)
        original = {
            name: f"original {name}".encode("ascii")
            for name in continuous_flow.HOST_RESOURCE_FILES
        }
        for name, filename in continuous_flow.HOST_RESOURCE_FILES.items():
            (source_dir / filename).write_bytes(original[name])
        original_snapshot_host_resources = continuous_flow.snapshot_host_resources
        expected_identity = runner.controlled_flow_host_fixture_identity(original)
        expected_host_resources = continuous_flow.host_resource_snapshot_identity(
            original
        )
        fixture_dirs: list[Path] = []
        observed_host_resources: list[dict[str, bytes]] = []

        def snapshot_source_host_resources() -> dict[str, bytes]:
            return original_snapshot_host_resources(source_dir)

        def fake_run_child(
            name: str, cycle: int, command: list[str], timeout: float
        ) -> runner.ChildExecution:
            del timeout
            if name == "normal lifecycle":
                return normal_execution(cycle, artifact=normal_preflight)
            fixture_dir = Path(command[command.index("--host-dir") + 1])
            fixture_dirs.append(fixture_dir)
            observed_host_resources.append(
                {
                    name: (fixture_dir / filename).read_bytes()
                    for name, filename in continuous_flow.HOST_RESOURCE_FILES.items()
                }
            )
            if cycle == 1:
                (
                    source_dir / continuous_flow.HOST_RESOURCE_FILES["host_js"]
                ).write_bytes(b"mutated source host bridge")
            return flow_execution(
                cycle,
                flow_artifact=controlled_preflight,
                restart_artifact=controlled_preflight,
                flow_host_resources=expected_host_resources,
                restart_host_resources=expected_host_resources,
            )

        with (
            mock.patch.object(
                runner.continuous_flow,
                "snapshot_host_resources",
                side_effect=snapshot_source_host_resources,
            ) as snapshot_host_resources,
            mock.patch.object(runner, "run_child", side_effect=fake_run_child),
            mock.patch.object(
                runner.continuous_flow,
                "validate_flow_result",
                return_value=self._retained_screenshot_policy()[1],
            ),
            mock.patch.object(runner.continuous_flow, "validate_restart_result"),
        ):
            result = runner.run_reliability(
                out_dir=out_dir,
                normal_module_name=runner.DEFAULT_NORMAL_MODULE_NAME,
                controlled_flow_module_name=runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME,
                normal_lifecycle_iterations=1,
                controlled_flow_iterations=2,
                normal_timeout=7.0,
                controlled_flow_timeout=11.0,
                diagnostics_dir=out_dir / "diagnostics",
                browser=None,
                node=None,
                relay_script=None,
                no_sandbox=False,
            )

        snapshot_host_resources.assert_called_once_with()
        self.assertEqual(
            b"mutated source host bridge",
            (source_dir / continuous_flow.HOST_RESOURCE_FILES["host_js"]).read_bytes(),
        )
        self.assertEqual([original, original], observed_host_resources)
        self.assertEqual(1, len(set(fixture_dirs)))
        self.assertFalse(fixture_dirs[0].exists())
        self.assertEqual(expected_identity, result["controlledFlow"]["hostFixture"])

    def test_m9_rejects_private_fixture_mutation_before_m6_server_capture(
        self,
    ) -> None:
        """A child server attesting B cannot pass against M9's frozen A bytes."""

        temporary, out_dir = self._make_out_dir()
        self.addCleanup(temporary.cleanup)
        normal_preflight, controlled_preflight = self._preflight_artifact_identities(
            out_dir
        )
        source_temporary = tempfile.TemporaryDirectory()
        self.addCleanup(source_temporary.cleanup)
        source_dir = Path(source_temporary.name)
        source_snapshots = {
            name: f"source fixture {name}".encode("ascii")
            for name in continuous_flow.HOST_RESOURCE_FILES
        }
        for name, filename in continuous_flow.HOST_RESOURCE_FILES.items():
            (source_dir / filename).write_bytes(source_snapshots[name])

        actual_snapshot_host_resources = continuous_flow.snapshot_host_resources
        child_names: list[tuple[str, int]] = []
        fixture_dirs: list[Path] = []
        served_identity: dict[str, object] | None = None

        def snapshot_parent_host_resources() -> dict[str, bytes]:
            return actual_snapshot_host_resources(source_dir)

        def fake_run_child(
            name: str, cycle: int, command: list[str], timeout: float
        ) -> runner.ChildExecution:
            del timeout
            child_names.append((name, cycle))
            if name == "normal lifecycle":
                return normal_execution(cycle, artifact=normal_preflight)
            self.assertEqual(1, cycle)
            host_dir = Path(command[command.index("--host-dir") + 1])
            fixture_dirs.append(host_dir)
            # This emulates a mutation after M9 materialized fixture A but
            # before M6's real descriptor-pinned server snapshot captures B.
            (host_dir / continuous_flow.HOST_RESOURCE_FILES["host_js"]).write_bytes(
                b"mutated before server capture"
            )
            nonlocal served_identity
            served_identity = continuous_flow.host_resource_snapshot_identity(
                actual_snapshot_host_resources(host_dir)
            )
            return flow_execution(
                cycle,
                flow_artifact=controlled_preflight,
                restart_artifact=controlled_preflight,
                flow_host_resources=served_identity,
                restart_host_resources=served_identity,
            )

        with (
            mock.patch.object(
                runner.continuous_flow,
                "snapshot_host_resources",
                side_effect=snapshot_parent_host_resources,
            ) as snapshot_host_resources,
            mock.patch.object(runner, "run_child", side_effect=fake_run_child),
            self.assertRaisesRegex(
                M0Error,
                "controlled-flow flow host resource identity disagrees with the "
                "frozen M9 fixture snapshot",
            ),
        ):
            runner.run_reliability(
                out_dir=out_dir,
                normal_module_name=runner.DEFAULT_NORMAL_MODULE_NAME,
                controlled_flow_module_name=runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME,
                normal_lifecycle_iterations=1,
                controlled_flow_iterations=2,
                normal_timeout=7.0,
                controlled_flow_timeout=11.0,
                diagnostics_dir=out_dir / "diagnostics",
                browser=None,
                node=None,
                relay_script=None,
                no_sandbox=False,
            )

        snapshot_host_resources.assert_called_once_with()
        self.assertIsNotNone(served_identity)
        self.assertNotEqual(
            continuous_flow.host_resource_snapshot_identity(source_snapshots),
            served_identity,
        )
        self.assertEqual(
            [("normal lifecycle", 1), ("controlled flow", 1)], child_names
        )
        self.assertEqual(1, len(fixture_dirs))
        self.assertFalse(fixture_dirs[0].exists())

    def test_controlled_flow_host_fixture_is_cleaned_after_nonzero_child(self) -> None:
        temporary, out_dir = self._make_out_dir()
        self.addCleanup(temporary.cleanup)
        normal_preflight, _controlled_preflight = self._preflight_artifact_identities(
            out_dir
        )
        host_snapshots = {
            name: f"fixture {name}".encode("ascii")
            for name in continuous_flow.HOST_RESOURCE_FILES
        }
        fixture_dirs: list[Path] = []

        def fake_run_child(
            name: str, cycle: int, command: list[str], timeout: float
        ) -> runner.ChildExecution:
            del timeout
            if name == "normal lifecycle":
                return normal_execution(cycle, artifact=normal_preflight)
            fixture_dirs.append(Path(command[command.index("--host-dir") + 1]))
            self.assertTrue(fixture_dirs[-1].is_dir())
            return runner.ChildExecution(
                name=name,
                cycle=cycle,
                elapsed_ms=1.0,
                returncode=1,
                stdout="",
                stderr="controlled child failed\n",
            )

        with (
            mock.patch.object(
                runner.continuous_flow,
                "snapshot_host_resources",
                return_value=host_snapshots,
            ) as snapshot_host_resources,
            mock.patch.object(runner, "run_child", side_effect=fake_run_child),
            self.assertRaisesRegex(
                M0Error, "controlled flow cycle 1 exited with status 1"
            ),
        ):
            runner.run_reliability(
                out_dir=out_dir,
                normal_module_name=runner.DEFAULT_NORMAL_MODULE_NAME,
                controlled_flow_module_name=runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME,
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

        snapshot_host_resources.assert_called_once_with()
        self.assertEqual(1, len(fixture_dirs))
        self.assertFalse(fixture_dirs[0].exists())

    def test_controlled_flow_artifact_drift_stops_before_later_cycles(self) -> None:
        temporary, out_dir = self._make_out_dir()
        self.addCleanup(temporary.cleanup)
        normal_preflight, controlled_flow_preflight = (
            self._preflight_artifact_identities(out_dir)
        )
        screenshot_contract, baseline_png, screenshot_policy = (
            self._retained_screenshot_policy()
        )
        substituted = copy.deepcopy(controlled_flow_preflight)
        substituted["wasm"] = {"bytes": 21, "sha256": "c" * 64}
        child_names: list[tuple[str, int]] = []

        def fake_run_child(
            name: str, cycle: int, command: list[str], timeout: float
        ) -> runner.ChildExecution:
            child_names.append((name, cycle))
            if name == "normal lifecycle":
                return normal_execution(cycle, artifact=normal_preflight)
            return flow_execution(
                cycle,
                flow_artifact=(
                    controlled_flow_preflight if cycle == 1 else substituted
                ),
                restart_artifact=(
                    controlled_flow_preflight if cycle == 1 else substituted
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
            with self.assertRaisesRegex(M0Error, "M9 parent preflight snapshot"):
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

    def test_run_rejects_later_controlled_flow_version_drift(self) -> None:
        temporary, out_dir = self._make_out_dir()
        self.addCleanup(temporary.cleanup)
        normal_preflight, controlled_flow_preflight = (
            self._preflight_artifact_identities(out_dir)
        )
        screenshot_contract, baseline_png, screenshot_policy = (
            self._retained_screenshot_policy()
        )
        drifted_versions = dict(VERSIONS)
        drifted_versions["port"] = "later-port-revision"
        child_names: list[tuple[str, int]] = []

        def fake_run_child(
            name: str, cycle: int, command: list[str], timeout: float
        ) -> runner.ChildExecution:
            del command, timeout
            child_names.append((name, cycle))
            if name == "normal lifecycle":
                return normal_execution(cycle, artifact=normal_preflight)
            child_versions = VERSIONS if cycle == 1 else drifted_versions
            return flow_execution(
                cycle,
                flow_versions=child_versions,
                restart_versions=child_versions,
                flow_artifact=controlled_flow_preflight,
                restart_artifact=controlled_flow_preflight,
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
            ),
            mock.patch.object(
                runner.continuous_flow,
                "validate_flow_result",
                return_value=baseline_png,
            ) as validate_flow,
            mock.patch.object(
                runner.continuous_flow, "validate_restart_result"
            ) as validate_restart,
            self.assertRaisesRegex(
                M0Error, "frozen M9 parent run version snapshot"
            ),
        ):
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
        self.parent_snapshot.assert_called_once()
        validate_flow.assert_called_once()
        validate_restart.assert_called_once()

    def test_normal_first_child_artifact_substitution_stops_later_launches(self) -> None:
        temporary, out_dir = self._make_out_dir()
        self.addCleanup(temporary.cleanup)
        normal_preflight, _ = self._preflight_artifact_identities(out_dir)
        substituted = copy.deepcopy(normal_preflight)
        substituted["loader"] = {"bytes": 7, "sha256": "f" * 64}
        child_names: list[tuple[str, int]] = []

        def fake_run_child(
            name: str, cycle: int, command: list[str], timeout: float
        ) -> runner.ChildExecution:
            del command, timeout
            child_names.append((name, cycle))
            if name != "normal lifecycle":
                self.fail("controlled flow must not start after normal substitution")
            return normal_execution(cycle, artifact=substituted)

        with mock.patch.object(runner, "run_child", side_effect=fake_run_child):
            with self.assertRaisesRegex(M0Error, "M9 parent preflight snapshot"):
                runner.run_reliability(
                    out_dir=out_dir,
                    normal_module_name=runner.DEFAULT_NORMAL_MODULE_NAME,
                    controlled_flow_module_name=(
                        runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME
                    ),
                    normal_lifecycle_iterations=2,
                    controlled_flow_iterations=2,
                    normal_timeout=7.0,
                    controlled_flow_timeout=11.0,
                    diagnostics_dir=out_dir / "diagnostics",
                    browser=None,
                    node=None,
                    relay_script=None,
                    no_sandbox=False,
                )

        self.assertEqual([("normal lifecycle", 1)], child_names)

    def test_normal_postflight_disk_mutation_stops_later_launches(self) -> None:
        temporary, out_dir = self._make_out_dir()
        self.addCleanup(temporary.cleanup)
        normal_preflight, _ = self._preflight_artifact_identities(out_dir)
        child_names: list[tuple[str, int]] = []

        def fake_run_child(
            name: str, cycle: int, command: list[str], timeout: float
        ) -> runner.ChildExecution:
            del command, timeout
            child_names.append((name, cycle))
            if name != "normal lifecycle":
                self.fail("controlled flow must not start after normal disk drift")
            (out_dir / "chrome_wasm.js").write_text(
                "mutated loader", encoding="utf-8"
            )
            return normal_execution(cycle, artifact=normal_preflight)

        with mock.patch.object(runner, "run_child", side_effect=fake_run_child):
            with self.assertRaisesRegex(M0Error, "changed since the M9 parent"):
                runner.run_reliability(
                    out_dir=out_dir,
                    normal_module_name=runner.DEFAULT_NORMAL_MODULE_NAME,
                    controlled_flow_module_name=(
                        runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME
                    ),
                    normal_lifecycle_iterations=2,
                    controlled_flow_iterations=1,
                    normal_timeout=7.0,
                    controlled_flow_timeout=11.0,
                    diagnostics_dir=out_dir / "diagnostics",
                    browser=None,
                    node=None,
                    relay_script=None,
                    no_sandbox=False,
                )

        self.assertEqual([("normal lifecycle", 1)], child_names)

    def test_controlled_first_child_artifact_substitution_stops_later_launches(
        self,
    ) -> None:
        temporary, out_dir = self._make_out_dir()
        self.addCleanup(temporary.cleanup)
        normal_preflight, controlled_flow_preflight = (
            self._preflight_artifact_identities(out_dir)
        )
        screenshot_contract, baseline_png, screenshot_policy = (
            self._retained_screenshot_policy()
        )
        substituted = copy.deepcopy(controlled_flow_preflight)
        substituted["wasm"] = {"bytes": 21, "sha256": "f" * 64}
        child_names: list[tuple[str, int]] = []

        def fake_run_child(
            name: str, cycle: int, command: list[str], timeout: float
        ) -> runner.ChildExecution:
            del command, timeout
            child_names.append((name, cycle))
            if name == "normal lifecycle":
                return normal_execution(cycle, artifact=normal_preflight)
            return flow_execution(
                cycle,
                flow_artifact=substituted,
                restart_artifact=substituted,
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
            ),
            mock.patch.object(
                runner.continuous_flow, "validate_flow_result"
            ) as validate_flow,
            mock.patch.object(
                runner.continuous_flow, "validate_restart_result"
            ) as validate_restart,
        ):
            with self.assertRaisesRegex(M0Error, "M9 parent preflight snapshot"):
                runner.run_reliability(
                    out_dir=out_dir,
                    normal_module_name=runner.DEFAULT_NORMAL_MODULE_NAME,
                    controlled_flow_module_name=(
                        runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME
                    ),
                    normal_lifecycle_iterations=1,
                    controlled_flow_iterations=2,
                    normal_timeout=7.0,
                    controlled_flow_timeout=11.0,
                    diagnostics_dir=out_dir / "diagnostics",
                    browser=None,
                    node=None,
                    relay_script=None,
                    no_sandbox=False,
                )

        self.assertEqual(
            [("normal lifecycle", 1), ("controlled flow", 1)], child_names
        )
        validate_flow.assert_not_called()
        validate_restart.assert_not_called()

    def test_controlled_postflight_disk_mutation_stops_later_launches(self) -> None:
        temporary, out_dir = self._make_out_dir()
        self.addCleanup(temporary.cleanup)
        normal_preflight, controlled_flow_preflight = (
            self._preflight_artifact_identities(out_dir)
        )
        screenshot_contract, baseline_png, screenshot_policy = (
            self._retained_screenshot_policy()
        )
        child_names: list[tuple[str, int]] = []

        def fake_run_child(
            name: str, cycle: int, command: list[str], timeout: float
        ) -> runner.ChildExecution:
            del command, timeout
            child_names.append((name, cycle))
            if name == "normal lifecycle":
                return normal_execution(cycle, artifact=normal_preflight)
            (out_dir / "chrome_wasm_m6_https_test.wasm").write_bytes(
                b"mutated wasm"
            )
            return flow_execution(
                cycle,
                flow_artifact=controlled_flow_preflight,
                restart_artifact=controlled_flow_preflight,
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
            ),
            mock.patch.object(
                runner.continuous_flow,
                "validate_flow_result",
                return_value=baseline_png,
            ) as validate_flow,
            mock.patch.object(
                runner.continuous_flow, "validate_restart_result"
            ) as validate_restart,
        ):
            with self.assertRaisesRegex(M0Error, "changed since the M9 parent"):
                runner.run_reliability(
                    out_dir=out_dir,
                    normal_module_name=runner.DEFAULT_NORMAL_MODULE_NAME,
                    controlled_flow_module_name=(
                        runner.DEFAULT_CONTROLLED_FLOW_MODULE_NAME
                    ),
                    normal_lifecycle_iterations=1,
                    controlled_flow_iterations=2,
                    normal_timeout=7.0,
                    controlled_flow_timeout=11.0,
                    diagnostics_dir=out_dir / "diagnostics",
                    browser=None,
                    node=None,
                    relay_script=None,
                    no_sandbox=False,
                )

        self.assertEqual(
            [("normal lifecycle", 1), ("controlled flow", 1)], child_names
        )
        validate_flow.assert_called_once()
        validate_restart.assert_called_once()

    def test_retained_visual_policy_rejects_cycle_two_drift_before_cycle_three(
        self,
    ) -> None:
        temporary, out_dir = self._make_out_dir()
        self.addCleanup(temporary.cleanup)
        normal_preflight, controlled_flow_preflight = (
            self._preflight_artifact_identities(out_dir)
        )
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
                return normal_execution(cycle, artifact=normal_preflight)
            return flow_execution(
                cycle,
                flow_artifact=controlled_flow_preflight,
                restart_artifact=controlled_flow_preflight,
            )

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
        normal_preflight, _ = self._preflight_artifact_identities(out_dir)
        substituted = copy.deepcopy(normal_preflight)
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
                    normal_preflight if cycle == 1 else substituted
                ),
            )

        with mock.patch.object(runner, "run_child", side_effect=fake_run_child):
            with self.assertRaisesRegex(M0Error, "M9 parent preflight snapshot"):
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
            host_dir=Path("/host-fixture"),
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
                "--host-dir",
                "/host-fixture",
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
