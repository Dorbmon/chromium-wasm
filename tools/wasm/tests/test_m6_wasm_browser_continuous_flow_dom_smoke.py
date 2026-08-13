#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the formal Target-6 continuous Chrome flow."""

from __future__ import annotations

import base64
from collections import deque
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error, REPO_ROOT
import run_m6_wasm_browser_continuous_flow_dom_smoke as smoke
import run_m6_wasm_browser_controlled_https_smoke as controlled_https
from tools.wasm.tests.m3_source_contract_test_support import source


VERSIONS = {
    "chromium": "chromium-revision",
    "v8": "v8-revision",
    "emscripten": "emscripten-revision",
    "port": "port-revision",
}
PINNED_NODE = (
    REPO_ROOT / "third_party/emsdk/node/22.16.0_64bit/bin/node"
)
ARTIFACT_IDENTITY = {
    "artifact_delivery": smoke.ARTIFACT_DELIVERY,
    "artifact_source_provenance": smoke.ARTIFACT_SOURCE_PROVENANCE,
    "loader": {"bytes": 10, "sha256": "a" * 64},
    "module_name": smoke.DEFAULT_MODULE_NAME,
    "wasm": {"bytes": 20, "sha256": "b" * 64},
}


def target(x: int, y: int) -> dict[str, object]:
    return {"x": x, "y": y, "clientX": x + 0.5, "clientY": y + 0.5}


def pointer(event_type: str, item: dict[str, object], buttons: int) -> dict[str, object]:
    return {
        "type": event_type,
        "trusted": True,
        "cancelable": True,
        "pointerType": "mouse",
        "primary": True,
        "pointerId": 1,
        "button": 0,
        "buttons": buttons,
        "accepted": True,
        "defaultPrevented": True,
        "x": item["x"],
        "y": item["y"],
        "reason": None,
    }


def adapter_metadata(text: str, sequence: int) -> dict[str, object]:
    return {
        "attached": True,
        "editable": True,
        "shortcutComplete": True,
        "proxyFocused": True,
        "textQueued": True,
        "deliveryAccepted": True,
        "deliveryRejected": False,
        "focusGeneration": sequence,
        "acceptedDeliveryFocusGeneration": sequence,
        "proxySessionCleared": False,
        "pendingDeliveryCount": 0,
        "pendingTextUtf8Bytes": 0,
        "tombstonedDeliveryCount": 0,
        "ctrlLRecords": [
            {
                "type": event_type,
                "code": code,
                "trusted": True,
                "cancelable": True,
                "canvasFocused": True,
                "accepted": True,
                "defaultPrevented": True,
            }
            for event_type, code in (
                ("keydown", "ControlLeft"),
                ("keydown", "KeyL"),
                ("keyup", "KeyL"),
                ("keyup", "ControlLeft"),
            )
        ],
        "beforeInputRecords": [
            {
                "inputType": "insertText",
                "dataOmitted": True,
                "dataUtf16Units": len(text),
                "dataUtf8Bytes": len(text.encode("utf-8")),
                "trusted": True,
                "cancelable": True,
                "isComposing": False,
                "proxyFocused": True,
                "queued": True,
                "defaultPrevented": True,
                "sequence": sequence,
                "nativeDispatched": True,
                "nativeAccepted": True,
            }
        ],
        "browserTextDeliveryReports": [
            {"action": 4, "sessionId": 0, "sequence": sequence, "accepted": True}
        ],
        "enterRecords": [
            {
                "type": event_type,
                "code": "Enter",
                "key": "Enter",
                "trusted": True,
                "cancelable": True,
                "proxyFocused": True,
                "accepted": True,
                "defaultPrevented": True,
            }
            for event_type in ("keydown", "keyup")
        ],
        "rejectedRecords": [],
        "cleanupRecords": [],
    }


def transaction(phase: str, text: str, sequence: int) -> dict[str, object]:
    return {
        "phase": phase,
        "adapterId": 1,
        "expectedSequence": sequence,
        "ctrlLComplete": True,
        "proxyFocused": True,
        "admissionCount": 1,
        "deliveryCount": 1,
        "deliverySequences": [sequence],
        "deliveryAccepted": True,
        "enterComplete": True,
        "rejected": False,
        "adapter": adapter_metadata(text, sequence),
    }


