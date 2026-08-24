#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the normal-profile fence-failure Node runner."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m6_wasm_browser_normal_lifecycle_smoke as normal_lifecycle
import run_m7_normal_profile_shutdown_fence_failure_smoke as runner


def _passing_output_events() -> list[dict[str, str]]:
    return [
        {
            "stream": "stderr",
            "text": normal_lifecycle.DEFAULT_STORAGE_PARTITION_RECEIPT,
        },
        {"stream": "stderr", "text": normal_lifecycle.READY_MARKER},
        {"stream": "stderr", "text": normal_lifecycle.PASS_MARKER},
        {"stream": "stderr", "text": runner.DIAGNOSTIC_MARKER},
    ]


def _passing_lifecycle_events() -> list[dict[str, object]]:
    output_events = _passing_output_events()
    # The diagnostic marker travels from the JsonPrefStore file-sequence
    # pthread over an asynchronous printErr message. It can arrive after the
    # synchronous process-exit bridge, even though native code emits it before
    # it resolves the failed shutdown fence.
    events: list[dict[str, object]] = [
        {"kind": "output", **event} for event in output_events[:3]
    ]
    events.extend(
        (
            {"kind": "processExit", "exitCode": runner.EXPECTED_EXIT_CODE},
            {"kind": "onExit", "exitCode": runner.EXPECTED_EXIT_CODE},
        )
    )
    events.append({"kind": "output", **output_events[3]})
    return events


def _passing_result() -> dict[str, object]:
    return {
        "runtimeExitCode": runner.EXPECTED_EXIT_CODE,
        "onExitCodes": [runner.EXPECTED_EXIT_CODE],
        # The generated loader normally consumes ExitStatus internally. The
        # runner records true only when its guarded factory-rejection fallback
        # sees the exact ExitStatus(13) object.
        "expectedExitStatusObserved": False,
        "abort": None,
        "rejection": None,
        "readyObserved": True,
        "passObserved": True,
        "hostShutdownRequests": [1, 0],
        "outputEvents": _passing_output_events(),
        "lifecycleEvents": _passing_lifecycle_events(),
        "canvasCopies": 1,
        "fatalReports": [],
        "frameReports": [
            {"protocol": 1, "id": 1, "width": 640, "height": 480, "timestampMs": 1}
        ],
        "readinessReports": [{"protocol": 1, "surfaceReady": True}],
        "focusReports": [
            {"protocol": 1, "keyboardTargetPresent": True, "active": True}
        ],
        "processExitReports": [
            {"protocol": 1, "exitCode": runner.EXPECTED_EXIT_CODE}
        ],
    }


def _write_diagnostic_args(out_dir: Path) -> None:
    (out_dir / "args.gn").write_text(
        runner.PRODUCT_GN_ENABLE_ARGUMENT + "\n", encoding="utf-8"
    )


