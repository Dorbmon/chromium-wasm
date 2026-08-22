#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import unittest


ROOT_DIR = Path(__file__).resolve().parents[3]
TOOLS_DIR = ROOT_DIR / "tools" / "wasm"


class M3BootstrapSourceContractTest(unittest.TestCase):
    def test_dom_distiller_artifacts_are_pinned_in_the_m3_closure(
        self,
    ) -> None:
        manifest = json.loads(
            (TOOLS_DIR / "toolchain_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        dependency = manifest["git_dependencies"]["dom_distiller_js"]
        bootstrap = (TOOLS_DIR / "bootstrap.py").read_text(encoding="utf-8")
        entry = subprocess.run(
            ["git", "ls-tree", "HEAD", "--", dependency["path"]],
            cwd=ROOT_DIR,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()

        self.assertEqual(entry[1], "commit")
        self.assertEqual(entry[2], dependency["revision"])
        m3_dependencies = bootstrap.split(
            "M3_ADDITIONAL_SUBMODULES = (", 1
        )[1].split(")", 1)[0]
        self.assertIn('"dom_distiller_js"', m3_dependencies)
        m0_dependencies = bootstrap.split(
            "M0_REQUIRED_SUBMODULES = (", 1
        )[1].split(")", 1)[0]
        self.assertNotIn('"dom_distiller_js"', m0_dependencies)

    def test_google_benchmark_is_pinned_for_wasm_unit_tests(self) -> None:
        manifest = json.loads(
            (TOOLS_DIR / "toolchain_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        dependency = manifest["git_dependencies"]["google_benchmark"]
        bootstrap = (TOOLS_DIR / "bootstrap.py").read_text(encoding="utf-8")
        entry = subprocess.run(
            ["git", "ls-tree", "HEAD", "--", dependency["path"]],
            cwd=ROOT_DIR,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()

        self.assertEqual(entry[1], "commit")
        self.assertEqual(entry[2], dependency["revision"])
        m3_dependencies = bootstrap.split(
            "M3_ADDITIONAL_SUBMODULES = (", 1
        )[1].split(")", 1)[0]
        self.assertIn('"google_benchmark"', m3_dependencies)
        m0_dependencies = bootstrap.split(
            "M0_REQUIRED_SUBMODULES = (", 1
        )[1].split(")", 1)[0]
        self.assertNotIn('"google_benchmark"', m0_dependencies)
        test_support = (ROOT_DIR / "base" / "test" / "BUILD.gn").read_text(
            encoding="utf-8"
        )
        self.assertIn('"//third_party/google_benchmark",', test_support)


if __name__ == "__main__":
    unittest.main()
