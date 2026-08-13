#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the loopback-only M5 preflight runner."""

from __future__ import annotations

import copy
import contextlib
from collections import deque
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import m3_content_server
import run_m5_controlled_preflight_smoke as controlled_smoke
import run_m5_wisp_smoke
from tools.wasm.tests.m3_source_contract_test_support import source


VERSIONS = {
    "chromium": "chromium-revision",
    "v8": "v8-revision",
    "emscripten": "emscripten-revision",
    "port": "port-revision",
}


class FakeServer:
    server_address = ("127.0.0.1", 38123)


def relay_ready() -> run_m5_wisp_smoke.RelayReady:
    return run_m5_wisp_smoke.parse_relay_ready_line(
        json.dumps(
            {
                "schema_version": 1,
                "wispEndpoint": "ws://127.0.0.1:40123/wisp/",
                "httpsUrl": "https://a.test:4443/m5/",
                "redirectUrl": "https://a.test:4443/m5/redirect-cookie",
                "plaintextHttpControlUrl": (
                    "http://a.test:4446/m5/plaintext-control"
                ),
                "mixedContentTargetUrl": (
                    "http://a.test:4446/m5/mixed-content-target"
                ),
                "http1Url": "https://a.test:4444/m5/cors-resource",
                "tlsFailureUrl": "https://a.test:4445/m5/tls-name-mismatch",
                "transcriptUrl": "http://127.0.0.1:40123/status",
            }
        )
    )


def passing_result() -> dict[str, object]:
    devtools = controlled_smoke.expected_controlled_preflight_devtools_network()
    return {
        "protocol": 1,
        "case": "wisp_controlled_preflight_m5",
        "status": "pass",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "versions": copy.deepcopy(VERSIONS),
        "initialFrame": {"id": 1, "width": 800, "height": 600},
        "controlledPreflightFrame": {"id": 2, "width": 800, "height": 600},
        "navigationResult": {"ok": True, "scheme": "https"},
        "controlledPreflightDevtoolsNetworkEnabled": {
            "protocol": 1,
            "state": "enabled",
            "networkEnabled": True,
            "events": [],
        },
        "readiness": {
            "runtimeInitialized": True,
            "shellReady": True,
            "surfaceReady": True,
            "navigationCommitted": True,
            "firstVisuallyNonEmptyPaint": True,
            "fatalErrors": [],
            "navigation": {
                "committed": True,
                "scheme": "https",
                "responseCode": 200,
                "connectionProtocol": "h2",
            },
            "controlledPreflightDevtoolsNetwork": devtools,
            "heartbeat": {
                "anchor": "m5-controlled-preflight-navigation-committed",
                "timerDelta": 2,
                "animationFrameDelta": 2,
                "maxTimerGapMs": 25,
            },
        },
        "logs": {
            "host": [
                "initialize:wisp-configured",
                "initialize:factory-resolved",
                "navigation:requested:data",
                "m5:controlled-preflight-devtools-network:start-requested",
                "m5:controlled-preflight-devtools-network:enabled",
                "navigation:requested:m5-controlled-preflight",
                "navigation:committed:m5-controlled-preflight",
                "m5:controlled-preflight-devtools-network:complete",
                "shutdown:complete",
            ],
            "stdout": [],
            "stderr": [],
        },
        "shutdown": {
            "ok": True,
            "accepted": True,
            "complete": True,
            "exitCode": 0,
            "runtimeExitCode": 0,
        },
        "failedChecks": [],
        "error": None,
    }


def passing_relay_status() -> dict[str, object]:
    return {
        "fixture": "chromium-wasm-m5-network-v1",
        "protocol": 1,
        "ready": True,
        "wispSessions": 1,
        "rejectedDestinations": 1,
        "localGatewayBlockedPortAttempts": 1,
        "localGateway443StreamsOpened": 1,
        "localGateway443Requests": 1,
        "udpPackets": 0,
        "relayErrors": 0,
        "h2Requests": {"protocol": "h2", "count": 1},
        "requestedDestinations": [{"hostname": "a.test", "port": 443}],
        "transcript": [
            {"sequence": 1, "event": "wisp-connected"},
            {"sequence": 2, "event": "wisp-ready"},
            {"sequence": 3, "event": "local-gateway-444-blocked"},
            {
                "sequence": 4,
                "event": "connect-requested",
                "destination": "a.test:443",
            },
            {
                "sequence": 5,
                "event": "connect-open",
                "destination": "a.test:443",
            },
            {"sequence": 6, "event": "local-gateway-443-request"},
        ],
    }