def flow_result() -> dict[str, object]:
    contract = controlled_https.load_controlled_https_screenshot_contract()
    baseline = smoke.CONTROLLED_HTTPS_SCREENSHOT_CONTRACT.with_name(
        str(contract["baseline"])
    ).read_bytes()
    targets = [target(100 + index * 30, 32 + index * 12) for index in range(7)]
    actions: list[dict[str, object]] = []
    for item in targets:
        actions.extend((pointer("down", item, 1), pointer("up", item, 0)))
    proof: dict[str, object] = {
        "wispConfigured": True,
        "runtimeArgumentsConfigured": True,
        "configurationPrecededFactory": True,
        "readyObserved": True,
        "httpsNavigatedObserved": True,
        "versionReadyObserved": True,
        "versionNavigatedObserved": True,
        "firstTabSelectedObserved": True,
        "menuReadyObserved": True,
        "menuOpenedObserved": True,
        "settingsNavigatedObserved": True,
        "firstTabReturnedObserved": True,
        "secondTabClosedObserved": True,
        "reloadReadyObserved": True,
        "reloadedObserved": True,
        "firstFvpObserved": True,
        "secondFvpObserved": True,
        "check1Queued": True,
        "check2Queued": True,
        "check3Queued": True,
        "check4Queued": True,
        "check5Queued": True,
        "check6Queued": True,
        "finalPresentationQueued": True,
        "passObserved": True,
        "timeoutObserved": False,
        "newTabTarget": targets[0],
        "switchFirstTarget": targets[1],
        "switchSecondTarget": targets[2],
        "menuTarget": targets[3],
        "settingsTarget": targets[4],
        "returnFirstTarget": targets[5],
        "closeSecondTarget": targets[6],
        "newTabActionOffset": 0,
        "switchFirstActionOffset": 2,
        "switchSecondActionOffset": 4,
        "menuActionOffset": 6,
        "settingsActionOffset": 8,
        "returnFirstActionOffset": 10,
        "closeSecondActionOffset": 12,
    }
    for before, after in (
        ("frameAtHttpsNavigated", "frameAfterHttpsNavigated"),
        ("frameAtFirstFvp", "frameAfterFirstFvp"),
        ("frameAtVersionReady", "frameAfterVersionReady"),
        ("frameAtVersionNavigated", "frameAfterVersionNavigated"),
        ("frameAtFirstTabSelected", "frameAfterFirstTabSelected"),
        ("frameAtMenuReady", "frameAfterMenuReady"),
        ("frameAtMenuOpened", "frameAfterMenuOpened"),
        ("frameAtSettingsNavigated", "frameAfterSettingsNavigated"),
        ("frameAtFirstTabReturned", "frameAfterFirstTabReturned"),
        ("frameAtReloadReady", "frameAfterReloadReady"),
        ("frameAtReloaded", "frameAfterReloaded"),
        ("frameAtSecondFvp", "frameAfterSecondFvp"),
    ):
        index = len([key for key in proof if key.startswith("frameAt")]) + 1
        proof[before] = index * 2
        proof[after] = index * 2 + 1
    # Make the final phase explicit: a frame can occur after RELOADED but
    # before phase-2 FVP; only frameAfterSecondFvp is screenshot-eligible.
    proof["frameAtReloaded"] = 20
    proof["frameAfterReloaded"] = 21
    proof["frameAtSecondFvp"] = 21
    proof["frameAfterSecondFvp"] = 22
    output = list(smoke.MARKERS)
    return {
        "protocol": 1,
        "case": smoke.CASE,
        "scope": smoke.SCOPE,
        "phase": smoke.FLOW_PHASE,
        "status": "pass",
        "formalTarget6AcceptanceFlow": True,
        "m6ProductBreadthComplete": False,
        "runtimeExitCode": 0,
        "processExitCode": 0,
        "runtimeInitialized": True,
        "factorySettled": True,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "abort": None,
        "fatalErrors": [],
        "windowErrors": [],
        "unhandledRejections": [],
        "versions": copy.deepcopy(VERSIONS),
        "artifact": copy.deepcopy(ARTIFACT_IDENTITY),
        "frameReports": [
            {"id": index, "width": 640, "height": 480, "timestampMs": float(index)}
            for index in range(1, 30)
        ],
        "readiness": {
            "shellReady": True,
            "surfaceReady": True,
            "firstVisuallyNonEmptyPaint": True,
        },
        "readinessReports": [
            {
                "shellReady": True,
                "surfaceReady": True,
                "firstVisuallyNonEmptyPaint": True,
            }
        ],
        "ozoneFocusReports": [{"keyboardTargetPresent": True, "active": True}],
        "ozoneTextInputStates": [
            {"focusedClientPresent": True, "editable": True, "canComposeInline": True}
        ],
        "ozoneTextInputDeliveries": [],
        "ozoneCursorReports": [],
        "continuousFlow": proof,
        "hostInput": {
            "singlePersistentAction4Adapter": True,
            "action4SessionId": 0,
            "textTransactions": [
                transaction("https", smoke.HTTPS_TEXT, 1),
                transaction("version", smoke.VERSION_TEXT, 2),
            ],
            "textAdapterDetachedAfterSecondSequence": True,
            "proxyTextEmpty": True,
            "pointerRecords": actions,
            "ctrlRRecords": [
                {
                    "type": event_type,
                    "code": code,
                    "trusted": True,
                    "cancelable": True,
                    "canvasFocused": True,
                    "accepted": True,
                    "defaultPrevented": True,
                }
                for event_type, code in (
                    ("keydown", "ControlLeft"),
                    ("keydown", "KeyR"),
                    ("keyup", "KeyR"),
                    ("keyup", "ControlLeft"),
                )
            ],
            "reloadRejectedRecords": [],
            "reloadCleanupRecords": [],
            "adapter": {"pendingDeliveryCount": 0},
        },
        "screenshot": {
            "mimeType": "image/png",
            "dataBase64": base64.b64encode(baseline).decode("ascii"),
            "width": 640,
            "height": 480,
            "frameId": 22,
            "timestampMs": 22.0,
            "observationSequence": 40,
        },
        "canvasBackingStore": {"width": 640, "height": 480},
        "stdout": [],
        "stderr": output,
        "error": None,
    }


def restart_result() -> dict[str, object]:
    return {
        "protocol": 1,
        "case": smoke.CASE,
        "scope": smoke.SCOPE,
        "phase": smoke.RESTART_PHASE,
        "status": "pass",
        "formalTarget6AcceptanceFlow": False,
        "m6ProductBreadthComplete": False,
        "outerPageFreshRestart": True,
        "runtimeExitCode": 0,
        "processExitCode": 0,
        "runtimeInitialized": True,
        "factorySettled": True,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "abort": None,
        "fatalErrors": [],
        "windowErrors": [],
        "unhandledRejections": [],
        "versions": copy.deepcopy(VERSIONS),
        "artifact": copy.deepcopy(ARTIFACT_IDENTITY),
        "continuousFlow": {
            "restartReadyObserved": True,
            "restartPresentationQueued": True,
            "restartClosingObserved": True,
            "frameAtRestartReady": 1,
            "frameAfterRestartReady": 2,
        },
        "stdout": [],
        "stderr": list(smoke.RESTART_MARKERS),
        "error": None,
    }


