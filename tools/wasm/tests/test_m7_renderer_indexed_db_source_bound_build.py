#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the M7 renderer IndexedDB local build receipt."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error, REPO_ROOT
import run_m7_chrome_renderer_indexed_db_outer_reload_dom_smoke as smoke
import run_m7_renderer_indexed_db_source_bound_build as attester
from tools.wasm.tests.m3_source_contract_test_support import source


def receipt_inputs() -> tuple[
    dict[str, str], dict[str, object], bytes, dict[str, dict[str, object]], Path
]:
    checkout = {"commit": "a" * 40, "tree": "b" * 40}
    manifest = {
        "path": attester.MANIFEST_RELATIVE_PATH,
        "schema_version": 1,
        "sha256": "c" * 64,
        "versions": {
            "chromium": "d" * 40,
            "emscripten": "e" * 40,
            "rust": "f" * 40,
            "v8": "0" * 40,
        },
    }
    gn_args = b'enable_chromium_wasm_m7_profile_indexed_db_test = true\n'
    artifacts = {
        f"{attester.PRODUCT_MODULE_NAME}.js": {"bytes": 71, "sha256": "1" * 64},
        f"{attester.PRODUCT_MODULE_NAME}.wasm": {"bytes": 72, "sha256": "2" * 64},
    }
    return checkout, manifest, gn_args, artifacts, REPO_ROOT / smoke.DEFAULT_OUT_DIR


