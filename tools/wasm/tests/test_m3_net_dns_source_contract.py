#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from pathlib import Path
import unittest


ROOT_DIR = Path(__file__).resolve().parents[3]


def source(path: str) -> str:
    return (ROOT_DIR / path).read_text(encoding="utf-8")


class M3NetDnsSourceContractTest(unittest.TestCase):
    def test_wasm_platform_factories_have_explicit_semantics(self) -> None:
        build = source("net/dns/BUILD.gn")
        address_sorter = source("net/dns/address_sorter_wasm.cc")
        address_sorter_test = source(
            "net/dns/address_sorter_wasm_unittest.cc"
        )
        dns_config = source("net/dns/dns_config_service_wasm.cc")

        self.assertIn('if (is_wasm) {', build)
        self.assertIn('"dns_config_service_wasm.cc"', build)
        self.assertIn(
            'if (is_wasm) {\n'
            '      sources += [ "address_sorter_wasm.cc" ]',
            build,
        )
        self.assertIn(
            'if (is_wasm) {\n'
            '    sources += [ "dns_config_service_wasm_unittest.cc" ]',
            build,
        )
        self.assertIn(
            'if (is_wasm) {\n'
            '      sources += [ "address_sorter_wasm_unittest.cc" ]',
            build,
        )
        self.assertIn(
            "base::SequencedTaskRunner::GetCurrentDefault()->PostTask(",
            address_sorter,
        )
        self.assertIn("endpoints));", address_sorter)
        self.assertIn(
            "Success describes the ordering operation, not network "
            "reachability.",
            address_sorter,
        )
        self.assertIn(
            "std::move(callback).Run(/*success=*/true, "
            "std::move(endpoints));",
            address_sorter,
        )
        self.assertNotIn("socket", address_sorter.lower())
        self.assertIn("EXPECT_FALSE(callback_called);", address_sorter_test)
        self.assertIn("sorter.reset();", address_sorter_test)
        self.assertIn("EXPECT_EQ(endpoints, sorted);", address_sorter_test)
        self.assertIn(
            "cannot read or watch the host browser's system DNS",
            dns_config,
        )
        self.assertIn("return nullptr;", dns_config)

    def test_wasm_disables_mdns_without_a_udp_transport(self) -> None:
        features = source("net/features.gni")
        implementation = source("net/dns/public/util.cc")
        wasm_branch = implementation.split(
            "#elif BUILDFLAG(IS_WASM)\n", maxsplit=1
        )[1].split("#else", maxsplit=1)[0]

        self.assertIn(
            'assert(!is_wasm || !enable_mdns,\n'
            '       "mDNS requires a multicast UDP transport")',
            features,
        )
        self.assertIn(
            "mDNS is disabled until Wasm has a multicast UDP transport",
            wasm_branch,
        )
        self.assertIn("NOTREACHED();", wasm_branch)
        self.assertNotIn("return GetMdnsGroupEndPoint", wasm_branch)
        self.assertNotIn("IPv4AllZeros", wasm_branch)

    def test_wasm_loopback_probe_reports_uncertainty(self) -> None:
        implementation = source("net/dns/loopback_only.cc")
        header = source("net/dns/loopback_only.h")
        wasm_branch = implementation.split(
            "#elif BUILDFLAG(IS_WASM)\n", maxsplit=1
        )[1].split("#elif", maxsplit=1)[0]

        self.assertIn(
            "M3 has no native network-interface provider", wasm_branch
        )
        self.assertIn("NOTIMPLEMENTED_LOG_ONCE();", wasm_branch)
        self.assertIn("return false;", wasm_branch)
        self.assertNotIn("return true;", wasm_branch)
        self.assertNotIn("getifaddrs", wasm_branch)
        self.assertIn(
            "Also results in false if it cannot determine this.", header
        )


if __name__ == "__main__":
    unittest.main()
