#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Static contracts for the bounded M4 primary-selection paste proof."""

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


class M4OzonePrimaryPasteContractTest(unittest.TestCase):
    def test_wasm_uses_unix_editing_behavior_without_becoming_posix(
        self,
    ) -> None:
        preferences = source(
            "third_party/blink/public/common/web_preferences/"
            "web_preferences.h"
        )

        wasm_branch = (
            "#elif BUILDFLAG(IS_WASM)\n"
            "      // Wasm Ozone has a process-local primary-selection "
            "clipboard. Use the\n"
            "      // Unix editing behavior so Blink keeps its normal "
            "primary-selection\n"
            "      // semantics without treating Wasm as a POSIX platform.\n"
            "      mojom::EditingBehavior::kEditingUnixBehavior;\n"
            "#elif BUILDFLAG(IS_POSIX)"
        )
        self.assertIn(wasm_branch, preferences)
        self.assertLess(
            preferences.index("#elif BUILDFLAG(IS_WASM)"),
            preferences.index("#elif BUILDFLAG(IS_POSIX)"),
        )

    def test_pointer_abi_maps_primary_middle_and_secondary_buttons(self) -> None:
        api = source("content/shell/browser/wasm_host_api.cc")
        host = source("tools/wasm/host/content_shell_host.js")

        for marker in (
            "ui::EventFlags button",
            "(button != 0 && button != 1 && button != 2)",
            "ui::EF_MIDDLE_MOUSE_BUTTON",
            "ui::EF_RIGHT_MOUSE_BUTTON",
            "gfx::Point(x, y), mouse_button",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, api)
        for marker in (
            "#activeM4PointerButton = null;",
            "const button = this.#activeM4PointerButton;",
            "event.button !== 0 && event.button !== 1 && event.button !== 2",
            "button === 0 ? 1 : button === 1 ? 4 : 2",
            "POINTER_ALREADY_ACTIVE",
            "POINTER_BUTTON_MISMATCH",
            "INVALID_POINTER_RELEASE",
            "record.buttons & buttonMask(activeButton)",
            "event.preventDefault();",
            "this.#activeM4PointerButton = button;",
            "[eventType, point.x, point.y, button]",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, host)

    def test_fixture_observes_native_primary_selection_paste(self) -> None:
        fixture = source(
            "tools/wasm/testdata/m4_ozone_primary_paste_page.html"
        )

        for marker in (
            'id="source-target" type="text" value="WASM"',
            'id="paste-target" type="text"',
            "sourceSelectionActivity",
            "pasteEventTrace",
            "pasteTextInputTrace",
            'pasteTarget.addEventListener("paste"',
            'inputType: event.inputType',
            '"PRIMARY SELECTION PASTED"',
            "pasteAuxClickTrusted",
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
        self.assertNotRegex(fixture, r"\.value\s*=(?!=)")
        self.assertNotRegex(fixture, r"\[['\"]value['\"]\]\s*=(?!=)")

    def test_driver_uses_only_normal_mouse_input(self) -> None:
        cdp = source("tools/wasm/m4_cdp.py")
        runner = source("tools/wasm/run_m4_ozone_smoke.py")
        server = source("tools/wasm/m3_content_server.py")

        middle_click = section(
            cdp,
            "    def dispatch_middle_click(self, x: float, y: float) -> None:",
            "\n\n    def dispatch_primary_drag(",
        )
        for marker in (
            '"button": "middle"',
            '"type": "mouseMoved"',
            '"type": "mousePressed"',
            '"type": "mouseReleased"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, middle_click)
        for forbidden in ("Input.insertText", "navigator.clipboard"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, middle_click)

        for marker in (
            '"primary-paste"',
            "M4_PRIMARY_PASTE_CASE",
            "m4_primary_paste_smoke_url",
            '"awaiting-dom-primary-paste-drag"',
            '"awaiting-dom-primary-paste"',
            "client.dispatch_primary_drag(",
            "client.dispatch_middle_click(paste_x, paste_y)",
            "validate_m4_primary_paste_result",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, runner)
        for marker in (
            'M4_PRIMARY_PASTE_CASE = "ozone_primary_paste_m4"',
            '"m4_ozone_primary_paste_page.html"',
            '"/__m3__/m4-primary-paste-fixture.html"',
            "def m4_primary_paste_smoke_url(",
            "def validate_m4_primary_paste_result(",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, server)
        post_handler = section(
            server,
            "    def do_POST(self) -> None:",
            "\n\n\nclass M3HTTPServer",
        )
        self.assertIn("M4_PRIMARY_PASTE_CASE", post_handler)

    def test_host_requires_native_selection_then_native_paste(self) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        smoke = section(
            host,
            "async function runM4OzonePrimaryPasteSmokeFromQuery()",
            "async function runM4OzoneWheelSmokeFromQuery()",
        )

        for marker in (
            "M4_PRIMARY_PASTE_CASE",
            "M4_PRIMARY_PASTE_FIXTURE",
            "host.enableM4PointerInput()",
            'state: "awaiting-dom-primary-paste-activation"',
            'state: "awaiting-dom-primary-paste-drag"',
            'state: "awaiting-dom-primary-paste"',
            "hasM4PrimaryPasteSourceSelection",
            "hasM4PrimaryPasteFinalPageEvidence",
            "primaryPasteProof",
            '"M4 primary-selection paste timeout: "',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, smoke)
        self.assertLess(
            smoke.index('state: "awaiting-dom-primary-paste-drag"'),
            smoke.index('state: "awaiting-dom-primary-paste"'),
        )
        self.assertLess(
            smoke.index('state: "awaiting-dom-primary-paste"'),
            smoke.index("const primaryPasteProof = Object.freeze({"),
        )


if __name__ == "__main__":
    unittest.main()
