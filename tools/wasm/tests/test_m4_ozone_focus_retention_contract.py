#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Static contracts for retained M4 Ozone/Blink focus."""

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


class M4OzoneFocusRetentionContractTest(unittest.TestCase):
    def test_fixture_keeps_the_editable_blink_target_through_an_inert_move(
        self,
    ) -> None:
        fixture = source("tools/wasm/testdata/m4_ozone_focus_retention_page.html")

        for marker in (
            'id="editable-target" type="text"',
            'id="retention-target"',
            "THEN MOVE OVER THIS INERT TARGET AND PRESS A",
            'retentionTarget.addEventListener("pointermove"',
            "retentionPointerMoveCount",
            "retentionPointerMoveTrusted",
            'window.addEventListener("blur"',
            "editableFocusCount === 1",
            "editableBlurCount === 0",
            "windowBlurCount === 0",
            "document.activeElement === editable",
            "keyEventTrace",
            "textInputTrace",
            "compositionEventCounts",
            '"FOCUS RETAINED"',
            '"chromium-wasm-m4-ozone-focus-retention-v1"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, fixture)
        self.assertNotIn('id="retention-target" tabindex', fixture)
        self.assertNotIn('retentionTarget.addEventListener("pointerdown"', fixture)
        self.assertNotIn('retentionTarget.addEventListener("click"', fixture)
        for forbidden in (
            ".focus(",
            ".blur(",
            "dispatchEvent(",
            "event.preventDefault()",
            "execCommand(",
            "Input.insertText",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, fixture)

    def test_host_requires_stable_native_focus_through_the_inert_move(self) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        smoke = section(
            host,
            "async function runM4OzoneFocusRetentionSmokeFromQuery()",
            "export async function runContentShellSmokeFromQuery",
        )

        for marker in (
            "#ozoneFocusReports",
            "ozoneFocusReports",
            "retentionOzoneFocusReports",
            "retentionFocusSequenceBefore",
            "retentionFocusSequenceAfter",
            "reportsAfter?.length === 0",
            "retentionOzoneFocusReports.length === 0",
            "nativeFocusStateStable",
            "keyboardTargetPresent === true",
            "windowBlurCount === 0",
            "keyboard?.activated === true",
            'state: "awaiting-dom-focus-retention-pointer"',
            'state: "awaiting-dom-focus-retention-key"',
            "matchesPointerTrace",
            "pointer?.receivedCount === expected.length",
            "record?.button === button",
            "record?.buttons === buttons",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, host if marker == "#ozoneFocusReports" else smoke)
        self.assertNotIn("reportsAfter.every", smoke)
        self.assertNotIn("finalOzoneFocusReports.every", smoke)
        pointer_trace = section(
            smoke,
            "  const expectedPointerTrace = () => [",
            "  const initialPointerTrace",
        )
        for marker in (
            '["move", editableTargetX, editableTargetY, -1, 0]',
            '["down", editableTargetX, editableTargetY, 0, 1]',
            '["up", editableTargetX, editableTargetY, 0, 0]',
            '["move", retentionTargetX, retentionTargetY, -1, 0]',
        ):
            with self.subTest(pointer_marker=marker):
                self.assertIn(marker, pointer_trace)
        self.assertNotIn('["down", retentionTargetX', pointer_trace)
        self.assertNotIn('["up", retentionTargetX', pointer_trace)
        self.assertLess(
            smoke.index('state: "awaiting-dom-focus-retention-pointer"'),
            smoke.index('state: "awaiting-dom-focus-retention-key"'),
        )
        self.assertLess(
            smoke.index('state: "awaiting-dom-focus-retention-key"'),
            smoke.index("M4 ready for trusted raw KeyA after retained focus"),
        )
        for forbidden in (
            "chromium_wasm_host_deactivate",
            "chromium_wasm_host_activate",
            "injectInput(",
            "chromium_wasm_host_click",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, smoke)

    def test_runner_uses_a_click_then_unpressed_move_then_a_raw_key_a(self) -> None:
        cdp = source("tools/wasm/m4_cdp.py")
        runner = source("tools/wasm/run_m4_ozone_smoke.py")
        server = source("tools/wasm/m3_content_server.py")

        driver = section(
            runner,
            '        elif args.input == "focus-retention":\n'
            '            stage = "dispatch_trusted_dom_focus_retention_activation"',
            '        else:\n            stage = "dispatch_trusted_dom_focus_activation"',
        )
        for marker in (
            "client.dispatch_primary_click(click_x, click_y)",
            '"awaiting-dom-focus-retention-pointer"',
            "retentionTargetX",
            "retentionTargetY",
            "client.dispatch_mouse_move(retention_x, retention_y)",
            '"awaiting-dom-focus-retention-key"',
            "client.dispatch_key_a()",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, driver)
        self.assertLess(
            driver.index("client.dispatch_primary_click(click_x, click_y)"),
            driver.index("client.dispatch_mouse_move(retention_x, retention_y)"),
        )
        self.assertLess(
            driver.index("client.dispatch_mouse_move(retention_x, retention_y)"),
            driver.index("client.dispatch_key_a()"),
        )
        self.assertNotIn(
            "client.dispatch_primary_click(retention_x, retention_y)", driver
        )
        self.assertNotIn("Input.insertText", driver)

        key_a = section(
            cdp,
            "    def dispatch_key_a(self) -> None:",
            "\n\n    def dispatch_key_b(self) -> None:",
        )
        for marker in (
            '"type": "rawKeyDown"',
            '"type": "keyUp"',
            '"code": "KeyA"',
            '"key": "a"',
            '"windowsVirtualKeyCode": 65',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, key_a)
        self.assertNotIn('"text":', key_a)

        for marker in (
            'M4_FOCUS_RETENTION_CASE = "ozone_focus_retention_m4"',
            '"m4_ozone_focus_retention_page.html"',
            '"/__m3__/m4-focus-retention-fixture.html"',
            "def m4_focus_retention_smoke_url(",
            "def validate_m4_focus_retention_result(",
            "retentionPointerMoveCount",
            "retentionPointerMoveTrusted",
            "retentionOzoneFocusReports",
            "nativeFocusStateStable",
            '"m4:pointer:move:queued"',
            "unexpected_reason",
            '"canvas-blur"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, server)

    def test_runtime_focus_loss_remains_distinct_from_shutdown(self) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        server = source("tools/wasm/m3_content_server.py")
        shutdown = section(
            host,
            "  async shutdown(timeoutMs = DEFAULT_SHUTDOWN_TIMEOUT_MS)",
            "  _reportFrame(value)",
        )

        self.assertIn('#deactivateM4HostWindow("shutdown")', shutdown)
        validator = section(
            server,
            "def validate_m4_focus_retention_result(",
            "@dataclass(frozen=True)",
        )
        for reason in (
            '"canvas-blur"',
            '"window-blur"',
            '"visibility-loss"',
            '"ime-proxy-blur"',
        ):
            with self.subTest(reason=reason):
                self.assertIn(reason, validator)
        self.assertNotIn('any("deactivate-queued"', validator)


if __name__ == "__main__":
    unittest.main()
