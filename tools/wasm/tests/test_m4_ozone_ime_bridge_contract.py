#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Static contracts for trusted M4 IME composition through Ozone."""

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

    def test_proxy_validates_then_queues_set_confirm_and_clear_records(
        self,
    ) -> None:
        host = source("tools/wasm/host/content_shell_host.js")

        for marker in (
            "MAXIMUM_IME_PROXY_TEXT_UNITS",
            "MAXIMUM_IME_PROXY_TEXT_BYTES",
            "M4_IME_TEXT_ACTION",
            "UTF8_ENCODER",
            "isWellFormedUtf16(value)",
            "#queueM4ImeProxyTextInput(action, sessionId, sequence, text, selection)",
            "chromium_wasm_host_text_input",
            '["number", "number", "number", "array", "number", "number", "number"]',
            "#queueM4ImeProxyClear(reason)",
            "#handleM4ImeProxyCompositionStart(event)",
            "#handleM4ImeProxyCompositionUpdate(event)",
            "#handleM4ImeProxyBeforeInput(event)",
            "#handleM4ImeProxyInput(event)",
            "#handleM4ImeProxyCompositionEnd(event)",
            'event.inputType !== "insertCompositionText"',
            "COMPOSITION_FLAG_MISMATCH",
            "PENDING_TRANSACTION_EXISTS",
            "INPUT_WITHOUT_PENDING_TRANSACTION",
            "NATIVE_SET_QUEUE_REJECTED",
            "NATIVE_CONFIRM_QUEUE_REJECTED",
            "NATIVE_CLEAR_QUEUE_REJECTED",
            "m4:ime-proxy:beforeinput:native-set-queued",
            "m4:ime-proxy:input:confirmed-native-set",
            "m4:ime-proxy:input:native-clear-queued",
            "m4:ime-proxy:compositionend:native-confirm-queued",
            "m4:ime-proxy:compositionend:clear-observed",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, host)
        for obsolete_marker in (
            "accepted-no-native-dispatch",
            "confirmed-no-native-dispatch",
            "m4:ime-proxy:compositionend:native-clear-queued",
        ):
            with self.subTest(obsolete_marker=obsolete_marker):
                self.assertNotIn(obsolete_marker, host)

        queue = section(
            host,
            "  #queueM4ImeProxyTextInput(action, sessionId, sequence, text, selection)",
            "  #queueM4ImeProxyClear(reason)",
        )
        for marker in (
            "const utf8 = UTF8_ENCODER.encode(text);",
            "MAXIMUM_IME_PROXY_TEXT_BYTES",
            "M4_IME_TEXT_ACTION.setComposition",
            "this.#callExport(",
            '"chromium_wasm_host_text_input"',
            "request.queued = result === 1;",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, queue)

        beforeinput = section(
            host,
            "  #handleM4ImeProxyBeforeInput(event)",
            "  #handleM4ImeProxyInput(event)",
        )
        for marker in (
            "this.#imeProxyPendingTransaction = transaction;",
            "M4_IME_TEXT_ACTION.setComposition",
            "this.#queueM4ImeProxyTextInput(",
            "this.#imeProxyNativeComposition = {",
            "record.nativeQueued = true;",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, beforeinput)

        input_handler = section(
            host,
            "  #handleM4ImeProxyInput(event)",
            "  #handleM4ImeProxyCompositionEnd(event)",
        )
        self.assertIn("this.#imeProxyPendingTransaction = null;", input_handler)
        self.assertNotIn("chromium_wasm_host_text_input", input_handler)
        for marker in (
            "if (this.#imeProxyTerminalCancellationPending)",
            "M4_IME_TEXT_ACTION.clearComposition",
            "this.#queueM4ImeProxyTextInput(",
            "this.#imeProxyExpectedTerminalAction =",
            "m4:ime-proxy:input:native-clear-queued",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, input_handler)

        composition_end = section(
            host,
            "  #handleM4ImeProxyCompositionEnd(event)",
            "  #disableM4ImeProxyInput",
        )
        for marker in (
            "M4_IME_TEXT_ACTION.confirmComposition",
            "this.#queueM4ImeProxyTextInput(",
            "this.#imeProxyNativeTerminalAction = request;",
            "this.#imeProxyCompositionActive = false;",
            "record.terminalObservedAfterClear = true;",
            "m4:ime-proxy:compositionend:clear-observed",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, composition_end)

        clear = section(
            host,
            "  #queueM4ImeProxyClear(reason)",
            "  #imeProxyInputStatus()",
        )
        self.assertIn("M4_IME_TEXT_ACTION.clearComposition", clear)
        self.assertIn("this.#imeProxyNativeTerminalAction = request;", clear)

    def test_only_composition_end_has_a_zero_authority_terminal_path(
        self,
    ) -> None:
        host = source("tools/wasm/host/content_shell_host.js")

        strict_event = section(
            host,
            "  #validateM4ImeProxyEvent(record)",
            "  #validateM4ImeProxyTerminal(record)",
        )
        for marker in (
            "if (!record.trusted) {",
            'this.#rejectM4ImeProxyRecord(record, "UNTRUSTED_DOM_EVENT");',
            "return this.#validateM4ImeProxyContext(record);",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, strict_event)
        self.assertNotIn("allowDerivedTerminal", strict_event)

        terminal = section(
            host,
            "  #validateM4ImeProxyTerminal(record)",
            "  #handleM4ImeProxyCompositionStart(event)",
        )
        for marker in (
            "Blink intentionally dispatches compositionend",
            "terminal has no",
            "exact private candidate created by prior trusted source events",
            "return this.#validateM4ImeProxyContext(record);",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, terminal)
        for forbidden in (
            "allowDerivedTerminal",
            "testOnly",
            "fixture",
            "token",
            "dispatchEvent",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, terminal)

        start = section(
            host,
            "  #handleM4ImeProxyCompositionStart(event)",
            "  #handleM4ImeProxyCompositionUpdate(event)",
        )
        update = section(
            host,
            "  #handleM4ImeProxyCompositionUpdate(event)",
            "  #handleM4ImeProxyBeforeInput(event)",
        )
        beforeinput = section(
            host,
            "  #handleM4ImeProxyBeforeInput(event)",
            "  #handleM4ImeProxyInput(event)",
        )
        input_handler = section(
            host,
            "  #handleM4ImeProxyInput(event)",
            "  #handleM4ImeProxyCompositionEnd(event)",
        )
        for handler in (start, update, beforeinput, input_handler):
            self.assertIn("#validateM4ImeProxyEvent(record)", handler)
            self.assertNotIn("#validateM4ImeProxyTerminal", handler)

        composition_end = section(
            host,
            "  #handleM4ImeProxyCompositionEnd(event)",
            "  #disableM4ImeProxyInput",
        )
        for marker in (
            "#validateM4ImeProxyTerminal(record)",
            "this.#imeProxyExpectedTerminalAction ===",
            "M4_IME_TEXT_ACTION.clearComposition",
            "record.terminalObservedAfterClear = true;",
            "m4:ime-proxy:compositionend:clear-observed",
            "!this.#imeProxyCompositionActive",
            "this.#imeProxyPendingTransaction !== null",
            "composition.sessionId !== this.#imeProxySessionId",
            "this.#imeProxyNativeTerminalAction !== null",
            "this.#imeProxyLastConfirmedText !== composition.text",
            "if (data !== composition.text)",
            "M4_IME_TEXT_ACTION.confirmComposition",
            "record.terminalDerivedFromTrustedTransaction = !record.trusted;",
            "composition.sessionId,",
            '"",',
            "{start: 0, end: 0}",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, composition_end)
        self.assertNotIn("#validateM4ImeProxyEvent(record)", composition_end)
        for forbidden in (
            "allowDerivedTerminal",
            "testOnly",
            "fixture",
            "token",
            "dispatchEvent",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, composition_end)

        normal_terminal = composition_end.split("    const composition =", 1)[1]
        self.assertNotIn(
            "M4_IME_TEXT_ACTION.clearComposition", normal_terminal
        )

        # One declaration plus the compositionend call; no other production
        # DOM handler may take the untrusted terminal path.
        self.assertEqual(host.count("#validateM4ImeProxyTerminal(record)"), 2)

        # The only direct native route calls are the lifecycle clear, trusted
        # beforeinput set, trusted empty-input clear, and constrained confirm.
        self.assertEqual(host.count("this.#queueM4ImeProxyTextInput("), 4)

    def test_trusted_empty_source_records_queue_clear_before_terminal(
        self,
    ) -> None:
        host = source("tools/wasm/host/content_shell_host.js")

        update = section(
            host,
            "  #handleM4ImeProxyCompositionUpdate(event)",
            "  #handleM4ImeProxyBeforeInput(event)",
        )
        for marker in (
            "#validateM4ImeProxyEvent(record)",
            'if (data === "")',
            "this.#imeProxyNativeComposition",
            "this.#imeProxyPendingTransaction !== null",
            "this.#imeProxyLastConfirmedText !==",
            "CANCELLATION_UPDATE_WITHOUT_CONFIRMED_COMPOSITION",
            "this.#imeProxyTerminalCancellationPending = true;",
            "m4:ime-proxy:compositionupdate:cancellation-pending",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, update)

        beforeinput = section(
            host,
            "  #handleM4ImeProxyBeforeInput(event)",
            "  #handleM4ImeProxyInput(event)",
        )
        for marker in (
            "#validateM4ImeProxyEvent(record)",
            'data === "" || data === null',
            "this.#imeProxyTerminalCancellationPending",
            "this.#imeProxyNativeComposition",
            "this.#imeProxyNativeTerminalAction !== null",
            "CANCELLATION_BEFOREINPUT_WITHOUT_COMPOSITION",
            "m4:ime-proxy:beforeinput:cancellation-pending",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, beforeinput)

        input_handler = section(
            host,
            "  #handleM4ImeProxyInput(event)",
            "  #handleM4ImeProxyCompositionEnd(event)",
        )
        for marker in (
            "#validateM4ImeProxyEvent(record)",
            "if (this.#imeProxyTerminalCancellationPending)",
            "(data !== null && data !== \"\")",
            "this.#imeProxyPendingTransaction !== null",
            "this.#imeProxyNativeTerminalAction !== null",
            'this.#imeProxy.value !== ""',
            "selection.start !== 0 || selection.end !== 0",
            "CANCELLATION_INPUT_TRANSACTION_MISMATCH",
            "M4_IME_TEXT_ACTION.clearComposition",
            "composition.sessionId,",
            "record.sequence,",
            '"",',
            "{start: 0, end: 0}",
            "this.#imeProxyExpectedTerminalAction =",
            "this.#imeProxyCompositionActive = false;",
            "this.#imeProxyTerminalCancellationPending = false;",
            "m4:ime-proxy:input:native-clear-queued",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, input_handler)
        self.assertNotIn("#validateM4ImeProxyTerminal", input_handler)

        composition_end = section(
            host,
            "  #handleM4ImeProxyCompositionEnd(event)",
            "  #disableM4ImeProxyInput",
        )
        clear_observation = composition_end.split("    const composition =", 1)[0]
        for marker in (
            "this.#imeProxyExpectedTerminalAction ===",
            "M4_IME_TEXT_ACTION.clearComposition",
            'data === ""',
            "this.#imeProxyExpectedTerminalAction = null;",
            "record.terminalObservedAfterClear = true;",
            "m4:ime-proxy:compositionend:clear-observed",
            "return;",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, clear_observation)
        self.assertNotIn("this.#queueM4ImeProxyTextInput(", clear_observation)

        # No fixture-only or generic untrusted source can enter this path.
        cancellation_handlers = update + beforeinput + input_handler
        for forbidden in (
            "allowDerivedTerminal",
            "testOnly",
            "fixture",
            "token",
            "dispatchEvent",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, cancellation_handlers)

    def test_c_abi_copies_validated_text_then_posts_to_the_ozone_boundary(
        self,
    ) -> None:
        api = source("content/shell/browser/wasm_host_api.cc")

        copy_record = section(
            api,
            "bool CopyM4TextInputRecord(",
            "class WasmHostObserver",
        )
        for marker in (
            "ParseWasmTextInputAction(action)",
            "kMaximumM4TextInputUtf8Bytes",
            "kMaximumM4TextInputUtf16Units",
            "emscripten_get_heap_size()",
            "base::IsStringUTF8AllowingNoncharacters(utf8)",
            "base::UTF8ToUTF16(utf8)",
            "WasmTextInputAction::kSetComposition",
            "WasmTextInputAction::kConfirmComposition",
            "WasmTextInputAction::kClearComposition",
            "gfx::Range(start, end)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, copy_record)

        dispatch = section(
            api,
            "void DispatchM4TextInputOnUiThread(ui::WasmTextInputRecord record)",
            "void LoadUrlOnUiThread",
        )
        for marker in (
            "DCHECK_CURRENTLY_ON(BrowserThread::UI);",
            "aura::WindowTreeHostPlatform::GetHostForWindow(shell->window())",
            "ui::DispatchWasmTextInput(host->GetAcceleratedWidget(),",
            "ReportTextInputDelivery(record, accepted);",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, dispatch)
        for forbidden in (
            "GetInputInjector",
            "InjectKeyEvent",
            "RenderWidgetHost",
            "WebInputEvent",
            "ForwardInputEvent",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, dispatch)

        export = section(
            api,
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_text_input(",
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_deactivate()",
        )
        for marker in (
            "const uint8_t* text_utf8",
            "CopyM4TextInputRecord(",
            "PostHostCommand(base::BindOnce(",
            "DispatchM4TextInputOnUiThread",
            "std::move(record)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, export)

    def test_delivery_acknowledgement_matches_the_host_queue(self) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        bridge = source("ui/ozone/platform/wasm/wasm_host_bridge.js")

        for marker in (
            "reportOzoneTextInputDelivery(report)",
            'deliverBridgeReport("_reportOzoneTextInputDelivery", [report]);',
            "_reportOzoneTextInputDelivery(value)",
            "#imeProxyNativeRequests",
            "nativeSetDeliveryCount",
            "nativeConfirmDeliveryCount",
            "nativeClearDeliveryCount",
            "nativePendingDelivery",
            "NATIVE_TEXT_INPUT_DELIVERY_REJECTED",
            "ozone:text-input-delivery:${actionName}:",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, host)
        delivery = section(
            host,
            "  _reportOzoneTextInputDelivery(value)",
            "  _reportProcessExit(value)",
        )
        for marker in (
            "const request = this.#imeProxyNativeRequests.find(",
            "request.deliveryAccepted !== null",
            "request.deliveryAccepted = report.accepted;",
            "this.#imeProxyNativeTerminalAction?.sequence === request.sequence",
            "this.#imeProxyNativeComposition = null;",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, delivery)

        for marker in (
            "chromium_wasm_report_ozone_text_input_delivery__proxy: 'sync'",
            "chromium_wasm_report_ozone_text_input_delivery: (",
            "Number.isSafeInteger(action)",
            "bridge.reportOzoneTextInputDelivery({",
            "accepted: accepted === 1",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, bridge)

    def test_native_text_input_loss_does_not_repeat_native_clear(self) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        input_method = source("ui/ozone/platform/wasm/wasm_input_method.cc")

        clear_state = section(
            host,
            "  #clearM4ImeProxyState(reason, {queueNativeClear = true} = {})",
            "  #rejectM4ImeProxyRecord(record, reason)",
        )
        self.assertIn("if (queueNativeClear) {", clear_state)
        self.assertIn("this.#queueM4ImeProxyClear(reason);", clear_state)

        text_input_state = section(
            host,
            "  _reportOzoneTextInputState(value)",
            "  _reportOzoneTextInputDelivery(value)",
        )
        for marker in (
            "WasmInputMethod clears its active composition",
            'this.#clearM4ImeProxyState("native-text-input-lost", {',
            "queueNativeClear: false,",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text_input_state)

        type_change = section(
            input_method,
            "void WasmInputMethod::OnTextInputTypeChanged(TextInputClient* client)",
            "void WasmInputMethod::CancelComposition",
        )
        self.assertLess(
            type_change.index("ClearActiveComposition(focused_client);"),
            type_change.index("ReportTextInputState();"),
        )

    def test_proxy_focus_waits_for_native_editable_input_method_state(
        self,
    ) -> None:
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
            "std::make_unique<WasmInputMethod>(ime_key_event_dispatcher, widget,",
            ozone_platform,
        )

    def test_ozone_routes_to_the_focused_text_input_client(self) -> None:
        input_method_header = source(
            "ui/ozone/platform/wasm/wasm_input_method.h"
        )
        input_method = source("ui/ozone/platform/wasm/wasm_input_method.cc")
        ozone_platform = source("ui/ozone/platform/wasm/ozone_platform_wasm.cc")
        window_manager_header = source(
            "ui/ozone/platform/wasm/wasm_window_manager.h"
        )
        window_manager = source(
            "ui/ozone/platform/wasm/wasm_window_manager.cc"
        )
        content_shell_build = source("content/shell/BUILD.gn")
        ozone_build = source("ui/ozone/platform/wasm/BUILD.gn")

        for marker in (
            "enum class WasmTextInputAction : int",
            "kSetComposition = 1",
            "kConfirmComposition = 2",
            "kClearComposition = 3",
            "struct WasmTextInputRecord",
            "std::u16string text;",
            "gfx::Range selection;",
            "bool DispatchTextInput(const WasmTextInputRecord& record);",
            "void CancelHostComposition();",
            "bool DispatchWasmTextInput(gfx::AcceleratedWidget widget,",
            "void CancelWasmTextInputForWidget(gfx::AcceleratedWidget widget);",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, input_method_header)

        dispatch = section(
            input_method,
            "bool WasmInputMethod::DispatchTextInput(const WasmTextInputRecord& record)",
            "void WasmInputMethod::CancelHostComposition()",
        )
        for marker in (
            "record.sequence <= last_sequence_",
            "window_manager_->IsKeyboardFocusedWidget(widget_)",
            "CanDispatchTextInput(client)",
            "active_composition_->session_id != record.session_id",
            "active_composition_->client.get() != client",
            "client->AsWeakPtr()",
            "client->SetCompositionText(composition);",
            "client->ConfirmCompositionText(/*keep_selection=*/false);",
            "client->ClearCompositionText();",
            "active_composition_.reset();",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, dispatch)
        for forbidden in (
            "SystemInputInjector",
            "InjectKeyEvent",
            "RenderWidgetHost",
            "WebInputEvent",
            "ForwardInputEvent",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, dispatch)

        # M6 adds its separately tagged committed-text action, but it must not
        # turn any of M4's composition actions into an InsertText shortcut.
        m4_composition_dispatch = dispatch.split(
            "case WasmTextInputAction::kInsertText:", 1
        )[0]
        self.assertNotIn("client->InsertText", m4_composition_dispatch)

        for marker in (
            "GetInputMethods()",
            "base::NoDestructor<InputMethodMap>",
            "GetInputMethodThreadChecker()",
            "DispatchWasmTextInput(gfx::AcceleratedWidget widget,",
            "CancelWasmTextInputForWidget(gfx::AcceleratedWidget widget)",
            "CancelComposition(const TextInputClient* client)",
            "OnWillChangeFocusedClient",
            "ClearActiveComposition(focused_before);",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, input_method)

        self.assertIn(
            "std::make_unique<WasmInputMethod>(ime_key_event_dispatcher, widget,",
            ozone_platform,
        )
        self.assertIn(
            "bool IsKeyboardFocusedWidget(gfx::AcceleratedWidget widget);",
            window_manager_header,
        )
        keyboard_focused = section(
            window_manager,
            "bool WasmWindowManager::IsKeyboardFocusedWidget(",
            "void WasmWindowManager::SetPointerCapture",
        )
        for marker in (
            "GetKeyboardFocusedWindow()",
            "window->widget() == widget",
            "window->IsVisible()",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, keyboard_focused)
        self.assertIn('"//ui/ozone/platform/wasm:wasm"', content_shell_build)
        self.assertIn('"//content/shell:*"', ozone_build)

    def test_smoke_proves_inner_blink_composition_and_terminal(self) -> None:
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
            'const expectedText = "\\u{1f642}";',
            "textInputTrace",
            "trusted: event.isTrusted === true",
            "valueMatchesExpected",
            "INNER EDITOR COMPOSING",
            "INNER EDITOR COMMITTED",
            "target.selectionStart",
            "target.selectionEnd",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, fixture)
        self.assertNotRegex(fixture, r"target\.value\s*(?<![=])=(?!=)")
        for forbidden in (
            ".focus(",
            "dispatchEvent(",
            "execCommand(",
            "Input.insertText",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, fixture)

        preedit = section(
            cdp,
            "    def dispatch_ime_preedit(self) -> None:",
            "\n\n    def dispatch_ime_commit(self) -> None:",
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
                self.assertIn(marker, preedit)
        self.assertNotIn('"Input.insertText"', preedit)

        commit = section(
            cdp,
            "    def dispatch_ime_commit(self) -> None:",
            "\n\n    def dispatch_ime_cancel(self) -> None:",
        )
        self.assertIn('self.call("Input.insertText", {"text": "🙂"})', commit)

        cancel = section(
            cdp,
            "    def dispatch_ime_cancel(self) -> None:",
            "\n\ndef wait_for_page_client",
        )
        for marker in (
            '"Input.imeSetComposition"',
            '"text": ""',
            '"selectionStart": 0',
            '"selectionEnd": 0',
            '"replacementStart": 0',
            '"replacementEnd": 0',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, cancel)

        for marker in (
            '"ime-bridge",',
            "M4_IME_BRIDGE_CASE",
            "m4_ime_bridge_smoke_url(",
            "awaiting-dom-ime-bridge-activation",
            "awaiting-dom-ime-preedit",
            "--ime-terminal",
            "args.ime_terminal",
            "awaiting-dom-ime-terminal",
            "client.dispatch_ime_preedit()",
            "client.dispatch_ime_commit()",
            "client.dispatch_ime_cancel()",
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
            "nativeSetDeliveryCount",
            "nativeConfirmDeliveryCount",
            "nativeClearDeliveryCount",
            "terminal_mode",
            "terminal_native_sequence = 7 if is_cancellation else 8",
            "INNER EDITOR COMMITTED",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, server)

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
            "terminalMode",
            "awaiting-dom-ime-terminal",
            "INNER EDITOR COMPOSING",
            "INNER EDITOR COMMITTED",
            "INNER EDITOR COMPOSITION ENDED",
            "nativeSetDeliveryCount",
            "nativeConfirmDeliveryCount",
            "nativeClearDeliveryCount",
            "nativePendingDelivery",
            "const terminalNativeSequence = isCancellation ? 7 : 8;",
            "proxy?.lastNativeDelivery?.sequence === terminalNativeSequence",
            "trace.slice(0, -1).every((record) => record?.trusted === true)",
            "trace.at(-1)?.trusted !== false",
            "derivedTerminalCount",
            "observedClearTerminalCount",
            "native-composition-cancelled",
            "valueMatchesExpected",
            "nativeDelivery",
            "innerBlinkComposition",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, smoke)
        for obsolete_marker in (
            "preedit-captured-no-native-dispatch",
            "innerBlinkUnchanged",
            "preRouteOnly",
        ):
            with self.subTest(obsolete_marker=obsolete_marker):
                self.assertNotIn(obsolete_marker, smoke)
        for forbidden in (
            "chromium_wasm_host_ime_transaction",
            "chromium_wasm_host_click",
            "injectInput(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, smoke)


if __name__ == "__main__":
    unittest.main()
