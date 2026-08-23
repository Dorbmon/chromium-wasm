#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused source and Node-runner contracts for the M8 DevTools smoke."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m8_wasm_browser_devtools_protocol_smoke as smoke
from tools.wasm.tests.m3_source_contract_test_support import source


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


def complete_output() -> str:
    return "\n".join(
        (
            smoke.NETWORK_ENABLE_MARKER,
            smoke.RUNTIME_ENABLE_MARKER,
            smoke.RUNTIME_EVALUATE_MARKER,
            smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
            smoke.DETACHED_MARKER,
            smoke.LIFECYCLE_PASS_MARKER,
        )
    )


class M8WasmBrowserDevToolsProtocolSmokeTest(unittest.TestCase):
    def test_source_keeps_the_protocol_client_fixed_and_lifecycle_owned(self) -> None:
        build = source("chrome/browser/wasm/BUILD.gn")
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        lifecycle = source("chrome/browser/wasm/wasm_browser_lifecycle.cc")
        protocol = source(
            "chrome/browser/wasm/wasm_browser_devtools_protocol_smoke.cc"
        )

        for expected in (
            'source_set("wasm_browser_devtools_protocol_smoke")',
            '":wasm_browser_devtools_protocol_smoke",',
            '"wasm_browser_devtools_protocol_smoke.cc"',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, build)

        self.assertIn(
            '"wasm-browser-devtools-protocol-smoke"', main_parts
        )
        self.assertIn(
            "browser_lifecycle_->StartDevToolsProtocolSmoke();", main_parts
        )
        self.assertIn("contents->GetOutermostWebContents()", lifecycle)
        self.assertIn("contents->GetPrimaryMainFrame()", lifecycle)
        self.assertIn(
            "browser_->GetBrowserView().GetActiveWebContents(), contents",
            lifecycle,
        )
        for expected in (
            "kDevToolsProtocolSmokeUrl[]",
            "data:text/html;charset=utf-8,Chromium%20Wasm%20DevTools%20smoke",
            "WasmBrowserDevToolsProtocolNavigationObserver",
            "OnDevToolsProtocolSmokeNavigationObserved",
            "content::NavigationController::LoadURLParams params(smoke_url)",
            "primary_main_frame->IsRenderFrameLive()",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, lifecycle)
        self.assertIn("devtools_protocol_smoke_->IsDetached()", lifecycle)

        for expected in (
            'R"({"id":1,"method":"Network.enable"})"',
            'R"({"id":2,"method":"Runtime.enable"})"',
            '"method":"Runtime.evaluate"',
            "console.log('chromium-wasm-m8-devtools-console')",
            '"returnByValue":true,',
            '"allowUnsafeEvalBlockedByCSP":false',
            "kFixedDevToolsProtocolSmokeUrl",
            "data:text/html;charset=utf-8,Chromium%20Wasm%20DevTools%20smoke",
            "CHECK_EQ(web_contents->GetLastCommittedURL(), expected_url);",
            "CHECK_EQ(primary_main_frame_->GetLastCommittedURL(), expected_url);",
            "permitted_url_ = expected_url;",
            "content::DevToolsAgentHost::GetOrCreateFor(web_contents)",
            "agent_host_->AttachClient(this)",
            "agent_host->DetachClient(this)",
            "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:NETWORK_ENABLE_OK",
            "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:RUNTIME_ENABLE_OK",
            "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:RUNTIME_EVALUATE_OK",
            "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:RUNTIME_CONSOLE_API_CALLED_OK",
            "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:DETACHED",
            "base::JSON_PARSE_RFC",
            "response.FindDict(\"result\")",
            "result->FindDict(\"result\")",
            "result->Find(\"exceptionDetails\")",
            "kRuntimeEvaluateExpectedValue",
            "Runtime.consoleAPICalled",
            "CompleteRuntimeEnable",
            "CompleteRuntimeConsoleApiCalled",
            "runtime_evaluate_response_received_",
            "runtime_console_api_called_received_",
            "not a page WebAssembly probe or enablement path",
            "return !is_webui && permitted_url_.is_valid() && url == permitted_url_;",
            "return render_frame_host == primary_main_frame_;",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, protocol)
        for forbidden in (
            "StartRemoteDebuggingServer",
            "StartRemoteDebuggingPipeHandler",
            "DevToolsHttpHandler",
            "WebSocket",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, protocol)
        for expected in (
            "bool WasmBrowserDevToolsProtocolSmoke::IsTrusted()",
            "bool WasmBrowserDevToolsProtocolSmoke::MayAccessAllCookies()",
            "bool WasmBrowserDevToolsProtocolSmoke::MayReadLocalFiles()",
            "bool WasmBrowserDevToolsProtocolSmoke::MayWriteLocalFiles()",
            "bool WasmBrowserDevToolsProtocolSmoke::AllowUnsafeOperations()",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, protocol)
        for method in (
            "IsTrusted",
            "MayAccessAllCookies",
            "MayReadLocalFiles",
            "MayWriteLocalFiles",
            "AllowUnsafeOperations",
        ):
            with self.subTest(method=method):
                self.assertRegex(
                    protocol,
                    rf"bool WasmBrowserDevToolsProtocolSmoke::{method}\(\) \{{\n"
                    r"  return false;\n\}",
                )

        complete = protocol[
            protocol.index("void WasmBrowserDevToolsProtocolSmoke::CompleteNetworkEnable") : protocol.index(
                "[[noreturn]] void WasmBrowserDevToolsProtocolSmoke::Fail"
            )
        ]
        self.assertLess(
            complete.index("kNetworkEnableSuccessMarker"),
            complete.index("kRuntimeEnableSuccessMarker"),
        )
        self.assertLess(
            complete.index("kRuntimeEnableSuccessMarker"),
            complete.index("kRuntimeEvaluateCommand"),
        )
        self.assertIn("kRuntimeEvaluateSuccessMarker", protocol)
        self.assertIn("kRuntimeConsoleApiCalledSuccessMarker", protocol)
        self.assertLess(
            complete.index("Detach();"), complete.index("kDetachedMarker")
        )
        self.assertIn("weak_ptr_factory_.GetWeakPtr()", lifecycle)
        self.assertIn("BeginDevToolsProtocolSmokeShutdown", lifecycle)
        self.assertIn(
            "if (shutdown_started_ || shutdown_complete_ || !browser_)", lifecycle
        )

    def test_runner_uses_only_the_fixed_switch_and_lifecycle_host(self) -> None:
        runner = smoke.runner_source("file:///chrome_wasm.js", 1000)
        for expected in (
            'arguments: ["--wasm-browser-devtools-protocol-smoke"]',
            smoke.NETWORK_ENABLE_MARKER,
            smoke.LIFECYCLE_PASS_MARKER,
            smoke.RESULT_PREFIX,
            "class MockCanvasContext",
            "globalThis.__chromiumWasmHostBridgeV1 = Object.freeze",
            "reportFrame(report)",
            "reportReadiness(report)",
            "reportFatal(message)",
            "reportProcessExit(report)",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, runner)
        for forbidden in (
            "StartRemoteDebuggingServer",
            "StartRemoteDebuggingPipeHandler",
            "ccall(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, runner)

    def test_accepts_fixed_enable_response_console_and_detach_evidence(self) -> None:
        smoke.validate_result(successful_result(), complete_output())

    def test_accepts_console_event_before_fixed_evaluate_response(self) -> None:
        smoke.validate_result(
            successful_result(),
            "\n".join(
                (
                    smoke.NETWORK_ENABLE_MARKER,
                    smoke.RUNTIME_ENABLE_MARKER,
                    smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
                    smoke.RUNTIME_EVALUATE_MARKER,
                    smoke.DETACHED_MARKER,
                    smoke.LIFECYCLE_PASS_MARKER,
                )
            ),
        )

    def test_rejects_missing_repeated_or_misordered_native_markers(self) -> None:
        repeated_network_enable = "\n".join(
            (
                smoke.NETWORK_ENABLE_MARKER,
                smoke.NETWORK_ENABLE_MARKER,
                smoke.RUNTIME_ENABLE_MARKER,
                smoke.RUNTIME_EVALUATE_MARKER,
                smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
                smoke.DETACHED_MARKER,
                smoke.LIFECYCLE_PASS_MARKER,
            )
        )
        missing_runtime_evaluate = "\n".join(
            (
                smoke.NETWORK_ENABLE_MARKER,
                smoke.RUNTIME_ENABLE_MARKER,
                smoke.DETACHED_MARKER,
                smoke.LIFECYCLE_PASS_MARKER,
            )
        )
        repeated_success = "\n".join(
            (
                smoke.NETWORK_ENABLE_MARKER,
                smoke.RUNTIME_ENABLE_MARKER,
                smoke.RUNTIME_EVALUATE_MARKER,
                smoke.RUNTIME_EVALUATE_MARKER,
                smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
                smoke.DETACHED_MARKER,
                smoke.LIFECYCLE_PASS_MARKER,
            )
        )
        missing_detach = "\n".join(
            (
                smoke.NETWORK_ENABLE_MARKER,
                smoke.RUNTIME_ENABLE_MARKER,
                smoke.RUNTIME_EVALUATE_MARKER,
                smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
                smoke.LIFECYCLE_PASS_MARKER,
            )
        )
        repeated_detach = "\n".join(
            (
                smoke.NETWORK_ENABLE_MARKER,
                smoke.RUNTIME_ENABLE_MARKER,
                smoke.RUNTIME_EVALUATE_MARKER,
                smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
                smoke.DETACHED_MARKER,
                smoke.DETACHED_MARKER,
                smoke.LIFECYCLE_PASS_MARKER,
            )
        )
        missing_runtime_enable = "\n".join(
            (
                smoke.NETWORK_ENABLE_MARKER,
                smoke.RUNTIME_EVALUATE_MARKER,
                smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
                smoke.DETACHED_MARKER,
                smoke.LIFECYCLE_PASS_MARKER,
            )
        )
        missing_console_api_called = "\n".join(
            (
                smoke.NETWORK_ENABLE_MARKER,
                smoke.RUNTIME_ENABLE_MARKER,
                smoke.RUNTIME_EVALUATE_MARKER,
                smoke.DETACHED_MARKER,
                smoke.LIFECYCLE_PASS_MARKER,
            )
        )
        wrong_order = "\n".join(
            (
                smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
                smoke.NETWORK_ENABLE_MARKER,
                smoke.RUNTIME_ENABLE_MARKER,
                smoke.RUNTIME_EVALUATE_MARKER,
                smoke.DETACHED_MARKER,
                smoke.LIFECYCLE_PASS_MARKER,
            )
        )
        for output, expression in (
            (repeated_network_enable, "2 Network.enable success"),
            (missing_runtime_evaluate, "Runtime.evaluate success"),
            (repeated_success, "2 Runtime.evaluate success"),
            (missing_detach, "0 DevTools detach"),
            (repeated_detach, "2 DevTools detach"),
            (missing_runtime_enable, "0 Runtime.enable success"),
            (missing_console_api_called, "0 Runtime.consoleAPICalled success"),
            (wrong_order, "not ordered"),
        ):
            with self.subTest(expression=expression):
                with self.assertRaisesRegex(M0Error, expression):
                    smoke.validate_result(successful_result(), output)

    def test_rejects_lifecycle_abort_or_missing_native_protocol_success(self) -> None:
        aborted = successful_result()
        aborted["abort"] = "abort"
        with self.assertRaisesRegex(M0Error, "aborted or rejected"):
            smoke.validate_result(aborted, complete_output())

        missing_network = complete_output().replace(
            smoke.NETWORK_ENABLE_MARKER, "not-a-network-enable-marker"
        )
        with self.assertRaisesRegex(M0Error, "ready marker"):
            smoke.validate_result(successful_result(), missing_network)

        missing_runtime_evaluate = complete_output().replace(
            smoke.RUNTIME_EVALUATE_MARKER, "not-a-runtime-evaluate-marker"
        )
        with self.assertRaisesRegex(M0Error, "Runtime.evaluate success"):
            smoke.validate_result(successful_result(), missing_runtime_evaluate)

        missing_console_api_called = complete_output().replace(
            smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
            "not-a-runtime-console-api-called-marker",
        )
        with self.assertRaisesRegex(M0Error, "Runtime.consoleAPICalled success"):
            smoke.validate_result(successful_result(), missing_console_api_called)

    def test_runner_explicitly_limits_the_native_witness(self) -> None:
        runner_program = source(
            "tools/wasm/run_m8_wasm_browser_devtools_protocol_smoke.py"
        )
        self.assertEqual(
            (
                "does_not_enable_or_exercise_page_webassembly",
                "does_not_provide_a_devtools_frontend_or_generic_protocol_bridge",
                "does_not_claim_m8_compatibility_completion",
            ),
            smoke.LIMITATIONS,
        )
        self.assertIn('"pageWebAssemblyExercised": False', runner_program)
        self.assertNotIn("pageWebAssemblyEnabled", runner_program)

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
