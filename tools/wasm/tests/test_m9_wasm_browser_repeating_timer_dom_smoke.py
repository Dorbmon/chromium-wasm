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
import unittest
from unittest import mock


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
    *, heartbeat: int, animation_frame: int, frames: int = 1, timer_markers: int = 6
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
        "shellReady": False,
        "surfaceReady": True,
        "firstVisuallyNonEmptyPaint": False,
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
        "quiescentObserved": True,
        "passObserved": True,
        "lifecyclePassObserved": True,
        "ozoneFocusObserved": True,
        "ticks": [
            {"ordinal": 1, "heartbeatCount": 1, "animationFrameCount": 1},
            {"ordinal": 2, "heartbeatCount": 2, "animationFrameCount": 1},
            {"ordinal": 3, "heartbeatCount": 3, "animationFrameCount": 2},
        ],
        "responsivenessAtPass": {
            "heartbeatCount": 4,
            "animationFrameCount": 3,
        },
        "responsivenessAtQuiescent": {
            "heartbeatCount": 4,
            "animationFrameCount": 3,
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
            smoke.READY_MARKER,
            f"{smoke.TICK_MARKER_PREFIX}1",
            f"{smoke.TICK_MARKER_PREFIX}2",
            f"{smoke.TICK_MARKER_PREFIX}3",
            smoke.QUIESCENT_MARKER,
            smoke.PASS_MARKER,
            smoke.LIFECYCLE_PASS_MARKER,
        ],
        "failedChecks": [],
        "error": None,
    }


def validate(result: dict[str, object]) -> None:
    smoke.validate_result(
        result,
        expected_versions=VERSIONS,
        expected_artifact_identity=ARTIFACT_IDENTITY,
        expected_capture_harness_identity=CAPTURE_HARNESS_IDENTITY,
    )


class M9WasmBrowserRepeatingTimerDomSmokeTest(unittest.TestCase):
    def test_accepts_three_native_ticks_and_clean_browser_drain(self) -> None:
        validate(successful_result())

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

    def test_native_timer_is_ui_owned_and_quiescent_before_shutdown(self) -> None:
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        header = source("chrome/browser/wasm/wasm_browser_main_parts.h")
        for marker in (
            "wasm-browser-m9-repeating-timer-smoke",
            "kWasmBrowserM9RepeatingTimerSmokeTickCount = 3",
            "kWasmBrowserM9RepeatingTimerSmokeInterval",
            "kWasmBrowserM9RepeatingTimerSmokeQuiescenceDuration",
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
            "runtime_arguments=[SWITCH]",
            "wait_for_normal_close_result",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, runner)
        self.assertNotIn("ccall(", runner)
        self.assertNotIn("drain_stream", runner)
        self.assertNotIn("stop_browser(", runner)

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