class RendererIndexedDBSourceBoundBuildTest(unittest.TestCase):
    def test_self_contained_args_append_only_the_selected_m7_flag(self) -> None:
        base = b'target_os = "emscripten"\nuse_ozone = true\n'
        expected = (
            base
            + b"enable_chromium_wasm_m7_profile_indexed_db_test = true\n"
        )
        self.assertEqual(expected, attester.expected_m7_gn_args_from_m6_args(base))
        with self.assertRaisesRegex(M0Error, "contain an M7 selection"):
            attester.expected_m7_gn_args_from_m6_args(
                base + b"enable_chromium_wasm_m7_profile_database_test = true\n"
            )
        with self.assertRaisesRegex(M0Error, "contain an M7 selection"):
            attester.expected_m7_gn_args_from_m6_args(
                base + b"enable_chromium_wasm_m7_profile_database_test = false\n"
            )
        for expression in (
            b"enable_chromium_wasm_m7_profile_database_test = !false\n",
            b"enable_chromium_wasm_m7_profile_database_test = true || false\n",
            b"# enable_chromium_wasm_m7_profile_database_test = true\n",
        ):
            with self.subTest(expression=expression):
                with self.assertRaisesRegex(M0Error, "contain an M7 selection"):
                    attester.expected_m7_gn_args_from_m6_args(base + expression)
        with self.assertRaisesRegex(M0Error, "invalid"):
            attester.expected_m7_gn_args_from_m6_args(base.rstrip(b"\n"))

    def test_only_one_literal_selected_m7_flag_is_accepted(self) -> None:
        good = b"enable_chromium_wasm_m7_profile_indexed_db_test = true\n"
        attester.validate_m7_indexed_db_gn_selection(good)
        for invalid in (
            good + b"enable_chromium_wasm_m7_profile_database_test = !false\n",
            good + b"enable_chromium_wasm_m7_profile_database_test = true || false\n",
            good + b"# enable_chromium_wasm_m7_profile_database_test = true\n",
            b"enable_chromium_wasm_m7_profile_indexed_db_test = true || false\n",
            good + good,
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(
                    M0Error, "selected M7 selector|literal selected M7 opt-in"
                ):
                    attester.validate_m7_indexed_db_gn_selection(invalid)

    def test_requires_the_pinned_emscripten_source_only_check(self) -> None:
        self.assertEqual(
            [
                sys.executable,
                str(REPO_ROOT / "tools/wasm/bootstrap.py"),
                "--emscripten-source-only",
                "--verify-only",
            ],
            attester._bootstrap_command(),
        )
        self.assertIn(
            "does-not-run-a-full-m3-bootstrap",
            attester.LIMITATIONS,
        )
        self.assertIn(
            "cooperative-local-reproducibility-receipt-not-independent-provenance",
            attester.LIMITATIONS,
        )
        self.assertIn(
            "does-not-prove-port-checkout-descends-from-manifest-chromium-revision",
            attester.LIMITATIONS,
        )
        self.assertIn(
            "does-not-verify-the-full-chromium-gitlink-dependency-closure",
            attester.LIMITATIONS,
        )
        self.assertIn(
            "does-not-validate-the-complete-chromium-m3-dependency-and-build-tool-closure",
            attester.LIMITATIONS,
        )
        self.assertIn(
            "does-not-bind-ignored-worktree-inputs-or-nested-dependency-working-tree-state",
            attester.LIMITATIONS,
        )

    def test_full_chrome_build_uses_an_explicit_extended_bound(self) -> None:
        out_dir = REPO_ROOT / "out" / "m7-receipt-timeout-test"
        with mock.patch.object(
            attester.clean_build,
            "run_required_command",
            return_value=object(),
        ) as run:
            attester._run_chrome_wasm_build(out_dir)
        run.assert_called_once_with(
            attester._autoninja_command(out_dir),
            "renderer IndexedDB fresh chrome_wasm build",
            timeout_seconds=attester.CHROME_WASM_BUILD_TIMEOUT_SECONDS,
        )
        self.assertEqual(10_800.0, attester.CHROME_WASM_BUILD_TIMEOUT_SECONDS)

    def test_receipt_binds_checkout_manifest_args_and_both_module_leaves(self) -> None:
        checkout, manifest, gn_args, artifacts, out_dir = receipt_inputs()
        receipt = attester.make_receipt(
            checkout=checkout,
            manifest=manifest,
            gn_args={
                "bytes": len(gn_args),
                "profile": attester.GN_ARGS_PROFILE,
                "sha256": attester._byte_identity(gn_args)["sha256"],
            },
            artifacts=artifacts,
            out_dir=out_dir,
        )
        self.assertFalse(receipt["m7_gate_complete"])
        self.assertEqual(
            {
                "marker": attester.BOOTSTRAP_MARKER,
                "mode": attester.BOOTSTRAP_MODE,
                "scope": attester.BOOTSTRAP_SCOPE,
            },
            receipt["bootstrap"],
        )
        self.assertEqual(attester.PRODUCT_MODULE_NAME, receipt["source_selection"]["module_name"])
        self.assertEqual(
            receipt,
            attester.validate_receipt_payload(
                receipt,
                expected_checkout=checkout,
                expected_manifest=manifest,
                expected_gn_args=gn_args,
                expected_artifacts=artifacts,
                out_dir=out_dir,
            ),
        )

    def test_receipt_rejects_stale_or_mutated_source_and_artifact_inputs(self) -> None:
        checkout, manifest, gn_args, artifacts, out_dir = receipt_inputs()
        receipt = attester.make_receipt(
            checkout=checkout,
            manifest=manifest,
            gn_args={
                "bytes": len(gn_args),
                "profile": attester.GN_ARGS_PROFILE,
                "sha256": attester._byte_identity(gn_args)["sha256"],
            },
            artifacts=artifacts,
            out_dir=out_dir,
        )
        mutations = (
            (
                lambda value: value["checkout"].__setitem__("tree", "9" * 40),
                "checkout differs",
            ),
            (
                lambda value: value["toolchain_manifest"]["versions"].__setitem__(
                    "emscripten", "8" * 40
                ),
                "manifest differs",
            ),
            (
                lambda value: value["gn"]["args"].__setitem__("sha256", "7" * 64),
                "GN args differ",
            ),
            (
                lambda value: value["artifacts"][
                    f"{attester.PRODUCT_MODULE_NAME}.wasm"
                ].__setitem__("sha256", "6" * 64),
                "artifacts differ",
            ),
        )
        for mutate, message in mutations:
            with self.subTest(message=message):
                changed = copy.deepcopy(receipt)
                mutate(changed)
                with self.assertRaisesRegex(M0Error, message):
                    attester.validate_receipt_payload(
                        changed,
                        expected_checkout=checkout,
                        expected_manifest=manifest,
                        expected_gn_args=gn_args,
                        expected_artifacts=artifacts,
                        out_dir=out_dir,
                    )

    def test_receipt_schema_rejects_extra_fields_and_duplicate_json_keys(self) -> None:
        checkout, manifest, gn_args, artifacts, out_dir = receipt_inputs()
        receipt = attester.make_receipt(
            checkout=checkout,
            manifest=manifest,
            gn_args={
                "bytes": len(gn_args),
                "profile": attester.GN_ARGS_PROFILE,
                "sha256": attester._byte_identity(gn_args)["sha256"],
            },
            artifacts=artifacts,
            out_dir=out_dir,
        )
        changed = copy.deepcopy(receipt)
        changed["unexpected"] = True
        with self.assertRaisesRegex(M0Error, "schema"):
            attester.validate_receipt_payload(
                changed,
                expected_checkout=checkout,
                expected_manifest=manifest,
                expected_gn_args=gn_args,
                expected_artifacts=artifacts,
                out_dir=out_dir,
            )
        with self.assertRaisesRegex(M0Error, "invalid"):
            attester._parse_json_object(b'{"a":1,"a":2}', "receipt")
        changed = copy.deepcopy(receipt)
        changed["gn"]["args"]["unexpected"] = True
        with self.assertRaisesRegex(M0Error, "GN args"):
            attester.validate_receipt_payload(
                changed,
                expected_checkout=checkout,
                expected_manifest=manifest,
                expected_gn_args=gn_args,
                expected_artifacts=artifacts,
                out_dir=out_dir,
            )

    def test_schema_versions_require_json_integers(self) -> None:
        checkout, manifest, gn_args, artifacts, out_dir = receipt_inputs()
        receipt = attester.make_receipt(
            checkout=checkout,
            manifest=manifest,
            gn_args={
                "bytes": len(gn_args),
                "profile": attester.GN_ARGS_PROFILE,
                "sha256": attester._byte_identity(gn_args)["sha256"],
            },
            artifacts=artifacts,
            out_dir=out_dir,
        )
        for field_path, value in (
            (("schema_version",), True),
            (("schema_version",), 1.0),
            (("toolchain_manifest", "schema_version"), True),
            (("toolchain_manifest", "schema_version"), 1.0),
        ):
            with self.subTest(field_path=field_path, value=value):
                changed = copy.deepcopy(receipt)
                target: dict[str, object] = changed
                for field in field_path[:-1]:
                    nested = target[field]
                    assert isinstance(nested, dict)
                    target = nested
                target[field_path[-1]] = value
                with self.assertRaisesRegex(M0Error, "metadata|toolchain manifest"):
                    attester.validate_receipt_payload(
                        changed,
                        expected_checkout=checkout,
                        expected_manifest=manifest,
                        expected_gn_args=gn_args,
                        expected_artifacts=artifacts,
                        out_dir=out_dir,
                    )

        for schema_version in (True, 1.0):
            with self.subTest(source_manifest_schema_version=schema_version):
                source_manifest = {
                    "schema_version": schema_version,
                    "chromium": {"revision": "a" * 40},
                    "emscripten": {"source_revision": "b" * 40},
                    "rust": {"source_revision": "c" * 40},
                    "git_dependencies": {"v8": {"revision": "d" * 40}},
                }
                with self.assertRaisesRegex(M0Error, "source versions"):
                    attester._manifest_record(source_manifest, b"{}")

    def test_receipt_writer_reads_back_and_refuses_replacement(self) -> None:
        checkout, manifest, gn_args, artifacts, _out_dir = receipt_inputs()
        with tempfile.TemporaryDirectory(dir=REPO_ROOT / "out") as temporary:
            out_dir = Path(temporary)
            receipt = attester.make_receipt(
                checkout=checkout,
                manifest=manifest,
                gn_args={
                    "bytes": len(gn_args),
                    "profile": attester.GN_ARGS_PROFILE,
                    "sha256": attester._byte_identity(gn_args)["sha256"],
                },
                artifacts=artifacts,
                out_dir=out_dir,
            )
            written = attester.write_receipt(out_dir, receipt)
            self.assertEqual(
                receipt,
                json.loads(written.read_text(encoding="utf-8")),
            )
            with self.assertRaisesRegex(M0Error, "already exists"):
                attester.write_receipt(out_dir, receipt)

    def test_runtime_receipt_binds_canonical_contents_and_served_bytes(self) -> None:
        checkout, manifest, gn_args, _artifacts, _out_dir = receipt_inputs()
        served_artifacts = {
            f"{attester.PRODUCT_MODULE_NAME}.js": b"export default {};\n",
            f"{attester.PRODUCT_MODULE_NAME}.wasm": b"\x00asm\x01\x00\x00\x00",
        }
        with tempfile.TemporaryDirectory(dir=REPO_ROOT / "out") as temporary:
            out_dir = Path(temporary) / smoke.DEFAULT_OUT_DIR.name
            out_dir.mkdir()
            receipt = attester.make_receipt(
                checkout=checkout,
                manifest=manifest,
                gn_args={
                    "bytes": len(gn_args),
                    "profile": attester.GN_ARGS_PROFILE,
                    "sha256": attester._byte_identity(gn_args)["sha256"],
                },
                artifacts={
                    name: attester._byte_identity(contents)
                    for name, contents in served_artifacts.items()
                },
                out_dir=out_dir,
            )
            receipt_path = attester.write_receipt(out_dir, receipt)

            def verify(
                *,
                args: bytes = gn_args,
                artifacts: dict[str, bytes] | None = None,
                path: Path = receipt_path,
            ) -> dict[str, object]:
                with mock.patch.object(
                    attester, "require_clean_attested_checkout"
                ), mock.patch.object(
                    attester, "checkout_identity", return_value=checkout
                ), mock.patch.object(
                    attester, "capture_manifest", return_value=({}, manifest, object())
                ), mock.patch.object(
                    attester, "expected_m7_gn_args", return_value=gn_args
                ):
                    return attester.verify_runtime_receipt(
                        path,
                        out_dir=out_dir,
                        served_args_gn=args,
                        served_artifacts=(
                            served_artifacts if artifacts is None else artifacts
                        ),
                    )

            self.assertEqual(receipt, verify())
            receipt_path.write_text(
                json.dumps(receipt, indent=2), encoding="utf-8"
            )
            with self.assertRaisesRegex(M0Error, "not canonical"):
                verify()
            receipt_path.write_bytes(attester._canonical_json_bytes(receipt))
            with self.assertRaisesRegex(M0Error, "served GN args"):
                verify(args=gn_args + b"# altered\n")
            altered_artifacts = dict(served_artifacts)
            altered_artifacts[f"{attester.PRODUCT_MODULE_NAME}.wasm"] += b"altered"
            with self.assertRaisesRegex(M0Error, "artifacts differ"):
                verify(artifacts=altered_artifacts)
            alternate_path = out_dir / "other.json"
            alternate_path.write_bytes(attester._canonical_json_bytes(receipt))
            with self.assertRaisesRegex(M0Error, "not in the selected output"):
                verify(path=alternate_path)

    def test_clean_source_allows_only_existing_documented_tool_symlinks(self) -> None:
        allowed = next(iter(attester.ALLOWED_UNTRACKED_TOOL_SYMLINKS))
        self.assertTrue((REPO_ROOT / allowed).is_symlink())
        with mock.patch.object(attester, "_git_output", return_value=f"?? {allowed}\0"):
            attester.require_clean_attested_checkout()
        with mock.patch.object(attester, "_git_output", return_value="?? elsewhere\0"):
            with self.assertRaisesRegex(M0Error, "clean tracked checkout"):
                attester.require_clean_attested_checkout()

    def test_source_builder_requires_runtime_compatible_output_leaf(self) -> None:
        incompatible = REPO_ROOT / "out" / "m7-receipt-incompatible-output"
        with mock.patch.object(
            attester.clean_build, "resolve_new_output_dir", return_value=incompatible
        ), mock.patch.object(attester, "require_clean_attested_checkout") as clean:
            with self.assertRaisesRegex(M0Error, "isolated runtime output leaf"):
                attester.run_source_bound_build(incompatible)
        clean.assert_not_called()

    def test_outer_runner_only_upgrades_after_receipt_validation(self) -> None:
        runner = source("tools/wasm/run_m7_chrome_renderer_indexed_db_outer_reload_dom_smoke.py")
        self.assertIn('parser.add_argument("--source-bound-receipt", type=Path)', runner)
        self.assertIn("source_bound_build.verify_runtime_receipt(", runner)
        self.assertLess(
            runner.index("source_bound_build.verify_runtime_receipt("),
            runner.index("artifact = artifact_identity("),
        )
        self.assertIn(
            "LOCAL_TOP_LEVEL_CLEAN_BUILD_ARTIFACT_SOURCE_PROVENANCE", runner
        )
        host = source("tools/wasm/host/chrome_wasm_renderer_indexed_db_outer_reload_smoke.js")
        self.assertIn('"unverified",', host)
        self.assertIn('"local_top_level_clean_build_emscripten_only_attested",', host)
        self.assertIn("ARTIFACT_SOURCE_PROVENANCE.has(", host)
        self.assertIn("artifact_source_provenance={source_provenance}", runner)


if __name__ == "__main__":
    unittest.main()
