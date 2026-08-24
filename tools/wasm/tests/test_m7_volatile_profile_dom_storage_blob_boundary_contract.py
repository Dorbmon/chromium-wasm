#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for in-memory DOM storage and blob paging on Wasm."""

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
    def test_dom_storage_uses_its_in_memory_backend_on_wasm(self) -> None:
        implementation = source(
            "content/browser/dom_storage/dom_storage_context_wrapper.cc"
        )

        path_helper = _body_after_signature(
            implementation,
            "std::optional<base::FilePath> GetDOMStoragePath(",
        )
        self.assertIn("#if BUILDFLAG(IS_WASM)", path_helper)
        self.assertIn("return std::nullopt;", path_helper)
        self.assertIn("return partition->GetStoragePartitionPath();", path_helper)

        for signature in (
            "void DOMStorageContextWrapper::MaybeBindSessionStorageControl(",
            "void DOMStorageContextWrapper::MaybeBindLocalStorageControl()",
        ):
            with self.subTest(signature=signature):
                body = _body_after_signature(implementation, signature)
                self.assertIn("GetDOMStoragePath(partition_)", body)
                self.assertNotIn("GetStoragePartitionPath()", body)

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