class M6WasmBrowserContinuousFlowDomSmokeTest(unittest.TestCase):
    def _start_relay(self, source_text: str) -> subprocess.Popen[str]:
        return subprocess.Popen(
            [sys.executable, "-c", source_text],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

    def _relay_readers(
        self, relay: subprocess.Popen[str]
    ) -> tuple[smoke.BrowserStderrReader, smoke.BrowserStderrReader]:
        self.assertIsNotNone(relay.stdout)
        self.assertIsNotNone(relay.stderr)
        stdout_reader = smoke.BrowserStderrReader(
            relay.stdout,  # type: ignore[arg-type]
            deque(),
            name="continuous-flow-test-relay-stdout",
        )
        stderr_reader = smoke.BrowserStderrReader(
            relay.stderr,  # type: ignore[arg-type]
            deque(),
            name="continuous-flow-test-relay-stderr",
        )
        return stdout_reader, stderr_reader

    def _assert_group_absent(self, process: subprocess.Popen[str]) -> None:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.01)
        self.fail("continuous-flow relay process group remained alive")

    def _run_main_with_cleanup_fakes(
        self,
        *,
        browser_cleanup_error: BaseException | None = None,
        relay_cleanup_error: BaseException | None = None,
        server_cleanup_error: BaseException | None = None,
        profile_cleanup_error: BaseException | None = None,
        operational_error: BaseException | None = None,
        abort_browser_error: BaseException | None = None,
        abort_relay_error: BaseException | None = None,
        before_compare: Callable[[], None] | None = None,
    ) -> tuple[int, str, str, dict[str, mock.Mock]]:
        """Run the post-launch path without a real server, relay, or Chrome."""

        server = mock.Mock()
        server.artifacts = {f"{smoke.DEFAULT_MODULE_NAME}.js": b"loader"}
        server_thread = mock.Mock()
        server_thread.is_alive.return_value = False
        relay = mock.Mock()
        relay.stdout = object()
        relay.stderr = object()
        browser = mock.Mock()
        browser.stderr = object()
        relay_stdout_reader = mock.Mock()
        relay_stderr_reader = mock.Mock()
        browser_stderr_reader = mock.Mock()
        profile = mock.Mock()
        profile.name = "/fake-profile"
        profile.cleanup.side_effect = profile_cleanup_error
        client = mock.Mock()
        relay_ready = mock.Mock()
        relay_ready.transcript_url = "http://relay.test/transcript"
        comparison = mock.Mock()
        comparison.matches = True
        comparison.as_dict.return_value = {"matches": True}

        def validate_flow(*_args: object, **_kwargs: object) -> bytes:
            if before_compare is not None:
                before_compare()
            return b"png"

        stop_browser = mock.Mock(side_effect=browser_cleanup_error)
        stop_relay = mock.Mock(side_effect=relay_cleanup_error)
        cleanup_server = mock.Mock(return_value=server_cleanup_error)
        abort_browser = mock.Mock(side_effect=abort_browser_error)
        abort_relay = mock.Mock(side_effect=abort_relay_error)
        wait_for_client = mock.Mock(return_value=client)
        dispatch_address = mock.Mock(side_effect=operational_error)
        dependencies = {
            "server": server,
            "server_thread": server_thread,
            "relay": relay,
            "browser": browser,
            "relay_stdout_reader": relay_stdout_reader,
            "relay_stderr_reader": relay_stderr_reader,
            "browser_stderr_reader": browser_stderr_reader,
            "profile": profile,
            "client": client,
            "stop_browser": stop_browser,
            "stop_relay": stop_relay,
            "cleanup_server": cleanup_server,
            "abort_browser": abort_browser,
            "abort_relay": abort_relay,
            "wait_for_client": wait_for_client,
            "dispatch_address": dispatch_address,
            "compare_screenshots": mock.Mock(return_value=comparison),
        }

        patches = (
            mock.patch.object(smoke, "check_boundary"),
            mock.patch.object(
                smoke.controlled_https, "check_controlled_https_boundary"
            ),
            mock.patch.object(smoke, "create_server", return_value=server),
            mock.patch.object(
                smoke, "artifact_identity", return_value=ARTIFACT_IDENTITY
            ),
            mock.patch.object(smoke, "verify_required_exports"),
            mock.patch.object(smoke, "verify_no_private_key_pem_snapshot_artifacts"),
            mock.patch.object(
                smoke.controlled_https,
                "load_controlled_https_screenshot_contract",
                return_value={
                    "baseline": "m6_controlled_https_browser_baseline.png",
                    "channel_tolerance": 2,
                    "maximum_different_pixel_ratio": 0.0025,
                },
            ),
            mock.patch.object(smoke, "load_manifest", return_value={}),
            mock.patch.object(smoke, "checked_output", return_value="test-head"),
            mock.patch.object(smoke, "manifest_versions", return_value=VERSIONS),
            mock.patch.object(smoke, "print_context", return_value={}),
            mock.patch.object(
                smoke, "find_browser", return_value=(Path("/fake-browser"), "test-browser")
            ),
            mock.patch.object(smoke, "find_node", return_value=Path("/fake-node")),
            mock.patch.object(smoke.threading, "Thread", return_value=server_thread),
            mock.patch.object(smoke, "relay_command", return_value=["relay"]),
            mock.patch.object(smoke, "browser_command", return_value=["browser"]),
            mock.patch.object(smoke, "m5_host_origin", return_value="http://host.test"),
            mock.patch.object(smoke.subprocess, "Popen", side_effect=[relay, browser]),
            mock.patch.object(
                smoke,
                "BrowserStderrReader",
                side_effect=(
                    relay_stdout_reader,
                    relay_stderr_reader,
                    browser_stderr_reader,
                ),
            ),
            mock.patch.object(
                smoke.controlled_https, "wait_for_relay_ready", return_value=relay_ready
            ),
            mock.patch.object(smoke, "smoke_url", return_value="http://host.test/smoke"),
            mock.patch.object(smoke.tempfile, "TemporaryDirectory", return_value=profile),
            mock.patch.object(smoke, "unused_loopback_port", return_value=9222),
            mock.patch.object(smoke, "wait_for_page_client", wait_for_client),
            mock.patch.object(smoke, "dispatch_address_transaction", dispatch_address),
            mock.patch.object(smoke, "wait_for_state", return_value={}),
            mock.patch.object(smoke, "click_target"),
            mock.patch.object(
                smoke, "wait_for_phase_result", side_effect=({"flow": True}, {"restart": True})
            ),
            mock.patch.object(smoke, "validate_flow_result", side_effect=validate_flow),
            mock.patch.object(
                smoke, "compare_screenshots", dependencies["compare_screenshots"]
            ),
            mock.patch.object(smoke, "validate_restart_result"),
            mock.patch.object(
                smoke.controlled_https, "fetch_relay_status", return_value={}
            ),
            mock.patch.object(smoke.controlled_https, "validate_relay_status"),
            mock.patch.object(smoke, "stop_browser_group", stop_browser),
            mock.patch.object(smoke, "stop_relay_group", stop_relay),
            mock.patch.object(
                smoke, "_cleanup_continuous_flow_server", cleanup_server
            ),
            mock.patch.object(smoke, "abort_browser_group", abort_browser),
            mock.patch.object(smoke, "abort_relay_group", abort_relay),
            mock.patch.object(
                smoke, "write_failure_diagnostics", return_value=Path("/diagnostic")
            ),
            mock.patch.object(sys, "argv", ["continuous-flow-runner"]),
        )
        with contextlib.ExitStack() as stack:
            for patcher in patches:
                stack.enter_context(patcher)
            stdout = stack.enter_context(
                mock.patch("sys.stdout", new_callable=io.StringIO)
            )
            stderr = stack.enter_context(
                mock.patch("sys.stderr", new_callable=io.StringIO)
            )
            result = smoke.main()
        return result, stdout.getvalue(), stderr.getvalue(), dependencies

    def test_host_is_deferred_ordinal_only_and_outer_restart_is_explicit(self) -> None:
        host = source("tools/wasm/host/chrome_wasm_browser_continuous_flow_smoke_host.js")
        for expected in (
            "ChromiumWasmTrustedTextInput",
            "ChromiumWasmTrustedPointerInput",
            "chromium_wasm_browser_host_continuous_flow_check",
            "chromium_wasm_browser_host_continuous_flow_presented",
            "setTimeout(() =>",
            "action4SessionId: 0",
            "textAdapterInstances === 1",
            "frameAtFirstFvp",
            "frameAfterFirstFvp",
            "frameAtSecondFvp",
            "frameAfterSecondFvp",
            "isStrictPostTargetFvpFrameForTesting",
            "location.replace(restart.href)",
            "RESTART_CLOSING",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, host)
        self.assertEqual(host.count("location.replace("), 1)
        for forbidden in ("window.open", "history.pushState", "Input.navigate"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, host)

    def test_runner_only_reads_frozen_state_then_dispatches_trusted_cdp_input(self) -> None:
        runner = source("tools/wasm/run_m6_wasm_browser_continuous_flow_dom_smoke.py")
        for expected in (
            "__chromiumWasmM6ContinuousFlowState",
            "client.dispatch_control_shortcut",
            'client.call("Input.insertText"',
            "Input.dispatchKeyEvent",
            "client.dispatch_primary_click",
            "compare_reviewed_baseline",
            "validate_restart_result",
            "--wasm-browser-host-continuous-flow-smoke",
            "--wasm-browser-host-continuous-flow-restart-smoke",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, runner)
        self.assertNotIn("Runtime.evaluate", runner)
        self.assertNotIn("ccall(", runner)
        self.assertNotIn("capture-baseline", runner)

    @unittest.skipUnless(os.name == "posix", "requires POSIX process groups")
    def test_reaped_relay_leader_with_pipe_holder_cannot_report_clean_cleanup(self) -> None:
        relay = self._start_relay(
            "import signal, subprocess, sys, time; "
            "subprocess.Popen([sys.executable, '-c', "
            "'import signal, time; signal.signal(signal.SIGTERM, "
            "signal.SIG_IGN); time.sleep(30)']); time.sleep(0.2); "
            "sys.stdout.write('relay leader exiting\\n'); sys.stdout.flush()"
        )
        stdout_reader, stderr_reader = self._relay_readers(relay)
        stdout_reader.start()
        stderr_reader.start()
        try:
            relay.wait(timeout=2)
            with (
                mock.patch.object(smoke, "CLEANUP_TIMEOUT_SECONDS", 0.1),
                self.assertRaisesRegex(M0Error, "required SIGKILL"),
            ):
                smoke.stop_relay_group(relay, stdout_reader, stderr_reader)
            self.assertFalse(stdout_reader.is_alive())
            self.assertFalse(stderr_reader.is_alive())
            self._assert_group_absent(relay)
        finally:
            try:
                smoke.abort_relay_group(relay, (stdout_reader, stderr_reader))
            except M0Error:
                pass

    @unittest.skipUnless(os.name == "posix", "requires POSIX process groups")
    def test_reaped_relay_leader_with_devnull_descendant_cannot_report_success(self) -> None:
        relay = self._start_relay(
            "import os, signal, subprocess, sys; "
            "subprocess.Popen([sys.executable, '-c', "
            "'import signal, time; signal.signal(signal.SIGTERM, "
            "signal.SIG_IGN); time.sleep(30)'], stdin=subprocess.DEVNULL, "
            "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(0.2); "
            "sys.stdout.write('relay leader exiting\\n'); sys.stdout.flush()"
        )
        stdout_reader, stderr_reader = self._relay_readers(relay)
        stdout_reader.start()
        stderr_reader.start()
        try:
            relay.wait(timeout=2)
            with (
                mock.patch.object(smoke, "CLEANUP_TIMEOUT_SECONDS", 0.1),
                self.assertRaisesRegex(M0Error, "required SIGKILL"),
            ):
                smoke.stop_relay_group(relay, stdout_reader, stderr_reader)
            self.assertFalse(stdout_reader.is_alive())
            self.assertFalse(stderr_reader.is_alive())
            self._assert_group_absent(relay)
        finally:
            try:
                smoke.abort_relay_group(relay, (stdout_reader, stderr_reader))
            except M0Error:
                pass

    @unittest.skipUnless(os.name == "posix", "requires POSIX process groups")
    def test_partial_relay_reader_start_failure_still_aborts_its_session(self) -> None:
        relay = self._start_relay("import time; time.sleep(30)")
        stdout_reader, stderr_reader = self._relay_readers(relay)
        stdout_reader.start()
        # Model a second Thread.start() failure: its pipe has not been handed
        # to a reader, while the first reader can already be blocked in read.
        self.assertFalse(stderr_reader.started)
        try:
            smoke.abort_relay_group(relay, (stdout_reader, stderr_reader))
            self.assertFalse(stdout_reader.is_alive())
            self.assertFalse(stderr_reader.started)
            self._assert_group_absent(relay)
        finally:
            try:
                smoke.abort_relay_group(relay, (stdout_reader, stderr_reader))
            except M0Error:
                pass

    def test_relay_cleanup_never_closes_live_readers(self) -> None:
        relay = mock.Mock()
        stdout_reader = mock.Mock()
        stderr_reader = mock.Mock()
        for reader in (stdout_reader, stderr_reader):
            reader.started = True
            reader.is_alive.return_value = True
            reader.error = None
            reader.reached_eof = False
        with (
            mock.patch.object(smoke, "_signal_relay_group"),
            mock.patch.object(
                smoke,
                "_wait_for_relay_cleanup",
                side_effect=[(False, None), (False, None)],
            ),
            self.assertRaisesRegex(M0Error, "output readers did not stop"),
        ):
            smoke.stop_relay_group(relay, stdout_reader, stderr_reader)
        stdout_reader.close_after_reader_stops.assert_not_called()
        stderr_reader.close_after_reader_stops.assert_not_called()

    def test_server_cleanup_uses_bounded_shutdown_and_handler_drain(self) -> None:
        server = mock.Mock()
        server_thread = mock.Mock()
        server_thread.is_alive.return_value = False
        with mock.patch.object(smoke, "shutdown_server_bounded") as shutdown:
            error = smoke._cleanup_continuous_flow_server(
                server=server,
                server_thread=server_thread,
                server_thread_started=True,
            )
        self.assertIsNone(error)
        shutdown.assert_called_once_with(
            server,
            timeout=smoke.CLEANUP_TIMEOUT_SECONDS,
            description="continuous-flow host server",
        )
        server.server_close.assert_called_once_with()
        server_thread.join.assert_called_once_with(timeout=smoke.CLEANUP_TIMEOUT_SECONDS)
        server.join_request_handlers.assert_called_once_with(
            timeout=smoke.CLEANUP_TIMEOUT_SECONDS,
            description="continuous-flow host server",
        )

    def test_cxx_lifecycle_has_exact_webui_and_watchdog_proof(self) -> None:
        coordinator = source("chrome/browser/wasm/wasm_browser_continuous_flow.cc")
        verifier = source("chrome/browser/wasm/wasm_browser_host_continuous_flow_smoke.cc")
        for expected in (
            "IsExactVersionWebUI",
            "kVersionTitle",
            "VersionUI",
            "IsExactSettingsWebUI",
            "WasmSettingsUI",
            "PAGE_TRANSITION_TYPED",
            "PAGE_TRANSITION_GENERATED",
            "PAGE_TRANSITION_RELOAD",
            "DidFirstVisuallyNonEmptyPaint",
            "ArmStepTimeout",
            "OnStepTimeout",
            "FailAndRequestOrderlyShutdown",
            "RESTART_CLOSING",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, coordinator)
        for expected in ("generation_", "dispatch_pending_", "PostTask", "kFinalPresentation"):
            with self.subTest(expected=expected):
                self.assertIn(expected, verifier)
        for forbidden in ("LoadURL", "ExecuteCommand", "NavigationController"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, verifier)

    def test_accepts_complete_target6_evidence(self) -> None:
        result = flow_result()
        contract = controlled_https.load_controlled_https_screenshot_contract()
        smoke.validate_flow_result(
            result,
            expected_versions=VERSIONS,
            expected_artifact_identity=ARTIFACT_IDENTITY,
            screenshot_contract=contract,
        )
        serialized = json.dumps(result, sort_keys=True)
        self.assertNotIn(smoke.HTTPS_TEXT, serialized)
        self.assertNotIn(smoke.VERSION_TEXT, serialized)

    def test_artifact_identity_requires_exact_schema_and_types(self) -> None:
        mutations: tuple[tuple[str, object], ...] = (
            ("missing", {key: value for key, value in ARTIFACT_IDENTITY.items() if key != "wasm"}),
            ("extra", {**ARTIFACT_IDENTITY, "extra": None}),
            ("bool", {**ARTIFACT_IDENTITY, "loader": {"bytes": True, "sha256": "a" * 64}}),
            ("fractional", {**ARTIFACT_IDENTITY, "loader": {"bytes": 1.5, "sha256": "a" * 64}}),
            ("module", {**ARTIFACT_IDENTITY, "module_name": "wrong_module"}),
        )
        for name, artifact in mutations:
            with self.subTest(name=name):
                with self.assertRaisesRegex(M0Error, "artifact"):
                    smoke.validate_artifact_identity(
                        artifact, expected_artifact_identity=ARTIFACT_IDENTITY
                    )

    def test_flow_and_restart_reject_artifact_substitution(self) -> None:
        contract = controlled_https.load_controlled_https_screenshot_contract()
        substituted = copy.deepcopy(ARTIFACT_IDENTITY)
        substituted["wasm"] = {"bytes": 21, "sha256": "c" * 64}
        flow = flow_result()
        flow["artifact"] = substituted
        with self.assertRaisesRegex(M0Error, "artifact identity disagrees"):
            smoke.validate_flow_result(
                flow,
                expected_versions=VERSIONS,
                expected_artifact_identity=ARTIFACT_IDENTITY,
                screenshot_contract=contract,
            )
        restart = restart_result()
        restart["artifact"] = substituted
        with self.assertRaisesRegex(M0Error, "artifact identity disagrees"):
            smoke.validate_restart_result(
                restart,
                expected_versions=VERSIONS,
                expected_artifact_identity=ARTIFACT_IDENTITY,
            )

    def test_server_serves_immutable_artifact_snapshot_after_disk_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            out_dir = root / "out"
            host_dir = root / "host"
            out_dir.mkdir()
            host_dir.mkdir()
            loader = b"export default function Module() {}\n"
            wasm = b"\x00asm\x01\x00\x00\x00"
            (out_dir / f"{smoke.DEFAULT_MODULE_NAME}.js").write_bytes(loader)
            (out_dir / f"{smoke.DEFAULT_MODULE_NAME}.wasm").write_bytes(wasm)
            for name in (
                "chrome_wasm_browser_continuous_flow_smoke.html",
                "chrome_wasm_browser_continuous_flow_smoke_host.js",
                "chrome_wasm_text_input.js",
                "chrome_wasm_pointer_input.js",
            ):
                (host_dir / name).write_text("asset", encoding="utf-8")
            server = smoke.create_server(
                "127.0.0.1",
                0,
                out_dir,
                "test-token",
                queue.Queue(maxsize=2),
                module_name=smoke.DEFAULT_MODULE_NAME,
                host_dir=host_dir,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                (out_dir / f"{smoke.DEFAULT_MODULE_NAME}.js").write_bytes(b"tampered")
                (out_dir / f"{smoke.DEFAULT_MODULE_NAME}.wasm").write_bytes(b"tampered")
                host, port = server.server_address[:2]
                base = f"http://{host}:{port}{smoke.HOST_ROOT}/artifacts/"
                with urlopen(base + f"{smoke.DEFAULT_MODULE_NAME}.js") as response:
                    self.assertEqual(loader, response.read())
                with urlopen(base + f"{smoke.DEFAULT_MODULE_NAME}.wasm") as response:
                    self.assertEqual(wasm, response.read())
                artifact = smoke.artifact_identity(
                    server, module_name=smoke.DEFAULT_MODULE_NAME
                )
                self.assertEqual(hashlib.sha256(loader).hexdigest(), artifact["loader"]["sha256"])
                self.assertEqual(hashlib.sha256(wasm).hexdigest(), artifact["wasm"]["sha256"])
                url = smoke.smoke_url(
                    server,
                    "test-token",
                    VERSIONS,
                    relay_ready=controlled_https.RelayReady(
                        "ws://127.0.0.1:12345/wisp/",
                        "https://a.test:444/m5/m6-ui",
                        "http://127.0.0.1:12345/transcript",
                    ),
                    artifact=artifact,
                    module_name=smoke.DEFAULT_MODULE_NAME,
                    timeout_seconds=15.0,
                )
                self.assertEqual(
                    artifact,
                    json.loads(parse_qs(urlsplit(url).query)["artifact"][0]),
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=1)

    def test_private_key_scan_rejects_snapshot_after_disk_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            out_dir = root / "out"
            host_dir = root / "host"
            out_dir.mkdir()
            host_dir.mkdir()
            loader_path = out_dir / f"{smoke.DEFAULT_MODULE_NAME}.js"
            loader_path.write_bytes(b"prefix\n-----BEGIN EC PRIVATE KEY-----\nsuffix")
            (out_dir / f"{smoke.DEFAULT_MODULE_NAME}.wasm").write_bytes(
                b"\x00asm\x01\x00\x00\x00"
            )
            for name in (
                "chrome_wasm_browser_continuous_flow_smoke.html",
                "chrome_wasm_browser_continuous_flow_smoke_host.js",
                "chrome_wasm_text_input.js",
                "chrome_wasm_pointer_input.js",
            ):
                (host_dir / name).write_text("asset", encoding="utf-8")
            server = smoke.create_server(
                "127.0.0.1",
                0,
                out_dir,
                "test-token",
                queue.Queue(maxsize=2),
                module_name=smoke.DEFAULT_MODULE_NAME,
                host_dir=host_dir,
            )
            try:
                loader_path.write_bytes(b"clean replacement")
                with self.assertRaisesRegex(M0Error, "private-key header"):
                    smoke.verify_no_private_key_pem_snapshot_artifacts(
                        server, module_name=smoke.DEFAULT_MODULE_NAME
                    )
            finally:
                server.server_close()

    def test_main_closes_pre_start_server_after_required_export_failure(self) -> None:
        server = mock.Mock()
        server.artifacts = {f"{smoke.DEFAULT_MODULE_NAME}.js": b"loader"}
        server.shutdown.side_effect = AssertionError(
            "a pre-start continuous-flow server must not be shut down"
        )
        with (
            mock.patch.object(smoke, "check_boundary"),
            mock.patch.object(
                smoke.controlled_https, "check_controlled_https_boundary"
            ),
            mock.patch.object(smoke, "create_server", return_value=server),
            mock.patch.object(
                smoke, "artifact_identity", return_value=ARTIFACT_IDENTITY
            ),
            mock.patch.object(
                smoke,
                "verify_required_exports",
                side_effect=M0Error("missing required export"),
            ),
            mock.patch.object(smoke, "find_browser") as find_browser,
            mock.patch.object(smoke.threading, "Thread") as thread,
            mock.patch.object(
                smoke, "write_failure_diagnostics", return_value=Path("/diagnostic")
            ),
            mock.patch.object(sys, "argv", ["continuous-flow-runner"]),
        ):
            self.assertEqual(1, smoke.main())

        server.shutdown.assert_not_called()
        server.server_close.assert_called_once_with()
        thread.assert_not_called()
        find_browser.assert_not_called()

    def test_main_compares_prelaunch_baseline_snapshot_after_disk_mutation(self) -> None:
        """The browser run cannot replace the reviewed PNG used for comparison."""

        baseline_a = b"reviewed baseline before launch"
        baseline_b = b"replacement baseline after launch"
        with tempfile.TemporaryDirectory() as temporary_directory:
            contract_path = (
                Path(temporary_directory)
                / "m6_controlled_https_screenshot_contract.json"
            )
            baseline_path = contract_path.with_name(
                "m6_controlled_https_browser_baseline.png"
            )
            baseline_path.write_bytes(baseline_a)

            def mutate_baseline_before_compare() -> None:
                baseline_path.write_bytes(baseline_b)

            with mock.patch.object(
                smoke, "CONTROLLED_HTTPS_SCREENSHOT_CONTRACT", contract_path
            ):
                result, _stdout, _stderr, dependencies = self._run_main_with_cleanup_fakes(
                    before_compare=mutate_baseline_before_compare
                )
            self.assertEqual(baseline_b, baseline_path.read_bytes())

        self.assertEqual(0, result)
        compare = dependencies["compare_screenshots"]
        compare.assert_called_once()
        self.assertEqual(b"png", compare.call_args.args[0])
        self.assertEqual(baseline_a, compare.call_args.args[1])
        self.assertNotEqual(baseline_b, compare.call_args.args[1])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires POSIX named pipes")
    def test_snapshot_reviewed_baseline_rejects_non_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            baseline_path = Path(temporary_directory) / "baseline.png"
            os.mkfifo(baseline_path)
            with self.assertRaisesRegex(M0Error, "must be a regular file"):
                smoke._snapshot_reviewed_screenshot_baseline(baseline_path)

    def test_snapshot_reviewed_baseline_rejects_empty_and_oversized_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            baseline_path = Path(temporary_directory) / "baseline.png"
            for name, contents in (
                ("empty", b""),
                ("oversized", b"x" * (smoke.MAX_SCREENSHOT_BYTES + 1)),
            ):
                with self.subTest(name=name):
                    baseline_path.write_bytes(contents)
                    with self.assertRaisesRegex(M0Error, "baseline is invalid"):
                        smoke._snapshot_reviewed_screenshot_baseline(baseline_path)

    @unittest.skipUnless(hasattr(os, "symlink"), "requires symbolic links")
    def test_snapshot_reviewed_baseline_rejects_symlink_substitution(self) -> None:
        if not hasattr(os, "O_NOFOLLOW"):
            self.skipTest("host cannot reject final-component symlinks")
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = root / "reviewed.png"
            baseline_path = root / "baseline.png"
            target.write_bytes(b"reviewed baseline")
            baseline_path.symlink_to(target)
            with self.assertRaises(M0Error):
                smoke._snapshot_reviewed_screenshot_baseline(baseline_path)

    def test_main_cleanup_failures_suppress_every_success_record(self) -> None:
        """A completed observation is not a pass until every owned cleanup succeeds."""

        cases = (
            ("browser", {"browser_cleanup_error": M0Error("browser cleanup failed")}),
            ("relay", {"relay_cleanup_error": M0Error("relay cleanup failed")}),
            ("server", {"server_cleanup_error": M0Error("server cleanup failed")}),
            ("profile", {"profile_cleanup_error": M0Error("profile cleanup failed")}),
        )
        for name, kwargs in cases:
            with self.subTest(cleanup=name):
                result, stdout, stderr, dependencies = self._run_main_with_cleanup_fakes(
                    **kwargs
                )

                self.assertEqual(1, result)
                self.assertEqual("", stdout)
                self.assertIn(f"FAIL reason={name} cleanup failed", stderr)
                output = stdout + stderr
                for marker in ("SCREENSHOT", "FLOW_RESULT", "RESTART_RESULT", "PASS"):
                    with self.subTest(cleanup=name, marker=marker):
                        self.assertNotIn(f"{smoke.SENTINEL}:{marker}", output)

                # Every case reaches cleanup-before-pass after a fully mocked
                # operational flow, rather than failing in setup or evidence
                # validation. Later cleanup may be failure-path abort cleanup.
                dependencies["wait_for_client"].assert_called_once()
                dependencies["stop_browser"].assert_called_once()
                if name != "browser":
                    dependencies["stop_relay"].assert_called_once()
                if name == "server":
                    # The failed success-path cleanup is retried in finally.
                    self.assertEqual(2, dependencies["cleanup_server"].call_count)
                if name == "profile":
                    dependencies["cleanup_server"].assert_called_once()
                    # The failed success-path cleanup is retried in finally.
                    self.assertEqual(2, dependencies["profile"].cleanup.call_count)

    def test_main_preserves_operational_failure_while_attempting_all_cleanup(self) -> None:
        """Failure cleanup cannot replace the original operational cause."""

        result, stdout, stderr, dependencies = self._run_main_with_cleanup_fakes(
            operational_error=M0Error("original operational failure"),
            abort_browser_error=M0Error("abort browser cleanup failed"),
            abort_relay_error=M0Error("abort relay cleanup failed"),
            server_cleanup_error=M0Error("server cleanup failed"),
            profile_cleanup_error=M0Error("profile cleanup failed"),
        )

        self.assertEqual(1, result)
        self.assertEqual("", stdout)
        self.assertIn("FAIL reason=original operational failure", stderr)
        for cleanup_message in (
            "abort browser cleanup failed",
            "abort relay cleanup failed",
            "server cleanup failed",
            "profile cleanup failed",
        ):
            with self.subTest(cleanup_message=cleanup_message):
                self.assertNotIn(cleanup_message, stderr)
        for marker in ("SCREENSHOT", "FLOW_RESULT", "RESTART_RESULT", "PASS"):
            with self.subTest(marker=marker):
                self.assertNotIn(f"{smoke.SENTINEL}:{marker}", stdout + stderr)

        dependencies["abort_browser"].assert_called_once_with(
            dependencies["browser"], dependencies["browser_stderr_reader"]
        )
        dependencies["abort_relay"].assert_called_once_with(
            dependencies["relay"],
            (
                dependencies["relay_stdout_reader"],
                dependencies["relay_stderr_reader"],
            ),
        )
        dependencies["cleanup_server"].assert_called_once()
        dependencies["profile"].cleanup.assert_called_once_with()
        dependencies["client"].close.assert_called_once_with()
        dependencies["stop_browser"].assert_not_called()
        dependencies["stop_relay"].assert_not_called()

    def _run_host_query(self, query: str) -> dict[str, object]:
        if not PINNED_NODE.is_file():
            self.skipTest("Node is unavailable")
        host = REPO_ROOT / "tools/wasm/host/chrome_wasm_browser_continuous_flow_smoke_host.js"
        script = f"""
globalThis.location = {{
  origin: "http://127.0.0.1",
  pathname: "/__m6_browser_continuous_flow__/",
  search: {json.dumps(query)},
}};
let fetchCalls = 0;
globalThis.fetch = () => {{
  fetchCalls += 1;
  throw new Error("unexpected continuous-flow fetch");
}};
const host = await import({json.dumps(host.as_uri())});
let error = null;
try {{
  await host.runChromeWasmBrowserContinuousFlowSmokeFromQuery();
}} catch (value) {{
  error = String(value);
}}
process.stdout.write(JSON.stringify({{error, fetchCalls}}));
"""
        completed = subprocess.run(
            [str(PINNED_NODE), "--input-type=module", "--eval", script],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        return json.loads(completed.stdout)

    def test_host_rejects_artifact_query_errors_before_fetch(self) -> None:
        common = {
            "token": "test-token",
            "module": smoke.DEFAULT_MODULE_NAME,
            "phase": smoke.FLOW_PHASE,
            "timeoutMs": "1000",
            "versions": json.dumps(VERSIONS, sort_keys=True, separators=(",", ":")),
        }
        malformed = urlencode({**common, "artifact": "{"})
        missing = urlencode(common)
        extra_artifact = {**ARTIFACT_IDENTITY, "extra": 1}
        extra = urlencode(
            {**common, "artifact": json.dumps(extra_artifact, sort_keys=True, separators=(",", ":"))}
        )
        mismatched = urlencode(
            {
                **common,
                "artifact": json.dumps(
                    {**ARTIFACT_IDENTITY, "module_name": "other_module"},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            }
        )
        for name, query in (
            ("malformed", malformed),
            ("missing", missing),
            ("extra", extra),
            ("module", mismatched),
        ):
            with self.subTest(name=name):
                observed = self._run_host_query("?" + query)
                self.assertIsInstance(observed["error"], str)
                self.assertEqual(0, observed["fetchCalls"])

    def test_host_verified_fetch_rejects_substitution_and_exact_type_aliases(self) -> None:
        if not PINNED_NODE.is_file():
            self.skipTest("Node is unavailable")
        host = REPO_ROOT / "tools/wasm/host/chrome_wasm_browser_continuous_flow_smoke_host.js"
        script = f"""
import crypto from "node:crypto";
const {{fetchVerifiedArtifact}} = await import({json.dumps(host.as_uri())});
const payload = new TextEncoder().encode("verified loader");
const sha256 = crypto.createHash("sha256").update(payload).digest("hex");
globalThis.fetch = async () => new Response(payload);
async function failure(identity) {{
  try {{
    await fetchVerifiedArtifact("http://127.0.0.1/artifact", identity, "test artifact");
  }} catch (error) {{
    return String(error);
  }}
  return "accepted";
}}
const valid = await fetchVerifiedArtifact(
    "http://127.0.0.1/artifact", {{bytes: payload.byteLength, sha256}}, "test artifact");
const substitution = await failure({{bytes: payload.byteLength, sha256: "0".repeat(64)}});
const bool = await failure({{bytes: true, sha256}});
const fractional = await failure({{bytes: 1.5, sha256}});
process.stdout.write(JSON.stringify({{valid: valid.byteLength, substitution, bool, fractional}}));
"""
        completed = subprocess.run(
            [str(PINNED_NODE), "--input-type=module", "--eval", script],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        observed = json.loads(completed.stdout)
        self.assertEqual(len(b"verified loader"), observed["valid"])
        self.assertIn("SHA-256 disagrees", observed["substitution"])
        self.assertIn("byte length", observed["bool"])
        self.assertIn("byte length", observed["fractional"])

    def test_rejects_marker_frame_then_fvp_retained_frame_mutation(self) -> None:
        result = flow_result()
        proof = result["continuousFlow"]
        assert isinstance(proof, dict)
        # Regression: a frame after RELOADED but before the phase-2 FVP signal
        # is retained/captured as the candidate. It must never satisfy the
        # final screenshot gate; a strictly later frame is required.
        proof["frameAfterSecondFvp"] = proof["frameAtSecondFvp"]
        screenshot = result["screenshot"]
        assert isinstance(screenshot, dict)
        screenshot["frameId"] = proof["frameAtSecondFvp"]
        screenshot["timestampMs"] = float(proof["frameAtSecondFvp"])
        with self.assertRaisesRegex(M0Error, "strict frame ordering"):
            smoke.validate_flow_result(
                result,
                expected_versions=VERSIONS,
                expected_artifact_identity=ARTIFACT_IDENTITY,
                screenshot_contract=controlled_https.load_controlled_https_screenshot_contract(),
            )

    def test_rejects_action4_sequence_pointer_and_screenshot_mutations(self) -> None:
        mutations = (
            (
                lambda result: result["hostInput"]["textTransactions"][1].__setitem__(
                    "deliverySequences", [1]
                ),
                "deliverySequences",
            ),
            (
                lambda result: result["hostInput"]["pointerRecords"][9].__setitem__(
                    "trusted", False
                ),
                "pointer action",
            ),
            (
                lambda result: result["screenshot"].__setitem__("frameId", 21),
                "screenshot",
            ),
        )
        for mutate, expression in mutations:
            with self.subTest(expression=expression):
                result = flow_result()
                mutate(result)
                with self.assertRaisesRegex(M0Error, expression):
                    smoke.validate_flow_result(
                        result,
                        expected_versions=VERSIONS,
                        expected_artifact_identity=ARTIFACT_IDENTITY,
                        screenshot_contract=controlled_https.load_controlled_https_screenshot_contract(),
                    )

    def test_parser_rejects_duplicate_or_wrong_phase(self) -> None:
        result = flow_result()
        payload = json.dumps(result, separators=(",", ":")).encode()
        self.assertEqual(smoke.parse_result_payload(payload, smoke.FLOW_PHASE), result)
        self.assertIsNone(smoke.parse_result_payload(payload, smoke.RESTART_PHASE))
        self.assertIsNone(
            smoke.parse_result_payload(
                b'{"protocol":1,"protocol":1,"case":"x"}', smoke.FLOW_PHASE
            )
        )


if __name__ == "__main__":
    unittest.main()
