#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Static contracts for the bounded M4 Blink pointer-selection proof."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M4OzoneSelectionContractTest(unittest.TestCase):
    def test_fixture_reads_native_selection_without_mutating_it(self) -> None:
        fixture = source("tools/wasm/testdata/m4_ozone_selection_page.html")

        for marker in (
            'id="editable-target"',
            'type="text"',
            'value="WASM"',
            "target.selectionStart",
            "target.selectionEnd",
            "target.selectionDirection",
            "selectedText",
            "selectionActivity",
            "selectCount",
            "selectionChangeCount",
            "mouseEventTrace",
            "pointerEventTrace",
            "textInputEvents",
            "event.isTrusted",
            '"TEXT SELECTED"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, fixture)
        for forbidden in (
            "setSelectionRange(",
            "setRangeText(",
            ".select(",
            "execCommand(",
            "dispatchEvent(",
            "event.preventDefault()",
            "Input.insertText",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, fixture)
        for assignment in (
            "selectionStart",
            "selectionEnd",
            "selectionDirection",
            "value",
        ):
            with self.subTest(assignment=assignment):
                self.assertIsNone(
                    re.search(
                        rf"(?:\.{assignment}|\[[\"']{assignment}[\"']\])"
                        r"\s*=\s*(?!=)",
                        fixture,
                    )
                )

    def test_fixture_assignment_guard_rejects_direct_selection_mutation(self) -> None:
        fixture = source("tools/wasm/testdata/m4_ozone_selection_page.html")

        for assignment in (
            "selectionStart",
            "selectionEnd",
            "selectionDirection",
            "value",
        ):
            with self.subTest(assignment=assignment):
                mutated = f"{fixture}\ntarget.{assignment} = 0;\n"
                self.assertIsNotNone(
                    re.search(
                        rf"(?:\.{assignment}|\[[\"']{assignment}[\"']\])"
                        r"\s*=\s*(?!=)",
                        mutated,
                    )
                )

                mutated = f'{fixture}\ntarget["{assignment}"] = 0;\n'
                self.assertIsNotNone(
                    re.search(
                        rf"(?:\.{assignment}|\[[\"']{assignment}[\"']\])"
                        r"\s*=\s*(?!=)",
                        mutated,
                    )
                )

    def test_host_requires_full_pointer_and_blink_selection_evidence(self) -> None:
        host = source("tools/wasm/host/content_shell_host.js")

        for marker in (
            'const M4_SELECTION_CASE = "ozone_selection_m4"',
            'const M4_SELECTION_FIXTURE = "chromium-wasm-m4-ozone-selection-v1"',
            "matchesM4SelectionQueuedPointerTrace",
            "matchesM4SelectionInnerTrace",
            "hasM4SelectionSilentTextInputEvents",
            "hasM4SelectionCollapsedNativeSelection",
            "hasM4SelectionForwardOrNeutralDirection",
            "hasM4SelectionFinalPageEvidence",
            "Object.freeze({",
            "selectionCollapsed",
            "selectionDirectionNeutral",
            "selectedTextEmpty",
            "queuedRecords",
            "async function runM4OzoneSelectionSmokeFromQuery()",
            "window.__chromiumWasmM4SelectionState",
            'state: "awaiting-dom-selection-activation"',
            'state: "awaiting-dom-selection-drag"',
            "dragMiddleX",
            "mouseEventTrace",
            "pointerEventTrace",
            "TEXT SELECTED",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, host)
        self.assertNotIn("chromium_wasm_host_click", host.split(
            "async function runM4OzoneSelectionSmokeFromQuery()", 1
        )[1].split("export async function runContentShellSmokeFromQuery", 1)[0])
        smoke = host.split(
            "async function runM4OzoneSelectionSmokeFromQuery()", 1
        )[1].split("export async function runContentShellSmokeFromQuery", 1)[0]
        self.assertLess(
            smoke.index("activationProof = Object.freeze({"),
            smoke.index('state: "awaiting-dom-selection-drag"'),
        )

    def test_server_and_runner_keep_the_selection_case_separate(self) -> None:
        server = source("tools/wasm/m3_content_server.py")
        runner = source("tools/wasm/run_m4_ozone_smoke.py")
        cdp = source("tools/wasm/m4_cdp.py")

        for marker in (
            'M4_SELECTION_CASE = "ozone_selection_m4"',
            'M4_SELECTION_FIXTURE = M3_TESTDATA_DIR / "m4_ozone_selection_page.html"',
            '"/__m3__/m4-selection-fixture.html": M4_SELECTION_FIXTURE',
            "def m4_selection_smoke_url(",
            "def validate_m4_selection_result(",
            "M4 selection activation proof",
            "queued pointer trace is not exactly eight records",
            "mouseEventTrace",
            "pointerEventTrace",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, server)
        for marker in (
            '"selection",',
            "M4_SELECTION_CASE",
            "window.__chromiumWasmM4SelectionState || null",
            '"awaiting-dom-selection-activation"',
            '"awaiting-dom-selection-drag"',
            "canvas_point_position(",
            "def validate_selection_activation_stage(",
            "validate_selection_activation_stage(selection_state)",
            "client.dispatch_primary_drag(",
            "validate_m4_selection_result(",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, runner)
        self.assertLess(
            runner.index("validate_selection_activation_stage(selection_state)"),
            runner.index("client.dispatch_primary_drag("),
        )
        drag = cdp.split("    def dispatch_primary_drag(", 1)[1].split(
            "\n    def dispatch_mouse_wheel(", 1
        )[0]
        for marker in (
            '"type": "mouseMoved"',
            '"type": "mousePressed"',
            '"type": "mouseReleased"',
            '"buttons": 1',
            '"pointerType": "mouse"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, drag)
        for forbidden in ("Input.insertText", "Input.imeSetComposition", '"text":'):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, drag)


if __name__ == "__main__":
    unittest.main()
