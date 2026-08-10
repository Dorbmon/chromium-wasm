#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for trusted DOM pointer delivery to the Wasm Chrome UI."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def _source_set_body(build_file: str, target: str) -> str:
    match = re.search(rf'\bsource_set\s*\(\s*"{re.escape(target)}"\s*\)', build_file)
    if not match:
        raise AssertionError(f"could not find source set {target!r}")
    opening_brace = build_file.find("{", match.end())
    if opening_brace == -1:
        raise AssertionError(f"source set {target!r} has no opening brace")
    depth = 0
    for index in range(opening_brace, len(build_file)):
        if build_file[index] == "{":
            depth += 1
        elif build_file[index] == "}":
            depth -= 1
            if depth == 0:
                return build_file[opening_brace + 1 : index]
    raise AssertionError(f"source set {target!r} has no closing brace")


class M6WasmBrowserHostPointerContractTest(unittest.TestCase):
    def test_c_abi_is_bounded_and_uses_public_ozone_injection(self) -> None:
        header = source("chrome/browser/wasm/wasm_browser_host_pointer.h")
        implementation = source("chrome/browser/wasm/wasm_browser_host_pointer.cc")

        for expected in (
            "InitializeWasmBrowserHostPointer()",
            "ShutdownWasmBrowserHostPointer();",
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_pointer",
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_pointer_exit",
            "kMaximumHostPointerCoordinate = 16383",
            "WasmBrowserHostPointerType::kMove",
            "WasmBrowserHostPointerType::kDown",
            "WasmBrowserHostPointerType::kUp",
            "EF_LEFT_MOUSE_BUTTON",
            "EF_MIDDLE_MOUSE_BUTTON",
            "EF_RIGHT_MOUSE_BUTTON",
            "CreateSystemInputInjector()",
            "MoveCursorTo(gfx::PointF(location))",
            "InjectMouseButton(button, /*down=*/true)",
            "InjectMouseButton(button, /*down=*/false)",
            "DispatchWasmMouseExit()",
            "PostMouseExit()",
            "has_unpressed_hover_target_",
            "x < 0 || x > kMaximumHostPointerCoordinate",
            "y > kMaximumHostPointerCoordinate",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, header + implementation)

        for forbidden in (
            "Browser*",
            '#include "content/public/browser/web_contents.h"',
            "ForwardMouseEvent",
            "Widget::OnMouse",
            "content/shell",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, header + implementation)

    def test_queued_records_have_independent_generation_and_button_state(self) -> None:
        implementation = source("chrome/browser/wasm/wasm_browser_host_pointer.cc")
        for expected in (
            "accepting_host_pointer_",
            "pressed_buttons_",
            "++generation_;",
            "task_runner_->PostTask(",
            "DispatchPointerOnUiThread",
            "generation == generation_",
            "IsTransitionAllowedLocked",
            "UpdatePressedButtonsLocked",
            "UpdateHoverTargetLocked",
            "DispatchMouseExitOnUiThread",
            "input_injector_.reset();",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, implementation)

        self.assertLess(
            implementation.index("UpdatePressedButtonsLocked(type, button);"),
            implementation.index("return true;", implementation.index("UpdatePressedButtonsLocked(type, button);")),
        )

    def test_main_parts_and_gn_keep_pointer_lifetime_independent(self) -> None:
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        build = source("chrome/browser/wasm/BUILD.gn")
        pointer_target = _source_set_body(build, "wasm_browser_host_pointer")
        main_parts_target = _source_set_body(build, "wasm_browser_main_parts")

        self.assertIn(
            '#include "chrome/browser/wasm/wasm_browser_host_pointer.h"',
            main_parts,
        )
        self.assertLess(
            main_parts.index("InitializeWasmBrowserHostInput()"),
            main_parts.index("InitializeWasmBrowserHostPointer()"),
        )
        post_main = main_parts.index("void WasmBrowserMainParts::PostMainMessageLoopRun")
        post_main_body = main_parts[post_main : main_parts.index(
            "bool WasmBrowserMainParts::PreflightResources", post_main
        )]
        self.assertLess(
            post_main_body.index("ShutdownWasmBrowserHostPointer();"),
            post_main_body.index("ShutdownWasmBrowserHostInput();"),
        )
        self.assertIn('visibility = [ ":wasm_browser_main_parts" ]', pointer_target)
        self.assertIn('"//ui/ozone",', pointer_target)
        self.assertIn('"//ui/ozone/platform/wasm:wasm",', pointer_target)
        self.assertIn('":wasm_browser_host_pointer",', main_parts_target)
        for forbidden in (
            '":wasm_browser",',
            '":wasm_browser_lifecycle",',
            "//chrome/browser/ui:ui",
            "//ui/views",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, pointer_target)

    def test_normal_host_reuses_the_shared_trusted_pointer_adapter(self) -> None:
        host = source("tools/wasm/host/chrome_wasm_host.js")
        adapter = source("tools/wasm/host/chrome_wasm_pointer_input.js")
        for expected in (
            'import {ChromiumWasmTrustedPointerInput}',
            "new ChromiumWasmTrustedPointerInput",
            "this.#pointerInput.attach();",
            "this.#pointerInput?.detach();",
            'this.#pointerInput?.releaseActivePointer("host-shutdown")',
        ):
            with self.subTest(normal_host_expected=expected):
                self.assertIn(expected, host)

        for expected in (
            "#canvasPointForPointerEvent(event)",
            "if (!record.trusted)",
            "if (!record.cancelable)",
            'record.pointerType !== "mouse"',
            "!record.primary",
            "record.button !== 0",
            "record.buttons !== 1",
            "chromium_wasm_browser_host_pointer",
            "chromium_wasm_browser_host_pointer_exit",
            "(cssX * this.#canvas.width) / contentWidth",
            "(cssY * this.#canvas.height) / contentHeight",
            "this.#canvas.setPointerCapture(record.pointerId)",
            '"pointerdown", this.#onPointerDown',
            '"pointermove", this.#onPointerMove',
            '"pointerup", this.#onPointerUp',
            '"pointerleave", this.#onPointerLeave',
            '"blur", this.#onCanvasBlur',
            '"visibilitychange", this.#onVisibilityChange',
            "#isTrustedActivePointerCleanupEvent(event)",
            "event?.isTrusted === true",
            "this.releaseActivePointer(\"canvas-blur\")",
            "this.releaseActivePointer(\"document-hidden\")",
        ):
            with self.subTest(adapter_expected=expected):
                self.assertIn(expected, adapter)

    def test_switch_gated_tab_verifier_has_a_bounded_phase_machine(self) -> None:
        build = source("chrome/browser/wasm/BUILD.gn")
        verifier = source("chrome/browser/wasm/wasm_browser_host_pointer_tab_smoke.cc")
        lifecycle = source("chrome/browser/wasm/wasm_browser_lifecycle.cc")
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        verifier_target = _source_set_body(build, "wasm_browser_host_pointer_tab_smoke")

        for expected in (
            "chromium_wasm_browser_host_pointer_tab_check",
            "chromium_wasm_browser_host_pointer_tab_presented",
            "kFirstCheck",
            "kSecondCheck",
            "kThirdCheck",
            "kFourthCheck",
            "kFourthPresentation",
            "IsExpectedCallbackLocked",
            "AdvanceExpectedCallbackLocked",
            "DisableAfterFailedCallback",
            "RepeatingCallback<bool(int)>",
        ):
            with self.subTest(verifier_expected=expected):
                self.assertIn(expected, verifier)
        for expected in (
            "StartHostPointerTabSmoke",
            "CHROMIUM_WASM_M6_HOST_POINTER_TABS:READY",
            "CHROMIUM_WASM_M6_HOST_POINTER_TABS:INSERTED",
            "CHROMIUM_WASM_M6_HOST_POINTER_TABS:FIRST_SELECTED",
            "CHROMIUM_WASM_M6_HOST_POINTER_TABS:SECOND_SELECTED",
            "CHROMIUM_WASM_M6_HOST_POINTER_TABS:CLOSED",
            "CHROMIUM_WASM_M6_HOST_POINTER_TABS:PASS",
            "host_pointer_tab_first_selection_verified_",
            "host_pointer_tab_second_selection_verified_",
            "host_pointer_tab_second_contents_",
            "tab_strip_model->active_index() != 0",
            "tab_strip_model->active_index() != 1",
            "browser_view.GetActiveWebContents()",
            "tab_strip->tab_button_for_testing(0)",
            "tab_strip->tab_button_for_testing(1)",
            "tab_strip_model->count() != 2",
            "tab_strip_model->count() != 1",
            "return false;",
        ):
            with self.subTest(lifecycle_expected=expected):
                self.assertIn(expected, lifecycle)
        self.assertIn('"wasm-browser-host-pointer-tab-smoke"', main_parts)
        self.assertIn(":wasm_browser_lifecycle", verifier_target)


if __name__ == "__main__":
    unittest.main()
