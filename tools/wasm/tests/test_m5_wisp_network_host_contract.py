#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the dedicated M5 HTTPS host-test lane."""

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M5WispNetworkHostContractTest(unittest.TestCase):
    def test_m5_url_is_a_fixed_https_fixture_not_a_general_navigation_api(
        self,
    ) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        start = host.index("function normalizeM5NetworkTestURL(value)")
        end = host.index("\nexport class ChromiumWasmM3Host", start)
        url_policy = host[start:end]

        self.assertIn('M5_NETWORK_TEST_HOSTNAME = "a.test"', host)
        self.assertIn('M5_NETWORK_TEST_PATH_PREFIX = "/m5/"', host)
        self.assertIn('parsed.protocol !== "https:"', url_policy)
        self.assertIn(
            "parsed.hostname !== M5_NETWORK_TEST_HOSTNAME", url_policy
        )
        self.assertIn("!parsed.port", url_policy)
        self.assertIn("parsed.username || parsed.password", url_policy)
        self.assertIn("parsed.search || parsed.hash", url_policy)
        self.assertIn(
            "parsed.pathname.startsWith(M5_NETWORK_TEST_PATH_PREFIX)",
            url_policy,
        )

    def test_data_navigation_stays_separate_from_the_test_only_m5_loader(
        self,
    ) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        data_loader = host.split("  async loadURL(url) {", 1)[1].split(
            "\n  async loadM5NetworkURL(url) {", 1
        )[0]
        m5_loader = host.split("  async loadM5NetworkURL(url) {", 1)[1].split(
            "\n  async injectInput(event)", 1
        )[0]

        self.assertIn('parsed.protocol !== "data:"', data_loader)
        self.assertIn('"chromium_wasm_host_load_url"', data_loader)
        self.assertNotIn("chromium_wasm_host_load_m5_url", data_loader)

        self.assertIn("this.#wispConfigured", m5_loader)
        self.assertIn("normalizeM5NetworkTestURL(url)", m5_loader)
        self.assertIn("this.#m5NetworkTestActive = true;", m5_loader)
        self.assertIn('"chromium_wasm_host_load_m5_url"', m5_loader)
        self.assertIn("this.#m5NetworkTestActive = false;", m5_loader)
        self.assertIn('scheme: "https"', m5_loader)

    def test_m5_reports_and_smoke_proof_are_separate_from_data_reports(
        self,
    ) -> None:
        host = source("tools/wasm/host/content_shell_host.js")

        self.assertIn("reportM5Navigation(report)", host)
        self.assertIn("reportM5PageProbe(report)", host)
        self.assertIn("_reportM5Navigation(value)", host)
        self.assertIn("_reportM5PageProbe(value)", host)
        self.assertIn('report.scheme !== "https"', host)
        self.assertIn("report.fixture !== M5_NETWORK_FIXTURE", host)
        self.assertIn("hasM5NetworkPageProbe(readiness.pageProbe)", host)
        self.assertIn("runM5WispNetworkSmokeFromQuery", host)
        self.assertIn("if (selectedCase === M5_NETWORK_CASE)", host)
        for marker in (
            "pageProbe?.h2Fetch === true",
            'pageProbe?.h2Protocol === "h2"',
            "pageProbe?.corsFetch === true",
            "pageProbe?.webSocketEcho === true",
            "pageProbe?.altSvcH3Advertised === true",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, host)

    def test_emscripten_bridge_cannot_relabel_m5_as_data_navigation(self) -> None:
        bridge = source("ui/ozone/platform/wasm/wasm_host_bridge.js")
        m5_navigation = bridge.split(
            "chromium_wasm_report_m5_navigation: () => {", 1
        )[1].split("\n  },", 1)[0]
        m5_probe = bridge.split(
            "chromium_wasm_report_m5_page_probe: (probe) => {", 1
        )[1].split("\n  },", 1)[0]

        self.assertIn("bridge.reportM5Navigation", m5_navigation)
        self.assertIn("scheme: 'https'", m5_navigation)
        self.assertNotIn("reportNavigation", m5_navigation)
        self.assertIn("bridge.reportM5PageProbe", m5_probe)
        self.assertNotIn("reportPageProbe", m5_probe)


if __name__ == "__main__":
    unittest.main()
