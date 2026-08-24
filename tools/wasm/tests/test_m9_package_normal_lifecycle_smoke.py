#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the package-snapshot ordinary Node lifecycle smoke."""

from __future__ import annotations

import contextlib
from copy import deepcopy
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tools.wasm import package
from tools.wasm import run_m6_wasm_browser_normal_lifecycle_smoke as normal_lifecycle
from tools.wasm import run_m9_package_normal_lifecycle_smoke as runner
from tools.wasm import run_m9_package_smoke as package_smoke
from tools.wasm.m0_common import M0Error, load_manifest


PORT_REVISION = "a" * 40


def _passing_child_result() -> dict[str, object]:
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


class M9PackageNormalLifecycleSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.manifest = load_manifest()
        self.notice_patch = mock.patch.object(
            package,
            "_generate_target_third_party_notices",
            side_effect=self._write_fake_target_third_party_notices,
        )
        self.notice_patch.start()
        self.out_dir = self._make_out_dir()
        self.dist_dir = self._stage()

    def tearDown(self) -> None:
        self.notice_patch.stop()
        self.temporary_directory.cleanup()

    def _write_fake_target_third_party_notices(
        self, *, out_dir: Path, destination: Path
    ) -> None:
        self.assertEqual(self.out_dir, out_dir)
        package._write_file(
            destination,
            package.TARGET_THIRD_PARTY_NOTICES_MARKER
            + b"\n--------------------\nSynthetic target notice for tests.\n",
        )

    def _make_out_dir(self) -> Path:
        out_dir = self.root / "raw-build-output"
        out_dir.mkdir()
        (out_dir / "chrome_wasm.js").write_text(
            'const wasm = "chrome_wasm.wasm";\n'
            "export default async function() { return {wasm}; }\n",
            encoding="utf-8",
        )
        (out_dir / "chrome_wasm.wasm").write_bytes(b"\x00asm\x01\x00\x00\x00")
        (out_dir / "args.gn").write_text(
            'target_os = "emscripten"\n'
            'target_cpu = "wasm"\n'
            'v8_snapshot_toolchain_runtime_root = "//out/runtime"\n',
            encoding="utf-8",
        )
        return out_dir

    def _stage(self) -> Path:
        dist_dir = self.root / "package"
        package.package_release(
            out_dir=self.out_dir,
            dist_dir=dist_dir,
            module_name="chrome_wasm",
            manifest=self.manifest,
            port_revision=PORT_REVISION,
        )
        return dist_dir

    def _package_snapshot(self) -> runner.PackageLifecycleSnapshot:
        return runner.capture_package_lifecycle_snapshot(self.dist_dir)

    def _fake_node(self) -> tuple[Path, runner.PinnedNodeRequirement]:
        node = self.root / "pinned-node"
        contents = b"#!/bin/sh\nif [ \"$1\" = \"--version\" ]; then\n  echo v22.16.0\n  exit 0\nfi\nexit 1\n"
        node.write_bytes(contents)
        node.chmod(0o700)
        return node, runner.PinnedNodeRequirement(
            version="22.16.0", sha256=hashlib.sha256(contents).hexdigest()
        )

    def _completed_child(
        self, result: dict[str, object] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            [],
            0,
            stdout=(
                normal_lifecycle.RESULT_PREFIX
                + json.dumps(result or _passing_child_result(), sort_keys=True)
                + "\n"
            ),
            stderr=(
                f"{normal_lifecycle.DEFAULT_STORAGE_PARTITION_RECEIPT}\n"
                f"{normal_lifecycle.READY_MARKER}\n"
                f"{normal_lifecycle.PASS_MARKER}\n"
            ),
        )

    def _result_for(
        self,
        snapshot: runner.PackageLifecycleSnapshot,
        node: runner.PinnedNodeSnapshot,
    ) -> dict[str, object]:
        return {
            "artifact": deepcopy(snapshot.artifact_identity),
            "canvasCopies": 1,
            "focusReports": 1,
            "frameReports": 1,
            "node": runner._node_identity(node),
            "packageRuntimeMetadata": deepcopy(snapshot.runtime_metadata),
            "readinessReports": 1,
            "scope": runner.SCOPE,
            "startupMs": 1.25,
        }

    def test_snapshot_maps_verified_public_bytes_to_private_lifecycle_names(self) -> None:
        snapshot = self._package_snapshot()
        version_bytes = (self.dist_dir / "VERSION.json").read_bytes()

        self.assertEqual(runner.PRIVATE_MODULE_NAME, snapshot.artifact.module_name)
        self.assertEqual(
            (self.dist_dir / "chromium-wasm.js").read_bytes(), snapshot.artifact.loader
        )
        self.assertEqual(
            (self.dist_dir / "chromium-wasm.wasm").read_bytes(), snapshot.artifact.wasm
        )
        self.assertEqual(
            package.package_runtime_status_metadata(version_bytes),
            snapshot.runtime_metadata,
        )
        self.assertEqual(
            hashlib.sha256(version_bytes).hexdigest(),
            snapshot.runtime_metadata["versionJsonSha256"],
        )
        self.assertEqual(package.RELEASE_STATUS, snapshot.runtime_metadata["releaseStatus"])
        self.assertEqual(package.EXPECTED_GATE_STATE, snapshot.runtime_metadata["gateState"])
        self.assertEqual(
            snapshot.runtime_metadata["build"]["artifactSourceProvenance"],
            snapshot.artifact_identity["artifact_source_provenance"],
        )
        self.assertEqual(runner.PUBLIC_MODULE_NAME, snapshot.artifact_identity["public_module_name"])
        self.assertEqual(runner.PRIVATE_MODULE_NAME, snapshot.artifact_identity["module_name"])
        self.assertEqual(
            runner.PACKAGE_ARTIFACT_DELIVERY,
            snapshot.artifact_identity["artifact_delivery"],
        )

    def test_snapshot_rejects_package_byte_mutation_before_private_materialization(self) -> None:
        tree = package_smoke.snapshot_package_tree(self.dist_dir)
        artifacts = dict(tree.artifacts)
        artifacts["chromium-wasm.js"] = b"mutated packaged loader"
        substituted = package_smoke.PackageTreeSnapshot(
            artifacts=artifacts, verification=dict(tree.verification)
        )

        with self.assertRaisesRegex(M0Error, "artifact hash mismatch"):
            runner.package_lifecycle_snapshot_from_tree(substituted)

    def test_result_schema_rejects_byte_and_runtime_metadata_substitution(self) -> None:
        snapshot = self._package_snapshot()
        node = runner.PinnedNodeSnapshot(
            contents=b"pinned node bytes",
            requirement=runner.PinnedNodeRequirement(
                version="22.16.0",
                sha256=hashlib.sha256(b"pinned node bytes").hexdigest(),
            ),
        )
        result = self._result_for(snapshot, node)
        self.assertEqual(
            {
                "artifact",
                "canvasCopies",
                "focusReports",
                "frameReports",
                "node",
                "packageRuntimeMetadata",
                "readinessReports",
                "scope",
                "startupMs",
            },
            set(result),
        )
        self.assertEqual(result, runner.validate_package_result(result, expected=snapshot, node=node))

        byte_substitution = deepcopy(result)
        byte_substitution["artifact"]["wasm"]["sha256"] = "f" * 64
        metadata_substitution = deepcopy(result)
        metadata_substitution["packageRuntimeMetadata"]["versionJsonSha256"] = "f" * 64
        gate_substitution = deepcopy(result)
        gate_substitution["packageRuntimeMetadata"]["gateState"]["m8_complete"] = True
        provenance_substitution = deepcopy(result)
        provenance_substitution["artifact"]["artifact_source_provenance"] = "verified"
        extra_field = deepcopy(result)
        extra_field["unexpected"] = True
        for name, invalid, fragment in (
            ("byte", byte_substitution, "artifact identity"),
            ("version metadata", metadata_substitution, "runtime metadata"),
            ("gate metadata", gate_substitution, "runtime metadata"),
            ("provenance", provenance_substitution, "source provenance"),
            ("extra field", extra_field, "result schema"),
        ):
            with self.subTest(name=name), self.assertRaisesRegex(M0Error, fragment):
                runner.validate_package_result(invalid, expected=snapshot, node=node)

    def test_capture_remains_independent_of_mutated_raw_build_output(self) -> None:
        snapshot = self._package_snapshot()
        packaged_loader = snapshot.artifact.loader
        packaged_wasm = snapshot.artifact.wasm
        (self.out_dir / "chrome_wasm.js").write_bytes(b"mutated raw output loader")
        (self.out_dir / "chrome_wasm.wasm").write_bytes(b"mutated raw output wasm")

        self.assertEqual(packaged_loader, snapshot.artifact.loader)
        self.assertEqual(packaged_wasm, snapshot.artifact.wasm)
        self.assertNotEqual(
            (self.out_dir / "chrome_wasm.js").read_bytes(), snapshot.artifact.loader
        )
        self.assertNotEqual(
            (self.out_dir / "chrome_wasm.wasm").read_bytes(), snapshot.artifact.wasm
        )

    def test_run_validates_child_lifecycle_and_cleans_private_snapshots(self) -> None:
        package_snapshot = self._package_snapshot()
        node, requirement = self._fake_node()
        expected = replace(package_snapshot, node_requirement=requirement)
        materialized_paths: list[Path] = []
        original_node_check = runner.validate_pinned_node_version

        def validate_node(path: Path, node_requirement: runner.PinnedNodeRequirement) -> None:
            materialized_paths.append(path)
            original_node_check(path, node_requirement)

        def run_smoke(module: Path, pinned_node: Path, timeout: float) -> subprocess.CompletedProcess[str]:
            self.assertEqual(30.0, timeout)
            self.assertEqual(expected.artifact.loader, module.read_bytes())
            self.assertEqual(expected.artifact.wasm, module.with_suffix(".wasm").read_bytes())
            self.assertTrue(pinned_node.is_file())
            materialized_paths.append(module)
            return self._completed_child()

        with (
            mock.patch.object(
                runner, "capture_package_lifecycle_snapshot", return_value=expected
            ),
            mock.patch.object(
                normal_lifecycle,
                "check_boundary",
                side_effect=AssertionError("package mode must not check a raw output"),
            ),
            mock.patch.object(runner, "validate_pinned_node_version", side_effect=validate_node),
            mock.patch.object(normal_lifecycle, "run_smoke", side_effect=run_smoke),
        ):
            result, completed = runner.run_package_normal_lifecycle(
                dist_dir=self.dist_dir, node=node, timeout=30.0
            )

        self.assertEqual(0, completed.returncode)
        self.assertEqual(result, runner.validate_package_result(
            result,
            expected=expected,
            node=runner.capture_pinned_node(node, requirement),
        ))
        self.assertEqual(2, len(materialized_paths))
        self.assertTrue(all(not path.parent.exists() for path in materialized_paths))

    def test_run_rejects_an_invalid_ordinary_child_lifecycle(self) -> None:
        package_snapshot = self._package_snapshot()
        node, requirement = self._fake_node()
        expected = replace(package_snapshot, node_requirement=requirement)
        invalid_child = _passing_child_result()
        invalid_child["passObserved"] = False

        with (
            mock.patch.object(
                runner, "capture_package_lifecycle_snapshot", return_value=expected
            ),
            mock.patch.object(
                normal_lifecycle,
                "run_smoke",
                return_value=self._completed_child(invalid_child),
            ),
            self.assertRaisesRegex(M0Error, "pass marker"),
        ):
            runner.run_package_normal_lifecycle(
                dist_dir=self.dist_dir, node=node, timeout=30.0
            )

    def test_explicit_node_must_match_its_bundled_hash(self) -> None:
        node, requirement = self._fake_node()
        captured = runner.capture_pinned_node(node, requirement)
        self.assertEqual(requirement, captured.requirement)
        self.assertEqual(node.read_bytes(), captured.contents)

        wrong = replace(requirement, sha256="0" * 64)
        with self.assertRaisesRegex(M0Error, "hash disagrees"):
            runner.capture_pinned_node(node, wrong)

    def test_main_requires_an_explicit_node_argument(self) -> None:
        stderr = io.StringIO()
        with (
            mock.patch.object(sys, "argv", ["run_m9_package_normal_lifecycle_smoke.py", "--dist-dir", str(self.dist_dir)]),
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit) as exit_error,
        ):
            runner.main()

        self.assertEqual(2, exit_error.exception.code)
        self.assertIn("--node", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
