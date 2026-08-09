#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the Chrome host-to-Ozone accelerator runtime smoke."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m6_wasm_browser_host_accelerator_smoke as smoke
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
        "hostInputCheckAccepted": True,
        "hostInputTransitions": [
            {"code": "ControlLeft", "down": 1},
            {"code": "KeyL", "down": 1},
            {"code": "KeyL", "down": 0},
            {"code": "ControlLeft", "down": 0},
        ],
        "passObserved": True,
        "processExitReports": [{"protocol": 1, "exitCode": 0}],
        "readyObserved": True,
        "readinessReports": [{"protocol": 1, "surfaceReady": True}],
        "rejection": None,
        "runtimeExitCode": 0,
    }


class M6WasmBrowserHostAcceleratorNodeSmokeTest(unittest.TestCase):
    def test_source_keeps_host_key_delivery_switch_gated_and_physical(self) -> None:
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        lifecycle = source("chrome/browser/wasm/wasm_browser_lifecycle.cc")
        bridge = source("chrome/browser/wasm/wasm_browser_host_input.cc")

        for expected in (
            '"wasm-browser-host-accelerator-smoke"',
            '"CHROMIUM_WASM_M6_HOST_ACCELERATORS:READY"',
            "browser_lifecycle_->StartHostAcceleratorSmoke();",
            "InitializeWasmBrowserHostInput()",
            "ShutdownWasmBrowserHostInput();",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, main_parts)

        for expected in (
            '"CHROMIUM_WASM_M6_HOST_ACCELERATORS:PASS"',
            "SetWasmBrowserHostAcceleratorVerificationForTesting(",
            "address_field->HasFocus()",
            "address_field->GetSelectedText() == address_field->GetText()",
            "BeginShutdown();",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, lifecycle)

        for expected in (
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_key",
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_accelerator_check",
            "CreateSystemInputInjector()",
            "InjectKeyEvent(physical_key, down,",
            "ControlLeft",
            "ShiftLeft",
            "AltLeft",
            "KeyL",
            "KeyR",
            "ArrowLeft",
            "ArrowRight",
            "Tab",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, bridge)

        for forbidden in (
            "Widget::OnKeyEvent",
            "BrowserCommandController",
            "content/shell",
            "LoadURL",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, bridge)

    def test_runner_uses_only_exported_host_records_after_ready(self) -> None:
        runner = smoke.runner_source("file:///chrome_wasm.js", 1000)
        for expected in (
            'arguments: ["--wasm-browser-host-accelerator-smoke"]',
            "queueMicrotask(submitHostAccelerator)",
            "chromium_wasm_browser_host_key",
            "chromium_wasm_browser_host_accelerator_check",
            "['ControlLeft', 1]",
            "['KeyL', 1]",
            "['KeyL', 0]",
            "['ControlLeft', 0]",
            "wasmModule.ccall",
            "onRuntimeInitialized()",
            "wasmModule = this;",
            "hostInputTransitions",
            "hostInputCheckAccepted",
            "onAbort(reason)",
            "onExit(code)",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, runner)

        self.assertNotIn("widget->OnKeyEvent", runner)
        ready_handler = runner.split("if (text.includes(readyMarker))", 1)[1]
        self.assertIn(
            "queueMicrotask(submitHostAccelerator)",
            ready_handler.split("}", 1)[0],
        )

    def test_accepts_complete_host_input_and_presentation_evidence(self) -> None:
        smoke.validate_result(
            successful_result(), f"{smoke.READY_MARKER}\n{smoke.PASS_MARKER}"
        )

    def test_rejects_missing_host_input_evidence(self) -> None:
        for field, value, expression in (
            ("hostInputTransitions", [], "exact Ctrl\\+L"),
            ("hostInputCheckAccepted", False, "verification was not accepted"),
            ("canvasCopies", 0, "canvas copy"),
            ("runtimeExitCode", 1, "did not exit zero"),
        ):
            with self.subTest(field=field):
                result = successful_result()
                result[field] = value
                with self.assertRaisesRegex(M0Error, expression):
                    smoke.validate_result(
                        result, f"{smoke.READY_MARKER}\n{smoke.PASS_MARKER}"
                    )

    def test_parser_requires_one_result_record(self) -> None:
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
