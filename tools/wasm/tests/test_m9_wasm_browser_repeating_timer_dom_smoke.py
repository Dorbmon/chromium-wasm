#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the bounded M9 native repeating-timer browser smoke."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m9_wasm_browser_repeating_timer_dom_smoke as smoke
from tools.wasm.tests.m3_source_contract_test_support import source


VERSIONS = {"chromium": "c", "v8": "v", "emscripten": "e", "port": "p"}


def event_loop_counts(
    *, heartbeat: int, animation_frame: int, frames: int = 1, timer_markers: int = 5
) -> dict[str, int]:
    return {
        "animationFrameCount": animation_frame,
        "fatalErrors": 0,
        "frameReports": frames,
        "heartbeatCount": heartbeat,
        "timerMarkers": timer_markers,
        "unhandledRejections": 0,
        "windowErrors": 0,
    }


def successful_result() -> dict[str, object]:
    readiness = {
        "shellReady": True,
        "surfaceReady": True,
        "firstVisuallyNonEmptyPaint": True,
    }
    before = event_loop_counts(heartbeat=4, animation_frame=3)
    after = event_loop_counts(heartbeat=5, animation_frame=4)
    return {
        "protocol": 1,
        "case": smoke.CASE,
        "scope": smoke.SCOPE,
        "status": "pass",
        "m9GateComplete": False,
        "m9TimerSmokeOnly": True,
        "runtimeExitCode": 0,
        "processExitCode": 0,
        "runtimeInitialized": True,
        "factorySettled": True,
        "factoryRejected": False,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "readyObserved": True,
        "passObserved": True,
        "lifecyclePassObserved": True,
        "ozoneFocusObserved": True,
        "ticks": [
            {"ordinal": 1, "heartbeatCount": 1, "animationFrameCount": 1},
            {"ordinal": 2, "heartbeatCount": 2, "animationFrameCount": 1},
            {"ordinal": 3, "heartbeatCount": 3, "animationFrameCount": 2},
        ],
        "responsivenessAtPass": {
            "heartbeatCount": 3,
            "animationFrameCount": 2,
        },
        "postExitObservation": {
            "before": before,
            "after": after,
            "graceMs": smoke.POST_EXIT_GRACE_MS,
            "animationFrameAdvanced": True,
            "errorsQuiet": True,
            "framesQuiet": True,
            "heartbeatAdvanced": True,
            "timerMarkersQuiet": True,
        },
        "abort": None,
        "fatalErrors": [],
        "windowErrors": [],
        "unhandledRejections": [],
        "versions": VERSIONS,
        "frameReports": [
            {"id": 1, "width": 640, "height": 480, "timestampMs": 1.0},
        ],
        "readiness": readiness,
        "readinessReports": [readiness],
        "stdout": [],
        "stderr": [
            smoke.READY_MARKER,
            f"{smoke.TICK_MARKER_PREFIX}1",
            f"{smoke.TICK_MARKER_PREFIX}2",
            f"{smoke.TICK_MARKER_PREFIX}3",
            smoke.PASS_MARKER,
            smoke.LIFECYCLE_PASS_MARKER,
        ],
        "failedChecks": [],
        "error": None,
    }


