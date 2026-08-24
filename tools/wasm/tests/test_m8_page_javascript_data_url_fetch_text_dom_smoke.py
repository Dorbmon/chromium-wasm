#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the bounded M8 data URL fetch/Response.text diagnostic."""

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


def successful_data_url_fetch_text_result() -> dict[str, object]:
    readiness = {
        "shellReady": True,
        "surfaceReady": True,
        "firstVisuallyNonEmptyPaint": True,
    }
    return {
        "protocol": 1,
        "case": smoke.PAGE_JAVASCRIPT_DATA_URL_FETCH_TEXT_CASE,
        "scope": smoke.PAGE_JAVASCRIPT_DATA_URL_FETCH_TEXT_SCOPE,
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
        "pageJavaScriptDataUrlFetchResponseObserved": True,
        "pageJavaScriptDataUrlFetchTextObserved": True,
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
            smoke.PAGE_JAVASCRIPT_DATA_URL_FETCH_TEXT_RESPONSE_MARKER,
            smoke.PAGE_JAVASCRIPT_DATA_URL_FETCH_TEXT_TEXT_MARKER,
            smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
            smoke.RUNTIME_EVALUATE_MARKER,
            smoke.PAGE_JAVASCRIPT_DATA_URL_FETCH_TEXT_MARKER,
            smoke.DETACHED_MARKER,
            smoke.LIFECYCLE_PASS_MARKER,
        ],
        "failedChecks": [],
        "error": None,
    }


