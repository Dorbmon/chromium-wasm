#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the standalone M8 V8 ARM32 codegen evidence."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error, gn_args_text, load_manifest
import run_m8_v8_arm32_wasm_codegen_smoke as smoke


def manifest() -> dict[str, object]:
    return load_manifest()


def create_bound_output(
    directory: Path, manifest_data: dict[str, object]
) -> tuple[Path, Path, Path]:
    out_dir = directory / "out"
    out_dir.mkdir()
    (out_dir / "args.gn").write_text(
        gn_args_text(manifest_data, smoke.MANIFEST_KEY), encoding="utf-8"
    )
    module = out_dir / smoke.MODULE_NAME
    module.write_text("export default async () => {};", encoding="utf-8")
    wasm = module.with_suffix(".wasm")
    wasm.write_bytes(b"\\0asm")
    return out_dir, module, wasm


def successful_runtime_output(module: Path, wasm: Path) -> str:
    receipt = {
        "artifact": str(module),
        "wasm": str(wasm),
        **smoke.EXPECTED_NODE_RESULT,
    }
    return smoke.NODE_PASS_PREFIX + json.dumps(receipt, sort_keys=True) + "\n"


def failed_runtime_output(detail: str = "runtime aborted") -> str:
    receipt = {
        "factoryCalls": 1,
        "onAbortCount": 1,
        "onExitCount": 0,
        "reason": "runtime_aborted",
        "detail": detail,
        "status": "fail",
        "stderrLines": 2,
        "stdoutLines": 5,
    }
    return (
        smoke.NODE_FAIL_PREFIX
        + json.dumps(
            receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        + "\n"
    )


class M8V8Arm32CodegenProfileTest(unittest.TestCase):
    def test_manifest_profile_is_explicitly_standalone_and_non_debug(self) -> None:
        profile = smoke.validate_profile(manifest())
        self.assertIn("dcheck_always_on = false", profile)
        self.assertIn("v8_jitless = false", profile)
        self.assertIn("v8_enable_webassembly = true", profile)
        self.assertIn("v8_enable_turbofan = true", profile)
        self.assertIn("v8_enable_wasm_arm32_codegen_smoke = true", profile)
        self.assertIn("enable_chromium_wasm_content = false", profile)
        self.assertIn("enable_chromium_wasm_chrome = false", profile)
        self.assertNotIn("enable_chromium_wasm_content = true", profile)
        self.assertNotIn("enable_chromium_wasm_chrome = true", profile)

    def test_profile_rejects_debug_or_browser_expansion(self) -> None:
        for existing, replacement, expected in (
            (
                "dcheck_always_on = false",
                "dcheck_always_on = true",
                "dcheck_always_on = false",
            ),
            ("is_debug = false", "is_debug = true", "is_debug = false"),
            (
                "v8_enable_debugging_features = false",
                "v8_enable_debugging_features = true",
                "v8_enable_debugging_features = false",
            ),
            (
                "v8_enable_verification_features = false",
                "v8_enable_verification_features = true",
                "v8_enable_verification_features = false",
            ),
            (
                "enable_chromium_wasm_content = false",
                "enable_chromium_wasm_content = true",
                "enable_chromium_wasm_content = false",
            ),
            (
                "enable_chromium_wasm_chrome = false",
                "enable_chromium_wasm_chrome = true",
                "enable_chromium_wasm_chrome = false",
            ),
        ):
            with self.subTest(replacement=replacement):
                data = manifest()
                profile = list(data[smoke.MANIFEST_KEY])
                profile[profile.index(existing)] = replacement
                data[smoke.MANIFEST_KEY] = profile
                with self.assertRaisesRegex(M0Error, expected):
                    smoke.validate_profile(data)

    def test_profile_binding_requires_exact_generated_args_and_module_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            data = manifest()
            out_dir, module, wasm = create_bound_output(temporary, data)
            self.assertEqual(
                smoke.verify_profile_binding(data, out_dir),
                (module.resolve(), wasm.resolve()),
            )

            (out_dir / "args.gn").write_text("v8_jitless = false\n", encoding="utf-8")
            with self.assertRaisesRegex(M0Error, "do not exactly match"):
                smoke.verify_profile_binding(data, out_dir)

    def test_profile_binding_rejects_missing_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            data = manifest()
            out_dir, _, wasm = create_bound_output(temporary, data)
            wasm.unlink()
            with self.assertRaisesRegex(M0Error, "Wasm sidecar"):
                smoke.verify_profile_binding(data, out_dir)


class M8V8Arm32CodegenRuntimeTest(unittest.TestCase):
    def test_runner_command_is_fixed_to_the_nested_v8_contract(self) -> None:
        command = smoke.runner_command(
            Path("/toolchain/node"), Path("/out/module.js"), 120_000
        )
        self.assertEqual(
            command,
            [
                "/toolchain/node",
                "--experimental-default-type=module",
                str(smoke.V8_RUNTIME_RUNNER),
                "--timeout-ms",
                "120000",
                "/out/module.js",
            ],
        )
        with self.assertRaisesRegex(M0Error, "outside"):
            smoke.runner_command(Path("node"), Path("module.js"), 600_001)

    def test_runtime_receipt_requires_one_exact_nested_runner_pass(self) -> None:
        module = Path("/out/module.js")
        wasm = Path("/out/module.wasm")
        receipt = smoke.validate_runtime_output(
            successful_runtime_output(module, wasm), "", module, wasm
        )
        self.assertEqual(receipt["stdoutLines"], 49)
        self.assertEqual(receipt["semanticSuite"], smoke.EXPECTED_SEMANTIC_SUITE)
        self.assertEqual(receipt["test262Cases"], 14)
        self.assertEqual(receipt["test262Executions"], 25)
        self.assertEqual(receipt["test262Profile"], smoke.EXPECTED_TEST262_PROFILE)

        malformed = successful_runtime_output(module, wasm).replace(
            '"onExitCount": 1', '"onExitCount": 2'
        )
        with self.assertRaisesRegex(M0Error, "disagrees"):
            smoke.validate_runtime_output(malformed, "", module, wasm)
        with self.assertRaisesRegex(M0Error, "stderr"):
            smoke.validate_runtime_output(
                successful_runtime_output(module, wasm), "unexpected", module, wasm
            )
        malformed_semantic_suite = successful_runtime_output(module, wasm).replace(
            smoke.EXPECTED_SEMANTIC_SUITE, "different_semantic_suite"
        )
        with self.assertRaisesRegex(M0Error, "disagrees"):
            smoke.validate_runtime_output(
                malformed_semantic_suite, "", module, wasm
            )
        malformed_test262_profile = successful_runtime_output(module, wasm).replace(
            smoke.EXPECTED_TEST262_PROFILE, "different_test262_profile"
        )
        with self.assertRaisesRegex(M0Error, "disagrees"):
            smoke.validate_runtime_output(
                malformed_test262_profile, "", module, wasm
            )

    def test_bounded_failure_receipt_preserves_only_valid_node_detail(self) -> None:
        expected = failed_runtime_output("unreachable").strip().removeprefix(
            smoke.NODE_FAIL_PREFIX
        )
        self.assertEqual(
            smoke.bounded_node_failure_receipt(failed_runtime_output("unreachable")),
            expected,
        )
        self.assertIsNone(
            smoke.bounded_node_failure_receipt(
                failed_runtime_output("x" * (smoke.MAX_NODE_FAILURE_RECEIPT_BYTES + 1))
            )
        )
        unicode_receipt = smoke.bounded_node_failure_receipt(
            failed_runtime_output("🦀" * 180)
        )
        self.assertIsNone(unicode_receipt)

    def test_run_smoke_binds_configuration_before_running_fixed_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            data = manifest()
            out_dir, module, wasm = create_bound_output(temporary, data)
            node = temporary / "node"
            node.write_bytes(b"node")
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=successful_runtime_output(module.resolve(), wasm.resolve()),
                stderr="",
            )
            with (
                mock.patch.object(smoke, "node_executable", return_value=node),
                mock.patch.object(smoke.subprocess, "run", return_value=completed) as run,
            ):
                result = smoke.run_smoke(out_dir, 120.0)

        self.assertEqual(result["status"], "pass")
        self.assertIs(result["m8GateComplete"], False)
        self.assertIs(result["v8ProvenanceEstablished"], False)
        self.assertEqual(
            result["runtime"]["semanticSuite"], smoke.EXPECTED_SEMANTIC_SUITE
        )
        self.assertEqual(result["runtime"]["test262Cases"], 14)
        self.assertEqual(result["runtime"]["test262Executions"], 25)
        self.assertEqual(
            result["runtime"]["test262Profile"], smoke.EXPECTED_TEST262_PROFILE
        )
        command = run.call_args.args[0]
        self.assertEqual(command[0], str(node))
        self.assertEqual(command[1:5], [
            "--experimental-default-type=module",
            str(smoke.V8_RUNTIME_RUNNER),
            "--timeout-ms",
            "120000",
        ])
        self.assertEqual(command[-1], str(module.resolve()))

    def test_run_smoke_reports_a_bounded_nested_node_failure_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            data = manifest()
            out_dir, _, _ = create_bound_output(temporary, data)
            node = temporary / "node"
            node.write_bytes(b"node")
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout=failed_runtime_output("unreachable"),
                stderr="untrusted process stderr",
            )
            with (
                mock.patch.object(smoke, "node_executable", return_value=node),
                mock.patch.object(smoke.subprocess, "run", return_value=completed),
            ):
                with self.assertRaisesRegex(
                    M0Error,
                    r'nested Node failure receipt=.*"reason":"runtime_aborted"',
                ) as raised:
                    smoke.run_smoke(out_dir, 120.0)

        self.assertNotIn("untrusted process stderr", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
