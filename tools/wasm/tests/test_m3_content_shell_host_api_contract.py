#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M3ContentShellHostApiContractTest(unittest.TestCase):
    def test_content_shell_uses_the_proven_v8_simulator_stack_budget(
        self,
    ) -> None:
        build = source("content/shell/BUILD.gn")

        self.assertIn("-sSTACK_SIZE=2097152", build)

    def test_responsiveness_window_starts_at_committed_navigation(
        self,
    ) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        navigation = host.split("_reportNavigation(value)", 1)[1].split(
            "_reportPageProbe(value)", 1
        )[0]

        self.assertIn(
            'this.#resetHeartbeatWindow("data-navigation-committed")',
            navigation,
        )
        self.assertGreater(
            navigation.index("#resetHeartbeatWindow"),
            navigation.index(
                'this.#navigation = {committed: true, scheme: "data"}'
            ),
        )
        self.assertIn("if (this.#heartbeatAnchor === null)", host)
        self.assertIn("timerDelta: 0", host)
        self.assertIn("animationFrameDelta: 0", host)

    def test_host_heap_access_uses_an_exported_growth_safe_view(self) -> None:
        build = source("content/shell/BUILD.gn")
        host = source("tools/wasm/host/content_shell_host.js")

        self.assertIn(
            "-sEXPORTED_RUNTIME_METHODS=ccall,HEAPU8",
            build,
        )
        # Array arguments used by the IME ABI share the same post-malloc,
        # growth-safe heap view as existing string arguments.
        self.assertIn("const heap = this.#module.HEAPU8;", host)
        self.assertIn("heap.set(encoded, pointer);", host)
        self.assertIn(
            'argumentType !== "string" && argumentType !== "array"', host
        )
        self.assertIn(
            "Fetch HEAPU8 after malloc because memory growth invalidates",
            host,
        )

    def test_host_commands_copy_inputs_then_post_to_the_ui_sequence(
        self,
    ) -> None:
        api = source("content/shell/browser/wasm_host_api.cc")
        main_parts = source(
            "content/shell/browser/shell_browser_main_parts.cc"
        )

        for export in (
            "chromium_wasm_host_resize",
            "chromium_wasm_host_load_url",
            "chromium_wasm_host_click",
            "chromium_wasm_host_deactivate",
            "chromium_wasm_host_shutdown",
        ):
            with self.subTest(export=export):
                self.assertIn(f"EMSCRIPTEN_KEEPALIVE int {export}", api)
        self.assertIn("task_runner->PostTask", api)
        self.assertIn("std::string(data_url, length)", api)
        self.assertIn("url.SchemeIs(url::kDataScheme)", api)
        self.assertIn("DCHECK_CURRENTLY_ON(BrowserThread::UI)", api)
        self.assertIn("InitializeWasmHostApi();", main_parts)
        self.assertIn("ShutdownWasmHostApi();", main_parts)

    def test_host_clicks_follow_ui_sequence_viewport_updates(self) -> None:
        api = source("content/shell/browser/wasm_host_api.cc")

        state = api.split("class WasmHostState", 1)[1].split(
            "WasmHostState& GetWasmHostState", 1
        )[0]
        resize = api.split("void ResizeOnUiThread", 1)[1].split(
            "void ClickOnUiThread", 1
        )[0]
        click = api.split("void ClickOnUiThread", 1)[1].split(
            "void LoadUrlOnUiThread", 1
        )[0]
        click_export = api.split(
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_click", 1
        )[1].split(
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_load_url", 1
        )[0]

        self.assertIn("SetViewportSizeOnUiThread", state)
        self.assertIn("ContainsViewportPointOnUiThread", state)
        self.assertIn("DCHECK_CURRENTLY_ON(BrowserThread::UI)", state)
        self.assertIn("gfx::Size viewport_size_;", state)
        self.assertIn(
            "GetWasmHostState().SetViewportSizeOnUiThread(size)", resize
        )
        self.assertGreater(
            resize.index("SetViewportSizeOnUiThread"),
            resize.index("ResizeWebContentForTests"),
        )
        self.assertIn(
            "ContainsViewportPointOnUiThread(location)", click
        )
        self.assertLess(
            click.index("ContainsViewportPointOnUiThread"),
            click.index("widget->ForwardMouseEvent(mouse_down)"),
        )
        self.assertIn("if (button != 0 || x < 0 || y < 0)", click_export)
        self.assertNotIn("kM3Width", api)
        self.assertNotIn("kM3Height", api)

    def test_m3_legacy_click_path_stays_separate_from_m4_input(
        self,
    ) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        api = source("content/shell/browser/wasm_host_api.cc")
        click = api.split("void ClickOnUiThread", 1)[1].split(
            "void DispatchDomPointerOnUiThread", 1
        )[0]

        self.assertIn("chromium_wasm_host_click", host)
        self.assertIn("CLICK_POSTED", host)
        self.assertIn("widget->ForwardMouseEvent(mouse_down)", click)
        self.assertIn("widget->ForwardMouseEvent(mouse_up)", click)
        self.assertIn("web_contents->Focus()", click)
        self.assertNotIn("SystemInputInjector", click)
        self.assertNotIn("chromium_wasm_host_key", click)

    def test_page_probes_are_bound_to_the_committed_navigation(self) -> None:
        api = source("content/shell/browser/wasm_host_api.cc")

        navigation_start = api.split("void DidStartNavigation", 1)[1].split(
            "void DidFinishNavigation", 1
        )[0]
        navigation_finish = api.split("void DidFinishNavigation", 1)[1].split(
            "void DocumentOnLoadCompletedInPrimaryMainFrame", 1
        )[0]
        probe = api.split("void ProbePage()", 1)[1].split(
            "bool probe_in_flight_", 1
        )[0]
        destroyed = api.split("void WebContentsDestroyed()", 1)[1].split(
            "private:", 1
        )[0]

        self.assertIn(
            "weak_ptr_factory_.InvalidateWeakPtrs();", navigation_start
        )
        self.assertIn("++navigation_generation_;", navigation_start)
        self.assertLess(
            api.index("void DidStartNavigation"),
            api.index("void DidFinishNavigation"),
        )
        self.assertNotIn("SchemeIs(url::kDataScheme)", navigation_start)
        self.assertIn("SchemeIs(url::kDataScheme)", navigation_finish)
        self.assertIn("navigation_generation_", probe)
        self.assertIn(
            "void OnPageProbe(uint64_t navigation_generation", probe
        )
        self.assertIn(
            "navigation_generation != navigation_generation_", probe
        )
        self.assertIn(
            "weak_ptr_factory_.InvalidateWeakPtrs();", destroyed
        )

    def test_shutdown_requires_content_and_runtime_exit_reports(self) -> None:
        main = source("content/shell/app/shell_main.cc")
        host = source("tools/wasm/host/content_shell_host.js")
        bridge = source("ui/ozone/platform/wasm/wasm_host_bridge.js")

        self.assertIn("chromium_wasm_report_process_exit(exit_code)", main)
        self.assertIn("this.#processExitPromise", host)
        self.assertIn("this.#runtimeExitPromise", host)
        self.assertIn("noExitRuntime: false", host)
        self.assertIn("shutdown:complete", host)
        self.assertIn("reportProcessExit", bridge)

    def test_resize_control_proves_a_real_surface_transition(self) -> None:
        api = source("content/shell/browser/wasm_host_api.cc")
        host = source("tools/wasm/host/content_shell_host.js")

        self.assertIn("kMaximumCanvasDimension", api)
        self.assertIn("kMaximumCanvasStorageBytes", api)
        self.assertIn("await host.resize(640, 480, 1)", host)
        self.assertIn("did not present the 640x480 resize probe", host)
        self.assertIn("did not restore the 800x600 surface", host)


if __name__ == "__main__":
    unittest.main()