class M8PageJavaScriptDataUrlFetchTextDomSmokeTest(unittest.TestCase):
    def test_mode_is_fixed_experimental_and_false_only(self) -> None:
        config = smoke.PAGE_JAVASCRIPT_DATA_URL_FETCH_TEXT_SMOKE_CONFIG
        self.assertEqual(config.mode_id, "page-javascript-data-url-fetch-text")
        self.assertEqual(config.query_mode, "page-javascript-data-url-fetch-text")
        self.assertEqual(
            config.sentinel,
            "CHROMIUM_WASM_M8_PAGE_JAVASCRIPT_DATA_URL_FETCH_TEXT_DOM",
        )
        self.assertEqual(
            config.runtime_arguments,
            ("--wasm-browser-m8-page-javascript-data-url-fetch-text-smoke",),
        )
        self.assertEqual(config.page_webassembly_expectations, ())
        self.assertEqual(
            config.ordinary_javascript_expectations,
            (
                ("v8ProvenanceEstablished", False),
                ("pageJavaScriptDataUrlFetchResponseObserved", True),
                ("pageJavaScriptDataUrlFetchTextObserved", True),
            ),
        )
        self.assertIn(
            "does_not_establish_v8_dependency_or_artifact_source_provenance",
            config.limitations,
        )
        self.assertIn("does_not_claim_m8_compatibility_completion", config.limitations)
        self.assertIs(
            smoke.smoke_config_for_page_javascript_data_url_fetch_text(True),
            config,
        )
        self.assertIs(
            smoke.smoke_config_for_page_javascript_data_url_fetch_text(False),
            smoke.DEFAULT_SMOKE_CONFIG,
        )

    def test_mode_requires_the_experimental_codegen_profile(self) -> None:
        m6 = smoke.chrome_build_profile(smoke.M6_CHROME_BUILD_PROFILE)
        codegen = smoke.chrome_build_profile(
            smoke.M8_CHROME_CODEGEN_EXPERIMENT_BUILD_PROFILE
        )
        with self.assertRaisesRegex(
            M0Error,
            "page-JavaScript data URL fetch text mode requires --build-profile "
            "m8-codegen-experiment",
        ):
            smoke.require_build_profile_for_smoke(
                m6, smoke.PAGE_JAVASCRIPT_DATA_URL_FETCH_TEXT_SMOKE_CONFIG
            )
        smoke.require_build_profile_for_smoke(
            codegen, smoke.PAGE_JAVASCRIPT_DATA_URL_FETCH_TEXT_SMOKE_CONFIG
        )

    def test_result_requires_two_ordered_phases_and_false_gates(self) -> None:
        config = smoke.PAGE_JAVASCRIPT_DATA_URL_FETCH_TEXT_SMOKE_CONFIG
        smoke.validate_result(
            successful_data_url_fetch_text_result(),
            expected_versions=VERSIONS,
            smoke_config=config,
        )
        for field, expected in config.ordinary_javascript_expectations:
            with self.subTest(field=field):
                result = copy.deepcopy(successful_data_url_fetch_text_result())
                result[field] = not expected
                with self.assertRaisesRegex(M0Error, rf"{field} mismatch"):
                    smoke.validate_result(
                        result, expected_versions=VERSIONS, smoke_config=config
                    )

        result = successful_data_url_fetch_text_result()
        result["stderr"][2], result["stderr"][3] = (
            result["stderr"][3],
            result["stderr"][2],
        )
        with self.assertRaisesRegex(M0Error, "phase markers are not ordered"):
            smoke.validate_result(
                result, expected_versions=VERSIONS, smoke_config=config
            )

        result = successful_data_url_fetch_text_result()
        result["m8GateComplete"] = True
        with self.assertRaisesRegex(M0Error, "m8GateComplete mismatch"):
            smoke.validate_result(
                result, expected_versions=VERSIONS, smoke_config=config
            )

    def test_url_and_result_payload_bind_the_closed_mode(self) -> None:
        config = smoke.PAGE_JAVASCRIPT_DATA_URL_FETCH_TEXT_SMOKE_CONFIG
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
            ["page-javascript-data-url-fetch-text"],
        )
        payload = json.dumps(successful_data_url_fetch_text_result()).encode("utf-8")
        self.assertEqual(
            smoke.parse_result_payload(payload, smoke_config=config),
            successful_data_url_fetch_text_result(),
        )
        self.assertIsNone(smoke.parse_result_payload(payload))

    def test_host_is_token_bound_and_does_not_own_the_page_fetch(self) -> None:
        host = source(
            "tools/wasm/host/chrome_wasm_browser_devtools_protocol_smoke_host.js"
        )
        for expected in (
            "PAGE_JAVASCRIPT_DATA_URL_FETCH_TEXT_SMOKE_MODE",
            "PAGE_JAVASCRIPT_DATA_URL_FETCH_TEXT_RESPONSE_MARKER",
            "PAGE_JAVASCRIPT_DATA_URL_FETCH_TEXT_TEXT_MARKER",
            "pageJavaScriptDataUrlFetchResponseObserved:",
            "pageJavaScriptDataUrlFetchTextObserved:",
            'query.getAll("mode")',
            "fetchExpectedSmokeMode",
            "arguments: [...this.#smokeMode.runtimeArguments]",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, host)
        for forbidden in (
            "chromium-wasm-m8-fixed-fetch-text-42",
            "fetch('data:text/plain;charset=utf-8",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, host)

    def test_native_route_has_only_the_fixed_two_phase_fetch_witness(self) -> None:
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        lifecycle = source("chrome/browser/wasm/wasm_browser_lifecycle.cc")
        lifecycle_header = source("chrome/browser/wasm/wasm_browser_lifecycle.h")
        protocol_header = source(
            "chrome/browser/wasm/wasm_browser_devtools_protocol_smoke.h"
        )
        protocol = source("chrome/browser/wasm/wasm_browser_devtools_protocol_smoke.cc")
        runner = source("tools/wasm/run_m8_wasm_browser_devtools_protocol_dom_smoke.py")

        self.assertIn(
            '"wasm-browser-m8-page-javascript-data-url-fetch-text-smoke"',
            main_parts,
        )
        self.assertEqual(
            main_parts.count("browser_m8_page_javascript_data_url_fetch_text_smoke"),
            3,
        )
        self.assertIn(
            "StartPageJavaScriptDataUrlFetchTextDevToolsProtocolSmoke", main_parts
        )
        self.assertIn(
            "StartPageJavaScriptDataUrlFetchTextDevToolsProtocolSmoke", lifecycle
        )
        self.assertIn(
            "StartPageJavaScriptDataUrlFetchTextDevToolsProtocolSmoke",
            lifecycle_header,
        )
        self.assertIn("kOrdinaryJavaScriptDataUrlFetchText", protocol_header)
        self.assertIn("--page-javascript-data-url-fetch-text", runner)
        self.assertIn("smoke_config_for_page_javascript_data_url_fetch_text", runner)

        command_start = protocol.index(
            "kPageJavaScriptDataUrlFetchTextRuntimeEvaluateCommand"
        )
        command_end = protocol.index(
            "constexpr char kPageWebAssemblyRuntimeEvaluateCommand", command_start
        )
        command = protocol[command_start:command_end]
        expected_order = (
            "const response=await fetch('data:text/plain;charset=utf-8,chromium-wasm-m8-fixed-fetch-text-42')",
            "console.log('chromium-wasm-m8-page-javascript-data-url-fetch-response-ok')",
            "const text=await response.text()",
            "console.log('chromium-wasm-m8-page-javascript-data-url-fetch-text-42-ok')",
            "return 'page-javascript-data-url-fetch-response-text-42-ok'",
        )
        positions = []
        for expected in expected_order:
            with self.subTest(expected=expected):
                self.assertIn(expected, command)
                positions.append(command.index(expected))
        self.assertEqual(positions, sorted(positions))
        for expected in (
            '"awaitPromise":true',
            '"returnByValue":true',
            "kPageJavaScriptDataUrlFetchTextResponseSuccessMarker",
            "kPageJavaScriptDataUrlFetchTextTextSuccessMarker",
            "runtime_console_api_call_count_ == 0",
            "runtime_console_api_call_count_ == 1",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, protocol)
        for forbidden in ("WebAssembly", "AbortController", "ReadableStream"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, command)


if __name__ == "__main__":
    unittest.main()
