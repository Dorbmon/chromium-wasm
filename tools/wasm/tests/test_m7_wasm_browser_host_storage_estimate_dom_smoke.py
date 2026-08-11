#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Result and host contracts for the M7 native-Settings storage smoke."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m7_wasm_browser_host_storage_estimate_dom_smoke as smoke
from tools.wasm.tests.m3_source_contract_test_support import source


VERSIONS = {"chromium": "c", "v8": "v", "emscripten": "e", "port": "p"}


def successful_result() -> dict[str, object]:
    readiness = {
        "shellReady": True,
        "surfaceReady": True,
        "firstVisuallyNonEmptyPaint": True,
    }
    return {
        "protocol": 1,
        "case": smoke.CASE,
        "scope": smoke.SCOPE,
        "status": "pass",
        "m7GateComplete": False,
        "runtimeExitCode": 0,
        "processExitCode": 0,
        "runtimeInitialized": True,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "readyObserved": True,
        "settingsNavigatedObserved": True,
        "passObserved": True,
        "storageResult": {
            "generation": 1,
            "status": "available",
            "delivered": True,
        },
        "storageCheckQueued": True,
        "storageCheckAccepted": True,
        "settingsPresentationQueued": True,
        "settingsPresentationAccepted": True,
        "fixedOrdinals": [1, 2],
        "navigationMarkerFrameId": 2,
        "frameIdAfterNavigation": 3,
        "abort": None,
        "fatalErrors": [],
        "windowErrors": [],
        "unhandledRejections": [],
        "versions": VERSIONS,
        "frameReports": [
            {"id": 1, "width": 640, "height": 480, "timestampMs": 1.0},
            {"id": 2, "width": 640, "height": 480, "timestampMs": 2.0},
            {"id": 3, "width": 640, "height": 480, "timestampMs": 3.0},
        ],
        "readiness": readiness,
        "readinessReports": [readiness],
        "stdout": [],
        "stderr": [
            smoke.READY_MARKER,
            smoke.NAVIGATED_MARKER,
            smoke.PASS_MARKER,
        ],
        "failedChecks": [],
        "error": None,
    }


class M7WasmBrowserHostStorageEstimateDomSmokeTest(unittest.TestCase):
    def test_accepts_native_settings_snapshot_and_later_frame_evidence(self) -> None:
        smoke.validate_result(successful_result(), expected_versions=VERSIONS)

    def test_rejects_nonterminal_estimate_wrong_ordinal_or_no_later_frame(self) -> None:
        mutations = (
            (
                lambda result: result["storageResult"].__setitem__(
                    "status", "error"
                ),
                "did not accept an available estimate",
            ),
            (
                lambda result: result["storageResult"].__setitem__(
                    "delivered", False
                ),
                "did not accept an available estimate",
            ),
            (
                lambda result: result.__setitem__("fixedOrdinals", [1, 3]),
                "fixedOrdinals mismatch",
            ),
            (
                lambda result: result.__setitem__("frameIdAfterNavigation", 2),
                "strictly later frame",
            ),
            (
                lambda result: result["storageResult"].__setitem__(
                    "usageBytes", 1
                ),
                "invalid storage-result shape",
            ),
        )
        for mutate, expression in mutations:
            with self.subTest(expression=expression):
                result = copy.deepcopy(successful_result())
                mutate(result)
                with self.assertRaisesRegex(M0Error, expression):
                    smoke.validate_result(result, expected_versions=VERSIONS)

    def test_result_parser_rejects_duplicate_keys_and_wrong_scope(self) -> None:
        payload = json.dumps(successful_result()).encode("utf-8")
        self.assertIsNotNone(smoke.parse_result_payload(payload))
        self.assertIsNone(
            smoke.parse_result_payload(
                b'{"protocol":1,"protocol":1,"case":"browser_host_storage_estimate_m7",'
                b'"scope":"outer-origin-estimate-native-settings-webui-later-frame"}'
            )
        )
        wrong_scope = successful_result()
        wrong_scope["scope"] = "wrong"
        self.assertIsNone(
            smoke.parse_result_payload(json.dumps(wrong_scope).encode("utf-8"))
        )

    def test_dedicated_host_defers_fixed_exports_and_runner_serves_adapter(self) -> None:
        host = source(
            "tools/wasm/host/chrome_wasm_browser_host_storage_estimate_smoke_host.js"
        )
        adapter = source("tools/wasm/host/chrome_wasm_storage_estimate.js")
        runner = source(
            "tools/wasm/run_m7_wasm_browser_host_storage_estimate_dom_smoke.py"
        )
        self.assertIn("Promise.resolve()", adapter)
        for marker in (
            'import {ChromiumWasmOuterOriginStorageEstimate} from "./chrome_wasm_storage_estimate.js";',
            "this.#storageCheckQueued = true;",
            "this.#settingsPresentationQueued = true;",
            "setTimeout(() => {",
            "chromium_wasm_browser_host_storage_estimate_check",
            "chromium_wasm_browser_host_storage_estimate_presented",
            "frameIdAfterNavigation",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, host)
        for forbidden in ("NavigationController", "LoadURL", "OpenURL", "Page.navigate"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, host)
        for marker in (
            'HOST_ROOT = "/__m7_browser_host_storage_estimate__"',
            "chrome_wasm_browser_host_storage_estimate_smoke_host.js",
            "chrome_wasm_storage_estimate.js",
            '"application/wasm"',
            '"Cross-Origin-Opener-Policy", "same-origin"',
            "verify_explicit_smoke_exports",
            "wait_for_normal_close_result",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, runner)
        self.assertNotIn("ccall(", runner)

    def test_host_javascript_parses_with_node_when_available(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is unavailable")
        for path in (
            "tools/wasm/host/chrome_wasm_storage_estimate.js",
            "tools/wasm/host/chrome_wasm_browser_host_storage_estimate_smoke_host.js",
        ):
            with self.subTest(path=path):
                completed = subprocess.run(
                    [node, "--check", str(TOOLS_DIR.parents[1] / path)],
                    capture_output=True,
                    encoding="utf-8",
                    check=False,
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    "Node rejected storage-estimate host asset:\n"
                    + completed.stdout
                    + completed.stderr,
                )


if __name__ == "__main__":
    unittest.main()
