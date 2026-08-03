#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Static contracts for trusted DOM-wheel delivery through Ozone and Aura."""

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


class M4OzoneWheelContractTest(unittest.TestCase):
    def test_system_injector_dispatches_precise_wheel_records(self) -> None:
        event_source = source("ui/ozone/platform/wasm/wasm_event_source.cc")

        injector = section(
            event_source,
            "void InjectMouseWheel(int delta_x, int delta_y) override",
            "void InjectKeyEvent(DomCode physical_key",
        )
        for marker in (
            "if (delta_x == 0 && delta_y == 0)",
            "event_source_->DispatchMouseWheelEvent(",
            "location_, gfx::Vector2d(delta_x, delta_y)",
            "button_flags_ | EF_PRECISION_SCROLLING_DELTA",
            "device_id_",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, injector)
        self.assertNotIn("NOTIMPLEMENTED_LOG_ONCE", injector)

    def test_wheel_event_source_uses_normal_platform_dispatch(self) -> None:
        header = source("ui/ozone/platform/wasm/wasm_event_source.h")
        event_source = source("ui/ozone/platform/wasm/wasm_event_source.cc")

        for marker in (
            "ui/gfx/geometry/vector2d.h",
            "bool DispatchMouseWheelEvent(const gfx::PointF& screen_location,",
            "const gfx::Vector2d& offset",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, header)

        dispatch = section(
            event_source,
            "bool WasmPlatformEventSource::DispatchMouseWheelEvent",
            "std::unique_ptr<SystemInputInjector> "
            "CreateWasmSystemInputInjector",
        )
        for marker in (
            "PlatformEventSource::ShouldIgnoreNativePlatformEvents()",
            "std::isfinite(screen_location.x())",
            "std::isfinite(screen_location.y())",
            "(offset.x() == 0 && offset.y() == 0)",
            "window_manager_->GetPointerTarget(root_location)",
            "MouseWheelEvent event(offset, location, root_location",
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

    def test_host_wheel_abi_inverts_dom_sign_and_never_bypasses_ozone(
        self,
    ) -> None:
        api = source("content/shell/browser/wasm_host_api.cc")

        dispatch = section(
            api,
            "void DispatchDomWheelOnUiThread",
            "void LoadUrlOnUiThread",
        )
        for marker in (
            "GetInputInjectorOnUiThread",
            "input_injector->MoveCursorTo(gfx::PointF(location))",
            "DOM WheelEvent deltas are positive for right/down.",
            "input_injector->InjectMouseWheel(-dom_delta.x(), -dom_delta.y())",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, dispatch)
        for forbidden in (
            "RenderWidgetHost",
            "WebMouseWheelEvent",
            "ForwardWheelEvent",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, dispatch)

        wheel_export = section(
            api,
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_wheel",
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_load_url",
        )
        for marker in (
            "x < 0 || y < 0",
            "(delta_x == 0 && delta_y == 0)",
            "std::numeric_limits<int>::min()",
            "PostHostCommand",
            "DispatchDomWheelOnUiThread",
            "gfx::Vector2d(delta_x, delta_y)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, wheel_export)
        self.assertIn("#include <limits>", api)
        self.assertIn('"ui/gfx/geometry/vector2d.h"', api)

    def test_host_rejects_unsupported_wheels_and_buffers_residuals(
        self,
    ) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        handler = section(
            host,
            "  #handleM4WheelEvent(event)",
            "  #disableM4WheelInput()",
        )

        for marker in (
            "event.isTrusted === true",
            "!event.cancelable",
            "event.altKey || event.ctrlKey || event.metaKey || event.shiftKey",
            "event.deltaMode !== 0",
            "Number.isFinite(domDeltaX)",
            "Number.isFinite(domDeltaY)",
            "Math.trunc(accumulatedX)",
            "Math.trunc(accumulatedY)",
            "this.#wheelResidualX",
            "this.#wheelResidualY",
            '"FRACTIONAL_DELTA_BUFFERED"',
            "chromium_wasm_host_wheel",
            "record.queued = result === 1",
            "event.preventDefault()",
            "this.#lastQueuedWheel = record",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, handler)
        self.assertLess(
            handler.index("record.queued = result === 1"),
            handler.index("this.#lastQueuedWheel = record"),
        )
        self.assertIn(
            'this.#canvas.addEventListener('
            '"wheel", listener, {passive: false});',
            host,
        )

    def test_fixture_requires_native_trusted_nested_scroll_evidence(
        self,
    ) -> None:
        fixture = source("tools/wasm/testdata/m4_ozone_wheel_page.html")

        for marker in (
            "#wheel-outer",
            "#wheel-inner",
            "overflow: auto;",
            "overscroll-behavior: contain;",
            'inner.addEventListener("wheel", (event) => {',
            "wheelEvents.trusted = event.isTrusted;",
            "wheelEvents.deltaMode = event.deltaMode;",
            "wheelEvents.deltaX = event.deltaX;",
            "wheelEvents.deltaY = event.deltaY;",
            "inner.scrollTop",
            "outer.scrollTop",
            "document.scrollingElement.scrollTop",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, fixture)
        self.assertNotIn("event.preventDefault()", fixture)
        self.assertNotIn("scrollTop =", fixture)

    def test_runner_and_cdp_drive_the_distinct_trusted_wheel_case(
        self,
    ) -> None:
        cdp = source("tools/wasm/m4_cdp.py")
        runner = source("tools/wasm/run_m4_ozone_smoke.py")
        server = source("tools/wasm/m3_content_server.py")

        cdp_wheel = section(
            cdp,
            "def dispatch_mouse_wheel(",
            "\n\ndef wait_for_page_client",
        )
        for marker in (
            '"Input.dispatchMouseEvent"',
            '"type": "mouseWheel"',
            '"deltaX": delta_x',
            '"deltaY": delta_y',
            '"pointerType": "mouse"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, cdp_wheel)

        for marker in (
            '"printable-key",',
            '"ime-bridge",',
            '"focus",',
            "M4_WHEEL_CASE",
            '"awaiting-dom-wheel"',
            "m4_wheel_smoke_url(",
            "client.dispatch_mouse_wheel(click_x, click_y, 0.0, 160.0)",
            "validate_m4_wheel_result(result, expected_versions=versions)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, runner)

        for marker in (
            'M4_WHEEL_CASE = "ozone_wheel_m4"',
            'M4_WHEEL_FIXTURE = M3_TESTDATA_DIR / "m4_ozone_wheel_page.html"',
            '"/__m3__/m4-wheel-fixture.html": M4_WHEEL_FIXTURE',
            "def m4_wheel_smoke_url(",
            "def validate_m4_wheel_result(",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, server)


if __name__ == "__main__":
    unittest.main()
