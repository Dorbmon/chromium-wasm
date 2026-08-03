#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Static contracts for the first raw navigation-key Ozone/Aura slice."""

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


class M4OzoneKeyboardContractTest(unittest.TestCase):
    def test_primary_pointer_activation_establishes_keyboard_target(
        self,
    ) -> None:
        event_source = source("ui/ozone/platform/wasm/wasm_event_source.cc")
        manager = source("ui/ozone/platform/wasm/wasm_window_manager.cc")
        window = source("ui/ozone/platform/wasm/wasm_window.cc")

        mouse_dispatch = section(
            event_source,
            "bool WasmPlatformEventSource::DispatchMouseEvent",
            "bool WasmPlatformEventSource::DispatchMouseWheelEvent",
        )
        self.assertIn("target->Activate();", mouse_dispatch)
        self.assertIn("EventType::kMousePressed", mouse_dispatch)
        self.assertIn("EF_LEFT_MOUSE_BUTTON", mouse_dispatch)

        wheel_dispatch = section(
            event_source,
            "bool WasmPlatformEventSource::DispatchMouseWheelEvent",
            "bool WasmPlatformEventSource::DispatchKeyEvent",
        )
        self.assertNotIn("target->Activate();", wheel_dispatch)

        for marker in (
            "keyboard_focused_window_ == window",
            "keyboard_focused_window_ = nullptr;",
            "void WasmWindowManager::SetKeyboardFocusedWindow",
            "WasmWindow* WasmWindowManager::GetKeyboardFocusedWindow",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, manager)

        activate = section(
            window,
            "void WasmWindow::Activate()",
            "void WasmWindow::Deactivate()",
        )
        self.assertIn("manager_->SetKeyboardFocusedWindow(this);", activate)
        deactivate = section(
            window,
            "void WasmWindow::Deactivate()",
            "void WasmWindow::SetUseNativeFrame",
        )
        self.assertIn(
            "manager_->SetKeyboardFocusedWindow(nullptr);", deactivate
        )

    def test_injector_and_event_source_normalize_bounded_raw_keys(self) -> None:
        event_source = source("ui/ozone/platform/wasm/wasm_event_source.cc")
        header = source("ui/ozone/platform/wasm/wasm_event_source.h")

        self.assertIn(
            "bool DispatchKeyEvent(EventType type,", header
        )
        injector = section(
            event_source,
            "void InjectKeyEvent(DomCode physical_key",
            " private:",
        )
        for marker in (
            "IsSupportedM4DomCode(physical_key)",
            "DomCode::ARROW_DOWN",
            "arrow_down_",
            "key_a_",
            "key_down == down",
            "key_down = down;",
            "EventType::kKeyPressed",
            "EventType::kKeyReleased",
            "event_source_->DispatchKeyEvent(",
            "EF_NONE",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, injector)
        self.assertIn("DomCode::US_A", event_source)
        self.assertNotIn("KeyEvent event", injector)

        dispatch = section(
            event_source,
            "bool WasmPlatformEventSource::DispatchKeyEvent",
            "std::unique_ptr<SystemInputInjector> "
            "CreateWasmSystemInputInjector",
        )
        for marker in (
            "PlatformEventSource::ShouldIgnoreNativePlatformEvents()",
            "EventType::kKeyPressed",
            "EventType::kKeyReleased",
            "IsSupportedM4DomCode(physical_key)",
            "window_manager_->GetKeyboardFocusedWindow()",
            "target->IsVisible()",
            "KeyboardLayoutEngineManager::GetKeyboardLayoutEngine",
            "layout_engine->Lookup",
            "KeyEvent event(type, key_code, physical_key, flags, dom_key,",
            "event.set_source_device_id(source_device_id)",
            "Event::DispatcherApi(&event).set_target(target)",
            "PlatformEventSource::DispatchEvent(&event)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, dispatch)
        self.assertLess(
            dispatch.index("Event::DispatcherApi(&event).set_target(target)"),
            dispatch.index("PlatformEventSource::DispatchEvent(&event)"),
        )
        for forbidden in (
            "RenderWidgetHost",
            "WebKeyboardEvent",
            "ForwardKeyboardEvent",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, dispatch)

    def test_key_abi_is_bounded_and_only_queues_through_ozone(self) -> None:
        api = source("content/shell/browser/wasm_host_api.cc")

        dispatch = section(
            api, "void DispatchDomKeyOnUiThread", "void LoadUrlOnUiThread"
        )
        for marker in (
            "GetInputInjectorOnUiThread",
            "input_injector->InjectKeyEvent(physical_key, down,",
            "suppress_auto_repeat=*/true",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, dispatch)
        for forbidden in (
            "web_contents->Focus",
            "RenderWidgetHost",
            "WebKeyboardEvent",
            "ForwardKeyboardEvent",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, dispatch)

        key_export = section(
            api,
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_key",
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_load_url",
        )
        for marker in (
            "!code || (down != 0 && down != 1)",
            "strnlen(code, content::kM4NavigationDomCode.size() + 1)",
            "std::string_view code_string(code, length)",
            "ui::KeycodeConverter::CodeStringToDomCode",
            "content::IsSupportedM4DomCode(physical_key)",
            "PostHostCommand",
            "DispatchDomKeyOnUiThread",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, key_export)
        self.assertIn("kM4NavigationDomCode", api)
        self.assertIn("kM4PrintableDomCode", api)
        self.assertIn("ui::DomCode::ARROW_DOWN", api)
        self.assertIn("ui::DomCode::US_A", api)

    def test_host_rejects_unsafe_keyboard_events_before_preventing_default(
        self,
    ) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        handler = section(
            host,
            "  #handleM4KeyboardEvent(type, event)",
            "  #disableM4KeyboardInput",
        )

        for marker in (
            "event.isTrusted === true",
            "!event.cancelable",
            "!record.canvasFocused",
            "!record.pointerActivated",
            "record.modifiers.alt",
            "record.repeat",
            "record.isComposing",
            'record.key === "Dead"',
            'record.key === "Process"',
            "expectedM4KeyboardKey(record.code)",
            "record.key !== expectedKey",
            "DUPLICATE_DOWN",
            "UNMATCHED_UP",
            "chromium_wasm_host_key",
            "record.queued = result === 1",
            "this.#keyboardCodesDown.add(record.code)",
            "this.#keyboardCodesDown.delete(record.code)",
            "event.preventDefault()",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, handler)
        self.assertLess(
            handler.index("record.queued = result === 1"),
            handler.index("event.preventDefault()"),
        )

        release = section(
            host,
            "  #releaseM4KeyboardKeys(reason, triggerEvent = null)",
            "  #handleM4KeyboardEvent",
        )
        self.assertIn("this.#keyboardCodesDown.clear();", release)
        self.assertIn("chromium_wasm_host_key", release)
        self.assertIn("generated: true", release)
        focus_listeners = section(
            host, "  enableM4FocusInput()", "  #heartbeat()"
        )
        for marker in (
            '"blur"',
            '"visibilitychange"',
            "#deactivateM4HostWindow",
            "m4:focus:listeners-attached",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, focus_listeners)

    def test_fixture_requires_real_focus_default_scroll_and_no_text_input(
        self,
    ) -> None:
        fixture = source("tools/wasm/testdata/m4_ozone_keyboard_page.html")

        for marker in (
            'id="keyboard-target" tabindex="0"',
            'target.addEventListener("click"',
            'target.addEventListener("focus"',
            'document.addEventListener("keydown"',
            'document.addEventListener("keyup"',
            "event.isTrusted",
            "event.defaultPrevented",
            "document.scrollingElement",
            "root.scrollTop",
            '"ARROW DOWN RECEIVED"',
            "textInputEvents",
            "beforeinputCount",
            "compositionstartCount",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, fixture)
        self.assertNotIn(".focus(", fixture)
        self.assertNotIn("event.preventDefault()", fixture)
        self.assertNotIn("scrollTop =", fixture)

    def test_runner_cdp_server_and_host_use_a_distinct_raw_key_case(
        self,
    ) -> None:
        cdp = source("tools/wasm/m4_cdp.py")
        runner = source("tools/wasm/run_m4_ozone_smoke.py")
        server = source("tools/wasm/m3_content_server.py")
        host = source("tools/wasm/host/content_shell_host.js")

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
        cdp_key = section(
            cdp,
            "def dispatch_arrow_down(self) -> None:",
            "\n\ndef wait_for_page_client",
        )
        self.assertIn("self.dispatch_arrow_down_down()", cdp_key)
        self.assertIn('"type": "keyUp"', cdp_key)

        for marker in (
            'choices=("pointer", "wheel", "keyboard", "printable-key", "focus")',
            "M4_KEYBOARD_CASE",
            '"awaiting-dom-keyboard-activation"',
            '"awaiting-dom-key"',
            "m4_keyboard_smoke_url(",
            "client.dispatch_primary_click(click_x, click_y)",
            "client.dispatch_arrow_down()",
            "validate_m4_keyboard_result(result, expected_versions=versions)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, runner)

        for marker in (
            'M4_KEYBOARD_CASE = "ozone_keyboard_m4"',
            'M4_KEYBOARD_FIXTURE = M3_TESTDATA_DIR / '
            '"m4_ozone_keyboard_page.html"',
            '"/__m3__/m4-keyboard-fixture.html": M4_KEYBOARD_FIXTURE',
            "def m4_keyboard_smoke_url(",
            "def validate_m4_keyboard_result(",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, server)

        smoke = section(
            host,
            "async function runM4OzoneKeyboardSmokeFromQuery()",
            "export async function runContentShellSmokeFromQuery",
        )
        for marker in (
            "host.enableM4PointerInput()",
            "host.enableM4KeyboardInput()",
            "window.__chromiumWasmM4KeyboardState",
            "ARROW DOWN RECEIVED",
            "textInputEvents",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, smoke)
        self.assertNotIn("injectInput(", smoke)
        self.assertNotIn("chromium_wasm_host_click", smoke)


if __name__ == "__main__":
    unittest.main()
