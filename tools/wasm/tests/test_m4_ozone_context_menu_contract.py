#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Static contracts for the bounded M4 native Aura context-menu path."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


class M4OzoneContextMenuContractTest(unittest.TestCase):
    def test_wasm_build_selects_the_dedicated_view_delegate(self) -> None:
        build = source("content/shell/BUILD.gn")

        aura_delegate_selection = build.split(
            'sources += [ "browser/shell_platform_delegate_aura.cc" ]', 1
        )[1]
        wasm_branch = aura_delegate_selection.split("if (is_wasm) {", 1)[1].split(
            "      } else {", 1
        )[0]
        non_wasm_branch = aura_delegate_selection.split(
            "      } else {", 1
        )[1].split("    }\n  } else {", 1)[0]

        self.assertIn(
            '"browser/shell_web_contents_view_delegate_wasm.cc"',
            wasm_branch,
        )
        self.assertNotIn("shell_web_contents_view_delegate_aura.cc", wasm_branch)
        self.assertIn(
            '"browser/shell_web_contents_view_delegate_aura.cc"',
            non_wasm_branch,
        )

    def test_menu_is_an_aura_child_not_a_second_platform_surface(self) -> None:
        delegate = source(
            "content/shell/browser/shell_web_contents_view_delegate_wasm.cc"
        )

        for marker in (
            "class WasmContextMenuOverlay final : public aura::WindowDelegate",
            "aura::client::WINDOW_TYPE_MENU",
            "root_window->AddChild(window_.get());",
            "root_window->StackChildAtTop(window_.get());",
            "const gfx::Rect menu_bounds(menu_origin, menu_size);",
            "window_->SetBounds(menu_bounds);",
            "window_->Show();",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, delegate)
        for forbidden in (
            "PlatformWindow",
            "CreatePlatformWindow",
            "WindowTreeHost",
            "SurfaceOzone",
            "chromium_wasm_host_",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, delegate)
        self.assertNotIn(
            "window_->SetBounds(gfx::Rect(menu_origin, menu_size_));",
            delegate,
        )

    def test_overlay_paints_copy_and_closes_the_native_menu_lifecycle(
        self,
    ) -> None:
        delegate = source(
            "content/shell/browser/shell_web_contents_view_delegate_wasm.cc"
        )
        overlay = section(
            delegate,
            "class WasmContextMenuOverlay final : public aura::WindowDelegate",
            "class ShellWebContentsViewDelegateWasm final",
        )

        for marker in (
            "blink::ContextMenuDataEditFlags::kCanCopy",
            "web_contents_->SetShowingContextMenu(true);",
            "web_contents_->SetShowingContextMenu(false);",
            "web_contents_->NotifyContextMenuClosed",
            "window_->SetCapture();",
            "window_->ReleaseCapture();",
            "void OnCaptureLost() override { Dismiss(); }",
            "void OnWindowTargetVisibilityChanged(bool visible) override",
            "~WasmContextMenuOverlay() override",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, overlay)

        mouse_handler = section(
            overlay,
            "void OnMouseEvent(ui::MouseEvent* event) override",
            "void OnPaint(const ui::PaintContext& context) override",
        )
        for marker in (
            "copy_enabled_",
            "ui::EF_LEFT_MOUSE_BUTTON",
            "web_contents_->Copy();",
            "Dismiss();",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, mouse_handler)
        self.assertLess(
            mouse_handler.index("web_contents_->Copy();"),
            mouse_handler.rindex("Dismiss();"),
        )

        paint = section(
            overlay,
            "void OnPaint(const ui::PaintContext& context) override",
            "void OnDeviceScaleFactorChanged",
        )
        for marker in (
            "ui::PaintRecorder",
            "DrawColor(copy_enabled_ ? kEnabledCopyRowColor",
            "PaintCopyLabel(recorder.canvas(), menu_size_);",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, paint)

        owner = section(
            delegate,
            "class ShellWebContentsViewDelegateWasm final",
            "}  // namespace",
        )
        self.assertIn("DismissContextMenu();", owner)
        self.assertIn("context_menu_->Dismiss();", owner)
        self.assertIn("context_menu_->is_showing()", owner)

    def test_secondary_pointer_and_outer_context_menu_are_strictly_gated(
        self,
    ) -> None:
        api = source("content/shell/browser/wasm_host_api.cc")
        host = source("tools/wasm/host/content_shell_host.js")

        for marker in (
            "(button != 0 && button != 1 && button != 2)",
            "ui::EF_RIGHT_MOUSE_BUTTON",
            "gfx::Point(x, y), mouse_button",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, api)

        pointer_handler = section(
            host,
            "  #handleM4PointerEvent(type, event) {",
            "\n\n  #handleM4ContextMenu(event) {",
        )
        for marker in (
            "event.button !== 0 && event.button !== 1 && event.button !== 2",
            "button === 0 ? 1 : button === 1 ? 4 : 2",
            "if (button === 2)",
            "this.#pendingM4ContextMenu = {",
            "suppressed: false",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, pointer_handler)

        context_handler = section(
            host,
            "  #handleM4ContextMenu(event) {",
            "\n\n  #disableM4PointerInput()",
        )
        for marker in (
            "trusted: event.isTrusted === true",
            "acceptedPointer: false",
            'record.reason = "UNTRUSTED_DOM_EVENT"',
            "record.button !== 2 || !point || !pending",
            "pending.suppressed === true",
            "pending.x !== point.x || pending.y !== point.y",
            'record.reason = "NO_QUEUED_SECONDARY_STREAM"',
            "if (event.cancelable)",
            "event.preventDefault();",
            "this.#pendingM4ContextMenu.suppressed = true;",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, context_handler)
        self.assertLess(
            context_handler.index('record.reason = "UNTRUSTED_DOM_EVENT"'),
            context_handler.index("event.preventDefault();"),
        )
        self.assertLess(
            context_handler.index('record.reason = "NO_QUEUED_SECONDARY_STREAM"'),
            context_handler.index("event.preventDefault();"),
        )

    def test_runner_routes_context_menu_through_native_phases_and_validator(
        self,
    ) -> None:
        runner = source("tools/wasm/run_m4_ozone_smoke.py")
        server = source("tools/wasm/m3_content_server.py")

        input_argument = section(
            runner,
            '    parser.add_argument(\n        "--input",',
            '    parser.add_argument(\n        "--ime-terminal",',
        )
        self.assertIn('"context-menu",', input_argument)

        setup = section(
            runner,
            '    elif args.input == "context-menu":',
            '\n    elif args.input == "selection":',
        )
        for marker in (
            "case = M4_CONTEXT_MENU_CASE",
            "window.__chromiumWasmM4ContextMenuState || null",
            'expected_state = "awaiting-dom-context-menu-activation"',
            "secondary click",
            "scan-derived Copy click",
            "ControlLeft+KeyV",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, setup)

        url_route = section(
            runner,
            '        elif args.input == "context-menu":',
            '\n        elif args.input == "selection":',
        )
        self.assertIn("m4_context_menu_smoke_url(", url_route)
        self.assertIn("timeout_seconds=min(90.0", url_route)

        driver = section(
            runner,
            '        elif args.input == "context-menu":\n'
            '            stage = "dispatch_trusted_dom_context_menu_source_activation"',
            '\n        elif args.input == "copy-paste":',
        )
        for marker in (
            "client.dispatch_primary_click(click_x, click_y)",
            "client.dispatch_primary_drag(",
            "drag_start_x",
            "drag_middle_x",
            "drag_end_x",
            "client.dispatch_secondary_click(secondary_x, secondary_y)",
            'x_field="menuTargetX"',
            'y_field="menuTargetY"',
            "client.dispatch_primary_click(copy_x, copy_y)",
            'x_field="pasteTargetX"',
            'y_field="pasteTargetY"',
            "client.dispatch_primary_click(paste_x, paste_y)",
            "client.dispatch_ctrl_v()",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, driver)

        phases = (
            "awaiting-dom-context-menu-activation",
            "awaiting-dom-context-menu-drag",
            "awaiting-dom-context-menu-open",
            "awaiting-dom-context-menu-copy",
            "awaiting-dom-context-menu-paste-activation",
            "awaiting-dom-context-menu-paste",
        )
        for earlier, later in zip(phases, phases[1:]):
            with self.subTest(earlier=earlier, later=later):
                self.assertLess(
                    runner.index(f'"{earlier}"'),
                    runner.index(f'"{later}"'),
                )
        self.assertLess(
            driver.index("client.dispatch_secondary_click(secondary_x, secondary_y)"),
            driver.index("client.dispatch_primary_click(copy_x, copy_y)"),
        )
        self.assertLess(
            driver.index("client.dispatch_primary_click(copy_x, copy_y)"),
            driver.index("client.dispatch_ctrl_v()"),
        )

        validator_route = section(
            runner,
            '        elif args.input == "context-menu":\n'
            "            validate_m4_context_menu_result(",
            '\n        elif args.input == "selection":',
        )
        self.assertIn("result, expected_versions=versions", validator_route)
        self.assertIn('input_key = "pointerInput"', validator_route)

        validator = section(
            server,
            "def validate_m4_context_menu_result(",
            "\n\ndef validate_m4_selection_result(",
        )
        for marker in (
            '"case": M4_CONTEXT_MENU_CASE',
            '"activationProof"',
            '"menuOpenProof"',
            '"menuCopyProof"',
            '"pasteProof"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, validator)

    def test_fixture_observes_native_selection_copy_without_dom_shortcuts(
        self,
    ) -> None:
        fixture = source("tools/wasm/testdata/m4_ozone_context_menu_page.html")

        for marker in (
            'id="context-source" type="text" value="MENU"',
            'id="context-paste" type="text"',
            'source.addEventListener("contextmenu"',
            "contextMenuTrace",
            "copyEventTrace",
            "pasteEventTrace",
            "pasteTextInputTrace",
            "selectionActivity",
            "NATIVE MENU COPY PASTED",
            "event.isTrusted === true",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, fixture)
        context_listener = section(
            fixture,
            'source.addEventListener("contextmenu", (event) => {',
            'source.addEventListener("select"',
        )
        self.assertNotIn("preventDefault", context_listener)
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
        self.assertIsNone(
            re.search(r"\[['\"]value['\"]\]\s*=\s*(?!=)", fixture)
        )


if __name__ == "__main__":
    unittest.main()
