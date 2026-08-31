#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Storage-boundary and marker contracts for the renderer IndexedDB host."""

from __future__ import annotations

from pathlib import Path
import subprocess
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


ROOT = Path(__file__).resolve().parents[3]
HOST = "tools/wasm/host/chrome_wasm_renderer_indexed_db_outer_reload_smoke.js"


class RendererIndexedDBOuterReloadHostTest(unittest.TestCase):
    def test_host_is_syntax_valid_storage_blind_and_does_not_self_navigate(self) -> None:
        host = source(HOST)
        completed = subprocess.run(
            ["node", "--check", str(ROOT / HOST)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        forbidden = (
            "globalThis.indexedDB",
            "navigator.storage",
            "navigator.locks",
            "localStorage",
            "sessionStorage",
            ".ccall(",
            ".getValue(",
            "HEAPU8",
            "WebAssembly.Memory",
        )
        for spelling in forbidden:
            with self.subTest(spelling=spelling):
                self.assertNotIn(spelling, host)
        for spelling in ("location.reload", "location.replace", "location.assign"):
            with self.subTest(spelling=spelling):
                self.assertNotIn(spelling, host)

    def test_host_uses_only_escrowed_argv_and_requires_all_close_markers(self) -> None:
        host = source(HOST)
        self.assertIn('"--wasm-profile-indexed-db-smoke=" + this.payload.mode', host)
        self.assertIn('"--wasm-profile-indexed-db-token-a=" + this.payload.tokenA', host)
        self.assertIn('"--wasm-profile-indexed-db-token-b=" + this.payload.tokenB', host)
        self.assertIn('"./bootstrap/" + this.context.session', host)
        self.assertIn('"./ready/" + this.context.resultToken', host)
        self.assertIn('"./result/" + this.context.resultToken', host)
        self.assertEqual(host.count('MARKER_PREFIX + "BACKING_STORES_CLOSED sha256="'), 3)
        self.assertEqual(host.count('MARKER_PREFIX + "FENCE_OK sha256="'), 3)
        self.assertEqual(host.count('MARKER_PREFIX + "LEASE_RELEASED"'), 3)
        self.assertIn("renderer-verify-a-write-b", host)
        self.assertIn("renderer-verify-b", host)
        self.assertIn("postDocumentEvidence", host)
        self.assertIn("postReady", host)
        self.assertLess(
            host.index("await this.postDocumentEvidence();"),
            host.index("this.payload = await this.fetchBootstrap();"),
        )

    def test_browser_side_page_is_external_script_only_and_uses_real_indexeddb(self) -> None:
        page = source("chrome/browser/wasm/wasm_profile_renderer_indexed_db_ui.cc")
        self.assertIn('<script src="m7_indexed_db_renderer.js"></script>', page)
        self.assertIn("globalThis.indexedDB", page)
        self.assertNotIn("localStorage", page)
        self.assertNotIn("navigator.locks", page)
        self.assertIn("renderer-write", page)
        self.assertIn("renderer-verify-a-write-b", page)
        self.assertIn("renderer-verify-b", page)
        self.assertIn("m7-indexed-db-renderer-write-ok", page)
        self.assertIn("m7-indexed-db-renderer-verify-a-write-b-ok", page)
        self.assertIn("m7-indexed-db-renderer-verify-b-ok", page)
        self.assertIn("m7-indexed-db-failed", page)
        self.assertIn("m7-renderer-indexed-db-close-fence-v1", page)
        self.assertIn("transaction.oncomplete", page)

    def test_source_selected_build_contract_is_not_a_generic_renderer_database_target(self) -> None:
        gni = source("chrome/browser/wasm/wasm_profile_indexed_db_smoke.gni")
        chrome_build = source("chrome/BUILD.gn")
        self.assertIn("enable_chromium_wasm_m7_profile_indexed_db_test", gni)
        self.assertIn("chrome_wasm_m7_profile_indexed_db_test", chrome_build)
        self.assertIn("CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST=1", chrome_build)
        self.assertNotIn("chrome_wasm_m7_renderer_database_test", chrome_build)


if __name__ == "__main__":
    unittest.main()
