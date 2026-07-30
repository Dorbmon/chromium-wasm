#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M3NetPlatformHooksSourceContractTest(unittest.TestCase):
    def test_wasm_selects_dedicated_network_and_mime_sources(self) -> None:
        build = source("net/BUILD.gn")
        wasm_sources = build.split(
            "  if (is_wasm) {\n"
            "    sources += [\n"
            '      "base/file_stream_context_wasm.cc",',
            1,
        )[1].split("  if (is_posix || is_fuchsia)", 1)[0]

        self.assertIn('"base/network_interfaces_wasm.cc",', wasm_sources)
        self.assertIn('"base/platform_mime_util_wasm.cc",', wasm_sources)
        self.assertIn('"cert/test_root_certs_builtin.cc",', wasm_sources)
        self.assertIn('"http/url_security_manager_wasm.cc",', wasm_sources)
        self.assertIn(
            "if (chrome_root_store_supported) {\n"
            '      sources += [ "cert/internal/system_trust_store_wasm.cc" ]',
            wasm_sources,
        )
        self.assertNotIn("network_interfaces_linux.cc", wasm_sources)
        self.assertNotIn("platform_mime_util_linux.cc", wasm_sources)
        self.assertNotIn("url_security_manager_posix.cc", wasm_sources)
        self.assertIn(
            'if (is_wasm) {\n'
            '    sources += [ "base/net_platform_wasm_unittest.cc" ]',
            build,
        )

    def test_network_enumeration_preserves_unknown_connection_type(
        self,
    ) -> None:
        implementation = source("net/base/network_interfaces_wasm.cc")

        self.assertIn("networks->clear();\n  return false;", implementation)
        self.assertIn(
            "connection-type inference remains CONNECTION_UNKNOWN",
            implementation,
        )
        self.assertIn(
            "std::string GetWifiSSID() {\n"
            "  // The host page does not expose Wi-Fi association details.\n"
            "  return std::string();\n"
            "}",
            implementation,
        )
        for host_api in ("getifaddrs", "ioctl", "SIOCGIWNAME"):
            self.assertNotIn(host_api, implementation)

    def test_platform_mime_hooks_defer_to_built_in_mappings(self) -> None:
        implementation = source("net/base/platform_mime_util_wasm.cc")
        mime_util = source("net/base/mime_util.cc")

        self.assertEqual(implementation.count("return false;"), 2)
        self.assertIn(
            "void PlatformMimeUtil::GetPlatformExtensionsForMimeType(",
            implementation,
        )
        self.assertIn(
            "// No host MIME extensions are available to add.",
            implementation,
        )
        self.assertNotIn("GetPlatformMimeTypeFromExtension(\n", mime_util)
        self.assertIn('{"application/wasm", "wasm"}', mime_util)

    def test_empty_url_security_allowlists_deny_ambient_credentials(
        self,
    ) -> None:
        implementation = source("net/http/url_security_manager_wasm.cc")

        self.assertIn(
            "std::unique_ptr<URLSecurityManager> "
            "URLSecurityManager::Create()",
            implementation,
        )
        self.assertIn(
            "return std::make_unique<URLSecurityManagerAllowlist>();",
            implementation,
        )
        self.assertIn(
            "Empty allowlists deny both\n"
            "  // ambient credentials and Kerberos delegation.",
            implementation,
        )
        self.assertNotIn("URLSecurityManagerWin", implementation)

    def test_tls_uses_chromium_roots_without_ambient_host_trust(
        self,
    ) -> None:
        implementation = source(
            "net/cert/internal/system_trust_store_wasm.cc"
        )

        self.assertIn(
            "std::unique_ptr<SystemTrustStore> "
            "CreateSslSystemTrustStoreChromeRoot(",
            implementation,
        )
        self.assertIn(
            "return CreateChromeOnlySystemTrustStore("
            "std::move(chrome_root));",
            implementation,
        )
        self.assertIn(
            "WebAssembly has no host or local certificate store",
            implementation,
        )
        self.assertNotIn("TrustStoreNSS", implementation)
        self.assertNotIn("TrustStoreInMemory", implementation)
        self.assertNotIn("AddTrustAnchor", implementation)

    def test_builtin_verifier_owns_wasm_test_roots(self) -> None:
        implementation = source("net/cert/test_root_certs_builtin.cc")
        generic = source("net/cert/test_root_certs.cc")

        self.assertIn(
            "bool TestRootCerts::AddImpl(X509Certificate* certificate) {\n"
            "  return true;\n"
            "}",
            implementation,
        )
        self.assertIn("void TestRootCerts::ClearImpl() {}", implementation)
        self.assertIn("void TestRootCerts::Init() {}", implementation)
        self.assertIn(
            "test_trust_store_.AddCertificate(std::move(parsed), trust);",
            generic,
        )
        self.assertIn(
            "ClearImpl();\n  test_trust_store_.Clear();",
            generic,
        )


if __name__ == "__main__":
    unittest.main()
