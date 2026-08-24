#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the bounded M9 native repeating-timer browser smoke."""

from __future__ import annotations

import contextlib
import copy
import io
import json
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m9_wasm_browser_repeating_timer_dom_smoke as smoke
from tools.wasm.tests.m3_source_contract_test_support import source


VERSIONS = {"chromium": "c", "v8": "v", "emscripten": "e", "port": "p"}
ARTIFACT_IDENTITY = {
    "artifact_delivery": smoke.ARTIFACT_DELIVERY,
    "artifact_source_provenance": smoke.ARTIFACT_SOURCE_PROVENANCE,
    "loader": {"bytes": 1, "sha256": "a" * 64},
    "module_name": smoke.PRODUCT_MODULE_NAME,
    "wasm": {"bytes": 1, "sha256": "b" * 64},
}
CAPTURE_HARNESS_IDENTITY = {
    "host_html": {"bytes": 1, "sha256": "c" * 64},
    "host_js": {"bytes": 1, "sha256": "d" * 64},
    "runner_source": {"bytes": 1, "sha256": "e" * 64},
    "source_snapshot_provenance": smoke.SOURCE_SNAPSHOT_PROVENANCE,
    "version_provenance": smoke.VERSION_PROVENANCE,
}


def event_loop_counts(
    *,
    heartbeat: int,
    animation_frame: int,
    frames: int = 1,
    timer_markers: int = 6,
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


def successful_result(
    config: smoke.TimerSmokeConfig = smoke.DEFAULT_TIMER_SMOKE_CONFIG,
) -> dict[str, object]:
    config = smoke._require_timer_smoke_config(config)
    readiness = {
        "shellReady": False,
        "surfaceReady": True,
        "firstVisuallyNonEmptyPaint": False,
    }
    before = event_loop_counts(
        heartbeat=config.tick_count + 1,
        animation_frame=config.tick_count + 1,
        timer_markers=config.tick_count + 3,
    )
    after = event_loop_counts(
        heartbeat=config.tick_count + 2,
        animation_frame=config.tick_count + 2,
        timer_markers=config.tick_count + 3,
    )
    return {
        "protocol": 1,
        "case": config.case,
        "scope": config.scope,
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
        "quiescentObserved": True,
        "passObserved": True,
        "lifecyclePassObserved": True,
        "ozoneFocusObserved": True,
        "ticks": [
            {
                "ordinal": ordinal,
                "heartbeatCount": ordinal,
                "animationFrameCount": ordinal,
            }
            for ordinal in range(1, config.tick_count + 1)
        ],
        "responsivenessAtPass": {
            "heartbeatCount": config.tick_count + 1,
            "animationFrameCount": config.tick_count + 1,
        },
        "responsivenessAtQuiescent": {
            "heartbeatCount": config.tick_count + 1,
            "animationFrameCount": config.tick_count + 1,
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
        "artifact": ARTIFACT_IDENTITY,
        "captureHarness": CAPTURE_HARNESS_IDENTITY,
        "frameReports": [
            {"id": 1, "width": 640, "height": 480, "timestampMs": 1.0},
        ],
        "readiness": readiness,
        "readinessReports": [readiness],
        "stdout": [],
        "stderr": [
            config.ready_marker,
            *(
                f"{smoke.TICK_MARKER_PREFIX}{ordinal}"
                for ordinal in range(1, config.tick_count + 1)
            ),
            config.quiescent_marker,
            config.pass_marker,
            smoke.LIFECYCLE_PASS_MARKER,
        ],
        "failedChecks": [],
        "error": None,
    }


def validate(
    result: dict[str, object],
    config: smoke.TimerSmokeConfig = smoke.DEFAULT_TIMER_SMOKE_CONFIG,
) -> None:
    smoke.validate_result(
        result,
        expected_versions=VERSIONS,
        expected_artifact_identity=ARTIFACT_IDENTITY,
        expected_capture_harness_identity=CAPTURE_HARNESS_IDENTITY,
        config=config,
    )


class M9WasmBrowserRepeatingTimerDomSmokeTest(unittest.TestCase):
    def test_accepts_three_native_ticks_and_clean_browser_drain(self) -> None:
        validate(successful_result())

    def test_accepts_only_the_fixed_one_hundred_tick_stress_contract(self) -> None:
        config = smoke.STRESS_100_TICKS_TIMER_SMOKE_CONFIG
        result = successful_result(config)
        validate(result, config)
        self.assertEqual(
            smoke.STRESS_100_TICKS_SWITCH, config.runtime_arguments[0]
        )
        self.assertEqual(100, len(result["ticks"]))
        self.assertEqual(103, result["postExitObservation"]["before"]["timerMarkers"])

        result["stderr"][-2] = smoke.PASS_MARKER
        with self.assertRaisesRegex(M0Error, "native markers"):
            validate(result, config)

    def test_accepts_only_the_fixed_one_thousand_tick_stress_contract(self) -> None:
        config = smoke.STRESS_1000_TICKS_TIMER_SMOKE_CONFIG
        result = successful_result(config)
        validate(result, config)
        self.assertEqual(
            smoke.STRESS_1000_TICKS_SWITCH, config.runtime_arguments[0]
        )
        self.assertEqual(1000, len(result["ticks"]))
        self.assertEqual(1003, result["postExitObservation"]["before"]["timerMarkers"])

        result["stderr"][-2] = smoke.STRESS_100_TICKS_PASS_MARKER
        with self.assertRaisesRegex(M0Error, "native markers"):
            validate(result, config)

    def test_closed_stress_config_rejects_arbitrary_timer_contracts(self) -> None:
        invalid = smoke.TimerSmokeConfig(
            mode="stress-101-ticks",
            case="browser_repeating_timer_m9_stress_101_ticks",
            scope="arbitrary",
            switch="--wasm-browser-m9-repeating-timer-smoke-ticks=101",
            ready_marker="READY",
            quiescent_marker="QUIESCENT",
            pass_marker="PASS",
            tick_count=101,
            minimum_timeout_seconds=30.0,
        )
        with self.assertRaisesRegex(M0Error, "closed supported mode"):
            smoke.validate_result(
                successful_result(),
                expected_versions=VERSIONS,
                expected_artifact_identity=ARTIFACT_IDENTITY,
                expected_capture_harness_identity=CAPTURE_HARNESS_IDENTITY,
                config=invalid,
            )

    def test_closed_stress_config_selects_one_thousand_ticks_only(self) -> None:
        self.assertIs(
            smoke.STRESS_1000_TICKS_TIMER_SMOKE_CONFIG,
            smoke.select_timer_smoke_config(
                stress_100_ticks=False, stress_1000_ticks=True
            ),
        )
        with self.assertRaisesRegex(M0Error, "mutually exclusive"):
            smoke.select_timer_smoke_config(
                stress_100_ticks=True, stress_1000_ticks=True
            )

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
                    "timerMarkers", 7
                ),
                "post-exit counters",
            ),
            (
                lambda result: result.__setitem__("processExitCode", 1),
                "processExitCode mismatch",
            ),
            (
                lambda result: result["responsivenessAtQuiescent"].__setitem__(
                    "heartbeatCount", 3
                ),
                "during native quiescence",
            ),
            (
                lambda result: result["stderr"].__setitem__(
                    4, smoke.PASS_MARKER
                ),
                "native markers",
            ),
        )
        for mutate, expression in mutations:
            with self.subTest(expression=expression):
                result = copy.deepcopy(successful_result())
                mutate(result)
                with self.assertRaisesRegex(M0Error, expression):
                    validate(result)

    def test_rejects_host_event_loop_stall_across_native_ticks(self) -> None:
        result = successful_result()
        result["ticks"] = [
            {"ordinal": ordinal, "heartbeatCount": 2, "animationFrameCount": 1}
            for ordinal in range(1, smoke.TICK_COUNT + 1)
        ]
        result["responsivenessAtQuiescent"] = {
            "heartbeatCount": 3,
            "animationFrameCount": 2,
        }
        with self.assertRaisesRegex(M0Error, "did not advance across native ticks"):
            validate(result)

    def test_rejects_substituted_artifact_or_capture_harness_identity(self) -> None:
        mutations = (
            (
                lambda result: result["artifact"].__setitem__(
                    "module_name", "alternate_wasm"
                ),
                "only supports the chrome_wasm product module",
            ),
            (
                lambda result: result["artifact"]["loader"].__setitem__(
                    "sha256", "f" * 64
                ),
                "artifact identity disagrees",
            ),
            (
                lambda result: result["captureHarness"]["host_js"].__setitem__(
                    "sha256", "f" * 64
                ),
                "capture harness disagrees",
            ),
        )
        for mutate, expression in mutations:
            with self.subTest(expression=expression):
                result = copy.deepcopy(successful_result())
                mutate(result)
                with self.assertRaisesRegex(M0Error, expression):
                    validate(result)

    def test_validates_explicit_package_alias_identity_overrides(self) -> None:
        artifact = copy.deepcopy(ARTIFACT_IDENTITY)
        harness = copy.deepcopy(CAPTURE_HARNESS_IDENTITY)
        artifact["artifact_delivery"] = "verified-package-private-alias"
        artifact["artifact_source_provenance"] = "local_clean_build_attested"
        harness["version_provenance"] = "verified-package-metadata-only"
        result = successful_result()
        result["artifact"] = copy.deepcopy(artifact)
        result["captureHarness"] = copy.deepcopy(harness)

        smoke.validate_result(
            result,
            expected_versions=VERSIONS,
            expected_artifact_identity=artifact,
            expected_capture_harness_identity=harness,
            expected_artifact_delivery=artifact["artifact_delivery"],
            expected_artifact_source_provenance=artifact[
                "artifact_source_provenance"
            ],
            expected_version_provenance=harness["version_provenance"],
        )

        result["artifact"]["artifact_delivery"] = "wrong-delivery"
        with self.assertRaisesRegex(M0Error, "artifact delivery"):
            smoke.validate_result(
                result,
                expected_versions=VERSIONS,
                expected_artifact_identity=artifact,
                expected_capture_harness_identity=harness,
                expected_artifact_delivery=artifact["artifact_delivery"],
                expected_artifact_source_provenance=artifact[
                    "artifact_source_provenance"
                ],
                expected_version_provenance=harness["version_provenance"],
            )

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

    def test_stress_result_parser_is_bound_to_its_fixed_case_and_scope(self) -> None:
        config = smoke.STRESS_100_TICKS_TIMER_SMOKE_CONFIG
        result = successful_result(config)
        payload = json.dumps(result, separators=(",", ":")).encode()
        self.assertEqual(smoke.parse_result_payload(payload, config=config), result)
        self.assertIsNone(smoke.parse_result_payload(payload))

        result["scope"] = smoke.SCOPE
        self.assertIsNone(
            smoke.parse_result_payload(json.dumps(result).encode(), config=config)
        )

    def test_long_stress_result_parser_is_bound_to_its_fixed_case_and_scope(
        self,
    ) -> None:
        config = smoke.STRESS_1000_TICKS_TIMER_SMOKE_CONFIG
        result = successful_result(config)
        payload = json.dumps(result, separators=(",", ":")).encode()
        self.assertEqual(smoke.parse_result_payload(payload, config=config), result)
        self.assertIsNone(smoke.parse_result_payload(payload))

        result["scope"] = smoke.STRESS_100_TICKS_SCOPE
        self.assertIsNone(
            smoke.parse_result_payload(json.dumps(result).encode(), config=config)
        )

    def test_stress_url_is_mode_bound_while_default_url_omits_mode(self) -> None:
        server = mock.Mock()
        server.module_name = smoke.PRODUCT_MODULE_NAME
        server.server_address = ("127.0.0.1", 12345)
        default_url = smoke.smoke_url(
            server,
            "test-token",
            VERSIONS,
            artifact=ARTIFACT_IDENTITY,
            capture_harness=CAPTURE_HARNESS_IDENTITY,
            module_name=smoke.PRODUCT_MODULE_NAME,
            timeout_seconds=15.0,
        )
        stress_url = smoke.smoke_url(
            server,
            "test-token",
            VERSIONS,
            artifact=ARTIFACT_IDENTITY,
            capture_harness=CAPTURE_HARNESS_IDENTITY,
            module_name=smoke.PRODUCT_MODULE_NAME,
            timeout_seconds=30.0,
            config=smoke.STRESS_100_TICKS_TIMER_SMOKE_CONFIG,
        )
        self.assertNotIn("mode", parse_qs(urlsplit(default_url).query))
        self.assertEqual(
            [smoke.STRESS_100_TICKS_MODE],
            parse_qs(urlsplit(stress_url).query)["mode"],
        )
        long_stress_url = smoke.smoke_url(
            server,
            "test-token",
            VERSIONS,
            artifact=ARTIFACT_IDENTITY,
            capture_harness=CAPTURE_HARNESS_IDENTITY,
            module_name=smoke.PRODUCT_MODULE_NAME,
            timeout_seconds=90.0,
            config=smoke.STRESS_1000_TICKS_TIMER_SMOKE_CONFIG,
        )
        self.assertEqual(
            [smoke.STRESS_1000_TICKS_MODE],
            parse_qs(urlsplit(long_stress_url).query)["mode"],
        )

    def test_server_mode_binding_rejects_injected_missing_and_repeated_modes(self) -> None:
        default = smoke.DEFAULT_TIMER_SMOKE_CONFIG
        stress = smoke.STRESS_100_TICKS_TIMER_SMOKE_CONFIG
        long_stress = smoke.STRESS_1000_TICKS_TIMER_SMOKE_CONFIG
        self.assertTrue(smoke._query_matches_timer_smoke_config("token=a", default))
        self.assertFalse(
            smoke._query_matches_timer_smoke_config(
                "token=a&mode=stress-100-ticks", default
            )
        )
        self.assertTrue(
            smoke._query_matches_timer_smoke_config(
                "token=a&mode=stress-100-ticks", stress
            )
        )
        self.assertTrue(
            smoke._query_matches_timer_smoke_config(
                "token=a&mode=stress-1000-ticks", long_stress
            )
        )
        for query in (
            "token=a",
            "token=a&mode=stress-101-ticks",
            "token=a&mode=stress-100-ticks&mode=stress-100-ticks",
        ):
            with self.subTest(query=query):
                self.assertFalse(smoke._query_matches_timer_smoke_config(query, stress))
        for query in (
            "token=a",
            "token=a&mode=stress-100-ticks",
            "token=a&mode=stress-1001-ticks",
            "token=a&mode=stress-1000-ticks&mode=stress-1000-ticks",
        ):
            with self.subTest(query=query):
                self.assertFalse(
                    smoke._query_matches_timer_smoke_config(query, long_stress)
                )

    def test_stress_server_rejects_tampered_mode_before_serving_the_host(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            host_dir = Path(temporary_directory)
            (host_dir / "chrome_wasm_browser_m9_repeating_timer_smoke.html").write_text(
                "<html>fixed host</html>\n", encoding="utf-8"
            )
            (host_dir / "chrome_wasm_browser_m9_repeating_timer_smoke.js").write_text(
                "export const fixedHost = true;\n", encoding="utf-8"
            )
            server = smoke.create_server_from_artifacts(
                "127.0.0.1",
                0,
                {
                    "chrome_wasm.js": b"export default async function() {}\n",
                    "chrome_wasm.wasm": b"\x00asm\x01\x00\x00\x00",
                },
                "test-token",
                queue.Queue(maxsize=1),
                module_name=smoke.PRODUCT_MODULE_NAME,
                host_dir=host_dir,
                runner_source_path=Path(__file__),
                config=smoke.STRESS_100_TICKS_TIMER_SMOKE_CONFIG,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            host, port = server.server_address[:2]
            try:
                with urlopen(
                    f"http://{host}:{port}{smoke.HOST_ROOT}/?mode=stress-100-ticks",
                    timeout=5,
                ) as response:
                    self.assertEqual(200, response.status)
                    self.assertEqual(b"<html>fixed host</html>\n", response.read())
                for query in ("", "?mode=stress-101-ticks", "?mode=stress-100-ticks&mode=stress-100-ticks"):
                    with self.subTest(query=query):
                        with self.assertRaises(HTTPError) as error:
                            urlopen(
                                f"http://{host}:{port}{smoke.HOST_ROOT}/{query}",
                                timeout=5,
                            )
                        self.assertEqual(400, error.exception.code)
                        error.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
                server.join_request_handlers(
                    timeout=5, description="M9 stress mode server"
                )
            self.assertFalse(thread.is_alive())

    def test_native_timer_is_ui_owned_and_quiescent_before_shutdown(self) -> None:
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        header = source("chrome/browser/wasm/wasm_browser_main_parts.h")
        for marker in (
            "wasm-browser-m9-repeating-timer-smoke",
            "wasm-browser-m9-repeating-timer-smoke-ticks",
            "kWasmBrowserM9RepeatingTimerSmokeTickCount = 3",
            "kWasmBrowserM9RepeatingTimerSmokeStressTickCount = 100",
            "kWasmBrowserM9RepeatingTimerSmokeLongStressTickCount = 1000",
            "kWasmBrowserM9RepeatingTimerSmokeInterval",
            "kWasmBrowserM9RepeatingTimerSmokeQuiescenceDuration",
            "kWasmBrowserM9RepeatingTimerSmokeTimeout",
            "kWasmBrowserM9RepeatingTimerSmokeStressTimeout",
            "kWasmBrowserM9RepeatingTimerSmokeLongStressTimeout",
            "base::Seconds(12)",
            "base::Seconds(75)",
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
            "CHROMIUM_WASM_M9_REPEATING_TIMER:QUIESCENT",
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
            tick.index("m9_repeating_timer_smoke_timer_.Stop();"),
            tick.index("->PostDelayedTask("),
        )
        self.assertLess(
            tick.index("->PostDelayedTask("),
            tick.index("kWasmBrowserM9RepeatingTimerSmokeQuiescentMarker"),
        )
        self.assertLess(
            tick.index("kWasmBrowserM9RepeatingTimerSmokeQuiescentMarker"),
            tick.index("kWasmBrowserM9RepeatingTimerSmokePassMarker"),
        )
        self.assertLess(
            tick.index("kWasmBrowserM9RepeatingTimerSmokePassMarker"),
            tick.index("RequestShutdown();"),
        )
        self.assertIn("weak_ptr_factory_.GetWeakPtr()", tick)
        self.assertIn("CHECK(!main_parts->m9_repeating_timer_smoke_timer_.IsRunning())", tick)
        self.assertIn("CHECK(main_parts->browser_lifecycle_->IsVisible())", tick)
        self.assertIn("StopM9RepeatingTimerSmoke();", timeout)
        self.assertIn("kWasmBrowserM9RepeatingTimerSmokeStressTickCount", main_parts)
        self.assertIn(
            "kWasmBrowserM9RepeatingTimerSmokeLongStressTickCount", main_parts
        )
        self.assertIn(
            "browser_m9_repeating_timer_default_smoke &&",
            main_parts,
        )
        self.assertIn(
            "browser_m9_repeating_timer_stress_smoke",
            main_parts,
        )

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
            "QUIESCENCE_DURATION_MS = 200",
            "QUIESCENT_MARKER",
            "quiescentObserved",
            "responsivenessAtQuiescent",
            "PRODUCT_MODULE_NAME = \"chrome_wasm\"",
            "POST_EXIT_GRACE_MS = 100",
            "STRESS_100_TICKS_MODE = \"stress-100-ticks\"",
            "STRESS_100_TICKS_SWITCH = \"--wasm-browser-m9-repeating-timer-smoke-ticks=100\"",
            "STRESS_1000_TICKS_MODE = \"stress-1000-ticks\"",
            "STRESS_1000_TICKS_SWITCH = \"--wasm-browser-m9-repeating-timer-smoke-ticks=1000\"",
            "MAX_RECORD_HISTORY = 2048",
            "timerSmokeConfigFromQuery",
            "query.getAll(\"mode\")",
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
            "query.get(\"ticks\")",
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
            "_require_product_module_name",
            "M9TrackingThreadingHTTPServer",
            "BrowserStderrReader",
            "stop_browser_group",
            "abort_browser_group",
            "shutdown_server_bounded",
            "capture_harness_identity",
            "immutable-in-memory-server-snapshot",
            "artifact_snapshot",
            "_validate_post_exit_observation",
            "_validate_native_markers",
            "--stress-100-ticks",
            "STRESS_100_MINIMUM_TIMEOUT_SECONDS = 30.0",
            "--stress-1000-ticks",
            "STRESS_1000_MINIMUM_TIMEOUT_SECONDS = 90.0",
            "config=timer_config",
            "wait_for_normal_close_result",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, runner)
        self.assertNotIn("ccall(", runner)
        self.assertNotIn("drain_stream", runner)
        self.assertNotIn("stop_browser(", runner)
        self.assertEqual(
            [smoke.SWITCH], smoke.DEFAULT_TIMER_SMOKE_CONFIG.runtime_arguments
        )

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

    def _run_host_query(self, query: str) -> dict[str, object]:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is unavailable")
        host = (
            TOOLS_DIR.parents[1]
            / "tools/wasm/host/chrome_wasm_browser_m9_repeating_timer_smoke.js"
        )
        script = f"""
globalThis.location = {{
  origin: "http://127.0.0.1",
  pathname: "/__m9_repeating_timer__/",
  search: {json.dumps(query)},
}};
let fetchCalls = 0;
globalThis.fetch = () => {{
  fetchCalls += 1;
  throw new Error("unexpected repeating-timer loader fetch");
}};
const host = await import({json.dumps(host.as_uri())});
let error = null;
try {{
  await host.runChromeWasmBrowserM9RepeatingTimerSmokeFromQuery();
}} catch (value) {{
  error = String(value);
}}
process.stdout.write(JSON.stringify({{error, fetchCalls}}));
"""
        completed = subprocess.run(
            [node, "--input-type=module", "--eval", script],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        return json.loads(completed.stdout)

    def test_alternate_module_query_is_rejected_before_loader_fetch(self) -> None:
        observed = self._run_host_query("?token=test-token&module=alternate_wasm")
        self.assertIn(
            "must select the chrome_wasm product module", observed["error"]
        )
        self.assertEqual(0, observed["fetchCalls"])

    def test_invalid_repeated_or_tampered_timer_modes_are_rejected_before_fetch(self) -> None:
        for mode_query in (
            "?mode=stress-101-ticks&token=test-token&module=chrome_wasm",
            "?mode=stress-100-ticks&mode=stress-100-ticks&token=test-token&module=chrome_wasm",
            "?mode=&token=test-token&module=chrome_wasm",
        ):
            with self.subTest(mode_query=mode_query):
                observed = self._run_host_query(mode_query)
                self.assertIn("closed supported mode once", observed["error"])
                self.assertEqual(0, observed["fetchCalls"])

    def test_rejects_alternate_product_module_at_server_and_url_boundaries(self) -> None:
        alternate_module = "alternate_wasm"
        with self.assertRaisesRegex(
            M0Error, "only supports the chrome_wasm product module"
        ):
            smoke.create_server(
                "127.0.0.1",
                0,
                Path("/missing-repeating-timer-output"),
                "test-token",
                queue.Queue(maxsize=1),
                module_name=alternate_module,
            )

        server = mock.Mock()
        server.module_name = smoke.PRODUCT_MODULE_NAME
        server.server_address = ("127.0.0.1", 12345)
        with self.assertRaisesRegex(
            M0Error, "only supports the chrome_wasm product module"
        ):
            smoke.smoke_url(
                server,
                "test-token",
                VERSIONS,
                artifact=ARTIFACT_IDENTITY,
                capture_harness=CAPTURE_HARNESS_IDENTITY,
                module_name=alternate_module,
                timeout_seconds=15.0,
            )

        server.module_name = alternate_module
        with self.assertRaisesRegex(
            M0Error, "only supports the chrome_wasm product module"
        ):
            smoke.smoke_url(
                server,
                "test-token",
                VERSIONS,
                artifact=ARTIFACT_IDENTITY,
                capture_harness=CAPTURE_HARNESS_IDENTITY,
                module_name=smoke.PRODUCT_MODULE_NAME,
                timeout_seconds=15.0,
            )

    def test_main_rejects_alternate_module_before_server_or_browser(self) -> None:
        stderr = io.StringIO()
        with (
            mock.patch.object(smoke, "check_boundary") as check_boundary,
            mock.patch.object(smoke, "create_server") as create_server,
            mock.patch.object(smoke, "find_browser") as find_browser,
            mock.patch.object(
                smoke.sys,
                "argv",
                ["repeating-timer-runner", "--module-name", "alternate_wasm"],
            ),
            mock.patch.object(smoke.sys, "stderr", stderr),
            self.assertRaisesRegex(SystemExit, "^2$"),
        ):
            smoke.main()

        self.assertIn("--module-name must be chrome_wasm", stderr.getvalue())
        check_boundary.assert_not_called()
        create_server.assert_not_called()
        find_browser.assert_not_called()

    def test_main_requires_a_thirty_second_timeout_for_stress_mode(self) -> None:
        stderr = io.StringIO()
        with (
            mock.patch.object(smoke, "check_boundary") as check_boundary,
            mock.patch.object(smoke, "create_server") as create_server,
            mock.patch.object(
                smoke.sys,
                "argv",
                [
                    "repeating-timer-runner",
                    "--stress-100-ticks",
                    "--timeout",
                    "29",
                ],
            ),
            mock.patch.object(smoke.sys, "stderr", stderr),
            self.assertRaisesRegex(SystemExit, "^2$"),
        ):
            smoke.main()

        self.assertIn(
            "--stress-100-ticks requires --timeout of at least 30 seconds",
            stderr.getvalue(),
        )
        check_boundary.assert_not_called()
        create_server.assert_not_called()

    def test_main_requires_a_ninety_second_timeout_for_long_stress_mode(self) -> None:
        stderr = io.StringIO()
        with (
            mock.patch.object(smoke, "check_boundary") as check_boundary,
            mock.patch.object(smoke, "create_server") as create_server,
            mock.patch.object(
                smoke.sys,
                "argv",
                [
                    "repeating-timer-runner",
                    "--stress-1000-ticks",
                    "--timeout",
                    "89",
                ],
            ),
            mock.patch.object(smoke.sys, "stderr", stderr),
            self.assertRaisesRegex(SystemExit, "^2$"),
        ):
            smoke.main()

        self.assertIn(
            "--stress-1000-ticks requires --timeout of at least 90 seconds",
            stderr.getvalue(),
        )
        check_boundary.assert_not_called()
        create_server.assert_not_called()

    def test_main_closes_an_unstarted_server_without_shutdown(self) -> None:
        server = mock.Mock()
        server.shutdown.side_effect = AssertionError(
            "an unstarted server must not be shut down"
        )
        server_thread = mock.Mock()
        server_thread.start.side_effect = RuntimeError("server thread start failed")

        with (
            mock.patch.object(smoke, "check_boundary"),
            mock.patch.object(smoke, "create_server", return_value=(server, {})),
            mock.patch.object(smoke, "artifact_identity", return_value=ARTIFACT_IDENTITY),
            mock.patch.object(
                smoke, "capture_harness_identity", return_value=CAPTURE_HARNESS_IDENTITY
            ),
            mock.patch.object(smoke, "load_manifest", return_value={}),
            mock.patch.object(smoke, "checked_output", return_value="p"),
            mock.patch.object(smoke, "manifest_versions", return_value=VERSIONS),
            mock.patch.object(smoke, "print_context"),
            mock.patch.object(
                smoke,
                "find_browser",
                return_value=(Path("/fake/browser"), "test-browser"),
            ) as find_browser,
            mock.patch.object(smoke.threading, "Thread", return_value=server_thread),
            mock.patch.object(smoke.subprocess, "Popen") as popen,
            mock.patch.object(sys, "argv", ["repeating-timer-runner"]),
            self.assertRaisesRegex(RuntimeError, "server thread start failed"),
        ):
            smoke.main()

        server.shutdown.assert_not_called()
        server.server_close.assert_called_once_with()
        server_thread.join.assert_not_called()
        server.join_request_handlers.assert_called_once_with(
            timeout=1, description="M9 repeating-timer server"
        )
        find_browser.assert_called_once_with(None)
        popen.assert_not_called()

    def test_main_aborts_group_when_stderr_reader_does_not_start(self) -> None:
        server = mock.Mock()
        server_thread = mock.Mock()
        server_thread.is_alive.return_value = False
        stderr_thread = mock.Mock()
        stderr_thread.start.side_effect = RuntimeError("stderr reader start failed")
        browser = mock.Mock()
        browser.stderr = object()
        profile = mock.Mock()
        profile.name = "/tmp/m9-repeating-timer-profile"

        with (
            mock.patch.object(smoke, "check_boundary"),
            mock.patch.object(smoke, "create_server", return_value=(server, {})),
            mock.patch.object(smoke, "artifact_identity", return_value=ARTIFACT_IDENTITY),
            mock.patch.object(
                smoke, "capture_harness_identity", return_value=CAPTURE_HARNESS_IDENTITY
            ),
            mock.patch.object(smoke, "load_manifest", return_value={}),
            mock.patch.object(smoke, "checked_output", return_value="p"),
            mock.patch.object(smoke, "manifest_versions", return_value=VERSIONS),
            mock.patch.object(smoke, "print_context"),
            mock.patch.object(
                smoke,
                "find_browser",
                return_value=(Path("/fake/browser"), "test-browser"),
            ),
            mock.patch.object(
                smoke, "smoke_url", return_value="http://127.0.0.1:12345/"
            ),
            mock.patch.object(smoke.tempfile, "TemporaryDirectory", return_value=profile),
            mock.patch.object(
                smoke,
                "browser_command",
                return_value=["/fake/browser", "profile", "url"],
            ),
            mock.patch.object(smoke.subprocess, "Popen", return_value=browser),
            mock.patch.object(
                smoke.threading, "Thread", side_effect=[server_thread, stderr_thread]
            ),
            mock.patch.object(smoke, "shutdown_server_bounded"),
            mock.patch.object(smoke, "abort_browser_group") as abort_browser_group,
            mock.patch.object(sys, "argv", ["repeating-timer-runner"]),
            self.assertRaisesRegex(RuntimeError, "stderr reader start failed"),
        ):
            smoke.main()

        server_thread.start.assert_called_once_with()
        abort_browser_group.assert_called_once_with(browser, mock.ANY, unowned_streams=())
        stderr_thread.join.assert_not_called()
        server.server_close.assert_called_once_with()
        server_thread.join.assert_called_once_with(timeout=1)
        profile.cleanup.assert_called_once_with()

    def test_main_never_reports_success_before_browser_group_cleanup(self) -> None:
        server = mock.Mock()
        server_thread = mock.Mock()
        server_thread.is_alive.return_value = False
        stderr_thread = mock.Mock()
        browser = mock.Mock()
        browser.stderr = object()
        profile = mock.Mock()
        profile.name = "/tmp/m9-repeating-timer-profile"
        stdout = io.StringIO()
        stderr = io.StringIO()

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(smoke, "check_boundary"))
            stack.enter_context(
                mock.patch.object(smoke, "create_server", return_value=(server, {}))
            )
            stack.enter_context(
                mock.patch.object(
                    smoke, "artifact_identity", return_value=ARTIFACT_IDENTITY
                )
            )
            stack.enter_context(
                mock.patch.object(
                    smoke,
                    "capture_harness_identity",
                    return_value=CAPTURE_HARNESS_IDENTITY,
                )
            )
            stack.enter_context(mock.patch.object(smoke, "load_manifest", return_value={}))
            stack.enter_context(mock.patch.object(smoke, "checked_output", return_value="p"))
            stack.enter_context(
                mock.patch.object(smoke, "manifest_versions", return_value=VERSIONS)
            )
            stack.enter_context(mock.patch.object(smoke, "print_context"))
            stack.enter_context(
                mock.patch.object(
                    smoke,
                    "find_browser",
                    return_value=(Path("/fake/browser"), "test-browser"),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    smoke, "smoke_url", return_value="http://127.0.0.1:12345/"
                )
            )
            stack.enter_context(
                mock.patch.object(smoke.tempfile, "TemporaryDirectory", return_value=profile)
            )
            stack.enter_context(
                mock.patch.object(
                    smoke,
                    "browser_command",
                    return_value=["/fake/browser", "profile", "url"],
                )
            )
            stack.enter_context(mock.patch.object(smoke.subprocess, "Popen", return_value=browser))
            stack.enter_context(
                mock.patch.object(
                    smoke.threading, "Thread", side_effect=[server_thread, stderr_thread]
                )
            )
            stack.enter_context(mock.patch.object(smoke, "shutdown_server_bounded"))
            stack.enter_context(
                mock.patch.object(smoke, "wait_for_result", return_value=successful_result())
            )
            stack.enter_context(mock.patch.object(smoke, "validate_result"))
            stop_browser_group = stack.enter_context(
                mock.patch.object(
                    smoke,
                    "stop_browser_group",
                    side_effect=M0Error("browser group cleanup failed"),
                )
            )
            stack.enter_context(
                mock.patch.object(smoke, "write_failure_diagnostics", return_value=Path("diag"))
            )
            stack.enter_context(mock.patch.object(sys, "argv", ["repeating-timer-runner"]))
            stack.enter_context(mock.patch.object(smoke.sys, "stdout", stdout))
            stack.enter_context(mock.patch.object(smoke.sys, "stderr", stderr))

            self.assertEqual(1, smoke.main())

        self.assertNotIn(f"{smoke.SENTINEL}:BROWSER_RESULT", stdout.getvalue())
        self.assertNotIn(f"{smoke.SENTINEL}:PASS", stdout.getvalue())
        stop_browser_group.assert_called_once_with(browser, mock.ANY)
        server_thread.start.assert_called_once_with()
        server.server_close.assert_called_once_with()
        server_thread.join.assert_called_once_with(timeout=1)
        profile.cleanup.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
