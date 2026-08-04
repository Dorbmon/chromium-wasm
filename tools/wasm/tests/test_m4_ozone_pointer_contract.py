#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Static contracts for trusted physical-pixel DOM-pointer Ozone/Aura input."""

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


class M4OzonePointerContractTest(unittest.TestCase):
    def test_event_source_is_built_owned_and_exposes_a_system_injector(
        self,
    ) -> None:
        build = source("ui/ozone/platform/wasm/BUILD.gn")
        platform = source("ui/ozone/platform/wasm/ozone_platform_wasm.cc")

        for path in ("wasm_event_source.cc", "wasm_event_source.h"):
            with self.subTest(path=path):
                self.assertIn(f'"{path}"', build)
        self.assertIn("wasm_event_source.h", platform)
        self.assertIn("std::unique_ptr<WasmPlatformEventSource>", platform)
        self.assertNotIn("WasmBootstrapPlatformEventSource", platform)

        initialize_ui = section(
            platform, "bool InitializeUI", "void InitializeGPU"
        )
        self.assertIn("std::make_unique<WasmWindowManager>()", initialize_ui)
        self.assertIn(
            "std::make_unique<WasmPlatformEventSource>(window_manager_.get())",
            initialize_ui,
        )
        self.assertLess(
            initialize_ui.index("std::make_unique<WasmWindowManager>()"),
            initialize_ui.index("std::make_unique<WasmPlatformEventSource>"),
        )

        injector_factory = section(
            platform,
            "std::unique_ptr<SystemInputInjector> CreateSystemInputInjector()",
            "std::unique_ptr<PlatformWindow> CreatePlatformWindow",
        )
        self.assertIn("if (!platform_event_source_)", injector_factory)
        self.assertIn(
            "CreateWasmSystemInputInjector(platform_event_source_.get())",
            injector_factory,
        )

    def test_system_injector_targets_and_dispatches_normal_ozone_events(
        self,
    ) -> None:
        event_source = source(
            "ui/ozone/platform/wasm/wasm_event_source.cc"
        )

        for marker in (
            "class WasmSystemInputInjector final : public SystemInputInjector",
            "void SetDeviceId(int device_id) override",
            "void MoveCursorTo(const gfx::PointF& location) override",
            "void InjectMouseButton(EventFlags button, bool down) override",
            "EventType::kMouseMoved",
            "EventType::kMousePressed",
            "EventType::kMouseReleased",
            "void InjectMouseWheel(int delta_x, int delta_y) override",
            "void InjectKeyEvent(DomCode physical_key",
            "NOTIMPLEMENTED_LOG_ONCE()",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, event_source)

        pressed = section(
            event_source, "if (down) {", "if (!(button_flags_ & button))"
        )
        released = section(
            event_source,
            "if (!(button_flags_ & button))",
            "void InjectMouseWheel",
        )
        self.assertLess(
            pressed.index("button_flags_ |= button"),
            pressed.index("EventType::kMousePressed"),
        )
        self.assertLess(
            released.index("EventType::kMouseReleased"),
            released.index("button_flags_ &= ~button"),
        )

        dispatch = section(
            event_source,
            "bool WasmPlatformEventSource::DispatchMouseEvent",
            "std::unique_ptr<SystemInputInjector> CreateWasmSystemInputInjector",
        )
        for marker in (
            "PlatformEventSource::ShouldIgnoreNativePlatformEvents()",
            "std::isfinite(screen_location.x())",
            "std::isfinite(screen_location.y())",
            "const gfx::Point root_location = gfx::ToFlooredPoint(screen_location);",
            "window_manager_->SetCursorScreenPointInPixels(root_location)",
            "window_manager_->GetPointerTarget(root_location)",
            "location.Offset(-target->GetBoundsInPixels().x()",
            "MouseEvent event(type, location, root_location",
            "Event::DispatcherApi(&event).set_target(target)",
            "PlatformEventSource::DispatchEvent(&event)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, dispatch)
        self.assertLess(
            dispatch.index("Event::DispatcherApi(&event).set_target(target)"),
            dispatch.index("PlatformEventSource::DispatchEvent(&event)"),
        )
        self.assertLess(
            dispatch.index(
                "window_manager_->SetCursorScreenPointInPixels(root_location)"
            ),
            dispatch.index("window_manager_->GetPointerTarget(root_location)"),
        )
        # DOM event positions map into the physical canvas backing store. Aura
        # applies the display transform when it forwards the native event, so
        # the Ozone source must not pre-convert event coordinates to DIPs.
        self.assertNotIn("GetBoundsInDIP()", dispatch)
        self.assertNotIn("GetCursorScreenPoint()", dispatch)

    def test_platform_screen_exposes_dips_while_hit_testing_stays_physical(
        self,
    ) -> None:
        manager_header = source("ui/ozone/platform/wasm/wasm_window_manager.h")
        manager = source("ui/ozone/platform/wasm/wasm_window_manager.cc")
        screen = source("ui/ozone/platform/wasm/wasm_screen.cc")

        for marker in (
            "gfx::AcceleratedWidget GetAcceleratedWidgetAtScreenPoint(\n"
            "      const gfx::Point& point_in_dip);",
            "WasmWindow* GetWindowAtScreenPointInPixels(\n"
            "      const gfx::Point& point_in_pixels);",
            "void SetDeviceScaleFactor(float device_scale_factor);",
            "void SetCursorScreenPointInPixels(const gfx::Point& point_in_pixels);",
            "void SetCursorOutsideDisplay();",
            "gfx::Point GetCursorScreenPoint() const;",
            "gfx::Point GetCursorScreenPointInPixels() const;",
            "gfx::PointF cursor_screen_point_in_dip_;",
            "float device_scale_factor_ = 1.0f;",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, manager_header)

        dip_widget_lookup = section(
            manager,
            "gfx::AcceleratedWidget WasmWindowManager::GetAcceleratedWidgetAtScreenPoint(",
            "void WasmWindowManager::SetDeviceScaleFactor",
        )
        self.assertIn(
            "gfx::ScalePoint(gfx::PointF(point_in_dip), device_scale_factor_)",
            dip_widget_lookup,
        )
        self.assertIn(
            "GetWindowAtScreenPointInPixels(point_in_pixels)",
            dip_widget_lookup,
        )
        self.assertLess(
            dip_widget_lookup.index("gfx::ScalePoint"),
            dip_widget_lookup.index("GetWindowAtScreenPointInPixels"),
        )

        cursor_set = section(
            manager,
            "void WasmWindowManager::SetCursorScreenPointInPixels(",
            "void WasmWindowManager::SetCursorOutsideDisplay",
        )
        self.assertIn("cursor_screen_point_in_dip_", cursor_set)
        self.assertIn("1.0f / device_scale_factor_", cursor_set)
        self.assertIn("gfx::ScalePoint", cursor_set)

        cursor_dip = section(
            manager,
            "gfx::Point WasmWindowManager::GetCursorScreenPoint() const",
            "gfx::Point WasmWindowManager::GetCursorScreenPointInPixels() const",
        )
        self.assertIn(
            "gfx::ToFlooredPoint(cursor_screen_point_in_dip_)", cursor_dip
        )
        cursor_pixels = section(
            manager,
            "gfx::Point WasmWindowManager::GetCursorScreenPointInPixels() const",
            "void WasmWindowManager::SetPointerFocusedWindow",
        )
        self.assertIn("cursor_screen_point_in_dip_.x() < 0", cursor_pixels)
        self.assertIn("cursor_screen_point_in_dip_.y() < 0", cursor_pixels)
        self.assertIn(
            "gfx::ScalePoint(cursor_screen_point_in_dip_, device_scale_factor_)",
            cursor_pixels,
        )
        self.assertIn(
            "cursor_screen_point_in_dip_ = gfx::PointF(-1, -1);", manager
        )
        self.assertIn("return window_manager_->GetCursorScreenPoint();", screen)
        self.assertIn(
            "return window_manager_->GetAcceleratedWidgetAtScreenPoint(point);",
            screen,
        )
        self.assertNotIn("GetCursorScreenPointInPixels()", screen)
        self.assertNotIn(
            "Host cursor position is unsupported by the M4 pointer slice", screen
        )

    def test_window_is_an_event_target_that_delegates_to_aura(self) -> None:
        header = source("ui/ozone/platform/wasm/wasm_window.h")
        window = source("ui/ozone/platform/wasm/wasm_window.cc")

        for marker in (
            "public PlatformWindow",
            "public PlatformEventDispatcher",
            "public EventTarget",
            "bool CanDispatchEvent(const PlatformEvent& event) override",
            "uint32_t DispatchEvent(const PlatformEvent& event) override",
            "bool CanAcceptEvent(const Event& event) override",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, header)
        self.assertIn("AddPlatformEventDispatcher(this)", window)
        self.assertIn("RemovePlatformEventDispatcher(this)", window)
        self.assertIn("return event.target() == this;", window)

        delegate_dispatch = section(
            window,
            "uint32_t WasmWindow::DispatchEventToDelegate",
            "void WasmWindow::ZoomWindowBounds",
        )
        for marker in (
            "DispatchEventFromNativeUiEvent",
            "PlatformWindowDelegate::DispatchEvent",
            "POST_DISPATCH_PERFORM_DEFAULT",
            "POST_DISPATCH_STOP_PROPAGATION",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, delegate_dispatch)
        self.assertNotIn("ForwardMouseEvent", window)
        self.assertNotIn("RenderWidgetHost", window)

    def test_window_manager_preserves_capture_and_visible_hit_testing(self) -> None:
        window = source("ui/ozone/platform/wasm/wasm_window.cc")
        manager = source("ui/ozone/platform/wasm/wasm_window_manager.cc")

        hide = section(
            window, "void WasmWindow::Hide", "void WasmWindow::Close"
        )
        self.assertIn("visible_ = false;", hide)
        self.assertIn("ReleaseCapture();", hide)
        self.assertIn("manager_->SetPointerCapture(this);", window)
        self.assertIn("manager_->ReleasePointerCapture(this);", window)
        self.assertIn("manager_->HasPointerCapture", window)

        capture_transfer = section(
            manager,
            "void WasmWindowManager::SetPointerCapture",
            "void WasmWindowManager::ReleasePointerCapture",
        )
        self.assertIn("old_capture->OnPointerCaptureLost();", capture_transfer)
        release_capture = section(
            manager,
            "void WasmWindowManager::ReleasePointerCapture",
            "bool WasmWindowManager::HasPointerCapture",
        )
        self.assertIn("pointer_capture_window_ = nullptr;", release_capture)
        self.assertNotIn("OnPointerCaptureLost", release_capture)

        remove_window = section(
            manager,
            "void WasmWindowManager::RemoveWindow",
            "WasmWindow* WasmWindowManager::GetWindow",
        )
        self.assertIn("pointer_capture_window_ == window", remove_window)
        self.assertIn("pointer_focused_window_ == window", remove_window)

        hit_test = section(
            manager,
            "WasmWindow* WasmWindowManager::GetWindowAtScreenPointInPixels",
            "gfx::AcceleratedWidget\nWasmWindowManager::GetAcceleratedWidgetAtScreenPoint",
        )
        for marker in (
            "stacking_order_.rbegin()",
            "window->IsVisible()",
            "GetBoundsInPixels().Contains(point_in_pixels)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, hit_test)

        pointer_target = section(
            manager,
            "WasmWindow* WasmWindowManager::GetPointerTarget",
            "}  // namespace ui",
        )
        self.assertIn("if (pointer_capture_window_)", pointer_target)
        self.assertIn("return pointer_capture_window_;", pointer_target)
        self.assertIn("GetWindowAtScreenPointInPixels(point)", pointer_target)
        self.assertLess(
            pointer_target.index("return pointer_capture_window_;"),
            pointer_target.index("GetWindowAtScreenPointInPixels(point)"),
        )

    def test_cursor_reaches_the_host_canvas_through_aura_and_ozone(self) -> None:
        shell = source("content/shell/browser/shell_platform_data_aura.cc")
        window = source("ui/ozone/platform/wasm/wasm_window.cc")
        bridge = source("ui/ozone/platform/wasm/wasm_host_bridge.js")
        host = source("tools/wasm/host/content_shell_host.js")
        fixture = source("tools/wasm/testdata/m4_ozone_input_page.html")

        for marker in (
            "class ShellNativeCursorManager final",
            "wm::CursorManager",
            "aura::client::SetCursorClient(host_->window(), cursor_manager_.get())",
            "cursor_loader_.SetPlatformCursor(&cursor)",
            "host_->SetCursor(cursor)",
            "aura::client::SetCursorClient(host_->window(), nullptr)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, shell)

        cursor_setter = section(
            window,
            "void WasmWindow::SetCursor",
            "void WasmWindow::MoveCursorTo",
        )
        for marker in (
            "BitmapCursor::FromPlatformCursor",
            "chromium_wasm_report_ozone_cursor(cursor_type)",
            "last_reported_cursor_type_",
            "host cannot present raster custom cursors",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, cursor_setter)
        self.assertNotIn(
            "Host cursor updates are unsupported by the M4 pointer slice",
            cursor_setter,
        )

        for marker in (
            "chromium_wasm_report_ozone_cursor__proxy: 'sync'",
            "cursorType < -1",
            "cursorType > 53",
            "isExactCursorType(cursorType)",
            "cursorType >= 20 && cursorType <= 28",
            "cursorType >= 43",
            "const delivered = bridge.reportOzoneCursor({",
            "return delivered === true &&",
            "ChromiumWasmHostBridge.isExactCursorType(cursorType) ? 1 : 0;",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, bridge)

        for marker in (
            "function ozoneCursorDescriptor(cursorType)",
            'return {cssCursor: "pointer", exact: true};',
            "reportOzoneCursor(report)",
            "_reportOzoneCursor(value)",
            "this.#canvas.style.cursor = descriptor.cssCursor;",
            "return true;",
            "return false;",
            "ozoneCursor: this.#ozoneCursor",
            "M4_CURSOR_TYPE_HAND",
            "hasM4PointerLinkHover",
            "cursorDelivered",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, host)

        self.assertIn("cursor: pointer;", fixture)
        self.assertIn("pointerMoveTrace", fixture)
        self.assertIn('targetId: event.target?.id || null', fixture)

    def test_host_pointer_abi_uses_public_ozone_not_the_m3_renderer_hook(
        self,
    ) -> None:
        api = source("content/shell/browser/wasm_host_api.cc")

        m4_dispatch = section(
            api,
            "void DispatchDomPointerOnUiThread",
            "void LoadUrlOnUiThread",
        )
        for marker in (
            "GetInputInjectorOnUiThread",
            "input_injector->MoveCursorTo",
            "ui::EventFlags button",
            "input_injector->InjectMouseButton(button, /*down=*/true)",
            "input_injector->InjectMouseButton(button, /*down=*/false)",
            "DomPointerEventType::kMove",
            "DomPointerEventType::kDown",
            "DomPointerEventType::kUp",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, m4_dispatch)
        for forbidden in (
            "RenderWidgetHost",
            "WebMouseEvent",
            "ForwardMouseEvent",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, m4_dispatch)

        pointer_export = section(
            api,
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_pointer",
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_load_url",
        )
        for marker in (
            "DomPointerEventType::kMove",
            "DomPointerEventType::kUp",
            "(button != 0 && button != 1 && button != 2)",
            "ui::EF_MIDDLE_MOUSE_BUTTON",
            "ui::EF_RIGHT_MOUSE_BUTTON",
            "x < 0 || y < 0",
            "PostHostCommand",
            "DispatchDomPointerOnUiThread",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, pointer_export)

        initialize = section(
            api, "void InitializeWasmHostApi", "void ShutdownWasmHostApi"
        )
        self.assertIn(
            "ui::OzonePlatform::GetInstance()->CreateSystemInputInjector()",
            initialize,
        )
        self.assertIn("state.SetInputInjector(std::move(input_injector));", initialize)
        self.assertIn(
            '#include "ui/ozone/platform/wasm/wasm_event_source.h"', api
        )
        self.assertIn("ui::DispatchWasmMouseExit()", api)
        self.assertNotIn("WasmSystemInputInjector", api)

        legacy_click = section(
            api, "void ClickOnUiThread", "void DispatchDomPointerOnUiThread"
        )
        self.assertIn("widget->ForwardMouseEvent(mouse_down)", legacy_click)
        self.assertIn("widget->ForwardMouseEvent(mouse_up)", legacy_click)

    def test_dom_listener_and_m4_runner_do_not_use_m3_direct_click(
        self,
    ) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        fixture = source("tools/wasm/testdata/m4_ozone_input_page.html")
        runner = source("tools/wasm/run_m4_ozone_smoke.py")
        cdp = source("tools/wasm/m4_cdp.py")

        handler = section(
            host, "  #handleM4PointerEvent", "  #disableM4PointerInput"
        )
        for marker in (
            "event.isTrusted === true",
            'event.pointerType !== "mouse"',
            "event.isPrimary !== true",
            "chromium_wasm_host_pointer",
            "setPointerCapture(pointerId)",
            "usedCapturedPoint",
            "type === \"cancel\"",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, handler)

        point_mapper = section(
            host,
            "  #canvasPointForPointerEvent(event) {",
            "  #releaseM4PointerCapture",
        )
        for marker in (
            "const contentWidth = this.#canvas.clientWidth;",
            "const contentHeight = this.#canvas.clientHeight;",
            "(cssX * this.#canvas.width) / contentWidth",
            "(cssY * this.#canvas.height) / contentHeight",
        ):
            with self.subTest(point_mapper_marker=marker):
                self.assertIn(marker, point_mapper)

        cancellation = section(
            host, "  #cancelActiveM4Pointer", "  #handleM4PointerEvent"
        )
        self.assertIn('"release-queued"', cancellation)
        self.assertNotIn('? "released"', cancellation)

        listeners = section(host, "  enableM4PointerInput()", "  #heartbeat()")
        for marker in (
            '"pointermove", "move"',
            '"pointerdown", "down"',
            '"pointerup", "up"',
            '"pointercancel", "cancel"',
            '"pointerleave"',
            '"lostpointercapture"',
            '"visibilitychange"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, listeners)

        m4_runner = section(
            host,
            "async function runM4OzonePointerSmokeFromQuery()",
            "export async function runContentShellSmokeFromQuery",
        )
        self.assertIn("host.enableM4PointerInput()", m4_runner)
        self.assertIn("window.__chromiumWasmM4State", m4_runner)
        self.assertNotIn("injectInput(", m4_runner)
        self.assertNotIn("chromium_wasm_host_click", m4_runner)
        self.assertIn("runM3SmokeFromQuery()", host)
        self.assertIn("runM4OzonePointerSmokeFromQuery()", host)

        for marker in (
            "__chromiumWasmM4Probe",
            "event.isTrusted",
            "fontReady",
            "timerTicks",
            "#m4-activated",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, fixture)
        self.assertIn("client.dispatch_primary_click", runner)
        self.assertIn("Input.dispatchMouseEvent", cdp)
        self.assertNotIn("chromium_wasm_host_click", runner)
        self.assertNotIn("chromium_wasm_host_click", cdp)


if __name__ == "__main__":
    unittest.main()
