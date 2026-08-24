#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for package-byte-only repeating-timer evidence.

The package wrapper is deliberately separate from the public pre-release host:
it may map verified public package bytes to private immutable test-host aliases,
but it must never turn the package into a release claim or expose a timer
control API through the public package index.
"""

from __future__ import annotations

import contextlib
from dataclasses import replace
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
import run_m9_package_repeating_timer_dom_smoke as runner
import run_m9_wasm_browser_repeating_timer_dom_smoke as repeating_timer
from m0_common import M0Error, load_manifest
from tools.wasm.tests.m3_source_contract_test_support import source


PORT_REVISION = "a" * 40


def byte_identity(contents: bytes) -> dict[str, object]:
    return {"bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}


class M9PackageRepeatingTimerDomSmokeTest(unittest.TestCase):
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

    def _snapshot(self) -> object:
        return runner.capture_package_repeating_timer_snapshot(self.dist_dir)

    def _host_dir(self) -> Path:
        host_dir = self.root / "repeating-timer-host"
        host_dir.mkdir()
        (host_dir / "chrome_wasm_browser_m9_repeating_timer_smoke.html").write_text(
            "<html>test host</html>\n", encoding="utf-8"
        )
        (
            host_dir / "chrome_wasm_browser_m9_repeating_timer_smoke.js"
        ).write_text("export const host = true;\n", encoding="utf-8")
        return host_dir

    def _alias_identity(self, snapshot: object) -> dict[str, object]:
        artifact_identity = snapshot.artifact_identity
        build = snapshot.runtime_metadata["build"]
        return {
            "artifact_delivery": runner.PACKAGE_ARTIFACT_DELIVERY,
            "artifact_source_provenance": build["artifactSourceProvenance"],
            "loader": dict(artifact_identity["loader"]),
            "module_name": runner.PRIVATE_MODULE_NAME,
            "wasm": dict(artifact_identity["wasm"]),
        }

    def _capture_harness_identity(self) -> dict[str, object]:
        return {
            "host_html": {"bytes": 1, "sha256": "a" * 64},
            "host_js": {"bytes": 1, "sha256": "b" * 64},
            "runner_source": {"bytes": 1, "sha256": "c" * 64},
            "source_snapshot_provenance": repeating_timer.SOURCE_SNAPSHOT_PROVENANCE,
            "version_provenance": runner.PACKAGE_VERSION_PROVENANCE,
        }

    def test_capture_uses_verified_public_package_bytes_and_false_gate_metadata(
        self,
    ) -> None:
        snapshot = self._snapshot()
        version_bytes = (self.dist_dir / "VERSION.json").read_bytes()

        self.assertIsInstance(snapshot, runner.PackageRepeatingTimerSnapshot)
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
            runner.PRIVATE_MODULE_NAME,
            snapshot.artifact_identity["private_module_name"],
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
                "port": PORT_REVISION,
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
        runner_source = self.root / "package-repeating-timer-runner.py"
        runner_source.write_text("# runner snapshot\n", encoding="utf-8")
        server = runner.create_package_repeating_timer_server(
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

    def test_server_rejects_forged_snapshot_bytes_before_alias_materialization(
        self,
    ) -> None:
        snapshot = self._snapshot()
        for field, replacement in (
            ("loader", b"forged package loader"),
            ("wasm", b"forged package wasm"),
        ):
            with self.subTest(field=field):
                forged = replace(
                    snapshot,
                    artifact=replace(snapshot.artifact, **{field: replacement}),
                )
                with mock.patch.object(
                    runner.timer, "create_server_from_artifacts"
                ) as create_server:
                    with self.assertRaises(M0Error):
                        runner.create_package_repeating_timer_server(
                            "127.0.0.1",
                            0,
                            forged,
                            "token",
                            queue.Queue(maxsize=1),
                        )
                create_server.assert_not_called()

    def test_server_aliases_keep_wasm_mime_and_required_isolation_headers(self) -> None:
        snapshot = self._snapshot()
        server = runner.create_package_repeating_timer_server(
            "127.0.0.1", 0, snapshot, "token", queue.Queue(maxsize=1)
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.server_address[:2]
            with urlopen(
                f"http://{host}:{port}{repeating_timer.HOST_ROOT}/artifacts/chrome_wasm.js",
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
                f"http://{host}:{port}{repeating_timer.HOST_ROOT}/artifacts/chrome_wasm.wasm",
                timeout=5,
            ) as response:
                self.assertEqual("application/wasm", response.headers.get_content_type())
                self.assertEqual(snapshot.artifact.wasm, response.read())
            with self.assertRaises(HTTPError) as error:
                urlopen(
                    f"http://{host}:{port}{repeating_timer.HOST_ROOT}/artifacts/"
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
                timeout=5, description="package repeating-timer test server"
            )
        self.assertFalse(thread.is_alive())

    def test_result_binds_package_metadata_and_private_aliases_before_child_validation(
        self,
    ) -> None:
        snapshot = self._snapshot()
        alias_identity = self._alias_identity(snapshot)
        harness = self._capture_harness_identity()
        child = {"opaque": "existing-repeating-timer-result"}
        result = runner.package_repeating_timer_result(child, snapshot)
        self.assertEqual(
            {
                "m9GateComplete",
                "packageArtifact",
                "packageRuntimeMetadata",
                "releaseStatus",
                "scope",
                "repeatingTimer",
            },
            set(result),
        )
        self.assertEqual(child, result["repeatingTimer"])

        with mock.patch.object(
            runner.repeating_timer, "validate_result"
        ) as validate_child:
            self.assertEqual(
                result,
                runner.validate_package_repeating_timer_result(
                    result,
                    expected_snapshot=snapshot,
                    expected_alias_identity=alias_identity,
                    expected_capture_harness_identity=harness,
                ),
            )

        validate_child.assert_called_once_with(
            child,
            expected_versions=runner._runtime_versions(snapshot.runtime_metadata),
            expected_artifact_identity=alias_identity,
            expected_capture_harness_identity=harness,
            expected_artifact_delivery=runner.PACKAGE_ARTIFACT_DELIVERY,
            expected_artifact_source_provenance=snapshot.runtime_metadata["build"][
                "artifactSourceProvenance"
            ],
            expected_version_provenance=runner.PACKAGE_VERSION_PROVENANCE,
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
                with mock.patch.object(runner.repeating_timer, "validate_result"):
                    with self.assertRaisesRegex(M0Error, expression):
                        runner.validate_package_repeating_timer_result(
                            invalid,
                            expected_snapshot=snapshot,
                            expected_alias_identity=alias_identity,
                            expected_capture_harness_identity=harness,
                        )

        mismatched_alias = json.loads(json.dumps(alias_identity))
        mismatched_alias["wasm"]["sha256"] = "f" * 64
        with mock.patch.object(runner.repeating_timer, "validate_result"):
            with self.assertRaisesRegex(M0Error, "private alias"):
                runner.validate_package_repeating_timer_result(
                    result,
                    expected_snapshot=snapshot,
                    expected_alias_identity=mismatched_alias,
                    expected_capture_harness_identity=harness,
                )

    def test_stress_wrapper_retains_package_bytes_and_fixed_child_mode(self) -> None:
        snapshot = self._snapshot()
        alias_identity = self._alias_identity(snapshot)
        harness = self._capture_harness_identity()
        config = repeating_timer.STRESS_100_TICKS_TIMER_SMOKE_CONFIG
        child = {"opaque": "one-hundred-fixed-timer-result"}
        result = runner.package_repeating_timer_result(
            child, snapshot, config=config
        )
        self.assertEqual(runner.STRESS_100_TICKS_SCOPE, result["scope"])
        self.assertFalse(result["m9GateComplete"])
        self.assertEqual(snapshot.artifact_identity, result["packageArtifact"])

        with mock.patch.object(
            runner.repeating_timer, "validate_result"
        ) as validate_child:
            self.assertEqual(
                result,
                runner.validate_package_repeating_timer_result(
                    result,
                    expected_snapshot=snapshot,
                    expected_alias_identity=alias_identity,
                    expected_capture_harness_identity=harness,
                    config=config,
                ),
            )
        self.assertEqual(config, validate_child.call_args.kwargs["config"])
        self.assertEqual(child, validate_child.call_args.args[0])

        result["scope"] = runner.SCOPE
        with mock.patch.object(runner.repeating_timer, "validate_result"):
            with self.assertRaisesRegex(M0Error, "result scope"):
                runner.validate_package_repeating_timer_result(
                    result,
                    expected_snapshot=snapshot,
                    expected_alias_identity=alias_identity,
                    expected_capture_harness_identity=harness,
                    config=config,
                )

    def test_wrapper_retains_timer_and_pre_release_limitations(self) -> None:
        runner_source = source(
            "tools/wasm/run_m9_package_repeating_timer_dom_smoke.py"
        )
        self.assertIn(
            'parser.add_argument("--dist-dir", type=Path, required=True)',
            runner_source,
        )
        self.assertNotIn('parser.add_argument("--out-dir"', runner_source)
        self.assertNotIn("check_boundary(", runner_source)
        self.assertNotIn("load_manifest(", runner_source)
        for expected in (
            "capture_package_lifecycle_snapshot(dist_dir)",
            "verified-package-module-bytes",
            "does_not_complete_m9_reliability_or_release_gates",
            "does_not_prove_m7_persistent_profile_or_recovery",
            "does_not_prove_m8_feature_compatibility_or_page_webassembly",
            "m9GateComplete\": False",
            "--stress-100-ticks",
            "STRESS_100_TICKS_SCOPE",
            "STRESS_100_MINIMUM_TIMEOUT_SECONDS",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, runner_source)
        self.assertIn(
            "does_not_measure_long_run_timer_reliability", runner.LIMITATIONS
        )

    def test_main_rejects_an_out_dir_argument_before_any_package_capture(self) -> None:
        stderr = tempfile.SpooledTemporaryFile(mode="w+t")
        try:
            with (
                mock.patch.object(
                    runner, "capture_package_repeating_timer_snapshot"
                ) as capture,
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "package-repeating-timer",
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

    def test_main_rejects_package_timeouts_that_cannot_preserve_child_minimum(
        self,
    ) -> None:
        for timeout in ("2", "2.5"):
            with self.subTest(timeout=timeout):
                stderr = tempfile.SpooledTemporaryFile(mode="w+t")
                try:
                    with (
                        mock.patch.object(
                            runner, "capture_package_repeating_timer_snapshot"
                        ) as capture,
                        mock.patch.object(
                            sys,
                            "argv",
                            [
                                "package-repeating-timer",
                                "--dist-dir",
                                str(self.dist_dir),
                                "--timeout",
                                timeout,
                            ],
                        ),
                        mock.patch.object(runner.sys, "stderr", stderr),
                        self.assertRaises(SystemExit) as failure,
                    ):
                        runner.main()
                    self.assertEqual(2, failure.exception.code)
                    capture.assert_not_called()
                    stderr.seek(0)
                    self.assertIn(
                        "--timeout must be at least three seconds", stderr.read()
                    )
                finally:
                    stderr.close()

    def test_main_requires_thirty_seconds_for_package_stress_mode(self) -> None:
        stderr = tempfile.SpooledTemporaryFile(mode="w+t")
        try:
            with (
                mock.patch.object(
                    runner, "capture_package_repeating_timer_snapshot"
                ) as capture,
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "package-repeating-timer",
                        "--dist-dir",
                        str(self.dist_dir),
                        "--stress-100-ticks",
                        "--timeout",
                        "29",
                    ],
                ),
                mock.patch.object(runner.sys, "stderr", stderr),
                self.assertRaises(SystemExit) as failure,
            ):
                runner.main()
            self.assertEqual(2, failure.exception.code)
            capture.assert_not_called()
            stderr.seek(0)
            self.assertIn(
                "--stress-100-ticks requires --timeout of at least 30 seconds",
                stderr.read(),
            )
        finally:
            stderr.close()

    def test_package_mode_normalizes_shared_timer_m0_error(self) -> None:
        package_runner = importlib.import_module(
            "tools.wasm.run_m9_package_repeating_timer_dom_smoke"
        )
        package_timer = importlib.import_module(
            "tools.wasm.run_m9_wasm_browser_repeating_timer_dom_smoke"
        )
        self.assertIs(package_timer, package_runner.timer)
        self.assertIsNot(package_runner.M0Error, package_timer.M0Error)

        stderr = io.StringIO()
        with (
            mock.patch.object(
                package_runner,
                "capture_package_repeating_timer_snapshot",
                side_effect=package_timer.M0Error("package-mode shared failure"),
            ),
            mock.patch.object(
                package_runner,
                "write_failure_diagnostics",
                return_value=Path("/tmp/package-repeating-timer-diagnostics.json"),
            ),
            mock.patch.object(
                package_runner.sys,
                "argv",
                ["package-repeating-timer", "--dist-dir", str(self.dist_dir)],
            ),
            mock.patch.object(package_runner.sys, "stderr", stderr),
        ):
            self.assertEqual(1, package_runner.main())

        self.assertIn("package-mode shared failure", stderr.getvalue())

    def test_main_aborts_browser_group_when_stderr_reader_does_not_start(
        self,
    ) -> None:
        snapshot = self._snapshot()
        server = mock.Mock()
        server_thread = mock.Mock()
        stderr_thread = mock.Mock()
        stderr_thread.start.side_effect = RuntimeError("stderr reader start failed")
        browser = mock.Mock()
        browser.stderr = object()
        profile = mock.Mock()
        profile.name = "/tmp/m9-package-repeating-timer-profile"

        with (
            mock.patch.object(
                runner,
                "capture_package_repeating_timer_snapshot",
                return_value=snapshot,
            ),
            mock.patch.object(
                runner, "create_package_repeating_timer_server", return_value=server
            ),
            mock.patch.object(runner, "_timer_alias_identity", return_value={}),
            mock.patch.object(
                runner.timer, "capture_harness_identity", return_value={}
            ),
            mock.patch.object(
                runner,
                "find_browser",
                return_value=(Path("/fake/browser"), "test-browser"),
            ),
            mock.patch.object(
                runner.timer, "smoke_url", return_value="http://127.0.0.1:12345/"
            ),
            mock.patch.object(
                runner.tempfile, "TemporaryDirectory", return_value=profile
            ),
            mock.patch.object(
                runner,
                "browser_command",
                return_value=["/fake/browser", "profile", "url"],
            ),
            mock.patch.object(runner.subprocess, "Popen", return_value=browser),
            mock.patch.object(
                runner.threading, "Thread", side_effect=[server_thread, stderr_thread]
            ),
            mock.patch.object(runner.timer, "_cleanup_repeating_timer_server"),
            mock.patch.object(runner, "abort_browser_group") as abort_browser_group,
            mock.patch.object(
                sys,
                "argv",
                ["package-repeating-timer", "--dist-dir", str(self.dist_dir)],
            ),
            mock.patch.object(runner.sys, "stdout", io.StringIO()),
            self.assertRaisesRegex(RuntimeError, "stderr reader start failed"),
        ):
            runner.main()

        server_thread.start.assert_called_once_with()
        abort_browser_group.assert_called_once_with(
            browser, mock.ANY, unowned_streams=()
        )
        stderr_thread.join.assert_not_called()
        profile.cleanup.assert_called_once_with()

    def test_main_never_reports_success_when_browser_or_server_cleanup_fails(
        self,
    ) -> None:
        snapshot = self._snapshot()
        for name, browser_cleanup_error, server_cleanup_error in (
            ("browser group", M0Error("browser group cleanup failed"), None),
            ("server", None, M0Error("server cleanup failed")),
        ):
            with self.subTest(name=name):
                server = mock.Mock()
                server_thread = mock.Mock()
                stderr_thread = mock.Mock()
                browser = mock.Mock()
                browser.stderr = object()
                profile = mock.Mock()
                profile.name = "/tmp/m9-package-repeating-timer-profile"
                stdout = io.StringIO()
                stderr = io.StringIO()

                with contextlib.ExitStack() as stack:
                    stack.enter_context(
                        mock.patch.object(
                            runner,
                            "capture_package_repeating_timer_snapshot",
                            return_value=snapshot,
                        )
                    )
                    stack.enter_context(
                        mock.patch.object(
                            runner,
                            "create_package_repeating_timer_server",
                            return_value=server,
                        )
                    )
                    stack.enter_context(
                        mock.patch.object(
                            runner, "_timer_alias_identity", return_value={}
                        )
                    )
                    stack.enter_context(
                        mock.patch.object(
                            runner.timer, "capture_harness_identity", return_value={}
                        )
                    )
                    stack.enter_context(
                        mock.patch.object(
                            runner,
                            "find_browser",
                            return_value=(Path("/fake/browser"), "test-browser"),
                        )
                    )
                    stack.enter_context(
                        mock.patch.object(
                            runner.timer,
                            "smoke_url",
                            return_value="http://127.0.0.1:12345/",
                        )
                    )
                    stack.enter_context(
                        mock.patch.object(
                            runner.tempfile, "TemporaryDirectory", return_value=profile
                        )
                    )
                    stack.enter_context(
                        mock.patch.object(
                            runner,
                            "browser_command",
                            return_value=["/fake/browser", "profile", "url"],
                        )
                    )
                    stack.enter_context(
                        mock.patch.object(
                            runner.subprocess, "Popen", return_value=browser
                        )
                    )
                    stack.enter_context(
                        mock.patch.object(
                            runner.threading,
                            "Thread",
                            side_effect=[server_thread, stderr_thread],
                        )
                    )
                    stack.enter_context(
                        mock.patch.object(
                            runner.timer,
                            "wait_for_result",
                            return_value={"opaque": "runtime result"},
                        )
                    )
                    stack.enter_context(
                        mock.patch.object(
                            runner, "validate_package_repeating_timer_result"
                        )
                    )
                    stop_browser_group = stack.enter_context(
                        mock.patch.object(
                            runner,
                            "stop_browser_group",
                            side_effect=browser_cleanup_error,
                        )
                    )
                    cleanup_server = stack.enter_context(
                        mock.patch.object(
                            runner.timer,
                            "_cleanup_repeating_timer_server",
                            return_value=server_cleanup_error,
                        )
                    )
                    stack.enter_context(
                        mock.patch.object(
                            runner,
                            "write_failure_diagnostics",
                            return_value=Path("diagnostics.json"),
                        )
                    )
                    stack.enter_context(
                        mock.patch.object(
                            sys,
                            "argv",
                            [
                                "package-repeating-timer",
                                "--dist-dir",
                                str(self.dist_dir),
                            ],
                        )
                    )
                    stack.enter_context(mock.patch.object(runner.sys, "stdout", stdout))
                    stack.enter_context(mock.patch.object(runner.sys, "stderr", stderr))

                    self.assertEqual(1, runner.main())

                self.assertNotIn(runner.RESULT_PREFIX, stdout.getvalue())
                self.assertNotIn(runner.PASS_MARKER, stdout.getvalue())
                stop_browser_group.assert_called_once_with(browser, mock.ANY)
                cleanup_server.assert_called_once_with(
                    server=server,
                    server_thread=server_thread,
                    server_thread_started=True,
                )
                server_thread.start.assert_called_once_with()
                profile.cleanup.assert_called_once_with()

if __name__ == "__main__":
    unittest.main()