def debug_cdp_snapshot() -> dict[str, object]:
    return {
        "state": "captured",
        "page": {
            "ready_state": "complete",
            "root_state": "running",
            "cross_origin_isolated": True,
            "shared_array_buffer": True,
            "host_present": True,
            "canvas_present": True,
            "canvas_focused": True,
        },
        "host": {
            "logs_available": True,
            "host_log_count": 5,
            "stdout_line_count": 1,
            "stderr_line_count": 2,
            "fatal_log_count": 0,
            "markers": {
                "initialize_start": True,
                "wisp_configured": True,
                "runtime_initialized": True,
                "factory_resolved": True,
                "initialize_complete": False,
            },
            "stdout_markers": {
                "loading_workers": 1,
                "worker_error": 0,
                "wasm": 1,
                "abort": 0,
                "error": 0,
            },
            "stderr_markers": {
                "loading_workers": 0,
                "worker_error": 1,
                "wasm": 0,
                "abort": 0,
                "error": 1,
            },
            "phases": {
                "resize": True,
                "bootstrap_requested": True,
                "network_preparation_requested": True,
                "network_enabled": True,
                "preflight_requested": False,
                "preflight_committed": False,
                "shutdown_accepted": False,
                "shutdown_complete": False,
                "shutdown_failed": False,
                "process_exit": False,
                "runtime_exit": False,
            },
            "fatal_markers": {
                "controlled_preflight": 1,
                "devtools_network": 1,
                "recorder_start_failed": 0,
                "agent_host_closed": 0,
                "gateway_denial": 0,
                "primary_frame_not_live": 0,
                "wisp_evidence_window_rejected": 0,
                "wisp_initial_diagnostics_not_clean": 0,
                "early_exit": 0,
                "shutdown": 0,
                "wisp": 0,
                "socket": 0,
                "uncaught": 0,
                "invalid": 1,
            },
            "readiness": {
                "available": False,
                "runtime_initialized": False,
                "shell_ready": False,
                "surface_ready": False,
                "navigation_committed": False,
                "first_visually_non_empty_paint": False,
                "fatal_error_count": 0,
                "frame_present": False,
            },
        },
        "resources": {
            "wasm": 1,
            "javascript": 2,
            "blob": 1,
            "other": 0,
        },
    }


class FakeDebugBrowser:
    def __init__(self, return_code: int | None = None) -> None:
        self.return_code = return_code

    def poll(self) -> int | None:
        return self.return_code


class FakeDebugClient:
    def __init__(self, value: object) -> None:
        self.value = value
        self.closed = False
        self.expression = ""

    def evaluate(self, expression: str) -> object:
        self.expression = expression
        return self.value

    def close(self) -> None:
        self.closed = True


class FakeProcess:
    def __init__(self, name: str) -> None:
        self.name = name
        self.stdout = object()
        self.stderr = object()

    def poll(self) -> None:
        return None


class FakeThread:
    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    def start(self) -> None:
        pass

    def join(self, timeout: float | None = None) -> None:
        del timeout


class FakeRunningServer:
    server_address = ("127.0.0.1", 38123)

    def serve_forever(self) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def server_close(self) -> None:
        pass


