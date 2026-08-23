#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for package-byte-only native tab-churn evidence."""

from __future__ import annotations

import hashlib
import importlib
import io
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.request import urlopen

TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

import package
import run_m9_package_tab_churn_dom_smoke as runner
import run_m9_wasm_browser_tab_churn_dom_smoke as tab_churn
from m0_common import M0Error, load_manifest
from tools.wasm.tests.m3_source_contract_test_support import source


PORT_REVISION = "a" * 40


def byte_identity(contents: bytes) -> dict[str, object]:
    return {"bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}


class M9PackageTabChurnDomSmokeTest(unittest.TestCase):
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
        exports = "\n".join(
            (
                'Module["_chromium_wasm_browser_host_pointer"]',
                'Module["_chromium_wasm_browser_host_pointer_exit"]',
                'Module["_chromium_wasm_browser_host_tab_churn_check"]',
                'Module["_chromium_wasm_browser_host_tab_churn_presented"]',
                'Module["_malloc"]',
                'Module["_free"]',
                'Module["ccall"]',
                'Module["HEAPU8"]',
                'Module["_chromium_wasm_browser_host_memory_linear_capacity_bytes"]',
                'Module["_chromium_wasm_browser_host_memory_linear_maximum_bytes"]',
                (
                    'Module["_chromium_wasm_browser_host_memory_page_allocator_'
                    'total_mapped_bytes"]'
                ),
            )
        )
        (out_dir / "chrome_wasm.js").write_text(
            'const wasm = "chrome_wasm.wasm";\n'
            + exports
            + "\nexport default async function() { return {wasm}; }\n",
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

    def _snapshot(self) -> runner.PackageTabChurnSnapshot:
        return runner.capture_package_tab_churn_snapshot(self.dist_dir)

    def _host_dir(self) -> Path:
        host_dir = self.root / "tab-churn-host"
        host_dir.mkdir()
        (host_dir / "chrome_wasm_browser_tab_churn_smoke.html").write_text(
            "<html>test host</html>\n", encoding="utf-8"
        )
        (
            host_dir / "chrome_wasm_browser_tab_churn_smoke_host.js"
        ).write_text("export const host = true;\n", encoding="utf-8")
        (host_dir / "chrome_wasm_pointer_input.js").write_text(
            "export const pointer = true;\n", encoding="utf-8"
        )
        return host_dir

    def test_capture_uses_verified_public_package_bytes_and_false_gate_metadata(self) -> None:
        snapshot = self._snapshot()
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
        self.assertEqual(package.EXPECTED_GATE_STATE, snapshot.runtime_metadata["gateState"])
        self.assertEqual(package.RELEASE_STATUS, snapshot.runtime_metadata["releaseStatus"])
        self.assertEqual(
            runner.PACKAGE_ARTIFACT_DELIVERY,
            snapshot.artifact_identity["artifact_delivery"],
        )
        self.assertEqual(
            runner.PUBLIC_MODULE_NAME, snapshot.artifact_identity["public_module_name"]
        )
        self.assertEqual(
            runner.PRIVATE_MODULE_NAME, snapshot.artifact_identity["private_module_name"]
        )
        self.assertEqual(
            byte_identity(snapshot.artifact.loader), snapshot.artifact_identity["loader"]
        )
        self.assertEqual(
            byte_identity(snapshot.artifact.wasm), snapshot.artifact_identity["wasm"]
        )
        self.assertEqual(
            {
                "chromium": self.manifest["chromium"]["revision"],
                "v8": self.manifest["git_dependencies"]["v8"]["revision"],
                "emscripten": self.manifest["emscripten"]["source_revision"],
            },
            runner._runtime_versions(snapshot.runtime_metadata),
        )

    def test_capture_rejects_a_staged_package_mutated_after_packaging(self) -> None:
        (self.dist_dir / "chromium-wasm.wasm").write_bytes(b"mutated package wasm")

        with self.assertRaisesRegex(M0Error, "hash mismatch"):
            self._snapshot()

    def test_server_serves_only_private_in_memory_aliases_of_package_bytes(self) -> None:
        snapshot = self._snapshot()
        host_dir = self._host_dir()
        runner_source = self.root / "package-tab-churn-runner.py"
        runner_source.write_text("# runner snapshot\n", encoding="utf-8")
        server = runner.create_package_tab_churn_server(
            "127.0.0.1",
            0,
            snapshot,
            "token",
            queue.Queue(maxsize=1),
            host_dir=host_dir,
            runner_source_path=runner_source,
        )
        try:
            self.assertEqual(
                {"chrome_wasm.js", "chrome_wasm.wasm"}, set(server.artifacts)
            )
            self.assertEqual(snapshot.artifact.loader, server.artifacts["chrome_wasm.js"])
            self.assertEqual(snapshot.artifact.wasm, server.artifacts["chrome_wasm.wasm"])
            (self.dist_dir / "chromium-wasm.js").write_bytes(b"mutated after capture")
            self.assertEqual(snapshot.artifact.loader, server.artifacts["chrome_wasm.js"])
        finally:
            server.server_close()

    def test_server_aliases_keep_wasm_mime_and_required_isolation_headers(self) -> None:
        snapshot = self._snapshot()
        server = runner.create_package_tab_churn_server(
            "127.0.0.1", 0, snapshot, "token", queue.Queue(maxsize=1)
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.server_address[:2]
            with urlopen(
                f"http://{host}:{port}{tab_churn.HOST_ROOT}/artifacts/chrome_wasm.js",
                timeout=5,
            ) as response:
                self.assertEqual("text/javascript", response.headers.get_content_type())
                self.assertEqual(snapshot.artifact.loader, response.read())
                self.assertEqual(
                    "same-origin", response.headers["Cross-Origin-Opener-Policy"]
                )
                self.assertEqual(
                    "require-corp", response.headers["Cross-Origin-Embedder-Policy"]
                )
            with urlopen(
                f"http://{host}:{port}{tab_churn.HOST_ROOT}/artifacts/chrome_wasm.wasm",
                timeout=5,
            ) as response:
                self.assertEqual("application/wasm", response.headers.get_content_type())
                self.assertEqual(snapshot.artifact.wasm, response.read())
            with self.assertRaises(HTTPError) as error:
                urlopen(
                    f"http://{host}:{port}{tab_churn.HOST_ROOT}/artifacts/"
                    "chromium-wasm.js",
                    timeout=5,
                )
            self.assertEqual(404, error.exception.code)
            error.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            server.join_request_handlers(
                timeout=5, description="package tab-churn test server"
            )
        self.assertFalse(thread.is_alive())

    def test_result_binds_package_metadata_and_private_aliases_before_child_validation(
        self,
    ) -> None:
        snapshot = self._snapshot()
        alias_identity = {
            "artifact_delivery": tab_churn.ARTIFACT_DELIVERY,
            "artifact_source_provenance": tab_churn.ARTIFACT_SOURCE_PROVENANCE,
            "loader": dict(snapshot.artifact_identity["loader"]),
            "module_name": runner.PRIVATE_MODULE_NAME,
            "wasm": dict(snapshot.artifact_identity["wasm"]),
        }
        harness = {
            "host_html": {"bytes": 1, "sha256": "a" * 64},
            "host_js": {"bytes": 1, "sha256": "b" * 64},
            "pointer_input_js": {"bytes": 1, "sha256": "c" * 64},
            "runner_source": {"bytes": 1, "sha256": "d" * 64},
            "source_snapshot_provenance": tab_churn.SOURCE_SNAPSHOT_PROVENANCE,
            "version_provenance": tab_churn.VERSION_PROVENANCE,
        }
        child = {"opaque": "existing-tab-churn-result"}
        result = runner.package_tab_churn_result(child, snapshot)

        with mock.patch.object(runner.tab_churn, "validate_result") as validate_child:
            self.assertEqual(
                result,
                runner.validate_package_tab_churn_result(
                    result,
                    expected_snapshot=snapshot,
                    expected_alias_identity=alias_identity,
                    expected_capture_harness_identity=harness,
                    expected_pointer_abi_rejection_seed=False,
                ),
            )

        validate_child.assert_called_once_with(
            child,
            expected_versions=runner._runtime_versions(snapshot.runtime_metadata),
            expected_artifact_identity=alias_identity,
            expected_capture_harness_identity=harness,
            expected_pointer_abi_rejection_seed=False,
        )

        mutations = (
            (
                lambda value: value["packageArtifact"]["loader"].__setitem__(
                    "sha256", "f" * 64
                ),
                "artifact identity",
            ),
            (
                lambda value: value["packageRuntimeMetadata"]["gateState"].__setitem__(
                    "m8_complete", True
                ),
                "runtime metadata",
            ),
            (
                lambda value: value.__setitem__("m9GateComplete", True),
                "must not complete M9",
            ),
            (
                lambda value: value.__setitem__("releaseStatus", "release"),
                "release status",
            ),
        )
        for mutate, expression in mutations:
            with self.subTest(expression=expression):
                invalid = json.loads(json.dumps(result))
                mutate(invalid)
                with mock.patch.object(runner.tab_churn, "validate_result"):
                    with self.assertRaisesRegex(M0Error, expression):
                        runner.validate_package_tab_churn_result(
                            invalid,
                            expected_snapshot=snapshot,
                            expected_alias_identity=alias_identity,
                            expected_capture_harness_identity=harness,
                            expected_pointer_abi_rejection_seed=False,
                        )

        mismatched_alias = json.loads(json.dumps(alias_identity))
        mismatched_alias["wasm"]["sha256"] = "f" * 64
        with mock.patch.object(runner.tab_churn, "validate_result"):
            with self.assertRaisesRegex(M0Error, "private alias"):
                runner.validate_package_tab_churn_result(
                    result,
                    expected_snapshot=snapshot,
                    expected_alias_identity=mismatched_alias,
                    expected_capture_harness_identity=harness,
                    expected_pointer_abi_rejection_seed=False,
                )

    def test_runner_accepts_only_a_package_directory_and_never_selects_raw_output(self) -> None:
        runner_source = source("tools/wasm/run_m9_package_tab_churn_dom_smoke.py")
        self.assertIn('parser.add_argument("--dist-dir", type=Path, required=True)', runner_source)
        self.assertNotIn('parser.add_argument("--out-dir"', runner_source)
        self.assertNotIn("check_boundary(", runner_source)
        self.assertNotIn("load_manifest(", runner_source)
        self.assertIn("capture_package_lifecycle_snapshot(dist_dir)", runner_source)
        self.assertIn("create_server_from_artifacts", runner_source)
        self.assertIn("verified-package-module-bytes", runner_source)
        self.assertIn("does_not_complete_m9_reliability_or_release_gates", runner_source)

    def test_main_rejects_an_out_dir_argument_before_any_package_capture(self) -> None:
        stderr = tempfile.SpooledTemporaryFile(mode="w+t")
        try:
            with (
                mock.patch.object(runner, "capture_package_tab_churn_snapshot") as capture,
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "package-tab-churn",
                        "--dist-dir",
                        str(self.dist_dir),
                        "--out-dir",
                        str(self.out_dir),
                    ],
                ),
                mock.patch.object(runner.sys, "stderr", stderr),
                self.assertRaises(SystemExit),
            ):
                runner.main()
            capture.assert_not_called()
            stderr.seek(0)
            self.assertIn("unrecognized arguments: --out-dir", stderr.read())
        finally:
            stderr.close()

    def test_package_mode_normalizes_shared_tab_churn_m0_error(self) -> None:
        package_runner = importlib.import_module(
            "tools.wasm.run_m9_package_tab_churn_dom_smoke"
        )
        package_tab_churn = importlib.import_module(
            "tools.wasm.run_m9_wasm_browser_tab_churn_dom_smoke"
        )
        self.assertIs(package_tab_churn, package_runner.tab_churn)
        self.assertIsNot(package_runner.M0Error, package_tab_churn.M0Error)
        stderr = io.StringIO()
        with (
            mock.patch.object(
                package_runner,
                "capture_package_tab_churn_snapshot",
                side_effect=package_tab_churn.M0Error("package-mode shared failure"),
            ),
            mock.patch.object(
                package_runner,
                "write_failure_diagnostics",
                return_value=Path("/tmp/package-tab-churn-diagnostics.json"),
            ),
            mock.patch.object(
                package_runner.sys,
                "argv",
                ["package-tab-churn", "--dist-dir", str(self.dist_dir)],
            ),
            mock.patch.object(package_runner.sys, "stderr", stderr),
        ):
            self.assertEqual(1, package_runner.main())

        self.assertIn("package-mode shared failure", stderr.getvalue())

    def test_package_mode_normalizes_shared_find_browser_m0_error(self) -> None:
        package_runner = importlib.import_module(
            "tools.wasm.run_m9_package_tab_churn_dom_smoke"
        )
        package_browser_smoke = importlib.import_module(
            "tools.wasm.run_browser_smoke"
        )
        package_snapshot = package_runner.capture_package_tab_churn_snapshot(
            self.dist_dir
        )
        alias_identity = {
            "loader": dict(package_snapshot.artifact_identity["loader"]),
            "wasm": dict(package_snapshot.artifact_identity["wasm"]),
        }
        server = mock.Mock()
        server.artifacts = {"chrome_wasm.js": b"test loader"}

        self.assertIsNot(package_runner.M0Error, package_browser_smoke.M0Error)
        self.assertIs(package_runner.tab_churn.M0Error, package_browser_smoke.M0Error)
        stderr = io.StringIO()
        stdout = io.StringIO()
        with (
            mock.patch.object(
                package_runner,
                "capture_package_tab_churn_snapshot",
                return_value=package_snapshot,
            ),
            mock.patch.object(
                package_runner,
                "create_package_tab_churn_server",
                return_value=server,
            ),
            mock.patch.object(
                package_runner.tab_churn,
                "artifact_identity",
                return_value=alias_identity,
            ),
            mock.patch.object(
                package_runner.tab_churn,
                "capture_harness_identity",
                return_value={},
            ),
            mock.patch.object(package_runner.tab_churn, "verify_required_exports"),
            mock.patch.object(
                package_runner,
                "find_browser",
                side_effect=package_browser_smoke.M0Error(
                    "package-mode browser discovery failure"
                ),
            ),
            mock.patch.object(
                package_runner,
                "write_failure_diagnostics",
                return_value=Path("/tmp/package-tab-churn-diagnostics.json"),
            ) as write_diagnostics,
            mock.patch.object(
                package_runner.sys,
                "argv",
                ["package-tab-churn", "--dist-dir", str(self.dist_dir)],
            ),
            mock.patch.object(package_runner.sys, "stderr", stderr),
            mock.patch.object(package_runner.sys, "stdout", stdout),
        ):
            self.assertEqual(1, package_runner.main())

        self.assertEqual("find_browser", write_diagnostics.call_args.kwargs["stage"])
        self.assertIsInstance(
            write_diagnostics.call_args.kwargs["error"], package_browser_smoke.M0Error
        )
        self.assertIn("package-mode browser discovery failure", stderr.getvalue())
        server.server_close.assert_called_once_with()
        server.join_request_handlers.assert_called_once_with(
            timeout=1, description="M9 package tab-churn server"
        )

    def test_shared_server_factory_rejects_nonprivate_or_empty_captured_artifacts(self) -> None:
        with self.assertRaisesRegex(M0Error, "artifact names"):
            tab_churn.create_server_from_artifacts(
                "127.0.0.1",
                0,
                {"chrome_wasm.js": b"loader"},
                "token",
                queue.Queue(maxsize=1),
                module_name="chrome_wasm",
            )
        with self.assertRaisesRegex(M0Error, "artifact bytes"):
            tab_churn.create_server_from_artifacts(
                "127.0.0.1",
                0,
                {"chrome_wasm.js": b"loader", "chrome_wasm.wasm": b""},
                "token",
                queue.Queue(maxsize=1),
                module_name="chrome_wasm",
            )


if __name__ == "__main__":
    unittest.main()
