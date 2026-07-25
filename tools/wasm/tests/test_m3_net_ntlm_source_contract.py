#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from pathlib import Path
import unittest


ROOT_DIR = Path(__file__).resolve().parents[3]
PORTABLE_NTLM_GUARD = (
    "#if BUILDFLAG(IS_POSIX) || BUILDFLAG(IS_FUCHSIA) || "
    "BUILDFLAG(IS_WASM)"
)


def source(path: str) -> str:
    return (ROOT_DIR / path).read_text(encoding="utf-8")


class M3NetNtlmSourceContractTest(unittest.TestCase):
    def test_wasm_uses_the_portable_ntlm_v2_preference(self) -> None:
        header = source("net/http/http_auth_preferences.h")
        implementation = source("net/http/http_auth_preferences.cc")

        self.assertEqual(header.count(PORTABLE_NTLM_GUARD), 3)
        self.assertEqual(implementation.count(PORTABLE_NTLM_GUARD), 1)
        self.assertIn("virtual bool NtlmV2Enabled() const;", header)
        self.assertIn("bool ntlm_v2_enabled_ = true;", header)
        self.assertIn(
            "bool HttpAuthPreferences::NtlmV2Enabled() const {\n"
            "  return ntlm_v2_enabled_;\n"
            "}",
            implementation,
        )

    def test_portable_ntlm_never_claims_default_credentials(self) -> None:
        handler = source("net/http/http_auth_handler_ntlm_portable.cc")

        self.assertIn(
            "bool HttpAuthHandlerNTLM::AllowsDefaultCredentials() {\n"
            "  // Default credentials are not supported in the portable "
            "implementation of\n"
            "  // NTLM, but are supported in the SSPI implementation.\n"
            "  return false;\n"
            "}",
            handler,
        )
        self.assertNotIn("GSSAPI", handler)
        self.assertNotIn("SSPILibrary", handler)


if __name__ == "__main__":
    unittest.main()
