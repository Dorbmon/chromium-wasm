#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the ordinary Chrome Wasm host shutdown bridge."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def _source_set_body(build_file: str, target: str) -> str:
    match = re.search(
        rf'\bsource_set\s*\(\s*"{re.escape(target)}"\s*\)', build_file
    )
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


class M6WasmBrowserHostLifecycleContractTest(unittest.TestCase):
    def test_bridge_exports_one_shot_request_and_invalidates_queued_work(self) -> None:
        header = source("chrome/browser/wasm/wasm_browser_host_lifecycle.h")
        implementation = source(
            "chrome/browser/wasm/wasm_browser_host_lifecycle.cc"
        )

        for expected in (
            "InitializeWasmBrowserHostLifecycle(",
            "base::RepeatingClosure request_shutdown",
            "ShutdownWasmBrowserHostLifecycle();",
            "chromium_wasm_browser_host_request_shutdown",
            "EMSCRIPTEN_KEEPALIVE",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, header + implementation)

        for expected in (
            "accepting_shutdown_requests_",
            "shutdown_requested_",
            "++generation_;",
            "task_runner_->PostTask(",
            "RunShutdownOnUiThread",
            "generation != generation_",
            "request_shutdown.Run();",
            "request_shutdown_.Reset();",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, implementation)

        self.assertLess(
            implementation.index("shutdown_requested_ = true;"),
            implementation.index("task_runner_->PostTask("),
        )
        self.assertLess(
            implementation.index("ShutdownOnUiThread"),
            implementation.index("chromium_wasm_browser_host_request_shutdown"),
        )

        for forbidden in (
            "Browser*",
            "SystemInputInjector",
            "OpenURL",
            "OpenGURL",
            '#include "content/public/browser/web_contents.h"',
            '#include "chrome/browser/wasm/wasm_browser_host_input.h"',
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, header + implementation)

    def test_main_parts_initializes_and_shuts_down_bridge_around_normal_lifecycle(self) -> None:
        implementation = source("chrome/browser/wasm/wasm_browser_main_parts.cc")

        normal_start = implementation.index("InitializeWasmBrowserHostLifecycle(")
        normal_end = implementation.index(
            "void WasmBrowserMainParts::WillRunMainMessageLoop", normal_start
        )
        normal_body = implementation[normal_start:normal_end]
        self.assertIn("&WasmBrowserMainParts::RequestShutdown", normal_body)
        self.assertIn("browser_lifecycle_->Initialize();", normal_body)
        self.assertIn("kWasmNormalBrowserReadyMarker", normal_body)
        self.assertNotIn("browser_lifecycle_smoke_requested_ = true", normal_body)

        post_main = implementation.index("void WasmBrowserMainParts::PostMainMessageLoopRun")
        post_main_body = implementation[
            post_main:implementation.index(
                "bool WasmBrowserMainParts::PreflightResources", post_main
            )
        ]
        self.assertLess(
            post_main_body.index("ShutdownWasmBrowserHostLifecycle();"),
            post_main_body.index("ShutdownWasmBrowserHostInput();"),
        )

    def test_target_is_main_parts_only_and_has_no_browser_or_ozone_graph(self) -> None:
        build = source("chrome/browser/wasm/BUILD.gn")
        target = _source_set_body(build, "wasm_browser_host_lifecycle")
        main_parts = _source_set_body(build, "wasm_browser_main_parts")

        self.assertIn('visibility = [ ":wasm_browser_main_parts" ]', target)
        self.assertIn('"//content/public/browser"', target)
        self.assertIn('":wasm_browser_host_lifecycle",', main_parts)
        for forbidden in (
            '":wasm_browser",',
            '":wasm_browser_host_input",',
            "//chrome/browser/ui:ui",
            "//ui/ozone",
            "//ui/views",
            "//content/public/browser/web_contents",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, target)


if __name__ == "__main__":
    unittest.main()
