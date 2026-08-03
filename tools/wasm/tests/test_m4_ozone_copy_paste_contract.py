#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Static contracts for bounded M4 Ctrl+C/Ctrl+V through Wasm Ozone."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


class M4OzoneCopyPasteContractTest(unittest.TestCase):
    def test_c_abi_keeps_control_copy_paste_as_explicit_physical_keys(
        self,
    ) -> None:
        api = source("content/shell/browser/wasm_host_api.cc")
        whitelist = section(
            api,
            "bool IsSupportedM4DomCode(ui::DomCode dom_code)",
            "enum class DomPointerEventType",
        )
        key_export = section(
            api,
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_key",
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_load_url",
        )

        for marker in (
            'kM4ControlLeftDomCode = "ControlLeft"',
            'kM4CopyDomCode = "KeyC"',
            'kM4PasteDomCode = "KeyV"',
            "kMaximumM4DomCodeLength = kM4ControlLeftDomCode.size()",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, api)
        for dom_code in ("CONTROL_LEFT", "US_C", "US_V"):
            with self.subTest(dom_code=dom_code):
                self.assertIn(f"ui::DomCode::{dom_code}", whitelist)
        for marker in (
            "strnlen(code, content::kMaximumM4DomCodeLength + 1)",
            "code_string != content::kM4ControlLeftDomCode",
            "code_string != content::kM4CopyDomCode",
            "code_string != content::kM4PasteDomCode",
            "ui::KeycodeConverter::CodeStringToDomCode",
            "content::IsSupportedM4DomCode(physical_key)",
            "content::GetWasmHostState().PostM4KeyCommand(",
            "DispatchDomKeyOnUiThread",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, key_export)

        queue_admission = section(
            api,
            "  bool PostM4KeyCommand(",
            "  void SetViewportSizeOnUiThread",
        )
        for marker in (
            "IsM4KeyTransitionAllowedLocked(physical_key, down)",
            "task_runner_->PostTask(FROM_HERE, std::move(command))",
            "RecordM4KeyTransitionLocked(physical_key, down)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, queue_admission)
        transition_admission = section(
            api,
            "  bool IsM4KeyTransitionAllowedLocked(",
            "  void RecordM4KeyTransitionLocked",
        )
        for marker in (
            "ui::DomCode::CONTROL_LEFT",
            "ui::DomCode::US_C",
            "ui::DomCode::US_V",
            "m4_control_left_down_",
            "m4_copy_down_",
            "m4_paste_down_",
            "key_down != down && (!down || m4_control_left_down_)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, transition_admission)

    def test_ozone_tracks_control_and_rejects_bare_copy_paste_keys(
        self,
    ) -> None:
        event_source = source("ui/ozone/platform/wasm/wasm_event_source.cc")
        injector = section(
            event_source,
            "  void InjectKeyEvent(DomCode physical_key",
            " private:",
        )

        for marker in (
            "DomCode::CONTROL_LEFT",
            "DomCode::US_C",
            "DomCode::US_V",
            "control_left_",
            "key_c_",
            "key_v_",
            "EF_CONTROL_DOWN",
            "event_source_->DispatchKeyEvent(",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, injector)
        self.assertRegex(
            injector,
            r"if \(down\s*&&\s*"
            r"\(physical_key == DomCode::US_C \|\|\s*"
            r"physical_key == DomCode::US_V\)\s*&&\s*!control_left_\)",
        )
        self.assertIn(
            "control_left_ || physical_key == DomCode::CONTROL_LEFT",
            injector,
        )
        self.assertNotIn("Input.insertText", injector)

    def test_host_requires_a_trusted_control_chord_before_queueing(self) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        handler = section(
            host,
            "  #handleM4KeyboardEvent(type, event)",
            "  #disableM4KeyboardInput",
        )
        release = section(
            host,
            "  #releaseM4KeyboardKeys(reason, triggerEvent = null)",
            "  #handleM4KeyboardEvent",
        )

        for marker in (
            "isM4CopyPasteShortcutCode(record.code)",
            "const controlHeld = this.#keyboardCodesDown.has(",
            "M4_CONTROL_LEFT_DOM_CODE",
            "UNSUPPORTED_SHORTCUT_STATE",
            "UNSUPPORTED_MODIFIERS",
            "expectedM4KeyboardKey(record.code)",
            '"chromium_wasm_host_key"',
            "record.queued = result === 1",
            "event.preventDefault()",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, handler)
        self.assertLess(
            handler.index("record.queued = result === 1"),
            handler.index("event.preventDefault()"),
        )
        for marker in (
            "const heldCodes = Array.from(this.#keyboardCodesDown);",
            "code !== M4_CONTROL_LEFT_DOM_CODE",
            "code === M4_CONTROL_LEFT_DOM_CODE",
            "controlStillHeld",
            '"chromium_wasm_host_key"',
            "[code, 0]",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, release)

    def test_fixture_observes_native_copy_paste_without_clipboard_shortcuts(
        self,
    ) -> None:
        fixture = source(
            "tools/wasm/testdata/m4_ozone_copy_paste_page.html"
        )

        for marker in (
            'id="copy-source" type="text" value="COPY"',
            'id="selection-decoy" type="text" value="DECOY"',
            'id="primary-verify-target" type="text"',
            'id="paste-target" type="text"',
            "copySelectionActivity",
            "decoySelectionActivity",
            "copyEventTrace",
            "primaryVerifyPasteEventTrace",
            "pasteEventTrace",
            'primaryVerifyTarget.addEventListener("paste"',
            'copySource.addEventListener("copy"',
            'pasteTarget.addEventListener("paste"',
            'event.clipboardData?.getData("text/plain")',
            '"CTRL COPY/PASTE DELIVERED"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, fixture)
        for forbidden in (
            "navigator.clipboard",
            "execCommand(",
            "setSelectionRange(",
            "setRangeText(",
            ".select(",
            "dispatchEvent(",
            "Input.insertText",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, fixture)
        self.assertIsNone(re.search(r"\.value\s*=\s*(?!=)", fixture))

    def test_smoke_proves_copy_paste_buffer_wins_over_primary_selection(
        self,
    ) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        cdp = source("tools/wasm/m4_cdp.py")
        runner = source("tools/wasm/run_m4_ozone_smoke.py")
        server = source("tools/wasm/m3_content_server.py")
        shortcut = section(
            cdp,
            "    def dispatch_control_shortcut(",
            "\n    def dispatch_ime_preedit",
        )
        smoke = section(
            host,
            "async function runM4OzoneCopyPasteSmokeFromQuery()",
            "async function runM4OzoneWheelSmokeFromQuery()",
        )

        for marker in (
            '"type": "rawKeyDown"',
            '"type": "keyUp"',
            '"code": "ControlLeft"',
            '"modifiers": 2',
            '"modifiers": 0',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, shortcut)
        self.assertNotIn('"text":', shortcut)
        self.assertNotIn("Input.insertText", shortcut)

        for marker in (
            "host.enableM4PointerInput()",
            "host.enableM4KeyboardInput()",
            'state: "awaiting-dom-copy-paste-copy"',
            'state: "awaiting-dom-copy-paste-decoy-drag"',
            'state: "awaiting-dom-copy-paste-primary-verify"',
            'state: "awaiting-dom-copy-paste-paste"',
            "copyProof",
            "decoySelectionProof",
            "primarySelectionPasteProof",
            "hasM4CopyPastePrimarySelectionPasteEvidence",
            "copyPasteBufferWins",
            "M4 Ctrl+C copy timeout",
            "M4 Ctrl+V paste timeout",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, smoke)
        self.assertIn(
            "pageProbe?.pasteValue === M4_COPY_PASTE_SOURCE_VALUE &&",
            smoke,
        )
        self.assertIn(
            "pageProbe?.pasteValue !== M4_COPY_PASTE_DECOY_VALUE",
            smoke,
        )
        paste_activation_state = (
            'state: "awaiting-dom-copy-paste-paste-activation"'
        )
        primary_verify_state = (
            'state: "awaiting-dom-copy-paste-primary-verify"'
        )
        self.assertIn(paste_activation_state, smoke)
        self.assertIn(primary_verify_state, smoke)
        self.assertLess(
            smoke.index(paste_activation_state),
            smoke.index(primary_verify_state),
        )

        runner_copy_paste = section(
            runner,
            '        elif args.input == "copy-paste":\n'
            '            stage = "dispatch_trusted_dom_copy_source_activation"',
            '        elif args.input == "wheel":',
        )
        self.assertLess(
            runner_copy_paste.index(
                'stage = "dispatch_trusted_dom_paste_activation"'
            ),
            runner_copy_paste.index(
                'stage = "dispatch_trusted_dom_primary_selection_verification"'
            ),
        )

        for marker in (
            '"copy-paste",',
            "M4_COPY_PASTE_CASE",
            "window.__chromiumWasmM4CopyPasteState || null",
            "client.dispatch_ctrl_c()",
            "client.dispatch_ctrl_v()",
            "validate_m4_copy_paste_result(",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, runner)
        for marker in (
            'M4_COPY_PASTE_CASE = "ozone_copy_paste_m4"',
            '"m4_ozone_copy_paste_page.html"',
            '"/__m3__/m4-copy-paste-fixture.html"',
            "def m4_copy_paste_smoke_url(",
            "def validate_m4_copy_paste_result(",
            "copyPasteBufferWins",
            '("down", "KeyC", "c", True)',
            '("down", "KeyV", "v", True)',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, server)

    def test_runner_reserves_a_bounded_long_case_timeout(self) -> None:
        runner = source("tools/wasm/run_m4_ozone_smoke.py")
        copy_paste_url = section(
            runner,
            '        elif args.input == "copy-paste":',
            '        elif args.input == "wheel":',
        )

        self.assertIn(
            "# This case has eight separately observed physical input phases.",
            copy_paste_url,
        )
        self.assertIn(
            "# Leave time for the outer driver to collect the posted result.",
            copy_paste_url,
        )
        self.assertIn(
            "timeout_seconds=min(90.0, max(1.0, args.timeout - 5.0)),",
            copy_paste_url,
        )
        self.assertNotIn(
            "timeout_seconds=min(30.0, max(1.0, args.timeout - 1.0)),",
            copy_paste_url,
        )


if __name__ == "__main__":
    unittest.main()
