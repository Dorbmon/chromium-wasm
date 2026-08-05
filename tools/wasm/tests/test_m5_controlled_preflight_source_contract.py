#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Source contracts for the isolated, loopback-only M5 preflight lane."""

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M5ControlledPreflightSourceContractTest(unittest.TestCase):
    def test_gn_target_is_controlled_and_precedes_public_target(self) -> None:
        build = source("content/shell/BUILD.gn")
        target = build.split(
            'executable("content_shell_wasm_m5_controlled_preflight_test") {'
        )[1].split(
            '\n  # This executable is intentionally distinct from the controlled fixture.',
            1,
        )[0]

        self.assertLess(
            build.index('executable("content_shell_wasm_m5_controlled_preflight_test") {'),
            build.index('executable("content_shell_wasm_m5_public_test") {'),
        )
        self.assertIn("testonly = true", target)
        self.assertIn(
            'CONTENT_SHELL_WASM_M5_CONTROLLED_PREFLIGHT_TEST=1', target
        )
        for marker in (
            '"app/wasm_m5_test_trust.cc"',
            '"app/wasm_m5_test_trust.h"',
            '":generate_wasm_m5_test_root_cert"',
            '"//net"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, target)

    def test_native_url_boundary_is_fixed_and_default_port_safe(self) -> None:
        api = source("content/shell/browser/wasm_host_api.cc")
        predicate = api.split(
            "bool IsM5ControlledPreflightUrl(const GURL& candidate_url) {", 1
        )[1].split("\n}\n\nbool IsObservedWasmHostUrl", 1)[0]
        loader = api.split(
            "void LoadM5ControlledPreflightOnUiThread() {", 1
        )[1].split("\n}\n\nvoid LoadM5PublicUrlOnUiThread", 1)[0]
        export = api.split(
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_run_m5_controlled_preflight() {",
            1,
        )[1].split(
            "\n}\n\nEMSCRIPTEN_KEEPALIVE int chromium_wasm_host_load_m5_public_url",
            1,
        )[0]

        for marker in (
            "IsWasmM5ControlledPreflightTestModeEnabled()",
            "SchemeIs(url::kHttpsScheme)",
            "candidate_url.host() == kM5NetworkTestHostname",
            "candidate_url.EffectiveIntPort() == 443",
            "!candidate_url.has_username()",
            "!candidate_url.has_query()",
            "candidate_url.path() == kM5NetworkLocalGatewayProbePath",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, predicate)
        self.assertNotIn("has_port()", predicate)
        self.assertNotIn("IsM5NetworkTestUrl", predicate)
        self.assertIn('GURL expected_url("https://a.test/m5/local-gateway-probe")', loader)
        self.assertIn("BeginGatewayDenialPreflight", loader)
        self.assertIn("IsWasmM5ControlledPreflightTestModeEnabled()", export)
        self.assertIn("LoadM5ControlledPreflightOnUiThread", export)
        self.assertNotIn("const char*", export)
        public_loader = api.split(
            "void LoadM5PublicUrlOnUiThread(GURL url) {", 1
        )[1].split("\n}\n\nvoid DeactivateHostWindowOnUiThread", 1)[0]
        self.assertNotIn("LoadM5ControlledPreflightOnUiThread", public_loader)
        self.assertNotIn("/m5/local-gateway-probe", public_loader)

    def test_controlled_callbacks_are_separate_and_url_free(self) -> None:
        api = source("content/shell/browser/wasm_host_api.cc")
        bridge = source("ui/ozone/platform/wasm/wasm_host_bridge.js")
        host = source("tools/wasm/host/content_shell_host.js")

        for marker in (
            "chromium_wasm_report_m5_controlled_preflight_devtools_network",
            "chromium_wasm_report_m5_controlled_preflight_navigation",
            "chromium_wasm_report_m5_controlled_preflight_navigation_error",
            "m5_controlled_preflight_devtools_network_recorder",
            "Lane::kControlledPreflight",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, api)
        controlled_bridge = bridge.split(
            "chromium_wasm_report_m5_controlled_preflight_devtools_network__deps:",
            1,
        )[1].split("\n  // The external/public M5 lane", 1)[0]
        self.assertNotIn("UTF8ToString(url)", controlled_bridge)
        self.assertIn("reportM5ControlledPreflightNavigation", controlled_bridge)
        self.assertIn("reportM5ControlledPreflightDevToolsNetwork", host)
        self.assertIn("runM5ControlledPreflight()", host)
        self.assertIn("controlledPreflightDevtoolsNetwork", host)
        self.assertIn("M5_CONTROLLED_PREFLIGHT_CASE", host)

    def test_controlled_mode_does_not_start_legacy_fixture_recorders(self) -> None:
        api = source("content/shell/browser/wasm_host_api.cc")
        initialization = api.split("void InitializeWasmHostApi() {", 1)[1].split(
            "\nvoid EnableWasmM5NetworkTestModeForTesting", 1
        )[0]
        controlled_block = initialization.split(
            "if (IsWasmM5ControlledPreflightTestModeEnabled()) {", 1
        )[1].split("\n  if (chromium_wasm_report_readiness", 1)[0]

        self.assertIn("M5PublicDevToolsNetworkRecorder", controlled_block)
        self.assertNotIn("M5DevToolsNetworkRecorder", controlled_block)
        self.assertNotIn("M5DownloadRecorder", controlled_block)

    def test_shell_main_installs_the_controlled_root_before_content_main(self) -> None:
        shell_main = source("content/shell/app/shell_main.cc")
        controlled_mode = shell_main.split(
            "#elif defined(CONTENT_SHELL_WASM_M5_CONTROLLED_PREFLIGHT_TEST)", 1
        )[1].split("#elif defined(CONTENT_SHELL_WASM_M5_PUBLIC_TEST)", 1)[0]
        self.assertIn("InstallWasmM5TestTrustRoot();", controlled_mode)
        self.assertIn(
            "EnableWasmM5ControlledPreflightTestModeForTesting();",
            controlled_mode,
        )

    def test_runner_and_harness_admit_only_the_new_case(self) -> None:
        runner = source("tools/wasm/run_m5_controlled_preflight_smoke.py")
        harness = source("tools/wasm/m3_content_server.py")
        host = source("tools/wasm/host/content_shell_host.js")

        self.assertIn("CHROMIUM_WASM_M5_CONTROLLED_PREFLIGHT", runner)
        self.assertIn("controlled_preflight_smoke_url", runner)
        self.assertIn("validate_controlled_preflight_relay_transcript", runner)
        self.assertNotIn('"m5_url"', runner.split("def controlled_preflight_smoke_url", 1)[1].split("\n\ndef _require_dict", 1)[0])
        self.assertIn("M5_CONTROLLED_PREFLIGHT_CASE", harness)
        self.assertIn("runM5ControlledPreflightSmokeFromQuery", host)


if __name__ == "__main__":
    unittest.main()
