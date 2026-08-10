#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Static contracts for the M7 trusted-DOM volatile clipboard import."""

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


class M7WasmBrowserHostClipboardContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.clipboard_header = source(
            "chrome/browser/wasm/wasm_browser_host_clipboard.h"
        )
        self.clipboard = source(
            "chrome/browser/wasm/wasm_browser_host_clipboard.cc"
        )
        self.clipboard_smoke = source(
            "chrome/browser/wasm/wasm_browser_host_clipboard_smoke.cc"
        )
        self.input_method_header = source(
            "ui/ozone/platform/wasm/wasm_input_method.h"
        )
        self.input_method = source("ui/ozone/platform/wasm/wasm_input_method.cc")
        self.host_bridge = source("ui/ozone/platform/wasm/wasm_host_bridge.js")
        self.adapter = source("tools/wasm/host/chrome_wasm_clipboard_input.js")
        self.normal_host = source("tools/wasm/host/chrome_wasm_host.js")
        self.lifecycle = source("chrome/browser/wasm/wasm_browser_lifecycle.cc")
        self.main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        self.build = source("chrome/browser/wasm/BUILD.gn")
        self.normal_runner = source("tools/wasm/run_chrome_wasm_smoke.py")

    def test_scope_is_one_way_volatile_plain_text_not_a_platform_clipboard(self) -> None:
        for marker in (
            "kMaximumHostClipboardUtf8Bytes = 192 * 1024",
            "kMaximumHostClipboardUtf16Units = 64 * 1024",
            "base::IsStringUTF8AllowingNoncharacters",
            "emscripten_get_heap_size()",
            "std::u16string converted",
            "chromium_wasm_browser_host_clipboard_paste",
            "chromium_wasm_browser_host_clipboard_cancel",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.clipboard)

        for forbidden in (
            "ClipboardNonBacked::",
            "Clipboard::Create",
            "PlatformClipboard",
            "ClipboardOzone",
            "views::Textfield",
            "SetText(",
            "NavigationController",
            "LoadURL",
            "OpenURL",
            "DispatchWasmTextInputWithFocusToken",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.clipboard)
        for forbidden in (
            "navigator.clipboard.",
            "execCommand(",
            "ClipboardEvent(",
            "Input.insertText",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.adapter)

    def test_commit_and_native_chord_use_the_existing_ui_thread_clipboard_and_ozone(self) -> None:
        dispatch = section(
            self.clipboard,
            "  void DispatchPasteOnUiThread()",
            "  mutable base::Lock lock_;",
        )
        for marker in (
            "DCHECK_CURRENTLY_ON(content::BrowserThread::UI)",
            "ui::ScopedClipboardWriter writer(ui::ClipboardBuffer::kCopyPaste)",
            "writer.WriteText(pending->text)",
            "ui::IsWasmTextInputFocusTokenCurrent",
            "ui::DomCode::CONTROL_LEFT",
            "ui::DomCode::US_V",
            "/*down=*/true",
            "/*down=*/false",
            "/*suppress_auto_repeat=*/true",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, dispatch)
        self.assertLess(
            dispatch.index("BeginPasteImportAndChord(admission)"),
            dispatch.index("writer.WriteText(pending->text)"),
        )
        self.assertEqual(dispatch.count("InjectKeyEvent("), 4)
        self.assertLess(
            dispatch.index("ui::DomCode::CONTROL_LEFT"),
            dispatch.index("ui::DomCode::US_V"),
        )
        self.assertIn("//ui/base/clipboard", self.build)
        self.assertIn('"//ui/ozone"', self.build)

    def test_focus_token_has_a_pure_query_not_direct_text_insertion(self) -> None:
        for marker in (
            "bool IsWasmTextInputFocusTokenCurrent(gfx::AcceleratedWidget widget,",
            "Returns whether |focus_token| still names the same editable focused client.",
            "return IsCurrentInputMethodFocusToken(widget, focus_token);",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.input_method_header + self.input_method)
        self.assertIn(
            "ui::CaptureWasmTextInputFocusToken(target_widget_)", self.clipboard
        )
        self.assertIn("ui::IsWasmTextInputFocusTokenCurrent", self.clipboard)

    def test_single_monotonic_admission_and_linearizable_cancellation_boundary(self) -> None:
        reservation = section(
            self.clipboard,
            "  std::optional<PasteAdmission> ReservePasteAdmission",
            "  void CancelPasteAdmission",
        )
        for marker in (
            "outstanding_paste_",
            "request_id <= last_request_id_",
            "active_request_id_ = request_id",
            "last_request_id_ = request_id",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, reservation)

        cancel = section(
            self.clipboard,
            "  bool CancelPendingPaste(int request_id)",
            " private:",
        )
        for marker in (
            "if (paste_import_started_)",
            "return false;",
            "active_paste_cancelled_ = true;",
            "TakeQueuedPasteLocked()",
            "ReportWasmBrowserHostClipboardPasteDelivery",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, cancel)

        begin = section(
            self.clipboard,
            "  bool BeginPasteImportAndChord(const PasteAdmission& admission)",
            "  void DispatchPasteOnUiThread()",
        )
        self.assertIn("base::AutoLock lock(lock_);", begin)
        self.assertIn("active_paste_cancelled_ || paste_import_started_", begin)
        self.assertIn("paste_import_started_ = true;", begin)
        self.assertIn("exact cancellation boundary", begin)
        dispatch = section(
            self.clipboard,
            "  void DispatchPasteOnUiThread()",
            "  mutable base::Lock lock_;",
        )
        self.assertLess(
            dispatch.index("BeginPasteImportAndChord(admission)"),
            dispatch.index("input_injector_->InjectKeyEvent"),
        )

    def test_distinct_terminal_delivery_is_authenticated_and_never_synchronously_reenters(self) -> None:
        delivery_import = section(
            self.host_bridge,
            "chromium_wasm_report_ozone_browser_clipboard_paste_delivery__deps",
            "chromium_wasm_report_navigation__deps",
        )
        for marker in (
            "requestId < 1",
            "accepted !== 0 && accepted !== 1",
            "reportOzoneBrowserClipboardPasteDelivery",
            "accepted: accepted === 1",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, delivery_import)

        terminal = section(
            self.adapter,
            "  handleOzoneBrowserClipboardPasteDelivery(report) {",
            "  snapshot()",
        )
        for marker in (
            "this.#pending = null;",
            "this.#clearProxyText();",
            "setTimeout(() => {",
            "this.#onNativeDelivery",
            "Never\n    // reenter a Wasm export here",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, terminal)
        self.assertLess(
            terminal.index("this.#pending = null;"), terminal.index("setTimeout(() => {"),
        )
        self.assertNotIn("#callHostPasteBytes(", terminal)
        self.assertNotIn("#callHostCancel(", terminal)

    def test_ozone_state_import_tombstones_sync_and_defers_native_cancel(self) -> None:
        state_handler = section(
            self.adapter,
            "  handleOzoneTextInputState(report) {",
            "  handleOzoneBrowserClipboardPasteDelivery(report)",
        )
        self.assertIn('"ozone-text-input-state-transition"', state_handler)
        self.assertIn("/*deferNativeCancel=*/true", state_handler)
        self.assertNotIn("#callHostCancel(", state_handler)

        clear_pending = section(
            self.adapter,
            "  #clearPending(reason, deferNativeCancel = false) {",
            "  #callHostPasteBytes(bytes, requestId) {",
        )
        for marker in (
            "this.#pending = null;",
            "this.#tombstoneRequest(pending.requestId);",
            "if (deferNativeCancel)",
            "setTimeout(() => {",
            "cleanup.canceled = this.#callHostCancel(pending.requestId);",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, clear_pending)
        self.assertLess(
            clear_pending.index("this.#pending = null;"),
            clear_pending.index("setTimeout(() => {"),
        )

    def test_trusted_dom_adapter_copies_before_preventing_and_tracks_only_metadata(self) -> None:
        paste_handler = section(
            self.adapter,
            "  #handlePaste(event) {",
            "}\n\nexport const chromeWasmTrustedClipboardInputContract",
        )
        for marker in (
            "event.isTrusted === true",
            "event.cancelable === true",
            "document.activeElement === this.#proxy",
            'hasPlainText(event.clipboardData)',
            'event.clipboardData.getData("text/plain")',
            "isWellFormedUtf16(text)",
            "this.#pending = {",
            "event.preventDefault();",
            "this.#callHostPasteBytes(bytes, requestId)",
            "delete record.event;",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, paste_handler)
        self.assertLess(
            paste_handler.index('event.clipboardData.getData("text/plain")'),
            paste_handler.index("event.preventDefault();"),
        )
        self.assertLess(
            paste_handler.index("this.#pending = {"),
            paste_handler.index("this.#callHostPasteBytes(bytes, requestId)"),
        )
        self.assertIn("bytes.fill(0);", self.adapter)
        self.assertIn("module._free(pointer)", self.adapter)
        self.assertIn("proxyTextEmpty: this.#proxy.value === \"\"", self.adapter)
        self.assertNotIn("textareaValue: this.#proxy.value", self.adapter)

    def test_lifecycle_binds_then_clears_before_browser_and_ozone_teardown(self) -> None:
        for marker in (
            "CHECK(SetWasmBrowserHostClipboardTarget(host->GetAcceleratedWidget()))",
            "ClearWasmBrowserHostClipboardTarget();\n  ClearWasmBrowserHostTextTarget();",
            "ClearWasmBrowserHostClipboardSmokeVerificationForTesting();",
            "CHROMIUM_WASM_M7_HOST_CLIPBOARD:READY",
            "CHROMIUM_WASM_M7_HOST_CLIPBOARD:PASTED",
            "CHROMIUM_WASM_M7_HOST_CLIPBOARD:PASS",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.lifecycle)
        shutdown = section(
            self.main_parts,
            "void WasmBrowserMainParts::PostMainMessageLoopRun()",
            "void WasmBrowserMainParts::PostDestroyThreads()",
        )
        self.assertLess(
            shutdown.index("chrome::ShutdownWasmBrowserHostClipboard();"),
            shutdown.index("ui::OzonePlatform::GetInstance()->PostMainMessageLoopRun();"),
        )
        self.assertIn("wasm-browser-host-clipboard-smoke", self.main_parts)
        self.assertIn('source_set("wasm_browser_host_clipboard")', self.build)
        self.assertIn('source_set("wasm_browser_host_clipboard_smoke")', self.build)

    def test_normal_host_serves_the_new_production_adapter_with_javascript_mime_type(self) -> None:
        self.assertIn(
            'import {ChromiumWasmTrustedClipboardInput} from "./chrome_wasm_clipboard_input.js";',
            self.normal_host,
        )
        self.assertIn("new ChromiumWasmTrustedClipboardInput", self.normal_host)
        self.assertIn("chrome_wasm_clipboard_input.js", self.normal_runner)
        self.assertIn("clipboard_input_js_bytes", self.normal_runner)
        self.assertIn('"text/javascript; charset=utf-8"', self.normal_runner)


if __name__ == "__main__":
    unittest.main()
