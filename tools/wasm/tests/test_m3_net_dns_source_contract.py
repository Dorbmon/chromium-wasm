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
