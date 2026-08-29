#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for Wasm DOM-storage containment and blob paging."""

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


class M7VolatileProfileDomStorageBlobBoundaryContractTest(unittest.TestCase):
    def test_dom_storage_paths_are_contained_on_wasm(self) -> None:
        implementation = source(
            "content/browser/dom_storage/dom_storage_context_wrapper.cc"
        )

        local_storage_path_helper = _body_after_signature(
            implementation,
            "std::optional<base::FilePath> GetLocalStoragePath(",
        )
        self.assertIn("#if BUILDFLAG(IS_WASM)", local_storage_path_helper)
        self.assertIn(
            "#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)",
            local_storage_path_helper,
        )
        self.assertIn(
            "if (!partition->GetConfig().is_default()) {\n"
            "    return std::nullopt;\n"
            "  }",
            local_storage_path_helper,
        )
        self.assertIn(
            "BrowserContext* const browser_context = partition->browser_context();",
            local_storage_path_helper,
        )
        self.assertIn("browser_context->GetPath()", local_storage_path_helper)

        normal_wasm_local_storage = local_storage_path_helper.split(
            "#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)", 1
        )[1].split("#else", 1)[1]
        self.assertIn(
            "static_cast<void>(partition);\n  return std::nullopt;",
            normal_wasm_local_storage,
        )
        self.assertNotIn("browser_context", normal_wasm_local_storage)
        self.assertNotIn("GetPath()", normal_wasm_local_storage)
        self.assertIn(
            "return partition->GetStoragePartitionPath();", local_storage_path_helper
        )

        session_storage_path_helper = _body_after_signature(
            implementation,
            "std::optional<base::FilePath> GetSessionStoragePath(",
        )
        self.assertIn("#if BUILDFLAG(IS_WASM)", session_storage_path_helper)
        self.assertIn(
            "static_cast<void>(partition);\n  return std::nullopt;",
            session_storage_path_helper,
        )
        self.assertNotIn(
            "CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST",
            session_storage_path_helper,
        )
        self.assertNotIn("browser_context", session_storage_path_helper)
        self.assertNotIn("GetPath()", session_storage_path_helper)
        self.assertIn(
            "return partition->GetStoragePartitionPath();", session_storage_path_helper
        )

        session_bind_body = _body_after_signature(
            implementation,
            "void DOMStorageContextWrapper::MaybeBindSessionStorageControl(",
        )
        self.assertIn("GetSessionStoragePath(partition_)", session_bind_body)
        self.assertNotIn("GetLocalStoragePath(partition_)", session_bind_body)
        self.assertNotIn("GetStoragePartitionPath()", session_bind_body)

        local_bind_body = _body_after_signature(
            implementation,
            "void DOMStorageContextWrapper::MaybeBindLocalStorageControl()",
        )
        self.assertIn("GetLocalStoragePath(partition_)", local_bind_body)
        self.assertNotIn("GetSessionStoragePath(partition_)", local_bind_body)
        self.assertNotIn("GetStoragePartitionPath()", local_bind_body)

    def test_blob_storage_does_not_enable_file_paging_on_wasm(self) -> None:
        implementation = source(
            "content/browser/blob_storage/chrome_blob_storage_context.cc"
        )

        get_for_body = _body_after_signature(
            implementation,
            "ChromeBlobStorageContext* ChromeBlobStorageContext::GetFor(",
        )
        self.assertIn("#if !BUILDFLAG(IS_WASM)", get_for_body)
        self.assertIn("RemoveOldBlobStorageDirectories", get_for_body)

        initialize_body = _body_after_signature(
            implementation,
            "void ChromeBlobStorageContext::InitializeOnIOThread(",
        )
        self.assertIn("#if BUILDFLAG(IS_WASM)", initialize_body)
        self.assertIn("std::make_unique<BlobStorageContext>();", initialize_body)
        self.assertIn("#else", initialize_body)
        self.assertIn(
            "std::make_unique<BlobStorageContext>(profile_dir, blob_storage_dir,",
            initialize_body,
        )


if __name__ == "__main__":
    unittest.main()
