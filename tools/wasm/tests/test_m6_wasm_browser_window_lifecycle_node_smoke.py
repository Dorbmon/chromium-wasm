#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the bounded Node shutdown-lifecycle runner."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m6_wasm_browser_window_lifecycle_smoke as smoke


def successful_result() -> dict[str, object]:
    return {
        "abort": None,
        "canvasCopies": 1,
        "fatalReports": [],
        "focusReports": [
            {
                "protocol": 1,
                "keyboardTargetPresent": True,
                "active": True,
            }
        ],
        "frameReports": [
            {
                "protocol": 1,
                "id": 1,
                "width": 640,
                "height": 480,
                "timestampMs": 1.0,
            }
        ],
        "passObserved": True,
        "processExitReports": [{"protocol": 1, "exitCode": 0}],
        "readyObserved": True,
        "readinessReports": [{"protocol": 1, "surfaceReady": True}],
        "rejection": None,
        "runtimeExitCode": 0,
    }


class M6WasmBrowserWindowLifecycleNodeSmokeTest(unittest.TestCase):
    def test_runner_source_installs_the_bounded_lifecycle_host_bridge(self) -> None:
        source = smoke.runner_source("file:///chrome_wasm.js", 1000)
        for expected in (
            "arguments: [\"--wasm-browser-window-lifecycle-smoke\"]",
            "readyMarker",
            "class MockCanvasContext",
            "putImageData(imageData, x, y)",
            "globalThis.__chromiumWasmHostBridgeV1 = Object.freeze",
            "reportFrame(report)",
            "reportReadiness(report)",
            "reportOzoneFocusState(report)",
            "reportFatal(message)",
            "reportProcessExit(report)",
            "onExit(code)",
            "passMarker",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, source)

    def test_accepts_visible_zero_exit_and_both_lifecycle_markers(self) -> None:
        smoke.validate_result(
            successful_result(), f"{smoke.READY_MARKER}\n{smoke.PASS_MARKER}"
        )

    def test_rejects_missing_ready_marker_and_nonzero_process_exit(self) -> None:
        with self.assertRaisesRegex(M0Error, "ready marker"):
            smoke.validate_result(successful_result(), smoke.PASS_MARKER)

        result = successful_result()
        result["processExitReports"] = [{"protocol": 1, "exitCode": 13}]
        with self.assertRaisesRegex(M0Error, "nonzero"):
            smoke.validate_result(
                result, f"{smoke.READY_MARKER}\n{smoke.PASS_MARKER}"
            )

    def test_rejects_missing_visible_surface_evidence(self) -> None:
        result = successful_result()
        result["frameReports"] = []
        with self.assertRaisesRegex(M0Error, "compositor frames"):
            smoke.validate_result(
                result, f"{smoke.READY_MARKER}\n{smoke.PASS_MARKER}"
            )

    def test_parser_rejects_missing_or_repeated_result_records(self) -> None:
        result = json.dumps(successful_result(), separators=(",", ":"))
        self.assertEqual(
            smoke._parse_result(f"{smoke.RESULT_PREFIX}{result}\n"),
            successful_result(),
        )
        with self.assertRaisesRegex(M0Error, "unique"):
            smoke._parse_result(
                f"{smoke.RESULT_PREFIX}{result}\n{smoke.RESULT_PREFIX}{result}\n"
            )


if __name__ == "__main__":
    unittest.main()
