#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for Wasm's explicit content-settings registry platform."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M6ContentSettingsWasmContractTest(unittest.TestCase):
    def test_wasm_uses_a_distinct_non_desktop_registry_bit(self) -> None:
        header = source(
            "components/content_settings/core/browser/website_settings_registry.h"
        )

        self.assertIn("PLATFORM_WASM = 1 << 7,", header)
        self.assertIn("distinct permission, persistence, and host-API", header)

        desktop_match = re.search(
            r"DESKTOP = (?P<body>.*?),\n\n"
            r"    // Settings applied to all platforms",
            header,
            re.DOTALL,
        )
        self.assertIsNotNone(desktop_match)
        self.assertNotIn("PLATFORM_WASM", desktop_match.group("body"))

        all_platforms_match = re.search(
            r"ALL_PLATFORMS =\n(?P<body>.*?),\n",
            header,
            re.DOTALL,
        )
        self.assertIsNotNone(all_platforms_match)
        self.assertIn("PLATFORM_WASM", all_platforms_match.group("body"))

    def test_wasm_rejects_desktop_only_entries_and_disables_sync(self) -> None:
        implementation = source(
            "components/content_settings/core/browser/website_settings_registry.cc"
        )

        register_match = re.search(
            r"WebsiteSettingsRegistry::Register\(.*?\) \{"
            r"(?P<body>.*?)\n\}",
            implementation,
            re.DOTALL,
        )
        self.assertIsNotNone(register_match)
        body = register_match.group("body")
        wasm_branch = body.split("#elif BUILDFLAG(IS_WASM)", 1)[1].split(
            "#else", 1
        )[0]
        self.assertIn("if (!(platform & PLATFORM_WASM))", wasm_branch)
        self.assertIn("return nullptr;", wasm_branch)
        self.assertIn(
            "sync_status = WebsiteSettingsInfo::UNSYNCABLE;", wasm_branch
        )
        self.assertNotIn("PLATFORM_LINUX", wasm_branch)


if __name__ == "__main__":
    unittest.main()
