#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Static contracts for Chrome's bounded committed-text Ozone bridge."""

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


class M6BrowserHostTextContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.input_method_header = source(
            "ui/ozone/platform/wasm/wasm_input_method.h"
        )
        self.input_method = source("ui/ozone/platform/wasm/wasm_input_method.cc")
        self.host_text = source(
            "chrome/browser/wasm/wasm_browser_host_text.cc"
        )
        self.host_bridge = source("ui/ozone/platform/wasm/wasm_host_bridge.js")
        self.lifecycle = source("chrome/browser/wasm/wasm_browser_lifecycle.cc")
        self.content_shell_api = source("content/shell/browser/wasm_host_api.cc")

    def test_action_four_is_a_narrow_non_composing_insert_text_transaction(self) -> None:
        for marker in (
            "kInsertText = 4",
            "struct WasmTextInputFocusToken",
            "CaptureWasmTextInputFocusToken",
            "DispatchWasmTextInputWithFocusToken",
            "record.session_id != 0",
            "!record.selection.is_empty()",
            "!CanInsertText(client)",
            "active_composition_",
            "client->InsertText(",
            "kMoveCursorAfterText",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.input_method_header + self.input_method)

        dispatch = section(
            self.input_method,
            "bool WasmInputMethod::DispatchTextInput(const WasmTextInputRecord& record)",
            "void WasmInputMethod::CancelHostComposition()",
        )
        insert_text = section(
            dispatch,
            "case WasmTextInputAction::kInsertText:",
            "  }\n  NOTREACHED();",
        )
        for forbidden in (
            "SetCompositionText",
            "ConfirmCompositionText",
            "ClearCompositionText",
            "SystemInputInjector",
            "InjectKeyEvent",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, insert_text)

    def test_ozone_focus_epoch_is_captured_and_revalidated_before_insert(self) -> None:
        for marker in (
            "struct WasmTextInputFocusState",
            "base::Lock& GetInputMethodFocusStatesLock()",
            "RegisterInputMethodFocusState(widget_);",
            "UnregisterInputMethodFocusState(widget_);",
            "AdvanceInputMethodFocusState(widget_, /*has_editable_client=*/false);",
            "AdvanceInputMethodFocusState(widget_, CanInsertText(GetTextInputClient()));",
            "AdvanceInputMethodFocusState(widget_, CanInsertText(focused_client));",
            "IsCurrentInputMethodFocusToken(widget, focus_token)",
            "record.action != WasmTextInputAction::kInsertText",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.input_method)

        reservation = section(
            self.host_text,
            "  std::optional<TextAdmission> ReserveTextAdmission",
            "  void CancelTextAdmission",
        )
        for marker in (
            "ui::CaptureWasmTextInputFocusToken(target_widget_)",
            "++pending_text_records_",
            "pending_text_utf8_bytes_ += text_utf8_bytes",
            "*focus_token",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, reservation)

        bridge_post = section(
            self.host_text,
            "  bool PostReservedText(std::u16string text, const TextAdmission& admission)",
            " private:",
        )
        for marker in (
            "target_widget_ != admission.target_widget",
            "generation_ != admission.generation",
            "target_generation_ != admission.target_generation",
            "pending_text_queue_.push_back",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, bridge_post)

        dispatch = section(
            self.host_text,
            "  void DispatchNextTextOnUiThread()",
            "  mutable base::Lock lock_;",
        )
        self.assertIn("ui::DispatchWasmTextInputWithFocusToken", dispatch)
        self.assertIn(
            "ReportWasmBrowserHostTextDelivery(pending->record, accepted);", dispatch
        )
        self.assertNotIn("static_cast<void>(ui::DispatchWasmTextInput", dispatch)

    def test_copying_abi_cannot_select_focus_or_hide_native_rejection(self) -> None:
        export = section(
            self.host_text,
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_text(",
            "}  // extern \"C\"",
        )
        for marker in (
            "const uint8_t* text_utf8",
            "int text_utf8_bytes",
            "ValidateWasmBrowserHostTextInput",
            "state.ReserveTextAdmission(text_bytes)",
            "CopyWasmBrowserHostText",
            "state.PostReservedText(std::move(text), *admission)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, export)
        self.assertLess(
            export.index("state.ReserveTextAdmission(text_bytes)"),
            export.index("CopyWasmBrowserHostText"),
        )
        for forbidden in (
            "Textfield",
            "SetText",
            "NavigationController",
            "LoadURL",
            "GetTextInputClient",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.host_text)

        delivery = section(
            self.host_text,
            "void ReportWasmBrowserHostTextDelivery(",
            "class WasmBrowserHostTextState",
        )
        for marker in (
            "chromium_wasm_report_ozone_browser_text_input_delivery",
            "record.session_id",
            "record.sequence",
            "accepted ? 1 : 0",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, delivery)

    def test_bridge_bounds_fifo_native_text_reservations_per_lifetime(self) -> None:
        for marker in (
            "kMaximumPendingHostTextRecords = 16",
            "kMaximumPendingHostTextUtf8Bytes = 192 * 1024",
            "pending_text_records_ >= kMaximumPendingHostTextRecords",
            "kMaximumPendingHostTextUtf8Bytes - pending_text_utf8_bytes_",
            "++pending_text_records_;",
            "pending_text_utf8_bytes_ += text_utf8_bytes;",
            "std::deque<PendingTextRecord> pending_text_queue_",
            "pending_text_queue_.push_back",
            "bool MaybeScheduleTextDispatchLocked()",
            "void DispatchNextTextOnUiThread()",
            "DrainQueuedTextRecordsLocked",
            "minimum_committed_records_before_dispatch_ = 2",
            "permanently_shutdown_",
            "ever_initialized_",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.host_text)

        dispatch = section(
            self.host_text,
            "  void DispatchNextTextOnUiThread()",
            "  mutable base::Lock lock_;",
        )
        self.assertIn(
            "ReportWasmBrowserHostTextDelivery(pending->record, accepted);", dispatch
        )
        self.assertIn("ReleaseTextReservationLocked(", dispatch)
        self.assertLess(
            dispatch.index("ReportWasmBrowserHostTextDelivery(pending->record, accepted);"),
            dispatch.index("ReleaseTextReservationLocked("),
        )
        self.assertLess(
            dispatch.index("ReleaseTextReservationLocked("),
            dispatch.index("if (!MaybeScheduleTextDispatchLocked())"),
        )
        self.assertIn("generation != generation_", self.host_text)
        self.assertGreaterEqual(self.host_text.count("pending_text_records_ = 0;"), 2)
        self.assertGreaterEqual(self.host_text.count("pending_text_utf8_bytes_ = 0;"), 2)
        self.assertIn("CHECK_LE(text_utf8_bytes, pending_text_utf8_bytes_);", self.host_text)
        self.assertNotIn("next_sequence_ = 0", self.host_text)
        self.assertIn("ReportWasmBrowserHostTextDelivery(pending.record, /*accepted=*/false);", self.host_text)

    def test_browser_delivery_report_is_separate_from_m4_and_exactly_keyed(self) -> None:
        browser_delivery = section(
            self.host_bridge,
            "chromium_wasm_report_ozone_browser_text_input_delivery__deps",
            "chromium_wasm_report_navigation__deps",
        )
        for marker in (
            "action !== 4",
            "sessionId !== 0",
            "sequence < 1",
            "reportOzoneBrowserTextInputDelivery",
            "accepted: accepted === 1",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, browser_delivery)

        m4_delivery = section(
            self.host_bridge,
            "chromium_wasm_report_ozone_text_input_delivery__deps",
            "// Chrome's address-field committed-text ABI",
        )
        self.assertIn("action > 3", m4_delivery)
        self.assertIn("sessionId < 1", m4_delivery)
        self.assertNotIn("reportOzoneBrowserTextInputDelivery", m4_delivery)

    def test_content_shell_explicitly_rejects_the_chrome_only_action(self) -> None:
        parser = section(
            self.content_shell_api,
            "std::optional<ui::WasmTextInputAction> ParseWasmTextInputAction",
            "bool CopyM4TextInputRecord",
        )
        self.assertIn("case static_cast<int>(ui::WasmTextInputAction::kInsertText):", parser)
        self.assertIn("return std::nullopt;", parser)
        validation = section(
            self.content_shell_api,
            "  switch (*parsed_action) {",
            "  *record = {*parsed_action",
        )
        self.assertIn("case ui::WasmTextInputAction::kInsertText:", validation)
        self.assertIn("return false;", validation)

    def test_lifecycle_drops_the_web_contents_raw_pointer_before_destroying_browser(self) -> None:
        for marker in (
            "host_text_navigation_observer_.reset();\n  host_text_contents_ = nullptr;",
            "CHECK(!host_text_contents_);",
            "host_text_contents_ = browser_view.GetActiveWebContents();",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.lifecycle)

    def test_smoke_arms_native_two_record_barrier_before_ready(self) -> None:
        for marker in (
            "ArmWasmBrowserHostTextSmokeTwoRecordBarrier()",
            "CHROMIUM_WASM_M6_HOST_TEXT:BURST_ARMED",
            "kHostTextSmokeBurstArmedMarker",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.lifecycle + self.host_text)


if __name__ == "__main__":
    unittest.main()
