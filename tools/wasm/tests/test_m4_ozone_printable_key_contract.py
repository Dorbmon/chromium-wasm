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
    def test_key_a_and_b_stay_bounded_physical_ozone_keys(self) -> None:
        api = source("content/shell/browser/wasm_host_api.cc")
        event_source = source("ui/ozone/platform/wasm/wasm_event_source.cc")

        for marker in (
            '"KeyA"',
            '"KeyB"',
            "ui::DomCode::US_A",
            "ui::DomCode::US_B",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, api)

        key_export = section(
            api,
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_key",
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_load_url",
        )
        for marker in (
            "code_string != content::kM4PrintableKeyADomCode",
            "code_string != content::kM4PrintableKeyBDomCode",
            "ui::KeycodeConverter::CodeStringToDomCode(code_string)",
            "content::IsSupportedM4DomCode(physical_key)",
            "GetWasmHostState().PostM4KeyCommand",
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
            "DomCode::US_A",
            "DomCode::US_B",
            "key_a_",
            "key_b_",
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

    def test_host_requires_deterministic_us_key_meanings(self) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        handler = section(
            host,
            "  #handleM4KeyboardEvent(type, event)",
            "  #disableM4KeyboardInput",
        )

        for marker in (
            'const M4_PRINTABLE_KEY_DOM_CODE = "KeyA"',
            'const M4_PRINTABLE_KEY_DOM_KEY = "a"',
            'const M4_PRINTABLE_KEY_B_DOM_CODE = "KeyB"',
            'const M4_PRINTABLE_KEY_B_DOM_KEY = "b"',
            "function expectedM4KeyboardKey(code)",
            "case M4_PRINTABLE_KEY_DOM_CODE:",
            "case M4_PRINTABLE_KEY_B_DOM_CODE:",
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

    def test_fixture_observes_two_real_default_edits_without_cheats(self) -> None:
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
            '"KeyB"',
            "keyEventTrace",
            "textInputTrace",
            "event.inputType",
            "target.value",
            "target.selectionStart",
            "target.selectionEnd",
            "textInputEvents",
            '"TEXT INPUT RECEIVED"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, fixture)
        for forbidden in (
            ".focus(",
            "event.preventDefault()",
            "execCommand(",
            "dispatchEvent(",
            "Input.insertText",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, fixture)
        self.assertNotRegex(fixture, r"target\.value\s*=(?!=)")

        text_trace_recorder = section(
            fixture,
            "function recordTextInputEvent(event)",
            'target.addEventListener("beforeinput", recordTextInputEvent);',
        )
        self.assertIn(
            "isComposing: event.isComposing === true", text_trace_recorder
        )

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
            "\n\n    def dispatch_key_b(self) -> None:",
        )
        key_b = section(
            cdp,
            "def dispatch_key_b(self) -> None:",
            "\n\n    def dispatch_backspace(self) -> None:",
        )
        for raw_key_method, code, key, virtual_key in (
            (key_a, "KeyA", "a", "65"),
            (key_b, "KeyB", "b", "66"),
        ):
            with self.subTest(code=code):
                for marker in (
                    '"type": "rawKeyDown"',
                    '"type": "keyUp"',
                    f'"code": "{code}"',
                    f'"key": "{key}"',
                    f'"windowsVirtualKeyCode": {virtual_key}',
                ):
                    self.assertIn(marker, raw_key_method)
                self.assertNotIn('"text":', raw_key_method)
                self.assertNotIn("Input.insertText", raw_key_method)

        for marker in (
            '"printable-key"',
            "M4_PRINTABLE_KEY_CASE",
            '"awaiting-dom-printable-key-activation"',
            '"awaiting-dom-printable-key"',
            '"awaiting-dom-printable-key-b"',
            "m4_printable_key_smoke_url(",
            "client.dispatch_key_a()",
            "client.dispatch_key_b()",
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
            '"KeyA"',
            '"KeyB"',
            '"value": "ab"',
            "keyEventTrace",
            "textInputTrace",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, server)

        printable_validator = section(
            server,
            "def validate_m4_printable_key_result(",
            "def validate_m4_backspace_result(",
        )
        for marker in (
            'result.get("keyAProof")',
            "expected_key_a_proof = {",
            '"outerTraceExact": True',
            '"innerTraceExact": True',
            '"textTraceExact": True',
            '"noComposition": True',
            '"value": "a"',
            '"selectionStart": 1',
            '"selectionEnd": 1',
            '"frameAfterKeyADown": True',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, printable_validator)
        expected_text_trace = section(
            printable_validator,
            "expected_text_trace = [",
            "text_trace = page_probe.get(\"textInputTrace\")",
        )
        self.assertIn('"isComposing": False', expected_text_trace)

        smoke = section(
            host,
            "async function runM4OzonePrintableKeySmokeFromQuery()",
            "async function runM4OzoneFocusSmokeFromQuery()",
        )
        for marker in (
            "host.enableM4PointerInput()",
            "host.enableM4KeyboardInput()",
            "window.__chromiumWasmM4PrintableKeyState",
            "M4_PRINTABLE_KEY_B_DOM_CODE",
            "M4_PRINTABLE_KEY_B_DOM_KEY",
            "keyEventTrace",
            "textInputTrace",
            "record?.isComposing === false",
            "keyAProof",
            'pageProbe?.value === "ab"',
            "keyboard.receivedCount === 4",
            "keyboard.trustedCount === 4",
            "keyboard.queuedCount === 4",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, smoke)
        self.assertNotIn("injectInput(", smoke)
        self.assertNotIn("chromium_wasm_host_click", smoke)
        self.assertNotIn("Input.insertText", smoke)


if __name__ == "__main__":
    unittest.main()
