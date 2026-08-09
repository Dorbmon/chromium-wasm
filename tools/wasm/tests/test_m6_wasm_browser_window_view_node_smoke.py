#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the bounded Node child-dialog presentation runner."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m6_wasm_browser_window_view_smoke as smoke


def successful_result() -> dict[str, object]:
    return {
        "abort": None,
        "canvasCopies": 2,
        "fatalReports": [],
        "focusReports": [
            {
                "protocol": 1,
                "keyboardTargetPresent": True,
                "active": True,
            }
        ],
        "frameReports": [
            {"protocol": 1, "id": 1, "width": 640, "height": 480, "timestampMs": 1.0},
            {"protocol": 1, "id": 2, "width": 640, "height": 480, "timestampMs": 2.0},
        ],
        "markerObserved": True,
        "processExitReports": [{"protocol": 1, "exitCode": 0}],
        "readinessReports": [{"protocol": 1, "surfaceReady": True}],
        "rejection": None,
        "runtimeExitCode": 0,
        "sawMagenta": True,
    }


class M6WasmBrowserWindowViewNodeSmokeTest(unittest.TestCase):
    def test_runner_source_installs_a_real_frame_copy_probe(self) -> None:
        source = smoke.runner_source("file:///chrome_wasm.js", 1000)
        for expected in (
            "arguments: [\"--wasm-browser-window-view-smoke\"]",
            "class MockCanvasContext",
            "putImageData(imageData, x, y)",
            "pixels[index] === 255",
            "pixels[index + 1] === 0",
            "pixels[index + 2] === 255",
            "pixels[index + 3] === 255",
            "result.sawMagenta = true;",
            "reportFrame(report)",
            "reportReadiness(report)",
            "reportOzoneFocusState(report)",
            "reportFatal(message)",
            "reportProcessExit(report)",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, source)

    def test_accepts_the_complete_bounded_presentation_result(self) -> None:
        smoke.validate_result(successful_result(), smoke.PASS_MARKER)

    def test_rejects_a_result_without_the_painted_child_pixel(self) -> None:
        result = successful_result()
        result["sawMagenta"] = False
        with self.assertRaisesRegex(M0Error, "magenta"):
            smoke.validate_result(result, smoke.PASS_MARKER)

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
