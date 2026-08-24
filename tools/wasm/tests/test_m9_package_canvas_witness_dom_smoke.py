#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for public-package Canvas2D backing-store evidence."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

import package
import run_m9_package_browser_smoke as package_browser
import run_m9_package_canvas_witness_dom_smoke as runner
import run_m9_package_smoke as package_smoke
from m0_common import M0Error, load_manifest
from tools.wasm.tests.m3_source_contract_test_support import source


PORT_REVISION = "a" * 40


def byte_identity(contents: bytes) -> dict[str, object]:
    return {"bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}


def pixel_witness(
    *, nonblack_rgb_sample_count: int = 0, distinct_rgb_value_count: int = 1
) -> dict[str, object]:
    columns = runner.CANVAS_PIXEL_WITNESS_GRID_COLUMNS
    rows = runner.CANVAS_PIXEL_WITNESS_GRID_ROWS
    return {
        "definition": runner.CANVAS_PIXEL_WITNESS_DEFINITION,
        "distinct_rgb_value_count": distinct_rgb_value_count,
        "non_black_rgb_sample_count": nonblack_rgb_sample_count,
        "sample_count": columns * rows,
        "sample_grid_columns": columns,
        "sample_grid_rows": rows,
        "visible_pixels_observed": nonblack_rgb_sample_count != 0,
    }


def backing_store_witness(
    *,
    frames_presented_at_observation: int = 7,
    nonblack_rgb_sample_count: int = 0,
    distinct_rgb_value_count: int = 1,
) -> dict[str, object]:
    return {
        "acknowledgement": runner.WITNESS_ACKNOWLEDGEMENT,
        "canvas_backing_store_height": 600,
        "canvas_backing_store_width": 800,
        "frames_presented_at_observation": frames_presented_at_observation,
        "witness": pixel_witness(
            nonblack_rgb_sample_count=nonblack_rgb_sample_count,
            distinct_rgb_value_count=distinct_rgb_value_count,
        ),
    }


class FakeClient:
    def __init__(self, value: object) -> None:
        self.value = value
        self.expressions: list[str] = []

    def evaluate(self, expression: str) -> object:
        self.expressions.append(expression)
        return self.value


class M9PackageCanvasWitnessDomSmokeTest(unittest.TestCase):
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

    def _server(self) -> object:
        return package_smoke.create_package_smoke_server("127.0.0.1", 0, self.dist_dir)

    def _snapshot(self) -> runner.PackageCanvasWitnessSnapshot:
        server = self._server()
        try:
            return runner.capture_package_canvas_witness_snapshot(server)
        finally:
            server.server_close()

    def test_capture_uses_verified_public_package_tree_and_false_gates(self) -> None:
        server = self._server()
        try:
            snapshot = runner.capture_package_canvas_witness_snapshot(server)
            artifacts = server.snapshot.artifacts
            version_bytes = artifacts["VERSION.json"]

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
                artifacts["index.html"], (self.dist_dir / "index.html").read_bytes()
            )
            self.assertEqual(
                byte_identity(artifacts["index.html"]),
                snapshot.artifact_identity["index_html"],
            )
            self.assertEqual(
                byte_identity(artifacts["chromium-wasm-host.js"]),
                snapshot.artifact_identity["host_js"],
            )
            self.assertEqual(
                byte_identity(artifacts["chromium-wasm.js"]),
                snapshot.artifact_identity["loader"],
            )
            self.assertEqual(
                byte_identity(artifacts["chromium-wasm.wasm"]),
                snapshot.artifact_identity["wasm"],
            )
            self.assertEqual(
                byte_identity(version_bytes), snapshot.artifact_identity["version_json"]
            )
            self.assertEqual(
                runner.PUBLIC_MODULE_NAME,
                snapshot.artifact_identity["public_module_name"],
            )
        finally:
            server.server_close()

    def test_server_snapshot_stays_bound_after_staged_tree_mutation(self) -> None:
        server = self._server()
        try:
            snapshot = runner.capture_package_canvas_witness_snapshot(server)
            served_loader = server.snapshot.artifacts["chromium-wasm.js"]
            served_wasm = server.snapshot.artifacts["chromium-wasm.wasm"]
            (self.dist_dir / "chromium-wasm.js").write_bytes(b"mutated loader")
            (self.dist_dir / "chromium-wasm.wasm").write_bytes(b"mutated Wasm")

            self.assertEqual(served_loader, server.snapshot.artifacts["chromium-wasm.js"])
            self.assertEqual(served_wasm, server.snapshot.artifacts["chromium-wasm.wasm"])
            self.assertEqual(byte_identity(served_loader), snapshot.artifact_identity["loader"])
            self.assertEqual(byte_identity(served_wasm), snapshot.artifact_identity["wasm"])
        finally:
            server.server_close()

    def test_capture_rejects_a_package_mutated_before_immutable_snapshot(self) -> None:
        (self.dist_dir / "chromium-wasm.wasm").write_bytes(b"mutated Wasm")

        with self.assertRaisesRegex(M0Error, "hash mismatch"):
            self._server()

    def test_black_and_nonblack_aggregate_witnesses_are_both_valid(self) -> None:
        for nonblack, distinct in ((0, 1), (1, 2), (64, 1)):
            with self.subTest(nonblack=nonblack, distinct=distinct):
                observed = backing_store_witness(
                    frames_presented_at_observation=5,
                    nonblack_rgb_sample_count=nonblack,
                    distinct_rgb_value_count=distinct,
                )
                self.assertEqual(
                    observed,
                    runner.validate_canvas_backing_store_witness(
                        observed, minimum_frames_presented=3
                    ),
                )

    def test_capture_uses_only_bounded_aggregate_canvas_values(self) -> None:
        observed = backing_store_witness(
            frames_presented_at_observation=5,
            nonblack_rgb_sample_count=1,
            distinct_rgb_value_count=2,
        )
        client = FakeClient(observed)

        self.assertEqual(
            observed,
            runner.capture_canvas_backing_store_witness(
                client, minimum_frames_presented=3
            ),
        )
        self.assertEqual([runner._CANVAS_PIXEL_WITNESS_EXPRESSION], client.expressions)
        expression = client.expressions[0]
        self.assertIn("#browser-canvas", expression)
        self.assertIn("framesPresented", expression)
        self.assertIn("getImageData", expression)
        self.assertIn("non_black_rgb_sample_count", expression)
        self.assertNotIn("captureScreenshot", expression)
        self.assertNotIn("firstVisuallyNonEmptyPaint", expression)

    def test_canvas_witness_expression_parses_when_pinned_node_is_available(self) -> None:
        node = (
            Path(__file__).resolve().parents[3]
            / "third_party/emsdk/node/22.16.0_64bit/bin/node"
        )
        if not node.is_file():
            self.skipTest("the pinned Node executable is unavailable")
        completed = subprocess.run(
            [
                str(node),
                "--input-type=module",
                "--eval",
                "new Function(" + json.dumps(runner._CANVAS_PIXEL_WITNESS_EXPRESSION) + ");",
            ],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(
            0, completed.returncode, completed.stdout + completed.stderr
        )

    def test_witness_rejects_invalid_counts_flags_and_frame_order(self) -> None:
        cases = (
            ("predates the acknowledged frame", {"frames_presented_at_observation": 2}),
            (
                "visible-pixels flag disagrees",
                {"witness": {"visible_pixels_observed": True}},
            ),
            (
                "RGB counts exceed",
                {"witness": {"non_black_rgb_sample_count": 65}},
            ),
            (
                "canvas dimension is invalid",
                {"canvas_backing_store_width": runner.MAX_FRAME_DIMENSION + 1},
            ),
        )
        for expected, changes in cases:
            with self.subTest(expected=expected):
                observed = backing_store_witness()
                for name, value in changes.items():
                    if name == "witness":
                        observed["witness"].update(value)
                    else:
                        observed[name] = value
                with self.assertRaisesRegex(M0Error, expected):
                    runner.validate_canvas_backing_store_witness(
                        observed, minimum_frames_presented=3
                    )

    def test_result_binds_witness_to_snapshot_and_retains_false_gates(self) -> None:
        snapshot = self._snapshot()
        witness = backing_store_witness(
            frames_presented_at_observation=7,
            nonblack_rgb_sample_count=1,
            distinct_rgb_value_count=2,
        )
        package_run = {
            "frames_presented_at_ready": 5,
            "process_exit_code": 0,
            "runtime_exit_code": 0,
            "shutdown_disabled": True,
            "shutdown_requested": True,
        }
        result = runner.package_canvas_witness_result(
            witness=witness, package_run=package_run, snapshot=snapshot
        )

        self.assertFalse(result["m9GateComplete"])
        self.assertFalse(result["performanceGate"])
        self.assertEqual(package.RELEASE_STATUS, result["releaseStatus"])
        self.assertEqual(list(runner.LIMITATIONS), result["limitations"])
        self.assertEqual(snapshot.runtime_metadata, result["packageRuntimeMetadata"])

        invalid_m9 = deepcopy(result)
        invalid_m9["m9GateComplete"] = True
        with self.assertRaisesRegex(M0Error, "must not complete M9"):
            runner.validate_package_canvas_witness_result(
                invalid_m9, expected_snapshot=snapshot
            )

        invalid_performance = deepcopy(result)
        invalid_performance["performanceGate"] = True
        with self.assertRaisesRegex(M0Error, "must not set a performance gate"):
            runner.validate_package_canvas_witness_result(
                invalid_performance, expected_snapshot=snapshot
            )

        invalid_metadata = deepcopy(result)
        invalid_metadata["packageRuntimeMetadata"]["gateState"][
            "m9_release_complete"
        ] = True
        with self.assertRaisesRegex(M0Error, "false-only contract"):
            runner.validate_package_canvas_witness_result(
                invalid_metadata, expected_snapshot=snapshot
            )

        invalid_loader = deepcopy(result)
        invalid_loader["packageArtifact"]["loader"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(M0Error, "artifact identity disagrees"):
            runner.validate_package_canvas_witness_result(
                invalid_loader, expected_snapshot=snapshot
            )

        invalid_exit_type = deepcopy(result)
        invalid_exit_type["packageRun"]["runtime_exit_code"] = False
        with self.assertRaisesRegex(M0Error, "shutdown is not clean"):
            runner.validate_package_canvas_witness_result(
                invalid_exit_type, expected_snapshot=snapshot
            )

    def test_run_reuses_public_package_epoch_and_metadata_binding(self) -> None:
        server = mock.Mock()
        server.server_address = ("127.0.0.1", 32123)
        server.snapshot = package_smoke.snapshot_package_tree(self.dist_dir)
        server_thread = mock.Mock()
        server_thread.is_alive.return_value = False
        stderr_reader = mock.Mock()
        stderr_reader.started = True
        browser = mock.Mock()
        browser.stderr = object()
        profile = mock.Mock()
        profile.name = "/tmp/m9-package-canvas-witness-profile"
        client = mock.Mock()
        ready = {"framesPresented": 5}
        post_witness_status = {"framesPresented": 7}
        shutdown = {
            "processExitCode": 0,
            "runtimeExitCode": 0,
            "shutdownDisabled": True,
            "shutdownRequested": True,
        }
        observed = backing_store_witness(
            frames_presented_at_observation=6,
            nonblack_rgb_sample_count=1,
            distinct_rgb_value_count=2,
        )

        with (
            mock.patch.object(
                runner, "find_browser", return_value=(Path("/fake/browser"), "test")
            ),
            mock.patch.object(runner, "create_package_smoke_server", return_value=server),
            mock.patch.object(runner.threading, "Thread", return_value=server_thread),
            mock.patch.object(runner.tempfile, "TemporaryDirectory", return_value=profile),
            mock.patch.object(runner, "unused_loopback_port", return_value=32124),
            mock.patch.object(
                runner,
                "browser_command",
                return_value=["/fake/browser", "profile", "url"],
            ),
            mock.patch.object(runner.subprocess, "Popen", return_value=browser),
            mock.patch.object(runner, "BrowserStderrReader", return_value=stderr_reader),
            mock.patch.object(runner, "wait_for_page_client", return_value=client),
            mock.patch.object(
                package_browser,
                "_wait_for_ready_package_document",
                return_value=(ready, 1000.0),
            ) as wait_for_ready,
            mock.patch.object(
                runner,
                "capture_canvas_backing_store_witness",
                return_value=observed,
            ) as capture,
            mock.patch.object(
                package_browser, "_status", return_value=post_witness_status
            ),
            mock.patch.object(package_browser, "_validate_fatal_health"),
            mock.patch.object(package_browser, "_require_ready_package_document") as bind_post,
            mock.patch.object(
                package_browser,
                "_request_clean_shutdown",
                return_value=shutdown,
            ) as request_shutdown,
            mock.patch.object(runner.secrets, "token_urlsafe", return_value="epoch"),
            mock.patch.object(runner, "stop_browser_group"),
            mock.patch.object(runner, "shutdown_server_bounded"),
        ):
            result = runner.run_package_canvas_witness_smoke(
                dist_dir=Path("/fake/dist"),
                browser_argument=None,
                no_sandbox=False,
                timeout=120.0,
            )

        expected_metadata = package.package_runtime_status_metadata(
            server.snapshot.artifacts["VERSION.json"]
        )
        expected_url = "http://127.0.0.1:32123/?m9_package_epoch=epoch"
        self.assertFalse(result["m9GateComplete"])
        self.assertEqual(expected_metadata, result["packageRuntimeMetadata"])
        self.assertEqual(expected_url, wait_for_ready.call_args.kwargs["expected_url"])
        self.assertEqual("epoch", wait_for_ready.call_args.kwargs["expected_epoch"])
        self.assertEqual(
            expected_metadata,
            wait_for_ready.call_args.kwargs["expected_package_metadata"],
        )
        capture.assert_called_once_with(client, minimum_frames_presented=5)
        self.assertEqual(expected_url, bind_post.call_args.kwargs["expected_url"])
        self.assertEqual("epoch", bind_post.call_args.kwargs["expected_epoch"])
        self.assertEqual(
            expected_metadata,
            bind_post.call_args.kwargs["expected_package_metadata"],
        )
        self.assertEqual(expected_url, request_shutdown.call_args.kwargs["expected_url"])
        self.assertEqual("epoch", request_shutdown.call_args.kwargs["expected_epoch"])
        self.assertEqual(1000.0, request_shutdown.call_args.kwargs["expected_time_origin"])
        client.close.assert_called_once_with()
        server.server_close.assert_called_once_with()
        profile.cleanup.assert_called_once_with()

    def test_source_contract_keeps_the_public_host_unmodified_and_nonvisual(self) -> None:
        runner_source = source("tools/wasm/run_m9_package_canvas_witness_dom_smoke.py")
        release_host = source("tools/wasm/host/release_host.js")
        package_browser_source = source("tools/wasm/run_m9_package_browser_smoke.py")

        self.assertIn("create_package_smoke_server", runner_source)
        self.assertIn("capture_package_canvas_witness_snapshot", runner_source)
        self.assertIn("package_browser._wait_for_ready_package_document", runner_source)
        self.assertIn("package_browser._require_ready_package_document", runner_source)
        self.assertIn("getImageData", runner_source)
        self.assertIn("does_not_retain_raw_pixels_or_screenshots", runner_source)
        self.assertIn("does_not_claim_generic_browser_readiness", runner_source)
        self.assertIn("m9GateComplete\": False", runner_source)
        self.assertIn("performanceGate\": False", runner_source)
        self.assertNotIn("captureScreenshot", runner_source)
        self.assertNotIn(".get(\"firstVisuallyNonEmptyPaint\")", runner_source)
        self.assertIn('id="browser-canvas"', source("tools/wasm/host/release_index.html"))
        self.assertIn("this.#frameCount += 1", release_host)
        self.assertIn("context.putImageData", source("ui/ozone/platform/wasm/wasm_host_bridge.js"))
        self.assertIn("hostBridge.reportFrame", source("ui/ozone/platform/wasm/wasm_host_bridge.js"))
        self.assertLess(
            source("ui/ozone/platform/wasm/wasm_host_bridge.js").index(
                "context.putImageData"
            ),
            source("ui/ozone/platform/wasm/wasm_host_bridge.js").index(
                "hostBridge.reportFrame"
            ),
        )
        self.assertIn("framesPresented", package_browser_source)


if __name__ == "__main__":
    unittest.main()
