#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for volatile-profile services without terminal drains."""

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


class M7VolatileProfileServiceBoundaryContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.header = source(
            "chrome/browser/wasm/wasm_content_browser_client.h"
        )
        self.implementation = source(
            "chrome/browser/wasm/wasm_content_browser_client.cc"
        )

    def test_optional_profile_disk_services_are_explicit_client_hooks(self) -> None:
        for declaration in (
            "bool AllowCompressionDictionaryTransport(\n"
            "      content::BrowserContext* context) override;",
            "bool ShouldEnableBtm(content::BrowserContext* browser_context) "
            "override;",
        ):
            with self.subTest(declaration=declaration):
                self.assertIn(declaration, self.header)

    def test_services_stay_disabled_until_they_have_terminal_drains(self) -> None:
        for signature in (
            "bool WasmContentBrowserClient::AllowCompressionDictionaryTransport(",
            "bool WasmContentBrowserClient::ShouldEnableBtm(",
        ):
            body = _body_after_signature(self.implementation, signature)
            with self.subTest(signature=signature):
                self.assertIn("return false;", body)
                self.assertNotIn("return true;", body)
                self.assertIn("profile-backed", body)
                self.assertIn("durable backing", body)
                self.assertIn("result-bearing terminal drain", body)


if __name__ == "__main__":
    unittest.main()
