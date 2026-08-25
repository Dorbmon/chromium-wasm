#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the bounded volatile Wasm page file picker."""

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M7WasmBrowserFilePickerContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.picker = source("chrome/browser/wasm/wasm_browser_file_picker.cc")
        self.picker_header = source(
            "chrome/browser/wasm/wasm_browser_file_picker.h"
        )
        self.browser = source("chrome/browser/wasm/wasm_browser.cc")
        self.build = source("chrome/browser/wasm/BUILD.gn")
        self.bridge = source("ui/ozone/platform/wasm/wasm_host_bridge.js")
        self.adapter = source("tools/wasm/host/chrome_wasm_file_picker.js")
        self.normal_host = source("tools/wasm/host/chrome_wasm_host.js")
        self.normal_runner = source("tools/wasm/run_chrome_wasm_smoke.py")
        self.release_host = source("tools/wasm/host/release_host.js")
        self.package = source("tools/wasm/package.py")

    def test_native_scope_is_one_regular_open_file_into_a_bounded_volatile_vault(self) -> None:
        for marker in (
            'kVolatileFilePickerRoot[] = "/tmp/chromium-wasm-file-picker"',
            "kMaximumFilePickerBytes = 8 * 1024 * 1024",
            "kMaximumVolatileFilePickerVaultBytes = 16 * 1024 * 1024",
            "kFilePickerChunkBytes = 64 * 1024",
            "params.mode != blink::mojom::FileChooserParams::Mode::kOpen",
            "params.open_writable || params.use_media_capture",
            "blink::mojom::FileChooserParams::Mode::kOpen",
            "base::WriteFile(imported_path, base::span(contents))",
            "DeleteVolatileFilesFor",
            "volatile_file_bytes_",
            "!IsContentsActive(pending_request_->web_contents)",
            "std::move(callback).Run(false)",
            "CanDragEnter",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.picker)

        for forbidden in (
            '"/profile',
            "OPFS",
            "FileSystemAccess",
            "showOpenFilePicker",
            "DownloadManager",
            "DragDrop",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.picker)

    def test_browser_owns_delegate_for_model_tabs_and_revokes_it_before_removal(self) -> None:
        for marker in (
            "std::make_unique<chrome::WasmBrowserFilePicker>",
            "case TabStripModelChange::kInserted",
            "file_picker_->AttachToWebContents(contents.contents)",
            "case TabStripModelChange::kReplaced",
            "file_picker_->DetachFromWebContents(replacement->old_contents)",
            "file_picker_->DetachFromWebContents(tab->GetContents())",
            "file_picker_->OnActiveWebContentsChanged()",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.browser)
        self.assertIn(
            "tab_strip_model_->GetActiveWebContents() == contents", self.picker
        )
        self.assertIn('"wasm_browser_file_picker.cc"', self.build)
        self.assertIn('"//ui/ozone/platform/wasm:wasm"', self.build)

    def test_cross_thread_transfer_uses_a_copy_and_safe_weak_pointer_check(self) -> None:
        for marker in (
            "IsValidHeapRange",
            "std::string copied_name",
            "active_request_->contents.insert",
            "active_request_->owner.MaybeValid()",
            "Phase::kCompletionPosted",
            "active_request_->phase = Phase::kAwaitingCancel",
            "active_request_->phase = Phase::kCancellationPosted",
            "base::BindOnce(&WasmBrowserFilePicker::OnHostFilePickerCompleted",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.picker)
        self.assertNotIn("!active_request_->owner ||", self.picker)

    def test_opaque_bridge_never_transfers_outer_paths_or_file_data(self) -> None:
        for marker in (
            "chromium_wasm_request_ozone_browser_file_picker",
            "requestOzoneBrowserFilePicker",
            "chromium_wasm_report_ozone_browser_file_picker_delivery",
            "reportOzoneBrowserFilePickerDelivery",
            "requestId > 0x7fffffff",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.bridge)
        self.assertNotIn("fileName", self.bridge)
        self.assertNotIn("filePath", self.bridge)
        self.assertNotIn("fileBytes", self.bridge)

    def test_trusted_dom_adapter_requires_activation_and_copies_bounded_chunks(self) -> None:
        for marker in (
            "navigator.userActivation?.isActive !== true",
            "HTMLInputElement.prototype.showPicker",
            "input.showPicker()",
            "queueMicrotask",
            "file-selection-dispatch-failed",
            "MAX_FILE_BYTES = 8 * 1024 * 1024",
            "FILE_CHUNK_BYTES = 64 * 1024",
            "chromium_wasm_browser_host_file_picker_begin",
            "chromium_wasm_browser_host_file_picker_chunk",
            "chromium_wasm_browser_host_file_picker_complete",
            "chromium_wasm_browser_host_file_picker_cancel",
            "heap.set(bytes, pointer)",
            "bytes.fill(0)",
            "input.value = \"\"",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.adapter)
        for forbidden in (
            "showOpenFilePicker",
            "input.click();",
            "navigator.storage",
            "fetch(",
            "webkitdirectory",
            "multiple = true",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.adapter)

    def test_normal_and_pre_release_hosts_ship_the_same_adapter_without_new_gate_claims(self) -> None:
        for text in (self.normal_host, self.release_host):
            self.assertIn("ChromiumWasmTrustedFilePicker", text)
            self.assertIn("requestOzoneBrowserFilePicker", text)
            self.assertIn("reportOzoneBrowserFilePickerDelivery", text)
        self.assertIn("chrome_wasm_file_picker.js", self.normal_runner)
        self.assertIn("file_picker_js_bytes", self.normal_runner)
        self.assertIn("chromium-wasm-file-picker.js", self.package)
        self.assertIn("pre_m7_m8_not_releasable", self.release_host)


if __name__ == "__main__":
    unittest.main()
