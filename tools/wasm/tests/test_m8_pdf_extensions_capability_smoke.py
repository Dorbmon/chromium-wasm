#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the bounded M8.7 extensions/PDF capability witness."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m8_pdf_extensions_capability_smoke as smoke
from tools.wasm.tests.m3_source_contract_test_support import source


def valid_stdout() -> str:
    return "\n".join(
        (
            *smoke.EXPECTED_MARKERS,
            f'{smoke.PREFIX}:NODE_EXIT {{"exitCode":0}}',
        )
    )


class M8PdfExtensionsCapabilityResultTest(unittest.TestCase):
    def test_accepts_exact_disabled_extensions_and_pdf_witness(self) -> None:
        smoke.validate_streams(valid_stdout(), "")

    def test_rejects_out_of_order_or_relaxed_boundary_result(self) -> None:
        lines = valid_stdout().splitlines()
        lines[1], lines[2] = lines[2], lines[1]
        with self.assertRaisesRegex(M0Error, "out of order"):
            smoke.validate_streams("\n".join(lines), "")

        enabled_extensions = valid_stdout().replace(
            "extensions_buildflags status=disabled",
            "extensions_buildflags status=enabled",
        )
        with self.assertRaisesRegex(M0Error, "exactly one"):
            smoke.validate_streams(enabled_extensions, "")

        enabled_pdf = valid_stdout().replace("pdf=disabled", "pdf=enabled")
        with self.assertRaisesRegex(M0Error, "exactly one"):
            smoke.validate_streams(enabled_pdf, "")

    def test_rejects_native_failure_or_missing_zero_exit(self) -> None:
        with self.assertRaisesRegex(M0Error, "failure marker"):
            smoke.validate_streams(valid_stdout(), f"{smoke.PREFIX}:FAIL stage=x")
        with self.assertRaisesRegex(M0Error, "exactly one zero native exit"):
            smoke.validate_streams(
                valid_stdout().replace('"exitCode":0', '"exitCode":1'), ""
            )

    def test_resolve_module_requires_fixed_js_and_wasm_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            out_dir = Path(temporary_directory)
            module = out_dir / smoke.MODULE_NAME
            module.write_text("export default async () => {};", encoding="utf-8")
            with self.assertRaisesRegex(M0Error, "sidecar"):
                smoke.resolve_module(out_dir)
            module.with_suffix(".wasm").write_bytes(b"\\0asm")
            self.assertEqual(smoke.resolve_module(out_dir), module.resolve())


class M8PdfExtensionsCapabilitySourceContractTest(unittest.TestCase):
    def test_wasm_profiles_explicitly_disable_the_feature_closures(self) -> None:
        manifest = json.loads(source("tools/wasm/toolchain_manifest.json"))
        for profile in (
            "m6_chrome_gn_args",
            "m8_chrome_codegen_experiment_gn_args",
        ):
            with self.subTest(profile=profile):
                assignments = dict(
                    argument.split(" = ", 1) for argument in manifest[profile]
                )
                self.assertEqual("false", assignments["enable_extensions"])
                self.assertEqual("false", assignments["enable_pdf"])
                self.assertEqual("false", assignments["enable_pdf_ink2"])
                self.assertEqual("false", assignments["enable_pdf_save_to_drive"])

    def test_target_is_wasm_chrome_only_and_uses_only_buildflags(self) -> None:
        build = source("chrome/browser/wasm/BUILD.gn")
        native = source(
            "chrome/browser/wasm/wasm_pdf_extensions_capability_smoke.cc"
        )
        runner = source("tools/wasm/run_m8_pdf_extensions_capability_smoke.py")

        self.assertIn("assert(is_wasm && enable_chromium_wasm_chrome)", build)
        self.assertIn('executable("wasm_pdf_extensions_capability_smoke")', build)
        self.assertIn(
            'sources = [ "wasm_pdf_extensions_capability_smoke.cc" ]', build
        )
        self.assertIn('"//extensions/buildflags",', build)
        self.assertIn('"//pdf:buildflags",', build)
        self.assertIn('#if !BUILDFLAG(IS_WASM)', native)
        self.assertIn('#if BUILDFLAG(IS_POSIX)', native)
        self.assertIn('"extensions/buildflags/buildflags.h"', native)
        self.assertIn('"pdf/buildflags.h"', native)
        for flag in (
            "ENABLE_EXTENSIONS",
            "ENABLE_EXTENSIONS_CORE",
            "ENABLE_PDF",
            "ENABLE_PDF_INK2",
            "ENABLE_PDF_SAVE_TO_DRIVE",
        ):
            self.assertIn(flag, native)
        self.assertIn("extensions_unexpectedly_enabled", native)
        self.assertIn("pdf_unexpectedly_enabled", native)
        self.assertIn("m8GateComplete\": False", runner)
        self.assertIn("compiled-extension-and-pdf-buildflag-boundary-only", runner)

    def test_witness_does_not_claim_or_construct_a_product_feature(self) -> None:
        native = source(
            "chrome/browser/wasm/wasm_pdf_extensions_capability_smoke.cc"
        )
        for forbidden in (
            '#include "content/public/browser/web_contents.h"',
            '#include "chrome/browser/extensions/chrome_extension_system.h"',
            '#include "extensions/browser/extension_service.h"',
            '#include "pdf/pdf.h"',
            '#include "pdf/pdfium/pdfium_engine.h"',
            "chromium_wasm_",
        ):
            self.assertNotIn(forbidden, native)
        self.assertIn("does not construct a Browser or WebContents", native)
        self.assertIn("does not attempt to turn an embedded host PDF viewer", native)


if __name__ == "__main__":
    unittest.main()
