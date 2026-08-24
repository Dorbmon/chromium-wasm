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
        self.lifecycle_implementation = source(
            "chrome/browser/wasm/wasm_browser_lifecycle.cc"
        )
        self.normal_lifecycle_runner = source(
            "tools/wasm/run_m6_wasm_browser_normal_lifecycle_smoke.py"
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

    def test_first_web_contents_receipt_uses_only_public_partition_apis(self) -> None:
        for include in (
            '#include "content/public/browser/storage_partition.h"',
            '#include "content/public/browser/storage_partition_config.h"',
        ):
            with self.subTest(include=include):
                self.assertIn(include, self.lifecycle_implementation)

        receipt = _body_after_signature(
            self.lifecycle_implementation,
            "void VerifyWasmDefaultStoragePartitionReceipt(",
        )
        for expected in (
            "web_contents->GetPrimaryMainFrame()",
            "primary_main_frame->GetStoragePartition()",
            "initial_partition->GetConfig()",
            "CHECK(config.is_default());",
            "CHECK(config.in_memory());",
            "profile->ForEachLoadedStoragePartition(",
            "CHECK(loaded_partition->GetConfig().in_memory());",
            "CHECK(initial_partition_is_loaded);",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, receipt)
        for forbidden in (
            "storage_partition_impl.h",
            "StoragePartitionImpl",
            "GetStoragePartitionPath",
            "GetPath()",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, receipt)

        initialize = _body_after_signature(
            self.lifecycle_implementation,
            "void WasmBrowserLifecycle::Initialize()",
        )
        self.assertLess(
            initialize.index("tab_strip_model->AppendWebContents("),
            initialize.index("VerifyWasmDefaultStoragePartitionReceipt("),
        )
        self.assertLess(
            initialize.index("VerifyWasmDefaultStoragePartitionReceipt("),
            initialize.index("BrowserView& browser_view"),
        )

    def test_normal_lifecycle_requires_the_fixed_path_free_receipt(self) -> None:
        for fragment in (
            '"CHROMIUM_WASM_M7_DEFAULT_STORAGE_PARTITION:RECEIPT "',
            '"default_in_memory=1 loaded_persistent_partitions=0"',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.lifecycle_implementation)
                self.assertIn(fragment, self.normal_lifecycle_runner)
        self.assertIn(
            "_require_default_storage_partition_receipt(output)",
            self.normal_lifecycle_runner,
        )
        self.assertIn(
            "line == DEFAULT_STORAGE_PARTITION_RECEIPT",
            self.normal_lifecycle_runner,
        )
        self.assertIn(
            "does not establish M7 completion", self.normal_lifecycle_runner
        )


if __name__ == "__main__":
    unittest.main()
