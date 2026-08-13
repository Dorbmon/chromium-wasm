#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the trusted M6 History and Downloads browser flow."""

from __future__ import annotations

import copy
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m6_wasm_browser_host_history_downloads_dom_smoke as smoke
from tools.wasm.tests.m3_source_contract_test_support import source


VERSIONS = {
    "chromium": "chromium-revision",
    "v8": "v8-revision",
    "emscripten": "emscripten-revision",
    "port": "port-revision",
}


def text_adapter(phase: str) -> dict[str, object]:
    sequence = 1 if phase == "first" else 2
    text = (
        smoke.FIRST_ADDRESS_TEXT
        if phase == "first"
        else smoke.SECOND_ADDRESS_TEXT
    )
    ctrl_l = [
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
    ]
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
        "ctrlLRecords": ctrl_l,
        "beforeInputRecords": [
            {
                "inputType": "insertText",
                "dataOmitted": True,
                "dataUtf16Units": len(text),
                "dataUtf8Bytes": len(text),
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


def text_transaction(phase: str) -> dict[str, object]:
    sequence = 1 if phase == "first" else 2
    return {
        "phase": phase,
        "adapterId": 1,
        "ctrlLComplete": True,
        "proxyFocusedAfterCtrlL": True,
        "nativeTextAdmissionCount": 1,
        "nativeTextDeliveryCount": 1,
        "nativeTextDeliverySequences": [sequence],
        "textDeliveryAccepted": True,
        "enterComplete": True,
        "rejected": False,
        # The host derives these redacted immutable deltas from the one
        # persistent shared adapter. No text value is retained.
        "adapter": text_adapter(phase),
    }


def pointer_record(
    event_type: str, x: int, y: int, *, button: int, buttons: int
) -> dict[str, object]:
    return {
        "type": event_type,
        "trusted": True,
        "cancelable": True,
        "pointerType": "mouse",
        "primary": True,
        "pointerId": 1,
        "button": button,
        "buttons": buttons,
        "accepted": True,
        "defaultPrevented": True,
        "x": x,
        "y": y,
        "reason": None,
    }


def target(x: int, y: int) -> dict[str, object]:
    return {"x": x, "y": y, "clientX": x + 16.5, "clientY": y + 16.5}


def successful_result() -> dict[str, object]:
    targets = [
        target(600, 40),
        target(618, 48),
        target(124, 105),
        target(618, 48),
        target(208, 142),
    ]
    records: list[dict[str, object]] = []
    for item in targets:
        records.append(pointer_record("down", item["x"], item["y"], button=0, buttons=1))
        records.append(pointer_record("up", item["x"], item["y"], button=0, buttons=0))
    proof: dict[str, object] = {
        "wispConfigured": True,
        "runtimeArgumentsConfigured": True,
        "configurationPrecededFactory": True,
        "readyObserved": True,
        "firstNavigatedObserved": True,
        "secondTabReadyObserved": True,
        "secondNavigatedObserved": True,
        "menuOpenHistoryObserved": True,
        "menuClosedHistoryObserved": True,
        "historyNavigatedObserved": True,
        "menuOpenDownloadsObserved": True,
        "menuClosedDownloadsObserved": True,
        "downloadsNavigatedObserved": True,
        "passObserved": True,
    }
    phase_pairs = (
        ("FirstNavigated", 1, 2),
        ("SecondTabReady", 3, 4),
        ("SecondNavigated", 5, 6),
        ("MenuOpenHistory", 7, 8),
        ("MenuClosedHistory", 9, 10),
        ("HistoryNavigated", 11, 12),
        ("MenuOpenDownloads", 13, 14),
        ("MenuClosedDownloads", 15, 16),
        ("DownloadsNavigated", 17, 18),
    )
    for name, before, after in phase_pairs:
        proof[f"frameIdAt{name}Marker"] = before
        proof[f"frameIdAfter{name}Marker"] = after
    output = [
        smoke.READY_MARKER,
        f"{smoke.FIRST_NAVIGATED_MARKER} x=600 y=40",
        smoke.SECOND_TAB_READY_MARKER,
        f"{smoke.SECOND_NAVIGATED_MARKER} x=618 y=48",
        f"{smoke.MENU_OPEN_HISTORY_MARKER} x=124 y=105",
        smoke.MENU_CLOSED_HISTORY_MARKER,
        f"{smoke.HISTORY_NAVIGATED_MARKER} x=618 y=48",
        f"{smoke.MENU_OPEN_DOWNLOADS_MARKER} x=208 y=142",
        smoke.MENU_CLOSED_DOWNLOADS_MARKER,
        smoke.DOWNLOADS_NAVIGATED_MARKER,
        smoke.PASS_MARKER,
    ]
    return {
        "protocol": 1,
        "case": smoke.CASE,
        "scope": smoke.SCOPE,
        "status": "pass",
        "m6GateComplete": False,
        "runtimeExitCode": 0,
        "processExitCode": 0,
        "runtimeInitialized": True,
        "factorySettled": True,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "abort": None,
        "fatalErrors": [],
        "windowErrors": [],
        "unhandledRejections": [],
        "versions": copy.deepcopy(VERSIONS),
        "frameReports": [
            {
                "id": identifier,
                "width": 640,
                "height": 480,
                "timestampMs": float(identifier),
            }
            for identifier in range(1, 20)
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
            {
                "focusedClientPresent": True,
                "editable": True,
                "canComposeInline": True,
            }
        ],
        "ozoneTextInputDeliveries": [],
        "ozoneCursorReports": [],
        "historyDownloads": proof,
        "hostInput": {
            "singleAdapterRetained": True,
            "textTransactions": [text_transaction("first"), text_transaction("second")],
            "pointerRecords": records,
            "newTabTarget": targets[0],
            "firstMenuTarget": targets[1],
            "historyTarget": targets[2],
            "secondMenuTarget": targets[3],
            "downloadsTarget": targets[4],
            "newTabActionOffset": 0,
            "firstMenuActionOffset": 2,
            "historyActionOffset": 4,
            "secondMenuActionOffset": 6,
            "downloadsActionOffset": 8,
            "newTabCheckQueued": True,
            "historyMenuOpenCheckQueued": True,
            "historyMenuClosedCheckQueued": True,
            "downloadsMenuOpenCheckQueued": True,
            "downloadsMenuClosedCheckQueued": True,
            "finalPresentationQueued": True,
        },
        "canvasBackingStore": {"width": 640, "height": 480},
        "stdout": [],
        "stderr": output,
        "failedChecks": [],
        "error": None,
    }


class M6WasmBrowserHostHistoryDownloadsDomSmokeTest(unittest.TestCase):
    def test_runner_uses_bounded_relay_readers_and_terminal_cleanup(self) -> None:
        runner = source(
            "tools/wasm/run_m6_wasm_browser_host_history_downloads_dom_smoke.py"
        )

        self.assertNotIn("def _drain_relay_stdout", runner)
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

    def test_main_suppresses_terminal_records_when_relay_cleanup_fails(self) -> None:
        class FakeProcess:
            def __init__(self) -> None:
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

        relay = FakeProcess()
        browser = FakeProcess()
        server = mock.Mock()
        server.server_address = ("127.0.0.1", 38123)
        client = mock.Mock()
        stop_relay = mock.Mock(side_effect=M0Error("relay cleanup failed"))
        abort_relay = mock.Mock()
        stdout = io.StringIO()
        stderr = io.StringIO()

        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            out_dir = Path(temporary) / "out"
            out_dir.mkdir()
            for suffix in (".js", ".wasm"):
                (out_dir / f"{smoke.DEFAULT_MODULE_NAME}{suffix}").write_bytes(b"x")
            stack.enter_context(
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "run_m6_wasm_browser_host_history_downloads_dom_smoke.py",
                        "--out-dir",
                        str(out_dir),
                        "--timeout",
                        "5",
                    ],
                )
            )
            stack.enter_context(mock.patch.object(smoke, "check_boundary"))
            stack.enter_context(
                mock.patch.object(smoke.controlled_https, "check_controlled_https_boundary")
            )
            stack.enter_context(mock.patch.object(smoke, "verify_required_exports"))
            stack.enter_context(
                mock.patch.object(smoke, "verify_no_private_key_pem_artifacts")
            )
            stack.enter_context(mock.patch.object(smoke, "load_manifest", return_value={}))
            stack.enter_context(mock.patch.object(smoke, "checked_output", return_value="head"))
            stack.enter_context(
                mock.patch.object(smoke, "manifest_versions", return_value=VERSIONS)
            )
            stack.enter_context(mock.patch.object(smoke, "print_context"))
            stack.enter_context(
                mock.patch.object(
                    smoke,
                    "find_browser",
                    return_value=(Path("/browser"), "browser-version"),
                )
            )
            stack.enter_context(mock.patch.object(smoke, "find_node", return_value=Path("/node")))
            stack.enter_context(mock.patch.object(smoke, "create_server", return_value=server))
            stack.enter_context(mock.patch.object(smoke.threading, "Thread", FakeThread))
            stack.enter_context(
                mock.patch.object(
                    smoke, "m5_host_origin", return_value="http://127.0.0.1:38123"
                )
            )
            stack.enter_context(mock.patch.object(smoke, "relay_command", return_value=["relay"]))
            stack.enter_context(
                mock.patch.object(
                    smoke.controlled_https,
                    "wait_for_relay_ready",
                    return_value=mock.Mock(),
                )
            )
            stack.enter_context(
                mock.patch.object(smoke, "smoke_url", return_value="http://127.0.0.1:38123/")
            )
            stack.enter_context(mock.patch.object(smoke, "unused_loopback_port", return_value=40123))
            stack.enter_context(mock.patch.object(smoke, "browser_command", return_value=["browser"]))
            stack.enter_context(
                mock.patch.object(smoke.subprocess, "Popen", side_effect=[relay, browser])
            )
            stack.enter_context(mock.patch.object(smoke, "wait_for_page_client", return_value=client))
            stack.enter_context(mock.patch.object(smoke, "dispatch_address_transaction"))
            stack.enter_context(mock.patch.object(smoke, "wait_for_state", return_value={}))
            stack.enter_context(mock.patch.object(smoke, "click_target"))
            stack.enter_context(
                mock.patch.object(smoke, "wait_for_result", return_value=successful_result())
            )
            stack.enter_context(
                mock.patch.object(smoke.controlled_https, "fetch_relay_status", return_value={})
            )
            stack.enter_context(
                mock.patch.object(smoke.controlled_https, "validate_relay_status")
            )
            stack.enter_context(mock.patch.object(smoke, "stop_process_group", stop_relay))
            stack.enter_context(mock.patch.object(smoke, "abort_process_group", abort_relay))
            stack.enter_context(mock.patch.object(smoke, "stop_browser"))
            stack.enter_context(
                mock.patch.object(
                    smoke,
                    "write_failure_diagnostics",
                    return_value=Path("/tmp/history-downloads.json"),
                )
            )
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(smoke.main(), 1)

        terminal = stdout.getvalue() + stderr.getvalue()
        for marker in ("BROWSER_RESULT", "PASS"):
            with self.subTest(marker=marker):
                self.assertNotIn(f"{smoke.SENTINEL}:{marker}", terminal)
        self.assertIn("FAIL reason=relay cleanup failed", terminal)
        stop_relay.assert_called_once()
        abort_relay.assert_called_once()
        self.assertEqual(
            abort_relay.call_args.kwargs["description"],
            "M6 History/Downloads relay",
        )
        self.assertEqual(abort_relay.call_args.kwargs["unowned_streams"], ())

    def test_host_uses_shared_adapters_deferred_ordinals_and_no_navigation_api(self) -> None:
        host = source(
            "tools/wasm/host/chrome_wasm_browser_host_history_downloads_smoke_host.js"
        )
        for expected in (
            'import {ChromiumWasmTrustedTextInput} from "./chrome_wasm_text_input.js";',
            'import {ChromiumWasmTrustedPointerInput} from "./chrome_wasm_pointer_input.js";',
            "new ChromiumWasmTrustedTextInput",
            "new ChromiumWasmTrustedPointerInput",
            "chromium_wasm_browser_host_history_downloads_check",
            "chromium_wasm_browser_host_history_downloads_presented",
            "setTimeout(() =>",
            "FIRST_ADDRESS_TEXT",
            "SECOND_ADDRESS_TEXT",
            "redactDiagnostic",
            "singleAdapterRetained",
            "awaiting-trusted-dom-new-tab",
            "awaiting-post-second-tab-frame",
            "awaiting-trusted-dom-menu-history",
            "awaiting-trusted-dom-history",
            "awaiting-trusted-dom-menu-downloads",
            "awaiting-trusted-dom-downloads",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, host)
        for forbidden in ("location.assign", "location.replace", "window.open"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, host)

    def test_runner_only_uses_cdp_input_and_read_only_host_state(self) -> None:
        runner = source("tools/wasm/run_m6_wasm_browser_host_history_downloads_dom_smoke.py")
        for expected in (
            "wait_for_page_client",
            "__chromiumWasmM6HostHistoryDownloadsState",
            "client.dispatch_control_shortcut",
            'client.call("Input.insertText"',
            "Input.dispatchKeyEvent",
            "client.dispatch_primary_click",
            "chromium_wasm_browser_host_history_downloads_check",
            "chromium_wasm_browser_host_history_downloads_presented",
            "chrome_wasm_text_input.js",
            "chrome_wasm_pointer_input.js",
            "--wasm-browser-host-history-downloads-smoke",
            "--wasm-browser-controlled-https-url",
            "validate_relay_status",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, runner)
        self.assertNotIn("Runtime.evaluate", runner)
        self.assertNotIn("ccall(", runner)

    def test_cxx_verifier_is_ordinal_only_and_lifecycle_owns_proof(self) -> None:
        verifier = source(
            "chrome/browser/wasm/wasm_browser_host_history_downloads_smoke.cc"
        )
        lifecycle = source("chrome/browser/wasm/wasm_browser_lifecycle.cc")
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        for expected in (
            "kSecondTabCheck",
            "kHistoryMenuOpenCheck",
            "kHistoryMenuClosedCheck",
            "kDownloadsMenuOpenCheck",
            "kDownloadsMenuClosedCheck",
            "kFinalPresentation",
            "generation_",
            "ClearCallbacksOnUiThread",
            "chromium_wasm_browser_host_history_downloads_check",
            "chromium_wasm_browser_host_history_downloads_presented",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, verifier)
        for forbidden in ("NavigationController", "WasmBrowserMenuView", "LoadURL"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, verifier)
        for expected in (
            "StartHostHistoryDownloadsSmoke",
            "PAGE_TRANSITION_TYPED",
            "PAGE_TRANSITION_GENERATED",
            "HasUserGesture()",
            "DidFirstVisuallyNonEmptyPaint",
            "WasmHistoryUI",
            "WasmDownloadsUI",
            "kHostHistoryDownloadsFirstJournalUrl",
            "kHostHistoryDownloadsRedactedJournalUrl",
            "MENU_OPEN_HISTORY",
            "MENU_OPEN_DOWNLOADS",
            "ClearWasmBrowserHostHistoryDownloadsSmokeVerificationForTesting",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, lifecycle)
        self.assertIn("wasm-browser-host-history-downloads-smoke", main_parts)

    def test_html_loads_the_dedicated_host_and_text_proxy(self) -> None:
        html = source(
            "tools/wasm/host/chrome_wasm_browser_host_history_downloads_smoke.html"
        )
        self.assertEqual(html.count('id="browser-canvas"'), 1)
        self.assertEqual(html.count('id="browser-text-proxy"'), 1)
        self.assertEqual(
            html.count('id="browser-history-downloads-status"'), 1
        )
        self.assertIn("chrome_wasm_browser_host_history_downloads_smoke_host.js", html)

    def test_accepts_complete_redacted_evidence(self) -> None:
        result = successful_result()
        smoke.validate_result(result, expected_versions=VERSIONS)
        serialized = json.dumps(result, sort_keys=True)
        self.assertNotIn(smoke.FIRST_ADDRESS_TEXT, serialized)
        self.assertNotIn(smoke.SECOND_ADDRESS_TEXT, serialized)

    def test_rejects_bad_sequence_frame_pointer_and_raw_text(self) -> None:
        mutations = (
            (
                lambda result: result["hostInput"]["textTransactions"][1].__setitem__(
                    "nativeTextDeliverySequences", [1]
                ),
                "counters",
            ),
            (
                lambda result: result["hostInput"]["textTransactions"][1].__setitem__(
                    "adapterId", 2
                ),
                "adapter identity",
            ),
            (
                lambda result: result["historyDownloads"].__setitem__(
                    "frameIdAfterDownloadsNavigatedMarker", 17
                ),
                "ordered presentation",
            ),
            (
                lambda result: result["hostInput"]["pointerRecords"][9].__setitem__(
                    "trusted", False
                ),
                "pointer action 9 trusted",
            ),
            (
                lambda result: result["hostInput"].__setitem__(
                    "historyActionOffset", 2
                ),
                "historyActionOffset",
            ),
            (
                lambda result: result["hostInput"]["textTransactions"][0][
                    "adapter"
                ]["beforeInputRecords"][0].__setitem__("data", "leak"),
                "retained raw text",
            ),
        )
        for mutate, expression in mutations:
            with self.subTest(expression=expression):
                result = successful_result()
                mutate(result)
                with self.assertRaisesRegex(M0Error, expression):
                    smoke.validate_result(result, expected_versions=VERSIONS)

    def test_parser_rejects_duplicate_or_wrong_scope_results(self) -> None:
        result = json.dumps(successful_result(), separators=(",", ":")).encode()
        self.assertEqual(smoke.parse_result_payload(result), successful_result())
        self.assertIsNone(
            smoke.parse_result_payload(
                b'{"protocol":1,"protocol":1,'
                b'"case":"browser_host_history_downloads_m6"}'
            )
        )


if __name__ == "__main__":
    unittest.main()
