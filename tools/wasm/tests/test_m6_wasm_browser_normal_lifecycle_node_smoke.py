#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the no-switch Wasm Browser Node lifecycle runner."""

from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m6_wasm_browser_normal_lifecycle_smoke as runner


def _passing_result() -> dict[str, object]:
    return {
        "runtimeExitCode": 0,
        "abort": None,
        "rejection": None,
        "readyObserved": True,
        "passObserved": True,
        "hostShutdownRequests": [1, 0],
        "canvasCopies": 1,
        "fatalReports": [],
        "frameReports": [
            {"protocol": 1, "id": 1, "width": 640, "height": 480, "timestampMs": 1}
        ],
        "readinessReports": [{"protocol": 1, "surfaceReady": True}],
        "focusReports": [
            {"protocol": 1, "keyboardTargetPresent": True, "active": True}
        ],
        "processExitReports": [{"protocol": 1, "exitCode": 0}],
    }


class M6WasmBrowserNormalLifecycleNodeSmokeTest(unittest.TestCase):
    def test_runner_is_no_switch_and_uses_only_the_shutdown_abi_after_ready(self) -> None:
        source = runner.runner_source("file:///tmp/chrome_wasm.js", 30000)
        self.assertIn("arguments: []", source)
        self.assertNotIn("--wasm-browser-smoke", source)
        self.assertIn("chromium_wasm_browser_host_request_shutdown", source)
        self.assertIn("result.hostShutdownRequests.push(first, second);", source)
        self.assertIn("if (first !== 1 || second !== 0)", source)
        self.assertIn("if (text.includes(readyMarker))", source)
        self.assertIn("onRuntimeInitialized()", source)
        self.assertIn("function hasVisibleBrowserEvidence()", source)
        self.assertIn("function maybeRequestHostShutdown()", source)
        self.assertIn("queueMicrotask(maybeRequestHostShutdown);", source)
        self.assertIn("result.frameReports.length > 0", source)
        self.assertIn("report.surfaceReady === true", source)
        self.assertIn("report.keyboardTargetPresent === true", source)
        self.assertIn("createModule(moduleOptions).catch", source)
        self.assertNotIn("await createModule", source)

    def test_validate_result_requires_visible_lifecycle_and_one_shot_shutdown(self) -> None:
        result = _passing_result()
        output = f"{runner.READY_MARKER}\n{runner.PASS_MARKER}"
        runner.validate_result(result, output)

        for key, value, fragment in (
            ("hostShutdownRequests", [1], "one-shot"),
            ("readyObserved", False, "ready marker"),
            ("passObserved", False, "pass marker"),
            ("runtimeExitCode", 13, "exit zero"),
        ):
            with self.subTest(key=key):
                invalid = copy.deepcopy(result)
                invalid[key] = value
                with self.assertRaisesRegex(M0Error, fragment):
                    runner.validate_result(invalid, output)

    def test_snapshot_materializes_captured_bytes_after_source_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            out_dir = Path(temporary) / "out"
            out_dir.mkdir()
            source_loader = out_dir / "chrome_wasm.js"
            source_wasm = out_dir / "chrome_wasm.wasm"
            original_loader = b"captured loader bytes"
            original_wasm = b"captured wasm bytes"
            source_loader.write_bytes(original_loader)
            source_wasm.write_bytes(original_wasm)

            snapshot = runner.capture_artifact_snapshot(out_dir, "chrome_wasm")
            identity = runner.artifact_identity(snapshot)
            source_loader.write_bytes(b"mutated source loader")
            source_wasm.write_bytes(b"mutated source wasm")

            with runner.materialized_artifact_snapshot(snapshot) as module:
                self.assertNotEqual(out_dir, module.parent)
                self.assertEqual(original_loader, module.read_bytes())
                self.assertEqual(original_wasm, module.with_suffix(".wasm").read_bytes())
                source = runner.runner_source(module.as_uri(), 30000)
                self.assertIn(module.as_uri(), source)
                self.assertNotIn(source_loader.as_uri(), source)
                completed = subprocess.CompletedProcess([], 0, "", "")
                with mock.patch.object(
                    runner.subprocess, "run", return_value=completed
                ) as run:
                    self.assertIs(completed, runner.run_smoke(module, Path("/node"), 30.0))
                self.assertIn(module.as_uri(), run.call_args.args[0][-1])

        self.assertEqual(
            {
                "artifact_delivery": runner.ARTIFACT_DELIVERY,
                "artifact_source_provenance": runner.ARTIFACT_SOURCE_PROVENANCE,
                "loader": {
                    "bytes": len(original_loader),
                    "sha256": hashlib.sha256(original_loader).hexdigest(),
                },
                "module_name": "chrome_wasm",
                "wasm": {
                    "bytes": len(original_wasm),
                    "sha256": hashlib.sha256(original_wasm).hexdigest(),
                },
            },
            identity,
        )

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires POSIX named pipes")
    def test_snapshot_rejects_a_fifo_execution_input_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            out_dir = Path(temporary) / "out"
            out_dir.mkdir()
            (out_dir / "chrome_wasm.js").write_bytes(b"loader")
            os.mkfifo(out_dir / "chrome_wasm.wasm")

            with self.assertRaisesRegex(M0Error, "regular file"):
                runner.capture_artifact_snapshot(out_dir, "chrome_wasm")

    @unittest.skipUnless(hasattr(os, "symlink"), "requires symbolic links")
    def test_snapshot_rejects_a_symlink_execution_input(self) -> None:
        if os.name != "posix":
            self.skipTest("host cannot reject final-component symlinks")
        with tempfile.TemporaryDirectory() as temporary:
            out_dir = Path(temporary) / "out"
            out_dir.mkdir()
            target = Path(temporary) / "replacement-loader.js"
            target.write_bytes(b"replacement loader")
            (out_dir / "chrome_wasm.js").symlink_to(target)
            (out_dir / "chrome_wasm.wasm").write_bytes(b"wasm")

            with self.assertRaisesRegex(M0Error, "opened safely"):
                runner.capture_artifact_snapshot(out_dir, "chrome_wasm")

    def test_artifact_identity_requires_exact_schema_and_configured_module(self) -> None:
        snapshot = runner.ArtifactSnapshot(
            module_name="chrome_wasm", loader=b"loader", wasm=b"wasm"
        )
        identity = runner.artifact_identity(snapshot)
        self.assertEqual(
            identity,
            runner.validate_artifact_identity(
                identity,
                expected_module_name="chrome_wasm",
                expected_artifact_identity=identity,
            ),
        )

        cases = (
            (
                "wrong module",
                lambda value: value.__setitem__("module_name", "other_module"),
                "configured module",
            ),
            (
                "wrong delivery",
                lambda value: value.__setitem__("artifact_delivery", "live-output"),
                "delivery",
            ),
            (
                "wrong provenance",
                lambda value: value.__setitem__(
                    "artifact_source_provenance", "verified"
                ),
                "source provenance",
            ),
            (
                "bool byte count",
                lambda value: value.__setitem__(
                    "loader", {"bytes": True, "sha256": "a" * 64}
                ),
                "byte count",
            ),
            (
                "uppercase hash",
                lambda value: value.__setitem__(
                    "wasm", {"bytes": 1, "sha256": "A" * 64}
                ),
                "SHA-256",
            ),
            (
                "unexpected field",
                lambda value: value.__setitem__("extra", "field"),
                "schema",
            ),
        )
        for name, mutate, fragment in cases:
            with self.subTest(name=name):
                invalid = copy.deepcopy(identity)
                mutate(invalid)
                with self.assertRaisesRegex(M0Error, fragment):
                    runner.validate_artifact_identity(
                        invalid, expected_module_name="chrome_wasm"
                    )

        different = copy.deepcopy(identity)
        different["wasm"] = {"bytes": 5, "sha256": "f" * 64}
        with self.assertRaisesRegex(M0Error, "disagrees with expectation"):
            runner.validate_artifact_identity(
                different,
                expected_module_name="chrome_wasm",
                expected_artifact_identity=identity,
            )


if __name__ == "__main__":
    unittest.main()
