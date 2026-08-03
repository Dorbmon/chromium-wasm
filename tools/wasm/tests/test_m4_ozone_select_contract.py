#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Static contracts for the M4 native HTML select-popup smoke."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


class M4OzoneSelectContractTest(unittest.TestCase):
    def test_fixture_observes_a_native_select_without_mutating_it(self) -> None:
        fixture = source("tools/wasm/testdata/m4_ozone_select_page.html")

        for marker in (
            '<select id="select-target"',
            '<option value="one"',
            '<option value="two"',
            "rgb(250, 0, 250)",
            "selectedIndex",
            'target.addEventListener("input"',
            'target.addEventListener("change"',
            "event.isTrusted",
            "inputEventTrace",
            "changeEventTrace",
            "SELECTED:${target.value}",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, fixture)
        for forbidden in (
            "showPicker(",
            "dispatchEvent(",
            "execCommand(",
            "Input.insertText",
            "setSelectionRange(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, fixture)
        for assignment in ("value", "selectedIndex"):
            with self.subTest(assignment=assignment):
                self.assertIsNone(
                    re.search(
                        rf"(?:\.{assignment}|\[[\"']{assignment}[\"']\])"
                        r"\s*=\s*(?!=)",
                        fixture,
                    )
                )

    def test_host_requires_open_popup_scan_and_native_option_delivery(self) -> None:
        host = source("tools/wasm/host/content_shell_host.js")

        for marker in (
            'const M4_SELECT_CASE = "ozone_select_m4"',
            'const M4_SELECT_FIXTURE = "chromium-wasm-m4-ozone-select-v1"',
            "function scanM4SelectPopupOption(canvas, selectBounds)",
            "popupOptionScan",
            "popupOpenPointer",
            "optionPointer",
            "hasM4SelectOpenerTrace",
            "host.enableM4PointerInput()",
            "async function runM4OzoneSelectSmokeFromQuery()",
            "window.__chromiumWasmM4SelectState",
            'state: "awaiting-dom-select-open"',
            'state: "awaiting-dom-select-option"',
            "M4_SELECT_OPTION_RGBA",
            "rgba: Array.from(M4_SELECT_OPTION_RGBA)",
            "SELECTED:two",
            "pointer?.queuedCount === 6",
            "pageProbe?.inputEventTrace?.length === 1",
            "scanM4SelectPopupOption(canvas, targetBounds) === null",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, host)
        smoke = section(
            host,
            "async function runM4OzoneSelectSmokeFromQuery()",
            "async function runM4OzoneSelectionSmokeFromQuery()",
        )
        self.assertNotIn("chromium_wasm_host_click", smoke)
        self.assertLess(
            smoke.index('state: "awaiting-dom-select-open"'),
            smoke.index('state: "awaiting-dom-select-option"'),
        )
        self.assertLess(
            smoke.index("scanM4SelectPopupOption(canvas, targetBounds)"),
            smoke.index('state: "awaiting-dom-select-option"'),
        )

    def test_server_runner_and_cdp_keep_the_select_case_separate(self) -> None:
        server = source("tools/wasm/m3_content_server.py")
        runner = source("tools/wasm/run_m4_ozone_smoke.py")

        for marker in (
            'M4_SELECT_CASE = "ozone_select_m4"',
            'M4_SELECT_FIXTURE = M3_TESTDATA_DIR / "m4_ozone_select_page.html"',
            '"/__m3__/m4-select-fixture.html": M4_SELECT_FIXTURE',
            "def m4_select_smoke_url(",
            "def validate_m4_select_result(",
            "M4 select popup option scan",
            "popupOptionScan",
            "popupOpenPointer",
            "optionPointer",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, server)
        for marker in (
            '"select",',
            "M4_SELECT_CASE",
            "m4_select_smoke_url(",
            "window.__chromiumWasmM4SelectState || null",
            '"awaiting-dom-select-open"',
            '"awaiting-dom-select-option"',
            "client.dispatch_primary_click(",
            "validate_m4_select_result(result, expected_versions=versions)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, runner)


if __name__ == "__main__":
    unittest.main()
