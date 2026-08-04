#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Static contracts for bounded 1x/2x Ozone resize and Blink reflow."""

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


class M4OzoneResizeContractTest(unittest.TestCase):
    def test_ozone_screen_updates_the_live_primary_display_before_window_resize(
        self,
    ) -> None:
        header = source("ui/ozone/platform/wasm/wasm_screen.h")
        screen = source("ui/ozone/platform/wasm/wasm_screen.cc")
        api = source("content/shell/browser/wasm_host_api.cc")

        for marker in (
            "base/sequence_checker.h",
            "static bool UpdatePrimaryDisplayForHostResize(",
            "const gfx::Size& size,",
            "float device_scale_factor);",
            "static WasmScreen* instance_;",
            "SEQUENCE_CHECKER(sequence_checker_);",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, header)

        update = section(
            screen,
            "bool WasmScreen::UpdatePrimaryDisplayForHostResize(",
            "const std::vector<display::Display>& WasmScreen::GetAllDisplays",
        )
        for marker in (
            "if (!screen)",
            "DCHECK_CALLED_ON_VALID_SEQUENCE(screen->sequence_checker_)",
            "CHECK(!size.IsEmpty())",
            "CHECK(device_scale_factor == 1.0f || device_scale_factor == 2.0f)",
            "screen->window_manager_->SetDeviceScaleFactor(device_scale_factor)",
            "display::Display display = screen->GetPrimaryDisplay()",
            "display.SetScaleAndBounds(device_scale_factor, gfx::Rect(size))",
            "display.set_work_area(display.bounds())",
            "screen->display_list_.UpdateDisplay(",
            "display::DisplayList::Type::PRIMARY",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, update)
        self.assertLess(
            update.index("SetDeviceScaleFactor(device_scale_factor)"),
            update.index("screen->display_list_.UpdateDisplay("),
        )

        resize = section(
            api,
            "void ResizeOnUiThread(const gfx::Size& logical_size,",
            "void ClickOnUiThread",
        )
        for marker in (
            "const gfx::Size& physical_size,",
            "float device_scale_factor)",
            "physical_size, device_scale_factor",
            'ReportFatal("M4 host resize has no live ozone_wasm screen")',
            "window->GetHost()->SetBoundsInPixels(gfx::Rect(physical_size))",
            "shell->ResizeWebContentForTests(logical_size)",
            "GetWasmHostState().SetViewportSizeOnUiThread(physical_size)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, resize)
        self.assertLess(
            resize.index("ui::WasmScreen::UpdatePrimaryDisplayForHostResize"),
            resize.index("window->GetHost()->SetBoundsInPixels"),
        )
        self.assertLess(
            resize.index("window->GetHost()->SetBoundsInPixels"),
            resize.index("shell->ResizeWebContentForTests"),
        )
        # WindowTreeHost bounds observers can tear down the host or Shell;
        # retaining the pre-bounds Shell pointer would make this resize path
        # unsafe even though the display update itself is correct.
        self.assertGreater(
            resize.rindex("shell = GetSingleShell();"),
            resize.index("window->GetHost()->SetBoundsInPixels"),
        )
        self.assertLess(
            resize.rindex("shell = GetSingleShell();"),
            resize.index("shell->ResizeWebContentForTests"),
        )

        resize_export = section(
            api,
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_resize(",
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_click",
        )
        for marker in (
            "(device_pixel_ratio != 1.0 && device_pixel_ratio != 2.0)",
            "const int device_scale_factor = static_cast<int>(device_pixel_ratio);",
            "const int64_t physical_width =",
            "static_cast<int64_t>(width) * device_scale_factor",
            "const int64_t physical_height =",
            "static_cast<int64_t>(height) * device_scale_factor",
            "physical_width > content::kMaximumCanvasDimension",
            "physical_height > content::kMaximumCanvasDimension",
            "physical_width * physical_height * 4",
            "&content::ResizeOnUiThread, gfx::Size(width, height)",
            "gfx::Size(static_cast<int>(physical_width)",
            "static_cast<float>(device_scale_factor)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, resize_export)

    def test_host_keeps_css_dips_separate_from_the_physical_canvas(self) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        surface = source("ui/ozone/platform/wasm/wasm_surface_ozone_canvas.cc")

        resize = section(
            host,
            "  async resize(width, height, devicePixelRatio = 1) {",
            "  async loadURL(url) {",
        )
        for marker in (
            "devicePixelRatio !== 1 && devicePixelRatio !== 2",
            "const physicalWidth = width * devicePixelRatio;",
            "const physicalHeight = height * devicePixelRatio;",
            "physicalWidth * physicalHeight * 4 * 2 > 128 * 1024 * 1024",
            "this.#canvas.width = physicalWidth;",
            "this.#canvas.height = physicalHeight;",
            "this.#canvas.style.width = `${width}px`;",
            "this.#canvas.style.height = `${height}px`;",
            "this.#currentDevicePixelRatio = devicePixelRatio;",
            "physicalWidth,",
            "physicalHeight,",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, resize)

        resize_canvas = surface.split(
            "void WasmSurfaceOzoneCanvas::ResizeCanvas(", 1
        )[1]
        self.assertIn("scale == 1.0f || scale == 2.0f", resize_canvas)
        self.assertNotIn("CHECK_EQ(scale, 1.0f)", resize_canvas)

    def test_fixture_observes_only_native_viewport_resize_and_reflow(self) -> None:
        fixture = source("tools/wasm/testdata/m4_ozone_resize_page.html")

        for marker in (
            "chromium-wasm-m4-ozone-resize-v1",
            "window.addEventListener(\"resize\"",
            "event.isTrusted",
            "window.innerWidth",
            "window.innerHeight",
            "document.documentElement.clientWidth",
            "document.documentElement.clientHeight",
            "screen.width",
            "screen.height",
            "screen.availWidth",
            "screen.availHeight",
            "window.devicePixelRatio",
            "matchMedia",
            "gridColumns",
            "gridWidth",
            "firstCard",
            "secondCard",
            "resizeEvents",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, fixture)
        for forbidden in (
            "window.resizeTo(",
            "dispatchEvent(",
            "ResizeObserver(",
            "event.preventDefault()",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, fixture)

    def test_host_server_and_runner_keep_the_resize_case_bounded_and_separate(
        self,
    ) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        server = source("tools/wasm/m3_content_server.py")
        runner = source("tools/wasm/run_m4_ozone_smoke.py")

        for marker in (
            'const M4_RESIZE_CASE = "ozone_resize_m4"',
            'const M4_RESIZE_FIXTURE = "chromium-wasm-m4-ozone-resize-v1"',
            "const M4_RESIZE_NARROW_WIDTH = 640",
            "const M4_RESIZE_NARROW_HEIGHT = 480",
            "async function runM4OzoneResizeSmokeFromQuery()",
            "window.__chromiumWasmM4ResizeState",
            "const narrowResize = await host.resize(",
            "M4_RESIZE_NARROW_WIDTH, M4_RESIZE_NARROW_HEIGHT, 1",
            "await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1)",
            "resizeProof",
            "resizeEvents",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, host)

        for marker in (
            'M4_RESIZE_CASE = "ozone_resize_m4"',
            'M4_RESIZE_FIXTURE = M3_TESTDATA_DIR / "m4_ozone_resize_page.html"',
            '"/__m3__/m4-resize-fixture.html": M4_RESIZE_FIXTURE',
            "def m4_resize_smoke_url(",
            "def validate_m4_resize_result(",
            "resizeProof",
            "resizeEvents",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, server)

        for marker in (
            '"resize",',
            "M4_RESIZE_CASE",
            "m4_resize_smoke_url(",
            "validate_m4_resize_result(result, expected_versions=versions)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, runner)

        resize_runner = section(
            runner,
            'if args.input == "resize":\n            # This case drives',
            "expected_url_prefix =",
        )
        self.assertIn("wait_for_host_resize_result", resize_runner)
        self.assertIn("wait_for_result(", resize_runner)
        self.assertNotIn("wait_for_page_client", resize_runner)
        self.assertNotIn("client.dispatch", resize_runner)
        resize_runner = section(
            runner,
            'if args.input == "resize":\n            # This case drives only',
            "        expected_url_prefix = url.split(\"?\", 1)[0]",
        )
        self.assertIn("wait_for_result(", resize_runner)
        self.assertIn(
            "validate_m4_resize_result(result, expected_versions=versions)",
            resize_runner,
        )
        self.assertNotIn("wait_for_page_client", resize_runner)
        self.assertNotIn("client.dispatch", resize_runner)


if __name__ == "__main__":
    unittest.main()
