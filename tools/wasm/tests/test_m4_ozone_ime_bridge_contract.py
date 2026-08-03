#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Static contracts for the M4 controlled textarea IME preedit gate."""

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


class M4OzoneImeBridgeContractTest(unittest.TestCase):
    def test_host_owns_a_real_focusable_proxy_textarea(self) -> None:
        host_page = source("tools/wasm/host/content_shell.html")
        host = source("tools/wasm/host/content_shell_host.js")

        for marker in (
            'id="m4-ime-proxy"',
            'tabindex="-1"',
            'aria-label="Chromium Wasm IME proxy"',
            'autocomplete="off"',
            'autocorrect="off"',
            'autocapitalize="off"',
            'spellcheck="false"',
            "#m4-ime-proxy",
            "width: 1px",
            "height: 1px",
            "pointer-events: none",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, host_page)
        proxy_element = section(
            host_page,
            '<textarea\n      id="m4-ime-proxy"',
            "</textarea>",
        )
        for forbidden in (
            "hidden",
            "disabled",
            "readonly",
            "inert",
            "display:none",
            "visibility:hidden",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, proxy_element)

        for marker in (
            "#imeProxy",
            "enableM4ImeProxyInput()",
            "#armM4ImeProxyActivation(record)",
            "#maybeActivateM4ImeProxy()",
            "this.#imeProxy.focus({preventScroll: true})",
            "#consumeM4ExpectedProxyFocusTransfer(relatedTarget)",
            "EXPECTED_PROXY_FOCUS_TRANSFER",
            "#cancelM4ImeProxyActivation(\"blur\")",
            "m4:ime-proxy:blur:canvas-return",
            "ime-proxy-blur",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, host)

    def test_preedit_is_trusted_bounded_and_confirmed_once(self) -> None:
        host = source("tools/wasm/host/content_shell_host.js")

        for marker in (
            "MAXIMUM_IME_PROXY_TEXT_UNITS",
            "isWellFormedUtf16(value)",
            "#handleM4ImeProxyCompositionStart(event)",
            "#handleM4ImeProxyCompositionUpdate(event)",
            "#handleM4ImeProxyBeforeInput(event)",
            "#handleM4ImeProxyInput(event)",
            'event.inputType !== "insertCompositionText"',
            "COMPOSITION_FLAG_MISMATCH",
            "PENDING_TRANSACTION_EXISTS",
            "INPUT_WITHOUT_PENDING_TRANSACTION",
            'opcode: "set-composition"',
            "rangeStart: 0",
            "rangeEnd: data.length",
            "accepted-no-native-dispatch",
            "confirmed-no-native-dispatch",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, host)

        beforeinput = section(
            host,
            "  #handleM4ImeProxyBeforeInput(event)",
            "  #handleM4ImeProxyInput(event)",
        )
        self.assertIn("this.#imeProxyPendingTransaction = {", beforeinput)
        self.assertNotIn("chromium_wasm_host_", beforeinput)
        input_handler = section(
            host,
            "  #handleM4ImeProxyInput(event)",
            "  #handleM4ImeProxyCompositionEnd(event)",
        )
        self.assertIn("this.#imeProxyPendingTransaction = null;", input_handler)
        self.assertNotIn("chromium_wasm_host_", input_handler)

    def test_proxy_focus_waits_for_native_editable_input_method_state(self) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        bridge = source("ui/ozone/platform/wasm/wasm_host_bridge.js")
        input_method_header = source(
            "ui/ozone/platform/wasm/wasm_input_method.h"
        )
        input_method = source("ui/ozone/platform/wasm/wasm_input_method.cc")
        ozone_platform = source("ui/ozone/platform/wasm/ozone_platform_wasm.cc")

        for marker in (
            "#ozoneTextInputState",
            "#ozoneTextInputReportSequence",
            "#hasM4EditableTextInputAcknowledgement()",
            "focusedClientPresent === true",
            "state.editable === true",
            "state.canComposeInline === true",
            "ozoneTextInputReportSequenceBefore",
            "textInputState.sequence <= request.ozoneTextInputReportSequenceBefore",
            "reportOzoneTextInputState(report)",
            "_reportOzoneTextInputState(value)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, host)
        for marker in (
            "chromium_wasm_report_ozone_text_input_state__proxy: 'sync'",
            "focusedClientPresent",
            "canComposeInline",
            "reportOzoneTextInputState",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, bridge)
        for marker in (
            "class WasmInputMethod final : public InputMethodMinimal",
            "OnTextInputTypeChanged(TextInputClient* client) override",
            "OnDidChangeFocusedClient",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, input_method_header)
        for marker in (
            "InputMethodMinimal::OnTextInputTypeChanged(client);",
            "GetTextInputClient()",
            "GetTextInputType() != TEXT_INPUT_TYPE_NONE",
            "client->CanComposeInline()",
            "chromium_wasm_report_ozone_text_input_state",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, input_method)
        self.assertIn(
            "std::make_unique<WasmInputMethod>(ime_key_event_dispatcher)",
            ozone_platform,
        )

    def test_smoke_is_explicitly_pre_route_and_keeps_inner_blink_unchanged(
        self,
    ) -> None:
        fixture = source("tools/wasm/testdata/m4_ozone_ime_bridge_page.html")
        host = source("tools/wasm/host/content_shell_host.js")
        cdp = source("tools/wasm/m4_cdp.py")
        runner = source("tools/wasm/run_m4_ozone_smoke.py")
        server = source("tools/wasm/m3_content_server.py")

        for marker in (
            'id="editable-target" type="text"',
            'target.addEventListener("beforeinput"',
            'target.addEventListener("input"',
            '"compositionstart", "compositionupdate", "compositionend"',
            "WAITING FOR PREEDIT BRIDGE",
            "target.value",
            "target.selectionStart",
            "target.selectionEnd",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, fixture)
        for forbidden in (
            "target.value =",
            ".focus(",
            "dispatchEvent(",
            "execCommand(",
            "Input.insertText",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, fixture)

        driver = section(
            cdp,
            "    def dispatch_ime_preedit(self) -> None:",
            "\n\ndef wait_for_page_client",
        )
        for marker in (
            '"Input.imeSetComposition"',
            '"text": "🙂"',
            '"selectionStart": 2',
            '"selectionEnd": 2',
            '"replacementStart": 0',
            '"replacementEnd": 0',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, driver)
        self.assertNotIn('"Input.insertText"', driver)

        for marker in (
            '"ime-bridge",',
            "M4_IME_BRIDGE_CASE",
            "m4_ime_bridge_smoke_url(",
            "awaiting-dom-ime-bridge-activation",
            "awaiting-dom-ime-preedit",
            "client.dispatch_ime_preedit()",
            "validate_m4_ime_bridge_result(",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, runner)
        for marker in (
            'M4_IME_BRIDGE_CASE = "ozone_ime_bridge_m4"',
            '"m4_ozone_ime_bridge_page.html"',
            '"/__m3__/m4-ime-bridge-fixture.html"',
            "def m4_ime_bridge_smoke_url(",
            "def validate_m4_ime_bridge_result(",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, server)
        result_endpoint = section(
            server,
            "    def do_POST(self) -> None:",
            "\n\n\nclass M3HTTPServer",
        )
        self.assertIn("M4_IME_BRIDGE_CASE", result_endpoint)

        smoke = section(
            host,
            "async function runM4OzoneImeBridgeSmokeFromQuery()",
            "async function runM4OzoneFocusSmokeFromQuery()",
        )
        for marker in (
            "host.enableM4PointerInput()",
            "host.enableM4FocusInput()",
            "host.enableM4ImeProxyInput()",
            "window.__chromiumWasmM4ImeBridgeState",
            "ozoneFocusAfterActivation.keyboardTargetPresent === true",
            "ozoneTextInputAfterActivation.editable === true",
            'pageProbe?.value === ""',
            "WAITING FOR PREEDIT BRIDGE",
            "preedit-captured-no-native-dispatch",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, smoke)
        for forbidden in (
            "chromium_wasm_host_text",
            "chromium_wasm_host_ime_transaction",
            "chromium_wasm_host_click",
            "Input.insertText",
            "injectInput(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, smoke)


if __name__ == "__main__":
    unittest.main()
