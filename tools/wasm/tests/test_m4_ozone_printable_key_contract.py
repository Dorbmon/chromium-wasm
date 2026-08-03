#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Static contracts for bounded printable Ozone/Aura key input."""

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


class M4OzonePrintableKeyContractTest(unittest.TestCase):
    def test_key_a_stays_a_bounded_physical_ozone_key(self) -> None:
        api = source("content/shell/browser/wasm_host_api.cc")
        event_source = source("ui/ozone/platform/wasm/wasm_event_source.cc")

        self.assertIn('kM4PrintableDomCode = "KeyA"', api)
        self.assertIn("ui::DomCode::US_A", api)
        key_export = section(
            api,
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_key",
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_load_url",
        )
        for marker in (
            "code_string != content::kM4PrintableDomCode",
            "ui::KeycodeConverter::CodeStringToDomCode(code_string)",
            "content::IsSupportedM4DomCode(physical_key)",
            "PostHostCommand",
            "DispatchDomKeyOnUiThread",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, key_export)
        for forbidden in (
            "RenderWidgetHost",
            "WebKeyboardEvent",
            "ForwardKeyboardEvent",
            "InsertText",
            "InsertChar",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, key_export)

        injector = section(
            event_source,
            "void InjectKeyEvent(DomCode physical_key",
            " private:",
        )
        for marker in (
            "IsSupportedM4DomCode(physical_key)",
            "DomCode::ARROW_DOWN",
            "key_a_",
            "key_down == down",
            "event_source_->DispatchKeyEvent(",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, injector)
        self.assertNotIn("KeyEvent event", injector)

        dispatch = section(
            event_source,
            "bool WasmPlatformEventSource::DispatchKeyEvent",
            "std::unique_ptr<SystemInputInjector> "
            "CreateWasmSystemInputInjector",
        )
        for marker in (
            "KeyboardLayoutEngineManager::GetKeyboardLayoutEngine",
            "layout_engine->Lookup(physical_key, flags, &dom_key, &key_code)",
            "KeyEvent event(type, key_code, physical_key, flags, dom_key,",
            "Event::DispatcherApi(&event).set_target(target)",
            "PlatformEventSource::DispatchEvent(&event)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, dispatch)
        for forbidden in (
            "RenderWidgetHost",
            "WebKeyboardEvent",
            "ForwardKeyboardEvent",
            "InsertText",
            "InsertChar",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, dispatch)

    def test_host_requires_the_deterministic_us_key_meaning(self) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        handler = section(
            host,
            "  #handleM4KeyboardEvent(type, event)",
            "  #disableM4KeyboardInput",
        )

        for marker in (
            'const M4_PRINTABLE_KEY_DOM_CODE = "KeyA"',
            'const M4_PRINTABLE_KEY_DOM_KEY = "a"',
            "function expectedM4KeyboardKey(code)",
            "case M4_PRINTABLE_KEY_DOM_CODE:",
            "expectedM4KeyboardKey(record.code)",
            "record.key !== expectedKey",
            "UNSUPPORTED_DOM_KEY",
            "chromium_wasm_host_key",
            "event.preventDefault()",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, host)
        self.assertLess(
            handler.index("record.queued = result === 1"),
            handler.index("event.preventDefault()"),
        )
        for forbidden in (
            # The separate IME ABI is `chromium_wasm_host_text_input`; keep
            # rejecting the old generic text-insertion export instead.
            "chromium_wasm_host_text(",
            "chromium_wasm_host_insert_text",
            "Input.insertText",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, host)

    def test_fixture_observes_real_default_editing_without_cheats(self) -> None:
        fixture = source(
            "tools/wasm/testdata/m4_ozone_printable_key_page.html"
        )

        for marker in (
            'id="editable-target" type="text"',
            'document.addEventListener("keydown"',
            'document.addEventListener("keyup"',
            'target.addEventListener("beforeinput"',
            'target.addEventListener("input"',
            "event.isTrusted",
            '"KeyA"',
            "event.inputType",
            "target.value",
            "target.selectionStart",
            "target.selectionEnd",
            "compositionstartCount",
            '"TEXT INPUT RECEIVED"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, fixture)
        for forbidden in (
            ".focus(",
            "target.value =",
            "event.preventDefault()",
            "execCommand(",
            "dispatchEvent(",
            "Input.insertText",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, fixture)

    def test_runner_server_and_cdp_keep_text_out_of_the_outer_protocol(
        self,
    ) -> None:
        cdp = source("tools/wasm/m4_cdp.py")
        runner = source("tools/wasm/run_m4_ozone_smoke.py")
        server = source("tools/wasm/m3_content_server.py")
        host = source("tools/wasm/host/content_shell_host.js")

        key_a = section(
            cdp,
            "def dispatch_key_a(self) -> None:",
            "\n\n    def dispatch_ime_preedit(self) -> None:",
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
        self.assertNotIn("Input.insertText", key_a)

        for marker in (
            '"printable-key"',
            "M4_PRINTABLE_KEY_CASE",
            '"awaiting-dom-printable-key-activation"',
            '"awaiting-dom-printable-key"',
            "m4_printable_key_smoke_url(",
            "client.dispatch_key_a()",
            "validate_m4_printable_key_result(",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, runner)

        for marker in (
            'M4_PRINTABLE_KEY_CASE = "ozone_printable_key_m4"',
            '"m4_ozone_printable_key_page.html"',
            '"/__m3__/m4-printable-key-fixture.html"',
            "def m4_printable_key_smoke_url(",
            "def validate_m4_printable_key_result(",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, server)

        smoke = section(
            host,
            "async function runM4OzonePrintableKeySmokeFromQuery()",
            "async function runM4OzoneFocusSmokeFromQuery()",
        )
        for marker in (
            "host.enableM4PointerInput()",
            "host.enableM4KeyboardInput()",
            "window.__chromiumWasmM4PrintableKeyState",
            "TEXT INPUT RECEIVED",
            "beforeinputInputType",
            "selectionStart",
            "keyboard.receivedCount === 2",
            "keyboard.trustedCount === 2",
            "keyboard.queuedCount === 2",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, smoke)
        self.assertNotIn("injectInput(", smoke)
        self.assertNotIn("chromium_wasm_host_click", smoke)


if __name__ == "__main__":
    unittest.main()
