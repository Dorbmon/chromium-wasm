#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the bounded M8 page-WebAssembly-memory browser-host smoke."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m8_wasm_browser_devtools_protocol_dom_smoke as smoke
from tools.wasm.tests.m3_source_contract_test_support import source


VERSIONS = {"chromium": "c", "v8": "v", "emscripten": "e", "port": "p"}


def successful_page_memory_result() -> dict[str, object]:
    readiness = {
        "shellReady": True,
        "surfaceReady": True,
        "firstVisuallyNonEmptyPaint": True,
    }
    return {
        "protocol": 1,
        "case": smoke.PAGE_WEBASSEMBLY_MEMORY_CASE,
        "scope": smoke.PAGE_WEBASSEMBLY_MEMORY_SCOPE,
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
        "pageWebAssemblyUnavailableObserved": False,
        "pageWebAssemblyAdd42Observed": False,
        "pageWebAssemblyInstantiateFunctionImportModuleInstanceCallbackI32Add42Observed": False,
        "pageWebAssemblyTablesObserved": False,
        "pageWebAssemblyMemoriesObserved": True,
        "pageWebAssemblyMemoryConstructedImportedReadWriteObserved": True,
        "pageWebAssemblyExceptionsObserved": False,
        "pageWebAssemblyMemoryGrowthObserved": False,
        "pageWebAssemblyThreadsObserved": False,
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
            smoke.PAGE_WEBASSEMBLY_MEMORY_MARKER,
            smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
            smoke.DETACHED_MARKER,
            smoke.LIFECYCLE_PASS_MARKER,
        ],
        "failedChecks": [],
        "error": None,
    }


