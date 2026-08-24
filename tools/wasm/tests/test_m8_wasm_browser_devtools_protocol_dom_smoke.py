#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the real-browser fixed M8 DevTools protocol smoke."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m8_wasm_browser_devtools_protocol_dom_smoke as smoke
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
        "m8GateComplete": False,
        "runtimeExitCode": 0,
        "processExitCode": 0,
        "runtimeInitialized": True,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocusAccepted": True,
        "networkEnableObserved": True,
        "runtimeEnableObserved": True,
        "runtimeEvaluateObserved": True,
        "pageWebAssemblyUnavailableObserved": True,
        "runtimeConsoleApiCalledObserved": True,
        "detachedObserved": True,
        "lifecyclePassObserved": True,
        "abort": None,
        "fatalErrors": [],
        "windowErrors": [],
        "unhandledRejections": [],
        "versions": VERSIONS,
        "frameReports": [
            {"id": 1, "width": 640, "height": 480, "timestampMs": 1.0},
        ],
        "readiness": readiness,
        "readinessReports": [readiness],
        "stdout": [],
        "stderr": [
            smoke.NETWORK_ENABLE_MARKER,
            smoke.RUNTIME_ENABLE_MARKER,
            smoke.RUNTIME_EVALUATE_MARKER,
            smoke.PAGE_WEBASSEMBLY_UNAVAILABLE_MARKER,
            smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
            smoke.DETACHED_MARKER,
            smoke.LIFECYCLE_PASS_MARKER,
        ],
        "failedChecks": [],
        "error": None,
    }


