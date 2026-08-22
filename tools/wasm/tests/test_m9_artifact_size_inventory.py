#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the non-release M9 artifact size inventory."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from tools.wasm import m0_common
from tools.wasm import package
from tools.wasm import run_m9_artifact_size_inventory as inventory


class ArtifactSizeInventoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.temporary_directory.name) / "out"
        self.out_dir.mkdir()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _write_artifacts(
        self,
        *,
        args_gn: bytes = b'is_debug = false\n',
        loader: bytes = b"loader-" * 23,
        wasm: bytes = b"wasm-" * 41,
    ) -> None:
        (self.out_dir / "args.gn").write_bytes(args_gn)
        (self.out_dir / "chrome_wasm.js").write_bytes(loader)
        (self.out_dir / "chrome_wasm.wasm").write_bytes(wasm)

    def test_raw_artifact_bound_stays_below_gzip_isize_wraparound(self) -> None:
        self.assertEqual((4 * 1024 * 1024 * 1024) - 1, inventory.MAX_ARTIFACT_BYTES)
        self.assertLess(inventory.MAX_ARTIFACT_BYTES, 2**32)

    def test_collects_fixed_artifacts_with_explicit_nonclaims(self) -> None:
        loader = b"loader-" * 23
        wasm = b"wasm-" * 41
        args_gn = b'is_debug = false\n'
        self._write_artifacts(args_gn=args_gn, loader=loader, wasm=wasm)

        result = inventory.collect_artifact_size_inventory(self.out_dir)

        inventory.validate_artifact_size_inventory(result)
        self.assertEqual(inventory.STATUS, result["status"])
        self.assertEqual(inventory.RELEASE_STATUS, result["release_status"])
        self.assertEqual(package.RELEASE_STATUS, result["release_status"])
        self.assertIs(False, result["m9_gate_complete"])
        self.assertIs(False, result["performance_gate"])
        self.assertEqual(package.EXPECTED_GATE_STATE, result["gate_state"])
        self.assertEqual(inventory.ARTIFACT_DELIVERY, result["artifact_delivery"])
        self.assertEqual(list(inventory.LIMITATIONS), result["limitations"])

        build = result["build"]
        assert isinstance(build, dict)
        self.assertEqual(inventory.PRODUCT_MODULE_NAME, build["input_module_name"])
        self.assertEqual(
            inventory.ARTIFACT_SOURCE_PROVENANCE,
            build["artifact_source_provenance"],
        )
        self.assertEqual(len(args_gn), build["args_gn"]["bytes"])
        self.assertEqual(
            hashlib.sha256(args_gn).hexdigest(), build["args_gn"]["sha256"]
        )

        artifacts = result["artifacts"]
        assert isinstance(artifacts, dict)
        self.assertEqual(inventory.PRODUCT_MODULE_NAME, artifacts["module_name"])
        self.assertEqual(len(loader) + len(wasm), artifacts["raw_total_bytes"])
        self.assertEqual(
            len(loader), artifacts["by_name"]["chrome_wasm.js"]["raw"]["bytes"]
        )
        self.assertEqual(
            hashlib.sha256(loader).hexdigest(),
            artifacts["by_name"]["chrome_wasm.js"]["raw"]["sha256"],
        )
        self.assertEqual(
            hashlib.sha256(wasm).hexdigest(),
            artifacts["by_name"]["chrome_wasm.wasm"]["raw"]["sha256"],
        )
        self.assertEqual(
            artifacts["raw_total_bytes"] - artifacts["gzip_total_bytes"],
            artifacts["gzip_savings_bytes"],
        )
        self.assertNotIn("pinned_identity", inventory._canonical_json_text(result))

    def test_local_gzip_observation_repeats_for_identical_inputs(self) -> None:
        self._write_artifacts()

        first = inventory.collect_artifact_size_inventory(self.out_dir)
        second = inventory.collect_artifact_size_inventory(self.out_dir)

        self.assertEqual(first, second)
        gzip_observation = first["gzip_observation"]
        assert isinstance(gzip_observation, dict)
        self.assertEqual("gzip", gzip_observation["content_encoding"])
        self.assertEqual(inventory.GZIP_PARAMETERS, gzip_observation["parameters"])
        self.assertEqual(inventory.GZIP_SCOPE, gzip_observation["scope"])
        producer = gzip_observation["producer"]
        assert isinstance(producer, dict)
        self.assertEqual(
            {
                "python_implementation",
                "python_version",
                "zlib_compile_version",
                "zlib_runtime_version",
            },
            set(producer),
        )

    def test_validator_rejects_false_completion_or_totals(self) -> None:
        self._write_artifacts()
        result = inventory.collect_artifact_size_inventory(self.out_dir)

        completion = copy.deepcopy(result)
        completion["m9_gate_complete"] = True
        with self.assertRaisesRegex(m0_common.M0Error, "non-release contract"):
            inventory.validate_artifact_size_inventory(completion)

        performance = copy.deepcopy(result)
        performance["performance_gate"] = True
        with self.assertRaisesRegex(m0_common.M0Error, "non-release contract"):
            inventory.validate_artifact_size_inventory(performance)

        release = copy.deepcopy(result)
        release["release_status"] = "release_complete"
        with self.assertRaisesRegex(m0_common.M0Error, "non-release contract"):
            inventory.validate_artifact_size_inventory(release)

        gate_state = copy.deepcopy(result)
        gate_state["gate_state"]["m8_complete"] = True
        with self.assertRaisesRegex(m0_common.M0Error, "gate state"):
            inventory.validate_artifact_size_inventory(gate_state)

        build_binding = copy.deepcopy(result)
        build = build_binding["build"]
        assert isinstance(build, dict)
        build["args_gn"]["bytes"] = True
        with self.assertRaisesRegex(m0_common.M0Error, "args.gn byte count"):
            inventory.validate_artifact_size_inventory(build_binding)

        boolean_byte_count = copy.deepcopy(result)
        artifacts = boolean_byte_count["artifacts"]
        assert isinstance(artifacts, dict)
        artifacts["by_name"]["chrome_wasm.js"]["gzip_observation"][
            "uncompressed_bytes"
        ] = True
        with self.assertRaisesRegex(m0_common.M0Error, "artifact identity"):
            inventory.validate_artifact_size_inventory(boolean_byte_count)

        totals = copy.deepcopy(result)
        artifacts = totals["artifacts"]
        assert isinstance(artifacts, dict)
        artifacts["raw_total_bytes"] = 1
        with self.assertRaisesRegex(m0_common.M0Error, "totals"):
            inventory.validate_artifact_size_inventory(totals)

        boolean_total = copy.deepcopy(result)
        artifacts = boolean_total["artifacts"]
        assert isinstance(artifacts, dict)
        artifacts["gzip_savings_bytes"] = False
        with self.assertRaisesRegex(m0_common.M0Error, "totals"):
            inventory.validate_artifact_size_inventory(boolean_total)

    def test_rejects_an_alternate_module_before_reading_artifacts(self) -> None:
        with mock.patch.object(inventory, "hash_regular_files") as snapshot:
            with self.assertRaisesRegex(m0_common.M0Error, "fixed chrome_wasm"):
                inventory.collect_artifact_size_inventory(
                    self.out_dir, module_name="other_module"
                )
        snapshot.assert_not_called()

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support is required")
    def test_rejects_a_symlinked_artifact(self) -> None:
        source = self.out_dir / "source.js"
        source.write_bytes(b"not-the-loader")
        (self.out_dir / "args.gn").write_bytes(b"is_debug = false\n")
        (self.out_dir / "chrome_wasm.js").symlink_to(source)
        (self.out_dir / "chrome_wasm.wasm").write_bytes(b"wasm")

        with self.assertRaisesRegex(m0_common.M0Error, "cannot be opened safely"):
            inventory.collect_artifact_size_inventory(self.out_dir)

    def test_requires_the_descriptor_pinned_args_gn_build_binding(self) -> None:
        self._write_artifacts()
        (self.out_dir / "args.gn").unlink()

        with self.assertRaisesRegex(m0_common.M0Error, "cannot be opened safely"):
            inventory.collect_artifact_size_inventory(self.out_dir)

    def test_main_emits_an_observation_not_a_pass_marker(self) -> None:
        self._write_artifacts()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(
                sys,
                "argv",
                [
                    "run_m9_artifact_size_inventory.py",
                    "--out-dir",
                    str(self.out_dir),
                ],
            ),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(0, inventory.main())

        self.assertEqual("", stderr.getvalue())
        lines = stdout.getvalue().splitlines()
        self.assertEqual(1, len(lines))
        self.assertTrue(lines[0].startswith(inventory.OBSERVED_PREFIX))
        self.assertNotIn(":PASS", lines[0])


if __name__ == "__main__":
    unittest.main()
