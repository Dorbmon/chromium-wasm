#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the no-switch Wasm Browser Node lifecycle runner."""

from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m6_wasm_browser_normal_lifecycle_smoke as runner


def _passing_result() -> dict[str, object]:
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


class M6WasmBrowserNormalLifecycleNodeSmokeTest(unittest.TestCase):
    def test_runner_is_no_switch_and_uses_only_the_shutdown_abi_after_ready(self) -> None:
        source = runner.runner_source("file:///tmp/chrome_wasm.js", 30000)
        self.assertIn("arguments: []", source)
        self.assertNotIn("--wasm-browser-smoke", source)
        self.assertIn("chromium_wasm_browser_host_request_shutdown", source)
        self.assertIn("result.hostShutdownRequests.push(first, second);", source)
        self.assertIn("if (first !== 1 || second !== 0)", source)
        self.assertIn("if (text.includes(readyMarker))", source)
        self.assertIn("onRuntimeInitialized()", source)
        self.assertIn("function hasVisibleBrowserEvidence()", source)
        self.assertIn("function maybeRequestHostShutdown()", source)
        self.assertIn("queueMicrotask(maybeRequestHostShutdown);", source)
        self.assertIn("result.frameReports.length > 0", source)
        self.assertIn("report.surfaceReady === true", source)
        self.assertIn("report.keyboardTargetPresent === true", source)
        self.assertIn("createModule(moduleOptions).catch", source)
        self.assertNotIn("await createModule", source)

    def test_validate_result_requires_visible_lifecycle_and_one_shot_shutdown(self) -> None:
        result = _passing_result()
        output = f"{runner.READY_MARKER}\n{runner.PASS_MARKER}"
        runner.validate_result(result, output)

        for key, value, fragment in (
            ("hostShutdownRequests", [1], "one-shot"),
            ("readyObserved", False, "ready marker"),
            ("passObserved", False, "pass marker"),
            ("runtimeExitCode", 13, "exit zero"),
        ):
            with self.subTest(key=key):
                invalid = copy.deepcopy(result)
                invalid[key] = value
                with self.assertRaisesRegex(M0Error, fragment):
                    runner.validate_result(invalid, output)


if __name__ == "__main__":
    unittest.main()
