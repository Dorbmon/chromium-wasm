#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the normal Wasm profile's volatile default partition."""

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def _body_after_signature(text: str, signature: str) -> str:
    """Returns one balanced C++ body without depending on source layout."""

    start = text.index(signature)
    opening_brace = text.index("{", start)
    depth = 0
    for index in range(opening_brace, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[opening_brace + 1 : index]
    raise AssertionError(f"missing closing brace for {signature}")


class M7VolatileDefaultStoragePartitionContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.browser_context_header = source(
            "content/public/browser/browser_context.h"
        )
        self.browser_context_implementation = source(
            "content/browser/browser_context.cc"
        )
        self.config_header = source(
            "content/public/browser/storage_partition_config.h"
        )
        self.config_implementation = source(
            "content/public/browser/storage_partition_config.cc"
        )
        self.wasm_profile_header = source("chrome/browser/wasm/wasm_profile.h")
        self.wasm_profile_implementation = source(
            "chrome/browser/wasm/wasm_profile.cc"
        )

    def test_default_policy_is_an_explicit_browser_context_opt_in(self) -> None:
        declaration = "virtual bool ShouldUseInMemoryDefaultStoragePartition();"
        self.assertIn(declaration, self.browser_context_header)

        default_policy = _body_after_signature(
            self.browser_context_implementation,
            "bool BrowserContext::ShouldUseInMemoryDefaultStoragePartition()",
        )
        self.assertIn("return false;", default_policy)

        self.assertIn(
            "bool ShouldUseInMemoryDefaultStoragePartition() override;",
            self.wasm_profile_header,
        )
        wasm_policy = _body_after_signature(
            self.wasm_profile_implementation,
            "bool WasmProfile::ShouldUseInMemoryDefaultStoragePartition()",
        )
        self.assertIn("return true;", wasm_policy)
        self.assertIn("regular profile", wasm_policy)
        self.assertIn("Preferences I/O", wasm_policy)

    def test_only_default_config_uses_the_opt_in(self) -> None:
        default_config = _body_after_signature(
            self.config_implementation,
            "StoragePartitionConfig StoragePartitionConfig::CreateDefault(",
        )
        self.assertIn("browser_context->IsOffTheRecord()", default_config)
        self.assertIn(
            "browser_context->ShouldUseInMemoryDefaultStoragePartition()",
            default_config,
        )
        self.assertNotIn("BUILDFLAG(IS_WASM)", default_config)

        explicit_config = _body_after_signature(
            self.config_implementation,
            "StoragePartitionConfig StoragePartitionConfig::Create(\n",
        )
        self.assertIn("in_memory || browser_context->IsOffTheRecord()", explicit_config)
        self.assertNotIn("ShouldUseInMemoryDefaultStoragePartition", explicit_config)

    def test_wasm_profile_stays_regular(self) -> None:
        constructor_start = self.wasm_profile_implementation.index(
            "WasmProfile::WasmProfile(base::FilePath profile_path)"
        )
        constructor = self.wasm_profile_implementation[constructor_start:]
        self.assertIn("Profile(/*otr_profile_id=*/nullptr)", constructor)
        self.assertIn("BrowserProfileType::kRegular", constructor)


if __name__ == "__main__":
    unittest.main()
