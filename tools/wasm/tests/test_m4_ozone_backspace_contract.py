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
            'const M4_BACKSPACE_FIXTURE = "chromium-wasm-m4-ozone-backspace-v2"',
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

        handler = section(
            host,
            "  #handleM4KeyboardEvent(type, event)",
            "  #disableM4KeyboardInput",
        )
        for marker in (
            "const backspaceRepeat = type === \"down\" && record.repeat &&",
            "record.code === M4_BACKSPACE_DOM_CODE",
            "this.#keyboardCodesDown.has(record.code)",
            "const boundedRepeat = arrowDownRepeat || backspaceRepeat",
            "if (record.repeat && !boundedRepeat)",
            "UNSUPPORTED_REPEAT",
            "chromium_wasm_host_backspace_repeat",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, handler)
        self.assertRegex(
            handler,
            r"const backspaceRepeat = type === \"down\" && record\.repeat &&\s*"
            r"record\.code === M4_BACKSPACE_DOM_CODE &&\s*"
            r"this\.\#keyboardCodesDown\.has\(record\.code\);",
        )

    def test_fixture_observes_the_exact_blink_edit_trace(self) -> None:
        fixture = source("tools/wasm/testdata/m4_ozone_backspace_page.html")

        for marker in (
            'id="editable-target" type="text"',
            'event.code !== "KeyA"',
            'event.code !== "KeyB"',
            'event.code !== "Backspace"',
            "keyEventTrace",
            "textInputTrace",
            "event.isTrusted",
            "event.repeat",
            "event.isComposing",
            "event.inputType",
            "compositionEventCounts",
            "target.selectionStart",
            "target.selectionEnd",
            '"chromium-wasm-m4-ozone-backspace-v2"',
            "textInputTrace.length === 8",
            '"TEXT INSERTED THEN REPEATEDLY DELETED"',
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

    def test_backspace_repeat_requires_a_held_backspace(self) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        handler = section(
            host,
            "  #handleM4KeyboardEvent(type, event)",
            "  #disableM4KeyboardInput",
        )

        # This guard rejects repeat-before-down and repeat-after-up because
        # the code is absent from #keyboardCodesDown, and rejects KeyA
        # repeats because the code must be the bounded Backspace code.
        for scenario, guard in (
            ("repeat-before-down", "this.#keyboardCodesDown.has(record.code)"),
            ("KeyA-repeat", "record.code === M4_BACKSPACE_DOM_CODE"),
            ("repeat-after-keyup", "this.#keyboardCodesDown.has(record.code)"),
        ):
            with self.subTest(scenario=scenario):
                self.assertIn(guard, handler)
                self.assertIn("if (record.repeat && !boundedRepeat)", handler)
                self.assertIn("UNSUPPORTED_REPEAT", handler)

    def test_runner_stages_key_a_key_b_and_backspace_repeat_without_text(
        self,
    ) -> None:
        cdp = source("tools/wasm/m4_cdp.py")
        runner = source("tools/wasm/run_m4_ozone_smoke.py")
        server = source("tools/wasm/m3_content_server.py")

        backspace_down = section(
            cdp,
            "    def dispatch_backspace_down(self) -> None:",
            "\n\n    def dispatch_backspace_repeat(self) -> None:",
        )
        backspace_base = section(
            cdp,
            "    def _backspace_key_event() -> dict[str, object]:",
            "\n\n    def dispatch_backspace_down(self) -> None:",
        )
        backspace_repeat = section(
            cdp,
            "    def dispatch_backspace_repeat(self) -> None:",
            "\n\n    def dispatch_backspace_up(self) -> None:",
        )
        backspace_up = section(
            cdp,
            "    def dispatch_backspace_up(self) -> None:",
            "\n\n    def dispatch_backspace(self) -> None:",
        )
        backspace = section(
            cdp,
            "    def dispatch_backspace(self) -> None:",
            "\n\n    def dispatch_control_shortcut(",
        )
        for marker in (
            '"code": "Backspace"',
            '"key": "Backspace"',
            '"windowsVirtualKeyCode": 8',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, backspace_base)
        self.assertIn('"type": "rawKeyDown"', backspace_down)
        self.assertIn('"autoRepeat": True', backspace_repeat)
        self.assertIn('"type": "keyUp"', backspace_up)
        for marker in (
            "self.dispatch_backspace_down()",
            "self.dispatch_backspace_repeat()",
            "self.dispatch_backspace_up()",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, backspace)
        for method in (backspace_down, backspace_repeat, backspace_up):
            self.assertNotIn('"text":', method)
            self.assertNotIn("Input.insertText", method)

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
            '"awaiting-dom-backspace-key-b"',
            "validate_backspace_key_a_stage(key_a_state)",
            "client.dispatch_key_b()",
            '"awaiting-dom-backspace-down"',
            "validate_backspace_key_b_stage(key_b_state)",
            "client.dispatch_backspace_down()",
            '"awaiting-dom-backspace-repeat"',
            "validate_backspace_initial_delete_stage(backspace_down_state)",
            "client.dispatch_backspace_repeat()",
            '"awaiting-dom-backspace-up"',
            "validate_backspace_repeat_delete_stage(backspace_repeat_state)",
            "client.dispatch_backspace_up()",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, driver)
        self.assertLess(
            driver.index("client.dispatch_key_a()"),
            driver.index('"awaiting-dom-backspace-key-b"'),
        )
        self.assertLess(
            driver.index("client.dispatch_key_b()"),
            driver.index('"awaiting-dom-backspace-down"'),
        )
        self.assertLess(
            driver.index("client.dispatch_backspace_down()"),
            driver.index('"awaiting-dom-backspace-repeat"'),
        )
        self.assertLess(
            driver.index("client.dispatch_backspace_repeat()"),
            driver.index('"awaiting-dom-backspace-up"'),
        )
        self.assertLess(
            driver.index('"awaiting-dom-backspace-up"'),
            driver.index("client.dispatch_backspace_up()"),
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
            "keyAProof",
            "keyBProof",
            "backspaceRepeatProof",
            "repeatExact",
            "queued key trace is not exactly seven records",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, server)

    def test_host_stages_key_a_key_b_and_held_backspace_repeat(self) -> None:
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
            'state: "awaiting-dom-backspace-key-b"',
            'state: "awaiting-dom-backspace-down"',
            'state: "awaiting-dom-backspace-repeat"',
            'state: "awaiting-dom-backspace-up"',
            "keyAProof = {",
            "keyBProof = {",
            "backspaceDownProof",
            "backspaceRepeatProof = {",
            "keyABQueue",
            "backspaceDownQueue",
            "backspaceRepeatQueue",
            "M4 trusted Ozone KeyB insert timeout before Backspace",
            "insertText",
            "deleteContentBackward",
            "TEXT INSERTED THEN REPEATEDLY DELETED",
            "keyboard?.receivedCount === 7",
            "compositionCounts?.compositionstart === 0",
            "repeatExact",
            "initialDownRepeatFalse",
            "repeatedDownRepeatTrue",
            "releaseRepeatFalse",
            "backspaceHeld",
            "releaseExact",
            "readiness.frame?.id > repeatedBackspaceDown?.frameIdBefore",
            "keyAProof,",
            "keyBProof,",
            "backspaceRepeatProof,",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, smoke)
        self.assertLess(
            smoke.index("keyAProof = {"),
            smoke.index('state: "awaiting-dom-backspace-key-b"'),
        )
        self.assertLess(
            smoke.index('state: "awaiting-dom-backspace-key-b"'),
            smoke.index("keyBProof = {"),
        )
        self.assertLess(
            smoke.index("keyBProof = {"),
            smoke.index('state: "awaiting-dom-backspace-down"'),
        )
        self.assertLess(
            smoke.index('state: "awaiting-dom-backspace-down"'),
            smoke.index('state: "awaiting-dom-backspace-repeat"'),
        )
        self.assertLess(
            smoke.index('state: "awaiting-dom-backspace-repeat"'),
            smoke.index('state: "awaiting-dom-backspace-up"'),
        )
        for forbidden in (
            "injectInput(",
            "chromium_wasm_host_click",
            "Input.insertText",
            "keyboard.receivedCount === 4",
            "pageProbe.resultText === \"TEXT INSERTED THEN DELETED\"",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, smoke)


if __name__ == "__main__":
    unittest.main()