class M8PageWebAssemblyMemoryDomSmokeTest(unittest.TestCase):
    def test_page_memory_mode_is_a_single_fixed_configuration(self) -> None:
        config = smoke.PAGE_WEBASSEMBLY_MEMORY_SMOKE_CONFIG
        self.assertEqual(config.mode_id, "page-webassembly-memory")
        self.assertEqual(config.query_mode, "page-webassembly-memory")
        self.assertEqual(
            config.sentinel, "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY_MEMORY_DOM"
        )
        self.assertEqual(config.case, "browser_page_webassembly_memory_m8")
        self.assertEqual(
            config.runtime_arguments,
            ("--wasm-browser-m8-page-webassembly-memory-smoke",),
        )
        self.assertEqual(
            config.page_webassembly_expectations,
            (
                ("pageWebAssemblyUnavailableObserved", False),
                ("pageWebAssemblyAdd42Observed", False),
                (
                    "pageWebAssemblyInstantiateFunctionImportModuleInstanceCallbackI32Add42Observed",
                    False,
                ),
                ("pageWebAssemblyTablesObserved", False),
                ("pageWebAssemblyMemoriesObserved", True),
                (
                    "pageWebAssemblyMemoryConstructedImportedReadWriteObserved",
                    True,
                ),
                ("pageWebAssemblyExceptionsObserved", False),
                ("pageWebAssemblyMemoryGrowthObserved", False),
                ("pageWebAssemblyThreadsObserved", False),
            ),
        )
        self.assertEqual(
            config.native_markers,
            (
                smoke.NETWORK_ENABLE_MARKER,
                smoke.RUNTIME_ENABLE_MARKER,
                smoke.RUNTIME_EVALUATE_MARKER,
                smoke.PAGE_WEBASSEMBLY_MEMORY_MARKER,
                smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
                smoke.DETACHED_MARKER,
                smoke.LIFECYCLE_PASS_MARKER,
            ),
        )
        self.assertIs(
            smoke.smoke_config_for_page_webassembly_memory(True), config
        )
        self.assertIs(
            smoke.smoke_config_for_page_webassembly_memory(False),
            smoke.DEFAULT_SMOKE_CONFIG,
        )

    def test_page_memory_result_requires_only_its_fixed_witness(self) -> None:
        smoke.validate_result(
            successful_page_memory_result(),
            expected_versions=VERSIONS,
            smoke_config=smoke.PAGE_WEBASSEMBLY_MEMORY_SMOKE_CONFIG,
        )
        for field, value in (
            ("pageWebAssemblyUnavailableObserved", True),
            ("pageWebAssemblyAdd42Observed", True),
            ("pageWebAssemblyTablesObserved", True),
            ("pageWebAssemblyMemoriesObserved", False),
            ("pageWebAssemblyMemoryConstructedImportedReadWriteObserved", False),
            ("pageWebAssemblyExceptionsObserved", True),
            ("pageWebAssemblyMemoryGrowthObserved", True),
            ("pageWebAssemblyThreadsObserved", True),
            ("m8GateComplete", True),
        ):
            with self.subTest(field=field):
                result = copy.deepcopy(successful_page_memory_result())
                result[field] = value
                with self.assertRaisesRegex(M0Error, rf"{field} mismatch"):
                    smoke.validate_result(
                        result,
                        expected_versions=VERSIONS,
                        smoke_config=smoke.PAGE_WEBASSEMBLY_MEMORY_SMOKE_CONFIG,
                    )

    def test_page_memory_result_rejects_wrong_or_repeated_native_markers(
        self,
    ) -> None:
        result = successful_page_memory_result()
        result["stderr"] = [
            smoke.NETWORK_ENABLE_MARKER,
            smoke.RUNTIME_ENABLE_MARKER,
            smoke.RUNTIME_EVALUATE_MARKER,
            smoke.PAGE_WEBASSEMBLY_ADD42_MARKER,
            smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
            smoke.DETACHED_MARKER,
            smoke.LIFECYCLE_PASS_MARKER,
        ]
        with self.assertRaisesRegex(M0Error, "marker count is 0"):
            smoke.validate_result(
                result,
                expected_versions=VERSIONS,
                smoke_config=smoke.PAGE_WEBASSEMBLY_MEMORY_SMOKE_CONFIG,
            )

        result = successful_page_memory_result()
        result["stderr"] = successful_page_memory_result()["stderr"] + [
            smoke.PAGE_WEBASSEMBLY_MEMORY_MARKER,
        ]
        with self.assertRaisesRegex(M0Error, "marker count is 2"):
            smoke.validate_result(
                result,
                expected_versions=VERSIONS,
                smoke_config=smoke.PAGE_WEBASSEMBLY_MEMORY_SMOKE_CONFIG,
            )

    def test_url_and_server_payload_bind_the_closed_page_memory_mode(self) -> None:
        server = SimpleNamespace(server_address=("127.0.0.1", 31337))
        default_url = smoke.smoke_url(
            server,
            "token",
            VERSIONS,
            module_name="chrome_wasm",
            timeout_seconds=30.0,
        )
        memory_url = smoke.smoke_url(
            server,
            "token",
            VERSIONS,
            module_name="chrome_wasm",
            timeout_seconds=30.0,
            smoke_config=smoke.PAGE_WEBASSEMBLY_MEMORY_SMOKE_CONFIG,
        )
        self.assertNotIn("mode=", default_url)
        self.assertEqual(
            parse_qs(urlsplit(default_url).query, keep_blank_values=True),
            {
                "token": ["token"],
                "module": ["chrome_wasm"],
                "timeoutMs": ["30000"],
                "versions": [json.dumps(VERSIONS, sort_keys=True, separators=(",", ":"))],
            },
        )
        self.assertEqual(
            parse_qs(urlsplit(memory_url).query, keep_blank_values=True),
            {
                "token": ["token"],
                "module": ["chrome_wasm"],
                "timeoutMs": ["30000"],
                "versions": [
                    json.dumps(VERSIONS, sort_keys=True, separators=(",", ":"))
                ],
                "mode": ["page-webassembly-memory"],
            },
        )

        payload = json.dumps(successful_page_memory_result()).encode("utf-8")
        self.assertEqual(
            smoke.parse_result_payload(
                payload, smoke_config=smoke.PAGE_WEBASSEMBLY_MEMORY_SMOKE_CONFIG
            ),
            successful_page_memory_result(),
        )
        self.assertIsNone(smoke.parse_result_payload(payload))

    def test_server_binds_the_page_memory_mode_to_the_result_token(self) -> None:
        server = smoke.DevToolsProtocolSmokeServer(
            ("127.0.0.1", 0), smoke.DevToolsProtocolSmokeRequestHandler
        )
        server.result_token = "fixed-memory-mode-token"
        server.smoke_config = smoke.PAGE_WEBASSEMBLY_MEMORY_SMOKE_CONFIG
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            host, port = server.server_address[:2]
            binding_url = (
                f"http://{host}:{port}{smoke.HOST_ROOT}/config/fixed-memory-mode-token"
            )
            with urlopen(binding_url, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(
                    json.loads(response.read()),
                    {"protocol": 1, "mode": "page-webassembly-memory"},
                )
            with self.assertRaises(HTTPError) as context:
                urlopen(
                    f"http://{host}:{port}{smoke.HOST_ROOT}/config/wrong-token",
                    timeout=5,
                )
            self.assertEqual(context.exception.code, 404)
            context.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)

    def test_existing_modes_remain_closed_and_distinct(self) -> None:
        self.assertEqual(
            smoke.DEFAULT_SMOKE_CONFIG.runtime_arguments,
            ("--wasm-browser-devtools-protocol-smoke",),
        )
        self.assertEqual(
            smoke.DEFAULT_SMOKE_CONFIG.page_webassembly_expectations,
            (
                ("pageWebAssemblyUnavailableObserved", True),
                (
                    "pageWebAssemblyInstantiateFunctionImportModuleInstanceCallbackI32Add42Observed",
                    False,
                ),
            ),
        )
        self.assertIsNone(smoke.DEFAULT_SMOKE_CONFIG.query_mode)
        self.assertIs(
            smoke.smoke_config_for_page_webassembly(True),
            smoke.PAGE_WEBASSEMBLY_SMOKE_CONFIG,
        )
        self.assertNotEqual(
            smoke.PAGE_WEBASSEMBLY_SMOKE_CONFIG,
            smoke.PAGE_WEBASSEMBLY_MEMORY_SMOKE_CONFIG,
        )

    def test_host_rejects_query_tampering_before_the_module_loader(self) -> None:
        host = source(
            "tools/wasm/host/chrome_wasm_browser_devtools_protocol_smoke_host.js"
        )
        for expected in (
            'const PAGE_WEBASSEMBLY_MEMORY_MODE = "page-webassembly-memory";',
            "const PAGE_WEBASSEMBLY_MEMORY_SWITCH =",
            '"--wasm-browser-m8-page-webassembly-memory-smoke";',
            "PAGE_WEBASSEMBLY_MEMORY_MARKER",
            "PAGE_WEBASSEMBLY_MEMORY_SMOKE_MODE",
            "pageWebAssemblyAdd42Observed: false",
            "pageWebAssemblyTablesObserved: false",
            "pageWebAssemblyMemoriesObserved: true",
            "pageWebAssemblyMemoryConstructedImportedReadWriteObserved: true",
            "pageWebAssemblyExceptionsObserved: false",
            "pageWebAssemblyMemoryGrowthObserved: false",
            "pageWebAssemblyThreadsObserved: false",
            "query.getAll(\"mode\")",
            "DevTools protocol query has an invalid mode",
            "DevTools protocol query has an unsupported field",
            "fetchExpectedSmokeMode",
            "DevTools protocol query mode does not match its binding",
            "PAGE_WEBASSEMBLY_MEMORY_SMOKE_MODE ?",
            "[PAGE_WEBASSEMBLY_MEMORY_SWITCH]",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, host)
        for forbidden in (
            "new WebAssembly",
            "WebAssembly.validate",
            "WebAssembly.Module",
            "WebAssembly.Instance",
            "globalThis.WebAssembly",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, host)
        self.assertLess(
            host.index("const expectedSmokeMode = await fetchExpectedSmokeMode"),
            host.index("const result = validateResult(await host.run("),
        )

    def test_native_route_has_one_literal_memory_import_witness(self) -> None:
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        lifecycle = source("chrome/browser/wasm/wasm_browser_lifecycle.cc")
        protocol = source(
            "chrome/browser/wasm/wasm_browser_devtools_protocol_smoke.cc"
        )
        self.assertIn(
            '"wasm-browser-m8-page-webassembly-memory-smoke"', main_parts
        )
        self.assertIn(
            "browser_lifecycle_->StartPageWebAssemblyMemoryDevToolsProtocolSmoke();",
            main_parts,
        )
        self.assertIn(
            "StartPageWebAssemblyMemoryDevToolsProtocolSmoke", lifecycle
        )
        for expected in (
            "WasmBrowserDevToolsProtocolSmokeMode::kMemoryImportReadWrite",
            "kPageWebAssemblyMemoryRuntimeEvaluateCommand",
            "new WebAssembly.Memory",
            "new WebAssembly.Module",
            "new WebAssembly.Instance",
            "memory.buffer",
            "Uint8Array",
            "kPageWebAssemblyMemorySuccessMarker",
            "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:",
            "MEMORY_CONSTRUCTED_IMPORTED_JS_WRITE_WASM_READ_WASM_WRITE_JS_READ_OK",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, protocol)


if __name__ == "__main__":
    unittest.main()