class M9WasmBrowserRepeatingTimerDomSmokeTest(unittest.TestCase):
    def test_accepts_three_native_ticks_and_clean_browser_drain(self) -> None:
        smoke.validate_result(successful_result(), expected_versions=VERSIONS)

    def test_rejects_watchdog_extra_tick_unresponsive_host_or_post_exit_output(self) -> None:
        mutations = (
            (
                lambda result: result["stderr"].__setitem__(
                    4, f"{smoke.TICK_MARKER_PREFIX}4"
                ),
                "native markers",
            ),
            (
                lambda result: result["stderr"].append(
                    "CHROMIUM_WASM_M9_REPEATING_TIMER:TIMEOUT observed=2"
                ),
                "native markers",
            ),
            (
                lambda result: result["responsivenessAtPass"].__setitem__(
                    "heartbeatCount", 1
                ),
                "interval did not advance",
            ),
            (
                lambda result: result["postExitObservation"].__setitem__(
                    "timerMarkersQuiet", False
                ),
                "post-exit check",
            ),
            (
                lambda result: result["postExitObservation"]["after"].__setitem__(
                    "timerMarkers", 6
                ),
                "post-exit counters",
            ),
            (
                lambda result: result.__setitem__("processExitCode", 1),
                "processExitCode mismatch",
            ),
        )
        for mutate, expression in mutations:
            with self.subTest(expression=expression):
                result = copy.deepcopy(successful_result())
                mutate(result)
                with self.assertRaisesRegex(M0Error, expression):
                    smoke.validate_result(result, expected_versions=VERSIONS)

    def test_parser_rejects_duplicate_keys_and_wrong_scope(self) -> None:
        result = successful_result()
        payload = json.dumps(result, separators=(",", ":")).encode()
        self.assertEqual(smoke.parse_result_payload(payload), result)
        self.assertIsNone(
            smoke.parse_result_payload(
                b'{"protocol":1,"protocol":1,'
                b'"case":"browser_repeating_timer_m9",'
                b'"scope":"fixed-three-native-ui-repeating-timer-ticks-with-host-event-loop-and-'
                b'post-shutdown-quiet-observation"}'
            )
        )
        result["scope"] = "wrong"
        self.assertIsNone(smoke.parse_result_payload(json.dumps(result).encode()))

    def test_native_timer_is_ui_owned_switch_gated_and_stopped_before_shutdown(self) -> None:
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        header = source("chrome/browser/wasm/wasm_browser_main_parts.h")
        for marker in (
            "wasm-browser-m9-repeating-timer-smoke",
            "kWasmBrowserM9RepeatingTimerSmokeTickCount = 3",
            "kWasmBrowserM9RepeatingTimerSmokeInterval",
            "kWasmBrowserM9RepeatingTimerSmokeTimeout",
            "StartM9RepeatingTimerSmoke",
            "OnM9RepeatingTimerSmokeTick",
            "OnM9RepeatingTimerSmokeTimeout",
            "StopM9RepeatingTimerSmoke",
            "m9_repeating_timer_smoke_requested_",
            "m9_repeating_timer_smoke_timer_",
            "m9_repeating_timer_smoke_timeout_timer_",
            "weak_ptr_factory_.GetWeakPtr()",
            "CHROMIUM_WASM_M9_REPEATING_TIMER:READY",
            "CHROMIUM_WASM_M9_REPEATING_TIMER:TICK",
            "CHROMIUM_WASM_M9_REPEATING_TIMER:PASS",
            "CHROMIUM_WASM_M9_REPEATING_TIMER:TIMEOUT",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, main_parts + header)

        tick_start = main_parts.index("void WasmBrowserMainParts::OnM9RepeatingTimerSmokeTick()")
        timeout_start = main_parts.index(
            "void WasmBrowserMainParts::OnM9RepeatingTimerSmokeTimeout()"
        )
        stop_start = main_parts.index("void WasmBrowserMainParts::StopM9RepeatingTimerSmoke()")
        tick = main_parts[tick_start:timeout_start]
        timeout = main_parts[timeout_start:stop_start]
        for function_body in (tick, timeout):
            self.assertIn("CHECK_CURRENTLY_ON(content::BrowserThread::UI);", function_body)
            self.assertNotIn("base::Unretained(this)", function_body)
        self.assertLess(
            tick.index("StopM9RepeatingTimerSmoke();"),
            tick.index("kWasmBrowserM9RepeatingTimerSmokePassMarker"),
        )
        self.assertLess(
            tick.index("kWasmBrowserM9RepeatingTimerSmokePassMarker"),
            tick.index("RequestShutdown();"),
        )
        self.assertIn("StopM9RepeatingTimerSmoke();", timeout)

        for shutdown_site in (
            "void WasmBrowserMainParts::RequestShutdown()",
            "void WasmBrowserMainParts::PostMainMessageLoopRun()",
            "void WasmBrowserMainParts::OnBrowserLifecycleShutdownComplete()",
            "void WasmBrowserMainParts::ShutdownFoundation()",
        ):
            begin = main_parts.index(shutdown_site)
            next_function = main_parts.find("\nvoid WasmBrowserMainParts::", begin + 1)
            body = main_parts[begin: next_function if next_function >= 0 else None]
            with self.subTest(shutdown_site=shutdown_site):
                self.assertIn("StopM9RepeatingTimerSmoke();", body)

    def test_host_uses_only_output_capture_and_real_event_loop_witnesses(self) -> None:
        html = source("tools/wasm/host/chrome_wasm_browser_m9_repeating_timer_smoke.html")
        host = source("tools/wasm/host/chrome_wasm_browser_m9_repeating_timer_smoke.js")
        self.assertIn('id="browser-canvas"', html)
        self.assertIn("runChromeWasmBrowserM9RepeatingTimerSmokeFromQuery", html)
        for marker in (
            "arguments: [SWITCH]",
            "mainScriptUrlOrBlob",
            "printErr(line)",
            "setInterval",
            "requestAnimationFrame",
            "POST_EXIT_GRACE_MS = 100",
            "timerMarkersQuiet",
            "framesQuiet",
            "heartbeatAdvanced",
            "animationFrameAdvanced",
            "reportProcessExit(report)",
            "reportFrame(report)",
            "reportReadiness(report)",
            "reportOzoneFocusState(report)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, host)
        for forbidden in (
            "ccall(",
            "chromium_wasm_browser_host_request_shutdown",
            "addEventListener(\"click\"",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, host)

    def test_runner_snapshots_artifacts_requires_isolation_and_validates_quietness(self) -> None:
        runner = source("tools/wasm/run_m9_wasm_browser_repeating_timer_dom_smoke.py")
        for marker in (
            'HOST_ROOT = "/__m9_repeating_timer__"',
            '"Cross-Origin-Opener-Policy", "same-origin"',
            '"Cross-Origin-Embedder-Policy", "require-corp"',
            '"application/wasm"',
            "_snapshot_artifacts",
            "artifact_snapshot",
            "_validate_post_exit_observation",
            "_validate_native_markers",
            "runtime_arguments=[SWITCH]",
            "wait_for_normal_close_result",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, runner)
        self.assertNotIn("ccall(", runner)

    def test_host_javascript_parses_with_node_when_available(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is unavailable")
        host = (
            TOOLS_DIR.parents[1]
            / "tools/wasm/host/chrome_wasm_browser_m9_repeating_timer_smoke.js"
        )
        completed = subprocess.run(
            [node, "--check", str(host)],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            "Node rejected repeating-timer host asset:\n"
            + completed.stdout
            + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
