#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused source contracts for the Wasm NetworkChangeNotifier."""

from __future__ import annotations

from pathlib import Path
import unittest


ROOT_DIR = Path(__file__).resolve().parents[3]


def source(path: str) -> str:
    return (ROOT_DIR / path).read_text(encoding="utf-8")


class M5NetworkChangeNotifierWasmContractTest(unittest.TestCase):
    def test_wasm_selects_a_dedicated_notifier_and_bridge(self) -> None:
        build = source("net/BUILD.gn")
        notifier = source("net/base/network_change_notifier.cc")

        self.assertIn('config("network_change_notifier_wasm_host_bridge")', build)
        self.assertIn('"base/network_change_notifier_wasm.js"', build)
        self.assertIn('"base/network_change_notifier_wasm.cc"', build)
        self.assertIn('"base/network_change_notifier_wasm.h"', build)
        self.assertIn(
            'all_dependent_configs += [ ":network_change_notifier_wasm_host_bridge" ]',
            build,
        )
        self.assertIn(
            '#elif BUILDFLAG(IS_WASM)\n'
            '#include "net/base/network_change_notifier_wasm.h"',
            notifier,
        )

        create_if_needed = notifier.split(
            "std::unique_ptr<NetworkChangeNotifier> NetworkChangeNotifier::CreateIfNeeded(",
            1,
        )[1]
        wasm_branch = create_if_needed.split("#elif BUILDFLAG(IS_WASM)", 1)[
            1
        ].split("#else", 1)[0]
        self.assertIn("std::make_unique<NetworkChangeNotifierWasm>()", wasm_branch)
        self.assertIn("static_cast<void>(initial_type);", wasm_branch)
        self.assertIn("static_cast<void>(initial_subtype);", wasm_branch)
        self.assertNotIn("NOTIMPLEMENTED", wasm_branch)

    def test_notifier_only_exposes_the_advisory_offline_unknown_contract(
        self,
    ) -> None:
        header = source("net/base/network_change_notifier_wasm.h")
        implementation = source("net/base/network_change_notifier_wasm.cc")
        common_test = source("net/base/network_change_notifier_unittest.cc")

        for marker in (
            "class NET_EXPORT_PRIVATE NetworkChangeNotifierWasm final",
            "CONNECTION_UNKNOWN",
            "CONNECTION_COST_UNKNOWN",
            "SUBTYPE_UNKNOWN",
            "base::RepeatingTimer",
            "SEQUENCE_CHECKER",
            "base::Lock",
            "GetCurrentMaxBandwidthAndConnectionType",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, header + implementation)

        self.assertIn(
            '#error "network_change_notifier_wasm.cc must only be built for WebAssembly"',
            implementation,
        )
        self.assertIn("kHostBridgeVersion = 1", implementation)
        self.assertIn("kHostStatePollInterval = base::Milliseconds(500)", implementation)
        self.assertIn("kOffline ? CONNECTION_NONE", implementation)
        self.assertIn("CONNECTION_UNKNOWN", implementation)
        self.assertIn("std::numeric_limits<double>::infinity()", implementation)
        self.assertIn("NotifyObserversOfConnectionTypeChange();", implementation)
        self.assertIn("NotifyObserversOfMaxBandwidthChange(", implementation)
        self.assertIn("NetworkChangeCalculator preserve normal", implementation)

        for forbidden in (
            "IPAddress",
            "NetworkInterface",
            "NotifyObserversOfDNSChange",
            "NotifyObserversOfIPAddressChange",
            "NotifyObserversOfConnectionCostChange",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, header + implementation)

        wasm_cost_test = common_test.split(
            "TEST_F(NetworkChangeNotifierConnectionCostTest, GetConnectionCost) {",
            1,
        )[1].split("TEST_F(NetworkChangeNotifierConnectionCostTest, AddObserver)", 1)[
            0
        ]
        self.assertIn("#if BUILDFLAG(IS_WASM)", wasm_cost_test)
        self.assertIn("EXPECT_EQ", wasm_cost_test)
        self.assertIn("CONNECTION_COST_UNKNOWN", wasm_cost_test)

    def test_normal_lifecycle_rejects_the_specific_old_stub(self) -> None:
        runner = source("tools/wasm/run_m6_wasm_browser_normal_lifecycle_smoke.py")

        self.assertIn("NETWORK_CHANGE_NOTIFIER_NOT_IMPLEMENTED_DIAGNOSTICS", runner)
        self.assertIn('"Not implemented reached in"', runner)
        self.assertIn('"NetworkChangeNotifier::CreateIfNeeded"', runner)
        self.assertIn("Wasm NetworkChangeNotifier", runner)


if __name__ == "__main__":
    unittest.main()
