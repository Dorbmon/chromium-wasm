#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M3TimeZoneMonitorSourceContractTest(unittest.TestCase):
    def test_wasm_reports_initial_icu_zone_without_host_change_watcher(
        self,
    ) -> None:
        build = source("services/device/time_zone_monitor/BUILD.gn")
        common = source(
            "services/device/time_zone_monitor/time_zone_monitor.cc"
        )
        wasm = source(
            "services/device/time_zone_monitor/time_zone_monitor_wasm.cc"
        )

        self.assertIn(
            'if (is_wasm) {\n'
            '    sources += [ "time_zone_monitor_wasm.cc" ]\n'
            "  }",
            build,
        )
        self.assertIn(
            "The base class captures ICU's initialized default time zone",
            wasm,
        )
        self.assertIn(
            "return std::make_unique<TimeZoneMonitorWasm>();",
            wasm,
        )
        self.assertIn(
            "timezone_(icu::TimeZone::createDefault())",
            common,
        )
        self.assertIn(
            "OnTimeZoneChange(GetTimeZoneId(*timezone_))",
            common,
        )

        for unsupported_observer in (
            "FilePathWatcher",
            "detectHostTimeZone",
            "UpdateIcuAndNotifyClients",
            "NotifyClients(",
        ):
            self.assertNotIn(unsupported_observer, wasm)


if __name__ == "__main__":
    unittest.main()