class M5ControlledPreflightSmokeTest(unittest.TestCase):
    def test_shared_browser_command_captures_worker_diagnostics(self) -> None:
        command = run_m5_wisp_smoke.m5_browser_command(
            Path("/test/browser"),
            "/test/profile",
            "http://127.0.0.1:38123/__m3__/",
            no_sandbox=True,
        )

        self.assertIn("--enable-logging=stderr", command)
        self.assertIn("--no-sandbox", command)
        self.assertIn(
            f"--window-size={run_m5_wisp_smoke.M5_BROWSER_WINDOW_SIZE}",
            command,
        )

    def test_debug_cdp_switches_are_loopback_only(self) -> None:
        switches = controlled_smoke.controlled_preflight_debug_cdp_switches(40123)

        self.assertEqual(
            switches,
            [
                "--remote-allow-origins=http://localhost",
                "--remote-debugging-address=127.0.0.1",
                "--remote-debugging-port=40123",
            ],
        )
        self.assertNotIn("0.0.0.0", " ".join(switches))
        with self.assertRaises(M0Error):
            controlled_smoke.controlled_preflight_debug_cdp_switches(0)

    def test_debug_cdp_snapshot_is_strictly_redacted(self) -> None:
        raw = debug_cdp_snapshot()
        raw["unrecognized"] = "wss://private.invalid/secret"
        raw["page"]["ready_state"] = "https://private.invalid/secret"  # type: ignore[index]
        raw["host"]["host_log_count"] = 9999  # type: ignore[index]
        raw["host"]["stdout_markers"]["unrecognized"] = (  # type: ignore[index]
            "https://private.invalid/secret"
        )

        snapshot = controlled_smoke.sanitize_controlled_preflight_debug_snapshot(raw)
        serialized = json.dumps(snapshot, sort_keys=True)

        self.assertEqual(snapshot["state"], "captured")
        self.assertEqual(snapshot["page"]["ready_state"], "other")  # type: ignore[index]
        self.assertEqual(
            snapshot["host"]["host_log_count"],  # type: ignore[index]
            controlled_smoke.DEBUG_CDP_MAXIMUM_COUNT,
        )
        self.assertNotIn("://", serialized)
        self.assertNotIn("private.invalid", serialized)

    def test_debug_cdp_capture_closes_client_and_preserves_only_schema(self) -> None:
        client = FakeDebugClient(debug_cdp_snapshot())
        with mock.patch.object(
            controlled_smoke, "wait_for_page_client", return_value=client
        ) as wait_for_client:
            snapshot = controlled_smoke.capture_controlled_preflight_debug_snapshot(
                browser=FakeDebugBrowser(),
                debug_port=40123,
                host_url_prefix="http://127.0.0.1:38123/__m3__/",
        )

        self.assertTrue(client.closed)
        self.assertIn("await host.logs()", client.expression)
        self.assertIn("await host.readiness()", client.expression)
        self.assertEqual(snapshot["state"], "captured")
        self.assertTrue(snapshot["host"]["markers"]["factory_resolved"])  # type: ignore[index]
        self.assertEqual(wait_for_client.call_args.args[:2], (40123, "http://127.0.0.1:38123/__m3__/"))

    def test_debug_cdp_capture_classifies_target_unavailability(self) -> None:
        with mock.patch.object(
            controlled_smoke,
            "wait_for_page_client",
            side_effect=M0Error("unavailable: ws://private.invalid/"),
        ):
            snapshot = controlled_smoke.capture_controlled_preflight_debug_snapshot(
                browser=FakeDebugBrowser(),
                debug_port=40123,
                host_url_prefix="http://127.0.0.1:38123/__m3__/",
            )

        self.assertEqual(snapshot, {"state": "target_unavailable"})

    def test_failure_diagnostics_store_only_the_redacted_cdp_subtree(self) -> None:
        raw = debug_cdp_snapshot()
        raw["page"]["root_state"] = "wss://private.invalid/secret"  # type: ignore[index]
        snapshot = controlled_smoke.sanitize_controlled_preflight_debug_snapshot(raw)

        with tempfile.TemporaryDirectory() as temporary:
            output = controlled_smoke.write_failure_diagnostics(
                Path(temporary),
                stage="wait_for_result",
                error=M0Error("timeout"),
                result=None,
                relay_status=None,
                relay_capture_state="unavailable",
                browser_stderr=deque(),
                relay_stderr=deque(),
                debug_cdp=snapshot,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(payload["debug_cdp"], snapshot)
        self.assertNotIn("://", json.dumps(payload["debug_cdp"]))
        self.assertEqual(payload["relay_status"], {"state": "unavailable"})

    def test_failure_diagnostics_redact_relay_status(self) -> None:
        relay_status = passing_relay_status()
        relay_status["requestedDestinations"].append(  # type: ignore[index]
            {"hostname": "private.invalid", "port": 5678}
        )
        relay_status["transcript"].append(  # type: ignore[index]
            {
                "sequence": 7,
                "event": "wss://private.invalid/secret",
                "destination": "private.invalid:5678",
            }
        )
        relay_status["h2Requests"] = {  # type: ignore[index]
            "protocol": "https://private.invalid/secret",
            "count": 9999,
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = controlled_smoke.write_failure_diagnostics(
                Path(temporary),
                stage="wait_for_result",
                error=M0Error("timeout"),
                result=None,
                relay_status=relay_status,
                relay_capture_state="captured",
                browser_stderr=deque(),
                relay_stderr=deque(),
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        snapshot = payload["relay_status"]
        serialized = json.dumps(snapshot, sort_keys=True)
        self.assertEqual(snapshot["state"], "captured")
        self.assertEqual(snapshot["h2"]["protocol"], "other")
        self.assertEqual(
            snapshot["h2"]["request_count"],  # type: ignore[index]
            controlled_smoke.DEBUG_CDP_MAXIMUM_COUNT,
        )
        self.assertEqual(
            snapshot["requested_destinations"]["a_test_443_count"],  # type: ignore[index]
            1,
        )
        self.assertNotIn("://", serialized)
        self.assertNotIn("private.invalid", serialized)

    def test_main_captures_relay_before_failure_cleanup(self) -> None:
        relay = FakeProcess("relay")
        browser = FakeProcess("browser")
        server = FakeRunningServer()
        events: list[str] = []
        captured_diagnostics: dict[str, object] = {}

        def fake_fetch_relay_transcript(
            transcript_url: str, *, timeout_seconds: float
        ) -> dict[str, object]:
            self.assertEqual(transcript_url, relay_ready().transcript_url)
            self.assertEqual(timeout_seconds, 2.0)
            events.append("fetch_relay")
            return passing_relay_status()

        def fake_stop_browser(process: FakeProcess) -> None:
            events.append(f"stop_{process.name}")

        def fake_abort_relay(
            process: FakeProcess,
            readers: object,
            *,
            description: str,
            unowned_streams: object,
        ) -> None:
            self.assertEqual(process, relay)
            self.assertEqual(description, "M5 controlled preflight relay")
            self.assertEqual(unowned_streams, ())
            self.assertEqual(len(tuple(readers)), 2)
            events.append("abort_relay")

        abort_patcher = mock.patch.object(
            controlled_smoke,
            "abort_process_group",
            side_effect=fake_abort_relay,
        )
        self.addCleanup(abort_patcher.stop)
        abort_patcher.start()

        def fake_write_failure_diagnostics(
            diagnostics_dir: Path, **kwargs: object
        ) -> Path:
            del diagnostics_dir
            events.append("write_diagnostics")
            captured_diagnostics.update(kwargs)
            return Path("/tmp/m5-controlled-preflight-failure.json")

        with tempfile.TemporaryDirectory() as temporary:
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "run_m5_controlled_preflight_smoke.py",
                        "--out-dir",
                        temporary,
                        "--timeout",
                        "1",
                    ],
                ),
                mock.patch.object(controlled_smoke, "load_manifest", return_value={}),
                mock.patch.object(
                    controlled_smoke, "checked_output", return_value="head"
                ),
                mock.patch.object(
                    controlled_smoke, "manifest_versions", return_value=VERSIONS
                ),
                mock.patch.object(controlled_smoke, "print_context"),
                mock.patch.object(
                    controlled_smoke,
                    "find_browser",
                    return_value=(Path("/browser"), "browser-version"),
                ),
                mock.patch.object(
                    controlled_smoke, "find_node", return_value=Path("/node")
                ),
                mock.patch.object(
                    controlled_smoke, "verify_no_private_key_pem_artifacts"
                ),
                mock.patch.object(
                    controlled_smoke, "create_m3_server", return_value=server
                ),
                mock.patch.object(
                    controlled_smoke.threading, "Thread", FakeThread
                ),
                mock.patch.object(
                    controlled_smoke,
                    "m5_host_origin",
                    return_value="http://127.0.0.1:38123",
                ),
                mock.patch.object(
                    controlled_smoke, "relay_command", return_value=["relay"]
                ),
                mock.patch.object(
                    controlled_smoke,
                    "wait_for_relay_ready",
                    return_value=relay_ready(),
                ),
                mock.patch.object(
                    controlled_smoke,
                    "controlled_preflight_smoke_url",
                    return_value="http://127.0.0.1:38123/__m3__/?test",
                ),
                mock.patch.object(
                    controlled_smoke,
                    "m5_browser_command",
                    return_value=["browser"],
                ),
                mock.patch.object(
                    controlled_smoke.subprocess,
                    "Popen",
                    side_effect=[relay, browser],
                ),
                mock.patch.object(
                    controlled_smoke,
                    "wait_for_result",
                    side_effect=M0Error("timeout"),
                ),
                mock.patch.object(
                    controlled_smoke,
                    "fetch_relay_transcript",
                    side_effect=fake_fetch_relay_transcript,
                ),
                mock.patch.object(
                    controlled_smoke,
                    "stop_browser",
                    side_effect=fake_stop_browser,
                ),
                mock.patch.object(
                    controlled_smoke,
                    "write_failure_diagnostics",
                    side_effect=fake_write_failure_diagnostics,
                ),
            ):
                self.assertEqual(controlled_smoke.main(), 1)

        self.assertLess(events.index("fetch_relay"), events.index("stop_browser"))
        self.assertLess(
            events.index("fetch_relay"), events.index("abort_relay")
        )
        self.assertEqual(captured_diagnostics["relay_capture_state"], "captured")
        self.assertEqual(
            captured_diagnostics["relay_status"], passing_relay_status()
        )

    def test_main_suppresses_terminal_records_when_relay_cleanup_fails(self) -> None:
        relay = FakeProcess("relay")
        browser = FakeProcess("browser")
        server = FakeRunningServer()
        stop_relay = mock.Mock(side_effect=M0Error("relay cleanup failed"))
        abort_relay = mock.Mock()
        stdout = io.StringIO()
        stderr = io.StringIO()

        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "run_m5_controlled_preflight_smoke.py",
                        "--out-dir",
                        temporary,
                        "--timeout",
                        "1",
                    ],
                )
            )
            stack.enter_context(
                mock.patch.object(controlled_smoke, "load_manifest", return_value={})
            )
            stack.enter_context(
                mock.patch.object(controlled_smoke, "checked_output", return_value="head")
            )
            stack.enter_context(
                mock.patch.object(
                    controlled_smoke, "manifest_versions", return_value=VERSIONS
                )
            )
            stack.enter_context(mock.patch.object(controlled_smoke, "print_context"))
            stack.enter_context(
                mock.patch.object(
                    controlled_smoke,
                    "find_browser",
                    return_value=(Path("/browser"), "browser-version"),
                )
            )
            stack.enter_context(
                mock.patch.object(controlled_smoke, "find_node", return_value=Path("/node"))
            )
            stack.enter_context(
                mock.patch.object(controlled_smoke, "verify_no_private_key_pem_artifacts")
            )
            stack.enter_context(
                mock.patch.object(controlled_smoke, "create_m3_server", return_value=server)
            )
            stack.enter_context(
                mock.patch.object(controlled_smoke.threading, "Thread", FakeThread)
            )
            stack.enter_context(
                mock.patch.object(
                    controlled_smoke,
                    "m5_host_origin",
                    return_value="http://127.0.0.1:38123",
                )
            )
            stack.enter_context(
                mock.patch.object(controlled_smoke, "relay_command", return_value=["relay"])
            )
            stack.enter_context(
                mock.patch.object(
                    controlled_smoke, "wait_for_relay_ready", return_value=relay_ready()
                )
            )
            stack.enter_context(
                mock.patch.object(
                    controlled_smoke,
                    "controlled_preflight_smoke_url",
                    return_value="http://127.0.0.1:38123/__m3__/?test",
                )
            )
            stack.enter_context(
                mock.patch.object(controlled_smoke, "m5_browser_command", return_value=["browser"])
            )
            stack.enter_context(
                mock.patch.object(
                    controlled_smoke.subprocess,
                    "Popen",
                    side_effect=[relay, browser],
                )
            )
            stack.enter_context(
                mock.patch.object(
                    controlled_smoke, "wait_for_result", return_value=passing_result()
                )
            )
            stack.enter_context(
                mock.patch.object(
                    controlled_smoke,
                    "fetch_relay_transcript",
                    return_value=passing_relay_status(),
                )
            )
            stack.enter_context(
                mock.patch.object(controlled_smoke, "stop_process_group", stop_relay)
            )
            stack.enter_context(
                mock.patch.object(controlled_smoke, "abort_process_group", abort_relay)
            )
            stack.enter_context(mock.patch.object(controlled_smoke, "stop_browser"))
            stack.enter_context(
                mock.patch.object(
                    controlled_smoke,
                    "write_failure_diagnostics",
                    return_value=Path("/tmp/controlled-preflight.json"),
                )
            )
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(controlled_smoke.main(), 1)

        terminal = stdout.getvalue() + stderr.getvalue()
        for marker in ("BROWSER_RESULT", "RELAY_TRANSCRIPT", "PASS"):
            with self.subTest(marker=marker):
                self.assertNotIn(f"{controlled_smoke.SENTINEL}:{marker}", terminal)
        stop_relay.assert_called_once()
        abort_relay.assert_called_once()
        self.assertEqual(
            abort_relay.call_args.kwargs["description"],
            "M5 controlled preflight relay",
        )
        self.assertEqual(abort_relay.call_args.kwargs["unowned_streams"], ())

    def test_main_preserves_partial_raw_pipe_ownership_before_reader_setup(self) -> None:
        relay = FakeProcess("relay")
        relay.stdout = None
        server = FakeRunningServer()
        abort_relay = mock.Mock()
        stdout = io.StringIO()
        stderr = io.StringIO()

        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "run_m5_controlled_preflight_smoke.py",
                        "--out-dir",
                        temporary,
                        "--timeout",
                        "1",
                    ],
                )
            )
            stack.enter_context(
                mock.patch.object(controlled_smoke, "load_manifest", return_value={})
            )
            stack.enter_context(
                mock.patch.object(controlled_smoke, "checked_output", return_value="head")
            )
            stack.enter_context(
                mock.patch.object(
                    controlled_smoke, "manifest_versions", return_value=VERSIONS
                )
            )
            stack.enter_context(mock.patch.object(controlled_smoke, "print_context"))
            stack.enter_context(
                mock.patch.object(
                    controlled_smoke,
                    "find_browser",
                    return_value=(Path("/browser"), "browser-version"),
                )
            )
            stack.enter_context(
                mock.patch.object(controlled_smoke, "find_node", return_value=Path("/node"))
            )
            stack.enter_context(
                mock.patch.object(controlled_smoke, "verify_no_private_key_pem_artifacts")
            )
            stack.enter_context(
                mock.patch.object(controlled_smoke, "create_m3_server", return_value=server)
            )
            stack.enter_context(
                mock.patch.object(controlled_smoke.threading, "Thread", FakeThread)
            )
            stack.enter_context(
                mock.patch.object(
                    controlled_smoke,
                    "m5_host_origin",
                    return_value="http://127.0.0.1:38123",
                )
            )
            stack.enter_context(
                mock.patch.object(controlled_smoke, "relay_command", return_value=["relay"])
            )
            stack.enter_context(
                mock.patch.object(controlled_smoke.subprocess, "Popen", return_value=relay)
            )
            stack.enter_context(
                mock.patch.object(controlled_smoke, "abort_process_group", abort_relay)
            )
            stack.enter_context(
                mock.patch.object(
                    controlled_smoke,
                    "write_failure_diagnostics",
                    return_value=Path("/tmp/controlled-preflight.json"),
                )
            )
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(controlled_smoke.main(), 1)

        terminal = stdout.getvalue() + stderr.getvalue()
        self.assertIn("FAIL reason=controlled preflight relay output pipes are unavailable", terminal)
        abort_relay.assert_called_once()
        self.assertEqual(abort_relay.call_args.args[1], ())
        self.assertEqual(
            abort_relay.call_args.kwargs["unowned_streams"],
            (relay.stderr,),
        )

    def test_smoke_url_has_only_transport_and_metadata_inputs(self) -> None:
        url = controlled_smoke.controlled_preflight_smoke_url(
            FakeServer(), "result-token", VERSIONS, relay_ready=relay_ready()
        )
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)

        self.assertEqual(parsed.scheme, "http")
        self.assertEqual(parsed.hostname, "127.0.0.1")
        self.assertEqual(
            query["case"], [m3_content_server.M5_CONTROLLED_PREFLIGHT_CASE]
        )
        self.assertEqual(
            query["module"], [
                "/__m3__/artifacts/"
                "content_shell_wasm_m5_controlled_preflight_test.js"
            ],
        )
        self.assertEqual(query["wisp_endpoint"], ["ws://127.0.0.1:40123/wisp/"])
        for forbidden in (
            "m5_url",
            "httpsUrl",
            "m5_public_url",
            "redirect_url",
            "m5_plaintext_http_control_url",
        ):
            self.assertNotIn(forbidden, query)

    def test_runner_uses_bounded_relay_readers_and_terminal_cleanup(self) -> None:
        runner = source("tools/wasm/run_m5_controlled_preflight_smoke.py")

        self.assertNotIn("_drain_relay_stdout", runner)
        self.assertNotIn("assert relay.stdout", runner)
        self.assertNotIn("assert relay.stderr", runner)
        self.assertIn("BrowserStderrReader(", runner)
        self.assertIn("relay_stdout_stream = relay.stdout", runner)
        self.assertIn("relay_stderr_stream = relay.stderr", runner)
        self.assertIn("relay output pipes are unavailable", runner)
        self.assertIn("on_line=ready_lines.put", runner)
        self.assertIn("on_eof=lambda: ready_lines.put(None)", runner)
        self.assertIn("stop_process_group(", runner)
        self.assertIn("abort_process_group(", runner)
        self.assertIn("unowned_streams=tuple(", runner)
        self.assertLess(
            runner.index("relay_stdout_stream = relay.stdout"),
            runner.index("relay output pipes are unavailable"),
        )
        self.assertLess(
            runner.index("relay output pipes are unavailable"),
            runner.index("BrowserStderrReader("),
        )
        self.assertLess(
            runner.index('stage = "cleanup_relay_before_pass"'),
            runner.index('f"{SENTINEL}:BROWSER_RESULT'),
        )
        self.assertLess(
            runner.index('stage = "cleanup_relay_before_pass"'),
            runner.index(f'print(f"{{SENTINEL}}:PASS"'),
        )

    def test_passing_result_is_accepted(self) -> None:
        controlled_smoke.validate_controlled_preflight_result(
            passing_result(), expected_versions=VERSIONS
        )

    def test_result_rejects_urls_and_mutated_native_evidence(self) -> None:
        invalid_url = passing_result()
        invalid_url["error"] = "https://leaked.invalid/"
        with self.assertRaises(M0Error):
            controlled_smoke.validate_controlled_preflight_result(
                invalid_url, expected_versions=VERSIONS
            )

        invalid_protocol = passing_result()
        invalid_protocol["readiness"]["controlledPreflightDevtoolsNetwork"][
            "responseProtocol"
        ] = "http/1.1"
        with self.assertRaises(M0Error):
            controlled_smoke.validate_controlled_preflight_result(
                invalid_protocol, expected_versions=VERSIONS
            )

        invalid_events = passing_result()
        invalid_events["readiness"]["controlledPreflightDevtoolsNetwork"][
            "events"
        ].pop()
        with self.assertRaises(M0Error):
            controlled_smoke.validate_controlled_preflight_result(
                invalid_events, expected_versions=VERSIONS
            )

    def test_passing_relay_transcript_is_accepted(self) -> None:
        controlled_smoke.validate_controlled_preflight_relay_transcript(
            passing_relay_status()
        )

    def test_relay_rejects_denial_after_document_or_a_second_destination(self) -> None:
        wrong_order = passing_relay_status()
        wrong_order["transcript"][2], wrong_order["transcript"][5] = (
            wrong_order["transcript"][5],
            wrong_order["transcript"][2],
        )
        with self.assertRaises(M0Error):
            controlled_smoke.validate_controlled_preflight_relay_transcript(
                wrong_order
            )

        extra_destination = passing_relay_status()
        extra_destination["requestedDestinations"].append(
            {"hostname": "a.test", "port": 444}
        )
        with self.assertRaises(M0Error):
            controlled_smoke.validate_controlled_preflight_relay_transcript(
                extra_destination
            )

    def test_harness_admits_the_controlled_preflight_result_case(self) -> None:
        self.assertIn(
            m3_content_server.M5_CONTROLLED_PREFLIGHT_CASE,
            m3_content_server.M3_RESULT_CASES,
        )


if __name__ == "__main__":
    unittest.main()
