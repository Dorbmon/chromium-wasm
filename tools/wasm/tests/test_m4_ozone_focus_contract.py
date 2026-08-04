#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Static contracts for trusted host focus loss through Ozone and Aura."""

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


class M4OzoneFocusContractTest(unittest.TestCase):
    def test_focus_loss_uses_generic_platform_window_and_aura_focus_client(
        self,
    ) -> None:
        api = source("content/shell/browser/wasm_host_api.cc")
        window = source("ui/ozone/platform/wasm/wasm_window.cc")
        bridge = source("ui/ozone/platform/wasm/wasm_host_bridge.js")
        shell_focus = source("content/shell/browser/shell_platform_data_aura.cc")

        dispatch = section(
            api,
            "void DeactivateHostWindowOnUiThread()",
            "void ShutdownOnUiThread()",
        )
        for marker in (
            "Shell* shell = GetSingleShell();",
            "aura::client::GetFocusClient(root_window)",
            "aura::WindowTreeHostPlatform::GetHostForWindow(root_window)",
            "focus_client->FocusWindow(nullptr);",
            "host->platform_window()->Deactivate();",
            "ReportFatal",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, dispatch)
        self.assertLess(
            dispatch.index("focus_client->FocusWindow(nullptr);"),
            dispatch.index("host->platform_window()->Deactivate();"),
        )
        self.assertGreaterEqual(dispatch.count("GetSingleShell()"), 2)
        self.assertGreater(
            dispatch.rindex("GetSingleShell()"),
            dispatch.index("focus_client->FocusWindow(nullptr);"),
        )
        for forbidden in (
            "WasmWindow",
            "RenderWidgetHost",
            "WebKeyboardEvent",
            "ForwardKeyboardEvent",
            "web_contents()->Blur",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, dispatch)

        focus_export = section(
            api,
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_deactivate()",
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_shutdown()",
        )
        self.assertIn("PostHostCommand", focus_export)
        self.assertIn("DeactivateHostWindowOnUiThread", focus_export)

        deactivate = section(
            window,
            "void WasmWindow::Deactivate()",
            "void WasmWindow::SetUseNativeFrame",
        )
        self.assertIn("manager_->SetKeyboardFocusedWindow(nullptr);", deactivate)
        self.assertIn("ReportOzoneFocusState(manager_, /*active=*/false);", deactivate)
        self.assertLess(
            deactivate.index("manager_->SetKeyboardFocusedWindow(nullptr);"),
            deactivate.index("activation_state_ == ActivationState::kInactive"),
        )
        normal_deactivation = deactivate.split(
            "activation_state_ = ActivationState::kInactive;", 1
        )[1]
        self.assertLess(
            normal_deactivation.index(
                "ReportOzoneFocusState(manager_, /*active=*/false);"
            ),
            normal_deactivation.index("delegate_->OnActivationChanged(false);"),
        )
        for marker in (
            "chromium_wasm_report_ozone_focus_state__proxy: 'sync'",
            "keyboardTargetPresent: keyboardTargetPresent === 1",
            "active: active === 1",
            "bridge.reportOzoneFocusState",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, bridge)

        focus_window = section(
            shell_focus,
            "  void FocusWindow(aura::Window* window) override {",
            "  void ResetFocusWithinActiveWindow",
        )
        self.assertIn("if (focused_window_ == window)", focus_window)
        self.assertIn("return;", focus_window)

    def test_host_releases_input_before_queueing_deactivation(self) -> None:
        host = source("tools/wasm/host/content_shell_host.js")

        loss = section(
            host,
            "  #deactivateM4HostWindow(reason, event = null)",
            "  #disableM4FocusInput",
        )
        for marker in (
            "#cancelActiveM4Pointer(reason)",
            "#releaseM4KeyboardKeys(reason, event)",
            "chromium_wasm_host_deactivate",
            "this.#ozoneFocusState = null;",
            "ozoneFocusReportSequenceBefore",
            "DUPLICATE_FOCUS_LOSS",
            "m4:focus:",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, loss)
        self.assertLess(
            loss.index("#releaseM4KeyboardKeys(reason, event)"),
            loss.index("chromium_wasm_host_deactivate"),
        )

        listeners = section(host, "  enableM4FocusInput()", "  #heartbeat()")
        for marker in (
            '"blur"',
            '"visibilitychange"',
            "canvas-blur",
            "window-blur",
            "visibility-loss",
            "m4:focus:listeners-attached",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, listeners)

        release = section(
            host,
            "  #releaseM4KeyboardKeys(reason, triggerEvent = null)",
            "  #handleM4KeyboardEvent",
        )
        for marker in (
            "generated: true",
            "triggerTrusted: triggerEvent?.isTrusted === true",
            "relatedTargetId",
            "this.#lastQueuedKeyUp = record",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, release)

    def test_fixture_and_runner_require_real_outer_focus_transfer(self) -> None:
        fixture = source("tools/wasm/testdata/m4_ozone_focus_page.html")
        host_page = source("tools/wasm/host/content_shell.html")
        host = source("tools/wasm/host/content_shell_host.js")
        runner = source("tools/wasm/run_m4_ozone_smoke.py")
        cdp = source("tools/wasm/m4_cdp.py")
        server = source("tools/wasm/m3_content_server.py")

        for marker in (
            'id="focus-target" tabindex="0"',
            'window.addEventListener("blur"',
            "document.hasFocus()",
            "windowBlurCount",
            '"WINDOW BLURRED"',
            "keyEvents",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, fixture)
        for forbidden in (".focus(", ".blur(", "dispatchEvent", "preventDefault()"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, fixture)

        self.assertIn('id="m4-focus-sink"', host_page)
        self.assertIn("hidden", host_page)
        self.assertIn("position: fixed", host_page)

        cdp_key_down = section(
            cdp,
            "def dispatch_arrow_down_down(self) -> None:",
            "\n\n    def dispatch_arrow_down(self) -> None:",
        )
        for marker in (
            '"Input.dispatchKeyEvent"',
            '"type": "rawKeyDown"',
            '"code": "ArrowDown"',
            '"windowsVirtualKeyCode": 40',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, cdp_key_down)
        self.assertNotIn('"text":', cdp_key_down)

        for marker in (
            '"printable-key",',
            '"ime-bridge",',
            '"focus",',
            "M4_FOCUS_CASE",
            "m4_focus_smoke_url(",
            "awaiting-dom-focus-key-down",
            "awaiting-dom-focus-loss",
            "read_focus_sink_position(client)",
            "client.dispatch_arrow_down_down()",
            "client.dispatch_primary_click(focus_sink_x, focus_sink_y)",
            "validate_m4_focus_result(result, expected_versions=versions)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, runner)
        for forbidden in (".blur()", ".focus()", "dispatchEvent("):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, runner)

        for marker in (
            'M4_FOCUS_CASE = "ozone_focus_m4"',
            'M4_FOCUS_FIXTURE = M3_TESTDATA_DIR / "m4_ozone_focus_page.html"',
            '"/__m3__/m4-focus-fixture.html": M4_FOCUS_FIXTURE',
            "def m4_focus_smoke_url(",
            "def validate_m4_focus_result(",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, server)

        smoke = section(
            host,
            "async function runM4OzoneFocusSmokeFromQuery()",
            "export async function runContentShellSmokeFromQuery",
        )
        for marker in (
            "host.enableM4FocusInput()",
            "window.__chromiumWasmM4FocusState",
            "focusSink.hidden = false",
            "focusSink.addEventListener(\"click\"",
            "ozoneKeyboardTargetCleared",
            "ozoneFocusState",
            "WINDOW BLURRED",
            "document.activeElement === focusSink",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, smoke)
        self.assertNotIn("injectInput(", smoke)
        self.assertNotIn("chromium_wasm_host_click", smoke)

    def test_focus_loss_reports_pointer_evidence_after_the_outer_exit(self) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        smoke = section(
            host,
            "async function runM4OzoneFocusSmokeFromQuery()",
            "export async function runContentShellSmokeFromQuery",
        )

        self.assertIn(
            "const pointerAfterFocusLoss = readiness?.pointerInput;", smoke
        )
        self.assertIn("pointer: clone(pointerAfterFocusLoss)", smoke)
        self.assertIn("pointerInput: pointerAfterFocusLoss", smoke)
        self.assertLess(
            smoke.index("const pointerAfterFocusLoss = readiness?.pointerInput;"),
            smoke.index("pointerInput: pointerAfterFocusLoss"),
        )


if __name__ == "__main__":
    unittest.main()
