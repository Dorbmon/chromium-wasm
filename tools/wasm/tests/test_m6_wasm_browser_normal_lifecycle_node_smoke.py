#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the no-switch Wasm Browser Node lifecycle runner."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
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
    def test_snapshot_run_version_identity_uses_one_manifest_and_head_observation(
        self,
    ) -> None:
        manifest = {"manifest": "test"}
        versions = {
            "chromium": "chromium-revision",
            "v8": "v8-revision",
            "emscripten": "emscripten-revision",
            "port": "port-revision",
        }
        with (
            mock.patch.object(
                runner, "checked_output", return_value="p" * 40
            ) as checked,
            mock.patch.object(
                runner, "manifest_versions", return_value=copy.deepcopy(versions)
            ) as manifest_versions,
        ):
            identity = runner.snapshot_run_version_identity(manifest)

        self.assertEqual(versions, identity)
        self.assertNotIn("source_provenance", identity)
        checked.assert_called_once_with(["git", "rev-parse", "HEAD"])
        manifest_versions.assert_called_once_with(manifest, "p" * 40)

    def test_snapshot_run_version_identity_rejects_nonexact_fields(self) -> None:
        invalid_versions = {
            "chromium": "chromium-revision",
            "v8": "v8-revision",
            "emscripten": "emscripten-revision",
            "port": "port-revision",
            "source_provenance": "unverified",
        }
        with (
            mock.patch.object(runner, "checked_output", return_value="p" * 40),
            mock.patch.object(
                runner, "manifest_versions", return_value=invalid_versions
            ),
            self.assertRaisesRegex(M0Error, "run version identity is invalid"),
        ):
            runner.snapshot_run_version_identity({"manifest": "test"})

    def test_main_reports_one_run_local_version_identity(self) -> None:
        manifest = {"emscripten": {"node_version": "test-node"}}
        versions = {
            "chromium": "chromium-revision",
            "v8": "v8-revision",
            "emscripten": "emscripten-revision",
            "port": "port-revision",
        }
        with tempfile.TemporaryDirectory() as temporary:
            out_dir = Path(temporary) / "out"
            out_dir.mkdir()
            (out_dir / "chrome_wasm.js").write_bytes(b"loader")
            (out_dir / "chrome_wasm.wasm").write_bytes(b"wasm")
            node = Path(temporary) / "node"
            node.write_text("node", encoding="utf-8")
            completed = subprocess.CompletedProcess(
                [],
                0,
                stdout=(
                    runner.RESULT_PREFIX
                    + json.dumps(_passing_result(), sort_keys=True)
                    + "\n"
                ),
                stderr=f"{runner.READY_MARKER}\n{runner.PASS_MARKER}\n",
            )
            stdout = io.StringIO()
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "run_m6_wasm_browser_normal_lifecycle_smoke.py",
                        "--out-dir",
                        str(out_dir),
                    ],
                ),
                mock.patch.object(runner, "check_boundary"),
                mock.patch.object(
                    runner, "load_manifest", return_value=manifest
                ) as load_manifest,
                mock.patch.object(
                    runner, "snapshot_run_version_identity", return_value=versions
                ) as snapshot_versions,
                mock.patch.object(runner, "node_executable", return_value=node),
                mock.patch.object(runner, "print_context"),
                mock.patch.object(
                    runner, "run_smoke", return_value=completed
                ) as run_smoke,
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(0, runner.main())

        load_manifest.assert_called_once_with()
        snapshot_versions.assert_called_once_with(manifest)
        run_smoke.assert_called_once()
        result_lines = [
            line
            for line in stdout.getvalue().splitlines()
            if line.startswith(f"{runner.SENTINEL}:NODE_RESULT ")
        ]
        self.assertEqual(1, len(result_lines))
        result = json.loads(result_lines[0].split(" ", 1)[1])
        self.assertEqual(versions, result["versions"])
        self.assertNotIn("source_provenance", result["versions"])

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

    def test_validate_result_rejects_undrained_volatile_profile_stores(self) -> None:
        result = _passing_result()
        base_output = f"{runner.READY_MARKER}\n{runner.PASS_MARKER}"
        for diagnostic in runner.UNDRAINED_VOLATILE_PROFILE_DIAGNOSTICS:
            with self.subTest(diagnostic=diagnostic):
                with self.assertRaisesRegex(
                    M0Error, "undrained volatile-profile store"
                ):
                    runner.validate_result(result, f"{base_output}\n{diagnostic}")

    def test_validate_result_rejects_network_change_notifier_stub(self) -> None:
        result = _passing_result()
        output = (
            f"{runner.READY_MARKER}\n{runner.PASS_MARKER}\n"
            "Not implemented reached in std::unique_ptr<net::NetworkChangeNotifier> "
            "net::NetworkChangeNotifier::CreateIfNeeded()."
        )
        with self.assertRaisesRegex(M0Error, "NetworkChangeNotifier"):
            runner.validate_result(result, output)

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
