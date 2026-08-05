#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused source contracts for the M5 test-only TLS trust lane."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.wasm.tests.m3_source_contract_test_support import ROOT_DIR, source


def gn_block(build: str, declaration: str) -> str:
    """Returns one top-level, two-space-indented GN declaration body."""
    return build.split(declaration, 1)[1].split("\n  }\n", 1)[0]


class M5WispTrustSourceContractTest(unittest.TestCase):
    def test_regular_content_shell_has_no_m5_trust_or_navigation_opt_in(
        self,
    ) -> None:
        build = source("content/shell/BUILD.gn")
        regular_target = gn_block(build, 'executable("content_shell_wasm") {')

        self.assertIn("testonly = true", regular_target)
        for test_only_marker in (
            "CONTENT_SHELL_WASM_M5_TEST",
            "wasm_m5_test_trust",
            "generate_wasm_m5_test_root_cert",
            "root_ca_cert.pem",
        ):
            with self.subTest(test_only_marker=test_only_marker):
                self.assertNotIn(test_only_marker, regular_target)

    def test_m5_target_and_certificate_action_are_explicitly_test_only(
        self,
    ) -> None:
        build = source("content/shell/BUILD.gn")
        certificate_action = gn_block(
            build, 'action("generate_wasm_m5_test_root_cert") {'
        )
        m5_target = gn_block(
            build, 'executable("content_shell_wasm_m5_test") {'
        )

        self.assertIn("testonly = true", certificate_action)
        for target in (
            '":content_shell_wasm_m5_test"',
            '":content_shell_wasm_m5_controlled_preflight_test"',
        ):
            with self.subTest(target=target):
                self.assertIn(target, certificate_action)
        self.assertIn(
            'script = "//net/data/ssl/scripts/'
            'generate-fuzzer-cert-include.py"',
            certificate_action,
        )
        self.assertIn(
            'sources = [ "//net/data/ssl/certificates/root_ca_cert.pem" ]',
            certificate_action,
        )
        self.assertIn("wasm_m5_test_root_cert.inc", certificate_action)

        self.assertIn("testonly = true", m5_target)
        self.assertIn('defines = [ "CONTENT_SHELL_WASM_M5_TEST=1" ]', m5_target)
        self.assertIn('"app/wasm_m5_test_trust.cc"', m5_target)
        self.assertIn('"app/wasm_m5_test_trust.h"', m5_target)
        self.assertIn('":generate_wasm_m5_test_root_cert"', m5_target)

    def test_certificate_generator_emits_only_der_not_pem_or_private_key(
        self,
    ) -> None:
        generator = ROOT_DIR / (
            "net/data/ssl/scripts/generate-fuzzer-cert-include.py"
        )
        root_pem = ROOT_DIR / "net/data/ssl/certificates/root_ca_cert.pem"
        trust_source = source("content/shell/app/wasm_m5_test_trust.cc")

        with tempfile.TemporaryDirectory() as temporary_directory:
            generated_include = (
                Path(temporary_directory) / "wasm_m5_test_root_cert.inc"
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(generator),
                    str(root_pem),
                    str(generated_include),
                ],
                capture_output=True,
                check=False,
                cwd=ROOT_DIR,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            generated_der = generated_include.read_text(encoding="utf-8")

        self.assertTrue(generated_der.startswith("0x30,"))
        self.assertIn("0x", generated_der)
        for forbidden_marker in (
            "-----",
            "BEGIN CERTIFICATE",
            "END CERTIFICATE",
            "PRIVATE KEY",
            "root_ca_cert.pem",
        ):
            with self.subTest(forbidden_marker=forbidden_marker):
                self.assertNotIn(forbidden_marker, generated_der)
                self.assertNotIn(forbidden_marker, trust_source)

        self.assertIn(
            '#include "content/shell/app/wasm_m5_test_root_cert.inc"',
            trust_source,
        )
        self.assertIn("net::ScopedTestRoot", trust_source)
        self.assertIn(
            "CreateFromBytes(kM5TestRootCertificateDer)", trust_source
        )
        self.assertNotIn("--embed-file", trust_source)

    def test_trust_root_and_test_mode_are_enabled_before_content_main(
        self,
    ) -> None:
        shell_main = source("content/shell/app/shell_main.cc")
        wasm_main = shell_main.split(
            "int main(int argc, const char** argv) {", 1
        )[1].split("#else\n  content::ShellMainDelegate delegate;", 1)[0]

        self.assertIn("#if defined(CONTENT_SHELL_WASM_M5_TEST)", wasm_main)
        install_root = wasm_main.index("content::InstallWasmM5TestTrustRoot();")
        enable_mode = wasm_main.index(
            "content::EnableWasmM5NetworkTestModeForTesting();"
        )
        content_main = wasm_main.index(
            "exit_code = content::ContentMain(std::move(params));"
        )
        self.assertLess(install_root, enable_mode)
        self.assertLess(enable_mode, content_main)

    def test_data_navigation_remains_production_default_and_m5_is_gated(
        self,
    ) -> None:
        api = source("content/shell/browser/wasm_host_api.cc")
        header = source("content/shell/browser/wasm_host_api.h")
        data_loader = api.split(
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_load_url(", 1
        )[1].split(
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_load_m5_url(", 1
        )[0]
        m5_loader = api.split(
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_load_m5_url(", 1
        )[1]

        self.assertIn("data_url", data_loader)
        self.assertIn("url.SchemeIs(url::kDataScheme)", data_loader)
        self.assertNotIn("IsM5NetworkTestUrl", data_loader)
        self.assertNotIn("CONTENT_SHELL_WASM_M5_TEST", data_loader)

        self.assertIn("EnableWasmM5NetworkTestModeForTesting", header)
        self.assertIn("data:-only navigation boundary", header)
        self.assertIn(
            "GetWasmM5NetworkTestMode().store(true, std::memory_order_relaxed)",
            api,
        )
        self.assertIn('kM5NetworkTestHostname = "a.test"', api)
        self.assertIn(
            "candidate_url.SchemeIs(url::kHttpsScheme)",
            api,
        )
        self.assertIn("candidate_url.host() == kM5NetworkTestHostname", api)
        self.assertIn("kM5NetworkTestPathPrefix = \"/m5/\"", api)
        self.assertIn(
            "if (!test_url || !content::IsWasmM5NetworkTestModeEnabled())",
            m5_loader,
        )
        self.assertIn("if (!content::IsM5NetworkTestUrl(url))", m5_loader)


if __name__ == "__main__":
    unittest.main()
