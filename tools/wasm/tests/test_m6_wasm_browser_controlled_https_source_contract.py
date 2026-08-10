#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Source contracts for the bounded M6 Chrome HTTPS/WISP UI smoke."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def source_set_body(build: str, target: str) -> str:
    match = re.search(
        rf'\bsource_set\s*\(\s*"{re.escape(target)}"\s*\)', build
    )
    if not match:
        raise AssertionError(f"missing source set {target!r}")
    opening_brace = build.find("{", match.end())
    if opening_brace < 0:
        raise AssertionError(f"missing opening brace for {target!r}")

    depth = 0
    for index in range(opening_brace, len(build)):
        if build[index] == "{":
            depth += 1
        elif build[index] == "}":
            depth -= 1
            if depth == 0:
                return build[opening_brace + 1 : index]
    raise AssertionError(f"missing closing brace for {target!r}")


class M6WasmBrowserControlledHttpsSourceContractTest(unittest.TestCase):
    def test_switch_runs_before_the_general_browser_smoke(self) -> None:
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")

        switch = (
            'constexpr char kWasmBrowserControlledHttpsSmokeSwitch[] =\n'
            '    "wasm-browser-controlled-https-smoke";'
        )
        run = "chrome::RunWasmBrowserControlledHttpsSmoke(profile_.get())"
        self.assertIn(switch, main_parts)
        self.assertIn(run, main_parts)
        self.assertLess(main_parts.index(run), main_parts.index(
            "chrome::RunWasmBrowserSmoke(profile_.get())"
        ))

        branch_start = main_parts.index(run) - 800
        branch_end = main_parts.index(run) + 600
        branch = main_parts[branch_start:branch_end]
        self.assertIn("RequestShutdown();", branch)
        self.assertIn("return content::RESULT_CODE_NORMAL_EXIT;", branch)

    def test_production_rejects_the_test_switch_without_test_registration(
        self,
    ) -> None:
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        entry_point = source("chrome/app/chrome_main_wasm.cc")
        mode_source = source(
            "chrome/browser/wasm/wasm_m6_controlled_https_test_mode.cc"
        )

        run = "chrome::RunWasmBrowserControlledHttpsSmoke(profile_.get())"
        run_index = main_parts.index(run)
        switch_branch = main_parts[run_index - 800:run_index + len(run)]
        self.assertIn("IsWasmM6ControlledHttpsTestModeEnabled()", switch_branch)
        self.assertIn("CHROME_RESULT_CODE_UNSUPPORTED_PARAM", switch_branch)
        self.assertLess(
            switch_branch.index("IsWasmM6ControlledHttpsTestModeEnabled()"),
            switch_branch.index("RunWasmBrowserControlledHttpsSmoke"),
        )

        self.assertIn("static std::atomic_bool enabled(false);", mode_source)
        self.assertIn("std::memory_order_release", mode_source)
        self.assertIn("std::memory_order_acquire", mode_source)
        test_guard_start = entry_point.index(
            "#if defined(CHROME_WASM_M6_CONTROLLED_HTTPS_TEST)",
            entry_point.index("base::CommandLine::Init"),
        )
        test_guard_end = entry_point.index("#endif", test_guard_start)
        test_guard = entry_point[test_guard_start:test_guard_end]
        self.assertIn("InstallWasmM6TestTrustRoot();", test_guard)
        self.assertIn("EnableWasmM6ControlledHttpsTestMode();", test_guard)
        self.assertLess(
            test_guard.index("InstallWasmM6TestTrustRoot();"),
            test_guard.index("EnableWasmM6ControlledHttpsTestMode();"),
        )

    def test_url_boundary_is_exact_and_transport_is_real(self) -> None:
        smoke = source("chrome/browser/wasm/wasm_browser_smoke.cc")

        for required in (
            '"wasm-browser-controlled-https-url"',
            'constexpr char kControlledHttpsHost[] = "a.test";',
            'constexpr char kControlledHttpsPath[] = "/m5/m6-ui";',
            "url.SchemeIs(url::kHttpsScheme)",
            "CHECK(url.has_port());",
            "CHECK_GT(url.EffectiveIntPort(), 0);",
            "CHECK_LE(url.EffectiveIntPort(), 65535);",
            "CHECK(!url.has_username());",
            "CHECK(!url.has_password());",
            "CHECK(!url.has_query());",
            "CHECK(!url.has_ref());",
            "CHECK_EQ(url.path(), kControlledHttpsPath);",
        ):
            with self.subTest(required=required):
                self.assertIn(required, smoke)

        run_start = smoke.index("bool RunWasmBrowserControlledHttpsSmoke(")
        run = smoke[run_start:]
        observer_start = smoke.index("class ActiveTabNavigationObserver")
        observer_end = smoke.index("void SendKeyPress", observer_start)
        observer = smoke[observer_start:observer_end]
        for required in (
            "net::IsWasmWispTransportConfigured()",
            "net::BeginWasmWispTransportDiagnostics(",
            "net::kWasmWispDiagnosticStreamConfirmed",
            "net::kWasmWispDiagnosticAllRequired",
            "WaitForNavigationAndFirstVisuallyNonEmptyPaint(",
            "chromium_wasm_report_readiness(",
            "browser_view.SchedulePaint();",
            "CHECK_EQ(raw_contents->GetTitle(), kControlledHttpsTitle);",
            "raw_browser->GetWindow()->Close();",
            "base::RunLoop().RunUntilIdle();",
            'std::puts(kControlledHttpsSmokeReadyMarker);',
            'std::puts(kControlledHttpsSmokeNavigatedMarker);',
            'std::puts(kControlledHttpsSmokeMarker);',
        ):
            with self.subTest(required=required):
                self.assertIn(required, run)

        for required in (
            "void DidFirstVisuallyNonEmptyPaint() override",
            "web_contents()->CompletedFirstVisuallyNonEmptyPaint()",
            "web_contents()->GetLastCommittedURL() != expected_url_",
        ):
            with self.subTest(observer_required=required):
                self.assertIn(required, observer)

        self.assertLess(
            run.index("net::BeginWasmWispTransportDiagnostics("),
            run.index("WaitForNavigationAndFirstVisuallyNonEmptyPaint("),
        )
        self.assertIn(
            "initial_wisp_diagnostics->completion_flags &\n"
            "               net::kWasmWispDiagnosticStreamConfirmed",
            run,
        )
        self.assertLess(
            run.index("std::puts(kControlledHttpsSmokeNavigatedMarker);"),
            run.index("raw_browser->GetWindow()->Close();"),
        )
        self.assertLess(
            run.index("WaitForNavigationAndFirstVisuallyNonEmptyPaint("),
            run.index("std::puts(kControlledHttpsSmokeNavigatedMarker);"),
        )
        self.assertLess(
            run.index("std::puts(kControlledHttpsSmokeNavigatedMarker);"),
            run.index("chromium_wasm_report_readiness("),
        )
        self.assertLess(
            run.index("chromium_wasm_report_readiness("),
            run.index("browser_view.SchedulePaint();"),
        )
        navigated = run.index(
            "std::puts(kControlledHttpsSmokeNavigatedMarker);"
        )
        close = run.index("raw_browser->GetWindow()->Close();")
        self.assertIn("WaitForBrowserSmokePresentation();", run[navigated:close])
        self.assertNotIn("raw_contents->GetController().LoadURL", run)
        self.assertNotIn("--ignore-certificate-errors", smoke)

    def test_smoke_target_declares_the_net_dependency(self) -> None:
        build = source("chrome/browser/wasm/BUILD.gn")
        smoke_target = source_set_body(build, "wasm_browser_smoke")
        self.assertIn('"//net",', smoke_target)
        self.assertNotIn("//chrome/browser/ui:ui", smoke_target)
        self.assertNotIn("//components/constrained_window", smoke_target)


if __name__ == "__main__":
    unittest.main()
