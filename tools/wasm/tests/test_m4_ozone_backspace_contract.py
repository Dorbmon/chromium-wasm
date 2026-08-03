#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Static contracts for the bounded M4 physical Backspace proof."""

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


class M4OzoneBackspaceContractTest(unittest.TestCase):
    def test_backspace_stays_on_the_bounded_physical_key_abi(self) -> None:
        api = source("content/shell/browser/wasm_host_api.cc")
        event_source = source("ui/ozone/platform/wasm/wasm_event_source.cc")
        host = source("tools/wasm/host/content_shell_host.js")

        for marker in (
            'kM4BackspaceDomCode = "Backspace"',
            "ui::DomCode::BACKSPACE",
            "IsSupportedM4DomCode",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, api)
        for marker in (
            "DomCode::BACKSPACE",
            "backspace_",
            "IsSupportedM4DomCode(physical_key)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, event_source)
        for marker in (
            'const M4_BACKSPACE_DOM_CODE = "Backspace"',
            'const M4_BACKSPACE_DOM_KEY = "Backspace"',
            "case M4_BACKSPACE_DOM_CODE:",
            "matchesM4BackspaceOuterKeyRecord",
            "queuedRecords",
            "chromium_wasm_host_key",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, host)
        for forbidden in (
            "chromium_wasm_host_text(",
            "chromium_wasm_host_insert_text",
            "Input.insertText",
            "InsertText",
            "InsertChar",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, host)

    def test_fixture_observes_the_exact_blink_edit_trace(self) -> None:
        fixture = source("tools/wasm/testdata/m4_ozone_backspace_page.html")

        for marker in (
            'id="editable-target" type="text"',
            'event.code !== "KeyA" && event.code !== "Backspace"',
            "keyEventTrace",
            "textInputTrace",
            "event.isTrusted",
            "event.inputType",
            "compositionEventCounts",
            "target.selectionStart",
            "target.selectionEnd",
            '"TEXT INSERTED THEN DELETED"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, fixture)
        for forbidden in (
            ".focus(",
            'target.value = "',
            "event.preventDefault()",
            "execCommand(",
            "dispatchEvent(",
            "Input.insertText",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, fixture)

    def test_runner_stages_key_a_before_backspace_without_text(self) -> None:
        cdp = source("tools/wasm/m4_cdp.py")
        runner = source("tools/wasm/run_m4_ozone_smoke.py")
        server = source("tools/wasm/m3_content_server.py")

        backspace = section(
            cdp,
            "    def dispatch_backspace(self) -> None:",
            "\n\n    def dispatch_ime_preedit(self) -> None:",
        )
        for marker in (
            '"type": "rawKeyDown"',
            '"type": "keyUp"',
            '"code": "Backspace"',
            '"key": "Backspace"',
            '"windowsVirtualKeyCode": 8',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, backspace)
        self.assertNotIn('"text":', backspace)
        self.assertNotIn("Input.insertText", backspace)

        driver = section(
            runner,
            '        elif args.input == "backspace":\n'
            '            stage = "dispatch_trusted_dom_backspace_activation"',
            '        elif args.input == "ime-bridge":',
        )
        for marker in (
            "client.dispatch_primary_click(click_x, click_y)",
            '"awaiting-dom-backspace-key-a"',
            "client.dispatch_key_a()",
            '"awaiting-dom-backspace"',
            "validate_backspace_key_a_stage(key_a_state)",
            "client.dispatch_backspace()",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, driver)
        self.assertLess(
            driver.index("client.dispatch_key_a()"),
            driver.index('"awaiting-dom-backspace"'),
        )
        self.assertLess(
            driver.index('"awaiting-dom-backspace"'),
            driver.index("client.dispatch_backspace()"),
        )
        self.assertNotIn("Input.insertText", driver)
        self.assertNotIn("dispatch_key_a_then_backspace", runner)

        for marker in (
            'M4_BACKSPACE_CASE = "ozone_backspace_m4"',
            '"m4_ozone_backspace_page.html"',
            '"/__m3__/m4-backspace-fixture.html"',
            "def m4_backspace_smoke_url(",
            "def validate_m4_backspace_result(",
            "deleteContentBackward",
            "queued key trace is not exactly four records",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, server)

    def test_host_waits_for_the_key_a_blink_edit_before_backspace(self) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        smoke = section(
            host,
            "async function runM4OzoneBackspaceSmokeFromQuery()",
            "async function runM4OzoneImeBridgeSmokeFromQuery()",
        )

        for marker in (
            "host.enableM4PointerInput()",
            "host.enableM4KeyboardInput()",
            "window.__chromiumWasmM4BackspaceState",
            'state: "awaiting-dom-backspace-key-a"',
            'state: "awaiting-dom-backspace"',
            "const keyAProof = {",
            "M4 trusted Ozone KeyA insert timeout before Backspace",
            "insertText",
            "deleteContentBackward",
            "TEXT INSERTED THEN DELETED",
            "keyboard?.receivedCount === 4",
            "compositionCounts?.compositionstart === 0",
            "readiness.frame?.id > backspaceDown?.frameIdBefore",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, smoke)
        self.assertLess(
            smoke.index("M4 trusted Ozone KeyA insert timeout before Backspace"),
            smoke.index("const keyAProof = {"),
        )
        self.assertLess(
            smoke.index("const keyAProof = {"),
            smoke.index('state: "awaiting-dom-backspace"'),
        )
        self.assertLess(
            smoke.index('state: "awaiting-dom-backspace"'),
            smoke.index("const backspaceDown = queuedRecords?.[2];"),
        )
        for forbidden in (
            "injectInput(",
            "chromium_wasm_host_click",
            "Input.insertText",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, smoke)


if __name__ == "__main__":
    unittest.main()
