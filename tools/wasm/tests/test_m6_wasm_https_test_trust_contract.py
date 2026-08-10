#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for Chrome's test-only controlled-M6 HTTPS trust lane."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.wasm.tests.m3_source_contract_test_support import ROOT_DIR, source


def gn_target_body(build: str, target: str) -> str:
    match = re.search(
        rf'\b(?:action|executable)\s*\(\s*"{re.escape(target)}"\s*\)',
        build,
    )
    if not match:
        raise AssertionError(f"missing GN target {target!r}")
    opening_brace = build.find("{", match.end())
    if opening_brace < 0:
        raise AssertionError(f"missing opening brace for {target!r}")

    depth = 0
    for index in range(opening_brace, len(build)):
        if build[index] == "{":
            depth += 1
        elif build[index] == "}":
            depth -= 1
            if depth == 0:
                return build[opening_brace + 1 : index]
    raise AssertionError(f"missing closing brace for {target!r}")


class M6WasmHttpsTestTrustContractTest(unittest.TestCase):
    def test_normal_chrome_target_does_not_link_the_test_root(self) -> None:
        build = source("chrome/BUILD.gn")
        production_target = gn_target_body(build, "chrome_wasm")

        for forbidden in (
            "CHROME_WASM_M6_CONTROLLED_HTTPS_TEST",
            "wasm_m6_test_trust",
            "generate_wasm_m6_test_root_cert",
            "root_ca_cert.pem",
            '"//net"',
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, production_target)

    def test_controlled_https_target_and_der_action_are_test_only(self) -> None:
        build = source("chrome/BUILD.gn")
        certificate_action = gn_target_body(
            build, "generate_wasm_m6_test_root_cert"
        )
        test_target = gn_target_body(build, "chrome_wasm_m6_https_test")

        self.assertIn("testonly = true", certificate_action)
        self.assertIn('":chrome_wasm_m6_https_test"', certificate_action)
        self.assertIn(
            'script = "//net/data/ssl/scripts/generate-fuzzer-cert-include.py"',
            certificate_action,
        )
        self.assertIn(
            'sources = [ "//net/data/ssl/certificates/root_ca_cert.pem" ]',
            certificate_action,
        )
        self.assertIn("wasm_m6_test_root_cert.inc", certificate_action)

        self.assertIn("testonly = true", test_target)
        self.assertIn(
            'defines = [ "CHROME_WASM_M6_CONTROLLED_HTTPS_TEST=1" ]',
            test_target,
        )
        for required in (
            '"app/chrome_exe_main_aura.cc"',
            '"app/chrome_main_wasm.cc"',
            '"browser/wasm/wasm_m6_test_trust.cc"',
            '"browser/wasm/wasm_m6_test_trust.h"',
            '":generate_wasm_m6_test_root_cert"',
            '"//base"',
            '"//net"',
        ):
            with self.subTest(required=required):
                self.assertIn(required, test_target)

    def test_generated_asset_is_der_only_and_trust_owner_is_process_lifetime(
        self,
    ) -> None:
        generator = ROOT_DIR / (
            "net/data/ssl/scripts/generate-fuzzer-cert-include.py"
        )
        root_pem = ROOT_DIR / "net/data/ssl/certificates/root_ca_cert.pem"
        trust_source = source("chrome/browser/wasm/wasm_m6_test_trust.cc")

        with tempfile.TemporaryDirectory() as temporary_directory:
            generated_include = (
                Path(temporary_directory) / "wasm_m6_test_root_cert.inc"
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
        for forbidden in (
            "-----",
            "BEGIN CERTIFICATE",
            "END CERTIFICATE",
            "PRIVATE KEY",
            "root_ca_cert.pem",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, generated_der)
                self.assertNotIn(forbidden, trust_source)

        for required in (
            '#include "chrome/browser/wasm/wasm_m6_test_root_cert.inc"',
            "net::ScopedTestRoot MakeM6TestRoot()",
            "CreateFromBytes(kM6TestRootCertificateDer)",
            "base::NoDestructor<net::ScopedTestRoot>",
            "CHECK(!test_root->IsEmpty());",
        ):
            with self.subTest(required=required):
                self.assertIn(required, trust_source)
        self.assertNotIn("--embed-file", trust_source)

    def test_trust_root_is_guarded_and_precedes_content_main(self) -> None:
        chrome_main = source("chrome/app/chrome_main_wasm.cc")
        self.assertIn(
            "#if defined(CHROME_WASM_M6_CONTROLLED_HTTPS_TEST)", chrome_main
        )
        self.assertIn(
            '#include "chrome/browser/wasm/wasm_m6_test_trust.h"  // nogncheck',
            chrome_main,
        )
        self.assertIn(
            '"wasm-browser-controlled-https-smoke"',
            chrome_main,
        )

        install_root = chrome_main.index("chrome::InstallWasmM6TestTrustRoot();")
        command_line_init = chrome_main.index(
            "base::CommandLine::Init(params.argc, params.argv);"
        )
        content_main = chrome_main.index(
            "const int result = content::ContentMain(std::move(params));"
        )
        self.assertLess(command_line_init, install_root)
        self.assertLess(install_root, content_main)
        test_guard_start = chrome_main.index(
            "#if defined(CHROME_WASM_M6_CONTROLLED_HTTPS_TEST)",
            command_line_init,
        )
        test_guard_end = chrome_main.index("#endif", test_guard_start)
        test_guard = chrome_main[test_guard_start:test_guard_end]
        self.assertIn("HasSwitch(", test_guard)
        self.assertIn("kWasmBrowserControlledHttpsSmokeSwitch", test_guard)
        self.assertIn("EnableWasmM6ControlledHttpsTestMode();", test_guard)


if __name__ == "__main__":
    unittest.main()
