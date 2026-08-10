#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused source and Node-runner contracts for --wasm-browser-smoke."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m6_wasm_browser_smoke as smoke
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
            smoke.READY_MARKER,
            smoke.TAB_STRIP_MARKER,
            smoke.VIEWS_ACCELERATORS_MARKER,
            smoke.TOP_CONTROLS_MARKER,
            smoke.BROWSER_MENU_MARKER,
            smoke.SETTINGS_BOOTSTRAP_MARKER,
            smoke.VERSION_WEBUI_MARKER,
            smoke.PASS_MARKER,
        )
    )


class M6WasmBrowserNodeSmokeTest(unittest.TestCase):
    def test_source_keeps_the_browser_smoke_explicit_and_terminal(self) -> None:
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        browser_smoke = source("chrome/browser/wasm/wasm_browser_smoke.cc")

        switch = (
            'constexpr char kWasmBrowserSmokeSwitch[] = "wasm-browser-smoke";'
        )
        self.assertIn(switch, main_parts)
        run = "chrome::RunWasmBrowserSmoke(profile_.get())"
        self.assertIn(run, main_parts)
        switch_index = main_parts.index(switch)
        run_index = main_parts.index(run)
        shutdown_index = main_parts.index("RequestShutdown();", run_index)
        normal_exit_index = main_parts.index(
            "return content::RESULT_CODE_NORMAL_EXIT;", shutdown_index
        )
        self.assertLess(switch_index, run_index)
        self.assertLess(run_index, shutdown_index)
        self.assertLess(shutdown_index, normal_exit_index)

        for expected in (
            '"CHROMIUM_WASM_M6_BROWSER:READY"',
            '"CHROMIUM_WASM_M6_BROWSER:PASS"',
            '"CHROMIUM_WASM_M6_TAB_STRIP:PASS"',
            '"CHROMIUM_WASM_M6_VIEWS_ACCELERATORS:PASS"',
            '"CHROMIUM_WASM_M6_TOP_CONTROLS:PASS"',
            '"CHROMIUM_WASM_M6_BROWSER_MENU:PASS"',
            '"CHROMIUM_WASM_M6_SETTINGS_BOOTSTRAP:PASS"',
            '"CHROMIUM_WASM_M6_VERSION_WEBUI:PASS"',
            "SubmitAddressAndWait(",
            "ClickNavigationButtonAndWait(",
            "CloseEmptyBrowserForSmoke(",
            "browser_view.Show();",
            "new_tab_button_for_testing()",
            "close_tab_button_for_testing(0)",
            "close_tab_button_for_testing(1)",
            "ClickButton(new_tab_button);",
            "ClickButton(first_close_tab_button);",
            "ClickButton(second_close_tab_button);",
            "tab_strip_model->SetTabBlocked(0, true);",
            "CHECK(!second_tab_button->GetEnabled());",
            "CHECK(!new_tab_button->GetEnabled());",
            "state.expected_active_contents.push_back(nullptr);",
            "std::puts(kBrowserSmokeReadyMarker);",
            "raw_browser->GetWindow()->Close();",
            "base::RunLoop().RunUntilIdle();",
            "CHECK(browser_manager->IsEmpty());",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, browser_smoke)

    def test_runner_source_installs_the_browser_host_bridge(self) -> None:
        runner = smoke.runner_source("file:///chrome_wasm.js", 1000)
        for expected in (
            'arguments: ["--wasm-browser-smoke"]',
            "readyMarker",
            "passMarker",
            "class MockCanvasContext",
            "putImageData(imageData, x, y)",
            "result.canvasCopies",
            "globalThis.__chromiumWasmHostBridgeV1 = Object.freeze",
            "reportFrame(report)",
            "reportReadiness(report)",
            "reportOzoneFocusState(report)",
            "reportFatal(message)",
            "reportProcessExit(report)",
            "onAbort(reason)",
            "onExit(code)",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, runner)

    def test_accepts_complete_browser_presentation_and_shutdown_evidence(self) -> None:
        smoke.validate_result(successful_result(), complete_output())

    def test_rejects_each_required_browser_smoke_signal(self) -> None:
        cases: list[tuple[str, dict[str, object], str]] = []

        missing_ready = successful_result()
        cases.append(
            (
                "ready",
                missing_ready,
                "\n".join(
                    (
                        smoke.VIEWS_ACCELERATORS_MARKER,
                        smoke.TOP_CONTROLS_MARKER,
                        smoke.PASS_MARKER,
                    )
                ),
            )
        )

        missing_pass = successful_result()
        cases.append(
            (
                "pass",
                missing_pass,
                "\n".join(
                    (
                        smoke.READY_MARKER,
                        smoke.VIEWS_ACCELERATORS_MARKER,
                        smoke.TOP_CONTROLS_MARKER,
                    )
                ),
            )
        )

        missing_top_controls = successful_result()
        cases.append(
            (
                "top-controls",
                missing_top_controls,
                "\n".join(
                    (
                        smoke.READY_MARKER,
                        smoke.VIEWS_ACCELERATORS_MARKER,
                        smoke.PASS_MARKER,
                    )
                ),
            )
        )

        missing_views_accelerators = successful_result()
        cases.append(
            (
                "Views accelerators",
                missing_views_accelerators,
                "\n".join(
                    (
                        smoke.READY_MARKER,
                        smoke.TAB_STRIP_MARKER,
                        smoke.TOP_CONTROLS_MARKER,
                        smoke.VERSION_WEBUI_MARKER,
                        smoke.PASS_MARKER,
                    )
                ),
            )
        )

        missing_tab_strip = successful_result()
        cases.append(
            (
                "tab-strip",
                missing_tab_strip,
                "\n".join(
                    (
                        smoke.READY_MARKER,
                        smoke.VIEWS_ACCELERATORS_MARKER,
                        smoke.TOP_CONTROLS_MARKER,
                        smoke.VERSION_WEBUI_MARKER,
                        smoke.PASS_MARKER,
                    )
                ),
            )
        )

        missing_version_webui = successful_result()
        cases.append(
            (
                "Version WebUI",
                missing_version_webui,
                "\n".join(
                    (
                        smoke.READY_MARKER,
                        smoke.VIEWS_ACCELERATORS_MARKER,
                        smoke.TAB_STRIP_MARKER,
                        smoke.TOP_CONTROLS_MARKER,
                        smoke.PASS_MARKER,
                    )
                ),
            )
        )

        missing_settings_bootstrap = successful_result()
        cases.append(
            (
                "Settings bootstrap",
                missing_settings_bootstrap,
                "\n".join(
                    (
                        smoke.READY_MARKER,
                        smoke.VIEWS_ACCELERATORS_MARKER,
                        smoke.TAB_STRIP_MARKER,
                        smoke.TOP_CONTROLS_MARKER,
                        smoke.BROWSER_MENU_MARKER,
                        smoke.VERSION_WEBUI_MARKER,
                        smoke.PASS_MARKER,
                    )
                ),
            )
        )

        missing_browser_menu = successful_result()
        cases.append(
            (
                "in-canvas menu",
                missing_browser_menu,
                "\n".join(
                    (
                        smoke.READY_MARKER,
                        smoke.VIEWS_ACCELERATORS_MARKER,
                        smoke.TAB_STRIP_MARKER,
                        smoke.TOP_CONTROLS_MARKER,
                        smoke.SETTINGS_BOOTSTRAP_MARKER,
                        smoke.VERSION_WEBUI_MARKER,
                        smoke.PASS_MARKER,
                    )
                ),
            )
        )

        no_canvas_copy = successful_result()
        no_canvas_copy["canvasCopies"] = 0
        cases.append(
            (
                "canvas copy",
                no_canvas_copy,
                complete_output(),
            )
        )

        no_frame = successful_result()
        no_frame["frameReports"] = []
        cases.append(
            (
                "compositor frames",
                no_frame,
                complete_output(),
            )
        )

        no_readiness = successful_result()
        no_readiness["readinessReports"] = []
        cases.append(
            (
                "ready surface",
                no_readiness,
                complete_output(),
            )
        )

        no_focus = successful_result()
        no_focus["focusReports"] = []
        cases.append(
            (
                "active keyboard target",
                no_focus,
                complete_output(),
            )
        )

        for description, result, output in cases:
            with self.subTest(description=description):
                with self.assertRaisesRegex(M0Error, description):
                    smoke.validate_result(result, output)

    def test_rejects_abort_fatal_and_nonzero_exit(self) -> None:
        for field, value, expression in (
            ("abort", "abort", "aborted or rejected"),
            ("fatalReports", ["fatal"], "fatal error"),
            ("runtimeExitCode", 1, "did not exit zero"),
        ):
            with self.subTest(field=field):
                result = successful_result()
                result[field] = value
                with self.assertRaisesRegex(M0Error, expression):
                    smoke.validate_result(result, complete_output())

        result = successful_result()
        result["processExitReports"] = [{"protocol": 1, "exitCode": 17}]
        with self.assertRaisesRegex(M0Error, "nonzero"):
            smoke.validate_result(result, complete_output())

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
