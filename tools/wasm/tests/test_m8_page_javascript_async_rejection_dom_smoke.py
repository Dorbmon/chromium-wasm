#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the bounded M8 async-rejection page smoke."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m8_wasm_browser_devtools_protocol_dom_smoke as smoke
from tools.wasm.tests.m3_source_contract_test_support import source


VERSIONS = {"chromium": "c", "v8": "v", "emscripten": "e", "port": "p"}


def successful_async_rejection_result() -> dict[str, object]:
    readiness = {
        "shellReady": True,
        "surfaceReady": True,
        "firstVisuallyNonEmptyPaint": True,
    }
    return {
        "protocol": 1,
        "case": smoke.PAGE_JAVASCRIPT_ASYNC_REJECTION_CASE,
        "scope": smoke.PAGE_JAVASCRIPT_ASYNC_REJECTION_SCOPE,
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
        "v8ProvenanceEstablished": False,
        "pageJavaScriptAsyncRejectionCatchFinallyOrderObserved": True,
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
            smoke.PAGE_JAVASCRIPT_ASYNC_REJECTION_MARKER,
            smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
            smoke.DETACHED_MARKER,
            smoke.LIFECYCLE_PASS_MARKER,
        ],
        "failedChecks": [],
        "error": None,
    }


class M8PageJavaScriptAsyncRejectionDomSmokeTest(unittest.TestCase):
    def test_mode_is_fixed_experimental_and_false_only(self) -> None:
        config = smoke.PAGE_JAVASCRIPT_ASYNC_REJECTION_SMOKE_CONFIG
        self.assertEqual(config.mode_id, "page-javascript-async-rejection")
        self.assertEqual(config.query_mode, "page-javascript-async-rejection")
        self.assertEqual(
            config.sentinel,
            "CHROMIUM_WASM_M8_PAGE_JAVASCRIPT_ASYNC_REJECTION_DOM",
        )
        self.assertEqual(
            config.runtime_arguments,
            ("--wasm-browser-m8-page-javascript-async-rejection-smoke",),
        )
        self.assertEqual(config.page_webassembly_expectations, ())
        self.assertEqual(
            config.ordinary_javascript_expectations,
            (
                ("v8ProvenanceEstablished", False),
                ("pageJavaScriptAsyncRejectionCatchFinallyOrderObserved", True),
            ),
        )
        self.assertIn(
            "does_not_establish_v8_dependency_or_artifact_source_provenance",
            config.limitations,
        )
        self.assertIn("does_not_claim_m8_compatibility_completion", config.limitations)
        self.assertIs(
            smoke.smoke_config_for_page_javascript_async_rejection(True), config
        )
        self.assertIs(
            smoke.smoke_config_for_page_javascript_async_rejection(False),
            smoke.DEFAULT_SMOKE_CONFIG,
        )

    def test_mode_requires_the_experimental_codegen_profile(self) -> None:
        m6 = smoke.chrome_build_profile(smoke.M6_CHROME_BUILD_PROFILE)
        codegen = smoke.chrome_build_profile(
            smoke.M8_CHROME_CODEGEN_EXPERIMENT_BUILD_PROFILE
        )
        with self.assertRaisesRegex(
            M0Error,
            "page-JavaScript async rejection mode requires --build-profile "
            "m8-codegen-experiment",
        ):
            smoke.require_build_profile_for_smoke(
                m6, smoke.PAGE_JAVASCRIPT_ASYNC_REJECTION_SMOKE_CONFIG
            )
        smoke.require_build_profile_for_smoke(
            codegen, smoke.PAGE_JAVASCRIPT_ASYNC_REJECTION_SMOKE_CONFIG
        )

    def test_result_requires_the_fixed_witness_and_false_gates(self) -> None:
        config = smoke.PAGE_JAVASCRIPT_ASYNC_REJECTION_SMOKE_CONFIG
        smoke.validate_result(
            successful_async_rejection_result(),
            expected_versions=VERSIONS,
            smoke_config=config,
        )
        for field, expected in config.ordinary_javascript_expectations:
            with self.subTest(field=field):
                result = copy.deepcopy(successful_async_rejection_result())
                result[field] = not expected
                with self.assertRaisesRegex(M0Error, rf"{field} mismatch"):
                    smoke.validate_result(
                        result, expected_versions=VERSIONS, smoke_config=config
                    )
        result = successful_async_rejection_result()
        result["m8GateComplete"] = True
        with self.assertRaisesRegex(M0Error, "m8GateComplete mismatch"):
            smoke.validate_result(
                result, expected_versions=VERSIONS, smoke_config=config
            )

    def test_result_rejects_wrong_or_repeated_native_marker(self) -> None:
        config = smoke.PAGE_JAVASCRIPT_ASYNC_REJECTION_SMOKE_CONFIG
        result = successful_async_rejection_result()
        result["stderr"] = [
            smoke.NETWORK_ENABLE_MARKER,
            smoke.RUNTIME_ENABLE_MARKER,
            smoke.RUNTIME_EVALUATE_MARKER,
            smoke.PAGE_JAVASCRIPT_SEMANTICS_MARKER,
            smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
            smoke.DETACHED_MARKER,
            smoke.LIFECYCLE_PASS_MARKER,
        ]
        with self.assertRaisesRegex(M0Error, "marker count is 0"):
            smoke.validate_result(
                result, expected_versions=VERSIONS, smoke_config=config
            )

        result = successful_async_rejection_result()
        result["stderr"] = result["stderr"] + [
            smoke.PAGE_JAVASCRIPT_ASYNC_REJECTION_MARKER,
        ]
        with self.assertRaisesRegex(M0Error, "marker count is 2"):
            smoke.validate_result(
                result, expected_versions=VERSIONS, smoke_config=config
            )

    def test_url_binds_the_closed_mode_and_result_shape(self) -> None:
        config = smoke.PAGE_JAVASCRIPT_ASYNC_REJECTION_SMOKE_CONFIG
        server = SimpleNamespace(server_address=("127.0.0.1", 31337))
        url = smoke.smoke_url(
            server,
            "token",
            VERSIONS,
            module_name="chrome_wasm",
            timeout_seconds=30.0,
            smoke_config=config,
        )
        self.assertEqual(
            parse_qs(urlsplit(url).query, keep_blank_values=True)["mode"],
            ["page-javascript-async-rejection"],
        )
        payload = json.dumps(successful_async_rejection_result()).encode("utf-8")
        self.assertEqual(
            smoke.parse_result_payload(payload, smoke_config=config),
            successful_async_rejection_result(),
        )
        self.assertIsNone(smoke.parse_result_payload(payload))

    def test_host_keeps_the_async_witness_native_and_token_bound(self) -> None:
        host = source(
            "tools/wasm/host/chrome_wasm_browser_devtools_protocol_smoke_host.js"
        )
        for expected in (
            'const PAGE_JAVASCRIPT_ASYNC_REJECTION_MODE = "page-javascript-async-rejection";',
            "PAGE_JAVASCRIPT_ASYNC_REJECTION_SMOKE_MODE",
            "PAGE_JAVASCRIPT_ASYNC_REJECTION_MARKER",
            "pageJavaScriptAsyncRejectionCatchFinallyOrderObserved:",
            "query.getAll(\"mode\")",
            "fetchExpectedSmokeMode",
            "arguments: [...this.#smokeMode.runtimeArguments]",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, host)
        for forbidden in (
            "Promise.reject('fixed-rejection')",
            "order.push('finally')",
            "page-javascript-async-rejection-catch-finally-order-ok",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, host)

    def test_native_route_is_fixed_and_arms_the_lifecycle_smoke(self) -> None:
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        lifecycle = source("chrome/browser/wasm/wasm_browser_lifecycle.cc")
        protocol_header = source(
            "chrome/browser/wasm/wasm_browser_devtools_protocol_smoke.h"
        )
        protocol = source("chrome/browser/wasm/wasm_browser_devtools_protocol_smoke.cc")
        runner = source("tools/wasm/run_m8_wasm_browser_devtools_protocol_dom_smoke.py")
        self.assertIn(
            '"wasm-browser-m8-page-javascript-async-rejection-smoke"', main_parts
        )
        self.assertIn(
            "const bool browser_m8_page_javascript_async_rejection_smoke =",
            main_parts,
        )
        self.assertEqual(
            main_parts.count("browser_m8_page_javascript_async_rejection_smoke"),
            3,
        )
        self.assertIn(
            "browser_m8_page_javascript_semantics_smoke ||\n"
            "      browser_m8_page_javascript_async_rejection_smoke ||\n"
            "      browser_m8_page_javascript_platform_semantics_smoke ||\n"
            "      browser_m8_page_webassembly_smoke",
            main_parts,
        )
        self.assertIn(
            "browser_m8_page_javascript_semantics_smoke) +\n"
            "                 static_cast<int>(\n"
            "                     browser_m8_page_javascript_async_rejection_smoke) +\n"
            "                 static_cast<int>(\n"
            "                     browser_m8_page_javascript_platform_semantics_smoke) +\n"
            "                 static_cast<int>(browser_m8_page_webassembly_smoke)",
            main_parts,
        )
        self.assertIn(
            "StartPageJavaScriptAsyncRejectionDevToolsProtocolSmoke", main_parts
        )
        self.assertIn(
            "StartPageJavaScriptAsyncRejectionDevToolsProtocolSmoke", lifecycle
        )
        self.assertIn("kOrdinaryJavaScriptAsyncRejection", protocol_header)
        self.assertIn("--page-javascript-async-rejection", runner)

        command_start = protocol.index(
            "kPageJavaScriptAsyncRejectionRuntimeEvaluateCommand"
        )
        command_end = protocol.index(
            "constexpr char kPageWebAssemblyRuntimeEvaluateCommand", command_start
        )
        command = protocol[command_start:command_end]
        for expected in (
            "Promise.reject('fixed-rejection')",
            "catch(error)",
            "finally{order.push('finally');}",
            "order.join(',')!=='try,catch,finally,after'",
            '"awaitPromise":true',
            '"returnByValue":true',
            "page-javascript-async-rejection-catch-finally-order-ok",
            "chromium-wasm-m8-page-javascript-async-rejection-catch-finally-order",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, command)
        for forbidden in ("WebAssembly", "fetch(", "SharedArrayBuffer", "setTimeout"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, command)


if __name__ == "__main__":
    unittest.main()