class M8WasmBrowserDevToolsProtocolDomSmokeTest(unittest.TestCase):
    def test_accepts_fixed_native_devtools_exchange(self) -> None:
        smoke.validate_result(successful_result(), expected_versions=VERSIONS)

    def test_accepts_console_event_before_evaluate_response(self) -> None:
        result = successful_result()
        result["stderr"] = [
            smoke.NETWORK_ENABLE_MARKER,
            smoke.RUNTIME_ENABLE_MARKER,
            smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
            smoke.RUNTIME_EVALUATE_MARKER,
            smoke.PAGE_WEBASSEMBLY_UNAVAILABLE_MARKER,
            smoke.DETACHED_MARKER,
            smoke.LIFECYCLE_PASS_MARKER,
        ]
        smoke.validate_result(result, expected_versions=VERSIONS)

    def test_rejects_missing_repeated_failed_or_misordered_markers(self) -> None:
        mutations = (
            (
                lambda result: result.__setitem__(
                    "stderr",
                    [
                        smoke.NETWORK_ENABLE_MARKER,
                        smoke.RUNTIME_ENABLE_MARKER,
                        smoke.RUNTIME_EVALUATE_MARKER,
                        smoke.PAGE_WEBASSEMBLY_UNAVAILABLE_MARKER,
                        smoke.DETACHED_MARKER,
                        smoke.LIFECYCLE_PASS_MARKER,
                    ],
                ),
                "marker count is 0",
            ),
            (
                lambda result: result.__setitem__(
                    "stderr",
                    [
                        smoke.NETWORK_ENABLE_MARKER,
                        smoke.RUNTIME_ENABLE_MARKER,
                        smoke.RUNTIME_EVALUATE_MARKER,
                        smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
                        smoke.DETACHED_MARKER,
                        smoke.LIFECYCLE_PASS_MARKER,
                    ],
                ),
                "marker count is 0",
            ),
            (
                lambda result: result.__setitem__(
                    "stderr",
                    [
                        smoke.NETWORK_ENABLE_MARKER,
                        smoke.RUNTIME_ENABLE_MARKER,
                        smoke.RUNTIME_EVALUATE_MARKER,
                        smoke.RUNTIME_EVALUATE_MARKER,
                        smoke.PAGE_WEBASSEMBLY_UNAVAILABLE_MARKER,
                        smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
                        smoke.DETACHED_MARKER,
                        smoke.LIFECYCLE_PASS_MARKER,
                    ],
                ),
                "marker count is 2",
            ),
            (
                lambda result: result.__setitem__(
                    "stderr",
                    [
                        smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
                        smoke.NETWORK_ENABLE_MARKER,
                        smoke.RUNTIME_ENABLE_MARKER,
                        smoke.RUNTIME_EVALUATE_MARKER,
                        smoke.PAGE_WEBASSEMBLY_UNAVAILABLE_MARKER,
                        smoke.DETACHED_MARKER,
                        smoke.LIFECYCLE_PASS_MARKER,
                    ],
                ),
                "not ordered",
            ),
            (
                lambda result: result.__setitem__(
                    "stderr",
                    successful_result()["stderr"] + [smoke.FAILURE_MARKER],
                ),
                "failure marker",
            ),
        )
        for mutate, expression in mutations:
            with self.subTest(expression=expression):
                result = copy.deepcopy(successful_result())
                mutate(result)
                with self.assertRaisesRegex(M0Error, expression):
                    smoke.validate_result(result, expected_versions=VERSIONS)

    def test_rejects_host_or_runtime_lifecycle_failures(self) -> None:
        mutations = (
            (
                lambda result: result.__setitem__("runtimeExitCode", 13),
                "runtimeExitCode mismatch",
            ),
            (
                lambda result: result.__setitem__("canvasFocusAccepted", False),
                "canvasFocusAccepted mismatch",
            ),
            (
                lambda result: result.__setitem__(
                    "pageWebAssemblyUnavailableObserved", False
                ),
                "pageWebAssemblyUnavailableObserved mismatch",
            ),
            (
                lambda result: result.__setitem__(
                    "fatalErrors", ["native host callback failed"]
                ),
                "fatalErrors is not empty",
            ),
            (
                lambda result: result.__setitem__(
                    "versions", {**VERSIONS, "port": "different"}
                ),
                "versions do not match",
            ),
        )
        for mutate, expression in mutations:
            with self.subTest(expression=expression):
                result = copy.deepcopy(successful_result())
                mutate(result)
                with self.assertRaisesRegex(M0Error, expression):
                    smoke.validate_result(result, expected_versions=VERSIONS)

    def test_parses_only_one_expected_result_object(self) -> None:
        result = successful_result()
        self.assertEqual(
            smoke.parse_result_payload(json.dumps(result).encode("utf-8")),
            result,
        )
        self.assertIsNone(
            smoke.parse_result_payload(
                (
                    b'{"protocol":1,"protocol":1,"case":"'
                    + smoke.CASE.encode("utf-8")
                    + b'","scope":"'
                    + smoke.SCOPE.encode("utf-8")
                    + b'"}'
                )
            )
        )
        bool_protocol = copy.deepcopy(result)
        bool_protocol["protocol"] = True
        self.assertIsNone(
            smoke.parse_result_payload(json.dumps(bool_protocol).encode("utf-8"))
        )
        altered = copy.deepcopy(result)
        altered["scope"] = "unexpected"
        self.assertIsNone(
            smoke.parse_result_payload(json.dumps(altered).encode("utf-8"))
        )

    def test_artifact_identity_is_bound_to_the_served_snapshot(self) -> None:
        server = SimpleNamespace(
            module_name="chrome_wasm",
            artifacts={
                "chrome_wasm.js": b"loader",
                "chrome_wasm.wasm": b"wasm",
            },
        )
        self.assertEqual(
            smoke.artifact_identity(server),
            {
                "delivery": smoke.ARTIFACT_DELIVERY,
                "module": "chrome_wasm",
                "loader": {
                    "bytes": 6,
                    "sha256": (
                        "d47712cceb4c780603026e6325221c1bcff90679ebc0"
                        "76baa51c71ebe796717c"
                    ),
                },
                "wasm": {
                    "bytes": 4,
                    "sha256": (
                        "336154bf67f765f8f75d16a0accee61b5ee5f6a75b2a"
                        "2905703df913bd550f3e"
                    ),
                },
            },
        )

    def test_host_and_runner_stay_real_browser_and_fixed_protocol_only(self) -> None:
        host = source(
            "tools/wasm/host/chrome_wasm_browser_devtools_protocol_smoke_host.js"
        )
        runner = source("tools/wasm/run_m8_wasm_browser_devtools_protocol_dom_smoke.py")
        html = source(
            "tools/wasm/host/chrome_wasm_browser_devtools_protocol_smoke.html"
        )

        for expected in (
            'const SWITCH = "--wasm-browser-devtools-protocol-smoke";',
            "Cross-Origin-Opener-Policy",
            "Cross-Origin-Embedder-Policy",
            "application/wasm",
            "snapshot_regular_files",
            "immutable-in-memory-server-snapshot",
            "requestOuterOriginStorageEstimate(_report) { return false; }",
            "reportOzoneBrowserClipboardPasteDelivery(_report) {}",
            "PAGE_WEBASSEMBLY_UNAVAILABLE_MARKER",
            "RUNTIME_CONSOLE_API_CALLED_MARKER",
            "LIFECYCLE_PASS_MARKER",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, host + runner)
        self.assertIn("tabindex=\"0\"", html)
        self.assertIn(
            "runChromeWasmBrowserDevToolsProtocolSmokeFromQuery", html
        )
        for forbidden in ("WebSocket", "ccall(", "Runtime.evaluate("):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, host + runner)


if __name__ == "__main__":
    unittest.main()