class M7NormalProfileShutdownFenceFailureNodeSmokeTest(unittest.TestCase):
    def test_validate_result_accepts_only_the_expected_failed_shutdown(self) -> None:
        runner.validate_result(_passing_result())

    def test_validate_result_requires_exit_13_once_from_both_runtime_paths(self) -> None:
        for field, value, fragment in (
            ("runtimeExitCode", 0, "status 13"),
            ("onExitCodes", [], "exactly one"),
            (
                "onExitCodes",
                [runner.EXPECTED_EXIT_CODE, runner.EXPECTED_EXIT_CODE],
                "exactly one",
            ),
            ("abort", "unexpected abort", "aborted or rejected"),
            ("rejection", "unexpected rejection", "aborted or rejected"),
            ("processExitReports", [], "exactly one host process exit"),
            (
                "processExitReports",
                [{"protocol": 1, "exitCode": 0}],
                "not status 13",
            ),
        ):
            with self.subTest(field=field):
                result = _passing_result()
                result[field] = value
                with self.assertRaisesRegex(M0Error, fragment):
                    runner.validate_result(result)

    def test_validate_result_requires_visible_evidence_and_one_shot_shutdown(self) -> None:
        for field, value, fragment in (
            ("readyObserved", False, "visible browser lifecycle"),
            ("passObserved", False, "visible browser lifecycle"),
            ("hostShutdownRequests", [1], "one-shot"),
            ("canvasCopies", 0, "canvas copy count"),
            ("fatalReports", ["fatal"], "fatal error"),
            ("frameReports", [], "no compositor frames"),
        ):
            with self.subTest(field=field):
                result = _passing_result()
                result[field] = value
                with self.assertRaisesRegex(M0Error, fragment):
                    runner.validate_result(result)

    def test_validate_result_requires_exact_post_readback_marker_and_normal_order(self) -> None:
        cases: list[tuple[str, list[dict[str, str]], str]] = []
        missing = _passing_output_events()
        missing.pop()
        cases.append(("missing", missing, "missing or repeated"))

        repeated = _passing_output_events()
        repeated.append({"stream": "stderr", "text": runner.DIAGNOSTIC_MARKER})
        cases.append(("repeated", repeated, "missing or repeated"))

        unordered = _passing_output_events()
        unordered[1], unordered[2] = unordered[2], unordered[1]
        cases.append(("unordered", unordered, "were not emitted in lifecycle order"))

        stdout_marker = _passing_output_events()
        stdout_marker[-1]["stream"] = "stdout"
        cases.append(("stdout-marker", stdout_marker, "through stderr"))

        for name, events, fragment in cases:
            with self.subTest(name=name):
                result = _passing_result()
                result["outputEvents"] = events
                with self.assertRaisesRegex(M0Error, fragment):
                    runner.validate_result(result)

    def test_validate_result_does_not_assume_cross_pthread_marker_arrival_order(self) -> None:
        result = _passing_result()
        output_events = _passing_output_events()
        marker = output_events.pop()
        output_events.insert(0, marker)
        result["outputEvents"] = output_events
        result["lifecycleEvents"] = [
            {"kind": "output", **event} for event in output_events
        ] + [
            {"kind": "processExit", "exitCode": runner.EXPECTED_EXIT_CODE},
            {"kind": "onExit", "exitCode": runner.EXPECTED_EXIT_CODE},
        ]
        runner.validate_result(result)

    def test_validate_result_requires_consistent_lifecycle_projections(self) -> None:
        result = _passing_result()
        lifecycle = result["lifecycleEvents"]
        self.assertIsInstance(lifecycle, list)
        lifecycle[0]["text"] = "different-output"
        with self.assertRaisesRegex(M0Error, "output projection disagrees"):
            runner.validate_result(result)

    def test_validate_result_requires_ordered_terminal_status_13_callbacks(self) -> None:
        cases: list[tuple[str, list[dict[str, object]], str]] = []
        missing = _passing_lifecycle_events()
        missing.pop(4)
        cases.append(("missing", missing, "onExit projection disagrees"))

        unordered = _passing_lifecycle_events()
        unordered[3], unordered[4] = unordered[4], unordered[3]
        cases.append(("unordered", unordered, "did not precede"))

        for name, events, fragment in cases:
            with self.subTest(name=name):
                result = _passing_result()
                result["lifecycleEvents"] = events
                with self.assertRaisesRegex(M0Error, fragment):
                    runner.validate_result(result)

    def test_validate_result_rejects_invalid_exit_status_observation_shape(self) -> None:
        result = _passing_result()
        result["expectedExitStatusObserved"] = 1
        with self.assertRaisesRegex(M0Error, "ExitStatus observation"):
            runner.validate_result(result)

    def test_generated_node_host_preserves_normal_lifecycle_and_guards_exit_status(self) -> None:
        source = runner.runner_source("file:///tmp/diagnostic.js", 30000)
        self.assertIn("arguments: []", source)
        self.assertNotIn("--wasm-browser-smoke", source)
        self.assertIn("chromium_wasm_browser_host_request_shutdown", source)
        self.assertIn("result.hostShutdownRequests.push(first, second);", source)
        self.assertIn("result.onExitCodes.push(numericCode);", source)
        self.assertIn("kind: 'processExit'", source)
        self.assertIn("kind: 'onExit'", source)
        self.assertIn("result.lifecycleEvents.push({kind: 'output'", source)
        self.assertIn("isExactExpectedEmscriptenExitStatus(error)", source)
        self.assertIn("status: expectedExitCode", source)
        self.assertIn("message: `Program terminated with exit(${expectedExitCode})`", source)
        self.assertIn("Object.getOwnPropertyDescriptors(value)", source)
        self.assertIn("let resolveDiagnosticMarker;", source)
        self.assertIn("const diagnosticMarkerPromise = new Promise((resolve) =>", source)
        self.assertIn("result.outputEvents.push({stream: 'stderr', text});", source)
        self.assertIn("resolveDiagnosticMarker();", source)
        self.assertIn(
            "result.outputEvents.filter((event) => event.text === diagnosticMarker)",
            source,
        )
        self.assertIn("await factoryPromise;", source)
        self.assertIn(
            "await Promise.race([diagnosticMarkerPromise, timeoutPromise]);", source
        )
        self.assertIn("process.exitCode = expectedDiagnosticExit ? 0 : 1;", source)

    def test_output_configuration_requires_only_the_diagnostic_mode(self) -> None:
        runner.validate_m7_output_configuration(
            (runner.PRODUCT_GN_ENABLE_ARGUMENT + "\n").encode("utf-8")
        )
        for args_gn, fragment in (
            (b"", "lacks its explicit opt-in"),
            (
                b"enable_chromium_wasm_m7_normal_profile_fence_failure_diagnostic=false\n",
                "lacks its explicit opt-in",
            ),
            (
                (
                    runner.PRODUCT_GN_ENABLE_ARGUMENT
                    + "\nenable_chromium_wasm_m7_profile_preferences_test=true\n"
                ).encode("utf-8"),
                "incompatible M7 Preferences storage",
            ),
            (
                (
                    runner.PRODUCT_GN_ENABLE_ARGUMENT
                    + "\nenable_chromium_wasm_m7_profile_database_test=true\n"
                ).encode("utf-8"),
                "incompatible M7 database storage",
            ),
        ):
            with self.subTest(args_gn=args_gn):
                with self.assertRaisesRegex(M0Error, fragment):
                    runner.validate_m7_output_configuration(args_gn)

    def test_main_returns_zero_only_after_validated_diagnostic(self) -> None:
        manifest = {"emscripten": {"node_version": "test-node"}}
        versions = {
            "chromium": "chromium-revision",
            "v8": "v8-revision",
            "emscripten": "emscripten-revision",
            "port": "port-revision",
        }
        with tempfile.TemporaryDirectory() as temporary:
            out_dir = Path(temporary) / runner.DEFAULT_OUT_DIR.name
            out_dir.mkdir()
            _write_diagnostic_args(out_dir)
            (out_dir / f"{runner.DEFAULT_MODULE_NAME}.js").write_bytes(b"loader")
            (out_dir / f"{runner.DEFAULT_MODULE_NAME}.wasm").write_bytes(b"wasm")
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
                stderr="",
            )
            output = io.StringIO()
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "run_m7_normal_profile_shutdown_fence_failure_smoke.py",
                        "--out-dir",
                        str(out_dir),
                    ],
                ),
                mock.patch.object(runner, "check_boundary"),
                mock.patch.object(runner, "validate_m7_generated_source_selection"),
                mock.patch.object(runner, "load_manifest", return_value=manifest),
                mock.patch.object(
                    runner.normal_lifecycle,
                    "snapshot_run_version_identity",
                    return_value=versions,
                ),
                mock.patch.object(runner, "node_executable", return_value=node),
                mock.patch.object(runner, "print_context"),
                mock.patch.object(runner, "run_smoke", return_value=completed),
                contextlib.redirect_stdout(output),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(0, runner.main())

        result_lines = [
            line
            for line in output.getvalue().splitlines()
            if line.startswith(f"{runner.SENTINEL}:NODE_RESULT ")
        ]
        self.assertEqual(1, len(result_lines))
        summary = json.loads(result_lines[0].split(" ", 1)[1])
        self.assertEqual(runner.EXPECTED_EXIT_CODE, summary["hostProcessExitCode"])
        self.assertEqual(versions, summary["versions"])
        self.assertNotIn("persistence", summary)

    def test_main_accepts_only_the_expected_native_launcher_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            out_dir = Path(temporary) / runner.DEFAULT_OUT_DIR.name
            out_dir.mkdir()
            _write_diagnostic_args(out_dir)
            (out_dir / f"{runner.DEFAULT_MODULE_NAME}.js").write_bytes(b"loader")
            (out_dir / f"{runner.DEFAULT_MODULE_NAME}.wasm").write_bytes(b"wasm")
            node = Path(temporary) / "node"
            node.write_text("node", encoding="utf-8")
            completed = subprocess.CompletedProcess(
                [],
                runner.EXPECTED_EXIT_CODE,
                stdout=(
                    runner.RESULT_PREFIX
                    + json.dumps(_passing_result(), sort_keys=True)
                    + "\n"
                ),
                stderr="",
            )
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "run_m7_normal_profile_shutdown_fence_failure_smoke.py",
                        "--out-dir",
                        str(out_dir),
                    ],
                ),
                mock.patch.object(runner, "check_boundary"),
                mock.patch.object(runner, "validate_m7_generated_source_selection"),
                mock.patch.object(
                    runner,
                    "load_manifest",
                    return_value={"emscripten": {"node_version": "test-node"}},
                ),
                mock.patch.object(
                    runner.normal_lifecycle,
                    "snapshot_run_version_identity",
                    return_value={
                        "chromium": "c",
                        "v8": "v",
                        "emscripten": "e",
                        "port": "p",
                    },
                ),
                mock.patch.object(runner, "node_executable", return_value=node),
                mock.patch.object(runner, "print_context"),
                mock.patch.object(runner, "run_smoke", return_value=completed),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(0, runner.main())

            completed = subprocess.CompletedProcess([], 14, "", "")
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "run_m7_normal_profile_shutdown_fence_failure_smoke.py",
                        "--out-dir",
                        str(out_dir),
                    ],
                ),
                mock.patch.object(runner, "check_boundary"),
                mock.patch.object(runner, "validate_m7_generated_source_selection"),
                mock.patch.object(
                    runner,
                    "load_manifest",
                    return_value={"emscripten": {"node_version": "test-node"}},
                ),
                mock.patch.object(
                    runner.normal_lifecycle,
                    "snapshot_run_version_identity",
                    return_value={
                        "chromium": "c",
                        "v8": "v",
                        "emscripten": "e",
                        "port": "p",
                    },
                ),
                mock.patch.object(runner, "node_executable", return_value=node),
                mock.patch.object(runner, "print_context"),
                mock.patch.object(runner, "run_smoke", return_value=completed),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(1, runner.main())

    def test_main_rejects_non_diagnostic_output_or_module_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            wrong_out_dir = Path(temporary) / "not-the-diagnostic-output"
            wrong_out_dir.mkdir()
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "run_m7_normal_profile_shutdown_fence_failure_smoke.py",
                        "--out-dir",
                        str(wrong_out_dir),
                    ],
                ),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(1, runner.main())

        with self.assertRaises(SystemExit) as error:
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "run_m7_normal_profile_shutdown_fence_failure_smoke.py",
                        "--module-name",
                        "chrome_wasm",
                    ],
                ),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                runner.main()
        self.assertEqual(2, error.exception.code)

    def test_diagnostic_explicitly_disclaims_profile_persistence(self) -> None:
        self.assertIn("does not prove OPFS persistence", runner.__doc__)
        self.assertIn("profile-persistence claim", runner.runner_source.__doc__ or "")


if __name__ == "__main__":
    unittest.main()
